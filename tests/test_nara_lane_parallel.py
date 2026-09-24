"""Nara lane concurrency (2026-09-24): up to K plan items at once; no model calls.

The lane may run K items concurrently so a local server that accepts several
requests is used, with K from config/nara_lane.json (default 1, the serial
lane) and capped at the server's max_running_requests - 1. These tests pin what
must not change as K rises: each item is claimed exactly once, even by racing
runners; a worker's crash touches only its own receipt; a runner that dies
leaves claims the next run recovers exactly once; and K=1 is the serial lane.
Every builder here is a mock, and every repo, mailbox and lock is under tmp_path.
"""
from __future__ import annotations

import collections
import fcntl
import itertools
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from orchestrator import nara_lane as lane
from orchestrator import oracle_mailbox as mailbox

LANE_ROOT = Path(lane.__file__).resolve().parents[1]
GOOD = {"tools/slug.py": "def slugify(text):\n    return '-'.join(text.lower().split())\n"}


def _plan(**over):
    body = {
        "title": "Add a slugify helper", "objective": "Create tools/slug.py with slugify(text).",
        "task_class": "tooling", "allowed_write_paths": ["tools/slug.py"],
        "acceptance": {"test_path": "tests/test_slug.py",
                       "test_content": "from tools.slug import slugify\n\ndef test_slug():\n    assert slugify('A b') == 'a-b'\n",
                       "test_argv": ["python", "-m", "pytest", "-q", "tests/test_slug.py"]},
        "budget": {"attempts": 2, "wall_clock_minutes": 5},
    }
    body.update(over)
    return body


def _fake_sandbox(worktree, argv, timeout=0):
    """Host-side stand-in for lane.sandbox_run (the real sandbox is tested elsewhere)."""
    done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *argv[4:]],
                          cwd=worktree, capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(worktree), "PYTHONDONTWRITEBYTECODE": "1"})
    return done.returncode, done.stdout + done.stderr


def _deployment(root: Path, slots) -> None:
    (root / "config/model_deployment.json").write_text(json.dumps({"max_running_requests": slots}))


def _policy(root: Path, **over) -> None:
    (root / "config/nara_lane.json").write_text(json.dumps({"require_meta_review": False, **over}))


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "tools").mkdir(parents=True)
    (root / "tools/__init__.py").write_text("")
    (root / "run_state").mkdir()
    (root / "config").mkdir()
    for cmd in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"]):
        subprocess.run(["git", *cmd], cwd=root, check=True)
    _policy(root)  # gate tested in test_oracle_nara_mailbox.py; written after the commit, like the live config
    monkeypatch.setattr(lane, "ROOT", root)
    monkeypatch.setattr(lane, "WORKTREES", tmp_path / "wt")
    monkeypatch.setattr(lane, "RUN_LOG", tmp_path / "run.jsonl")
    monkeypatch.setattr(lane, "_prechecked", lambda _item: True)  # precheck gate tested in its own file
    monkeypatch.delenv(lane.CONCURRENCY_ENV, raising=False)
    return root


def _slow_builder(spans, delay=1.0):
    def build(body, worktree, feedback, timeout=0):
        start = time.monotonic()
        time.sleep(delay)
        spans[body["title"]] = (start, time.monotonic())
        return dict(GOOD)
    return build


def _by_item(receipts):
    states = collections.defaultdict(list)
    for row in receipts:
        states[row["in_reply_to"]].append(row["body"]["state"])
    return states


def _mailbox_states(path):
    return _by_item(r for r in mailbox.read(path) if r["kind"] == "receipt")


# --- configuration -----------------------------------------------------------

def test_k_defaults_to_one_and_is_capped_by_the_deployment(repo, monkeypatch):
    assert lane.lane_concurrency() == 1  # no deployment file, no config field
    _deployment(repo, 4)
    assert lane.lane_concurrency() == 1  # no config field: today's serial lane
    _policy(repo, max_concurrent_items=2)
    assert lane.lane_concurrency() == 2
    _policy(repo, max_concurrent_items=8)
    assert lane.lane_concurrency() == 3  # never every server slot
    for slots in (1, 2):
        _deployment(repo, slots)
        assert lane.lane_concurrency() == 1 and lane.lane_concurrency(5) == 1  # floor 1, never 0
    for broken in ('{"max_running_requests": true}', '{"max_running_requests": "4"}', "not json", "[]"):
        (repo / "config/model_deployment.json").write_text(broken)
        assert lane.server_slots() == 1 and lane.lane_concurrency(3) == 1
    _deployment(repo, 4)
    for bad in (0, -2, True, "3", 2.0, None):
        _policy(repo, max_concurrent_items=bad)
        assert lane.lane_concurrency() == 1, bad
    _policy(repo, max_concurrent_items=1)
    monkeypatch.setenv(lane.CONCURRENCY_ENV, "3")
    assert lane.lane_concurrency() == 3 and lane.lane_concurrency(2) == 2  # the argument wins over the env
    monkeypatch.setenv(lane.CONCURRENCY_ENV, "9")
    assert lane.lane_concurrency() == 3
    monkeypatch.setenv(lane.CONCURRENCY_ENV, "two")
    assert lane.lane_concurrency() == 1


def test_cli_passes_max_concurrent_to_the_runner(monkeypatch):
    seen = []
    monkeypatch.setattr(lane, "run_queue", lambda **kw: seen.append(kw) or [])
    assert lane.main(["run", "--max-concurrent", "2"]) == 0 and lane.main(["run"]) == 0
    assert seen == [{"max_concurrent": 2}, {"max_concurrent": None}]


def test_builder_timeout_is_1800_s_with_no_retries_and_the_wall_clock_fits_it(repo, monkeypatch):
    calls = []

    def fake_call_sync(messages, **kwargs):  # never an inference request
        calls.append(kwargs)
        return {"completion": json.dumps({"files": GOOD})}

    import agent_wrapper.wrapper as wrapper
    monkeypatch.setattr(wrapper, "call_sync", fake_call_sync)
    assert lane.builder(_plan(), repo, "") == GOOD
    assert calls[0]["request_timeout_s"] == 1800 and "max_retries" not in calls[0]
    shared_decode_build_s = lane.BUILDER_MAX_TOKENS / 15  # ~15 tok/s with the server's slots shared
    assert shared_decode_build_s < lane.BUILDER_TIMEOUT_S
    assert 2 * shared_decode_build_s + 3 * lane.TEST_TIMEOUT_S < lane.MAX_WALL_MINUTES * 60
    assert lane.admission({"actor": "oracle", "body": _plan(budget={"attempts": 3, "wall_clock_minutes": 60})}) == []
    assert lane.admission({"actor": "oracle", "body": _plan(budget={"attempts": 3, "wall_clock_minutes": 61})})
    seen = []

    def recording(body, worktree, feedback, timeout=0):
        seen.append(timeout)
        return dict(GOOD)

    path = repo / "run_state/mb.jsonl"
    mailbox.post("oracle", "plan_item", _plan(budget={"attempts": 1, "wall_clock_minutes": 60}), to="nara", path=path)
    assert lane.run_queue(path, build=recording, sandbox=_fake_sandbox, ready=lambda: True)[-1]["body"]["state"] == \
        "validated"
    assert 1700 < seen[0] <= 1800


# --- behaviour ---------------------------------------------------------------

def test_k1_is_the_serial_lane(repo, monkeypatch):
    """No pool, one item to its terminal receipt before the next is claimed."""
    _deployment(repo, 4)  # four server slots, but no max_concurrent_items: still serial
    monkeypatch.setattr(lane, "ThreadPoolExecutor", lambda **_k: pytest.fail("the serial lane uses no pool"))
    path = repo / "run_state/mb.jsonl"
    first = mailbox.post("oracle", "plan_item", _plan(title="one"), to="nara", path=path)
    second = mailbox.post("oracle", "plan_item", _plan(title="two"), to="nara", path=path)
    spans = {}
    posted = lane.run_queue(path, build=_slow_builder(spans, 0.2), sandbox=_fake_sandbox, ready=lambda: True)
    assert [(r["in_reply_to"], r["body"]["state"]) for r in posted] == [
        (first["msg_id"], "claimed"), (first["msg_id"], "validated"),
        (second["msg_id"], "claimed"), (second["msg_id"], "validated")]
    assert spans["one"][1] <= spans["two"][0]
    assert not [json.loads(line) for line in (repo.parent / "run.jsonl").read_text().splitlines()
                if json.loads(line)["task_id"] == "nara-lane:runner"]  # no concurrency log row at K=1


def test_two_items_run_concurrently_on_their_own_branches(repo):
    _deployment(repo, 4)
    _policy(repo, max_concurrent_items=2)
    path = repo / "run_state/mb.jsonl"
    items = [mailbox.post("oracle", "plan_item", _plan(title=t), to="nara", path=path) for t in ("one", "two")]
    spans = {}
    posted = lane.run_queue(path, build=_slow_builder(spans, 1.5), sandbox=_fake_sandbox, ready=lambda: True)
    (a_start, a_end), (b_start, b_end) = spans["one"], spans["two"]
    assert a_start < b_end and b_start < a_end, spans  # the two builds overlapped in time
    assert [r["seq"] for r in posted] == sorted(r["seq"] for r in posted)
    assert _by_item(posted) == {i["msg_id"]: ["claimed", "validated"] for i in items}
    finals = {r["in_reply_to"]: r["body"] for r in posted if r["body"]["state"] == "validated"}
    assert {f["branch"] for f in finals.values()} == {f"nara/{i['msg_id']}" for i in items}
    for final in finals.values():
        assert final["changed_files"] == ["tests/test_slug.py", "tools/slug.py"]
        author = subprocess.run(["git", "log", "--format=%an", "-1", final["branch"]], cwd=repo,
                                capture_output=True, text=True).stdout.strip()
        assert author == "Nara (lab lane)"
    assert not (repo / "tools/slug.py").exists()  # never merged
    assert lane.run_queue(path, build=_slow_builder({}, 0), sandbox=_fake_sandbox, ready=lambda: True) == []


def test_every_check_still_runs_per_item_under_concurrency(repo):
    """A scope escape in one concurrent item fails that item only."""
    _deployment(repo, 4)
    _policy(repo, max_concurrent_items=3)
    path = repo / "run_state/mb.jsonl"
    held = mailbox.post("oracle", "plan_item", _plan(allowed_write_paths=["orchestrator/x.py"]), to="nara", path=path)
    bad = mailbox.post("oracle", "plan_item", _plan(title="escape"), to="nara", path=path)
    good = mailbox.post("oracle", "plan_item", _plan(title="good"), to="nara", path=path)

    def build(body, worktree, feedback, timeout=0):
        time.sleep(0.5)
        if body["title"] == "escape":
            (worktree / "tools/extra.py").write_text("x = 1\n")
        return dict(GOOD)

    posted = lane.run_queue(path, build=build, sandbox=_fake_sandbox, ready=lambda: True)
    finals = {r["in_reply_to"]: r["body"] for r in posted if r["body"]["state"] != "claimed"}
    assert finals[held["msg_id"]]["state"] == "held"
    assert finals[bad["msg_id"]]["state"] == "failed" and "outside scope" in finals[bad["msg_id"]]["reason"]
    assert finals[good["msg_id"]]["state"] == "validated"


def test_racing_runners_never_double_claim(repo, monkeypatch):
    """Three runners race with the runner lock bypassed, so only the per-item
    claim locks stand between them: every item is still claimed exactly once."""
    _deployment(repo, 4)
    _policy(repo, max_concurrent_items=2)
    lock_ids = itertools.count()
    monkeypatch.setattr(lane, "_lane_lock_path", lambda: repo.parent / f"runner-{next(lock_ids)}.lock")
    path = repo / "run_state/mb.jsonl"
    items = [mailbox.post("oracle", "plan_item", _plan(title=f"item {n}"), to="nara", path=path) for n in range(4)]
    go, results = threading.Barrier(3), []

    def runner():
        go.wait()
        results.append(lane.run_queue(path, build=_slow_builder({}, 0.4), sandbox=_fake_sandbox, ready=lambda: True))

    threads = [threading.Thread(target=runner) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(120)
    assert len(results) == 3
    assert _by_item([r for rs in results for r in rs]) == {i["msg_id"]: ["claimed", "validated"] for i in items}
    assert _mailbox_states(path) == {i["msg_id"]: ["claimed", "validated"] for i in items}


_CHILD = r"""
import json, os, sys, time
from pathlib import Path
cfg = json.loads(sys.argv[1])
sys.path.insert(0, cfg["lane_root"])
from orchestrator import nara_lane as lane
lane.ROOT = Path(cfg["root"])
lane.WORKTREES = Path(cfg["worktrees"])
lane.RUN_LOG = Path(cfg["run_log"])
lane._prechecked = lambda _item: True
lane._lane_lock_path = lambda: Path(cfg["runner_lock"])
sys.path.insert(0, cfg["tests_dir"])
from test_nara_lane_parallel import GOOD, _fake_sandbox

def build(body, worktree, feedback, timeout=0):
    Path(cfg["marks"], body["title"]).write_text("")
    if cfg.get("die_on") == body["title"]:
        while len(os.listdir(cfg["marks"])) < cfg["wait_for"]:
            time.sleep(0.05)
        os._exit(17)  # the whole runner dies with another item in flight
    time.sleep(cfg["delay"])
    return dict(GOOD)

while not Path(cfg["go"]).exists():
    time.sleep(0.01)
posted = lane.run_queue(Path(cfg["mailbox"]), build=build, sandbox=_fake_sandbox, ready=lambda: True,
                        max_concurrent=cfg["k"])
print(json.dumps(posted))
"""


def _spawn(repo, name, **cfg):
    tmp = repo.parent
    (tmp / "marks").mkdir(exist_ok=True)
    cfg = {"lane_root": str(LANE_ROOT), "root": str(repo), "worktrees": str(lane.WORKTREES),
           "run_log": str(tmp / f"{name}.jsonl"), "runner_lock": str(tmp / f"{name}.lock"),
           "tests_dir": str(Path(__file__).parent), "marks": str(tmp / "marks"), "go": str(tmp / "go"),
           "mailbox": str(repo / "run_state/mb.jsonl"), "delay": 0.4, "k": 2, **cfg}
    env = {**os.environ, "MOCK_LLM": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop(lane.CONCURRENCY_ENV, None)
    return subprocess.Popen([sys.executable, "-c", _CHILD, json.dumps(cfg)], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, env=env, cwd=str(repo.parent))


def test_racing_runner_processes_never_double_claim(repo):
    """The same race across processes, each with its own runner lock."""
    _deployment(repo, 4)
    path = repo / "run_state/mb.jsonl"
    items = [mailbox.post("oracle", "plan_item", _plan(title=f"item {n}"), to="nara", path=path) for n in range(4)]
    children = [_spawn(repo, f"runner{n}") for n in range(3)]
    (repo.parent / "go").write_text("")
    outputs = [child.communicate(timeout=180) for child in children]
    assert all(child.returncode == 0 for child in children), [err[-2000:] for _out, err in outputs]
    posted = [r for out, _err in outputs for r in json.loads(out.strip().splitlines()[-1])]
    assert _by_item(posted) == {i["msg_id"]: ["claimed", "validated"] for i in items}
    assert _mailbox_states(path) == {i["msg_id"]: ["claimed", "validated"] for i in items}


class _Boom(BaseException):
    """Not an Exception, so implement() does not turn it into a failed receipt itself."""


def test_a_crashed_worker_fails_its_own_item_only(repo):
    _deployment(repo, 4)
    _policy(repo, max_concurrent_items=2)
    path = repo / "run_state/mb.jsonl"
    doomed = mailbox.post("oracle", "plan_item", _plan(title="doomed"), to="nara", path=path)
    fine = mailbox.post("oracle", "plan_item", _plan(title="fine"), to="nara", path=path)
    started = threading.Event()

    def build(body, worktree, feedback, timeout=0):
        if body["title"] == "doomed":
            assert started.wait(30)
            raise _Boom("worker died")
        started.set()
        time.sleep(1.0)
        return dict(GOOD)

    posted = lane.run_queue(path, build=build, sandbox=_fake_sandbox, ready=lambda: True)
    assert _by_item(posted) == {doomed["msg_id"]: ["claimed", "failed"], fine["msg_id"]: ["claimed", "validated"]}
    assert _mailbox_states(path) == _by_item(posted)
    reason = next(r["body"]["reason"] for r in posted if r["body"]["state"] == "failed")
    assert "lane worker crashed: _Boom" in reason
    assert lane.run_queue(path, build=build, sandbox=_fake_sandbox, ready=lambda: True) == []


def test_a_dead_runner_leaves_claims_recovered_exactly_once(repo, monkeypatch):
    """A runner process dies with two items in flight: the next run posts one
    abandoned receipt for each, and a third run posts nothing."""
    _deployment(repo, 4)
    path = repo / "run_state/mb.jsonl"
    items = [mailbox.post("oracle", "plan_item", _plan(title=t), to="nara", path=path) for t in ("dies", "flies")]
    child = _spawn(repo, "doomed", die_on="dies", wait_for=2, delay=30)
    (repo.parent / "go").write_text("")
    _out, err = child.communicate(timeout=120)
    assert child.returncode == 17, err[-2000:]
    assert _mailbox_states(path) == {i["msg_id"]: ["claimed"] for i in items}
    monkeypatch.setattr(lane, "_lane_lock_path", lambda: repo.parent / "next.lock")
    recovered = lane.run_queue(path, build=_slow_builder({}, 0), sandbox=_fake_sandbox, ready=lambda: True)
    assert _by_item(recovered) == {i["msg_id"]: ["failed"] for i in items}
    assert all(r["body"]["reason"] == "lane interrupted; item abandoned" for r in recovered)
    assert lane.run_queue(path, build=_slow_builder({}, 0), sandbox=_fake_sandbox, ready=lambda: True) == []
    assert _mailbox_states(path) == {i["msg_id"]: ["claimed", "failed"] for i in items}


def test_a_held_claim_lock_means_in_progress_not_abandoned(repo):
    path = repo / "run_state/mb.jsonl"
    item = mailbox.post("oracle", "plan_item", _plan(), to="nara", path=path)
    mailbox.post("nara", "receipt", {"state": "claimed"}, to="oracle", in_reply_to=item["msg_id"], path=path)
    lock_path = lane._claim_lock_path(item["msg_id"])
    assert lock_path.parent == repo / "run_state/nara_lane_claims" and item["msg_id"] not in lock_path.name
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as held:  # another live runner is working on it
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert lane.run_queue(path, build=_slow_builder({}, 0), sandbox=_fake_sandbox, ready=lambda: True) == []
    posted = lane.run_queue(path, build=_slow_builder({}, 0), sandbox=_fake_sandbox, ready=lambda: True)
    assert [r["body"] for r in posted] == [{"state": "failed", "reason": "lane interrupted; item abandoned"}]


def test_an_item_withdrawn_after_the_fold_is_not_claimed(repo, monkeypatch):
    """The claim re-reads the mailbox under the item's lock, so a withdraw that
    lands after the runner's first read is honoured instead of claimed over."""
    path = repo / "run_state/mb.jsonl"
    item = mailbox.post("oracle", "plan_item", _plan(), to="nara", path=path)
    real_ready = lambda: mailbox.post("oracle", "withdraw", {}, to="nara", in_reply_to=item["msg_id"],
                                      path=path) is not None
    assert lane.run_queue(path, build=lambda *a, **k: pytest.fail("never built"), sandbox=_fake_sandbox,
                          ready=real_ready) == []
    assert mailbox.fold(mailbox.read(path))[item["msg_id"]]["state"] == "withdrawn"


def test_pause_stops_new_claims_while_workers_finish(repo):
    _deployment(repo, 4)
    _policy(repo, max_concurrent_items=2)
    path = repo / "run_state/mb.jsonl"
    items = [mailbox.post("oracle", "plan_item", _plan(title=f"item {n}"), to="nara", path=path) for n in range(3)]

    both_started = threading.Barrier(2)

    def build(body, worktree, feedback, timeout=0):
        both_started.wait(30)
        (repo / "run_state/pause_nara_lane").write_text("")  # paused while two items are in flight
        time.sleep(0.5)
        return dict(GOOD)

    posted = lane.run_queue(path, build=build, sandbox=_fake_sandbox, ready=lambda: True)
    assert _by_item(posted) == {i["msg_id"]: ["claimed", "validated"] for i in items[:2]}
    assert mailbox.fold(mailbox.read(path))[items[2]["msg_id"]]["state"] == "open"
