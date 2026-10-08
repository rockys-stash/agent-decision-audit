import { Link, useSearchParams } from "react-router-dom";
import { Empty, ErrorPanel, Loading, Mark, PageHead } from "../components/ui";
import { api, useApi, type ViolationsView } from "../lib/api";

export function Violations() {
  const v = useApi<ViolationsView>(api.violations);
  const [params, setParams] = useSearchParams();
  const check = params.get("check") ?? "";

  if (v.error) return <ErrorPanel error={v.error} retry={v.retry} what="violations" />;
  if (!v.data) return <Loading rows={8} label="Loading findings" />;
  const items = check ? v.data.items.filter((i) => i.check === check) : v.data.items;
  const totalInjected = Object.values(v.data.injected).reduce((a, b) => a + b, 0);
  const onTarget = (i: ViolationsView["items"][number]) => i.simulation_truth !== null && i.targets.includes(i.simulation_truth);

  return (
    <>
      <PageHead title="Incident board">
        Findings of the audit standard&apos;s automated checks, run over every stored trace (level L4) when the deployment was recorded. Each finding
        links to the step that triggered it. The column on the right compares the finding with what the simulation actually injected.
      </PageHead>
      <div className="grid two" style={{ marginBottom: 16 }}>
        <section className="panel">
          <div className="panel-head">
            <h2>Findings by check</h2>
            <span className="muted small">{v.data.items.length.toLocaleString("en-GB")} findings</span>
          </div>
          <div className="table-wrap" tabIndex={0}>
            <table>
              <thead>
                <tr>
                  <th scope="col">Check</th>
                  <th scope="col">Looks for</th>
                  <th scope="col" className="r">
                    Findings
                  </th>
                </tr>
              </thead>
              <tbody>
                {v.data.checks.map((c) => (
                  <tr key={c.check}>
                    <th scope="row">
                      <button
                        type="button"
                        className="btn ghost"
                        style={{ minHeight: 26, padding: "0 6px", fontFamily: "var(--mono)", fontSize: 12.5 }}
                        aria-pressed={check === c.check}
                        onClick={() => setParams(check === c.check ? {} : { check: c.check }, { replace: true })}
                      >
                        {c.check}
                      </button>
                    </th>
                    <td className="small secondary">{c.targets.join(", ") || "any recomputation mismatch"}</td>
                    <td className="r">{c.findings}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="panel-note">Select a check to filter the findings below.</div>
        </section>
        <section className="panel">
          <div className="panel-head">
            <h2>What was injected (simulation ground truth)</h2>
            <span className="muted small">{totalInjected} decisions</span>
          </div>
          <div className="table-wrap" tabIndex={0}>
            <table>
              <thead>
                <tr>
                  <th scope="col">Violation</th>
                  <th scope="col" className="r">
                    Decisions
                  </th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(v.data.injected)
                  .sort((a, b) => b[1] - a[1])
                  .map(([k, n]) => (
                    <tr key={k}>
                      <th scope="row" className="mono" style={{ fontWeight: 400, fontSize: 12.5 }}>
                        {k}
                      </th>
                      <td className="r">{n}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
          <div className="panel-note">
            The two held-out kinds (rate_operand_mismatch, evidence_substitution) have no check written for them; see experiment E3 for how often other
            checks and reference replay catch them.
          </div>
        </section>
      </div>
      <section className="panel">
        <div className="panel-head">
          <h2>{check ? `Findings of ${check}` : "All findings"}</h2>
          <span className="muted small">{items.length} shown</span>
        </div>
        {items.length === 0 ? (
          <Empty title="No findings for this check">It did not fire on any decision in this deployment.</Empty>
        ) : (
          <div className="table-wrap" tabIndex={0} style={{ maxHeight: 560 }}>
            <table className="sticky-first">
              <thead>
                <tr>
                  <th scope="col">Claim</th>
                  <th scope="col">Check</th>
                  <th scope="col">Finding</th>
                  <th scope="col">Ground truth</th>
                </tr>
              </thead>
              <tbody>
                {items.slice(0, 400).map((i, k) => (
                  <tr key={`${i.decision_id}-${i.check}-${k}`}>
                    <th scope="row">
                      <Link className="mono" to={`/cases/${encodeURIComponent(i.decision_id)}${i.step !== null ? `?step=${i.step}` : ""}`}>
                        {i.decision_id.split(":")[1]}
                      </Link>
                    </th>
                    <td className="mono small">{i.check}</td>
                    <td className="small">{i.message}</td>
                    <td className="small">
                      {onTarget(i) ? (
                        <Mark tone="ok" glyph="✓">
                          {i.simulation_truth}
                        </Mark>
                      ) : i.simulation_truth ? (
                        <Mark tone="attest" glyph="◐" title="A violation was injected, but not the kind this check targets">
                          other: {i.simulation_truth}
                        </Mark>
                      ) : (
                        <Mark tone="bad" glyph="✕">
                          none injected
                        </Mark>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {items.length > 400 && <div className="panel-note">Showing the first 400 findings.</div>}
      </section>
    </>
  );
}
