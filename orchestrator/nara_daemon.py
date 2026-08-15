"""D-063 Stage-2 always-on Nara daemon — event-driven portfolio scheduler.

Owner's spec (verbatim): "Nara should always be progressing something.
Whether that's ideation, research design, falsification, updating journey,
ledgering, deploying agent development team."

Invariant: if any agent-advanceable work exists and budget remains, a
coordinator cycle runs; otherwise the daemon idles HONESTLY (one log line,
no cycle — never busywork) with heartbeat backoff.

Every pass runs the SAME gate ladder as cron/run-coordinator.sh, in order,
in-process: (1) flock on the cron's OWN lock file (daemon and cron never
overlap); (2) the D-049 sentinel; (3) the pause-file kill switch; (4)
memory preflight via a subprocess bash call into preflight_mem.sh (need=0);
then cron/secrets.env sourcing (a missing key is LOUD, rule 7) and the
daily-budget check. Every gate refusal is a DESIGNED exit. The cycle is the
same entry the cron launches — coordinator_cycle, execute mode — with the
cron's env mirrored for the call (MOCK_LLM unset, NARA_SKEPTIC=1; rule 10);
the coordinator's own pause/budget re-checks stay live inside.

Wakes: cheap mtime polling (no inotify dep) over the lab channel, finding
follow-ups, the idea ledger, the authorize-fix queue, and the packet
ledger; heartbeat floor NARA_HEARTBEAT_S (default 1800 s); consecutive
no-work wakes double it up to 2 h; any event or work resets it.

Packet dispatch (deploying the agent development team) ships DARK: inert
unless NARA_PACKET_DISPATCH=1, and even then it refuses loudly without
NARA_PACKET_AGENT_CMD (JSON argv list). One packet per wake.

Observability: one line per wake to logs/nara-daemon.log; daemon start/stop
rows in the run log (agent "nara_daemon", rule 6); cycles log through the
coordinator machinery. An unexpected error logs + sleeps CRASH_BACKOFF_S —
never a loop-storm. Install/stop: systemd/nara-daemon.service (human-run).
CLI: python -m orchestrator.nara_daemon [--once] [--dry-run]
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orchestrator import coordinator, packet_dispatcher, runtime
from workers import idea_ledger, idea_projection

REPO_ROOT = Path(__file__).resolve().parent.parent

# Gate-ladder paths — the SAME files cron/run-coordinator.sh uses.
LOCK_PATH = REPO_ROOT / "run_state" / ".coordinator-cron.lock"
RATIFIED_PATH = REPO_ROOT / "run_state" / "d049_ratified"
PAUSE_PATH = REPO_ROOT / "run_state" / "pause_coordinator"
MEM_GUARD = REPO_ROOT / "experiments" / "exp008_qat_eval" / "preflight_mem.sh"
SECRETS_ENV = REPO_ROOT / "cron" / "secrets.env"

# Wake-source watch list (mtime polling).
LAB_CHANNEL_PATH = REPO_ROOT / "memory" / "lab_channel.jsonl"
FOLLOWUPS_PATH = REPO_ROOT / "memory" / "finding_followups.jsonl"
IDEA_LEDGER_PATH = REPO_ROOT / "memory" / "idea_ledger.jsonl"
FIX_QUEUE_PATH = REPO_ROOT / "memory" / "authorize_fix_queue.jsonl"
PACKETS_PATH = REPO_ROOT / "run_state" / "packets.jsonl"

IDEAS_MD_PATH = REPO_ROOT / "memory" / "ideas.md"
DAEMON_LOG_PATH = REPO_ROOT / "logs" / "nara-daemon.log"

AGENT_NAME = "nara_daemon"
MEM_NEED_GIB = 0          # cycles only CALL resident servers (cron parity)
POLL_S = 20               # mtime poll interval inside a wait
HEARTBEAT_MAX_S = 7200    # idle backoff ceiling (2 h)
CRASH_BACKOFF_S = 60      # sleep after an unexpected main-loop error

# The two "await human" gap shapes from coordinator.assess_state — NOT
# agent-actionable (the 2026-08-05..14 fixed point: they saturate and freeze).
HUMAN_GAP_MARKERS = ("await a human gate verdict", "await human review")

_sleep = time.sleep  # module-level so tests can stub sleeping


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _daemon_log(line: str) -> None:
    """Append one '[nara-daemon] <ts> <line>' row to logs/nara-daemon.log."""
    p = Path(DAEMON_LOG_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(f"[nara-daemon] {_utcnow_iso()} {line}\n")


def heartbeat_base_s() -> int:
    return int(os.environ.get("NARA_HEARTBEAT_S", "1800"))


def next_heartbeat_s(
    current_s: int, *, had_event: bool, had_work: bool,
    base_s: int, max_s: int = HEARTBEAT_MAX_S,
) -> int:
    """Idle-backoff arithmetic (pure): any event or work resets to the base;
    a no-work heartbeat wake doubles the interval up to max_s."""
    if had_event or had_work:
        return base_s
    return min(current_s * 2, max_s)


# ── wake ─────────────────────────────────────────────────────────────────

def _watch_paths() -> dict[str, Path]:
    return {
        "lab_channel": Path(LAB_CHANNEL_PATH),
        "finding_followups": Path(FOLLOWUPS_PATH),
        "idea_ledger": Path(IDEA_LEDGER_PATH),
        "authorize_fix_queue": Path(FIX_QUEUE_PATH),
        "packets": Path(PACKETS_PATH),
    }


def _stat_sig(path: Path) -> tuple[int, int] | None:
    """(mtime_ns, size) change signature; None when the file is absent."""
    try:
        st = path.stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def wait_for_wake(heartbeat_s: float, *, poll_s: float = POLL_S) -> str:
    """Block until a watched file changes or the heartbeat floor elapses.
    Returns "event:<source>" or "heartbeat". Cheap mtime polling only."""
    watched = _watch_paths()
    baseline = {name: _stat_sig(p) for name, p in watched.items()}
    deadline = time.monotonic() + max(float(heartbeat_s), 0.0)
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return "heartbeat"
        _sleep(min(poll_s, remaining))
        for name, p in watched.items():
            if _stat_sig(p) != baseline[name]:
                return f"event:{name}"


# ── gates (run-coordinator.sh parity) ────────────────────────────────────

def _preflight_ok() -> bool:
    """Gate 4 — memory preflight via the SAME bash guard the cron sources.
    Non-zero return (refuse or fail-closed) -> False."""
    proc = subprocess.run(
        ["bash", "-c",
         f'source "{MEM_GUARD}" && preflight_mem_guard {MEM_NEED_GIB}'],
        capture_output=True, text=True,
    )
    return proc.returncode == 0


def _source_secrets() -> None:
    """cron/secrets.env sourcing semantics, in-process: parse `export K=V`
    lines into os.environ. Absence of the key is LOUD, never silent."""
    p = Path(SECRETS_ENV)
    if p.exists():
        for raw in p.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):]
            key, sep, val = line.partition("=")
            if sep and key.strip():
                os.environ[key.strip()] = val.strip().strip("'\"")
    if not os.environ.get("SEMANTIC_SCHOLAR_API_KEY"):
        _daemon_log(
            "WARN: SEMANTIC_SCHOLAR_API_KEY absent (no cron/secrets.env key) "
            "— external search will be BLIND this cycle"
        )


# ── work-exists predicate ────────────────────────────────────────────────

def agent_actionable_gaps(gaps: list[str]) -> list[str]:
    """Gaps the AGENT can advance: everything except the two 'await human'
    shapes (ladder-debt 'at L' gaps and staleness 'loop has not iterated'
    gaps count; a human verdict queue is not agent work)."""
    return [
        g for g in gaps
        if isinstance(g, str)
        and not any(marker in g for marker in HUMAN_GAP_MARKERS)
    ]


def _loud_read(label: str, fn):
    """Run a pure read; a failure is LOGGED (never silent), then degrades
    to [] so one broken source can't kill the daemon's whole verdict."""
    try:
        return fn()
    except Exception as exc:
        _daemon_log(f"WARN: {label} failed: {type(exc).__name__}: {exc}")
        return []


def _gaps() -> list[str]:
    """assess_state gaps (pure reads; loud-degrading)."""
    return _loud_read(
        "assess_state",
        lambda: list(coordinator.assess_state().get("gaps") or []))


def _agenda() -> list[dict]:
    """Unconsumed idea-ledger agenda items (loud-degrading)."""
    return _loud_read(
        "agenda read",
        lambda: idea_projection.agenda_topics(
            idea_ledger.load_state(IDEA_LEDGER_PATH)))


def _packet_dispatch_armed() -> bool:
    return os.environ.get("NARA_PACKET_DISPATCH") == "1"


def _queued_packets() -> list[dict]:
    return _loud_read(
        "packet queue read",
        lambda: packet_dispatcher.consume_authorize_fix_queue(
            Path(FIX_QUEUE_PATH)))


def work_exists() -> dict[str, Any]:
    """TRUE iff any of: (a) an agent-actionable assess_state gap,
    (b) unconsumed agenda items, (c) NARA_PACKET_DISPATCH=1 AND enqueued
    authorize-fix packets. FALSE -> honest idle (no cycle, never busywork)."""
    reasons: list[str] = []
    actionable = agent_actionable_gaps(_gaps())
    if actionable:
        reasons.append(f"gaps:{len(actionable)}")
    agenda = _agenda()
    if agenda:
        reasons.append(f"agenda:{len(agenda)}")
    if _packet_dispatch_armed():
        packets = _queued_packets()
        if packets:
            reasons.append(f"packets:{len(packets)}")
    return {"work": bool(reasons), "reasons": reasons}


# ── cycle + hygiene + packet seams ───────────────────────────────────────

def _cycle_budget() -> int:
    return int(os.environ.get("NARA_CYCLE_BUDGET", "6"))


def _budget_remaining(budget: int) -> bool:
    """Pre-check mirror of the coordinator's daily cap (the coordinator
    re-enforces inside the cycle; a refusal there is a DESIGNED outcome)."""
    return coordinator._daily_spent() + budget <= coordinator.DAILY_BUDGET_CAP


def _run_cycle(budget: int) -> dict:
    """ONE execute-mode coordinator cycle — the same entry the cron script
    launches, its env mirrored for the call: MOCK_LLM unset, NARA_SKEPTIC=1."""
    saved = {k: os.environ.get(k) for k in ("MOCK_LLM", "NARA_SKEPTIC")}
    os.environ.pop("MOCK_LLM", None)
    os.environ["NARA_SKEPTIC"] = "1"
    try:
        return coordinator.coordinator_cycle(budget=budget, dry_run=False)
    finally:
        for key, val in saved.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val


def _rerender_ideas() -> bool:
    """Post-cycle hygiene: re-render memory/ideas.md from the ledger (the
    byte-stable projection). Returns True when the file changed."""
    try:
        text = idea_projection.render_ideas_md(
            idea_ledger.load_state(IDEA_LEDGER_PATH))
        p = Path(IDEAS_MD_PATH)
        if p.exists() and p.read_text() == text:
            return False
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return True
    except Exception as exc:
        _daemon_log(f"WARN: ideas.md re-render failed: "
                    f"{type(exc).__name__}: {exc}")
        return False


def _dispatch_packet(packet: dict, *, agent_cmd: list[str]) -> dict:
    """Thin seam over packet_dispatcher.dispatch_packet (patchable)."""
    return packet_dispatcher.dispatch_packet(packet, agent_cmd=agent_cmd)


def _maybe_dispatch_one_packet() -> str | None:
    """DARK unless NARA_PACKET_DISPATCH=1. Dispatch at most ONE queued
    packet per wake; an armed seam without NARA_PACKET_AGENT_CMD (JSON argv
    list) logs and skips — never a silent default agent."""
    if not _packet_dispatch_armed():
        return None
    packets = _queued_packets()
    if not packets:
        return None
    raw = os.environ.get("NARA_PACKET_AGENT_CMD")
    if not raw:
        _daemon_log("packet dispatch armed but no agent_cmd configured "
                    "(NARA_PACKET_AGENT_CMD absent) — skipping dispatch")
        return "skipped:no_agent_cmd"
    try:
        agent_cmd = json.loads(raw)
        if not (isinstance(agent_cmd, list)
                and all(isinstance(a, str) for a in agent_cmd)):
            raise ValueError("NARA_PACKET_AGENT_CMD must be a JSON list of str")
    except (json.JSONDecodeError, ValueError) as exc:
        _daemon_log(f"WARN: invalid NARA_PACKET_AGENT_CMD: {exc} — "
                    "skipping dispatch")
        return "skipped:bad_agent_cmd"
    try:
        report = _dispatch_packet(packets[0], agent_cmd=agent_cmd)
        return str(report.get("status", "unknown"))
    except Exception as exc:
        _daemon_log(f"WARN: packet dispatch failed: "
                    f"{type(exc).__name__}: {exc}")
        return "error"


# ── one pass ─────────────────────────────────────────────────────────────

def run_pass(*, wake_reason: str = "manual", dry_run: bool = False) -> dict:
    """One wake -> gates -> work verdict -> (maybe) one cycle + hygiene +
    (dark) packet dispatch. Always logs exactly one wake line."""
    outcome = _run_pass(wake_reason=wake_reason, dry_run=dry_run)
    _daemon_log(f"wake={outcome['wake']} work={outcome['work']} "
                f"action={outcome['action']}")
    return outcome


def _run_pass(*, wake_reason: str, dry_run: bool) -> dict:
    outcome: dict[str, Any] = {
        "wake": wake_reason, "work": "unevaluated", "action": "",
        "worked": False,
    }
    # Gate 1 — flock (same lock file as cron: daemon and cron never overlap).
    Path(LOCK_PATH).parent.mkdir(parents=True, exist_ok=True)
    lock_fh = open(LOCK_PATH, "w")
    try:
        try:
            fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            outcome["action"] = "skipped:flock"
            return outcome
        # Gate 2 — ratification sentinel (only the human creates it).
        if not Path(RATIFIED_PATH).exists():
            outcome["action"] = "refused:d049_sentinel"
            return outcome
        # Gate 3 — human kill switch.
        if Path(PAUSE_PATH).exists():
            outcome["action"] = "refused:pause"
            return outcome
        # Gate 4 — memory preflight (subprocess into the bash guard).
        if not _preflight_ok():
            outcome["action"] = "refused:preflight"
            return outcome
        _source_secrets()

        verdict = work_exists()
        outcome["work"] = (
            "yes:" + ",".join(verdict["reasons"]) if verdict["work"] else "no"
        )
        if not verdict["work"]:
            outcome["action"] = "idle"  # honest idle — never busywork
            return outcome
        if dry_run:
            outcome["action"] = "dry_run"
            return outcome
        budget = _cycle_budget()
        if not _budget_remaining(budget):
            # DESIGNED exit, exactly like the cron's budget refusal.
            outcome["action"] = "refused:daily_budget"
            return outcome

        pre_ledger = _stat_sig(Path(IDEA_LEDGER_PATH))
        report = _run_cycle(budget)
        outcome["worked"] = True
        outcome["cycle_status"] = report.get("status")
        action = f"cycle:{report.get('status')}"
        # Post-cycle hygiene: re-render ideas.md iff the ledger changed.
        if _stat_sig(Path(IDEA_LEDGER_PATH)) != pre_ledger:
            if _rerender_ideas():
                action += "+ideas_md"
        packet_status = _maybe_dispatch_one_packet()
        if packet_status is not None:
            outcome["packet"] = packet_status
            action += f"+packet:{packet_status}"
        outcome["action"] = action
        return outcome
    finally:
        lock_fh.close()  # releases the flock


# ── main loop ────────────────────────────────────────────────────────────

def run_forever() -> int:
    base = heartbeat_base_s()
    hb = base
    t0 = time.time()
    passes = 0
    runtime.append_run_log({
        "task_id": "nara_daemon:start", "status": "started",
        "observable_actual": (
            f"daemon resident pid={os.getpid()} heartbeat_base={base}s"),
        "observable_expected": "daemon resident until stopped",
        "duration_ms": 0,
    }, agent=AGENT_NAME)
    _daemon_log(f"daemon start pid={os.getpid()} heartbeat_base={base}s")
    try:
        while True:
            try:
                reason = wait_for_wake(hb)
                outcome = run_pass(wake_reason=reason)
                passes += 1
                hb = next_heartbeat_s(
                    hb,
                    had_event=reason.startswith("event:"),
                    had_work=bool(outcome.get("worked")),
                    base_s=base,
                )
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                # A crash must not loop-storm: log + fixed backoff, continue.
                _daemon_log(f"ERROR: {type(exc).__name__}: {exc} — "
                            f"backing off {CRASH_BACKOFF_S}s")
                _sleep(CRASH_BACKOFF_S)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        runtime.append_run_log({
            "task_id": "nara_daemon:stop", "status": "stopped",
            "observable_actual": f"daemon stopped after {passes} pass(es)",
            "observable_expected": "clean stop",
            "duration_ms": int((time.time() - t0) * 1000),
        }, agent=AGENT_NAME)
        _daemon_log(f"daemon stop after {passes} pass(es)")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m orchestrator.nara_daemon",
        description=(
            "D-063 Stage-2 always-on Nara daemon. Default: resident loop "
            "(event wakes + heartbeat floor), one coordinator cycle per "
            "wake when agent-advanceable work exists and budget remains, "
            "behind the same gate ladder as cron/run-coordinator.sh."
        ),
    )
    p.add_argument("--once", action="store_true",
                   help="One wake-evaluate-maybe-cycle pass, then exit "
                        "(testing / cron parity).")
    p.add_argument("--dry-run", action="store_true",
                   help="Evaluate gates + work verdict and log; never cycle. "
                        "Implies a single pass.")
    args = p.parse_args(argv)
    if args.once or args.dry_run:
        outcome = run_pass(wake_reason="once", dry_run=args.dry_run)
        print(json.dumps(outcome, ensure_ascii=False, default=str))
        return 0
    return run_forever()


if __name__ == "__main__":
    raise SystemExit(main())
