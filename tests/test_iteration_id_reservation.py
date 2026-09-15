"""A failed iteration's cache must remain owned by its original run ID."""
from __future__ import annotations

import hashlib
import json

from orchestrator import iteration_cache, nara


def test_failed_iteration_cache_is_not_reused(tmp_path, monkeypatch):
    memory = tmp_path / "memory" / "loop_memory.jsonl"
    memory.parent.mkdir()
    memory.write_text(json.dumps({"iteration_id": "iter-2026-09-15-003"}) + "\n")
    cache = tmp_path / "iteration_cache"
    old = cache / "iter-2026-09-15-004"
    old.mkdir(parents=True)
    evidence = old / "critique.json"
    evidence.write_bytes(b'{"status":"passed","result":{"verdict":"refuted"}}\n')
    original_sha = hashlib.sha256(evidence.read_bytes()).hexdigest()
    monkeypatch.setattr(nara, "LOOP_MEMORY_PATH", memory)
    monkeypatch.setattr(iteration_cache, "CACHE_ROOT", cache)

    assert nara._next_iteration_id("2026-09-15", reserve=False) == "iter-2026-09-15-005"
    assert not (cache / "iter-2026-09-15-005").exists()
    assert nara._next_iteration_id("2026-09-15") == "iter-2026-09-15-005"
    assert (cache / "iter-2026-09-15-005").is_dir()
    assert nara._next_iteration_id("2026-09-15") == "iter-2026-09-15-006"
    assert hashlib.sha256(evidence.read_bytes()).hexdigest() == original_sha


def test_non_directory_reservation_and_preview_remain_fail_closed(tmp_path, monkeypatch):
    memory = tmp_path / "memory" / "loop_memory.jsonl"
    memory.parent.mkdir()
    memory.write_text("")
    cache = tmp_path / "iteration_cache"
    cache.mkdir()
    (cache / "iter-2026-09-15-001").write_text("occupied")
    monkeypatch.setattr(nara, "LOOP_MEMORY_PATH", memory)
    monkeypatch.setattr(iteration_cache, "CACHE_ROOT", cache)
    assert nara._next_iteration_id("2026-09-15", reserve=False) == "iter-2026-09-15-002"
    assert nara._next_iteration_id("2026-09-15") == "iter-2026-09-15-002"
    assert (cache / "iter-2026-09-15-001").read_text() == "occupied"
