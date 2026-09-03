# Team 1 validation — 2026-09-03

Spawn: `codex-team1-related-work-20260903`
State basis: `56c1b3abae968c8288471b30946000c29ae6f228`

## Contract checks

| Check | Verdict | Evidence |
| --- | --- | --- |
| HEAD identity | PASS | Child and primary both resolved the contracted full SHA. |
| Cached work reused | PASS | The 324-target `rw_targets_raw.json` pool was used; no second broad sweep was performed. |
| Bounded refinement | PASS | Three refinement passes reported, matching the contract cap. |
| Named seeds | PASS | Eleven verified, Autoscience Mira retained as vendor-only, ERA retained unresolved, and XScientist ownership intent left open. |
| Primary-source reachability | PASS | Primary independently opened every named arXiv/Nature source and spot-checked the numerical claims for CodeScientist, Curie, MLR-Bench, ScientistOne, ForeSci, SCP, Agon, and XScientist. |
| Local gap claims | PASS | `workers/claim_extract.py`, `workers/evidence_ladder.py`, the events schema, and the five-row calibration-only event ledger were checked directly. |
| Positioning and novelty bounds | PASS | The report separates a bounded comparison from an exhaustive priority claim. |
| Draft decisions | PASS | DRAFT-D-078 through DRAFT-D-081 include context, choice, alternatives, rationale, reversibility, lineage, touchpoints, and open ratification questions. |
| Read-only boundary | PASS | No child writes appeared; only the primary-owned spawn ledger and live daemon frontier-call ledger were modified. |
| Closure protocol | PASS | Exact sentinel and run-log-shaped closure row returned. |

## Corrections retained

- SCP is Science Context Protocol (`arXiv:2512.24189`), not Scientific
  Criticism Protocol.
- XScientist exists, but the report does not infer it was the owner's intended
  referent.
- Autoscience Mira is vendor-only evidence and is not conflated with Deep
  Principle's MIRA.
- ERA remains a dead end rather than being silently relabeled as Google
  co-scientist or Robin.

## Outputs

- `docs/related_work_2026-09.md`
- `docs/decisions_draft_2026-09.md`
