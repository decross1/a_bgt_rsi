"""Loop v1 integration tests — the SERIAL INTEGRATOR's wiring assertions.

These exercise the spine wiring in orchestrator/nara.run_iteration for the
four Loop v1 components:

  - Step 1.5 meta_review pre-step  -> conditioning bullets injected into the
                                      initial user message + stored under
                                      record["meta_review"].
  - Step 2.5 redteam_critic        -> deterministic retry sub-loop; final
                                      result + retries_used stored under
                                      record["redteam"]; a "fatal_flaw" with
                                      retries left re-calls hypothesize and
                                      overwrites the cached hypothesis.
  - Step 8 gate_status             -> record["gate_status"] == "pending" at
                                      finalize.
  - Step 5 cross_tier_comparison   -> kwarg threaded into
                                      record["cross_tier_comparison"].

Plus a schema-level check that the four new optional blocks validate and
that old (pre-v1) rows lacking them still validate.

The LLM and the runtime are fully faked so the test is self-contained and
runs under MOCK_LLM with no live backend and no writes to real state files.
finalize_iteration_record is monkeypatched to CAPTURE the record (and still
schema-validate it) instead of appending to the real loop_memory.jsonl.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest

from orchestrator import nara

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads(
    (REPO_ROOT / "schema" / "iteration_record.schema.json").read_text()
)
_VALIDATOR = jsonschema.Draft7Validator(SCHEMA)


# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------
class _FakeFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, name, arguments, idx):
        self.id = f"call_{idx}"
        self.type = "function"
        self.function = _FakeFunction(name, json.dumps(arguments))


class _FakeMessage:
    def __init__(self, content, tool_calls):
        self.content = content
        self.tool_calls = tool_calls


class _FakeResp:
    def __init__(self, content, tool_calls):
        self.choices = [SimpleNamespace(message=_FakeMessage(content, tool_calls))]
        self.model = "fake-model"
        self.usage = SimpleNamespace(prompt_tokens=1, completion_tokens=1)


class _FakeBackend:
    name = "fake-backend"
    default_model = "fake-model"
    model_version = "fake-1.0"
    host_metadata = {"host": "test"}

    def __init__(self, scripted):
        # scripted: list of (content, [(tool_name, args), ...] | None)
        self._scripted = list(scripted)
        self._i = 0

    def create_chat(self, **kwargs):
        content, calls = self._scripted[self._i]
        self._i += 1
        tcs = None
        if calls:
            tcs = [_FakeToolCall(n, a, j) for j, (n, a) in enumerate(calls)]
        return _FakeResp(content, tcs)


class _FakeRuntime:
    """Captures state writes/events; dispatches tools from a scripted table."""

    def __init__(self, tool_results):
        # tool_results: dict tool_name -> list of worker-contract dicts
        #               (popped in call order so re-hypothesize can differ).
        self._tool_results = {k: list(v) for k, v in tool_results.items()}
        self.events = []
        self.dispatched = []

    def write_state(self, path, state):
        pass

    def delete_state(self, path):
        pass

    def log_event(self, event):
        self.events.append(event)

    def dispatch_tool(self, name, args, *, parent_request_id):
        self.dispatched.append((name, args))
        queue = self._tool_results.get(name)
        if queue:
            return queue.pop(0)
        return {"status": "passed", "result": {}, "errors": []}


def _hyp_result(text):
    return {
        "status": "passed",
        "result": {"text": text, "candidates_considered": 1,
                   "all_candidates": [text]},
        "errors": [],
    }


def _journal_result():
    return {
        "status": "passed",
        "result": {"journal_entry_path": "journal/iterations/999.md"},
        "errors": [],
    }


def _redteam(verdict, critique="", confidence=0.5):
    return {
        "status": "passed",
        "result": {
            "verdict": verdict,
            "critique": critique,
            "suggested_revision": critique if verdict == "fatal_flaw" else None,
            "confidence": confidence,
            "subagent_turns_used": 1,
            "subagent_wall_seconds": 0.1,
            "subagent_status": "passed",
            "subagent_backend": "fake-backend",
            "subagent_model": "fake-model",
        },
        "errors": [],
        "wrapper_request_id": None,
        "parent_request_id": None,
    }


@pytest.fixture
def captured_record(monkeypatch):
    """Run run_iteration with fakes; capture the record handed to finalize."""
    box = {}

    def _fake_finalize(record):
        # Still schema-validate — a wiring bug that produces an invalid
        # record must fail the test, not be silently swallowed.
        errs = list(_VALIDATOR.iter_errors(record))
        assert not errs, f"record invalid: {errs[0].message}"
        box["record"] = record
        return {"status": "passed", "loop_memory_path": "x",
                "iteration_id": record["iteration_id"]}

    monkeypatch.setattr(nara, "finalize_iteration_record", _fake_finalize)
    # Deterministic iteration id (avoid reading real loop_memory.jsonl).
    monkeypatch.setattr(nara, "_next_iteration_id",
                        lambda *a, **k: "iter-2026-06-05-001")
    return box


def _full_chain_script():
    """Five-step happy path: one assistant turn per tool, then a final
    no-tool summary turn."""
    return [
        ("Hypothesizing.", [("hypothesize", {"topic": "t"})]),
        ("Retrieving.", [("retrieve_literature", {"hypothesis_text": "h", "k": 10})]),
        ("Classifying.", [("novelty_classify", {"hypothesis_text": "h", "iteration_id": "i"})]),
        ("Critiquing.", [("critic_loop_v0", {"hypothesis_text": "h", "iteration_id": "i"})]),
        ("Journaling.", [("journal_writer", {"topic": "t", "iteration_id": "i", "nara_summary": "s"})]),
        ("Final summary of the iteration.", None),
    ]


def _tool_table():
    return {
        "hypothesize": [_hyp_result("H1 original hypothesis")],
        "retrieve_literature": [{"status": "passed",
                                 "result": {"k": 0, "neighbors": []}, "errors": []}],
        "novelty_classify": [{"status": "passed",
                              "result": {"class": "novel", "rationale": "r",
                                         "top_neighbor_id": None}, "errors": []}],
        "critic_loop_v0": [{"status": "passed",
                            "result": {"verdict": "survives", "rationale": "r",
                                       "contradicting_paper_id": None}, "errors": []}],
        "journal_writer": [_journal_result()],
    }


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------
def test_schema_accepts_new_blocks_and_old_rows():
    """The four new blocks validate; a pre-v1 row lacking them still validates."""
    base = {
        "iteration_id": "iter-2026-06-05-001",
        "started_at": "2026-06-05T00:00:00Z",
        "ended_at": "2026-06-05T00:01:00Z",
        "seed": {"topic": "t", "source": "human_cli"},
        "nara_summary": "s",
        "tool_calls_made": ["journal_writer"],
        "journal_entry_path": "journal/iterations/999.md",
        "model_version": "v",
        "wrapper_call_ids": [],
    }
    # Old row (no new blocks) is still valid — required[] was not touched.
    _VALIDATOR.validate(base)

    enriched = dict(base)
    enriched["redteam"] = {"verdict": "proceed", "critique": "c",
                           "suggested_revision": None, "confidence": 0.9,
                           "retries_used": 0, "subagent_status": "passed"}
    enriched["meta_review"] = {"conditioning_bullets": ["a", "b", "c"],
                               "rows_considered": 3}
    enriched["gate_status"] = "pending"
    enriched["cross_tier_comparison"] = {"claim": "x", "agreement": True}
    _VALIDATOR.validate(enriched)

    # gate_status enum is enforced (never coerced).
    bad = dict(base)
    bad["gate_status"] = "approved"
    with pytest.raises(jsonschema.ValidationError):
        _VALIDATOR.validate(bad)


def test_happy_path_wires_all_four(monkeypatch, captured_record):
    captured_user = {}

    def _meta(**kwargs):
        return {"status": "passed",
                "result": {"conditioning_bullets": ["keep X", "stop Y", "Z surprised"],
                           "rows_considered": 4},
                "errors": [], "wrapper_request_id": None, "parent_request_id": None}

    monkeypatch.setattr(nara, "_meta_review", _meta)
    monkeypatch.setattr(nara, "_redteam_critic",
                        lambda *a, **k: _redteam("proceed"))
    monkeypatch.setattr(nara, "get_backend",
                        lambda b: _FakeBackend(_full_chain_script()))
    monkeypatch.setattr(nara.iteration_cache, "write_entry", lambda *a, **k: None)

    rt = _FakeRuntime(_tool_table())
    rec = nara.run_iteration("test topic", runtime=rt)

    # Step 8 gate.
    assert rec["gate_status"] == "pending"
    # Step 1.5 meta_review stored.
    assert rec["meta_review"]["conditioning_bullets"] == ["keep X", "stop Y", "Z surprised"]
    # Step 2.5 redteam stored with retries_used.
    assert rec["redteam"]["verdict"] == "proceed"
    assert rec["redteam"]["retries_used"] == 0
    # The full chain captured.
    assert "hypothesis" in rec and "critique" in rec
    captured_record["record"] is rec


def test_meta_review_bullets_injected_into_user_message(monkeypatch, captured_record):
    seen = {}

    def _meta(**kwargs):
        return {"status": "passed",
                "result": {"conditioning_bullets": ["BULLET_ALPHA", "BULLET_BETA", "BULLET_GAMMA"],
                           "rows_considered": 4},
                "errors": [], "wrapper_request_id": None, "parent_request_id": None}

    class _SpyBackend(_FakeBackend):
        def create_chat(self, **kwargs):
            # Capture the user message on the FIRST turn only.
            if "first_user" not in seen:
                for m in kwargs["messages"]:
                    if m["role"] == "user":
                        seen["first_user"] = m["content"]
                        break
            return super().create_chat(**kwargs)

    monkeypatch.setattr(nara, "_meta_review", _meta)
    monkeypatch.setattr(nara, "_redteam_critic", lambda *a, **k: _redteam("proceed"))
    monkeypatch.setattr(nara, "get_backend",
                        lambda b: _SpyBackend(_full_chain_script()))
    monkeypatch.setattr(nara.iteration_cache, "write_entry", lambda *a, **k: None)

    nara.run_iteration("test topic", runtime=_FakeRuntime(_tool_table()))
    assert "Prior-iteration conditioning:" in seen["first_user"]
    assert "- BULLET_ALPHA" in seen["first_user"]


def test_meta_review_failure_degrades_gracefully(monkeypatch, captured_record):
    """A meta_review crash must not crash the chain; a fallback is logged."""
    def _boom(**kwargs):
        raise RuntimeError("meta_review exploded")

    monkeypatch.setattr(nara, "_meta_review", _boom)
    monkeypatch.setattr(nara, "_redteam_critic", lambda *a, **k: _redteam("proceed"))
    monkeypatch.setattr(nara, "get_backend",
                        lambda b: _FakeBackend(_full_chain_script()))
    monkeypatch.setattr(nara.iteration_cache, "write_entry", lambda *a, **k: None)

    rt = _FakeRuntime(_tool_table())
    rec = nara.run_iteration("test topic", runtime=rt)
    # Chain still completed; meta_review block omitted from the record.
    assert "meta_review" not in rec
    assert rec["gate_status"] == "pending"
    assert any(e.get("event_type") == "loop_v0_fallback"
               and "meta_review" in e.get("note", "") for e in rt.events)


def test_redteam_fatal_flaw_retries_and_overwrites(monkeypatch, captured_record):
    """fatal_flaw with retries left re-calls hypothesize, overwrites the
    cached hypothesis, caps at 2 retries; final result records retries_used."""
    monkeypatch.setattr(nara, "_meta_review",
                        lambda **k: {"status": "error", "result": None,
                                     "errors": ["empty"], "wrapper_request_id": None,
                                     "parent_request_id": None})

    # Always fatal_flaw -> should retry exactly twice (cap) then stop.
    monkeypatch.setattr(nara, "_redteam_critic",
                        lambda *a, **k: _redteam("fatal_flaw", "kill it"))
    monkeypatch.setattr(nara, "get_backend",
                        lambda b: _FakeBackend(_full_chain_script()))

    cache_writes = []
    monkeypatch.setattr(nara.iteration_cache, "write_entry",
                        lambda iid, key, val: cache_writes.append((key, val)))

    # hypothesize returns distinct texts on each (re)call.
    table = _tool_table()
    table["hypothesize"] = [
        _hyp_result("H1 original"),
        _hyp_result("H2 revised"),
        _hyp_result("H3 revised again"),
    ]
    rt = _FakeRuntime(table)
    rec = nara.run_iteration("test topic", runtime=rt)

    # Two retries (cap), so hypothesize dispatched: 1 initial (via tool_call)
    # + 2 retries = 3 total.
    hyp_dispatches = [d for d in rt.dispatched if d[0] == "hypothesize"]
    assert len(hyp_dispatches) == 3
    assert rec["redteam"]["verdict"] == "fatal_flaw"
    assert rec["redteam"]["retries_used"] == 2
    # Final cached/recorded hypothesis is the last revision.
    assert rec["hypothesis"]["text"] == "H3 revised again"
    # Retry events logged (inviolate rule 7 — fallbacks/selections logged).
    assert sum(1 for e in rt.events
               if e.get("event_type") == "loop_v0_redteam_retry") == 2


def test_cross_tier_comparison_threaded(monkeypatch, captured_record):
    comparison = {"claim": "c", "mechanism_a": {"supports": True},
                  "mechanism_b": {"supports": True}, "agreement": True,
                  "diagnostic_note": "both agree"}
    monkeypatch.setattr(nara, "_meta_review",
                        lambda **k: {"status": "error", "result": None,
                                     "errors": ["e"], "wrapper_request_id": None,
                                     "parent_request_id": None})
    monkeypatch.setattr(nara, "_redteam_critic", lambda *a, **k: _redteam("proceed"))
    monkeypatch.setattr(nara, "get_backend",
                        lambda b: _FakeBackend(_full_chain_script()))
    monkeypatch.setattr(nara.iteration_cache, "write_entry", lambda *a, **k: None)

    rec = nara.run_iteration("test topic", runtime=_FakeRuntime(_tool_table()),
                             cross_tier_comparison=comparison)
    assert rec["cross_tier_comparison"] == comparison
