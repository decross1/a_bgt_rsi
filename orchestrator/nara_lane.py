"""Nara's implementor lane (owner direction 2026-09-22, D-082).

Turns Oracle plan items from the mailbox into validated branches, one at a
time and outside the research coordinator. Per item: admit deterministically,
write Oracle's red-first test into a fresh worktree from HEAD, confirm it
fails, let a local-Flash builder edit only the allowed paths, run the test in a
network-less bubblewrap sandbox, check the diff scope and the test's bytes,
commit on nara/<id>, and post a receipt. It never merges, pushes, or edits its
own fence; Oracle's integrator reviews and merges.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from orchestrator import oracle_mailbox as mailbox

ROOT = Path(__file__).resolve().parents[1]
WORKTREES = ROOT.parent / "a_bgt_rsi_worktrees" / "nara-lane"
VENV = ROOT / ".venv-chroma"
PAUSES = ("run_state/pause_coordinator", "run_state/pause_nara_lane")
RUN_LOG = ROOT / "run_state/week1.run.jsonl"
ALLOWED_PREFIXES = ("docs/", "tests/", "tools/", "bench/", "experiments/", "workers/", "notes/")
DENIED_PREFIXES = ("tests/conftest.py", "tools/premerge_check.sh", "tools/qwen_builder.sh",
                   "workers/idea_ledger.py", "experiments/exp008_qat_eval/", "bench/flash_")
DENIED_PATTERN = re.compile(r"PREREGISTRATION|^experiments/research_campaign_|[*?\[\]]|(^|/)\.\.?(/|$)|//")
MAX_ATTEMPTS, MAX_WALL_MINUTES = 3, 30
MAX_TEST_BYTES, MAX_FILE_BYTES, BUILDER_MAX_TOKENS = 8 * 1024, 48 * 1024, 12000
TEST_TIMEOUT_S = 300


def log(task: str, status: str, actual: str, expected: str) -> None:
    row = dict(timestamp=datetime.now(timezone.utc).isoformat(), task_id=f"nara-lane:{task}", agent="nara",
               status=status, observable_actual=actual[:2000], observable_expected=expected, duration_ms=0)
    with RUN_LOG.open("a") as handle:
        handle.write(json.dumps(row) + "\n")


def _path_ok(path: str) -> bool:
    return (path.startswith(ALLOWED_PREFIXES) and not path.startswith(DENIED_PREFIXES)
            and not DENIED_PATTERN.search(path) and not path.startswith("/"))


def admission(item: dict) -> list[str]:
    """Deterministic policy; an empty list means admissible."""
    body, reasons = item["body"], []
    if item["actor"] != "oracle":
        reasons.append("plan items must come from oracle")
    for path in body["allowed_write_paths"]:
        if not _path_ok(path):
            reasons.append(f"path outside the lane fence: {path}")
    acceptance = body["acceptance"]
    test_path, argv = acceptance["test_path"], acceptance["test_argv"]
    if not (_path_ok(test_path) and re.search(r"(^|/)test_[^/]+\.py$", test_path)):
        reasons.append(f"acceptance test must be a test_*.py inside the fence: {test_path}")
    if len(acceptance["test_content"].encode()) > MAX_TEST_BYTES:
        reasons.append("acceptance test exceeds 8 KiB")
    if argv[:3] != ["python", "-m", "pytest"] or test_path not in argv:
        reasons.append("test_argv must be python -m pytest ... <test_path>")
    budget = body.get("budget") or {}
    if budget.get("attempts", 1) > MAX_ATTEMPTS or budget.get("wall_clock_minutes", 1) > MAX_WALL_MINUTES:
        reasons.append(f"budget exceeds {MAX_ATTEMPTS} attempts / {MAX_WALL_MINUTES} minutes")
    return reasons


def sandbox_run(worktree: Path, argv: list[str], timeout: float = TEST_TIMEOUT_S) -> tuple[int, str]:
    """Run model-built tests with no network, no home directory and one writable tree."""
    cmd = ["bwrap", "--tmpfs", "/tmp"]  # first, so a worktree under /tmp is bound on top of it
    for directory in ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc"):
        if Path(directory).exists():
            cmd += ["--ro-bind", directory, directory]
    cmd += ["--ro-bind", str(VENV), str(VENV), "--bind", str(worktree), str(worktree), "--chdir", str(worktree),
            "--proc", "/proc", "--dev", "/dev", "--unshare-net", "--unshare-pid",
            "--die-with-parent", "--new-session", "--clearenv",
            "--setenv", "PATH", "/usr/bin:/bin", "--setenv", "HOME", "/tmp",
            "--setenv", "PYTHONDONTWRITEBYTECODE", "1", "--setenv", "MOCK_LLM", "1",
            "--setenv", "PYTHONPATH", str(worktree),
            str(VENV / "bin/python"), *argv[1:], "-p", "no:cacheprovider"]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        return 124, f"test timed out after {timeout:.0f} s: {(exc.stdout or '')[-2000:]}"
    return done.returncode, (done.stdout + done.stderr)[-6000:]


def _git(*args: str, cwd: Path | None = None) -> str:
    """cwd defaults to ROOT at call time (not import time), so tests can redirect it."""
    return subprocess.run(["git", *args], cwd=cwd or ROOT, check=True, capture_output=True, text=True,
                          timeout=120).stdout


def builder(body: dict, worktree: Path, feedback: str) -> dict[str, str]:
    """One local-Flash call proposing full contents for the allowed files."""
    from agent_wrapper.wrapper import call_sync

    test_path = body["acceptance"]["test_path"]
    writable = [p for p in body["allowed_write_paths"] if p != test_path]
    current = {}
    for path in writable:
        target = worktree / path
        current[path] = target.read_text()[:MAX_FILE_BYTES] if target.is_file() else None
    prompt = {
        "objective": body["objective"], "title": body["title"], "writable_paths": writable,
        "current_contents": current, "acceptance_test_path": test_path,
        "acceptance_test": body["acceptance"]["test_content"], "last_test_output": feedback[-4000:],
    }
    record = call_sync(
        [{"role": "system", "content": (
            "You are Nara's builder for the lab. Make the acceptance test pass by writing complete file "
            "contents. Reply with ONLY a JSON object {\"files\": {\"<path>\": \"<full content>\"}} using only "
            "the writable_paths. Never modify the acceptance test. Standard library only unless the file "
            "already imports something else.")},
         {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}],
        temperature=0.2, max_tokens=BUILDER_MAX_TOKENS, caller_tag="nara_lane_builder",
        extra_body={"chat_template_kwargs": {"enable_thinking": False}}, request_timeout_s=900,
        log_path=os.environ.get("LOOP_V0_CALLS_LOG", str(ROOT / "logs/calls.jsonl")))  # durable provenance
    text = record["completion"]
    start = text.find("{")
    if start < 0:
        raise ValueError("builder returned no JSON object")
    files = json.JSONDecoder().raw_decode(text[start:])[0].get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("builder returned no files")
    for path, content in files.items():
        if path not in writable or not isinstance(content, str) or len(content.encode()) > MAX_FILE_BYTES:
            raise ValueError(f"builder wrote outside its writable paths or over size: {path}")
    return files


def implement(entry: dict, build=builder, sandbox=sandbox_run) -> dict:
    """Run one admitted item to a terminal receipt body; never raises."""
    item = entry["item"]
    body, msg_id = item["body"], item["msg_id"]
    acceptance = body["acceptance"]
    budget = body.get("budget") or {}
    deadline = time.monotonic() + 60 * min(budget.get("wall_clock_minutes", MAX_WALL_MINUTES), MAX_WALL_MINUTES)
    attempts_allowed = min(budget.get("attempts", MAX_ATTEMPTS), MAX_ATTEMPTS)
    worktree, branch = WORKTREES / msg_id, f"nara/{msg_id}"
    try:
        if worktree.exists():
            return {"state": "failed", "reason": f"worktree already exists: {worktree}"}
        WORKTREES.mkdir(parents=True, exist_ok=True)
        _git("worktree", "add", "-b", branch, str(worktree), "HEAD")
        test_file = worktree / acceptance["test_path"]
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text(acceptance["test_content"])
        test_sha = hashlib.sha256(acceptance["test_content"].encode()).hexdigest()
        rc, output = sandbox(worktree, acceptance["test_argv"])
        if rc == 0:
            return {"state": "failed", "reason": "acceptance test passed before any change (not red-first)",
                    "branch": branch, "test_tail": output[-1500:]}
        attempts = 0
        while attempts < attempts_allowed and time.monotonic() < deadline:
            attempts += 1
            try:
                files = build(body, worktree, output)
            except Exception as exc:  # recorded as feedback for the next attempt
                output = f"builder error: {type(exc).__name__}: {exc}"
                continue
            for path, content in files.items():
                target = worktree / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
            rc, output = sandbox(worktree, acceptance["test_argv"])
            if rc == 0:
                break
        changed = {line[3:].strip() for line in _git("status", "--porcelain", "--untracked-files=all",
                                                        cwd=worktree).splitlines() if line.strip()}
        allowed = set(body["allowed_write_paths"]) | {acceptance["test_path"]}
        result = {"branch": branch, "worktree": str(worktree), "attempts": attempts,
                  "changed_files": sorted(changed), "test_tail": output[-1500:]}
        if changed - allowed:
            return {**result, "state": "failed", "reason": f"changes outside scope: {sorted(changed - allowed)}"}
        if hashlib.sha256(test_file.read_bytes()).hexdigest() != test_sha:
            return {**result, "state": "failed", "reason": "the acceptance test was modified"}
        if rc != 0:
            return {**result, "state": "failed", "reason": "acceptance test still failing"}
        _git("add", "-A", cwd=worktree)
        _git("-c", "user.name=Nara (lab lane)", "-c", "user.email=nara@lab.local", "commit", "-q", "-m",
             f"Nara lane: {body['title']}\n\nOracle plan item {msg_id}; validated in the lane sandbox.", cwd=worktree)
        return {**result, "state": "validated", "head_sha": _git("rev-parse", "HEAD", cwd=worktree).strip()}
    except Exception as exc:
        return {"state": "failed", "reason": f"{type(exc).__name__}: {exc}", "branch": branch}


def run_queue(path: Path = mailbox.PATH, build=builder, sandbox=sandbox_run, ready=None) -> list[dict]:
    """Process every open item once; returns the receipts posted."""
    if any((ROOT / pause).exists() for pause in PAUSES):
        return []
    if ready is None:
        from orchestrator.flash_resident import check_ready as ready
    posted = []
    lock_path = ROOT / "run_state/.nara_lane.lock"
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return []
        entries = sorted(mailbox.fold(mailbox.read(path)).values(), key=lambda e: e["item"]["seq"])
        for entry in entries:
            msg_id = entry["item"]["msg_id"]
            if entry["state"] == "claimed":  # a previous lane process died mid-item
                posted.append(mailbox.post("nara", "receipt", {"state": "failed", "reason": "lane interrupted; item abandoned"},
                                           to="oracle", in_reply_to=msg_id, path=path))
                continue
            if entry["state"] != "open":
                continue
            reasons = admission(entry["item"])
            if reasons:
                posted.append(mailbox.post("nara", "receipt", {"state": "held", "reasons": reasons},
                                           to="oracle", in_reply_to=msg_id, path=path))
                log(msg_id, "held", "; ".join(reasons), "admissible plan item")
                continue
            if not ready():
                log(msg_id, "deferred", "Flash resident not ready", "Flash ready")
                break
            posted.append(mailbox.post("nara", "receipt", {"state": "claimed"}, to="oracle", in_reply_to=msg_id, path=path))
            outcome = implement(entry, build, sandbox)
            posted.append(mailbox.post("nara", "receipt", outcome, to="oracle", in_reply_to=msg_id, path=path))
            log(msg_id, "completed" if outcome["state"] == "validated" else "failed",
                json.dumps({k: outcome.get(k) for k in ("state", "reason", "branch", "head_sha", "attempts")}),
                "validated branch")
    return posted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["run", "status"])
    args = parser.parse_args(argv)
    if args.command == "status":
        view = {k: {"title": v["item"]["body"]["title"], "state": v["state"]}
                for k, v in mailbox.fold(mailbox.read()).items()}
        print(json.dumps(view, indent=2))
        return 0
    for receipt in run_queue():
        print(json.dumps({"re": receipt["in_reply_to"], "state": receipt["body"]["state"],
                          "reason": receipt["body"].get("reason") or receipt["body"].get("reasons")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
