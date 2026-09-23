# archive/docs-2026-09

Docs moved here on 2026-09-23 during the v2 docs/prompt cleanup (see the
owner request logged under `notes/research/` for that session, and
`docs/v2/DOCUMENTATION_INDEX.md` for the current live-doc map). Each is
superseded evidence, not a description of the deployed system. All remain
readable in place; only their location under `docs/` changed.

| File | Why archived |
| --- | --- |
| `FLASH_NEXT_AB_PLAN.md`, `FLASH_NEXT_AB_RUNBOOK.md`, `FLASH_NEXT_QUALIFICATION_RUNBOOK.md`, `flash_next_model_selection_20260915.md`, `FLASH_PERSONAL_RESEARCH.md` | Flash A/B benchmark and qualification plans/runbooks. The owner selected Flash and ended further benchmarking on 2026-09-18/19; see `docs/FLASH_RESIDENT.md` and the kept evidence file `docs/FLASH_PERSONAL_RESULTS_20260918.md`. |
| `FLASH_FOLLOWON_OPERATOR.md` | Flash follow-on operator plan superseded by the deployed `docs/v2/OPERATOR_GUIDE.md` and `docs/FLASH_RESIDENT.md`. |
| `qwen38_cutover_memo.md` | Qwen 3.8 cutover memo; the Gemma/Qwen pair it describes stopped 2026-09-19 (rollback only). |
| `roadmap_full_loop.md`, `ui_reframe_plan.md` | June-era 4-session roadmap and UI page-spec plan, both executed and superseded by the current UI and `LOOP_V2.md`. |
| `todo_cockpit_seam_plan.md` mentions elsewhere are unaffected — that plan stayed in `docs/` (still referenced by live `ui/backend/` code); it was NOT moved. |
| `t2_mcp_wiring_draft.md` | T2 MCP wiring draft; T2 shipped (see `human/sessions/`), no live inbound references. |
| `nemoclaw_smoke_runbook.md`, `nemoclaw_agent_run_runbook.md`, `live_session_runbook.md` | NemoClaw/OpenClaw smoke and live-session runbooks for the retired β sandbox exploration; superseded by the current Oracle/Nara/meta-oracle actor model. |
| `exp008_qat_live.md` (from `docs/runbooks/`) | QAT live-run runbook for a completed/retired experiment track. |
| `miasma_safe_check.md` | Point-in-time safety check, since superseded by later gate/pause mechanisms. |
| `overgating_promotion_analysis.md`, `veto_elevation.md` mentions elsewhere are unaffected — both stayed in `docs/` (still referenced by live `workers/` code); they were NOT moved. |
| `coordinator_receipt_truth_t05.md`, `planner_admission_repair_20260908.md` | Point-in-time coordinator/planner review receipts, no live inbound references. |
| `project_health_2026-09.md`, `systems_review_2026-09.md`, `external_spark_brief_review_2026-08-17.md`, `decisions_draft_2026-09.md` | Dated point-in-time reviews superseded by later decisions and the current architecture/operator docs. |

## Not moved (checked and kept live — still load-bearing)

These candidates were verified to have inbound references from live code or
from files this cleanup was not authorized to edit, so they were left in
place rather than archived:

- `docs/qwen38_role_setups.md`, `docs/qwen38_upgrade_checklist.md`,
  `docs/qwen_fp8_windows_plan.md` — referenced from `DECISIONS.md` and/or
  `LOOP_V1.md` (both out of scope for this cleanup) and, for the fp8 plan,
  from live code (`bench/fp8_ab/*.py`, `tests/test_fp8_ab_driver.py`).
- `docs/todo_cockpit_seam_plan.md`, `docs/cockpit_seam_wiring.md` —
  referenced from live `ui/backend/` and `orchestrator/` code and tests.
- `docs/overgating_promotion_analysis.md` — referenced from
  `workers/retrieval_relevance.py`.
- `docs/veto_elevation.md` — referenced from `workers/constraint_distill.py`.
- `docs/ui_simplification_plan_2026-08-15.md` — referenced from
  `ui/backend/coordinator.py`.

## Known accepted link drift

`DECISIONS.md` (append-only, out of scope for this cleanup) links several of
the files moved above at their old `docs/` paths. Decision records are
historical prose and are not edited to chase a doc move; those particular
links are accepted as stale. Everywhere else this cleanup could edit, inbound
links were repointed to the new `archive/docs-2026-09/` path.
