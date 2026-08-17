"""Filesystem-only tests for orchestrator.tier_registry.

Pure inspection of experiments/ on disk; no model, no imports of the
experiment modules. Runs under MOCK_LLM with nothing stubbed that matters.
"""
from orchestrator import tier_registry as tr


def test_list_tiers_spectrum_order():
    assert tr.list_tiers() == ["synthetic", "semi_synthetic", "applied"]


def test_exp004_full_capability_in_synthetic():
    entry = tr.get_experiment("exp004_combinatorial_auction")
    assert entry["tier"] == "synthetic"
    assert entry["has_run"] is True
    assert entry["has_analyze"] is True
    assert entry["has_loop_bridge"] is True
    assert entry["dir"] == "experiments/exp004_combinatorial_auction"


def test_exp006_in_semi_synthetic():
    entry = tr.get_experiment("exp006_mechanism_design")
    assert entry["tier"] == "semi_synthetic"
    assert entry in tr.experiments_in_tier("semi_synthetic")


def test_applied_tier_has_polymarket():
    # exp007_polymarket is the first applied-tier entry: design-only,
    # CFTC-gated PAPER forecasting (no live trading).
    entries = tr.experiments_in_tier("applied")
    ids = [e["experiment_id"] for e in entries]
    assert ids == ["exp007_polymarket"]
    assert tr.tiers_status()["applied"] == 1
    e7 = tr.get_experiment("exp007_polymarket")
    assert e7["tier"] == "applied"
    assert e7["has_run"] is True
    assert e7["has_analyze"] is True
    assert e7["has_loop_bridge"] is True
    # The first REAL paper-forecasting run landed 2026-06-10 (Session 3:
    # 18 live resolved markets -> analyze.py wrote summary.json), flipping
    # this from the pre-run None to the json path — the transition this
    # pin's original comment predicted.
    assert e7["results_summary"] == (
        "experiments/exp007_polymarket/results/summary.json"
    )


def test_get_unknown_experiment_raises_keyerror():
    try:
        tr.get_experiment("exp999_does_not_exist")
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError for unknown experiment_id")


def test_heterogeneity_is_surfaced_honestly():
    # exp001 gained analyze.py + loop_bridge.py on 2026-06-09 (reverse-path
    # limb E); the remaining honest heterogeneity is exp005.
    e1 = tr.get_experiment("exp001_repeated_pd")
    assert e1["has_run"] is True
    assert e1["has_analyze"] is True
    assert e1["has_loop_bridge"] is True
    # exp005 has analyze but no loop_bridge.
    e5 = tr.get_experiment("exp005_mechanism_aware")
    assert e5["has_analyze"] is True
    assert e5["has_loop_bridge"] is False


def test_results_summary_resolution():
    # json summary preferred over md when both/either present. exp003 ships md;
    # exp004 + exp005 now ship real json summaries (real runs landed 2026-06-05).
    assert tr.get_experiment("exp004_combinatorial_auction")["results_summary"] == \
        "experiments/exp004_combinatorial_auction/results/summary.json"
    assert tr.get_experiment("exp003_vickrey_rediscovery")["results_summary"] == \
        "experiments/exp003_vickrey_rediscovery/results/summary.md"
    assert tr.get_experiment("exp005_mechanism_aware")["results_summary"] == \
        "experiments/exp005_mechanism_aware/results/summary.json"


def test_tiers_status_counts():
    # 5→8 on 2026-08-17: exp010/exp011/exp012 (L2 block, PREREG_l2block) —
    # deliberate pinned-test update for a documented registry change.
    assert tr.tiers_status() == {"synthetic": 8, "semi_synthetic": 1, "applied": 1}
