#!/usr/bin/env python3
"""
Fixture tests for tools/premerge_check.sh (LOOP_V1 packet pre-merge gate).

Each test builds a synthetic git repo in tmp_path (init, seed commit on
main, feature branch), makes a clean or violating diff, and asserts the
script's exit code and that the violated rule is NAMED in its output.
Hermetic: no network, no LLM, no dependence on the real repo's git state
or the user's global git config.

Run:
    MOCK_LLM=1 .venv-chroma/bin/python -m pytest tests/test_premerge_check.py -x -q
"""
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "premerge_check.sh"

_GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_AUTHOR_NAME": "fixture",
    "GIT_AUTHOR_EMAIL": "fixture@test.invalid",
    "GIT_COMMITTER_NAME": "fixture",
    "GIT_COMMITTER_EMAIL": "fixture@test.invalid",
}


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, env=_GIT_ENV, check=True,
                   capture_output=True, text=True)


def _write(repo, rel, content):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def _commit_all(repo, msg):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", msg)


def make_repo(tmp_path):
    """Seed repo on main with protected + ordinary files, then branch."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _write(repo, "orchestrator/nara.py", "SPINE = True\n")
    _write(repo, "workers/foo.py", "def foo():\n    return 1\n")
    _write(repo, "tests/test_foo.py",
           "def test_foo():\n    assert True\n")
    _write(repo, "ui/app.py", "APP = 'ui'\n")
    _write(repo, "PINS.md", "vLLM image: vllm/vllm-openai:v0.21.0\n")
    _commit_all(repo, "seed")
    _git(repo, "checkout", "-b", "feature")
    return repo


def check(repo, base="main", max_lines=None):
    cmd = [str(SCRIPT), base]
    if max_lines is not None:
        cmd.append(str(max_lines))
    return subprocess.run(cmd, cwd=repo, env=_GIT_ENV,
                          capture_output=True, text=True)


def test_clean_diff_passes(tmp_path):
    repo = make_repo(tmp_path)
    _write(repo, "workers/bar.py", "def bar():\n    return 2\n")
    _commit_all(repo, "add worker")
    r = check(repo)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK" in r.stdout


def test_empty_diff_passes(tmp_path):
    repo = make_repo(tmp_path)
    r = check(repo)
    assert r.returncode == 0
    assert "OK" in r.stdout


def test_protected_spine_file_fails(tmp_path):
    repo = make_repo(tmp_path)
    _write(repo, "orchestrator/nara.py", "SPINE = False\n")
    _commit_all(repo, "touch spine")
    r = check(repo)
    assert r.returncode == 1
    assert "protected-path" in r.stdout
    assert "orchestrator/nara.py" in r.stdout


def test_protected_run_state_dir_fails(tmp_path):
    repo = make_repo(tmp_path)
    _write(repo, "run_state/x.json", "{}\n")
    _commit_all(repo, "touch run_state")
    r = check(repo)
    assert r.returncode == 1
    assert "protected-path" in r.stdout
    assert "run_state/x.json" in r.stdout


def test_protected_claude_md_fails(tmp_path):
    repo = make_repo(tmp_path)
    _write(repo, "CLAUDE.md", "new contract\n")
    _commit_all(repo, "touch CLAUDE.md")
    r = check(repo)
    assert r.returncode == 1
    assert "protected-path" in r.stdout


def test_ui_allowed_without_ui_session_worktree(tmp_path):
    repo = make_repo(tmp_path)
    _write(repo, "ui/app.py", "APP = 'ui2'\n")
    _commit_all(repo, "touch ui")
    r = check(repo)
    assert r.returncode == 0, r.stdout + r.stderr


def test_ui_blocked_when_ui_session_worktree_live(tmp_path):
    repo = make_repo(tmp_path)
    _git(repo, "worktree", "add", "-b", "ui-session",
         str(tmp_path / "ui-session"), "main")
    _write(repo, "ui/app.py", "APP = 'ui2'\n")
    _commit_all(repo, "touch ui")
    r = check(repo)
    assert r.returncode == 1
    assert "protected-path" in r.stdout
    assert "ui/app.py" in r.stdout


def test_version_pin_modification_fails(tmp_path):
    repo = make_repo(tmp_path)
    _write(repo, "PINS.md", "vLLM image: vllm/vllm-openai:v0.20.0\n")
    _commit_all(repo, "downgrade pin")
    r = check(repo)
    assert r.returncode == 1
    assert "version-pin" in r.stdout
    assert "v0.21.0" in r.stdout


def test_version_pin_added_elsewhere_fails(tmp_path):
    repo = make_repo(tmp_path)
    _write(repo, "workers/bar.py", "MODEL = 'gemma-4-26b-a4b-nvfp4'\n")
    _commit_all(repo, "hardcode weights path")
    r = check(repo)
    assert r.returncode == 1
    assert "version-pin" in r.stdout


def test_deleted_test_fails(tmp_path):
    repo = make_repo(tmp_path)
    _git(repo, "rm", "-q", "tests/test_foo.py")
    _git(repo, "commit", "-m", "delete test")
    r = check(repo)
    assert r.returncode == 1
    assert "test-removal" in r.stdout
    assert "tests/test_foo.py" in r.stdout


def test_renamed_test_fails(tmp_path):
    repo = make_repo(tmp_path)
    _git(repo, "mv", "tests/test_foo.py", "tests/test_bar.py")
    _git(repo, "commit", "-m", "rename test")
    r = check(repo)
    assert r.returncode == 1
    assert "test-removal" in r.stdout


def test_added_skip_marker_fails(tmp_path):
    repo = make_repo(tmp_path)
    _write(repo, "tests/test_foo.py",
           "import pytest\n\n"
           "@pytest.mark.skip(reason='later')\n"
           "def test_foo():\n    assert True\n")
    _commit_all(repo, "skip test")
    r = check(repo)
    assert r.returncode == 1
    assert "test-skip" in r.stdout


def test_added_xfail_marker_fails(tmp_path):
    repo = make_repo(tmp_path)
    _write(repo, "tests/test_foo.py",
           "import pytest\n\n"
           "@pytest.mark.xfail\n"
           "def test_foo():\n    assert True\n")
    _commit_all(repo, "xfail test")
    r = check(repo)
    assert r.returncode == 1
    assert "test-skip" in r.stdout


def test_added_pytest_skip_call_fails(tmp_path):
    repo = make_repo(tmp_path)
    _write(repo, "tests/test_foo.py",
           "import pytest\n\n"
           "def test_foo():\n    pytest.skip('nope')\n")
    _commit_all(repo, "runtime skip")
    r = check(repo)
    assert r.returncode == 1
    assert "test-skip" in r.stdout


def test_banned_rm_rf_fails(tmp_path):
    repo = make_repo(tmp_path)
    _write(repo, "workers/bar.py",
           "import os\nos.system('rm -rf /some/dir')\n")
    _commit_all(repo, "add nuke")
    r = check(repo)
    assert r.returncode == 1
    assert "banned-pattern" in r.stdout
    assert "rm -rf" in r.stdout


def test_banned_api_key_assignment_fails(tmp_path):
    repo = make_repo(tmp_path)
    _write(repo, "workers/bar.py",
           "os.environ['x'] = 'ANTHROPIC_API_KEY=sk-test'\n")
    _commit_all(repo, "leak key")
    r = check(repo)
    assert r.returncode == 1
    assert "banned-pattern" in r.stdout


def test_removed_banned_line_is_not_flagged(tmp_path):
    """Banned patterns gate ADDED lines only; deleting one is fine."""
    repo = make_repo(tmp_path)
    _write(repo, "workers/danger.py", "os.system('crontab -r')\n")
    _commit_all(repo, "seed danger on feature")
    # Re-base check against feature's own parent won't help; instead check
    # a follow-up commit that deletes the line, diffed against feature tip.
    _git(repo, "tag", "with-danger")
    _write(repo, "workers/danger.py", "pass\n")
    _commit_all(repo, "remove danger")
    r = check(repo, base="with-danger")
    assert r.returncode == 0, r.stdout + r.stderr


def test_diff_size_over_budget_fails(tmp_path):
    repo = make_repo(tmp_path)
    _write(repo, "workers/big.py",
           "".join(f"x{i} = {i}\n" for i in range(50)))
    _commit_all(repo, "big diff")
    r = check(repo, max_lines=10)
    assert r.returncode == 1
    assert "diff-size" in r.stdout


def test_diff_size_within_budget_passes(tmp_path):
    repo = make_repo(tmp_path)
    _write(repo, "workers/small.py", "y = 1\n")
    _commit_all(repo, "small diff")
    r = check(repo, max_lines=10)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK" in r.stdout


def test_no_budget_means_no_size_limit(tmp_path):
    repo = make_repo(tmp_path)
    _write(repo, "workers/big.py",
           "".join(f"x{i} = {i}\n" for i in range(200)))
    _commit_all(repo, "big diff no budget")
    r = check(repo)
    assert r.returncode == 0


def test_multiple_violations_all_named(tmp_path):
    repo = make_repo(tmp_path)
    _write(repo, "orchestrator/nara.py", "SPINE = 2\n")
    _write(repo, "workers/bar.py", "os.system('rm -rf x')\n")
    _commit_all(repo, "two violations")
    r = check(repo)
    assert r.returncode == 1
    assert "protected-path" in r.stdout
    assert "banned-pattern" in r.stdout


def test_usage_error_no_args(tmp_path):
    repo = make_repo(tmp_path)
    r = subprocess.run([str(SCRIPT)], cwd=repo, env=_GIT_ENV,
                       capture_output=True, text=True)
    assert r.returncode == 2
    assert "usage" in r.stderr


def test_bad_base_ref_is_usage_error(tmp_path):
    repo = make_repo(tmp_path)
    r = check(repo, base="no-such-ref")
    assert r.returncode == 2


def test_non_numeric_budget_is_usage_error(tmp_path):
    repo = make_repo(tmp_path)
    r = subprocess.run([str(SCRIPT), "main", "lots"], cwd=repo,
                       env=_GIT_ENV, capture_output=True, text=True)
    assert r.returncode == 2
