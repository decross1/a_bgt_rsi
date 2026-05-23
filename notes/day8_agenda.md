# Day 8 agenda — first items on entry

Notes for the Track A session that opens Day 8 / Day 38 (the
Week-1 → Week-2 boundary). Per `agent/orchestration.md` §"Session
launch checklist", pull this open at session start and clear the
top-of-list items before beginning the Day-8 plan.

## First agenda item — stray files left at Day-7 EOD

Two untracked files on `main` after the Day-7 close-out that should
be resolved on Day-8 entry, not earlier (human review preferred):

1. **`notes/day7_expected_ranged.md`** (52 bytes, typo'd duplicate)
   - Content: `LLM-vs-mirror expected coop rate range: [0.60, 0.95]`
   - Canonical: `notes/day7_expected_range.md` (which has the full
     diagnostic table + amended range `[0.60, 1.00]`)
   - Decision: delete (typo) or rename to `notes/day7_expected_range_human_scratch.md`
     to preserve the original paper-style write-down. The content
     is fully captured in the canonical file either way.

2. **`run_state/week1.run.jsonl.pre-rectify-bak`** (~107 KB safety backup)
   - Pre-rectification snapshot of the run log (Day-7 fix at commit
     `083033d` escaped 4 sets of inner quotes in Day-6 entries).
   - Decision: delete. The fix is committed + verified (0 malformed
     across 132 lines post-rectification); UI integrity tests pass;
     attestation already cleared on the strength of the rectified
     file. No rollback path is needed.

Both above are safe to delete from `main` directly; nothing else
references them.

## Other Day-7 carry-overs into Day 8

3. **Publication review gate `day7_publication_review`** stays in
   `state.human_gates_pending`. The results-announcement post is
   itself a Week-2 task; do NOT auto-publish even if the post is
   drafted. See `journal/day7.md` (the preliminary-banner journal)
   — that post is the weekly retrospective, not the results post.

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
   user memory) — items 1, 2, 3, 4 all closed during Day 7. Prune
   the file or delete it entirely on Day-8 entry to keep the index
   tight.

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
