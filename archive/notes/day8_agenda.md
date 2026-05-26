# Day 8 agenda — first items on entry

Notes for the Track A session that opens Day 8 / Day 38 (the
Week-1 → Week-2 boundary). Per `agent/orchestration.md` §"Session
launch checklist", pull this open at session start and clear the
top-of-list items before beginning the Day-8 plan.

## First agenda item — stray files left at Day-7 EOD ✅ RESOLVED 2026-05-24

Two untracked files on `main` after the Day-7 close-out that should
be resolved on Day-8 entry, not earlier (human review preferred):

1. **`notes/day7_expected_ranged.md`** (52 bytes, typo'd duplicate)
   — **DELETED 2026-05-24 in commit 5fe49b9.** Content preserved
   verbatim as the "Original expected cooperation-rate range
   (2026-05-23 pre-run)" line in canonical `notes/day7_expected_range.md`.

2. **`run_state/week1.run.jsonl.pre-rectify-bak`** (~107 KB safety backup)
   — **DELETED 2026-05-24 in commit 5fe49b9.** Rectified log
   verified 0 malformed across 133 lines; no rollback path needed.

## Other Day-7 carry-overs into Day 8

3. **Publication review gate `day7_publication_review`** ✅ **CLEARED
   2026-05-24 (D-028).** Disposition: no-publish-standalone; the
   Day-7 result aggregates into a broader future publication that
   combines Day-7 with subsequent experiments (Week 2+). State file:
   `human_gates_pending = []`. Journal `journal/day7.md` banner
   updated; `notes/day7_expected_range.md` amended with the
   publication disposition.

4. **Retrospective Q4-Q6 still templated** in
   `human/retrospectives/week1.md` (sections 4, 5, 6, plus the `__`
   placeholder counts inside section 7's four checked-but-uncounted
   boxes). The boxes are checked + the attestation hash is in place;
   filling the narrative is a follow-up the human can do at their own
   pace and re-commit as an amendment.

5. **Verifier-naming drift** flagged by Track D
   (`notes/track-d-observations.md` 2026-05-23 entry, last paragraph):
   `agent_wrapper/wrapper.py:verify_log_integrity` validates the
   call-record schema; `ui/backend/unlock.py:verify_run_log_integrity`
   validates the run-log schema. Either disambiguate `autonomy.md`
   §4.3 to point at the right verifier per file, or unify under one
   apparatus-side function. Week-2 polish, not blocking.

6. **Track-C cron NOT yet installed** in user crontab. Track-C
   install playbook is in `notes/track-c-day7-cron.md`. Day-8 candidate
   for the SLA-sweep (every 15 min) + claims-weekly (Sunday 04:00 UTC).

7. **Day-7 carry-overs memory file** (`day7-carryovers.md` in
   user memory) — ✅ verified 2026-05-24 already pruned (no file in
   `~/.claude/.../memory/`).

8. **Track-A aux session commit** (`5705a11`) — the session-launch
   checklist + plan.yaml strategies amendment landed mid-day. Day 8
   should READ `agent/orchestration.md` §"Session launch checklist"
   first (it's the new top-of-file orientation per the START_HERE.md
   cross-reference added in `5705a11`).

## Day-8 work proper (after the items above clear)

- Day-8 plan content lives in `plan.yaml` `day_8` or
  `PHASE_1_ROADMAP.md` §5.1 (Day 38 — UI v1 deployment + dispatch
  plumbing). The roadmap is the canonical Week-2 plan; `plan.yaml`
  does not yet have detailed Day-8+ tasks (Week-2 plan execution is
  a Day-38 task).
- Concurrency cap on Day 8: per the unlock conditional, ALIGNMENT
  EVIDENCE 1/2 attestations is in place from Week 1. Week-2 tier
  shifts apply ONLY after the Day-44 / week2.md attestation. Day 8
  operates at Week-1 tiers.
