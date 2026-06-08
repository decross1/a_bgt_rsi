# exp008 — QAT-vs-pin eval results

EVAL-ONLY benchmark. The production pin was never swapped; all eval calls ran against the scratch container (:8002) and logged to `runs/*.jsonl`, never the production `logs/calls.jsonl`.

**Verdict: INSUFFICIENT**

- small-N or missing metric: tool_call_adherence (missing on an arm)

## Decision metrics (QAT over pin)

_no decision-eligible metrics (see reasons above)_

## Per-arm robustness (modal verdict stability)

- **pin**: no robustness sweep present
- **qat**: no robustness sweep present

## Confusion matrices (reference -> predicted)

### arm: pin
- novelty_agreement: novel->novel: 6, novel->rediscovery: 2, rediscovery->rediscovery: 2
- tool_call_adherence: well_formed->malformed: 12

### arm: qat
- novelty_agreement: novel->unclear: 8, rediscovery->unclear: 2

## Tertiary metrics (NON-DECISION)

tok/s and memory are recorded for context only; they are non-comparable across launch profiles and are NOT decision inputs.


## Pre-registered config

- source: default (config.yaml present but lacks this analyzer's threshold keys) (config.yaml absent — DEFAULT used)
- materiality thresholds: {'novelty_agreement': 0.05, 'calibration_error': 0.02, 'tool_call_adherence': 0.05, 'noise_floor_metric': 'control_self_tier_flip_rate', 'noise_floor_probe_runs': 5, 'margin_over_noise_floor': 0.1, 'fallback_absolute_disagreement_threshold': 0.2, 'small_n_caveat': 'Only ~10 fixtures. With N=10, one tier flip is 0.10 of the set, so the resolution is coarse and any result is DIRECTIONAL, not proof. A "material" flag here is a signal to investigate on a larger fixture set, never a deployment decision on its own.\n'}
- tool-call adherence floor: 0.9
- min sample per arm/metric: 10
