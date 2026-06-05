"""Experiments endpoint tests (Page B). Each test builds its OWN FastAPI
app pinned at a tmp experiments dir — no real repo reads. Covers the three
heterogeneous shapes (exp001 json, exp003 markdown, exp002 no-results) plus
the absent-dir degrade path and path-traversal rejection.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.experiments import (
    EXPLOIT_GAP_THRESHOLD,
    MAX_PER_ROUND_ROWS,
    _aggregate_per_round,
    _derive_headline,
    _md_verdict_tone,
    register,
)


def _client(experiments_dir: Path) -> TestClient:
    app = FastAPI()
    register(app, experiments_dir=experiments_dir)
    return TestClient(app)


def _make_exp001(root: Path) -> None:
    res = root / "exp001_repeated_pd" / "results"
    res.mkdir(parents=True)
    summary = {
        "n_opponents": 2,
        "rounds_per_opponent": 2,
        "total_rounds": 4,
        "via_orchestrator": True,
        "total_wall_clock_s": 1.5,
        "per_opponent": [
            {"opponent": "tft", "n_rounds": 2, "llm_coop_rate": 1.0,
             "opp_coop_rate": 1.0, "llm_mean_payoff": 5.0,
             "opp_mean_payoff": 5.0, "wall_clock_s": 0.7},
            {"opponent": "all_d", "n_rounds": 2, "llm_coop_rate": 0.0,
             "opp_coop_rate": 0.0, "llm_mean_payoff": 1.0,
             "opp_mean_payoff": 2.0, "wall_clock_s": 0.8},
        ],
    }
    (res / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    rows = [
        {"opponent": "tft", "round": 1, "llm": "C", "opp": "C",
         "llm_payoff": 5, "opp_payoff": 5},
        {"opponent": "tft", "round": 2, "llm": "C", "opp": "C",
         "llm_payoff": 5, "opp_payoff": 5},
        {"opponent": "all_d", "round": 1, "llm": "C", "opp": "D",
         "llm_payoff": 0, "opp_payoff": 7},
        {"opponent": "all_d", "round": 2, "llm": "D", "opp": "D",
         "llm_payoff": 1, "opp_payoff": 1},
    ]
    (res / "per_round.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    (res / "tft.csv").write_text("round,llm\n1,C\n", encoding="utf-8")


def _make_exp003(root: Path) -> None:
    res = root / "exp003_vickrey_rediscovery" / "results"
    res.mkdir(parents=True)
    (res / "summary.md").write_text(
        "# exp003 — Vickrey rediscovery\n\n**Verdict: YES**\n",
        encoding="utf-8")
    trials = [
        {"trial_idx": 0, "bids": [2.97, 5.82], "winner_idx": 1,
         "price_paid": 2.97},
        {"trial_idx": 1, "bids": [35.12], "winner_idx": 0, "price_paid": 35.12},
    ]
    (res / "trials.jsonl").write_text(
        "\n".join(json.dumps(t) for t in trials) + "\n", encoding="utf-8")


def _make_exp002(root: Path) -> None:
    # No results/ dir — just code + top-level notes.
    d = root / "exp002_loop_v0_robustness"
    d.mkdir(parents=True)
    (d / "runner.py").write_text("# runner\n", encoding="utf-8")
    (d / "notes.md").write_text("notes\n", encoding="utf-8")


# ─── list endpoint ────────────────────────────────────────────────────


def test_list_available_false_when_dir_absent(tmp_path):
    client = _client(tmp_path / "does_not_exist")
    resp = client.get("/api/experiments")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert body["experiments"] == []


def test_list_reports_per_experiment_flags(tmp_path):
    root = tmp_path / "experiments"
    root.mkdir()
    _make_exp001(root)
    _make_exp003(root)
    _make_exp002(root)
    # A scaffolding dir that must be skipped.
    (root / "fixtures").mkdir()

    client = _client(root)
    body = client.get("/api/experiments").json()
    assert body["available"] is True
    by_id = {e["id"]: e for e in body["experiments"]}
    assert "fixtures" not in by_id

    e1 = by_id["exp001_repeated_pd"]
    assert e1["has_summary_json"] is True
    assert e1["has_summary_md"] is False
    assert e1["has_per_round"] is True
    assert e1["has_trials"] is False
    assert e1["n_results_files"] >= 2

    e3 = by_id["exp003_vickrey_rediscovery"]
    assert e3["has_summary_md"] is True
    assert e3["has_trials"] is True
    assert e3["has_summary_json"] is False

    e2 = by_id["exp002_loop_v0_robustness"]
    assert e2["has_results_dir"] is False
    assert e2["has_summary_json"] is False
    assert e2["has_summary_md"] is False
    assert e2["n_results_files"] == 0


# ─── detail endpoint: json shape (exp001) ─────────────────────────────


def test_detail_json_shape_parses_summary_and_aggregates_rounds(tmp_path):
    root = tmp_path / "experiments"
    root.mkdir()
    _make_exp001(root)
    client = _client(root)
    body = client.get("/api/experiments/exp001_repeated_pd").json()
    assert body["has_summary_json"] is True
    assert body["summary_json"]["n_opponents"] == 2
    assert body["summary_md"] is None
    assert body["trials"] is None

    pr = body["per_round"]
    assert pr is not None
    assert set(pr["by_opponent"].keys()) == {"tft", "all_d"}
    assert len(pr["by_opponent"]["tft"]) == 2
    assert pr["total_rows"] == 4
    # exp001 rows carry no task_id -> linkage absent, surfaced honestly.
    assert pr["round_inspector_linkage"] is False


def test_detail_per_round_accumulates_cumulative_payoff(tmp_path):
    root = tmp_path / "experiments"
    root.mkdir()
    _make_exp001(root)
    client = _client(root)
    body = client.get("/api/experiments/exp001_repeated_pd").json()
    pr = body["per_round"]
    # tft: 5,5 -> cum 5,10 (llm) and 5,10 (opp)
    tft = pr["by_opponent"]["tft"]
    assert [r["cum_llm"] for r in tft] == [5, 10]
    assert [r["cum_opp"] for r in tft] == [5, 10]
    # all_d: llm 0,1 -> cum 0,1 ; opp 7,1 -> cum 7,8
    all_d = pr["by_opponent"]["all_d"]
    assert [r["cum_llm"] for r in all_d] == [0, 1]
    assert [r["cum_opp"] for r in all_d] == [7, 8]


def test_detail_headline_flags_exploitation(tmp_path):
    root = tmp_path / "experiments"
    root.mkdir()
    _make_exp001(root)
    client = _client(root)
    body = client.get("/api/experiments/exp001_repeated_pd").json()
    hl = body["headline"]
    assert hl is not None
    # all_d out-scores the LLM (2.0 vs 1.0) -> exploited; tft does not.
    assert hl["tone"] == "bad"
    assert hl["n_exploited"] == 1
    assert hl["n_opponents"] == 2
    assert hl["worst"]["opponent"] == "all_d"
    assert "all_d" in hl["verdict"]
    assert hl["mean_llm_coop_rate"] == 0.5  # (1.0 + 0.0) / 2


def test_detail_headline_not_exploited_when_llm_holds(tmp_path):
    root = tmp_path / "experiments"
    res = root / "expK" / "results"
    res.mkdir(parents=True)
    summary = {
        "per_opponent": [
            {"opponent": "tft", "llm_coop_rate": 1.0,
             "llm_mean_payoff": 5.0, "opp_mean_payoff": 5.0},
        ],
    }
    (res / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    client = _client(root)
    body = client.get("/api/experiments/expK").json()
    hl = body["headline"]
    assert hl["tone"] == "ok"
    assert hl["n_exploited"] == 0
    assert hl["worst"] is None


# ─── detail endpoint: markdown shape (exp003) ─────────────────────────


def test_detail_markdown_shape_returns_md_and_trial_sample(tmp_path):
    root = tmp_path / "experiments"
    root.mkdir()
    _make_exp003(root)
    client = _client(root)
    body = client.get("/api/experiments/exp003_vickrey_rediscovery").json()
    assert body["has_summary_md"] is True
    assert "Verdict: YES" in body["summary_md"]
    assert body["summary_json"] is None
    assert body["per_round"] is None
    trials = body["trials"]
    assert trials["total_rows"] == 2
    assert trials["sample"][0]["trial_idx"] == 0
    # Verdict line pulled out of the markdown into the headline.
    hl = body["headline"]
    assert hl is not None
    assert hl["verdict"] == "Verdict: YES"
    assert hl["tone"] == "ok"


def test_detail_trials_sample_is_bounded(tmp_path):
    root = tmp_path / "experiments"
    res = root / "expN" / "results"
    res.mkdir(parents=True)
    (res / "summary.md").write_text("# x\n", encoding="utf-8")
    big = "\n".join(json.dumps({"trial_idx": i}) for i in range(120)) + "\n"
    (res / "trials.jsonl").write_text(big, encoding="utf-8")
    client = _client(root)
    body = client.get("/api/experiments/expN").json()
    assert body["trials"]["total_rows"] == 120
    assert len(body["trials"]["sample"]) == 50  # MAX_TRIALS_SAMPLE
    assert body["trials"]["truncated"] is True


# ─── detail endpoint: no-results shape (exp002) ───────────────────────


def test_detail_no_results_shape(tmp_path):
    root = tmp_path / "experiments"
    root.mkdir()
    _make_exp002(root)
    client = _client(root)
    body = client.get("/api/experiments/exp002_loop_v0_robustness").json()
    assert body["has_results_dir"] is False
    assert body["summary_json"] is None
    assert body["summary_md"] is None
    assert body["per_round"] is None
    assert body["trials"] is None


# ─── errors / safety ──────────────────────────────────────────────────


def test_detail_404_when_experiment_absent(tmp_path):
    root = tmp_path / "experiments"
    root.mkdir()
    client = _client(root)
    assert client.get("/api/experiments/nope").status_code == 404


def test_detail_rejects_path_traversal(tmp_path):
    root = tmp_path / "experiments"
    root.mkdir()
    client = _client(root)
    for bad in ("..", "%2e%2e", "a%2Fb"):
        resp = client.get(f"/api/experiments/{bad}")
        assert resp.status_code in (400, 404), bad


# ─── headline honesty: no-payoff per_opponent rows (the high-sev bug) ──


def test_headline_undetermined_when_no_numeric_payoffs():
    """REGRESSION: per_opponent rows with NO numeric payoff fields must not
    yield the green 'held its own' verdict. Exploitation is undetermined, not
    a favorable outcome — we never claim a positive result from absent data."""
    hl = _derive_headline(
        {"per_opponent": [
            {"opponent": "tft", "llm_coop_rate": 1.0},
            {"opponent": "all_d", "llm_coop_rate": 0.0},
        ]}
    )
    assert hl is not None
    assert hl["tone"] == "warn"
    assert "undetermined" in hl["verdict"].lower()
    # Not the fabricated favorable claim.
    assert "held its own" not in hl["verdict"].lower()
    assert hl["n_exploited"] == 0
    assert hl["worst"] is None


def test_headline_undetermined_when_payoffs_non_numeric():
    """Null / non-numeric payoffs are not a comparison either."""
    hl = _derive_headline(
        {"per_opponent": [
            {"opponent": "tft", "llm_mean_payoff": None,
             "opp_mean_payoff": None},
            {"opponent": "all_d", "llm_mean_payoff": "n/a",
             "opp_mean_payoff": "n/a"},
        ]}
    )
    assert hl["tone"] == "warn"
    assert "undetermined" in hl["verdict"].lower()


def test_headline_held_its_own_requires_a_real_comparison():
    """The green 'held its own' ok-verdict only fires when at least one real
    (lp, op) comparison was made AND no opponent exploited the LLM."""
    hl = _derive_headline(
        {"per_opponent": [
            {"opponent": "tft", "llm_mean_payoff": 5.0,
             "opp_mean_payoff": 5.0},
        ]}
    )
    assert hl["tone"] == "ok"
    assert "held its own" in hl["verdict"].lower()


def test_headline_endpoint_warn_on_no_payoff_shape(tmp_path):
    """End-to-end through the detail endpoint, not just the helper."""
    res = tmp_path / "expX" / "results"
    res.mkdir(parents=True)
    summary = {"per_opponent": [
        {"opponent": "tft", "llm_coop_rate": 1.0},
        {"opponent": "all_d", "llm_coop_rate": 0.0},
    ]}
    (res / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    body = _client(tmp_path).get("/api/experiments/expX").json()
    assert body["headline"]["tone"] == "warn"


def test_headline_exposes_exploit_gap_threshold(tmp_path):
    """The exploit threshold is echoed so the frontend has a single source of
    truth and never re-hardcodes 0.5."""
    root = tmp_path / "experiments"
    root.mkdir()
    _make_exp001(root)
    body = _client(root).get("/api/experiments/exp001_repeated_pd").json()
    assert body["headline"]["exploit_gap_threshold"] == EXPLOIT_GAP_THRESHOLD


# ─── md verdict tone: word-boundary, not substring scan ───────────────


def test_md_verdict_tone_anchors_on_decision_token():
    assert _md_verdict_tone("Verdict: YES") == "ok"
    assert _md_verdict_tone("**Verdict: NO**".replace("**", "")) == "bad"
    assert _md_verdict_tone("Verdict: YES — bidders rediscovered it") == "ok"
    assert _md_verdict_tone("Verdict: NO — collapsed under defection") == "bad"


def test_md_verdict_tone_does_not_mistone_on_embedded_substrings():
    """'no' inside 'economic'/'cannot'/'enough' must NOT tint a verdict red,
    and 'yes' inside 'eyes' must NOT tint it green. Both fall through to
    warn unless the decision token itself is YES/NO."""
    # 'economic' and 'not' contain 'no' as a substring; decision is unclear.
    v = "Verdict: The LLM did not converge — economic dominance not reached"
    assert _md_verdict_tone(v) == "warn"
    # 'eyes' contains 'yes'; no clean leading YES.
    assert _md_verdict_tone("Verdict: kept its eyes on the payoff") == "warn"


def test_md_verdict_tone_warn_fallback_when_no_yes_no():
    assert _md_verdict_tone("Verdict: inconclusive") == "warn"
    # A clean 'no' token (followed by a word boundary) reads as a NO decision.
    assert _md_verdict_tone("Verdict: no, the LLM regressed") == "bad"
    # ...but a word merely STARTING with 'no' (e.g. 'notably') is not the
    # token 'no' and must not be read as a NO decision.
    assert _md_verdict_tone("Verdict: notably ambiguous outcome") == "warn"


def test_detail_md_verdict_no_tone_is_bad(tmp_path):
    """A clean leading NO verdict tones bad through the endpoint."""
    res = tmp_path / "expNo" / "results"
    res.mkdir(parents=True)
    (res / "summary.md").write_text(
        "# x\n\n**Verdict: NO** — LLM did not rediscover it.\n",
        encoding="utf-8")
    body = _client(tmp_path).get("/api/experiments/expNo").json()
    assert body["headline"]["verdict"].startswith("Verdict: NO")
    assert body["headline"]["tone"] == "bad"


# ─── md overrides json when an experiment carries BOTH ────────────────


def test_md_verdict_overrides_json_headline(tmp_path):
    """When a results dir has BOTH summary.json and summary.md, the markdown
    verdict wins (it is the producer's authored conclusion). Pin that."""
    res = tmp_path / "expBoth" / "results"
    res.mkdir(parents=True)
    # JSON alone would derive an EXPLOITED (bad) headline...
    summary = {"per_opponent": [
        {"opponent": "all_d", "llm_coop_rate": 0.0,
         "llm_mean_payoff": 1.0, "opp_mean_payoff": 2.0},
    ]}
    (res / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (res / "summary.md").write_text(
        "**Verdict: YES** — authored conclusion\n", encoding="utf-8")
    body = _client(tmp_path).get("/api/experiments/expBoth").json()
    # MD verdict wins, not the JSON-derived exploited verdict.
    assert body["headline"]["verdict"].startswith("Verdict: YES")
    assert body["headline"]["tone"] == "ok"
    # JSON is still parsed and present alongside.
    assert body["summary_json"] is not None


# ─── per_round aggregation: truncation, malformed lines ───────────────


def test_aggregate_per_round_truncates_at_cap(tmp_path, monkeypatch):
    """The MAX_PER_ROUND_ROWS cap sets truncated=true and stops scanning."""
    import backend.experiments as mod
    monkeypatch.setattr(mod, "MAX_PER_ROUND_ROWS", 3)
    path = tmp_path / "per_round.jsonl"
    rows = [{"opponent": "tft", "round": i, "llm_payoff": 1, "opp_payoff": 1}
            for i in range(10)]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                    encoding="utf-8")
    agg = _aggregate_per_round(path)
    assert agg["truncated"] is True
    assert agg["total_rows"] == 3


def test_aggregate_per_round_skips_malformed_lines(tmp_path):
    """A corrupt JSON line is skipped, never 500s, and is not counted."""
    path = tmp_path / "per_round.jsonl"
    path.write_text(
        json.dumps({"opponent": "tft", "round": 1,
                    "llm_payoff": 5, "opp_payoff": 5}) + "\n"
        + "{not valid json\n"
        + json.dumps({"opponent": "tft", "round": 2,
                      "llm_payoff": 5, "opp_payoff": 5}) + "\n",
        encoding="utf-8")
    agg = _aggregate_per_round(path)
    assert agg["total_rows"] == 2  # malformed row not counted
    assert len(agg["by_opponent"]["tft"]) == 2


def test_aggregate_per_round_linkage_true_when_task_id_present(tmp_path):
    """A per_round.jsonl that DOES carry task_id flips linkage to true."""
    path = tmp_path / "per_round.jsonl"
    path.write_text(
        json.dumps({"opponent": "tft", "round": 1, "task_id": "t-1",
                    "llm_payoff": 5, "opp_payoff": 5}) + "\n",
        encoding="utf-8")
    agg = _aggregate_per_round(path)
    assert agg["round_inspector_linkage"] is True


# ─── corrupt summary.json -> error branch (no 500, red-banner field) ──


def test_detail_corrupt_summary_json_sets_error_field(tmp_path):
    res = tmp_path / "expCorrupt" / "results"
    res.mkdir(parents=True)
    (res / "summary.json").write_text("{ this is not json", encoding="utf-8")
    resp = _client(tmp_path).get("/api/experiments/expCorrupt")
    assert resp.status_code == 200  # never a 500
    body = resp.json()
    assert "summary_json_error" in body
    assert body["summary_json"] is None
    assert body["headline"] is None
