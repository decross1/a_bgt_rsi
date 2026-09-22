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


def _good_builder(body, worktree, feedback):
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

    def escaping(body, worktree, feedback):
        (worktree / "tools/extra.py").write_text("x = 1\n")  # outside allowed paths
        return _good_builder(body, worktree, feedback)

    receipt = lane.run_queue(path, build=escaping, sandbox=_fake_sandbox, ready=lambda: True)[-1]["body"]
    assert receipt["state"] == "failed" and "outside scope" in receipt["reason"]
    second = mailbox.post("oracle", "plan_item", _plan(title="again"), to="nara", path=path)

    def tamper(body, worktree, feedback):
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


@pytest.mark.skipif(not Path("/usr/bin/bwrap").exists(), reason="bubblewrap unavailable")
def test_real_sandbox_isolates_network_home_and_host_writes(tmp_path):
    marker = lane.ROOT / "run_state" / "sandbox-escape-marker"
    code = (
        "import socket, pathlib, sys\n"
        "s = socket.socket()\n"
        "try:\n    s.connect(('127.0.0.1', 30080)); print('NET-OPEN')\n"
        "except OSError:\n    print('NET-BLOCKED')\n"
        "print('HOME-HIDDEN' if not pathlib.Path('/home/decross1/.codex').exists() else 'HOME-VISIBLE')\n"
        f"pathlib.Path({str(marker)!r}).parent.mkdir(parents=True, exist_ok=True)\n"
        f"pathlib.Path({str(marker)!r}).write_text('x')\n"
        "pathlib.Path('inside.txt').write_text('ok')\n"
    )
    rc, output = lane.sandbox_run(tmp_path, ["python", "-c", code], timeout=60)
    assert "NET-BLOCKED" in output and "HOME-HIDDEN" in output, output
    assert not marker.exists() and (tmp_path / "inside.txt").read_text() == "ok"
