"""Run an agent over a world's claims and record every decision (shared by all experiments)."""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Any

from agentaudit.agent import ClaimsAgent, FaultyClaimsAgent
from agentaudit.log import EventLog
from agentaudit.sdk import Auditor
from agentaudit.world import World, ts

AGENT = "claims-agent"


def decision_id(claim_id: str) -> str:
    return f"{AGENT}:{claim_id}"


@dataclass
class Simulation:
    world: World
    agent: ClaimsAgent
    log: EventLog
    truth: dict[str, dict[str, Any]] = field(default_factory=dict)  # decision id -> ground truth

    def day(self, did: str) -> float:
        return float(self.world.claims[did.split(":", 1)[1]].values[0]["submit_day"])


def make_agent(
    world: World, variant: str, attempt_rate: float = 0.0, fault_seed: int = 0
) -> ClaimsAgent:
    if variant == "clean":
        return ClaimsAgent(world)
    if variant == "faulty":
        return FaultyClaimsAgent(world, attempt_rate, fault_seed)
    raise ValueError(f"unknown agent variant '{variant}'")


def outcome_of(final: dict[str, Any], truth: dict[str, Any]) -> str:
    paid = final["decision"] in ("pay", "partial") and float(final["amount"]) > 0
    if truth["fraud"]:
        return "fraud_found_after_payment" if paid else "fraud_confirmed"
    return "closed_paid" if paid else "closed_denied"


def simulate(
    world: World,
    log: EventLog,
    variant: str = "clean",
    attempt_rate: float = 0.0,
    fault_seed: int = 0,
    audit_seed: int = 0,
    n_claims: int | None = None,
) -> Simulation:
    """Decide claims in arrival order; append each outcome when it becomes known."""
    agent = make_agent(world, variant, attempt_rate, fault_seed)
    auditor = Auditor(log, seed=audit_seed)
    sim = Simulation(world, agent, log)
    pending: list[tuple[float, str, dict[str, Any]]] = []

    def flush(until: float) -> None:
        while pending and pending[0][0] <= until:
            day, did, detail = heapq.heappop(pending)
            auditor.outcome(did, ts(day), str(detail.pop("outcome")), detail)

    for cid in world.order[:n_claims]:
        day = float(world.claims[cid].values[0]["submit_day"])
        flush(day)
        world.clock = day
        did = decision_id(cid)
        with auditor.decision(AGENT, cid, ts(day), day, did) as ctx:
            info = agent.decide(ctx, cid)
        truth = world.truth[cid]
        final = {"decision": "", "amount": 0.0}
        for r in log.records(did):
            if r.event.kind == "final":
                final = r.event.data
        sim.truth[did] = {**info, "fraud": truth["fraud"], "true_loss_eur": truth["true_loss_eur"],
                          "day": day}  # fmt: skip
        heapq.heappush(pending, (truth["outcome_day"], did, {
            "outcome": outcome_of(final, truth), "fraud": truth["fraud"],
        }))  # fmt: skip
    flush(float("inf"))
    return sim
