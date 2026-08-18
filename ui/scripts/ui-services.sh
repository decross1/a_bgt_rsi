#!/usr/bin/env bash
# UI observability services launcher for a_bgt_rsi.
#
#   ui-services.sh start    # (default) free ports + (re)launch ALL UI services, detached
#   ui-services.sh ensure   # restart ONLY the services that are down (cron health-watch)
#   ui-services.sh stop     # stop the UI services
#   ui-services.sh status   # report UI + apparatus service status
#
# Three UI services, each setsid-detached (survive an SSH disconnect / crash):
#   - backend   uvicorn  -> :8700   (reads logs/run_state, serves the API)
#   - sampler   python   -> writes ui/logs/telemetry.jsonl (GPU/host/vLLM telemetry)
#   - frontend  vite     -> :5173   (the SPA; talks to :8700)
#
# `start` is idempotent (frees the port / kills the old proc first). `ensure` is
# the cron health-watch: it (re)starts only a service that is currently down and
# is otherwise silent, so the cron log only grows when it actually heals something.
#
# Apparatus services (Gemma/Qwen vLLM, nemoclaw) are PRIMARY-SESSION-OWNED and only
# REPORTED here, never started — their version pins are inviolate (CLAUDE.md §2).
set -u
# Robust under a minimal environment (cron @reboot / */N): ensure node/npm
# (/usr/bin) and the standard tools (lsof/pgrep/ps/curl/setsid/ss) are on PATH.
export PATH="/usr/local/bin:/usr/bin:/bin:${PATH:-}"

PRIMARY=/home/decross1/projects/a_bgt_rsi
UI="$PRIMARY/ui"
PY="$UI/.venv/bin/python"            # main-checkout venv (has fastapi/uvicorn/psutil)
# Backend runs under .venv-chroma (2026-08-18): /api/doc_titles reads Chroma
# metadata, and .venv-chroma carries uvicorn+fastapi+chromadb (+openai).
# Sampler STAYS on ui/.venv (needs psutil, absent from .venv-chroma).
BACKEND_PY="$UI/../.venv-chroma/bin/python"
LOGDIR="$UI/logs/services"           # gitignored (logs/*)
BACKEND_PORT=8700
FRONTEND_PORT=5173
mkdir -p "$LOGDIR"

_ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
_port_up()    { ss -ltn 2>/dev/null | grep -q ":$1 "; }
_sampler_pid() { pgrep -f "python.*sampler.sampler" 2>/dev/null | head -1; }
_proc_up()    { pgrep -f "$1" >/dev/null 2>&1; }

# _launch <logfile> <workdir> <cmd...> — setsid-detached so it outlives this shell.
_launch() { local log=$1 wd=$2; shift 2; ( cd "$wd" && setsid "$@" > "$log" 2>&1 < /dev/null & disown ); }

_start_backend()  { _launch "$LOGDIR/backend.log" "$UI"          env -u MOCK_LLM "$BACKEND_PY" -m uvicorn backend.app:app --host 0.0.0.0 --port "$BACKEND_PORT"; }
_start_sampler()  { _launch "$LOGDIR/sampler.log" "$UI"          "$PY" -m sampler.sampler; }
_start_frontend() { _launch "$LOGDIR/vite.log"    "$UI/frontend" npm run dev; }

_kill_port() {
  local port=$1 pids
  pids=$(lsof -ti tcp:"$port" 2>/dev/null) || true
  [ -n "${pids:-}" ] && kill $pids 2>/dev/null && echo "  freed :$port (killed $pids)"
  return 0
}
# Kill the python sampler ONLY — never a bash launcher whose cmdline matches.
_kill_sampler() {
  local pid cmd
  for pid in $(pgrep -f "sampler.sampler" 2>/dev/null); do
    cmd=$(ps -o cmd= -p "$pid" 2>/dev/null) || continue
    case "$cmd" in
      *bash*|*"-c "*) : ;;
      *python*sampler.sampler*) kill "$pid" 2>/dev/null && echo "  stopped sampler $pid" ;;
    esac
  done
}

stop() {
  echo "== stopping UI services =="
  _kill_port "$BACKEND_PORT"; _kill_port "$FRONTEND_PORT"; _kill_sampler
}

start() {
  echo "== (re)starting UI services =="
  stop; sleep 1
  _start_backend;  echo "  launched backend  -> $LOGDIR/backend.log"
  _start_sampler;  echo "  launched sampler  -> $LOGDIR/sampler.log"
  _start_frontend; echo "  launched frontend -> $LOGDIR/vite.log"
  curl -s --retry 30 --retry-delay 1 --retry-connrefused -o /dev/null "http://127.0.0.1:$BACKEND_PORT/api/health" \
    && echo "  backend healthy" || echo "  backend did NOT come up — see $LOGDIR/backend.log"
  echo; status
}

# Health-watch: restart ONLY what is down. Silent when all up (cron-friendly).
ensure() {
  if ! _port_up "$BACKEND_PORT";  then echo "$(_ts) backend down -> restarting";  _start_backend;  fi
  if [ -z "$(_sampler_pid)" ];    then echo "$(_ts) sampler down -> restarting";  _start_sampler;  fi
  if ! _port_up "$FRONTEND_PORT"; then echo "$(_ts) frontend down -> restarting"; _start_frontend; fi
}

status() {
  echo "== UI services (ours) =="
  printf "  backend  :%s   %s\n" "$BACKEND_PORT"  "$(_port_up $BACKEND_PORT && echo up || echo DOWN)"
  printf "  frontend :%s   %s\n" "$FRONTEND_PORT" "$(_port_up $FRONTEND_PORT && echo up || echo DOWN)"
  printf "  sampler        %s\n" "$([ -n "$(_sampler_pid)" ] && echo "up (pid $(_sampler_pid))" || echo DOWN)"
  if curl -s -o /dev/null "http://127.0.0.1:$BACKEND_PORT/api/health" 2>/dev/null; then
    printf "  backend version: %s\n" "$(curl -s http://127.0.0.1:$BACKEND_PORT/api/health | "$PY" -c 'import sys,json;print(json.load(sys.stdin).get("version","?"))' 2>/dev/null)"
  fi
  echo "== apparatus (primary-session-owned — reported, NOT started here) =="
  printf "  gemma vLLM :8000   %s\n" "$(_port_up 8000 && echo up || echo DOWN)"
  printf "  qwen  vLLM :8001   %s\n" "$(_port_up 8001 && echo up || echo DOWN)"
  printf "  nemoclaw/openshell %s\n" "$(_proc_up 'openshell-sandbox|nemoclaw-start' && echo up || echo DOWN)"
  printf "  ollama-auth-proxy  %s\n" "$(_proc_up 'ollama-auth-proxy' && echo up || echo DOWN)"
}

case "${1:-start}" in
  start)  start ;;
  ensure) ensure ;;
  stop)   stop ;;
  status) status ;;
  *) echo "usage: $0 {start|ensure|stop|status}"; exit 2 ;;
esac
