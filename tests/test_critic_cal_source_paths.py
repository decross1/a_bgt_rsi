"""Explicit critic-calibration inputs must control reads and provenance.

These regressions use only synthetic temporary files.  They protect callers
that reconstruct a locked study away from the mutable, gitignored production
ledgers.
"""
from __future__ import annotations

import hashlib
import json

from bench.critic_cal import audit_overrides as audit
from bench.critic_cal import build_manifest as bm


def _write_jsonl(path, rows) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_build_metadata_hashes_the_explicit_loop_memory(tmp_path, monkeypatch):
    """``build(path)`` must not hash the module's live default instead."""
    explicit = tmp_path / "explicit-loop-memory.jsonl"
    explicit.write_text("", encoding="utf-8")
    monkeypatch.setattr(bm, "LOOP_MEMORY_PATH", tmp_path / "missing-live.jsonl")

    # An empty synthetic population keeps this regression about path plumbing,
    # without copying any ignored production records into the test suite.
    monkeypatch.setattr(bm, "S1_EXPECTED_N", 0)
    monkeypatch.setattr(bm, "S2_QUOTA", ())
    monkeypatch.setattr(bm, "S3_N", 0)
    monkeypatch.setattr(bm, "TOTAL_N", 0)

    fixtures, metadata = bm.build(explicit)

    assert fixtures == []
    assert metadata["loop_memory_rows"] == 0
    assert metadata["loop_memory_sha256"] == hashlib.sha256(
        explicit.read_bytes()
    ).hexdigest()


def test_audit_cluster_reconstruction_reads_explicit_loop_memory(
    tmp_path, monkeypatch
):
    """``build_report`` must carry its explicit source into cluster replay."""
    iteration_id = "iter-synthetic-source-path"
    raw_row = {
        "iteration_id": iteration_id,
        "started_at": "2026-08-01T00:00:00Z",
        "hypothesis": {"text": "Synthetic path-plumbing hypothesis."},
        "retrieval": {
            "neighbors": [{"doc_id": "synthetic:1", "chunk_text": "Synthetic."}],
            "relevance": {"category": "ok", "low_confidence": False},
        },
        "novelty": {"class": "novel"},
        "critique": {
            "verdict": "undecidable",
            "verdict_overridden_from": "survives",
            "override_reason": "relevance category synthetic override",
            "subagent_status": "passed",
        },
        "redteam": {"verdict": "proceed"},
    }
    explicit = tmp_path / "explicit-loop-memory.jsonl"
    _write_jsonl(explicit, [raw_row])

    ledger = tmp_path / "idea-ledger.jsonl"
    _write_jsonl(
        ledger,
        [
            {
                "event_type": "cluster_created",
                "ts": "2026-08-01T00:00:00Z",
                "cluster_id": "cluster-synthetic-source-path",
                "origin": "iteration",
                "member_id": iteration_id,
            }
        ],
    )
    feedback = tmp_path / "loop-feedback.jsonl"
    feedback.write_text("", encoding="utf-8")
    monkeypatch.setattr(audit, "LOOP_MEMORY_PATH", tmp_path / "missing-live.jsonl")

    report = audit.build_report(
        loop_memory_path=explicit,
        idea_ledger_path=ledger,
        loop_feedback_path=feedback,
        include_rows=False,
        now="fixed",
    )

    assert report["inputs"]["loop_memory"]["sha256"] == hashlib.sha256(
        explicit.read_bytes()
    ).hexdigest()
    assert report["clusters"]["n_open_clusters"] == 1
    cluster = report["clusters"]["clusters"][0]
    assert cluster["latest_iteration"] == iteration_id
    assert cluster["level"] == "L0"
    assert cluster["level_if_verdict_were_survives"] == "L1"
    assert cluster["critic_only_blocked"] is True
