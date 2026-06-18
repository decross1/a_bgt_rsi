"""Tests for orchestrator/skill_signals.py — the apparatus-side skill-signals
emitter (D-056). Covers the reconciled contract: NON-BLOCKING emit, NON-DROPPING
skill-name validation, rule-4 enum rejection, append-only, no `_source`, and the
swallow guard. All writes go to tmp (explicit `path=` or the conftest redirect of
SKILL_SIGNALS_PATH) so a full pytest run adds ZERO live rows (D-048)."""
from __future__ import annotations

import json

from orchestrator import skill_signals as ss


def _rows(p):
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def test_gap_emits_required_fields(tmp_path):
    p = tmp_path / "skill_signals.jsonl"
    ok = ss.emit_skill_signal(
        agent="workflow:wf_x/builder", skill="validate", signal_class="gap",
        severity="med", evidence="validate assumes a schema file the apparatus lacks",
        task_id="P7-iter-1", path=p)
    assert ok is True
    rows = _rows(p)
    assert len(rows) == 1
    r = rows[0]
    for f in ("timestamp", "agent", "skill", "signal_class", "severity",
              "evidence", "task_id"):
        assert f in r and r[f]
    assert r["signal_class"] == "gap"
    assert "_source" not in r  # the framework adds it, never us


def test_misuse_emits(tmp_path):
    p = tmp_path / "s.jsonl"
    assert ss.emit_skill_signal(
        agent="a", skill="fallback", signal_class="misuse", severity="low",
        evidence="substituted a manual retry; fallback skill had no time-cap slot",
        task_id="t1", path=p) is True
    assert _rows(p)[0]["signal_class"] == "misuse"


def test_unknown_skill_still_emits_non_dropping(tmp_path):
    p = tmp_path / "s.jsonl"
    # A skill name not in the in-repo constant must STILL emit (with skill_known=false),
    # never be suppressed — neutralizes the framework-rename staleness hazard.
    assert ss.emit_skill_signal(
        agent="a", skill="some-renamed-skill", signal_class="gap", severity="low",
        evidence="x", task_id="t", path=p) is True
    r = _rows(p)[0]
    assert r["skill"] == "some-renamed-skill"
    assert r["skill_known"] is False


def test_known_skill_has_no_skill_known_field(tmp_path):
    p = tmp_path / "s.jsonl"
    ss.emit_skill_signal(agent="a", skill="run-log", signal_class="gap",
                         severity="low", evidence="x", task_id="t", path=p)
    assert "skill_known" not in _rows(p)[0]


def test_optional_fields_included_when_given(tmp_path):
    p = tmp_path / "s.jsonl"
    ss.emit_skill_signal(
        agent="a", skill="run-log", signal_class="misuse", severity="high",
        evidence="x", task_id="t", invocation_ref="week1.run.jsonl:L9",
        expected="a slot", actual="improvised", suggested_fix="widen the skill", path=p)
    r = _rows(p)[0]
    assert r["invocation_ref"] == "week1.run.jsonl:L9"
    assert r["expected"] == "a slot" and r["actual"] == "improvised"
    assert r["suggested_fix"] == "widen the skill"


def test_append_only(tmp_path):
    p = tmp_path / "s.jsonl"
    ss.emit_skill_signal(agent="a", skill="run-log", signal_class="gap",
                         severity="low", evidence="one", task_id="t", path=p)
    ss.emit_skill_signal(agent="a", skill="run-log", signal_class="gap",
                         severity="low", evidence="two", task_id="t", path=p)
    rows = _rows(p)
    assert len(rows) == 2 and rows[0]["evidence"] == "one"


def test_rule4_bad_signal_class_swallowed_nothing_written(tmp_path):
    p = tmp_path / "s.jsonl"
    assert ss.emit_skill_signal(agent="a", skill="run-log", signal_class="recovered",
                                severity="low", evidence="x", task_id="t", path=p) is False
    assert not p.exists()  # rejected, not coerced; nothing written


def test_rule4_bad_severity_and_empty_fields_swallowed(tmp_path):
    p = tmp_path / "s.jsonl"
    assert ss.emit_skill_signal(agent="a", skill="run-log", signal_class="gap",
                                severity="HUGE", evidence="x", task_id="t", path=p) is False
    assert ss.emit_skill_signal(agent="a", skill="  ", signal_class="gap",
                                severity="low", evidence="x", task_id="t", path=p) is False
    assert ss.emit_skill_signal(agent="a", skill="run-log", signal_class="gap",
                                severity="low", evidence="x", task_id="", path=p) is False
    assert not p.exists()


def test_emit_never_raises_non_blocking(tmp_path):
    # A non-writable target must NOT raise into the task — it swallows + returns False.
    bad = tmp_path / "nope.jsonl"
    bad.mkdir()  # a directory at the row path => open(...,'a') fails
    assert ss.emit_skill_signal(agent="a", skill="run-log", signal_class="gap",
                                severity="low", evidence="x", task_id="t", path=bad) is False


def test_default_path_is_module_global(monkeypatch, tmp_path):
    # The helper resolves SKILL_SIGNALS_PATH at call time (so D-048 conftest redirect
    # works). The autouse _no_live_artifacts fixture already redirects it to tmp;
    # here we redirect explicitly and confirm the default path is honored.
    target = tmp_path / "viamodule.jsonl"
    monkeypatch.setattr(ss, "SKILL_SIGNALS_PATH", target)
    assert ss.emit_skill_signal(agent="a", skill="validate", signal_class="gap",
                                severity="low", evidence="x", task_id="t") is True
    assert target.exists() and _rows(target)[0]["skill"] == "validate"


def test_no_brain_access_in_source():
    # The emit path must touch no framework/brain artifact (D-014). Structural pin.
    src = (ss.__file__)
    text = open(src).read()
    for forbidden in ("memory/brain", "agent_system", "ingest_apparatus",
                      "drift_signals", "BOUNDARY"):
        assert forbidden not in text, f"skill_signals.py must not reference {forbidden}"
