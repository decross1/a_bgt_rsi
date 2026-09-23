"""Oracle's acceptance-test precheck (plan 2026-09-23 d1, G7.1; 2026-09-22 retro fix TOOL).

Why this exists: on 2026-09-22 three postings of the lab-state-packet plan item
cost the lane six holds and two withdrawals, because Oracle asserted its test
discriminated (red without the tool, green with a correct one) without running
it; one of those tests failed 9 of 11 checks from a defect in the test itself.

Precheck runs that claim instead of asserting it: it draws a fixture worktree
from main, writes the acceptance test, runs it with no implementation (it must
be red), then again with an author-supplied known-good stub (a green stub makes
the item prechecked), and writes a receipt named for sha256(test_content) under
run_state/precheck_receipts/. admission() holds an item whose test has no
matching green receipt, so an undiscriinating test never costs a lane cycle.

Scope, per the meta review (claude-bfc06cece11638c0): the gate lives in
admission(), not in oracle_mailbox.post() - the mailbox is a generic channel and
its own tests post plan items without receipts - and the stub stays in the
precheck fixture, never copied into Nara's worktree.

Hermetic: the unit tests hand precheck an injected `sandbox` (a host subprocess
pytest run, as tests/test_oracle_nara_mailbox.py does) so they need no
bubblewrap; test_precheck_runs_in_the_real_sandbox confirms both runs through
lane.sandbox_run itself, skipping if bwrap is unavailable.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys

import pytest

from orchestrator import nara_lane as lane
from orchestrator import oracle_mailbox as mailbox

# The item under test needs a module that does not exist on main, so the no-stub
# run is red for the right reason (the tool is missing), not because an
# assertion is wrong. Two shapes of the same assertion: `tools_pkg` imports it as
# a package member, which works in a sandbox bound to the real lab repo (it has
# tools/__init__.py) and in a scratch repo that carries one; `sibling` imports it
# by filename from beside the test, which works in a scratch repo whose root is
# on sys.path through rootdir conftest handling.
STUB = {"tools/precheck_slug_fixture.py": "def slugify(text):\n    return '-'.join(text.lower().split())\n"}
BROKEN_STUB = {"tools/precheck_slug_fixture.py": "def slugify(text):\n    return text.lower()\n"}
TEST_PATH = "tests/test_precheck_slug_fixture.py"
ARGV = ["python", "-m", "pytest", "-q", TEST_PATH]
REPO_TEST = (
    "from tools.precheck_slug_fixture import slugify\n"
    "\n"
    "def test_slug():\n"
    "    assert slugify('A b') == 'a-b'\n"
    "\n"
    "def test_rejects_empty():\n"
    "    assert slugify('   ') == ''\n"
)
# For the lane-queue tests, whose scratch repo has no tools package: the module
# sits beside the test and the test puts that directory on sys.path itself, so it
# resolves identically under pytest's rootdir/import modes.
LANE_TEST = (
    "from precheck_slug_sibling import slugify\n"
    "\n"
    "def test_slug():\n"
    "    assert slugify('A b') == 'a-b'\n"
    "\n"
    "def test_rejects_empty():\n"
    "    assert slugify('   ') == ''\n"
)
LANE_TEST_PATH = "tests/test_precheck_slug_sibling.py"
# The precheck stub for that test: the module beside it. The lane's builder writes
# the real deliverable (tools/slug.py), which the scratch repo cannot import - see
# test_run_queue_admits_a_receipted_item_and_validates_it for what that costs.
LANE_STUB = {"tests/precheck_slug_sibling.py": "def slugify(text):\n    return '-'.join(text.lower().split())\n"}
LANE_STUB_PATH = "tests/test_precheck_slug_sibling_stub_ok.py"
LANE_STUB_TEST = ("from precheck_slug_sibling import slugify\n"
                  "\n"
                  "def test_stub_is_known_good():\n"
                  "    assert slugify('A b') == 'a-b'\n")


def _host_sandbox(worktree, argv, timeout=0):
    """Stand in for lane.sandbox_run: the same pytest invocation, host-side, no bwrap."""
    done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *argv[4:]],
                          cwd=worktree, capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(worktree),
                               "PYTHONDONTWRITEBYTECODE": "1"})
    return done.returncode, done.stdout + done.stderr


def _precheck_root_of(root):
    """Where precheck throws its fixture worktrees for this repo: beside it, never inside it."""
    return pathlib.Path(root).parent / "precheck-worktrees"


def _repo(tmp_path, monkeypatch):
    """A scratch git repo standing in for the lab. precheck and the lane both draw
    their worktree from its HEAD, so it must not carry the module under test."""
    root = tmp_path / "repo"
    (root / "run_state").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty",
                    "-m", "init"], cwd=root, check=True)
    monkeypatch.setattr(lane, "ROOT", root)

    monkeypatch.setattr(lane, "WORKTREES", tmp_path / "lane-wt")
    monkeypatch.setattr(lane, "RUN_LOG", tmp_path / "run.jsonl")
    monkeypatch.setattr(lane, "log", lambda *a, **k: None)
    monkeypatch.setattr(lane, "_paused", lambda: False)
    # The lane's single-writer lock, the mailbox path and the meta-review gate all
    # resolve through the live repo at import/call time; tests that drive run_queue
    # redirect them (a lock held by the live nara-lane timer makes run_queue
    # silently return [], which reads as "nothing to do").
    monkeypatch.setattr(lane, "_lane_lock_path", lambda: tmp_path / ".nara_lane.lock")
    (root / ".gitignore").write_text("run_state/\n")  # run_state/ is the runtime directory, not repo content
    subprocess.run(["git", "add", ".gitignore"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "ignore run_state"],
                   cwd=root, check=True)
    monkeypatch.setattr(lane.mailbox, "PATH", root / "run_state/mb.jsonl")
    # The precheck-receipt gate is what these tests are about, so no item posted
    # here may be treated as already reviewed. The live mailbox does hold old
    # reviews for old msg_ids, so a test item's id is salted per test.
    return root


def test_precheck_reports_red_when_the_tool_is_absent(tmp_path, monkeypatch):
    """(a) The item's test, prechecked with no implementation, is red, and the
    report carries that run's output so a wrong test is diagnosable. This test is
    also the red-first proof for the entry point: before this change there was no
    lane.precheck to call, so it failed with AttributeError instead of asserting
    hasattr (review claude-c0a841a1831ad8a6, finding 3)."""
    _repo(tmp_path, monkeypatch)
    report = lane.precheck(TEST_PATH, REPO_TEST, ARGV, stubs=None, sandbox=_host_sandbox)
    assert report["red_run"]["passed"] is False
    assert "No module named" in report["red_run"]["output"]
    assert report["green_run"] is None and report["green_receipt"] is None
    assert report["test_sha256"] == lane.test_sha256(REPO_TEST)


def test_precheck_against_a_correct_stub_is_green_and_receipts(tmp_path, monkeypatch):
    """(b) The same item prechecked against a stub that satisfies the test is
    green, and the green run writes a receipt bound to sha256(test_content)."""
    root = _repo(tmp_path, monkeypatch)
    report = lane.precheck(TEST_PATH, REPO_TEST, ARGV, stubs=[STUB], sandbox=_host_sandbox)
    assert report["green_run"]["passed"] is True
    sha = report["test_sha256"] == lane.test_sha256(REPO_TEST)
    receipt = lane.receipt_path(report["test_sha256"], root=root)
    assert receipt == root / "run_state/precheck_receipts" / f"{report['test_sha256']}.json"
    assert report["green_receipt"] == str(receipt) and sha
    body = json.loads(receipt.read_text())
    assert body["state"] == "green" and body["test_sha256"] == report["test_sha256"]
    assert body["test_path"] == TEST_PATH and body["stub_paths"] == sorted(STUB)


def test_run_queue_does_not_reach_the_builder_for_a_held_item(tmp_path, monkeypatch):
    """The lane's own queue holds a receipted-free item before the builder runs."""
    root = _repo(tmp_path, monkeypatch)
    (root / "config").mkdir()
    (root / "config/nara_lane.json").write_text('{"require_meta_review": false}')
    monkeypatch.setattr(lane, "meta_verdict", lambda _rows, _item: "accept")
    path = root / "run_state/mb.jsonl"
    item = post(path, LANE_TEST_PATH)
    held = lane.run_queue(path, build=_never_build, sandbox=_host_sandbox, ready=lambda: True)
    assert [(r["in_reply_to"], r["body"]["state"]) for r in held] == [(item["msg_id"], "held")]
    assert any("precheck receipt" in r for r in held[-1]["body"]["reasons"])


def test_run_queue_admits_an_item_with_a_green_precheck_receipt(tmp_path, monkeypatch):
    """The other half, with a real precheck receipt on disk: the item is claimed,
    the builder runs, and the item reaches a terminal receipt instead of being
    held for a missing receipt. The deliverable here is tests/precheck_slug_sibling.py
    (the module the acceptance test imports), so the build is in scope for the
    scratch repo, which has no tools package."""
    root = _repo(tmp_path, monkeypatch)
    (root / "config").mkdir()
    (root / "config/nara_lane.json").write_text('{"require_meta_review": false}')
    monkeypatch.setattr(lane, "meta_verdict", lambda _rows, _item: "accept")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)  # the test itself is repo content, like real main
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "add the test"],
                   cwd=root, check=True)
    lane.precheck(LANE_TEST_PATH, LANE_TEST, ["python", "-m", "pytest", "-q", LANE_TEST_PATH],
                  stubs=[LANE_STUB], sandbox=_host_sandbox)
    path = root / "run_state/mb.jsonl"
    body = _plan(LANE_TEST_PATH, LANE_TEST, allowed_write_paths=["tests/precheck_slug_sibling.py"])
    item = mailbox.post("oracle", "plan_item", body, to="nara", path=path)
    admitted = lane.run_queue(path, build=lambda *_a, **_k: dict(LANE_STUB), sandbox=_host_sandbox,
                              ready=lambda: True)
    assert [(r["in_reply_to"], r["body"]["state"]) for r in admitted] == [
        (item["msg_id"], "claimed"), (item["msg_id"], "validated")], json.dumps([r["body"] for r in admitted])
    assert admitted[-1]["body"]["branch"] == f"nara/{item['msg_id']}"
    assert lane.run_queue(path, build=lambda *_a, **_k: dict(LANE_STUB), sandbox=_host_sandbox,
                          ready=lambda: True) == []


def test_a_held_item_is_terminal_so_a_repost_carries_the_receipt(tmp_path, monkeypatch):
    """(c4) Why precheck comes before posting: a `held` receipt is terminal in the
    mailbox fold, so the pre-transaction hold costs Oracle a withdraw-and-repost -
    the same path an `amend` verdict already forces."""
    root = _repo(tmp_path, monkeypatch)
    (root / "config").mkdir()
    (root / "config/nara_lane.json").write_text('{"require_meta_review": false}')
    monkeypatch.setattr(lane, "meta_verdict", lambda _rows, _item: "accept")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)  # a posted test is repo content, like real main
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "add the test"],
                   cwd=root, check=True)
    path = root / "run_state/mb.jsonl"
    blocked = post(path, LANE_TEST_PATH)
    held = lane.run_queue(path, build=_never_build, sandbox=_host_sandbox, ready=lambda: True)
    assert mailbox_state(path, blocked["msg_id"]) == "held"  # terminal: not re-examined next pass
    lane.precheck(LANE_STUB_PATH, LANE_STUB_TEST, ["python", "-m", "pytest", "-q", LANE_STUB_PATH],
                  stubs=[LANE_STUB], sandbox=_host_sandbox)
    repost = mailbox.post("oracle", "plan_item",
                          _plan(LANE_STUB_PATH, LANE_STUB_TEST, allowed_write_paths=["tests/precheck_slug_sibling.py"]),
                          to="nara", path=path)
    admitted = lane.run_queue(path, build=lambda *_a, **_k: dict(LANE_STUB), sandbox=_host_sandbox,
                              ready=lambda: True)
    assert [(r["in_reply_to"], r["body"]["state"]) for r in admitted] == [
        (repost["msg_id"], "claimed"), (repost["msg_id"], "validated")], json.dumps([r["body"] for r in admitted])


def test_lane_holds_an_item_with_no_precheck_receipt(tmp_path, monkeypatch):
    """(c1) A plan item whose test sha has no green receipt is inadmissible."""
    _repo(tmp_path, monkeypatch)
    reasons = lane.admission({"actor": "oracle", "body": _plan()})
    assert any("precheck receipt" in r for r in reasons), reasons


def test_lane_holds_an_item_whose_receipt_is_for_a_different_sha(tmp_path, monkeypatch):
    """(c2) A receipt that exists but covers different test content is no help."""
    root = _repo(tmp_path, monkeypatch)
    other = lane.test_sha256(REPO_TEST + "# edited after precheck\n")
    lane.receipt_path(other, root=root).parent.mkdir(parents=True, exist_ok=True)
    lane.receipt_path(other, root=root).write_text(json.dumps({"test_sha256": other, "state": "green"}))
    assert any("precheck receipt" in r for r in lane.admission({"actor": "oracle", "body": _plan()}))


def test_lane_admits_the_exact_receipted_content(tmp_path, monkeypatch):
    """(c3) The other half of the sha binding: with the matching green receipt,
    admission() reports no reason at all."""
    root = _repo(tmp_path, monkeypatch)
    sha = lane.test_sha256(REPO_TEST)
    lane.receipt_path(sha, root=root).parent.mkdir(parents=True, exist_ok=True)
    lane.receipt_path(sha, root=root).write_text(json.dumps({"test_sha256": sha, "test_path": TEST_PATH,
                                                            "state": "green"}))
    assert lane.admission({"actor": "oracle", "body": _plan()}) == []


def test_precheck_is_not_green_against_a_broken_stub(tmp_path, monkeypatch):
    """(c5) A stub that does not satisfy the test leaves the item not-green: only
    a passing stub run writes a receipt."""
    root = _repo(tmp_path, monkeypatch)
    report = lane.precheck(TEST_PATH, REPO_TEST, ARGV, stubs=[BROKEN_STUB], sandbox=_host_sandbox)
    assert report["green_run"] is None and report["green_receipt"] is None
    assert report["runs"][-1]["passed"] is False and report["runs"][-1]["stub"] == sorted(BROKEN_STUB)
    assert not (root / "run_state/precheck_receipts").exists()
    assert any("precheck receipt" in r for r in lane.admission({"actor": "oracle", "body": _plan()}))


def test_precheck_refuses_a_stub_that_writes_the_acceptance_test(tmp_path, monkeypatch):
    """(e1) Review claude-c0a841a1831ad8a6, finding 1: admission() does not forbid the
    test path among a stub's paths, and precheck used to write the stub over the test, so
    a green receipt could record a test that never ran. Refused, no receipt."""
    root = _repo(tmp_path, monkeypatch)
    hijacked = {TEST_PATH: "def test_v():\n    assert True\n"}
    with pytest.raises(lane.PrecheckError, match="may not write the acceptance test"):
        lane.precheck(TEST_PATH, REPO_TEST, ARGV, stubs=[hijacked], sandbox=_host_sandbox)
    assert not (root / "run_state/precheck_receipts").exists()
    assert not _precheck_root_of(root).exists()  # refused before a fixture was drawn


def test_a_later_stub_cannot_pass_on_an_earlier_stubs_edit_to_a_tracked_file(tmp_path, monkeypatch):
    """(e2) Review claude-c0a841a1831ad8a6, finding 2: `git clean` leaves tracked
    modifications, so stub 2 used to pass on stub 1's edit and the receipt named the wrong
    known-good stub. Two stubs, one tracked file: the chain must end not-green."""
    root = _repo(tmp_path, monkeypatch)
    (root / "tools").mkdir()
    (root / "tools/__init__.py").write_text("")
    (root / "tools/value.py").write_text("VALUE = 1\n")
    for cmd in (["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "tools"]):
        subprocess.run(["git", *cmd], cwd=root, check=True)
    test = ("from tools.value import VALUE\n"
            "from tools.extra import bonus\n"  # only stub 2 supplies this
            "\ndef test_v():\n    assert VALUE == 42 and bonus() == 7\n")
    stub1 = {"tools/value.py": "VALUE = 42\n"}                           # fails: no tools.extra
    stub2 = {"tools/extra.py": "def bonus():\n    return 7\n"}          # passes only if VALUE is still 42
    report = lane.precheck(TEST_PATH, test, ARGV, stubs=[stub1, stub2], sandbox=_host_sandbox)
    assert [r["passed"] for r in report["runs"]] == [False, False, False], [
        (r["stub"], r["passed"], r["output"][-300:]) for r in report["runs"]]
    assert report["green_run"] is None and report["green_receipt"] is None
    assert not (root / "run_state/precheck_receipts").exists()


def test_two_prechecks_do_not_delete_each_others_fixtures(tmp_path, monkeypatch):
    """(e3) Review claude-57ed6698d0247f2c, amendment 2: the assertions have to observe
    the directory the run actually drew from. A fake sandbox records the fixture path it
    was given, so the test sees where the fixture really lived; at 0a2fc37 fixtures were
    created in ROOT.parent, beside the repo, and these assertions pass only after the
    mkdtemp(dir=_precheck_root()) fix."""
    root = _repo(tmp_path, monkeypatch)
    shared = lane._precheck_root()
    seen: list[pathlib.Path] = []

    def spy(worktree, argv, *, timeout=None):
        seen.append(pathlib.Path(worktree))
        return _host_sandbox(worktree, argv, timeout=timeout)

    report = lane.precheck(TEST_PATH, REPO_TEST, ARGV, stubs=[STUB], sandbox=spy)
    assert report["green_run"]["passed"] is True
    assert seen, "the sandbox never ran, so nothing was observed"
    # <root>/precheck-worktrees/precheck-<sha>-<rand>/wt  ->  the shared root
    drawn = {p.parent.parent for p in seen}
    assert drawn == {shared}, f"fixture drawn outside the shared root: {drawn}"
    stray = [p for p in root.parent.glob("precheck-*") if p != shared]
    assert not stray, f"fixture created beside the repo, not in {shared}: {stray}"
    assert not pathlib.Path(report["fixture"]).exists(), "this run's fixture was left behind"
    assert shared.exists()  # the shared root survives; only this run's directory is removed


def test_a_sibling_fixtures_directory_survives_another_runs_cleanup(tmp_path, monkeypatch):
    """The reason per-run directories matter: the finally block removes only its own.
    A planted sibling inside the shared root must still be there afterwards."""
    root = _repo(tmp_path, monkeypatch)
    shared = lane._precheck_root()
    sibling = shared / "precheck-another-run-0000" / "wt"
    sibling.mkdir(parents=True)
    report = lane.precheck(TEST_PATH, REPO_TEST, ARGV, stubs=[STUB], sandbox=_host_sandbox)
    assert report["green_run"]["passed"] is True
    assert sibling.exists(), "a finished precheck deleted a sibling's fixture directory"
    assert pathlib.Path(report["fixture"]).parent.parent == shared


def test_precheck_refuses_an_oversized_test(tmp_path, monkeypatch):
    """(d) The new entry point goes through admission()'s 8 KiB limit rather than
    reimplementing it. Stated honestly: this check is red before the change only
    in that there is no precheck to run; admission()'s size rule itself already
    passes on main, which is why it is not claimed as a red-first behaviour."""
    _repo(tmp_path, monkeypatch)
    big = REPO_TEST + "# " + "x" * lane.MAX_TEST_BYTES
    with pytest.raises(lane.PrecheckError, match="8 KiB"):
        lane.precheck(TEST_PATH, big, ARGV, stubs=[STUB], sandbox=_host_sandbox)


def test_precheck_refuses_a_non_red_first_test(tmp_path, monkeypatch):
    """A test that passes with no implementation cannot gate anything."""
    _repo(tmp_path, monkeypatch)
    trivial = "def test_always():\n    assert True\n"
    with pytest.raises(lane.PrecheckError, match="not red-first"):
        lane.precheck("tests/test_precheck_trivial.py", trivial,
                      ["python", "-m", "pytest", "-q", "tests/test_precheck_trivial.py"],
                      stubs=[STUB], sandbox=_host_sandbox)


def test_precheck_receipts_live_in_run_state_not_in_a_worktree(tmp_path, monkeypatch):
    """The receipt is host state: precheck writes it under ROOT/run_state, and its
    fixture worktree is removed afterwards, stub and all."""
    root = _repo(tmp_path, monkeypatch)
    report = lane.precheck(TEST_PATH, REPO_TEST, ARGV, stubs=[STUB], sandbox=_host_sandbox)
    assert lane.receipt_path(report["test_sha256"], root=root).is_file()
    # The directory the run actually drew from, not one that stays empty either way:
    # report["fixture"] names the worktree, its parent is this run's mkdtemp directory.
    per_run = pathlib.Path(report["fixture"]).parent
    assert per_run.parent == _precheck_root_of(root)
    assert not per_run.exists(), "the run's own fixture directory was left behind"
    assert not any(_precheck_root_of(root).iterdir()), "no per-run directory was cleaned up"
    assert not (root / "tools/precheck_slug_fixture.py").exists()  # ... and never into the repo
    stub_in_repo = root / "tools/precheck_slug_fixture.py"
    assert not stub_in_repo.exists()  # the known-good stub never lands in the repo or Nara's worktree


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap (bwrap) not installed")
def test_precheck_runs_in_the_real_sandbox(tmp_path, monkeypatch):
    """The claim is about the real sandbox, so confirm both runs through
    lane.sandbox_run: red with no tool, green with the stub, in a scratch repo."""
    root = _repo(tmp_path, monkeypatch)
    (root / "tools").mkdir()
    (root / "tools/__init__.py").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "package tools"],
                   cwd=root, check=True)
    report = lane.precheck(TEST_PATH, REPO_TEST, ARGV, stubs=[STUB])
    assert report["red_run"]["passed"] is False and report["green_run"]["passed"] is True
    written = json.loads(lane.receipt_path(report["test_sha256"], root=root).read_text())
    assert written["state"] == "green"


def _plan(test_path=TEST_PATH, test_content=REPO_TEST, **over):
    body = {
        "title": "Add a slugify helper", "objective": "Create tools/slug.py with slugify(text).",
        "task_class": "tooling", "allowed_write_paths": ["tools/slug.py"],
        "acceptance": {"test_path": test_path, "test_content": test_content,
                       "test_argv": ["python", "-m", "pytest", "-q", test_path]},
        "budget": {"attempts": 2, "wall_clock_minutes": 5},
    }
    body.update(over)
    return body


def post(path, test_path=TEST_PATH):
    content = LANE_TEST if test_path == LANE_TEST_PATH else REPO_TEST
    return mailbox.post("oracle", "plan_item", _plan(test_path, content), to="nara", path=path)


def mailbox_state(path, msg_id):
    return mailbox.fold(mailbox.read(path))[msg_id]["state"]


def _never_build(body, worktree, feedback, timeout=0):
    raise AssertionError("the builder must not run for a held item")


def _lane_builder(body, worktree, feedback, timeout=0):
    return dict(LANE_BUILDER)
