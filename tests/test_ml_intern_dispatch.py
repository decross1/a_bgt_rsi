"""Slice-2 ML-Intern dispatch wiring tests — the SERIAL INTEGRATOR's
spine assertions for the orchestrator-driven backfill in
orchestrator/nara.run_iteration.

The escalation path is DETERMINISTIC and orchestrator-driven (not a Nara
tool call). When retrieve_literature returns result.escalation.should_escalate
== True, nara must:
  - call workers.ml_intern EXACTLY once,
  - re-dispatch retrieve_literature when ml_intern stored >0 papers,
  - update captured["retrieval"] + the iteration cache from the re-run,
  - fire at most ONCE per iteration even if the re-run also escalates,
  - and NEVER crash the iteration when ml_intern errors / stores 0.

nara._ml_intern is monkeypatched as a SPY; the LLM and runtime are faked
(pattern lifted from tests/test_loop_v1_integration.py). Runs under
MOCK_LLM with no live backend.
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
# Fakes (mirror tests/test_loop_v1_integration.py)
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
    """Dispatches tools from a scripted per-name queue; records events."""

    def __init__(self, tool_results):
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


# --------------------------------------------------------------------------
# Result builders
# --------------------------------------------------------------------------
def _hyp_result(text="H1 hypothesis"):
    return {
        "status": "passed",
        "result": {"text": text, "candidates_considered": 1,
                   "all_candidates": [text]},
        "errors": [],
    }


def _retrieval(should_escalate, *, max_score=0.42, neighbor_id="seed-1"):
    """A retrieve_literature envelope with an escalation block."""
    return {
        "status": "passed",
        "result": {
            "k": 10,
            "neighbors": [{
                "doc_id": neighbor_id,
                "content_hash": "sha256:abc",
                "score": max_score,
                "source_layer": "foundational",
                "title": "t",
            }],
            "escalation": {
                "should_escalate": should_escalate,
                "max_score": max_score,
                "distinct_books": 1,
                "books": ["osborne_rubinstein"],
                "reason": "test",
            },
        },
        "errors": [],
    }


def _journal_result():
    return {
        "status": "passed",
        "result": {"journal_entry_path": "journal/iterations/999.md"},
        "errors": [],
    }


def _ml_intern_ok(papers_stored=4):
    return {
        "status": "passed",
        "result": {
            "query": "q",
            "papers_fetched": papers_stored,
            "papers_stored": papers_stored,
            "collection": "ml_intern_fetched",
            "escalated_from": "iter-2026-06-05-001",
        },
        "errors": [],
        "parent_request_id": None,
    }


def _ml_intern_err():
    return {
        "status": "error",
        "result": None,
        "errors": ["MLInternFetchError: S2 unreachable"],
        "parent_request_id": None,
    }


def _full_chain_script():
    return [
        ("Hypothesizing.", [("hypothesize", {"topic": "t"})]),
        ("Retrieving.", [("retrieve_literature", {"hypothesis_text": "h", "k": 10})]),
        ("Classifying.", [("novelty_classify", {"hypothesis_text": "h", "iteration_id": "i"})]),
        ("Critiquing.", [("critic_loop_v0", {"hypothesis_text": "h", "iteration_id": "i"})]),
        ("Journaling.", [("journal_writer", {"topic": "t", "iteration_id": "i", "nara_summary": "s"})]),
        ("Final summary.", None),
    ]


def _tool_table(retrieval_queue):
    return {
        "hypothesize": [_hyp_result()],
        "retrieve_literature": list(retrieval_queue),
        "novelty_classify": [{"status": "passed",
                              "result": {"class": "novel", "rationale": "r",
                                         "top_neighbor_id": None}, "errors": []}],
        "critic_loop_v0": [{"status": "passed",
                            "result": {"verdict": "survives", "rationale": "r",
                                       "contradicting_paper_id": None}, "errors": []}],
        "journal_writer": [_journal_result()],
    }


@pytest.fixture
def captured_record(monkeypatch):
    box = {}

    def _fake_finalize(record):
        errs = list(_VALIDATOR.iter_errors(record))
        assert not errs, f"record invalid: {errs[0].message}"
        box["record"] = record
        return {"status": "passed", "loop_memory_path": "x",
                "iteration_id": record["iteration_id"]}

    monkeypatch.setattr(nara, "finalize_iteration_record", _fake_finalize)
    monkeypatch.setattr(nara, "_next_iteration_id",
                        lambda *a, **k: "iter-2026-06-05-001")
    # Neutralize the two other orchestrator pre/sub-steps so this test
    # isolates the ml_intern wiring.
    monkeypatch.setattr(nara, "_meta_review",
                        lambda **k: {"status": "error", "result": None,
                                     "errors": ["skip"], "wrapper_request_id": None,
                                     "parent_request_id": None})
    monkeypatch.setattr(nara, "_redteam_critic",
                        lambda *a, **k: {"status": "passed",
                                         "result": {"verdict": "proceed", "critique": "",
                                                    "suggested_revision": None,
                                                    "confidence": 0.5},
                                         "errors": [], "wrapper_request_id": None,
                                         "parent_request_id": None})
    monkeypatch.setattr(nara.iteration_cache, "write_entry", lambda *a, **k: None)
    return box


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------
def test_escalation_calls_ml_intern_once_and_re_retrieves(monkeypatch, captured_record):
    """should_escalate=True -> ml_intern called once AND retrieve_literature
    re-dispatched; captured retrieval + cache updated from the re-run."""
    calls = []
    monkeypatch.setattr(nara, "_ml_intern",
                        lambda *a, **k: calls.append((a, k)) or _ml_intern_ok())
    monkeypatch.setattr(nara, "get_backend",
                        lambda b: _FakeBackend(_full_chain_script()))

    cache_writes = []
    monkeypatch.setattr(nara.iteration_cache, "write_entry",
                        lambda iid, key, val: cache_writes.append((key, val)))

    # First retrieval escalates; the re-run (orchestrator-issued) does NOT.
    rt = _FakeRuntime(_tool_table([
        _retrieval(True, neighbor_id="weak-seed"),
        _retrieval(False, max_score=0.91, neighbor_id="strong-after-backfill"),
    ]))
    rec = nara.run_iteration("test topic", runtime=rt)

    assert len(calls) == 1, "ml_intern must be called exactly once"
    # The ML-Intern hypothesis_text arg is the captured hypothesis text.
    assert calls[0][0][0] == "H1 hypothesis"

    # retrieve_literature dispatched twice: Nara's tool_call + the orchestrator re-run.
    ret_dispatches = [d for d in rt.dispatched if d[0] == "retrieve_literature"]
    assert len(ret_dispatches) == 2
    # T1c (2026-06-09): the post-backfill re-dispatch is the ONE call site
    # that opts back into the ml_intern_fetched collection now that the
    # default retrieval scope excludes it (corpus de-drift, D-038 kept).
    assert ret_dispatches[1][1] == {
        "hypothesis_text": "H1 hypothesis", "k": 10,
        "include_ml_intern": True,
    }

    # captured retrieval reflects the re-run (the strong post-backfill result).
    assert rec["retrieval"]["neighbors"][0]["doc_id"] == "strong-after-backfill"
    # The re-run retrieval was written back to the cache.
    assert any(k == "retrieval" and
               (v.get("result") or {}).get("neighbors", [{}])[0].get("doc_id")
               == "strong-after-backfill"
               for k, v in cache_writes)

    # Dispatch + result events both logged.
    mi_events = [e for e in rt.events if e.get("event_type") == "loop_v0_ml_intern"]
    assert {e["phase"] for e in mi_events} == {"dispatch", "result"}


def test_no_escalation_skips_ml_intern(monkeypatch, captured_record):
    """should_escalate=False -> ml_intern NOT called, no re-dispatch."""
    calls = []
    monkeypatch.setattr(nara, "_ml_intern",
                        lambda *a, **k: calls.append((a, k)) or _ml_intern_ok())
    monkeypatch.setattr(nara, "get_backend",
                        lambda b: _FakeBackend(_full_chain_script()))

    rt = _FakeRuntime(_tool_table([_retrieval(False, max_score=0.95)]))
    rec = nara.run_iteration("test topic", runtime=rt)

    assert calls == [], "ml_intern must not be called without escalation"
    ret_dispatches = [d for d in rt.dispatched if d[0] == "retrieve_literature"]
    assert len(ret_dispatches) == 1
    assert not any(e.get("event_type") == "loop_v0_ml_intern" for e in rt.events)


def test_guard_fires_ml_intern_only_once_when_rerun_also_escalates(monkeypatch, captured_record):
    """Re-retrieval also escalating -> ml_intern still called only once
    (the once-per-iteration guard prevents an escalation loop)."""
    calls = []
    monkeypatch.setattr(nara, "_ml_intern",
                        lambda *a, **k: calls.append((a, k)) or _ml_intern_ok())
    monkeypatch.setattr(nara, "get_backend",
                        lambda b: _FakeBackend(_full_chain_script()))

    # BOTH the initial and the re-run retrieval escalate; the guard must
    # still cap ml_intern at a single call.
    rt = _FakeRuntime(_tool_table([
        _retrieval(True, neighbor_id="weak-1"),
        _retrieval(True, neighbor_id="weak-2-still-escalating"),
    ]))
    nara.run_iteration("test topic", runtime=rt)

    assert len(calls) == 1, "guard must cap ml_intern at one call per iteration"
    ret_dispatches = [d for d in rt.dispatched if d[0] == "retrieve_literature"]
    # Exactly one re-run (the orchestrator does not re-escalate the re-run).
    assert len(ret_dispatches) == 2


def test_ml_intern_error_leaves_original_retrieval_and_completes(monkeypatch, captured_record):
    """ml_intern status=error -> no re-dispatch; original (weak) retrieval
    intact; chain completes without crashing."""
    monkeypatch.setattr(nara, "_ml_intern", lambda *a, **k: _ml_intern_err())
    monkeypatch.setattr(nara, "get_backend",
                        lambda b: _FakeBackend(_full_chain_script()))

    rt = _FakeRuntime(_tool_table([_retrieval(True, neighbor_id="weak-original")]))
    rec = nara.run_iteration("test topic", runtime=rt)

    # No re-dispatch: only Nara's single retrieve_literature tool_call.
    ret_dispatches = [d for d in rt.dispatched if d[0] == "retrieve_literature"]
    assert len(ret_dispatches) == 1
    # Original weak retrieval preserved.
    assert rec["retrieval"]["neighbors"][0]["doc_id"] == "weak-original"
    # Chain still finished cleanly.
    assert rec["journal_entry_path"] == "journal/iterations/999.md"
    # Both ml_intern events logged even on the error path.
    mi_events = [e for e in rt.events if e.get("event_type") == "loop_v0_ml_intern"]
    assert {e["phase"] for e in mi_events} == {"dispatch", "result"}
    assert any(e["phase"] == "result" and e["status"] == "error" for e in mi_events)
