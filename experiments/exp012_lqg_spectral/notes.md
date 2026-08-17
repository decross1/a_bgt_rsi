# exp012 — spectral-slowdown surrogate (cl-iter-2026-08-15-002)

LOCKED design: `experiments/PREREG_l2block_2026-08-17.md`
§exp012_lqg_spectral, **v2.1** — quantization-only bounded arm +
fixation/cycle detection. The decision rules live as module constants in
`analyze.py`, copied verbatim from the lock; any later change is a new
dated amendment there, never an edit.

**Scope limit (binding):** this is a linear belief-best-response
contraction surrogate, NOT an LQG game and NOT partially nested. The
verbatim note is `analyze.SCOPE_LIMIT_NOTE`; it is written into
`summary.md`, `summary.json` (`scope_limit`), and the bridge outcome
`summary` string so it reaches the ledger events.

## Files

- `dynamics.py` — instance draw (directed ER p=0.35, acyclic redraw
  logged), M rescale, θ* direct solve, FULL/BOUNDED arms with the
  PINNED per-step check order (fixation FIRST, then hash-set revisit,
  then budget_exhausted at t_max=20000).
- `run.py` — 30 seeds × 7 ρ_eff × 2 arms = 420 rows to
  `results/trials.jsonl`; paired design (one (A, b, θ0) triple per seed
  shared across its 14 cells); errors recorded as rows; active_run +
  emit_task_triple telemetry is try/except so it can never abort a run.
- `analyze.py` — rules 1–5 verbatim; H0_construction closed-form null;
  cycling-fraction-vs-ρ named non-gating finding; Verdict on line 1 of
  `summary.md`; machine-readable `summary.json`.
- `loop_bridge.py` — exp003-shape Tier-2 → Tier-3 bridge; `--dry-run`
  default; `LOOP_V0_CALLS_LOG` set at module load before any
  orchestrator import (pinned by `tests/test_experiment_log_isolation.py`).

## Run

```bash
# headline run (~seconds; pure numpy, zero LLM calls, MOCK_LLM-safe)
./.venv-chroma/bin/python experiments/exp012_lqg_spectral/run.py
./.venv-chroma/bin/python experiments/exp012_lqg_spectral/analyze.py
# bridge (dry-run default; --live needs env -u MOCK_LLM + Gemma)
./.venv-chroma/bin/python experiments/exp012_lqg_spectral/loop_bridge.py
# tests
MOCK_LLM=1 ./.venv-chroma/bin/python -m pytest tests/test_exp012_lqg_spectral.py -q
```

Observed wall (2026-08-17 build smoke, scratch output only — the
official run is the integrator's): 420 trials ≈ 0.1 s; analyze incl.
the B=1000 bootstrap ≈ 0.1 s. The t_max=20000 worst case never bound —
trials fixate or cycle within tens of steps at this grid.

## Implementation pins NOT spelled out in the locked text

Reported here so nothing is silent:

- **Draw order inside RNG(base+s):** graph A first (redraws consume
  draws), then b, then θ0. The lock pins the pairing and the RNG stream,
  not the intra-stream order; this order is now the reproducibility pin.
- **Rule-4 resampling unit:** "seed-level bootstrap (resample seeds
  within each (ρ, arm) cell)" is implemented as ONE resampled seed
  multiset per replicate applied to every cell — the seed is the unit,
  preserving the locked paired design. RNG seed pinned:
  `BOOTSTRAP_SEED = 20260817` (not in the locked text).
- **Fixation test form:** implemented as bitwise θ_{t+1} == θ_t (the
  lock's primary phrasing); q_t == q_{t−1} is equivalent because the
  update depends only on the quantized vector.
- **Breakpoint ties:** RSS ties across candidates break to the lowest
  ρ* (np.argmin). Degenerate fits (non-finite ln R, empty candidate
  set) fail rules 1–3, never coerced.
- **Counts guard (exp010 norm, additive):** effect_confirmed
  additionally requires every (ρ, arm) cell to carry exactly 30 valid
  rows — the rules were locked at that n; confirming on other counts
  would silently coerce the design. Reported as `counts_match_lock`.
- **JSON caveat:** on degenerate/synthetic inputs `delta_bic` can be
  ±inf/nan; Python's json emits `Infinity`/`NaN` (non-strict JSON).
  Real-run values are finite; `value` is always finite by construction.

## Expected geometry (from the lock's own null)

R_pred sits well BELOW 1 across the sweep (bounded fixation tolerance
≈ Δ/2 vs the full arm's 1e-6 band), so ln R < 0 is not a bug. The YES
case requires a ΔBIC≥10 kink with the locked slope floors — rule 3 is
the named load-bearing defense against the null's own curvature.
