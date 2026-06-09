"""Tests for orchestrator/domain_anchor.py + the pure centroid math in
scripts/build_domain_anchor.py.

Everything here runs under MOCK_LLM with NO embedder and NO Chroma store:
the loader paths use tmp files, anchor_cosine is exercised only on its
None-returning branches (MOCK_LLM / missing anchor / empty text — each a
distinct logged reason), and the centroid function is pure math. The real
build + a real-embedding anchor_cosine smoke belong to the integrator's
serial `env -u MOCK_LLM` pass.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

import orchestrator.domain_anchor as da
from scripts.build_domain_anchor import centroid

REPO_ROOT = Path(__file__).resolve().parent.parent


def _write_anchor(path: Path, vector=(1.0, 0.0, 0.0), dim=None) -> Path:
    path.write_text(json.dumps({
        "model": "bge-m3",
        "dim": len(vector) if dim is None else dim,
        "vector": list(vector),
        "collections": {"osborne_rubinstein": 3},
        "built_at": "2026-06-09T00:00:00+00:00",
        "builder_commit": "deadbee",
    }))
    return path


# --- load_anchor -------------------------------------------------------------

def test_load_anchor_missing_file_is_none(tmp_path):
    assert da.load_anchor(tmp_path / "nope.json") is None


def test_load_anchor_malformed_json_is_none(tmp_path):
    p = tmp_path / "anchor.json"
    p.write_text("{not json!!")
    assert da.load_anchor(p) is None


def test_load_anchor_bad_shape_is_none(tmp_path):
    # dim disagrees with len(vector) -> shape check fails.
    p = _write_anchor(tmp_path / "anchor.json", vector=(1.0, 0.0), dim=999)
    assert da.load_anchor(p) is None
    # non-numeric vector entries -> shape check fails.
    p2 = tmp_path / "anchor2.json"
    p2.write_text(json.dumps({"dim": 2, "vector": [1.0, "oops"]}))
    assert da.load_anchor(p2) is None


def test_load_anchor_valid_file_loads(tmp_path):
    p = _write_anchor(tmp_path / "anchor.json")
    anchor = da.load_anchor(p)
    assert isinstance(anchor, dict)
    assert anchor["vector"] == [1.0, 0.0, 0.0]
    assert anchor["dim"] == 3


def test_load_anchor_is_cached_per_path(tmp_path):
    p = _write_anchor(tmp_path / "anchor.json")
    first = da.load_anchor(p)
    p.unlink()  # cached result must survive the file going away
    assert da.load_anchor(p) is first


# --- anchor_cosine None paths -------------------------------------------------

def test_anchor_cosine_none_under_mock_llm(tmp_path, monkeypatch):
    """MOCK_LLM (the default shell state) -> None, even with a valid anchor."""
    monkeypatch.setenv("MOCK_LLM", "1")
    p = _write_anchor(tmp_path / "anchor.json")
    assert da.anchor_cosine("repeated prisoner dilemma cooperation", p) is None


def test_anchor_cosine_none_when_anchor_missing(tmp_path, monkeypatch):
    """No anchor file -> None BEFORE any embedder load is attempted."""
    monkeypatch.delenv("MOCK_LLM", raising=False)
    assert da.anchor_cosine("some hypothesis", tmp_path / "nope.json") is None


def test_anchor_cosine_none_on_empty_text(tmp_path, monkeypatch):
    """Empty / non-str text -> None BEFORE any embedder load is attempted."""
    monkeypatch.delenv("MOCK_LLM", raising=False)
    p = _write_anchor(tmp_path / "anchor.json")
    assert da.anchor_cosine("", p) is None
    assert da.anchor_cosine("   ", p) is None
    assert da.anchor_cosine(None, p) is None  # type: ignore[arg-type]


# --- pure centroid math (scripts/build_domain_anchor.py) ----------------------

def test_centroid_normalizes_then_means():
    # [2,0] and [0,1] L2-normalize to [1,0] and [0,1]; mean renormalized is
    # the 45-degree unit vector — magnitude differences must NOT bias it.
    c = centroid([[2.0, 0.0], [0.0, 1.0]])
    assert c == pytest.approx([1 / math.sqrt(2), 1 / math.sqrt(2)])


def test_centroid_is_unit_norm():
    c = centroid([[3.0, 4.0], [1.0, 1.0], [0.5, 2.0]])
    assert math.sqrt(sum(x * x for x in c)) == pytest.approx(1.0)


def test_centroid_rejects_empty_and_mismatched():
    with pytest.raises(ValueError):
        centroid([])
    with pytest.raises(ValueError):
        centroid([[1.0, 0.0], [1.0, 0.0, 0.0]])


def test_build_script_help_exits_zero():
    """--help must work without touching Chroma (heavy imports deferred)."""
    res = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "build_domain_anchor.py"),
         "--help"],
        capture_output=True, text=True, timeout=60,
    )
    assert res.returncode == 0
    assert "domain anchor" in res.stdout.lower() or "foundational" in res.stdout.lower()
