# H1 REST displayed-quote diagnostic

The runnable adapter is `rest_reference_driver.py`. It evaluates **one frozen 2–5h pilot block** of the BTCUSDT Spot 1h long/flat application using public, sealed REST L5 snapshots and hourly signed-flow features. It reads local files only. The original `applied_trial/v1` contract and its `sequence_valid=true` paper gate remain unchanged. Every result here says `nonexecutable_reference_only=true`, `sequence_valid=false`, `paper_supported=false`, `orders_placed=0`, and `external_plan_freeze_proof=unverified`; an independent preregistration receipt is still needed to establish when the plan existed.

The plan JSON has exactly these fields and must be written and externally sealed **before** the forward HH:05 start. Replace `<...>` with actual values from preserved source and historical development receipts; the template is intentionally not an executable study with invented hashes.

```json
{
  "schema": "applied-h1-rest-reference-plan/v1",
  "study_id": "h1-btcusdt-rest-YYYYMMDD",
  "symbol": "BTCUSDT",
  "rule_origin": "fixed_unfitted_engineering_preset/v1",
  "topic_transfer_sha256": "<SHA256 of exact H1 topic-transfer JSON published before forward start>",
  "source": {
    "source_id": "binance-spot-public",
    "collector_source_sha256": "<SHA256 of exact bench/applied_trading/public_spot_capture.py>",
    "feature_builder_source_sha256": "<SHA256 of exact bench/applied_trading/prospective_hourly_features.py>"
  },
  "split": {
    "frozen_at": "<actual UTC plan-seal timestamp>",
    "forward_start": "<later UTC HH:05:00 timestamp>",
    "forward_end": "<2 to 5 hours later at UTC HH:05:00>"
  },
  "policy": {
    "hold_s": 3600,
    "latency_s": 30,
    "entry_timeout_s": 600,
    "exit_timeout_s": 600,
    "max_quote_receive_delay_s": 30,
    "max_observation_age_s": 300,
    "paper_size_quote": 100,
    "candidate": {
      "intercept_bps": 0,
      "momentum_weight_bps": 1,
      "flow_weight_bps": 60,
      "depletion_weight_bps": 80,
      "min_flow": 0.1,
      "min_depletion": 0.1
    },
    "baseline": {
      "intercept_bps": 0,
      "momentum_weight_bps": 1
    }
  },
  "cost": {
    "fee_leg_bps": 10,
    "slippage_leg_bps": 5,
    "double_multiplier": 2,
    "fee_source_url": "https://www.binance.com/en/support/faq/detail/115000429332"
  }
}
```

Candidate and baseline intercept/momentum values **must be identical**; the validator rejects any mismatch. The numeric flow/depletion rule shown here is a **code-owned unfitted engineering preset for a plumbing pilot**; this v1 runner rejects other weights/thresholds to prevent unnoticed tuning. It is not fitted from the historical trade-only archive, not optimized on book data, and not a trading recommendation. Historical trade-only data cannot estimate a visible-depth coefficient; a future full forward validation needs separate book-data development and a preregistered untouched holdout. Zero intents or no later quotes are valid pilot findings. Both arms have the same one-position/one-hour cap and use the same later displayed quote pair per scheduled cell, but realized intents/exposure can differ; the result reports both arm counts and does not claim identical exposure matching. The signal is additive flow and visible-size contraction with a joint minimum threshold. It does not estimate an interaction coefficient or dealer behavior. The ordinary reference cost is at least 10 bps fee per leg; displayed ask entry and bid exit incorporate the observed spread before subtracting fee/slippage and doubled cost. The chosen reference size is only a top-level **displayed depth filter**, not a queue position or executable fill.

After capture has continued through at least `forward_end + hold_s + exit_timeout_s`, derive `features.jsonl`/`feature-source.json` using the unchanged `prospective_hourly_features` CLI on a contiguous ordered list of at most 96 sealed **complete_incremental_batch** directories and at most 250,000 trade events. The 96-batch cap at a five-minute cadence cannot cover 24 hours, much less a month, once the prior-hour marker and exit reserve are included; a busy trade period may hit the 250,000-event bound sooner. This pilot deliberately limits the frozen block to 2–5 hours chosen before outcomes. A future forward study must bind and aggregate separately frozen ordered blocks without dropping failed or missing block cells; this script makes no 30-day claim. Then run from the worktree; pass the *same* ordered batch list used to build features:

```bash
PYTHONPATH=/home/decross1/projects/a_bgt_rsi_worktrees/flash-followon-20260915 \
python /tmp/applied-gt-trading-20260915/rest_reference_driver.py \
  --plan /absolute/direct-child/h1-rest-plan.json \
  --topic-transfer /absolute/direct-child/h1-topic-transfer.json \
  --feature-dir /absolute/direct-child/feature-output \
  --batch /absolute/direct-child/first-complete-batch \
  --batch /absolute/direct-child/next-complete-batch \
  --output-dir /absolute/new-direct-child/reference-result
```

The driver first binds the plan's topic-transfer SHA to the exact known-prior H1 transfer JSON, preserving its independent application lane and unchanged science ladder. It reprojects every batch, verifies the GET attempt chain and raw frames, recomputes feature rows from the unchanged builder, rejects any interbatch sealed-to-start gap longer than 15 minutes, and then retains each selected quote's URL, HTTP 200 receipt, request start, local receipt, raw SHA, `lastUpdateId`, five book levels and top-level depth in private `reference-cells.jsonl`. It selects an ask only if the **REST request started after** the decision plus latency and within the entry timeout; it selects a bid only after the entry receipt plus the frozen one-hour hold. A quote received later from a request started too early is unusable. The public `result.json` binds the private ledger hash and gives content-free counts. It computes net reference bps per **all declared schedule cells** only when the temporal window has closed **and** every scheduled arm outcome is identified. Planned abstention and exposure cap are known zero; missing/stale features and intended-but-unavailable quotes are unknown, never implicit zero. Such a sealed window is `closed_with_missing_evidence` and its all-scheduled return fields are null; observed-only sums and their denominators remain visible. An unfinished source window is `incomplete`, also with all-scheduled scores withheld. The output copies the exact evaluated plan, topic-transfer and code bytes to `plan.raw.json`, `topic-transfer.raw.json` and `driver-source.py`, binding all SHA-256 digests in the result. Those archives make a run reproducible, but they **do not prove prestart publication**; `external_plan_freeze_proof` stays unverified until a separate immutable receipt binds publication time before the forward start. Every case remains diagnostic only.

When both later reference snapshots exist, the driver also computes a **midquote** one-hour movement and matched candidate/baseline squared-error and direction diagnostics on the same observed quote-pair denominator, including no-intent cells. These observed-only forecast metrics cannot fill missing schedule cells; a 2–5h pilot has no useful clustered uncertainty or mechanism-identification power.

This adapter never says a displayed quote could have been executed. No REST request/receipt proves venue event time, cancellations, queue or actual order fill. The v1 `paper_supported` route remains unavailable until a separately reviewed diff-depth reconciliation and stronger quote-source receipt exist. A continuous WebSocket subscription is also **not** a series of new post-boundary HTTP requests: current v1 quote validation hardcodes local HTTP snapshots and requires `request_started_at` after each entry/exit boundary. A later typed WS source must preserve subscription start, venue/frame update IDs, local frame receipt and reconciled book chronology rather than inventing a per-frame request start.

Run installed focused checks outside a GPU program with `.venv-chroma/bin/python -m pytest -q tests/test_applied_trading_rest_reference_driver.py tests/test_applied_trading_h1_pilot_lifecycle.py`. They cover raw-plan/topic/source identity, fixed candidate/baseline, HH:05 schedule, ordered source batches, post-boundary quote selection, private-cell denominator and deterministic result replay, and score withholding on missing evidence. The dated [publication and due-evaluation operator sequence](PUBLICATION_AND_H1_DUE_OPERATOR.md) records any actual plan, diagnostic result or timer activation; this guide alone is not an execution receipt.
