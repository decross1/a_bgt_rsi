# Track C — Day 8 — critic + novelty fixture set

**Date:** 2026-05-24
**Session:** `claude-track-c-day8-fixtures` (worktree `day8-fixtures`)
**Pulls from:** `PHASE_1_ROADMAP.md` §5.1 Day-39 needs (critic eval),
Day-41 needs (novelty calibration).

## What landed

### Day-39 critic fixtures — `experiments/fixtures/critic_hypotheses/`

20 hypothesis fixtures (19 known-flawed + 1 ground-truth-positive)
for the Day-39 (W2-01) critic-agent eval. Each fixture is a
self-contained JSON file with the schema in
`experiments/fixtures/loader.py` (`REQUIRED_FIELDS`,
`FLAW_TAXONOMY`).

Flaw-type coverage (19 distinct categories, 1 fixture each):

- `spurious_causation`, `prompt_leakage`, `misspecified_payoff`,
  `sample_size_insufficient`, `post_hoc_rationale`,
  `overgeneralization`, `selection_bias`, `confounded_treatment`,
  `measurement_artifact`, `circular_reasoning`, `goodhart`,
  `regression_to_mean`, `missing_baseline`, `temperature_artifact`,
  `ungrounded_extrapolation`, `ambiguous_construct`,
  `publication_threshold`, `anthropomorphic_attribution`,
  `mis_specified_construct_validity`.

Domain spread: 4 game theory, 8 LLM behavior, 2 mechanism design,
6 methodology (all four declared domains represented).

Severity spread: 5 subtle, 11 moderate, 4 obvious. The subtle set is
the calibration challenge — a critic that catches only the obvious
ones would still score 4/19 (21%) and fail the ≥80% target by a wide
margin. The subtle set is what separates a substantive critic from
a flag-everything critic.

The ground-truth-positive (`020_sound_cooperation_lockin.json`) is
the Day-7 cooperation-lock-in finding written with the scope
guardrails the actual result respects (4-run diagnostic ladder,
explicit non-generalization disclaimer, aggregate-publication
framing). It serves as the false-positive guard for the critic: a
substantive flaw-flag on this fixture means the critic flags
everything and the precision metric collapses.

### Day-41 novelty fixtures — `experiments/fixtures/novelty_calibration/`

10 (hypothesis, prior-art) fixtures with ground-truth tier +
novelty score, sized exactly to the W2-05 spec ("10 synthetic-tier
outcomes with ground truth; κ + Spearman; threshold documented").

Tier distribution: 2 `well_known`, 3 `incremental`, 3 `novel`,
2 `surprising`. Off-diagonal mass exists for κ; score range covers
[0.02, 0.85] for Spearman.

The two "borderline" fixtures (`09`, `10`) sit in the
incremental/novel boundary to probe whether the evaluator scores
mid-spectrum claims as mid-spectrum, or defaults to extremes.

### Tests — `tests/test_critic_fixtures.py`

21 tests, all passing under a worktree-local `.venv-day8` (pytest
9.0.3, Python 3.12.3). Coverage:

- Critic: count = 20, label balance 19/1, schema-version uniform,
  ids unique + match filename, enum fields in range,
  `none` ↔ `sound` invariant, flaw-taxonomy coverage (every
  declared flaw type has ≥1 fixture AND every used flaw type is
  declared), `expected_critique_targets` non-empty list of strings
  with ≥3 entries each, domain coverage, severity spread ≥2 per
  level, hypothesis text ≥80 chars, sound baseline is the Day-7
  cooperation-lock-in, no JSON parse errors, no stray non-JSON
  files.
- Novelty: count = 10, schema validation, tier coverage,
  score-tier monotonicity (so κ and Spearman agree on direction).

The flaw-taxonomy-coverage test deserves a callout: it fails if
someone adds a fixture using an undeclared flaw type, AND it fails
if someone adds a taxonomy entry with no example. Together those
two failures keep the taxonomy and the fixture set in lockstep.

## Design decisions

### Why per-file JSON instead of a single YAML

- One file per fixture means a single corrupt fixture can't take
  down the whole set, and `git blame` on a fixture's history is
  one file deep.
- JSON is what `workers/critic.py` will ingest anyway; no YAML
  → JSON translation step.
- Costs ~20 extra files but the directory listing is the index.

### Why `experiments/fixtures/` instead of `schema/`

Track B owns `schema/**`. The fixture *shape* is documented in
`loader.py` (Track C zone) with a `schema_version` field. If the
shape stabilizes and another evaluator starts consuming the same
shape, the right move is to promote a `fixture.schema.json` into
`schema/` via Track B on Day 9+. Until then keeping it Track-C-local
avoids a coordination round-trip.

The Track C addendum explicitly authorized `experiments/fixtures/`
as a new subdir; `agent/ownership.yaml`'s `experiments` zone could
be amended to cover it formally on Day 9.

### Why `flaw_description` is internal-only

A few of the subtle fixtures (e.g., `005_post_hoc_rationale`,
`009_measurement_artifact`) describe an incident in the surrounding
research process. If the description leaked into the
`hypothesis_text` the critic would be cued. The loader and tests
keep them separate. The Day-39 driver should pass *only*
`hypothesis_text` (and optionally `context`) to the critic; everything
else is for scoring.

### Why a ground-truth-positive at all

A critic optimized on flaw-only fixtures will learn to always flag.
The 1 sound fixture lets the eval report precision, not just recall.
The plan asks for ≥80% recall on flawed; the false-positive rate on
the sound fixture is the precision sanity check. One sound fixture
out of 20 is light — Day-39 may want to expand to 3–5 sound fixtures
once the critic is calibrated.

## Open / next-day notes

- `agent/ownership.yaml` `experiments` zone does not formally cover
  `experiments/fixtures/`. Track A or B should amend on Day 9 to add
  the glob `experiments/fixtures/**` to the `experiments` zone (or
  create a new `fixtures` zone).
- The novelty-calibration set is intentionally small (10). Day 41
  may want 20–30 once the auto-evaluator is in place; the schema is
  designed to extend without breaking.
- The worktree-local `.venv-day8/` is git-ignored at the worktree
  level only; it should NOT be committed. The release-time gitignore
  check in the commit step below verifies this.

## Files written by this session

| File                                                                      | Purpose                      |
|---------------------------------------------------------------------------|------------------------------|
| `experiments/fixtures/__init__.py`                                        | package marker               |
| `experiments/fixtures/README.md`                                          | top-level fixture docs       |
| `experiments/fixtures/loader.py`                                          | schema + load functions      |
| `experiments/fixtures/critic_hypotheses/001..020_*.json`                  | 20 critic fixtures           |
| `experiments/fixtures/novelty_calibration/README.md`                      | novelty subdir docs          |
| `experiments/fixtures/novelty_calibration/01..10_*.json`                  | 10 novelty fixtures          |
| `tests/test_critic_fixtures.py`                                           | 21 tests, all passing        |
| `notes/track-c-day8-fixtures.md`                                          | this file                    |
| `run_state/claims.jsonl` (append only)                                    | claim + release entries      |

## Sentinel

When this session commits, releases its claim, and exits, it prints:
`TRACK C COMPLETE — ready to merge`.
