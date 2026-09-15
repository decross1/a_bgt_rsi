# One H1 Spot research sequence alongside model evaluation

The public BTCUSDT archive, fixed 60-day reference score, five-minute capture
timer, H1 plan, and due evaluator are separate stages. Bounded capture and the
offline due evaluator can coexist with model evaluation under independent
locks and a 21 GiB available-memory preflight. Heavy historical acquisition
remains separately scheduled. Dated receipts record the exact source versions,
publications, and services that ran; a changed source requires a new future plan.

The historical study is trade-only, not L2. It tests a lagged signed-taker-flow
feature beyond the same lagged return/volatility/volume baseline on a fixed
40-day development/20-day validation split, 4-hour embargo, 1h primary/4h
secondary horizons. Its 10 bps fee plus 5 bps slippage per leg and last-trade
prices are **reference costs/prices**, not executable fills. The REST H1 pilot
is another type: a 2–5h forward displayed-quote diagnostic with a code-owned
unfitted engineering preset. `sequence_valid=false`, `paper_supported=false`,
and no orders or account requests throughout. Unknown outcomes have null
all-scheduled returns. [Historical adapter](https://github.com/binance/binance-public-data),
[mechanism transfer](H1_STRATEGIC_TRANSFER.md).

From the delivered canonical checkout, after all model cohorts/supervisors
have closed and original residents and Nara are restored, choose **one**
checkout/source bundle for the historical acquisition and score. The existing
2026-09-14 archive receipt pins the current fetcher SHA; do not edit the
fetcher midway. Root owns the actual heavy acquisition and service activation:

```bash
cd /home/decross1/projects/a_bgt_rsi
sha256sum bench/applied_trading/public_archive_adapter.py bench/applied_trading/trade_only_baseline.py
.venv-chroma/bin/python -m bench.applied_trading.trade_only_baseline --plan --symbol BTCUSDT
bash bench/applied_trading/acquire_fixed_60.sh
mkdir -p /home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/applied-trading-public-data/reference-results
.venv-chroma/bin/python -m bench.applied_trading.trade_only_baseline --run --symbol BTCUSDT --archive-root /home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/applied-trading-public-data/archives --output-dir /home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/applied-trading-public-data/reference-results/BTCUSDT-fixed60-20260915-a
mkdir -p /home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/applied-trading-public-data/publications
.venv-chroma/bin/python -m bench.applied_trading.publication_index --result-child /home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/applied-trading-public-data/reference-results/BTCUSDT-fixed60-20260915-a --publish-baseline
```

The acquisition script only publishes each of 60 exact UTC day directories
after its official ZIP/CHECKSUM and 24 processed hourly rows pass. It records
failed day-level attempts separately; historical failed-GET per-request counts
are unavailable. The baseline reader rehashes all ZIP/CHECKSUM/fetch/processed
source files before scoring. The publication CLI does another complete rehash,
requires its 60 daily rows to equal the result, checks 476 1h and 473 4h
private validation predictions, and writes immutable
`publications/source-gate-BTCUSDT-fixed60-v1.json` first, then
`publications/fixed60-BTCUSDT-v1.json` last. A gate alone does not show scores;
the UI binds gate, raw result, private predictions and source hashes. Partial
runs are preserved; if the reference output child already exists after a failed
attempt, choose a **new** direct-child suffix rather than overwriting it, and
pass that exact child to `publication_index`. Partial days/results never get an
index. Source hash changes cause admission failure
rather than quiet version substitution.

For forward capture, review source hashes and current scheduler state, then
perform a **fresh independent** venue-tail bootstrap after the model program:

```bash
cd /home/decross1/projects/a_bgt_rsi
sha256sum bench/applied_trading/public_spot_capture.py bench/applied_trading/hourly_capture.py bench/applied_trading/capture_tick.py
.venv-chroma/bin/python -m bench.applied_trading.capture_tick --plan
.venv-chroma/bin/python -m bench.applied_trading.capture_tick --bootstrap-new --max-wall-s 150
mkdir -p "$HOME/.config/systemd/user"
cp bench/applied_trading/systemd/applied-h1-capture.service bench/applied_trading/systemd/applied-h1-capture.timer "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now applied-h1-capture.timer
```

If the saved `_scheduler/state.json` from the older smoke lineage exists, the
manual bootstrap requires the exact raw SHA in `--abandon-state-sha256`; the
wrapper archives it. The five-minute timer starts 30 seconds after the boundary
and holds its own scheduler lock. It does not acquire model/weekly/coordinator
leases because it uses no model or GPU. A pause marker, unreadable memory
measurement, or less than 21 GiB available memory produces a zero-GET skip.
This is a start-time check; systemd retains the 512 MiB capture and 1 GiB due
worker caps, while the model controller continues its own continuous monitoring. After a verified >15-minute
resource gap, it journals the missing interval and starts a **new** independent
tail lineage; it does not stitch old and new cursors. Source/schema drift or an
incomplete capture branch blocks. Choose the H1 start at least 90 minutes after
a fresh bootstrap so its unusable warmup lies outside the pilot input and a
prior-hour witness can exist. The plan can be published immediately after
bootstrap; there is no need to wait 90 minutes merely to freeze it. If capture
is not stable by that future start, the due result will be unknown.

Freeze one actual future UTC HH:05:00 start at least 20 minutes after local
publication and at least 90 minutes after the fresh bootstrap. The plan builder
fills **real** source/topic SHA-256 values and the fixed unfitted candidate
and matched momentum baseline; it never fabricates development hashes. For
example, replace the start and study ID below with a future time and a unique
registered suffix before running:

```bash
mkdir -p /home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/applied-trading-public-data/prospective-studies
.venv-chroma/bin/python -m bench.applied_trading.h1_pilot_lifecycle --publish-plan --study-id h1-btcusdt-rest-20260915-a01 --forward-start-utc 2026-09-15T16:05:00Z --hours 3
cp bench/applied_trading/systemd/applied-h1-rest-due@.service bench/applied_trading/systemd/applied-h1-rest-due@.timer "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now applied-h1-rest-due@h1-btcusdt-rest-20260915-a01.timer
```

The example start is **not** an executed or currently frozen study. If it is
already in the past or capture is not stable, choose a later HH:05 and a new ID;
do not alter an existing published plan. The plan receipt binds actual raw
plan/topic SHA and source bundle, with local O_EXCL creation time before start.
It labels `freeze_proof=local_exclusive_write_only` and
`external_plan_freeze_proof=unverified`; a separate externally timestamped
Git/remote witness would be needed for a stronger preregistration claim. The
H1 study remains a plumbing/diagnostic pilot either way.

The due timer checks at minute 3 after each five-minute capture boundary and
never makes a market GET. Before `forward_end + 1h hold + 10m exit reserve`,
it is a no-op. After due, it retains its own worker lock and the same memory/pause
preflight, scans at most 10,000 capture child names and selects at most 96 ordered
batches from a fixed 90-minute lookback through the frozen exit horizon. It
reruns source projection, exact GET/cursor/as-of feature admission and the
unchanged REST quote driver. A quote must come from a GET **started** after
the decision/hold boundary; L5 display and lastUpdateId do not prove fill or
diff-depth chronology. It writes the source-bound private ledger and raw result
into a new study child, then an immutable result publication receipt. Unknown
source/quote cells yield `closed_with_missing_evidence` and null paired
all-scheduled returns. If the source is late it retries for at most 30 minutes
after due; then it publishes `closed_missing_source` with all declared cells
unknown and both scores null. Resource or operator-pause skips retry at the next timer tick; a final
published result turns later ticks into cheap `already_closed` checks. No
manual memory of the hold/exit horizon is required.

The applied sidecar links a **known prior** dealer adverse-selection/inventory
mechanism to a falsifiable predictive proxy; it does not claim that REST sizes
identify a dealer or strategic causal effect. The next bounded GT question is
whether a controlled quote/abstain agent with explicit spread reward,
adverse-selection loss and inventory penalty chooses a different quote policy
from an analytical/scripted best-response baseline when order-flow and
inventory signals change. Score that independent agent decision task first;
only then compare its directional predictions with timestamped quote-supply
features. The synthetic market canaries calibrate model reasoning, not market
or agent-behavior evidence. This application has no science L0–L5 promotion,
and H3 event prediction remains WATCH.
