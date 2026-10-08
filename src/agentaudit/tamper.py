"""Tampering attacks on a stored log, and the integrity layers that should catch them (E4).

The attacker has write access to the log database (events, blobs and checkpoints) and, in the
strongest variant, the checkpoint signing key. Nobody but the witness can write to the
external witness store. Attackers renumber sequence numbers after deleting or inserting
events, so a plain sequence check cannot see the change.
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass
from typing import Any

from agentaudit.log import Signer, VerifyReport, Witness, chain_hash, verify_rows

Row = tuple[int, dict[str, Any], str, str]
Checkpoint = tuple[int, str, str]

ATTACKS = (
    "edit_event",  # change a stored event's content
    "edit_blob",  # change a stored tool output (blob)
    "delete_event",  # remove an event, renumber the rest
    "insert_event",  # insert a forged event, linked to its predecessor
    "reorder_events",  # swap two adjacent events
    "truncate_tail",  # drop the most recent events (and checkpoints beyond the new end)
    "rewrite_without_key",  # edit, then recompute every later hash; drop unverifiable checkpoints
    "rewrite_with_key",  # edit, recompute every later hash and re-sign every later checkpoint
)
DEFENSES = (
    "sequence_only",
    "hash_chain",
    "chain_and_signed_checkpoints",
    "chain_checkpoints_and_anchor",
)


@dataclass
class Tampered:
    rows: list[Row]
    blobs: dict[str, str]
    checkpoints: list[Checkpoint]
    target: int  # sequence number where the change was made


def _renumber(rows: list[Row]) -> list[Row]:
    return [(i, body, prev, h) for i, (_, body, prev, h) in enumerate(rows, start=1)]


def _rechain(rows: list[Row], start: int) -> list[Row]:
    """Recompute prev/hash from position ``start`` (1-based) to the end."""
    out = list(rows[: start - 1])
    prev = out[-1][3] if out else "0" * 64
    for seq, body, _, _ in rows[start - 1 :]:
        h = chain_hash(prev, body)
        out.append((seq, body, prev, h))
        prev = h
    return out


def _edit(body: dict[str, Any]) -> dict[str, Any]:
    b = copy.deepcopy(body)
    data = b["data"]
    for key in ("amount", "value", "score", "passed", "decision"):
        if key in data:
            v = data[key]
            if isinstance(v, bool):
                data[key] = not v
            elif isinstance(v, int | float):
                data[key] = v * 0.5 if v else 1.0  # halving zero would change nothing
            else:
                data[key] = "deny" if v == "pay" else "pay"
            break
    else:
        data["note"] = "edited"
    if b == body:  # an attack that changes nothing would be counted as undetected
        raise AssertionError("edit left the event unchanged")
    return b


def attack(
    kind: str,
    rows: list[Row],
    blobs: dict[str, str],
    checkpoints: list[Checkpoint],
    rng: random.Random,
    signer: Signer,
) -> Tampered:
    n = len(rows)
    k = rng.randrange(1, n - 1)
    r, b, cps = list(rows), dict(blobs), list(checkpoints)
    if kind == "edit_event":
        seq, body, prev, h = r[k - 1]
        r[k - 1] = (seq, _edit(body), prev, h)
    elif kind == "edit_blob":
        refs = [(i, row[1]["data"]["output"]["$blob"]) for i, row in enumerate(r, start=1)
                if isinstance(row[1]["data"].get("output"), dict) and "$blob" in row[1]["data"]["output"]]  # fmt: skip
        k, ref = refs[rng.randrange(len(refs))]
        # The same blob may be shared by several events; the first reference is where it shows.
        k = next(i for i, x in refs if x == ref)
        b[ref] = b[ref].replace("1", "2", 1) if "1" in b[ref] else b[ref] + " "
    elif kind == "delete_event":
        del r[k - 1]
        r = _renumber(r)
    elif kind == "insert_event":
        seq, body, _, _ = r[k - 1]
        forged = _edit(body)
        r.insert(k, (0, forged, r[k - 1][3], chain_hash(r[k - 1][3], forged)))
        r = _renumber(r)
        k = k + 2  # the forged event chains correctly; its successor no longer does
    elif kind == "reorder_events":
        r[k - 1], r[k] = r[k], r[k - 1]
        r = _renumber(r)
    elif kind == "truncate_tail":
        m = rng.randrange(1, min(2000, n - 1))
        r = r[: n - m]
        cps = [c for c in cps if c[0] <= len(r)]
        k = len(r) + 1
    elif kind == "rewrite_without_key":
        seq, body, prev, h = r[k - 1]
        r[k - 1] = (seq, _edit(body), prev, h)
        r = _rechain(r, k)
        cps = [c for c in cps if c[0] < k]  # cannot re-sign, so hide the evidence
    elif kind == "rewrite_with_key":
        seq, body, prev, h = r[k - 1]
        r[k - 1] = (seq, _edit(body), prev, h)
        r = _rechain(r, k)
        cps = [
            (s, r[s - 1][3], signer.sign(s, r[s - 1][3])) if s >= k else (s, hd, mac)
            for s, hd, mac in cps
        ]
    else:
        raise ValueError(kind)
    return Tampered(r, b, cps, k)


def check(
    defense: str,
    t: Tampered,
    signer: Signer,
    witness: Witness,
    checkpoint_every: int,
) -> VerifyReport:
    if defense == "sequence_only":
        return verify_rows(t.rows, None, chain=False)
    if defense == "hash_chain":
        return verify_rows(t.rows, t.blobs)
    if defense == "chain_and_signed_checkpoints":
        return verify_rows(t.rows, t.blobs, checkpoints=t.checkpoints, signer=signer,
                           checkpoint_every=checkpoint_every)  # fmt: skip
    if defense == "chain_checkpoints_and_anchor":
        return verify_rows(t.rows, t.blobs, checkpoints=t.checkpoints, signer=signer,
                           checkpoint_every=checkpoint_every, witness=witness)  # fmt: skip
    raise ValueError(defense)
