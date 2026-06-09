# Relevance-gate-only sweep (no LLM workers)

- cases: **22**
- gate recall on must-fire cases: **0/8** — FAIL
- false fires on expect-off cases (over-gating, incl. canaries): **0** — PASS

| case | dom | gate exp/act | anchor | ov3 | cur_ov | spread | maxcos | category:rule |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| novel_on_01_quant_lockin | on | False/False | 0.558 | 0.174 | 0.130 | 0.056 | 0.580 | ok:- |
| novel_on_02_critic_flip_model | on | False/False | 0.558 | 0.097 | 0.069 | 0.026 | 0.557 | ok:- |
| novel_on_03_levelk_quantal_bridge | on | False/False | 0.633 | 0.256 | 0.064 | 0.137 | 0.734 | ok:- |
| redisc_on_01_tft_reciprocity | on | False/False | 0.635 | 0.333 | 0.255 | 0.057 | 0.678 | ok:- |
| redisc_on_02_folk_theorem | on | False/False | 0.747 | 0.467 | 0.467 | 0.051 | 0.781 | ok:- |
| redisc_on_03_quantal_response | on | False/False | 0.733 | 0.133 | 0.133 | 0.030 | 0.727 | ok:- |
| fase_off_01_semantic_entropy | off | True/False ✗ | 0.609 | 0.159 | 0.064 | 0.045 | 0.631 | ok:- |
| fase_off_02_db_index_tuning | off | True/False ✗ | 0.561 | 0.193 | - | 0.019 | 0.565 | ok:- |
| nonsense_01_word_salad | on | False/False | 0.618 | 0.133 | 0.133 | 0.044 | 0.628 | ok:- |
| nonsense_02_not_a_question | on | False/False | 0.640 | 0.267 | 0.267 | 0.073 | 0.736 | ok:- |
| falsifiable_01_finite_pd_cooperate | on | False/False | 0.703 | 0.263 | 0.263 | 0.064 | 0.734 | ok:- |
| falsifiable_02_dominant_tft | on | False/False | 0.652 | 0.359 | 0.359 | 0.020 | 0.629 | ok:- |
| camo_off_01_fase_gt_vocab | off | True/False ✗ | 0.633 | 0.240 | 0.062 | 0.044 | 0.646 | ok:- |
| camo_off_02_btree_mechanism | off | True/False ✗ | 0.636 | 0.095 | 0.048 | 0.028 | 0.609 | ok:- |
| camo_off_03_framework_coordination | off | True/False ✗ | 0.605 | 0.069 | 0.035 | 0.031 | 0.597 | ok:- |
| camo_off_04_raft_punishment | off | True/False ✗ | 0.632 | 0.131 | 0.119 | 0.046 | 0.623 | ok:- |
| drift_off_01_rag_chunk_overlap | off | True/False ✗ | 0.605 | 0.167 | 0.056 | 0.017 | 0.579 | ok:- |
| drift_off_02_belief_distillation | off | True/False ✗ | 0.605 | 0.095 | 0.095 | 0.039 | 0.608 | ok:- |
| canary_on_01_ultimatum_plain | on | False/False | 0.620 | 0.121 | 0.121 | 0.035 | 0.665 | ok:- |
| canary_on_02_hawkdove_ess | on | False/False | 0.660 | 0.195 | 0.195 | 0.049 | 0.705 | ok:- |
| canary_on_03_llm_gt_hybrid | on | False/False | 0.669 | 0.131 | 0.101 | 0.022 | 0.637 | ok:- |
| pbeauty_068_01_levelk | on | False/False | 0.670 | 0.322 | 0.092 | 0.158 | 0.779 | ok:- |
