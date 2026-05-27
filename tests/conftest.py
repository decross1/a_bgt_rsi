"""Repo-wide pytest fixtures.

Today: just the per-test iteration_cache redirect so worker tests can
pre-populate cache fixtures without touching `run_state/iteration_cache/`.
"""
from __future__ import annotations

import pytest

from orchestrator import iteration_cache


@pytest.fixture
def cache(tmp_path, monkeypatch):
    """Redirect iteration_cache.CACHE_ROOT to a per-test tmp dir.

    Returns the iteration_cache module so tests can call
    `cache.write_entry(...)` / `cache.read_entry(...)` directly with the
    redirect already in place. Workers (which import the module by name)
    pick up the redirect automatically.
    """
    monkeypatch.setattr(iteration_cache, "CACHE_ROOT", tmp_path / "iteration_cache")
    return iteration_cache
