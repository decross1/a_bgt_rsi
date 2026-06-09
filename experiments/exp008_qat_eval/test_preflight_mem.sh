#!/usr/bin/env bash
# exp008_qat_eval — test harness for preflight_mem.sh.
#
# Verifies both branches DETERMINISTICALLY (independent of the live box state)
# by injecting a known MemAvailable through the PREFLIGHT_MEMINFO override, so
# the tests exercise the REAL shipped preflight_mem_guard (not a copy). Also
# runs one LIVE check against the real /proc/meminfo.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${HERE}/preflight_mem.sh"

fail=0
check() {  # check <label> <expected_rc> <actual_rc>
  local label="$1" want="$2" got="$3"
  if [[ "$got" == "$want" ]]; then
    echo "PASS: ${label} (rc=${got})"
  else
    echo "FAIL: ${label} (expected rc=${want}, got rc=${got})"; fail=1
  fi
}

# Drive the REAL guard with an injected MemAvailable (GiB) via PREFLIGHT_MEMINFO.
run_with_avail_gib() {  # run_with_avail_gib <avail_gib> <need_gib>
  local avail_gib="$1" need_gib="$2" rc tmp
  tmp="$(mktemp)"
  printf 'MemTotal:       127600524 kB\nMemAvailable:   %s kB\n' \
    "$(( avail_gib * 1024 * 1024 ))" > "$tmp"
  PREFLIGHT_MEMINFO="$tmp" preflight_mem_guard "$need_gib"; rc=$?
  rm -f "$tmp"
  return $rc
}

echo "=== deterministic branch tests (injected MemAvailable, real guard) ==="

# OVER-budget: arm C need=56, +30 margin = 86 required; inject 40 GiB avail -> REFUSE.
run_with_avail_gib 40 56; check "OVER-budget arm C (avail 40 < 86) refuses" 1 $?

# UNDER-budget: Qwen need=30, +30 margin = 60 required; inject 92 GiB avail -> PASS.
run_with_avail_gib 92 30; check "UNDER-budget qwen (avail 92 >= 60) passes" 0 $?

# Edge: exactly at the threshold (avail == required) PASSES (>=).
run_with_avail_gib 46 16; check "arm B at threshold (avail 46 == 46) passes" 0 $?

# Edge: one GiB under the threshold REFUSES.
run_with_avail_gib 45 16; check "arm B one under (avail 45 < 46) refuses" 1 $?

# Fail-closed: unreadable meminfo -> rc 2.
PREFLIGHT_MEMINFO=/nonexistent_meminfo_xyz preflight_mem_guard 16
check "unreadable meminfo fails closed" 2 $?

# Fail-closed: non-numeric need -> rc 2.
run_with_avail_gib 92 "not-a-number"; check "non-numeric need fails closed" 2 $?

echo "=== live box check (real /proc/meminfo, advisory) ==="
# Real reading via the SHIPPED guard. We don't assert a fixed rc (box state
# varies); we just confirm it runs, reads MemAvailable, and returns 0/1/2.
preflight_mem_guard 16; live_rc=$?
case "$live_rc" in
  0|1|2) echo "PASS: live guard ran and returned a valid rc=${live_rc}";;
  *) echo "FAIL: live guard returned unexpected rc=${live_rc}"; fail=1;;
esac

# Confirm the shipped guard never INVOKES nvidia-smi (prohibitory comments that
# mention the word are fine; an actual command call on a non-comment line is not).
if grep -vE '^[[:space:]]*#' "${HERE}/preflight_mem.sh" | grep -q 'nvidia-smi'; then
  echo "FAIL: preflight_mem.sh invokes nvidia-smi on a non-comment line (forbidden on GB10)"; fail=1
else
  echo "PASS: preflight_mem.sh does not invoke nvidia-smi (only mentions it in comments)"
fi

echo
if (( fail == 0 )); then echo "ALL TESTS PASSED"; exit 0; else echo "TESTS FAILED"; exit 1; fi
