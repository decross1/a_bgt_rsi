"""Unit tests for experiments/replication_driver.py.

Runs under MOCK_LLM (no real model / no run_iteration call). All file IO
goes through tmp_path fixtures shaped like the real summaries.
"""
import json

from experiments.replication_driver import build_comparison


def _write_pd_summary(path, *, supports):
    """Write an exp001-shaped summary.json. supports=True -> equilibrium
    play (reciprocators cooperate, all_d punished); False -> cooperates
    indiscriminately (no rediscovery)."""
    all_d_coop = 0.12 if supports else 1.0
    data = {
        "n_opponents": 2,
        "per_opponent": [
            {"opponent": "tft", "llm_coop_rate": 1.0},
            {"opponent": "grim_trigger", "llm_coop_rate": 1.0},
            {"opponent": "all_c", "llm_coop_rate": 1.0},
            {"opponent": "mirror_llm", "llm_coop_rate": 1.0},
            {"opponent": "all_d", "llm_coop_rate": all_d_coop},
        ],
    }
    path.write_text(json.dumps(data))


def _write_vickrey_summary(path, *, supports):
    """Write an exp003-shaped summary.md. supports=True -> truthful
    fraction above the 0.75 threshold; False -> below."""
    pct = "100.0%" if supports else "40.0%"
    frac = "50/50" if supports else "20/50"
    path.write_text(
        "# exp003 — Vickrey rediscovery summary\n\n"
        f"- Truthful fraction at eps=5.0: {frac} ({pct})\n"
    )


def test_disagreement_is_diagnostic_signal(tmp_path):
    pd = tmp_path / "pd.json"
    vk = tmp_path / "vk.md"
    _write_pd_summary(pd, supports=True)
    _write_vickrey_summary(vk, supports=False)

    comp = build_comparison(pd, vk)

    assert comp["agreement"] is False
    assert comp["mechanism_a"]["supports"] is True
    assert comp["mechanism_b"]["supports"] is False
    assert comp["diagnostic_note"]
    assert "DIAGNOSTIC SIGNAL" in comp["diagnostic_note"]
    # disagreement is recorded, not discarded
    assert set(comp) == {
        "claim", "mechanism_a", "mechanism_b", "agreement", "diagnostic_note"
    }


def test_both_support_is_agreement(tmp_path):
    pd = tmp_path / "pd.json"
    vk = tmp_path / "vk.md"
    _write_pd_summary(pd, supports=True)
    _write_vickrey_summary(vk, supports=True)

    comp = build_comparison(pd, vk)

    assert comp["agreement"] is True
    assert comp["mechanism_a"]["supports"] is True
    assert comp["mechanism_b"]["supports"] is True
    assert comp["diagnostic_note"]
