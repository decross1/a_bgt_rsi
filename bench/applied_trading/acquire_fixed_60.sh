#!/usr/bin/env bash
# Fixed-calendar public historical acquisition; execute only outside GPU windows.
set -euo pipefail

project_repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)
archive_root=/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/applied-trading-public-data/archives
archive_attempt_root="$archive_root/_attempts"
python_bin="$project_repo/.venv-chroma/bin/python"
cd "$project_repo"

archive_source_sha=$(sha256sum bench/applied_trading/public_archive_adapter.py | cut -d ' ' -f 1)
baseline_source_sha=$(sha256sum bench/applied_trading/trade_only_baseline.py | cut -d ' ' -f 1)
[[ "$archive_source_sha" == 740944d154778ab7f933523b7b7103c85e38719510e6debd53821e57131a179a ]] || {
  echo 'Archive fetcher changed; freeze and review a new 60-day acquisition plan.' >&2
  exit 2
}
[[ "$baseline_source_sha" == 7addeda71a319e8d3670f7b3ab2a1bea4e8a8fd58585a92c858d14709a30935e ]] || {
  echo 'Reference baseline changed; freeze and review a new registered result plan.' >&2
  exit 2
}
[[ -d "$archive_root" && ! -L "$archive_root" && ! -L "$archive_attempt_root" ]] || {
  echo 'Registered archive root is missing or redirected.' >&2
  exit 2
}
mkdir -p -- "$archive_attempt_root"

for offset in {0..59}; do
  day=$(date -u -d "2026-07-17 +${offset} days" +%F)
  canonical="$archive_root/BTCUSDT-$day"
  if [[ -e "$canonical" || -L "$canonical" ]]; then
    echo "PRESERVED_EXISTING $day; admission deferred to full 60-day baseline" >&2
    continue
  fi
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  attempt="$archive_attempt_root/BTCUSDT-$day-$stamp-$$"
  stdout_log="$archive_attempt_root/BTCUSDT-$day-$stamp-$$.stdout.log"
  stderr_log="$archive_attempt_root/BTCUSDT-$day-$stamp-$$.stderr.log"
  echo "ISSUED_PUBLIC_FETCH $day $attempt" >&2
  if "$python_bin" -m bench.applied_trading.public_archive_adapter \
      --fetch-public --symbol BTCUSDT --day "$day" --output-dir "$attempt" \
      >"$stdout_log" 2>"$stderr_log"; then
    [[ -f "$attempt/fetch-receipt.json" && -f "$attempt/processed/source-receipt.json" && ! -e "$canonical" ]] || {
      echo "SUCCESS_SHAPE_MISSING_OR_CANONICAL_COLLISION $day; preserve attempt" >&2
      exit 2
    }
    # The public adapter can process a day with fewer than 24 trade hours; do
    # not place such a day in the exact fixed-calendar baseline archive root.
    if ! "$python_bin" - "$attempt" "$day" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

attempt, day = Path(sys.argv[1]), sys.argv[2]
fetch_raw = (attempt / "fetch-receipt.json").read_bytes()
source_raw = (attempt / "processed/source-receipt.json").read_bytes()
flow_raw = (attempt / "processed/hourly-flow.jsonl").read_bytes()
fetch, source = json.loads(fetch_raw), json.loads(source_raw)
if not (fetch.get("schema") == "applied-trial-binance-archive-public-fetch/v1"
        and fetch.get("symbol") == source.get("symbol") == "BTCUSDT"
        and fetch.get("day") == source.get("day") == day
        and source.get("hourly_rows") == 24
        and len(flow_raw.splitlines()) == 24
        and fetch.get("processed_source_receipt_sha256")
            == hashlib.sha256(source_raw).hexdigest()
        and source.get("hourly_flow_sha256")
            == hashlib.sha256(flow_raw).hexdigest()):
    raise SystemExit("staged historical day is not a complete bound 24-hour child")
PY
    then
      echo "SUCCESS_DAY_INCOMPLETE $day; preserve attempt" >&2
      exit 2
    fi
    mv -T -- "$attempt" "$canonical"
    echo "STAGED_VERIFIED_DAY $day $canonical" >&2
  else
    echo "FAILED_PUBLIC_FETCH $day; preserve attempt/logs and stop, no selected-day skip" >&2
    exit 1
  fi
done

echo 'FETCH_LOOP_CLOSED; now run the exact 60-day baseline reader for source/day/hour admission.' >&2
