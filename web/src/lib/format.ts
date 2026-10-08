import type { CI, DecisionType, Status } from "./api";

export const LEVELS = [0, 1, 2, 3, 4] as const;
export const LEVEL_LABEL: Record<number, string> = {
  0: "L0 output",
  1: "L1 inputs",
  2: "L2 tools",
  3: "L3 steps",
  4: "L4 environment",
};
export const LEVEL_HELP: Record<number, string> = {
  0: "Only the final decision and its time.",
  1: "Adds the input claim, the stated rationale and the outcome.",
  2: "Adds every tool call and external-service answer with its output, the evidence cited and human decisions.",
  3: "Adds every calculation, rule, model score, confidence, alternative and intermediate decision.",
  4: "Adds the environment: agent configuration version, model versions, random seeds, actors and request ids.",
};

export const TYPE_LABEL: Record<DecisionType, string> = {
  rule: "Rule only",
  calculation: "Calculation",
  fx: "Currency conversion",
  model: "Fraud model",
  stochastic: "Random QA sample",
  opaque: "External assessor",
  human: "Human adjuster",
};

export const STATUS: Record<Status, { word: string; glyph: string; tone: "ok" | "attest" | "bad" | "neutral"; help: string }> = {
  reproduced: { word: "Reproduced", glyph: "✓", tone: "ok", help: "Every step re-derived from the record and matched." },
  attested: { word: "Attested", glyph: "◐", tone: "attest", help: "Matched, but some steps (a person, an external service) could only be taken from the record." },
  unverifiable: { word: "Unverifiable", glyph: "?", tone: "neutral", help: "Matched what was recorded, but needed inputs the record does not hold." },
  diverged: { word: "Diverged", glyph: "✕", tone: "bad", help: "The replay disagreed with the record at some step." },
  not_reconstructable: { word: "Not reconstructable", glyph: "∅", tone: "bad", help: "The replay could not run: a human decision that was not recorded cannot be re-requested." },
};

export const KIND_LABEL: Record<string, string> = {
  decision: "decision",
  config: "config",
  tool: "tool",
  input: "input",
  evidence: "evidence",
  calc: "calc",
  rule: "rule",
  model: "model",
  external: "external",
  rng: "random",
  confidence: "confidence",
  alternatives: "alternatives",
  intermediate: "route",
  human: "human",
  final: "final",
  outcome: "outcome",
};

export const DEFENSE_LABEL: Record<string, string> = {
  sequence_only: "Sequence numbers",
  hash_chain: "Hash chain",
  chain_and_signed_checkpoints: "+ signed checkpoints",
  chain_checkpoints_and_anchor: "+ external anchor",
};

export const ATTACK_LABEL: Record<string, string> = {
  edit_event: "Edit an event",
  edit_blob: "Edit a stored tool output",
  delete_event: "Delete an event",
  insert_event: "Insert an event",
  reorder_events: "Swap two events",
  truncate_tail: "Truncate the tail",
  rewrite_without_key: "Rewrite the suffix without the key",
  rewrite_with_key: "Rewrite the suffix with the key",
};

export const EXPERIMENT_LABEL: Record<string, string> = {
  e1_reconstruction: "E1 Reconstruction",
  e2_audit_delay: "E2 Audit delay",
  e3_violations: "E3 Violations",
  e4_tamper: "E4 Tamper evidence",
  e5_overhead: "E5 Overhead",
};

const eur = new Intl.NumberFormat("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function money(v: number): string {
  return `EUR ${eur.format(v)}`;
}

export function pct(v: number | null | undefined, digits = 1): string {
  return v === null || v === undefined ? "n/a" : `${(v * 100).toFixed(digits)}%`;
}

export function pctCI(c: CI | undefined, digits = 1): string {
  if (!c || c.mean === null) return "n/a";
  const m = (c.mean * 100).toFixed(digits);
  if (c.lo === null || c.hi === null) return `${m}%`;
  const lo = (c.lo * 100).toFixed(digits);
  const hi = (c.hi * 100).toFixed(digits);
  return lo === hi && lo === m ? `${m}%` : `${m}% [${lo}, ${hi}]`;
}

export function numCI(c: CI | undefined, digits = 1): string {
  if (!c || c.mean === null) return "n/a";
  const f = (x: number) => x.toLocaleString("en-GB", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  if (c.lo === null || c.hi === null) return f(c.mean);
  return `${f(c.mean)} [${f(c.lo)}, ${f(c.hi)}]`;
}

export function date(ts: string): string {
  return ts.slice(0, 10);
}

export function short(hash: string | null | undefined, n = 10): string {
  return hash ? hash.slice(0, n) : "–";
}

/** Compact one-line rendering of a recorded value. */
export function brief(v: unknown, max = 60): string {
  let s: string;
  if (v === null || v === undefined) s = "–";
  else if (typeof v === "number") s = Number.isInteger(v) ? String(v) : String(Number(v.toPrecision(8)));
  else if (typeof v === "string") s = v;
  else s = JSON.stringify(v);
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}
