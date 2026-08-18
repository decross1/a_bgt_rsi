# Judge-calibration set v2 (`set_v2.jsonl`)

Ground-truth labeled claim pairs for calibrating the `workers/idea_judge.py`
equivalence judge (LOOP_V1 P3 "Judge calibration") **before the LLM layer
activates**. The judge activates only if every pre-registered bar in
`workers/idea_judge.py` (`EQUIV_PRECISION_MIN` 0.90, `EQUIV_RECALL_MIN` 0.80,
`FALSE_EQUIV_MAX` 0.10, `SYMMETRY_DISAGREE_MAX` 0.10, `VERDICT_FLIP_MAX` 0.15)
passes independently — never coerced; fail → prefilter-only stands.

**This directory does NOT run calibration.** Running the real calibration
(`env -u MOCK_LLM ... -m workers.idea_judge --calibrate`) and recording its
result via the `experiment` skill is the integrator's job.

## Provenance (v2 is FROZEN)

- Generated: 2026-08-18 by `build_set.py`, seed **20260818**.
- Corpus snapshot at generation: `memory/loop_memory.jsonl` @ 152 rows,
  `memory/idea_ledger.jsonl` @ 295 events (repo HEAD `b36424b`).
- `md5sum set_v2.jsonl` = `e5c7487f8a799eda95532084a9ef90ba`.
- The lab is always-on and the corpora grow hourly: **regenerating later
  yields a DIFFERENT (still deterministic) set — that is a v3, not v2.**
  Don't overwrite this file casually; calibration ground truth must stay
  stable so results are comparable.

## Ground truth

A claim universe is extracted from `loop_memory.jsonl` (`hypothesis.text`,
fallback `seed.topic`; first-occurrence text dedup; leaked structured
payloads — texts starting `{`/`[`, 6 dropped at generation — excluded).
Ground-truth "same idea" components are the union-find closure over:

1. **lexical edges** — symmetric token-jaccard ≥ `GROUND_TRUTH_JACCARD`
   (0.6, imported from `workers.idea_judge`; tokens via the shared
   `retrieval_relevance._tokenize`), and
2. **ledger edges** — co-membership in a `memory/idea_ledger.jsonl` cluster
   (`cluster_created`/`member_added` events; these ARE the historical 8–10×
   restatement clusters, member counts ~16/13/8/5).

## Composition (74 pairs)

| bucket | n | label | construction |
| --- | --- | --- | --- |
| positives | 24 | `equivalent` | intra-component pairs, biggest clusters first (per-cluster: 6+6+3+3 from the four ≥3-text clusters, 6×1 from two-text clusters); 16/24 are ledger- or transitively-linked (pair jaccard < 0.6) — the non-trivial cases |
| hard_negatives | 30 | `not_equivalent` | top cross-component pairs by the SAME lexical prefilter layer `idea_ledger.accept_candidate` uses (`mine_paper_gap._lexical_overlap`, imported, symmetrized via max of both directions); overlap 1.00–0.43 — same-setting/different-mechanism confusers |
| random_negatives | 20 | `not_equivalent` | seeded-random (`random.Random(20260818)`) sample of the remaining cross-component pairs; overlap 0.00–0.32 |

Every cross-component pair is provably below the lexical ground-truth bar
(jaccard < 0.6 — otherwise union-find would have merged the components), so
negatives are cross-cluster **by construction**, and under the MOCK_LLM
lexical stub the false-equivalence rate over this set is exactly 0.

**Honest deviation from the LOOP_V1 targets (~50/30/20):** positives are 24,
not ~50. The historical clusters' "sizes 10/8/7/4" counted *members*, and
most members are verbatim restatements; after text dedup (required so no
pair is duplicated and no `a == b` pair pads recall) today's corpus supports
exactly 24 distinct-text same-cluster pairs. Hard negatives rank by lexical
overlap only (not embedding cosine): the builder must be reproducible with
no model available, and under MOCK_LLM stub embeddings a cosine ranking
would be hash-geometry noise.

## Row format

One JSON object per line:

```json
{"pair_id": "v2-000", "bucket": "positives", "label": "equivalent",
 "a": "<claim text>", "b": "<claim text>",
 "cluster_a": "gt-002", "cluster_b": "gt-002",
 "jaccard": 0.7273, "prefilter_overlap": 0.8462}
```

`a`/`b`/`label` are exactly the fields `workers.idea_judge.calibrate`'s
labeled-pair loop reads (labels `equivalent`/`not_equivalent`, the vocabulary
`_score_calls` branches on); the rest is provenance. To consume:

```python
from bench.judge_cal.build_set import load_set  # or import via file path
pairs = load_set()   # -> {"positives": [...], "hard_negatives": [...], "random_negatives": [...]}
# identical shape to workers.idea_judge.build_calibration_pairs(...)
```

## Regenerate / verify

```bash
.venv-chroma/bin/python bench/judge_cal/build_set.py            # rebuild (LLM-free, deterministic)
MOCK_LLM=1 .venv-chroma/bin/python -m pytest tests/test_judge_cal_set.py
```

The builder makes no model or embedding calls, so `MOCK_LLM` does not affect
it; determinism is seed + corpus bytes only.
