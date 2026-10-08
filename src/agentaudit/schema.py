"""Decision-trace schema: event kinds, instrumentation levels and level projection.

A trace is the ordered list of events of one decision. The SDK always records the full trace;
an instrumentation level is a projection of it that keeps only what a system logging at that
level would have kept. Projection works at two granularities: whole event kinds have a minimum
level, and some fields inside an event (who a human was, which model version ran) have a
higher minimum level than the event itself.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any

from pydantic import BaseModel, ConfigDict


class Level(IntEnum):
    L0 = 0  # output: decision id, input id, final decision
    L1 = 1  # + full input, rationale, outcome
    L2 = 2  # + tool calls with outputs, evidence, external-service and human responses
    L3 = 3  # + calculations, rules, model inferences, confidence, alternatives, intermediates
    L4 = 4  # + environment: agent/model versions, seeds, identities, request ids

    @property
    def label(self) -> str:
        return LEVEL_LABELS[self]


LEVEL_LABELS = {
    Level.L0: "L0 output",
    Level.L1: "L1 inputs",
    Level.L2: "L2 tools",
    Level.L3: "L3 steps",
    Level.L4: "L4 environment",
}

# Minimum level at which each event kind is kept.
KIND_LEVEL: dict[str, Level] = {
    "decision": Level.L0,  # decision opened: id, agent, input reference
    "final": Level.L0,  # final decision
    "input": Level.L1,  # the input payload as the agent saw it
    "outcome": Level.L1,  # what happened afterwards (appended later)
    "tool": Level.L2,  # tool call with arguments and output
    "external": Level.L2,  # call to an external, non-reproducible service (output only)
    "evidence": Level.L2,  # a source excerpt the decision relies on
    "human": Level.L2,  # a person's decision on an escalated case
    "calc": Level.L3,  # calculation: expression, operands, value
    "rule": Level.L3,  # rule evaluation: expression, inputs, result
    "model": Level.L3,  # model inference: features, score
    "confidence": Level.L3,
    "alternatives": Level.L3,
    "intermediate": Level.L3,  # intermediate decision (e.g. escalate, route)
    "config": Level.L4,  # agent version and parameters in force
    "rng": Level.L4,  # random draw with its seed
}
KINDS = tuple(KIND_LEVEL)

# Fields that need a higher level than their event: (kind, field) -> level.
FIELD_LEVEL: dict[tuple[str, str], Level] = {
    ("final", "rationale"): Level.L1,
    ("decision", "agent_version"): Level.L4,
    ("model", "version"): Level.L4,
    ("human", "actor"): Level.L4,
    ("human", "rationale"): Level.L4,
    ("external", "request_id"): Level.L4,
    ("tool", "request_id"): Level.L4,
}

# Fields that describe the recording, not the decision; ignored when comparing a replay.
VOLATILE_FIELDS = frozenset({"wall_ms", "request_id"})


class Event(BaseModel):
    """One recorded step. ``data`` holds canonical-JSON-compatible values only."""

    model_config = ConfigDict(frozen=True)

    decision_id: str
    step: int
    kind: str
    name: str
    ts: str
    data: dict[str, Any]

    def body(self) -> dict[str, Any]:
        """The hashed content of the event (everything except chain fields)."""
        return {
            "decision_id": self.decision_id,
            "step": self.step,
            "kind": self.kind,
            "name": self.name,
            "ts": self.ts,
            "data": self.data,
        }


def project(events: list[Event], level: Level) -> list[Event]:
    """What a system logging at ``level`` would hold for this decision."""
    out: list[Event] = []
    for e in events:
        if KIND_LEVEL.get(e.kind, Level.L4) > level:
            continue
        drop = [k for k in e.data if FIELD_LEVEL.get((e.kind, k), Level.L0) > level]
        if drop:
            e = e.model_copy(update={"data": {k: v for k, v in e.data.items() if k not in drop}})
        out.append(e)
    return out


def signature(e: Event) -> tuple[str, str, str]:
    """Comparable identity of a step for replay: kind, name and non-volatile content."""
    from agentaudit.canonical import canonical

    content = {k: v for k, v in e.data.items() if k not in VOLATILE_FIELDS}
    return (e.kind, e.name, canonical(content))
