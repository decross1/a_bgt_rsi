from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


TOOL = Path(__file__).resolve().parents[1] / "tools" / "audit_skeptic_readiness.py"


def _write_jsonl(path: Path, rows: list[dict]) -> bytes:
    payload = b"".join(
        json.dumps(row, sort_keys=True).encode() + b"\n" for row in rows)
    path.write_bytes(payload)
    return payload


def _neighbor(text: str) -> dict:
    return {"doc_id": "d1", "score": 0.8, "title": text, "chunk_text": text}


def test_audit_is_read_only_windowed_and_replays_primary_r0(tmp_path):
    loop_path = tmp_path / "loop.jsonl"
    calls_path = tmp_path / "calls.jsonl"
    strong_hypothesis = "agents coordinate votes using mechanism incentives"
    strong_neighbors = [_neighbor(strong_hypothesis)] * 3
    loops = [
        {
            "ended_at": "2026-09-08T01:00:00Z", "iteration_id": "raw-survives",
            "hypothesis": {"text": strong_hypothesis},
            "retrieval": {"neighbors": strong_neighbors, "relevance": {
                "category": "off_domain", "topicality": "off",
                "low_confidence": True, "anchor_cosine": 0.7,
            }},
            "critique": {"verdict": "undecidable", "low_confidence": True,
                         "verdict_overridden_from": "survives"},
        },
        {
            "ended_at": "2026-09-08T02:00:00Z", "iteration_id": "direct-undecidable",
            "hypothesis": {"text": strong_hypothesis},
            "retrieval": {"neighbors": strong_neighbors, "relevance": {
                "category": "off_domain", "topicality": "off",
                "low_confidence": True, "anchor_cosine": 0.7,
            }},
            "critique": {"verdict": "undecidable", "low_confidence": True},
        },
        {
            "ended_at": "2026-09-08T03:00:00Z", "iteration_id": "current-eligible",
            "hypothesis": {"text": strong_hypothesis},
            "retrieval": {"neighbors": strong_neighbors, "relevance": {
                "category": "ok", "topicality": "on", "low_confidence": False,
                "anchor_cosine": 0.7,
            }},
            "critique": {"verdict": "survives", "low_confidence": False,
                         "skeptic_verdict": "survives_debate",
                         "skeptic_model": "qwen3.8-27b-nvfp4-mtp"},
        },
        {  # excluded by the explicit upper bound
            "ended_at": "2026-09-10T00:00:01Z", "iteration_id": "future",
            "hypothesis": {"text": strong_hypothesis},
            "retrieval": {"neighbors": strong_neighbors, "relevance": {}},
            "critique": {"verdict": "survives", "low_confidence": False},
        },
    ]
    calls = [
        {"timestamp": "2026-09-08T01:01:00Z", "backend": "vllm-gemma",
         "model": "gemma", "caller_tag": "critic_loop_v0"},
        {"timestamp": "2026-09-08T01:02:00Z", "backend": "vllm-qwen",
         "model": "qwen3.8-27b-nvfp4-mtp", "caller_tag": "skeptic_attack"},
        {"timestamp": "2026-09-11T00:00:00Z", "backend": "vllm-qwen",
         "model": "qwen", "caller_tag": "skeptic_attack"},
    ]
    loop_bytes = _write_jsonl(loop_path, loops)
    call_bytes = _write_jsonl(calls_path, calls)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}

    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        [sys.executable, str(TOOL), "--loop-memory", str(loop_path),
         "--calls", str(calls_path), "--since", "2026-09-08T00:00:00Z",
         "--until", "2026-09-10T00:00:00Z"],
        check=True, capture_output=True, text=True, env=env,
    )
    report = json.loads(proc.stdout)
    assert proc.stderr == ""
    assert report["quality_benchmark"] is False
    assert report["read_only"] is True
    assert report["loop"]["completed_rows"] == 3
    assert report["loop"]["current_clean_survives_eligible"] == 1
    assert report["loop"]["raw_survives_overridden"] == 1
    assert report["loop"]["rows_with_qwen38_skeptic_verdict"] == 1
    replay = report["loop"]["r0_advisory_replay"]
    assert replay["state_counts"] == {"ok|low=false": 3}
    assert replay["stored_raw_survives_now_clean"] == 1
    assert report["calls"]["wrapper_calls"] == 2
    assert report["calls"]["qwen_attributed_calls"] == 1
    assert report["calls"]["skeptic_tagged_calls"] == 1
    assert report["sources"]["loop_memory"]["sha256"] == \
        hashlib.sha256(loop_bytes).hexdigest()
    assert report["sources"]["calls"]["sha256"] == \
        hashlib.sha256(call_bytes).hexdigest()
    after = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert after == before


def test_audit_rejects_an_inverted_window(tmp_path):
    loop_path = tmp_path / "loop.jsonl"
    calls_path = tmp_path / "calls.jsonl"
    _write_jsonl(loop_path, [])
    _write_jsonl(calls_path, [])
    proc = subprocess.run(
        [sys.executable, str(TOOL), "--loop-memory", str(loop_path),
         "--calls", str(calls_path), "--since", "2026-09-10T00:00:00Z",
         "--until", "2026-09-09T00:00:00Z"],
        capture_output=True, text=True,
    )
    assert proc.returncode != 0
    assert proc.stdout == ""
    assert "--until must be greater than or equal" in proc.stderr
