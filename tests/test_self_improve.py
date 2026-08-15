"""Tests for orchestrator/self_improve.py (D-066 self-improvement planner).

Hermetic by construction: tmp_path telemetry + tmp_path packets/tests/queue,
every seam injected (`propose_fn`, `revise_fn`, `invoke_fn`, `run_test`,
`run_log`). No real model call, no frontier CLI subprocess, no pytest
subprocess, no writes outside tmp_path.

Pinned behaviors:
  - evidence is PURE reads; a missing source yields an explicit
    "[unavailable: <path>]" marker and an EMPTY section (never invented).
  - a proposal that does not parse RAISES — no silent stub.
  - the review ladder matches frontier_review.screen_candidate, including the
    cross-run disagreement protocol.
  - MAX_IMPROVE_ROUNDS = 3 is HARD (out-of-band raises); exhaustion returns
    emitted:false WITH the transcript.
  - Tier-S / untiered / outside-repo paths are REFUSED at emit, each named.
  - red-first is PROVEN: a passing (or collection-erroring) acceptance test
    emits nothing and the file is removed; only pytest rc=1 emits.
  - the emitted packet validates against the REAL task_packet schema, its
    test_cmd uses an ABSOLUTE interpreter, and the queue row is accepted by
    packet_dispatcher.consume_authorize_fix_queue.
  - --dry-run writes nothing at all, including run-log rows.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import jsonschema
import pytest

from orchestrator import packet_dispatcher as pd
from orchestrator import self_improve as si


# ── fixtures / factories ─────────────────────────────────────────────────────

def _jsonl(path: Path, rows: list[dict]) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


def _proposal(**over) -> dict:
    base = {
        "title": "digest the repeated near-miss reason",
        "problem": "promotion near-miss reason 'ladder L0 < L1' repeated x120",
        "change": "add workers/near_miss_digest.py returning the top reason",
        "rationale": "the same near-miss reason repeats every cycle unread",
        "files_in_scope": ["workers/near_miss_digest.py"],
        "acceptance_test_path": "tests/test_near_miss_digest.py",
        "acceptance_test_intent": "top_reason() returns the most frequent reason",
        "acceptance_test_source": "def test_top_reason():\n    assert False\n",
        "risk": "none; one new Tier-P file, revert by deleting it",
    }
    base.update(over)
    return base


def _propose_fn(proposal=None):
    return lambda digest: json.dumps(proposal or _proposal())


def _invoke(verdicts: dict, calls: list | None = None):
    """Canned frontier seam. `verdicts[role]` is a verdict string, an
    Exception to raise, or a list popped once per call (cross-runs pop the
    next entry)."""
    def fn(vendor, prompt, *, timeout_s, role, **kw):
        if calls is not None:
            calls.append({"vendor": vendor, "role": role})
        value = verdicts[role]
        if isinstance(value, list):
            value = value.pop(0)
        if isinstance(value, Exception):
            raise value
        return {"text": json.dumps({"verdict": value,
                                    "reasoning": f"{role} says {value}"}),
                "vendor": vendor, "exit_code": 0, "error": None}
    return fn


def _emit_dirs(tmp_path):
    return {"packets_dir": tmp_path / "packets", "tests_dir": tmp_path / "tests",
            "queue_path": tmp_path / "authorize_fix_queue.jsonl"}


# ── stage 1: gather_evidence ─────────────────────────────────────────────────

def _telemetry(tmp_path, *, cycles=3, failures=2) -> dict:
    _jsonl(tmp_path / "run.jsonl", [
        {"task_id": "ok", "agent": "nara", "status": "passed"},
    ] + [
        {"task_id": f"boom-{i}", "agent": "nara", "status": "failed",
         "observable_actual": f"failure {i}"} for i in range(failures)
    ] + [
        {"task_id": "degrade", "agent": "nara", "status": "fallback",
         "observable_actual": "primary path failed"},
    ])
    _jsonl(tmp_path / "health.jsonl", [
        {"timestamp": "2026-08-03T09:00:00Z", "signal": "ml_intern_zero_papers",
         "severity": "degraded", "detail": "stored 0 papers"},
        {"timestamp": "2026-08-03T15:00:00Z", "signal": "ml_intern_zero_papers",
         "severity": "degraded", "detail": "stored 0 papers again"},
        {"timestamp": "2026-08-15T23:00:00Z", "signal": "loop_stalled",
         "severity": "stalled", "detail": "the loop did not move"},
    ])
    (tmp_path / "alert.json").write_text(json.dumps(
        {"level": "red", "reasons": ["loop_stalled"],
         "updated_at": "2026-08-15T23:00:33+00:00"}))
    _jsonl(tmp_path / "cycles.jsonl", [
        {"run_id": f"coordinator_{i}", "status": "executed",
         "plan": [{"action": "promote_findings"}], "promoted_finding_ids": []}
        for i in range(cycles)
    ])
    _jsonl(tmp_path / "near.jsonl", [
        {"reason": "evidence ladder L0 < L1", "stage": "threshold"}
        for _ in range(5)
    ] + [{"reason": "topicality advisory", "stage": "screen"}])
    (tmp_path / "daemon.log").write_text(
        "wake=1 work=False action=idle\nWARN: packet dispatch failed\n")
    return {
        "run_log_path": tmp_path / "run.jsonl",
        "health_path": tmp_path / "health.jsonl",
        "alert_path": tmp_path / "alert.json",
        "cycles_path": tmp_path / "cycles.jsonl",
        "near_miss_path": tmp_path / "near.jsonl",
        "daemon_log_path": tmp_path / "daemon.log",
    }


def test_gather_evidence_mines_every_section(tmp_path):
    ev = si.gather_evidence(**_telemetry(tmp_path))

    assert [f["status"] for f in ev["failures"]] == ["failed", "failed", "fallback"]
    assert ev["failures"][0]["task_id"] == "boom-0"
    assert {h["signal"] for h in ev["health"]} == {"ml_intern_zero_papers",
                                                   "loop_stalled"}
    top = next(h for h in ev["health"] if h["signal"] == "ml_intern_zero_papers")
    assert top["count"] == 2 and top["severity"] == "degraded"
    assert ev["alert"] == {"level": "red", "reasons": ["loop_stalled"],
                           "updated_at": "2026-08-15T23:00:33+00:00"}
    assert len(ev["cycles"]) == 3
    # Three identical cycles = a loop repeating itself; that is the signal.
    assert ev["cycle_repeats"] == [
        {"signature": "status=executed plan=promote_findings", "count": 3}]
    assert ev["near_misses"][0] == {"reason": "evidence ladder L0 < L1",
                                    "count": 5}
    assert any("idle" in line for line in ev["daemon"])
    assert ev["unavailable"] == []
    assert "EVIDENCE DIGEST" in ev["digest"]
    assert "loop_stalled" in ev["digest"] and "boom-0" in ev["digest"]


def test_gather_evidence_marks_missing_sources_and_invents_nothing(tmp_path):
    ev = si.gather_evidence(
        run_log_path=tmp_path / "nope-run.jsonl",
        health_path=tmp_path / "nope-health.jsonl",
        alert_path=tmp_path / "nope-alert.json",
        cycles_path=tmp_path / "nope-cycles.jsonl",
        near_miss_path=tmp_path / "nope-near.jsonl",
        daemon_log_path=tmp_path / "nope-daemon.log",
    )
    assert ev["failures"] == [] and ev["health"] == [] and ev["cycles"] == []
    assert ev["near_misses"] == [] and ev["daemon"] == [] and ev["alert"] is None
    assert len(ev["unavailable"]) == 6
    for marker in ev["unavailable"]:
        assert marker.startswith("[unavailable: ") and "nope-" in marker
        assert marker in ev["digest"]


def test_gather_evidence_caps_every_section(tmp_path):
    paths = _telemetry(tmp_path, cycles=20, failures=30)
    ev = si.gather_evidence(**paths, limit=4)
    assert len(ev["failures"]) == 4 and len(ev["cycles"]) == 4
    assert len(ev["health"]) <= 4 and len(ev["near_misses"]) <= 4


# ── stage 2: propose ─────────────────────────────────────────────────────────

def test_propose_returns_the_parsed_proposal():
    out = si.propose({"digest": "d"}, propose_fn=_propose_fn())
    assert out["title"] == _proposal()["title"]
    assert out["files_in_scope"] == ["workers/near_miss_digest.py"]


@pytest.mark.parametrize("raw", [
    "not json at all",
    json.dumps({"title": "t"}),                                    # missing fields
    json.dumps(_proposal(files_in_scope=[])),                      # empty scope
    json.dumps(_proposal(files_in_scope=["a", "b", "c", "d", "e", "f", "g"])),
    json.dumps(_proposal(acceptance_test_path="workers/thing.py")),  # not a test
    json.dumps(_proposal(acceptance_test_source="x = 1\n")),       # no test fn
    json.dumps(_proposal(risk="")),                                # empty field
])
def test_propose_parse_failure_raises_never_stubs(raw):
    with pytest.raises(ValueError):
        si.propose({"digest": "d"}, propose_fn=lambda digest: raw)


def test_propose_without_a_digest_refuses():
    with pytest.raises(ValueError, match="no digest"):
        si.propose({"failures": []}, propose_fn=_propose_fn())


def test_default_proposer_under_mock_llm_is_a_parseable_tier_p_stub(monkeypatch):
    monkeypatch.setenv("MOCK_LLM", "1")
    out = si.propose({"digest": "EVIDENCE DIGEST\n  - loop_stalled x3"})
    assert si.scope_violations(out["files_in_scope"] +
                               [out["acceptance_test_path"]]) == []
    assert "def test_" in out["acceptance_test_source"]


# ── stage 3: the review ladder ───────────────────────────────────────────────

@pytest.mark.parametrize("feas,risk,expected", [
    ("veto", "veto", "veto"),
    ("pass", "pass", "pass"),
    ("veto", "inconclusive", "veto"),
    ("pass", "inconclusive", "pass"),
    ("inconclusive", "inconclusive", "inconclusive"),
])
def test_review_ladder_without_cross_run(feas, risk, expected):
    out = si.review(_proposal(), invoke_fn=_invoke(
        {"feasibility_reviewer": feas, "risk_scope_reviewer": risk}))
    assert out["verdict"] == expected
    assert out["escalated"] is False
    assert out["feasibility"]["role"] == "feasibility_reviewer"
    assert out["risk_scope"]["vendor"] == si.ROLE_VENDOR_DEFAULTS[
        "risk_scope_reviewer"]


def test_review_cross_run_confirms_a_vendor_independent_veto():
    calls: list = []
    out = si.review(_proposal(), invoke_fn=_invoke(
        {"feasibility_reviewer": "pass",
         "risk_scope_reviewer": ["veto", "veto"]}, calls))
    assert out["verdict"] == "veto" and out["escalated"] is False
    # The VETOING role re-runs on the other role's vendor.
    assert calls[-1] == {"vendor": si.ROLE_VENDOR_DEFAULTS["feasibility_reviewer"],
                         "role": "risk_scope_reviewer"}
    assert out["risk_scope"]["cross_run"]["verdict"] == "veto"


def test_review_cross_run_that_does_not_replicate_escalates():
    out = si.review(_proposal(), invoke_fn=_invoke(
        {"feasibility_reviewer": ["veto", "pass"],
         "risk_scope_reviewer": "pass"}))
    assert out["verdict"] == "inconclusive" and out["escalated"] is True


def test_review_fails_open_to_inconclusive_never_veto():
    out = si.review(_proposal(), invoke_fn=_invoke(
        {"feasibility_reviewer": RuntimeError("cli down"),
         "risk_scope_reviewer": "pass"}))
    assert out["feasibility"]["verdict"] == "inconclusive"
    assert out["feasibility"]["parse_ok"] is False
    assert out["verdict"] == "pass"  # pass + inconclusive -> pass


def test_review_off_enum_verdict_is_not_coerced():
    def fn(vendor, prompt, *, timeout_s, role, **kw):
        return {"text": json.dumps({"verdict": "probably fine"}),
                "exit_code": 0, "error": None}
    out = si.review(_proposal(), invoke_fn=fn)
    assert out["verdict"] == "inconclusive"
    assert "off-enum" in out["feasibility"]["reasoning"]


def test_review_refuses_to_spawn_real_clis_under_mock_llm(monkeypatch):
    monkeypatch.setenv("MOCK_LLM", "1")
    with pytest.raises(ValueError, match="MOCK_LLM"):
        si.review(_proposal())


# ── stage 4: the bounded loop ────────────────────────────────────────────────

def _plan(tmp_path, verdicts, **over):
    kwargs = dict(
        evidence={"digest": "EVIDENCE DIGEST\n  - loop_stalled x3"},
        propose_fn=_propose_fn(),
        revise_fn=lambda proposal, critiques, rnd: json.dumps(
            {**proposal, "title": f"{proposal['title']} r{rnd}"}),
        invoke_fn=_invoke(verdicts),
        run_log=lambda *a, **k: None,
        **_emit_dirs(tmp_path),
    )
    kwargs.update(over)
    return si.plan_improvement(**kwargs)


def test_plan_exhausts_three_rounds_then_refuses_to_emit(tmp_path):
    report = _plan(tmp_path, {"feasibility_reviewer": ["veto"] * 3,
                              "risk_scope_reviewer": ["veto"] * 3},
                   emit=True, run_test=lambda p: (1, ""))
    assert report["approved"] is False and report["emitted"] is False
    assert report["rounds_used"] == si.MAX_IMPROVE_ROUNDS == 3
    assert len(report["transcript"]) == 3
    assert "no frontier pass in 3 round(s)" in report["reason"]
    # Two revisions happened between the three reviews.
    assert report["proposal"]["title"].endswith("r1 r2")
    # Nothing was written: no packet, no test file, no queue row.
    assert not (tmp_path / "packets").exists()
    assert not (tmp_path / "tests").exists()
    assert not (tmp_path / "authorize_fix_queue.jsonl").exists()


def test_plan_inconclusive_never_reaches_emit(tmp_path):
    report = _plan(tmp_path, {"feasibility_reviewer": ["inconclusive"] * 3,
                              "risk_scope_reviewer": ["inconclusive"] * 3},
                   emit=True, run_test=lambda p: (1, ""))
    assert report["approved"] is False and report["emitted"] is False
    assert report["transcript"][-1]["verdict"] == "inconclusive"


def test_plan_stops_at_the_first_pass(tmp_path):
    report = _plan(tmp_path, {"feasibility_reviewer": ["veto", "pass"],
                              "risk_scope_reviewer": ["veto", "pass"]})
    assert report["approved"] is True and report["rounds_used"] == 2
    assert report["emitted"] is False  # emit not requested
    assert "emit not requested" in report["reason"]


@pytest.mark.parametrize("bad", [0, 4, 99, -1, "3", 2.0])
def test_max_rounds_cap_is_hard_never_clamped(bad):
    with pytest.raises(ValueError, match="cap is hard"):
        si.plan_improvement(max_rounds=bad, evidence={"digest": "d"},
                            propose_fn=_propose_fn(),
                            invoke_fn=_invoke({"feasibility_reviewer": "pass",
                                               "risk_scope_reviewer": "pass"}))


def test_dry_run_writes_absolutely_nothing(tmp_path):
    logged: list = []
    report = _plan(tmp_path, {"feasibility_reviewer": "pass",
                              "risk_scope_reviewer": "pass"},
                   dry_run=True, emit=True, run_test=lambda p: (1, ""),
                   run_log=lambda *a, **k: logged.append(a))
    assert report["approved"] is True and report["emitted"] is False
    assert "dry_run" in report["reason"]
    assert logged == []                                   # not even a run-log row
    assert list(tmp_path.iterdir()) == []


# ── stage 5: the scope gate ──────────────────────────────────────────────────

@pytest.mark.parametrize("path,tier", [
    ("orchestrator/nara.py", "S"),
    ("orchestrator/tool_registry.py", "S"),
    ("schema/task_packet.schema.json", "S"),
    ("schema/", "S"),
    ("run_state/week1.run.jsonl", "S"),
    ("CLAUDE.md", "S"),
    ("DECISIONS.md", "S"),
    ("cron/serve-models.sh", "S"),
    ("ui/src/App.tsx", "S"),
    ("agent/prompts/ui_session.md", "S"),
    ("orchestrator/coordinator.py", "untiered"),
    ("setup.py", "untiered"),
    ("../elsewhere/thing.py", "outside-repo"),
])
def test_scope_gate_refuses_everything_outside_tier_p(tmp_path, path, tier):
    # The gate is mechanical and reports the tier it matched, per path.
    assert si.scope_violations([path]) == [
        {"path": path if tier == "outside-repo" else path.rstrip("/"),
         "tier": tier, "reason": si.scope_violations([path])[0]["reason"]}]
    proposal = _proposal(files_in_scope=[path])
    with pytest.raises(si.ScopeRefusal) as exc:
        si.emit_packet(proposal, run_test=lambda p: (1, ""), **_emit_dirs(tmp_path))
    assert path.rstrip("/") in str(exc.value)
    assert f"({tier}:" in str(exc.value)
    assert not (tmp_path / "packets").exists()
    assert not (tmp_path / "tests").exists()


@pytest.mark.parametrize("path", ["workers/x.py", "tools/x.sh", "tests/test_x.py",
                                  "docs/x.md", "bench/x.py", "experiments/x.py"])
def test_scope_gate_admits_tier_p(path):
    assert si.scope_violations([path]) == []


def test_scope_gate_names_every_offender(tmp_path):
    proposal = _proposal(files_in_scope=["orchestrator/nara.py", "workers/ok.py",
                                         "schema/x.json"])
    with pytest.raises(si.ScopeRefusal) as exc:
        si.emit_packet(proposal, run_test=lambda p: (1, ""), **_emit_dirs(tmp_path))
    assert "orchestrator/nara.py" in str(exc.value)
    assert "schema/x.json" in str(exc.value)
    assert "workers/ok.py" not in str(exc.value)


def test_scope_gate_refuses_a_pinned_version_string(tmp_path):
    proposal = _proposal(change="bump the image to vllm/vllm-openai:v0.21.0")
    with pytest.raises(si.ScopeRefusal, match="version pin"):
        si.emit_packet(proposal, run_test=lambda p: (1, ""), **_emit_dirs(tmp_path))


def test_packet_with_nothing_but_the_test_in_scope_is_refused(tmp_path):
    proposal = _proposal(files_in_scope=["tests/test_near_miss_digest.py"])
    with pytest.raises(ValueError, match="nothing to edit"):
        si.emit_packet(proposal, run_test=lambda p: (1, ""), **_emit_dirs(tmp_path))


# ── stage 6: red-first, PROVEN ───────────────────────────────────────────────

def test_emit_refuses_when_the_acceptance_test_passes(tmp_path):
    dirs = _emit_dirs(tmp_path)
    logged: list = []
    out = si.emit_packet(_proposal(), run_test=lambda p: (0, "1 passed"),
                         run_log=lambda ev, **k: logged.append(ev), **dirs)
    assert out["emitted"] is False
    assert out["reason"] == "acceptance test is not red"
    assert out["test_rc"] == 0
    # The file is removed, no packet is written, no queue row is enqueued.
    assert list(dirs["tests_dir"].iterdir()) == []
    assert not dirs["packets_dir"].exists()
    assert not dirs["queue_path"].exists()
    assert logged and logged[0]["status"] == "refused"


@pytest.mark.parametrize("rc", [2, 3, 4, 5, 124])
def test_emit_refuses_a_collection_error_as_not_red(tmp_path, rc):
    dirs = _emit_dirs(tmp_path)
    out = si.emit_packet(_proposal(), run_test=lambda p: (rc, "ERROR collecting"),
                         run_log=lambda *a, **k: None, **dirs)
    assert out["emitted"] is False
    assert out["reason"].startswith("acceptance test is not red")
    assert f"exit code {rc}" in out["reason"]
    assert list(dirs["tests_dir"].iterdir()) == []
    assert not dirs["packets_dir"].exists()


def test_emit_writes_the_test_and_runs_it_before_emitting(tmp_path):
    dirs = _emit_dirs(tmp_path)
    seen: list = []

    def run_test(path: Path):
        # The dispatcher's red-first check is PROVEN here: the file exists and
        # carries the proposal's source at the moment it is run.
        seen.append((Path(path).exists(), Path(path).read_text()))
        return 1, "1 failed"

    out = si.emit_packet(_proposal(), run_test=run_test,
                         run_log=lambda *a, **k: None, **dirs)
    assert seen == [(True, _proposal()["acceptance_test_source"])]
    assert out["emitted"] is True and out["test_rc"] == 1
    assert (dirs["tests_dir"] / "test_near_miss_digest.py").exists()


def test_emit_refuses_to_clobber_an_existing_test(tmp_path):
    dirs = _emit_dirs(tmp_path)
    dirs["tests_dir"].mkdir()
    (dirs["tests_dir"] / "test_near_miss_digest.py").write_text("# mine\n")
    with pytest.raises(ValueError, match="already exists"):
        si.emit_packet(_proposal(), run_test=lambda p: (1, ""), **dirs)
    assert (dirs["tests_dir"] / "test_near_miss_digest.py").read_text() == "# mine\n"


def test_emit_packet_dry_run_writes_nothing(tmp_path):
    dirs = _emit_dirs(tmp_path)
    out = si.emit_packet(_proposal(), dry_run=True,
                         run_test=lambda p: pytest.fail("must not run"), **dirs)
    assert out["emitted"] is False and out["scope_ok"] is True
    assert out["packet_id"] == "PKT-SELF-digest-the-repeated-near-miss-reason"
    assert list(tmp_path.iterdir()) == []


# ── stage 7: the emitted artifacts ───────────────────────────────────────────

def _emit_ok(tmp_path, proposal=None):
    dirs = _emit_dirs(tmp_path)
    out = si.emit_packet(proposal or _proposal(), run_test=lambda p: (1, "1 failed"),
                         run_log=lambda *a, **k: None, **dirs)
    assert out["emitted"] is True
    return out, dirs


def test_emitted_packet_validates_against_the_real_schema(tmp_path):
    out, _ = _emit_ok(tmp_path)
    packet = json.loads(Path(out["packet_path"]).read_text())
    jsonschema.validate(instance=packet,
                        schema=json.loads(si.SCHEMA_PATH.read_text()))
    pd._validate_packet(packet)  # the dispatcher's own gate accepts it
    assert packet["task_id"] == out["packet_id"]
    assert packet["acceptance_criteria"]["must_fail_before"] is True
    assert packet["budgets"] == {"max_attempts": 2, "wall_clock_minutes": 20,
                                 "max_diff_lines": 200}
    # The acceptance test is OUT of the agent's scope: it may not weaken it.
    assert "tests/test_near_miss_digest.py" in packet["files_out_of_scope"]
    assert "tests/test_near_miss_digest.py" not in packet["files_in_scope"]
    assert any("outside files_in_scope" in a for a in packet["forbidden_actions"])
    assert packet["rollback"]["branch_delete"] is True
    assert "COMMIT it before dispatch" in packet["rollback"]["notes"]


def test_emitted_test_cmd_uses_an_absolute_interpreter(tmp_path):
    out, _ = _emit_ok(tmp_path)
    packet = json.loads(Path(out["packet_path"]).read_text())
    cmd = packet["acceptance_criteria"]["test_cmd"]
    assert cmd.startswith("MOCK_LLM=1 ")
    interpreter = cmd.split()[1]
    assert os.path.isabs(interpreter), cmd
    assert interpreter.endswith("/.venv-chroma/bin/python")
    assert "-m pytest tests/test_near_miss_digest.py -x -q" in cmd


def test_queue_row_is_consumed_by_the_dispatcher(tmp_path):
    out, dirs = _emit_ok(tmp_path)
    rows = [json.loads(ln) for ln in
            dirs["queue_path"].read_text().splitlines() if ln.strip()]
    assert len(rows) == 1
    assert rows[0]["outcome"] == "authorize_fix"
    assert rows[0]["status"] == "enqueued"
    assert rows[0]["authorized_by"] == "self_improve"

    packets = pd.consume_authorize_fix_queue(dirs["queue_path"])
    assert len(packets) == 1
    assert packets[0]["task_id"] == out["packet_id"]
    pd._validate_packet(packets[0])


def test_packet_id_is_schema_legal_for_an_awkward_title(tmp_path):
    out, _ = _emit_ok(tmp_path, _proposal(title="  !!! 3 fixes: A/B & C  "))
    assert out["packet_id"] == "PKT-SELF-3-fixes-A-B-C"
    jsonschema.validate(
        instance=json.loads(Path(out["packet_path"]).read_text()),
        schema=json.loads(si.SCHEMA_PATH.read_text()))


def test_plan_end_to_end_emits_on_a_pass(tmp_path):
    logged: list = []
    report = _plan(tmp_path, {"feasibility_reviewer": "pass",
                              "risk_scope_reviewer": "pass"},
                   emit=True, run_test=lambda p: (1, "1 failed"),
                   run_log=lambda ev, **k: logged.append(ev))
    assert report["approved"] is True and report["emitted"] is True
    assert Path(report["emit"]["packet_path"]).exists()
    assert (tmp_path / "authorize_fix_queue.jsonl").exists()
    assert {e["status"] for e in logged} >= {"passed"}
    assert all(e["task_id"].startswith("self_improve:") for e in logged)
