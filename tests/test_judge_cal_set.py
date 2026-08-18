"""Tests for the judge-calibration set v2 (LOOP_V1 P3) —
bench/judge_cal/set_v2.jsonl + its deterministic generator
bench/judge_cal/build_set.py.

Covers: size/composition bounds, generator determinism, format compatibility
with workers.idea_judge --calibrate consumption, no duplicated pairs,
positives genuinely same-cluster / negatives genuinely cross-cluster by
construction. Runs green under MOCK_LLM=1; never calls a real model and
never runs a real calibration (integrator's job).
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from workers import idea_judge  # noqa: E402
from workers.idea_judge import GROUND_TRUTH_JACCARD, _jaccard  # noqa: E402
from workers.retrieval_relevance import _tokenize  # noqa: E402

SET_PATH = REPO_ROOT / "bench" / "judge_cal" / "set_v2.jsonl"
BUILD_SET_PATH = REPO_ROOT / "bench" / "judge_cal" / "build_set.py"

_spec = importlib.util.spec_from_file_location("judge_cal_build_set", BUILD_SET_PATH)
build_set = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_set)

ROW_KEYS = {"pair_id", "bucket", "label", "a", "b",
            "cluster_a", "cluster_b", "jaccard", "prefilter_overlap"}


def _rows() -> list[dict]:
    return [json.loads(line) for line in
            SET_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


# ── Frozen-set: composition, format, dedup, cluster semantics ────────────────

def test_composition_bounds():
    rows = _rows()
    counts = {b: sum(1 for r in rows if r["bucket"] == b) for b in build_set.BUCKETS}
    # Positives are corpus-limited (~50 target; the historical 8-10x clusters
    # are mostly VERBATIM restatements, which dedup collapses) — band, not cap.
    assert 20 <= counts["positives"] <= build_set.TARGET_POSITIVES
    assert counts["hard_negatives"] == build_set.TARGET_HARD_NEGATIVES
    assert counts["random_negatives"] == build_set.TARGET_RANDOM_NEGATIVES
    assert sum(counts.values()) == len(rows) >= 70


def test_row_format_matches_calibrate_expectations():
    rows = _rows()
    assert rows, "set_v2.jsonl is empty"
    seen_ids = set()
    for r in rows:
        assert set(r.keys()) == ROW_KEYS
        assert r["bucket"] in build_set.BUCKETS
        # The exact label vocabulary idea_judge.build_calibration_pairs emits
        # and _score_calls branches on.
        expected = "equivalent" if r["bucket"] == "positives" else "not_equivalent"
        assert r["label"] == expected
        for side in ("a", "b"):
            assert isinstance(r[side], str) and r[side].strip()
            # judge_pair rejects structured payloads implicitly via hygiene:
            assert r[side][0] not in "{["
        assert r["pair_id"] not in seen_ids
        seen_ids.add(r["pair_id"])
        for k in ("jaccard", "prefilter_overlap"):
            assert isinstance(r[k], (int, float)) and 0.0 <= r[k] <= 1.0


def test_no_pair_duplicated_and_no_self_pairs():
    rows = _rows()
    unordered = {frozenset((r["a"], r["b"])) for r in rows}
    assert all(r["a"] != r["b"] for r in rows)
    assert len(unordered) == len(rows)


def test_positives_same_cluster_negatives_cross_cluster():
    for r in _rows():
        if r["bucket"] == "positives":
            assert r["cluster_a"] == r["cluster_b"]
        else:
            assert r["cluster_a"] != r["cluster_b"]
            # By union-find construction a cross-component pair can never
            # reach the ground-truth lexical edge bar — verify independently.
            jac = _jaccard(_tokenize(r["a"]), _tokenize(r["b"]))
            assert jac < GROUND_TRUTH_JACCARD
            assert abs(jac - r["jaccard"]) < 1e-3


def test_hard_negatives_are_hard_and_sorted():
    rows = [r for r in _rows() if r["bucket"] == "hard_negatives"]
    scores = [r["prefilter_overlap"] for r in rows]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] > 0.3  # genuinely high-overlap confusers at the top


def test_load_set_shape_matches_build_calibration_pairs():
    got = build_set.load_set(SET_PATH)
    assert set(got.keys()) == set(build_set.BUCKETS)
    rows = _rows()
    for bucket in build_set.BUCKETS:
        items = got[bucket]
        assert len(items) == sum(1 for r in rows if r["bucket"] == bucket)
        for item in items:
            # The exact item shape idea_judge.build_calibration_pairs returns.
            assert set(item.keys()) == {"a", "b", "label"}


def test_mock_judge_pipeline_consumes_set(monkeypatch):
    """Mirror workers.idea_judge.calibrate's labeled-pair loop over load_set
    output with the MOCK judge (both orders x both temps), then score with the
    real _score_calls. Proves direct consumability end to end WITHOUT running
    a real calibration. The deterministic lexical stub is symmetric and
    temperature-free, and every negative is below the mock-equivalence bar by
    construction — so false-equivalence, symmetry, and flip must all be 0."""
    monkeypatch.setenv("MOCK_LLM", "1")
    pairs = build_set.load_set(SET_PATH)
    labeled = (
        [(p, "positives") for p in pairs["positives"]]
        + [(p, "hard_negatives") for p in pairs["hard_negatives"]]
        + [(p, "random_negatives") for p in pairs["random_negatives"]]
    )
    pair_calls = []
    for pid, (pair, _bucket) in enumerate(labeled):
        for temp in idea_judge.CALIBRATION_TEMPS:
            for order, (a, b) in (("ab", (pair["a"], pair["b"])),
                                  ("ba", (pair["b"], pair["a"]))):
                verdict = idea_judge.judge_pair(a, b, temperature=temp)["verdict"]
                pair_calls.append({"pair_id": pid, "label": pair["label"],
                                   "temp": temp, "order": order, "verdict": verdict})
    metrics = idea_judge._score_calls(pair_calls)
    check = idea_judge.passes(metrics)
    assert set(metrics.keys()) == set(check["checks"].keys())
    assert metrics["false_equiv_rate"] == 0.0
    assert metrics["symmetry_disagree_rate"] == 0.0
    assert metrics["verdict_flip_rate"] == 0.0


# ── Generator: determinism + by-construction properties on a fixture ─────────

def test_determinism_same_inputs_same_bytes(tmp_path):
    # Snapshot the live corpora ONCE (the always-on lab appends to them),
    # then build twice from the snapshots: byte-identical output required.
    lm = tmp_path / "loop_memory.jsonl"
    il = tmp_path / "idea_ledger.jsonl"
    shutil.copyfile(REPO_ROOT / "memory" / "loop_memory.jsonl", lm)
    shutil.copyfile(REPO_ROOT / "memory" / "idea_ledger.jsonl", il)
    out1, out2 = tmp_path / "one.jsonl", tmp_path / "two.jsonl"
    build_set.write_set(build_set.build_rows(lm, il, seed=build_set.SEED), out1)
    build_set.write_set(build_set.build_rows(lm, il, seed=build_set.SEED), out2)
    b1, b2 = out1.read_bytes(), out2.read_bytes()
    assert b1 == b2
    assert b1  # non-empty


FIXTURE_CLAIMS = {
    # Cluster ALPHA: A1~A2 lexically (jaccard >= 0.6); A3 joins via ledger only.
    "it-a1": "delegated voting concentrates influence near hub nodes inside "
             "preferential attachment networks",
    "it-a2": "delegated voting concentrates influence near hub nodes inside "
             "preferential attachment topologies",
    "it-a3": "auction reserve pricing shifts bidder truthfulness during sealed "
             "second price rounds",
    # Cluster BETA: lexical pair.
    "it-b1": "gradient perturbation stabilizes cooperative training dynamics "
             "inside independent learner populations",
    "it-b2": "gradient perturbation stabilizes cooperative training dynamics "
             "inside independent learner collectives",
    # Singletons.
    "it-s1": "spectral clustering reveals modular committee structures",
    "it-s2": "citation cascades amplify reviewer bias inside peer review pipelines",
}


def _write_fixture(tmp_path: Path) -> tuple[Path, Path]:
    lm = tmp_path / "loop_memory.jsonl"
    lines = []
    for it, text in FIXTURE_CLAIMS.items():
        if it == "it-s1":  # exercise the seed.topic fallback path
            lines.append({"iteration_id": it, "seed": {"topic": text}})
        else:
            lines.append({"iteration_id": it, "hypothesis": {"text": text}})
    # A leaked structured payload: must be dropped by hygiene, never paired.
    lines.append({"iteration_id": "it-junk",
                  "hypothesis": {"text": '{"candidates": ["leaked blob"]}'}})
    lm.write_text("".join(json.dumps(r) + "\n" for r in lines))
    il = tmp_path / "idea_ledger.jsonl"
    il.write_text("".join(json.dumps(e) + "\n" for e in [
        {"event_type": "cluster_created", "cluster_id": "cl-fix-1", "member_id": "it-a1"},
        {"event_type": "member_added", "cluster_id": "cl-fix-1", "member_id": "it-a3"},
        {"event_type": "cluster_killed", "cluster_id": "cl-fix-1"},  # ignored
    ]))
    return lm, il


def test_fixture_construction_properties(tmp_path):
    lm, il = _write_fixture(tmp_path)
    rows = build_set.build_rows(lm, il, seed=build_set.SEED)
    by_bucket = {b: [r for r in rows if r["bucket"] == b] for b in build_set.BUCKETS}

    # Positives: exactly the intra-component pairs — ALPHA {a1,a2,a3} (the
    # ledger edge pulls a3 in despite ~zero lexical overlap) then BETA {b1,b2}.
    got_pos = {frozenset((r["a"], r["b"])) for r in by_bucket["positives"]}
    c = FIXTURE_CLAIMS
    assert got_pos == {
        frozenset((c["it-a1"], c["it-a2"])),
        frozenset((c["it-a1"], c["it-a3"])),
        frozenset((c["it-a2"], c["it-a3"])),
        frozenset((c["it-b1"], c["it-b2"])),
    }
    ledger_pair = next(r for r in by_bucket["positives"]
                       if frozenset((r["a"], r["b"])) == frozenset((c["it-a1"], c["it-a3"])))
    assert ledger_pair["jaccard"] < GROUND_TRUTH_JACCARD  # same-cluster by LEDGER
    assert all(r["cluster_a"] == r["cluster_b"] for r in by_bucket["positives"])

    # Hygiene: the structured blob appears nowhere.
    assert all("leaked blob" not in r["a"] + r["b"] for r in rows)

    # Negatives: cross-component only; hard bucket takes all supply here
    # (7 texts, 4 components -> 17 cross pairs < 30), random gets the rest (0).
    assert len(by_bucket["hard_negatives"]) == 17
    assert len(by_bucket["random_negatives"]) == 0
    for r in by_bucket["hard_negatives"]:
        assert r["cluster_a"] != r["cluster_b"]
        assert r["label"] == "not_equivalent"
    scores = [r["prefilter_overlap"] for r in by_bucket["hard_negatives"]]
    assert scores == sorted(scores, reverse=True)


def test_missing_corpus_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_set.build_rows(tmp_path / "absent.jsonl", tmp_path / "also_absent.jsonl")
    lm, _il = _write_fixture(tmp_path)
    with pytest.raises(FileNotFoundError):
        build_set.build_rows(lm, tmp_path / "absent_ledger.jsonl")
