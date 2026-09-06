# LAB016 coherent Model I/O retention

Fresh Codex engineering task after LAB015 CLOSED/source-review PASS, integration HOLD. Source-only public branch lineage; no scientific/runtime authorization change. Exact basis499a09d over publicd1c4; existing owned lab/ui-provenance-20260905-014 checkout and PR5. Standing native Git/PR maintenance authority applies. BOUNDARY.md is absent from this repository; no new runtime or research task is inferred.

Exact allowed paths before source edits:
- ui/frontend/src/routes/ModelIO.tsx
- ui/frontend/tests/test_session_thread.tsx
- ui/frontend/docs/UI_MODELIO_RETENTION_20260906_016.md

Required: preserve all loaded thread turns in every committed live/retained feed transition, including split pages and duplicate identities. Preserve chronology, boundaries, gaps, query isolation, pause/resume, expanded rows and failed/late reads. Add HQ's deterministic Profiler regression without changing existing four-turn assertions; exercise filter changes and duplicate slices. A Profiler commit is not a physical-paint measurement.

Accepted2026-09-06T01:06:57Z; code target01:26:57Z, terminal01:36:57Z. At most two production attempts and one eight-minute task-only read-only preparation lane, no fanout. Focused and typecheck/build <=120s each; at most two full frontend runs <=120s, only on materially changed candidates. Preserve negatives; stop recurring unexplained failures or scope conflict. Use pinned private loop fixture and installed dependencies.

Plan: reproduce deterministic intermediate loss first; implement a minimal coherent feed transition in the existing module; retain original tests and add transition/filter/duplicate coverage; run focused, build and full frontend validation; parent source review and exact manifest; linear commit/push to existing draft PR5; terminal to HQ for fresh independent whole-range review. No pollhub/controller/cache/fetch architecture change, live model logs, backend/action writer, model calls, service changes, merge or adoption. Recovery retains the unmerged candidate and evidence.


## Result

ModelIO computes retained slices alongside the incoming live page and uses that same pure transition for passive persistence. Loaded identified turns stay in one chronological session card through the tested commits, including shorter replacement slices with overlapping request IDs. The change preserves existing call/thread identity folding and the existing gap heuristic; it does not invent identities for anonymous rows.

Each existing table result now carries its originating query key as local bookkeeping. That prevents an old hook snapshot from being relabeled after a filter change. Retained pages are withheld immediately across queries; an old boundary cannot page a pending new query. Existing older-page callbacks check their query and reset generation before changing rows, boundary or pager. No endpoint, request count, pollhub, action writer or backend schema was changed.

The original four-turn assertions remain intact, with the HQ Profiler diagnostic strengthened to require four turns in every observed replacement-page commit. New cases cover overlapping thread slices, chronological/unique identified turns, preserved expansion, filter isolation, pending boundaries, late successes/failures, pause/resume, failed current polls and paging reset. These are React DOM commit observations, not physical-paint measurements.

Validation on September6,2026: 66 focused tests passed; typecheck/build passed; the first and only full frontend run after this production repair passed all1,338 tests across87 files, with zero skips/failures/errors. Existing bundle-size warning remains. The original diagnostic failed before repair with committed counts[2,4]. Expanded red tests also reproduced stale filter/page behavior. One added test initially rejected an unconsumed deferred fixture; request sequencing was corrected, and the negative log retained. No assertion timeout was enlarged and no original assertion was weakened. Old LAB015 full-suite failure and all historical evidence remain archived.

One production implementation attempt was used. All26 prior LAB015 changed paths and the private pinned loop fixture remain byte-identical. Candidate delivery is a linear update to draftPR5, pending fresh independent whole-range HQ review. No merge, source adoption, service change, model call, experiment, human ruling or worker acceptance occurred.
