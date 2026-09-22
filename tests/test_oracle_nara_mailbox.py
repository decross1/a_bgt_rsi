"""Oracle <-> Nara mailbox and Nara's implementor lane (D-082); no model calls."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from orchestrator import nara_lane as lane
from orchestrator import oracle_mailbox as mailbox


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


def test_post_read_fold_and_chain(tmp_path):
    path = tmp_path / "mb.jsonl"
    item = mailbox.post("oracle", "plan_item", _plan(), to="nara", path=path)
    mailbox.post("nara", "receipt", {"state": "claimed"}, to="oracle", in_reply_to=item["msg_id"], path=path)
    mailbox.post("nara", "receipt", {"state": "validated", "branch": "nara/x"}, to="oracle",
                 in_reply_to=item["msg_id"], path=path)
    mailbox.post("nara", "receipt", {"state": "failed"}, to="oracle", in_reply_to=item["msg_id"], path=path)
    view = mailbox.fold(mailbox.read(path))
    assert view[item["msg_id"]]["state"] == "validated"  # terminal states stick
    lines = path.read_text().splitlines()
    tampered = json.loads(lines[1])
    tampered["body"]["state"] = "validated"
    path.write_text("\n".join([lines[0], json.dumps(tampered), *lines[2:]]) + "\n")
    with pytest.raises(mailbox.MailboxError, match="chain broken"):
        mailbox.read(path)


def test_actor_and_shape_rules(tmp_path):
    path = tmp_path / "mb.jsonl"
    with pytest.raises(mailbox.MailboxError, match="may not post"):
        mailbox.post("nara", "plan_item", _plan(), to="nara", path=path)
    with pytest.raises(mailbox.MailboxError, match="may not post"):
        mailbox.post("oracle", "receipt", {"state": "validated"}, to="nara", in_reply_to="x", path=path)
    with pytest.raises(mailbox.MailboxError, match="task_class"):
        mailbox.post("oracle", "plan_item", _plan(task_class="registration"), to="nara", path=path)
    with pytest.raises(mailbox.MailboxError, match="must reply"):
        mailbox.post("nara", "receipt", {"state": "claimed"}, to="oracle", path=path)
    with pytest.raises(mailbox.MailboxError, match="exceeds"):
        mailbox.post("oracle", "note", {"text": "x" * 20000}, to="nara", path=path)
    for actor in ("claude", "codex", "human:derrick"):
        with pytest.raises(mailbox.MailboxError, match="may not post"):
            mailbox.post(actor, "plan_item", _plan(), to="nara", path=path)  # Oracle plans
    with pytest.raises(mailbox.MailboxError, match="may not post"):
        mailbox.post("claude", "receipt", {"state": "validated"}, to="all", in_reply_to="x", path=path)
    with pytest.raises(mailbox.MailboxError, match="to must be"):
        mailbox.post("claude", "note", {"text": "hi"}, to="everyone", path=path)
    mailbox.post("claude", "note", {"text": "shared state"}, to="all", path=path)
    mailbox.post("human:derrick", "question", {"text": "status?"}, to="all", path=path)
    question = mailbox.post("nara", "question", {"text": "Which schema?"}, to="oracle", path=path)
    mailbox.post("oracle", "answer", {"text": "v2"}, to="nara", in_reply_to=question["msg_id"], path=path)


def test_admission_fence():
    assert lane.admission({"actor": "oracle", "body": _plan()}) == []
    bad = _plan(allowed_write_paths=["orchestrator/nara_lane.py", "tests/conftest.py", "docs/../CLAUDE.md",
                                     "experiments/x/PREREGISTRATION.md", "tools/*.py", "bench/flash_x.py"])
    reasons = lane.admission({"actor": "oracle", "body": bad})
    assert len([r for r in reasons if r.startswith("path outside")]) == 6
    shell = _plan(acceptance={**_plan()["acceptance"], "test_argv": ["bash", "-c", "rm -rf /"]})
    assert any("test_argv" in r for r in lane.admission({"actor": "oracle", "body": shell}))
    assert any("oracle" in r for r in lane.admission({"actor": "human:x", "body": _plan()}))
    extra = _plan(acceptance={**_plan()["acceptance"],  # the JUnit verdict must name Oracle's own module
                              "test_argv": ["python", "-m", "pytest", "-q", "tests/test_other.py", "tests/test_slug.py"]})
    assert any("no other test file" in r for r in lane.admission({"actor": "oracle", "body": extra}))


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "tools").mkdir(parents=True)
    (root / "tools/__init__.py").write_text("")
    (root / "run_state").mkdir()
    for cmd in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"]):
        subprocess.run(["git", *cmd], cwd=root, check=True)
    monkeypatch.setattr(lane, "ROOT", root)
    monkeypatch.setattr(lane, "WORKTREES", tmp_path / "wt")
    monkeypatch.setattr(lane, "RUN_LOG", tmp_path / "run.jsonl")
    return root


def _fake_sandbox(worktree, argv, timeout=0):
    done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *argv[4:]],
                          cwd=worktree, capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(worktree),
                               "PYTHONDONTWRITEBYTECODE": "1"})  # as the real sandbox sets
    return done.returncode, done.stdout + done.stderr


def _good_builder(body, worktree, feedback, timeout=0):
    return {"tools/slug.py": "def slugify(text):\n    return '-'.join(text.lower().split())\n"}


def test_lane_validates_red_first_item_on_its_own_branch(repo):
    path = repo / "run_state/mb.jsonl"
    item = mailbox.post("oracle", "plan_item", _plan(), to="nara", path=path)
    posted = lane.run_queue(path, build=_good_builder, sandbox=_fake_sandbox, ready=lambda: True)
    states = [r["body"]["state"] for r in posted]
    assert states == ["claimed", "validated"]
    final = posted[-1]["body"]
    assert final["branch"] == f"nara/{item['msg_id']}" and final["changed_files"] == ["tests/test_slug.py", "tools/slug.py"]
    log = subprocess.run(["git", "log", "--format=%an", "-1", final["branch"]], cwd=repo, capture_output=True, text=True)
    assert log.stdout.strip() == "Nara (lab lane)"
    main = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo, capture_output=True, text=True)
    assert not (repo / "tools/slug.py").exists() and main.stdout.strip() in {"master", "main"}  # never merged
    assert lane.run_queue(path, build=_good_builder, sandbox=_fake_sandbox, ready=lambda: True) == []


def test_lane_fails_scope_escape_and_test_tampering(repo):
    path = repo / "run_state/mb.jsonl"
    mailbox.post("oracle", "plan_item", _plan(), to="nara", path=path)

    def escaping(body, worktree, feedback, timeout=0):
        (worktree / "tools/extra.py").write_text("x = 1\n")  # outside allowed paths
        return _good_builder(body, worktree, feedback)

    receipt = lane.run_queue(path, build=escaping, sandbox=_fake_sandbox, ready=lambda: True)[-1]["body"]
    assert receipt["state"] == "failed" and "outside scope" in receipt["reason"]
    second = mailbox.post("oracle", "plan_item", _plan(title="again"), to="nara", path=path)

    def tamper(body, worktree, feedback, timeout=0):
        (worktree / "tests/test_slug.py").write_text("def test_slug():\n    pass\n")
        return {"tools/slug.py": "def slugify(t):\n    return t\n"}

    receipt = lane.run_queue(path, build=tamper, sandbox=_fake_sandbox, ready=lambda: True)[-1]["body"]
    assert receipt["state"] == "failed" and "modified" in receipt["reason"], second


def test_lane_holds_inadmissible_and_requires_red_first(repo):
    path = repo / "run_state/mb.jsonl"
    mailbox.post("oracle", "plan_item", _plan(allowed_write_paths=["orchestrator/x.py"]), to="nara", path=path)
    passing = _plan(acceptance={**_plan()["acceptance"], "test_content": "def test_ok():\n    assert True\n"})
    mailbox.post("oracle", "plan_item", passing, to="nara", path=path)
    posted = lane.run_queue(path, build=_good_builder, sandbox=_fake_sandbox, ready=lambda: True)
    assert posted[0]["body"]["state"] == "held"
    assert posted[-1]["body"]["state"] == "failed" and "red-first" in posted[-1]["body"]["reason"]


def test_lane_respects_pause_and_recovers_abandoned_claims(repo):
    path = repo / "run_state/mb.jsonl"
    item = mailbox.post("oracle", "plan_item", _plan(), to="nara", path=path)
    (repo / "run_state/pause_nara_lane").write_text("")
    assert lane.run_queue(path, build=_good_builder, sandbox=_fake_sandbox, ready=lambda: True) == []
    (repo / "run_state/pause_nara_lane").unlink()
    mailbox.post("nara", "receipt", {"state": "claimed"}, to="oracle", in_reply_to=item["msg_id"], path=path)
    posted = lane.run_queue(path, build=_good_builder, sandbox=_fake_sandbox, ready=lambda: True)
    assert posted[0]["body"] == {"state": "failed", "reason": "lane interrupted; item abandoned"}


def test_malformed_item_is_held_instead_of_jamming_the_queue(repo, monkeypatch):
    path = repo / "run_state/mb.jsonl"
    with pytest.raises(mailbox.MailboxError, match="budget"):
        mailbox.post("oracle", "plan_item", _plan(budget={"attempts": "2"}), to="nara", path=path)
    with pytest.raises(mailbox.MailboxError, match="strings"):
        mailbox.post("oracle", "plan_item", _plan(acceptance={**_plan()["acceptance"], "test_content": 7}),
                     to="nara", path=path)
    with monkeypatch.context() as patch:  # a row written around post()
        patch.setattr(mailbox, "validate_plan_item", lambda body: None)
        mailbox.post("oracle", "plan_item", _plan(budget={"attempts": "2"}), to="nara", path=path)
    good = mailbox.post("oracle", "plan_item", _plan(), to="nara", path=path)
    posted = lane.run_queue(path, build=_good_builder, sandbox=_fake_sandbox, ready=lambda: True)
    assert posted[0]["body"]["state"] == "held" and "malformed" in posted[0]["body"]["reasons"][0]
    assert posted[-1]["in_reply_to"] == good["msg_id"] and posted[-1]["body"]["state"] == "validated"
    assert posted[-1]["body"]["base_sha"]
    with path.open("a") as handle:
        handle.write("{torn\n")
    with pytest.raises(mailbox.MailboxError, match="not JSON"):
        mailbox.read(path)


def test_lane_never_writes_through_a_symlink(repo, tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("host file\n")
    path = repo / "run_state/mb.jsonl"
    mailbox.post("oracle", "plan_item", _plan(), to="nara", path=path)

    def planting(worktree, argv, timeout=0):  # sandboxed code swaps an allowed path for a symlink
        (worktree / "tools/slug.py").unlink(missing_ok=True)
        (worktree / "tools/slug.py").symlink_to(victim)
        return 1, "red"

    receipt = lane.run_queue(path, build=_good_builder, sandbox=planting, ready=lambda: True)[-1]["body"]
    assert receipt["state"] == "failed" and "symlink" in receipt["reason"]
    assert victim.read_text() == "host file\n"


def test_lane_refuses_a_rewritten_git_pointer(repo, tmp_path):
    marker = tmp_path / "PWNED"
    path = repo / "run_state/mb.jsonl"
    mailbox.post("oracle", "plan_item", _plan(), to="nara", path=path)

    def rewriting(worktree, argv, timeout=0):  # sandboxed code points .git at a gitdir it controls
        fake = worktree / "tools/fakegit"
        (fake / "objects").mkdir(parents=True, exist_ok=True)
        (fake / "refs").mkdir(exist_ok=True)
        (fake / "HEAD").write_text("ref: refs/heads/x\n")
        (fake / "config").write_text(f"[core]\n\tfsmonitor = touch {marker}\n")
        (worktree / ".git").write_text(f"gitdir: {fake}\n")
        return _fake_sandbox(worktree, argv, timeout)

    receipt = lane.run_queue(path, build=_good_builder, sandbox=rewriting, ready=lambda: True)[-1]["body"]
    assert receipt["state"] == "failed" and not marker.exists()


def test_real_sandbox_blocks_both_escape_routes(repo, tmp_path):
    """End to end with bubblewrap: model code tries the symlink and .git routes from inside the sandbox."""
    victim, marker = tmp_path / "victim.txt", tmp_path / "PWNED"
    victim.write_text("host file\n")
    evil = (
        "import os, pathlib\n"
        "seen = []\n"
        "here = pathlib.Path('tools')\n"
        "os.symlink(%r, 'tools/link.tmp'); os.replace('tools/link.tmp', 'tools/slug.py')\n"
        "fake = here / 'fakegit'\n"
        "(fake / 'objects').mkdir(parents=True, exist_ok=True); (fake / 'refs').mkdir(exist_ok=True)\n"
        "(fake / 'HEAD').write_text('ref: refs/heads/x\\n')\n"
        "(fake / 'config').write_text('[core]\\n\\tfsmonitor = touch %s\\n')\n"
        "for attempt in (lambda: pathlib.Path('.git').write_text('gitdir: ' + str(fake.resolve())),\n"
        "                lambda: os.replace(str(fake), '.git')):\n"
        "    try:\n        attempt(); seen.append('GIT-WRITABLE')\n"
        "    except OSError:\n        seen.append('GIT-READ-ONLY')\n"
        "def slugify(text):\n    return ' '.join(seen)\n"  # the observations land in the test output
    ) % (str(victim), str(marker))
    calls = []

    def builder(body, worktree, feedback, timeout=0):
        calls.append(feedback)
        return {"tools/slug.py": evil if len(calls) == 1 else _good_builder(body, worktree, feedback)["tools/slug.py"]}

    path = repo / "run_state/mb.jsonl"
    item = mailbox.post("oracle", "plan_item", _plan(), to="nara", path=path)
    receipt = lane.run_queue(path, build=builder, sandbox=lane.sandbox_run, ready=lambda: True)[-1]["body"]
    worktree = lane.WORKTREES / item["msg_id"]
    pointer = (worktree / ".git").read_text()
    assert "GIT-READ-ONLY GIT-READ-ONLY" in calls[1] and "GIT-WRITABLE" not in calls[1], calls[1]
    assert receipt["state"] == "failed" and "symlink" in receipt["reason"], receipt
    assert victim.read_text() == "host file\n" and not marker.exists()
    assert pointer.startswith("gitdir: ") and "fakegit" not in pointer


def test_real_sandbox_requires_a_junit_pass(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_exit.py").write_text("import os\nos._exit(0)\n")
    (tmp_path / "tests/test_ok.py").write_text("def test_ok():\n    assert True\n")
    rc, output = lane.sandbox_run(tmp_path, ["python", "-m", "pytest", "-q", "tests/test_exit.py"], timeout=120)
    assert rc != 0 and "no JUnit report" in output, output
    rc, output = lane.sandbox_run(tmp_path, ["python", "-m", "pytest", "-q", "tests/test_ok.py"], timeout=120)
    assert rc == 0 and "acceptance_passed=1" in output, output


def test_real_sandbox_isolates_network_home_and_host_writes(tmp_path):
    worktree, marker = tmp_path / "wt", tmp_path / "outside" / "sandbox-escape-marker"
    worktree.mkdir()
    code = (
        "import socket, pathlib, sys\n"
        "s = socket.socket()\n"
        "try:\n    s.connect(('127.0.0.1', 30080)); print('NET-OPEN')\n"
        "except OSError:\n    print('NET-BLOCKED')\n"
        f"print('HOME-HIDDEN' if not pathlib.Path({__file__!r}).exists() else 'HOME-VISIBLE')\n"
        "try:\n"
        f"    pathlib.Path({str(marker)!r}).parent.mkdir(parents=True, exist_ok=True)\n"
        f"    pathlib.Path({str(marker)!r}).write_text('x')\n"
        "except OSError:\n    pass\n"
        "pathlib.Path('inside.txt').write_text('ok')\n"
    )
    rc, output = lane.sandbox_run(worktree, ["python", "-c", code], timeout=60)
    assert "NET-BLOCKED" in output and "HOME-HIDDEN" in output, output
    assert not marker.exists() and (worktree / "inside.txt").read_text() == "ok"
