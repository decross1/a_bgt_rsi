# `meta_review_trios/`

Fixtures for the **Day-40 (W2-02) active meta-review duplication test**.
20 hypothesis trios. Each trio represents a snapshot of the meta-review
context as the next-hypothesis worker is about to fire:

- `last_3_hypotheses` — the three most recent hypotheses the
  meta-reviewer has already emitted.
- `proposed_hypothesis_text` — a candidate hypothesis the worker is
  considering emitting next.

The meta-reviewer's job in W2-02 is to flag the proposed hypothesis as
a duplicate of any of the three when it is one, and to let it through
when it is not. This fixture set is the ground-truth labeled corpus
that gates whether the meta-reviewer passes its 20-trial duplication
test on Day 40.

## Ground-truth balance

Exactly 10 of the 20 trios are duplicates
(`expected_duplicate_label = true`) and exactly 10 are non-duplicates
(`expected_duplicate_label = false`). This 50/50 split is deliberate:
the test is binary classification, and unbalanced fixtures would let
a degenerate "always-not-duplicate" baseline post a misleading
accuracy.

## Severity spread

Each label × severity bucket has at least 2 fixtures:

| severity   | duplicate | non-duplicate |
|------------|-----------|---------------|
| `subtle`   | 4         | 4             |
| `moderate` | 4         | 4             |
| `obvious`  | 2         | 2             |

Subtle fixtures are the load-bearing ones: a meta-reviewer that only
catches obvious-case duplicates is not earning its keep against an
LLM hypothesis worker that will paraphrase its own recent output.
Conversely, the subtle *non-duplicates* test for false positives —
the meta-reviewer must not over-flag hypotheses that share keywords
with recent history but make distinct claims.

## Schema (per-file JSON)

| field                       | type           | notes                                                                                |
|-----------------------------|----------------|--------------------------------------------------------------------------------------|
| `trio_id`                   | string         | matches filename stem; stable across runs                                            |
| `last_3_hypotheses`         | list[3 of str] | the meta-reviewer's three most recent emissions; order matters (most-recent last)    |
| `proposed_hypothesis_text`  | string         | the candidate hypothesis under review                                                |
| `expected_duplicate_label`  | bool           | `true` iff the proposed hypothesis duplicates any entry in `last_3_hypotheses`        |
| `duplicate_of_index`        | int or null    | index 0/1/2 into `last_3_hypotheses` when label is true; `null` when label is false  |
| `severity`                  | string         | `subtle` / `moderate` / `obvious`                                                    |
| `domain`                    | string         | one of `game_theory`, `llm_behavior`, `mech_design`, `methodology`                  |
| `rationale`                 | string         | INTERNAL — why this is (or is not) a duplicate; never shown to the meta-reviewer    |
| `schema_version`            | string         | "1.0"                                                                                |

`rationale` is the meta-review analogue of `flaw_description` in the
critic_hypotheses set: it documents the why for human review and for
debugging false positives/negatives, and must never leak into the
input the meta-reviewer sees.

## Why "trios" and not pairs or N-history

The Day-40 W2-02 spec says "no duplication of last-3 hypotheses." The
fixture shape mirrors that exactly: three entries, no more. If the
spec evolves to look at a longer or shorter window, the loader's
`load_meta_review_trios()` returns full dicts and a future version
can carry an `n_history` field — but right now `last_3_hypotheses` is
hard-coded at length 3 and the validator enforces it.

## Positional balance

Across the 10 duplicate fixtures, the `duplicate_of_index` is varied
(some 0, some 1, some 2) so a meta-reviewer that only checks the most
recent emission (a common shortcut) cannot post 80% accuracy by
exploiting positional skew. See the underlying files for the
distribution.

## Loading

```python
from experiments.fixtures.loader import (
    load_meta_review_trios,
    validate_trio_fixture,
)

trios = load_meta_review_trios()
assert len(trios) == 20
assert sum(t["expected_duplicate_label"] for t in trios) == 10
for t in trios:
    assert not validate_trio_fixture(t), validate_trio_fixture(t)
```

## Adding a new trio

1. Append the JSON file under this directory with `trio_id` matching
   the filename stem.
2. Keep the 10/10 label balance; if a new fixture would skew the
   balance, pair it with one of the opposite label.
3. Vary `duplicate_of_index` across the duplicate set — do not stack
   all duplicates against index 2.
4. Re-run `tests/test_meta_review_fixtures.py` (Track B authors the
   test; the loader is already in place).

## Why fixtures live here, not in `schema/`

Same reason as `critic_hypotheses/`: Track C owns
`experiments/fixtures/**` and the fixture *shape* is documented in
`loader.py`. If the meta-review trio schema stabilizes and other
consumers (the Day-43 in-loop critic, the Day-45 holdout protocol)
start reading it, Track B can promote `trio.schema.json` to `schema/`.
