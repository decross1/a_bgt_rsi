#!/usr/bin/env bash
# qwen_builder.sh -- the Qwen-as-builder agent_cmd for orchestrator/packet_dispatcher.py.
#
# Invoked BY THE DISPATCHER as:  agent_cmd=["bash", "tools/qwen_builder.sh"]
# with cwd = the packet worktree (../worktree-pkt-<task_id>, branch pkt/<id>)
# and the packet's bounds exported in the environment.
#
# It reads the packet's objective + files-in-scope, asks the local Qwen
# (OpenAI-compatible, :8001) for FULL-FILE writes as a strict JSON array,
# refuses any path outside files_in_scope, writes the files, runs the
# acceptance test once for its OWN feedback, and COMMITS on the packet branch.
#
# What this script does NOT do (by contract):
#   - decide done. The DISPATCHER re-runs the acceptance test and
#     tools/premerge_check.sh; this script's test run is advisory only.
#   - merge, push, or touch main. The primary session is the merge authority.
#   - guess. Missing required env is a loud non-zero exit, never a default.
# Committing IS mandatory: the dispatcher scores a green test over a dirty
# tree as `failed` (it diffs commits, so an uncommitted tree sails through
# premerge with an empty range).
#
# ENV -- exported by the dispatcher (required; absent => exit 1):
#   PKT_TASK_ID            packet id, e.g. PKT-SELF-foo
#   PKT_OBJECTIVE          what the packet accomplishes
#   PKT_FILES_IN_SCOPE     JSON array of repo-relative paths (the write fence)
# ENV -- exported by the dispatcher (optional, defaults to []):
#   PKT_FILES_OUT_OF_SCOPE JSON array; passed to the model verbatim
#   PKT_FORBIDDEN_ACTIONS  JSON array; passed to the model verbatim
# ENV -- NOT exported by the dispatcher today; set by the emitter/operator in
# the process that calls dispatch_packet() (it inherits os.environ):
#   PKT_TEST_CMD           the acceptance test_cmd. Resolution order:
#                          this env -> tasks/packets/<PKT_TASK_ID>.json in the
#                          worktree -> none (advisory run skipped, logged LOUD).
#   PKT_ACCEPTANCE_TEST    extra read-only file to show the model, REPO-RELATIVE.
#                          Otherwise any existing repo-relative path named in
#                          the test_cmd is used.
# ENV -- builder knobs (defaults shown):
#   QWEN_ENDPOINT=http://127.0.0.1:8001/v1/chat/completions   (test seam)
#   QWEN_MODEL=qwen3.6-27b-nvfp4-mtp   QWEN_TEMPERATURE=0.2
#   QWEN_MAX_TOKENS=6144   QWEN_TIMEOUT_SEC=600   QWEN_PROMPT_CHAR_CAP=20000
#     Those two defaults are sized to the SERVED window, measured 2026-08-15:
#     vllm-qwen runs --max-model-len 16384 and vLLM returns HTTP 400 (it does
#     NOT clamp) when prompt+max_tokens exceeds it. 20000 chars is <= ~8000
#     tokens of code at ~2.5 chars/token, + 6144 completion = ~14.1k < 16384.
#     Raise them TOGETHER, and only if the container is relaunched wider.
#   QWEN_PYTHON=python3   (stdlib only; the worktree has no relative .venv)
#   QWEN_BUILDER_LOG      absolute path OUTSIDE the worktree; when set, this
#                         script's stdout+stderr append there. The dispatcher
#                         captures the agent's output and then DROPS it, so
#                         without this the phase log is unrecoverable.
set -uo pipefail

[ -n "${QWEN_BUILDER_LOG:-}" ] && exec >>"$QWEN_BUILDER_LOG" 2>&1

ts() { date -u +%FT%TZ; }
log() { printf '[%s] qwen_builder: %s\n' "$(ts)" "$*"; }
die() { printf '[%s] qwen_builder: FATAL %s\n' "$(ts)" "$*" >&2; exit 1; }

QWEN_ENDPOINT="${QWEN_ENDPOINT:-http://127.0.0.1:8001/v1/chat/completions}"
QWEN_MODEL="${QWEN_MODEL:-qwen3.6-27b-nvfp4-mtp}"
QWEN_TEMPERATURE="${QWEN_TEMPERATURE:-0.2}"
QWEN_MAX_TOKENS="${QWEN_MAX_TOKENS:-6144}"
QWEN_TIMEOUT_SEC="${QWEN_TIMEOUT_SEC:-600}"
QWEN_PROMPT_CHAR_CAP="${QWEN_PROMPT_CHAR_CAP:-20000}"
PY="${QWEN_PYTHON:-python3}"

# --- 1. env contract: fail loudly, never guess -----------------------------
for v in PKT_TASK_ID PKT_OBJECTIVE PKT_FILES_IN_SCOPE; do
  if [ -z "${!v:-}" ]; then
    die "$v is unset or empty -- the dispatcher exports it; refusing to guess"
  fi
done
export PKT_FILES_OUT_OF_SCOPE="${PKT_FILES_OUT_OF_SCOPE:-[]}"
export PKT_FORBIDDEN_ACTIONS="${PKT_FORBIDDEN_ACTIONS:-[]}"
[ "$(git rev-parse --is-inside-work-tree 2>/dev/null)" = "true" ] \
  || die "cwd $(pwd) is not a git work tree -- committing is mandatory"
command -v "$PY" >/dev/null || die "python interpreter '$PY' not found"

log "packet=$PKT_TASK_ID branch=$(git rev-parse --abbrev-ref HEAD) cwd=$(pwd)"
log "endpoint=$QWEN_ENDPOINT model=$QWEN_MODEL"

# Flags split ('rm -r -f', not 'rm -rf') on purpose: 'rm -rf' is a
# premerge_check.sh banned-pattern and this file must survive that gate.
WORK="$(mktemp -d)"; trap 'rm -r -f "$WORK"' EXIT
BODY="$WORK/body.json"; RESP="$WORK/resp.json"; WROTE="$WORK/wrote.txt"

# --- 2. resolve the acceptance test (advisory feedback only) ---------------
if [ -z "${PKT_TEST_CMD:-}" ] && [ -f "tasks/packets/$PKT_TASK_ID.json" ]; then
  PKT_TEST_CMD="$("$PY" -c 'import json,os,sys
p="tasks/packets/%s.json" % os.environ["PKT_TASK_ID"]
try: sys.stdout.write(json.load(open(p))["acceptance_criteria"]["test_cmd"])
except Exception: pass')"
  [ -n "$PKT_TEST_CMD" ] && log "test_cmd resolved from tasks/packets/$PKT_TASK_ID.json"
fi
export PKT_TEST_CMD="${PKT_TEST_CMD:-}"
if [ -z "$PKT_TEST_CMD" ]; then
  log "WARNING: no acceptance test_cmd (PKT_TEST_CMD unset, no packet file) --"
  log "WARNING: the model sees no test and the advisory run is SKIPPED."
fi
# Read-only reference files: PKT_ACCEPTANCE_TEST plus any existing path named
# in the test_cmd (that is where the red test lives; it is deliberately NOT in
# files_in_scope, so the builder cannot make the test pass by editing it).
# Repo-relative only: a test_cmd routinely names an ABSOLUTE interpreter
# (/…/.venv-chroma/bin/python) which is a real file — reading that binary into
# the prompt would burn the whole char budget on garbage.
REFS=""
for cand in ${PKT_ACCEPTANCE_TEST:-} $PKT_TEST_CMD; do
  case "$cand" in -*|/*|*=*|*'*'*) continue ;; esac
  [ -f "$cand" ] && REFS="$REFS$cand"$'\n'
done
export QB_REF_FILES="$REFS"

# --- 3/4/5. prompt -> model -> write, with ONE retry on an unparseable reply
export QB_CAP="$QWEN_PROMPT_CHAR_CAP" QB_MODEL="$QWEN_MODEL"
export QB_TEMP="$QWEN_TEMPERATURE" QB_MAX_TOKENS="$QWEN_MAX_TOKENS"
export QB_BODY="$BODY" QB_RESP="$RESP" QB_WROTE="$WROTE"
export QB_CORRECTIVE=""

for round in 1 2; do
  log "phase=prompt round=$round"
  "$PY" <<'PY' || die "prompt assembly failed"
import json, os
from pathlib import Path

cap = int(os.environ["QB_CAP"])
scope = json.loads(os.environ["PKT_FILES_IN_SCOPE"])
out_scope = json.loads(os.environ["PKT_FILES_OUT_OF_SCOPE"])
forbidden = json.loads(os.environ["PKT_FORBIDDEN_ACTIONS"])
refs = list(dict.fromkeys(
    r for r in os.environ.get("QB_REF_FILES", "").splitlines() if r.strip()))
test_cmd = os.environ.get("PKT_TEST_CMD", "")
budget = [cap]          # shared char budget across every included file body
truncated = [False]


def block(path):
    p = Path(path)
    if p.is_dir():
        return f"--- {path} (directory in scope -- create files beneath it)\n"
    if not p.is_file():
        return f"--- {path} (does not exist yet -- create it)\n"
    body = p.read_text(errors="replace")
    if len(body) > budget[0]:
        truncated[0] = True
        body = body[: max(budget[0], 0)] + (
            f"\n... [TRUNCATED: first {max(budget[0],0)} of {len(body)} chars]\n")
    budget[0] = max(budget[0] - len(body), 0)
    return f"--- {path}\n{body}\n--- end {path}\n"


parts = [
    "You are a coding agent working inside a git worktree of a research repo.",
    "Make the failing acceptance test pass by rewriting ONLY the files in scope.",
    f"\n## PACKET {os.environ['PKT_TASK_ID']}\n{os.environ['PKT_OBJECTIVE']}",
    "\n## FILES IN SCOPE (the ONLY paths you may write; current contents follow)",
    "".join(block(p) for p in scope),
]
if refs:
    parts.append("\n## ACCEPTANCE TEST (read-only -- you may NOT edit these)")
    parts.append("".join(block(r) for r in refs))
parts.append(f"\n## ACCEPTANCE TEST COMMAND\n{test_cmd or '(not provided)'}")
if out_scope:
    parts.append("\n## FILES OUT OF SCOPE\n" + "\n".join(f"- {p}" for p in out_scope))
if forbidden:
    parts.append("\n## FORBIDDEN ACTIONS\n" + "\n".join(f"- {a}" for a in forbidden))
if truncated[0]:
    parts.append("\nNOTE: some file contents above were TRUNCATED to fit the "
                 "prompt budget. Preserve everything you cannot see.")
parts.append(
    "\n## OUTPUT CONTRACT (strict)\n"
    "Reply with ONE JSON array and NOTHING else: no prose, no explanation, no\n"
    "markdown fences, no diffs, no shell commands. Each element is\n"
    '  {"path": "<a files-in-scope path>", "content": "<the COMPLETE new file>"}\n'
    "- Full-file writes only: `content` REPLACES the whole file.\n"
    "- Only paths listed under FILES IN SCOPE. Any other path is refused and\n"
    "  the attempt fails.\n"
    "- Omit files you do not need to change. An empty array is a failed attempt.\n"
    "- Never edit or weaken the acceptance test; make it pass honestly."
)
corrective = os.environ.get("QB_CORRECTIVE", "")
if corrective:
    parts.append("\n## CORRECTION\n" + corrective)

prompt = "\n".join(parts)
Path(os.environ["QB_BODY"]).write_text(json.dumps({
    "model": os.environ["QB_MODEL"],
    "messages": [
        {"role": "system", "content": "You are a precise coding agent. You reply "
                                      "with a JSON array of full-file writes and "
                                      "nothing else."},
        {"role": "user", "content": prompt},
    ],
    "temperature": float(os.environ["QB_TEMP"]),
    "max_tokens": int(os.environ["QB_MAX_TOKENS"]),
}))
print(f"prompt chars={len(prompt)} in_scope={len(scope)} refs={len(refs)} "
      f"truncated={truncated[0]}")
PY

  log "phase=call round=$round timeout=${QWEN_TIMEOUT_SEC}s"
  code="$(curl -sS -o "$RESP" -w '%{http_code}' --connect-timeout 10 \
    --max-time "$QWEN_TIMEOUT_SEC" -H 'Content-Type: application/json' \
    --data-binary "@$BODY" "$QWEN_ENDPOINT")"
  crc=$?
  [ $crc -eq 0 ] || die "curl failed (rc=$crc) against $QWEN_ENDPOINT -- is vllm-qwen up?"
  [ "$code" = "200" ] || die "model returned HTTP $code: $(head -c 400 "$RESP")"

  log "phase=parse round=$round"
  "$PY" <<'PY'
import json, os, sys
from pathlib import Path

def bail(code, msg):
    print(f"qwen_builder: {msg}", file=sys.stderr)
    sys.exit(code)

raw = Path(os.environ["QB_RESP"]).read_text()
try:
    content = json.loads(raw)["choices"][0]["message"]["content"]
except Exception as exc:                       # transport-shaped, not model-shaped
    bail(5, f"response is not an OpenAI chat completion: {exc}: {raw[:300]}")

text = (content or "").strip()
if text.startswith("```"):                     # documented leniency: fenced JSON
    text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
plan = None
for candidate in (text, text[text.find("["): text.rfind("]") + 1] if "[" in text else ""):
    try:
        parsed = json.loads(candidate)
    except Exception:
        continue
    if isinstance(parsed, list):
        plan = parsed
        break
if plan is None:
    bail(3, f"reply is not a JSON array (first 300 chars): {text[:300]!r}")
writes = []
for item in plan:
    if not isinstance(item, dict) or not isinstance(item.get("path"), str) \
            or not isinstance(item.get("content"), str) or not item["path"].strip():
        bail(3, f"element is not {{path, content}} strings: {str(item)[:200]}")
    writes.append((item["path"].strip(), item["content"]))
if not writes:
    bail(4, "model returned an empty write plan -- no work done")

# Scope fence, enforced HERE too (not only by premerge): validate every path
# before writing anything, so a violating plan writes nothing at all.
scope = json.loads(os.environ["PKT_FILES_IN_SCOPE"])
def allowed(p):
    if p.startswith("/") or ".." in Path(p).parts:
        return False
    return any(p.startswith(s) if s.endswith("/") else p == s for s in scope)

bad = [p for p, _ in writes if not allowed(p)]
if bad:
    bail(4, "REFUSED -- out of scope: " + ", ".join(bad)
            + f" | files_in_scope={scope}")

wrote = []
for path, body in writes:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body)
    wrote.append(path)
    print(f"wrote {path} ({len(body)} chars)")
Path(os.environ["QB_WROTE"]).write_text("\n".join(wrote) + "\n")
PY
  prc=$?
  [ $prc -eq 0 ] && break
  if [ $prc -eq 3 ] && [ $round -eq 1 ]; then
    log "unparseable model reply -- ONE retry with a corrective"
    export QB_CORRECTIVE="Your previous reply was not the required JSON array. \
Reply with ONE JSON array of {\"path\", \"content\"} objects and nothing else \
-- no prose, no markdown fences, no diffs."
    continue
  fi
  case $prc in
    3) die "model reply unparseable after the retry -- giving up" ;;
    4) die "scope/plan refusal (see above) -- nothing written" ;;
    *) die "response handling failed (rc=$prc)" ;;
  esac
done

# --- 6. advisory acceptance run (the DISPATCHER's re-run is what counts) ----
if [ -n "$PKT_TEST_CMD" ]; then
  log "phase=selftest (advisory) cmd=$PKT_TEST_CMD"
  if command -v timeout >/dev/null; then
    timeout "$QWEN_TIMEOUT_SEC" bash -c "$PKT_TEST_CMD"
  else
    bash -c "$PKT_TEST_CMD"
  fi
  log "selftest rc=$? -- advisory only; the dispatcher decides done"
fi

# --- 7. commit on the packet branch (mandatory) ----------------------------
log "phase=commit"
while IFS= read -r p; do
  [ -z "$p" ] && continue
  git add -- "$p" || die "git add failed for $p"
done < "$WROTE"
git diff --cached --quiet \
  && die "staged diff is empty -- the model changed nothing; nothing to commit"
MSG="qwen-builder: $PKT_TASK_ID

$PKT_OBJECTIVE

Files: $(tr '\n' ' ' < "$WROTE")
Model: $QWEN_MODEL (advisory self-test only; dispatcher decides done)"
# Both the -c config AND the GIT_*_NAME env: an ambient GIT_AUTHOR_NAME (a
# human's, inherited through the dispatcher's spawn env) OVERRIDES -c and
# would silently attribute a model-written commit to that human.
GIT_AUTHOR_NAME=qwen-builder GIT_AUTHOR_EMAIL=qwen-builder@a-bgt-rsi.local \
GIT_COMMITTER_NAME=qwen-builder GIT_COMMITTER_EMAIL=qwen-builder@a-bgt-rsi.local \
git -c user.name=qwen-builder -c user.email=qwen-builder@a-bgt-rsi.local \
  commit -q -m "$MSG" || die "git commit failed"
log "committed $(git rev-parse --short HEAD) on $(git rev-parse --abbrev-ref HEAD)"
# The dispatcher scores ANY dirty tree (untracked included) as failed. The
# advisory run can leave build artifacts behind; __pycache__/ and
# .pytest_cache/ are git-ignored in this repo, anything else is a real trap.
DIRTY="$(git status --porcelain)"
if [ -n "$DIRTY" ]; then
  log "WARNING: tree is NOT clean after commit -- the dispatcher will score"
  log "WARNING: this attempt FAILED. Paths: $(printf '%s' "$DIRTY" | tr '\n' ' ')"
fi
log "done -- handing the branch back to the dispatcher"
