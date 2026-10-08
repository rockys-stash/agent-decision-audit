"""Canonical JSON and hashing shared by the log, the replay engine and the detector."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any


def normalise(value: Any) -> Any:
    """Convert a value to plain JSON types with stable floats.

    Floats are rounded to 10 significant digits so that the same computation on different
    platforms or library versions hashes identically; NaN and infinities are rejected because
    canonical JSON cannot represent them.
    """
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite float in audit record")
        return float(f"{value:.10g}")
    if hasattr(value, "item") and callable(value.item):  # numpy scalar
        return normalise(value.item())
    if isinstance(value, dict):
        return {str(k): normalise(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [normalise(v) for v in value]
    raise TypeError(f"cannot record value of type {type(value).__name__}")


def canonical(value: Any) -> str:
    return json.dumps(normalise(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256(text: str | bytes) -> str:
    data = text.encode() if isinstance(text, str) else text
    return hashlib.sha256(data).hexdigest()


def digest(value: Any) -> str:
    return sha256(canonical(value))
