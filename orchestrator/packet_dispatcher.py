"""LOOP_V1 P4 stage-(ii) packet dispatcher (dev-time, primary-session-invoked).

Consumes one task packet (schema/task_packet.schema.json) and drives a coding
agent through the bounded attempt loop:

  validate -> preconditions -> red-first acceptance check -> per attempt:
  ledger "dispatched" line BEFORE invoke -> worktree branch pkt/<task_id> ->
  invoke the INJECTED agent_cmd under the wall-clock cap -> the DISPATCHER
  (never the agent) re-runs the acceptance test and tools/premerge_check.sh
  in the worktree -> ledger closing line -> done / retry / budget_exhausted.

Ledger: run_state/packets.jsonl — a MACHINE-ENFORCED control, two lines per
attempt (open {status:"dispatched"} before invoke, then a closing line with
the dispatcher's verdict). spawn.jsonl stays a hand-kept discipline; the
semantics are deliberately not mixed (LOOP_V1.md P4).

Decisions the dispatcher owns (decided_by:"dispatcher", never the agent):
  - a packet whose acceptance test already passes is REFUSED ("nothing to
    do") — must_fail_before is load-bearing, not documentation (rule 4);
  - a failed precondition is a structured refusal, no attempt burned;
  - the acceptance verdict comes from re-running acceptance_criteria.test_cmd
    in the worktree, digested (sha256) into the ledger;
  - premerge_check.sh runs against the merge-base with budgets.max_diff_lines;
    an over-budget or protected-path diff is terminal "failed" — a retry in
    the same worktree cannot un-commit the violation;
  - the dispatcher NEVER merges. The report names the pkt/<task_id> branch
    and leaves the merge to the primary session (single merge authority).
  - on failure, rollback.branch_delete / rollback.notes surface as a
    rollback_hint in the report; the dispatcher does not delete branches.

The agent seam is INJECTED: agent_cmd is a subprocess argv run inside the
worktree with files_in_scope / files_out_of_scope / forbidden_actions exported
in its environment. Default None raises — there is no silent default agent.
Sentinel/timeout/escalation patterns are salvaged from the stale
agent_wrapper/dispatch_coding_agent.py (not imported; that module targets the
retired track machinery).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import jsonschema

from orchestrator import runtime

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "schema" / "task_packet.schema.json"
PREMERGE_SCRIPT = REPO_ROOT / "tools" / "premerge_check.sh"
LEDGER_PATH = REPO_ROOT / "run_state" / "packets.jsonl"
AGENT_NAME = "packet_dispatcher"

RunLog = Callable[..., None]  # (event: dict, *, agent: str) -> None


class PacketDispatchError(RuntimeError):
    """Protocol violations the dispatcher refuses to proceed past: invalid
    packet, no agent seam configured, worktree creation failure."""


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sh(cmd: str, cwd: Path, timeout: float | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, shell=True, cwd=str(cwd), capture_output=True, text=True,
        timeout=timeout,
    )


def _append_ledger(ledger_path: Path, row: dict) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with open(ledger_path, "a") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _validate_packet(packet: dict) -> None:
    schema = json.loads(SCHEMA_PATH.read_text())
    try:
        jsonschema.validate(instance=packet, schema=schema)
    except jsonschema.ValidationError as exc:
        raise PacketDispatchError(f"packet failed schema validation: {exc.message}") from exc
    # Belt-and-braces read of the red-first pin: the schema consts it to true,
    # and the dispatcher reads it explicitly so the field is control, not
    # documentation.
    if packet["acceptance_criteria"]["must_fail_before"] is not True:
        raise PacketDispatchError("acceptance_criteria.must_fail_before must be true")


def _ensure_worktree(repo_root: Path, task_id: str) -> Path:
    """Create (or reuse, across attempts) ../worktree-pkt-<task_id> on branch
    pkt/<task_id>. Raises on git failure — no silent fallback path."""
    worktree = repo_root.parent / f"worktree-pkt-{task_id}"
    branch = f"pkt/{task_id}"
    if worktree.exists():
        return worktree
    have_branch = _sh(f"git rev-parse --verify --quiet {branch}", repo_root).returncode == 0
    flag = "" if have_branch else f"-b {branch} "
    ref = branch if have_branch else ""
    proc = _sh(f"git worktree add {flag}{worktree} {ref}".strip(), repo_root)
    if proc.returncode != 0:
        raise PacketDispatchError(
            f"git worktree add failed for {worktree}: {proc.stderr.strip()}"
        )
    return worktree


def _refusal(packet_id: str, reason: str, detail: str, run_log: RunLog) -> dict:
    run_log(
        {
            "task_id": f"packet:{packet_id}",
            "status": "refused",
            "observable_actual": f"{reason}: {detail}",
            "observable_expected": "packet dispatchable",
            "duration_ms": 0,
        },
        agent=AGENT_NAME,
    )
    return {
        "packet_id": packet_id,
        "status": "refused",
        "refusal_reason": reason,
        "detail": detail,
        "attempts_used": 0,
        "merged": False,
    }


def dispatch_packet(
    packet: dict,
    *,
    agent_cmd: list[str] | None = None,
    ledger_path: Path | None = None,
    repo_root: Path | None = None,
    run_log: RunLog | None = None,
) -> dict:
    """Dispatch one packet; returns the report dict. Never merges.

    agent_cmd is the injected agent seam (argv run in the worktree). None
    raises once dispatch would actually need an agent — there is no default
    agent to fall back to. ledger_path / repo_root / run_log are injectable
    for hermetic tests; defaults are the live repo paths + runtime.append_run_log.
    """
    _validate_packet(packet)
    ledger_path = Path(ledger_path) if ledger_path is not None else LEDGER_PATH
    repo_root = Path(repo_root) if repo_root is not None else REPO_ROOT
    log = run_log if run_log is not None else runtime.append_run_log

    packet_id = packet["task_id"]
    budgets = packet["budgets"]
    test_cmd = packet["acceptance_criteria"]["test_cmd"]
    timeout_sec = budgets["wall_clock_minutes"] * 60

    # --- preconditions: zero-token shell gates; any nonzero refuses, no
    # attempt burned.
    for pre in packet["preconditions"]:
        proc = _sh(pre, repo_root)
        if proc.returncode != 0:
            return _refusal(
                packet_id, "precondition_failed",
                f"{pre!r} exited {proc.returncode}: {proc.stderr.strip()[:500]}",
                log,
            )

    # --- red-first: the acceptance test must FAIL before any work.
    try:
        proc = _sh(test_cmd, repo_root, timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        # A hung acceptance test is a refusal, not a crash (2026-08-14
        # review): no attempt burned, structured reason returned.
        return _refusal(
            packet_id, "acceptance_test_timeout",
            f"acceptance test {test_cmd!r} timed out after {timeout_sec}s "
            "during the red-first check",
            log,
        )
    if proc.returncode == 0:
        return _refusal(
            packet_id, "nothing_to_do",
            f"acceptance test {test_cmd!r} already passes (must_fail_before)",
            log,
        )

    base_sha = _sh("git rev-parse HEAD", repo_root).stdout.strip()
    if agent_cmd is None:
        raise PacketDispatchError(
            "no agent seam configured: agent_cmd is required to dispatch"
        )

    # Scope + forbidden_actions ride in the agent's environment: the packet's
    # bounds are handed to the agent verbatim, and enforced after the fact by
    # the premerge gate (belt and braces, like the schema says).
    agent_env = {
        "PKT_TASK_ID": packet_id,
        "PKT_OBJECTIVE": packet["objective"],
        "PKT_FILES_IN_SCOPE": json.dumps(packet["files_in_scope"]),
        "PKT_FILES_OUT_OF_SCOPE": json.dumps(packet["files_out_of_scope"]),
        "PKT_FORBIDDEN_ACTIONS": json.dumps(packet["forbidden_actions"]),
    }

    final_status = "budget_exhausted"
    digest = ""
    verify_tail = ""
    premerge_ok: bool | None = None
    attempts_used = 0
    worktree: Path | None = None
    for attempt in range(1, budgets["max_attempts"] + 1):
        attempts_used = attempt
        t0 = time.perf_counter()
        # Attempt increments BEFORE invoke: even an agent crash leaves the
        # dispatched line on the ledger (the open/close pin).
        _append_ledger(ledger_path, {
            "ts": _utcnow_iso(), "status": "dispatched",
            "packet_id": packet_id, "attempt": attempt,
        })
        worktree = _ensure_worktree(repo_root, packet_id)

        agent_error: str | None = None
        # Secrets never reach a packet agent (mirrors the frontier_cli
        # env-strip guard; 2026-08-14 review): the agent inherits the
        # environment MINUS the metered/vendor keys.
        spawn_env = {k: v for k, v in os.environ.items()
                     if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
                                  "OPENAI_API_KEY", "SEMANTIC_SCHOLAR_API_KEY")}
        spawn_env.update(agent_env)
        # The agent's own output is EVIDENCE, not noise: a builder that
        # refused an out-of-scope write, or blew its context window, says so
        # on stdout and nowhere else. Dropping it (as this did until
        # 2026-08-15) makes those failures invisible in packets.jsonl.
        agent_tail = ""
        agent_rc: int | None = None
        try:
            proc = subprocess.run(
                list(agent_cmd), cwd=str(worktree), timeout=timeout_sec,
                capture_output=True, text=True,
                env=spawn_env,
            )
            agent_rc = proc.returncode
            agent_tail = ((proc.stdout or "") + (proc.stderr or "")).strip()[-800:]
            if proc.returncode != 0:
                agent_error = f"agent exited {proc.returncode}"
        except subprocess.TimeoutExpired:
            agent_error = f"agent timed out after {timeout_sec}s"
        except (FileNotFoundError, OSError) as exc:
            agent_error = f"agent launch failed: {exc}"

        # --- dispatcher decides: re-run the acceptance test in the worktree.
        try:
            verify = _sh(test_cmd, worktree, timeout=timeout_sec)
            verify_out = (verify.stdout or "") + (verify.stderr or "")
            verify_rc = verify.returncode
        except subprocess.TimeoutExpired:
            verify_out, verify_rc = "acceptance re-run timed out", 1
        digest = _digest(verify_out)
        # Diagnosability (2026-08-14 e2e lesson): a digest alone made a
        # failing verify undiagnosable from the ledger — carry the output
        # tail on failed attempts (same class as the coordinator cycle rows
        # dropping planner state).
        verify_tail = verify_out.strip()[-300:] if verify_rc != 0 else ""

        attempt_status = "failed"
        premerge_ok = None
        if verify_rc == 0:
            # Done requires COMMITTED work: a green test over an uncommitted
            # working tree is not a mergeable branch (2026-08-14 review pin —
            # the premerge gate diffs commits, so a dirty tree sailed
            # through it with an empty range). The agent must commit.
            dirty = _sh("git status --porcelain", worktree).stdout.strip()
            if dirty:
                note = (f"agent left uncommitted changes "
                        f"({len(dirty.splitlines())} paths) — done requires "
                        f"a committed branch")
                agent_error = f"{agent_error}; {note}" if agent_error else note
            else:
                merge_base = _sh(
                    f"git merge-base HEAD {base_sha}", worktree
                ).stdout.strip()
                gate = subprocess.run(
                    ["bash", str(PREMERGE_SCRIPT), merge_base or base_sha,
                     str(budgets["max_diff_lines"])],
                    cwd=str(worktree), capture_output=True, text=True,
                )
                premerge_ok = gate.returncode == 0
                attempt_status = "done" if premerge_ok else "failed"

        is_terminal = (
            attempt_status == "done"
            or premerge_ok is False  # green test, dirty diff: retry can't un-commit
            or attempt == budgets["max_attempts"]
        )
        if is_terminal and attempt_status != "done" and attempt == budgets["max_attempts"] and premerge_ok is not False:
            attempt_status = "budget_exhausted"

        _append_ledger(ledger_path, {
            "ts": _utcnow_iso(), "status": attempt_status,
            "packet_id": packet_id, "attempt": attempt,
            "test_output_digest": digest, "decided_by": "dispatcher",
            **({"verify_tail": verify_tail} if verify_tail else {}),
            **({"agent_error": agent_error} if agent_error else {}),
            **({"agent_rc": agent_rc} if agent_rc is not None else {}),
            # Only on a non-done attempt: a green build needs no post-mortem.
            **({"agent_tail": agent_tail}
               if agent_tail and attempt_status != "done" else {}),
        })
        log(
            {
                "task_id": f"packet:{packet_id}",
                "status": attempt_status,
                "observable_actual": (
                    agent_error or f"acceptance rc={verify_rc}, premerge_ok={premerge_ok}"
                ),
                "observable_expected": "acceptance rc=0, premerge_ok=True",
                "duration_ms": int((time.perf_counter() - t0) * 1000),
            },
            agent=AGENT_NAME,
        )
        if is_terminal:
            final_status = attempt_status
            break

    report: dict[str, Any] = {
        "packet_id": packet_id,
        "status": final_status,
        "attempts_used": attempts_used,
        "branch": f"pkt/{packet_id}",
        "worktree": str(worktree) if worktree else None,
        "test_output_digest": digest,
        "premerge_ok": premerge_ok,
        "merged": False,  # NEVER merges; the primary session owns the merge.
    }
    if final_status != "done" and verify_tail:
        report["verify_tail"] = verify_tail
    if final_status != "done":
        rollback = packet["rollback"]
        hint = (
            f"git worktree remove --force {worktree} && git branch -D pkt/{packet_id}"
            if rollback["branch_delete"] else "manual rollback required"
        )
        if rollback["notes"]:
            hint += f"; notes: {rollback['notes']}"
        report["rollback_hint"] = hint
    return report


def consume_authorize_fix_queue(path: Path) -> list[dict]:
    """Read-only mapping of memory/authorize_fix_queue.jsonl enqueue rows to
    packet dicts. Rows carrying an explicit "packet" object pass it through
    verbatim; otherwise a skeleton packet is built from the spawn-contract
    block (task_statement -> objective). Skeletons without a real
    acceptance test_cmd will FAIL dispatch_packet's schema validation — the
    helper maps, the dispatcher validates (rule 4: never coerced)."""
    path = Path(path)
    packets: list[dict] = []
    if not path.exists():
        return packets
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue  # malformed line: skip on read, never rewrite
        if not isinstance(row, dict) or row.get("status") != "enqueued":
            continue
        if row.get("outcome") != "authorize_fix":
            continue
        if isinstance(row.get("packet"), dict):
            packets.append(row["packet"])
            continue
        contract = row.get("contract") or {}
        ref = str(row.get("ref_id", "")).strip()
        safe_ref = "".join(c if c.isalnum() or c in "_-" else "-" for c in ref)
        packets.append({
            "task_id": f"PKT-fix-{safe_ref or 'unknown'}",
            "objective": contract.get("task_statement", ""),
            "files_in_scope": [],
            "files_out_of_scope": [],
            "preconditions": [],
            "acceptance_criteria": {
                "test_cmd": contract.get("acceptance_test_cmd", ""),
                "must_fail_before": True,
            },
            "budgets": {
                "max_attempts": 1, "wall_clock_minutes": 30,
                "max_diff_lines": 400,
            },
            "forbidden_actions": ["git push", "merge", "edit files outside files_in_scope"],
            "rollback": {"branch_delete": True, "notes": ""},
        })
    return packets
