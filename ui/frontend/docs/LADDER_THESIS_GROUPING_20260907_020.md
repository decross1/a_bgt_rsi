# Ladder topic collections — implementation plan

The Ladder currently starts with individual record IDs and six rung columns.
A reader must open a record and then its dossier to discover its topic. Related
questions cannot be scanned together, and the large chart dominates a narrow
screen. This change makes topic collections the default existing Ladder view;
the original board and table remain available for record-level inspection.

## Presentation contract

- Use the existing read-only Ladder and iteration projections. Join an iteration
  only by its exact recorded member ID. Never group shortened stems, shared
  words, retrieval similarity or an inferred scientific equivalence.
- A collection groups equal recorded topics. A small explicit presentation
  mapping places the two named liquid-democracy topics under one labeled
  **curated topic collection — association only**, keeping both subgroups.
  Unlisted lookalikes do not enter that collection.
- Each original cluster appears exactly once. Mixed topics, missing provenance,
  conflicting duplicate iteration IDs and unsupported member kinds stay
  explicit; they cannot bridge unrelated collections.
- Keep every original ID, cluster status, rung, negative/reopening history,
  distinct recorded hypothesis and member link. A collection has a distribution
  of record stages, never a single inherited maximum stage. Hypothesis text is
  recorded evidence, not a newly validated claim binding.
- Show collection and record counts separately. Search/filter on member content
  retains the collection context and reports matching versus total records.
  Stable keys preserve expansion across refresh and sorting. Unknown or missing
  sources remain visible; a failed refresh retains dated last-good data.
- Start with readable titles and compact stage/status counts. Expand one
  collection to inspect its distinct questions, then follow the existing
  dossier link for full evidence and human decisions. No new page or action.

## Exact candidate paths

1. `ui/frontend/docs/LADDER_THESIS_GROUPING_20260907_020.md`
2. `ui/frontend/src/routes/Ladder.tsx`
3. `ui/frontend/src/components/ladder/thesisModel.ts`
4. `ui/frontend/src/components/ladder/ThesisFamilies.tsx`
5. `ui/frontend/src/components/ladder/ClusterPeek.tsx`
6. `ui/frontend/src/api/ladder.ts`
7. `ui/frontend/src/App.tsx` — only responsive existing navigation wrapping
8. `ui/frontend/tests/test_thesis_model.ts`
9. `ui/frontend/tests/test_thesis_families.tsx`
10. `ui/frontend/tests/test_ladder_page.tsx`
11. `ui/frontend/tests/test_validate_routes_console.tsx` — only affected route fixture wiring

No backend, raw ledger, runtime, policy, model, dependency or action-writer
change is included. Any needed scope amendment is recorded before editing.

## Validation and delivery

Use pure synthetic fixtures for deterministic rules and private captured
current data for the real named examples. Cover exact-topic and curated-group
membership, unrelated lookalikes, no-source and mixed-source cases, duplicate
IDs, reordered refreshes, cross-stage/killed records, keyboard navigation,
member search/filter, stale/error/empty sources and narrow layouts. Preserve
existing board/table behavior and real human-action semantics.

Run focused regression tests, the full frontend suite, typecheck and build.
Pin a clean committed candidate and public base for a distinct adversarial
whole-range review. Reconcile findings before native PR merge. Adopt only the
reviewed source delta into the existing canonical checkout while preserving
operator/runtime changes and private ancestry, then verify actual served source
and a fresh browser journey. Do not push canonical history or restart a backend.

Source freeze target: 2026-09-07 08:00 UTC. First visible delivery target:
08:30 UTC, retaining at least 30 minutes for validation/recovery. Stop a bounded
slice on ownership/integrity conflict or repeated unexplained failure. Recovery
preserves the unmerged candidate and evidence; no reset, clean or force push.

## Implemented reader flow

The existing `/ladder` route starts with collections. Search a recorded topic,
hypothesis or ID, narrow by recorded stage/status, expand a collection, then
open a member's existing dossier. Liquid democracy is explicitly curated from
the two exact public topic labels; equal topics are associations, not proof that
claims are equivalent. Killed records remain available through the status filter
and in each collection's all-record distribution. The board and table are still
available and do not lose collection filters or expansion when switching views.

Only the slim iteration fields used for the join are polled. A failed refresh
retains the last received payload with its error. Record/topic receipt times and
the latest cluster event time are separate; the two APIs are not an atomic
snapshot. Unsupported, mixed and missing joins stay separate. The supplied
Ladder projection carries the current disposition and latest negative, not a
complete raw-event archive. The dossier remains the path to available papers,
pipeline evidence and human decisions. None of this revalidates claim binding,
scientific eligibility or a historical finding.

Browser-only fixture previews are development evidence, not shared deployment.
The existing Vite process can adopt reviewed frontend source without a backend
restart. Delivery requires a separate served-source and real-browser check.

## Adversarial review repairs

Duplicate or missing cluster IDs stay individual and visibly unverified. The
original source ID is displayed separately from an internal snapshot key used
for filtering, rendering and selection. Canonical source content plus a
collision-checked ordinal distinguishes ambiguous copies without inventing
scientific identities. A changed ambiguous snapshot may close its detail panel;
unique valid source IDs keep their usual continuity across refreshes.

Compact records traverse the raw member list before attaching iteration
metadata, preserving interleaved source-finding chronology. The command palette
cycles Collections, Board and Table; invoking the graveyard from another view
opens its visible board target. Regression tests preserve the original review
counterexamples rather than relying only on current backend uniqueness.


## Second review disposition and exact scope amendment

The whole-range review at `7673921` found the remaining ambiguous-ID agenda,
Board/Table row-key and Inspect-name seams. The current captured 202 rows have
unique source IDs and no agenda, but malformed-input safety is also required.
The repair adds only existing `LadderBoard.tsx` and `LadderTable.tsx` to the
previous ten-path range. Both receive the same internal snapshot key used by
Collections and selection. Displayed source IDs remain unchanged.

The model exposes whether a nonblank source ID occurs exactly once in the
received payload. This is local uniqueness, not authenticated scientific
identity. Detail panels withhold ID-keyed agenda attribution when it is absent
or ambiguous; a unique ID retains its agenda even when topic association is
uncertain. Ambiguous Inspect controls include a presentation-only snapshot
number, never a new research ID. Raw records, rulings and ledgers are unchanged.
