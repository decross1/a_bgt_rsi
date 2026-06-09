"""Tests for the exp001 narrative-vs-list path: analyze verdict (both
sides of the pre-registered threshold), loop_bridge outcome shape vs the
iteration_record schema, and the llm_agent history-framing axis.

Pure/MOCK-safe: synthetic fixture data only; no LLM calls, no real
run_state or results writes (module path constants are monkeypatched
to tmp_path, the established exp006 pattern).
"""
from __future__ import annotations

import json
from pathlib import Path

from experiments.exp001_repeated_pd import analyze as analyze_mod
from experiments.exp001_repeated_pd import loop_bridge as bridge_mod
from experiments.exp001_repeated_pd import llm_agent

REPO = Path(__file__).resolve().parents[1]
SCHEMA = json.loads(
    (REPO / "schema" / "iteration_record.schema.json").read_text())


def _arm_summary(rates: dict[str, float], rounds: int = 100) -> dict:
    return {
        "total_rounds": rounds * len(rates),
        "per_opponent": [
            {"opponent": opp, "n_rounds": rounds, "llm_coop_rate": rate}
            for opp, rate in rates.items()
        ],
    }


def _write_arms(tmp_path, monkeypatch, narrative_rates, list_rates):
    nar = tmp_path / "narrative" / "summary.json"
    lst = tmp_path / "list" / "summary.json"
    for path, rates in ((nar, narrative_rates), (lst, list_rates)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_arm_summary(rates)))
    summary_md = tmp_path / "summary.md"
    monkeypatch.setattr(analyze_mod, "NARRATIVE_SUMMARY_JSON", nar)
    monkeypatch.setattr(analyze_mod, "LIST_SUMMARY_JSON", lst)
    monkeypatch.setattr(analyze_mod, "SUMMARY_PATH", summary_md)
    return nar, lst, summary_md


# ---- analyze: pre-registered verdict, both sides of the threshold ----

def test_analyze_clear_gap_is_verdict_yes(tmp_path, monkeypatch):
    _, _, summary_md = _write_arms(
        tmp_path, monkeypatch,
        narrative_rates={"tft": 0.90, "all_d": 0.70},
        list_rates={"tft": 0.60, "all_d": 0.40})
    assert analyze_mod.main() == 0
    text = summary_md.read_text()
    assert "Verdict=YES" in text
    assert "Verdict=NO" not in text
    assert "- delta(narrative - list): +0.3000" in text


def test_analyze_small_gap_is_verdict_no_not_coerced(tmp_path, monkeypatch):
    # delta = +0.04: directionally consistent with the thesis but below
    # the pre-registered 0.10 threshold — MUST be NO (inviolate rule 4).
    _, _, summary_md = _write_arms(
        tmp_path, monkeypatch,
        narrative_rates={"tft": 0.70, "all_d": 0.58},
        list_rates={"tft": 0.66, "all_d": 0.54})
    assert analyze_mod.main() == 0
    text = summary_md.read_text()
    assert "Verdict=NO" in text
    assert "Verdict=YES" not in text


def test_verdict_for_threshold_is_pre_registered_constant():
    assert analyze_mod.VERDICT_THRESHOLD == 0.10
    # Exact decimal arithmetic (2026-06-09 review): delta is the true
    # decimal difference, not the binary-float subtraction artifact.
    assert analyze_mod.verdict_for(0.80, 0.60) == ("YES", 0.2)


def test_verdict_for_exact_boundary_is_yes():
    """delta == 0.10 exactly must verdict YES — binary-float subtraction
    (0.71 - 0.61 = 0.0999...98) must not flip a true boundary delta to NO."""
    verdict, delta = analyze_mod.verdict_for(0.71, 0.61)
    assert (verdict, delta) == ("YES", 0.1)
    verdict, delta = analyze_mod.verdict_for(0.62, 0.60)
    assert verdict == "NO"


# ---- loop_bridge: outcome shape vs the iteration_record schema ----

def _bridge_fixture(tmp_path, monkeypatch, verdict="NO", nar=0.65, lst=0.61):
    delta = nar - lst
    summary_md = tmp_path / "summary.md"
    summary_md.write_text("\n".join([
        "# exp001 — narrative-vs-list history framing summary",
        f"Verdict={verdict} — fixture.",
        f"- coop_rate(narrative): {nar:.4f}",
        f"- coop_rate(list): {lst:.4f}",
        f"- delta(narrative - list): {delta:+.4f}",
    ]))
    nar_json = tmp_path / "narrative" / "summary.json"
    lst_json = tmp_path / "list" / "summary.json"
    for p in (nar_json, lst_json):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"total_rounds": 500, "per_opponent": []}))
    monkeypatch.setattr(bridge_mod, "SUMMARY_PATH", summary_md)
    monkeypatch.setattr(bridge_mod, "NARRATIVE_SUMMARY_JSON", nar_json)
    monkeypatch.setattr(bridge_mod, "LIST_SUMMARY_JSON", lst_json)


def test_bridge_outcome_matches_schema_shape(tmp_path, monkeypatch):
    _bridge_fixture(tmp_path, monkeypatch, verdict="NO", nar=0.65, lst=0.61)
    outcome = bridge_mod.build_experiment_outcome()

    eo_schema = SCHEMA["properties"]["experiment_outcome"]
    for field in eo_schema["required"]:  # experiment_id, metric, value
        assert field in outcome, f"missing required field {field}"
    assert set(outcome) <= set(eo_schema["properties"])

    assert outcome["experiment_id"] == "exp001_repeated_pd"
    assert outcome["metric"] == "narrative_minus_list_cooperation"
    assert isinstance(outcome["value"], float)
    assert abs(outcome["value"] - 0.04) < 1e-9
    assert outcome["trials"] == 1000  # 500 rounds per arm
    assert "Verdict=NO" in outcome["summary"]
    assert isinstance(outcome["results_path"], str)


def test_bridge_yes_verdict_and_topic_seed(tmp_path, monkeypatch):
    _bridge_fixture(tmp_path, monkeypatch, verdict="YES", nar=0.85, lst=0.55)
    outcome = bridge_mod.build_experiment_outcome()
    assert "Verdict=YES" in outcome["summary"]
    topic = bridge_mod.build_topic_seed(outcome)
    assert "narrative" in topic and "list" in topic
    assert "+30.00%" in topic


def test_bridge_dry_run_default_makes_no_llm_call(tmp_path, monkeypatch, capsys):
    _bridge_fixture(tmp_path, monkeypatch)
    assert bridge_mod.main([]) == 0  # default = dry-run, no nara import
    out = capsys.readouterr().out
    assert "[dry-run] not calling run_iteration" in out
    assert "experiment_outcome payload:" in out


# ---- llm_agent: the narrative-vs-list history-framing axis ----

def test_rules_variants_gained_list_and_narrative_arms():
    assert llm_agent.RULES_VARIANTS["list"] == ""
    assert llm_agent.RULES_VARIANTS["narrative"] == ""
    # arms must not alter the rules text — the only axis is the framing
    a_list = llm_agent.LLMAgent(rules_variant="list")
    a_base = llm_agent.LLMAgent(rules_variant="baseline")
    a_narr = llm_agent.LLMAgent(rules_variant="narrative")
    assert a_list._rules == a_base._rules == a_narr._rules


def test_narrative_render_differs_from_list_render_only_in_framing():
    history = [("C", "C"), ("C", "D"), ("D", "D")]
    listed = llm_agent._format_history(history)
    narrative = llm_agent._format_history_narrative(history)
    assert listed != narrative
    assert "round 1: you=C, them=C" in listed
    assert "In round 1 you both played C." in narrative
    assert "In round 2 you played C while they played D." in narrative
    # neutral framing: no strategy names, no evaluative language
    for word in ("tit", "grim", "betray", "punish", "reward"):
        assert word not in narrative.lower()
    # empty history is identical text in both framings
    assert (llm_agent._format_history_narrative([])
            == llm_agent._format_history([])
            == "No rounds have been played yet.")
