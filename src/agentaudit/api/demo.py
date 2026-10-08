"""The audit database the console serves: one simulated deployment, recorded in full.

The demo deployment runs the faulty agent variant (violations injected into a share of
decisions) so that the console has findings to investigate. What was injected is simulation
ground truth: it is stored in a separate, unchained table and labelled as such in the UI.
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any

from agentaudit.detect import Standard, detect
from agentaudit.experiments.simulate import simulate
from agentaudit.log import Signer, SQLiteLog, VerifyReport, Witness, verify_sqlite
from agentaudit.schema import Level
from agentaudit.world import World

CHECKPOINT_EVERY = 100
ANCHOR_EVERY = 500
TRUTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS simulation_truth (
  decision_id TEXT PRIMARY KEY, decision_type TEXT NOT NULL, violation TEXT, fraud INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS findings (
  decision_id TEXT NOT NULL, check_name TEXT NOT NULL, step INTEGER, message TEXT NOT NULL,
  targets TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS findings_decision ON findings(decision_id);
"""


def default_paths(root: Path) -> tuple[Path, Path, Path]:
    # Empty values (as in a copied .env.example) mean "use the default".
    var = Path(os.environ.get("AGENTAUDIT_VAR") or root / "var")
    db = Path(os.environ.get("AGENTAUDIT_DB") or var / "audit.db")
    return (
        db,
        Path(os.environ.get("AGENTAUDIT_WITNESS") or var / "witness.jsonl"),
        var / "signing.key",
    )


def signing_key(key_path: Path, create: bool) -> bytes:
    """The checkpoint key: AGENTAUDIT_SIGNING_KEY (hex), else a local key file for the demo."""
    env = os.environ.get("AGENTAUDIT_SIGNING_KEY")
    if env:
        key = bytes.fromhex(env)
        if len(key) < 32:
            raise RuntimeError(
                "AGENTAUDIT_SIGNING_KEY must be at least 32 bytes (64 hex characters)"
            )
        return key
    if key_path.exists():
        return bytes.fromhex(key_path.read_text().strip())
    if not create:
        raise RuntimeError("no signing key: set AGENTAUDIT_SIGNING_KEY or run `agentaudit demo-db`")
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    key_path.write_text(key.hex())
    key_path.chmod(0o600)
    return key


def build_demo(root: Path, seed: int = 0, n_claims: int = 600, attempt_rate: float = 0.4) -> Path:
    db, witness_path, key_path = default_paths(root)
    for p in (db, witness_path, Path(str(db) + "-wal"), Path(str(db) + "-shm")):
        p.unlink(missing_ok=True)
    signer = Signer(signing_key(key_path, create=True))
    witness = Witness(witness_path)
    log = SQLiteLog(db, signer=signer, witness=witness, checkpoint_every=CHECKPOINT_EVERY,
                    anchor_every=ANCHOR_EVERY)  # fmt: skip
    world = World(seed, n_claims)
    with log.batch():
        sim = simulate(world, log, "faulty", attempt_rate=attempt_rate, fault_seed=seed,
                       audit_seed=seed)  # fmt: skip
    std = Standard.load(root / "configs" / "audit_standard.yaml")
    log.con.executescript(TRUTH_SCHEMA)
    with log.batch():
        for did, t in sim.truth.items():
            log.con.execute("INSERT INTO simulation_truth VALUES (?, ?, ?, ?)",
                            (did, t["type"], t["violation"], int(bool(t["fraud"]))))  # fmt: skip
            for f in detect(log.events(did), Level.L4, std).findings:
                log.con.execute("INSERT INTO findings VALUES (?, ?, ?, ?, ?)",
                                (did, f.check, f.step, f.message, json.dumps(list(f.targets))))  # fmt: skip
    log.set_meta("deployment", {
        "seed": seed, "n_claims": n_claims, "variant": "faulty", "attempt_rate": attempt_rate,
        "fault_seed": seed, "checkpoint_every": CHECKPOINT_EVERY, "anchor_every": ANCHOR_EVERY,
        "standard": std.id, "standard_version": std.version,
    })  # fmt: skip
    log.close()
    return db


def open_db(root: Path, db: Path | None = None) -> tuple[SQLiteLog, Signer, Witness, int]:
    default_db, witness_path, key_path = default_paths(root)
    path = db or default_db
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist; run `agentaudit demo-db` first")
    signer = Signer(signing_key(key_path, create=False))
    log = SQLiteLog(path)
    meta: dict[str, Any] = log.get_meta("deployment") or {}
    return log, signer, Witness(witness_path), int(meta.get("checkpoint_every", CHECKPOINT_EVERY))


def verify_db(log: SQLiteLog, signer: Signer, witness: Witness, every: int) -> VerifyReport:
    return verify_sqlite(log, checkpoints=log.checkpoints(), signer=signer, checkpoint_every=every,
                         witness=witness)  # fmt: skip
