"""Experiment runner: E1-E5, driven by YAML configs, one versioned result directory per run.

Each seed is an independent world (claims, policies, drift, models) and the unit of
resampling; seeds run in parallel worker processes.
"""

from __future__ import annotations

import json
import os
import platform
import random
import subprocess
import tempfile
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from agentaudit.agent import DECISION_TYPES, HELD_OUT, VIOLATIONS, ClaimsAgent
from agentaudit.canonical import canonical
from agentaudit.detect import CHECKS, Live, Standard, detect
from agentaudit.experiments.simulate import simulate
from agentaudit.experiments.stats import mean_ci, pooled_rate
from agentaudit.log import (
    MemoryLog,
    Signer,
    SQLiteLog,
    Witness,
    dehydrate,
    raw_rows,
    verify_sqlite,
)
from agentaudit.questions import QUESTIONS, answer_all
from agentaudit.replay import STATUSES, replay, route
from agentaudit.schema import Level, project
from agentaudit.sdk import NullContext, activate
from agentaudit.tamper import ATTACKS, DEFENSES, attack
from agentaudit.tamper import check as tamper_check
from agentaudit.world import World


class ExperimentConfig(BaseModel):
    experiment: str
    kind: str
    description: str
    base_seed: int = 20261008
    seeds: int = 10
    n_claims: int = 2000
    workers: int = 4
    delays: list[float] = [30.0]
    levels: list[int] = [0, 1, 2, 3, 4]
    answer_delay: float | None = None
    live: bool = True
    attempt_rate: float = 0.4
    sample_rates: list[float] = [0.05, 0.1]
    trials: int = 100
    checkpoint_every: int = 100
    anchor_every: int = 1000
    repeats: int = 3
    standard: str = "configs/audit_standard.yaml"


def load_config(path: Path) -> ExperimentConfig:
    return ExperimentConfig.model_validate(yaml.safe_load(path.read_text()))


def _commit(root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _nonce(*parts: Any) -> int:
    return random.Random(canonical(list(parts))).getrandbits(63)


# --- E1 / E2 reconstruction -------------------------------------------------------------------
def reconstruction_seed(cfg: ExperimentConfig, seed: int) -> dict[str, Any]:
    world = World(seed, cfg.n_claims)
    log = MemoryLog()
    sim = simulate(world, log, "clean", audit_seed=seed)
    agent = sim.agent
    counts: Counter[str] = Counter()
    causes: Counter[str] = Counter()
    unrecorded: Counter[str] = Counter()
    answers: Counter[str] = Counter()
    for did in log.decision_ids():
        trace = log.events(did)
        day, dtype = sim.day(did), sim.truth[did]["type"]
        true_route = route(trace)
        for delay in cfg.delays:
            audit_day = day + delay
            for lvl in cfg.levels:
                level = Level(lvl)
                r = replay(
                    agent.decide,
                    world,
                    trace,
                    level,
                    audit_day,
                    "record",
                    _nonce(seed, did, delay, lvl),
                )
                same = r.status != "not_reconstructable" and route(r.replayed) == true_route
                counts[f"record|{delay}|{lvl}|{dtype}|{r.status}|{int(same)}"] += 1
                if r.status == "unverifiable":
                    for u in r.unrecorded_inputs:
                        unrecorded[f"{delay}|{lvl}|{u.split(' (')[0]}"] += 1
                if cfg.answer_delay is not None and delay == cfg.answer_delay:
                    rec = project([e for e in trace if e.kind != "outcome"], level)
                    replayed = r.replayed if r.status != "not_reconstructable" else None
                    for q, a in answer_all(rec, level, replayed, trace).items():
                        answers[f"{lvl}|{q}|{a}"] += 1
            if cfg.live:
                r = replay(
                    agent.decide,
                    world,
                    trace,
                    Level.L4,
                    audit_day,
                    "live",
                    _nonce(seed, did, delay, "live"),
                )
                same = r.status != "not_reconstructable" and route(r.replayed) == true_route
                counts[f"live|{delay}|4|{dtype}|{r.status}|{int(same)}"] += 1
                if r.status == "diverged" and r.divergence:
                    causes[f"{delay}|{r.divergence.split(':')[0]}"] += 1
                elif r.status == "not_reconstructable":
                    causes[f"{delay}|human (not recorded for live re-execution)"] += 1
    types = Counter(t["type"] for t in sim.truth.values())
    return {"seed": seed, "decisions": len(sim.truth), "types": dict(types), "counts": dict(counts),
            "live_divergence": dict(causes), "unrecorded": dict(unrecorded), "answers": dict(answers)}  # fmt: skip


def summarise_reconstruction(
    cfg: ExperimentConfig, per_seed: list[dict[str, Any]]
) -> dict[str, Any]:
    modes = ["record"] + (["live"] if cfg.live else [])
    rows = []
    for mode in modes:
        for delay in cfg.delays:
            for lvl in cfg.levels if mode == "record" else [4]:
                for dtype in ["all", *DECISION_TYPES]:
                    per: dict[str, list[float]] = defaultdict(list)
                    n_total = 0
                    for s in per_seed:
                        sel = {k: v for k, v in s["counts"].items()
                               if k.startswith(f"{mode}|{delay}|{lvl}|") and (dtype == "all" or k.split("|")[3] == dtype)}  # fmt: skip
                        n = sum(sel.values())
                        n_total += n
                        if n == 0:
                            continue
                        for st in STATUSES:
                            per[st].append(
                                sum(v for k, v in sel.items() if k.split("|")[4] == st) / n
                            )
                        same = sum(v for k, v in sel.items() if k.split("|")[5] == "1")
                        accepted_wrong = sum(v for k, v in sel.items()
                                             if k.split("|")[4] in ("reproduced", "attested", "unverifiable") and k.split("|")[5] == "0")  # fmt: skip
                        full = sum(
                            v
                            for k, v in sel.items()
                            if k.split("|")[4] in ("reproduced", "attested")
                        )
                        per["route_match"].append(same / n)
                        per["silent_misreconstruction"].append(accepted_wrong / n)
                        per["fully_reconstructed"].append(full / n)
                    if n_total == 0:
                        continue
                    rows.append({"mode": mode, "delay": delay, "level": lvl, "type": dtype, "n": n_total,
                                 **{k: mean_ci(v) for k, v in per.items()}})  # fmt: skip
    answers = []
    if cfg.answer_delay is not None:
        for lvl in cfg.levels:
            for q in QUESTIONS:
                tot = Counter[str]()
                per_seed_correct = []
                for s in per_seed:
                    sel = {
                        k.split("|")[2]: v
                        for k, v in s["answers"].items()
                        if k.startswith(f"{lvl}|{q}|")
                    }
                    n = sum(sel.values())
                    tot.update(sel)
                    if n:
                        per_seed_correct.append(
                            (sel.get("record", 0) + sel.get("replay_correct", 0)) / n
                        )
                n = sum(tot.values())
                answers.append({"level": lvl, "question": q, "text": QUESTIONS[q][0],
                                "correct": mean_ci(per_seed_correct),
                                **{k: tot.get(k, 0) / n for k in ("record", "replay_correct", "replay_wrong", "unanswerable", "record_wrong")}})  # fmt: skip
    causes: Counter[str] = Counter()
    unrec: Counter[str] = Counter()
    for s in per_seed:
        causes.update(s["live_divergence"])
        unrec.update(s["unrecorded"])
    types = Counter[str]()
    for s in per_seed:
        types.update(s["types"])
    return {"rows": rows, "answers": answers, "live_divergence": dict(causes),
            "unrecorded": dict(unrec), "decision_types": dict(types),
            "decisions": sum(s["decisions"] for s in per_seed)}  # fmt: skip


# --- E3 violations ----------------------------------------------------------------------------
def violations_seed(cfg: ExperimentConfig, seed: int, root: Path) -> dict[str, Any]:
    std = Standard.load(root / cfg.standard)
    out: dict[str, Any] = {"seed": seed}
    res: dict[str, Counter[str]] = {"faulty": Counter(), "clean": Counter()}
    checks: Counter[str] = Counter()
    for variant in ("faulty", "clean"):
        world = World(seed, cfg.n_claims)
        log = MemoryLog()
        sim = simulate(
            world, log, variant, attempt_rate=cfg.attempt_rate, fault_seed=seed, audit_seed=seed
        )
        reference = ClaimsAgent(world)  # the approved (clean) agent code
        c = res[variant]
        rng = random.Random(seed * 7 + 1)
        sampled = {rate: {d for d in sim.truth if rng.random() < rate} for rate in cfg.sample_rates}
        for did, truth in sim.truth.items():
            viol = truth["violation"] or "none"
            day = sim.day(did)
            trace = log.events(did)
            c[f"decisions|{viol}"] += 1
            for rate, ss in sampled.items():
                if did in ss:
                    c[f"sample|{rate}|{viol}"] += 1
            for lvl in cfg.levels:
                level = Level(lvl)
                d = detect(trace, level, std, Live(world, day + cfg.delays[0]))
                flagged = bool(d.findings)
                attributed = viol != "none" and any(viol in f.targets for f in d.findings)
                live_only = flagged and all(f.live for f in d.findings)
                c[f"rule|{lvl}|{viol}|{int(flagged)}"] += 1
                c[f"attributed|{lvl}|{viol}|{int(attributed)}"] += 1
                c[f"liveonly|{lvl}|{viol}|{int(live_only)}"] += 1
                for f in d.findings:
                    ok = viol != "none" and viol in f.targets
                    checks[f"{variant}|{lvl}|{f.check}|{int(ok)}|{int(viol != 'none')}"] += 1
                for name, ev in d.evaluable.items():
                    if ev:
                        checks[f"evaluable|{variant}|{lvl}|{name}"] += 1
                r = replay(
                    reference.decide,
                    world,
                    trace,
                    level,
                    day + cfg.delays[0],
                    "record",
                    _nonce(seed, did, lvl, variant),
                )
                c[f"replay|{lvl}|{viol}|{int(r.status == 'diverged')}"] += 1
        out[variant] = dict(c)
    out["checks"] = dict(checks)
    return out


def summarise_violations(cfg: ExperimentConfig, per_seed: list[dict[str, Any]]) -> dict[str, Any]:
    def total(variant: str, key: str) -> list[int]:
        return [s[variant].get(key, 0) for s in per_seed]

    by_type = []
    for viol in VIOLATIONS:
        n = total("faulty", f"decisions|{viol}")
        row: dict[str, Any] = {"violation": viol, "held_out": viol in HELD_OUT, "injected": sum(n)}
        for lvl in cfg.levels:
            for det in ("rule", "attributed", "replay"):
                k = total("faulty", f"{det}|{lvl}|{viol}|1")
                row[f"{det}_L{lvl}"] = pooled_rate(k, n)
        for rate in cfg.sample_rates:
            row[f"sample_{rate}"] = pooled_rate(total("faulty", f"sample|{rate}|{viol}"), n)
        by_type.append(row)
    by_level = []
    for lvl in cfg.levels:
        for det in ("rule", "replay"):
            viol_flags = [
                sum(s["faulty"].get(f"{det}|{lvl}|{v}|1", 0) for v in VIOLATIONS) for s in per_seed
            ]
            viol_n = [
                sum(s["faulty"].get(f"decisions|{v}", 0) for v in VIOLATIONS) for s in per_seed
            ]
            fp_faulty = total("faulty", f"{det}|{lvl}|none|1")
            clean_fp = total("clean", f"{det}|{lvl}|none|1")
            clean_n = total("clean", "decisions|none")
            flagged = [a + b for a, b in zip(viol_flags, fp_faulty, strict=True)]
            core = [
                sum(
                    s["faulty"].get(f"{det}|{lvl}|{v}|1", 0)
                    for v in VIOLATIONS
                    if v not in HELD_OUT
                )
                for s in per_seed
            ]
            core_n = [
                sum(s["faulty"].get(f"decisions|{v}", 0) for v in VIOLATIONS if v not in HELD_OUT)
                for s in per_seed
            ]
            live_only = (
                [
                    sum(s["faulty"].get(f"liveonly|{lvl}|{v}|1", 0) for v in ("none", *VIOLATIONS))
                    for s in per_seed
                ]
                if det == "rule"
                else None
            )
            by_level.append({
                "level": lvl, "detector": det,
                "recall_all": pooled_rate(viol_flags, viol_n),
                "recall_designed": pooled_rate(core, core_n),
                "precision": pooled_rate(viol_flags, flagged),
                "clean_fp_per_1000": {k: (v * 1000 if isinstance(v, float) else v) for k, v in pooled_rate(clean_fp, clean_n).items()},
                "flagged_live_only": sum(live_only) if live_only is not None else None,
            })  # fmt: skip
    checks = []
    agg: Counter[str] = Counter()
    for s in per_seed:
        agg.update(s["checks"])
    for lvl in cfg.levels:
        for name, (targets, _) in CHECKS.items():
            fired = sum(
                v
                for k, v in agg.items()
                if k.startswith(("faulty|", "clean|")) and k.split("|")[1:3] == [str(lvl), name]
            )
            on_target = sum(
                v
                for k, v in agg.items()
                if k.startswith(("faulty|", "clean|"))
                and k.split("|")[1:4] == [str(lvl), name, "1"]
            )
            on_clean = sum(
                v
                for k, v in agg.items()
                if k.startswith("clean|") and k.split("|")[1:3] == [str(lvl), name]
            )
            evaluable = agg.get(f"evaluable|faulty|{lvl}|{name}", 0) + agg.get(
                f"evaluable|clean|{lvl}|{name}", 0
            )
            checks.append({"level": lvl, "check": name, "targets": list(targets), "findings": fired,
                           "on_target": on_target, "on_clean_agent": on_clean, "evaluable": evaluable})  # fmt: skip
    return {"by_type": by_type, "by_level": by_level, "checks": checks,
            "decisions_faulty": sum(sum(total("faulty", f"decisions|{v}")) for v in ("none", *VIOLATIONS)),
            "decisions_clean": sum(total("clean", "decisions|none"))}  # fmt: skip


# --- E4 tamper evidence -----------------------------------------------------------------------
def tamper_seed(cfg: ExperimentConfig, seed: int) -> dict[str, Any]:
    world = World(seed, cfg.n_claims)
    signer = Signer(random.Random(seed).randbytes(32), key_id=f"k{seed}")
    witness = Witness()
    with tempfile.TemporaryDirectory() as tmp:
        log = SQLiteLog(Path(tmp) / "audit.db", signer=signer, witness=witness,
                        checkpoint_every=cfg.checkpoint_every, anchor_every=cfg.anchor_every)  # fmt: skip
        simulate(world, log, "clean", audit_seed=seed)
        clean = verify_sqlite(log, checkpoints=log.checkpoints(), signer=signer,
                              checkpoint_every=cfg.checkpoint_every, witness=witness)  # fmt: skip
        rows = raw_rows(log.con)
        blobs = dict(log.con.execute("SELECT hash, content FROM blobs").fetchall())
        cps = log.checkpoints()
        log.close()
    rng = random.Random(seed)
    res: Counter[str] = Counter()
    last_anchor = max((s for s, _ in witness.entries), default=0)
    for kind in ATTACKS:
        for _ in range(cfg.trials):
            t = attack(kind, rows, blobs, cps, rng, signer)
            tail = "after_last_anchor" if t.target > last_anchor else "anchored"
            for d in DEFENSES:
                rep = tamper_check(d, t, signer, witness, cfg.checkpoint_every)
                b = rep.first_bad_seq
                where = (
                    "exact"
                    if b == t.target
                    else "window"
                    if b is not None and 0 <= b - t.target < cfg.checkpoint_every
                    else "elsewhere"
                )
                res[f"{kind}|{d}|{int(not rep.valid)}|{where}|{tail}"] += 1
    return {"seed": seed, "events": len(rows), "anchors": len(witness.entries), "checkpoints": len(cps),
            "clean_valid": clean.valid, "counts": dict(res)}  # fmt: skip


def summarise_tamper(cfg: ExperimentConfig, per_seed: list[dict[str, Any]]) -> dict[str, Any]:
    agg: Counter[str] = Counter()
    for s in per_seed:
        agg.update(s["counts"])
    rows = []
    for kind in ATTACKS:
        for d in DEFENSES:
            sel = {k: v for k, v in agg.items() if k.startswith(f"{kind}|{d}|")}
            n = sum(sel.values())
            det = sum(v for k, v in sel.items() if k.split("|")[2] == "1")
            loc = sum(
                v for k, v in sel.items() if k.split("|")[2] == "1" and k.split("|")[3] == "exact"
            )
            win = sum(
                v
                for k, v in sel.items()
                if k.split("|")[2] == "1" and k.split("|")[3] in ("exact", "window")
            )
            tail_n = sum(v for k, v in sel.items() if k.endswith("after_last_anchor"))
            tail_det = sum(
                v
                for k, v in sel.items()
                if k.endswith("after_last_anchor") and k.split("|")[2] == "1"
            )
            rows.append({"attack": kind, "defense": d, "trials": n, "detected": det / n,
                         "localised": loc / det if det else None,
                         "localised_within_checkpoint": win / det if det else None,
                         "after_last_anchor": tail_n, "detected_after_last_anchor": tail_det})  # fmt: skip
    return {"rows": rows, "events_per_log": [s["events"] for s in per_seed],
            "clean_logs_valid": all(s["clean_valid"] for s in per_seed),
            "anchors_per_log": [s["anchors"] for s in per_seed]}  # fmt: skip


# --- E5 overhead ------------------------------------------------------------------------------
def overhead_seed(cfg: ExperimentConfig, seed: int) -> dict[str, Any]:
    out: dict[str, Any] = {"seed": seed}
    timings: dict[str, list[float]] = defaultdict(list)
    for rep in range(cfg.repeats):
        world = World(seed, cfg.n_claims)
        agent = ClaimsAgent(world)
        t0 = time.perf_counter()
        for cid in world.order:
            day = float(world.claims[cid].values[0]["submit_day"])
            world.clock = day
            ctx = NullContext(cid, day, seed)
            with activate(ctx):
                agent.decide(ctx, cid)
        timings["uninstrumented"].append((time.perf_counter() - t0) * 1000 / cfg.n_claims)

        world = World(seed, cfg.n_claims)
        mem = MemoryLog()
        t0 = time.perf_counter()
        sim = simulate(world, mem, "clean", audit_seed=seed)
        timings["memory_log"].append((time.perf_counter() - t0) * 1000 / cfg.n_claims)

        world = World(seed, cfg.n_claims)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit.db"
            signer = Signer(b"k" * 32)
            log = SQLiteLog(path, signer=signer, witness=Witness(Path(tmp) / "witness.jsonl"),
                            checkpoint_every=cfg.checkpoint_every, anchor_every=cfg.anchor_every)  # fmt: skip
            t0 = time.perf_counter()
            simulate(world, log, "clean", audit_seed=seed)
            timings["sqlite_log"].append((time.perf_counter() - t0) * 1000 / cfg.n_claims)
            n_events = len(raw_rows(log.con))
            t0 = time.perf_counter()
            verify_sqlite(log)
            timings["verify_chain_events_per_s"].append(n_events / (time.perf_counter() - t0))
            t0 = time.perf_counter()
            verify_sqlite(log, checkpoints=log.checkpoints(), signer=signer,
                          checkpoint_every=cfg.checkpoint_every, witness=Witness(Path(tmp) / "witness.jsonl"))  # fmt: skip
            timings["verify_all_events_per_s"].append(n_events / (time.perf_counter() - t0))
            log.con.execute("VACUUM")
            log.close()
            if rep == 0:
                out["sqlite_bytes_per_decision"] = os.path.getsize(path) / cfg.n_claims
                out["events_per_decision"] = n_events / cfg.n_claims
        dids = mem.decision_ids()
        t0 = time.perf_counter()
        for did in dids[:500]:
            replay(
                sim.agent.decide, sim.world, mem.events(did), Level.L4, sim.day(did) + 30, "record"
            )
        timings["replay_record_L4_ms"].append(
            (time.perf_counter() - t0) * 1000 / min(500, len(dids))
        )
        if rep == 0:
            size: dict[str, float] = {}
            dedup: dict[str, float] = {}
            for lvl in Level:
                total = 0
                blobs: dict[str, int] = {}
                inline = 0
                for did in dids:
                    for e in project(mem.events(did), lvl):
                        body = canonical(e.body())
                        total += len(body)
                        stored, b = dehydrate(e.data)
                        inline += len(canonical({**e.body(), "data": stored}))
                        for h, content in b.items():
                            blobs[h] = len(content)
                size[lvl.label] = total / len(dids)
                dedup[lvl.label] = (inline + sum(blobs.values())) / len(dids)
            out["json_bytes_per_decision"] = size
            out["deduplicated_bytes_per_decision"] = dedup
    out["timings"] = {k: sorted(v)[len(v) // 2] for k, v in timings.items()}  # median of repeats
    return out


def summarise_overhead(cfg: ExperimentConfig, per_seed: list[dict[str, Any]]) -> dict[str, Any]:
    keys = per_seed[0]["timings"].keys()
    timings = {k: mean_ci([s["timings"][k] for s in per_seed]) for k in keys}
    levels = list(per_seed[0]["json_bytes_per_decision"])
    size = {lvl: mean_ci([s["json_bytes_per_decision"][lvl] for s in per_seed]) for lvl in levels}
    dedup = {
        lvl: mean_ci([s["deduplicated_bytes_per_decision"][lvl] for s in per_seed])
        for lvl in levels
    }
    return {"timings": timings, "json_bytes_per_decision": size, "deduplicated_bytes_per_decision": dedup,
            "sqlite_bytes_per_decision": mean_ci([s["sqlite_bytes_per_decision"] for s in per_seed]),
            "events_per_decision": mean_ci([s["events_per_decision"] for s in per_seed]),
            "cpu": platform.processor() or platform.machine(), "cpu_count": os.cpu_count()}  # fmt: skip


# --- driver -----------------------------------------------------------------------------------
def _run_seed(args: tuple[str, ExperimentConfig, int, str]) -> dict[str, Any]:
    kind, cfg, seed, root = args
    if kind == "reconstruction":
        return reconstruction_seed(cfg, seed)
    if kind == "violations":
        return violations_seed(cfg, seed, Path(root))
    if kind == "tamper":
        return tamper_seed(cfg, seed)
    if kind == "overhead":
        return overhead_seed(cfg, seed)
    raise ValueError(kind)


SUMMARISERS: dict[str, Callable[[ExperimentConfig, list[dict[str, Any]]], dict[str, Any]]] = {
    "reconstruction": summarise_reconstruction,
    "violations": summarise_violations,
    "tamper": summarise_tamper,
    "overhead": summarise_overhead,
}


def run_experiment(cfg_path: Path, root: Path, quiet: bool = False) -> Path:
    cfg = load_config(cfg_path)
    say: Callable[[str], None] = (lambda s: None) if quiet else (lambda s: print(s, flush=True))
    commit = _commit(root)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = root / "results" / cfg.experiment / f"{stamp}-{commit[:7]}"
    out_dir.mkdir(parents=True, exist_ok=False)
    (out_dir / "config.yaml").write_text(yaml.safe_dump(cfg.model_dump(), sort_keys=False))
    say(f"{cfg.experiment}: {cfg.description}")
    t0 = time.time()
    seeds = [cfg.base_seed + i for i in range(cfg.seeds)]
    jobs = [(cfg.kind, cfg, s, str(root)) for s in seeds]
    workers = 1 if cfg.kind == "overhead" else min(cfg.workers, len(seeds))
    per_seed: list[dict[str, Any]] = []
    if workers == 1:
        for j in jobs:
            per_seed.append(_run_seed(j))
            say(f"  seed {j[2]} done ({time.time() - t0:.0f}s)")
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for res in pool.map(_run_seed, jobs):
                per_seed.append(res)
                say(f"  seed {res['seed']} done ({time.time() - t0:.0f}s)")
    with (out_dir / "per_seed.jsonl").open("w") as f:
        for r in per_seed:
            f.write(json.dumps(r, allow_nan=False) + "\n")
    summary = SUMMARISERS[cfg.kind](cfg, per_seed)
    summary["provenance"] = {
        "experiment": cfg.experiment, "description": cfg.description, "kind": cfg.kind,
        "run_id": out_dir.name, "created_at": stamp, "commit": commit, "base_seed": cfg.base_seed,
        "seeds": cfg.seeds, "n_claims": cfg.n_claims, "python": platform.python_version(),
        "workers": workers, "runtime_seconds": round(time.time() - t0, 1),
    }  # fmt: skip
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1, allow_nan=False))
    (root / "results" / cfg.experiment / "LATEST").write_text(out_dir.name + "\n")
    say(f"wrote {out_dir.relative_to(root)} in {time.time() - t0:.0f}s")
    return out_dir
