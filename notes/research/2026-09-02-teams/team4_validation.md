# Team 4 validation — 2026-09-03

Spawn: `codex-team4-ui-review-20260903`
State basis: `56c1b3abae968c8288471b30946000c29ae6f228`

## Cache accounting

- Journal: 479 rows, 1,094,701 bytes.
- Events: 247 starts, 103 failures, 129 results.
- Canonical unique results: 114.
- Unique work represented: 38 page/lens sweeps, three owner-flow traces,
  thirteen comparable-product passes, three color/docs passes, and 57
  refuters.
- Gap: the tokens `pattern-color-a11y` lens never returned; its `c`, `d`, `h`,
  and composite are unsupported.

The primary independently reproduced the journal counts, verified no diff in
`ui/` or `ui_plan.md` from `d1c4a6e`, enumerated the temporary screenshot
directory, checked representative dimensions, and visually inspected Graph,
Cycles, and Experiment detail.

Correct screenshot root:

`/tmp/claude-1000/-home-decross1-projects-a-bgt-rsi/fb6a3b4d-c6c2-437e-8b34-f1160d6a5099/scratchpad/ui_shots/`

The child initially named an equivalent path under the transcript tree. That
path did not exist; a validation follow-up supplied the extant temporary root.

## Scorecard

| Rank | Surface | Composite |
| ---: | --- | ---: |
| 1 | Graph | 12.0/48 |
| 2 | Cycles | 17.3/48 |
| 3 | Experiment detail | 17.3/48 |
| 4 | Inspector | 17.3/48 |
| 5 | Model I/O | 17.5/48 |
| 6 | Experiments | 18.0/48 |
| 7 | Channel | 18.7/48 |
| 8 | Dossier index | 19.0/48 |
| 9 | Dossier reader | 20.0/48 |
| 10 | Ladder | 21.3/48 |
| 11 | Pulse | 23.0/48 |
| 12 | Shell | 24.5/48 |
| — | Tokens | unsupported |

Inspector ties the third score, but Graph, Cycles, and Experiment detail are
the stable weakest-three cut used for mockups.

## Contract checks

| Check | Verdict | Evidence |
| --- | --- | --- |
| HEAD identity | PASS | Child and primary resolved the contracted SHA. |
| Cache counts | PASS | Recomputed directly from `journal.jsonl`. |
| Screenshot inventory | PASS after correction | Extant temporary root enumerated; representative images inspected. |
| Thirteen-surface scorecard | PASS | Token gap is explicit rather than imputed. |
| Findings/refuters | PASS | Ranked anchors distinguish majority-kept, qualified, and unrefuted evidence. |
| Three owner flows | PASS | Gate, agenda, and bubble paths have measured before states and bounded targets. |
| Work order | PASS | Appended to `human/sessions/2026-09-03.md` with path boundaries and acceptance checks. |
| Three mockup briefs/assets | PASS | Separate versioned PNGs generated and inspected. |
| Read-only boundary | PASS | Child wrote no files; primary alone materialized outputs. |
| Closure protocol | PASS | Exact sentinel and run-log-shaped row returned. |

## Outputs

- `human/sessions/2026-09-03.md` — future UI-session work order
- `mockups/2026-09-03-graph-recent-work-map.png`
- `mockups/2026-09-03-cycles-audit-timeline.png`
- `mockups/2026-09-03-experiment-outcome-reconciliation.png`
