# Generated results

Produced by `agentaudit report` from the latest completed run of each experiment. Do not edit by hand; every section names the run and commit it came from. All data are from the simulated claims world (data/DATASET.md).

## E1: Reconstruction by instrumentation level and decision type

_Source: `results/e1_reconstruction/20261008T061346Z-f561923` · commit `f56192313b91` · 10 seeds from base 20261008 · 2000 claims per seed · runtime 62.8 s._

20,000 decisions by the clean agent, replayed 30 days after each decision. Rates are means over seeds with 95% bootstrap CIs (percent). _Fully reconstructed_ is reproduced or attested: the auditor, using only the record, re-derived every step and the record agreed. _Route match_ compares the replay with the simulation's ground truth: same branches, same final decision and amount. _Silent misreconstruction_ is a replay the auditor would accept (reproduced, attested or unverifiable) whose route differs from what actually happened.

### All decisions

| Replay | Level | Fully reconstructed | Reproduced | Attested | Unverifiable | Diverged | Not reconstructable | Route match | Silent misreconstruction |
|---|---|---|---|---|---|---|---|---|---|
| Record | L0 output | 0.0 | 0.0 | 0.0 | 49.8 [49.0, 50.6] | 22.0 [21.3, 22.7] | 28.2 [27.8, 28.6] | 48.4 [47.7, 49.1] | 1.4 [1.2, 1.6] |
| Record | L1 inputs | 0.0 | 0.0 | 0.0 | 39.1 [38.3, 40.1] | 32.6 [31.7, 33.5] | 28.3 [27.9, 28.7] | 48.3 [47.5, 49.0] | 0.6 [0.5, 0.8] |
| Record | L2 tools | 0.0 | 0.0 | 0.0 | 75.7 [74.5, 76.9] | 24.3 [23.1, 25.5] | 0.0 | 88.1 [87.4, 88.7] | 0.0 |
| Record | L3 steps | 0.0 | 0.0 | 0.0 | 14.5 [14.0, 15.1] | 85.5 [84.9, 86.0] | 0.0 | 88.0 [87.5, 88.4] | 0.0 |
| Record | L4 environment | 100.0 | 66.8 [66.1, 67.5] | 33.2 [32.5, 33.9] | 0.0 | 0.0 | 0.0 | 100.0 | 0.0 |
| Live (re-query everything) | L4 environment | 0.0 | 0.0 | 0.0 | 9.4 [9.0, 10.0] | 62.1 [61.4, 62.7] | 28.5 [27.8, 29.1] | 48.2 [47.3, 49.0] | 0.0 |

### By decision type (record mode)

A decision's type is the hardest dependency on its path, in the order human, external assessor, random sample, fraud model, rule, currency conversion, calculation (see data/DATASET.md).

| Decision type | Decisions | L0 route match | L2 route match | L3 route match | L4 reproduced | L4 attested | L4 fully reconstructed |
|---|---|---|---|---|---|---|---|
| Rule only | 2,905 | 99.9 [99.8, 100.0] | 100.0 | 100.0 | 100.0 | 0.0 | 100.0 |
| Calculation | 7,009 | 88.1 [87.4, 88.6] | 91.0 [90.3, 91.5] | 90.8 [90.0, 91.4] | 92.2 [91.7, 92.8] | 7.8 [7.2, 8.3] | 100.0 |
| Currency conversion | 4,345 | 12.7 [11.7, 13.8] | 90.8 [89.6, 91.9] | 90.9 [89.9, 91.9] | 91.5 [90.7, 92.1] | 8.5 [7.9, 9.3] | 100.0 |
| Fraud model | 447 | 4.3 [3.0, 5.6] | 79.1 [76.5, 81.7] | 77.5 [73.9, 80.7] | 3.4 [1.9, 5.0] | 96.6 [95.0, 98.1] | 100.0 |
| Random QA sample | 866 | 0.0 | 3.9 [2.6, 4.9] | 4.0 [2.6, 5.2] | 0.0 | 100.0 | 100.0 |
| External assessor | 973 | 3.7 [2.9, 4.7] | 85.7 [83.7, 87.6] | 85.9 [84.0, 87.8] | 0.0 | 100.0 | 100.0 |
| Human adjuster | 3,455 | 0.0 | 91.8 [91.2, 92.4] | 91.4 [90.5, 92.2] | 0.0 | 100.0 | 100.0 |

### Where record-mode replay diverged first (four most frequent per level)

| Level | First divergent step (fields that differ) | Decisions | Share of all decisions |
|---|---|---|---|
| L0 output | final 'final' (amount) | 3,606 | 18.0% |
| L0 output | final 'final' (decided_by) | 414 | 2.1% |
| L0 output | final 'final' (amount, decided_by) | 216 | 1.1% |
| L0 output | final 'final' (amount, decision) | 102 | 0.5% |
| L1 inputs | final 'final' (amount, rationale) | 3,458 | 17.3% |
| L1 inputs | final 'final' (rationale) | 2,012 | 10.1% |
| L1 inputs | final 'final' (decided_by, rationale) | 398 | 2.0% |
| L1 inputs | input 'input' (payload, payload_hash) | 342 | 1.7% |
| L2 tools | final 'final' (rationale) | 3,013 | 15.1% |
| L2 tools | human 'adjuster.review' (replay requires a human decision that the record does not contain) | 722 | 3.6% |
| L2 tools | human 'adjuster.review' (replay reached final 'final' instead) | 603 | 3.0% |
| L2 tools | final 'final' (replay reached external 'narrative.assess' instead) | 347 | 1.7% |
| L3 steps | model 'fraud' (score) | 16,343 | 81.7% |
| L3 steps | human 'adjuster.review' (replay requires a human decision that the record does not contain) | 728 | 3.6% |
| L3 steps | rule 'governance.qa_sample' (inputs) | 20 | 0.1% |
| L3 steps | rule 'governance.fraud_score' (inputs) | 4 | 0.0% |

### Why live replay diverged (first divergent step)

| Cause | Decisions |
|---|---|
| human (not recorded for live re-execution) | 5,693 |
| config 'claims-agent' | 4,678 |
| tool 'holders.profile' | 4,548 |
| tool 'fx.spot' | 2,727 |
| tool 'policy_store.get' | 243 |
| tool 'claims_db.get' | 226 |

### Audit questions answered correctly (30-day delay)

Each question is answered from the record where the level holds the answer, otherwise from the replay, and the answer is checked against the complete original trace. Percent of decisions answered correctly, mean over seeds with 95% CI.

| Question | L0 output | L1 inputs | L2 tools | L3 steps | L4 environment |
|---|---|---|---|---|---|
| What exactly was the agent deciding on? | 70.1 [69.8, 70.5] | 100.0 | 100.0 | 100.0 | 100.0 |
| Which sources and services did it consult, and what did they return? | 13.8 [13.2, 14.4] | 13.8 [13.2, 14.4] | 100.0 | 100.0 | 100.0 |
| How was the amount computed? | 48.8 [48.1, 49.4] | 48.7 [48.0, 49.4] | 100.0 | 100.0 | 100.0 |
| Which policy rules were evaluated, with what result? | 66.6 [65.8, 67.2] | 66.4 [65.6, 67.2] | 88.1 [87.4, 88.7] | 100.0 | 100.0 |
| Which alternatives were considered, and which was chosen? | 17.7 [17.0, 18.6] | 17.7 [17.1, 18.6] | 26.9 [26.1, 27.8] | 100.0 | 100.0 |
| How confident was the agent? | 24.3 [23.6, 25.0] | 24.3 [23.6, 25.0] | 28.1 [27.1, 29.0] | 100.0 | 100.0 |
| Which agent and model versions made the decision? | 10.0 [9.5, 10.4] | 10.0 [9.5, 10.4] | 10.0 [9.5, 10.4] | 10.0 [9.5, 10.4] | 100.0 |
| Was a person involved, and who? | 68.4 [67.8, 69.0] | 68.3 [67.6, 69.0] | 72.1 [71.3, 72.8] | 72.1 [71.3, 72.8] | 100.0 |

Questions where an answer was given but was wrong (share of decisions, pooled):

- L0 output, input: 1.67% wrong (1.67% from the replay, 0.00% from the record)
- L0 output, sources: 58.01% wrong (58.01% from the replay, 0.00% from the record)
- L1 inputs, sources: 57.92% wrong (57.92% from the replay, 0.00% from the record)
- L0 output, computation: 22.99% wrong (22.99% from the replay, 0.00% from the record)
- L1 inputs, computation: 22.97% wrong (22.97% from the replay, 0.00% from the record)
- L0 output, rules: 5.24% wrong (5.24% from the replay, 0.00% from the record)
- L1 inputs, rules: 5.27% wrong (5.27% from the replay, 0.00% from the record)
- L2 tools, rules: 11.91% wrong (11.91% from the replay, 0.00% from the record)
- L0 output, alternatives: 54.07% wrong (54.07% from the replay, 0.00% from the record)
- L1 inputs, alternatives: 53.95% wrong (53.95% from the replay, 0.00% from the record)
- L2 tools, alternatives: 73.11% wrong (73.11% from the replay, 0.00% from the record)
- L0 output, confidence: 47.46% wrong (47.46% from the replay, 0.00% from the record)
- L1 inputs, confidence: 47.39% wrong (47.39% from the replay, 0.00% from the record)
- L2 tools, confidence: 71.91% wrong (71.91% from the replay, 0.00% from the record)
- L0 output, versions: 61.83% wrong (61.83% from the replay, 0.00% from the record)
- L1 inputs, versions: 61.74% wrong (61.74% from the replay, 0.00% from the record)
- L2 tools, versions: 90.05% wrong (90.05% from the replay, 0.00% from the record)
- L3 steps, versions: 90.05% wrong (90.05% from the replay, 0.00% from the record)
- L0 output, human: 3.42% wrong (3.42% from the replay, 0.00% from the record)
- L1 inputs, human: 3.41% wrong (3.41% from the replay, 0.00% from the record)
- L2 tools, human: 27.93% wrong (27.93% from the replay, 0.00% from the record)
- L3 steps, human: 27.93% wrong (27.93% from the replay, 0.00% from the record)

## E2: Reconstruction as the audit happens later

_Source: `results/e2_audit_delay/20261008T061449Z-f561923` · commit `f56192313b91` · 10 seeds from base 20261008 · 2000 claims per seed · runtime 222.8 s._

All decisions by the clean agent. The audit day is the decision day plus the delay; anything the record lacks is looked up as it is on the audit day. Percent, mean over seeds with 95% CI.

### Route match (replay followed the original path)

| Replay | Level | 0 days | 7 days | 30 days | 90 days | 180 days |
|---|---|---|---|---|---|---|
| Record | L0 output | 69.0 [68.2, 69.7] | 50.7 [49.8, 51.5] | 48.4 [47.6, 49.1] | 43.1 [42.5, 43.9] | 39.5 [39.0, 40.1] |
| Record | L1 inputs | 69.0 [68.4, 69.6] | 50.5 [49.9, 51.1] | 48.3 [47.5, 49.0] | 43.0 [42.3, 43.7] | 39.5 [39.0, 40.0] |
| Record | L2 tools | 91.9 [91.6, 92.3] | 90.9 [90.5, 91.4] | 88.1 [87.4, 88.7] | 80.9 [80.5, 81.3] | 76.1 [75.4, 76.8] |
| Record | L3 steps | 91.9 [91.3, 92.5] | 91.0 [90.6, 91.3] | 88.0 [87.5, 88.4] | 81.0 [80.4, 81.6] | 76.1 [75.5, 77.0] |
| Record | L4 environment | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| Live | L4 environment | 68.7 [67.9, 69.5] | 50.4 [49.6, 51.1] | 48.2 [47.3, 49.0] | 43.0 [42.4, 43.7] | 39.6 [39.0, 40.2] |

### Silent misreconstruction (accepted by the auditor, but the wrong path)

| Replay | Level | 0 days | 7 days | 30 days | 90 days | 180 days |
|---|---|---|---|---|---|---|
| Record | L0 output | 0.0 | 0.4 [0.3, 0.5] | 1.4 [1.2, 1.6] | 4.1 [3.7, 4.4] | 6.3 [5.8, 6.8] |
| Record | L1 inputs | 0.0 | 0.2 [0.1, 0.2] | 0.6 [0.5, 0.7] | 1.5 [1.3, 1.7] | 2.2 [1.9, 2.5] |
| Record | L2 tools | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| Record | L3 steps | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| Record | L4 environment | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| Live | L4 environment | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |

### Fully reconstructed (reproduced or attested)

| Replay | Level | 0 days | 7 days | 30 days | 90 days | 180 days |
|---|---|---|---|---|---|---|
| Record | L0 output | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| Record | L1 inputs | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| Record | L2 tools | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| Record | L3 steps | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| Record | L4 environment | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| Live | L4 environment | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |

### Live replay: first divergent step by delay (decisions)

| Cause | 0 days | 7 days | 30 days | 90 days | 180 days |
|---|---|---|---|---|---|
| config 'claims-agent' | 0 | 1,110 | 4,670 | 11,856 | 11,909 |
| external 'narrative.assess' | 1,041 | 0 | 0 | 0 | 0 |
| human (not recorded for live re-execution) | 5,626 | 5,615 | 5,708 | 5,783 | 5,727 |
| rng 'qa.sample' | 10,428 | 0 | 0 | 0 | 0 |
| tool 'claims_db.get' | 0 | 27 | 225 | 187 | 247 |
| tool 'fx.spot' | 0 | 4,016 | 2,732 | 568 | 502 |
| tool 'holders.profile' | 0 | 6,512 | 4,538 | 950 | 854 |
| tool 'policy_store.get' | 0 | 78 | 242 | 182 | 333 |

## E3: Automated detection of policy violations

_Source: `results/e3_violations/20261008T061832Z-f561923` · commit `f56192313b91` · 20 seeds from base 20261008 · 2000 claims per seed · runtime 209.3 s._

The faulty agent attempts a violation on a share of claims; the type is drawn from 13 kinds, 2 of which (rate_operand_mismatch, evidence_substitution) were held out while the checks were written. 40,000 faulty-agent and 40,000 clean-agent decisions. _Rule_ is the 13-check audit standard run on the trace as stored at each level (falling back to live lookups 30 days later where the level lacks data). _Reference replay_ re-runs the approved agent code on the recorded inputs and flags any divergence. Rates are pooled over seeds with 95% CIs from resampling seeds.

### By level

| Level | Detector | Recall, all violations | Recall, designed-for types | Precision | False positives per 1,000 clean decisions | Flags that needed live data |
|---|---|---|---|---|---|---|
| L0 output | Rule checks | 6.2 [5.7, 6.8] | 7.0 [6.4, 7.6] | 94.4 [91.8, 96.6] | 0.93 | 320 |
| L0 output | Reference replay | 46.7 [45.6, 47.8] | 44.8 [43.5, 46.1] | 32.7 [31.8, 33.5] | 218.88 |  |
| L1 inputs | Rule checks | 15.9 [14.8, 16.9] | 17.7 [16.5, 18.8] | 97.7 [96.7, 98.6] | 0.93 | 320 |
| L1 inputs | Reference replay | 53.2 [52.2, 54.3] | 51.5 [50.4, 52.7] | 26.7 [26.0, 27.4] | 325.43 |  |
| L2 tools | Rule checks | 65.7 [64.3, 67.1] | 69.8 [68.6, 71.0] | 100.0 | 0.00 | 0 |
| L2 tools | Reference replay | 79.4 [78.5, 80.2] | 78.9 [78.0, 79.9] | 42.0 [40.8, 43.0] | 243.22 |  |
| L3 steps | Rule checks | 88.1 [87.1, 89.0] | 94.7 [94.2, 95.3] | 100.0 | 0.00 | 0 |
| L3 steps | Reference replay | 100.0 | 100.0 | 20.5 [20.1, 20.8] | 855.50 |  |
| L4 environment | Rule checks | 92.8 [92.0, 93.5] | 99.9 [99.9, 100.0] | 100.0 | 0.00 | 0 |
| L4 environment | Reference replay | 95.3 [94.9, 95.8] | 94.8 [94.3, 95.3] | 100.0 | 0.00 |  |

### By violation type (recall, percent)

| Violation | Injected | Rule L0 | Rule L2 | Rule L4 | Replay L4 | Sample audit 5% | Sample audit 10% |
|---|---|---|---|---|---|---|---|
| approval_bypass | 137 | 100.0 | 100.0 | 100.0 | 100.0 | 3.6 | 10.2 |
| unsupported_denial | 678 | 0.0 | 100.0 | 100.0 | 100.0 | 6.6 | 8.7 |
| limit_exceeded | 143 | 93.0 | 93.0 | 100.0 | 100.0 | 4.2 | 7.7 |
| calc_input_mismatch | 957 | 16.1 | 80.9 | 100.0 | 100.0 | 5.1 | 8.0 |
| unverified_amount | 305 | 0.3 | 64.3 | 100.0 | 100.0 | 3.6 | 9.8 |
| fraud_escalation_skipped | 59 | 13.6 | 13.6 | 100.0 | 100.0 | 6.8 | 3.4 |
| prohibited_feature | 1,044 | 0.0 | 100.0 | 100.0 | 100.0 | 4.8 | 9.5 |
| stale_rate | 370 | 0.3 | 98.6 | 98.6 | 100.0 | 5.7 | 9.7 |
| unauthorised_tool | 1,067 | 0.0 | 100.0 | 100.0 | 100.0 | 4.8 | 8.6 |
| segregation_of_duties | 329 | 0.3 | 0.0 | 100.0 | 0.0 | 6.1 | 11.6 |
| missing_checks | 1,218 | 0.3 | 0.0 | 100.0 | 100.0 | 4.7 | 9.6 |
| rate_operand_mismatch (held out) | 385 | 0.0 | 57.1 | 57.1 | 100.0 | 5.2 | 10.6 |
| evidence_substitution (held out) | 339 | 0.0 | 0.0 | 0.0 | 100.0 | 5.3 | 10.9 |

### Checks at L4

| Check | Targets | Findings | On a violation it targets | On the clean agent | Decisions evaluable |
|---|---|---|---|---|---|
| approval_limit | approval_bypass | 145 | 137 | 0 | 80,000 |
| denial_basis | unsupported_denial | 678 | 678 | 0 | 80,000 |
| clause_limit | limit_exceeded | 311 | 143 | 0 | 80,000 |
| payout_recompute | limit_exceeded, calc_input_mismatch, unverified_amount | 1,201 | 981 | 0 | 80,000 |
| calc_provenance | calc_input_mismatch, limit_exceeded | 1,100 | 1,100 | 0 | 80,000 |
| verified_amount | unverified_amount | 305 | 305 | 0 | 80,000 |
| fraud_escalation | fraud_escalation_skipped | 69 | 59 | 0 | 80,000 |
| protected_attributes | prohibited_feature | 1,044 | 1,044 | 0 | 80,000 |
| rate_freshness | stale_rate | 365 | 365 | 0 | 80,000 |
| tool_allowlist | unauthorised_tool | 1,067 | 1,067 | 0 | 80,000 |
| segregation_of_duties | segregation_of_duties | 329 | 329 | 0 | 80,000 |
| required_checks | missing_checks | 1,218 | 1,218 | 0 | 80,000 |
| recomputation |  | 0 | 0 | 0 | 80,000 |

## E4: Tamper evidence of the stored log

_Source: `results/e4_tamper/20261008T063552Z-443db66` · commit `443db66ab94a` · 5 seeds from base 20261008 · 300 claims per seed · runtime 671.7 s._

Each seed records a clean run into SQLite (8,709 to 8,999 events per log; 8 anchors) and applies every attack 100 times at random positions. Untampered logs verified as valid: yes. _Detected_ is the share of tampered logs the defence rejects; _located_ is the share of detections that point at the tampered event exactly.

### Detected (percent of trials)

| Attack | Sequence numbers | Hash chain | + signed checkpoints | + external anchor |
|---|---|---|---|---|
| Edit an event | 0 | 100 | 100 | 100 |
| Edit a stored tool output | 0 | 100 | 100 | 100 |
| Delete an event | 0 | 100 | 100 | 100 |
| Insert an event | 0 | 100 | 100 | 100 |
| Swap two events | 0 | 100 | 100 | 100 |
| Truncate the tail | 0 | 0 | 0 | 58 |
| Rewrite suffix, no key | 0 | 0 | 99 | 99 |
| Rewrite suffix, with key | 0 | 0 | 0 | 89 |

### Located exactly / within one checkpoint interval (percent of detections)

| Attack | Sequence numbers | Hash chain | + signed checkpoints | + external anchor |
|---|---|---|---|---|
| Edit an event | n/a | 100 / 100 | 100 / 100 | 100 / 100 |
| Edit a stored tool output | n/a | 100 / 100 | 100 / 100 | 100 / 100 |
| Delete an event | n/a | 100 / 100 | 100 / 100 | 100 / 100 |
| Insert an event | n/a | 100 / 100 | 99 / 99 | 99 / 99 |
| Swap two events | n/a | 100 / 100 | 100 / 100 | 100 / 100 |
| Truncate the tail | n/a | n/a | n/a | 100 / 100 |
| Rewrite suffix, no key | n/a | n/a | 1 / 100 | 1 / 100 |
| Rewrite suffix, with key | n/a | n/a | n/a | 0 / 9 |

### Attacks that only touched events after the last anchor (full defence)

| Attack | Trials | Detected |
|---|---|---|
| Edit an event | 52 | 52 |
| Edit a stored tool output | 54 | 54 |
| Delete an event | 43 | 43 |
| Insert an event | 57 | 57 |
| Swap two events | 55 | 55 |
| Truncate the tail | 211 | 0 |
| Rewrite suffix, no key | 51 | 48 |
| Rewrite suffix, with key | 55 | 0 |

## E5: Cost of instrumentation

_Source: `results/e5_overhead/20261008T063030Z-f561923` · commit `f56192313b91` · 3 seeds from base 20261008 · 2000 claims per seed · runtime 235.3 s._

Median of repeats per seed, then mean over seeds with 95% CI. Machine: x86_64, 4 CPUs; timings are machine-dependent and comparable only within this table.

| Measure | Value |
|---|---|
| Agent without instrumentation, ms per decision | 0.77 [0.73, 0.79] |
| Recording to memory (L4), ms per decision | 2.37 [2.23, 2.56] |
| Recording to SQLite with checkpoints and anchors, ms per decision | 4.59 [4.49, 4.68] |
| Record-mode L4 replay, ms per decision | 1.19 [1.17, 1.22] |
| Chain verification, events per second | 47,408 [44,774, 48,890] |
| Chain, checkpoint and anchor verification, events per second | 47,799 [47,635, 48,107] |
| Events per decision | 29.3 [29.0, 29.5] |
| SQLite bytes per decision (after VACUUM) | 13,650 [13,529, 13,746] |

### Trace size per decision by level (bytes of canonical JSON)

| Level | Inline | With tool outputs stored once as blobs |
|---|---|---|
| L0 output | 372 [372, 372] | 372 [372, 372] |
| L1 inputs | 1,330 [1,329, 1,332] | 1,330 [1,329, 1,332] |
| L2 tools | 4,873 [4,840, 4,903] | 4,583 [4,549, 4,619] |
| L3 steps | 8,779 [8,703, 8,835] | 8,488 [8,412, 8,551] |
| L4 environment | 9,520 [9,438, 9,580] | 9,230 [9,147, 9,296] |

## Trust study with people

Status: pending. The audit-question results above are a proxy for whether a trail supports trust; no study with human auditors has been run (protocol in docs/STUDY.md).

