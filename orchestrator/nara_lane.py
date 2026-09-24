"""Nara's implementor lane (owner direction 2026-09-22, D-082).

Turns Oracle plan items from the mailbox into validated branches, one at a
time unless concurrency is raised (below) and outside the research
coordinator. Per item: admit deterministically,
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

Precheck gate (2026-09-22 retro fix TOOL, plan item d1): an author's claim that
an acceptance test discriminates was asserted without being run twice, and the
cost was three postings, two withdrawals and six lane holds. `precheck()` runs
the claim instead: in the sandbox with no implementation (it must be red) and
again with an author-supplied known-good stub (it must be green), then writes a
receipt named for sha256(test_content) under run_state/precheck_receipts/. An
item whose test has no matching green receipt is held by admission(). The gate
is deliberately not in oracle_mailbox.post() - the mailbox is a generic channel
and its own tests post plan items without receipts - so it can only be enforced
at the lane, which means a hold costs a withdraw-and-repost (a `held` receipt is
terminal in the fold, as an `amend` verdict already found). The receipt is a
discipline, not authentication: the actor who writes the test writes the receipt.

Concurrency (2026-09-24): one runner holds run_state/.nara_lane.lock for its
whole pass, as before, and may run up to K items at once in a bounded thread
pool. K is `max_concurrent_items` in config/nara_lane.json (default 1, the
serial lane), overridable by --max-concurrent or NARA_LANE_MAX_CONCURRENT, and
always capped at the server's max_running_requests - 1 from
config/model_deployment.json (floor 1), so the lane never takes every server
slot. Only the runner's dispatcher claims, in mailbox order; every claim takes a
per-item flock under run_state/nara_lane_claims/ and re-reads the mailbox under
it before posting `claimed`, and the lock is held until the terminal receipt is
posted. A `claimed` item is recovered as abandoned only when its claim lock is
free (its claimant died). Admission, the review gate, the fence, the sandbox and
the per-item checks are unchanged and run per item exactly as in the serial lane.
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
import sys
import subprocess
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
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
# 60 minutes / 1800 s (2026-09-24): with K items sharing the server's decode, a
# 12K-token build at ~15-20 tok/s takes 10-14 minutes, so the serial budgets
# (30 minutes / 900 s) would time out a correct build. Retries stay at zero.
MAX_ATTEMPTS, MAX_WALL_MINUTES = 3, 60
MAX_TEST_BYTES, MAX_FILE_BYTES, BUILDER_MAX_TOKENS = 8 * 1024, 48 * 1024, 12000
TEST_TIMEOUT_S = 300
BUILDER_TIMEOUT_S = 1800.0
CONCURRENCY_ENV = "NARA_LANE_MAX_CONCURRENT"
MAX_CONCURRENT_ITEMS = 4  # hard ceiling, whatever the config or the server says
# nara-lane.service stops a pass at TimeoutStartSec=5400; a pass stops claiming
# before an item's full budget would run past that, less a safety margin.
PASS_BUDGET_ENV = "NARA_LANE_PASS_BUDGET_S"
DEFAULT_PASS_BUDGET_S = 5400 - 300
_GIT_SERIAL = threading.Lock()  # worktree creation and commits, one at a time per runner
_LOG_SERIAL = threading.Lock()


class LaneError(RuntimeError):
    pass


class FixtureCheckError(RuntimeError):
    """A declared fixture source cannot be read, parsed or judged. Refuse the item
    rather than skip the row: a silently-skipped row is how a gate starts lying."""
    pass


def _fixture_objects(path: Path) -> list[dict]:
    """The live rows a fixture is checked against: one object for a JSON file, one per
    non-blank line for JSONL, which is the shape of most live lab state
    (run_state/oracle_nara_mailbox.jsonl, run_state/week1.run.jsonl).

    Raises FixtureCheckError naming the file when it cannot be read, when a line does
    not parse, or when a row is not an object.
    """
    try:
        text = path.read_text(errors="replace")
    except OSError as exc:
        raise FixtureCheckError(f"cannot read {path}: {exc}") from exc
    if path.suffix == ".jsonl":
        rows = []
        for number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                raise FixtureCheckError(f"{path} line {number} is not JSON") from None
            if not isinstance(row, dict):
                raise FixtureCheckError(f"{path} line {number} is not a JSON object")
            rows.append(row)
        return rows
    try:
        doc = json.loads(text)
    except ValueError:
        raise FixtureCheckError(f"{path} is not parseable JSON") from None
    if not isinstance(doc, dict):
        raise FixtureCheckError(f"{path} is a JSON {type(doc).__name__}, not an object")
    return [doc]


def _observed_keys(rows: list[dict], fixture: dict) -> set:
    """Top-level keys the live file really holds. Where rows carry a `kind` field, the
    union is over rows of the fixture's own kind, because rows of another kind
    legitimately differ in shape (a mailbox `note` and a `receipt` share few keys).
    A fixture of a kind the file never holds is judged against all rows and refused
    below, where the real kinds are listed.
    """
    kinds = {r["kind"] for r in rows if isinstance(r.get("kind"), str)}
    kind = fixture.get("kind")
    if kinds and isinstance(kind, str) and kind in kinds:
        rows = [r for r in rows if r.get("kind") == kind]
    return {key for row in rows for key in row}


def _fixture_is_tracked(path: Path, root: Path) -> bool:
    """Whether git tracks `path` in `root`. A live source a fixture claims to come from
    has to be a file other people can read and would notice changing; an untracked file
    in a working tree proves nothing about the lab's data.

    Separate and monkeypatchable, because the real answer needs `git ls-files` against
    the root that runs admission() - and a test that assumed one particular checkout is
    what the rejected d3 did wrong (review claude-0404f2c56845b56f, seq 216)."""
    try:
        out = subprocess.run(["git", *GIT_SAFE, "-C", str(root), "ls-files", "--error-unmatch",
                              str(path.relative_to(root))],
                             capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError, ValueError):
        return False
    return out.returncode == 0


def check_fixtures(item: dict) -> list[str]:
    """Refuse a plan item whose test fixtures do not match the live files it declares.

    Three days of lane holds came from one authoring defect (retro
    claude-fd99b8f6159965c4, cause missing_context), and plan 2026-09-24 d1 cost nine
    postings of the same shape: a fixture was derived by hand from a live file and got
    its shape wrong - a key the file does not have, or an enum value it never holds -
    or a plan item named a source file that exists nowhere. The lane found each one
    only after a sandbox run, so every mistake cost a posting, a review round and a
    hold. This refuses it before the sandbox rather than asking the author to be
    careful.

    A plan item declares `fixture_sources` {fixture name: repo-relative live path} and
    `fixtures` {fixture name: the object its test uses}; `fixture_enums` {fixture name:
    [field, ...]} names the fields whose values must also occur in the live file. Enum
    fields are declared, never inferred - a str-valued field is not assumed to be an
    enum, which would refuse most string fields in the lab's history.

    Deliberately loose where looseness costs nothing: a fixture named in no source map
    is unchecked (synthetic fixtures are fine), nested keys are not compared (top level
    only, which is where the drift showed), and an enum field the fixture omits is
    skipped. Sources, enums and fixtures are shape-checked by
    mailbox.validate_plan_item(), so they are objects of the right type by here.

    Raises FixtureCheckError on a live file that cannot be read, parsed or judged;
    otherwise returns refusal reasons (empty means everything declared is observed).
    """
    body = item["body"]
    sources, enums = body.get("fixture_sources") or {}, body.get("fixture_enums") or {}
    fixtures = body.get("fixtures", {})
    if not isinstance(fixtures, dict):
        return ["fixtures must be an object mapping fixture name -> the object the test uses"]
    reasons: list[str] = []
    root = Path(ROOT)
    for name, rel in sorted(sources.items()):
        if rel.startswith("/") or ".." in Path(rel).parts:
            reasons.append(f"fixture_sources.{name} points outside the repo root: {rel}")
            continue
        live = root / rel
        try:
            live.resolve().relative_to(root.resolve())
        except ValueError:
            reasons.append(f"fixture_sources.{name} points outside the repo root: {rel}")
            continue
        if not live.is_file():
            reasons.append(f"fixture_sources.{name} names a live file that does not exist: {rel}")
            continue
        if not _fixture_is_tracked(live, root):
            reasons.append(f"fixture_sources.{name} is not tracked by git, so it is not the "
                           f"lab's data: {rel}")
            continue
        fixture = fixtures.get(name)
        if fixture is None:
            continue                       # case 6 (check_declared_sources_ship_fixtures)
        if not isinstance(fixture, dict):
            reasons.append(f"fixtures.{name} must be an object, got {type(fixture).__name__}")
            continue
        rows = _fixture_objects(live)
        observed = _observed_keys(rows, fixture)
        for key in sorted(set(fixture) - observed):
            reasons.append(f"fixtures.{name} has a key no live row of {rel} has: {key} "
                           f"(live keys: {sorted(observed)[:20]})")
        kinds = {r["kind"] for r in rows if isinstance(r.get("kind"), str)}
        kind = fixture.get("kind")
        if kinds and isinstance(kind, str) and kind not in kinds:
            reasons.append(f"fixtures.{name} has kind {kind!r}, which {rel} never holds "
                           f"(live kinds: {sorted(kinds)})")
        for field in sorted(enums.get(name, [])):
            if field not in fixture:
                continue
            value = fixture[field]
            values = {r[field] for r in rows if field in r and isinstance(r[field], str)}
            if isinstance(value, str) and value not in values:
                reasons.append(f"fixtures.{name}.{field}={value!r} is a value the live file {rel} "
                               f"never holds (live values: {sorted(values)[:20]})")
    return reasons


def check_declared_sources_ship_fixtures(item: dict) -> list[str]:
    """Refuse an item that declares fixture_sources or fixture_enums without the fixture
    data that declaration is about.

    A declaration claims the lane can check a fixture against a live file. That is only
    meaningful if the item also ships the fixture object, because the fixture is what
    the test uses and what the check compares. On the rejected d3 branch a bare
    `fixture_sources` entry passed every check - `fixtures` was an unknown key to
    validate_plan_item - so the gate was decorative (review claude-56275cf790bac03c,
    finding 1). Both maps take the rule and both are keyed by fixture name, so a name
    the shipped fixtures do not hold is a declaration about nothing.
    """
    body = item["body"]
    sources = set(body.get("fixture_sources") or {})
    enums = set(body.get("fixture_enums") or {})
    shipped = {k for k, v in (body.get("fixtures") or {}).items() if isinstance(v, dict)}
    reasons = [f"fixture_sources.{name} declares a live file but the item ships no fixtures.{name}, "
               f"so nothing is compared and Nara's worktree gets no fixture: ship "
               f"fixtures.{name} or drop the declaration"
               for name in sorted(sources - shipped)]
    reasons += [f"fixture_enums.{name} declares enum fields for a fixture the item does not ship, "
                f"so no value is ever checked: ship fixtures.{name} or drop the declaration"
                for name in sorted(enums - shipped)]
    return reasons


def log(task: str, status: str, actual: str, expected: str, duration_ms: int = 0) -> None:
    row = dict(timestamp=datetime.now(timezone.utc).isoformat(), task_id=f"nara-lane:{task}", agent="nara",
               status=status, observable_actual=actual[:2000], observable_expected=expected,
               duration_ms=duration_ms)
    with _LOG_SERIAL, RUN_LOG.open("a") as handle:
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
    if not reasons:  # declared fixtures must match the live files (plan 2026-09-24 d3)
        try:
            reasons.extend(check_declared_sources_ship_fixtures(item))
            reasons.extend(check_fixtures(item))
        except FixtureCheckError as exc:
            reasons.append(f"fixture_sources cannot be checked: {exc}")
    if not reasons and not _prechecked(item):  # last, so it never masks an earlier reason
        sha = test_sha256(acceptance["test_content"])
        reasons.append(f"no green precheck receipt for sha256(test_content) {sha}: run "
                       "`python -m orchestrator.nara_lane precheck --test-path P --test-file F --stub S`; "
                       f"the receipt would be {receipt_path(sha)}")
    return reasons


def test_sha256(test_content: str) -> str:
    return hashlib.sha256(test_content.encode()).hexdigest()


def _receipt_dir(root: Path | None = None) -> Path:
    """Where precheck receipts live, resolved at call time: they are written to
    run_state/ at runtime, never inside a precheck or Nara worktree. A test that
    redirects lane ROOT gets receipts under the redirected ROOT."""
    return (Path(root) if root is not None else Path(ROOT)) / "run_state/precheck_receipts"


def receipt_path(sha: str, *, root: Path | None = None) -> Path:
    """The receipt for one exact acceptance-test content, named for its sha256."""
    return _receipt_dir(root) / f"{sha}.json"


def _prechecked(item: dict) -> bool:
    """True when a green precheck receipt covers this exact test content."""
    acceptance = item["body"]["acceptance"]
    directory = _receipt_dir()
    path = directory / f"{test_sha256(acceptance['test_content'])}.json"
    if path.is_symlink() or not path.is_file():
        return False
    try:
        body = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    return (isinstance(body, dict) and body.get("state") == "green"
            and body.get("test_sha256") == test_sha256(acceptance["test_content"]) == path.stem)


class PrecheckError(RuntimeError):
    pass


def precheck(test_path: str, test_content: str, test_argv: list[str], *,
             stubs: list[dict[str, str]] | None = None, sandbox=None,
             timeout: float = TEST_TIMEOUT_S) -> dict:
    """Run an acceptance test's discrimination claim in the sandbox before posting it.

    Draws a fixture worktree from main, writes the test, and runs it with no
    implementation (must be red) and once per supplied stub (a green stub makes
    the item prechecked). Reports each run's output so a non-discriminating test
    is diagnosable, and writes run_state/precheck_receipts/<sha256>.json only on
    a green run. The stub is a fixture for this check only: it is never copied
    into Nara's worktree, which is created fresh by implement().

    Two things would otherwise let a green receipt record a claim that was never
    shown, so they are refused here (review claude-c0a841a1831ad8a6): a stub may
    not write the acceptance test - it would overwrite the test whose sha the
    receipt names, so the passing run would not be the posted test - and every
    stub runs on a worktree reset to main including tracked modifications, so a
    stub never passes on a previous stub's leftover edit.

    Raises PrecheckError on an inadmissible test (checked by admission(), not
    reimplemented here), a stub that writes the acceptance test, or a test that is
    not red-first.
    """
    sandbox = sandbox or sandbox_run
    # Structural checks first, on the test alone: an oversized or malformed test is
    # refused before any fixture is drawn, so refusal leaves no worktree behind.
    if len(test_content.encode()) > MAX_TEST_BYTES:
        raise PrecheckError(f"acceptance test exceeds {MAX_TEST_BYTES // 1024} KiB")
    if not (_path_ok(test_path) and re.search(r"(^|/)test_[^/]+\.py$", test_path)):
        raise PrecheckError(f"acceptance test must be a test_*.py inside the lane fence: {test_path}")
    named = [a for a in test_argv if isinstance(a, str) and re.search(r"(^|/)test_[^/]+\.py", a)]
    if list(test_argv)[:3] != ["python", "-m", "pytest"] or named != [test_path]:
        raise PrecheckError("test_argv must be python -m pytest ... <test_path> and name no other test file")
    for stub in stubs or []:
        if test_path in stub:
            raise PrecheckError(f"stub may not write the acceptance test: {test_path}")
    # Everything the stubs would write then goes through the lane's own fence.
    item = {"actor": "oracle", "msg_id": "precheck", "body": {
        "title": "precheck", "objective": "", "task_class": "tooling",
        "allowed_write_paths": sorted({p for stub in (stubs or []) for p in stub}),
        "acceptance": {"test_path": test_path, "test_content": test_content, "test_argv": list(test_argv)}}}
    reasons = admission_without_receipt(item)
    if reasons:
        raise PrecheckError("; ".join(reasons))
    sha = test_sha256(test_content)
    base = _git("rev-parse", "main").strip()
    fixture_root = tempfile.mkdtemp(prefix=f"precheck-{sha[:16]}-", dir=str(_precheck_root()))
    fixture = Path(fixture_root) / "wt"
    try:
        _git("worktree", "add", "--detach", str(fixture), base)
    except subprocess.CalledProcessError as exc:
        _git("worktree", "prune")
        detail = (exc.stderr or "").strip() if isinstance(exc.stderr, str) else ""
        raise PrecheckError(f"cannot draw a precheck fixture worktree: {detail[:400]}") from exc
    runs: list[dict] = []
    try:
        _write(fixture, test_path, test_content)
        rc, output = sandbox(fixture, list(test_argv), timeout=timeout)
        red = {"stub": None, "passed": rc == 0, "output": output[-3000:]}
        runs.append(red)
        if rc == 0:
            raise PrecheckError("acceptance test is not red-first: it passes with no implementation\n"
                                + output[-1500:])
        green = None
        for stub in stubs or []:
            _reset_fixture(fixture)
            for path, content in stub.items():
                _write(fixture, path, content)
            _write(fixture, test_path, test_content)  # last: a stub can never replace the test
            rc, output = sandbox(fixture, list(test_argv), timeout=timeout)
            runs.append({"stub": sorted(stub), "passed": rc == 0, "output": output[-3000:]})
            if rc == 0:
                green = {"stub": sorted(stub), "passed": True, "output": output[-3000:]}
                break
        report = {"test_sha256": sha, "test_path": test_path, "base_sha": base, "fixture": str(fixture),
                  "red_run": red, "green_run": green, "green_receipt": None, "runs": runs}
        if green is not None:
            path = receipt_path(sha)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "schema": "nara-lane-precheck/v1", "test_sha256": sha, "test_path": test_path,
                "state": "green", "stub_paths": green["stub"], "base_sha": base,
                "prechecked_at": datetime.now(timezone.utc).isoformat(),
                "note": "a discipline, not authentication: the test author writes this receipt"},
                indent=2) + "\n")
            report["green_receipt"] = str(path)
        return report
    finally:
        if fixture.exists():
            _git("worktree", "remove", "--force", str(fixture))
        _git("worktree", "prune")
        shutil.rmtree(fixture_root, ignore_errors=True)  # this run's own fixture root only


def _precheck_root() -> Path:
    """Where precheck fixture roots are created and thrown away: beside the repo,
    never inside it, resolved from lane ROOT at call time so a test that redirects
    ROOT cannot draw from - or clean up - a real repository. Each run gets its own
    tempfile directory under here (never this shared directory itself), so two
    prechecks cannot delete each other's fixtures."""
    root = Path(ROOT).parent / "precheck-worktrees"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _reset_fixture(worktree: Path) -> None:
    """Put the fixture back to exactly `main`, so each stub is checked alone.

    Both halves are needed: `reset --hard` reverts edits to tracked files (clean
    does not, so a later stub would otherwise pass on an earlier stub's leftover),
    and `clean -qfdx` removes untracked ones, including the acceptance test, which
    precheck rewrites after the stub so a stub can never stand in for it.
    """
    _git("reset", "-q", "--hard", "HEAD", cwd=worktree)
    _git("clean", "-qfdx", cwd=worktree)


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


def builder(body: dict, worktree: Path, feedback: str, timeout: float = BUILDER_TIMEOUT_S, *,
            caller_tag: str = "nara_lane_builder") -> dict[str, str]:
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
        temperature=0.2, max_tokens=BUILDER_MAX_TOKENS, caller_tag=caller_tag,
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


def item_budget_s(body: dict) -> int:
    """An item's wall-clock budget in seconds, as implement() enforces it."""
    budget = body.get("budget") or {}
    return 60 * min(budget.get("wall_clock_minutes", MAX_WALL_MINUTES), MAX_WALL_MINUTES)


def implement(entry: dict, build=builder, sandbox=sandbox_run) -> dict:
    """Run one admitted item to a terminal receipt body; never raises."""
    item = entry["item"]
    body, msg_id = item["body"], item["msg_id"]
    acceptance = body["acceptance"]
    test_path, argv = acceptance["test_path"], acceptance["test_argv"]
    budget = body.get("budget") or {}
    deadline = time.monotonic() + item_budget_s(body)
    attempts_allowed = min(budget.get("attempts", MAX_ATTEMPTS), MAX_ATTEMPTS)
    worktree, branch = WORKTREES / msg_id, f"nara/{msg_id}"
    base_sha = None
    try:
        if worktree.exists():
            return {"state": "failed", "reason": f"worktree already exists: {worktree}"}
        WORKTREES.mkdir(parents=True, exist_ok=True)
        with _GIT_SERIAL:
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
                kwargs = {"timeout": _left(deadline, BUILDER_TIMEOUT_S)}
                if build is builder:  # custom builders keep the historic four-argument seam
                    kwargs["caller_tag"] = f"nara_lane_builder:{msg_id}"
                files = build(body, worktree, output, **kwargs)
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
        with _GIT_SERIAL:
            _git("add", "--", *changed, cwd=worktree)
            _git("-c", "user.name=Nara (lab lane)", "-c", "user.email=nara@lab.local", "commit", "-q", "-m",
                 f"Nara lane: {body['title']}\n\nOracle plan item {msg_id}; validated in the lane sandbox.",
                 cwd=worktree)
        return {**result, "state": "validated", "head_sha": _git("rev-parse", "HEAD", cwd=worktree).strip()}
    except Exception as exc:
        return {"state": "failed", "reason": f"{type(exc).__name__}: {exc}", "branch": branch, "base_sha": base_sha}


def _policy() -> dict:
    """config/nara_lane.json, or {} when missing or unreadable (which requires review)."""
    try:
        policy = json.loads((ROOT / "config/nara_lane.json").read_text())
    except (OSError, ValueError):
        policy = {}
    return policy if isinstance(policy, dict) else {}


def meta_verdict(rows: list[dict], item: dict) -> str:
    """'accept', 'awaiting', or the latest non-accepting meta-oracle verdict on this item."""
    policy = _policy()
    exempt = policy.get("review_optional_task_classes")
    if policy.get("require_meta_review") is False or (
            isinstance(exempt, list) and item["body"].get("task_class") in exempt):
        return "accept"
    verdicts = [r["body"]["verdict"] for r in rows if r.get("kind") == "review"  # rows are not schema-checked on read
                and r.get("actor") in mailbox.REVIEWERS and r.get("in_reply_to") == item["msg_id"]
                and isinstance(r.get("body"), dict) and r["body"].get("verdict") in mailbox.VERDICTS]
    return verdicts[-1] if verdicts else "awaiting"


def _positive_int(value) -> int | None:
    return value if type(value) is int and value >= 1 else None


def server_slots() -> int:
    """max_running_requests from config/model_deployment.json; 1 when missing or unreadable."""
    try:
        deployment = json.loads((Path(ROOT) / "config/model_deployment.json").read_text())
    except (OSError, ValueError):
        return 1
    return _positive_int(deployment.get("max_running_requests") if isinstance(deployment, dict) else None) or 1


def _env_int(name: str) -> int | None:
    """A positive decimal integer from the environment; None when unset, 0 when malformed."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    return int(raw) if raw.isascii() and raw.isdigit() else 0


def lane_concurrency(requested: int | None = None) -> int:
    """How many items one run may process at once.

    The request is the argument (the --max-concurrent flag), else the
    NARA_LANE_MAX_CONCURRENT environment variable, else `max_concurrent_items` in
    config/nara_lane.json, else 1; anything that is not a positive integer counts
    as 1. It is then capped at server_slots() - 1 so the lane always leaves the
    server a slot, and at MAX_CONCURRENT_ITEMS, with a floor of 1 so a
    single-slot server keeps today's serial lane.
    """
    if requested is None:
        requested = _env_int(CONCURRENCY_ENV)
    if requested is None:
        requested = _policy().get("max_concurrent_items", 1)
    return max(1, min(_positive_int(requested) or 1, server_slots() - 1, MAX_CONCURRENT_ITEMS))


def pass_budget_s() -> int:
    """Seconds one run may spend before it stops claiming: NARA_LANE_PASS_BUDGET_S,
    else `pass_budget_s` in config/nara_lane.json, else DEFAULT_PASS_BUDGET_S
    (the service's TimeoutStartSec less a margin). Malformed or oversized values
    use the default, because a larger budget would let the service cut work off."""
    value = _env_int(PASS_BUDGET_ENV)
    if value is None:
        value = _policy().get("pass_budget_s")
    return min(_positive_int(value) or DEFAULT_PASS_BUDGET_S, DEFAULT_PASS_BUDGET_S)


def _clock() -> float:
    """The pass clock, separate from implement()'s deadlines so tests can drive it."""
    return time.monotonic()


def _read_mailbox(path: Path) -> list[dict]:
    """mailbox.read() under a shared hold of the mailbox's own lock (the file
    oracle_mailbox.post() holds exclusively), so a row being appended is never
    read half-written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with (path.parent / ".oracle_nara_mailbox.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_SH)
        return mailbox.read(path)


def _lane_lock_path() -> Path:
    """The lane-runner lock, under run_state/, resolved at call time with ROOT.
    One runner dispatches at a time; items are claimed under _claim_lock_path."""
    return Path(ROOT) / "run_state/.nara_lane.lock"


def _claim_lock_path(msg_id: str) -> Path:
    """The per-item claim lock, named for sha256(msg_id): rows are not
    schema-checked on read, so a msg_id never becomes a path component here."""
    return Path(ROOT) / "run_state/nara_lane_claims" / f"{hashlib.sha256(msg_id.encode()).hexdigest()[:32]}.lock"


def _claim(path: Path, msg_id: str, expected: str):
    """The item's claim lock, held, if the item is still in `expected` state when
    re-read under it; otherwise None. A live claimant holds this lock from before
    its `claimed` receipt until after its terminal one, so a held lock means the
    item is in progress and a free lock on a `claimed` item means it was abandoned.
    flock is per open file, so this excludes other threads as well as processes.
    Raises MailboxError, with the claim released, when the mailbox is unreadable."""
    lock_path = _claim_lock_path(msg_id)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = os.fdopen(os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o644), "a")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    try:
        current = mailbox.fold(_read_mailbox(path)).get(msg_id)
    except BaseException:
        handle.close()
        raise
    if current is None or current["state"] != expected:
        handle.close()
        return None
    return handle


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


def _open_item(rows: list[dict], item: dict) -> bool:
    """Whether the current mailbox still has this item open."""
    current = mailbox.fold(rows).get(item["msg_id"])
    return current is not None and current["state"] == "open"


def _open_with_verdict(rows: list[dict], item: dict, verdicts: set[str]) -> bool:
    """Whether the current mailbox still has this open item at one of ``verdicts``."""
    return _open_item(rows, item) and meta_verdict(rows, item) in verdicts


def _claim_if_meta_accepts(path: Path, entry: dict) -> dict | None:
    """Atomically post ``claimed`` only for the mailbox's current accepting review.

    The caller already holds the per-item claim lock.  ``post_if`` takes the
    mailbox writer lock, so the review recheck and the claimed append share one
    mailbox prefix (claim lock -> mailbox lock); a reviewer cannot amend or
    reject in between them.
    """
    item = entry["item"]
    return mailbox.post_if("nara", "receipt", {"state": "claimed"}, to="oracle",
                           in_reply_to=item["msg_id"], path=path,
                           condition=lambda rows: _open_with_verdict(rows, item, {"accept"}))


def _post_held(path: Path, entry: dict, reasons: list[str], verdicts: set[str] | None = None) -> dict | None:
    """Append ``held`` only while the item remains open, and optionally rejected."""
    item = entry["item"]
    return mailbox.post_if(
        "nara", "receipt", {"state": "held", "reasons": reasons},
        to="oracle", in_reply_to=item["msg_id"], path=path,
        condition=(lambda rows: _open_with_verdict(rows, item, verdicts)) if verdicts else
        (lambda rows: _open_item(rows, item)),
    )


def _hold_open(path: Path, entry: dict, reasons: list[str], verdicts: set[str] | None = None) -> dict | None:
    """Claim an open item briefly to append a state-conditional held receipt.

    This covers rejections before a worker claim too: claim lock then mailbox
    lock prevents a withdrawal during admission from acquiring a stale hold.
    """
    claim = _claim(path, entry["item"]["msg_id"], "open")
    if claim is None:
        return None
    try:
        return _post_held(path, entry, reasons, verdicts)
    finally:
        claim.close()


def _finish(path: Path, entry: dict, claim, build, sandbox, keep, contain: bool) -> None:
    """Implement one claimed item and post its terminal receipt, then release the claim.

    contain=False is the serial lane: anything implement() or the receipt raises
    propagates, exactly as before. contain=True is a pool worker: a crash becomes
    this item's own `failed` receipt, and a receipt that cannot be posted is
    logged and left to the next run's abandoned-claim recovery, so one worker's
    failure never touches another item's receipt.
    """
    msg_id = entry["item"]["msg_id"]
    try:
        started = time.monotonic()
        try:
            outcome = implement(entry, build, sandbox)
        except BaseException as exc:
            if not contain:
                raise
            outcome = {"state": "failed", "reason": f"lane worker crashed: {type(exc).__name__}: {exc}"}
        try:
            keep(_receipt(path, msg_id, outcome))
        except BaseException as exc:
            if not contain:
                raise
            log(msg_id, "failed", f"terminal receipt not posted: {type(exc).__name__}: {exc}",
                "terminal receipt posted")
            return
        log(msg_id, "completed" if outcome["state"] == "validated" else "failed",
            json.dumps({k: outcome.get(k) for k in ("state", "reason", "branch", "head_sha", "attempts")}),
            "validated branch", duration_ms=int((time.monotonic() - started) * 1000))
    finally:
        claim.close()


def _worker(path: Path, entry: dict, claim, build, sandbox, keep, slots) -> None:
    try:
        _finish(path, entry, claim, build, sandbox, keep, contain=True)
    finally:
        slots.release()


def run_queue(path: Path | None = None, build=builder, sandbox=sandbox_run, ready=None,
              max_concurrent: int | None = None) -> list[dict]:
    """Process every open item once; returns the receipts posted, in mailbox order.

    With lane_concurrency() == 1 each item runs to its terminal receipt before
    the next is examined (the serial lane). Above 1, the dispatcher still
    examines, admits and claims items one at a time in mailbox order, but hands
    each claimed item to a pool worker and waits only for a free slot, checking
    the pause files and Flash readiness again just before each claim.

    At any K, the run stops claiming once the time it has run plus the next
    item's budget would pass pass_budget_s(), so the service's stop timeout never
    cuts an item short; unclaimed items stay open for the next run. An unreadable
    mailbox mid-pass stops claiming as well.
    """
    if _paused():
        return []
    path = mailbox.PATH if path is None else path  # resolved at call time, like _git's ROOT
    if ready is None:
        from orchestrator.flash_resident import check_ready as ready
    posted = []
    posted_lock = threading.Lock()

    def keep(receipt: dict) -> None:
        with posted_lock:
            posted.append(receipt)

    pass_started, pass_budget = _clock(), pass_budget_s()
    lock_path = _lane_lock_path()
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return []
        try:
            rows = _read_mailbox(path)
            entries = sorted(mailbox.fold(rows).values(), key=lambda e: e["item"]["seq"])
        except mailbox.MailboxError as exc:
            log("mailbox", "failed", f"mailbox unreadable: {exc}", "readable mailbox")
            return []
        workers = lane_concurrency(max_concurrent)
        pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="nara-lane-item") if workers > 1 else None
        slots = threading.BoundedSemaphore(workers)
        if pool is not None:
            log("runner", "started", f"max_concurrent_items={workers} server_slots={server_slots()}",
                "bounded concurrent lane")
        try:
            for entry in entries:
                if _paused():
                    break
                msg_id = entry["item"]["msg_id"]
                if entry["state"] == "claimed":  # a lane process died mid-item, unless its claim is still held
                    try:
                        claim = _claim(path, msg_id, "claimed")
                    except mailbox.MailboxError as exc:
                        log("mailbox", "failed", f"mailbox unreadable mid-pass: {exc}", "readable mailbox")
                        break
                    if claim is None:
                        continue
                    with claim:
                        keep(_receipt(path, msg_id, {"state": "failed", "reason": "lane interrupted; item abandoned"}))
                    continue
                if entry["state"] != "open":
                    continue
                try:
                    reasons = admission(entry["item"])
                except Exception as exc:
                    reasons = [f"malformed plan item: {type(exc).__name__}: {exc}"]
                meta_rejection = False
                if not reasons:
                    verdict = meta_verdict(rows, entry["item"])
                    if verdict == "awaiting":  # stays open; the review row wakes the lane again
                        log(msg_id, "deferred", "awaiting meta-oracle review", "accepting review")
                        continue
                    if verdict != "accept":
                        reasons = [f"meta-oracle verdict: {verdict}; withdraw and repost"]
                        meta_rejection = True
                if reasons:
                    try:
                        held = _hold_open(path, entry, reasons, {"amend", "reject"} if meta_rejection else None)
                    except mailbox.MailboxError as exc:
                        log("mailbox", "failed", f"mailbox unreadable mid-pass: {exc}", "readable mailbox")
                        break
                    if held is not None:
                        keep(held)
                        log(msg_id, "held", "; ".join(reasons), "admissible plan item")
                    else:
                        log(msg_id, "deferred", "item changed before held receipt", "open item")
                    continue
                slots.acquire()  # the serial lane never waits here: its slot is back before the next item
                handed_off = False
                try:
                    if pool is not None and _paused():  # a pause may have landed while waiting for a slot
                        break
                    elapsed, budget_s = _clock() - pass_started, item_budget_s(entry["item"]["body"])
                    if budget_s > pass_budget:
                        reason = (f"item wall-clock budget {budget_s} s exceeds pass budget {pass_budget} s; "
                                  "withdraw and repost with a fitting budget")
                        try:
                            held = _hold_open(path, entry, [reason])
                        except mailbox.MailboxError as exc:
                            log("mailbox", "failed", f"mailbox unreadable mid-pass: {exc}", "readable mailbox")
                            break
                        if held is not None:
                            keep(held)
                            log(msg_id, "held", reason, "item budget fits the pass")
                        else:
                            log(msg_id, "deferred", "item changed before held receipt", "open item")
                        continue
                    if elapsed + budget_s > pass_budget:
                        log(msg_id, "deferred", f"pass budget: {elapsed:.0f} s run + item budget "
                            f"{budget_s} s > {pass_budget} s", "time left in the pass")
                        break
                    if not ready():
                        log(msg_id, "deferred", "Flash resident not ready", "Flash ready")
                        break
                    try:
                        claim = _claim(path, msg_id, "open")
                    except mailbox.MailboxError as exc:
                        log("mailbox", "failed", f"mailbox unreadable mid-pass: {exc}", "readable mailbox")
                        break
                    if claim is None:  # withdrawn, expired or claimed elsewhere since the fold was read
                        continue
                    try:
                        claimed = _claim_if_meta_accepts(path, entry)
                    except BaseException:
                        claim.close()
                        raise
                    if claimed is None:
                        try:
                            held = _post_held(path, entry,
                                              ["meta-oracle verdict changed before claim; withdraw and repost"],
                                              {"amend", "reject"})
                        except BaseException:
                            claim.close()
                            raise
                        if held is not None:
                            keep(held)
                            log(msg_id, "held", "meta-oracle verdict changed before claim", "accepting review")
                        else:
                            log(msg_id, "deferred", "meta-oracle review changed or item closed before claim",
                                "accepting review")
                        claim.close()
                        continue
                    keep(claimed)
                    if pool is None:
                        _finish(path, entry, claim, build, sandbox, keep, contain=False)
                    else:
                        pool.submit(_worker, path, entry, claim, build, sandbox, keep, slots)
                        handed_off = True
                finally:
                    if not handed_off:
                        slots.release()
        finally:
            if pool is not None:
                pool.shutdown(wait=True)  # the runner lock is held until every worker has posted
    if pool is not None:
        posted.sort(key=lambda row: row["seq"])
    return posted


def admission_without_receipt(item: dict) -> list[str]:
    """admission() minus the precheck-receipt rule, for the precheck entry point
    itself, whose test has no receipt by definition (it is what makes one)."""
    reasons = admission(item)
    return [r for r in reasons if "precheck receipt" not in r]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["run", "status", "precheck"])
    parser.add_argument("--test-path", help="precheck: where the acceptance test lives in the worktree")
    parser.add_argument("--test-file", type=Path, help="precheck: file holding the acceptance test content")
    parser.add_argument("--stub", action="append", default=[], type=Path,
                        help="precheck: a JSON file mapping repo path -> known-good content (repeatable)")
    parser.add_argument("--argv", help="precheck: JSON list, the test command (default: python -m pytest -q TEST)")
    parser.add_argument("--max-concurrent", type=int,
                        help=f"run: items processed at once (default: ${CONCURRENCY_ENV}, else "
                             "config/nara_lane.json max_concurrent_items, else 1; capped at the server's "
                             "max_running_requests - 1)")
    args = parser.parse_args(argv)
    if args.command == "status":
        view = {k: {"title": v["item"]["body"]["title"], "state": v["state"]}
                for k, v in mailbox.fold(mailbox.read()).items()}
        print(json.dumps(view, indent=2))
        return 0
    if args.command == "precheck":
        if not (args.test_path and args.test_file):
            parser.error("precheck needs --test-path and --test-file")
        argv_list = json.loads(args.argv) if args.argv else ["python", "-m", "pytest", "-q", args.test_path]
        stubs = [json.loads(path.read_text()) for path in args.stub]
        try:
            report = precheck(args.test_path, args.test_file.read_text(), argv_list, stubs=stubs)
        except (PrecheckError, LaneError) as exc:
            print(f"precheck: {exc}", file=sys.stderr)
            return 2
        print(json.dumps({k: report[k] for k in
                          ("test_sha256", "test_path", "base_sha", "red_run", "green_run", "green_receipt")},
                         indent=2))
        return 0 if report["green_run"] else 1
    for receipt in run_queue(max_concurrent=args.max_concurrent):
        print(json.dumps({"re": receipt["in_reply_to"], "state": receipt["body"]["state"],
                          "reason": receipt["body"].get("reason") or receipt["body"].get("reasons")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
