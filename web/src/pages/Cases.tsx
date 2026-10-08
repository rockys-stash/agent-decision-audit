import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Empty, ErrorPanel, Loading, Mark, PageHead } from "../components/ui";
import { api, useApi, type CaseList, type DecisionType } from "../lib/api";
import { date, money, TYPE_LABEL } from "../lib/format";

const PAGE = 50;

export function Cases() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const decision = params.get("decision") ?? "";
  const decidedBy = params.get("decided_by") ?? "";
  const flagged = params.get("flagged") ?? "";
  const dtype = params.get("decision_type") ?? "";
  const search = params.get("search") ?? "";
  const page = Math.max(0, Number(params.get("page") ?? 0) || 0);
  const [draft, setDraft] = useState(search);
  useEffect(() => setDraft(search), [search]);

  const list = useApi<CaseList>(
    api.cases({ decision, decided_by: decidedBy, flagged, decision_type: dtype, search, limit: PAGE, offset: page * PAGE }),
  );

  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    next.delete("page");
    setParams(next, { replace: true });
  };
  const goPage = (p: number) => {
    const next = new URLSearchParams(params);
    if (p > 0) next.set("page", String(p));
    else next.delete("page");
    setParams(next);
  };

  const total = list.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE));

  return (
    <>
      <PageHead title="Case files">
        Every decision the claims agent made in this deployment, recorded in full (level L4) in a hash-chained log. Open a case to replay it step by
        step and see what an auditor could reconstruct at each instrumentation level.
      </PageHead>
      <form
        className="toolbar"
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          set("search", draft.replace(/[^A-Za-z0-9-]/g, ""));
        }}
      >
        <label className="field">
          Decision
          <select value={decision} onChange={(e) => set("decision", e.target.value)}>
            <option value="">Any</option>
            <option value="pay">Pay</option>
            <option value="partial">Partial</option>
            <option value="deny">Deny</option>
          </select>
        </label>
        <label className="field">
          Decided by
          <select value={decidedBy} onChange={(e) => set("decided_by", e.target.value)}>
            <option value="">Anyone</option>
            <option value="agent">Agent</option>
            <option value="human">Human adjuster</option>
          </select>
        </label>
        <label className="field">
          Detector findings
          <select value={flagged} onChange={(e) => set("flagged", e.target.value)}>
            <option value="">Any</option>
            <option value="true">With findings</option>
            <option value="false">No findings</option>
          </select>
        </label>
        <label className="field">
          Decision type (ground truth)
          <select value={dtype} onChange={(e) => set("decision_type", e.target.value)}>
            <option value="">Any</option>
            {(Object.keys(TYPE_LABEL) as DecisionType[]).map((t) => (
              <option key={t} value={t}>
                {TYPE_LABEL[t]}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Claim id
          <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="CLM-00042" maxLength={40} size={12} />
        </label>
        <button className="btn" type="submit">
          Search
        </button>
      </form>

      {list.error ? (
        <ErrorPanel error={list.error} retry={list.retry} what="cases" />
      ) : !list.data ? (
        <Loading rows={10} label="Loading cases" />
      ) : list.data.items.length === 0 ? (
        <div className="panel">
          <Empty title="No decisions match these filters">
            Clear a filter or the claim id search. <Link to="/cases">Show all cases</Link>
          </Empty>
        </div>
      ) : (
        <div className="panel">
          <div className="panel-head">
            <span className="secondary small">
              {total.toLocaleString("en-GB")} decisions{list.loading ? " · updating…" : ""}
            </span>
            <span className="muted small">Select a row or press Enter on a claim link to open its replay.</span>
          </div>
          <div className="table-wrap" tabIndex={0}>
            <table className="sticky-first">
              <thead>
                <tr>
                  <th scope="col">Claim</th>
                  <th scope="col">Date</th>
                  <th scope="col">Decision</th>
                  <th scope="col" className="r">
                    Amount
                  </th>
                  <th scope="col">Decided by</th>
                  <th scope="col" className="r">
                    Steps
                  </th>
                  <th scope="col">Findings</th>
                  <th scope="col" className="hide-mobile">
                    Ground truth: type · injected violation
                  </th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((c) => (
                  <tr key={c.decision_id} className="row-link" onClick={() => navigate(`/cases/${encodeURIComponent(c.decision_id)}`)}>
                    <th scope="row">
                      <Link to={`/cases/${encodeURIComponent(c.decision_id)}`} className="mono" onClick={(e) => e.stopPropagation()}>
                        {c.claim_id}
                      </Link>
                    </th>
                    <td className="mono">{date(c.ts)}</td>
                    <td>{c.decision}</td>
                    <td className="r mono">{money(c.amount)}</td>
                    <td>{c.decided_by === "human" ? "Adjuster" : "Agent"}</td>
                    <td className="r">{c.steps}</td>
                    <td>
                      {c.findings > 0 ? (
                        <Mark tone="bad" glyph="▲">
                          {c.findings} {c.findings === 1 ? "finding" : "findings"}
                        </Mark>
                      ) : (
                        <span className="muted">none</span>
                      )}
                    </td>
                    <td className="hide-mobile">
                      <span className="pill truth">{c.simulation_truth.decision_type ? TYPE_LABEL[c.simulation_truth.decision_type] : "–"}</span>{" "}
                      {c.simulation_truth.violation && <span className="pill truth mono">{c.simulation_truth.violation}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="panel-note" style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
            <button className="btn" type="button" disabled={page === 0} onClick={() => goPage(page - 1)}>
              Previous
            </button>
            <span>
              Page {page + 1} of {pages}
            </span>
            <button className="btn" type="button" disabled={page + 1 >= pages} onClick={() => goPage(page + 1)}>
              Next
            </button>
            <span style={{ marginLeft: "auto" }}>Dashed pills are simulation ground truth, not part of the audit record.</span>
          </div>
        </div>
      )}
    </>
  );
}
