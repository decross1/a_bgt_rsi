# `experiments/fixtures/`

Static fixtures for downstream agent evaluations. Each subdirectory
holds one fixture set keyed by evaluator.

## Subdirectories

- **`critic_hypotheses/`** — 20 hypotheses (19 known-flawed + 1
  ground-truth-positive baseline) consumed by the Day-39 critic
  agent eval (`workers/critic.py`). Success criterion: critic flags
  ≥ 80% of the 19 flawed fixtures with a *substantively different*
  critique (not just "this is wrong"). The ground-truth-positive
  serves as a false-positive guard.

- **`novelty_calibration/`** — small set of (hypothesis, prior-art)
  pairs used by the Day-41 auto-evaluator calibration (W2-05). Each
  fixture carries a ground-truth novelty label so κ + Spearman can
  be scored. Stretch deliverable on Day 8.

- **`meta_review_trios/`** — 20 hypothesis trios consumed by the
  Day-40 (W2-02) active-meta-review duplication test. Per-trio: the
  meta-reviewer's last 3 emissions and a proposed next hypothesis,
  with a ground-truth duplicate/non-duplicate label. Balance is 10
  duplicates + 10 non-duplicates so a degenerate baseline cannot
  exploit class skew. Schema rationale in
  `meta_review_trios/README.md`.

## Fixture schema (critic_hypotheses)

Per-file JSON. Required fields:

| field                       | type    | notes                                                    |
|-----------------------------|---------|----------------------------------------------------------|
| `id`                        | string  | matches filename stem; stable across runs               |
| `hypothesis_text`           | string  | what the critic agent receives as input                  |
| `domain`                    | string  | one of: `game_theory`, `llm_behavior`, `mech_design`, `methodology` |
| `injected_flaw_type`        | string  | from the flaw taxonomy in `loader.py`; `none` for the baseline |
| `flaw_description`          | string  | INTERNAL — why this is flawed; not shown to the critic   |
| `expected_critique_targets` | list    | substrings/concepts a substantive critique should hit    |
| `ground_truth_label`        | string  | `flawed` or `sound`                                      |
| `severity`                  | string  | `subtle` / `moderate` / `obvious`                        |
| `context`                   | string  | optional — experimental setup the hypothesis came from   |
| `schema_version`            | string  | "1.0"                                                    |

## Why fixtures live here, not in `schema/`

Track B owns `schema/**`. The fixture *shape* is documented here in
`loader.py` (Track C zone). If the shape stabilizes and other
evaluators start consuming it, promote `fixture.schema.json` to
`schema/` via Track B on Day 9+.

## Loading

```python
from experiments.fixtures.loader import load_critic_fixtures

fixtures = load_critic_fixtures()
assert len(fixtures) == 20
assert sum(f["ground_truth_label"] == "flawed" for f in fixtures) == 19
```

## Adding a new flaw category

Update the `FLAW_TAXONOMY` set in `loader.py`, add at least one
fixture using it under `critic_hypotheses/`, and rerun
`tests/test_critic_fixtures.py`.
