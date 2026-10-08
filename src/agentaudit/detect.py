"""Automated policy-violation detection over decision traces.

Each check reads only what a trace at the given instrumentation level holds. Where the trace
lacks the data, a check may fall back to looking the data up in the live systems at audit
time (as an output-only checker must); those findings are marked ``live`` because they can be
wrong when the systems changed after the decision. A check that has neither reports itself as
not evaluable for that decision, which is different from finding nothing.

Checks are configured by an audit standard (``configs/audit_standard.yaml``) that is
independent of the agent's own configuration.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from agentaudit.replay import recompute_steps
from agentaudit.schema import Event, Level, project
from agentaudit.world import World, day_of


class Dated(BaseModel):
    from_day: float
    value: float


class Standard(BaseModel):
    id: str
    version: str
    approval_limit_eur: list[Dated]
    fraud_threshold: list[Dated]
    max_rate_age_days: float
    allowed_tools: list[str]
    prohibited_features: list[str]
    required_rules_before_payment: list[str]

    @staticmethod
    def load(path: Path) -> Standard:
        return Standard.model_validate(yaml.safe_load(path.read_text()))

    @staticmethod
    def on(values: list[Dated], day: float) -> float:
        v = values[0].value
        for d in values:
            if day >= d.from_day:
                v = d.value
        return v


@dataclass(frozen=True)
class Finding:
    decision_id: str
    check: str
    targets: tuple[str, ...]  # violation types this check is designed to catch
    step: int | None
    message: str
    live: bool = False  # relied on a live lookup at audit time

    def as_dict(self) -> dict[str, Any]:
        return {"decision_id": self.decision_id, "check": self.check, "targets": list(self.targets),
                "step": self.step, "message": self.message, "live": self.live}  # fmt: skip


@dataclass
class TraceView:
    """Convenient access to one projected trace."""

    events: list[Event]
    level: Level
    decision_id: str = ""
    day: float = 0.0
    by_kind: dict[str, list[Event]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for e in self.events:
            self.by_kind.setdefault(e.kind, []).append(e)
        if self.events:
            self.decision_id = self.events[0].decision_id
            self.day = day_of(self.events[0].ts)

    def first(self, kind: str, name: str | None = None) -> Event | None:
        for e in self.by_kind.get(kind, []):
            if name is None or e.name == name:
                return e
        return None

    def all(self, kind: str, name: str | None = None) -> list[Event]:
        return [e for e in self.by_kind.get(kind, []) if name is None or e.name == name]

    @property
    def final(self) -> Event | None:
        return self.first("final")

    @property
    def input_ref(self) -> str:
        d = self.first("decision")
        return str(d.data["input_ref"]) if d else ""


class Live:
    """Live systems as an auditor could query them on ``audit_day``."""

    def __init__(self, world: World, audit_day: float) -> None:
        self.world, self.audit_day = world, audit_day

    def _at(self, fn: Callable[..., Any], *args: Any) -> Any:
        saved = self.world.clock
        self.world.clock = self.audit_day
        try:
            return fn(*args)
        finally:
            self.world.clock = saved

    def claim(self, claim_id: str) -> dict[str, Any]:
        return dict(self._at(self.world.get_claim, claim_id))

    def policy(self, policy_id: str) -> dict[str, Any]:
        return dict(self._at(self.world.get_policy, policy_id))


Check = Callable[[TraceView, Standard, Live | None], list[Finding] | None]
CHECKS: dict[str, tuple[tuple[str, ...], Check]] = {}


def check(name: str, targets: Iterable[str]) -> Callable[[Check], Check]:
    def reg(fn: Check) -> Check:
        CHECKS[name] = (tuple(targets), fn)
        return fn

    return reg


def _f(t: TraceView, name: str, step: int | None, msg: str, live: bool = False) -> Finding:
    return Finding(t.decision_id, name, CHECKS[name][0], step, msg, live)


def _paid(t: TraceView) -> Event | None:
    f = t.final
    if (
        f is not None
        and f.data.get("decision") in ("pay", "partial")
        and float(f.data.get("amount", 0)) > 0
    ):
        return f
    return None


def _policy(t: TraceView, live: Live | None) -> tuple[dict[str, Any] | None, bool]:
    """The policy document as the agent saw it (L2+), else as it is now (live)."""
    e = t.first("tool", "policy_store.get")
    if e is not None and "output" in e.data:
        return dict(e.data["output"]), False
    if live is None:
        return None, False
    inp = t.first("input")
    claim = inp.data["payload"] if inp is not None else live.claim(t.input_ref)
    return live.policy(claim["policy_id"]), True


@check("approval_limit", ["approval_bypass"])
def _approval(t: TraceView, std: Standard, live: Live | None) -> list[Finding] | None:
    f = t.final
    if f is None or "decided_by" not in f.data:
        return None
    limit = Standard.on(std.approval_limit_eur, t.day)
    if _paid(t) and f.data["decided_by"] == "agent" and float(f.data["amount"]) >= limit:
        return [_f(t, "approval_limit", f.step,
                   f"EUR {f.data['amount']:,.2f} paid without human approval (limit {limit:,.0f})")]  # fmt: skip
    return []


@check("denial_basis", ["unsupported_denial"])
def _denial(t: TraceView, std: Standard, live: Live | None) -> list[Finding] | None:
    f = t.final
    if f is None or f.data.get("decision") != "deny" or f.data.get("decided_by") != "agent":
        return [] if f is not None else None
    if t.level >= Level.L3:
        failed = [r for r in t.all("rule") if not r.data["passed"]
                  and r.name.split(".")[0] in ("policy", "exclusion", "reporting")]  # fmt: skip
        if not failed:
            return [
                _f(
                    t,
                    "denial_basis",
                    f.step,
                    "denied with no failed policy, exclusion or reporting rule",
                )
            ]
        return []
    rationale = f.data.get("rationale")
    if rationale is None:
        return None
    inp = t.first("input")
    if inp is None or "exclusion '" not in rationale:
        return [] if inp is not None else None
    cited = rationale.split("exclusion '")[1].split("'")[0].replace(" ", "_")
    if not inp.data["payload"]["attributes"].get(cited, False):
        return [
            _f(
                t,
                "denial_basis",
                f.step,
                f"cites exclusion '{cited}' but the claim does not have it",
            )
        ]
    return []


@check("clause_limit", ["limit_exceeded"])
def _limit(t: TraceView, std: Standard, live: Live | None) -> list[Finding] | None:
    policy, used_live = _policy(t, live)
    if policy is None:
        return None
    payout = t.first("calc", "payout")
    if payout is not None:
        cat = _category(t, live)
        lim = policy["clauses"][cat]["limit"] - policy["deductible"]
        if float(payout.data["value"]) > lim + 0.01:
            return [
                _f(
                    t,
                    "clause_limit",
                    payout.step,
                    f"payout {payout.data['value']:,.2f} exceeds clause limit net of deductible {lim:,.2f}",
                )
            ]
        return []
    f = _paid(t)
    if f is None:
        return [] if t.final is not None else None
    cat = _category(t, live)
    if cat is None:
        return None
    lim = policy["clauses"][cat]["limit"] - policy["deductible"]
    if float(f.data["amount"]) > lim + 0.01:
        return [
            _f(
                t,
                "clause_limit",
                f.step,
                f"paid {f.data['amount']:,.2f} over clause limit net of deductible {lim:,.2f}",
                used_live,
            )
        ]
    return []


def _category(t: TraceView, live: Live | None) -> Any:
    inp = t.first("input")
    if inp is not None:
        return inp.data["payload"]["category"]
    tool = t.first("tool", "claims_db.get")
    if tool is not None and "output" in tool.data:
        return tool.data["output"]["category"]
    return live.claim(t.input_ref)["category"] if live is not None else None


@check("payout_recompute", ["limit_exceeded", "calc_input_mismatch", "unverified_amount"])
def _recompute_payout(t: TraceView, std: Standard, live: Live | None) -> list[Finding] | None:
    """Recompute the payout from the recorded sources with the reference formula (L2+)."""
    claim_e, policy_e = t.first("tool", "claims_db.get"), t.first("tool", "policy_store.get")
    if claim_e is None or policy_e is None or "output" not in claim_e.data:
        return None
    f = _paid(t)
    if f is None or f.data.get("decided_by") != "agent":
        return []
    claim, policy = claim_e.data["output"], policy_e.data["output"]
    receipts = sum(float(e.data["output"]["amount"]) for e in t.all("tool", "documents.get")
                   if e.data["output"]["type"] == "receipt")  # fmt: skip
    rate = 1.0
    fx = t.first("tool", "fx.spot") or t.first("tool", "fx.on_date")
    if fx is not None:
        rate = float(fx.data["output"]["rate"])
    verified = min(float(claim["amount"]), round(receipts, 2))
    clause = policy["clauses"][claim["category"]]
    expected = round(
        max(0.0, min(round(verified * rate, 2), clause["limit"]) - policy["deductible"]), 2
    )
    if abs(float(f.data["amount"]) - expected) > 0.01:
        return [
            _f(
                t,
                "payout_recompute",
                f.step,
                f"paid {f.data['amount']:,.2f}; recorded sources give {expected:,.2f}",
            )
        ]
    return []


@check("calc_provenance", ["calc_input_mismatch", "limit_exceeded"])
def _provenance(t: TraceView, std: Standard, live: Live | None) -> list[Finding] | None:
    """Calculation inputs must equal the values in the sources they came from (L3)."""
    payout, policy_e = t.first("calc", "payout"), t.first("tool", "policy_store.get")
    if payout is None or policy_e is None or "output" not in policy_e.data:
        return [] if t.level >= Level.L3 else None
    policy = policy_e.data["output"]
    ops = payout.data["operands"]
    out = []
    if "deductible" in ops and float(ops["deductible"]) != float(policy["deductible"]):
        out.append(
            _f(
                t,
                "calc_provenance",
                payout.step,
                f"deductible operand {ops['deductible']} differs from policy {policy['deductible']}",
            )
        )
    if "limit" not in ops:
        out.append(_f(t, "calc_provenance", payout.step, "payout formula has no clause limit"))
    return out


@check("verified_amount", ["unverified_amount"])
def _verified(t: TraceView, std: Standard, live: Live | None) -> list[Finding] | None:
    v, r = t.first("calc", "verified_amount"), t.first("calc", "receipts_total")
    if v is None or r is None:
        return [] if t.level >= Level.L3 else None
    receipts = float(r.data["value"])
    if receipts > 0 and float(v.data["value"]) > receipts + 0.01:
        return [
            _f(
                t,
                "verified_amount",
                v.step,
                f"verified amount {v.data['value']:,.2f} exceeds receipts {receipts:,.2f}",
            )
        ]
    return []


@check("fraud_escalation", ["fraud_escalation_skipped"])
def _fraud(t: TraceView, std: Standard, live: Live | None) -> list[Finding] | None:
    m = t.first("model", "fraud")
    if m is None:
        return [] if t.level >= Level.L3 else None
    thr = Standard.on(std.fraud_threshold, t.day)
    f = t.final
    if float(m.data["score"]) >= thr and f is not None and f.data.get("decided_by") == "agent":
        return [
            _f(
                t,
                "fraud_escalation",
                m.step,
                f"fraud score {m.data['score']:.2f} ≥ {thr} but decided without review",
            )
        ]
    return []


@check("protected_attributes", ["prohibited_feature"])
def _protected(t: TraceView, std: Standard, live: Live | None) -> list[Finding] | None:
    out = []
    m = t.first("model", "fraud")
    if m is not None:
        used = sorted(set(m.data["features"]) & set(std.prohibited_features))
        if used:
            out.append(
                _f(
                    t,
                    "protected_attributes",
                    m.step,
                    f"model used protected attribute(s): {', '.join(used)}",
                )
            )
        return out
    if t.level < Level.L2:
        return None
    demo = t.first("tool", "holders.demographics")
    if demo is not None:
        out.append(
            _f(
                t,
                "protected_attributes",
                demo.step,
                "protected attributes retrieved during an automated decision",
            )
        )
    return out


@check("rate_freshness", ["stale_rate"])
def _rate(t: TraceView, std: Standard, live: Live | None) -> list[Finding] | None:
    if t.level < Level.L2:
        return None
    out = []
    for e in t.all("tool"):
        if e.name.startswith("fx.") and "output" in e.data:
            age = t.day - float(e.data["output"]["as_of_day"])
            if age > std.max_rate_age_days:
                out.append(
                    _f(
                        t,
                        "rate_freshness",
                        e.step,
                        f"exchange rate {age:.1f} days old (max {std.max_rate_age_days:.0f})",
                    )
                )
    return out


@check("tool_allowlist", ["unauthorised_tool"])
def _tools(t: TraceView, std: Standard, live: Live | None) -> list[Finding] | None:
    if t.level < Level.L2:
        return None
    return [_f(t, "tool_allowlist", e.step, f"tool '{e.name}' is not on the allowlist")
            for e in t.all("tool") if e.name not in std.allowed_tools]  # fmt: skip


@check("segregation_of_duties", ["segregation_of_duties"])
def _sod(t: TraceView, std: Standard, live: Live | None) -> list[Finding] | None:
    h = t.first("human")
    if h is None:
        return [] if t.level >= Level.L2 else None
    if "actor" not in h.data:
        return None
    inp = t.first("input") or t.first("tool", "claims_db.get")
    if inp is None:
        return None
    claim = inp.data["payload"] if inp.kind == "input" else inp.data["output"]
    if h.data["actor"] == claim["intake_handler"]:
        return [
            _f(
                t,
                "segregation_of_duties",
                h.step,
                f"{h.data['actor']} handled intake and decided the review",
            )
        ]
    return []


@check("required_checks", ["missing_checks"])
def _required(t: TraceView, std: Standard, live: Live | None) -> list[Finding] | None:
    if t.level < Level.L3:
        return None
    if t.first("calc", "payout") is None:
        return []
    names = [r.name for r in t.all("rule")]
    policy, _ = _policy(t, None)
    cat = _category(t, None)
    required = ["policy.active", f"coverage.{cat}", "reporting.window"]
    if policy is not None and cat is not None:
        required += [f"exclusion.{e}" for e in policy["clauses"][cat]["exclusions"]]
    missing = [r for r in required if not any(fnmatch.fnmatch(n, r) for n in names)]
    if missing:
        return [
            _f(
                t,
                "required_checks",
                None,
                f"required check(s) not performed before payment: {', '.join(missing)}",
            )
        ]
    return []


@check("recomputation", [])
def _recomputation(t: TraceView, std: Standard, live: Live | None) -> list[Finding] | None:
    if t.level < Level.L3:
        return None
    return [_f(t, "recomputation", c.step, f"{c.kind} '{c.name}': {c.detail}")
            for c in recompute_steps(t.events) if c.status != "match"]  # fmt: skip


@dataclass
class DetectionResult:
    findings: list[Finding]
    evaluable: dict[str, bool]


def detect(
    trace: list[Event], level: Level, std: Standard, live: Live | None = None
) -> DetectionResult:
    """Run every check on ``trace`` projected to ``level``."""
    view = TraceView(project([e for e in trace if e.kind != "outcome"], level), level)
    findings: list[Finding] = []
    evaluable: dict[str, bool] = {}
    for name, (_, fn) in CHECKS.items():
        res = fn(view, std, live)
        evaluable[name] = res is not None
        findings.extend(res or [])
    return DetectionResult(findings, evaluable)
