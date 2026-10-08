"""Regenerates the report's tables (Markdown) and figures (SVG) from the latest completed runs.

Every number written here is read from a ``summary.json`` produced by ``agentaudit run``; each
section names the run id and commit it came from. Experiments without a completed run are
reported as pending rather than omitted. Output is deterministic for a given set of runs, so CI
can check that the committed report matches the committed results.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentaudit.agent import DECISION_TYPES, HELD_OUT, VIOLATIONS
from agentaudit.schema import LEVEL_LABELS, Level
from agentaudit.tamper import ATTACKS, DEFENSES

EXPERIMENTS = ("e1_reconstruction", "e2_audit_delay", "e3_violations", "e4_tamper", "e5_overhead")
STATUS_LABELS = {
    "reproduced": "Reproduced",
    "attested": "Attested",
    "unverifiable": "Unverifiable",
    "diverged": "Diverged",
    "not_reconstructable": "Not reconstructable",
}
TYPE_LABELS = {
    "rule": "Rule only",
    "calculation": "Calculation",
    "fx": "Currency conversion",
    "model": "Fraud model",
    "stochastic": "Random QA sample",
    "opaque": "External assessor",
    "human": "Human adjuster",
}
DEFENSE_LABELS = {
    "sequence_only": "Sequence numbers",
    "hash_chain": "Hash chain",
    "chain_and_signed_checkpoints": "+ signed checkpoints",
    "chain_checkpoints_and_anchor": "+ external anchor",
}
ATTACK_LABELS = {
    "edit_event": "Edit an event",
    "edit_blob": "Edit a stored tool output",
    "delete_event": "Delete an event",
    "insert_event": "Insert an event",
    "reorder_events": "Swap two events",
    "truncate_tail": "Truncate the tail",
    "rewrite_without_key": "Rewrite suffix, no key",
    "rewrite_with_key": "Rewrite suffix, with key",
}

# Light-mode chart tokens from docs/DESIGN.md. Levels use one teal ramp, light to dark, so the
# order reads as "more instrumentation"; live replay is a neutral reference.
INK, INK2, MUTED, GRID, SURFACE = "#121314", "#45474b", "#63656a", "#e1e1dd", "#ffffff"
LEVEL_COLOR = ("#9ab8b4", "#6f9f99", "#46867e", "#1f6d65", "#0b4f4a")
REFERENCE = "#8e9095"
DETECTOR_COLOR = {"rule": "#0f6e68", "replay": "#45474b"}
OK, ATTEST = "#2f6b3a", "#8a5a12"  # status tokens: reproduced, attested only


# --- loading and formatting --------------------------------------------------------------------
def _latest(root: Path, exp: str) -> dict[str, Any] | None:
    marker = root / "results" / exp / "LATEST"
    if not marker.exists():
        return None
    run = root / "results" / exp / marker.read_text().strip() / "summary.json"
    if not run.exists():
        return None
    data: dict[str, Any] = json.loads(run.read_text())
    return data


def _pct(s: dict[str, Any] | float | None, digits: int = 1, ci: bool = True) -> str:
    """A rate as a percentage, with its 95% CI when one is available."""
    if s is None:
        return "n/a"
    if isinstance(s, int | float):
        return f"{s * 100:.{digits}f}"
    if s.get("mean") is None:
        return "n/a"
    m = f"{s['mean'] * 100:.{digits}f}"
    if ci and s.get("lo") is not None and s.get("hi") is not None:
        lo, hi = s["lo"] * 100, s["hi"] * 100
        if round(lo, digits) == round(hi, digits) == round(s["mean"] * 100, digits):
            return m
        return f"{m} [{lo:.{digits}f}, {hi:.{digits}f}]"
    return m


def _num(s: dict[str, Any] | None, digits: int = 1) -> str:
    if not s or s.get("mean") is None:
        return "n/a"
    m = f"{s['mean']:,.{digits}f}"
    if s.get("lo") is not None and s.get("hi") is not None:
        return f"{m} [{s['lo']:,.{digits}f}, {s['hi']:,.{digits}f}]"
    return m


def _prov(s: dict[str, Any]) -> str:
    p = s["provenance"]
    extra = f" · {p['n_claims']} claims per seed" if "n_claims" in p else ""
    return (
        f"_Source: `results/{p['experiment']}/{p['run_id']}` · commit `{p['commit'][:12]}` · "
        f"{p['seeds']} seeds from base {p['base_seed']}{extra} · runtime {p['runtime_seconds']} s._"
    )


def _span(values: list[int]) -> str:
    lo, hi = min(values), max(values)
    return f"{lo:,}" if lo == hi else f"{lo:,} to {hi:,}"


def _pending(title: str, exp: str) -> list[str]:
    return [f"## {title}", "", f"Status: pending (no completed run of `{exp}`).", ""]


def _row(
    s: dict[str, Any], mode: str, delay: float, level: int, dtype: str = "all"
) -> dict[str, Any] | None:
    for r in s["rows"]:
        if (
            r["mode"] == mode
            and float(r["delay"]) == float(delay)
            and r["level"] == level
            and r["type"] == dtype
        ):
            return r
    return None


def _level(lvl: int) -> str:
    return LEVEL_LABELS[Level(lvl)]


# --- tables ------------------------------------------------------------------------------------
def _e1_tables(s: dict[str, Any]) -> list[str]:
    delay = s["rows"][0]["delay"]
    out = ["## E1: Reconstruction by instrumentation level and decision type", "", _prov(s), "",
           f"{s['decisions']:,} decisions by the clean agent, replayed {delay:g} days after each decision. Rates are "
           "means over seeds with 95% bootstrap CIs (percent). _Fully reconstructed_ is reproduced or attested: the "
           "auditor, using only the record, re-derived every step and the record agreed. _Route match_ compares the "
           "replay with the simulation's ground truth: same branches, same final decision and amount. _Silent "
           "misreconstruction_ is a replay the auditor would accept (reproduced, attested or unverifiable) whose "
           "route differs from what actually happened.", "",
           "### All decisions", "",
           "| Replay | Level | Fully reconstructed | Reproduced | Attested | Unverifiable | Diverged | Not reconstructable | Route match | Silent misreconstruction |",
           "|---|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
    rows = [("record", lvl) for lvl in range(5)] + [("live", 4)]
    for mode, lvl in rows:
        r = _row(s, mode, delay, lvl)
        if r is None:
            continue
        name = "Record" if mode == "record" else "Live (re-query everything)"
        out.append(
            f"| {name} | {_level(lvl)} | {_pct(r['fully_reconstructed'])} | "
            + " | ".join(_pct(r[k]) for k in STATUS_LABELS)
            + f" | {_pct(r['route_match'])} | {_pct(r['silent_misreconstruction'])} |"
        )
    types = s.get("decision_types", {})
    out += ["", "### By decision type (record mode)", "",
            "A decision's type is the hardest dependency on its path, in the order human, external assessor, random "
            "sample, fraud model, rule, currency conversion, calculation (see data/DATASET.md).", "",
            "| Decision type | Decisions | L0 route match | L2 route match | L3 route match | L4 reproduced | L4 attested | L4 fully reconstructed |",
            "|---|---|---|---|---|---|---|---|"]  # fmt: skip
    for t in DECISION_TYPES:
        r0, r2, r3, r4 = (_row(s, "record", delay, lvl, t) for lvl in (0, 2, 3, 4))
        if r4 is None:
            continue
        out.append(
            f"| {TYPE_LABELS[t]} | {types.get(t, 0):,} | {_pct(r0 and r0['route_match'])} | {_pct(r2 and r2['route_match'])} | "
            f"{_pct(r3 and r3['route_match'])} | {_pct(r4['reproduced'])} | {_pct(r4['attested'])} | {_pct(r4['fully_reconstructed'])} |"
        )
    if s.get("record_divergence"):
        out += ["", "### Where record-mode replay diverged first (four most frequent per level)", "",
                "| Level | First divergent step (fields that differ) | Decisions | Share of all decisions |",
                "|---|---|---|---|"]  # fmt: skip
        for lvl in range(5):
            items = [(k.split("|", 2)[2], n) for k, n in s["record_divergence"].items()
                     if k.split("|")[1] == str(lvl) and float(k.split("|")[0]) == float(delay)]  # fmt: skip
            for step, n in sorted(items, key=lambda kv: (-kv[1], kv[0]))[:4]:
                out.append(f"| {_level(lvl)} | {step} | {n:,} | {n / s['decisions'] * 100:.1f}% |")
    if s.get("live_divergence"):
        out += ["", "### Why live replay diverged (first divergent step)", "",
                "| Cause | Decisions |", "|---|---|"]  # fmt: skip
        for key, n in sorted(s["live_divergence"].items(), key=lambda kv: -kv[1]):
            out.append(f"| {key.split('|', 1)[1]} | {n:,} |")
    if s.get("answers"):
        out += ["", f"### Audit questions answered correctly ({delay:g}-day delay)", "",
                "Each question is answered from the record where the level holds the answer, otherwise from the replay, "
                "and the answer is checked against the complete original trace. Percent of decisions answered correctly, "
                "mean over seeds with 95% CI.", "",
                "| Question | " + " | ".join(_level(lvl) for lvl in range(5)) + " |",
                "|---|" + "---|" * 5]  # fmt: skip
        by_q: dict[str, dict[int, dict[str, Any]]] = {}
        texts: dict[str, str] = {}
        for a in s["answers"]:
            by_q.setdefault(a["question"], {})[a["level"]] = a
            texts[a["question"]] = a["text"]
        for q, lv in by_q.items():
            out.append(
                f"| {texts[q]} | "
                + " | ".join(_pct(lv[lvl]["correct"]) if lvl in lv else "n/a" for lvl in range(5))
                + " |"
            )
        wrong = [
            (q, lvl, a)
            for q, lv in by_q.items()
            for lvl, a in lv.items()
            if a["replay_wrong"] + a["record_wrong"] > 0
        ]
        if wrong:
            out += [
                "",
                "Questions where an answer was given but was wrong (share of decisions, pooled):",
                "",
            ]
            for q, lvl, a in wrong:
                out.append(f"- {_level(lvl)}, {q}: {_pct(a['replay_wrong'] + a['record_wrong'], 2)}% wrong "
                           f"({_pct(a['replay_wrong'], 2)}% from the replay, {_pct(a['record_wrong'], 2)}% from the record)")  # fmt: skip
    return [*out, ""]


def _e2_tables(s: dict[str, Any]) -> list[str]:
    delays = sorted({float(r["delay"]) for r in s["rows"]})
    out = ["## E2: Reconstruction as the audit happens later", "", _prov(s), "",
           "All decisions by the clean agent. The audit day is the decision day plus the delay; anything the record "
           "lacks is looked up as it is on the audit day. Percent, mean over seeds with 95% CI.", "",
           "### Route match (replay followed the original path)", "",
           "| Replay | Level | " + " | ".join(f"{d:g} days" for d in delays) + " |",
           "|---|---|" + "---|" * len(delays)]  # fmt: skip
    for mode, lvl in [("record", lvl) for lvl in range(5)] + [("live", 4)]:
        cells = [_row(s, mode, d, lvl) for d in delays]
        if all(c is None for c in cells):
            continue
        name = "Record" if mode == "record" else "Live"
        out.append(
            f"| {name} | {_level(lvl)} | "
            + " | ".join(_pct(c and c["route_match"]) for c in cells)
            + " |"
        )
    out += ["", "### Silent misreconstruction (accepted by the auditor, but the wrong path)", "",
            "| Replay | Level | " + " | ".join(f"{d:g} days" for d in delays) + " |",
            "|---|---|" + "---|" * len(delays)]  # fmt: skip
    for mode, lvl in [("record", lvl) for lvl in range(5)] + [("live", 4)]:
        cells = [_row(s, mode, d, lvl) for d in delays]
        if all(c is None for c in cells):
            continue
        name = "Record" if mode == "record" else "Live"
        out.append(
            f"| {name} | {_level(lvl)} | "
            + " | ".join(_pct(c and c["silent_misreconstruction"]) for c in cells)
            + " |"
        )
    out += ["", "### Fully reconstructed (reproduced or attested)", "",
            "| Replay | Level | " + " | ".join(f"{d:g} days" for d in delays) + " |",
            "|---|---|" + "---|" * len(delays)]  # fmt: skip
    for mode, lvl in [("record", lvl) for lvl in range(5)] + [("live", 4)]:
        cells = [_row(s, mode, d, lvl) for d in delays]
        if all(c is None for c in cells):
            continue
        name = "Record" if mode == "record" else "Live"
        out.append(
            f"| {name} | {_level(lvl)} | "
            + " | ".join(_pct(c and c["fully_reconstructed"]) for c in cells)
            + " |"
        )
    if s.get("live_divergence"):
        causes = sorted({k.split("|", 1)[1] for k in s["live_divergence"]})
        out += ["", "### Live replay: first divergent step by delay (decisions)", "",
                "| Cause | " + " | ".join(f"{d:g} days" for d in delays) + " |",
                "|---|" + "---|" * len(delays)]  # fmt: skip
        for c in causes:
            out.append(
                f"| {c} | "
                + " | ".join(f"{s['live_divergence'].get(f'{d}|{c}', 0):,}" for d in delays)
                + " |"
            )
    return [*out, ""]


def _e3_tables(s: dict[str, Any]) -> list[str]:
    out = ["## E3: Automated detection of policy violations", "", _prov(s), "",
           f"The faulty agent attempts a violation on a share of claims; the type is drawn from {len(VIOLATIONS)} "
           f"kinds, {len(HELD_OUT)} of which ({', '.join(HELD_OUT)}) were held out while the checks were written. "
           f"{s['decisions_faulty']:,} faulty-agent and {s['decisions_clean']:,} clean-agent decisions. _Rule_ is the "
           "13-check audit standard run on the trace as stored at each level (falling back to live lookups 30 days "
           "later where the level lacks data). _Reference replay_ re-runs the approved agent code on the recorded "
           "inputs and flags any divergence. Rates are pooled over seeds with 95% CIs from resampling seeds.", "",
           "### By level", "",
           "| Level | Detector | Recall, all violations | Recall, designed-for types | Precision | False positives per 1,000 clean decisions | Flags that needed live data |",
           "|---|---|---|---|---|---|---|"]  # fmt: skip
    for r in s["by_level"]:
        fp = r["clean_fp_per_1000"]
        fp_s = "n/a" if fp.get("mean") is None else f"{fp['mean']:.2f}"
        live = "" if r["flagged_live_only"] is None else f"{r['flagged_live_only']:,}"
        out.append(
            f"| {_level(r['level'])} | {'Rule checks' if r['detector'] == 'rule' else 'Reference replay'} | "
            f"{_pct(r['recall_all'])} | {_pct(r['recall_designed'])} | {_pct(r['precision'])} | {fp_s} | {live} |"
        )
    rates = sorted({k.split("_", 1)[1] for r in s["by_type"] for k in r if k.startswith("sample_")})
    out += ["", "### By violation type (recall, percent)", "",
            "| Violation | Injected | Rule L0 | Rule L2 | Rule L4 | Replay L4 | " + " | ".join(f"Sample audit {float(x) * 100:g}%" for x in rates) + " |",
            "|---|---|---|---|---|---|" + "---|" * len(rates)]  # fmt: skip
    for r in s["by_type"]:
        name = r["violation"] + (" (held out)" if r["held_out"] else "")
        out.append(
            f"| {name} | {r['injected']:,} | {_pct(r.get('rule_L0'), ci=False)} | {_pct(r.get('rule_L2'), ci=False)} | "
            f"{_pct(r.get('rule_L4'), ci=False)} | {_pct(r.get('replay_L4'), ci=False)} | "
            + " | ".join(_pct(r.get(f"sample_{x}"), ci=False) for x in rates)
            + " |"
        )
    l4 = [c for c in s["checks"] if c["level"] == 4]
    if l4:
        out += ["", "### Checks at L4", "",
                "| Check | Targets | Findings | On a violation it targets | On the clean agent | Decisions evaluable |",
                "|---|---|---|---|---|---|"]  # fmt: skip
        for c in l4:
            out.append(f"| {c['check']} | {', '.join(c['targets'])} | {c['findings']:,} | {c['on_target']:,} | "
                       f"{c['on_clean_agent']:,} | {c['evaluable']:,} |")  # fmt: skip
    return [*out, ""]


def _e4_tables(s: dict[str, Any]) -> list[str]:
    ev = s["events_per_log"]
    out = ["## E4: Tamper evidence of the stored log", "", _prov(s), "",
           f"Each seed records a clean run into SQLite ({min(ev):,} to {max(ev):,} events per log; "
           f"{_span(s['anchors_per_log'])} anchors) and applies every attack "
           f"{s['rows'][0]['trials'] // len(ev)} times at random positions. Untampered logs verified as valid: "
           f"{'yes' if s['clean_logs_valid'] else 'no'}. _Detected_ is the share of tampered logs the defence rejects; "
           "_located_ is the share of detections that point at the tampered event exactly.", "",
           "### Detected (percent of trials)", "",
           "| Attack | " + " | ".join(DEFENSE_LABELS[d] for d in DEFENSES) + " |",
           "|---|" + "---|" * len(DEFENSES)]  # fmt: skip
    rows = {(r["attack"], r["defense"]): r for r in s["rows"]}
    for a in ATTACKS:
        out.append(
            f"| {ATTACK_LABELS[a]} | "
            + " | ".join(_pct(rows[(a, d)]["detected"], 0) for d in DEFENSES)
            + " |"
        )
    out += ["", "### Located exactly / within one checkpoint interval (percent of detections)", "",
            "| Attack | " + " | ".join(DEFENSE_LABELS[d] for d in DEFENSES) + " |",
            "|---|" + "---|" * len(DEFENSES)]  # fmt: skip
    for a in ATTACKS:
        cells = []
        for d in DEFENSES:
            r = rows[(a, d)]
            cells.append(
                "n/a"
                if r["localised"] is None
                else f"{_pct(r['localised'], 0)} / {_pct(r['localised_within_checkpoint'], 0)}"
            )
        out.append(f"| {ATTACK_LABELS[a]} | " + " | ".join(cells) + " |")
    tail = [(a, rows[(a, "chain_checkpoints_and_anchor")]) for a in ATTACKS]
    tail = [(a, r) for a, r in tail if r["after_last_anchor"]]
    if tail:
        out += ["", "### Attacks that only touched events after the last anchor (full defence)", "",
                "| Attack | Trials | Detected |", "|---|---|---|"]  # fmt: skip
        for a, r in tail:
            out.append(
                f"| {ATTACK_LABELS[a]} | {r['after_last_anchor']:,} | {r['detected_after_last_anchor']:,} |"
            )
    return [*out, ""]


def _e5_tables(s: dict[str, Any]) -> list[str]:
    t = s["timings"]
    out = ["## E5: Cost of instrumentation", "", _prov(s), "",
           f"Median of repeats per seed, then mean over seeds with 95% CI. Machine: {s['cpu']}, {s['cpu_count']} CPUs; "
           "timings are machine-dependent and comparable only within this table.", "",
           "| Measure | Value |", "|---|---|",
           f"| Agent without instrumentation, ms per decision | {_num(t['uninstrumented'], 2)} |",
           f"| Recording to memory (L4), ms per decision | {_num(t['memory_log'], 2)} |",
           f"| Recording to SQLite with checkpoints and anchors, ms per decision | {_num(t['sqlite_log'], 2)} |",
           f"| Record-mode L4 replay, ms per decision | {_num(t['replay_record_L4_ms'], 2)} |",
           f"| Chain verification, events per second | {_num(t['verify_chain_events_per_s'], 0)} |",
           f"| Chain, checkpoint and anchor verification, events per second | {_num(t['verify_all_events_per_s'], 0)} |",
           f"| Events per decision | {_num(s['events_per_decision'], 1)} |",
           f"| SQLite bytes per decision (after VACUUM) | {_num(s['sqlite_bytes_per_decision'], 0)} |",
           "", "### Trace size per decision by level (bytes of canonical JSON)", "",
           "| Level | Inline | With tool outputs stored once as blobs |", "|---|---|---|"]  # fmt: skip
    for lvl, v in s["json_bytes_per_decision"].items():
        out.append(
            f"| {lvl} | {_num(v, 0)} | {_num(s['deduplicated_bytes_per_decision'][lvl], 0)} |"
        )
    return [*out, ""]


# --- figures -----------------------------------------------------------------------------------
def _setup() -> Any:
    import matplotlib

    matplotlib.use("Agg")
    import logging

    import matplotlib.pyplot as plt

    # Inter is the console's font; it is rarely installed system-wide, so fall back quietly.
    logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
    plt.rcParams.update({
        "font.family": ["Inter", "DejaVu Sans"], "font.size": 9, "text.color": INK,
        "axes.edgecolor": MUTED, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
        "axes.spines.top": False, "axes.spines.right": False, "svg.fonttype": "none",
        "svg.hashsalt": "agentaudit", "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
        "legend.frameon": False,
    })  # fmt: skip
    return plt


def _save(plt: Any, fig: Any, path: Path) -> Path:
    fig.savefig(path, metadata={"Date": None})
    plt.close(fig)
    return path


def _err(r: dict[str, Any]) -> tuple[list[float], list[float]]:
    m = r["mean"] * 100
    lo = r["lo"] * 100 if r.get("lo") is not None else m
    hi = r["hi"] * 100 if r.get("hi") is not None else m
    return [m - lo], [hi - m]


def _fig_e1(plt: Any, s: dict[str, Any], out: Path) -> Path:
    delay = s["rows"][0]["delay"]
    types = [t for t in DECISION_TYPES if _row(s, "record", delay, 4, t)]
    fig, axes = plt.subplots(
        1, 2, figsize=(9.2, 3.9), sharey=True, gridspec_kw={"width_ratios": [1.5, 1]}
    )
    ax = axes[0]
    for i, t in enumerate(types):
        for lvl in range(5):
            r = _row(s, "record", delay, lvl, t)
            if r is None or r["route_match"]["mean"] is None:
                continue
            lo, hi = _err(r["route_match"])
            ax.errorbar(r["route_match"]["mean"] * 100, i + (lvl - 2) * 0.15, xerr=[lo, hi], fmt="o", ms=4.5,
                        color=LEVEL_COLOR[lvl], elinewidth=1.5, capsize=0, label=_level(lvl) if i == 0 else None)  # fmt: skip
    ax.set_xlim(-3, 103)
    ax.set_title("Route match with the original decision (%)", loc="left", fontsize=9.5)
    ax.grid(axis="y", visible=False)
    ax.set_yticks(range(len(types)), [TYPE_LABELS[t] for t in types])
    ax.invert_yaxis()
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=5, fontsize=7.5, handletextpad=0.2,
              columnspacing=0.8)  # fmt: skip
    ax = axes[1]
    for i, t in enumerate(types):
        r = _row(s, "record", delay, 4, t)
        assert r is not None
        rep, att = r["reproduced"]["mean"] * 100, r["attested"]["mean"] * 100
        ax.barh(i, rep, height=0.55, color=OK, label="Reproduced (re-derived)" if i == 0 else None)
        ax.barh(i, att, left=rep, height=0.55, color=ATTEST, edgecolor=SURFACE, linewidth=1.5,
                label="Attested (taken from the record)" if i == 0 else None)  # fmt: skip
    ax.set_xlim(0, 100)
    ax.set_title("L4 record replay: how each step was verified (%)", loc="left", fontsize=9.5)
    ax.grid(axis="y", visible=False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=1, fontsize=7.5)
    fig.suptitle(f"E1: record-mode replay {delay:g} days after the decision, by decision type",
                 x=0.01, ha="left", fontsize=10)  # fmt: skip
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    return _save(plt, fig, out / "e1_reconstruction.svg")


def _fig_e2(plt: Any, s: dict[str, Any], out: Path) -> Path:
    delays = sorted({float(r["delay"]) for r in s["rows"]})
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.6))
    for ax, metric, title in ((axes[0], "route_match", "Route match (%)"),
                              (axes[1], "silent_misreconstruction", "Silent misreconstruction (%)")):  # fmt: skip
        series = [("record", lvl, _level(lvl), LEVEL_COLOR[lvl], "-") for lvl in range(5)]
        series.append(("live", 4, "Live, L4", REFERENCE, "--"))
        ends: list[tuple[float, str, float]] = []
        for mode, lvl, label, color, ls in series:
            pts = [(d, _row(s, mode, d, lvl)) for d in delays]
            pts2 = [
                (d, r[metric]) for d, r in pts if r is not None and r[metric]["mean"] is not None
            ]
            if not pts2:
                continue
            xs = [d for d, _ in pts2]
            ys = [m["mean"] * 100 for _, m in pts2]
            lo = [(m["lo"] if m["lo"] is not None else m["mean"]) * 100 for _, m in pts2]
            hi = [(m["hi"] if m["hi"] is not None else m["mean"]) * 100 for _, m in pts2]
            ax.fill_between(xs, lo, hi, color=color, alpha=0.15, linewidth=0)
            ax.plot(xs, ys, ls, color=color, lw=2, marker="o", ms=4, label=label)
            ends.append((ys[-1], label, xs[-1]))
        groups: list[list[tuple[float, str, float]]] = []
        for e in sorted(ends):
            if groups and abs(groups[-1][-1][0] - e[0]) < 4:
                groups[-1].append(e)
            else:
                groups.append([e])
        for g in groups:
            text = ", ".join(
                sorted(
                    lbl.split(" ")[0] if not lbl.startswith("Live") else "~live" for _, lbl, _ in g
                )
            ).replace("~", "")
            ax.annotate(text, (g[0][2], sum(v for v, _, _ in g) / len(g)), xytext=(6, 0),
                        textcoords="offset points", va="center", fontsize=7.5, color=INK2)  # fmt: skip
        ax.set_xscale("symlog", linthresh=7)
        ax.set_xticks(delays, [f"{d:g}" for d in delays])
        ax.set_xlim(right=delays[-1] * 1.9)
        ax.set_xlabel("Days between decision and audit")
        ax.set_title(title, loc="left", fontsize=9.5)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=6, fontsize=8)
    fig.suptitle("E2: reconstruction against audit delay", x=0.01, ha="left", fontsize=10)
    fig.tight_layout(rect=(0, 0.07, 1, 0.95))
    return _save(plt, fig, out / "e2_audit_delay.svg")


def _fig_e3(plt: Any, s: dict[str, Any], out: Path) -> Path:
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.4))
    levels = sorted({r["level"] for r in s["by_level"]})
    for ax, metric, title in ((axes[0], "recall_all", "Recall, all injected violations (%)"),
                              (axes[1], "precision", "Precision (%)")):  # fmt: skip
        for j, det in enumerate(("rule", "replay")):
            for lvl in levels:
                r = next(
                    (x for x in s["by_level"] if x["level"] == lvl and x["detector"] == det), None
                )
                if r is None or r[metric]["mean"] is None:
                    continue
                lo, hi = _err(r[metric])
                ax.errorbar(lvl + (j - 0.5) * 0.18, r[metric]["mean"] * 100, yerr=[lo, hi], fmt="o", ms=5,
                            color=DETECTOR_COLOR[det], elinewidth=1.5, capsize=0,
                            label=("Rule checks" if det == "rule" else "Reference replay") if lvl == levels[0] else None)  # fmt: skip
        ax.set_xticks(levels, [_level(lvl).split(" ")[0] for lvl in levels])
        ax.set_ylim(-3, 103)
        ax.set_title(title, loc="left", fontsize=9.5)
        ax.grid(axis="x", visible=False)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=2, fontsize=8)
    fig.suptitle(
        "E3: automated violation detection by instrumentation level", x=0.01, ha="left", fontsize=10
    )
    fig.tight_layout(rect=(0, 0.07, 1, 0.95))
    return _save(plt, fig, out / "e3_violations.svg")


def _fig_e4(plt: Any, s: dict[str, Any], out: Path) -> Path:
    rows = {(r["attack"], r["defense"]): r for r in s["rows"]}
    fig, ax = plt.subplots(figsize=(8.2, 3.9))
    ax.grid(visible=False)
    for i, a in enumerate(ATTACKS):
        for j, d in enumerate(DEFENSES):
            v = rows[(a, d)]["detected"]
            shade = (1 - v) * 0.86 + v * 0.0
            face = (0.06 + shade * 0.9, 0.43 + shade * 0.52, 0.41 + shade * 0.55)
            ax.add_patch(
                plt.Rectangle((j, i), 0.96, 0.92, facecolor=face, edgecolor=SURFACE, linewidth=2)
            )
            ax.text(j + 0.48, i + 0.46, f"{v * 100:.0f}%", ha="center", va="center", fontsize=8.5,
                    color=SURFACE if v > 0.55 else INK)  # fmt: skip
    ax.set_xlim(0, len(DEFENSES))
    ax.set_ylim(len(ATTACKS), 0)
    ax.set_xticks([j + 0.48 for j in range(len(DEFENSES))], [DEFENSE_LABELS[d] for d in DEFENSES])
    ax.set_yticks([i + 0.46 for i in range(len(ATTACKS))], [ATTACK_LABELS[a] for a in ATTACKS])
    ax.tick_params(length=0)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.set_title(
        "E4: share of tampered logs detected, by attack and defence", loc="left", fontsize=10
    )
    fig.tight_layout()
    return _save(plt, fig, out / "e4_tamper.svg")


def generate_report(root: Path) -> list[Path]:
    s = {e: _latest(root, e) for e in EXPERIMENTS}
    lines = ["# Generated results", "",
             "Produced by `agentaudit report` from the latest completed run of each experiment. Do not edit by hand; "
             "every section names the run and commit it came from. All data are from the simulated claims world "
             "(data/DATASET.md).", ""]  # fmt: skip
    sections = [
        (
            "e1_reconstruction",
            "E1: Reconstruction by instrumentation level and decision type",
            _e1_tables,
        ),
        ("e2_audit_delay", "E2: Reconstruction as the audit happens later", _e2_tables),
        ("e3_violations", "E3: Automated detection of policy violations", _e3_tables),
        ("e4_tamper", "E4: Tamper evidence of the stored log", _e4_tables),
        ("e5_overhead", "E5: Cost of instrumentation", _e5_tables),
    ]
    for exp, title, fn in sections:
        data = s[exp]
        lines += fn(data) if data else _pending(title, exp)
    lines += ["## Trust study with people", "",
              "Status: pending. The audit-question results above are a proxy for whether a trail supports trust; "
              "no study with human auditors has been run (protocol in docs/STUDY.md).", ""]  # fmt: skip
    out = root / "research" / "generated" / "results.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    written = [out]

    plt = _setup()
    fig_dir = root / "research" / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    for exp, fig_fn in (("e1_reconstruction", _fig_e1), ("e2_audit_delay", _fig_e2),
                        ("e3_violations", _fig_e3), ("e4_tamper", _fig_e4)):  # fmt: skip
        data = s[exp]
        if data:
            written.append(fig_fn(plt, data, fig_dir))
    return written
