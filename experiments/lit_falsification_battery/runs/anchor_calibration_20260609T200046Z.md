# Anchor-cosine calibration report

- labelled cases: 22 (on=14, off=8)
- historical iterations: 41

## Labelled distribution

| case | domain | anchor_cosine |
| --- | --- | --- |
| novel_on_02_critic_flip_model | on | 0.5577 |
| novel_on_01_quant_lockin | on | 0.5582 |
| fase_off_02_db_index_tuning | off | 0.5610 |
| camo_off_03_framework_coordination | off | 0.6046 |
| drift_off_01_rag_chunk_overlap | off | 0.6048 |
| drift_off_02_belief_distillation | off | 0.6048 |
| fase_off_01_semantic_entropy | off | 0.6085 |
| nonsense_01_word_salad | on | 0.6182 |
| canary_on_01_ultimatum_plain | on | 0.6203 |
| camo_off_04_raft_punishment | off | 0.6319 |
| novel_on_03_levelk_quantal_bridge | on | 0.6332 |
| camo_off_01_fase_gt_vocab | off | 0.6333 |
| redisc_on_01_tft_reciprocity | on | 0.6351 |
| camo_off_02_btree_mechanism | off | 0.6365 |
| nonsense_02_not_a_question | on | 0.6397 |
| falsifiable_02_dominant_tft | on | 0.6524 |
| canary_on_02_hawkdove_ess | on | 0.6604 |
| canary_on_03_llm_gt_hybrid | on | 0.6688 |
| pbeauty_068_01_levelk | on | 0.6699 |
| falsifiable_01_finite_pd_cooperate | on | 0.7028 |
| redisc_on_03_quantal_response | on | 0.7326 |
| redisc_on_02_folk_theorem | on | 0.7466 |

## Historical iterations (unlabelled; FASE bug marked)

| iteration | known_off | anchor_cosine |
| --- | --- | --- |
| iter-2026-05-27-001 | False | 0.6377 |
| iter-2026-05-27-002 | False | 0.7036 |
| iter-2026-05-27-003 | False | 0.6773 |
| iter-2026-05-27-004 | False | 0.6627 |
| iter-2026-05-27-005 | False | 0.7086 |
| iter-2026-05-27-006 | False | 0.6887 |
| iter-2026-05-27-007 | False | 0.6860 |
| iter-2026-05-27-008 | False | 0.6489 |
| iter-2026-05-27-009 | False | 0.6551 |
| iter-2026-05-27-010 | False | 0.7222 |
| iter-2026-05-27-011 | False | 0.7161 |
| iter-2026-05-27-012 | False | 0.6789 |
| iter-2026-05-27-013 | False | 0.6789 |
| iter-2026-05-27-014 | False | 0.6789 |
| iter-2026-05-27-015 | False | 0.6789 |
| iter-2026-05-27-016 | False | 0.6789 |
| iter-2026-05-27-017 | False | 0.6789 |
| iter-2026-05-27-018 | False | 0.7222 |
| iter-2026-05-27-019 | False | 0.7222 |
| iter-2026-05-27-020 | False | 0.7222 |
| iter-2026-05-27-021 | False | 0.7222 |
| iter-2026-05-27-022 | False | 0.7222 |
| iter-2026-05-27-023 | False | 0.7179 |
| iter-2026-05-27-024 | False | 0.7161 |
| iter-2026-05-27-025 | False | 0.7161 |
| iter-2026-05-27-026 | False | 0.7161 |
| iter-2026-05-27-027 | False | 0.7158 |
| iter-2026-05-27-028 | False | 0.6154 |
| iter-2026-06-05-001 | False | 0.5829 |
| iter-2026-06-05-002 | False | 0.6058 |
| iter-2026-06-05-003 | False | 0.5883 |
| iter-2026-06-05-004 | False | 0.6040 |
| iter-2026-06-05-005 | False | 0.5410 |
| iter-2026-06-05-006 | False | 0.5468 |
| iter-2026-06-06-001 | False | 0.5607 |
| iter-2026-06-08-001 | False | 0.6414 |
| iter-2026-06-09-001 | True | 0.5771 |
| iter-2026-06-09-002 | False | 0.6144 |
| iter-2026-06-09-003 | False | 0.6251 |
| iter-2026-06-09-004 | False | 0.6500 |
| iter-2026-06-09-005 | False | 0.6782 |

## Candidate threshold rule (PROPOSAL, not applied)

```json
{
  "min_gap_required": 0.05,
  "max_off_domain": 0.6365,
  "min_on_domain": 0.5577,
  "gap": -0.0788,
  "anchor_borderline": 0.5577,
  "anchor_low": null,
  "note": "NO clean threshold: gap -0.0788 < 0.05 \u2014 the anchor cosine does not separate the labelled sets; do not ship ANCHOR_LOW from this data."
}
```
