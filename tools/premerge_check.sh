#!/usr/bin/env bash
# premerge_check.sh -- pure-bash pre-merge gate for packet branches (LOOP_V1).
# Usage: tools/premerge_check.sh <base-ref> [max_diff_lines]
#
# Examines `git diff <base-ref>..HEAD` in the CURRENT repo (cwd) and FAILs
# (exit 1), naming each violated rule, on:
#   protected-path   -- a protected file/dir is touched (spine, run_state/,
#                       CLAUDE.md, DECISIONS.md, cron/serve-models.sh, agent/,
#                       and ui/ while a ui-session worktree is live);
#   version-pin      -- a canonical version-pin string appears in changed lines
#                       (v0.21.0, gemma-4-26b-a4b-nvfp4, cluster:0.0.13);
#   test-removal     -- a tests/test_*.py file is deleted or renamed;
#   test-skip        -- added lines introduce @pytest.mark.skip / xfail or
#                       pytest.skip(;
#   banned-pattern   -- added lines contain rm -rf, crontab -r, or
#                       ANTHROPIC_API_KEY=;
#   diff-size        -- changed lines (adds+dels) exceed max_diff_lines.
# Exit 0 with an OK summary otherwise. Exit 2 on usage error. No LLM, no
# network; every check is independent and every violation is reported
# (never coerced -- inviolate rule 4).
set -uo pipefail

if [ $# -lt 1 ] || [ $# -gt 2 ]; then
  echo "usage: $0 <base-ref> [max_diff_lines]" >&2
  exit 2
fi
BASE="$1"
MAX_DIFF_LINES="${2:-}"
if [ -n "$MAX_DIFF_LINES" ] && ! [[ "$MAX_DIFF_LINES" =~ ^[0-9]+$ ]]; then
  echo "usage: max_diff_lines must be a non-negative integer, got '$MAX_DIFF_LINES'" >&2
  exit 2
fi

if ! git rev-parse --verify --quiet "$BASE" >/dev/null; then
  echo "FAIL [usage] base-ref '$BASE' does not resolve in this repo" >&2
  exit 2
fi

VIOLATIONS=0
fail() {  # fail <rule> <detail>
  echo "FAIL [$1] $2"
  VIOLATIONS=$((VIOLATIONS + 1))
}

# --- gather the diff once -------------------------------------------------
CHANGED_FILES="$(git diff --name-only "$BASE" HEAD)"
NAME_STATUS="$(git diff --name-status -M "$BASE" HEAD)"
DIFF_TEXT="$(git diff "$BASE" HEAD)"
# Changed lines only (+/-), excluding the +++/--- file headers.
CHANGED_LINES="$(printf '%s\n' "$DIFF_TEXT" | grep -E '^[+-]' | grep -vE '^(\+\+\+|---)' || true)"
ADDED_LINES="$(printf '%s\n' "$CHANGED_LINES" | grep -E '^\+' || true)"

# --- 1. protected paths ---------------------------------------------------
PROTECTED_EXACT=(
  "orchestrator/nara.py"
  "orchestrator/tool_registry.py"
  "schema/iteration_record.schema.json"
  "CLAUDE.md"
  "DECISIONS.md"
  "cron/serve-models.sh"
)
PROTECTED_PREFIX=("run_state/" "agent/")
# ui/ is protected only while a ui-session worktree is live (operating
# contract: a workflow agent racing the UI session forces a manual reconcile).
if git worktree list 2>/dev/null | grep -q "ui-session"; then
  PROTECTED_PREFIX+=("ui/")
fi

while IFS= read -r f; do
  [ -z "$f" ] && continue
  for p in "${PROTECTED_EXACT[@]}"; do
    if [ "$f" = "$p" ]; then
      fail "protected-path" "touches protected file: $f"
    fi
  done
  for p in "${PROTECTED_PREFIX[@]}"; do
    case "$f" in
      "$p"*) fail "protected-path" "touches protected path: $f (under $p)" ;;
    esac
  done
done <<< "$CHANGED_FILES"

# --- 2. version-pin strings ----------------------------------------------
PIN_STRINGS=("v0.21.0" "gemma-4-26b-a4b-nvfp4" "cluster:0.0.13")
for pin in "${PIN_STRINGS[@]}"; do
  if printf '%s\n' "$CHANGED_LINES" | grep -qF "$pin"; then
    fail "version-pin" "changed lines touch pinned string: $pin"
  fi
done

# --- 3. deleted / renamed tests ------------------------------------------
while IFS=$'\t' read -r status f1 f2; do
  [ -z "$status" ] && continue
  case "$status" in
    D)
      case "$f1" in
        tests/test_*.py) fail "test-removal" "test deleted: $f1" ;;
      esac ;;
    R*)
      case "$f1" in
        tests/test_*.py) fail "test-removal" "test renamed: $f1 -> $f2" ;;
      esac ;;
  esac
done <<< "$NAME_STATUS"

# --- 4. added skip/xfail markers -----------------------------------------
if printf '%s\n' "$ADDED_LINES" | grep -qE '@pytest\.mark\.(skip|xfail)'; then
  fail "test-skip" "added line contains @pytest.mark.skip/xfail"
fi
if printf '%s\n' "$ADDED_LINES" | grep -qF 'pytest.skip('; then
  fail "test-skip" "added line contains pytest.skip("
fi

# --- 5. banned patterns in added lines -----------------------------------
BANNED=("rm -rf" "crontab -r" "ANTHROPIC_API_KEY=")
for pat in "${BANNED[@]}"; do
  if printf '%s\n' "$ADDED_LINES" | grep -qF "$pat"; then
    fail "banned-pattern" "added line contains banned pattern: $pat"
  fi
done

# --- 6. diff size budget --------------------------------------------------
# Changed-line count = adds + dels from numstat (binary files count 0).
DIFF_LINE_COUNT="$(git diff --numstat "$BASE" HEAD \
  | awk '{ if ($1 != "-") a += $1; if ($2 != "-") a += $2 } END { print a + 0 }')"
if [ -n "$MAX_DIFF_LINES" ] && [ "$DIFF_LINE_COUNT" -gt "$MAX_DIFF_LINES" ]; then
  fail "diff-size" "diff has $DIFF_LINE_COUNT changed lines > budget $MAX_DIFF_LINES"
fi

# --- verdict --------------------------------------------------------------
FILE_COUNT="$(printf '%s\n' "$CHANGED_FILES" | grep -c . || true)"
if [ "$VIOLATIONS" -gt 0 ]; then
  echo "premerge_check: FAIL ($VIOLATIONS violation(s)) against $BASE..HEAD"
  exit 1
fi
echo "premerge_check: OK -- $FILE_COUNT file(s), $DIFF_LINE_COUNT changed line(s) against $BASE..HEAD"
exit 0
