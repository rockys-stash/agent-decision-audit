"""Standard audit questions, and what a trace (or a replay) can answer about them.

These operationalise RQ3's proxy: an audit trail supports accountability to the extent that an
auditor can answer these questions correctly about any decision. Each answer function returns
``None`` when the events at the given level do not hold the information.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agentaudit.schema import Event, Level

Answer = Callable[[list[Event], Level], Any]


def _kind(events: list[Event], kind: str) -> list[Event]:
    return [e for e in events if e.kind == kind]


def _input(events: list[Event], level: Level) -> Any:
    e = _kind(events, "input")
    return e[0].data["payload_hash"] if e else None


def _sources(events: list[Event], level: Level) -> Any:
    if level < Level.L2:
        return None
    tools = [
        (e.kind, e.name, e.data.get("output_hash"))
        for e in events
        if e.kind in ("tool", "external")
    ]
    return sorted(tools) if tools else None


def _computation(events: list[Event], level: Level) -> Any:
    if level < Level.L3:
        return None
    return [(e.name, e.data["value"]) for e in _kind(events, "calc")]


def _rules(events: list[Event], level: Level) -> Any:
    if level < Level.L3:
        return None
    return [(e.name, e.data["passed"]) for e in _kind(events, "rule")]


def _alternatives(events: list[Event], level: Level) -> Any:
    if level < Level.L3:
        return None
    e = _kind(events, "alternatives")
    return (e[0].data["options"], e[0].data["chosen"]) if e else []


def _confidence(events: list[Event], level: Level) -> Any:
    if level < Level.L3:
        return None
    e = _kind(events, "confidence")
    return e[0].data["value"] if e else None


def _versions(events: list[Event], level: Level) -> Any:
    if level < Level.L4:
        return None
    cfg = _kind(events, "config")
    model = _kind(events, "model")
    return (
        cfg[0].data["version"] if cfg else None,
        model[0].data.get("version") if model else None,
    )


def _human(events: list[Event], level: Level) -> Any:
    if level < Level.L4:
        return None
    h = _kind(events, "human")
    return (True, h[0].data.get("actor")) if h else (False, None)


QUESTIONS: dict[str, tuple[str, Answer]] = {
    "input": ("What exactly was the agent deciding on?", _input),
    "sources": ("Which sources and services did it consult, and what did they return?", _sources),
    "computation": ("How was the amount computed?", _computation),
    "rules": ("Which policy rules were evaluated, with what result?", _rules),
    "alternatives": ("Which alternatives were considered, and which was chosen?", _alternatives),
    "confidence": ("How confident was the agent?", _confidence),
    "versions": ("Which agent and model versions made the decision?", _versions),
    "human": ("Was a person involved, and who?", _human),
}


def answer_all(
    recorded: list[Event], level: Level, replayed: list[Event] | None, truth: list[Event]
) -> dict[str, str]:
    """Answer every question from the record if possible, else from the replay.

    Returns, per question: ``record`` (answered from the record; always correct, the record is
    what happened), ``replay_correct`` / ``replay_wrong`` (inferred by replay, checked against
    the full original trace), or ``unanswerable``.
    """
    out = {}
    for q, (_, fn) in QUESTIONS.items():
        rec = fn(recorded, level)
        true = fn(truth, Level.L4)
        if rec is not None:
            out[q] = "record" if rec == true else "record_wrong"
        elif replayed is not None:
            out[q] = "replay_correct" if fn(replayed, Level.L4) == true else "replay_wrong"
        else:
            out[q] = "unanswerable"
    return out
