"""Hermetic tests for workers/idea_judge.py (P3/A5).

No network, no real model calls: the real-model path is exercised with canned
completions via a monkeypatched call_sync; everything else runs under
MOCK_LLM=1 (deterministic lexical stub + stub embeddings) against tmp_path
fixtures.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from workers import idea_judge


# ── fixtures ─────────────────────────────────────────────────────────────────

CLUSTER_A = [
    "agents defect faster when payoff asymmetry increases under noisy repeated interactions",
    "agents defect faster when payoff asymmetry increases under noisy iterated interactions",
    "agents defect faster when payoff asymmetry grows under noisy repeated interactions",
    "agents defect faster whenever payoff asymmetry increases under noisy repeated interactions",
]

CLUSTER_B = [
    "bidders shade valuations more aggressively as auction bundle complexity rises steeply",
    "bidders shade valuations more aggressively as auction bundle complexity climbs steeply",
    "bidders shade valuations more aggressively while auction bundle complexity rises steeply",
    "bidders shade valuations most aggressively as auction bundle complexity rises steeply",
]

DISTINCT = [
    "forecaster calibration degrades sharply near market resolution deadlines",
    "level-k reasoning depth predicts convergence speed in beauty contests",
    "tit-for-tat variants dominate stochastic tournaments with implementation errors",
    "mechanism designers overweight revenue relative to allocative efficiency",
]


def _write_loop_memory(tmp_path: Path) -> Path:
    p = tmp_path / "loop_memory.jsonl"
    rows = [{"hypothesis": {"text": t}, "seed": {"topic": "x"}}
            for t in CLUSTER_A + CLUSTER_B + DISTINCT]
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return p


@pytest.fixture(autouse=True)
def _mock_llm_env(monkeypatch):
    """Default every test to MOCK_LLM=1; real-path tests delenv explicitly."""
    monkeypatch.setenv("MOCK_LLM", "1")


@pytest.fixture(autouse=True)
def _no_run_log(monkeypatch):
    """calibrate() appends to the run log on non-dry runs; keep tests
    hermetic and record calls instead."""
    calls: list[dict] = []
    monkeypatch.setattr(idea_judge.runtime, "append_run_log",
                        lambda event, **kw: calls.append(event))
    return calls


# ── judge_pair: MOCK_LLM stub ────────────────────────────────────────────────

def test_mock_stub_identical_is_equivalent_and_labeled():
    out = idea_judge.judge_pair(CLUSTER_A[0], CLUSTER_A[0])
    assert out["verdict"] == "equivalent"
    assert "MOCK_LLM" in out["delta"]  # never masquerades as a model verdict
    assert 0.0 <= out["confidence"] <= 1.0


def test_mock_stub_disjoint_is_distinct():
    out = idea_judge.judge_pair(CLUSTER_A[0], DISTINCT[0])
    assert out["verdict"] == "distinct"


def test_mock_stub_deterministic_and_symmetric():
    a, b = CLUSTER_A[0], CLUSTER_B[0]
    out1 = idea_judge.judge_pair(a, b)
    out2 = idea_judge.judge_pair(a, b)
    rev = idea_judge.judge_pair(b, a)
    assert out1 == out2
    assert out1["verdict"] == rev["verdict"]


@pytest.mark.parametrize("bad", ["", "   ", None, 42])
def test_judge_pair_rejects_empty_input(bad):
    with pytest.raises(ValueError):
        idea_judge.judge_pair(bad, "a real claim text")
    with pytest.raises(ValueError):
        idea_judge.judge_pair("a real claim text", bad)


# ── judge_pair: real path with canned completions ────────────────────────────

def _canned(monkeypatch, completion: str):
    monkeypatch.delenv("MOCK_LLM", raising=False)
    captured: dict = {}

    def fake_call_sync(messages, **kwargs):
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        return {"completion": completion, "request_id": "req-test"}

    monkeypatch.setattr(idea_judge, "call_sync", fake_call_sync)
    return captured


def test_real_path_clean_json(monkeypatch):
    cap = _canned(monkeypatch, json.dumps(
        {"verdict": "better_with_delta", "delta": "adds a falsifiable bound", "confidence": 0.8}))
    out = idea_judge.judge_pair("claim a", "claim b", temperature=0.7)
    assert out == {"verdict": "better_with_delta",
                   "delta": "adds a falsifiable bound", "confidence": 0.8}
    assert cap["kwargs"]["temperature"] == 0.7
    assert cap["kwargs"]["caller_tag"] == "idea_judge"


def test_real_path_json_embedded_in_prose(monkeypatch):
    _canned(monkeypatch,
            'Sure! Here is my judgment:\n{"verdict": "distinct", "delta": "", '
            '"confidence": 0.55}\nHope that helps.')
    out = idea_judge.judge_pair("claim a", "claim b")
    assert out["verdict"] == "distinct"
    assert out["confidence"] == 0.55


def test_real_path_null_delta_becomes_empty_string(monkeypatch):
    _canned(monkeypatch, '{"verdict": "equivalent", "delta": null, "confidence": 1.0}')
    out = idea_judge.judge_pair("claim a", "claim b")
    assert out["delta"] == ""


@pytest.mark.parametrize("completion", [
    "no json here at all",
    '{"verdict": "maybe", "delta": "", "confidence": 0.5}',      # bad enum
    '{"verdict": "equivalent", "delta": "", "confidence": 1.5}',  # out of range
    '{"verdict": "equivalent", "delta": "", "confidence": "hi"}',  # non-numeric
    '{"verdict": "equivalent", "delta": 42, "confidence": 0.5}',  # bad delta
    '{"verdict": "equivalent", "delta": "", "confidence": 0.5',   # unbalanced
])
def test_real_path_invalid_output_raises_never_fabricates(monkeypatch, completion):
    _canned(monkeypatch, completion)
    with pytest.raises(ValueError):
        idea_judge.judge_pair("claim a", "claim b")


# ── passes(): pre-registered threshold arithmetic, never coerced ─────────────

def _good_metrics(**overrides):
    m = {"equiv_precision": 0.95, "equiv_recall": 0.85, "false_equiv_rate": 0.05,
         "symmetry_disagree_rate": 0.05, "verdict_flip_rate": 0.10}
    m.update(overrides)
    return m


def test_passes_all_good():
    assert idea_judge.passes(_good_metrics())["all_pass"] is True


@pytest.mark.parametrize("key,at_bar,beyond", [
    ("equiv_precision", 0.90, 0.8999),
    ("equiv_recall", 0.80, 0.7999),
    ("false_equiv_rate", 0.10, 0.1001),
    ("symmetry_disagree_rate", 0.10, 0.1001),
    ("verdict_flip_rate", 0.15, 0.1501),
])
def test_passes_exact_bar_passes_and_just_beyond_fails(key, at_bar, beyond):
    at = idea_judge.passes(_good_metrics(**{key: at_bar}))
    assert at["checks"][key]["pass"] is True
    assert at["all_pass"] is True
    over = idea_judge.passes(_good_metrics(**{key: beyond}))
    assert over["checks"][key]["pass"] is False
    assert over["all_pass"] is False


@pytest.mark.parametrize("missing_value", [None, "0.95", True])
def test_passes_missing_or_nonnumeric_metric_fails_that_check(missing_value):
    out = idea_judge.passes(_good_metrics(equiv_precision=missing_value))
    assert out["checks"]["equiv_precision"]["pass"] is False
    assert out["checks"]["equiv_precision"]["value"] is None
    assert out["all_pass"] is False
    # other checks stand independently
    assert out["checks"]["equiv_recall"]["pass"] is True


def test_passes_checks_are_independent():
    out = idea_judge.passes(_good_metrics(equiv_recall=0.5, verdict_flip_rate=0.9))
    fails = {k for k, c in out["checks"].items() if not c["pass"]}
    assert fails == {"equiv_recall", "verdict_flip_rate"}


# ── judge_active(): refusal below the bar ────────────────────────────────────

def test_judge_active_true_only_on_full_pass():
    assert idea_judge.judge_active({"metrics": _good_metrics()}) is True
    assert idea_judge.judge_active({"metrics": _good_metrics(equiv_precision=0.89)}) is False


def test_judge_active_never_trusts_stored_flag():
    results = {"all_pass": True, "metrics": _good_metrics(equiv_recall=0.1)}
    assert idea_judge.judge_active(results) is False


@pytest.mark.parametrize("bad", [None, {}, {"metrics": {}}, {"metrics": None}, "yes", 1])
def test_judge_active_refuses_malformed_results(bad):
    assert idea_judge.judge_active(bad) is False


# ── calibration-set construction ─────────────────────────────────────────────

def test_build_pairs_missing_loop_memory_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        idea_judge.build_calibration_pairs(tmp_path / "nope.jsonl")


def test_build_pairs_positives_come_from_big_clusters_only(tmp_path):
    pairs = idea_judge.build_calibration_pairs(_write_loop_memory(tmp_path), seed=0)
    # two clusters of 4 -> C(4,2)*2 = 12 positive pairs
    assert len(pairs["positives"]) == 12
    assert all(p["label"] == "equivalent" for p in pairs["positives"])
    # a positive pair never crosses clusters
    for p in pairs["positives"]:
        in_a = p["a"] in CLUSTER_A and p["b"] in CLUSTER_A
        in_b = p["a"] in CLUSTER_B and p["b"] in CLUSTER_B
        assert in_a or in_b
    assert pairs["hard_negatives"], "expected cross-cluster hard negatives"
    assert all(p["label"] == "not_equivalent"
               for p in pairs["hard_negatives"] + pairs["random_negatives"])


def test_build_pairs_small_clusters_yield_no_positives(tmp_path):
    p = tmp_path / "lm.jsonl"
    rows = [{"hypothesis": {"text": t}} for t in CLUSTER_A[:2] + DISTINCT]
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    pairs = idea_judge.build_calibration_pairs(p, seed=0)
    assert pairs["positives"] == []  # cluster of 2 < MIN_CLUSTER_SIZE


def test_build_pairs_deterministic_for_seed(tmp_path):
    lm = _write_loop_memory(tmp_path)
    assert idea_judge.build_calibration_pairs(lm, seed=7) == \
        idea_judge.build_calibration_pairs(lm, seed=7)


# ── calibrate(): scoring, dry-run, refusal wiring ────────────────────────────

def _oracle_judge(a, b, temperature=0.2, **kw):
    """Perfect lexical oracle — agrees with ground truth by construction."""
    jac = idea_judge._jaccard(idea_judge._tokenize(a), idea_judge._tokenize(b))
    v = "equivalent" if jac >= idea_judge.GROUND_TRUTH_JACCARD else "distinct"
    return {"verdict": v, "delta": "", "confidence": 1.0}


def test_calibrate_perfect_oracle_passes_all_bars(tmp_path, _no_run_log):
    lm = _write_loop_memory(tmp_path)
    out = tmp_path / "results.json"
    results = idea_judge.calibrate(lm, results_path=out, judge_fn=_oracle_judge)
    assert results["metrics"]["equiv_precision"] == 1.0
    assert results["metrics"]["equiv_recall"] == 1.0
    assert results["metrics"]["false_equiv_rate"] == 0.0
    assert results["metrics"]["symmetry_disagree_rate"] == 0.0
    assert results["metrics"]["verdict_flip_rate"] == 0.0
    assert results["all_pass"] is True
    assert idea_judge.judge_active(results) is True
    # both orders x 2 temps per pair
    n_pairs = sum(results["counts"][k] for k in
                  ("positives", "hard_negatives", "random_negatives"))
    assert results["counts"]["calls"] == n_pairs * 2 * len(idea_judge.CALIBRATION_TEMPS)
    # written to disk and readable back
    on_disk = json.loads(out.read_text())
    assert on_disk["all_pass"] is True
    # run-log row appended for the executed calibration (rule 6)
    assert len(_no_run_log) == 1
    assert _no_run_log[0]["task_id"] == "idea_judge_calibrate"


def test_calibrate_always_equivalent_judge_fails_and_is_refused(tmp_path):
    lm = _write_loop_memory(tmp_path)
    always = lambda a, b, temperature=0.2, **kw: {
        "verdict": "equivalent", "delta": "", "confidence": 1.0}
    results = idea_judge.calibrate(lm, results_path=tmp_path / "r.json",
                                   judge_fn=always)
    assert results["metrics"]["false_equiv_rate"] == 1.0
    assert results["checks"]["false_equiv_rate"]["pass"] is False
    assert results["all_pass"] is False
    assert idea_judge.judge_active(results) is False  # refusal below the bar


def test_calibrate_parse_failures_count_against_the_judge(tmp_path):
    lm = _write_loop_memory(tmp_path)

    def flaky(a, b, temperature=0.2, **kw):
        raise ValueError("unparseable model output")

    results = idea_judge.calibrate(lm, results_path=tmp_path / "r.json",
                                   judge_fn=flaky)
    assert results["counts"]["parse_failures"] == results["counts"]["calls"]
    assert results["metrics"]["equiv_recall"] == 0.0
    assert results["metrics"]["symmetry_disagree_rate"] == 1.0
    assert results["all_pass"] is False


def test_calibrate_dry_run_writes_nothing(tmp_path, _no_run_log):
    lm = _write_loop_memory(tmp_path)
    out = tmp_path / "sub" / "results.json"
    results = idea_judge.calibrate(lm, results_path=out, dry_run=True,
                                   judge_fn=_oracle_judge)
    assert results["all_pass"] is True
    assert not out.exists()
    assert not out.parent.exists()
    assert _no_run_log == []  # no run-log row on a dry run


def test_calibrate_default_judge_under_mock_is_deterministic(tmp_path):
    lm = _write_loop_memory(tmp_path)
    r1 = idea_judge.calibrate(lm, results_path=tmp_path / "a.json", dry_run=True)
    r2 = idea_judge.calibrate(lm, results_path=tmp_path / "b.json", dry_run=True)
    assert r1["metrics"] == r2["metrics"]
    assert r1["mock_llm"] is True


def test_cli_requires_calibrate_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        idea_judge.main([])
    assert exc.value.code == 2


def test_cli_dry_run_writes_nothing(tmp_path, capsys, _no_run_log):
    lm = _write_loop_memory(tmp_path)
    out = tmp_path / "results.json"
    rc = idea_judge.main(["--calibrate", "--dry-run",
                          "--loop-memory", str(lm), "--results", str(out)])
    assert rc == 0
    assert not out.exists()
    assert _no_run_log == []
    printed = capsys.readouterr().out
    assert "judge_active" in printed
