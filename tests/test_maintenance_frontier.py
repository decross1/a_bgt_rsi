"""Offline transport contract; fake CLIs never contact either provider."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from agent_wrapper import maintenance_frontier as mf


def fake_claude(tmp_path, monkeypatch, body):
    path = tmp_path / "claude"
    path.write_text(f"#!{sys.executable}\n" + "import sys,json,os,time\n"
                    "if '--version' in sys.argv:\n print('test-cli');sys.exit()\n"
                    "if 'auth' in sys.argv:\n print(json.dumps({'loggedIn': True, 'authMethod': 'claude.ai', 'apiProvider': 'firstParty'}));sys.exit()\n"
                    + body)
    path.chmod(0o755)
    monkeypatch.setenv("FRONTIER_CLAUDE_BIN", str(path))
    monkeypatch.delenv("MOCK_LLM", raising=False)
    return path


def test_isolated_subscription_invocation_and_receipt(tmp_path, monkeypatch):
    fake_claude(tmp_path, monkeypatch, """
assert 'ANTHROPIC_API_KEY' not in os.environ
assert 'OPENAI_API_KEY' not in os.environ
assert '--tools' in sys.argv and sys.argv[sys.argv.index('--tools')+1] == ''
assert '--bare' not in sys.argv
assert not os.path.exists('AGENTS.md')
prompt=sys.stdin.read()
print(json.dumps({'result':prompt,'is_error':False,'modelUsage':{'test-model':{'outputTokens':2}}}))
""")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "should-not-leave")
    monkeypatch.setenv("OPENAI_API_KEY", "should-not-leave")
    ledger = tmp_path / "receipt.jsonl"
    result = mf.invoke_maintenance_frontier("claude", "test input", timeout_s=5,
                                            role="upgrade_adversary", ledger_path=ledger)
    assert result["error"] is None
    assert result["text"] == "test input"
    assert result["model_ids"] == ["test-model"]
    receipt = json.loads(ledger.read_text())
    assert receipt["auth_mode"] == "subscription"
    assert "test input" not in ledger.read_text()
    assert "should-not-leave" not in ledger.read_text()


def test_pinned_broken_binary_never_silently_falls_back(tmp_path, monkeypatch):
    monkeypatch.delenv("MOCK_LLM", raising=False)
    monkeypatch.setenv("FRONTIER_CLAUDE_BIN", str(tmp_path / "missing"))
    r = mf.invoke_maintenance_frontier("claude", "x", timeout_s=2, role="r",
                                       ledger_path=tmp_path / "calls.jsonl")
    assert r["error_category"] == "PREFLIGHT_FAILED"
    assert r["text"] == ""


def test_mock_cannot_be_scored_as_success(tmp_path, monkeypatch):
    monkeypatch.setenv("MOCK_LLM", "1")
    monkeypatch.setattr(mf, "_run", lambda *a, **k: pytest.fail("spawned"))
    r = mf.invoke_maintenance_frontier("claude", "x", timeout_s=2, role="r",
                                       ledger_path=tmp_path / "calls.jsonl")
    assert r["mock"] and r["error_category"] == "MOCK_MODE"


def test_timeout_and_output_limit_terminate_child(tmp_path, monkeypatch):
    fake_claude(tmp_path, monkeypatch, "time.sleep(20)\n")
    start = time.monotonic()
    r = mf.invoke_maintenance_frontier("claude", "x", timeout_s=.4, role="r",
                                       ledger_path=tmp_path / "calls.jsonl")
    assert r["error_category"] == "TIMEOUT"
    assert time.monotonic() - start < 3
    fake_claude(tmp_path, monkeypatch, "print('x'*100000)\n")
    monkeypatch.setattr(mf, "MAX_OUTPUT_BYTES", 8192)
    r = mf.invoke_maintenance_frontier("claude", "x", timeout_s=3, role="r",
                                       ledger_path=tmp_path / "calls.jsonl")
    assert r["error_category"] == "OUTPUT_LIMIT"


def test_malformed_and_provider_error_are_not_success(tmp_path, monkeypatch):
    for body in ["print('not-json')\n", "print(json.dumps({'is_error':True,'result':'bad'}))\n"]:
        fake_claude(tmp_path, monkeypatch, body)
        r = mf.invoke_maintenance_frontier("claude", "x", timeout_s=3, role="r",
                                           ledger_path=tmp_path / "calls.jsonl")
        assert r["error_category"] == "INVALID_RESPONSE"
        assert r["text"] == ""


def test_codex_event_error_after_partial_message_fails():
    events = '\n'.join([json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'partial'}}),
                        json.dumps({'type':'turn.failed','error':{'message':'quota'}})])
    with pytest.raises(ValueError):
        mf._parse_response("codex", events)


def test_codex_partial_output_is_not_a_completed_review():
    event = json.dumps({'type': 'item.completed', 'item': {
        'type': 'agent_message', 'text': 'partial'}})
    with pytest.raises(ValueError, match='did not complete'):
        mf._parse_response('codex', event)


def test_codex_command_disables_tool_and_plugin_paths(tmp_path):
    cmd = mf._command("codex", "/test/codex", "model-x")
    for feature in ("shell_tool", "unified_exec", "apps", "plugins", "hooks", "multi_agent"):
        assert cmd[cmd.index(feature)-1] == "--disable"
    assert 'web_search="disabled"' in cmd
    assert '--ephemeral' in cmd and cmd[-1] == '-'


def test_codex_requires_subscription_auth_without_printing_token(tmp_path, monkeypatch):
    monkeypatch.delenv("MOCK_LLM", raising=False)
    monkeypatch.setattr(mf, "_home", lambda: tmp_path)
    (tmp_path/'.codex').mkdir()
    (tmp_path/'.codex/auth.json').write_text(json.dumps({'auth_mode':'apikey','OPENAI_API_KEY':'secret'}))
    with pytest.raises(ValueError, match="subscription"):
        mf._codex_auth()
