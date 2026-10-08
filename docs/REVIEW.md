# Internal review board

Seven reviewers read the code, the experiments and the console before release. Each finding has a status:

- **fixed:** changed in code, with the commit or test that shows it;
- **verified:** checked and found correct, no change needed;
- **accepted:** a known limitation, documented where a reader will see it;
- **open:** not resolved.

This is a self-review carried out by the author against each reviewer's brief, not review by independent people.

## Research reviewer

| # | Finding | Status |
|---|---|---|
| R1 | E4 showed the hash chain catching only 98% of `edit_event` attacks. The attack generator sometimes made no change at all (halving a zero amount), and an unchanged log was counted as "undetected". `_edit` now always changes the event and asserts that it did (`test_edit_attack_always_changes_the_event`). E4 was re-run; the old run is kept and marked superseded (D19). | fixed |
| R2 | "L4 reconstructs 100%" is true by construction once the SDK records every non-deterministic input. The report must not present it as an empirical finding. REPORT.md §4 separates definitional from measured results. | fixed |
| R3 | Rule-check recall (92.8% over all kinds, 99.9% on designed-for kinds) is optimistic, because 11 of 13 violation kinds were known when the checks were written. Two kinds are held out and reported separately. | accepted |
| R4 | The trust research question cannot be answered without people. The audit-question accuracy is labelled as a proxy throughout, and the human study is a protocol only (docs/STUDY.md, *Status: pending*). | open |
| R5 | The agent is not a language model, so "steps" (L3) are explicit computations. REPORT.md §6 states which parts of the SDK would carry over to an LLM agent. The LLM experiment is *Status: pending*: no model API key is available. | open |
| R6 | E3 reports rule checks and reference replay separately, but not their union, which is what a deployment would run. Noted in REPORT.md as not measured. | accepted |
| R7 | Seeds and intervals: E1 and E2 use 10 seeds and E3 uses 20, with 95% bootstrap CIs; rare events are pooled over seeds and reported as counts. | verified |

## Engineering reviewer

| # | Finding | Status |
|---|---|---|
| E1 | Replays were not bit-exact at first: floating-point round-trips through JSON and wall-clock fields made record-mode L4 replays diverge. Fixed with canonical number encoding and volatile-field handling (D11, D12); E1 now reproduces every L4 decision. | fixed |
| E2 | Result directories were named after the commit even when the working tree had uncommitted changes to the code. `_commit` now appends `-dirty` when `src`, `configs`, `pyproject.toml` or `uv.lock` differ from HEAD. | fixed |
| E3 | Full verification is O(n) in the number of events (0.33 s for the 17,708-event demo log; about 47,000 events per second in E5). Incremental verification from the last good checkpoint is future work. | accepted |
| E4 | `research/` is generated. CI re-runs `agentaudit report` and fails if the generated tables differ from the committed files, so the report cannot drift from the runs. Figures are not compared: project 02's CI showed SVG layout changes with the installed fonts. | fixed |
| E5 | Empty values in `.env` (for example `AGENTAUDIT_DB=`) were treated as paths. `default_paths` now treats empty values as unset. | fixed |

## QA reviewer

| # | Finding | Status |
|---|---|---|
| Q1 | Pressing n then p quickly in the replay stepped from a stale position. Key handling now reads the current step from a ref. Covered by `test_replay_steps_like_a_debugger`. | fixed |
| Q2 | No test showed that the integrity endpoint notices a change made to the database outside the API. `test_integrity_detects_an_out_of_band_edit` edits event 200 directly in SQLite and expects `first_bad_seq == 200`. | fixed |
| Q3 | Tests: 36 Python tests (core, SDK, replay, detection, tamper, API) and 27 browser tests (all pages on desktop and mobile, replay keyboard stepping, tamper lab, filters, not-found, axe-core in both themes). | verified |

## Security reviewer

| # | Finding | Status |
|---|---|---|
| S1 | `GET /api/integrity` re-verified the whole log on every request, so any client could keep a CPU busy. Results are now cached for 5 seconds behind a lock, and the response says how old the result is. | fixed |
| S2 | `agentaudit serve --host 0.0.0.0` would expose the API without authentication if no token was set. It now refuses to start on a non-loopback host without `AGENTAUDIT_API_TOKEN` (`test_serve_refuses_a_public_host_without_a_token`). | fixed |
| S3 | npm audit reported advisories in the Vite and esbuild dev server. Upgraded to Vite 6.4.3; `npm audit` reports 0 vulnerabilities. `pip-audit` reports none. | fixed |
| S4 | The checkpoint signing key must be at least 32 bytes and is read from the environment or a file outside the repository; none is committed. The bearer token is compared in constant time. | verified |
| S5 | The rate limiter is keyed by client IP, in memory and per process. Behind a proxy all clients share one bucket, and limits reset on restart. Adequate for a local forensic tool. | accepted |
| S6 | The demo exposes `simulation_truth` (decision type, injected violation) through the API, so the console can show ground truth. A real deployment would not have this table. It is labelled "Simulation truth" wherever it appears. | accepted |
| S7 | The witness in the demo is a local file. Its protection from the operator is assumed, not tested; REPORT.md says so. | accepted |
| S8 | The API is read-only: replays use a rebuilt copy of the simulated world, and the tamper lab attacks an in-memory copy (`test_integrity_and_tamper_lab_never_write`). | verified |

## UX reviewer

| # | Finding | Status |
|---|---|---|
| U1 | The half-filled circle used for "attested" rendered as a different glyph or tofu in some fonts. Replaced with an inline SVG. | fixed |
| U2 | axe-core found scrollable tables that could not be reached by keyboard, low contrast on the attested mark over heat-map cells, and on the current step in the timeline. All fixed; axe passes in both themes at both viewports. | fixed |
| U3 | Loading, empty and error states exist on every page and are exercised by the browser tests. | verified |

## Recruiter

| # | Finding | Status |
|---|---|---|
| C1 | The README must lead with what was found, not with what was built. The key findings section quotes the generated results with their run ids. | fixed |
| C2 | Screenshots are taken by the browser tests from the running console, not mocked. | verified |

## PhD supervisor

| # | Finding | Status |
|---|---|---|
| P1 | The most interesting result is not that L4 works but how partial records fail: L3 diverges on 85.5% of decisions because the model version is missing, and replay-derived answers are confidently wrong. The report leads with these. | fixed |
| P2 | A third of all decisions are only attested even at L4. That ceiling is set by humans and opaque services in the loop, and should be stated as a limit of replay-based auditing. REPORT.md RQ2 and §5. | fixed |
| P3 | Drift parameters are chosen, not estimated from a real deployment, so the decay curves in E2 show the mechanism, not real-world rates. Stated in §6. | accepted |
