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


def _make_per_mechanism(root: Path, exp_id: str, rows: list[dict],
                        n_trials: int = 50) -> None:
    res = root / exp_id / "results"
    res.mkdir(parents=True)
    summary = {"per_mechanism": rows, "n_trials": n_trials}
    (res / "summary.json").write_text(json.dumps(summary), encoding="utf-8")


def _make_flat(root: Path, exp_id: str, summary: dict) -> None:
    res = root / exp_id / "results"
    res.mkdir(parents=True)
    (res / "summary.json").write_text(json.dumps(summary), encoding="utf-8")


def _client(experiments_dir: Path, loop_memory_path: Path | None = None) -> TestClient:
    app = FastAPI()
    if loop_memory_path is None:
        # A path that does not exist -> the bridge reader degrades to empty.
        loop_memory_path = experiments_dir.parent / "absent_loop_memory.jsonl"
    register(app, experiments_dir=experiments_dir,
             loop_memory_path=loop_memory_path)
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


# (The list-endpoint cases died with the /api/experiments INDEX endpoint in
# UI simplification S3 — /api/research is the index the page renders.)


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


# ─── per_mechanism shape (exp004/005): YES/NO tally headline ───────────


def test_per_mechanism_headline_all_yes_is_ok():
    """All rows YES -> ok 'YES on all N mechanisms', with the tally fields."""
    hl = _derive_headline({"per_mechanism": [
        {"mechanism": "first_price", "verdict": "YES"},
        {"mechanism": "vcg", "verdict": "YES"},
        {"mechanism": "sequential_second_price", "verdict": "YES"},
    ], "n_trials": 150})
    assert hl is not None
    assert hl["kind"] == "per_mechanism"
    assert hl["tone"] == "ok"
    assert hl["n_mechanisms"] == 3
    assert hl["n_yes"] == 3
    assert hl["verdict"] == "YES on all 3 mechanisms"


def test_per_mechanism_headline_mixed_is_warn():
    """A split of YES/NO rows tones warn and reports the K/N split."""
    hl = _derive_headline({"per_mechanism": [
        {"mechanism": "first_price", "verdict": "YES"},
        {"mechanism": "vcg", "verdict": "NO"},
    ]})
    assert hl["kind"] == "per_mechanism"
    assert hl["tone"] == "warn"
    assert hl["n_mechanisms"] == 2
    assert hl["n_yes"] == 1
    assert "1/2" in hl["verdict"]


def test_per_mechanism_headline_all_no_is_bad():
    hl = _derive_headline({"per_mechanism": [
        {"mechanism": "first_price", "verdict": "NO"},
        {"mechanism": "vcg", "verdict": "NO"},
    ]})
    assert hl["tone"] == "bad"
    assert hl["n_yes"] == 0
    assert hl["verdict"] == "NO on all 2 mechanisms"


def test_per_mechanism_missing_verdict_counts_as_not_yes():
    """A row with an absent/ambiguous verdict is never tallied as YES — we do
    not guess a favorable per-row outcome from absent data."""
    hl = _derive_headline({"per_mechanism": [
        {"mechanism": "first_price", "verdict": "YES"},
        {"mechanism": "vcg"},  # no verdict field at all
    ]})
    assert hl["tone"] == "warn"
    assert hl["n_yes"] == 1


def test_per_mechanism_explicit_invalid_token_not_counted_as_yes():
    """An explicit non-YES/NO per-row token (e.g. the pre-registered 'INVALID'
    verdict for high parse-failure runs) is NOT tallied as YES and tones the
    headline away from green — we never read a favorable outcome from a token
    that is not a clean YES."""
    hl = _derive_headline({"per_mechanism": [
        {"mechanism": "first_price", "verdict": "YES"},
        {"mechanism": "vcg", "verdict": "INVALID"},
    ]})
    assert hl["kind"] == "per_mechanism"
    assert hl["n_yes"] == 1            # INVALID not counted as YES
    assert hl["tone"] == "warn"        # mixed split, not green
    assert hl["n_mechanisms"] == 2


def test_empty_per_mechanism_list_falls_through_to_flat_verdict():
    """REGRESSION: an empty per_mechanism array plus a real top-level verdict
    must fall through to the flat deriver rather than short-circuit to None and
    silently drop the present verdict."""
    hl = _derive_headline({"per_mechanism": [], "verdict": "NO"})
    assert hl is not None
    assert hl["kind"] == "flat"
    assert hl["tone"] == "bad"
    assert hl["verdict"] == "NO"


def test_empty_per_opponent_list_falls_through_to_flat_verdict():
    """Same short-circuit guard for the legacy per_opponent shape: an empty
    per_opponent array with a top-level verdict reads the flat verdict."""
    hl = _derive_headline({"per_opponent": [], "verdict": "YES"})
    assert hl is not None
    assert hl["kind"] == "flat"
    assert hl["tone"] == "ok"
    assert hl["verdict"] == "YES"


def test_empty_structured_list_no_flat_verdict_is_none():
    """An empty structured list with NO top-level verdict still yields None —
    we never fabricate a headline from nothing."""
    assert _derive_headline({"per_mechanism": []}) is None


def test_per_mechanism_headline_through_detail_endpoint(tmp_path):
    """exp004-like (efficiency/revenue) per_mechanism -> structured headline."""
    _make_per_mechanism(tmp_path, "exp004", [
        {"mechanism": "first_price", "truthful_fraction": 0.965,
         "mean_efficiency": 0.998, "mean_revenue": 82.9,
         "parse_failure_rate": 0.0, "verdict": "YES"},
        {"mechanism": "vcg", "truthful_fraction": 0.965,
         "mean_efficiency": 0.998, "mean_revenue": 63.6,
         "parse_failure_rate": 0.0, "verdict": "YES"},
    ], n_trials=150)
    body = _client(tmp_path).get("/api/experiments/exp004").json()
    hl = body["headline"]
    assert hl["kind"] == "per_mechanism"
    assert hl["tone"] == "ok"
    assert hl["n_yes"] == 2
    # The flat scalar n_trials is still passed through on the summary.
    assert body["summary_json"]["n_trials"] == 150


# ─── flat top-level-verdict shape (exp006) ─────────────────────────────


def test_flat_headline_yes_is_ok():
    hl = _derive_headline({"verdict": "YES", "n_trials": 40,
                           "designer_mean_efficiency": 0.71})
    assert hl is not None
    assert hl["kind"] == "flat"
    assert hl["tone"] == "ok"
    assert hl["verdict"] == "YES"


def test_flat_headline_no_is_bad():
    hl = _derive_headline({"verdict": "NO", "n_trials": 40,
                           "feasibility_rate": 0.525})
    assert hl["kind"] == "flat"
    assert hl["tone"] == "bad"
    assert hl["verdict"] == "NO"


def test_flat_headline_ambiguous_is_warn():
    hl = _derive_headline({"verdict": "INVALID", "n_trials": 40})
    assert hl["kind"] == "flat"
    assert hl["tone"] == "warn"


def test_flat_headline_absent_verdict_is_none():
    """No top-level verdict and no per_* rows -> no headline, never invented."""
    assert _derive_headline({"n_trials": 40, "feasibility_rate": 0.5}) is None


def test_flat_headline_through_detail_endpoint(tmp_path):
    """exp006-like flat summary -> NO verdict tones bad through the endpoint."""
    _make_flat(tmp_path, "exp006", {
        "verdict": "NO", "n_trials": 40, "n_errors": 0,
        "designer_mean_efficiency": 0.710, "feasibility_rate": 0.525,
        "matches_vcg_rate": 0.375, "parse_failures": 13,
    })
    body = _client(tmp_path).get("/api/experiments/exp006").json()
    hl = body["headline"]
    assert hl["kind"] == "flat"
    assert hl["tone"] == "bad"
    assert hl["verdict"] == "NO"
    # Flat scalar metrics ride along on summary_json for the metrics card.
    assert body["summary_json"]["feasibility_rate"] == 0.525


# ─── research page: tier grouping + verdict + bridge ──────────────────


def test_research_available_false_when_dir_absent(tmp_path):
    """No experiments dir -> available:false, never a 500; tiers/untiered []."""
    resp = _client(tmp_path / "does_not_exist").get("/api/research")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert body["tiers"] == []
    assert body["untiered"] == []


def test_research_groups_by_tier_in_spectrum_order(tmp_path):
    """Tiers render synthetic -> semi_synthetic -> applied, each with its
    declared experiments in order."""
    root = tmp_path / "experiments"
    root.mkdir()
    _make_exp001(root)  # synthetic exp001
    body = _client(root).get("/api/research").json()
    assert body["available"] is True
    assert [t["tier"] for t in body["tiers"]] == [
        "synthetic", "semi_synthetic", "applied"]
    syn = next(t for t in body["tiers"] if t["tier"] == "synthetic")
    assert [e["id"] for e in syn["experiments"]] == [
        "exp001_repeated_pd",
        "exp003_vickrey_rediscovery",
        "exp004_combinatorial_auction",
        "exp005_mechanism_aware",
    ]
    # Each tier carries a human label + one-line description.
    assert syn["label"]
    assert syn["description"]


def test_research_untiered_dir_is_bucketed_separately(tmp_path):
    """An experiment DIR not in the tier map lands in untiered[], not a tier."""
    root = tmp_path / "experiments"
    root.mkdir()
    _make_exp002(root)  # exp002_loop_v0_robustness is NOT in the tier map
    body = _client(root).get("/api/research").json()
    untiered_ids = [e["id"] for e in body["untiered"]]
    assert "exp002_loop_v0_robustness" in untiered_ids
    # And it is not smuggled into any tier.
    for t in body["tiers"]:
        assert "exp002_loop_v0_robustness" not in [e["id"] for e in t["experiments"]]


def test_research_tier_lists_absent_dir_as_design_only(tmp_path):
    """A tier experiment whose dir is ABSENT is still listed (design-only):
    has_results_dir false, verdict null — never dropped or guessed."""
    root = tmp_path / "experiments"
    root.mkdir()
    # No exp007 dir on disk at all.
    body = _client(root).get("/api/research").json()
    applied = next(t for t in body["tiers"] if t["tier"] == "applied")
    e7 = next(e for e in applied["experiments"] if e["id"] == "exp007_polymarket")
    assert e7["has_results_dir"] is False
    assert e7["verdict"] is None
    assert e7["bridge"] == []


def test_research_verdict_derived_from_json(tmp_path):
    """summary.json -> verdict {text, tone} via the detail headline logic."""
    root = tmp_path / "experiments"
    _make_per_mechanism(root, "exp004_combinatorial_auction", [
        {"mechanism": "first_price", "verdict": "YES"},
        {"mechanism": "vcg", "verdict": "YES"},
    ], n_trials=150)
    body = _client(root).get("/api/research").json()
    syn = next(t for t in body["tiers"] if t["tier"] == "synthetic")
    e4 = next(e for e in syn["experiments"]
              if e["id"] == "exp004_combinatorial_auction")
    assert e4["verdict"]["tone"] == "ok"
    assert "YES on all 2" in e4["verdict"]["text"]


def test_research_verdict_derived_from_md(tmp_path):
    """No json, a summary.md -> verdict from the markdown verdict line."""
    root = tmp_path / "experiments"
    root.mkdir()
    _make_exp003(root)  # exp003 ships summary.md '**Verdict: YES**'
    body = _client(root).get("/api/research").json()
    syn = next(t for t in body["tiers"] if t["tier"] == "synthetic")
    e3 = next(e for e in syn["experiments"]
              if e["id"] == "exp003_vickrey_rediscovery")
    assert e3["verdict"]["tone"] == "ok"
    assert "Verdict: YES" in e3["verdict"]["text"]


def test_research_verdict_none_when_no_summary(tmp_path):
    """A results dir with neither summary -> verdict null, not fabricated."""
    root = tmp_path / "experiments"
    res = root / "exp001_repeated_pd" / "results"
    res.mkdir(parents=True)
    (res / "tft.csv").write_text("round,llm\n1,C\n", encoding="utf-8")
    body = _client(root).get("/api/research").json()
    syn = next(t for t in body["tiers"] if t["tier"] == "synthetic")
    e1 = next(e for e in syn["experiments"] if e["id"] == "exp001_repeated_pd")
    assert e1["has_results_dir"] is True
    assert e1["verdict"] is None


def test_research_bridge_attached_from_loop_memory(tmp_path):
    """An experiment_outcome row in loop_memory.jsonl attaches a bridge entry
    keyed by experiment_id; experiments with none get []."""
    root = tmp_path / "experiments"
    root.mkdir()
    _make_exp003(root)
    mem = tmp_path / "loop_memory.jsonl"
    mem.write_text(
        json.dumps({
            "iteration_id": "iter-2026-05-27-028",
            "experiment_outcome": {
                "experiment_id": "exp003_vickrey_rediscovery",
                "metric": "truthful_bid_fraction",
                "value": 1.0,
                "trials": 50,
            },
        }) + "\n"
        # A malformed row must be skipped, not 500.
        + "{not json\n",
        encoding="utf-8")
    body = _client(root, loop_memory_path=mem).get("/api/research").json()
    syn = next(t for t in body["tiers"] if t["tier"] == "synthetic")
    e3 = next(e for e in syn["experiments"]
              if e["id"] == "exp003_vickrey_rediscovery")
    assert len(e3["bridge"]) == 1
    assert e3["bridge"][0]["iteration_id"] == "iter-2026-05-27-028"
    assert e3["bridge"][0]["metric"] == "truthful_bid_fraction"
    assert e3["bridge"][0]["value"] == 1.0
    assert e3["bridge"][0]["trials"] == 50
    # An experiment with no outcome row gets an empty bridge.
    e1 = next(e for e in syn["experiments"] if e["id"] == "exp001_repeated_pd")
    assert e1["bridge"] == []


def test_research_bridge_empty_when_loop_memory_absent(tmp_path):
    """No loop_memory.jsonl -> every bridge is [], never an error."""
    root = tmp_path / "experiments"
    root.mkdir()
    _make_exp003(root)
    body = _client(
        root, loop_memory_path=tmp_path / "nope.jsonl"
    ).get("/api/research").json()
    for t in body["tiers"]:
        for e in t["experiments"]:
            assert e["bridge"] == []


# ─── md does NOT override a STRUCTURED json headline (exp004/5/6) ───────


def test_md_does_not_override_structured_per_mechanism_headline(tmp_path):
    """If a per_mechanism experiment ALSO ships a summary.md, the structured
    json headline (the producer's per-row verdict tally) wins — the markdown
    verdict does not clobber it. Contrast test_md_verdict_overrides_json_headline
    which pins md-over-json for the legacy per_opponent shape."""
    res = tmp_path / "exp004" / "results"
    res.mkdir(parents=True)
    (res / "summary.json").write_text(json.dumps({"per_mechanism": [
        {"mechanism": "first_price", "verdict": "YES"},
        {"mechanism": "vcg", "verdict": "YES"},
    ], "n_trials": 100}), encoding="utf-8")
    # A markdown verdict that would tone the OTHER way if it won.
    (res / "summary.md").write_text(
        "**Verdict: NO** — markdown-authored\n", encoding="utf-8")
    body = _client(tmp_path).get("/api/experiments/exp004").json()
    hl = body["headline"]
    assert hl["kind"] == "per_mechanism"
    assert hl["tone"] == "ok"
    assert hl["verdict"] == "YES on all 2 mechanisms"


def test_md_does_not_override_structured_flat_headline(tmp_path):
    res = tmp_path / "exp006" / "results"
    res.mkdir(parents=True)
    (res / "summary.json").write_text(
        json.dumps({"verdict": "NO", "n_trials": 40}), encoding="utf-8")
    (res / "summary.md").write_text(
        "**Verdict: YES** — markdown-authored\n", encoding="utf-8")
    body = _client(tmp_path).get("/api/experiments/exp006").json()
    hl = body["headline"]
    assert hl["kind"] == "flat"
    assert hl["tone"] == "bad"
    assert hl["verdict"] == "NO"


# ─── research page: present-but-empty results dir (real exp007 shape) ───


def test_research_tier_present_but_empty_results_dir(tmp_path):
    """The PRODUCTION exp007 shape: results/ EXISTS on disk but holds only a
    .gitkeep (no summary). has_results_dir is true, yet there is nothing to
    derive — verdict null, no summaries, bridge empty. This is the design-only
    card the frontend keys 'notRun' on (verdict null + no summaries + no
    bridge), and it must never fabricate a verdict from an empty dir."""
    root = tmp_path / "experiments"
    res = root / "exp007_polymarket" / "results"
    res.mkdir(parents=True)
    (res / ".gitkeep").write_text("", encoding="utf-8")
    body = _client(root).get("/api/research").json()
    applied = next(t for t in body["tiers"] if t["tier"] == "applied")
    e7 = next(e for e in applied["experiments"]
              if e["id"] == "exp007_polymarket")
    assert e7["has_results_dir"] is True   # the dir IS present...
    assert e7["has_summary_json"] is False  # ...but carries no summary
    assert e7["has_summary_md"] is False
    assert e7["verdict"] is None            # nothing to derive — not fabricated
    assert e7["bridge"] == []


# ─── research/detail verdict PARITY: one shared resolver, no divergence ─


def test_research_and_detail_verdict_parity_per_opponent_md_override(tmp_path):
    """REGRESSION (honesty): a per_opponent (exp001) experiment that ships BOTH
    a summary.json deriving EXPLOITED *and* an authored summary.md '**Verdict:
    NO**' must read IDENTICALLY on /api/research and on the detail endpoint.
    The two surfaces share one resolver, so the markdown override that the
    detail page applies is replicated on the research card — they cannot
    diverge (previously /api/research returned the json EXPLOITED verdict while
    the detail page returned the markdown NO)."""
    root = tmp_path / "experiments"
    res = root / "exp001_repeated_pd" / "results"
    res.mkdir(parents=True)
    # JSON alone would derive an EXPLOITED (bad) per_opponent headline...
    (res / "summary.json").write_text(json.dumps({"per_opponent": [
        {"opponent": "all_d", "llm_coop_rate": 0.0,
         "llm_mean_payoff": 1.0, "opp_mean_payoff": 2.0},
    ]}), encoding="utf-8")
    # ...but the authored markdown verdict overrides it for this shape.
    (res / "summary.md").write_text(
        "**Verdict: NO** — authored conclusion\n", encoding="utf-8")
    client = _client(root)

    detail = client.get("/api/experiments/exp001_repeated_pd").json()
    research = client.get("/api/research").json()
    syn = next(t for t in research["tiers"] if t["tier"] == "synthetic")
    e1 = next(e for e in syn["experiments"]
              if e["id"] == "exp001_repeated_pd")

    # Detail headline is the markdown NO (override applied)...
    assert detail["headline"]["verdict"].startswith("Verdict: NO")
    assert detail["headline"]["tone"] == "bad"
    # ...and the research card carries the SAME verdict text + tone.
    assert e1["verdict"]["text"] == detail["headline"]["verdict"]
    assert e1["verdict"]["tone"] == detail["headline"]["tone"]
    assert e1["verdict"]["text"].startswith("Verdict: NO")


# ─── bridge: multiple iterations per experiment; malformed outcome rows ─


def test_research_bridge_lists_multiple_iterations_for_one_experiment(tmp_path):
    """exp004 (or any experiment) with TWO experiment_outcome iterations in
    loop_memory.jsonl gets BOTH listed on its bridge, in file order."""
    root = tmp_path / "experiments"
    _make_per_mechanism(root, "exp004_combinatorial_auction", [
        {"mechanism": "first_price", "verdict": "YES"},
    ], n_trials=50)
    mem = tmp_path / "loop_memory.jsonl"
    mem.write_text(
        json.dumps({
            "iteration_id": "iter-A",
            "experiment_outcome": {
                "experiment_id": "exp004_combinatorial_auction",
                "metric": "mean_efficiency", "value": 0.99, "trials": 50,
            },
        }) + "\n"
        + json.dumps({
            "iteration_id": "iter-B",
            "experiment_outcome": {
                "experiment_id": "exp004_combinatorial_auction",
                "metric": "truthful_fraction", "value": 0.96, "trials": 75,
            },
        }) + "\n",
        encoding="utf-8")
    body = _client(root, loop_memory_path=mem).get("/api/research").json()
    syn = next(t for t in body["tiers"] if t["tier"] == "synthetic")
    e4 = next(e for e in syn["experiments"]
              if e["id"] == "exp004_combinatorial_auction")
    assert [b["iteration_id"] for b in e4["bridge"]] == ["iter-A", "iter-B"]
    assert e4["bridge"][0]["metric"] == "mean_efficiency"
    assert e4["bridge"][1]["metric"] == "truthful_fraction"


def test_research_bridge_skips_malformed_outcome_rows_without_500(tmp_path):
    """experiment_outcome rows that are unusable — missing experiment_id, a
    non-dict outcome, an outcome whose experiment_id is the wrong type, or a
    non-dict top-level row — are SKIPPED, never 500ing the page. Only the one
    well-formed outcome attaches a bridge."""
    root = tmp_path / "experiments"
    root.mkdir()
    _make_exp003(root)
    mem = tmp_path / "loop_memory.jsonl"
    mem.write_text(
        # outcome without experiment_id -> skipped
        json.dumps({"iteration_id": "i1",
                    "experiment_outcome": {"metric": "x", "value": 1}}) + "\n"
        # outcome that is not a dict -> skipped
        + json.dumps({"iteration_id": "i2",
                      "experiment_outcome": "not-a-dict"}) + "\n"
        # experiment_id of the wrong type -> skipped
        + json.dumps({"iteration_id": "i3",
                      "experiment_outcome": {"experiment_id": 123,
                                             "metric": "x"}}) + "\n"
        # a top-level row that is a JSON array, not an object -> skipped
        + json.dumps([1, 2, 3]) + "\n"
        # the one well-formed outcome -> attaches
        + json.dumps({"iteration_id": "i4",
                      "experiment_outcome": {
                          "experiment_id": "exp003_vickrey_rediscovery",
                          "metric": "truthful_bid_fraction", "value": 1.0}}) + "\n",
        encoding="utf-8")
    resp = _client(root, loop_memory_path=mem).get("/api/research")
    assert resp.status_code == 200  # never a 500 on malformed outcome rows
    body = resp.json()
    syn = next(t for t in body["tiers"] if t["tier"] == "synthetic")
    e3 = next(e for e in syn["experiments"]
              if e["id"] == "exp003_vickrey_rediscovery")
    assert len(e3["bridge"]) == 1
    assert e3["bridge"][0]["iteration_id"] == "i4"
    # No other experiment picked up a bridge from the skipped rows.
    for t in body["tiers"]:
        for e in t["experiments"]:
            if e["id"] != "exp003_vickrey_rediscovery":
                assert e["bridge"] == []
