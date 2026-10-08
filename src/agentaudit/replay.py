"""Replay engine: re-derive a recorded decision and compare it step by step.

The engine re-runs the agent's own code under a :class:`ReplayContext`. Every non-deterministic
input the agent asks for (tool output, external-service response, human decision, model
version, configuration, random draw) is served from the trace when the trace holds it
(*record mode*), or fetched from the live environment at audit time when it does not, or when
*live mode* is requested. The replayed steps are then compared with the recorded steps at the
trace's instrumentation level.

Outcome for the auditor, who sees only the trace:

``reproduced``
    the replay matched every recorded step and used only recorded inputs; every calculation,
    rule and model score was recomputed.
``attested``
    as above, but some steps (an adjuster's decision, an external service's answer) could only
    be taken from the record, not re-derived.
``unverifiable``
    the replay matched what was recorded, but needed inputs the trace does not hold (live
    lookups, an unrecorded random draw, the model or agent version current at audit time), so
    the auditor cannot know that the replay followed the original path.
``diverged``
    the replay disagreed with the record at some step (reported as the first divergence).
``not_reconstructable``
    the replay could not run (a human decision that was not recorded cannot be re-requested).

The experiments also compare the replay with the complete original trace (simulation ground
truth) to find *silent misreconstructions*: replays the auditor would accept that did not
follow the original path.
"""

from __future__ import annotations

import random
from collections import defaultdict, deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, TypeVar

from agentaudit import expr
from agentaudit.canonical import digest, normalise
from agentaudit.schema import FIELD_LEVEL, KIND_LEVEL, Event, Level, project, signature
from agentaudit.sdk import (
    ConfigRegistry,
    ModelRegistry,
    NotReplayableError,
    activate,
    call_args,
)
from agentaudit.world import World, ts

T = TypeVar("T")
Mode = Literal["record", "live"]
STATUSES = ("reproduced", "attested", "unverifiable", "diverged", "not_reconstructable")


@dataclass
class StepCheck:
    step: int
    kind: str
    name: str
    status: str  # match | mismatch | missing | extra
    detail: str = ""


@dataclass
class ReplayResult:
    decision_id: str
    level: int
    mode: str
    audit_day: float
    status: str
    final_match: bool
    first_divergence: int | None
    divergence: str | None
    unrecorded_inputs: list[str]
    attested: list[str]
    replayed: list[Event] = field(default_factory=list)
    checks: list[StepCheck] = field(default_factory=list)
    error: str | None = None

    def summary(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "level": self.level,
            "mode": self.mode,
            "audit_day": self.audit_day,
            "status": self.status,
            "final_match": self.final_match,
            "first_divergence": self.first_divergence,
            "divergence": self.divergence,
            "unrecorded_inputs": self.unrecorded_inputs,
            "attested": self.attested,
            "error": self.error,
        }


class ReplayContext:
    """Implements the agent's :class:`agentaudit.sdk.Context` against a recorded trace."""

    def __init__(
        self,
        recorded: list[Event],
        world: World,
        audit_day: float,
        mode: Mode,
        nonce: int,
    ) -> None:
        first = recorded[0] if recorded else None
        self.decision_id = first.decision_id if first else "?"
        self.ts = first.ts if first else ts(audit_day)
        self.world, self.audit_day, self.mode = world, audit_day, mode
        self.queues: dict[tuple[str, str], deque[Event]] = defaultdict(deque)
        if mode == "record":
            for e in recorded:
                self.queues[(e.kind, e.name)].append(e)
        self.step = 0
        self.events: list[Event] = []
        self.unrecorded: list[str] = []
        self.attested: list[str] = []
        self._rng = random.Random(nonce)

    # -- helpers
    def _emit(self, kind: str, name: str, data: dict[str, Any]) -> None:
        self.events.append(Event(decision_id=self.decision_id, step=self.step, kind=kind,
                                 name=name, ts=self.ts, data=normalise(data)))  # fmt: skip
        self.step += 1

    def _recorded(self, kind: str, name: str, args: dict[str, Any] | None = None) -> Event | None:
        q = self.queues.get((kind, name))
        if not q:
            return None
        e = q[0]
        if args is not None and (e.data.get("args"), e.data.get("kwargs")) != (
            args["args"],
            args["kwargs"],
        ):
            return None  # the replay asked something different: the record cannot answer it
        return q.popleft()

    def _live(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        saved = self.world.clock
        self.world.clock = self.audit_day
        try:
            return fn(*args, **kwargs)
        finally:
            self.world.clock = saved

    # -- Context interface
    def tool(self, name: str, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        a = call_args(args, kwargs)
        rec = self._recorded("tool", name, a)
        if rec is not None and "output" in rec.data:
            out: Any = rec.data["output"]
        else:
            out = normalise(self._live(fn, *args, **kwargs))
            self.unrecorded.append(f"tool {name}")
        self._emit("tool", name, {**a, "output": out, "output_hash": digest(out)})
        return out

    def external(self, name: str, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        a = call_args(args, kwargs)
        rec = self._recorded("external", name, a)
        if rec is not None and "output" in rec.data:
            out: Any = rec.data["output"]
            self.attested.append(f"external {name}")
        else:
            out = normalise(self._live(fn, *args, **kwargs))
            self.unrecorded.append(f"external {name}")
        self._emit("external", name, {**a, "output": out, "output_hash": digest(out)})
        return out

    def input(self, payload: Mapping[str, Any]) -> None:
        self._emit("input", "input", {"payload": dict(payload), "payload_hash": digest(payload)})

    def evidence(self, source: str, excerpt: str, supports: str) -> None:
        self._emit("evidence", supports, {"source": source, "excerpt": excerpt})

    def calc(self, name: str, expression: str, **operands: Any) -> Any:
        value = normalise(expr.evaluate(expression, operands))
        self._emit("calc", name, {"expr": expression, "operands": operands, "value": value})
        return value

    def rule(self, rule_id: str, expression: str, clause: str | None = None, **inputs: Any) -> bool:
        passed = bool(expr.evaluate(expression, inputs))
        self._emit("rule", rule_id, {"expr": expression, "inputs": inputs, "passed": passed,
                                     "clause": clause})  # fmt: skip
        return passed

    def model(self, name: str, registry: ModelRegistry, features: Mapping[str, float]) -> float:
        rec = self._recorded("model", name)
        if rec is not None and "version" in rec.data:
            version = str(rec.data["version"])
        else:
            version = registry.current(self.audit_day)
            self.unrecorded.append(f"model version ({name})")
        score = float(normalise(registry.predict(version, features)))
        self._emit("model", name, {"features": dict(features), "score": score, "version": version})
        return score

    def config(self, name: str, registry: ConfigRegistry) -> dict[str, Any]:
        rec = self._recorded("config", name)
        if rec is not None:
            version = str(rec.data["version"])
        else:
            version = registry.current(self.audit_day)
            self.unrecorded.append(f"agent version ({name})")
        params = registry.params(version)
        self._emit("config", name, {"version": version, "params": params,
                                    "params_hash": digest(params)})  # fmt: skip
        return params

    def rng(self, name: str) -> float:
        rec = self._recorded("rng", name)
        if rec is not None:
            seed = int(rec.data["seed"])
        else:
            seed = self._rng.getrandbits(63)
            self.unrecorded.append(f"random draw ({name})")
        value = random.Random(seed).random()
        self._emit("rng", name, {"seed": seed, "value": value})
        return value

    def confidence(self, value: float, basis: str) -> None:
        self._emit("confidence", "confidence", {"value": value, "basis": basis})

    def alternatives(self, options: list[dict[str, Any]], chosen: str) -> None:
        self._emit("alternatives", "alternatives", {"options": options, "chosen": chosen})

    def intermediate(self, name: str, value: Any, reason: str) -> None:
        self._emit("intermediate", name, {"value": value, "reason": reason})

    def human(self, name: str, fn: Callable[..., dict[str, Any]], *args: Any) -> dict[str, Any]:
        rec = self._recorded("human", name)
        if rec is None:
            raise NotReplayableError("human", name)
        self.attested.append(f"human {name}")
        out = dict(rec.data)
        self._emit("human", name, out)
        return out

    def final(
        self, decision: str, amount: float, currency: str, decided_by: str, rationale: str
    ) -> None:
        self._emit("final", "final", {"decision": decision, "amount": amount,
                                      "currency": currency, "decided_by": decided_by,
                                      "rationale": rationale})  # fmt: skip


def _comparable(events: list[Event]) -> list[Event]:
    return [e for e in events if e.kind != "outcome"]


def compare(recorded: list[Event], replayed: list[Event]) -> list[StepCheck]:
    """Step-by-step comparison of two traces at the same level."""
    checks = []
    for i in range(max(len(recorded), len(replayed))):
        a = recorded[i] if i < len(recorded) else None
        b = replayed[i] if i < len(replayed) else None
        if a is None:
            assert b is not None
            checks.append(
                StepCheck(i, b.kind, b.name, "extra", "replay took a step the record lacks")
            )
        elif b is None:
            checks.append(StepCheck(i, a.kind, a.name, "missing", "replay ended before this step"))
        elif signature(a) == signature(b):
            checks.append(StepCheck(i, a.kind, a.name, "match"))
        else:
            checks.append(StepCheck(i, a.kind, a.name, "mismatch", _diff(a, b)))
    return checks


def _diff(a: Event, b: Event) -> str:
    if (a.kind, a.name) != (b.kind, b.name):
        return f"replay reached {b.kind} '{b.name}' instead"
    keys = sorted(k for k in set(a.data) | set(b.data) if a.data.get(k) != b.data.get(k))
    keys = [k for k in keys if k not in ("wall_ms", "request_id")]
    return "differs in " + ", ".join(keys[:4])


def _final(events: list[Event]) -> tuple[Any, ...] | None:
    for e in events:
        if e.kind == "final":
            return (e.data.get("decision"), e.data.get("amount"), e.data.get("decided_by"))
    return None


def replay(
    agent_decide: Callable[[Any, str], Any],
    world: World,
    trace: list[Event],
    level: Level,
    audit_day: float,
    mode: Mode = "record",
    nonce: int = 0,
) -> ReplayResult:
    """Replay one decision from its full trace as seen at ``level``.

    ``agent_decide(ctx, input_ref)`` is the agent's decision function (the same code that
    produced the trace). ``trace`` is the complete recorded trace; it is projected to
    ``level`` here, so callers can replay one recording at several levels.
    """
    recorded = project(_comparable(trace), level)
    head = recorded[0]
    ctx = ReplayContext(recorded, world, audit_day, mode, nonce)
    ctx._emit("decision", head.name, {"input_ref": head.data["input_ref"], "agent": head.name})
    try:
        with activate(ctx):
            agent_decide(ctx, str(head.data["input_ref"]))
    except NotReplayableError as e:
        if mode == "record" and level >= KIND_LEVEL[e.kind]:
            # This level records every human decision, so the record shows none was made:
            # the replayed path requires a review that the original decision did not have.
            return ReplayResult(head.decision_id, int(level), mode, audit_day, "diverged", False,
                                ctx.step, f"{e.kind} '{e.name}': replay requires a {e.kind} decision "
                                f"that the record does not contain", sorted(set(ctx.unrecorded)),
                                ctx.attested, ctx.events, [], str(e))  # fmt: skip
        return ReplayResult(head.decision_id, int(level), mode, audit_day, "not_reconstructable",
                            False, None, f"{e.kind} {e.name}", sorted(set(ctx.unrecorded)),
                            ctx.attested, ctx.events, [], str(e))  # fmt: skip
    replayed = project(ctx.events, level)
    checks = compare(recorded, replayed)
    first = next((c for c in checks if c.status != "match"), None)
    final_match = _final(recorded) == _final(replayed)
    if first is not None or not final_match:
        status = "diverged"
    elif ctx.unrecorded:
        status = "unverifiable"
    elif ctx.attested:
        status = "attested"
    else:
        status = "reproduced"
    return ReplayResult(
        head.decision_id, int(level), mode, audit_day, status, final_match,
        first.step if first else None,
        f"{first.kind} '{first.name}': {first.detail}" if first else None,
        sorted(set(ctx.unrecorded)), ctx.attested, ctx.events, checks,
    )  # fmt: skip


def faithful(original: list[Event], result: ReplayResult) -> bool:
    """Ground truth: did the replay follow the original path exactly (all fields, all steps)?"""
    if result.status == "not_reconstructable":
        return False
    a = [signature(_path_only(e)) for e in _comparable(original)]
    b = [signature(_path_only(e)) for e in result.replayed]
    return a == b


def _path_only(e: Event) -> Event:
    """Drop identity metadata (versions, actors, rationales): compare what was done."""
    drop = {k for (kind, k) in FIELD_LEVEL if kind == e.kind}
    if not drop & set(e.data):
        return e
    return e.model_copy(update={"data": {k: v for k, v in e.data.items() if k not in drop}})


def recompute_steps(events: list[Event]) -> list[StepCheck]:
    """Recompute every recorded calculation and rule from its own operands (no agent code)."""
    out = []
    for e in events:
        if e.kind == "calc":
            try:
                v = normalise(expr.evaluate(e.data["expr"], e.data["operands"]))
                ok = v == e.data["value"]
                out.append(StepCheck(e.step, e.kind, e.name, "match" if ok else "mismatch",
                                     "" if ok else f"recorded {e.data['value']}, recomputed {v}"))  # fmt: skip
            except (expr.ExpressionError, KeyError, TypeError) as err:
                out.append(
                    StepCheck(e.step, e.kind, e.name, "mismatch", f"cannot recompute: {err}")
                )
        elif e.kind == "rule":
            try:
                p = bool(expr.evaluate(e.data["expr"], e.data["inputs"]))
                ok = p == e.data["passed"]
                out.append(StepCheck(e.step, e.kind, e.name, "match" if ok else "mismatch",
                                     "" if ok else f"recorded {e.data['passed']}, recomputed {p}"))  # fmt: skip
            except (expr.ExpressionError, KeyError, TypeError) as err:
                out.append(
                    StepCheck(e.step, e.kind, e.name, "mismatch", f"cannot recompute: {err}")
                )
    return out


def route(events: list[Event]) -> list[tuple[Any, ...]]:
    """The decision path: which steps ran and how each branch point came out.

    Two traces with the same route took the same branches and reached the same final decision
    and amount, even if intermediate numbers (a drifted exchange rate, a new random draw that
    did not change any branch) differ.
    """
    out: list[tuple[Any, ...]] = []
    for e in events:
        if e.kind == "outcome":
            continue
        if e.kind == "rule":
            out.append((e.kind, e.name, e.data["passed"]))
        elif e.kind == "intermediate":
            out.append((e.kind, e.name, e.data["value"]))
        elif e.kind == "final":
            out.append((e.kind, e.data["decision"], e.data["amount"], e.data["decided_by"]))
        elif e.kind == "human":
            out.append((e.kind, e.name, e.data.get("decision"), e.data.get("amount")))
        else:
            out.append((e.kind, e.name))
    return out
