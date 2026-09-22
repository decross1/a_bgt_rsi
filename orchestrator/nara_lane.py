"""Nara's implementor lane (owner direction 2026-09-22, D-082).

Turns Oracle plan items from the mailbox into validated branches, one at a
time and outside the research coordinator. Per item: admit deterministically,
write Oracle's red-first test into a fresh worktree, confirm it fails, let a
local-Flash builder edit only the allowed paths, run the test in a network-less
bubblewrap sandbox, then commit on nara/<id> and post a receipt. It never
merges, pushes, or edits its own fence; Oracle's integrator reviews and merges.

Everything the sandbox can write is untrusted afterwards: the worktree's .git
pointer is read-only inside the sandbox and re-checked on the host, changes are
computed from a stat walk (not git status), host reads and writes refuse
symlinks, git runs with fsmonitor and hooks disabled, and a pass needs pytest's
own JUnit report, not just exit code 0.

Meta-oracle gate (owner direction 2026-09-22): unless config/nara_lane.json
exempts it, an item waits, still open, for a `review` from the meta-oracle that
replies to it. `accept` admits it; `amend` or `reject` holds it (Oracle withdraws
and reposts). A missing or unreadable policy file requires review.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from orchestrator import oracle_mailbox as mailbox

ROOT = Path(__file__).resolve().parents[1]
WORKTREES = ROOT.parent / "a_bgt_rsi_worktrees" / "nara-lane"
VENV = ROOT / ".venv-chroma"
PAUSES = ("run_state/pause_coordinator", "run_state/pause_nara_lane")
RUN_LOG = ROOT / "run_state/week1.run.jsonl"
ALLOWED_PREFIXES = ("docs/", "tests/", "tools/", "bench/", "experiments/", "workers/", "notes/")
DENIED_PREFIXES = ("tests/conftest.py", "tests/test_oracle_nara_mailbox.py", "tests/test_flash_",  # its own fence
                   "tools/premerge_check.sh", "tools/qwen_builder.sh", "workers/idea_ledger.py",
                   "experiments/exp008_qat_eval/", "bench/flash_")
DENIED_PATTERN = re.compile(r"PREREGISTRATION|^experiments/research_campaign_|[*?\[\]]|(^|/)\.\.?(/|$)|//"
                            r"|(^|/)\.git(/|$)|(^|/)\.gitattributes$|(^|/)\.gitmodules$")
GIT_SAFE = ("-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-c", "core.sshCommand=false",
            "-c", "submodule.recurse=false")
MAX_ATTEMPTS, MAX_WALL_MINUTES = 3, 30
MAX_TEST_BYTES, MAX_FILE_BYTES, BUILDER_MAX_TOKENS = 8 * 1024, 48 * 1024, 12000
TEST_TIMEOUT_S = 300


class LaneError(RuntimeError):
    pass


def log(task: str, status: str, actual: str, expected: str, duration_ms: int = 0) -> None:
    row = dict(timestamp=datetime.now(timezone.utc).isoformat(), task_id=f"nara-lane:{task}", agent="nara",
               status=status, observable_actual=actual[:2000], observable_expected=expected,
               duration_ms=duration_ms)
    with RUN_LOG.open("a") as handle:
        handle.write(json.dumps(row) + "\n")


def _path_ok(path: str) -> bool:
    return (isinstance(path, str) and path.startswith(ALLOWED_PREFIXES) and not path.startswith(DENIED_PREFIXES)
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
    named = [a for a in argv if isinstance(a, str) and re.search(r"(^|/)test_[^/]+\.py", a)]
    if argv[:3] != ["python", "-m", "pytest"] or named != [test_path]:
        reasons.append("test_argv must be python -m pytest ... <test_path> and name no other test file")
    budget = body.get("budget") or {}
    if budget.get("attempts", 1) > MAX_ATTEMPTS or budget.get("wall_clock_minutes", 1) > MAX_WALL_MINUTES:
        reasons.append(f"budget exceeds {MAX_ATTEMPTS} attempts / {MAX_WALL_MINUTES} minutes")
    return reasons


def _junit_verdict(report: Path, test_path: str) -> tuple[bool, str]:
    """A pass needs at least one executed test from the acceptance module and none failing."""
    if report.is_symlink() or not report.is_file():
        return False, "no JUnit report (the test process exited before pytest finished)"
    root = ET.parse(report).getroot()
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    tests, failures, errors = (sum(int(s.get(key, 0)) for s in suites) for key in ("tests", "failures", "errors"))
    module = test_path[:-3].replace("/", ".")
    cases = [c for s in suites for c in s.iter("testcase") if (c.get("classname") or "").startswith(module)]
    passed = [c for c in cases if not any(c.find(tag) is not None for tag in ("failure", "error", "skipped"))]
    summary = f"junit tests={tests} failures={failures} errors={errors} acceptance_passed={len(passed)}"
    return failures == 0 and errors == 0 and bool(passed), summary


def sandbox_run(worktree: Path, argv: list[str], timeout: float = TEST_TIMEOUT_S) -> tuple[int, str]:
    """Run model-built tests with no network, no home directory and one writable tree."""
    cmd = ["bwrap", "--tmpfs", "/tmp"]  # first, so a worktree under /tmp is bound on top of it
    for directory in ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc"):
        if Path(directory).exists():
            cmd += ["--ro-bind", directory, directory]
    cmd += ["--ro-bind", str(VENV), str(VENV), "--bind", str(worktree), str(worktree)]
    if (worktree / ".git").exists():  # the worktree's git pointer stays read-only
        cmd += ["--ro-bind", str(worktree / ".git"), str(worktree / ".git")]
    args = [*argv[1:], "-p", "no:cacheprovider"]
    test_path = next((a for a in argv if re.search(r"(^|/)test_[^/]+\.py$", a)), None)
    junit_dir = None
    if argv[:3] == ["python", "-m", "pytest"] and test_path:
        junit_dir = Path(tempfile.mkdtemp(prefix="nara-lane-junit-"))
        cmd += ["--bind", str(junit_dir), "/lane-junit"]
        args.append("--junitxml=/lane-junit/report.xml")
    cmd += ["--chdir", str(worktree), "--proc", "/proc", "--dev", "/dev", "--unshare-net", "--unshare-pid",
            "--die-with-parent", "--new-session", "--clearenv",
            "--setenv", "PATH", "/usr/bin:/bin", "--setenv", "HOME", "/tmp",
            "--setenv", "PYTHONDONTWRITEBYTECODE", "1", "--setenv", "MOCK_LLM", "1",
            "--setenv", "PYTHONPATH", str(worktree), str(VENV / "bin/python"), *args]
    try:
        try:
            done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            return 124, f"test timed out after {timeout:.0f} s: {str(exc.stdout or '')[-2000:]}"
        output = (done.stdout + done.stderr)[-6000:]
        if junit_dir is None:
            return done.returncode, output
        ok, summary = _junit_verdict(junit_dir / "report.xml", test_path)
        return (0 if done.returncode == 0 and ok else (done.returncode or 1)), f"{output}\n[lane] {summary}"
    finally:
        if junit_dir is not None:
            shutil.rmtree(junit_dir, ignore_errors=True)


def _git(*args: str, cwd: Path | None = None) -> str:
    """cwd defaults to ROOT at call time (not import time), so tests can redirect it."""
    return subprocess.run(["git", *GIT_SAFE, *args], cwd=cwd or ROOT, check=True, capture_output=True,
                          text=True, timeout=120).stdout


def _checked(worktree: Path, rel: str) -> Path:
    """The path inside the worktree, refusing symlinks anywhere along it."""
    current = worktree
    for part in Path(rel).parts:
        current = current / part
        if current.is_symlink():
            raise LaneError(f"symlink in worktree path: {rel}")
    root = worktree.resolve()
    resolved = current.resolve()
    if resolved != root and root not in resolved.parents:
        raise LaneError(f"path leaves the worktree: {rel}")
    return current


def _write(worktree: Path, rel: str, content: str) -> None:
    target = _checked(worktree, rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not target.is_file():  # a FIFO would block the host
        raise LaneError(f"not a regular file: {rel}")
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW | os.O_NONBLOCK, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(content)


def _read(worktree: Path, rel: str) -> bytes | None:
    target = _checked(worktree, rel)
    if not target.exists():
        return None
    if not target.is_file():
        raise LaneError(f"not a regular file: {rel}")
    fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        return handle.read(MAX_FILE_BYTES + 1)


def _snapshot(worktree: Path) -> dict[str, tuple]:
    """Every entry's type and stat signature; ctime cannot be forged by the sandbox."""
    entries = {}
    for dirpath, dirnames, filenames in os.walk(worktree, followlinks=False):
        rel_dir = os.path.relpath(dirpath, worktree)
        names = filenames + [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]
        for name in names:
            if rel_dir == "." and name == ".git":
                continue
            info = os.lstat(os.path.join(dirpath, name))
            entries[os.path.normpath(os.path.join(rel_dir, name))] = (
                stat.S_IFMT(info.st_mode), info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    return entries


def _dotgit(worktree: Path) -> bytes:
    pointer = worktree / ".git"
    if pointer.is_symlink() or not pointer.is_file():
        raise LaneError("worktree .git pointer is not a regular file")
    return pointer.read_bytes()


def builder(body: dict, worktree: Path, feedback: str, timeout: float = 900) -> dict[str, str]:
    """One local-Flash call proposing full contents for the allowed files."""
    from agent_wrapper.wrapper import call_sync

    test_path = body["acceptance"]["test_path"]
    writable = [p for p in body["allowed_write_paths"] if p != test_path]
    current = {}
    for path in writable:
        data = _read(worktree, path)
        current[path] = None if data is None else data[:MAX_FILE_BYTES].decode("utf-8", "replace")
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
        extra_body={"chat_template_kwargs": {"enable_thinking": False}}, request_timeout_s=timeout,
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


def _left(deadline: float, cap: float) -> float:
    """Seconds allowed for the next step so one item cannot overrun its wall-clock budget."""
    return min(cap, max(5.0, deadline - time.monotonic()))


def implement(entry: dict, build=builder, sandbox=sandbox_run) -> dict:
    """Run one admitted item to a terminal receipt body; never raises."""
    item = entry["item"]
    body, msg_id = item["body"], item["msg_id"]
    acceptance = body["acceptance"]
    test_path, argv = acceptance["test_path"], acceptance["test_argv"]
    budget = body.get("budget") or {}
    deadline = time.monotonic() + 60 * min(budget.get("wall_clock_minutes", MAX_WALL_MINUTES), MAX_WALL_MINUTES)
    attempts_allowed = min(budget.get("attempts", MAX_ATTEMPTS), MAX_ATTEMPTS)
    worktree, branch = WORKTREES / msg_id, f"nara/{msg_id}"
    base_sha = None
    try:
        if worktree.exists():
            return {"state": "failed", "reason": f"worktree already exists: {worktree}"}
        WORKTREES.mkdir(parents=True, exist_ok=True)
        base_sha = _git("rev-parse", "HEAD").strip()
        _git("worktree", "add", "-b", branch, str(worktree), base_sha)
        pointer = _dotgit(worktree)
        before = _snapshot(worktree)
        _write(worktree, test_path, acceptance["test_content"])
        test_sha = hashlib.sha256(acceptance["test_content"].encode()).hexdigest()
        rc, output = sandbox(worktree, argv, timeout=_left(deadline, TEST_TIMEOUT_S))
        if rc == 0:
            return {"state": "failed", "reason": "acceptance test passed before any change (not red-first)",
                    "branch": branch, "base_sha": base_sha, "test_tail": output[-1500:]}
        attempts = 0
        while attempts < attempts_allowed and time.monotonic() < deadline:
            attempts += 1
            try:
                files = build(body, worktree, output, timeout=_left(deadline, 900.0))
            except LaneError:
                raise
            except Exception as exc:  # recorded as feedback for the next attempt
                output = f"builder error: {type(exc).__name__}: {exc}"
                continue
            for path, content in files.items():
                _write(worktree, path, content)
            rc, output = sandbox(worktree, argv, timeout=_left(deadline, TEST_TIMEOUT_S))
            if rc == 0:
                break
        after = _snapshot(worktree)
        changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
        result = {"branch": branch, "worktree": str(worktree), "base_sha": base_sha, "attempts": attempts,
                  "changed_files": changed, "test_tail": output[-1500:]}
        allowed = set(body["allowed_write_paths"]) | {test_path}
        outside = [path for path in changed if path not in allowed]
        if outside:
            return {**result, "state": "failed", "reason": f"changes outside scope: {outside}"}
        irregular = [path for path in changed if path not in after or not stat.S_ISREG(after[path][0])]
        if irregular:
            return {**result, "state": "failed", "reason": f"changed paths must stay regular files: {irregular}"}
        if hashlib.sha256(_read(worktree, test_path) or b"").hexdigest() != test_sha:
            return {**result, "state": "failed", "reason": "the acceptance test was modified"}
        if rc != 0:
            return {**result, "state": "failed", "reason": "acceptance test still failing"}
        if _dotgit(worktree) != pointer:
            return {**result, "state": "failed", "reason": "worktree .git pointer changed"}
        _git("add", "--", *changed, cwd=worktree)
        _git("-c", "user.name=Nara (lab lane)", "-c", "user.email=nara@lab.local", "commit", "-q", "-m",
             f"Nara lane: {body['title']}\n\nOracle plan item {msg_id}; validated in the lane sandbox.", cwd=worktree)
        return {**result, "state": "validated", "head_sha": _git("rev-parse", "HEAD", cwd=worktree).strip()}
    except Exception as exc:
        return {"state": "failed", "reason": f"{type(exc).__name__}: {exc}", "branch": branch, "base_sha": base_sha}


def meta_verdict(rows: list[dict], item: dict) -> str:
    """'accept', 'awaiting', or the latest non-accepting meta-oracle verdict on this item."""
    try:
        policy = json.loads((ROOT / "config/nara_lane.json").read_text())
    except (OSError, ValueError):
        policy = {}
    policy = policy if isinstance(policy, dict) else {}
    exempt = policy.get("review_optional_task_classes")
    if policy.get("require_meta_review") is False or (
            isinstance(exempt, list) and item["body"].get("task_class") in exempt):
        return "accept"
    verdicts = [r["body"]["verdict"] for r in rows if r.get("kind") == "review"  # rows are not schema-checked on read
                and r.get("actor") in mailbox.REVIEWERS and r.get("in_reply_to") == item["msg_id"]
                and isinstance(r.get("body"), dict) and r["body"].get("verdict") in mailbox.VERDICTS]
    return verdicts[-1] if verdicts else "awaiting"


def _paused() -> bool:
    return any((ROOT / pause).exists() for pause in PAUSES)


def _compact(body: dict) -> dict:
    """Keep receipts under the mailbox row limit."""
    out = {}
    for key, value in body.items():
        if isinstance(value, list) and len(value) > 40:
            value = value[:40] + [f"... {len(value) - 40} more"]
        if isinstance(value, str) and len(value) > 1500:
            value = value[-1500:]
        out[key] = value
    return out


def _receipt(path: Path, msg_id: str, body: dict) -> dict:
    try:
        return mailbox.post("nara", "receipt", _compact(body), to="oracle", in_reply_to=msg_id, path=path)
    except mailbox.MailboxError as exc:
        return mailbox.post("nara", "receipt", {"state": body["state"], "reason": f"full receipt rejected: {exc}"[:500],
                                                "branch": body.get("branch"), "head_sha": body.get("head_sha")},
                            to="oracle", in_reply_to=msg_id, path=path)


def run_queue(path: Path = mailbox.PATH, build=builder, sandbox=sandbox_run, ready=None) -> list[dict]:
    """Process every open item once; returns the receipts posted."""
    if _paused():
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
        try:
            rows = mailbox.read(path)
            entries = sorted(mailbox.fold(rows).values(), key=lambda e: e["item"]["seq"])
        except mailbox.MailboxError as exc:
            log("mailbox", "failed", f"mailbox unreadable: {exc}", "readable mailbox")
            return []
        for entry in entries:
            if _paused():
                break
            msg_id = entry["item"]["msg_id"]
            if entry["state"] == "claimed":  # a previous lane process died mid-item
                posted.append(_receipt(path, msg_id, {"state": "failed", "reason": "lane interrupted; item abandoned"}))
                continue
            if entry["state"] != "open":
                continue
            try:
                reasons = admission(entry["item"])
            except Exception as exc:
                reasons = [f"malformed plan item: {type(exc).__name__}: {exc}"]
            if not reasons:
                verdict = meta_verdict(rows, entry["item"])
                if verdict == "awaiting":  # stays open; the review row wakes the lane again
                    log(msg_id, "deferred", "awaiting meta-oracle review", "accepting review")
                    continue
                if verdict != "accept":
                    reasons = [f"meta-oracle verdict: {verdict}; withdraw and repost"]
            if reasons:
                posted.append(_receipt(path, msg_id, {"state": "held", "reasons": reasons}))
                log(msg_id, "held", "; ".join(reasons), "admissible plan item")
                continue
            if not ready():
                log(msg_id, "deferred", "Flash resident not ready", "Flash ready")
                break
            posted.append(_receipt(path, msg_id, {"state": "claimed"}))
            started = time.monotonic()
            outcome = implement(entry, build, sandbox)
            posted.append(_receipt(path, msg_id, outcome))
            log(msg_id, "completed" if outcome["state"] == "validated" else "failed",
                json.dumps({k: outcome.get(k) for k in ("state", "reason", "branch", "head_sha", "attempts")}),
                "validated branch", duration_ms=int((time.monotonic() - started) * 1000))
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
