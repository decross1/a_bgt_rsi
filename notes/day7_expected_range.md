# Day 7 — pre-computed expected cooperation-rate range

Written down BEFORE the 500-round experiment fires, per plan.yaml
`day7_block2_precompute_expected_range` (the silent-model-
misconfiguration safeguard).

**Subject:** LLM (Gemma 4) vs. mirror agent (TFT-equivalent), 100 rounds.

**Original expected cooperation-rate range (2026-05-23 pre-run):** `[0.60, 0.95]`.

**Provenance:** human attestation (decross1, 2026-05-23), consistent
with the source plan's published range of roughly 60–95% over 100
rounds (Horton 2023 territory).

**Use:** after `day7_block2_run_experiment` completes, compare the
actual `coop_rate_llm_vs_tft` against this band. **Outside-band ->
do NOT declare success — investigate** (MARLIN backend status,
parse-failure events in `logs/exp001.jsonl`, prompt drift).

---

## 2026-05-23 amendment — Day 7.3, 4-run diagnostic complete

**Updated range: `[0.60, 1.00]`.**

The baseline run produced LLM-vs-TFT coop rate = 1.000, *outside* the
original upper bound. The precompute-range safeguard fired correctly
and drove a 4-run diagnostic ladder:

| Run    | T   | Prompt              | LLM-vs-TFT |
|--------|-----|---------------------|------------|
| baseline | 0.0 | baseline            | 1.000      |
| 7.1    | 0.2 | baseline            | 1.000      |
| 7.2    | 0.7 | baseline            | 1.000      |
| 7.3    | 0.0 | exploitation_hint   | 1.000      |

**Sampling AND framing both ruled out as artifacts** — the cooperation
lock-in is the model's prior, not a measurement bug.

The same model with the same prompt defects 88–98% against `all_d`
(0.120 / 0.110 / 0.120 / 0.020 across the 4 runs). The model IS
responsive to incentives where the data warrants it — it simply does
not defect first against a non-defecting opponent.

**Disposition:** range amended; Day-7.3 marks the slip resolved. The
cooperation-lock-in finding is the publish-worthy Day-7 headline (but
publication itself still gates on `day7_publication_review_gate`,
which is hard-gate / never auto-clears).
