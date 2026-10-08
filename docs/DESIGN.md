# Design: "Casefile", a forensic replay interface

## Visual concept

A forensic workstation crossed with a step debugger. An auditor opens a case file (one recorded decision) and steps through it like a debugger:

- the timeline on the left is the call stack;
- the centre pane shows the current step's inputs, outputs and recomputation;
- a watch panel on the right shows how the decision's state variables change.

Every step carries a verification mark from the replay engine. The tone is a quiet evidence room: paper-white or graphite surfaces, hairline rules, monospace for anything that is evidence, and one restrained teal accent for focus and the current step. Divergence and violation states are reserved and always carry a shape and a word as well as a colour.

| Forensic element | Interface element |
|---|---|
| Case files | Decision list with filters (decision type, verification status, violations, outcome) |
| Evidence bench | Replay view: timeline, step inspector, watch panel, record vs live comparison |
| Incident board | Violations: detector findings grouped by rule, each linked to the step that triggered it |
| Seal and custody | Integrity: chain verification, signed checkpoints, external anchors, and a tamper lab that attacks a copy |
| Lab notebook | Experiments E1 to E5 and the method notes |

## Information architecture

```
Cases        /cases                      decision list (default)
Replay       /cases/:id?step=n&mode=record|live
Violations   /violations                 findings by rule and type
Integrity    /integrity                  chain, checkpoints, anchors, tamper lab
Experiments  /experiments?exp=e1..e5
Method       /method                     levels, decision types, definitions, limits, pending study
```

**Primary interaction:** open a case, press `n`/`p` (or `j`/`k`) to step, `f` to jump to the first divergence, and `v` to jump to the next violation. Toggle record and live replay to see what has drifted since the decision.

## Navigation model

- A top bar holds the product mark, a world/seed selector, chain status (intact or broken, with shape) and a theme toggle.
- Section tabs sit below it.
- The replay view is three panes on desktop (timeline | inspector | watch). On tablets the watch panel folds under the inspector. On mobile the timeline becomes a horizontal step scrubber above the inspector, with the watch panel below.
- Every case, step and mode is in the URL, so a finding can be linked exactly.

## Typography

- **Inter** (400/500/600) for interface text; **JetBrains Mono** (400/500) for ids, hashes, amounts, expressions, payloads and timestamps.
- Scale (px): 12 / 13 / 14 (body) / 16 / 20 / 26. Line height 1.45 for UI and 1.55 for prose. Tabular numerals in every numeric column.

## Color tokens

Follows the OS theme unless one is chosen; both themes are first class.

| Token | Light | Dark | Use |
|---|---|---|---|
| `--page` | `#f5f5f3` | `#111213` | page plane |
| `--surface` | `#ffffff` | `#18191b` | panels |
| `--surface-2` | `#efefec` | `#202124` | headers, code, inputs |
| `--ink` | `#121314` | `#ededec` | primary text |
| `--ink-2` | `#45474b` | `#b8b9bc` | secondary text |
| `--ink-3` | `#63656a` | `#8e9095` | muted labels (AA on surface) |
| `--rule` | `#e1e1dd` | `#2c2d30` | hairlines |
| `--accent` | `#0f6e68` | `#5fb8ae` | focus, current step, links |
| `--accent-weak` | `#e3f0ee` | `#1b2e2c` | current-step background |
| `--ok` | `#2f6b3a` | `#7cbf86` | reproduced ✓ |
| `--attest` | `#8a5a12` | `#d9a85a` | attested only ◐ |
| `--bad` | `#b3261e` | `#f0887f` | diverged ✕, violation, broken chain |

Status colours never stand alone: each pairs with a glyph (✓ ◐ ✕ ▲) and a word.

## Spacing, shape and components

- **Spacing:** 4-px base scale (4, 8, 12, 16, 24, 32, 48).
- **Shape:** radius 6 on panels and 4 on controls. Hairline borders, no shadows except a 1-px focus ring.
- **Components:**
  - step rows (index, kind glyph, name, verification mark);
  - key–value evidence tables;
  - an expression card (formula, operands, recorded vs recomputed);
  - a diff row (recorded vs replayed);
  - hash chips (first 10 hex characters, full hash on focus or hover, copy button);
  - segmented controls; pills for decision type.

## Data visualisation

- Interval plots (dot + 95% CI) for rates by level and decision type.
- Line charts for reconstruction against audit delay (one line per level, direct labels).
- A heat table for the attack × defense matrix, with the number and a glyph in each cell.
- A categorical palette of 5 restrained hues for levels L0–L4, ordered light to dark in one hue family plus the accent, so order reads as "more instrumentation".
- Every chart has a table twin and keyboard-reachable values.

## Motion

Only to orient: the current-step highlight slides in 120 ms, and the watch values flash once (accent background, 400 ms) when a step changes them. Motion is disabled under `prefers-reduced-motion`.

## States

- **Loading:** skeleton rows sized like the content; no spinners over 300 ms without text.
- **Empty:** a sentence saying why the view is empty (no decisions match the filters, the experiment has no completed run) and how to fill it.
- **Error:** a panel with the API's message, a Retry button and `role="alert"`. Unknown cases and steps get a specific not-found message.

## Responsive behaviour

Breakpoints at 1100 px (three panes become two) and 720 px (single column, step scrubber). No horizontal page scroll at 360 px. Tables scroll inside their own container with a sticky first column.

## Accessibility

- WCAG 2.1 AA contrast in both themes.
- Semantic landmarks, one `h1` per view, and a skip link.
- The timeline is a listbox with arrow-key navigation, and the current step is announced through `aria-live="polite"` in the inspector heading.
- Visible focus rings.
- Every keyboard shortcut has a button equivalent.
- axe-core runs in the browser test suite for every view in both themes and viewports.
