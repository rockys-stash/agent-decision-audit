# Can an agent's decisions be reconstructed after the fact? A simulation study of decision audit trails

**Scope.** Every number below comes from executed code. Each is copied from [generated/results.md](generated/results.md), which `agentaudit report` regenerates from the committed runs in `results/`. All data come from a simulated insurance-claims world ([data/DATASET.md](../data/DATASET.md)). The agent is a rule-and-model pipeline, not a language model. No study with people has been run: the trust question is answered only through a proxy, and the study itself is *Status: pending* ([docs/STUDY.md](../docs/STUDY.md)).

## 1. Question

An autonomous agent pays, partly pays or denies insurance claims, and escalates some to human adjusters. Months later, an auditor asks why a particular claim was decided the way it was. What must the agent have recorded at decision time for that question to have a trustworthy answer?

We instrument the agent with an audit SDK that records every step of every decision in a hash-chained log. We then ask four questions from the brief, plus two engineering questions:

| | Question | Experiment |
|---|---|---|
| RQ1 | Can decisions be fully reconstructed? | E1, E2 |
| RQ2 | Which decision types resist auditing? | E1 |
| RQ3 | Does an audit trail support trust? (proxy: can standard audit questions be answered correctly?) | E1 |
| RQ4 | Can policy violations be detected automatically? | E3 |
| Integrity | Is the log tamper-evident, and against which attacker? | E4 |
| Cost | What does instrumentation cost? | E5 |

## 2. Setup

**World.**
- Each seed generates 900 policies and 2,000 claims over 180 days.
- The environment keeps changing for 360 days:
  - exchange rates drift;
  - 30% of policies are revised;
  - 10% of claims are amended;
  - holders accumulate claims;
  - the fraud model is retrained every 30 days;
  - the agent is upgraded on days 75 and 150.
- An external narrative assessor returns a different score on every call, and adjusters cannot be asked twice.

**Instrumentation levels.** The SDK always records the full trace. A level is what a less complete logging system would have kept:

| Level | Keeps |
|---|---|
| L0 | output only |
| L1 | adds the input and the rationale |
| L2 | adds tool calls with outputs, evidence and human decisions |
| L3 | adds calculations, rules, model scores, confidence, alternatives and intermediate decisions |
| L4 | adds the environment: configuration and model versions, random seeds, actors and request ids |

Levels are exact projections of one record, so they differ only in what was kept.

**Replay.**
- The auditor re-runs the agent's code against the record:
  - **Record mode** serves recorded inputs and looks up only what is missing, as it is on the audit day.
  - **Live mode** looks everything up again.
- The outcome is one of five:
  - *reproduced*;
  - *attested* (matched, but some steps could only be taken from the record);
  - *unverifiable* (matched, but needed unrecorded inputs);
  - *diverged*;
  - *not reconstructable*.
- Because the simulation keeps the complete trace, we can also check whether the replay followed the original **route**: the same branches and the same final decision, amount and decider.
- A replay the auditor would accept but whose route is wrong is a **silent misreconstruction**.

Definitions are in [docs/METRICS.md](../docs/METRICS.md). Means are over seeds with 95% bootstrap CIs; rare events are pooled over seeds.

## 3. Results

### RQ1: Can decisions be fully reconstructed? (E1, E2)

**With the full environment recorded, yes: every decision, at every audit delay.**
- At L4, record-mode replay fully reconstructed 100% of 20,000 decisions 30 days later: 66.8% reproduced and 33.2% attested.
- The same holds at 0, 7, 90 and 180 days (E2).
- Every route matched, with no silent misreconstructions.

This part is largely **definitional**: a complete record of every non-deterministic input, replayed through deterministic code, must reproduce the decision. What the experiment adds is evidence that the SDK actually captures every such input. Before two fixes (D11, D12) it did not, because of floating-point round-trips and wall-clock fields.

**Nothing short of L4 fully reconstructs a single decision.** At 30 days:

| Record kept | Route match | Diverged | Not reconstructable | Silent misreconstruction |
|---|---|---|---|---|
| L0 output | 48.4% | 22.0% | 28.2% | 1.4% |
| L1 inputs | 48.3% | 32.6% | 28.3% | 0.6% |
| L2 tools | 88.1% | 24.3% | 0% | 0% |
| L3 steps | 88.0% | 85.5% | 0% | 0% |
| L4 environment | 100% | 0% | 0% | 0% |
| Live re-query | 48.2% | 62.1% | 28.5% | 0% |

Three findings go beyond the definitions.

1. **Recording tool outputs is the step that matters for the route.**
   - L2 nearly doubles route match over L0 (88.1% vs 48.4%).
   - Re-querying every source live does no better than keeping only the output (48.2%).
   - L3 adds nothing to route match over L2 (88.0%). Its value is in answering audit questions (RQ3).
2. **Partial records make the auditor's job harder, not easier, in one specific way.**
   - At L3, 85.5% of replays diverge, more than at any other level.
   - In 81.7% of all decisions the first divergence is the fraud score: L3 records the score but not the model version, so the replay rescores with the model current on the audit day.
   - The divergence is correctly reported. But an auditor holding an L3 record sees a disagreement on most decisions and cannot tell which ones matter (route match is still 88.0%).
3. **Output-only records degrade with time, and they degrade silently.**
   - L0 route match falls from 69.0% (same-day audit) to 50.7% at 7 days, 43.1% at 90 days and 39.5% at 180 days.
   - Silent misreconstruction at L0 grows from 0% to 1.4% at 30 days and 6.3% at 180 days: replays an auditor would accept that took a different path. At L1 it reaches 2.2%.
   - From L2 up it is 0% at every delay. Once tool outputs are recorded, drift that changes the route shows up as a divergence instead of passing unnoticed.

**What drifts.** Live replay's first divergence, by delay:
- At 0 days: only the unrecorded random draw (10,428) and the external assessor (1,041).
- At 7 days: holder profiles (6,512) and exchange rates (4,016).
- At 90 days and later: mostly the agent's own configuration, because the agent was upgraded (11,856 at 90 days).
- Decisions that needed an adjuster (about 5,700 at every delay) cannot be re-run at all.

### RQ2: Which decision types resist auditing? (E1)

Route match at 30 days, and how L4 verifies each type:

| Decision type | n | L0 | L2 | L3 | L4 reproduced | L4 attested only |
|---|---|---|---|---|---|---|
| Rule only | 2,905 | 99.9% | 100% | 100% | 100% | 0% |
| Calculation | 7,009 | 88.1% | 91.0% | 90.8% | 92.2% | 7.8% |
| Currency conversion | 4,345 | 12.7% | 90.8% | 90.9% | 91.5% | 8.5% |
| Fraud model | 447 | 4.3% | 79.1% | 77.5% | 3.4% | 96.6% |
| Random QA sample | 866 | 0% | 3.9% | 4.0% | 0% | 100% |
| External assessor | 973 | 3.7% | 85.7% | 85.9% | 0% | 100% |
| Human adjuster | 3,455 | 0% | 91.8% | 91.4% | 0% | 100% |

- **Rule-only decisions are auditable from the output alone.** Their inputs (policy dates, exclusion flags) rarely change.
- **Currency conversions need their inputs recorded.** Route match goes from 12.7% at L0 to 90.8% at L2.
- **Random draws are the hardest.** Without the seed (recorded only at L4), only 3.9–4.0% of QA-sampled decisions follow the original route, because a fresh draw almost never selects the same claim again.
- **The fraud model** loses about a fifth of routes even at L2–L3, because the model version is missing.
- **People and opaque external services can never be re-derived, only attested.**
  - 100% of human, external-assessor and QA-sampled decisions, and 96.6% of model-type decisions (which mostly end with an adjuster), are verified at L4 only by taking a recorded answer on trust.
  - So one third of all decisions (33.2%) rest on recorded testimony even with complete instrumentation. That share is set by how many decisions involve a person or an opaque service; logging more does not reduce it.

### RQ3: Does an audit trail support trust? (E1, proxy only)

We cannot measure trust without people (*Status: pending*). The proxy asks whether eight standard audit questions are answered correctly, from the record if it holds the answer and otherwise from a replay:

| Question | L0 | L2 | L3 | L4 |
|---|---|---|---|---|
| What was decided on | 70.1% | 100% | 100% | 100% |
| Sources and their answers | 13.8% | 100% | 100% | 100% |
| How the amount was computed | 48.8% | 100% | 100% | 100% |
| Rules evaluated | 66.6% | 88.1% | 100% | 100% |
| Alternatives considered | 17.7% | 26.9% | 100% | 100% |
| Confidence | 24.3% | 28.1% | 100% | 100% |
| Agent and model versions | 10.0% | 10.0% | 10.0% | 100% |
| Whether a person was involved, and who | 68.4% | 72.1% | 72.1% | 100% |

- Only L4 answers all eight.
- Versions cannot be answered correctly at any lower level except by luck (10%).
- The more important number is how often a replay gives a **confident wrong answer**. At L2 a replay answers the alternatives question wrongly for 73.1% of decisions, the confidence question for 71.9% and the versions question for 90.1%.
- An auditor who reconstructs missing facts by re-running the agent will often be wrong without knowing it.
- This is the strongest argument in the data for recording reasoning steps (L3) and the environment (L4), rather than relying on replay to fill gaps.

### RQ4: Can policy violations be detected automatically? (E3)

The faulty agent attempted a violation on 40% of 40,000 claims. Kinds were drawn from 13, of which 6,031 attempts took effect. Two kinds were **held out**: no check was written for them.

| Record kept | Rule checks: recall | Precision | False positives per 1,000 clean decisions | Reference replay: recall | Precision | FP per 1,000 |
|---|---|---|---|---|---|---|
| L0 | 6.2% | 94.4% | 0.93 | 46.7% | 32.7% | 218.9 |
| L2 | 65.7% | 100% | 0 | 79.4% | 42.0% | 243.2 |
| L3 | 88.1% | 100% | 0 | 100% | 20.5% | 855.5 |
| L4 | 92.8% | 100% | 0 | 95.3% | 100% | 0 |

- **On full traces, the audit standard's rule checks catch the violations they were written for.**
  - Recall is 99.9% on the 11 designed-for kinds, with precision 100% and no false positives on 40,000 clean decisions.
  - Recall over all 13 kinds is 92.8%. This misses the ≥ 0.95 hypothesis, and the shortfall is entirely the held-out kinds.
  - The generic payout-recomputation check catches 57.1% of `rate_operand_mismatch` without being designed for it.
  - Rules catch 0% of `evidence_substitution` (a receipt from another claim counted as evidence). Every recorded number is internally consistent; the evidence itself is wrong.
- **Reference replay is the complementary detector, and it works only on complete records.**
  - Re-running the approved code on the recorded inputs catches 100% of both held-out kinds at L4.
  - It misses `segregation_of_duties` (0%), because an adjuster's decision can only be attested, not re-derived.
  - Below L4 it is unusable. Ordinary drift makes it flag 219–856 of every 1,000 clean decisions.
  - We did not measure the union of the two detectors at L4.
- **Output-only checking is nearly blind.** At L0, rule checks catch 6.2% of violations.
- **Sample audits recover roughly their sampling fraction.** Recall per kind is 3.4–11.6% for 5% and 10% samples, and that assumes the auditor finds every violation in the sample.

### Integrity: is the log tamper-evident? (E4)

Five logs of about 8,700–9,000 events each; eight attacks, each applied 100 times per log at random positions. Checkpoints are signed every 100 events and the head is anchored with the witness every 1,000 events. Untampered logs always verified as valid.

| Attack | Sequence numbers | Hash chain | + signed checkpoints | + external anchor |
|---|---|---|---|---|
| Edit an event or a stored tool output | 0% | 100% | 100% | 100% |
| Delete, insert or swap events | 0% | 100% | 100% | 100% |
| Truncate the tail | 0% | 0% | 0% | 58% |
| Rewrite the suffix, without the key | 0% | 0% | 99% | 99% |
| Rewrite the suffix, with the key | 0% | 0% | 0% | 89% |

- **Renumbering defeats sequence checks entirely.** The hash chain catches every in-place change and locates it at the exact event (99–100% of detections).
- **The chain alone is blind to truncation and to recomputation.** An attacker who drops the tail, or edits an event and recomputes every later hash, leaves a valid chain.
- **Signed checkpoints stop an attacker without the key** (99%), but only to within a checkpoint interval: the first missing or invalid checkpoint is reported, not the edited event (exact location in 1%). The 1% missed are edits after the last checkpoint.
- **Only the external anchor catches truncation and an operator holding the key.** It catches them only when the change reaches back past an anchor: none of the 211 truncations and none of the 55 keyed rewrites confined to events after the last anchor were detected. The anchor interval is therefore the window in which an insider can rewrite history undetected.
- This run replaces the first E4 run, whose attack generator sometimes produced no change at all (D19). The earlier run is kept in `results/e4_tamper/20261008T062201Z-f561923`.

### Cost (E5)

Measured on this 4-CPU machine (comparable only within the table):

| Measure | Value |
|---|---|
| Agent without instrumentation | 0.77 ms per decision |
| Recording to memory | 2.37 ms per decision |
| Recording to SQLite with checkpoints and anchors | 4.59 ms per decision |
| Record-mode L4 replay | 1.19 ms per decision |
| Verification throughput | about 47,000 events per second |

- A decision produces 29.3 events and 13.7 kB in SQLite.
- Trace size grows from 372 B (L0) to 4.9 kB (L2), 8.8 kB (L3) and 9.5 kB (L4) of canonical JSON per decision.
- Storing tool outputs once as content-addressed blobs saves only about 290 bytes per decision here, because few outputs are shared between decisions.
- The hypothesis of "a few kB after deduplication" holds for size, but deduplication contributes little to it.

## 4. What is definitional and what is not

**Definitional:**
- L4 reproducing every decision (given deterministic code and a complete record).
- L0 and live replay never reaching *reproduced* (the status requires recorded inputs).
- Humans never being re-derivable.

**Measured and not definitional:**
- How often each level recovers the original route, and how that decays with delay.
- How often partial records lead an auditor to accept a wrong reconstruction.
- Which drift sources dominate at which delay.
- How often replay-based answers to audit questions are wrong.
- Detector recall and precision, especially on held-out violations and on the clean agent.
- Which integrity layer catches which attack, and how precisely it localises it.
- The runtime and storage cost.

## 5. What the evidence supports

1. Record tool outputs (L2) at minimum. It is the largest single gain in reconstruction, and the first level at which drift can no longer cause silent misreconstruction.
2. Record the environment (L4) whenever decisions depend on models, configuration or randomness. Without versions and seeds, even a step-level record (L3) produces a divergence on most decisions.
3. Do not fill gaps in a record by re-running the agent and trusting the answer. Replay-derived answers were wrong for most decisions on alternatives, confidence and versions.
4. Treat decisions that involve people or opaque services as *attested*, not verified. In this world that was a third of all decisions, at any level of logging.
5. Combine rule-based checks with reference replay. They fail on different violations.
6. Anchor the log head with a party the operator cannot overwrite. Neither a hash chain nor signed checkpoints stop an operator who holds the signing key.

## 6. Threats to validity

- **Synthetic world and simple agent.** Drift rates and the agent's structure are chosen, not measured. An LLM agent's reasoning is not explicit, so the L3 record would be a model-written rationale, not the computation. The SDK's capture of tool calls, inputs, versions and seeds would carry over; its capture of "steps" would not.
- **Decision types are labelled by the simulation.** A different precedence order would move decisions between types, but not the per-level totals.
- **Designed-for checks.** Recall on the 11 designed-for violation kinds is an upper bound; only two kinds were held out. The injected faults are clean, single-step deviations, and real violations may be subtler.
- **Integrity.** The witness is a local file, and its protection is assumed, not tested. The signing key lives next to the database in the demo.
- **Timing** comes from one machine.

## 7. Reproduction

```bash
make setup
make experiments     # E1–E5 then `agentaudit report`; runtimes are in each run's provenance
```

- Results are written to `results/<experiment>/<UTC time>-<commit>/` with `per_seed.jsonl`, `summary.json` and provenance (commit, seeds, configuration, runtime).
- CI checks that `agentaudit report` regenerates the tables in `research/generated` byte-identical from the committed runs. Figures are regenerated but not compared, because their layout depends on the fonts installed.
- E1, E2, E3 and E5 ran at commit `f561923`. E4 was re-run at `443db66` after a fix to its attack generator (D19).

## 8. Pending

- A study with human auditors on whether the trail changes trust, detection and review time. **Status: pending** (protocol in [docs/STUDY.md](../docs/STUDY.md)).
- Instrumenting a language-model agent with the same SDK. **Status: pending** (no model API key in the build environment).
