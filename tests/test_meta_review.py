"""Tests for workers.meta_review.

Stubs wrapper.call_sync via monkeypatch — never hits the real Gemma.
Writes loop_memory + loop_feedback fixtures to tmp_path so no shared
state is touched. Runs green under MOCK_LLM (call_sync is patched).
"""
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from workers import meta_review as mr_mod


@pytest.fixture(autouse=True)
def _hermetic_idea_ledger(tmp_path, monkeypatch):
    """D-060 hermeticity: meta_review appends idea-ledger conditioning lines
    from DEFAULT_IDEA_LEDGER — point it at a nonexistent tmp path so these
    tests never read the real repo ledger."""
    monkeypatch.setattr(mr_mod, "DEFAULT_IDEA_LEDGER",
                        tmp_path / "no_idea_ledger.jsonl")


def _fake_call_sync(completion_text: str, request_id: str = "req-mr"):
    def stub(messages, *, temperature=0.0, top_p=1.0, seed=None, max_tokens=None,
             caller_tag="unspecified", parent_request_id=None,
             retrieval_context=None, log_path=None, model=None):
        return {
            "request_id": request_id,
            "completion": completion_text,
            "model": "gemma-4-26b-a4b",
            "model_version": "test",
            "parent_request_id": parent_request_id,
            "caller_tag": caller_tag,
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "latency_ms": 100.0,
        }
    return stub


def _write_jsonl(path: Path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def _memory_rows(k=6):
    rows = []
    for i in range(1, k + 1):
        iid = f"iter-2026-06-0{i}-001"
        rows.append({
            "iteration_id": iid,
            "seed": {"topic": f"topic {i}"},
            "hypothesis": {"text": f"Hypothesis number {i} about cooperation."},
            "novelty": {"class": "incremental" if i % 2 else "novel"},
            "critique": {"verdict": "valid" if i % 2 else "needs_revision"},
            "experiment_outcome": {"summary": f"outcome summary {i}"} if i == 3 else None,
        })
    return rows


_GOOD_COMPLETION = json.dumps({
    "conditioning_bullets": [
        "Verbatim sharp hypotheses kept winning; keep human framing intact.",
        "Paraphrased seeds the human marked invalid kept losing — avoid them.",
        "Vickrey rediscovery surprised: 100% truthful bidding emerged.",
    ]
})


def test_three_to_five_bullets_and_rows_considered(monkeypatch, tmp_path):
    mem = tmp_path / "loop_memory.jsonl"
    fb = tmp_path / "loop_feedback.jsonl"
    _write_jsonl(mem, _memory_rows(6))
    _write_jsonl(fb, [
        {"iteration_id": "iter-2026-06-02-001", "verdict": "invalid",
         "note": "phrasing artifact", "gated_at": "2026-06-02T00:00:00Z", "gated_by": "human"},
        {"iteration_id": "iter-2026-06-03-001", "verdict": "valid",
         "note": "ok", "gated_at": "2026-06-03T00:00:00Z", "gated_by": "human"},
    ])
    monkeypatch.setattr(mr_mod, "call_sync", _fake_call_sync(_GOOD_COMPLETION, "req-1"))

    out = mr_mod.meta_review(n=8, loop_memory_path=mem, feedback_path=fb,
                             parent_request_id="par-1")
    assert out["status"] == "passed"
    assert out["wrapper_request_id"] == "req-1"
    assert out["parent_request_id"] == "par-1"
    bullets = out["result"]["conditioning_bullets"]
    assert 3 <= len(bullets) <= 5
    assert out["result"]["rows_considered"] > 0
    assert out["result"]["rows_considered"] == 6


def test_missing_feedback_file_does_not_crash(monkeypatch, tmp_path):
    mem = tmp_path / "loop_memory.jsonl"
    _write_jsonl(mem, _memory_rows(6))
    missing_fb = tmp_path / "does_not_exist.jsonl"
    assert not missing_fb.exists()
    monkeypatch.setattr(mr_mod, "call_sync", _fake_call_sync(_GOOD_COMPLETION))

    out = mr_mod.meta_review(n=8, loop_memory_path=mem, feedback_path=missing_fb)
    assert out["status"] == "passed"
    assert 3 <= len(out["result"]["conditioning_bullets"]) <= 5
    assert out["result"]["rows_considered"] == 6


def test_tail_respects_n(monkeypatch, tmp_path):
    mem = tmp_path / "loop_memory.jsonl"
    _write_jsonl(mem, _memory_rows(6))
    monkeypatch.setattr(mr_mod, "call_sync", _fake_call_sync(_GOOD_COMPLETION))
    out = mr_mod.meta_review(n=2, loop_memory_path=mem,
                             feedback_path=tmp_path / "nope.jsonl")
    assert out["status"] == "passed"
    assert out["result"]["rows_considered"] == 2


def test_caps_bullets_at_five(monkeypatch, tmp_path):
    mem = tmp_path / "loop_memory.jsonl"
    _write_jsonl(mem, _memory_rows(6))
    completion = json.dumps({"conditioning_bullets": [f"b{i}" for i in range(8)]})
    monkeypatch.setattr(mr_mod, "call_sync", _fake_call_sync(completion))
    out = mr_mod.meta_review(loop_memory_path=mem, feedback_path=tmp_path / "x.jsonl")
    assert out["status"] == "passed"
    assert len(out["result"]["conditioning_bullets"]) == 5


def test_too_few_bullets_is_error(monkeypatch, tmp_path):
    mem = tmp_path / "loop_memory.jsonl"
    _write_jsonl(mem, _memory_rows(6))
    completion = json.dumps({"conditioning_bullets": ["only one"]})
    monkeypatch.setattr(mr_mod, "call_sync", _fake_call_sync(completion))
    out = mr_mod.meta_review(loop_memory_path=mem, feedback_path=tmp_path / "x.jsonl")
    assert out["status"] == "error"
    assert out["result"] is None


def test_empty_memory_is_error(monkeypatch, tmp_path):
    mem = tmp_path / "loop_memory.jsonl"
    mem.write_text("")
    monkeypatch.setattr(mr_mod, "call_sync", _fake_call_sync(_GOOD_COMPLETION))
    out = mr_mod.meta_review(loop_memory_path=mem, feedback_path=tmp_path / "x.jsonl")
    assert out["status"] == "error"
    assert any("no iteration_records" in e for e in out["errors"])


def test_handles_none_nested_fields(monkeypatch, tmp_path):
    # Real loop_memory rows leave hypothesis/novelty/critique as None.
    mem = tmp_path / "loop_memory.jsonl"
    _write_jsonl(mem, [{
        "iteration_id": "iter-2026-05-26-001",
        "seed": {"topic": "TfT dominance"},
        "hypothesis": None, "novelty": None, "critique": None,
        "experiment_outcome": None,
    }])
    monkeypatch.setattr(mr_mod, "call_sync", _fake_call_sync(_GOOD_COMPLETION))
    out = mr_mod.meta_review(loop_memory_path=mem, feedback_path=tmp_path / "x.jsonl")
    assert out["status"] == "passed"
    assert out["result"]["rows_considered"] == 1


def _constraint_row(cluster_id="cl-iter-2026-06-05-002"):
    """One design-constraint row as workers.constraint_distill writes it —
    frontier text carried as provenance-tagged annotation."""
    return {
        "constraint_id": "dc-testrow",
        "ts": "2026-08-19T00:00:00Z",
        "cluster_id": cluster_id,
        "claim_head": "Convergence of LLM agents to the payoff-dominant "
                      "equilibrium in a ring-network stag hunt",
        "flaw_class": "missing_control",
        "flaw_class_all": ["missing_control", "no_evidence"],
        "missing_controls": ["a well-mixed or complete-graph baseline",
                             "an ablation removing neighbor observability"],
        "source": {"kind": "frontier_screen", "role": "methods_reviewer",
                   "vendor_or_model": "claude", "verdict": "veto",
                   "verbatim_quote": "Missing controls include a well-mixed "
                                     "or complete-graph baseline."},
        "status": "active",
    }


def _armed_env(monkeypatch, tmp_path, value="1"):
    """Point meta_review at a tmp constraint store and arm the DARK gate."""
    store = tmp_path / "design_constraints.jsonl"
    _write_jsonl(store, [_constraint_row()])
    monkeypatch.setattr(mr_mod, "DEFAULT_DESIGN_CONSTRAINTS", store)
    monkeypatch.setenv(mr_mod.CONSTRAINT_GATE_ENV, value)
    return store


def test_constraint_conditioning_is_off_by_default(monkeypatch, tmp_path, capsys):
    """DARK by default: the env var unset means no constraint bullets, and
    the gate state is LOGGED either way."""
    monkeypatch.delenv(mr_mod.CONSTRAINT_GATE_ENV, raising=False)
    store = tmp_path / "design_constraints.jsonl"
    _write_jsonl(store, [_constraint_row()])
    monkeypatch.setattr(mr_mod, "DEFAULT_DESIGN_CONSTRAINTS", store)
    mem = tmp_path / "loop_memory.jsonl"
    rows = _memory_rows(3)
    rows[-1]["seed"] = {"topic": "ring network stag hunt convergence imitation"}
    _write_jsonl(mem, rows)
    monkeypatch.setattr(mr_mod, "call_sync", _fake_call_sync(_GOOD_COMPLETION))

    out = mr_mod.meta_review(loop_memory_path=mem, feedback_path=tmp_path / "x.jsonl")
    assert out["status"] == "passed"
    assert out["result"]["constraint_conditioning"] == "off"
    assert not any("[constraint from" in b
                   for b in out["result"]["conditioning_bullets"])
    assert "design-constraint conditioning: OFF" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["0", "false", "off", "", "no"])
def test_falsey_gate_values_stay_dark(monkeypatch, tmp_path, value):
    _armed_env(monkeypatch, tmp_path, value)
    mem = tmp_path / "loop_memory.jsonl"
    rows = _memory_rows(3)
    rows[-1]["seed"] = {"topic": "ring network stag hunt convergence imitation"}
    _write_jsonl(mem, rows)
    monkeypatch.setattr(mr_mod, "call_sync", _fake_call_sync(_GOOD_COMPLETION))

    out = mr_mod.meta_review(loop_memory_path=mem, feedback_path=tmp_path / "x.jsonl")
    assert out["result"]["constraint_conditioning"] == "off"
    assert not any("[constraint from" in b
                   for b in out["result"]["conditioning_bullets"])


def test_armed_gate_injects_labelled_constraint_bullets(monkeypatch, tmp_path, capsys):
    _armed_env(monkeypatch, tmp_path)
    mem = tmp_path / "loop_memory.jsonl"
    rows = _memory_rows(3)
    rows[-1]["seed"] = {"topic": "ring network stag hunt convergence imitation"}
    _write_jsonl(mem, rows)
    monkeypatch.setattr(mr_mod, "call_sync", _fake_call_sync(_GOOD_COMPLETION))

    out = mr_mod.meta_review(loop_memory_path=mem, feedback_path=tmp_path / "x.jsonl")
    assert out["status"] == "passed"
    assert out["result"]["constraint_conditioning"] == "on"
    bullets = out["result"]["conditioning_bullets"]
    labelled = [b for b in bullets if b.startswith("[constraint from ")]
    assert len(labelled) == 1
    assert "frontier_screen/methods_reviewer" in labelled[0]
    assert "well-mixed or complete-graph baseline" in labelled[0]
    # The model's own bullets are kept, not displaced.
    assert bullets[:3] == json.loads(_GOOD_COMPLETION)["conditioning_bullets"]
    assert "design-constraint conditioning: ON" in capsys.readouterr().err


def test_armed_gate_adds_nothing_off_topic(monkeypatch, tmp_path):
    _armed_env(monkeypatch, tmp_path)
    mem = tmp_path / "loop_memory.jsonl"
    rows = _memory_rows(3)
    rows[-1]["seed"] = {"topic": "differential privacy accountant tightness"}
    _write_jsonl(mem, rows)
    monkeypatch.setattr(mr_mod, "call_sync", _fake_call_sync(_GOOD_COMPLETION))

    out = mr_mod.meta_review(loop_memory_path=mem, feedback_path=tmp_path / "x.jsonl")
    assert out["result"]["constraint_conditioning"] == "on"
    assert not any("[constraint from" in b
                   for b in out["result"]["conditioning_bullets"])


def test_armed_gate_with_missing_store_does_not_break(monkeypatch, tmp_path):
    monkeypatch.setattr(mr_mod, "DEFAULT_DESIGN_CONSTRAINTS",
                        tmp_path / "absent.jsonl")
    monkeypatch.setenv(mr_mod.CONSTRAINT_GATE_ENV, "1")
    mem = tmp_path / "loop_memory.jsonl"
    _write_jsonl(mem, _memory_rows(3))
    monkeypatch.setattr(mr_mod, "call_sync", _fake_call_sync(_GOOD_COMPLETION))

    out = mr_mod.meta_review(loop_memory_path=mem, feedback_path=tmp_path / "x.jsonl")
    assert out["status"] == "passed"
    assert out["result"]["constraint_conditioning"] == "on"


def test_wrapper_exception_returns_error(monkeypatch, tmp_path):
    mem = tmp_path / "loop_memory.jsonl"
    _write_jsonl(mem, _memory_rows(6))

    def broken(*a, **kw):
        raise ConnectionError("vllm unreachable")
    monkeypatch.setattr(mr_mod, "call_sync", broken)
    out = mr_mod.meta_review(loop_memory_path=mem, feedback_path=tmp_path / "x.jsonl")
    assert out["status"] == "error"
    assert any("vllm unreachable" in e for e in out["errors"])
    assert out["result"] is None
