"""Audit SDK: instrument an agent so every decision leaves a complete, chained trace.

Usage::

    auditor = Auditor(log, clock=lambda: now, seed=7)
    with auditor.decision("claims-agent", input_ref=claim_id) as d:
        claim = claims_db_get(claim_id)          # an @audited_tool: recorded automatically
        payout = d.calc("payout", "max(0, min(amount, limit) - deductible)",
                        amount=a, limit=l, deductible=k)
        if d.rule("policy.active", "start <= incident <= end", start=s, incident=i, end=e):
            ...
        d.final("pay", amount=payout, currency="EUR", decided_by="agent", rationale="...")

Agents call tools through :func:`audited_tool` wrappers or ``d.tool``; the active decision is
found through a context variable, so tools deep inside agent code are captured without
passing a handle around. The same agent code runs unchanged under the replay engine, which
provides a different :class:`Context` implementation (see :mod:`agentaudit.replay`).
"""

from __future__ import annotations

import contextvars
import functools
import random
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any, Protocol, TypeVar

from agentaudit import expr
from agentaudit.canonical import digest, normalise
from agentaudit.log import EventLog
from agentaudit.schema import Event

T = TypeVar("T")

_current: contextvars.ContextVar[Context | None] = contextvars.ContextVar("audit_ctx", default=None)


class NotReplayableError(RuntimeError):
    """Raised during replay when a step cannot be re-derived (e.g. an unrecorded human)."""

    def __init__(self, kind: str, name: str) -> None:
        super().__init__(f"{kind} '{name}' was not recorded and cannot be re-executed")
        self.kind, self.name = kind, name


class ModelRegistry(Protocol):
    def current(self, day: float) -> str: ...
    def predict(self, version: str, features: Mapping[str, float]) -> float: ...


class ConfigRegistry(Protocol):
    def current(self, day: float) -> str: ...
    def params(self, version: str) -> dict[str, Any]: ...


class Context(Protocol):
    """What an instrumented agent can call during a decision."""

    decision_id: str

    def tool(self, name: str, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T: ...
    def external(self, name: str, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T: ...
    def input(self, payload: Mapping[str, Any]) -> None: ...
    def evidence(self, source: str, excerpt: str, supports: str) -> None: ...
    def calc(self, name: str, expression: str, **operands: Any) -> Any: ...
    def rule(
        self, rule_id: str, expression: str, clause: str | None = None, **inputs: Any
    ) -> bool: ...
    def model(self, name: str, registry: ModelRegistry, features: Mapping[str, float]) -> float: ...
    def config(self, name: str, registry: ConfigRegistry) -> dict[str, Any]: ...
    def rng(self, name: str) -> float: ...
    def confidence(self, value: float, basis: str) -> None: ...
    def alternatives(self, options: list[dict[str, Any]], chosen: str) -> None: ...
    def intermediate(self, name: str, value: Any, reason: str) -> None: ...
    def human(self, name: str, fn: Callable[..., dict[str, Any]], *args: Any) -> dict[str, Any]: ...
    def final(
        self, decision: str, amount: float, currency: str, decided_by: str, rationale: str
    ) -> None: ...


def current() -> Context | None:
    return _current.get()


def audited_tool(name: str) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorate a tool function so calls inside a decision are recorded (or replayed)."""

    def wrap(fn: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(fn)
        def inner(*args: Any, **kwargs: Any) -> T:
            ctx = _current.get()
            if ctx is None:
                return fn(*args, **kwargs)
            return ctx.tool(name, fn, *args, **kwargs)

        inner.__audited_tool__ = name  # type: ignore[attr-defined]
        return inner

    return wrap


@contextmanager
def activate(ctx: Context) -> Iterator[Context]:
    token = _current.set(ctx)
    try:
        yield ctx
    finally:
        _current.reset(token)


def call_args(args: tuple[Any, ...], kwargs: Mapping[str, Any]) -> dict[str, Any]:
    return normalise({"args": list(args), "kwargs": dict(kwargs)})


class RecordingContext:
    """Records the full trace of one decision into an event log."""

    def __init__(self, auditor: Auditor, decision_id: str, ts: str, day: float) -> None:
        self.auditor, self.decision_id, self.ts, self.day = auditor, decision_id, ts, day
        self.step = 0
        self.closed = False

    def _emit(self, kind: str, name: str, data: dict[str, Any]) -> None:
        self.auditor.log.append(
            Event(decision_id=self.decision_id, step=self.step, kind=kind, name=name, ts=self.ts,
                  data=normalise(data))
        )  # fmt: skip
        self.step += 1

    def tool(self, name: str, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        # The agent receives exactly what is recorded (canonical form), so a replay that is
        # served from the record sees bit-identical inputs.
        out = normalise(fn(*args, **kwargs))
        self._emit("tool", name, {
            **call_args(args, kwargs), "output": out, "output_hash": digest(out),
            "request_id": self.auditor.request_id(),
        })  # fmt: skip
        return out

    def external(self, name: str, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        out = normalise(fn(*args, **kwargs))
        self._emit("external", name, {
            **call_args(args, kwargs), "output": normalise(out), "output_hash": digest(out),
            "request_id": self.auditor.request_id(),
        })  # fmt: skip
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
        version = registry.current(self.day)
        score = float(normalise(registry.predict(version, features)))
        self._emit("model", name, {"features": dict(features), "score": score, "version": version})
        return score

    def config(self, name: str, registry: ConfigRegistry) -> dict[str, Any]:
        version = registry.current(self.day)
        params = registry.params(version)
        self._emit("config", name, {"version": version, "params": params,
                                    "params_hash": digest(params)})  # fmt: skip
        return params

    def rng(self, name: str) -> float:
        seed = self.auditor.next_seed()
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
        out = normalise(fn(*args))
        self._emit("human", name, dict(out))
        return out

    def final(
        self, decision: str, amount: float, currency: str, decided_by: str, rationale: str
    ) -> None:
        self._emit("final", "final", {"decision": decision, "amount": amount,
                                      "currency": currency, "decided_by": decided_by,
                                      "rationale": rationale})  # fmt: skip
        self.closed = True


class NullContext:
    """Same interface, records nothing. Used to measure instrumentation overhead (E5)."""

    def __init__(self, decision_id: str, day: float, seed: int = 0) -> None:
        self.decision_id, self.day = decision_id, day
        self._rng = random.Random(seed)

    def tool(self, name: str, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        return fn(*args, **kwargs)

    def external(self, name: str, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        return fn(*args, **kwargs)

    def input(self, payload: Mapping[str, Any]) -> None:
        pass

    def evidence(self, source: str, excerpt: str, supports: str) -> None:
        pass

    def calc(self, name: str, expression: str, **operands: Any) -> Any:
        return expr.evaluate(expression, operands)

    def rule(self, rule_id: str, expression: str, clause: str | None = None, **inputs: Any) -> bool:
        return bool(expr.evaluate(expression, inputs))

    def model(self, name: str, registry: ModelRegistry, features: Mapping[str, float]) -> float:
        return float(registry.predict(registry.current(self.day), features))

    def config(self, name: str, registry: ConfigRegistry) -> dict[str, Any]:
        return registry.params(registry.current(self.day))

    def rng(self, name: str) -> float:
        return self._rng.random()

    def confidence(self, value: float, basis: str) -> None:
        pass

    def alternatives(self, options: list[dict[str, Any]], chosen: str) -> None:
        pass

    def intermediate(self, name: str, value: Any, reason: str) -> None:
        pass

    def human(self, name: str, fn: Callable[..., dict[str, Any]], *args: Any) -> dict[str, Any]:
        return fn(*args)

    def final(
        self, decision: str, amount: float, currency: str, decided_by: str, rationale: str
    ) -> None:
        pass


class Auditor:
    """Opens decisions and owns the log, seeds and request ids."""

    def __init__(self, log: EventLog, seed: int = 0) -> None:
        self.log = log
        self._seeds = random.Random(seed)
        self._requests = 0
        self._next_step: dict[str, int] = {}

    def next_seed(self) -> int:
        return self._seeds.getrandbits(63)

    def request_id(self) -> str:
        self._requests += 1
        return f"req-{self._requests:08d}"

    @contextmanager
    def decision(
        self, agent: str, input_ref: str, ts: str, day: float, decision_id: str | None = None
    ) -> Iterator[RecordingContext]:
        did = decision_id or f"{agent}:{input_ref}"
        ctx = RecordingContext(self, did, ts, day)
        ctx._emit("decision", agent, {"input_ref": input_ref, "agent": agent})
        with activate(ctx):
            yield ctx
        if not ctx.closed:
            raise RuntimeError(f"decision {did} ended without a final decision")
        self._next_step[did] = ctx.step

    def outcome(self, decision_id: str, ts: str, outcome: str, detail: Mapping[str, Any]) -> None:
        step = self._next_step.get(decision_id, 0)
        self.log.append(
            Event(decision_id=decision_id, step=step, kind="outcome", name=outcome, ts=ts,
                  data=normalise(dict(detail)))
        )  # fmt: skip
        self._next_step[decision_id] = step + 1
