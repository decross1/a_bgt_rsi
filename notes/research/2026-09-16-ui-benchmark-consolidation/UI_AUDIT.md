# Oracle Lab UI cleanup verification — 2026-09-16

## Outcome

The cleanup now presents four primary destinations: **Now, Research, Benchmarks, and Operations**. Records and Evaluations remain reachable as Research archive views, and legacy deep links still resolve. The standalone graph redirects to bounded Trace history because its source IDs did not support a reliable graph/detail contract.

Research leads with the current thesis, then source-bound evidence, criticism, learning status, and next agenda. The three current member records use distinct evidence-derived titles:

- Payoff arithmetic and strategic consistency (`iter-2026-09-15-007`)
- Seat-indexed action tables (`iter-2026-09-15-008`)
- Future retaliation and joint payoff (`iter-2026-09-15-009`)

The parent title, “Strategic consistency: arithmetic, action tables, and retaliation,” remains the collection label. Exact IDs remain visible as provenance instead of serving as primary titles.

The selected journey is fetched only for the selected iteration. Exact ID, scope, component-lifetime, and stale-response checks prevent one record from being shown under another. No bulk hydration of the historical corpus was added.

## Truth and workflow boundaries

The Research view distinguishes a campaign pointer from execution. It does not imply that completed iterations with pending recorded stages are queued or running. The proposed application agenda is labeled **proposed** and **not yet preregistered**; options are preferred, prediction markets are next, and crypto requires a justified mechanism. Data-access requirements remain inside each lane's requirements.

A workflow mismatch was found during the live audit: `/api/human_todo?research_scope=active` contained 0 items, the all-history queue contained 289 items, and neither queue contained 007–009, while seven coordinator-cycle records mentioned those IDs in prose. Those bubbles had no typed iteration membership. The captured evidence is in `gate-workflow-evidence.json`.

The frontend now refuses to turn an `iter-*` prefix or coordinator prose into an action. An unqueued preserved iteration remains readable and interrogable, but it has no verdict form, terminal command, or defer control. Its overview says that `pending` is a recorded gate stage and does not establish a human-action request. The coordinator source was subsequently aligned upstream so it requests open-thread verdicts only when a nonempty experiment outcome makes the item eligible for the human queue; the isolated preview backend was intentionally not restarted after that source change.

A direct dossier cannot currently prove current-campaign membership from its journey payload. It therefore keeps the safe **All research history / Preserved archive** boundary even when reached from the current thesis. A future current-scope presentation needs a source-bound campaign identity from the backend; route parameters or ID shape are insufficient.

## Consolidation completed

| Decision | Result |
|---|---|
| Keep | Atlas shell, grouped navigation, theme control, command palette, Model I/O list/detail, Operations overview, exact record detail routes. |
| Merge | Selected journey evidence and next-step context now live in the Research canvas and single Dossier overview. |
| Merge | Records and Evaluations are Research archive links rather than competing primary destinations. |
| Merge | Benchmarks leads with the versioned fixed canary, prospective progress, evidence layers, dated arm history, and matched per-construct signals. Older diagnostics remain in an expandable evidence catalog. |
| Move | Coordinator history was removed from Evaluations and remains in bounded Trace history. |
| Retire | `/graph` redirects to `/cycles`; the misleading disconnected graph and broken drill-down were removed. |
| Delete | Unused `OweStrip.tsx`, `ClusterPeek.tsx`, graph components, and their unused graph dependencies were removed after static reachability checks. |

## Visual and interaction verification

The original audit covered every canonical route, the compatibility redirects, representative record/evaluation/call/chain detail states, narrow reflow, dark theme, drawer keyboard behavior, and the command palette. The post-cleanup captures exercise the changed Research, Record archive, Dossier, Evaluations, Trace, graph redirect, Benchmark, narrow, dark, and keyboard states.

Final focused evidence:

- `23-research-thesis-first.png` — current thesis precedes the proposed agenda; all three member titles are distinct; the selected claim states that no human-action request is inferred.
- `24-record-detail-readonly-gate.png` — one H1 overview with question, what happened, qualified learning, and a next step that treats pending as a recorded stage.
- `24b-record-detail-readonly-resolution.png` — the explicit read-only queue boundary, with no verdict, CLI, or defer control.
- `25-command-palette-keyboard.png` — Ctrl+K opens the dialog, and focus lands on an input named “Search commands.”
- `26-research-agenda.png` — the agenda says “not yet preregistered”; data requirements stay in disclosure content.

No accepted capture has horizontal document overflow. The final Firefox sessions used for each capture were closed.

## Remaining product risks

1. Trace history is bounded to recent cards, but one coordinator topic can still contain enough prose and absolute local paths to dominate a viewport. The next cleanup should summarize each card and reveal raw diagnostics on demand.
2. The Record archive is bounded, but some preserved claim prose remains too dense for quick scanning. A compact claim/disposition/evidence/last-event row would improve it without rewriting history.
3. The production bundle is about 1.317 MB minified (363 KB gzip) and still triggers Vite's 500 KB chunk warning. Route-level code splitting is a worthwhile performance follow-up.
4. Screenshot and DOM inspection do not establish full screen-reader announcements, computed contrast, 200–400% zoom behavior, reduced-motion behavior, or every write-action error path. These need an assistive-technology pass.

Independent benchmark read-model review found three truth-boundary issues: the latest-cohort progress state used global historical eligibility, pending cohort ordering lacked registration time, and withheld rows could retain an unverified snapshot label or policy. The backend owner corrected all three. A final frontend contract check also found that fail-closed stable-runtime rows were discarded before the needs-review state could render. Pulse now accepts the backend's bounded display-only unknown shape while keeping exact run ID and phase checks for active resident claims.

## Verification

- `npm run typecheck` — passed.
- `npm test -- --run` — 106 files, 1,598 tests passed.
- `npm run build` — passed; only the existing large-chunk warning remains.
- `node ui/scripts/component-inventory.mjs` — 144 source files, 138 reachable, no unresolved imports, no production deletion candidates.

Artifacts in this directory contain the post-cleanup screenshots, matching DOM snapshots, capture summaries, and the bounded gate-workflow evidence snapshot. The parent `audit-report.md` and `route-coverage.json` contain the full initial route audit and its 25 accepted captures.

## Artifact location

All screenshot names above are relative to:

`/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-16/ui-benchmark-eight-hour/ui-audit/post-cleanup/`

The initial route audit is `../audit-report.md` and its machine-readable coverage is `../route-coverage.json`. These are local review artifacts, not research results.
