"""exp007 applied-paper refine CLI — the interactive-refinement seam (start/turn).

Runs under MOCK_LLM (the exp007 harness uses its deterministic stub forecast), so no
model is touched. SESSIONS_DIR is redirected to tmp_path so no run_state is polluted.
"""
import json

import pytest

from experiments.exp007_polymarket import refine_cli


def _last_envelope(capsys) -> dict:
    out = capsys.readouterr().out.strip().splitlines()
    return json.loads(out[-1])


def test_start_then_turn_reruns_and_scores(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(refine_cli, "SESSIONS_DIR", tmp_path)

    assert refine_cli.main(["start", "--session-id", "s1"]) == 0
    env = _last_envelope(capsys)
    assert env["ok"] and env["action"] == "start"
    assert env["params"] == refine_cli.DEFAULTS
    assert "trading" in env["note"].lower()  # zero-trading disclaimer present

    assert refine_cli.main(
        ["turn", "--session-id", "s1", "--param", "n:3", "--message", "fewer markets"]
    ) == 0
    env = _last_envelope(capsys)
    assert env["ok"] and env["action"] == "turn"
    assert env["params"]["n"] == 3          # the tweak took
    assert env["message"] == "fewer markets"
    assert env["n_forecast"] >= 0
    assert "brier" in env                    # None or float, never absent / fabricated
    assert env["turns"] == 1


def test_turn_without_start_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(refine_cli, "SESSIONS_DIR", tmp_path)
    assert refine_cli.main(["turn", "--session-id", "ghost"]) != 0


def test_unknown_param_rejected(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(refine_cli, "SESSIONS_DIR", tmp_path)
    refine_cli.main(["start", "--session-id", "s2"])
    capsys.readouterr()
    # only seed/temperature/n are tunable — there is no trading surface to address
    assert refine_cli.main(["turn", "--session-id", "s2", "--param", "wallet:0xabc"]) != 0


def test_non_numeric_param_rejected(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(refine_cli, "SESSIONS_DIR", tmp_path)
    refine_cli.main(["start", "--session-id", "s3"])
    capsys.readouterr()
    assert refine_cli.main(["turn", "--session-id", "s3", "--param", "temperature:hot"]) != 0
