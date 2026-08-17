Verdict=NO. LOCKED criteria not met: failed rule1(dBIC), rule3(slopes), rule4(bootstrap), rule5(censoring).

# exp012 — spectral-slowdown summary (contraction surrogate)

Claim under test (cl-iter-2026-08-15-002, L1): bounded rationality (precision-constrained belief updating) slows convergence specifically when the information structure's adjacency spectral radius exceeds a critical threshold. LOCKED prereg (v2.1): experiments/PREREG_l2block_2026-08-17.md.

## Scope limit (binding, verbatim)

This environment is a linear belief-best-response contraction surrogate — it is NOT an LQG game (no state dynamics or cost matrices) and NOT partially nested (the sweep requires cyclic digraphs; genuinely nested/acyclic structures have adjacency spectral radius exactly 0, degenerating the claim's threshold quantity — this degeneracy is itself recorded as a finding about the claim's framing). Any Verdict binds to the surrogate; the evidence_level_changed / cluster event must carry this scope limit verbatim.

## Medians and fit

- rho_eff grid: [0.21, 0.32, 0.42, 0.53, 0.63, 0.74, 0.84]
- median T_full: [9.0, 12.0, 15.0, 21.0, 28.0, 43.0, 73.5]
- median T_bounded: [4.0, 5.0, 6.0, 7.5, 9.0, 13.0, 21.5]
- ln R: [-0.8109, -0.8755, -0.9163, -1.0296, -1.135, -1.1963, -1.2292]
- fitted rho*: 0.735 | slope below/above: -0.7665 / -0.3403

## Rule 1 — dBIC (LOCKED)

- dBIC = BIC_1seg - BIC_2seg = -1.235 (>= 10: False)

## Rule 2 — interior breakpoint, uncensored cells above (LOCKED)

- rho* in [0.32, 0.74): True
- cells above [0.74, 0.84] capped fractions ['0.0333', '0.0000'] (each < 0.5: True)
- rule 2 pass: True

## Rule 3 — slope floors (LOCKED)

- slope above -0.3403 >= 2.0 and >= 3.0x max(slope below -0.7665, 0.25): False

## Rule 4 — seed-level bootstrap (LOCKED)

- B=1000, pass fraction 0.000 (>= 0.9), IQR(rho*) 0.2650 (<= 0.15), degenerate resamples 0
- rule 4 pass: False

## Rule 5 — censoring robustness (LOCKED)

- survivor-median refit: rho* 0.670, rules 1-3 False/True/False
- rule 5 pass: False

## H0_construction (closed-form null on record, non-gating)

- ln R_pred: [-0.9608, -1.0713, -1.1599, -1.2633, -1.3576, -1.4682, -1.6126]
- max |ln R_obs - ln R_pred|: 0.3834
- R_pred, not 1, is the no-threshold expectation; the null is SMOOTH in ρ — rule 3's positive-slope floor is the load-bearing defense against its own curvature.

## Cycling fraction vs rho (named non-gating finding)

- rho=0.21: cycling 0.000, budget 0.000, capped 0.000 (n=30)
- rho=0.32: cycling 0.000, budget 0.000, capped 0.000 (n=30)
- rho=0.42: cycling 0.033, budget 0.000, capped 0.033 (n=30)
- rho=0.53: cycling 0.067, budget 0.000, capped 0.067 (n=30)
- rho=0.63: cycling 0.000, budget 0.000, capped 0.000 (n=30)
- rho=0.74: cycling 0.033, budget 0.000, capped 0.033 (n=30)
- rho=0.84: cycling 0.000, budget 0.000, capped 0.000 (n=30)

metric=slowdown_breakpoint_rho_eff value=-1.0
Rows: 420 (errors: 0). Counts match LOCKED design: True.
