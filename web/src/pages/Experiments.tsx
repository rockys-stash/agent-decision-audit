import { useSearchParams } from "react-router-dom";
import { IntervalRows, LineChart, TableTwin, type Series } from "../components/charts";
import { Empty, ErrorPanel, Glyph, Loading, Mark, PageHead, ProvenanceLine, Segmented } from "../components/ui";
import {
  api,
  useApi,
  type CI,
  type DecisionType,
  type ExperimentInfo,
  type OverheadSummary,
  type ReconRow,
  type ReconSummary,
  type Status,
  type TamperSummary,
  type ViolationSummary,
} from "../lib/api";
import { ATTACK_LABEL, DEFENSE_LABEL, EXPERIMENT_LABEL, LEVEL_LABEL, LEVELS, numCI, pct, pctCI, STATUS, TYPE_LABEL } from "../lib/format";

const EXPS = Object.keys(EXPERIMENT_LABEL);
const LEVEL_COLOR = ["var(--l0)", "var(--l1)", "var(--l2)", "var(--l3)", "var(--l4)"];
const TYPES = Object.keys(TYPE_LABEL) as DecisionType[];
const STATUS_ORDER: Status[] = ["reproduced", "attested", "unverifiable", "diverged", "not_reconstructable"];
const STATUS_FILL: Record<Status, string> = {
  reproduced: "var(--ok)",
  attested: "var(--attest)",
  unverifiable: "var(--ref)",
  diverged: "var(--bad)",
  not_reconstructable: "color-mix(in srgb, var(--bad) 45%, var(--surface))",
};

function row(s: ReconSummary, mode: string, delay: number, level: number, type = "all"): ReconRow | undefined {
  return s.rows.find((r) => r.mode === mode && r.delay === delay && r.level === level && r.type === type);
}

function StatusBar({ r }: { r: ReconRow }) {
  return (
    <div style={{ display: "flex", height: 12, borderRadius: 2, overflow: "hidden", gap: 2, minWidth: 120 }} aria-hidden="true">
      {STATUS_ORDER.map((s) => {
        const v = r[s].mean ?? 0;
        return v > 0 ? <span key={s} style={{ width: `${v * 100}%`, background: STATUS_FILL[s] }} title={`${STATUS[s].word} ${pct(v)}`} /> : null;
      })}
    </div>
  );
}

function StatusLegend() {
  return (
    <div className="legend">
      {STATUS_ORDER.map((s) => (
        <span className="key" key={s}>
          <span className="swatch" style={{ background: STATUS_FILL[s] }} />
          <Glyph glyph={STATUS[s].glyph} /> {STATUS[s].word}
        </span>
      ))}
    </div>
  );
}

function E1({ s }: { s: ReconSummary }) {
  const [params, setParams] = useSearchParams();
  const delay = s.rows[0]?.delay ?? 30;
  const level = Math.min(4, Math.max(0, Number(params.get("level") ?? 2) || 0));
  const rows = [...LEVELS.map((l) => row(s, "record", delay, l)), row(s, "live", delay, 4)].filter((r): r is ReconRow => !!r);
  const qs = Array.from(new Set(s.answers.map((a) => a.question)));
  return (
    <div className="stack">
      <section className="panel">
        <div className="panel-head">
          <h2>What an auditor can verify, by what the log kept</h2>
          <ProvenanceLine p={s.provenance} />
        </div>
        <div className="panel-body stack">
          <p className="secondary small" style={{ margin: 0 }}>
            {s.decisions.toLocaleString("en-GB")} decisions by the clean agent, each replayed {delay} days later from a record at every level. Means over seeds
            with 95% CIs. <em>Route match</em> compares the replay with what actually happened; <em>silent misreconstruction</em> is a replay the auditor
            would accept whose route is wrong.
          </p>
          <StatusLegend />
          <div className="table-wrap" tabIndex={0}>
            <table className="sticky-first">
              <thead>
                <tr>
                  <th scope="col">Record kept</th>
                  <th scope="col">Verification outcome</th>
                  {STATUS_ORDER.map((st) => (
                    <th key={st} scope="col" className="r">
                      {STATUS[st].word}
                    </th>
                  ))}
                  <th scope="col" className="r">
                    Route match
                  </th>
                  <th scope="col" className="r">
                    Silent misreconstruction
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={`${r.mode}${r.level}`}>
                    <th scope="row">{r.mode === "live" ? "Live re-query (L4 code)" : LEVEL_LABEL[r.level]}</th>
                    <td>
                      <StatusBar r={r} />
                    </td>
                    {STATUS_ORDER.map((st) => (
                      <td key={st} className="r">
                        {pct(r[st].mean)}
                      </td>
                    ))}
                    <td className="r">{pctCI(r.route_match)}</td>
                    <td className="r">{pctCI(r.silent_misreconstruction)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>
      <section className="panel">
        <div className="panel-head">
          <h2>Which decision types resist auditing</h2>
          <Segmented label="Level" options={LEVELS.map((l) => ({ id: l as number, label: `L${l}` }))} value={level} onChange={(v) => setParams({ exp: "e1_reconstruction", level: String(v) }, { replace: true })} />
        </div>
        <div className="panel-body grid two">
          <IntervalRows
            title={`Route match at ${LEVEL_LABEL[level]}`}
            better="higher"
            format={(v) => `${(v * 100).toFixed(1)}%`}
            rows={TYPES.map((t) => ({ key: t, label: `${TYPE_LABEL[t]} (${(s.decision_types[t] ?? 0).toLocaleString("en-GB")})`, color: LEVEL_COLOR[level] ?? "var(--accent)", stat: row(s, "record", delay, level, t)?.route_match }))}
          />
          <IntervalRows
            title="Attested only (not re-derivable) at L4"
            format={(v) => `${(v * 100).toFixed(1)}%`}
            rows={TYPES.map((t) => ({ key: t, label: TYPE_LABEL[t], color: "var(--attest)", stat: row(s, "record", delay, 4, t)?.attested }))}
          />
        </div>
        <div className="panel-body" style={{ paddingTop: 0 }}>
          <TableTwin
            caption="Route match by decision type and level"
            head={["Decision type", ...LEVELS.map((l) => `L${l}`), "L4 attested"]}
            rows={TYPES.map((t) => [TYPE_LABEL[t], ...LEVELS.map((l) => pctCI(row(s, "record", delay, l, t)?.route_match)), pctCI(row(s, "record", delay, 4, t)?.attested)])}
          />
        </div>
      </section>
      <section className="panel">
        <div className="panel-head">
          <h2>Audit questions answered correctly</h2>
        </div>
        <div className="table-wrap" tabIndex={0}>
          <table className="sticky-first">
            <thead>
              <tr>
                <th scope="col">Question</th>
                {LEVELS.map((l) => (
                  <th key={l} scope="col" className="r">
                    L{l}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {qs.map((q) => (
                <tr key={q}>
                  <th scope="row">{s.answers.find((a) => a.question === q)?.text}</th>
                  {LEVELS.map((l) => (
                    <td key={l} className="r">
                      {pct(s.answers.find((a) => a.question === q && a.level === l)?.correct.mean)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="panel-note">Answered from the record where the level holds the answer, otherwise from the replay; checked against the full original trace.</div>
      </section>
      <section className="panel">
        <div className="panel-head">
          <h2>Why re-querying live diverged (first divergent step)</h2>
        </div>
        <div className="table-wrap" tabIndex={0}>
          <table>
            <thead>
              <tr>
                <th scope="col">Cause</th>
                <th scope="col" className="r">
                  Decisions
                </th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(s.live_divergence)
                .sort((a, b) => b[1] - a[1])
                .map(([k, n]) => (
                  <tr key={k}>
                    <th scope="row" className="mono" style={{ fontWeight: 400, fontSize: 12.5 }}>
                      {k.split("|").slice(1).join("|")}
                    </th>
                    <td className="r">{n.toLocaleString("en-GB")}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function E2({ s }: { s: ReconSummary }) {
  const delays = Array.from(new Set(s.rows.map((r) => r.delay))).sort((a, b) => a - b);
  const mk = (metric: "route_match" | "silent_misreconstruction"): Series[] => [
    ...LEVELS.map((l) => ({
      key: `L${l}`,
      name: LEVEL_LABEL[l] ?? `L${l}`,
      color: LEVEL_COLOR[l] ?? "var(--accent)",
      points: delays.map((d, i) => {
        const c = row(s, "record", d, l)?.[metric];
        return { x: i, y: (c?.mean ?? 0) * 100, lo: c?.lo !== null && c?.lo !== undefined ? c.lo * 100 : null, hi: c?.hi !== null && c?.hi !== undefined ? c.hi * 100 : null };
      }),
    })),
    {
      key: "live",
      name: "Live re-query",
      color: "var(--ref)",
      dashed: true,
      points: delays.map((d, i) => ({ x: i, y: (row(s, "live", d, 4)?.[metric].mean ?? 0) * 100 })),
    },
  ];
  const fx = (i: number) => `${delays[Math.round(i)] ?? ""} d`;
  return (
    <div className="stack">
      <section className="panel">
        <div className="panel-head">
          <h2>Reconstruction as the audit happens later</h2>
          <ProvenanceLine p={s.provenance} />
        </div>
        <div className="panel-body grid two">
          <div>
            <h3 style={{ marginBottom: 8 }}>Route match (%)</h3>
            <LineChart series={mk("route_match")} xLabel="Days between decision and audit" yLabel="Route match (%)" formatX={fx} formatY={(v) => v.toFixed(0)} yDomain={[0, 100]} ariaLabel="Route match against audit delay, one line per level" />
          </div>
          <div>
            <h3 style={{ marginBottom: 8 }}>Silent misreconstruction (%)</h3>
            <LineChart series={mk("silent_misreconstruction")} xLabel="Days between decision and audit" yLabel="Accepted but wrong (%)" formatX={fx} formatY={(v) => v.toFixed(1)} ariaLabel="Silent misreconstruction against audit delay" legend={false} />
          </div>
        </div>
        <div className="panel-body" style={{ paddingTop: 0 }}>
          <TableTwin
            caption="Route match by level and delay"
            head={["Record kept", ...delays.map((d) => `${d} days`)]}
            rows={[
              ...LEVELS.map((l) => [LEVEL_LABEL[l] ?? "", ...delays.map((d) => pctCI(row(s, "record", d, l)?.route_match))]),
              ["Live re-query", ...delays.map((d) => pctCI(row(s, "live", d, 4)?.route_match))],
            ]}
          />
        </div>
        <div className="panel-note">L4 is flat at 100% by construction: the full environment is recorded, so nothing drifts. The lower levels lose route match as policies, claims, rates, models and the agent itself change.</div>
      </section>
    </div>
  );
}

function E3({ s }: { s: ViolationSummary }) {
  const lv = (det: string, metric: "recall_all" | "precision") =>
    LEVELS.map((l) => ({ key: `${det}${l}`, label: LEVEL_LABEL[l] ?? "", color: det === "rule" ? "var(--accent)" : "var(--ink-2)", stat: s.by_level.find((b) => b.level === l && b.detector === det)?.[metric] }));
  const cell = (r: ViolationSummary["by_type"][number], k: string) => {
    const c = r[k] as CI | undefined;
    return c && typeof c === "object" ? pct(c.mean) : "n/a";
  };
  return (
    <div className="stack">
      <section className="panel">
        <div className="panel-head">
          <h2>Automated detection by what the log kept</h2>
          <ProvenanceLine p={s.provenance} />
        </div>
        <div className="panel-body grid two">
          <IntervalRows title="Rule checks: recall, all violations" better="higher" format={(v) => `${(v * 100).toFixed(1)}%`} rows={lv("rule", "recall_all")} />
          <IntervalRows title="Rule checks: precision" better="higher" format={(v) => `${(v * 100).toFixed(1)}%`} rows={lv("rule", "precision")} />
          <IntervalRows title="Reference replay: recall, all violations" better="higher" format={(v) => `${(v * 100).toFixed(1)}%`} rows={lv("replay", "recall_all")} />
          <IntervalRows title="Reference replay: precision" better="higher" format={(v) => `${(v * 100).toFixed(1)}%`} rows={lv("replay", "precision")} />
        </div>
        <div className="panel-note">
          {s.decisions_faulty.toLocaleString("en-GB")} decisions by the faulty agent and {s.decisions_clean.toLocaleString("en-GB")} by the clean agent. Reference replay re-runs the approved code on
          the recorded inputs; below L4 it also flags ordinary drift, which is why its precision collapses.
        </div>
      </section>
      <section className="panel">
        <div className="panel-head">
          <h2>Recall by violation type</h2>
        </div>
        <div className="table-wrap" tabIndex={0}>
          <table className="sticky-first">
            <thead>
              <tr>
                <th scope="col">Violation</th>
                <th scope="col" className="r">
                  Injected
                </th>
                <th scope="col" className="r">
                  Rules L0
                </th>
                <th scope="col" className="r">
                  Rules L2
                </th>
                <th scope="col" className="r">
                  Rules L4
                </th>
                <th scope="col" className="r">
                  Replay L4
                </th>
                <th scope="col" className="r">
                  10% sample audit
                </th>
              </tr>
            </thead>
            <tbody>
              {s.by_type.map((r) => (
                <tr key={r.violation}>
                  <th scope="row" className="mono" style={{ fontWeight: 400, fontSize: 12.5 }}>
                    {r.violation}
                    {r.held_out && <span className="pill" style={{ marginLeft: 6, fontFamily: "var(--font)" }}>held out</span>}
                  </th>
                  <td className="r">{r.injected.toLocaleString("en-GB")}</td>
                  <td className="r">{cell(r, "rule_L0")}</td>
                  <td className="r">{cell(r, "rule_L2")}</td>
                  <td className="r">{cell(r, "rule_L4")}</td>
                  <td className="r">{cell(r, "replay_L4")}</td>
                  <td className="r">{cell(r, "sample_0.1")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function E4({ s }: { s: TamperSummary }) {
  const attacks = Array.from(new Set(s.rows.map((r) => r.attack)));
  const defenses = Array.from(new Set(s.rows.map((r) => r.defense)));
  const get = (a: string, d: string) => s.rows.find((r) => r.attack === a && r.defense === d);
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Which integrity layer catches which attack</h2>
        <ProvenanceLine p={s.provenance} />
      </div>
      <div className="table-wrap" tabIndex={0}>
        <table className="heat sticky-first">
          <thead>
            <tr>
              <th scope="col">Attack</th>
              {defenses.map((d) => (
                <th key={d} scope="col" className="r">
                  {DEFENSE_LABEL[d] ?? d}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {attacks.map((a) => (
              <tr key={a}>
                <th scope="row">{ATTACK_LABEL[a] ?? a}</th>
                {defenses.map((d) => {
                  const r = get(a, d);
                  const v = r?.detected ?? 0;
                  return (
                    <td key={d} className="cell" style={{ background: `color-mix(in srgb, var(--accent) ${Math.round(v * 12)}%, transparent)` }}>
                      {v >= 0.995 ? (
                        <Mark tone="ok" glyph="✓">
                          {pct(v, 0)}
                        </Mark>
                      ) : v <= 0.005 ? (
                        <Mark tone="bad" glyph="✕">
                          {pct(v, 0)}
                        </Mark>
                      ) : (
                        <Mark tone="attest" glyph="◐">
                          {pct(v, 0)}
                        </Mark>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="panel-note">
        Share of tampered logs rejected, over {s.rows[0]?.trials ?? 0} trials per cell ({s.events_per_log.length} logs of {Math.min(...s.events_per_log).toLocaleString("en-GB")}–
        {Math.max(...s.events_per_log).toLocaleString("en-GB")} events). Untampered logs verified as valid: {s.clean_logs_valid ? "all" : "not all"}. An attacker holding the
        signing key can only be caught by the external anchor, and only for events before the last anchor.
      </div>
    </section>
  );
}

const TIMING_LABEL: Record<string, string> = {
  uninstrumented: "Agent without instrumentation (ms per decision)",
  memory_log: "Recording to memory (ms per decision)",
  sqlite_log: "Recording to SQLite with checkpoints and anchors (ms per decision)",
  replay_record_L4_ms: "Record-mode L4 replay (ms per decision)",
  verify_chain_events_per_s: "Chain verification (events per second)",
  verify_all_events_per_s: "Chain, checkpoint and anchor verification (events per second)",
};

function E5({ s }: { s: OverheadSummary }) {
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Cost of instrumentation</h2>
        <ProvenanceLine p={s.provenance} />
      </div>
      <div className="grid two panel-body">
        <div className="table-wrap" tabIndex={0}>
          <table>
            <thead>
              <tr>
                <th scope="col">Measure</th>
                <th scope="col" className="r">
                  Value [95% CI]
                </th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(TIMING_LABEL).map(([k, label]) => (
                <tr key={k}>
                  <th scope="row">{label}</th>
                  <td className="r mono">{numCI(s.timings[k], k.includes("per_s") ? 0 : 2)}</td>
                </tr>
              ))}
              <tr>
                <th scope="row">Events per decision</th>
                <td className="r mono">{numCI(s.events_per_decision, 1)}</td>
              </tr>
              <tr>
                <th scope="row">SQLite bytes per decision</th>
                <td className="r mono">{numCI(s.sqlite_bytes_per_decision, 0)}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div className="table-wrap" tabIndex={0}>
          <table>
            <thead>
              <tr>
                <th scope="col">Record kept</th>
                <th scope="col" className="r">
                  Bytes per decision
                </th>
                <th scope="col" className="r">
                  With tool outputs stored once
                </th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(s.json_bytes_per_decision).map(([k, v]) => (
                <tr key={k}>
                  <th scope="row">{k}</th>
                  <td className="r mono">{numCI(v, 0)}</td>
                  <td className="r mono">{numCI(s.deduplicated_bytes_per_decision[k], 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="panel-note">
        Machine: {s.cpu}, {s.cpu_count} CPUs. Timings depend on the machine and are comparable only within this table.
      </div>
    </section>
  );
}

function Body({ exp }: { exp: string }) {
  const r = useApi<unknown>(api.experiment(exp));
  if (r.error?.status === 404)
    return (
      <div className="panel">
        <Empty title="Status: pending">
          No completed run of <code>{exp}</code>. Run <code>uv run agentaudit run configs/{exp}.yaml</code>.
        </Empty>
      </div>
    );
  if (r.error) return <ErrorPanel error={r.error} retry={r.retry} what={exp} />;
  if (!r.data || r.loading) return <Loading rows={8} label={`Loading ${exp}`} />;
  if (exp === "e1_reconstruction") return <E1 s={r.data as ReconSummary} />;
  if (exp === "e2_audit_delay") return <E2 s={r.data as ReconSummary} />;
  if (exp === "e3_violations") return <E3 s={r.data as ViolationSummary} />;
  if (exp === "e4_tamper") return <E4 s={r.data as TamperSummary} />;
  return <E5 s={r.data as OverheadSummary} />;
}

export function Experiments() {
  const [params, setParams] = useSearchParams();
  const list = useApi<ExperimentInfo[]>(api.experiments);
  const exp = EXPS.includes(params.get("exp") ?? "") ? (params.get("exp") as string) : "e1_reconstruction";
  return (
    <>
      <PageHead title="Lab notebook">
        Experiments E1 to E5, read from the latest completed run of each. All data come from the simulated claims world; every number shows the run and
        commit it came from.
      </PageHead>
      <div className="toolbar">
        <Segmented
          label="Experiment"
          options={EXPS.map((e) => {
            const st = list.data?.find((x) => x.experiment === e)?.status;
            return { id: e, label: `${EXPERIMENT_LABEL[e]}${st === "pending" ? " (pending)" : ""}` };
          })}
          value={exp}
          onChange={(v) => setParams({ exp: v })}
        />
      </div>
      <Body key={exp} exp={exp} />
    </>
  );
}
