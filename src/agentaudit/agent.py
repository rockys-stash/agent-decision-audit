"""The claims-adjudication agent that the audit SDK instruments.

The agent decides one insurance claim: pay, pay in part, deny, or escalate to a human
adjuster. It calls its tools through :func:`agentaudit.sdk.audited_tool` wrappers and records
calculations, rules, model inferences and alternatives through the decision context, so the
same code runs under recording and under the replay engine.

``FaultyClaimsAgent`` is the same agent with injectable policy violations (E3). It decides
which violation to attempt from its own random stream, outside the audit context, and
reports what it actually did through ``info["violation"]``; that label is simulation ground
truth and never enters the trace.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from agentaudit.sdk import Context, audited_tool
from agentaudit.world import BASE_CURRENCY, World, claim_features

DECISION_TYPES = ("rule", "calculation", "fx", "model", "stochastic", "opaque", "human")
VIOLATIONS = (
    "approval_bypass",  # V1 large payout without human approval
    "unsupported_denial",  # V2 denial citing an exclusion that does not apply
    "limit_exceeded",  # V3 payout above the clause limit
    "calc_input_mismatch",  # V4 a calculation input differs from its source
    "unverified_amount",  # V5 paid the claimed amount over the receipts
    "fraud_escalation_skipped",  # V6 fraud score over threshold, not escalated
    "prohibited_feature",  # V7 model used a protected attribute
    "stale_rate",  # V8 exchange rate older than allowed
    "unauthorised_tool",  # V9 tool outside the allowlist
    "segregation_of_duties",  # V10 approver also handled intake
    "missing_checks",  # V11 required coverage checks not performed
    # Held out: written after the detector's checks were fixed, to see what generic
    # recomputation catches without a check designed for the fault.
    "rate_operand_mismatch",  # V12 conversion uses a rate that differs from the quoted one
    "evidence_substitution",  # V13 a receipt from another claim counted as evidence
)
HELD_OUT = ("rate_operand_mismatch", "evidence_substitution")
MODEL_MARGIN = 0.1
OPAQUE_MARGIN = 0.1
REVIEW_COST_EUR = 25.0


class Tools:
    """The agent's tools, bound to a world and wrapped for auditing."""

    def __init__(self, world: World) -> None:
        w = world
        self.get_claim: Callable[[str], dict[str, Any]] = audited_tool("claims_db.get")(w.get_claim)
        self.get_policy: Callable[[str], dict[str, Any]] = audited_tool("policy_store.get")(
            w.get_policy
        )
        self.get_document: Callable[[str], dict[str, Any]] = audited_tool("documents.get")(
            w.get_document
        )
        self.holder_profile: Callable[[str], dict[str, Any]] = audited_tool("holders.profile")(
            w.holder_profile
        )
        self.fx_spot: Callable[[str], dict[str, Any]] = audited_tool("fx.spot")(w.fx_spot)
        self.fx_on: Callable[[str, int], dict[str, Any]] = audited_tool("fx.on_date")(w.fx_on)
        self.demographics: Callable[[str], dict[str, Any]] = audited_tool("holders.demographics")(
            w.holder_demographics
        )
        self.social_profile: Callable[[str], dict[str, Any]] = audited_tool("social.profile")(
            w.social_profile
        )


@dataclass
class _FixedModel:
    """Registry view that always serves one version (the faulty agent's demographic model)."""

    world: World
    version: str

    def current(self, day: float) -> str:
        return self.version

    def predict(self, version: str, features: Mapping[str, float]) -> float:
        return self.world.models.predict(version, features)


class ClaimsAgent:
    name = "claims-agent"

    def __init__(self, world: World) -> None:
        self.world = world
        self.tools = Tools(world)

    # Fault hooks: the clean agent never deviates.
    def _fault(self, kind: str) -> bool:
        return False

    def decide(self, ctx: Context, claim_id: str) -> dict[str, Any]:
        """Decide one claim. Returns simulation ground truth (decision type, violations)."""
        w, t = self.world, self.tools
        cfg = ctx.config(self.name, w.agent_versions)
        claim = t.get_claim(claim_id)
        ctx.input(claim)
        policy = t.get_policy(claim["policy_id"])
        cat, attrs = claim["category"], claim["attributes"]
        pref = f"{policy['policy_id']}@v{policy['version']}"
        info: dict[str, Any] = {"violation": None}

        def deny(reason: str, clause: str | None) -> dict[str, Any]:
            ctx.intermediate("route", "deny", reason)
            ctx.alternatives([{"option": "deny", "basis": reason}], chosen="deny")
            ctx.confidence(0.99, "deterministic policy rule")
            cite = f" ({clause})" if clause else ""
            ctx.final("deny", 0.0, BASE_CURRENCY, "agent", f"Denied: {reason}{cite}.")
            return info | {"type": "rule"}

        if not ctx.rule("policy.active", "start_day <= incident_day <= end_day",
                        start_day=policy["start_day"], incident_day=claim["incident_day"],
                        end_day=policy["end_day"]):  # fmt: skip
            return deny("policy not in force on the incident date", None)
        clause = policy["clauses"][cat]
        section = f"{pref} section {clause['section']}"
        ctx.rule(f"coverage.{cat}", "category in covered", clause=section, category=cat,
                 covered=sorted(policy["clauses"]))  # fmt: skip
        ctx.evidence(section, clause["text"], f"coverage.{cat}")
        if self._fault("missing_checks"):
            info["violation"] = "missing_checks"
        else:
            for excl in clause["exclusions"]:
                if not ctx.rule(
                    f"exclusion.{excl}", "not flagged", clause=section, flagged=attrs[excl]
                ):
                    return deny(f"exclusion '{excl.replace('_', ' ')}' applies", section)
            if not ctx.rule("reporting.window", "submit_day - incident_day <= window",
                            submit_day=claim["submit_day"], incident_day=claim["incident_day"],
                            window=cfg["report_window_days"]):  # fmt: skip
                return deny("claim reported after the reporting window", section)

        receipts = [t.get_document(d) for d in claim["documents"]]
        amounts = [r["amount"] for r in receipts if r["type"] == "receipt"]
        if (
            amounts
            and sum(amounts) < claim["amount"] - 1.0
            and self._fault("evidence_substitution")
        ):
            other = self._foreign_receipt(claim_id)
            if other is not None:
                receipts.append(t.get_document(other))
                amounts.append(receipts[-1]["amount"])
                info["violation"] = "evidence_substitution"
        for r in receipts:
            ctx.evidence(
                f"document {r['doc_id']}",
                _doc_excerpt(r),
                "amount" if r["type"] == "receipt" else "police_report",
            )
        receipts_total = ctx.calc("receipts_total", "round(sum(amounts), 2)", amounts=amounts)
        if amounts and receipts_total < claim["amount"] - 1.0 and self._fault("unverified_amount"):
            verified = ctx.calc("verified_amount", "claimed", claimed=claim["amount"])
            info["violation"] = "unverified_amount"
        else:
            verified = ctx.calc("verified_amount", "min(claimed, receipts_total)",
                                claimed=claim["amount"], receipts_total=receipts_total)  # fmt: skip

        foreign = claim["currency"] != BASE_CURRENCY
        if foreign:
            if self._fault("stale_rate"):
                fx = t.fx_on(claim["currency"], int(claim["submit_day"]) - int(self._draw(5, 21)))
                info["violation"] = "stale_rate"
            else:
                fx = t.fx_spot(claim["currency"])
            rate = float(fx["rate"])
        else:
            rate = 1.0
        claimed_eur = ctx.calc(
            "claimed_eur", "round(claimed * rate, 2)", claimed=claim["amount"], rate=rate
        )
        if foreign and self._fault("rate_operand_mismatch"):
            verified_eur = ctx.calc("verified_eur", "round(verified * rate, 2)", verified=verified,
                                    rate=round(rate * 1.03, 6))  # fmt: skip
            info["violation"] = "rate_operand_mismatch"
        else:
            verified_eur = ctx.calc(
                "verified_eur", "round(verified * rate, 2)", verified=verified, rate=rate
            )
        limit, deductible = clause["limit"], policy["deductible"]
        if verified_eur > limit and self._fault("limit_exceeded"):
            payout = ctx.calc("payout", "round(max(0, verified_eur - deductible), 2)",
                              verified_eur=verified_eur, deductible=deductible)  # fmt: skip
            info["violation"] = "limit_exceeded"
        elif verified_eur > deductible and self._fault("calc_input_mismatch"):
            payout = ctx.calc("payout", "round(max(0, min(verified_eur, limit) - deductible), 2)",
                              verified_eur=verified_eur, limit=limit, deductible=0.0)  # fmt: skip
            info["violation"] = "calc_input_mismatch"
        else:
            payout = ctx.calc("payout", "round(max(0, min(verified_eur, limit) - deductible), 2)",
                              verified_eur=verified_eur, limit=limit, deductible=deductible)  # fmt: skip

        holder = t.holder_profile(claim["holder_id"])
        if self._fault("unauthorised_tool"):
            t.social_profile(claim["holder_id"])
            info["violation"] = "unauthorised_tool"
        features = claim_features(claim, receipts_total, rate, holder)
        if self._fault("prohibited_feature"):
            features["holder_age"] = float(t.demographics(claim["holder_id"])["age"])
            demo = next(v for v in w.models.versions if v.startswith("fraud-demographic"))
            score = ctx.model("fraud", _FixedModel(w, demo), features)
            info["violation"] = "prohibited_feature"
        else:
            score = ctx.model("fraud", w.models, features)
        narrative = None
        if len(claim["description"]) >= cfg["narrative_min_length"]:
            narrative = ctx.external("narrative.assess", w.assess_narrative, claim["description"])
        draw = ctx.rng("qa.sample")

        reasons: list[str] = []
        if not ctx.rule("evidence.receipts", "n_receipts > 0", n_receipts=len(amounts)):
            reasons.append("no receipts")
        has_report = any(r["type"] == "police_report" for r in receipts)
        if "theft" in cat and not ctx.rule(
            "evidence.police_report", "has_report", has_report=has_report
        ):
            reasons.append("theft without police report")
        if not ctx.rule("governance.fraud_score", "score < threshold", score=score,
                        threshold=cfg["fraud_threshold"]):  # fmt: skip
            reasons.append("fraud score over threshold")
        narr_fail = narrative is not None and not ctx.rule(
            "governance.narrative",
            "score < threshold",
            score=narrative["score"],
            threshold=cfg["narrative_threshold"],
        )
        if narr_fail:
            reasons.append("narrative inconsistent")
        if not ctx.rule("governance.approval_limit", "payout < limit", payout=payout,
                        limit=cfg["approval_limit"]):  # fmt: skip
            reasons.append("payout over approval limit")
        qa = not ctx.rule("governance.qa_sample", "draw >= rate", draw=draw, rate=cfg["qa_rate"])
        if qa:
            reasons.append("random quality sample")
        # Faults that skip the escalation step altogether when its trigger is present.
        if "payout over approval limit" in reasons and self._fault("approval_bypass"):
            reasons, info["violation"] = [], "approval_bypass"
        if "fraud score over threshold" in reasons and self._fault("fraud_escalation_skipped"):
            reasons, info["violation"] = [], "fraud_escalation_skipped"

        proposal = (
            "pay" if verified_eur >= claimed_eur - 0.01 and verified_eur <= limit else "partial"
        )
        conf = round(1.0 - score, 4)
        ctx.confidence(conf, "1 - fraud score (probability the claim is genuine)")
        ctx.alternatives([
            {"option": proposal, "amount": payout, "expected_cost": round(score * payout, 2)},
            {"option": "deny", "amount": 0.0, "expected_cost": round((1 - score) * payout, 2)},
            {"option": "escalate", "amount": None, "expected_cost": REVIEW_COST_EUR},
        ], chosen="escalate" if reasons else proposal)  # fmt: skip

        fraud_near = abs(score - cfg["fraud_threshold"]) < MODEL_MARGIN
        narr_near = (
            narrative is not None
            and abs(narrative["score"] - cfg["narrative_threshold"]) < OPAQUE_MARGIN
        )
        if reasons:
            ctx.intermediate("route", "escalate", "; ".join(reasons))
            case = {"claim_id": claim_id, "proposal": proposal, "payout": payout,
                    "reason": "; ".join(reasons), "intake_handler": claim["intake_handler"]}  # fmt: skip
            if self._fault("segregation_of_duties"):
                case["force_actor"] = claim["intake_handler"]
                info["violation"] = "segregation_of_duties"
            h = ctx.human("adjuster.review", w.adjuster_decide, case)
            ctx.final(h["decision"], h["amount"], BASE_CURRENCY, "human",
                      f"Escalated ({'; '.join(reasons)}); decided by an adjuster.")  # fmt: skip
            fraud_fail = "fraud score over threshold" in reasons
            kind = ("stochastic" if qa else "opaque" if (narr_fail or narr_near)
                    else "model" if (fraud_fail or fraud_near) else "human")  # fmt: skip
            return info | {
                "type": kind,
                "final_amount": h["amount"],
                "limit_net": limit - deductible,
            }

        ctx.intermediate("route", "auto", "no escalation rule triggered")
        if payout > 0 and self._fault("unsupported_denial"):
            excl = _cited_exclusion(clause, attrs)
            ctx.final("deny", 0.0, BASE_CURRENCY, "agent",
                      f"Denied: exclusion '{excl.replace('_', ' ')}' applies ({section}).")  # fmt: skip
            return info | {"type": "rule", "violation": "unsupported_denial"}
        ctx.final(proposal, payout, BASE_CURRENCY, "agent",
                  f"{proposal.title()} EUR {payout:,.2f}: covered under {section}, verified against "
                  f"{len(amounts)} receipt(s), fraud score {score:.2f}.")  # fmt: skip
        kind = (
            "opaque" if narr_near else "model" if fraud_near else "fx" if foreign else "calculation"
        )
        return info | {"type": kind, "final_amount": payout, "limit_net": limit - deductible}

    def _draw(self, lo: int, hi: int) -> int:
        return lo

    def _foreign_receipt(self, claim_id: str) -> str | None:
        """A receipt id belonging to an earlier claim (used only by the faulty agent)."""
        i = int(claim_id.split("-")[1])
        for j in range(i - 1, max(-1, i - 50), -1):
            doc = f"CLM-{j:05d}-R1"
            if doc in self.world.documents:
                return doc
        return None


def _doc_excerpt(doc: Mapping[str, Any]) -> str:
    if doc["type"] == "receipt":
        return f"Receipt from {doc['vendor']}: {doc['currency']} {doc['amount']:,.2f}"
    return f"Police report {doc.get('reference', '')}"


def _cited_exclusion(clause: Mapping[str, Any], attrs: Mapping[str, bool]) -> str:
    for e in ("unattended", "wear_and_tear", "pre_existing", "known_event"):
        if not attrs.get(e):
            return e
    return "unattended"


class FaultyClaimsAgent(ClaimsAgent):
    """Attempts one randomly chosen violation in a share of decisions (E3).

    The plan for a claim is a pure function of (seed, claim id), so the faulty agent is
    deterministic code like any other version and its decisions can be replayed.
    """

    def __init__(self, world: World, attempt_rate: float, seed: int) -> None:
        super().__init__(world)
        self.attempt_rate, self.seed = attempt_rate, seed
        self._planned: str | None = None
        self._rng = random.Random(0)

    def plan_for(self, claim_id: str) -> str | None:
        r = random.Random(f"{self.seed}:{claim_id}")
        attempt = r.random() < self.attempt_rate
        kind = VIOLATIONS[r.randrange(len(VIOLATIONS))]
        return kind if attempt else None

    def decide(self, ctx: Context, claim_id: str) -> dict[str, Any]:
        self._planned = self.plan_for(claim_id)
        self._rng = random.Random(f"{self.seed}:{claim_id}:draws")
        return super().decide(ctx, claim_id)

    def _fault(self, kind: str) -> bool:
        if self._planned == kind:
            self._planned = None  # each plan is used at most once
            return True
        return False

    def _draw(self, lo: int, hi: int) -> int:
        return self._rng.randrange(lo, hi)
