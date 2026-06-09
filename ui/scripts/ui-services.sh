#!/usr/bin/env bash
# UI observability services launcher for a_bgt_rsi.
#
#   ui-services.sh start    # (default) free ports + (re)launch all UI services, detached
#   ui-services.sh stop     # stop the UI services
#   ui-services.sh status   # report UI + apparatus service status
#
# Manages the THREE UI services, each launched with setsid so they survive an
# SSH disconnect / terminal close:
#   - backend   uvicorn  -> :8700   (reads logs/run_state, serves the API)
#   - sampler   python   -> writes ui/logs/telemetry.jsonl (GPU/host/vLLM telemetry)
#   - frontend  vite     -> :5173   (the SPA; talks to :8700)
#
# Idempotent: `start` frees the port / kills the old process first, so it is safe
# to run after a crash or power blip.
#
# Apparatus services (Gemma/Qwen vLLM, nemoclaw) are PRIMARY-SESSION-OWNED and are
# only REPORTED here, never started — their version pins are inviolate (CLAUDE.md
# §2: vLLM v0.21.0, --moe-backend marlin, etc.). `status` shows them so you know
# what still needs the primary session after a reboot.
set -u

# Robust under a minimal environment (e.g. cron @reboot): ensure node/npm
# (/usr/bin) and the standard tools (lsof/pgrep/ps/curl/setsid) are on PATH.
export PATH="/usr/local/bin:/usr/bin:/bin:${PATH:-}"

PRIMARY=/home/decross1/projects/a_bgt_rsi
UI="$PRIMARY/ui"
PY="$UI/.venv/bin/python"            # main-checkout venv (has fastapi/uvicorn/psutil)
LOGDIR="$UI/logs/services"           # gitignored (logs/*)
BACKEND_PORT=8700
FRONTEND_PORT=5173

mkdir -p "$LOGDIR"

_kill_port() {
  local port=$1 pids
  pids=$(lsof -ti tcp:"$port" 2>/dev/null) || true
  if [ -n "${pids:-}" ]; then kill $pids 2>/dev/null && echo "  freed :$port (killed $pids)"; fi
}

# Kill the python sampler ONLY — never the bash launcher wrapper (pgrep -f also
# matches a shell whose command line contains 'sampler.sampler').
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

_running_sampler() { pgrep -f "python.*sampler.sampler" 2>/dev/null | head -1; }

_launch() {           # _launch <name> <logfile> <workdir> <cmd...>
  local name=$1 log=$2 wd=$3; shift 3
  ( cd "$wd" && setsid "$@" > "$log" 2>&1 < /dev/null & disown )
  echo "  launched $name -> $log"
}

stop() {
  echo "== stopping UI services =="
  _kill_port "$BACKEND_PORT"
  _kill_port "$FRONTEND_PORT"
  _kill_sampler
}

start() {
  echo "== (re)starting UI services =="
  stop
  sleep 1
  _launch backend  "$LOGDIR/backend.log"  "$UI"          env -u MOCK_LLM "$PY" -m uvicorn backend.app:app --host 0.0.0.0 --port "$BACKEND_PORT"
  _launch sampler  "$LOGDIR/sampler.log"  "$UI"          "$PY" -m sampler.sampler
  _launch frontend "$LOGDIR/vite.log"     "$UI/frontend" npm run dev
  echo "== waiting for the backend to answer =="
  curl -s --retry 30 --retry-delay 1 --retry-connrefused -o /dev/null "http://127.0.0.1:$BACKEND_PORT/api/health" \
    && echo "  backend healthy" || echo "  backend did NOT come up — see $LOGDIR/backend.log"
  echo
  status
}

_port_up()  { ss -ltn 2>/dev/null | grep -q ":$1 " && echo up || echo DOWN; }
_proc_up()  { pgrep -f "$1" >/dev/null 2>&1 && echo up || echo DOWN; }

status() {
  echo "== UI services (ours) =="
  printf "  backend  :%s   %s\n"  "$BACKEND_PORT"  "$(_port_up $BACKEND_PORT)"
  printf "  frontend :%s   %s\n"  "$FRONTEND_PORT" "$(_port_up $FRONTEND_PORT)"
  printf "  sampler        %s%s\n" "$( [ -n "$(_running_sampler)" ] && echo up || echo DOWN )" \
    "$( [ -n "$(_running_sampler)" ] && echo " (pid $(_running_sampler))" || echo '' )"
  if curl -s -o /dev/null "http://127.0.0.1:$BACKEND_PORT/api/health" 2>/dev/null; then
    printf "  backend version: %s\n" "$(curl -s http://127.0.0.1:$BACKEND_PORT/api/health | "$PY" -c 'import sys,json;print(json.load(sys.stdin).get("version","?"))' 2>/dev/null)"
  fi
  echo "== apparatus (primary-session-owned — reported, NOT started here) =="
  printf "  gemma vLLM :8000   %s\n" "$(_port_up 8000)"
  printf "  qwen  vLLM :8001   %s\n" "$(_port_up 8001)"
  printf "  nemoclaw/openshell %s\n" "$(_proc_up 'openshell-sandbox|nemoclaw-start')"
  printf "  ollama-auth-proxy  %s\n" "$(_proc_up 'ollama-auth-proxy')"
}

case "${1:-start}" in
  start)  start ;;
  stop)   stop ;;
  status) status ;;
  *) echo "usage: $0 {start|stop|status}"; exit 2 ;;
esac
