import { useCallback, useEffect, useMemo, useRef } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Empty, ErrorPanel, Hash, Loading, Mark, Segmented, StatusMark, Truth } from "../components/ui";
import { api, useApi, type CaseDetail, type Meta, type Replay, type ReplayStep, type StepCheck, type TraceEvent } from "../lib/api";
import { brief, date, KIND_LABEL, LEVEL_HELP, LEVEL_LABEL, LEVELS, money, STATUS, TYPE_LABEL } from "../lib/format";

const DELAYS = [0, 7, 30, 90, 180];
// Per-call identifiers that a replay cannot and need not reproduce (schema.VOLATILE_FIELDS).
const VOLATILE = new Set(["request_id", "wall_ms"]);

interface StepView {
  index: number;
  event: TraceEvent;
  recorded: boolean; // present in the record at the chosen level
  check?: StepCheck;
  replayed?: ReplayStep;
  findings: CaseDetail["findings"];
}

function answerTone(a: string): { tone: "ok" | "attest" | "bad" | "neutral"; glyph: string; word: string } {
  switch (a) {
    case "record":
      return { tone: "ok", glyph: "✓", word: "From the record" };
    case "replay_correct":
      return { tone: "attest", glyph: "◐", word: "From the replay, correct" };
    case "replay_wrong":
      return { tone: "bad", glyph: "✕", word: "From the replay, wrong" };
    case "record_wrong":
      return { tone: "bad", glyph: "✕", word: "Record is wrong" };
    default:
      return { tone: "neutral", glyph: "∅", word: "Cannot be answered" };
  }
}

/** The decision's state after each step: what a debugger's watch panel would show. */
function watchState(events: TraceEvent[], upto: number, level: number): { key: string; value: string; step: number }[] {
  const state = new Map<string, { value: string; step: number }>();
  events.slice(0, upto + 1).forEach((e, i) => {
    if (e.level > level) return;
    const d = Object.fromEntries(Object.entries(e.data).filter(([k]) => (e.field_levels[k] ?? e.level) <= level));
    const put = (k: string, v: unknown) => state.set(k, { value: brief(v, 28), step: i });
    if (e.kind === "config") put("agent version", d.version);
    else if (e.kind === "calc") put(e.name, d.value);
    else if (e.kind === "rule") put(e.name, d.passed ? "pass" : "fail");
    else if (e.kind === "model") put(`model ${e.name}`, d.score);
    else if (e.kind === "external") put(e.name, (d.output as { score?: unknown } | undefined)?.score);
    else if (e.kind === "rng") put(`draw ${e.name}`, d.value);
    else if (e.kind === "intermediate") put(e.name, d.value);
    else if (e.kind === "confidence") put("confidence", d.value);
    else if (e.kind === "human") put("adjuster", d.decision);
    else if (e.kind === "final") put("final", `${String(d.decision)} ${brief(d.amount)}`);
    else if (e.kind === "outcome") put("outcome", d.outcome);
  });
  return [...state.entries()].map(([key, v]) => ({ key, ...v }));
}

function CheckMark({ view, level }: { view: StepView; level: number }) {
  if (view.event.kind === "outcome") return <span className="muted small">after</span>;
  if (!view.recorded)
    return (
      <span className="muted small" title={`Not recorded at ${LEVEL_LABEL[level]}`}>
        <span aria-hidden="true">–</span>
        <span className="sr-only">not recorded</span>
      </span>
    );
  if (!view.check) return <span className="muted small">·</span>;
  return view.check.status === "match" ? (
    <Mark tone="ok" glyph="✓">
      <span className="sr-only">matched</span>
    </Mark>
  ) : (
    <Mark tone="bad" glyph="✕">
      <span className="sr-only">{view.check.status}</span>
    </Mark>
  );
}

function DataTable({ event, level, replayed }: { event: TraceEvent; level: number; replayed?: ReplayStep }) {
  const keys = Object.keys(event.data);
  return (
    <div className="table-wrap" tabIndex={0}>
      <table>
        <thead>
          <tr>
            <th scope="col">Field</th>
            <th scope="col">Recorded</th>
            {replayed && <th scope="col">Replayed</th>}
            <th scope="col">Recorded from</th>
          </tr>
        </thead>
        <tbody>
          {keys.map((k) => {
            const fl = event.field_levels[k] ?? event.level;
            const hidden = fl > level;
            const rec = event.data[k];
            const rep = replayed?.data[k];
            const changed = replayed !== undefined && !hidden && !VOLATILE.has(k) && JSON.stringify(rec) !== JSON.stringify(rep);
            return (
              <tr key={k} className={`diff-row${changed ? " changed" : ""}`}>
                <th scope="row" style={{ fontFamily: "var(--mono)", fontSize: 12, fontWeight: 400 }}>
                  {k}
                </th>
                <td className={hidden ? "muted" : ""}>{hidden ? `not recorded at ${LEVEL_LABEL[level]?.split(" ")[0]}` : brief(rec, 140)}</td>
                {replayed && (
                  <td>
                    {hidden ? "–" : brief(rep, 140)}
                    {changed && <span className="sr-only"> (differs)</span>}
                  </td>
                )}
                <td>
                  <span className="level-chip">L{fl}</span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function CaseReplay() {
  const { caseId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const level = Math.min(4, Math.max(0, Number(params.get("level") ?? 4) || 0));
  const mode = params.get("mode") === "live" ? "live" : "record";
  const delayRaw = Number(params.get("delay") ?? 30);
  const delay = DELAYS.includes(delayRaw) ? delayRaw : 30;
  const code = params.get("code") === "approved" ? "approved" : "deployed";

  const meta = useApi<Meta>(api.meta);
  const detail = useApi<CaseDetail>(api.case(caseId));
  const replay = useApi<Replay>(api.replay(caseId, { level, mode, delay, code }));

  const set = useCallback(
    (updates: Record<string, string | number | null>) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [k, v] of Object.entries(updates)) {
            if (v === null) next.delete(k);
            else next.set(k, String(v));
          }
          return next;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  const steps: StepView[] = useMemo(() => {
    const dd = detail.data;
    if (!dd) return [];
    const r = replay.data;
    const byStep = new Map<number, { check?: StepCheck; replayed?: ReplayStep }>();
    if (r) r.recorded.forEach((rec, i) => byStep.set(rec.step, { check: r.checks[i], replayed: r.replayed[i] }));
    const recordedSteps = new Set(r?.recorded.map((x) => x.step));
    return dd.events.map((e, index) => ({
      index,
      event: e,
      recorded: e.kind === "outcome" ? e.level <= level : r ? recordedSteps.has(e.step) : e.level <= level,
      check: byStep.get(e.step)?.check,
      replayed: byStep.get(e.step)?.replayed,
      findings: dd.findings.filter((f) => f.step === e.step && e.kind !== "outcome"),
    }));
  }, [detail.data, replay.data, level]);

  const n = steps.length;
  const current = Math.min(Math.max(0, Number(params.get("step") ?? 0) || 0), Math.max(0, n - 1));
  const stepRef = useRef(current);
  stepRef.current = current;
  const clamp = useCallback((i: number) => Math.min(Math.max(0, i), Math.max(0, n - 1)), [n]);
  const go = useCallback(
    (i: number) => {
      stepRef.current = clamp(i);
      set({ step: stepRef.current });
    },
    [set, clamp],
  );
  // Relative moves start from the step last requested, so fast key repeats before the next
  // render do not reuse a stale value.
  const move = useCallback(
    (delta: number) => {
      stepRef.current = clamp(stepRef.current + delta);
      set({ step: stepRef.current });
    },
    [set, clamp],
  );

  const firstDivergence = useMemo(() => {
    const r = replay.data;
    if (!r || r.first_divergence === null) return null;
    const rec = r.recorded[r.first_divergence];
    if (rec) return steps.findIndex((s) => s.event.step === rec.step);
    const human = steps.findIndex((s) => s.event.kind === "human");
    return human >= 0 ? human : steps.length - 1;
  }, [replay.data, steps]);

  const nextViolation = useCallback(() => {
    const idx = steps.findIndex((s, i) => i > current && s.findings.length > 0);
    const wrap = steps.findIndex((s) => s.findings.length > 0);
    return idx >= 0 ? idx : wrap;
  }, [steps, current]);

  const timelineRef = useRef<HTMLOListElement>(null);
  useEffect(() => {
    timelineRef.current?.querySelector<HTMLElement>(`[data-index="${current}"]`)?.scrollIntoView({ block: "nearest" });
  }, [current]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA")) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "n" || e.key === "j") move(1);
      else if (e.key === "p" || e.key === "k") move(-1);
      else if (e.key === "f" && firstDivergence !== null) go(firstDivergence);
      else if (e.key === "v") {
        const v = nextViolation();
        if (v >= 0) go(v);
      } else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, move, firstDivergence, nextViolation]);

  if (detail.error) {
    return (
      <>
        <p>
          <Link to="/cases">All cases</Link>
        </p>
        <ErrorPanel error={detail.error} retry={detail.retry} what={`case ${caseId}`} />
      </>
    );
  }
  if (!detail.data) return <Loading rows={12} label="Loading case" />;

  const d = detail.data;
  const final = d.events.find((e) => e.kind === "final");
  const view = steps[current];
  const watch = watchState(d.events, current, level);
  const r = replay.data;
  const faulty = meta.data?.deployment.variant === "faulty";

  return (
    <>
      <p style={{ marginBottom: 6 }}>
        <Link to="/cases">All cases</Link>
      </p>
      <div className="page-head">
        <div>
          <h1>
            <span className="mono" style={{ fontSize: 19 }}>
              {d.decision_id.split(":")[1]}
            </span>
          </h1>
          <p>
            {final ? (
              <>
                {String(final.data.decision)} {money(Number(final.data.amount))} · decided by {final.data.decided_by === "human" ? "an adjuster" : "the agent"} ·{" "}
                {date(final.ts)} · {d.events.length} recorded steps
              </>
            ) : (
              "No final decision recorded"
            )}
          </p>
        </div>
      </div>

      <div className="panel" style={{ marginBottom: 16 }}>
        <div className="panel-body toolbar" style={{ marginBottom: 0 }}>
          <div className="field" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span className="small secondary" id="lvl-label">
              What the log kept
            </span>
            <Segmented
              label="Instrumentation level"
              options={LEVELS.map((l) => ({ id: l as number, label: `L${l}`, title: `${LEVEL_LABEL[l]}: ${LEVEL_HELP[l]}` }))}
              value={level}
              onChange={(v) => set({ level: v })}
            />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span className="small secondary">Inputs for the replay</span>
            <Segmented
              label="Replay mode"
              options={[
                { id: "record", label: "From the record", title: "Serve recorded inputs; look up only what the record lacks" },
                { id: "live", label: "Re-query live", title: "Look every input up again on the audit day" },
              ]}
              value={mode}
              onChange={(v) => set({ mode: v })}
            />
          </div>
          <label className="field">
            Audit after
            <select value={delay} onChange={(e) => set({ delay: e.target.value })}>
              {DELAYS.map((x) => (
                <option key={x} value={x}>
                  {x} days
                </option>
              ))}
            </select>
          </label>
          {faulty && (
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <span className="small secondary">Code replayed</span>
              <Segmented
                label="Agent code to replay"
                options={[
                  { id: "deployed", label: "Deployed", title: "The code that made the decision" },
                  { id: "approved", label: "Approved reference", title: "The approved clean agent: divergence means the deployed code deviated" },
                ]}
                value={code}
                onChange={(v) => set({ code: v })}
              />
            </div>
          )}
          <span className="muted small hide-mobile" style={{ marginLeft: "auto" }}>
            <span className="kbd">n</span>/<span className="kbd">p</span> step · <span className="kbd">f</span> first divergence · <span className="kbd">v</span> next
            finding
          </span>
        </div>
        <div className="panel-note" aria-live="polite">
          {replay.error ? (
            <span role="alert">Replay failed: {replay.error.message}</span>
          ) : !r || replay.loading ? (
            <span>Replaying at {LEVEL_LABEL[level]}…</span>
          ) : (
            <span style={{ display: "flex", gap: "4px 14px", flexWrap: "wrap", alignItems: "center" }}>
              <StatusMark status={r.status} />
              <span className="secondary">{STATUS[r.status].help}</span>
              {r.divergence && (
                <span>
                  First divergence: <span className="mono">{r.divergence}</span>{" "}
                  {firstDivergence !== null && (
                    <button className="btn ghost" type="button" onClick={() => go(firstDivergence)} style={{ minHeight: 26, padding: "0 8px" }}>
                      Go to step
                    </button>
                  )}
                </span>
              )}
              {r.unrecorded_inputs.length > 0 && <span>Looked up on the audit day: {r.unrecorded_inputs.join(", ")}</span>}
              {r.attested.length > 0 && <span>Taken from the record only: {[...new Set(r.attested)].join(", ")}</span>}
            </span>
          )}
        </div>
      </div>

      <div className="scrubber panel" style={{ padding: 10, marginBottom: 12 }}>
        <button className="btn" type="button" onClick={() => go(current - 1)} aria-label="Previous step" disabled={current === 0}>
          ‹
        </button>
        <label className="sr-only" htmlFor="scrub">
          Step
        </label>
        <input id="scrub" type="range" min={0} max={Math.max(0, n - 1)} value={current} onChange={(e) => go(Number(e.target.value))} />
        <span className="mono small">
          {current + 1}/{n}
        </span>
        <button className="btn" type="button" onClick={() => go(current + 1)} aria-label="Next step" disabled={current >= n - 1}>
          ›
        </button>
      </div>

      <div className="replay">
        <section className="panel timeline-pane" aria-label="Steps">
          <div className="panel-head">
            <h2>Steps</h2>
            <span className="muted small">{steps.filter((s) => s.recorded).length} kept at L{level}</span>
          </div>
          <ol className="timeline" ref={timelineRef}>
            {steps.map((s) => (
              <li key={s.index}>
                <button
                  type="button"
                  data-index={s.index}
                  aria-current={s.index === current ? "step" : undefined}
                  className={s.recorded ? "" : "hidden-at-level"}
                  onClick={() => go(s.index)}
                >
                  <span className="idx">{s.index + 1}</span>
                  <span className="label">
                    <span className="kind">{KIND_LABEL[s.event.kind] ?? s.event.kind}</span>
                    {s.event.name}
                    {!s.recorded && <span className="sr-only"> (not recorded at this level)</span>}
                  </span>
                  <span style={{ display: "inline-flex", gap: 4 }}>
                    {s.findings.length > 0 && (
                      <Mark tone="bad" glyph="▲">
                        <span className="sr-only">finding</span>
                      </Mark>
                    )}
                    <CheckMark view={s} level={level} />
                  </span>
                </button>
              </li>
            ))}
          </ol>
        </section>

        <section className="panel" aria-label="Step inspector">
          {!view ? (
            <Empty title="This case has no steps" />
          ) : (
            <>
              <div className="panel-head inspector-head">
                <h2>
                  <span className="muted mono" style={{ fontWeight: 400, fontSize: 13 }}>
                    {view.index + 1}. {KIND_LABEL[view.event.kind] ?? view.event.kind}
                  </span>{" "}
                  <span className="mono">{view.event.name}</span>
                </h2>
                <span className="small" style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
                  <span className="level-chip">recorded from L{view.event.level}</span>
                  {view.event.kind === "outcome" ? (
                    <span className="muted">appended when the outcome became known</span>
                  ) : !view.recorded ? (
                    <span className="muted">not in the record at L{level}</span>
                  ) : view.check ? (
                    view.check.status === "match" ? (
                      <Mark tone="ok" glyph="✓">
                        Replay matched
                      </Mark>
                    ) : (
                      <Mark tone="bad" glyph="✕">
                        Replay {view.check.status === "mismatch" ? "differs" : view.check.status}
                      </Mark>
                    )
                  ) : null}
                </span>
              </div>
              <div className="panel-body stack">
                {view.findings.map((f, i) => (
                  <div className="finding" key={i}>
                    <Mark tone="bad" glyph="▲">
                      {f.check}
                    </Mark>{" "}
                    {f.message}
                  </div>
                ))}
                {view.check && view.check.status !== "match" && view.check.detail && (
                  <p className="secondary" style={{ margin: 0 }}>
                    {view.check.detail}
                  </p>
                )}
                {(view.event.kind === "calc" || view.event.kind === "rule") && typeof view.event.data.expr === "string" && (
                  <Expression event={view.event} recomputation={d.recomputation.find((c) => c.step === view.event.step)} />
                )}
                <DataTable event={view.event} level={level} replayed={view.recorded ? view.replayed : undefined} />
                <dl className="kv">
                  <dt>Log position</dt>
                  <dd className="mono">seq {view.event.seq}</dd>
                  <dt>Recorded at</dt>
                  <dd className="mono">{view.event.ts}</dd>
                  <dt>Previous hash</dt>
                  <dd>
                    <Hash value={view.event.prev_hash} n={16} />
                  </dd>
                  <dt>This event&apos;s hash</dt>
                  <dd>
                    <Hash value={view.event.hash} n={16} />
                  </dd>
                </dl>
              </div>
            </>
          )}
        </section>

        <aside className="stack watch-pane" aria-label="Watch and questions">
          <section className="panel watch">
            <div className="panel-head">
              <h2>Watch</h2>
              <span className="muted small">
                after step {current + 1}, as kept at L{level}
              </span>
            </div>
            <div className="panel-body">
              {watch.length === 0 ? (
                <p className="muted small">No state yet.</p>
              ) : (
                <dl>
                  {watch.map((w) => (
                    <div key={w.key} style={{ display: "contents" }}>
                      <dt className={w.step === current ? "changed" : ""} title={w.key}>
                        {w.key}
                      </dt>
                      <dd className={w.step === current ? "changed" : ""}>{w.value}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </div>
          </section>
          <section className="panel">
            <div className="panel-head">
              <h2>Audit questions at L{level}</h2>
            </div>
            <div className="panel-body">
              {!r ? (
                <p className="muted small">Waiting for the replay…</p>
              ) : (
                <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 8 }}>
                  {r.answers.map((a) => {
                    const t = answerTone(a.answer);
                    return (
                      <li key={a.question} className="small">
                        <div>{a.text}</div>
                        <Mark tone={t.tone} glyph={t.glyph}>
                          {t.word}
                        </Mark>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
            <div className="panel-note">Checked against the complete original trace.</div>
          </section>
          {d.simulation_truth && (
            <Truth>
              Decision type: {TYPE_LABEL[d.simulation_truth.decision_type]}. Injected violation: <span className="mono">{d.simulation_truth.violation ?? "none"}</span>.
              Fraudulent claim: {d.simulation_truth.fraud ? "yes" : "no"}.
            </Truth>
          )}
        </aside>
      </div>
    </>
  );
}

function Expression({ event, recomputation }: { event: TraceEvent; recomputation?: StepCheck }) {
  const operands = (event.kind === "calc" ? event.data.operands : event.data.inputs) as Record<string, unknown> | undefined;
  const result = event.kind === "calc" ? event.data.value : event.data.passed;
  return (
    <div>
      <div className="expr">
        {String(event.data.expr)}
        {"  →  "}
        <strong>{brief(result)}</strong>
      </div>
      {operands && Object.keys(operands).length > 0 && (
        <p className="small secondary" style={{ margin: "6px 0 0" }}>
          {Object.entries(operands).map(([k, v], i) => (
            <span key={k}>
              {i > 0 && " · "}
              <span className="mono">{k}</span> = <span className="mono">{brief(v, 40)}</span>
            </span>
          ))}
        </p>
      )}
      {recomputation && (
        <p className="small" style={{ margin: "6px 0 0" }}>
          {recomputation.status === "match" ? (
            <Mark tone="ok" glyph="✓">
              Recomputed from its own operands: same result
            </Mark>
          ) : (
            <Mark tone="bad" glyph="✕">
              {recomputation.detail}
            </Mark>
          )}
        </p>
      )}
    </div>
  );
}
