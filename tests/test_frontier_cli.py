"""Tests for agent_wrapper/frontier_cli.py (LOOP_V1 P2 frontier seam).

Hermetic: every test either runs under MOCK_LLM (CLI never spawned) or
monkeypatches subprocess.run — no network, no real CLI calls, ledgers in
tmp_path only.
"""
from __future__ import annotations

import hashlib
import json
import subprocess

import pytest

from agent_wrapper import frontier_cli as fc


def _read_ledger(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def _completed(cmd, stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess(
        cmd, returncode=returncode, stdout=stdout, stderr=stderr
    )


CLAUDE_OK_STDOUT = json.dumps(
    {"type": "result", "is_error": False, "result": "claude says hi"}
)


@pytest.fixture
def fake_run(monkeypatch):
    """Monkeypatch subprocess.run; records every (cmd, env) pair. The reply
    for the MAIN call (not the --version probe) is settable via .reply."""
    calls = []

    class Fake:
        reply = None  # callable(cmd, kwargs) -> CompletedProcess, or raises

        def __call__(self, cmd, **kwargs):
            calls.append({"cmd": list(cmd), "env": kwargs.get("env")})
            if cmd[-1] == "--version":
                return _completed(cmd, stdout="9.9.9-test\n")
            assert self.reply is not None, "test forgot to set fake_run.reply"
            return self.reply(cmd, kwargs)

    fake = Fake()
    fake.calls = calls
    monkeypatch.setattr(fc.subprocess, "run", fake)
    monkeypatch.setattr(fc, "_version_cache", {})
    return fake


@pytest.fixture
def real_mode(monkeypatch):
    """Unset MOCK_LLM so the (monkeypatched) subprocess path is exercised."""
    monkeypatch.delenv("MOCK_LLM", raising=False)


# ------------------------------------------------------------ MOCK_LLM ------


def test_mock_llm_stub_never_spawns(monkeypatch, tmp_path):
    monkeypatch.setenv("MOCK_LLM", "1")

    def boom(*a, **k):  # pragma: no cover - failure path
        raise AssertionError("subprocess.run must not be called under MOCK_LLM")

    monkeypatch.setattr(fc.subprocess, "run", boom)
    ledger = tmp_path / "ledger.jsonl"
    res = fc.invoke_frontier(
        "claude", "hello", timeout_s=5, role="methods_reviewer",
        ledger_path=ledger,
    )
    assert res["error"] is None
    assert res["cli_version"] == "mock"
    assert res["vendor"] == "claude"
    assert res["exit_code"] == 0
    assert res["failure_code"] is None
    assert res["resolved_binary_path"] is None
    sha = hashlib.sha256(b"hello").hexdigest()
    assert sha[:16] in res["text"]
    # deterministic: same inputs -> same text
    res2 = fc.invoke_frontier(
        "claude", "hello", timeout_s=5, role="methods_reviewer",
        ledger_path=ledger,
    )
    assert res2["text"] == res["text"]
    rows = _read_ledger(ledger)
    assert len(rows) == 2
    assert rows[0]["prompt_sha256"] == sha
    assert rows[0]["failure_code"] is None
    assert rows[0]["resolved_binary_path"] is None


# ------------------------------------------------- env stripping (MANDATORY)


def test_spawned_env_strips_anthropic_keys(monkeypatch, tmp_path, fake_run,
                                           real_mode):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-live-secret")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok-secret")
    monkeypatch.setenv("HOME", "/home/x")  # a key that MUST survive
    fake_run.reply = lambda cmd, kw: _completed(cmd, stdout=CLAUDE_OK_STDOUT)
    res = fc.invoke_frontier(
        "claude", "p", timeout_s=5, role="methods_reviewer",
        ledger_path=tmp_path / "l.jsonl",
    )
    assert res["error"] is None
    assert len(fake_run.calls) >= 2  # --version probe + main call
    for call in fake_run.calls:
        env = call["env"]
        assert env is not None, "subprocess must receive an explicit env"
        assert "ANTHROPIC_API_KEY" not in env
        assert "ANTHROPIC_AUTH_TOKEN" not in env
        assert env.get("HOME") == "/home/x"
    # the process's own environ is untouched
    import os
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-live-secret"


# ------------------------------------------------------------ commands ------


def test_claude_command_shape(tmp_path, fake_run, real_mode):
    fake_run.reply = lambda cmd, kw: _completed(cmd, stdout=CLAUDE_OK_STDOUT)
    fc.invoke_frontier(
        "claude", "review this", timeout_s=7, role="methods_reviewer",
        ledger_path=tmp_path / "l.jsonl",
    )
    main = fake_run.calls[-1]["cmd"]
    # cmd[0] is RESOLVED (env pin > ~/.npm-global/bin > bare name) since the
    # 2026-08-18 cron-PATH outage; the flag shape stays pinned verbatim.
    assert main[0] == fc._resolve_binary("claude")
    assert main[0].endswith("claude")
    assert main[1:] == ["-p", "--output-format", "json", "review this"]


def test_codex_command_shape(tmp_path, fake_run, real_mode):
    codex_line = json.dumps(
        {"type": "item.completed",
         "item": {"type": "agent_message", "text": "codex says hi"}}
    )
    fake_run.reply = lambda cmd, kw: _completed(cmd, stdout=codex_line)
    res = fc.invoke_frontier(
        "codex", "novelty?", timeout_s=7, role="novelty_reviewer",
        ledger_path=tmp_path / "l.jsonl",
    )
    main = fake_run.calls[-1]["cmd"]
    # Model + effort are PINNED by this module, not inherited from the
    # machine-global ~/.codex/config.toml (2026-08-16: that config's gpt-5.6 /
    # "max" started returning 400 and took this reviewer dark for 6 hours).
    assert main[0] == fc._resolve_binary("codex")
    assert main[0].endswith("codex")
    assert main[1:] == [
        "exec", "--skip-git-repo-check",
        "--sandbox", "read-only",
        "-m", fc.CODEX_MODEL,
        "-c", f"model_reasoning_effort={fc.CODEX_REASONING_EFFORT}",
        "--json", "novelty?",
    ]
    # Pinned, not inherited (D-068/D-069). Moved to the 5.6-class reviewer on
    # 2026-08-16 once the account regained access; both values were probed
    # live before the pin changed.
    assert (fc.CODEX_MODEL, fc.CODEX_REASONING_EFFORT) == ("gpt-5.6-sol", "max")
    assert res["text"] == "codex says hi"
    assert res["cli_version"] == "9.9.9-test"


def test_unknown_vendor_raises(tmp_path):
    with pytest.raises(ValueError):
        fc.invoke_frontier(
            "gemini", "p", timeout_s=5, role="r",
            ledger_path=tmp_path / "l.jsonl",
        )


# ------------------------------------------------------------- parsing ------


def test_codex_legacy_msg_shape_parses(tmp_path, fake_run, real_mode):
    lines = "\n".join([
        "non-json status line",
        json.dumps({"id": "1", "msg": {"type": "task_started"}}),
        json.dumps({"id": "2", "msg": {"type": "agent_message",
                                       "message": "legacy reply"}}),
    ])
    fake_run.reply = lambda cmd, kw: _completed(cmd, stdout=lines)
    res = fc.invoke_frontier(
        "codex", "p", timeout_s=5, role="novelty_reviewer",
        ledger_path=tmp_path / "l.jsonl",
    )
    assert res["error"] is None
    assert res["text"] == "legacy reply"


def test_claude_unparseable_stdout_is_structured_error(tmp_path, fake_run,
                                                       real_mode):
    fake_run.reply = lambda cmd, kw: _completed(cmd, stdout="not json at all")
    res = fc.invoke_frontier(
        "claude", "p", timeout_s=5, role="methods_reviewer",
        ledger_path=tmp_path / "l.jsonl",
    )
    assert res["error"] is not None and "unparseable" in res["error"]
    assert res["text"] == ""
    assert res["exit_code"] == 0
    assert res["failure_code"] == "unparseable_output"


def test_claude_is_error_flag_is_structured_error(tmp_path, fake_run,
                                                  real_mode):
    stdout = json.dumps({"is_error": True, "result": "over budget"})
    fake_run.reply = lambda cmd, kw: _completed(cmd, stdout=stdout)
    res = fc.invoke_frontier(
        "claude", "p", timeout_s=5, role="methods_reviewer",
        ledger_path=tmp_path / "l.jsonl",
    )
    assert res["error"] is not None
    assert res["text"] == ""
    assert res["failure_code"] == "cli_reported_error"
    assert "over budget" not in res["error"]


def test_codex_no_agent_message_is_structured_error(tmp_path, fake_run,
                                                    real_mode):
    fake_run.reply = lambda cmd, kw: _completed(
        cmd, stdout=json.dumps({"type": "turn.completed"})
    )
    res = fc.invoke_frontier(
        "codex", "p", timeout_s=5, role="novelty_reviewer",
        ledger_path=tmp_path / "l.jsonl",
    )
    assert res["error"] is not None and "unparseable" in res["error"]


# --------------------------------------------------------- failure modes ----


def test_nonzero_exit_is_structured_error(tmp_path, fake_run, real_mode):
    fake_run.reply = lambda cmd, kw: _completed(
        cmd, returncode=2, stderr="secret account detail"
    )
    ledger = tmp_path / "l.jsonl"
    res = fc.invoke_frontier(
        "claude", "p", timeout_s=5, role="methods_reviewer", ledger_path=ledger,
    )
    assert res["error"] == "nonzero exit 2"
    assert res["failure_code"] == "nonzero_exit"
    assert "secret account detail" not in json.dumps(res)
    assert res["exit_code"] == 2
    row = _read_ledger(ledger)[-1]
    assert row["exit_code"] == 2
    assert row["failure_code"] == "nonzero_exit"
    assert "secret account detail" not in json.dumps(row)


def test_timeout_is_structured_error(tmp_path, fake_run, real_mode):
    def raise_timeout(cmd, kw):
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])

    fake_run.reply = raise_timeout
    ledger = tmp_path / "l.jsonl"
    res = fc.invoke_frontier(
        "codex", "p", timeout_s=3, role="novelty_reviewer", ledger_path=ledger,
    )
    assert res["error"] is not None and "timeout" in res["error"]
    assert res["exit_code"] == -1
    assert res["failure_code"] == "timeout"
    assert _read_ledger(ledger)[-1]["failure_code"] == "timeout"


def test_missing_binary_is_structured_error(tmp_path, fake_run, real_mode):
    def raise_fnf(cmd, kw):
        raise FileNotFoundError("No such file or directory: 'claude'")

    fake_run.reply = raise_fnf
    res = fc.invoke_frontier(
        "claude", "p", timeout_s=5, role="methods_reviewer",
        ledger_path=tmp_path / "l.jsonl",
    )
    assert res["error"] is not None and "launch failed" in res["error"]
    assert res["exit_code"] == 127
    assert res["failure_code"] == "launch_error"
    assert "No such file" not in res["error"]


# -------------------------------------------------------------- ledger ------


def test_ledger_row_shape_and_written_before_return(tmp_path, fake_run,
                                                    real_mode):
    fake_run.reply = lambda cmd, kw: _completed(cmd, stdout=CLAUDE_OK_STDOUT)
    ledger = tmp_path / "l.jsonl"
    fc.invoke_frontier(
        "claude", "the prompt", timeout_s=5, role="methods_reviewer",
        ledger_path=ledger,
    )
    rows = _read_ledger(ledger)
    assert len(rows) == 1
    row = rows[0]
    assert set(row) == {
        "timestamp", "vendor", "cli_version", "role", "verdict",
        "duration_ms", "exit_code", "prompt_sha256",
        "resolved_binary_path", "failure_code",
    }
    assert row["vendor"] == "claude"
    assert row["role"] == "methods_reviewer"
    assert row["verdict"] is None  # verdict is null at this layer
    assert row["prompt_sha256"] == hashlib.sha256(b"the prompt").hexdigest()
    assert isinstance(row["duration_ms"], int)
    assert row["timestamp"].endswith("Z")
    assert row["failure_code"] is None
    assert row["resolved_binary_path"] == fc._binary_path(fc._resolve_binary("claude"))


def test_default_ledger_path_used_when_none(monkeypatch, tmp_path, fake_run,
                                            real_mode):
    default = tmp_path / "run_state" / "frontier_calls.jsonl"
    monkeypatch.setattr(fc, "DEFAULT_LEDGER", default)
    fake_run.reply = lambda cmd, kw: _completed(cmd, stdout=CLAUDE_OK_STDOUT)
    fc.invoke_frontier("claude", "p", timeout_s=5, role="methods_reviewer")
    assert len(_read_ledger(default)) == 1


def test_version_probe_failure_yields_unknown(tmp_path, monkeypatch,
                                              real_mode):
    calls = []

    def fake(cmd, **kwargs):
        calls.append(list(cmd))
        if cmd[-1] == "--version":
            raise OSError("no binary")
        return _completed(cmd, stdout=CLAUDE_OK_STDOUT)

    monkeypatch.setattr(fc.subprocess, "run", fake)
    monkeypatch.setattr(fc, "_version_cache", {})
    res = fc.invoke_frontier(
        "claude", "p", timeout_s=5, role="methods_reviewer",
        ledger_path=tmp_path / "l.jsonl",
    )
    assert res["cli_version"] == "unknown"
    assert res["error"] is None


# ── repo-owned CODEX_HOME (2026-08-16, second D-068-class outage) -------------

def _fake_home(tmp_path, monkeypatch, *, with_auth=True):
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    if with_auth:
        (home / ".codex" / "auth.json").write_text('{"token": "t"}')
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(fc, "CODEX_HOME_DIR", tmp_path / "codex_home")
    return home


def test_codex_spawns_with_a_repo_owned_home_carrying_our_pins(tmp_path,
                                                              monkeypatch):
    """The machine-global ~/.codex/config.toml is shared with other projects
    and is rewritten by the CLI itself — twice on 2026-08-16 it broke every
    call. The apparatus reads its OWN config and borrows only the credential."""
    _fake_home(tmp_path, monkeypatch)
    env = fc._spawn_env("codex")
    assert env["CODEX_HOME"] == str(tmp_path / "codex_home")
    cfg = (tmp_path / "codex_home" / "config.toml").read_text()
    assert f'model = "{fc.CODEX_MODEL}"' in cfg
    assert f'model_reasoning_effort = "{fc.CODEX_REASONING_EFFORT}"' in cfg
    # The credential is BORROWED, not copied — a copied token outlives its
    # rotation.
    link = tmp_path / "codex_home" / "auth.json"
    assert link.is_symlink()
    assert link.resolve() == (tmp_path / "home" / ".codex" / "auth.json")


def test_the_pin_is_rewritten_every_call_so_a_stale_home_cannot_outvote_it(
        tmp_path, monkeypatch):
    _fake_home(tmp_path, monkeypatch)
    fc._spawn_env("codex")
    (tmp_path / "codex_home" / "config.toml").write_text('model = "stale"\n')
    fc._spawn_env("codex")
    assert 'model = "stale"' not in (
        tmp_path / "codex_home" / "config.toml").read_text()


def test_other_vendors_are_untouched_by_the_codex_home(tmp_path, monkeypatch):
    _fake_home(tmp_path, monkeypatch)
    assert "CODEX_HOME" not in fc._spawn_env("claude")
    assert "CODEX_HOME" not in fc._spawn_env()


def test_absent_credential_leaves_codex_home_unset_rather_than_faking_one(
        tmp_path, monkeypatch):
    """There is nowhere else for the credential to come from, so the call is
    left to fail with the REAL error instead of on a manufactured home."""
    _fake_home(tmp_path, monkeypatch, with_auth=False)
    assert "CODEX_HOME" not in fc._spawn_env("codex")
    assert not (tmp_path / "codex_home").exists()


def test_resolve_binary_order(monkeypatch, tmp_path):
    """Env pin > user npm install > bare name (2026-08-18 cron-PATH outage:
    cron resolved a stale root claude 2.1.143 (exit 1) and no codex at all
    (exit 127) because the current CLIs live only in ~/.npm-global/bin)."""
    monkeypatch.setenv("FRONTIER_CODEX_BIN", "/pinned/codex")
    assert fc._resolve_binary("codex") == "/pinned/codex"
    monkeypatch.delenv("FRONTIER_CODEX_BIN", raising=False)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    exe = fake_bin / "codex"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    monkeypatch.setattr(fc, "_USER_NPM_BIN", fake_bin)
    monkeypatch.setattr(fc, "_USER_LOCAL_BIN", tmp_path / "missing-local")
    assert fc._resolve_binary("codex") == str(exe)
    exe.unlink()
    monkeypatch.setattr(fc.shutil, "which", lambda name: None)
    assert fc._resolve_binary("codex") == "codex"


def test_claude_resolver_prefers_explicit_then_npm_then_current_user_then_path(
        monkeypatch, tmp_path):
    npm = tmp_path / "npm"
    user = tmp_path / "local"
    npm.mkdir()
    user.mkdir()
    npm_cli = npm / "claude"
    user_cli = user / "claude"
    for path in (npm_cli, user_cli):
        path.write_text("#!/bin/sh\n")
        path.chmod(0o755)
    monkeypatch.setattr(fc, "_USER_NPM_BIN", npm)
    monkeypatch.setattr(fc, "_USER_LOCAL_BIN", user)
    monkeypatch.setattr(fc.shutil, "which", lambda name: "/stale-path/claude")
    monkeypatch.setenv("FRONTIER_CLAUDE_BIN", "/missing/explicit-claude")
    assert fc._resolve_binary("claude") == "/missing/explicit-claude"
    monkeypatch.delenv("FRONTIER_CLAUDE_BIN")
    assert fc._resolve_binary("claude") == str(npm_cli)
    npm_cli.unlink()
    assert fc._resolve_binary("claude") == str(user_cli)
    user_cli.chmod(0o644)
    assert fc._resolve_binary("claude") == "/stale-path/claude"


def test_invalid_explicit_pin_never_falls_back(tmp_path, monkeypatch, fake_run,
                                               real_mode):
    monkeypatch.setenv("FRONTIER_CLAUDE_BIN", "/missing/pinned-claude")

    def missing(cmd, kw):
        assert cmd[0] == "/missing/pinned-claude"
        raise FileNotFoundError("secret account text")

    fake_run.reply = missing
    ledger = tmp_path / "l.jsonl"
    result = fc.invoke_frontier("claude", "p", timeout_s=5,
                                role="methods_reviewer", ledger_path=ledger)
    assert result["failure_code"] == "launch_error"
    assert result["resolved_binary_path"] == "/missing/pinned-claude"
    assert _read_ledger(ledger)[0]["resolved_binary_path"] == "/missing/pinned-claude"
    assert "secret account text" not in json.dumps(result)


def test_version_cache_follows_selected_binary_not_vendor(tmp_path, monkeypatch,
                                                          real_mode):
    seen = []

    def fake(cmd, **kw):
        seen.append(list(cmd))
        if cmd[-1] == "--version":
            return _completed(cmd, stdout=f"version-{cmd[0]}\n")
        return _completed(cmd, stdout=CLAUDE_OK_STDOUT)

    monkeypatch.setattr(fc.subprocess, "run", fake)
    monkeypatch.setattr(fc, "_version_cache", {})
    ledger = tmp_path / "l.jsonl"
    for pin in ("/pinned/claude-a", "/pinned/claude-b", "/pinned/claude-b"):
        monkeypatch.setenv("FRONTIER_CLAUDE_BIN", pin)
        result = fc.invoke_frontier("claude", "p", timeout_s=5,
                                    role="methods_reviewer", ledger_path=ledger)
        assert result["cli_version"] == f"version-{pin}"
        assert result["resolved_binary_path"] == pin
    assert [cmd[0] for cmd in seen if cmd[-1] == "--version"] == [
        "/pinned/claude-a", "/pinned/claude-b",
    ]
    assert [row["resolved_binary_path"] for row in _read_ledger(ledger)] == [
        "/pinned/claude-a", "/pinned/claude-b", "/pinned/claude-b",
    ]
