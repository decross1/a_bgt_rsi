"""EMIT join-contract tests (Limb H, wf-2026-06-09-evening).

The UI reads EXACT field names from EMIT artifacts (join contract, UI commit
0fdb671); a producer rename silently blanks a UI panel without erroring. These
tests pin the producer-side field names at the cheapest honest unit for each
artifact — the real record-assembly / append function, never a full
run_iteration. Fully offline under MOCK_LLM: the Qwen skeptics and the Gemma
synthesis call are monkeypatched (mirrors tests/test_finding_promotion.py);
every file write lands in tmp_path.

Producers covered:
  - orchestrator.journal_stub.finalize_iteration_record (the loop_memory
    append nara.run_iteration uses) carrying retrieval.relevance write-through
    from the REAL workers.retrieval_relevance.relevance function,
  - orchestrator.finding_promotion (surfaced finding rows),
  - orchestrator.coordinator._persist_bubble_up (bubble rows),
  - orchestrator.coordinator_cycle_log.emit_health_signals (health rows)
    and cycle_row_from_report (dispatched_iteration_id),
  - orchestrator.active_run.update_active_run (in-flight doc).

NOTE on assertion style: required UI-contract field names are asserted as a
SUBSET (extra fields allowed — the frozen-interface contract says new
relevance keys are additive), but the three legacy relevance keys
{relevance, low_confidence, reason} must always be present.

Tool-plane seed.source='nemoclaw_agent' write-through is NOT re-tested here:
tests/test_tool_plane.py already pins it (boundary-identity assertion in
test_run_tool_happy_path_returns_extracted_result_envelope plus the
_FAKE_RECORD shape) — see that file before adding coverage.
"""
import json
import sys
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from orchestrator import active_run, coordinator, coordinator_cycle_log
from orchestrator import finding_promotion as fp
from orchestrator import journal_stub
from orchestrator.subagent import SubAgentResult
from workers.retrieval_relevance import relevance


# ── shared fixture helpers ────────────────────────────────────────────


def _read_jsonl(path: Path):
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def _neighbor(doc_id, score, chunk_text="", title=None):
    return {
        "doc_id": doc_id,
        "content_hash": "h-" + doc_id,
        "score": score,
        "source_layer": "foundational",
        "chunk_text": chunk_text,
        "title": title,
    }


def _iteration_record(iid, retrieval):
    """Minimal schema-valid iteration_record, retrieval supplied by the test."""
    return {
        "iteration_id": iid,
        "started_at": "2026-06-09T00:00:00Z",
        "ended_at": "2026-06-09T00:01:00Z",
        "seed": {"topic": "second-price auction truthfulness", "source": "human_cli"},
        "hypothesis": {
            "text": "truthful bidding dominates strategies in second price sealed bid auctions",
            "candidates_considered": 1,
        },
        "retrieval": retrieval,
        "nara_summary": "summary",
        "tool_calls_made": ["journal_writer"],
        "journal_entry_path": "journal/iterations/001.md",
        "model_version": "test",
        "wrapper_call_ids": ["req-1"],
    }


# ── 1. write-through: retrieval.relevance lands in the loop_memory row ──


def _finalize_to_tmp(monkeypatch, tmp_path, record):
    """Append via the REAL producer path nara.run_iteration uses
    (finalize_iteration_record: validate + append), onto a tmp loop_memory."""
    mem = tmp_path / "loop_memory.jsonl"
    monkeypatch.setattr(journal_stub, "LOOP_MEMORY_PATH", mem)
    journal_stub.finalize_iteration_record(record)
    rows = _read_jsonl(mem)
    assert len(rows) == 1
    return rows[0]


def test_loop_memory_row_carries_relevance_low_confidence_true(monkeypatch, tmp_path):
    # Empty retrieval -> the REAL relevance() emits low_confidence=True.
    # Mirror nara.py: payload["relevance"] = relevance(neighbors, hyp_text).
    payload = {"k": 0, "neighbors": []}
    payload["relevance"] = relevance(
        payload.get("neighbors") or [],
        "truthful bidding dominates strategies in second price sealed bid auctions",
    )
    record = _iteration_record("iter-2026-06-09-901", payload)
    row = _finalize_to_tmp(monkeypatch, tmp_path, record)

    rel = row["retrieval"]["relevance"]
    # FROZEN keys (UI join contract): present, with the right JSON types.
    assert {"relevance", "low_confidence", "reason"} <= set(rel.keys())
    assert isinstance(rel["relevance"], (int, float))
    assert rel["low_confidence"] is True  # bool True preserved through JSON
    assert isinstance(rel["reason"], str) and rel["reason"]


def test_loop_memory_row_carries_relevance_low_confidence_false(monkeypatch, tmp_path):
    # On-domain retrieval: high lexical overlap + strong cosine -> not low-conf.
    payload = {
        "k": 1,
        "neighbors": [
            _neighbor(
                "vickrey61",
                0.71,
                chunk_text=(
                    "In a second price sealed bid auction, truthful bidding is "
                    "a dominant strategy for every bidder."
                ),
                title="Counterspeculation, Auctions, and Competitive Sealed Tenders",
            )
        ],
    }
    payload["relevance"] = relevance(
        payload.get("neighbors") or [],
        "truthful bidding dominates strategies in second price sealed bid auctions",
    )
    record = _iteration_record("iter-2026-06-09-902", payload)
    row = _finalize_to_tmp(monkeypatch, tmp_path, record)

    rel = row["retrieval"]["relevance"]
    assert {"relevance", "low_confidence", "reason"} <= set(rel.keys())
    assert rel["low_confidence"] is False
    assert 0.0 <= rel["relevance"] <= 1.0


# ── 2. surfaced finding row shape ─────────────────────────────────────


def _promotable_row(iid):
    return {
        "iteration_id": iid,
        "started_at": "2026-06-01T00:00:00Z",
        "ended_at": "2026-06-01T00:01:00Z",
        "seed": {"topic": f"topic for {iid}", "source": "human_cli"},
        "hypothesis": {
            "text": "Unprimed LLMs rediscover strategyproof truthful bidding.",
            "candidates_considered": 1,
        },
        "novelty": {"class": "novel", "rationale": "novelty rationale"},
        "critique": {"verdict": "survives", "rationale": "critic rationale"},
        # D-059: promotable now means ladder-grade — L1 relevance, L2 sound
        # experiment, L3 replication, redteam "proceed" (the vote is L3->L4).
        "retrieval": {"relevance": {"relevance": 0.8, "low_confidence": False,
                                    "reason": "fixture"}},
        "redteam": {"verdict": "proceed", "critique": "rt", "confidence": 0.8},
        "experiment_outcome": {"experiment_id": "exp_fixture", "metric": "m",
                               "value": 1.0, "trials": 1000,
                               "summary": "Verdict=YES. fixture effect."},
        "cross_tier_comparison": {"replicated": True, "note": "fixture"},
        "journal_entry_path": "journal/iterations/001.md",
        "nara_summary": "summary",
        "tool_calls_made": ["journal_writer"],
        "model_version": "test",
        "wrapper_call_ids": ["x"],
    }


def test_promoted_finding_row_carries_ui_contract_fields(monkeypatch, tmp_path):
    # Skeptics all say "stands" (mirrors tests/test_finding_promotion.py stubs).
    def stub_subagent(**kwargs):
        return SubAgentResult(
            status="passed",
            result={"verdict": "stands", "attack": "a", "confidence": 0.7},
            wrapper_call_ids=["sa"], turns_used=1, wall_seconds=0.1,
            output_tokens_used=10,
        )

    def stub_synth(messages, **kwargs):
        return {
            "request_id": "req-synth",
            "completion": json.dumps(
                {"why_it_matters": "w", "what_would_change_it": "c"}
            ),
        }

    monkeypatch.setattr(fp, "run_subagent", stub_subagent)
    monkeypatch.setattr(fp, "call_sync", stub_synth)
    # promote_findings announces itself via active_run — keep that in tmp too.
    monkeypatch.setattr(active_run, "ACTIVE_RUN_PATH", tmp_path / "active_run.json")

    mem = tmp_path / "loop_memory.jsonl"
    surfaced = tmp_path / "surfaced_findings.jsonl"
    mem.write_text(json.dumps(_promotable_row("iter-2026-06-01-001")) + "\n")

    out = fp.promote_findings(
        loop_memory_path=mem,
        feedback_path=tmp_path / "loop_feedback.jsonl",
        surfaced_path=surfaced,
        n_skeptics=3,
    )
    assert len(out["promoted"]) == 1

    rows = _read_jsonl(surfaced)
    assert len(rows) == 1
    finding = rows[0]
    # UI join contract: these exact names must be present (extras allowed).
    required = {
        "finding_id", "title", "source_iteration_id", "novelty_class",
        "critic_verdict", "promoted_at", "status",
    }
    assert required <= set(finding.keys())
    assert finding["finding_id"] == "sf-iter-2026-06-01-001"
    assert finding["source_iteration_id"] == "iter-2026-06-01-001"
    assert finding["novelty_class"] == "novel"
    assert finding["critic_verdict"] == "survives"
    assert finding["status"] == "surfaced"
    assert isinstance(finding["title"], str) and finding["title"]
    assert isinstance(finding["promoted_at"], str) and finding["promoted_at"]


# ── 3. bubble row + health row shapes ─────────────────────────────────


def test_persisted_bubble_row_carries_ui_contract_fields(tmp_path):
    bubbles_path = tmp_path / "coordinator_bubbles.jsonl"
    coordinator._persist_bubble_up(
        [{"finding_ids": ["sf-iter-2026-06-01-001"], "note": "worth a look"}],
        run_id="coordinator_abc123",
        path=bubbles_path,
    )
    rows = _read_jsonl(bubbles_path)
    assert len(rows) == 1
    row = rows[0]
    assert {"timestamp", "run_id", "finding_ids", "note"} <= set(row.keys())
    assert row["run_id"] == "coordinator_abc123"
    assert row["finding_ids"] == ["sf-iter-2026-06-01-001"]
    assert row["note"] == "worth a look"
    assert isinstance(row["timestamp"], str) and row["timestamp"]


def _dispatched_report(iteration_id, run_id="coordinator_xyz789"):
    return {
        "run_id": run_id,
        "status": "executed",
        "plan": [
            {"name": "run_loop_iteration", "cost": 1,
             "args": {"topic": "auction efficiency"}},
        ],
        "state": {"topic_suggestions": [
            {"topic": "auction efficiency", "source": "arxiv"}]},
        "executed": [
            {"action": "run_loop_iteration", "status": "passed",
             "result": {"iteration_id": iteration_id}},
        ],
        "bubble_up": [],
    }


def test_health_rows_carry_ui_contract_fields(tmp_path):
    iid = "iter-2026-06-09-903"
    health_path = tmp_path / "health_signals.jsonl"
    run_log = tmp_path / "week1.run.jsonl"
    calls_log = tmp_path / "calls.jsonl"
    # ml-intern ran but stored 0 papers for this iteration.
    run_log.write_text(json.dumps({
        "event_type": "loop_v0_ml_intern", "phase": "result",
        "iteration_id": iid, "status": "passed",
        "papers_fetched": 3, "papers_stored": 0,
    }) + "\n")
    # Qwen served a call for this iteration but emitted empty content.
    calls_log.write_text(json.dumps({
        "run_id": iid, "model": "qwen3.6-27b", "completion": "   ",
    }) + "\n")

    signals = coordinator_cycle_log.emit_health_signals(
        _dispatched_report(iid),
        health_path=health_path,
        run_log_path=run_log,
        calls_log_path=calls_log,
    )
    assert len(signals) == 2  # ml_intern_zero_papers + qwen_degraded_empty_content

    rows = _read_jsonl(health_path)
    assert len(rows) == 2
    for row in rows:
        # UI join contract for run_state/health_signals.jsonl rows.
        assert {"timestamp", "run_id", "signal", "severity",
                "iteration_id", "detail"} <= set(row.keys())
        assert row["severity"] == "degraded"
        assert row["iteration_id"] == iid
        assert row["run_id"] == "coordinator_xyz789"
        assert isinstance(row["signal"], str) and row["signal"]
        assert isinstance(row["detail"], str) and row["detail"]
    assert {r["signal"] for r in rows} == {
        "ml_intern_zero_papers", "qwen_degraded_empty_content",
    }


# ── 4. update_active_run in-flight doc at each coordinator step ───────


@pytest.fixture
def tmp_active_run(tmp_path, monkeypatch):
    p = tmp_path / "active_run.json"
    monkeypatch.setattr(active_run, "ACTIVE_RUN_PATH", p)
    return p


def test_update_active_run_each_coordinator_step_is_schema_valid(tmp_active_run):
    schema = json.loads(active_run.SCHEMA_PATH.read_text())
    active_run.write_active_run("coordinator_def456", "coordinator", "cycle")
    for step in ("assess", "plan", "validate", "dispatch"):
        active_run.update_active_run(
            current_step=step, narration=f"now in {step}"
        )
        doc = json.loads(tmp_active_run.read_text())
        # The module's own schema validation (the same one _atomic_write runs).
        jsonschema.validate(doc, schema)
        assert doc["current_step"] == step
        assert isinstance(doc["current_step"], str)
        assert doc["narration"] == f"now in {step}"
        assert isinstance(doc["narration"], str)
        # Identity fields survive every merge.
        assert doc["run_id"] == "coordinator_def456"
        assert doc["kind"] == "coordinator"


# ── 5. cycle row: dispatched_iteration_id join key ────────────────────


def test_cycle_row_dispatched_iteration_id_present_and_equal():
    iid = "iter-2026-06-09-904"
    row = coordinator_cycle_log.cycle_row_from_report(
        _dispatched_report(iid), timestamp="2026-06-09T12:00:00Z"
    )
    assert "dispatched_iteration_id" in row
    assert row["dispatched_iteration_id"] == iid


def test_cycle_row_omits_dispatched_iteration_id_on_errored_dispatch():
    # A FAILED dispatch must surface as an explicit errored outcome, never a
    # phantom join key (absence of the id is the contract for a failed run).
    report = _dispatched_report("ignored")
    report["executed"] = [
        {"action": "run_loop_iteration", "status": "error",
         "reason": "boom: backend unreachable"},
    ]
    row = coordinator_cycle_log.cycle_row_from_report(
        report, timestamp="2026-06-09T12:00:00Z"
    )
    assert "dispatched_iteration_id" not in row
    assert row["outcomes"] == [
        {"action": "run_loop_iteration", "status": "errored",
         "error": "boom: backend unreachable"},
    ]
