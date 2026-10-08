"""HTTP API for the forensic console.

- Reads are open on localhost unless ``AGENTAUDIT_API_TOKEN`` is set; then every ``/api``
  route except ``/api/health`` needs ``Authorization: Bearer <token>``.
- The API never writes to the audit log. Replays run against a rebuilt copy of the simulated
  world, and the tamper lab attacks an in-memory copy of the stored rows.
- Every client is rate limited (token bucket). Replays and tamper-lab runs are expensive and
  have a stricter bucket.
"""

from __future__ import annotations

import hmac
import json
import os
import random
import re
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from agentaudit.agent import ClaimsAgent, FaultyClaimsAgent
from agentaudit.api.demo import open_db, verify_db
from agentaudit.detect import CHECKS, Standard
from agentaudit.log import raw_rows
from agentaudit.questions import QUESTIONS, answer_all
from agentaudit.replay import recompute_steps, replay
from agentaudit.schema import FIELD_LEVEL, KIND_LEVEL, LEVEL_LABELS, Level, project
from agentaudit.tamper import ATTACKS, DEFENSES, attack
from agentaudit.tamper import check as tamper_check
from agentaudit.world import World, day_of

EXPERIMENTS = ("e1_reconstruction", "e2_audit_delay", "e3_violations", "e4_tamper", "e5_overhead")
_ID = re.compile(r"^[A-Za-z0-9_.:\-]{1,80}$")


class RateLimiter:
    def __init__(self, rate: float, burst: int) -> None:
        self.rate, self.burst = rate, burst
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get(key, (float(self.burst), now))
            tokens = min(self.burst, tokens + (now - last) * self.rate)
            if tokens < 1:
                self._buckets[key] = (tokens, now)
                return False
            self._buckets[key] = (tokens - 1, now)
            if len(self._buckets) > 10_000:  # bound memory under many clients
                self._buckets = dict(list(self._buckets.items())[-5_000:])
            return True


EXPENSIVE = ("/replay", "/tamper-lab")


class GuardMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, token: str | None, reads: RateLimiter, heavy: RateLimiter) -> None:
        super().__init__(app)
        self.token, self.reads, self.heavy = token, reads, heavy

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if path.startswith("/api"):
            client = request.client.host if request.client else "unknown"
            limiter = self.heavy if path.endswith(EXPENSIVE) else self.reads
            if not limiter.allow(client):
                return JSONResponse({"detail": "rate limit exceeded"}, status_code=429,
                                    headers={"Retry-After": "1"})  # fmt: skip
            if self.token and path != "/api/health":
                supplied = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
                if not hmac.compare_digest(supplied.encode(), self.token.encode()):
                    return JSONResponse({"detail": "unauthorized"}, status_code=401)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'"
        )
        return response


class TamperIn(BaseModel):
    attack: Literal[
        "edit_event", "edit_blob", "delete_event", "insert_event", "reorder_events",
        "truncate_tail", "rewrite_without_key", "rewrite_with_key",
    ]  # fmt: skip
    seed: int = 0


def _safe(segment: str) -> str:
    if not _ID.match(segment) or segment in {".", ".."}:
        raise HTTPException(400, "invalid identifier")
    return segment


def _event_json(seq: int, prev: str, h: str, e: Any) -> dict[str, Any]:
    fields = {
        k: int(FIELD_LEVEL.get((e.kind, k), KIND_LEVEL.get(e.kind, Level.L4))) for k in e.data
    }
    return {"seq": seq, "prev_hash": prev, "hash": h, "step": e.step, "kind": e.kind,
            "name": e.name, "ts": e.ts, "data": e.data, "level": int(KIND_LEVEL.get(e.kind, Level.L4)),
            "field_levels": fields}  # fmt: skip


def create_app(root: Path, db_path: Path | None = None, static_dir: Path | None = None) -> FastAPI:
    root = root.resolve()
    results = root / "results"
    static = static_dir or root / "web" / "dist"
    log, signer, witness, every = open_db(root, db_path)
    meta: dict[str, Any] = log.get_meta("deployment") or {}
    std = Standard.load(root / "configs" / "audit_standard.yaml")
    replay_lock = threading.Lock()

    @lru_cache(maxsize=1)
    def world() -> World:
        return World(int(meta.get("seed", 0)), int(meta.get("n_claims", 600)))

    def agent(code: str) -> ClaimsAgent:
        w = world()
        if code == "approved" or meta.get("variant") != "faulty":
            return ClaimsAgent(w)
        return FaultyClaimsAgent(w, float(meta["attempt_rate"]), int(meta["fault_seed"]))

    app = FastAPI(title="Decision audit API", version="1.0.0", docs_url="/api/docs",
                  openapi_url="/api/openapi.json")  # fmt: skip
    app.add_middleware(
        GuardMiddleware,
        token=os.environ.get("AGENTAUDIT_API_TOKEN") or None,
        reads=RateLimiter(rate=float(os.environ.get("AGENTAUDIT_RATE_PER_SEC", "50")), burst=200),
        heavy=RateLimiter(rate=1.0, burst=10),
    )

    def q(sql: str, args: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        with log.lock:
            return list(log.con.execute(sql, args).fetchall())

    def truth(did: str) -> dict[str, Any] | None:
        rows = q(
            "SELECT decision_type, violation, fraud FROM simulation_truth WHERE decision_id = ?",
            (did,),
        )
        if not rows:
            return None
        t, v, f = rows[0]
        return {"decision_type": t, "violation": v, "fraud": bool(f)}

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok"}

    @app.get("/api/meta")
    def meta_view() -> dict[str, Any]:
        n_events, n_dec = q("SELECT COUNT(*), COUNT(DISTINCT decision_id) FROM events")[0]
        head = q("SELECT hash FROM events ORDER BY seq DESC LIMIT 1")
        return {
            "deployment": meta, "events": n_events, "decisions": n_dec,
            "head": head[0][0] if head else None, "checkpoints": len(log.checkpoints()),
            "anchors": len(witness.entries), "levels": {int(k): v for k, v in LEVEL_LABELS.items()},
            "kind_levels": {k: int(v) for k, v in KIND_LEVEL.items()},
            "field_levels": [{"kind": k, "field": f, "level": int(v)} for (k, f), v in FIELD_LEVEL.items()],
            "standard": {"id": std.id, "version": std.version},
        }  # fmt: skip

    @app.get("/api/cases")
    def cases(
        decision: str | None = Query(None, pattern="^(pay|partial|deny)$"),
        decided_by: str | None = Query(None, pattern="^(agent|human)$"),
        flagged: bool | None = None,
        decision_type: str | None = Query(
            None, pattern="^(rule|calculation|fx|model|stochastic|opaque|human)$"
        ),
        search: str | None = Query(None, max_length=40, pattern=r"^[A-Za-z0-9\-]*$"),
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        rows = q(
            "SELECT e.decision_id, e.ts, e.data, (SELECT COUNT(*) FROM events x WHERE x.decision_id = e.decision_id),"
            " (SELECT COUNT(*) FROM findings f WHERE f.decision_id = e.decision_id),"
            " t.decision_type, t.violation FROM events e LEFT JOIN simulation_truth t ON t.decision_id = e.decision_id"
            " WHERE e.kind = 'final' ORDER BY e.seq"
        )
        out = []
        for did, ts_, data, steps, nf, dtype, viol in rows:
            d = json.loads(data)
            if decision and d["decision"] != decision:
                continue
            if decided_by and d["decided_by"] != decided_by:
                continue
            if flagged is not None and (nf > 0) != flagged:
                continue
            if decision_type and dtype != decision_type:
                continue
            if search and search.lower() not in did.lower():
                continue
            out.append({"decision_id": did, "claim_id": did.split(":", 1)[1], "ts": ts_,
                        "decision": d["decision"], "amount": d["amount"], "decided_by": d["decided_by"],
                        "steps": steps, "findings": nf,
                        "simulation_truth": {"decision_type": dtype, "violation": viol}})  # fmt: skip
        return {"total": len(out), "items": out[offset : offset + limit]}

    def _records(did: str) -> list[Any]:
        recs = log.records(_safe(did))
        if not recs:
            raise HTTPException(404, f"unknown decision '{did}'")
        return recs

    @app.get("/api/cases/{did}")
    def case(did: str) -> dict[str, Any]:
        recs = _records(did)
        events = [r.event for r in recs]
        findings = [{"check": c, "step": s, "message": m, "targets": json.loads(t)}
                    for c, s, m, t in q("SELECT check_name, step, message, targets FROM findings WHERE decision_id = ? ORDER BY step", (did,))]  # fmt: skip
        return {
            "decision_id": did, "events": [_event_json(r.seq, r.prev_hash, r.hash, r.event) for r in recs],
            "findings": findings,
            "recomputation": [c.__dict__ for c in recompute_steps(events)],
            "simulation_truth": truth(did),
        }  # fmt: skip

    @app.get("/api/cases/{did}/replay")
    def replay_case(
        did: str,
        level: int = Query(4, ge=0, le=4),
        mode: Literal["record", "live"] = "record",
        delay: float = Query(30.0, ge=0, le=180),
        code: Literal["deployed", "approved"] = "deployed",
    ) -> dict[str, Any]:
        recs = _records(did)
        trace = [r.event for r in recs]
        day = day_of(trace[0].ts)
        with replay_lock:
            r = replay(agent(code).decide, world(), trace, Level(level), day + delay, mode,
                       nonce=random.Random(f"{did}:{level}:{mode}:{delay}").getrandbits(63))  # fmt: skip
        recorded = project([e for e in trace if e.kind != "outcome"], Level(level))
        replayed = project(r.replayed, Level(level))
        answers = answer_all(
            recorded, Level(level), r.replayed if r.status != "not_reconstructable" else None, trace
        )
        return {
            **r.summary(),
            "checks": [c.__dict__ for c in r.checks],
            "recorded": [{"step": e.step, "kind": e.kind, "name": e.name, "data": e.data} for e in recorded],
            "replayed": [{"step": e.step, "kind": e.kind, "name": e.name, "data": e.data} for e in replayed],
            "answers": [{"question": k, "text": QUESTIONS[k][0], "answer": v} for k, v in answers.items()],
            "code": code,
        }  # fmt: skip

    @app.get("/api/violations")
    def violations() -> dict[str, Any]:
        rows = q("SELECT f.decision_id, f.check_name, f.step, f.message, f.targets, t.violation"
                 " FROM findings f LEFT JOIN simulation_truth t ON t.decision_id = f.decision_id ORDER BY f.rowid")  # fmt: skip
        by_check: dict[str, int] = {}
        items = []
        for did, chk, step, msg, targets, viol in rows:
            by_check[chk] = by_check.get(chk, 0) + 1
            items.append({"decision_id": did, "check": chk, "step": step, "message": msg,
                          "targets": json.loads(targets), "simulation_truth": viol})  # fmt: skip
        checks = [
            {"check": n, "targets": list(t), "findings": by_check.get(n, 0)}
            for n, (t, _) in CHECKS.items()
        ]
        injected = q(
            "SELECT violation, COUNT(*) FROM simulation_truth WHERE violation IS NOT NULL GROUP BY violation"
        )
        return {"checks": checks, "items": items, "injected": dict(injected)}

    @app.get("/api/integrity")
    def integrity() -> dict[str, Any]:
        rep = verify_db(log, signer, witness, every)
        head = q("SELECT seq, hash FROM events ORDER BY seq DESC LIMIT 1")
        cps = log.checkpoints()
        return {**rep.as_dict(), "head_seq": head[0][0] if head else 0, "head": head[0][1] if head else None,
                "last_checkpoint": cps[-1][0] if cps else None,
                "anchors": [{"seq": s, "head": h} for s, h in witness.entries[-10:]],
                "checkpoint_every": every, "anchor_every": meta.get("anchor_every")}  # fmt: skip

    @app.post("/api/integrity/tamper-lab")
    def tamper_lab(body: TamperIn) -> dict[str, Any]:
        with log.lock:
            rows = raw_rows(log.con)
            blobs = dict(log.con.execute("SELECT hash, content FROM blobs").fetchall())
        t = attack(body.attack, rows, blobs, log.checkpoints(), random.Random(body.seed), signer)
        return {"attack": body.attack, "target_seq": t.target, "events_after": len(t.rows),
                "results": [{"defense": d, **tamper_check(d, t, signer, witness, every).as_dict()} for d in DEFENSES]}  # fmt: skip

    @app.get("/api/standard")
    def standard() -> dict[str, Any]:
        return {
            **std.model_dump(),
            "checks": [{"check": n, "targets": list(t)} for n, (t, _) in CHECKS.items()],
        }

    def summary_of(exp: str) -> dict[str, Any]:
        if exp not in EXPERIMENTS:
            raise HTTPException(404, f"unknown experiment '{exp}'")
        marker = results / exp / "LATEST"
        if not marker.exists():
            raise HTTPException(404, "experiment has no completed run")
        run = _safe(marker.read_text().strip())
        return dict(json.loads((results / exp / run / "summary.json").read_text()))

    @app.get("/api/experiments")
    def experiments() -> list[dict[str, Any]]:
        out = []
        for exp in EXPERIMENTS:
            try:
                p = summary_of(exp)["provenance"]
                out.append({"experiment": exp, "status": "complete", **p})
            except HTTPException:
                out.append({"experiment": exp, "status": "pending"})
        return out

    @app.get("/api/experiments/{exp}")
    def experiment(exp: str) -> dict[str, Any]:
        return summary_of(_safe(exp))

    @app.get("/api/{rest:path}")
    def api_404(rest: str) -> Response:
        return JSONResponse({"detail": "not found"}, status_code=404)

    @app.get("/{rest:path}")
    def spa(rest: str) -> Response:
        if not static.exists():
            return JSONResponse(
                {"detail": "console not built (npm --prefix web run build)"}, status_code=404
            )
        candidate = (static / rest).resolve()
        if rest and candidate.is_file() and candidate.is_relative_to(static.resolve()):
            return FileResponse(candidate)
        return FileResponse(static / "index.html")

    app.state.attacks = ATTACKS
    return app
