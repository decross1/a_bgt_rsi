"""Tests for orchestrator/iteration_cache.py.

Verifies the atomic write semantics, round-trip correctness, missing-key
diagnostics, and the has_entry probe. Modeled on the runtime-interface
test style.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from orchestrator import iteration_cache as ic


@pytest.fixture
def tmp_cache(tmp_path, monkeypatch):
    """Redirect CACHE_ROOT to a per-test tmp dir so tests don't touch the
    real run_state/ tree."""
    monkeypatch.setattr(ic, "CACHE_ROOT", tmp_path / "iteration_cache")
    return tmp_path / "iteration_cache"


class TestCacheDir:
    def test_returns_subdir_of_cache_root(self, tmp_cache):
        d = ic.cache_dir("iter-2026-05-27-001")
        assert d == tmp_cache / "iter-2026-05-27-001"

    def test_does_not_create(self, tmp_cache):
        ic.cache_dir("iter-x")
        assert not (tmp_cache / "iter-x").exists()


class TestWriteEntry:
    def test_roundtrip(self, tmp_cache):
        payload = {"k": 10, "neighbors": [{"doc_id": "x", "score": 0.83}]}
        path = ic.write_entry("iter-1", "retrieval", payload)
        assert path.exists()
        assert json.loads(path.read_text()) == payload

    def test_creates_iteration_dir(self, tmp_cache):
        ic.write_entry("iter-2", "hypothesis", {"text": "h"})
        assert (tmp_cache / "iter-2").is_dir()

    def test_overwrites_atomically(self, tmp_cache):
        ic.write_entry("iter-3", "k", {"v": 1})
        ic.write_entry("iter-3", "k", {"v": 2})
        assert ic.read_entry("iter-3", "k") == {"v": 2}
        # No leftover .tmp file
        assert not (tmp_cache / "iter-3" / "k.json.tmp").exists()

    def test_multiple_keys_coexist(self, tmp_cache):
        ic.write_entry("iter-4", "hypothesis", {"text": "h"})
        ic.write_entry("iter-4", "retrieval", {"k": 10})
        assert ic.read_entry("iter-4", "hypothesis") == {"text": "h"}
        assert ic.read_entry("iter-4", "retrieval") == {"k": 10}


class TestReadEntry:
    def test_returns_payload(self, tmp_cache):
        ic.write_entry("iter-5", "novelty", {"class": "novel"})
        assert ic.read_entry("iter-5", "novelty") == {"class": "novel"}

    def test_missing_iteration_raises_with_path(self, tmp_cache):
        with pytest.raises(KeyError, match="iteration cache miss"):
            ic.read_entry("iter-does-not-exist", "anything")

    def test_missing_key_raises_with_path(self, tmp_cache):
        ic.write_entry("iter-6", "hypothesis", {"text": "h"})
        with pytest.raises(KeyError, match="anything.json"):
            ic.read_entry("iter-6", "anything")


class TestHasEntry:
    def test_true_after_write(self, tmp_cache):
        ic.write_entry("iter-7", "critique", {"verdict": "survives"})
        assert ic.has_entry("iter-7", "critique") is True

    def test_false_before_write(self, tmp_cache):
        assert ic.has_entry("iter-8", "nothing") is False
        ic.write_entry("iter-8", "hypothesis", {"text": "h"})
        assert ic.has_entry("iter-8", "critique") is False
