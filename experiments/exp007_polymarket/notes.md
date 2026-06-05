# exp007 — Polymarket paper-forecasting (applied tier)

**DESIGN-ONLY paper forecasting; NO live trading (CLAUDE.md CFTC guardrail).**

Polymarket is design-only until CFTC compliance work is done (Phase 2+).
Nothing in this experiment places an order, signs a transaction, touches a
wallet or private key, spends money, or authenticates to a trading
endpoint. The only external I/O is a single read-only, unauthenticated
`GET` against the public Gamma markets API, and that runs only when
`--live-data` is passed. The default path is fully offline against a
committed fixture.

## What this is

The first **applied-tier** rung of the sandbox spectrum
(`orchestrator/tier_registry.py`). The synthetic and semi-synthetic tiers
test whether the model rediscovers mechanism-design results in toy worlds;
the applied tier asks a sharper question on real-world data:

> Given a real binary prediction-market question, with no priming on the
> market price, can the model emit a calibrated probability that is
> better than the contemporaneous market-implied probability?

The research metric is **forecasting skill**, measured as the **Brier
Skill Score (BSS)** of the model's forecasts relative to the market price
as the reference forecaster, per
[`docs/sources/research_program_v2.md`](../../docs/sources/research_program_v2.md).
BSS > 0 means the model beats the market; BSS < 0 means it trails.

This is a paper-forecasting result. It is **NOT** trading P&L. There is no
position, no order, no money, and no edge being acted on.

## Pipeline

1. **`market_data.py`** — read-only Gamma adapter. `fetch_markets(...)`
   (live, `--live-data`) or `load_fixture(path)` (offline, default).
   Normalizes each market to
   `{market_id, question, implied_prob, resolved, outcome, category,
   end_date}`. Raises `MarketDataError` on any failure; never crashes;
   import does no network I/O.
2. **`forecaster.py`** — neutral LLM prompt asking for a calibrated YES
   probability as JSON `{"prob": <0..1>, "reasoning": <str>}`. Clamps to
   `[0, 1]`; parse failures return `prob=0.5` with a `"parse_failure:"`
   reasoning prefix (observable). Emits a probability ONLY.
3. **`run.py`** — for each RESOLVED market, get a forecast and append a
   row `{market_id, question, prob, market_prob, outcome}` to
   `results/forecasts.jsonl`. Offline by default; under `MOCK_LLM` the
   forecaster is a deterministic stub keyed on `(seed, question)` so no
   live model is called. No order/trade code.
4. **`scoring.py`** — pure-arithmetic Brier + Brier Skill Score +
   `summarize(rows)`. No I/O.
5. **`analyze.py`** — scores `forecasts.jsonl` and writes
   `results/summary.json` + `summary.md` with `mean_brier_model`,
   `mean_brier_market`, `bss`, `n`, and a verdict:
   - `INSUFFICIENT` if `n < 10`,
   - `BEATS_MARKET` if `bss > 0` over the minimum sample,
   - `BELOW_MARKET` otherwise.
6. **`loop_bridge.py`** — copies the exp003 bridge contract:
   `EXPERIMENT_ID="exp007_polymarket"`, `METRIC_NAME="brier_skill_score"`,
   `value = bss`; `--dry-run` default / `--live` threads the
   `experiment_outcome` payload into a LOOP_V0 iteration via
   `orchestrator.nara.run_iteration`.

## Reproduce (offline, MOCK_LLM default)

```bash
MOCK_LLM=1 ./.venv-chroma/bin/python experiments/exp007_polymarket/run.py --n 20
MOCK_LLM=1 ./.venv-chroma/bin/python experiments/exp007_polymarket/analyze.py
MOCK_LLM=1 ./.venv-chroma/bin/python experiments/exp007_polymarket/loop_bridge.py
```

The committed `results/summary.json` was generated this way against the
deterministic stub forecaster; its BSS is a mock artifact, not a real
forecasting result. A real run requires `env -u MOCK_LLM` + a live Gemma
backend.

## Explicitly OUT of scope

- Any live trading: placing orders, signing transactions, wallets/keys,
  spending money, authenticating to a trading endpoint. **None of it
  exists here and none of it is to be added** until CFTC compliance work
  is done.
- Live market-data fetch (`--live-data`) is the only network path and is
  read-only and unauthenticated; the default and all tests run offline.
- Treating BSS as a P&L or an actionable edge. It is a calibration /
  forecasting-skill measure only.
