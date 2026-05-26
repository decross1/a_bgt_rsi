# Track C — Day 9 fixtures (Day-40 forward-stage + Day-39 plumbing)

Date: 2026-05-25 (Day 39, current_day = day_9)
Worktree: `worktree-day9-fixtures`
Agent: `claude-track-c-day9-fixtures`

## What landed

1. **`experiments/fixtures/meta_review_trios/`** — 20 hypothesis trios
   for the Day-40 W2-02 active-meta-review duplication test. Balance:
   10 duplicates / 10 non-duplicates. Severity spread: 4 / 4 / 2 per
   label across {subtle, moderate, obvious}. Domain spread: all four
   declared domains (`game_theory`, `llm_behavior`, `mech_design`,
   `methodology`) represented.

2. **`experiments/fixtures/loader.py`** — extended with
   `load_meta_review_trios()`, `validate_trio_fixture()`, and the
   `TRIO_DIR` / `TRIO_REQUIRED_FIELDS` / `TRIO_SEVERITIES` constants.
   Validator enforces:
   - exactly 3 entries in `last_3_hypotheses`, all non-empty strings;
   - `expected_duplicate_label` is a real `bool` (Python's `1 == True`
     trap is caught by `isinstance(label, bool)`);
   - if `expected_duplicate_label = True`, then `duplicate_of_index`
     must be one of `{0, 1, 2}`; if `False`, `duplicate_of_index`
     must be `None`.

3. **`experiments/fixtures/meta_review_trios/README.md`** — schema
   rationale, same shape as the Day-8 critic_hypotheses README block.

4. **`experiments/fixtures/README.md`** — index updated to include
   the `meta_review_trios/` subdirectory entry.

5. **`tests/fixtures/critic_eval_inputs.jsonl`** — JSONL view of the
   20 Day-8 critic fixtures, one line per fixture with
   `{id, hypothesis_text, context}`. This is the lightweight feed
   Track A's Day-39 critic eval pipes into `workers/critic.py`
   directly — no need to round-trip through 20 separate per-file
   JSON loads.

6. **`cron/run-critic-eval.sh`** (stretch) — nightly wrapper modeled
   after `cron/sla-sweep.sh` and `cron/daily-arxiv.sh`. NOT installed
   in crontab (per the same day-7/day-8 cron-install discipline). The
   wrapper preflight-checks the existence of `workers/critic.py` and
   bails with a clear message if the Day-39 worker has not yet
   landed; this is by design, so an early install does not silently
   no-op.

## Decisions taken

- **Trio file naming** uses the `NNN_<label>_<severity>_<short-id>`
  convention rather than the day-8 `NNN_<flaw-type>_<topic>` because
  the trio set's load-bearing dimensions are `expected_duplicate_label`
  and `severity`, not the flaw taxonomy.

- **`duplicate_of_index`** is included as a non-required (the
  validator treats it as optional but constrained-when-present) field.
  Required by the validator only when `expected_duplicate_label` is
  `True`. This lets the Day-40 eval not just score binary accuracy but
  also check that the meta-reviewer points to the *correct* prior
  hypothesis it considers a duplicate of.

- **Positional balance**: across the 10 duplicates, `duplicate_of_index`
  is distributed `{0: 4, 1: 3, 2: 3}` (filename-order sequence:
  `[0, 0, 2, 2, 0, 1, 1, 2, 0, 1]`). A meta-reviewer that always
  returns "duplicate of the most recent" (index 2) would post 3/10 on
  duplicates and 10/10 on non-duplicates — 65%, below the W2-02
  pass threshold. A reviewer that always returns "duplicate of the
  oldest" (index 0) would post 4/10 — 70%, also below threshold.

- **`rationale` field is internal documentation**, mirroring
  `flaw_description` in critic_hypotheses. Track A's Day-40 worker
  must not pass it into the meta-reviewer prompt; the loader returns
  it for human review and validator-side use only. The README states
  this explicitly.

- **No `tests/test_meta_review_fixtures.py` written here**. Per the
  Day-9 task brief, that test file is Track-B-owned; this worktree
  authors the fixture, Track B authors the test. The loader's
  validator is in place so Track B's test file can be a 10-line
  wrapper around `validate_trio_fixture()`.

- **Critic-eval JSONL** keeps only the three fields a critic worker
  needs: `id` (so output rows can be joined back to the per-file
  fixture for label/severity), `hypothesis_text` (the input), and
  `context` (the optional experimental setup). The flaw taxonomy,
  ground-truth label, and `flaw_description` are deliberately
  excluded — they live in `experiments/fixtures/critic_hypotheses/`
  for ground-truth use, and must not be visible to the critic.

## Sanity checks run in this worktree

```text
loader smoke:    load_meta_review_trios() returned 20 fixtures
validator:       validate_trio_fixture() returned [] for all 20
balance:         {True: 10, False: 10}
severity:        {subtle: 8, moderate: 8, obvious: 4}
sev × label:     each bucket >= 2 (subtle/mod = 4 each, obvious = 2 each)
domain coverage: all 4 declared domains present
JSONL row count: 20 lines, schema {id, hypothesis_text, context}
shell syntax:    bash -n cron/run-critic-eval.sh -> OK
```

## What this enables for Day 40

- `workers/meta_review.py` (Track A's Day-40 deliverable) can read
  `load_meta_review_trios()` and run its 20-trial duplication test
  with no further fixture authoring required.
- The 50/50 label split + non-trivial severity spread means a degenerate
  classifier (always-duplicate or always-not-duplicate) can post no
  better than 50% accuracy. Substantive performance requires the
  meta-reviewer to actually engage with semantic content.
- The `duplicate_of_index` field lets Day-40 score not just accuracy
  but also *correct-attribution* among the duplicate-positive cases.

## What this does NOT do

- Does not author `tests/test_meta_review_fixtures.py` — Track B zone.
- Does not author `workers/meta_review.py` — Track A zone.
- Does not install `cron/run-critic-eval.sh` in crontab — same
  human-step discipline as the day-7/day-8 cron deliverables.
- Does not run the Day-39 critic eval — Track A consumes
  `tests/fixtures/critic_eval_inputs.jsonl` from this drop, but the
  eval itself is a Track-A Block 2 task today.
