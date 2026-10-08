# Study protocol: does an audit trail support trust?

**Status: pending.** No participants have been recruited and no data collected. Nothing in this repository reports results of this study. The audit-question measure in E1 is a proxy for one part of it (can the questions an auditor asks be answered correctly from the record?), not a measure of trust.

## Question

When people review an agent's decisions, does access to a step-by-step audit trail change:

- how well their trust is **calibrated**: relying on correct decisions and challenging wrong ones;
- whether they find the agent's errors;
- how long a review takes?

## Design

A within-subjects study with three conditions, counterbalanced with a Latin square:

1. **Outcome only (L0):** the decision, amount and date.
2. **Rationale (L1):** adds the input claim and the agent's one-line rationale.
3. **Full trail (L4 in Casefile):** the replay console with steps, recomputation, findings and the record-versus-replay comparison.

**Participants:** claims handlers or auditors (target 24), or, failing that, students with a short training module (reported separately).

**Materials:**
- 36 decisions drawn from the demo deployment and stratified by decision type.
- 12 of them carry an injected violation, including the two held-out kinds.
- Ground truth comes from the simulation.
- Each participant sees 12 decisions per condition, with no decision repeated.

**Task:** for each decision, answer:
- "Is this decision correct and policy-compliant?" (yes, no or unsure);
- a confidence rating from 1 to 7;
- for "no", which step is wrong.

## Measures

- **Appropriate reliance:** accepting compliant decisions plus rejecting violating ones, over all decisions.
- **Detection:** recall and precision of violation reports, and step-localisation accuracy.
- **Calibration of participant confidence:** Brier score against correctness.
- **Time per decision.**
- **Trust questionnaires:** a validated trust-in-automation scale, and a short post-condition questionnaire on perceived transparency.

## Analysis plan

- Mixed-effects logistic regression for correctness, with condition as a fixed effect and participant and decision as random intercepts.
- Linear mixed models for time (log) and Brier score.
- Pre-registered contrast: full trail against rationale.
- Pre-registered secondary contrast: rationale against outcome only.
- Planned sample: power analysis to be done on a pilot of 6 participants. The target of 24 is a placeholder until then.

## Ethics

- Ethics review is required before any recruitment.
- No personal data is used: all claims are synthetic.
- Responses are stored without identifiers, and participants can withdraw.

## What would change our conclusions

- If the full trail improves detection but makes participants over-trust attested steps (adjuster or external-service answers), the console should present attested steps differently.
- If time per decision rises without a gain in detection, the trail is evidence for auditors and investigators, not a review aid.
