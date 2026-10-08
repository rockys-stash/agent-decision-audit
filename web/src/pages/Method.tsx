import { Glyph, PageHead } from "../components/ui";
import { LEVEL_HELP, LEVEL_LABEL, LEVELS, STATUS, TYPE_LABEL } from "../lib/format";
import type { DecisionType, Status } from "../lib/api";

const TYPE_HELP: Record<DecisionType, string> = {
  rule: "Denied automatically by a policy rule (lapsed policy, exclusion, reporting window).",
  calculation: "Paid automatically in EUR from receipts, limits and the deductible.",
  fx: "Paid automatically in a foreign currency, so it depends on that day's exchange rate.",
  model: "The fraud model's score failed, or came within 0.1 of, the threshold; the model is retrained every 30 days.",
  stochastic: "Sent to a person by a random quality-control draw.",
  opaque: "An external narrative assessor's score failed, or came within 0.1 of, its threshold; the service gives a different answer on every call.",
  human: "Escalated for another reason and decided by an adjuster, whose decision cannot be re-requested.",
};

export function Method() {
  return (
    <>
      <PageHead title="Method and limits">
        How the console decides what an auditor can and cannot verify, and what the evidence does not show.
      </PageHead>
      <div className="prose">
        <h2>The record</h2>
        <p>
          The audit SDK wraps the agent&apos;s tools and records every step of a decision as an event: the input claim, every tool call and its output,
          the evidence cited, every calculation and rule as an expression with its operands, model scores, confidence, the alternatives considered, any
          human decision, the final decision and, later, the outcome. Events are appended to a log in which each event&apos;s hash covers the previous
          hash, so changing, removing, inserting or reordering any event breaks every hash after it.
        </p>
        <h2>Instrumentation levels</h2>
        <p>A level is what a less complete logging system would have kept. Lower levels are projections of the same full record, so they can be compared exactly.</p>
        <ul>
          {LEVELS.map((l) => (
            <li key={l}>
              <strong>{LEVEL_LABEL[l]}.</strong> {LEVEL_HELP[l]}
            </li>
          ))}
        </ul>
        <h2>Replay and verification outcomes</h2>
        <p>
          The replay engine re-runs the agent&apos;s own code. In record mode it serves each input from the record and looks up only what the record lacks,
          as it is on the audit day. In live mode it looks everything up again. It then compares the replayed steps with the recorded ones.
        </p>
        <ul>
          {(Object.keys(STATUS) as Status[]).map((s) => (
            <li key={s}>
              <strong>
                <Glyph glyph={STATUS[s].glyph} /> {STATUS[s].word}.
              </strong>{" "}
              {STATUS[s].help}
            </li>
          ))}
        </ul>
        <p>
          The experiments also know what actually happened (the simulation keeps the complete trace). A replay the auditor would accept but whose route
          differs from the original is a <em>silent misreconstruction</em>: the most dangerous outcome, because nobody notices.
        </p>
        <h2>Decision types</h2>
        <p>Each decision is labelled with the hardest dependency on its path. This label is simulation ground truth and is never part of the record.</p>
        <ul>
          {(Object.keys(TYPE_LABEL) as DecisionType[]).map((t) => (
            <li key={t}>
              <strong>{TYPE_LABEL[t]}.</strong> {TYPE_HELP[t]}
            </li>
          ))}
        </ul>
        <h2>Violation detection</h2>
        <p>
          A YAML audit standard defines thirteen checks: approval limits, denial basis, clause limits, payout recomputation, calculation provenance,
          verified amounts, fraud escalation, protected attributes, exchange-rate freshness, a tool allowlist, segregation of duties, required checks and
          generic recomputation. Each check says which data it needs; at a level that lacks the data, it either falls back to a live lookup (marked as
          such) or reports that it cannot be evaluated. Reference replay is a second detector: it re-runs the approved code on the recorded inputs and
          flags any divergence.
        </p>
        <h2>Limits of the evidence</h2>
        <ul>
          <li>
            All data come from a simulated insurance-claims world with documented drift rates, and the agent is a rule-and-model pipeline, not a language
            model. Its reasoning is explicit by construction; an LLM agent&apos;s would not be.
          </li>
          <li>Two of the thirteen violation kinds were held out while the checks were written. The other eleven had checks designed for them, so their recall is an upper bound.</li>
          <li>
            Whether an audit trail builds trust needs a study with people. The audit-question results are only a proxy. Status: pending (protocol in{" "}
            <code>docs/STUDY.md</code>).
          </li>
          <li>The external witness is a local file here. Anchoring only helps if the witness is held by someone the operator cannot overwrite.</li>
          <li>Simulation ground truth (decision types, injected violations, fraud) is shown with dashed borders and is never available to a real auditor.</li>
        </ul>
      </div>
    </>
  );
}
