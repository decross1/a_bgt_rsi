#!/usr/bin/env python3
"""Fixture tests for tools/qwen_builder.sh (the packet dispatcher's Qwen
agent_cmd).

Hermetic by construction. The injection seam is **QWEN_ENDPOINT**: the script
POSTs to whatever URL that env names, so every test points it at a canned
`http.server` running on 127.0.0.1:<ephemeral> inside the test process. Real
curl and real JSON parsing are exercised; the real :8001 is never contacted
(the runner env is stripped of QWEN_*/PKT_* before each run, so a leaked shell
variable cannot redirect a test at the live model either).

Each test builds a throwaway git repo in tmp_path: an in-scope worker, an
out-of-scope acceptance test, and a test_cmd that decides on file content
alone (no pytest-inside-pytest, no imports).

Run:
    MOCK_LLM=1 .venv-chroma/bin/python -m pytest tests/test_qwen_builder.py -q
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "qwen_builder.sh"

_GIT_ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_AUTHOR_NAME": "fixture",
    "GIT_AUTHOR_EMAIL": "fixture@test.invalid",
    "GIT_COMMITTER_NAME": "fixture",
    "GIT_COMMITTER_EMAIL": "fixture@test.invalid",
}

GOOD_PLAN = json.dumps([
    {"path": "workers/thing.py", "content": "def thing():\n    return 42\n"},
])


# --------------------------------------------------------------------------
# canned model server (the QWEN_ENDPOINT seam)
# --------------------------------------------------------------------------
class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 (http.server API)
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.server.requests.append(json.loads(body))
        idx = len(self.server.requests) - 1
        if idx >= len(self.server.replies):
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b'{"error": "no canned reply left"}')
            return
        payload = json.dumps({
            "id": "fake", "object": "chat.completion", "model": "fake-qwen",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant",
                                     "content": self.server.replies[idx]}}],
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):  # keep pytest output clean
        pass


@pytest.fixture
def qwen():
    """Canned model server. Set `qwen.replies` to the assistant contents to
    hand back, in order; read `qwen.requests` for what the script sent."""
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    srv.replies, srv.requests = [], []
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    srv.url = f"http://127.0.0.1:{srv.server_address[1]}/v1/chat/completions"
    yield srv
    srv.shutdown()
    srv.server_close()


# --------------------------------------------------------------------------
# repo fixture + runner
# --------------------------------------------------------------------------
def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, env={**os.environ, **_GIT_ENV},
                          check=True, capture_output=True, text=True).stdout


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "worktree-pkt-PKT-T1"
    (repo / "workers").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "workers" / "thing.py").write_text("def thing():\n    return 0\n")
    # Acceptance test: OUT of scope on purpose -- the builder must not be able
    # to make it pass by editing it.
    (repo / "tests" / "test_thing.py").write_text(
        "import sys\n"
        "sys.exit(0 if 'return 42' in open('workers/thing.py').read() else 1)\n"
    )
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "seed")
    return repo


def run_builder(repo: Path, qwen, **over) -> subprocess.CompletedProcess:
    """Invoke the script the way the dispatcher does (cwd = worktree)."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("QWEN_", "PKT_"))}
    env.update(_GIT_ENV)
    env.update({
        "QWEN_ENDPOINT": qwen.url,
        "QWEN_MODEL": "fake-qwen",
        "QWEN_TIMEOUT_SEC": "30",
        "PKT_TASK_ID": "PKT-T1",
        "PKT_OBJECTIVE": "make thing() return 42",
        "PKT_FILES_IN_SCOPE": json.dumps(["workers/thing.py"]),
        "PKT_FILES_OUT_OF_SCOPE": json.dumps(["orchestrator/nara.py", "run_state/"]),
        "PKT_FORBIDDEN_ACTIONS": json.dumps(["git push", "edit the acceptance test"]),
        "PKT_TEST_CMD": "python3 tests/test_thing.py",
    })
    for k, v in over.items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v
    return subprocess.run(["bash", str(SCRIPT)], cwd=repo, env=env,
                          capture_output=True, text=True, timeout=120)


def _log_count(repo: Path) -> int:
    return len(_git(repo, "log", "--format=%H").splitlines())


def _prompt(qwen, idx: int = 0) -> str:
    return qwen.requests[idx]["messages"][-1]["content"]


# --------------------------------------------------------------------------
# 1. env contract -- fail loudly, never guess
# --------------------------------------------------------------------------
@pytest.mark.parametrize("missing",
                         ["PKT_TASK_ID", "PKT_OBJECTIVE", "PKT_FILES_IN_SCOPE"])
def test_missing_required_env_fails_loudly(tmp_path, qwen, missing):
    repo = make_repo(tmp_path)
    qwen.replies = [GOOD_PLAN]
    r = run_builder(repo, qwen, **{missing: None})
    assert r.returncode != 0
    assert missing in r.stderr and "FATAL" in r.stderr
    assert qwen.requests == [], "must not call the model without its bounds"
    assert _log_count(repo) == 1


def test_empty_required_env_is_also_missing(tmp_path, qwen):
    repo = make_repo(tmp_path)
    qwen.replies = [GOOD_PLAN]
    r = run_builder(repo, qwen, PKT_OBJECTIVE="")
    assert r.returncode != 0
    assert "PKT_OBJECTIVE" in r.stderr


def test_non_git_cwd_fails(tmp_path, qwen):
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    qwen.replies = [GOOD_PLAN]
    r = run_builder(plain, qwen)
    assert r.returncode != 0
    assert "not a git work tree" in r.stderr
    assert qwen.requests == []


# --------------------------------------------------------------------------
# 2. prompt contract
# --------------------------------------------------------------------------
def test_prompt_carries_objective_scope_test_and_output_contract(tmp_path, qwen):
    repo = make_repo(tmp_path)
    qwen.replies = [GOOD_PLAN]
    r = run_builder(repo, qwen)
    assert r.returncode == 0, r.stdout + r.stderr
    body = qwen.requests[0]
    assert body["model"] == "fake-qwen"
    assert body["temperature"] == 0.2
    p = _prompt(qwen)
    assert "make thing() return 42" in p                  # objective
    assert "workers/thing.py" in p and "return 0" in p    # in-scope + contents
    assert "sys.exit(0 if 'return 42'" in p               # acceptance test body
    assert "python3 tests/test_thing.py" in p             # exact test_cmd
    assert "orchestrator/nara.py" in p                    # out of scope
    assert "git push" in p                                # forbidden actions
    assert "JSON array" in p and "full-file" in p.lower()  # output contract


def test_prompt_truncates_over_the_char_cap(tmp_path, qwen):
    repo = make_repo(tmp_path)
    (repo / "workers" / "thing.py").write_text("# pad\n" + "x = 1\n" * 5000)
    _git(repo, "commit", "-aqm", "big file")
    qwen.replies = [GOOD_PLAN]
    r = run_builder(repo, qwen, QWEN_PROMPT_CHAR_CAP="500")
    assert r.returncode == 0, r.stdout + r.stderr
    p = _prompt(qwen)
    assert "TRUNCATED" in p
    assert len(p) < 6000


def test_absolute_interpreter_in_test_cmd_is_not_slurped_as_a_reference(
        tmp_path, qwen):
    """An emitted packet's test_cmd names an ABSOLUTE interpreter, which is a
    real file; reading that binary in would burn the whole prompt budget."""
    repo = make_repo(tmp_path)
    interp = tmp_path / "fake_python"
    interp.write_bytes(b"\x7fELF" + b"\x00" * 4000)
    qwen.replies = [GOOD_PLAN]
    r = run_builder(repo, qwen,
                    PKT_TEST_CMD=f"MOCK_LLM=1 {interp} -m pytest "
                                 "tests/test_thing.py -x -q")
    # the fake interpreter cannot run, but the advisory result decides nothing
    assert r.returncode == 0, r.stdout + r.stderr
    assert "selftest rc=126" in r.stdout
    assert _log_count(repo) == 2, "a red advisory run still commits"
    p = _prompt(qwen)
    assert "ELF" not in p and str(interp) not in p.split("TEST COMMAND")[0]
    assert "sys.exit(0 if 'return 42'" in p, "the real test file is still shown"


def test_test_cmd_resolved_from_packet_file_when_env_absent(tmp_path, qwen):
    repo = make_repo(tmp_path)
    (repo / "tasks" / "packets").mkdir(parents=True)
    (repo / "tasks" / "packets" / "PKT-T1.json").write_text(json.dumps({
        "task_id": "PKT-T1",
        "acceptance_criteria": {"test_cmd": "python3 tests/test_thing.py",
                                "must_fail_before": True},
    }))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "packet")
    qwen.replies = [GOOD_PLAN]
    r = run_builder(repo, qwen, PKT_TEST_CMD=None)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "resolved from tasks/packets/PKT-T1.json" in r.stdout
    assert "python3 tests/test_thing.py" in _prompt(qwen)


def test_absent_test_cmd_is_loud_but_not_fatal(tmp_path, qwen):
    repo = make_repo(tmp_path)
    qwen.replies = [GOOD_PLAN]
    r = run_builder(repo, qwen, PKT_TEST_CMD=None)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "WARNING" in r.stdout and "advisory run is SKIPPED" in r.stdout
    assert _log_count(repo) == 2, "still commits -- the dispatcher decides done"


# --------------------------------------------------------------------------
# 3. happy path -- writes AND commits
# --------------------------------------------------------------------------
def test_happy_path_writes_and_commits(tmp_path, qwen):
    repo = make_repo(tmp_path)
    qwen.replies = [GOOD_PLAN]
    r = run_builder(repo, qwen)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (repo / "workers" / "thing.py").read_text() == "def thing():\n    return 42\n"
    assert _git(repo, "status", "--porcelain").strip() == "", "tree must be clean"
    assert _log_count(repo) == 2
    # the runner env carries a human GIT_AUTHOR_NAME; the builder must still
    # attribute the commit to itself (provenance: a model wrote this)
    assert _git(repo, "log", "-1", "--format=%an").strip() == "qwen-builder"
    assert _git(repo, "log", "-1", "--format=%ae").strip() == \
        "qwen-builder@a-bgt-rsi.local"
    assert "PKT-T1" in _git(repo, "log", "-1", "--format=%B")
    assert "selftest rc=0" in r.stdout            # advisory run went green
    assert "dispatcher decides done" in r.stdout


def test_fenced_json_reply_is_accepted(tmp_path, qwen):
    repo = make_repo(tmp_path)
    qwen.replies = ["```json\n" + GOOD_PLAN + "\n```"]
    r = run_builder(repo, qwen)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _log_count(repo) == 2


def test_new_file_in_scope_is_created(tmp_path, qwen):
    repo = make_repo(tmp_path)
    plan = json.dumps([{"path": "workers/new_mod.py", "content": "V = 1\n"}])
    qwen.replies = [plan]
    r = run_builder(repo, qwen,
                    PKT_FILES_IN_SCOPE=json.dumps(["workers/new_mod.py"]),
                    PKT_TEST_CMD="test -f workers/new_mod.py")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (repo / "workers" / "new_mod.py").read_text() == "V = 1\n"
    assert _git(repo, "status", "--porcelain").strip() == ""


# --------------------------------------------------------------------------
# 4. the scope fence (enforced here, not only by premerge)
# --------------------------------------------------------------------------
def test_out_of_scope_path_is_refused_and_nothing_is_written(tmp_path, qwen):
    repo = make_repo(tmp_path)
    qwen.replies = [json.dumps([
        {"path": "workers/thing.py", "content": "def thing():\n    return 42\n"},
        {"path": "orchestrator/nara.py", "content": "SPINE = False\n"},
    ])]
    r = run_builder(repo, qwen)
    assert r.returncode != 0
    assert "REFUSED" in r.stderr and "orchestrator/nara.py" in r.stderr
    assert not (repo / "orchestrator").exists()
    # all-or-nothing: the in-scope sibling write is not applied either
    assert (repo / "workers" / "thing.py").read_text() == "def thing():\n    return 0\n"
    assert _log_count(repo) == 1
    assert len(qwen.requests) == 1, "a scope refusal is terminal, not retried"


@pytest.mark.parametrize("bad_path", ["/etc/passwd", "../escape.py",
                                      "workers/../../oops.py"])
def test_escaping_paths_are_refused(tmp_path, qwen, bad_path):
    repo = make_repo(tmp_path)
    qwen.replies = [json.dumps([{"path": bad_path, "content": "x = 1\n"}])]
    r = run_builder(repo, qwen)
    assert r.returncode != 0
    assert "REFUSED" in r.stderr
    assert _log_count(repo) == 1


def test_directory_scope_entry_allows_paths_beneath_it(tmp_path, qwen):
    repo = make_repo(tmp_path)
    qwen.replies = [GOOD_PLAN]
    r = run_builder(repo, qwen, PKT_FILES_IN_SCOPE=json.dumps(["workers/"]))
    assert r.returncode == 0, r.stdout + r.stderr
    assert _log_count(repo) == 2


# --------------------------------------------------------------------------
# 5. unparseable replies -- exactly one retry
# --------------------------------------------------------------------------
def test_unparseable_reply_retries_once_then_gives_up(tmp_path, qwen):
    repo = make_repo(tmp_path)
    qwen.replies = ["Sure! I'd start by refactoring the module...",
                    "Here is a diff instead:\n--- a/workers/thing.py"]
    r = run_builder(repo, qwen)
    assert r.returncode != 0
    assert len(qwen.requests) == 2, "exactly one retry"
    assert "not the required JSON array" in _prompt(qwen, 1)
    assert "unparseable after the retry" in r.stderr
    assert _log_count(repo) == 1


def test_retry_succeeds_after_a_bad_first_reply(tmp_path, qwen):
    repo = make_repo(tmp_path)
    qwen.replies = ["I cannot comply as JSON.", GOOD_PLAN]
    r = run_builder(repo, qwen)
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(qwen.requests) == 2
    assert "ONE retry" in r.stdout
    assert _log_count(repo) == 2


def test_wrong_element_shape_is_treated_as_unparseable(tmp_path, qwen):
    repo = make_repo(tmp_path)
    qwen.replies = [json.dumps([{"file": "workers/thing.py", "body": "x"}]),
                    json.dumps(["workers/thing.py"])]
    r = run_builder(repo, qwen)
    assert r.returncode != 0
    assert len(qwen.requests) == 2
    assert _log_count(repo) == 1


# --------------------------------------------------------------------------
# 6. no-progress and transport failures
# --------------------------------------------------------------------------
def test_empty_plan_is_a_failure(tmp_path, qwen):
    repo = make_repo(tmp_path)
    qwen.replies = ["[]"]
    r = run_builder(repo, qwen)
    assert r.returncode != 0
    assert "empty write plan" in r.stderr
    assert _log_count(repo) == 1
    assert len(qwen.requests) == 1


def test_identical_content_leaves_nothing_to_commit(tmp_path, qwen):
    repo = make_repo(tmp_path)
    qwen.replies = [json.dumps([{"path": "workers/thing.py",
                                 "content": "def thing():\n    return 0\n"}])]
    r = run_builder(repo, qwen)
    assert r.returncode != 0
    assert "nothing to commit" in r.stderr
    assert _log_count(repo) == 1


def test_http_error_fails_loudly(tmp_path, qwen):
    repo = make_repo(tmp_path)
    qwen.replies = []          # server answers 500
    r = run_builder(repo, qwen)
    assert r.returncode != 0
    assert "HTTP 500" in r.stderr
    assert _log_count(repo) == 1


def test_unreachable_endpoint_fails_loudly(tmp_path, qwen):
    repo = make_repo(tmp_path)
    r = run_builder(repo, qwen,
                    QWEN_ENDPOINT="http://127.0.0.1:1/v1/chat/completions")
    assert r.returncode != 0
    assert "curl failed" in r.stderr
    assert _log_count(repo) == 1


def test_dirty_tree_after_commit_is_warned_about(tmp_path, qwen):
    """The advisory run can leave artifacts; a dirty tree is scored `failed`
    by the dispatcher, so the builder says so rather than exiting quietly."""
    repo = make_repo(tmp_path)
    qwen.replies = [GOOD_PLAN]
    r = run_builder(repo, qwen, PKT_TEST_CMD="touch stray_artifact.txt")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "tree is NOT clean after commit" in r.stdout
    assert "stray_artifact.txt" in r.stdout


def test_defaults_fit_the_served_context_window():
    """vllm-qwen runs --max-model-len 16384 and vLLM returns HTTP 400 rather
    than clamping (probed 2026-08-15), so prompt cap + completion must fit."""
    src = SCRIPT.read_text()
    cap = int(re.search(r'QWEN_PROMPT_CHAR_CAP:-(\d+)', src).group(1))
    max_tokens = int(re.search(r'QWEN_MAX_TOKENS:-(\d+)', src).group(1))
    worst_case_prompt_tokens = cap / 2.5      # dense code, not prose
    assert worst_case_prompt_tokens + max_tokens < 16384


def test_builder_log_env_captures_the_phase_log(tmp_path, qwen):
    repo = make_repo(tmp_path)
    logfile = tmp_path / "builder.log"
    qwen.replies = [GOOD_PLAN]
    r = run_builder(repo, qwen, QWEN_BUILDER_LOG=str(logfile))
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout == ""      # redirected away from the dispatcher's dropped pipe
    assert "phase=commit" in logfile.read_text()
