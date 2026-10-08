import { useCallback, useEffect, useRef, useState } from "react";

/* ---------- types mirrored from the API (src/agentaudit/api/app.py) ---------- */
export type Status = "reproduced" | "attested" | "unverifiable" | "diverged" | "not_reconstructable";
export type DecisionType = "rule" | "calculation" | "fx" | "model" | "stochastic" | "opaque" | "human";

export interface Meta {
  deployment: {
    seed?: number;
    n_claims?: number;
    variant?: string;
    attempt_rate?: number;
    checkpoint_every?: number;
    anchor_every?: number;
    standard?: string;
    standard_version?: string;
  };
  events: number;
  decisions: number;
  head: string | null;
  checkpoints: number;
  anchors: number;
  levels: Record<string, string>;
  kind_levels: Record<string, number>;
  field_levels: { kind: string; field: string; level: number }[];
  standard: { id: string; version: string };
}

export interface CaseSummary {
  decision_id: string;
  claim_id: string;
  ts: string;
  decision: string;
  amount: number;
  decided_by: string;
  steps: number;
  findings: number;
  simulation_truth: { decision_type: DecisionType | null; violation: string | null };
}

export interface CaseList {
  total: number;
  items: CaseSummary[];
}

export interface TraceEvent {
  seq: number;
  prev_hash: string;
  hash: string;
  step: number;
  kind: string;
  name: string;
  ts: string;
  data: Record<string, unknown>;
  level: number;
  field_levels: Record<string, number>;
}

export interface StepCheck {
  step: number;
  kind: string;
  name: string;
  status: "match" | "mismatch" | "missing" | "extra";
  detail: string;
}

export interface Finding {
  check: string;
  step: number | null;
  message: string;
  targets: string[];
}

export interface CaseDetail {
  decision_id: string;
  events: TraceEvent[];
  findings: Finding[];
  recomputation: StepCheck[];
  simulation_truth: { decision_type: DecisionType; violation: string | null; fraud: boolean } | null;
}

export interface ReplayStep {
  step: number;
  kind: string;
  name: string;
  data: Record<string, unknown>;
}

export interface Replay {
  decision_id: string;
  level: number;
  mode: "record" | "live";
  audit_day: number;
  status: Status;
  final_match: boolean;
  first_divergence: number | null;
  divergence: string | null;
  unrecorded_inputs: string[];
  attested: string[];
  error: string | null;
  checks: StepCheck[];
  recorded: ReplayStep[];
  replayed: ReplayStep[];
  answers: { question: string; text: string; answer: string }[];
  code: "deployed" | "approved";
}

export interface ViolationsView {
  checks: { check: string; targets: string[]; findings: number }[];
  items: { decision_id: string; check: string; step: number | null; message: string; targets: string[]; simulation_truth: string | null }[];
  injected: Record<string, number>;
}

export interface VerifyReport {
  valid: boolean;
  events: number;
  first_bad_seq: number | null;
  problems: string[];
  checkpoints_checked: number;
  anchors_checked: number;
}

export interface Integrity extends VerifyReport {
  head_seq: number;
  head: string | null;
  last_checkpoint: number | null;
  anchors: { seq: number; head: string }[];
  checkpoint_every: number;
  anchor_every: number | null;
  verified_seconds_ago: number;
}

export interface TamperResult {
  attack: string;
  target_seq: number;
  events_after: number;
  results: (VerifyReport & { defense: string })[];
}

export interface Standard {
  id: string;
  version: string;
  checks: { check: string; targets: string[] }[];
  [key: string]: unknown;
}

export interface CI {
  mean: number | null;
  lo: number | null;
  hi: number | null;
  n: number;
  k?: number;
}

export interface Provenance {
  experiment: string;
  description: string;
  kind: string;
  run_id: string;
  created_at: string;
  commit: string;
  base_seed: number;
  seeds: number;
  n_claims: number;
  runtime_seconds: number;
}

export interface ExperimentInfo extends Partial<Provenance> {
  experiment: string;
  status: "pending" | "complete";
}

export interface ReconRow {
  mode: "record" | "live";
  delay: number;
  level: number;
  type: string;
  n: number;
  reproduced: CI;
  attested: CI;
  unverifiable: CI;
  diverged: CI;
  not_reconstructable: CI;
  route_match: CI;
  silent_misreconstruction: CI;
  fully_reconstructed: CI;
}

export interface ReconSummary {
  rows: ReconRow[];
  answers: { level: number; question: string; text: string; correct: CI; record: number; replay_correct: number; replay_wrong: number; unanswerable: number; record_wrong: number }[];
  live_divergence: Record<string, number>;
  record_divergence?: Record<string, number>;
  decision_types: Record<string, number>;
  decisions: number;
  provenance: Provenance;
}

export interface ViolationSummary {
  by_type: ({ violation: string; held_out: boolean; injected: number } & Record<string, CI | string | boolean | number>)[];
  by_level: { level: number; detector: "rule" | "replay"; recall_all: CI; recall_designed: CI; precision: CI; clean_fp_per_1000: CI; flagged_live_only: number | null }[];
  checks: { level: number; check: string; targets: string[]; findings: number; on_target: number; on_clean_agent: number; evaluable: number }[];
  decisions_faulty: number;
  decisions_clean: number;
  provenance: Provenance;
}

export interface TamperSummary {
  rows: { attack: string; defense: string; trials: number; detected: number; localised: number | null; localised_within_checkpoint: number | null; after_last_anchor: number; detected_after_last_anchor: number }[];
  events_per_log: number[];
  clean_logs_valid: boolean;
  anchors_per_log: number[];
  provenance: Provenance;
}

export interface OverheadSummary {
  timings: Record<string, CI>;
  json_bytes_per_decision: Record<string, CI>;
  deduplicated_bytes_per_decision: Record<string, CI>;
  sqlite_bytes_per_decision: CI;
  events_per_decision: CI;
  cpu: string;
  cpu_count: number;
  provenance: Provenance;
}

/* ---------- fetching ---------- */
export class ApiError extends Error {
  constructor(
    public url: string,
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

const cache = new Map<string, unknown>();
// Everything except integrity is immutable for a deployment; replays are deterministic.
const UNCACHED = /^\/api\/integrity/;

async function errorFrom(url: string, res: Response): Promise<ApiError> {
  let detail = res.statusText;
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === "string") detail = body.detail;
    else if (Array.isArray(body.detail)) detail = body.detail.map((d: { msg?: string }) => d.msg ?? "invalid input").join("; ");
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(url, res.status, detail);
}

export async function getJson<T>(url: string): Promise<T> {
  if (cache.has(url)) return cache.get(url) as T;
  let res: Response;
  try {
    res = await fetch(url, { headers: { Accept: "application/json" } });
  } catch {
    throw new ApiError(url, 0, "The audit API could not be reached.");
  }
  if (!res.ok) throw await errorFrom(url, res);
  const data = (await res.json()) as T;
  if (!UNCACHED.test(url)) cache.set(url, data);
  return data;
}

export async function postJson<T>(url: string, body: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError(url, 0, "The audit API could not be reached.");
  }
  if (!res.ok) throw await errorFrom(url, res);
  return (await res.json()) as T;
}

export interface ApiState<T> {
  data: T | undefined;
  error: ApiError | undefined;
  loading: boolean;
  retry: () => void;
}

/** Fetches JSON for ``url``; keeps the previous data while a new URL loads. */
export function useApi<T>(url: string | null): ApiState<T> {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<ApiError | undefined>(undefined);
  const [loading, setLoading] = useState<boolean>(url !== null);
  const [nonce, setNonce] = useState(0);
  const current = useRef(url);

  useEffect(() => {
    current.current = url;
    if (url === null) {
      setLoading(false);
      return;
    }
    let alive = true;
    setLoading(true);
    setError(undefined);
    getJson<T>(url)
      .then((d) => {
        if (alive && current.current === url) setData(d);
      })
      .catch((e: unknown) => {
        if (alive && current.current === url) setError(e instanceof ApiError ? e : new ApiError(url, 0, String(e)));
      })
      .finally(() => {
        if (alive && current.current === url) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [url, nonce]);

  const retry = useCallback(() => {
    if (url) cache.delete(url);
    setNonce((n) => n + 1);
  }, [url]);

  return { data, error, loading, retry };
}

const q = (params: Record<string, string | number | undefined>) =>
  new URLSearchParams(Object.entries(params).filter((e): e is [string, string | number] => e[1] !== undefined && e[1] !== "").map(([k, v]) => [k, String(v)])).toString();

export const api = {
  meta: "/api/meta",
  cases: (params: Record<string, string | number | undefined>) => `/api/cases?${q(params)}`,
  case: (id: string) => `/api/cases/${encodeURIComponent(id)}`,
  replay: (id: string, params: Record<string, string | number>) => `/api/cases/${encodeURIComponent(id)}/replay?${q(params)}`,
  violations: "/api/violations",
  integrity: "/api/integrity",
  tamperLab: "/api/integrity/tamper-lab",
  standard: "/api/standard",
  experiments: "/api/experiments",
  experiment: (exp: string) => `/api/experiments/${encodeURIComponent(exp)}`,
};
