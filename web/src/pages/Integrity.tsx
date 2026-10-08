import { useState } from "react";
import { ErrorPanel, Hash, Loading, Mark, PageHead } from "../components/ui";
import { api, ApiError, postJson, useApi, type Integrity as IntegrityT, type TamperResult } from "../lib/api";
import { ATTACK_LABEL, DEFENSE_LABEL } from "../lib/format";

const ATTACKS = Object.keys(ATTACK_LABEL);

export function Integrity() {
  const integrity = useApi<IntegrityT>(api.integrity);
  const [attack, setAttack] = useState(ATTACKS[0] ?? "edit_event");
  const [seed, setSeed] = useState(1);
  const [lab, setLab] = useState<TamperResult | null>(null);
  const [labError, setLabError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  const run = async () => {
    setRunning(true);
    setLabError(null);
    try {
      setLab(await postJson<TamperResult>(api.tamperLab, { attack, seed }));
    } catch (e) {
      setLabError(e instanceof ApiError ? `${e.status ? `HTTP ${e.status}: ` : ""}${e.message}` : String(e));
    } finally {
      setRunning(false);
    }
  };

  return (
    <>
      <PageHead
        title="Seal and custody"
        actions={
          <button className="btn" type="button" onClick={integrity.retry} disabled={integrity.loading}>
            {integrity.loading ? "Verifying…" : "Verify again"}
          </button>
        }
      >
        Every event is chained to the one before it by a SHA-256 hash. Every 100 events an HMAC-signed checkpoint records the head, and every 500 events
        the head is anchored in a separate witness file. This page verifies all three on the stored log.
      </PageHead>

      {integrity.error ? (
        <ErrorPanel error={integrity.error} retry={integrity.retry} what="the integrity report" />
      ) : !integrity.data ? (
        <Loading rows={4} label="Verifying the chain" />
      ) : (
        <div className="grid two" style={{ marginBottom: 16 }}>
          <section className="panel">
            <div className="panel-head">
              <h2>Stored log</h2>
              {integrity.data.valid ? (
                <Mark tone="ok" glyph="✓">
                  Intact
                </Mark>
              ) : (
                <Mark tone="bad" glyph="✕">
                  Broken at seq {integrity.data.first_bad_seq}
                </Mark>
              )}
            </div>
            <div className="panel-body">
              <dl className="kv">
                <dt>Events verified</dt>
                <dd className="num">{integrity.data.events.toLocaleString("en-GB")}</dd>
                <dt>Signed checkpoints checked</dt>
                <dd className="num">{integrity.data.checkpoints_checked}</dd>
                <dt>Anchors checked</dt>
                <dd className="num">{integrity.data.anchors_checked}</dd>
                <dt>Head</dt>
                <dd>
                  seq <span className="mono">{integrity.data.head_seq}</span> · <Hash value={integrity.data.head} n={20} />
                </dd>
                <dt>Last checkpoint</dt>
                <dd className="mono">{integrity.data.last_checkpoint ?? "–"}</dd>
                <dt>Verified</dt>
                <dd>{integrity.data.verified_seconds_ago < 1 ? "just now" : `${integrity.data.verified_seconds_ago} s ago (results are reused for 5 s)`}</dd>
              </dl>
              {integrity.data.problems.length > 0 && (
                <ul className="small" role="alert">
                  {integrity.data.problems.map((p) => (
                    <li key={p}>{p}</li>
                  ))}
                </ul>
              )}
            </div>
          </section>
          <section className="panel">
            <div className="panel-head">
              <h2>Latest anchors in the witness store</h2>
            </div>
            <div className="table-wrap" tabIndex={0}>
              <table>
                <thead>
                  <tr>
                    <th scope="col" className="r">
                      At seq
                    </th>
                    <th scope="col">Anchored head</th>
                  </tr>
                </thead>
                <tbody>
                  {integrity.data.anchors.map((a) => (
                    <tr key={a.seq}>
                      <td className="r mono">{a.seq}</td>
                      <td>
                        <Hash value={a.head} n={24} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="panel-note">
              In a real deployment the witness lives with another party (a transparency log, a regulator, a timestamping service). Here it is a local file.
            </div>
          </section>
        </div>
      )}

      <section className="panel">
        <div className="panel-head">
          <h2>Tamper lab</h2>
          <span className="muted small">Attacks a copy in memory. The stored log is never written.</span>
        </div>
        <div className="panel-body">
          <form
            className="toolbar"
            onSubmit={(e) => {
              e.preventDefault();
              void run();
            }}
          >
            <label className="field">
              Attack
              <select value={attack} onChange={(e) => setAttack(e.target.value)}>
                {ATTACKS.map((a) => (
                  <option key={a} value={a}>
                    {ATTACK_LABEL[a]}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              Random position (seed)
              <input type="number" min={0} max={1_000_000} value={seed} onChange={(e) => setSeed(Math.max(0, Math.min(1_000_000, Number(e.target.value) || 0)))} />
            </label>
            <button className="btn primary" type="submit" disabled={running}>
              {running ? "Attacking the copy…" : "Run attack"}
            </button>
          </form>
          {labError && (
            <p role="alert" className="finding">
              {labError}
            </p>
          )}
          {lab ? (
            <>
              <p className="secondary small">
                {ATTACK_LABEL[lab.attack]} at seq <span className="mono">{lab.target_seq}</span>; the tampered copy has {lab.events_after.toLocaleString("en-GB")}{" "}
                events. Which integrity layers notice?
              </p>
              <div className="table-wrap" tabIndex={0}>
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Defence</th>
                      <th scope="col">Verdict</th>
                      <th scope="col">Points to</th>
                      <th scope="col">Why</th>
                    </tr>
                  </thead>
                  <tbody>
                    {lab.results.map((r) => (
                      <tr key={r.defense}>
                        <th scope="row">{DEFENSE_LABEL[r.defense] ?? r.defense}</th>
                        <td>
                          {r.valid ? (
                            <Mark tone="bad" glyph="✕" title="The tampered log passes this check">
                              Accepted as valid
                            </Mark>
                          ) : (
                            <Mark tone="ok" glyph="✓">
                              Tampering detected
                            </Mark>
                          )}
                        </td>
                        <td className="mono">{r.first_bad_seq ?? "–"}</td>
                        <td className="small secondary">{r.problems[0] ?? ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <p className="muted small">Choose an attack and run it to see which layers detect it. Experiment E4 repeats this 500 times per attack.</p>
          )}
        </div>
      </section>
    </>
  );
}
