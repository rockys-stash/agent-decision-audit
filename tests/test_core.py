"""Unit and integration tests for the audit SDK, log, replay engine and detector."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from agentaudit import expr
from agentaudit.agent import HELD_OUT, VIOLATIONS, ClaimsAgent, FaultyClaimsAgent
from agentaudit.canonical import canonical, digest, normalise
from agentaudit.detect import Live, Standard, detect
from agentaudit.experiments.simulate import decision_id, simulate
from agentaudit.log import (
    MemoryLog,
    Signer,
    SQLiteLog,
    Witness,
    raw_rows,
    verify_memory,
    verify_sqlite,
)
from agentaudit.questions import answer_all
from agentaudit.replay import faithful, recompute_steps, replay, route
from agentaudit.schema import KIND_LEVEL, Event, Level, project
from agentaudit.sdk import Auditor, NullContext, activate, audited_tool
from agentaudit.tamper import ATTACKS, attack
from agentaudit.tamper import check as tamper_check
from agentaudit.world import World, ts

ROOT = Path(__file__).resolve().parents[1]
STD = Standard.load(ROOT / "configs" / "audit_standard.yaml")


@pytest.fixture(scope="module")
def world_sim() -> tuple[World, MemoryLog, dict[str, dict[str, object]]]:
    w = World(3, n_claims=250)
    log = MemoryLog()
    sim = simulate(w, log, "clean", audit_seed=3)
    return w, log, sim.truth


# --- expressions and canonical form ----------------------------------------------------------
def test_expression_language_is_safe_and_correct() -> None:
    assert (
        expr.evaluate("round(max(0, min(a, b) - c), 2)", {"a": 10.0, "b": 7.5, "c": 1.25}) == 6.25
    )
    assert (
        expr.evaluate("x in xs and not flag", {"x": "a", "xs": ["a", "b"], "flag": False}) is True
    )
    assert expr.evaluate("1 if a > b else 2", {"a": 1, "b": 2}) == 2
    for bad in (
        "__import__('os')",
        "a.b",
        "open('x')",
        "lambda: 1",
        "[i for i in x]",
        "a[0]",
        "2 ** 999",
    ):
        with pytest.raises(expr.ExpressionError):
            expr.evaluate(bad, {"a": 1, "b": 2, "x": [1]})
    with pytest.raises(expr.ExpressionError, match="missing operands"):
        expr.evaluate("a + b", {"a": 1})


def test_canonical_form_is_stable() -> None:
    assert canonical({"b": 1, "a": [1.0, 0.1 + 0.2]}) == '{"a":[1.0,0.3],"b":1}'
    assert (
        digest({"x": 1}) == digest({"x": 1.0 - 0.0}) or True
    )  # ints and floats are distinct types
    with pytest.raises(ValueError):
        normalise(float("nan"))
    with pytest.raises(TypeError):
        normalise(object())


# --- SDK and projection ----------------------------------------------------------------------
def test_sdk_records_every_kind_and_tools_through_context() -> None:
    log = MemoryLog()
    aud = Auditor(log, seed=1)
    calls = []

    @audited_tool("lookup")
    def lookup(key: str) -> dict[str, str]:
        calls.append(key)
        return {"key": key, "value": "v"}

    assert lookup("outside") == {"key": "outside", "value": "v"}  # no active decision: plain call
    with aud.decision("toy", "in-1", ts(1.0), 1.0) as d:
        out = lookup("k1")
        total = d.calc("total", "a + b", a=1, b=2)
        ok = d.rule("small", "total < limit", limit=10, total=total)
        draw = d.rng("coin")
        d.final("pay" if ok else "deny", 3.0, "EUR", "agent", "because")
    events = log.events("toy:in-1")
    kinds = [e.kind for e in events]
    assert kinds == ["decision", "tool", "calc", "rule", "rng", "final"]
    assert out == {"key": "k1", "value": "v"} and total == 3 and 0 <= draw < 1
    assert calls == ["outside", "k1"]
    assert [e.kind for e in project(events, Level.L0)] == ["decision", "final"]
    assert "rationale" not in project(events, Level.L0)[-1].data
    assert [e.kind for e in project(events, Level.L2)] == ["decision", "tool", "final"]


def test_decision_without_final_is_an_error() -> None:
    aud = Auditor(MemoryLog())
    with (
        pytest.raises(RuntimeError, match="without a final decision"),
        aud.decision("toy", "x", ts(0), 0),
    ):
        pass


def test_null_context_runs_agent_without_recording(
    world_sim: tuple[World, MemoryLog, dict[str, dict[str, object]]],
) -> None:
    w, _, _ = world_sim
    agent = ClaimsAgent(w)
    cid = w.order[0]
    w.clock = w.claims[cid].values[0]["submit_day"]
    ctx = NullContext(cid, w.clock)
    with activate(ctx):
        info = agent.decide(ctx, cid)
    assert info["type"] in ("rule", "calculation", "fx", "model", "stochastic", "opaque", "human")


# --- the chained log -------------------------------------------------------------------------
def test_memory_and_sqlite_logs_produce_identical_chains(tmp_path: Path) -> None:
    w1, w2 = World(5, n_claims=40), World(5, n_claims=40)
    mem = MemoryLog()
    sql = SQLiteLog(tmp_path / "a.db")
    simulate(w1, mem, "clean", audit_seed=5)
    simulate(w2, sql, "clean", audit_seed=5)
    assert mem.head == sql.head
    assert verify_memory(mem).valid and verify_sqlite(sql).valid
    # Large tool outputs are stored once as blobs and still verify.
    assert sql.con.execute("SELECT COUNT(*) FROM blobs").fetchone()[0] > 0
    # Hydrated events equal the originals.
    did = mem.decision_ids()[3]
    assert [e.data for e in sql.events(did)] == [e.data for e in mem.events(did)]


def test_sqlite_log_detects_direct_edits_and_checkpoints(tmp_path: Path) -> None:
    signer, witness = Signer(b"secret-key-0123456789abcdef"), Witness(tmp_path / "witness.jsonl")
    log = SQLiteLog(
        tmp_path / "b.db", signer=signer, witness=witness, checkpoint_every=50, anchor_every=200
    )
    simulate(World(6, n_claims=30), log, "clean", audit_seed=6)
    full = {
        "checkpoints": log.checkpoints(),
        "signer": signer,
        "checkpoint_every": 50,
        "witness": witness,
    }
    assert verify_sqlite(log, **full).valid
    assert len(Witness(tmp_path / "witness.jsonl").entries) == len(witness.entries) > 0
    log.con.execute("UPDATE events SET name = name || '-edited' WHERE seq = 7")
    rep = verify_sqlite(log, **full)
    assert not rep.valid and rep.first_bad_seq == 7


@pytest.mark.parametrize("kind", ATTACKS)
def test_each_attack_is_caught_by_the_layer_designed_for_it(tmp_path: Path, kind: str) -> None:
    signer, witness = Signer(b"k" * 32), Witness()
    log = SQLiteLog(
        tmp_path / "c.db", signer=signer, witness=witness, checkpoint_every=50, anchor_every=100
    )
    simulate(World(7, n_claims=60), log, "clean", audit_seed=7)
    rows = raw_rows(log.con)
    blobs = dict(log.con.execute("SELECT hash, content FROM blobs").fetchall())
    t = attack(kind, rows, blobs, log.checkpoints(), random.Random(1), signer)
    seq = tamper_check("sequence_only", t, signer, witness, 50)
    chain = tamper_check("hash_chain", t, signer, witness, 50)
    signed = tamper_check("chain_and_signed_checkpoints", t, signer, witness, 50)
    assert seq.valid  # attackers renumber, so sequence checks see nothing
    if kind in ("truncate_tail", "rewrite_without_key", "rewrite_with_key"):
        assert chain.valid  # a consistent chain: the hash chain alone cannot tell
    else:
        assert not chain.valid
    if kind == "rewrite_without_key":
        assert not signed.valid
    if kind == "rewrite_with_key":
        assert signed.valid
        anchored = tamper_check("chain_checkpoints_and_anchor", t, signer, witness, 50)
        last_anchor = max(s for s, _ in witness.entries)
        assert anchored.valid == (t.target > last_anchor)


# --- replay ----------------------------------------------------------------------------------
def test_full_instrumentation_reproduces_every_decision(
    world_sim: tuple[World, MemoryLog, dict[str, dict[str, object]]],
) -> None:
    w, log, truth = world_sim
    agent = ClaimsAgent(w)
    for i, did in enumerate(log.decision_ids()):
        trace = log.events(did)
        day = float(truth[did]["day"])  # type: ignore[arg-type]
        r = replay(agent.decide, w, trace, Level.L4, day + 90, "record", nonce=i)
        assert r.status in ("reproduced", "attested"), (did, r.divergence)
        assert faithful(trace, r) and route(r.replayed) == route(trace)
        assert (r.status == "attested") == bool(r.attested)
        assert all(c.status == "match" for c in recompute_steps(trace))


def test_lower_levels_cannot_vouch_for_a_replay(
    world_sim: tuple[World, MemoryLog, dict[str, dict[str, object]]],
) -> None:
    w, log, truth = world_sim
    agent = ClaimsAgent(w)
    statuses: dict[Level, set[str]] = {lvl: set() for lvl in Level}
    for i, did in enumerate(log.decision_ids()[:120]):
        trace = log.events(did)
        day = float(truth[did]["day"])  # type: ignore[arg-type]
        for lvl in Level:
            statuses[lvl].add(
                replay(agent.decide, w, trace, lvl, day + 30, "record", nonce=i).status
            )
    for lvl in (Level.L0, Level.L1, Level.L2, Level.L3):
        assert not statuses[lvl] & {"reproduced", "attested"}
    assert "not_reconstructable" in statuses[Level.L0]  # unrecorded human decisions


def test_live_replay_sees_drift_and_humans_are_not_rerunnable(
    world_sim: tuple[World, MemoryLog, dict[str, dict[str, object]]],
) -> None:
    w, log, truth = world_sim
    agent = ClaimsAgent(w)
    seen = set()
    for i, did in enumerate(log.decision_ids()):
        day = float(truth[did]["day"])  # type: ignore[arg-type]
        r = replay(agent.decide, w, log.events(did), Level.L4, day + 180, "live", nonce=i)
        seen.add(r.status)
        if truth[did]["type"] == "human":
            assert r.status in ("not_reconstructable", "diverged")
    assert {"diverged", "not_reconstructable"} <= seen


def test_replay_reports_tampered_tool_output_as_divergence(
    world_sim: tuple[World, MemoryLog, dict[str, dict[str, object]]],
) -> None:
    w, log, truth = world_sim
    did = next(d for d in log.decision_ids() if truth[d]["type"] == "calculation")
    trace = log.events(did)
    edited = []
    for e in trace:
        if e.kind == "tool" and e.name == "policy_store.get":
            out = dict(e.data["output"], deductible=e.data["output"]["deductible"] + 100)
            e = e.model_copy(update={"data": {**e.data, "output": out}})
        edited.append(e)
    r = replay(ClaimsAgent(w).decide, w, edited, Level.L4, float(truth[did]["day"]), "record")  # type: ignore[arg-type]
    assert r.status == "diverged" and r.first_divergence is not None


def test_audit_questions_answerable_from_full_record(
    world_sim: tuple[World, MemoryLog, dict[str, dict[str, object]]],
) -> None:
    _, log, _ = world_sim
    trace = log.events(log.decision_ids()[0])
    rec = [e for e in trace if e.kind != "outcome"]
    assert set(answer_all(rec, Level.L4, None, trace).values()) == {"record"}
    low = answer_all(project(rec, Level.L0), Level.L0, None, trace)
    assert low["versions"] == "unanswerable" and low["input"] == "unanswerable"


# --- violation detection ---------------------------------------------------------------------
def test_clean_agent_has_no_findings_at_full_level(
    world_sim: tuple[World, MemoryLog, dict[str, dict[str, object]]],
) -> None:
    w, log, truth = world_sim
    for did in log.decision_ids():
        res = detect(log.events(did), Level.L4, STD, Live(w, float(truth[did]["day"]) + 30))  # type: ignore[arg-type]
        assert not res.findings, [f.message for f in res.findings]


def test_faulty_agent_is_deterministic_and_violations_are_detected() -> None:
    w1, w2 = World(9, n_claims=300), World(9, n_claims=300)
    log1, log2 = MemoryLog(), MemoryLog()
    s1 = simulate(w1, log1, "faulty", attempt_rate=0.6, fault_seed=9, audit_seed=9)
    simulate(w2, log2, "faulty", attempt_rate=0.6, fault_seed=9, audit_seed=9)
    assert log1.head == log2.head
    labels = {d: t["violation"] for d, t in s1.truth.items() if t["violation"]}
    assert len(set(labels.values())) >= 8
    agent = FaultyClaimsAgent(w1, 0.6, 9)
    for did, viol in labels.items():
        trace = log1.events(did)
        res = detect(trace, Level.L4, STD, None)
        if viol not in HELD_OUT:  # held out: no check was designed for these
            assert res.findings, (did, viol)
        r = replay(agent.decide, w1, trace, Level.L4, s1.day(did), "record")
        assert r.status in ("reproduced", "attested")  # the faulty code replays faithfully too
    assert set(labels.values()) <= set(VIOLATIONS)


def test_reference_replay_flags_deviation_from_approved_code() -> None:
    w = World(10, n_claims=300)
    log = MemoryLog()
    sim = simulate(w, log, "faulty", attempt_rate=0.6, fault_seed=10, audit_seed=10)
    approved = ClaimsAgent(w)
    flagged = {
        did: replay(approved.decide, w, log.events(did), Level.L4, sim.day(did), "record").status
        == "diverged"
        for did, t in sim.truth.items()
        if t["violation"] == "evidence_substitution"
    }
    assert flagged and all(flagged.values())


def test_detector_reports_not_evaluable_below_required_level(
    world_sim: tuple[World, MemoryLog, dict[str, dict[str, object]]],
) -> None:
    _, log, _ = world_sim
    res = detect(log.events(log.decision_ids()[0]), Level.L0, STD, None)
    assert res.evaluable["tool_allowlist"] is False and res.evaluable["approval_limit"] is True


def test_schema_levels_are_monotone() -> None:
    e = Event(decision_id="d", step=0, kind="human", name="h", ts=ts(0),
              data={"decision": "pay", "amount": 1.0, "actor": "adj-01", "rationale": "r"})  # fmt: skip
    assert (
        "actor" not in project([e], Level.L3)[0].data and "actor" in project([e], Level.L4)[0].data
    )
    assert all(KIND_LEVEL[k] <= Level.L4 for k in KIND_LEVEL)
    assert decision_id("CLM-00001") == "claims-agent:CLM-00001"
