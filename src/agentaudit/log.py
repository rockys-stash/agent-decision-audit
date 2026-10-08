"""Tamper-evident, hash-chained event logs.

Every event is chained to its predecessor: ``hash = sha256(prev_hash + canonical(body))``.
Large tool outputs are stored once as content-addressed blobs and referenced from the event
(``{"$blob": <sha256>}``); the chain covers the reference and verification re-hashes each blob,
so blob content is protected too.

Three integrity layers can be checked independently (E4 compares them):

* the chain itself: detects edits, deletions, insertions and reordering, but not an attacker
  who rewrites the whole chain from the point of the change;
* signed checkpoints: an HMAC over (seq, head hash) every ``checkpoint_every`` events, with a
  key the log writer holds but the storage does not; detects rewrites by anyone without the key;
* an external witness: head hashes periodically appended to a separate append-only store;
  detects rewrites even by a key holder, up to the last anchored event.
"""

from __future__ import annotations

import hmac
import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from agentaudit.canonical import canonical, normalise, sha256
from agentaudit.schema import Event

GENESIS = "0" * 64
BLOB_MIN_BYTES = 256


def chain_hash(prev_hash: str, body: dict[str, Any]) -> str:
    return sha256(prev_hash + canonical(body))


def dehydrate(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Move large ``output`` values into blobs. Returns stored data and new blobs."""
    blobs: dict[str, str] = {}
    out = dict(data)
    if "output" in out:
        text = canonical(out["output"])
        if len(text) >= BLOB_MIN_BYTES:
            h = sha256(text)
            blobs[h] = text
            out["output"] = {"$blob": h}
    return out, blobs


def hydrate(data: dict[str, Any], blobs: dict[str, str] | sqlite3.Connection) -> dict[str, Any]:
    ref = data.get("output")
    if isinstance(ref, dict) and set(ref) == {"$blob"}:
        h = ref["$blob"]
        if isinstance(blobs, dict):
            text = blobs[h]
        else:
            row = blobs.execute("SELECT content FROM blobs WHERE hash = ?", (h,)).fetchone()
            if row is None:
                raise KeyError(f"missing blob {h}")
            text = row[0]
        return {**data, "output": json.loads(text)}
    return data


@dataclass(frozen=True)
class Signer:
    """HMAC-SHA256 signer for checkpoints. The key never enters the log."""

    key: bytes
    key_id: str = "k1"

    def sign(self, seq: int, head: str) -> str:
        return hmac.new(self.key, f"{seq}:{head}".encode(), "sha256").hexdigest()

    def check(self, seq: int, head: str, mac: str) -> bool:
        return hmac.compare_digest(self.sign(seq, head), mac)


@dataclass
class Witness:
    """An external append-only store of head hashes (a file, or a list in memory)."""

    path: Path | None = None
    entries: list[tuple[int, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.path is not None and self.path.exists():
            for line in self.path.read_text().splitlines():
                rec = json.loads(line)
                self.entries.append((int(rec["seq"]), str(rec["head"])))

    def anchor(self, seq: int, head: str) -> None:
        self.entries.append((seq, head))
        if self.path is not None:
            with self.path.open("a") as f:
                f.write(json.dumps({"seq": seq, "head": head}) + "\n")


@dataclass(frozen=True)
class Record:
    seq: int
    event: Event
    prev_hash: str
    hash: str


@dataclass
class VerifyReport:
    valid: bool
    events: int
    first_bad_seq: int | None = None
    problems: list[str] = field(default_factory=list)
    checkpoints_checked: int = 0
    anchors_checked: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "events": self.events,
            "first_bad_seq": self.first_bad_seq,
            "problems": self.problems[:20],
            "checkpoints_checked": self.checkpoints_checked,
            "anchors_checked": self.anchors_checked,
        }


class EventLog(Protocol):
    def append(self, event: Event) -> Record: ...
    def records(self, decision_id: str | None = None) -> list[Record]: ...


class MemoryLog:
    """In-memory chained log; used by experiments. Same hashes as :class:`SQLiteLog`."""

    def __init__(
        self,
        signer: Signer | None = None,
        witness: Witness | None = None,
        checkpoint_every: int = 100,
        anchor_every: int = 1000,
    ) -> None:
        self._records: list[Record] = []
        self._by_decision: dict[str, list[Record]] = {}
        self.blobs: dict[str, str] = {}
        self.checkpoints: list[tuple[int, str, str]] = []
        self.signer, self.witness = signer, witness
        self.checkpoint_every, self.anchor_every = checkpoint_every, anchor_every

    @property
    def head(self) -> str:
        return self._records[-1].hash if self._records else GENESIS

    def append(self, event: Event) -> Record:
        stored, blobs = dehydrate(event.data)
        self.blobs.update(blobs)
        stored_event = event.model_copy(update={"data": normalise(stored)})
        seq = len(self._records) + 1
        h = chain_hash(self.head, stored_event.body())
        rec = Record(seq, event.model_copy(update={"data": normalise(event.data)}), self.head, h)
        self._records.append(rec)
        self._by_decision.setdefault(event.decision_id, []).append(rec)
        if self.signer and seq % self.checkpoint_every == 0:
            self.checkpoints.append((seq, h, self.signer.sign(seq, h)))
        if self.witness and seq % self.anchor_every == 0:
            self.witness.anchor(seq, h)
        return rec

    def records(self, decision_id: str | None = None) -> list[Record]:
        if decision_id is None:
            return list(self._records)
        return list(self._by_decision.get(decision_id, []))

    def decision_ids(self) -> list[str]:
        return list(self._by_decision)

    def events(self, decision_id: str) -> list[Event]:
        return [r.event for r in self._by_decision.get(decision_id, [])]


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  seq INTEGER PRIMARY KEY,
  decision_id TEXT NOT NULL,
  step INTEGER NOT NULL,
  kind TEXT NOT NULL,
  name TEXT NOT NULL,
  ts TEXT NOT NULL,
  data TEXT NOT NULL,
  prev_hash TEXT NOT NULL,
  hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_decision ON events(decision_id, step);
CREATE TABLE IF NOT EXISTS blobs (hash TEXT PRIMARY KEY, content TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS checkpoints (
  seq INTEGER PRIMARY KEY, head_hash TEXT NOT NULL, mac TEXT NOT NULL, key_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class SQLiteLog:
    """Durable chained log in SQLite (WAL). Thread-safe: one connection behind a lock."""

    def __init__(
        self,
        path: Path,
        signer: Signer | None = None,
        witness: Witness | None = None,
        checkpoint_every: int = 100,
        anchor_every: int = 1000,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.con = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA synchronous=NORMAL")
        self.con.executescript(SCHEMA)
        self.lock = threading.RLock()
        self.signer, self.witness = signer, witness
        self.checkpoint_every, self.anchor_every = checkpoint_every, anchor_every
        self._batch: int = 0
        row = self.con.execute("SELECT seq, hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        self._seq, self._head = (int(row[0]), str(row[1])) if row else (0, GENESIS)

    @property
    def head(self) -> str:
        return self._head

    @contextmanager
    def batch(self) -> Iterator[None]:
        """Group many appends into one transaction (much faster for bulk writes)."""
        with self.lock:
            self.con.execute("BEGIN IMMEDIATE")
            self._batch += 1
            try:
                yield
            except BaseException:
                self.con.execute("ROLLBACK")
                self._batch -= 1
                row = self.con.execute(
                    "SELECT seq, hash FROM events ORDER BY seq DESC LIMIT 1"
                ).fetchone()
                self._seq, self._head = (int(row[0]), str(row[1])) if row else (0, GENESIS)
                raise
            self.con.execute("COMMIT")
            self._batch -= 1

    def append(self, event: Event) -> Record:
        stored, blobs = dehydrate(event.data)
        stored = normalise(stored)
        with self.lock:
            own_tx = self._batch == 0
            if own_tx:
                self.con.execute("BEGIN IMMEDIATE")
            try:
                stored_event = event.model_copy(update={"data": stored})
                seq = self._seq + 1
                h = chain_hash(self._head, stored_event.body())
                for bh, content in blobs.items():
                    self.con.execute(
                        "INSERT OR IGNORE INTO blobs(hash, content) VALUES (?, ?)", (bh, content)
                    )
                self.con.execute(
                    "INSERT INTO events(seq, decision_id, step, kind, name, ts, data, prev_hash, hash)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (seq, event.decision_id, event.step, event.kind, event.name, event.ts,
                     canonical(stored), self._head, h),
                )  # fmt: skip
                if self.signer and seq % self.checkpoint_every == 0:
                    self.con.execute(
                        "INSERT INTO checkpoints(seq, head_hash, mac, key_id) VALUES (?, ?, ?, ?)",
                        (seq, h, self.signer.sign(seq, h), self.signer.key_id),
                    )
                if own_tx:
                    self.con.execute("COMMIT")
            except BaseException:
                if own_tx:
                    self.con.execute("ROLLBACK")
                raise
            prev, self._seq, self._head = self._head, seq, h
        if self.witness and seq % self.anchor_every == 0:
            self.witness.anchor(seq, h)
        return Record(seq, event.model_copy(update={"data": normalise(event.data)}), prev, h)

    def _row_to_record(self, row: tuple[Any, ...]) -> Record:
        seq, did, step, kind, name, ts, data, prev, h = row
        ev = Event(
            decision_id=did, step=step, kind=kind, name=name, ts=ts,
            data=hydrate(json.loads(data), self.con),
        )  # fmt: skip
        return Record(int(seq), ev, prev, h)

    def records(self, decision_id: str | None = None) -> list[Record]:
        cols = "seq, decision_id, step, kind, name, ts, data, prev_hash, hash"
        with self.lock:
            if decision_id is None:
                rows = self.con.execute(f"SELECT {cols} FROM events ORDER BY seq").fetchall()
            else:
                rows = self.con.execute(
                    f"SELECT {cols} FROM events WHERE decision_id = ? ORDER BY seq", (decision_id,)
                ).fetchall()
            return [self._row_to_record(r) for r in rows]

    def events(self, decision_id: str) -> list[Event]:
        return [r.event for r in self.records(decision_id)]

    def checkpoints(self) -> list[tuple[int, str, str]]:
        with self.lock:
            rows = self.con.execute("SELECT seq, head_hash, mac FROM checkpoints ORDER BY seq")
            return [(int(a), str(b), str(c)) for a, b, c in rows.fetchall()]

    def set_meta(self, key: str, value: Any) -> None:
        with self.lock:
            self.con.execute(
                "INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)),
            )

    def get_meta(self, key: str) -> Any:
        with self.lock:
            row = self.con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def close(self) -> None:
        self.con.close()


def raw_rows(con: sqlite3.Connection) -> list[tuple[int, dict[str, Any], str, str]]:
    """(seq, stored body, prev_hash, hash) for every event, exactly as stored."""
    rows = con.execute(
        "SELECT seq, decision_id, step, kind, name, ts, data, prev_hash, hash FROM events ORDER BY seq"
    ).fetchall()
    out = []
    for seq, did, step, kind, name, ts, data, prev, h in rows:
        body = {"decision_id": did, "step": step, "kind": kind, "name": name, "ts": ts,
                "data": json.loads(data)}  # fmt: skip
        out.append((int(seq), body, str(prev), str(h)))
    return out


def verify_rows(
    rows: list[tuple[int, dict[str, Any], str, str]],
    blobs: dict[str, str] | None = None,
    *,
    chain: bool = True,
    checkpoints: list[tuple[int, str, str]] | None = None,
    signer: Signer | None = None,
    checkpoint_every: int = 100,
    witness: Witness | None = None,
) -> VerifyReport:
    """Verify stored rows against the selected integrity layers.

    With ``chain=False`` and no checkpoints or witness, only sequence numbers are checked
    (a gap or a duplicate is the most a plain table can reveal).
    """
    rep = VerifyReport(valid=True, events=len(rows))

    def bad(seq: int, why: str) -> None:
        if rep.first_bad_seq is None or seq < rep.first_bad_seq:
            rep.first_bad_seq = seq
        rep.valid = False
        rep.problems.append(f"seq {seq}: {why}")

    computed: dict[int, str] = {}
    prev = GENESIS
    for i, (seq, body, stored_prev, stored_hash) in enumerate(rows, start=1):
        if seq != i:
            bad(min(seq, i), f"sequence gap or reorder (expected {i})")
        if not chain:
            computed[seq] = stored_hash
            continue
        if stored_prev != prev:
            bad(seq, "prev_hash does not match the preceding event")
        h = chain_hash(prev, body)
        if h != stored_hash:
            bad(seq, "content does not match its hash")
        ref = body["data"].get("output")
        if blobs is not None and isinstance(ref, dict) and "$blob" in ref:
            content = blobs.get(ref["$blob"])
            if content is None or sha256(content) != ref["$blob"]:
                bad(seq, "referenced blob missing or altered")
        computed[seq] = h
        prev = h
    if checkpoints is not None:
        if signer is None:
            raise ValueError("checkpoint verification needs the signer")
        for seq, head, mac in checkpoints:
            rep.checkpoints_checked += 1
            if not signer.check(seq, head, mac):
                bad(seq, "checkpoint signature invalid")
            elif seq > len(rows):
                bad(len(rows) + 1, f"log truncated before signed checkpoint {seq}")
            elif computed.get(seq) != head:
                bad(seq, "chain differs from signed checkpoint")
        present = {s for s, _, _ in checkpoints}
        for seq in range(checkpoint_every, len(rows) + 1, checkpoint_every):
            if seq not in present:
                bad(seq, "signed checkpoint missing")
    if witness is not None:
        for seq, head in witness.entries:
            rep.anchors_checked += 1
            if seq > len(rows):
                bad(len(rows) + 1, f"log truncated before anchored event {seq}")
            elif computed.get(seq) != head:
                bad(seq, "chain differs from external anchor")
    return rep


def verify_memory(log: MemoryLog, **layers: Any) -> VerifyReport:
    rows = []
    for r in log.records():
        stored, _ = dehydrate(r.event.data)
        body = r.event.model_copy(update={"data": normalise(stored)}).body()
        rows.append((r.seq, body, r.prev_hash, r.hash))
    return verify_rows(rows, log.blobs, **layers)


def verify_sqlite(log: SQLiteLog, **layers: Any) -> VerifyReport:
    with log.lock:
        rows = raw_rows(log.con)
        blobs = dict(log.con.execute("SELECT hash, content FROM blobs").fetchall())
    return verify_rows(rows, blobs, **layers)
