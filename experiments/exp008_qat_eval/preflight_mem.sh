#!/usr/bin/env bash
# exp008_qat_eval — PRE-FLIGHT free-memory GUARD.
#
# WHY (CLAUDE.md inviolate rules; 2026-06-08 arm-C freeze):
#   This box is a DGX Spark / GB10 with ~121.7 GiB of UNIFIED memory feeding
#   BOTH the GPU (vLLM weights + KV cache) AND the OS/desktop/SSH. There is no
#   separate VRAM. On 2026-06-08 a ~48 GiB unquantized arm-C model was launched
#   beside the ~49 GiB production gemma; the OS starved, SSH+UI went down ~2.5h,
#   and the kernel OOM-killed the scratch container. The honest lesson: a 2nd
#   large model eats the SAME pool the OS lives in, so an over-commit HANGS the
#   machine — it does not merely OOM a container cleanly. Hence a GENEROUS OS
#   margin and a refuse-BEFORE-docker-run guard.
#
# MEMORY SOURCE (load-bearing):
#   * NEVER nvidia-smi — its memory fields read N/A on the GB10 unified arch.
#   * Read /proc/meminfo MemAvailable, NOT MemFree. MemFree understates usable
#     memory by the reclaimable page cache (measured live 2026-06-09: MemFree
#     ~11 GiB vs MemAvailable ~33 GiB). MemAvailable is the kernel's own
#     estimate of memory usable to START a new app without swapping — exactly
#     the launch-safety question this guard asks.
#
# CONTRACT:
#   preflight_mem_guard <model_need_gib>
#     returns 0  -> proceed (MemAvailable >= need + OS_MARGIN_GIB)
#     returns 1  -> refuse  (would risk OS starvation)
#     returns 2  -> cannot read memory -> FAIL-CLOSED
#   The sourcer MUST check the return and abort `docker run` on non-zero.
#
# Typical needs (caller-passed): arm B (llama.cpp Q4_0 GGUF) ~16; arm C
#   (vLLM unquantized, --gpu-memory-utilization 0.46 -> reserved budget) ~56;
#   on-box Qwen skeptic (--gpu-memory-utilization 0.25) ~30.
set -uo pipefail

# OS safety headroom ON TOP of the model need. GENEROUS by design: the freeze
# happened with ~60 GiB nominally free, so a thin margin is disproven by the
# incident. 30 GiB (~25% of the 121.7 GiB pool) covers the OS+desktop+SSH+
# NemoClaw gateway+UI working set, vLLM allocation transients and KV-cache
# growth beyond the static weight figure, and the fact that vLLM sizes
# --gpu-memory-utilization against MemTotal (not instantaneous free).
# HARD-PINNED (inviolate rule 7): do not quietly loosen this.
OS_MARGIN_GIB=30

# Log helper — matches serve_qat.sh's "[HH:MM:SS] msg" style; goes to stderr so
# it never pollutes a sourcer's stdout.
preflight_log() { echo "[$(date +%T)] $*" >&2; }

preflight_mem_guard() {
  local model_need_gib="${1:?model_need_gib required (GiB)}"

  # Strip any fractional part -> floored integer GiB (conservative; floor on the
  # NEED side rounds the requirement DOWN, but we also floor MemAvailable below
  # which is the conservative direction for the gate).
  local need_gib="${model_need_gib%.*}"
  if ! [[ "$need_gib" =~ ^[0-9]+$ ]]; then
    preflight_log "REFUSE preflight_mem: model_need_gib='${model_need_gib}' is not numeric (fail-closed)"
    return 2
  fi

  # 1. Read MemAvailable from /proc/meminfo (NEVER nvidia-smi). The source path
  #    is /proc/meminfo in all real use; PREFLIGHT_MEMINFO overrides it ONLY for
  #    the hermetic test harness (it lets the test inject a known MemAvailable
  #    so it exercises THIS function rather than a copy).
  local meminfo="${PREFLIGHT_MEMINFO:-/proc/meminfo}"
  local avail_kb
  avail_kb=$(awk '/^MemAvailable:/ {print $2}' "$meminfo" 2>/dev/null)
  if [[ -z "$avail_kb" || ! "$avail_kb" =~ ^[0-9]+$ ]]; then
    preflight_log "REFUSE preflight_mem: could not read MemAvailable from /proc/meminfo (fail-closed)"
    return 2
  fi
  local avail_gib=$(( avail_kb / 1024 / 1024 ))          # integer GiB, floored
  local required_gib=$(( need_gib + OS_MARGIN_GIB ))

  # 2. Refuse when available < need + margin.
  if (( avail_gib < required_gib )); then
    preflight_log "REFUSE preflight_mem: MemAvailable=${avail_gib}GiB < need(${need_gib})+margin(${OS_MARGIN_GIB})=${required_gib}GiB on GB10 unified pool (total~121.7GiB). Launch would risk OS starvation (ref: 2026-06-08 arm-C freeze). Free memory (e.g. stop vllm-qwen) or use a smaller arm, then retry."
    return 1
  fi
  preflight_log "PASS preflight_mem: MemAvailable=${avail_gib}GiB >= need(${need_gib})+margin(${OS_MARGIN_GIB})=${required_gib}GiB. Proceeding."
  return 0
}

# Allow direct invocation for testing/manual checks: `preflight_mem.sh <need_gib>`.
# When sourced (BASH_SOURCE[0] != $0) this block is skipped and only the function
# is exported into the caller's shell.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  preflight_mem_guard "${1:?usage: preflight_mem.sh <model_need_gib>}"
  exit $?
fi
