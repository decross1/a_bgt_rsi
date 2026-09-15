# Applied game-theory paper research

This package tests one known strategic-liquidity mechanism: whether hourly taker-flow imbalance conditioned on thin visible liquidity adds a useful signal beyond ordinary momentum for BTCUSDT Spot long/flat timing. The one-hour horizon is primary; four hours is a secondary horizon, **not** the separate funding/crowding hypothesis. Data collection and historical diagnostics can start now. No account, credential, order, or model endpoint is used. A positive historical reference-cost result is not an executable trading edge.

Run commands from this repository root with its `.venv-chroma/bin/python`. Use new direct-child artifact directories each time. The registered capture root is `/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/applied-trading-public-data/captures`; the archive root is its sibling `archives`.

```bash
.venv-chroma/bin/python -m bench.applied_trading.public_spot_capture --plan --symbol BTCUSDT --max-pages 8
.venv-chroma/bin/python -m bench.applied_trading.public_spot_capture --run --symbol BTCUSDT --max-pages 8 --output-dir /home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/applied-trading-public-data/captures/spot-BTCUSDT-YYYYMMDDTHHMMSSZ
# The no-cursor warmup must be marked incomplete. Read its real next_aggregate_id,
# then issue the next call with --from-id and a fresh output name.
.venv-chroma/bin/python -m bench.applied_trading.public_spot_capture --run --symbol BTCUSDT --from-id ACTUAL_SEALED_CURSOR --max-pages 8 --output-dir /home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/applied-trading-public-data/captures/spot-BTCUSDT-YYYYMMDDTHHMMSSZ
.venv-chroma/bin/python -m bench.applied_trading.hourly_capture --plan
.venv-chroma/bin/python -m bench.applied_trading.hourly_capture --run-once --previous-batch ABSOLUTE_COMPLETE_BATCH --bootstrap-warmup ABSOLUTE_FIRST_WARMUP --max-pages 8 --output-dir /home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/applied-trading-public-data/captures/spot-BTCUSDT-YYYYMMDDTHHMMSSZ
```

`hourly_capture` is a **manual one-shot** locked continuation. For later invocations omit `--bootstrap-warmup`, and give its last `continued_complete` batch as predecessor. At most two metadata GETs and eight trade-page GETs are issued. It stops if an attempt fails, a cursor/page gap appears, or the eight-page cap cannot catch up. An incomplete continuation remains an immutable failed attempt; it cannot donate a later cursor. There is no timer yet. A future five-minute cadence must start only after the model decision and must preserve every issued request in its denominator; a stopped branch needs a separately acknowledged recovery receipt before any restart from an earlier cursor.

The collector journals **every issued GET**, including failed transport, HTTP, or HTTP-200 validation. Each successful response has raw bytes, exact URL, receipt time, SHA-256, and a hash-chained attempt row. `requests_attempted = requests_succeeded + requests_failed` holds only when all attempts were journaled. A continuation receipt adds predecessor and successor counts; its cumulative count is a lineage receipt, not a claim that all market events since the beginning of venue history were observed. `source_valid_frames` means successful sealed HTTP-200 response frames whose raw bytes pass the current read-only receipt validator. It does **not** mean an executable quote, available historical L2, filled trade, validated study, or profitable strategy. REST depth has local request/receipt times and no venue event time or diff-depth sequence; aggregate-trade `T` is venue event time and cannot be used before the local response was received.

Use `project_known_collection(directory)` to view two observed collector identities. The currently packaged source is checked against its exact on-disk bytes and reports `collector_source_status=current_verified`. The 2026-09-15 09:04/09:05 smoke collector declared SHA-256 `780d846508ac2a5003d32bb372ddab68b5fb406c55feefab82794d553053bcf5`, but its **exact source bytes were not preserved**; its raw attempt/receipt chain can be inspected, while `collector_source_status=historical_source_unavailable` and `collector_source_verified=false` must remain visible. Any other declared source SHA rejects. This status must not be silently promoted to source verified by checking a newer collector version or used as a future cursor donor. The 09:11 deliberately capped branch was already collected under the current source before this stricter rule; it remains a stopped branch and cannot donate a cursor.

```bash
.venv-chroma/bin/python -m bench.applied_trading.public_archive_adapter --plan --symbol BTCUSDT --day 2026-09-14
.venv-chroma/bin/python -m bench.applied_trading.public_archive_adapter --fetch-public --symbol BTCUSDT --day 2026-09-14 --output-dir /home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/applied-trading-public-data/archives/BTCUSDT-2026-09-14
.venv-chroma/bin/python -m bench.applied_trading.trade_only_baseline --plan --symbol BTCUSDT
# --run is for the complete fixed 60 UTC days 2026-07-17..2026-09-14 only.
.venv-chroma/bin/python -m bench.applied_trading.trade_only_baseline --run --symbol BTCUSDT --archive-root /home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/applied-trading-public-data/archives --output-dir NEW_ABSOLUTE_RESULT_DIR
```

The official completed one-day 2026-09-14 archive has already been fetched and SHA-checked. It yielded exactly 24 UTC trade-only hourly rows; the 60-day historical diagnostic has **not** run. That diagnostic has one fixed train-only ridge penalty, 40 development days, 20 chronological validation days and a four-hour embargo. It compares lagged momentum/volatility/volume with the same inputs plus signed taker flow at one-hour and four-hour horizons; last-trade prices and a 30-bps roundtrip reference-cost scenario are never represented as executable fills. Missing day or hour invalidates the fixed dataset rather than disappearing from a denominator.

After two or more genuinely complete, cursor-contiguous batches span a **closed** hour, `prospective_hourly_features` can emit as-of features with their source-frame hashes and availability times. A stale book or missing left/right trade marker withholds a decision. Freeze actual development/validation receipts, coefficient and cost policy before a forward paper window. The later `applied_trial/v1` manifest and `paper_driver` require prospective post-boundary entry/exit quote requests, matched no-trade and equal-exposure momentum baselines, every scheduled opportunity, and doubled-cost sensitivity. `paper_supported` requires external source admission; there is no automatic science L1–L5 promotion or order path. The 30-day sequence is in [30_DAY_EXECUTION.md](30_DAY_EXECUTION.md).

```bash
COLLECTOR_SHA256=$(sha256sum bench/applied_trading/public_spot_capture.py | cut -d' ' -f1)
.venv-chroma/bin/python -m bench.applied_trading.prospective_hourly_features --symbol BTCUSDT --expected-collector-sha256 "$COLLECTOR_SHA256" --input-batch ABSOLUTE_COMPLETE_BATCH_1 --input-batch ABSOLUTE_COMPLETE_BATCH_2 --output-dir NEW_ABSOLUTE_FEATURE_DIR
# Only after a real preregistered forward trial contains manifest.json,
# capture-receipt.json, observations.jsonl and quotes.jsonl:
.venv-chroma/bin/python -m bench.applied_trading.paper_driver --trial-dir SEALED_ABSOLUTE_TRIAL_DIR --output-dir NEW_ABSOLUTE_PAPER_RESULT_DIR
```
