"""Tests for the SINGLE-SHOT autoresearch driver.

All tests run under MOCK_LLM (no live model). The dry-run path makes no
model call by construction; the live path is exercised with a monkeypatched
run_iteration so no real chain (and no GPU) is ever touched here.
"""
from __future__ import annotations

import json

import pytest

from orchestrator import autoresearch

EXP_ID = "exp004_combinatorial_auction"


def _assert_well_formed_outcome(outcome: dict) -> None:
    # schema/iteration_record.schema.json experiment_outcome required fields.
    assert outcome["experiment_id"] == EXP_ID
    assert isinstance(outcome["metric"], str) and outcome["metric"]
    assert "value" in outcome and isinstance(outcome["value"], (int, float))


def test_dry_run_returns_payload_without_calling_run_iteration(monkeypatch):
    calls = []

    def _fail(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("run_iteration must NOT be called in a dry-run")

    # Patch at the import source the driver lazily imports from.
    monkeypatch.setattr("orchestrator.nara.run_iteration", _fail, raising=False)

    payload = autoresearch.run_autoresearch(
        "synthetic", EXP_ID, reuse_results=True, live=False
    )

    assert payload["dry_run"] is True
    assert "iteration_id" not in payload
    assert payload["tier"] == "synthetic"
    assert payload["experiment_id"] == EXP_ID
    _assert_well_formed_outcome(payload["experiment_outcome"])
    assert calls == []


def test_live_surfaces_iteration_id(monkeypatch):
    fake_record = {"iteration_id": "iter-2026-06-05-042"}
    seen = {}

    def _fake_run_iteration(topic, *, source, **kwargs):
        seen["topic"] = topic
        seen["source"] = source
        seen["kwargs"] = kwargs
        return fake_record

    monkeypatch.setattr(
        "orchestrator.nara.run_iteration", _fake_run_iteration, raising=False
    )

    payload = autoresearch.run_autoresearch(
        "synthetic", EXP_ID, reuse_results=True, live=True
    )

    assert payload["dry_run"] is False
    assert payload["iteration_id"] == "iter-2026-06-05-042"
    _assert_well_formed_outcome(payload["experiment_outcome"])
    # The bridged outcome is threaded into run_iteration unchanged.
    assert seen["source"] == "human_cli"
    assert seen["kwargs"]["experiment_outcome"] == payload["experiment_outcome"]


def test_wrong_tier_assertion_raises():
    # exp004 belongs to the `synthetic` tier; asserting it against
    # `semi_synthetic` must raise.
    with pytest.raises(AssertionError):
        autoresearch.run_autoresearch(
            "semi_synthetic", EXP_ID, reuse_results=True, live=False
        )


def test_replicate_records_cross_tier_comparison(monkeypatch):
    monkeypatch.setattr(
        "orchestrator.nara.run_iteration",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no model")),
        raising=False,
    )
    payload = autoresearch.run_autoresearch(
        "synthetic", EXP_ID, reuse_results=True, replicate=True, live=False
    )
    assert "cross_tier_comparison" in payload
    assert "agreement" in payload["cross_tier_comparison"]


def test_minimal_outcome_from_summary_no_loop_bridge(tmp_path, monkeypatch):
    """When a registry entry reports no loop_bridge, the outcome is built
    minimally from a top-level {metric, value} summary.json."""
    exp_id = "exp_fake_minimal"
    rel_dir = f"experiments/{exp_id}"
    abs_dir = tmp_path / rel_dir
    (abs_dir / "results").mkdir(parents=True)
    (abs_dir / "results" / "summary.json").write_text(
        json.dumps({"metric": "fake_metric", "value": 0.5})
    )
    # Resolve the registry's repo-relative dir against the tmp tree.
    monkeypatch.setattr(autoresearch, "REPO_ROOT", tmp_path)

    # A registry-shaped entry with no loop_bridge.
    exp = {
        "experiment_id": exp_id,
        "tier": "synthetic",
        "dir": rel_dir,
        "has_loop_bridge": False,
        "results_summary": f"{rel_dir}/results/summary.json",
    }
    outcome = autoresearch._build_experiment_outcome(exp)
    assert outcome == {
        "experiment_id": exp_id,
        "metric": "fake_metric",
        "value": 0.5,
    }
