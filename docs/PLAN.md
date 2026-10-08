# Plan: Agent Decision Audit Trail

## 1. Scope

Make an autonomous agent's decisions traceable and auditable. For every decision the system records:

- input, context, evidence and sources, tools used, calculations, intermediate decisions;
- confidence, applied policy rules, alternatives considered, final decision;
- human intervention and outcome.

Records go into a tamper-evident, hash-chained log.

Deliverables:

1. **Audit SDK / middleware** (`agentaudit.sdk`). It instruments a Python agent with a decision context, audited tool wrappers, recorded calculations, rule evaluations, model inferences, random draws and human interventions. Context propagation means tools called anywhere inside a decision are captured without passing a handle around.
2. **Storage schema** (`agentaudit.store`). SQLite tables for decisions, events (hash-chained), content-addressed blobs for tool outputs and source snapshots, and signed checkpoints, plus an external witness file for head-hash anchoring.
3. **Replay engine** (`agentaudit.replay`). Re-runs the agent's code against the trace (record mode: tool outputs and other non-deterministic inputs come from the trace) or against the live environment at audit time (live mode). It compares the replayed event sequence to the recorded one step by step, recomputes every calculation and rule and reloads the recorded model version. It reports the first divergence.
4. **Policy-violation detector** (`agentaudit.detect`). Declarative YAML rules evaluated over traces, plus trace-completeness checks.
5. **A working agent to instrument** (`agentaudit.agents.claims`). An insurance-claims adjudication agent operating in a simulated world (`agentaudit.world`) with policies, claims, documents, an exchange-rate service, a fraud model that is retrained over time, a free-text "narrative assessor" that behaves like an external non-deterministic model, and human adjusters.
6. **Forensic replay interface** (`web/`). Step through a decision like a debugger.
7. **Experiments E1 to E5**, a research report and the documentation set.

## 2. Research questions and hypotheses

| RQ | Question | Hypothesis | Experiment |
|---|---|---|---|
| RQ1 | Can decisions be fully reconstructed? | With full instrumentation (tool outputs, intermediate steps, environment: model and policy versions, seeds), record-mode replay reproduces ≥ 99% of decisions step by step. Output-only logging reproduces far fewer, and the share falls with audit delay. | E1, E2 |
| RQ2 | Which decision types resist auditing? | Decisions that depend on mutable external data, stochastic choices, retrained models, an opaque external judgment or a human are the hardest. The first three become reconstructable once the environment is captured; the last two can only be *attested*, not re-derived. | E1, E2 |
| RQ3 | Does an audit trail support trust? | Proxy: the share of standard audit questions (who, what, when, which evidence, which rule, which alternatives, which model version, was a human involved) that can be answered correctly from the trace rises with instrumentation level. Trust itself needs a study with people: **Status: pending**. | E1 (answerability) |
| RQ4 | Can policy violations be detected automatically? | Rule-based detection over full traces finds injected violations with recall ≥ 0.95 and few false positives on a clean agent. With output-only logs most violation types are undetectable. Random sample audits recover only their sampling fraction. | E3 |
| (integrity) | Is the log tamper-evident, and against whom? | A hash chain detects edits, deletions, insertions and reordering but not a full-chain rewrite. Keyed checkpoints detect rewrites by an attacker without the key. An external anchor detects rewrites even with the key, up to the last anchor. | E4 |
| (cost) | What does instrumentation cost? | Full instrumentation adds milliseconds per decision and a few kB of storage after blob deduplication. | E5 |

**Baselines:**
- Reconstruction: output-only logging (L0), which is typical application logging.
- Violations: an output-only checker, and random sample audits at matched human effort.
- Tamper evidence: a plain table with no chain.

## 3. Instrumentation levels (ablation)

| Level | Recorded |
|---|---|
| L0 output | decision id, input id, final decision, timestamp |
| L1 inputs | + full input payload and final rationale |
| L2 tools | + every tool call with arguments and outputs (content-addressed), evidence with source references |
| L3 steps | + calculations with operands, rule evaluations, model inferences (features, score), confidence, alternatives, intermediate decisions |
| L4 environment | + agent code hash, policy hash, model version, RNG seeds, data-snapshot versions, human identity and rationale, external-service request ids |

The same agent run produces all five traces: the SDK writes the full trace, and each level is a projection of it. Levels therefore differ only in what was kept, never in which decisions were made.

## 4. Simulated world and agent

Data are synthetic, which is justified because the experiments need ground truth that no public dataset provides:

- which inputs actually determined each decision;
- which violations were injected;
- how the environment changed after each decision.

Parameters are documented in `data/DATASET.md`. A world covers 180 simulated days:

- **Policies:** travel, home contents and gadget products, each with clause limits, a deductible, exclusions and validity dates. Policy documents are **revised** at random dates, so the live store returns the latest version.
- **Claims:** category, amount and currency, incident and submission dates, and attached documents (receipts, police reports) that may disagree with the claim. Some claims are **amended** after a decision.
- **Exchange rates:** a daily random walk per currency, so the "live" rate drifts.
- **Fraud model:** gradient boosting **retrained every 30 days** on the claims resolved so far. All versions are kept in a model registry.
- **Narrative assessor:** scores the claim's free-text description through a stand-in for an external model API. It is non-deterministic and has no seed control; only its output can be recorded.
- **Adjusters:** simulated people who decide escalated claims and write a rationale.
- **QA sampling:** 5% of auto-decisions are randomly selected for a second look.

**Claims agent:** intake → policy lookup and validity → coverage and exclusion rules → document verification → currency conversion → payout calculation → fraud score → narrative assessment (for long descriptions) → confidence → alternatives → governance rules → decision (pay, partial pay, deny, escalate) → human adjuster for escalations → outcome.

**Decision types** are labelled from the path the decision actually took, by the agent itself as ground truth:

| Type | Decisive element |
|---|---|
| rule | coverage or validity rule alone (e.g. denied as excluded) |
| calculation | straight-through payout from verified amounts |
| fx | foreign-currency payout (depends on an exchange rate) |
| model | fraud score within a margin of its threshold |
| stochastic | QA sampling or a random tie-break changed the path |
| opaque | the narrative assessor's output changed the path |
| human | an adjuster decided |

## 5. Experiments

All experiments are config-driven (`configs/*.yaml`) with logged seeds. Each writes `results/<exp>/<UTC timestamp>-<commit>/`. The plan is 10 seeds (worlds) × 2,000 claims, and CIs are bootstrapped over seeds.

- **E1 Reconstruction × level × decision type.** Record-mode and live-mode replay at an audit delay of 30 days. Metrics:
  - reproduced, attested-only, diverged or not reconstructable;
  - first-divergence step type;
  - answerability of 8 audit questions.
- **E2 Audit delay.** Live-mode replay at delays of 0, 7, 30, 90 and 180 days per level, plus the drift source of each divergence.
- **E3 Violation detection.**
  - A faulty agent variant injects 10 violation types, each at 3% per eligible decision. Labels go to an oracle file, never into the trace.
  - The detector runs at each level and reports precision, recall and F1 per type.
  - Comparisons: an output-only checker; random sample audits at 5% and 10% with a perfect auditor (an upper bound for sampling); false positives on the clean agent.
- **E4 Tamper evidence.**
  - Attacks: edit payload, delete event, insert forged event, reorder, truncate tail, full rewrite without the key, full rewrite with the key.
  - Defenses: none, hash chain, chain + HMAC checkpoints, chain + checkpoints + external anchor.
  - Metrics: detection rate and localisation (first bad sequence number reported correctly).
- **E5 Overhead.** Wall time per decision with and without instrumentation, storage bytes per decision per level, and chain verification throughput.

## 6. Risks and dependencies

| Item | Status |
|---|---|
| LLM agent / API key | Not available. Not needed: the narrative assessor stands in for an opaque external model and is labelled as such. An LLM agent instrumented with the same SDK is future work. |
| Human study on trust | Unobtainable here. Protocol in `docs/STUDY.md`; **Status: pending**. |
| Results being "by construction" | Some outcomes follow from what each level records. The experiments quantify how often each case occurs in a realistic mix, how it changes with audit delay, and whether the engine and detector actually work, including on traces they were not designed around (faulty agent). The report states which results are definitional. |
| Compute | 4 CPU cores; each experiment is sized to finish within minutes. |

## 7. Stack

- **Core:** Python 3.11+, numpy, scikit-learn (fraud model), pydantic v2, PyYAML.
- **API:** FastAPI + uvicorn, with SQLite for storage.
- **UI:** React 18 + TypeScript (strict) + Vite.
- **Tests:** pytest, Playwright with axe-core.
- **Tooling:** uv and npm lockfiles; ruff and mypy (strict); ESLint; GitHub Actions.
