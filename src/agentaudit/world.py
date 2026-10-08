"""A simulated insurance-claims world in which an agent makes auditable decisions.

The world is synthetic on purpose: the audit experiments need ground truth that no public
dataset provides (which inputs determined a decision, which violations were injected, how
the environment changed after each decision). Everything is generated from one seed, so a
world can be rebuilt exactly for replay. Parameters are documented in ``data/DATASET.md``.

Things that change after a decision, and so make later re-execution diverge:

* exchange rates follow a daily random walk (the agent uses the spot rate);
* policy documents are revised (limits, deductibles, exclusions);
* claims are amended (new receipts, changed amounts);
* a holder's prior-claim count grows;
* the fraud model is retrained every 30 days;
* the agent itself is upgraded (new thresholds) on fixed dates;
* the narrative assessor, an external service, returns a slightly different score per call;
* adjusters are people: their decisions cannot be re-requested.
"""

from __future__ import annotations

import bisect
import datetime as dt
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from agentaudit.canonical import digest

BASE_DATE = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
BASE_CURRENCY = "EUR"
FX_START = {"USD": 0.92, "GBP": 1.17, "CHF": 1.04, "JPY": 0.0062, "INR": 0.011}
FX_DAILY_VOL = 0.006
CURRENCY_SHARE = {"EUR": 0.62, "USD": 0.12, "GBP": 0.1, "CHF": 0.06, "JPY": 0.05, "INR": 0.05}

PRODUCTS: dict[str, dict[str, tuple[float, float, str | None]]] = {
    # category: (limit low, limit high, exclusion)
    "travel": {
        "baggage": (1500, 3000, "unattended"),
        "medical": (5000, 15000, "pre_existing"),
        "cancellation": (2000, 5000, "known_event"),
    },
    "home": {
        "theft": (2000, 10000, "unattended"),
        "water": (3000, 12000, "wear_and_tear"),
        "fire": (5000, 20000, None),
    },
    "gadget": {
        "damage": (500, 2000, "wear_and_tear"),
        "device_theft": (500, 2000, "unattended"),
    },
}
CATEGORIES = sorted({c for p in PRODUCTS.values() for c in p})
EXCLUSION_TEXT = {
    "unattended": "loss of items left unattended in a public place",
    "pre_existing": "conditions that existed before the policy started",
    "known_event": "cancellation caused by an event known when the trip was booked",
    "wear_and_tear": "gradual deterioration, wear and tear",
}
LOSS_MEDIAN = {"baggage": 700, "medical": 2500, "cancellation": 1400, "theft": 2200,
               "water": 3500, "fire": 6000, "damage": 450, "device_theft": 800}  # fmt: skip
ADJUSTERS = [f"adj-{i:02d}" for i in range(1, 9)]
HORIZON_DAYS = 360
CLAIM_DAYS = 180
RETRAIN_EVERY = 30
OUTCOME_DELAY = (20, 70)
PROHIBITED_FEATURES = ("holder_age", "holder_nationality")


def ts(day: float) -> str:
    return (BASE_DATE + dt.timedelta(days=day)).isoformat(timespec="seconds")


def day_of(ts_text: str) -> float:
    return (dt.datetime.fromisoformat(ts_text) - BASE_DATE).total_seconds() / 86400


@dataclass
class Versioned:
    """A record with dated versions; ``at(day)`` is what a live lookup returns on that day."""

    days: list[float] = field(default_factory=list)
    values: list[dict[str, Any]] = field(default_factory=list)

    def add(self, day: float, value: dict[str, Any]) -> None:
        i = bisect.bisect_right(self.days, day)
        self.days.insert(i, day)
        self.values.insert(i, value)

    def at(self, day: float) -> dict[str, Any] | None:
        i = bisect.bisect_right(self.days, day) - 1
        return self.values[i] if i >= 0 else None


def clause_text(
    section: int, category: str, limit: float, deductible: float, exclusions: list[str]
) -> str:
    excl = "; ".join(EXCLUSION_TEXT[e] for e in exclusions) or "none"
    return (
        f"Section {section}. {category.replace('_', ' ').title()} losses are covered up to "
        f"EUR {limit:,.0f} per claim, less a deductible of EUR {deductible:,.0f}. "
        f"Exclusions: {excl}."
    )


def claim_features(
    claim: Mapping[str, Any],
    receipts_total: float,
    rate: float,
    holder: Mapping[str, Any],
) -> dict[str, float]:
    """Fraud-model features. Shared by the agent and the model trainer."""
    f = {
        "log_amount_eur": math.log1p(float(claim["amount"]) * rate),
        "days_to_report": float(claim["submit_day"] - claim["incident_day"]),
        "receipt_ratio": min(2.0, receipts_total / max(1.0, float(claim["amount"]))),
        "n_documents": float(len(claim["documents"])),
        "prior_claims": float(holder["prior_claims"]),
        "tenure_days": float(holder["tenure_days"]),
        "description_length": float(len(claim["description"])),
    }
    for c in CATEGORIES:
        f[f"cat_{c}"] = 1.0 if claim["category"] == c else 0.0
    return f


FEATURE_NAMES = list(claim_features(
    {"amount": 1, "submit_day": 0, "incident_day": 0, "documents": [], "description": "",
     "category": CATEGORIES[0]}, 0.0, 1.0, {"prior_claims": 0, "tenure_days": 0},
))  # fmt: skip


class FraudModels:
    """Model registry: a fraud model retrained every 30 days; all versions kept."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        self.versions: dict[str, Any] = {}
        self.feature_names: dict[str, list[str]] = {}
        self.trained_on: dict[str, float] = {}
        self._schedule: list[tuple[float, str]] = []
        self._cache: dict[tuple[str, str], float] = {}

    def fit(
        self, day: float, X: np.ndarray, y: np.ndarray, names: list[str], tag: str = "fraud"
    ) -> str:
        from sklearn.ensemble import HistGradientBoostingClassifier

        model = HistGradientBoostingClassifier(
            max_iter=80, learning_rate=0.08, max_leaf_nodes=15, random_state=self.seed
        )
        model.fit(X, y)
        version = f"{tag}-d{int(day):03d}-{digest([self.seed, day, len(y), names])[:8]}"
        self.versions[version] = model
        self.feature_names[version] = names
        self.trained_on[version] = day
        if tag == "fraud":
            self._schedule.append((day, version))
            self._schedule.sort()
        return version

    def current(self, day: float) -> str:
        i = bisect.bisect_right([d for d, _ in self._schedule], day) - 1
        return self._schedule[max(i, 0)][1]

    def predict(self, version: str, features: Mapping[str, float]) -> float:
        names = self.feature_names[version]
        key = (version, digest([features.get(n, 0.0) for n in names]))
        if key not in self._cache:
            x = np.array([[float(features.get(n, 0.0)) for n in names]])
            self._cache[key] = round(float(self.versions[version].predict_proba(x)[0, 1]), 6)
        return self._cache[key]


AGENT_VERSIONS: list[tuple[float, str, dict[str, Any]]] = [
    (0.0, "claims-agent@1.0", {
        "fraud_threshold": 0.5, "approval_limit": 5000, "narrative_threshold": 0.7,
        "narrative_min_length": 160, "qa_rate": 0.05, "report_window_days": 30,
    }),
    (75.0, "claims-agent@1.1", {
        "fraud_threshold": 0.45, "approval_limit": 4000, "narrative_threshold": 0.7,
        "narrative_min_length": 160, "qa_rate": 0.05, "report_window_days": 30,
    }),
    (150.0, "claims-agent@1.2", {
        "fraud_threshold": 0.45, "approval_limit": 4000, "narrative_threshold": 0.65,
        "narrative_min_length": 140, "qa_rate": 0.04, "report_window_days": 30,
    }),
]  # fmt: skip


class AgentVersions:
    """Configuration registry for the agent: thresholds in force on each day."""

    def current(self, day: float) -> str:
        version = AGENT_VERSIONS[0][1]
        for start, v, _ in AGENT_VERSIONS:
            if day >= start:
                version = v
        return version

    def params(self, version: str) -> dict[str, Any]:
        for _, v, p in AGENT_VERSIONS:
            if v == version:
                return dict(p)
        raise KeyError(version)


DESCRIPTION_OPENERS = [
    "The loss happened while I was travelling.",
    "I noticed the problem when I came home.",
    "This happened on the date given in the form.",
    "I am submitting this claim with the documents attached.",
]
DESCRIPTION_DETAIL = [
    "The receipts show what I paid.",
    "A neighbour can confirm what happened.",
    "I reported it as soon as I could.",
    "The item was about two years old.",
    "I have photos of the damage if needed.",
    "The repair shop gave me an estimate.",
]
DESCRIPTION_INCONSISTENT = [
    "I think it was the week before, or maybe after.",
    "The amount might be higher, I am still adding things up.",
    "I do not have the receipts any more but the price was about that.",
    "Several other items were also lost but I forgot to list them before.",
]


class World:
    """All state of one simulated world. ``clock`` is the current day for live lookups."""

    def __init__(self, seed: int, n_claims: int = 2000, n_policies: int = 900) -> None:
        self.seed = seed
        rng = np.random.default_rng(seed)
        self.clock = 0.0
        self._build_fx(rng)
        self._build_policies(rng, n_policies)
        self._build_claims(rng, n_claims)
        self.models = FraudModels(seed)
        self.agent_versions = AgentVersions()
        self._train_models(np.random.default_rng(seed + 10_000))
        self._narrative_rng = np.random.default_rng(seed + 20_000)
        self._human_rng = np.random.default_rng(seed + 30_000)

    # ----------------------------------------------------------------- construction
    def _build_fx(self, rng: np.random.Generator) -> None:
        self.fx: dict[str, np.ndarray] = {BASE_CURRENCY: np.ones(HORIZON_DAYS + 1)}
        for cur, start in FX_START.items():
            steps = rng.normal(0, FX_DAILY_VOL, HORIZON_DAYS)
            self.fx[cur] = start * np.exp(np.concatenate([[0.0], np.cumsum(steps)]))

    def _build_policies(self, rng: np.random.Generator, n: int) -> None:
        self.policies: dict[str, Versioned] = {}
        self.holders: dict[str, dict[str, Any]] = {}
        products = list(PRODUCTS)
        for i in range(n):
            pid, hid = f"POL-{i:05d}", f"H-{i:05d}"
            product = products[int(rng.integers(len(products)))]
            start = float(rng.integers(-200, 30))
            deductible = float(rng.choice([50, 100, 250]))
            clauses = {}
            for k, (cat, (lo, hi, excl)) in enumerate(PRODUCTS[product].items(), start=1):
                limit = float(round(rng.uniform(lo, hi), -2))
                exclusions = [excl] if excl else []
                clauses[cat] = {"section": k, "limit": limit, "exclusions": exclusions,
                                "text": clause_text(k, cat, limit, deductible, exclusions)}  # fmt: skip
            doc = {"policy_id": pid, "holder_id": hid, "product": product, "start_day": start,
                   "end_day": start + 365 if rng.random() > 0.1 else float(rng.integers(0, 150)), "deductible": deductible, "clauses": clauses,
                   "version": 1, "revised_day": start}  # fmt: skip
            v = Versioned()
            v.add(-1e9, doc)
            if rng.random() < 0.3:  # one revision during the horizon
                rday = float(rng.uniform(0, HORIZON_DAYS))
                rev = _revise(doc, rng, rday)
                v.add(rday, rev)
            self.policies[pid] = v
            self.holders[hid] = {
                "holder_id": hid,
                "since_day": start - float(rng.integers(0, 2000)),
                "age": int(rng.integers(19, 85)),
                "nationality": str(rng.choice(["DE", "FR", "NL", "IT", "ES", "PL", "IN", "US"])),
                "claim_days": [],
            }

    def _make_claim(
        self, rng: np.random.Generator, cid: str, day: float, pid: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        policy = self.policies[pid].at(day)
        assert policy is not None
        cat = list(policy["clauses"])[int(rng.integers(len(policy["clauses"])))]
        fraud = bool(rng.random() < 0.08)
        delay = float(rng.geometric(1 / (14 if fraud else 7)))
        incident = round(day - delay, 4)
        true_loss = float(round(LOSS_MEDIAN[cat] * math.exp(rng.normal(0, 0.75)), 2))
        claimed = round(true_loss * (rng.uniform(1.3, 2.4) if fraud else 1.0), 2)
        cur = str(rng.choice(list(CURRENCY_SHARE), p=list(CURRENCY_SHARE.values())))
        rate = float(self.fx[cur][max(0, int(day))])
        claimed_local = round(claimed / rate, 2)
        attrs = {
            "unattended": bool(rng.random() < 0.08),
            "pre_existing": bool(cat == "medical" and rng.random() < 0.08),
            "known_event": bool(cat == "cancellation" and rng.random() < 0.06),
            "wear_and_tear": bool(rng.random() < 0.05),
            "police_report": bool(rng.random() < 0.85) if "theft" in cat else False,
        }
        docs = []
        missing = rng.random() < (0.3 if fraud else 0.08)
        if not missing:
            # Honest claimants sometimes lose receipts; some fraudsters forge receipts that
            # match the inflated amount. Receipts alone therefore do not reveal fraud.
            if fraud:
                covered = claimed if rng.random() < 0.4 else true_loss
            else:
                covered = true_loss * (float(rng.uniform(0.5, 1.0)) if rng.random() < 0.35 else 1.0)
            parts = rng.dirichlet(np.ones(int(rng.integers(1, 4))))
            for j, share in enumerate(parts):
                did = f"{cid}-R{j + 1}"
                self.documents[did] = {"doc_id": did, "type": "receipt", "currency": cur,
                                       "amount": round(covered / rate * float(share), 2),
                                       "day": incident - float(rng.integers(30, 700)),
                                       "vendor": f"Vendor {int(rng.integers(100, 999))}"}  # fmt: skip
                docs.append(did)
        if attrs["police_report"]:
            did = f"{cid}-P1"
            self.documents[did] = {"doc_id": did, "type": "police_report", "day": incident + 1,
                                   "reference": f"PR-{int(rng.integers(10**5, 10**6))}"}  # fmt: skip
            docs.append(did)
        n_detail = int(rng.integers(0, 4))
        parts_text = [DESCRIPTION_OPENERS[int(rng.integers(len(DESCRIPTION_OPENERS)))]]
        parts_text += [
            DESCRIPTION_DETAIL[int(i)]
            for i in rng.choice(len(DESCRIPTION_DETAIL), n_detail, replace=False)
        ]
        if fraud or rng.random() < 0.05:
            k = int(rng.integers(1, 3))
            parts_text += [
                DESCRIPTION_INCONSISTENT[int(i)]
                for i in rng.choice(len(DESCRIPTION_INCONSISTENT), k, replace=False)
            ]
        claim = {
            "claim_id": cid, "policy_id": pid, "holder_id": policy["holder_id"], "category": cat,
            "incident_day": incident, "submit_day": day, "amount": claimed_local, "currency": cur,
            "description": " ".join(parts_text), "documents": docs, "attributes": attrs,
            "intake_handler": ADJUSTERS[int(rng.integers(len(ADJUSTERS)))], "version": 1,
        }  # fmt: skip
        truth = {"fraud": fraud, "true_loss_eur": true_loss,
                 "inconsistency": 0.25 + (0.4 if fraud else 0.0) + 0.05 * (len(parts_text) - 1)}  # fmt: skip
        return claim, truth

    def _build_claims(self, rng: np.random.Generator, n: int) -> None:
        self.documents: dict[str, dict[str, Any]] = {}
        self.claims: dict[str, Versioned] = {}
        self.truth: dict[str, dict[str, Any]] = {}
        self.order: list[str] = []
        pids = list(self.policies)
        days = np.round(np.sort(rng.uniform(0, CLAIM_DAYS, n)), 4)
        for i, day in enumerate(days):
            cid = f"CLM-{i:05d}"
            # a policy that is mostly in force; some claims hit lapsed policies on purpose
            pid = pids[int(rng.integers(len(pids)))]
            claim, truth = self._make_claim(rng, cid, float(day), pid)
            v = Versioned()
            v.add(-1e9, claim)
            if rng.random() < 0.1:  # amended after submission
                aday = float(day + rng.uniform(5, 120))
                amended = dict(claim, version=2)
                did = f"{cid}-R9"
                self.documents[did] = {"doc_id": did, "type": "receipt", "currency": claim["currency"],
                                       "amount": round(float(claim["amount"]) * float(rng.uniform(0.1, 0.4)), 2),
                                       "day": claim["incident_day"], "vendor": "Vendor 900"}  # fmt: skip
                amended["documents"] = [*claim["documents"], did]
                amended["amount"] = round(float(claim["amount"]) * float(rng.uniform(1.0, 1.3)), 2)
                v.add(aday, amended)
            self.claims[cid] = v
            self.truth[cid] = truth | {"outcome_day": float(day + rng.uniform(*OUTCOME_DELAY))}
            self.holders[claim["holder_id"]]["claim_days"].append(float(day))
            self.order.append(cid)

    def _train_models(self, rng: np.random.Generator) -> None:
        # Historical claims (before day 0) bootstrap the first model; later versions add
        # claims whose outcome (fraud or not) was known by the retraining day.
        hist_X, hist_y = [], []
        pids = list(self.policies)
        for i in range(3000):
            day = float(rng.uniform(-360, 0))
            claim, truth = self._make_claim(
                rng, f"HIST-{i:05d}", day, pids[int(rng.integers(len(pids)))]
            )
            receipts = sum(float(self.documents[d]["amount"]) for d in claim["documents"]
                           if self.documents[d]["type"] == "receipt")  # fmt: skip
            rate = float(self.fx[claim["currency"]][0])
            holder = {
                "prior_claims": int(rng.poisson(0.3)),
                "tenure_days": float(rng.integers(0, 2300)),
            }
            f = claim_features(claim, receipts, rate, holder)
            hist_X.append([f[n] for n in FEATURE_NAMES])
            hist_y.append(int(truth["fraud"]))
        for k in range(HORIZON_DAYS // RETRAIN_EVERY):
            day = float(k * RETRAIN_EVERY)
            X, y = list(hist_X), list(hist_y)
            for cid in self.order:
                t = self.truth[cid]
                if t["outcome_day"] <= day:
                    f = self.reference_features(cid, day)
                    X.append([f[n] for n in FEATURE_NAMES])
                    y.append(int(t["fraud"]))
            self.models.fit(day, np.array(X), np.array(y), list(FEATURE_NAMES))
        # A model that (wrongly) uses a prohibited attribute: used only by the faulty agent.
        Xa = np.column_stack([np.array(hist_X), rng.integers(19, 85, len(hist_y))])
        self.models.fit(
            0.0, Xa, np.array(hist_y), [*FEATURE_NAMES, "holder_age"], tag="fraud-demographic"
        )

    def reference_features(self, cid: str, day: float) -> dict[str, float]:
        claim = self.claims[cid].at(self.truth_day(cid))
        assert claim is not None
        receipts = sum(float(self.documents[d]["amount"]) for d in claim["documents"]
                       if self.documents[d]["type"] == "receipt")  # fmt: skip
        holder = self._holder_view(claim["holder_id"], claim["submit_day"])
        rate = float(self.fx[claim["currency"]][max(0, int(claim["submit_day"]))])
        return claim_features(claim, receipts, rate, holder)

    def truth_day(self, cid: str) -> float:
        return float(self.claims[cid].values[0]["submit_day"])

    def _holder_view(self, hid: str, day: float) -> dict[str, Any]:
        h = self.holders[hid]
        return {"holder_id": hid, "tenure_days": float(max(0.0, day - h["since_day"])),
                "prior_claims": sum(1 for d in h["claim_days"] if d < day)}  # fmt: skip

    # ----------------------------------------------------------------- live tools
    def get_claim(self, claim_id: str) -> dict[str, Any]:
        c = self.claims[claim_id].at(self.clock)
        if c is None:
            raise KeyError(claim_id)
        return dict(c)

    def get_policy(self, policy_id: str) -> dict[str, Any]:
        p = self.policies[policy_id].at(self.clock)
        if p is None:
            raise KeyError(policy_id)
        return dict(p)

    def get_document(self, doc_id: str) -> dict[str, Any]:
        return dict(self.documents[doc_id])

    def holder_profile(self, holder_id: str) -> dict[str, Any]:
        return self._holder_view(holder_id, self.clock)

    def holder_demographics(self, holder_id: str) -> dict[str, Any]:
        h = self.holders[holder_id]
        return {"holder_id": holder_id, "age": h["age"], "nationality": h["nationality"]}

    def fx_spot(self, currency: str) -> dict[str, Any]:
        d = int(min(max(0.0, self.clock), HORIZON_DAYS))
        return {"currency": currency, "rate": round(float(self.fx[currency][d]), 6), "as_of_day": d}

    def fx_on(self, currency: str, day: int) -> dict[str, Any]:
        d = int(min(max(0, day), HORIZON_DAYS))
        return {"currency": currency, "rate": round(float(self.fx[currency][d]), 6), "as_of_day": d}

    def social_profile(self, holder_id: str) -> dict[str, Any]:
        h = self.holders[holder_id]
        return {"holder_id": holder_id, "posts_mentioning_travel": int(h["age"]) % 7}

    def assess_narrative(self, text: str) -> dict[str, Any]:
        """External narrative assessor: non-deterministic, no seed control, output only."""
        base = (
            0.25 + 0.4 * sum(s in text for s in DESCRIPTION_INCONSISTENT) / 2 + 0.0004 * len(text)
        )
        score = float(np.clip(base + self._narrative_rng.normal(0, 0.08), 0, 1))
        label = "inconsistent" if score >= 0.6 else "consistent"
        return {"score": round(score, 4), "label": label,
                "summary": f"Narrative reads as {label} (score {score:.2f})."}  # fmt: skip

    def adjuster_decide(self, case: Mapping[str, Any]) -> dict[str, Any]:
        """A person decides an escalated claim. Cannot be re-requested during an audit."""
        cid = case["claim_id"]
        truth = self.truth[cid]
        exclude = {case.get("intake_handler")}
        if case.get("force_actor"):
            actor = str(case["force_actor"])
        else:
            pool = [a for a in ADJUSTERS if a not in exclude]
            actor = pool[int(self._human_rng.integers(len(pool)))]
        correct = self._human_rng.random() < 0.92
        if (truth["fraud"] and correct) or (
            not truth["fraud"] and not correct and self._human_rng.random() < 0.5
        ):
            decision, amount = "deny", 0.0
            why = "Documents do not support the amount claimed; denied after review."
        else:
            decision, amount = (
                ("pay" if case["proposal"] == "pay" else "partial"),
                float(case["payout"]),
            )
            why = "Reviewed documents and narrative; agent's payout calculation confirmed."
        return {"decision": decision, "amount": round(amount, 2), "actor": actor,
                "rationale": f"{why} Escalation reason: {case['reason']}."}  # fmt: skip


def _revise(doc: dict[str, Any], rng: np.random.Generator, day: float) -> dict[str, Any]:
    rev = {**doc, "clauses": {k: dict(v) for k, v in doc["clauses"].items()},
           "version": 2, "revised_day": day}  # fmt: skip
    kind = rng.integers(3)
    cat = list(rev["clauses"])[int(rng.integers(len(rev["clauses"])))]
    cl = rev["clauses"][cat]
    if kind == 0:
        cl["limit"] = float(round(cl["limit"] * rng.uniform(0.6, 1.3), -2))
    elif kind == 1:
        rev["deductible"] = float(rng.choice([100, 250, 500]))
    elif "unattended" not in cl["exclusions"]:
        cl["exclusions"] = [*cl["exclusions"], "unattended"]
    for c in rev["clauses"].values():
        c["text"] = clause_text(c["section"], next(k for k, v in rev["clauses"].items() if v is c),
                                c["limit"], rev["deductible"], c["exclusions"])  # fmt: skip
    return rev
