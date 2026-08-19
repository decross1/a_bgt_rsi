"""Tests — graveyard re-adjudication battery (bench/readjudication).

Prereg: experiments/PREREG_readjudication_2026-08-19.md (v2). Everything
here runs under MOCK_LLM=1 with ZERO model calls:

- manifest determinism: byte-identical output under shuffled loop_memory
  and shuffled fixture input order, and under different PYTHONHASHSEEDs in
  a real subprocess (this repo shipped a hash-seed-ordering bug on
  2026-08-18 — the ordering key is sha256, never builtins.hash());
- exclusion reporting: every qualifying-by-kill-code cluster lands in
  targets XOR exclusions, each exclusion carries a reason from the frozen
  enum, and the L1 `cluster_refined_since_kill` rule fires with sidecars;
- contamination refusal (L9): a control text that is also a target text
  refuses the build;
- bar arithmetic AT the thresholds (C1, C2, C3a, C3b, C4) including the
  F1 revert scenario the old bars had ~zero power against;
- unscored semantics: never `proceed`, phi's bound pair, kappa_old's
  all-rows polarity, U decomposed by NEW verdict, R partitioned
  exhaustively;
- prompt-sha assertion: the frozen old prompt matches its pin, and a
  drifted module constant refuses before any call;
- `--out` anchoring (the R1a driver crashed on a relative --out AFTER
  spending its calls);
- the driver makes ZERO calls under the MOCK_LLM refusal.
"""
import json
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from bench.readjudication import build_manifest as bm
from bench.readjudication import driver

MANIFEST_PATH = REPO_ROOT / "bench" / "readjudication" / "manifest.jsonl"
OLD_PROMPT_PATH = REPO_ROOT / "bench" / "readjudication" / "old_prompt.txt"


# ── helpers ─────────────────────────────────────────────────────────

def _shuffle_lines(src: Path, dst: Path, seed: int) -> Path:
    lines = [ln for ln in src.read_text().splitlines() if ln.strip()]
    random.Random(seed).shuffle(lines)
    dst.write_text("\n".join(lines) + "\n")
    return dst


def _control(row_id, label, verdict, provenance="constructed"):
    return {"row_id": row_id, "kind": "control", "label": label,
            "verdict": verdict, "provenance_class": provenance}


def _target(row_id, verdict, **kw):
    row = {"row_id": row_id, "kind": "target", "verdict": verdict,
           "label": None, "era": "2026-08", "historical_confidence": 0.95,
           "cluster_member_count": 1}
    row.update(kw)
    return row


def _arm_rows(good_verdicts, bad_verdicts, target_verdicts=()):
    rows = [_control(f"g{i}", "known_good", v)
            for i, v in enumerate(good_verdicts)]
    rows += [_control(f"b{i}", "known_bad", v)
             for i, v in enumerate(bad_verdicts)]
    rows += [_target(f"t{i}", v) for i, v in enumerate(target_verdicts)]
    return rows


# ── manifest: determinism ───────────────────────────────────────────

@pytest.mark.parametrize("seed", [0, 1, 17, 2026])
def test_manifest_is_byte_identical_under_shuffled_inputs(tmp_path, seed):
    """Input LINE ORDER must not reach the output. loop_memory is read into
    a dict keyed by iteration_id and fixtures are re-sorted before the
    order key is applied, so a shuffle changes only the source shas."""
    lm = _shuffle_lines(REPO_ROOT / "memory" / "loop_memory.jsonl",
                        tmp_path / "loop_memory.jsonl", seed)
    fx = _shuffle_lines(REPO_ROOT / "bench" / "redteam_cal" / "fixtures.jsonl",
                        tmp_path / "fixtures.jsonl", seed + 1000)

    meta_a, rows_a = bm.build()
    meta_b, rows_b = bm.build(loop_memory_path=lm, fixtures_path=fx)

    assert [json.dumps(r, sort_keys=True) for r in rows_a] == \
           [json.dumps(r, sort_keys=True) for r in rows_b]
    volatile = {"loop_memory_sha256", "fixtures_sha256", "fixtures_path"}
    assert {k: v for k, v in meta_a.items() if k not in volatile} == \
           {k: v for k, v in meta_b.items() if k not in volatile}


def test_manifest_is_byte_identical_under_shuffled_ledger_blocks(tmp_path):
    """Ledger EVENT order matters to the reducer only WITHIN a cluster.
    Shuffling whole per-cluster blocks (order preserved inside each) must
    not move a single manifest row."""
    src = REPO_ROOT / "memory" / "idea_ledger.jsonl"
    blocks: dict = {}
    order: list = []
    for line in src.read_text().splitlines():
        if not line.strip():
            continue
        cid = json.loads(line).get("cluster_id")
        if cid not in blocks:
            blocks[cid] = []
            order.append(cid)
        blocks[cid].append(line)
    random.Random(5).shuffle(order)
    shuffled = tmp_path / "idea_ledger.jsonl"
    shuffled.write_text(
        "\n".join(ln for cid in order for ln in blocks[cid]) + "\n")

    _, rows_a = bm.build()
    _, rows_b = bm.build(ledger_path=shuffled)
    assert [r["row_id"] for r in rows_a] == [r["row_id"] for r in rows_b]
    assert [json.dumps(r, sort_keys=True) for r in rows_a] == \
           [json.dumps(r, sort_keys=True) for r in rows_b]


@pytest.mark.parametrize("hashseed", ["0", "1", "12345"])
def test_manifest_has_no_hash_seed_dependence(tmp_path, hashseed):
    """A real subprocess per seed — PYTHONHASHSEED only takes effect at
    interpreter start, so an in-process check would prove nothing."""
    out = tmp_path / f"m{hashseed}.jsonl"
    env = dict(os.environ, PYTHONHASHSEED=hashseed, MOCK_LLM="1")
    res = subprocess.run(
        [sys.executable, "-m", "bench.readjudication.build_manifest",
         "--out", str(out)],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=300,
    )
    assert res.returncode == 0, res.stderr
    assert out.read_bytes() == MANIFEST_PATH.read_bytes()


def test_order_key_is_sha256_of_utf8_row_id():
    import hashlib
    for rid in ("cl-iter-2026-08-16-019", "rtc-bad-cons-02", "é—unicode"):
        assert bm.order_key(rid) == hashlib.sha256(
            rid.encode("utf-8")).hexdigest()


def test_locked_manifest_matches_the_driver_pin():
    """The lock is only a lock if the driver's pinned sha is the file's."""
    assert bm.sha256_file(MANIFEST_PATH) == driver.LOCKED_MANIFEST_SHA256
    meta, rows = bm.load_manifest(MANIFEST_PATH)
    kinds = {k: sum(1 for r in rows if r["kind"] == k)
             for k in driver.LOCKED_MANIFEST_COUNTS}
    assert kinds == driver.LOCKED_MANIFEST_COUNTS
    assert rows == sorted(rows, key=lambda r: (r["order_key"], r["row_id"]))


# ── manifest: exclusions ────────────────────────────────────────────

def test_every_qualifying_cluster_is_a_target_xor_an_exclusion():
    meta, rows = bm.load_manifest(MANIFEST_PATH)
    targets = {r["row_id"] for r in rows if r["kind"] == "target"}
    excluded = {e["cluster_id"] for e in meta["exclusions"]}
    assert not (targets & excluded)
    assert len(targets) + len(excluded) == meta["qualifying_by_kill_code"]
    assert meta["n_targets"] == len(targets)
    assert meta["n_excluded"] == len(meta["exclusions"])


def test_exclusion_reasons_come_from_the_frozen_enum_and_are_counted():
    meta, _ = bm.load_manifest(MANIFEST_PATH)
    for exc in meta["exclusions"]:
        assert exc["reason"] in bm.EXCLUSION_REASONS
        assert exc["cluster_id"]
    for reason, n in meta["exclusions_by_reason"].items():
        assert reason in bm.EXCLUSION_REASONS
        assert n == sum(1 for e in meta["exclusions"]
                        if e["reason"] == reason)


def test_refined_cluster_is_excluded_and_gets_both_sidecar_texts():
    """L1: the reduced cluster's LIVE claim is the refined one, so a proceed
    on the superseded founding text is not reopening evidence for it. Rule
    fixed BEFORE the number: it is 1 cluster today."""
    meta, rows = bm.load_manifest(MANIFEST_PATH)
    refined = [e["cluster_id"] for e in meta["exclusions"]
               if e["reason"] == "cluster_refined_since_kill"]
    assert refined
    sidecars = [r for r in rows if r["kind"] == "sidecar"]
    for cid in refined:
        variants = {r["variant"] for r in sidecars if r["cluster_id"] == cid}
        assert variants == {"founding", "refined"}
    assert all(r["row_id"] not in {s["row_id"] for s in sidecars}
               for r in rows if r["kind"] == "target")


def test_a_cluster_missing_its_founding_text_is_excluded_not_dropped():
    state = {"cl-iter-2026-01-01-001": {
        "members": ["iter-2026-01-01-001"], "evidence_level": "L0",
        "kill_reason": {"code": "redteam_fatal_flaw",
                        "evidence_key": "iteration:iter-2026-01-01-001:redteam"},
        "reopening_condition": dict(bm.REQUIRED_REOPENING_CONDITION)}}
    targets, exclusions = bm.select_targets(state, {})
    assert targets == []
    assert [e["reason"] for e in exclusions] == ["historical_verdict_not_fatal"]


def test_post_swap_and_backend_mismatch_are_separate_exclusion_reasons():
    def _cluster():
        return {"members": ["iter-x"], "evidence_level": "L0",
                "kill_reason": {"code": "redteam_fatal_flaw",
                                "evidence_key": "iteration:iter-x:redteam"},
                "reopening_condition": dict(bm.REQUIRED_REOPENING_CONDITION)}

    def _row(ended_at, backend="vllm-gemma", model="gemma-4-26b-a4b"):
        return {"iter-x": {
            "iteration_id": "iter-x", "ended_at": ended_at,
            "hypothesis": {"text": "a claim"},
            "redteam": {"verdict": "fatal_flaw", "subagent_backend": backend,
                        "subagent_model": model, "retries_used": 2,
                        "subagent_status": "passed", "confidence": 0.9}}}

    _, exc = bm.select_targets({"cl-a": _cluster()},
                               _row("2026-08-18T07:00:00Z"))
    assert exc[0]["reason"] == "judged_post_swap"
    _, exc = bm.select_targets({"cl-a": _cluster()},
                               _row("2026-08-17T00:00:00Z", backend="vllm-qwen"))
    assert exc[0]["reason"] == "historical_backend_mismatch"
    targets, exc = bm.select_targets({"cl-a": _cluster()},
                                     _row("2026-08-17T00:00:00Z"))
    assert exc == [] and len(targets) == 1
    assert targets[0]["claim_text"] == "a claim"


def test_contamination_scan_refuses_a_control_that_is_also_a_target():
    """L9 lock-time assertion — a colliding row would make a known-bad LABEL
    and a reopen-eligibility CLAIM refer to the same claim."""
    text = "the very same claim text on both sides"
    targets = [{"cluster_id": "cl-a", "founding_iteration": "iter-a",
                "claim_text": text, "claim_sha256": bm.sha256_text(text)}]
    controls = [{"row_id": "rtc-bad-01", "claim_text": text,
                 "claim_sha256": bm.sha256_text(text)}]
    scan = bm.contamination_scan(targets, controls)
    assert scan["clean"] is False
    assert scan["exact_text_collisions"]

    clean = bm.contamination_scan(
        targets, [{"row_id": "rtc-bad-01",
                   "claim_text": "an entirely unrelated proposition",
                   "claim_sha256": bm.sha256_text("x")}])
    assert clean["clean"] is True


def test_live_manifest_contamination_is_clean_and_reported():
    meta, _ = bm.load_manifest(MANIFEST_PATH)
    scan = meta["contamination_scan"]
    assert scan["clean"] is True
    assert scan["max_cross_set_jaccard"]["jaccard"] < \
        bm.CONTAMINATION_JACCARD_MAX


# ── bars ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fatal_bad,expected", [(5, False), (6, True),
                                                (7, True), (0, False)])
def test_C1_new_catches_bad_at_the_threshold(fatal_bad, expected):
    bad = ["fatal_flaw"] * fatal_bad + ["proceed"] * (12 - fatal_bad)
    ev = driver.evaluate_arm(_arm_rows(["proceed"] * 12, bad), "new")
    assert ev["bars"]["C1_new_catches_bad"]["pass"] is expected


def test_C1_counts_unscored_against_the_new_arm():
    """Unscored is NEVER proceed and never a catch (prereg §5)."""
    bad = ["fatal_flaw"] * 5 + ["unscored"] * 7
    ev = driver.evaluate_arm(_arm_rows(["proceed"] * 12, bad), "new")
    assert ev["bars"]["C1_new_catches_bad"]["pass"] is False
    assert ev["bars"]["C1_new_catches_bad"]["fatal"] == 5


@pytest.mark.parametrize("fatal_good,parsed,expected", [
    (4, 12, True),    # 4/12 = 33.3% <= 35%
    (5, 12, False),   # 5/12 = 41.7% > 35%
    (2, 7, True),     # 2/7 = 28.6%
    (3, 7, False),    # 3/7 = 42.9%
])
def test_C4_new_passes_good_at_the_threshold(fatal_good, parsed, expected):
    good = (["fatal_flaw"] * fatal_good
            + ["proceed"] * (parsed - fatal_good)
            + ["unscored"] * (12 - parsed))
    ev = driver.evaluate_arm(_arm_rows(good, ["fatal_flaw"] * 12), "new")
    assert ev["bars"]["C4_new_passes_good"]["pass"] is expected


def test_C4_catches_the_silently_reverted_new_arm():
    """F1: the failure the draft's bars had ~zero power against. Under a
    revert BOTH arms run the old prompt, so C1 passes with certainty (the
    old prompt scored 12/12 on known-bad) and C2 passes trivially. C4 is
    the bar that fires."""
    good = ["unscored"] * 5 + ["fatal_flaw"] * 6 + ["proceed"] * 1  # R1a old arm
    bad = ["fatal_flaw"] * 12                                      # R1a old arm
    ev = driver.evaluate_arm(_arm_rows(good, bad), "new")
    assert ev["bars"]["C1_new_catches_bad"]["pass"] is True
    assert ev["bars"]["C4_new_passes_good"]["pass"] is False
    assert ev["run_validity"]["void"] is True


@pytest.mark.parametrize("fatal_good,parsed,expected", [
    (6, 12, True), (5, 12, False), (4, 7, True), (3, 7, False),
    (3, 5, True), (2, 5, False),
])
def test_C2_old_condemns_good_at_the_threshold(fatal_good, parsed, expected):
    good = (["fatal_flaw"] * fatal_good
            + ["proceed"] * (parsed - fatal_good)
            + ["unscored"] * (12 - parsed))
    ev = driver.evaluate_arm(_arm_rows(good, ["fatal_flaw"] * 12), "old")
    assert ev["bars"]["C2_old_condemns_good"]["pass"] is expected


def test_C2_is_not_evaluable_below_five_parsed():
    good = ["fatal_flaw"] * 4 + ["unscored"] * 8
    ev = driver.evaluate_arm(_arm_rows(good, ["fatal_flaw"] * 12), "old")
    bar = ev["bars"]["C2_old_condemns_good"]
    assert bar["evaluable"] is False and bar["pass"] is False


def test_old_arm_parse_health_is_reported_never_barred():
    """The old prompt demonstrably fails parse on sound claims — that is the
    instrument under study, not a run failure (prereg §4.3)."""
    ev = driver.evaluate_arm(
        _arm_rows(["unscored"] * 12, ["fatal_flaw"] * 12,
                  ["unscored"] * 40), "old")
    assert ev["bars"]["old_parse_health_REPORTED_ONLY"]["hard"] is False
    assert ev["run_validity"]["void"] is False


@pytest.mark.parametrize("n_unscored,expected", [(13, True), (14, False)])
def test_C3a_target_parse_health_at_the_cap(n_unscored, expected):
    targets = ["unscored"] * n_unscored + ["proceed"] * (88 - n_unscored)
    ev = driver.evaluate_arm(
        _arm_rows(["proceed"] * 12, ["fatal_flaw"] * 12, targets), "new")
    assert ev["bars"]["C3a_parse_health_targets"]["pass"] is expected


@pytest.mark.parametrize("n_unscored,expected", [(4, True), (5, False)])
def test_C3b_control_parse_health_at_the_cap(n_unscored, expected):
    good = ["unscored"] * n_unscored + ["proceed"] * (12 - n_unscored)
    ev = driver.evaluate_arm(_arm_rows(good, ["fatal_flaw"] * 12), "new")
    assert ev["bars"]["C3b_parse_health_controls"]["pass"] is expected


def test_C3_split_catches_a_target_concentrated_parse_regression():
    """F5: the pooled 113-row bar passed while 17 TARGET verdicts vanished.
    Split, the same run voids."""
    targets = ["unscored"] * 17 + ["proceed"] * 71
    ev = driver.evaluate_arm(
        _arm_rows(["proceed"] * 12, ["fatal_flaw"] * 12, targets), "new")
    pooled = 17  # of 112 main-pass rows = 15.2% — under the draft's 17/113
    assert pooled / 112 < 0.16
    assert ev["bars"]["C3a_parse_health_targets"]["pass"] is False
    assert ev["run_validity"]["void"] is True


# ── verdict semantics + cross-arm statistics ────────────────────────

def _artifacts(old_targets, new_targets, good=None, bad=None):
    good = good or ["proceed"] * 12
    bad = bad or ["fatal_flaw"] * 12
    new_rows = _arm_rows(good, bad, new_targets)
    old_rows = _arm_rows(["fatal_flaw"] * 12, bad, old_targets)
    return (
        {"arm": "old", "rows": old_rows,
         "evaluation": driver.evaluate_arm(old_rows, "old")},
        {"arm": "new", "rows": new_rows,
         "evaluation": driver.evaluate_arm(new_rows, "new")},
    )


def test_unscored_is_never_a_proceed_in_phi():
    old, new = _artifacts(["fatal_flaw"] * 4, ["unscored"] * 4)
    ev = driver.evaluate_pair(old, new)
    assert ev["phi"]["numerator"] == 0
    assert ev["phi"]["point"] == 0.0
    assert ev["phi"]["interval_bound"] == [0.0, 1.0]
    assert ev["phi"]["unscored_on_targets"] == 4


def test_phi_interval_bound_and_quotability_rule():
    old, new = _artifacts(["fatal_flaw"] * 10,
                          ["proceed"] * 5 + ["unscored"] * 4 + ["fatal_flaw"])
    ev = driver.evaluate_pair(old, new)
    assert ev["phi"]["interval_bound"] == [0.5, 0.9]
    assert ev["phi"]["point_estimate_quotable_alone"] is True
    old, new = _artifacts(["fatal_flaw"] * 10,
                          ["proceed"] * 5 + ["unscored"] * 5)
    ev = driver.evaluate_pair(old, new)
    assert ev["phi"]["point_estimate_quotable_alone"] is False


def test_kappa_old_primary_polarity_counts_unscored_as_non_reproduction():
    """F3(ii): an OLD-arm unscored today IS the event that historically
    meant 'proceed, no kill'. 60/88 (0.68), not 60/72 (0.83)."""
    old_t = ["fatal_flaw"] * 60 + ["proceed"] * 12 + ["unscored"] * 16
    new_t = ["proceed"] * 88
    old, new = _artifacts(old_t, new_t)
    ev = driver.evaluate_pair(old, new)
    assert ev["kappa_old"]["primary_all_rows"]["x"] == 60
    assert ev["kappa_old"]["primary_all_rows"]["n"] == 88
    assert round(ev["kappa_old"]["primary_all_rows"]["rate"], 4) == 0.6818
    assert round(
        ev["kappa_old"]["secondary_parsed_only_UPPER_BOUND"]["rate"], 4
    ) == 0.8333


def test_two_by_two_identity_and_U_decomposed_by_new_verdict():
    old_t = ["fatal_flaw", "proceed", "fatal_flaw", "proceed", "unscored",
             "unscored"]
    new_t = ["proceed", "proceed", "fatal_flaw", "fatal_flaw", "proceed",
             "unscored"]
    old, new = _artifacts(old_t, new_t)
    ev = driver.evaluate_pair(old, new)
    t = ev["two_by_two"]
    assert (t["A_old_fatal_new_proceed"], t["B_old_proceed_new_proceed"],
            t["C_old_fatal_new_fatal"], t["D_old_proceed_new_fatal"],
            t["U_either_arm_unscored"]) == (1, 1, 1, 1, 2)
    assert t["identity_holds"] is True
    assert t["U_by_new_verdict"] == {"proceed": 1, "fatal_flaw": 0,
                                     "unscored": 1}
    assert t["U_old_unscored_and_new_proceed"] == 1


def test_R_is_partitioned_exhaustively_including_the_U_and_R_bucket():
    """F6: R strictly contains A u B; the U-and-R rows had no cell and no
    rank in the draft's disposition menu."""
    old_t = ["fatal_flaw", "proceed", "unscored"]
    new_t = ["proceed", "proceed", "proceed"]
    old, new = _artifacts(old_t, new_t)
    ev = driver.evaluate_pair(old, new)
    part = ev["R_partition"]
    assert part["sizes"] == {"A": 1, "B": 1, "U_and_R": 1}
    assert part["identity_holds"] is True
    assert part["sizes"]["A"] + part["sizes"]["B"] + part["sizes"]["U_and_R"] \
        == ev["phi"]["numerator"]


def test_prompt_attribution_reading_is_gated_on_the_same_run_bad_controls():
    """F4: phi needs a pre-stated comparator or every phi is a finding."""
    # NEW proceeds on 11/12 known-bad AND on ~90% of targets -> overlapping
    # CIs -> the attribution reading is UNAVAILABLE.
    permissive_bad = ["proceed"] * 11 + ["fatal_flaw"]
    old, new = _artifacts(["fatal_flaw"] * 10, ["proceed"] * 9 + ["fatal_flaw"],
                          bad=permissive_bad)
    ev = driver.evaluate_pair(old, new)
    assert ev["phi_comparators"]["prompt_attribution_reading_available"] \
        is False
    # A discriminating NEW arm: 1/12 proceed on known-bad, 90% on targets.
    old, new = _artifacts(["fatal_flaw"] * 10, ["proceed"] * 9 + ["fatal_flaw"],
                          bad=["fatal_flaw"] * 11 + ["proceed"])
    ev = driver.evaluate_pair(old, new)
    assert ev["phi_comparators"]["prompt_attribution_reading_available"] \
        is True


def test_mcnemar_exact_matches_hand_computed_values():
    assert driver._mcnemar_exact(20, 2) == pytest.approx(1.211e-4, rel=1e-2)
    assert driver._mcnemar_exact(10, 3) == pytest.approx(0.0923, rel=1e-2)
    assert driver._mcnemar_exact(0, 0) == 1.0


def test_evaluate_pair_refuses_a_partial_new_artifact():
    old, new = _artifacts(["fatal_flaw"], ["proceed"])
    new["evaluation"] = {"uninterpretable": True, "reason": "aborted"}
    with pytest.raises(ValueError, match="no same-run control rates"):
        driver.evaluate_pair(old, new)


def test_sidecar_rows_never_enter_a_bar_or_a_statistic():
    rows = _arm_rows(["proceed"] * 12, ["fatal_flaw"] * 12, ["proceed"] * 5)
    rows += [{"row_id": "sidecar:cl-x:refined", "kind": "sidecar",
              "verdict": "fatal_flaw", "label": None}]
    ev = driver.evaluate_arm(rows, "new")
    assert ev["counts"]["sidecars_EXPLORATORY"]["n"] == 1
    assert ev["bars"]["C3a_parse_health_targets"]["n"] == 5
    assert ev["counts"]["targets"]["n"] == 5


# ── prompt sha assertion ────────────────────────────────────────────

def test_frozen_old_prompt_matches_the_pinned_sha_and_the_r1a_artifact():
    text = driver.load_old_prompt()
    assert bm.sha256_text(text) == driver.OLD_PROMPT_SHA256
    r1a = json.loads(
        (REPO_ROOT / driver.R1A_REFERENCE["old"]["path"]).read_text())
    assert r1a["prompt_sha256"] == driver.OLD_PROMPT_SHA256


def test_live_production_prompt_matches_the_pinned_new_sha():
    from workers import redteam_critic as rt
    assert bm.sha256_text(rt.REDTEAM_AGENT_SYSTEM_PROMPT) == \
        driver.NEW_PROMPT_SHA256


def test_extract_old_prompt_from_git_reproduces_the_pin():
    """Appendix A's recovery is CODE, not prose: AST + literal_eval over the
    31-fragment implicit concatenation (a regex would fail OPEN)."""
    assert bm.sha256_text(bm.extract_old_prompt()) == bm.OLD_PROMPT_SHA256


def test_run_arm_refuses_a_drifted_module_prompt_before_any_call(monkeypatch,
                                                                tmp_path):
    """F1: a silently reverted / edited seam refuses BEFORE the first call —
    exit 7 for the new arm, exit 6 for the old."""
    called = []
    from workers import redteam_critic as rt
    monkeypatch.setattr(rt, "REDTEAM_AGENT_SYSTEM_PROMPT", "not the prompt")
    monkeypatch.setattr(rt, "redteam_critic",
                        lambda *a, **k: called.append(a) or {})
    monkeypatch.delenv("MOCK_LLM", raising=False)
    rc = driver.run_arm("new", tmp_path / "new.json")
    assert rc == 7
    assert called == []
    assert not (tmp_path / "new.json").exists()


def test_run_arm_end_to_end_on_the_locked_manifest_with_a_stubbed_worker(
        monkeypatch, tmp_path):
    """Structural smoke of the whole arm path — row build, per-row sha
    assertion, served-model join, artifact + calls dump, evaluation — with a
    STUBBED worker, so zero model calls are made."""
    from workers import redteam_critic as rt
    seen = []

    def fake(text, iteration_id, **kw):
        seen.append(iteration_id)
        return {"status": "passed", "result": {
            "verdict": "proceed", "critique": "c", "confidence": 0.9,
            "subagent_status": "passed", "subagent_backend": "vllm-gemma",
            "subagent_model": "gemma-4-26b-a4b"}, "errors": [],
            "wrapper_request_id": None}

    monkeypatch.setattr(rt, "redteam_critic", fake)
    monkeypatch.setattr(driver, "probe_served_model",
                        lambda *a, **k: {"url": "stub",
                                         "model": driver.PINNED_MODEL,
                                         "probed_at": "stub", "error": None})
    monkeypatch.delenv("MOCK_LLM", raising=False)
    out = tmp_path / "new.json"
    assert driver.run_arm("new", out) == 0
    art = json.loads(out.read_text())
    assert art["prompt_sha256"] == driver.NEW_PROMPT_SHA256
    assert len(seen) == 114 + driver.REPLICATE_N
    assert all(r["prompt_sha256_at_call"] == driver.NEW_PROMPT_SHA256
               for r in art["rows"])
    ev = art["evaluation"]
    assert ev["bars"]["C1_new_catches_bad"]["pass"] is False  # stub proceeds
    assert ev["run_validity"]["void"] is True
    assert art["served_model_probe_before"]["model"] == driver.PINNED_MODEL
    assert art["vllm_image_digest"]
    assert list((tmp_path).glob("calls_new_*.jsonl"))
    # Q3 replicate is scored separately and never enters the target counts.
    rep = ev["q3_replicate_agreement"]
    assert rep["n"] == driver.REPLICATE_N and rep["rate"] == 1.0
    assert ev["counts"]["targets"]["n"] == 88


def test_run_arm_refuses_a_manifest_sha_mismatch(monkeypatch, tmp_path):
    monkeypatch.setattr(driver, "LOCKED_MANIFEST_SHA256", "deadbeef")
    rc = driver.run_arm("new", tmp_path / "new.json")
    assert rc == 4


def test_run_arm_refuses_a_fixtures_sha_mismatch(monkeypatch, tmp_path):
    monkeypatch.setattr(driver, "LOCKED_FIXTURES_SHA256", "deadbeef")
    rc = driver.run_arm("new", tmp_path / "new.json")
    assert rc == 5


# ── --out anchoring ─────────────────────────────────────────────────

def test_relative_out_is_anchored_to_repo_root_before_anything_expensive(
        monkeypatch, tmp_path):
    """The R1a driver crashed on a relative --out AFTER spending its calls.
    Anchoring happens first; here the run then refuses on the sha, and the
    anchored path is the one that would have been written."""
    seen = {}
    monkeypatch.setattr(driver, "LOCKED_MANIFEST_SHA256", "deadbeef")
    real_mkdir = Path.mkdir

    def spy_mkdir(self, *a, **k):
        seen.setdefault("parent", self)
        return real_mkdir(self, *a, **k)

    monkeypatch.setattr(Path, "mkdir", spy_mkdir)
    rc = driver.run_arm("new", Path("bench/readjudication/runs/x.json"))
    assert rc == 4
    assert seen["parent"] == driver.REPO_ROOT / "bench/readjudication/runs"
    assert seen["parent"].is_absolute()


def test_evaluate_pair_mode_anchors_a_relative_out(tmp_path, monkeypatch):
    old, new = _artifacts(["fatal_flaw"], ["proceed"])
    (tmp_path / "old.json").write_text(json.dumps(old))
    (tmp_path / "new.json").write_text(json.dumps(new))
    monkeypatch.setattr(driver, "REPO_ROOT", tmp_path)
    rc = driver.main(["--evaluate-pair", str(tmp_path / "old.json"),
                      str(tmp_path / "new.json"),
                      "--out", "runs/eval.json"])
    assert rc == 0
    assert (tmp_path / "runs" / "eval.json").exists()


def test_out_is_required():
    with pytest.raises(SystemExit):
        driver.main(["--arm", "new"])


def test_exactly_one_mode_is_required(tmp_path):
    assert driver.main(["--out", str(tmp_path / "x.json")]) == 10
    assert driver.main(["--arm", "new", "--evaluate-pair", "a", "b",
                        "--out", str(tmp_path / "x.json")]) == 10


# ── MOCK_LLM refusal: ZERO calls ────────────────────────────────────

def test_driver_makes_zero_calls_under_mock_llm(monkeypatch, tmp_path):
    monkeypatch.setenv("MOCK_LLM", "1")
    called = []
    from workers import redteam_critic as rt
    monkeypatch.setattr(rt, "redteam_critic",
                        lambda *a, **k: called.append(a) or {})
    monkeypatch.setattr(driver, "run_arm",
                        lambda *a, **k: pytest.fail("run_arm must not run"))
    rc = driver.main(["--arm", "new", "--out", str(tmp_path / "new.json")])
    assert rc == 2
    assert called == []
    assert not (tmp_path / "new.json").exists()


def test_mock_llm_refusal_is_exit_2_in_a_real_subprocess(tmp_path):
    res = subprocess.run(
        [sys.executable, "-m", "bench.readjudication.driver",
         "--arm", "old", "--out", str(tmp_path / "old.json")],
        cwd=REPO_ROOT, env=dict(os.environ, MOCK_LLM="1"),
        capture_output=True, text=True, timeout=120,
    )
    assert res.returncode == 2
    assert "REFUSING (exit 2)" in res.stderr
    assert not (tmp_path / "old.json").exists()
