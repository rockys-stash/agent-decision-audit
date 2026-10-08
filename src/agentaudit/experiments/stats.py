"""Seed-level statistics: means with bootstrap confidence intervals."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def mean_ci(
    values: Sequence[float], n_boot: int = 2000, seed: int = 0
) -> dict[str, float | int | None]:
    """Mean and 95% percentile-bootstrap CI over independent replications (seeds)."""
    v = np.asarray([x for x in values if x is not None and not np.isnan(x)], dtype=float)
    if len(v) == 0:
        return {"mean": None, "lo": None, "hi": None, "n": 0}
    if len(v) == 1:
        return {"mean": float(v[0]), "lo": None, "hi": None, "n": 1}
    rng = np.random.default_rng(seed)
    boots = rng.choice(v, size=(n_boot, len(v)), replace=True).mean(axis=1)
    return {"mean": float(v.mean()), "lo": float(np.percentile(boots, 2.5)),
            "hi": float(np.percentile(boots, 97.5)), "n": len(v)}  # fmt: skip


def pooled_rate(
    successes: Sequence[int], totals: Sequence[int], n_boot: int = 2000, seed: int = 0
) -> dict[str, float | int | None]:
    """Pooled rate over seeds with a CI from resampling seeds (for rare events)."""
    s, t = np.asarray(successes, dtype=float), np.asarray(totals, dtype=float)
    if t.sum() == 0:
        return {"mean": None, "lo": None, "hi": None, "n": 0, "k": 0}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(s), size=(n_boot, len(s)))
    ss, tt = s[idx].sum(axis=1), t[idx].sum(axis=1)
    boots = np.divide(ss, tt, out=np.full(ss.shape, np.nan), where=tt > 0)
    boots = boots[~np.isnan(boots)]
    return {"mean": float(s.sum()) / float(t.sum()), "lo": float(np.percentile(boots, 2.5)),
            "hi": float(np.percentile(boots, 97.5)), "n": int(t.sum()), "k": int(s.sum())}  # fmt: skip
