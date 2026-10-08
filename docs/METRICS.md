# Metrics

Definitions of every number in `research/generated/results.md` and the console's lab notebook. Code references point to where each is computed.

## Replay outcomes (E1, E2)

A replay re-runs the agent's code for one decision against the record as kept at a level (`agentaudit.replay.replay`). The auditor sees only the record, and the outcome is what the auditor can conclude:

| Outcome | Definition |
|---|---|
| Reproduced | Every recorded step matched the replayed step at this level, the final decision matched, and the replay used only recorded inputs. Every calculation, rule and model score was recomputed. |
| Attested | As reproduced, but at least one step (an adjuster's decision, an external service's answer) could only be taken from the record, not re-derived. |
| Unverifiable | The recorded steps matched, but the replay needed inputs the record does not hold, so it looked them up on the audit day: a tool output, a random draw, or the model or agent version current then. |
| Diverged | Some step or the final decision differed from the record. The first such step is the first divergence. Also used when the record shows no human decision but the replay's path requires one. |
| Not reconstructable | The replay could not run: it needed a human decision that the level does not record, and a person cannot be asked again. |

Derived rates, each a share of decisions:

- **Fully reconstructed** = reproduced + attested.
- **Route match** = the replay's route equals the original's. A route is the sequence of step kinds and names, each rule's pass or fail, each intermediate decision, any human decision, and the final decision, amount and decider (`replay.route`). It uses the complete original trace, so it is ground truth, not something the auditor knows.
- **Silent misreconstruction** = the auditor would accept the replay (reproduced, attested or unverifiable) and its route differs from the original. This is the failure that nobody notices.

## Audit questions (E1)

Eight questions (`agentaudit.questions.QUESTIONS`): the input, sources and their answers, how the amount was computed, which rules were evaluated, the alternatives, the confidence, the agent and model versions, and whether a person was involved and who.

Each question is answered from the record at the level if the record holds the answer, otherwise from the replay, and compared with the answer from the complete original trace. Outcomes:

- `record` (correct, from the record);
- `record_wrong`;
- `replay_correct`;
- `replay_wrong`;
- `unanswerable`.

**Correct** = record + replay_correct.

## Violation detection (E3)

- **Recall, all violations** = flagged decisions that carry an injected violation ÷ decisions that carry one, pooled over seeds.
- **Recall, designed-for types** = the same, over the 11 kinds that had a check written for them.
- **Precision** = flagged decisions that carry a violation ÷ all flagged decisions of the faulty agent.
- **False positives per 1,000 clean decisions** = decisions of the clean agent flagged by the detector, per 1,000.
- **Flags that needed live data** = rule flags at that level that relied only on findings computed from live lookups on the audit day, because the level lacked the data.
- **Per-check "on a violation it targets"** = findings on decisions whose injected kind is among the check's targets.
- **Reference replay flag** = replay of the approved (clean) code against the record at the level ends in *diverged*.
- **Sample audit recall** = share of violating decisions that fall in a uniform random sample of the given size. This assumes a perfect auditor for sampled decisions, so it is an upper bound for sampling.

CIs for pooled rates come from resampling seeds (`experiments.stats.pooled_rate`).

## Tamper evidence (E4)

- **Detected** = share of tampered logs that the defence rejects.
- **Located exactly** = share of detections whose first bad sequence number equals the tampered position.
- **Within one checkpoint interval** = the reported position is at most 99 events after the tampered one.
- **After the last anchor** = trials whose tampered position is beyond the last anchored head; these are reported separately for the full defence.

## Overhead (E5)

- Milliseconds per decision with no recording (`NullContext`), with an in-memory log, and with SQLite plus checkpoints and anchors.
- Record-mode L4 replay time per decision.
- Verification throughput in events per second, for the chain alone and for chain, checkpoints and anchors.
- Bytes of canonical JSON per decision at each level, inline and with tool outputs stored once as content-addressed blobs.
- SQLite file bytes per decision after VACUUM.

For each seed, the median of the repeats is taken; then the mean over seeds is reported with a CI.

## Statistics

- Seeds are independent worlds. Means over seeds come with 95% percentile-bootstrap CIs over seeds (2,000 resamples; `experiments.stats.mean_ci`).
- Rare-event rates are pooled over seeds with a CI from resampling whole seeds (`pooled_rate`).
- No hypothesis tests are reported. Where a level is at 0% or 100% in every seed, the CI collapses to that value and is printed without brackets.
