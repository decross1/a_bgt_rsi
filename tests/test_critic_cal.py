"""Tests — D1/D2 critic calibration + override audit (bench/critic_cal).

Prereg: experiments/PREREG_critic_cal_2026-08-19.md (v2). Everything here
runs under MOCK_LLM=1 with ZERO model calls and zero retrieval calls.

Covered:
- manifest determinism (rebuild is byte-identical; parametrized over
  SHUFFLED loop_memory input order and three PYTHONHASHSEEDs), tamper
  refusal, stratum shape, and the S1 census-drift refusal;
- exclusion reporting: every rejected candidate carries a reason, counts
  by reason sum to the total, and nothing is dropped silently;
- replay fidelity: seeded envelopes have the ``result`` wrapper the
  critic actually reads, cache and loop_memory copies agree by sha256,
  and the relevance-warning invariant holds per stratum;
- audit determinism (shuffled input + hash seeds), invariant enforcement,
  and the two blocking predicates being named and computed separately;
- driver bar arithmetic exactly AT each threshold, Clopper-Pearson spot
  checks, --out anchoring to REPO_ROOT, and the hard MOCK_LLM refusal;
- the driver makes ZERO model calls under MOCK_LLM (it refuses first).
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from bench.critic_cal import audit_overrides as audit  # noqa: E402
from bench.critic_cal import build_manifest as bm  # noqa: E402
from bench.critic_cal import driver as drv  # noqa: E402

PY = str(REPO_ROOT / ".venv-chroma" / "bin" / "python")


@pytest.fixture(scope="module")
def loop_memory() -> list[dict]:
    return bm._read_jsonl(bm.LOOP_MEMORY_PATH)


@pytest.fixture(scope="module")
def manifest() -> list[dict]:
    return bm.load_manifest()


# ===========================================================================
# Manifest — determinism, shape, refusal
# ===========================================================================

def test_manifest_matches_a_fresh_resolution(manifest):
    """The frozen manifest re-resolves byte-for-byte from the source stores.
    This is what makes the manifest (not the builder) the reproducible
    artifact — and unlike a live-retrieval builder, it can actually hold."""
    bm.verify_manifest(manifest)


def test_manifest_shape_and_strata(manifest):
    assert len(manifest) == bm.TOTAL_N == 26
    counts = {s: sum(1 for f in manifest if f["stratum"] == s) for s in ("S1", "S2", "S3")}
    assert counts == {"S1": 10, "S2": 8, "S3": 8}
    assert len({f["fixture_id"] for f in manifest}) == len(manifest)
    # One judgment can never consume two fixture slots.
    assert len({f["iteration_id"] for f in manifest}) == len(manifest)


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
def test_manifest_is_invariant_under_shuffled_input(loop_memory, seed):
    """Row ORDER in loop_memory.jsonl must not reach the manifest. The fold
    is over a set of rows; only the pinned sort keys order the output."""
    baseline, _ = bm.resolve(loop_memory)
    shuffled = list(loop_memory)
    random.Random(seed).shuffle(shuffled)
    got, _ = bm.resolve(shuffled)
    assert bm.serialize(got) == bm.serialize(baseline)


@pytest.mark.parametrize("hashseed", ["0", "1", "12345"])
def test_manifest_is_invariant_under_pythonhashseed(hashseed):
    """This repo shipped a hash-seed ordering bug on 2026-08-18. Rebuild in
    a fresh interpreter under three seeds and compare the emitted bytes."""
    env = dict(os.environ, PYTHONHASHSEED=hashseed, MOCK_LLM="1")
    out = subprocess.run(
        [PY, "-c",
         "import sys; sys.path.insert(0, '.');"
         "from bench.critic_cal import build_manifest as bm;"
         "f, _ = bm.build();"
         "import hashlib;"
         "print(hashlib.sha256(bm.serialize(f).encode()).hexdigest())"],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=300,
    )
    assert out.returncode == 0, out.stderr
    expected = hashlib.sha256(bm.MANIFEST_PATH.read_bytes()).hexdigest()
    assert out.stdout.strip() == expected


def test_manifest_refuses_a_tampered_row(manifest):
    tampered = copy.deepcopy(manifest)
    tampered[0]["hypothesis_text"] = tampered[0]["hypothesis_text"] + " TAMPERED"
    with pytest.raises(bm.ResolutionError) as exc:
        bm.verify_manifest(tampered)
    assert "diverges" in str(exc.value)


def test_s1_census_drift_refuses_rather_than_resampling(loop_memory):
    """S1 is a CENSUS. If the population changes the builder must refuse,
    not quietly pick a different 10 (inviolate rule 4)."""
    trimmed = [
        r for r in loop_memory
        if not (
            (r.get("critique") or {}).get("verdict") == "undecidable"
            and "verdict_overridden_from" not in (r.get("critique") or {})
            and bm.pack_is_adequate(r)
            and r.get("iteration_id") == "iter-2026-08-18-002"
        )
    ]
    with pytest.raises(bm.ResolutionError) as exc:
        bm.resolve(trimmed)
    assert "CENSUS" in str(exc.value)


def test_self_check_rejects_a_wrong_relevance_warning_state(manifest):
    bad = copy.deepcopy(manifest)
    s1 = next(f for f in bad if f["stratum"] == "S1")
    s1["prompt_shape"]["relevance_warning_fires"] = True
    with pytest.raises(bm.ResolutionError) as exc:
        bm._self_check(bad)
    assert "relevance warning" in str(exc.value)


# ===========================================================================
# Exclusion reporting — never a silent drop
# ===========================================================================

def test_every_exclusion_carries_a_reason_and_the_counts_reconcile(loop_memory):
    _, meta = bm.resolve(loop_memory)
    by_reason = meta["exclusions_by_reason"]
    assert by_reason, "expected exclusions to be reported"
    for entry in by_reason:
        assert entry["reason"].strip()
        assert entry["n"] == len(entry["iteration_ids"]) > 0
    assert sum(e["n"] for e in by_reason) == meta["n_exclusions_total"]


def test_unusable_rows_are_excluded_by_name_not_by_silence(loop_memory):
    _, meta = bm.resolve(loop_memory)
    reasons = {e["reason"]: e for e in meta["exclusions_by_reason"]}
    no_crit = [r for r in loop_memory if not (r.get("critique") or {})]
    assert reasons["no critique block"]["n"] == len(no_crit)
    assert sorted(reasons["no critique block"]["iteration_ids"]) == sorted(
        r["iteration_id"] for r in no_crit
    )
    # Non-'passed' critic calls are excluded at BUILD time, so a run-time
    # status != passed can only be a driver defect (V1), never a finding.
    assert any("subagent_status" in k for k in reasons)


def test_pool_sizes_are_reported_alongside_the_picks(loop_memory):
    _, meta = bm.resolve(loop_memory)
    for stratum in ("S1", "S2", "S3"):
        s = meta["strata"][stratum]
        assert s["pool_n"] >= s["n"]
    for q in meta["strata"]["S2"]["quotas"]:
        assert len(q["chosen"]) == q["quota"] <= q["pool_n"]


# ===========================================================================
# Replay fidelity — the shape the critic actually reads
# ===========================================================================

def test_seeded_envelope_has_the_result_wrapper_the_critic_reads(manifest):
    """critic_loop_v0.py:619 reads retrieval['result']['neighbors']. The
    loop_memory copy is FLATTENED (no 'result' wrapper); the cache copy is
    the full worker envelope. Copying the flattened block straight in would
    make the worker return status 'error' AFTER the calls were spent."""
    for f in manifest:
        env = f["retrieval_envelope"]
        assert set(env) >= {"status", "result"}, f["fixture_id"]
        neighbors = env["result"]["neighbors"]
        assert isinstance(neighbors, list) and neighbors
        assert all("doc_id" in n for n in neighbors)


def test_cache_and_loop_memory_packs_agree_by_sha256(manifest, loop_memory):
    by_id = {r["iteration_id"]: r for r in loop_memory}
    for f in manifest:
        mem = by_id[f["iteration_id"]]["retrieval"]
        assert bm._canon_sha(f["retrieval_envelope"]["result"]["neighbors"]) == (
            bm._canon_sha(mem["neighbors"])
        ), f["fixture_id"]
        assert bm._canon_sha(f["retrieval_envelope"]["result"].get("relevance")) == (
            bm._canon_sha(mem.get("relevance"))
        ), f["fixture_id"]


def test_relevance_warning_fires_exactly_on_the_flagged_stratum(manifest):
    for f in manifest:
        fires = f["prompt_shape"]["relevance_warning_fires"]
        assert fires == (f["stratum"] == "S3"), f["fixture_id"]


def test_cache_namespace_cannot_collide_with_the_iter_glob(manifest):
    """experiments/lit_falsification_battery/calibrate_anchor.py:80 globs
    the shared cache root for 'iter-*'. The synthetic ids must miss it."""
    for f in manifest:
        assert f["cache_iteration_id"].startswith("critcal-")
        assert not f["cache_iteration_id"].startswith("iter-")


def test_relevance_recompute_divergence_is_recorded_not_applied(loop_memory):
    """The pure recomputation is a diagnostic, never the replayed block:
    recomputing would erase the flagged stratum (D-075 R2 demoted R0 for
    curated-phrase hypotheses, and R0 needs an LLM verdict the recorded
    block alone carries)."""
    fixtures, meta = bm.resolve(loop_memory)
    div = meta["relevance_recompute_divergence"]
    assert div["n_fixtures_diverging"] > 0
    for f in fixtures:
        if f["stratum"] == "S3":
            # replayed block still flags; the recomputation may not
            assert f["relevance_recorded"]["low_confidence"] is True


def test_probe_suppresses_the_warning_and_touches_nothing_else(manifest):
    f = next(x for x in manifest if x["stratum"] == "S3")
    env = f["retrieval_envelope"]
    probe = drv.suppress_warning(env)
    assert env["result"]["relevance"]["low_confidence"] is True
    assert probe["result"]["relevance"]["low_confidence"] is False
    assert probe["result"]["relevance"]["category"] == "ok"
    assert "probe_mutation" in probe["result"]["relevance"]
    assert probe["result"]["neighbors"] == env["result"]["neighbors"]


# ===========================================================================
# Driver bar arithmetic — exactly AT the thresholds
# ===========================================================================

def _row(stratum: str, verdict_raw: str, *, recorded: str = "survives",
         status: str = "passed", kind: str | None = None, turns: int = 1) -> dict:
    return {
        "fixture_id": f"{stratum}-x{verdict_raw}{recorded}{turns}{kind}",
        "stratum": stratum,
        "worker_status": status,
        "verdict_raw": verdict_raw,
        "verdict_final": verdict_raw,
        "recorded_verdict_raw": recorded,
        "undecidable_kind": kind if kind is not None else (
            "substantive" if verdict_raw == "undecidable" else None
        ),
        "mid_flight_retrieval_inferred": turns >= 2,
    }


def _arm_rows(s1_dec: int, s2_und: int, s3_und: int) -> list[dict]:
    rows = []
    for i in range(10):
        rows.append(_row("S1", "survives" if i < s1_dec else "undecidable",
                         recorded="undecidable", turns=i))
    for i in range(8):
        rows.append(_row("S2", "undecidable" if i < s2_und else "survives",
                         recorded="survives", turns=i))
    for i in range(8):
        rows.append(_row("S3", "undecidable" if i < s3_und else "survives",
                         recorded="undecidable", turns=i))
    return rows


@pytest.mark.parametrize("k,expected", [(0, False), (1, False), (2, True), (8, True)])
def test_C1_at_its_threshold(k, expected):
    ev = drv.evaluate(_arm_rows(5, 0, k), "production")
    assert ev["bars"]["C1"]["k"] == k
    assert ev["bars"]["C1"]["pass"] is expected


@pytest.mark.parametrize("k,expected", [(0, True), (4, True), (5, False), (8, False)])
def test_C2_at_its_threshold(k, expected):
    ev = drv.evaluate(_arm_rows(5, k, 4), "production")
    assert ev["bars"]["C2"]["k"] == k
    assert ev["bars"]["C2"]["pass"] is expected


@pytest.mark.parametrize("n_bad,expected_pass", [(0, True), (2, True), (3, False)])
def test_V1_parse_health_at_its_threshold(n_bad, expected_pass):
    rows = _arm_rows(5, 0, 4)
    for i in range(n_bad):
        rows[i]["worker_status"] = "error"
        rows[i]["undecidable_kind"] = "worker_error"
    ev = drv.evaluate(rows, "production")
    assert ev["run_validity"]["V1"]["n_non_substantive"] == n_bad
    assert ev["run_validity"]["V1"]["pass"] is expected_pass
    assert ev["arm_void"] is (not expected_pass)


def test_failure_sink_undecidables_never_score_as_judgments():
    """critic_loop_v0.py:801-848 makes 'undecidable' both a verdict AND the
    failure sink. A schema_mismatch row is charged to V1 and leaves C2's
    denominator entirely — scoring it would let a broken instrument look
    merely cautious."""
    rows = _arm_rows(5, 0, 4)
    s2 = [r for r in rows if r["stratum"] == "S2"]
    s2[0]["verdict_raw"] = "undecidable"
    s2[0]["undecidable_kind"] = "schema_mismatch"
    ev = drv.evaluate(rows, "production")
    assert ev["run_validity"]["V1"]["n_non_substantive"] == 1
    assert ev["bars"]["C2"]["k"] == 0
    assert ev["bars"]["C2"]["n"] == 7


def test_worker_error_rows_leave_the_discrimination_denominators():
    rows = _arm_rows(5, 0, 4)
    for r in rows:
        if r["stratum"] == "S3":
            r["worker_status"] = "error"
            r["undecidable_kind"] = "worker_error"
            break
    ev = drv.evaluate(rows, "production")
    assert ev["bars"]["C1"]["n"] == 7


def test_degenerate_instruments_each_fail_exactly_one_bar():
    always = drv.evaluate(_arm_rows(0, 8, 8), "production")
    assert always["bars"]["C1"]["pass"] is True
    assert always["bars"]["C2"]["pass"] is False
    never = drv.evaluate(_arm_rows(10, 0, 0), "production")
    assert never["bars"]["C1"]["pass"] is False
    assert never["bars"]["C2"]["pass"] is True


def test_E1_is_an_estimate_with_no_pass_fail():
    ev = drv.evaluate(_arm_rows(7, 0, 4), "production")
    e1 = ev["estimates"]["E1_recorded_undecidable_replays_decisive"]
    assert e1["k"] == 7 and e1["n"] == 10
    assert e1["pass_fail"] is None
    assert "pass" not in e1
    assert set(e1["pre_stated_reading"]) == {">=7 of 10", "<=3 of 10", "4-6 of 10"}


def test_mid_flight_split_is_reported_and_never_excluded():
    ev = drv.evaluate(_arm_rows(5, 0, 4), "production")
    mf = ev["mid_flight_retrieval"]
    assert mf["n_inferred"] > 0
    # denominators are untouched by the split
    assert ev["bars"]["C1"]["n"] == 8 and ev["bars"]["C2"]["n"] == 8


def test_attribution_sentence_and_void_semantics_ride_on_every_evaluation():
    ev = drv.evaluate(_arm_rows(5, 0, 4), "production")
    assert "59 undecidable rows" in ev["attribution"]
    assert "10 are" in ev["attribution"] and "30 were" in ev["attribution"]
    assert "re-thresholding" in ev["void_semantics"]
    assert "capped at EXACTLY ONE" in ev["void_semantics"]


@pytest.mark.parametrize("x,n,lo,hi", [
    (10, 120, 0.0407, 0.1479),
    (7, 52, 0.0559, 0.2579),
    (19, 36, 0.3549, 0.6959),
    (7, 10, 0.3475, 0.9333),
    (3, 10, 0.0667, 0.6525),
])
def test_clopper_pearson_spot_checks(x, n, lo, hi):
    got_lo, got_hi = drv.clopper_pearson(x, n)
    assert got_lo == pytest.approx(lo, abs=1e-4)
    assert got_hi == pytest.approx(hi, abs=1e-4)


def test_pinned_reference_rates_match_the_live_record():
    """The bar-calibration references in the driver are not folklore — they
    must still reproduce from the ledger the audit reads."""
    rep = audit.build_report(include_rows=False, now="fixed")
    ref = rep["production_reference_rates"]
    assert (ref["all_time"]["k"], ref["all_time"]["n"]) == (
        drv.REF_NATIVE_UNDECIDABLE_ADEQUATE_ALLTIME
    )
    aug = next(m for m in ref["by_month"] if m["month"] == "2026-08")
    assert (aug["k"], aug["n"]) == drv.REF_NATIVE_UNDECIDABLE_ADEQUATE_AUGUST


# ===========================================================================
# Driver refusals and --out anchoring
# ===========================================================================

def test_driver_refuses_under_mock_llm_and_makes_zero_calls(tmp_path):
    """The refusal happens BEFORE any repo import, so nothing that could
    make a call is ever loaded. Asserted two ways: the exit code, and an
    empty wrapper calls log in the same interpreter."""
    env = dict(os.environ, MOCK_LLM="1")
    out = subprocess.run(
        [PY, "-m", "bench.critic_cal.driver", "--arm", "production",
         "--out", str(tmp_path / "x.json")],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=120,
    )
    assert out.returncode == 2, out.stdout + out.stderr
    assert "REFUSING (exit 2)" in out.stderr
    assert not (tmp_path / "x.json").exists()


def test_driver_zero_calls_under_mock_llm_via_memory_log(tmp_path):
    env = dict(os.environ, MOCK_LLM="1")
    probe = (
        "import sys; sys.path.insert(0, '.');"
        "from bench.critic_cal.driver import main;"
        "rc = main(['--arm', 'production', '--out', 'bench/critic_cal/runs/z.json']);"
        "from agent_wrapper import wrapper as w;"
        "print('RC', rc, 'CALLS', len(w.MEMORY_LOG))"
    )
    out = subprocess.run([PY, "-c", probe], cwd=REPO_ROOT, env=env,
                         capture_output=True, text=True, timeout=180)
    assert out.returncode == 0, out.stderr
    assert "RC 2 CALLS 0" in out.stdout
    assert not (REPO_ROOT / "bench" / "critic_cal" / "runs" / "z.json").exists()


def test_probe_arm_refuses_without_owner_ratification(tmp_path, monkeypatch):
    monkeypatch.delenv("MOCK_LLM", raising=False)
    rc = drv.main(["--arm", "warning-suppressed-probe",
                   "--out", str(tmp_path / "p.json")])
    assert rc == 5
    assert not (tmp_path / "p.json").exists()


@pytest.mark.parametrize("rel", ["a.json", "runs/a.json", "./a.json",
                                 "bench/critic_cal/runs/prod.json"])
def test_out_is_anchored_to_repo_root(rel):
    """A relative --out crashed a battery AFTER its calls were spent (R1a).
    Anchoring is a named function called first thing in run_arm."""
    anchored = drv.anchor_out(Path(rel))
    assert anchored.is_absolute()
    assert anchored.is_relative_to(drv.REPO_ROOT)


def test_absolute_out_is_left_alone(tmp_path):
    p = tmp_path / "elsewhere.json"
    assert drv.anchor_out(p) == p


def test_run_arm_anchors_before_anything_can_fail(monkeypatch):
    """Given a relative --out, run_arm must reach its refusals without a
    path exception — the R1a failure mode was a crash at artifact-write
    time, i.e. AFTER the calls."""
    monkeypatch.setattr(drv, "load_manifest", lambda *a, **k: [])
    monkeypatch.setattr(drv, "manifest_shape_ok", lambda f: (False, "forced"))
    assert drv.run_arm("production", Path("relative/out.json"), None) == 4


def test_paired_probe_reading_rule_is_code_not_prose():
    """The probe's comparison rule is pre-stated as an executable function
    so it cannot be narrated after the numbers land."""
    prod = [_row("S3", "undecidable", recorded="undecidable") for _ in range(8)]
    probe = [dict(r) for r in prod]
    for i, r in enumerate(prod):
        r["fixture_id"] = probe[i]["fixture_id"] = f"S3-f{i}"

    # total effect: every fixture flips when the warning is removed
    for r in probe:
        r["verdict_raw"] = "survives"
    cmp_total = drv.paired_probe_comparison(prod, probe)
    assert cmp_total["discordant_warning_only"] == 8
    assert cmp_total["sign_test_two_sided_p"] == pytest.approx(2 / 256)
    assert cmp_total["effect_read"] is True

    # 7 flip, 1 stays -> only 7 DISCORDANT pairs, all one way: still p<0.05
    probe[0]["verdict_raw"] = "undecidable"
    cmp_seven = drv.paired_probe_comparison(prod, probe)
    assert cmp_seven["discordant_warning_only"] == 7
    assert cmp_seven["concordant"] == 1
    assert cmp_seven["sign_test_two_sided_p"] == pytest.approx(2 / 128)
    assert cmp_seven["effect_read"] is True

    # 5 discordant, all one way -> p=0.0625, NOT an effect
    for r in probe[:3]:
        r["verdict_raw"] = "undecidable"
    cmp_five = drv.paired_probe_comparison(prod, probe)
    assert cmp_five["discordant_warning_only"] == 5
    assert cmp_five["sign_test_two_sided_p"] == pytest.approx(2 / 32)
    assert cmp_five["effect_read"] is False

    # ANY reversal kills it: 7 one way, 1 the other -> p=0.0703
    prod_rev = [dict(r) for r in prod]
    prod_rev[0]["verdict_raw"] = "survives"
    probe_rev = [dict(r) for r in prod]
    for r in probe_rev[1:]:
        r["verdict_raw"] = "survives"
    cmp_rev = drv.paired_probe_comparison(prod_rev, probe_rev)
    assert (cmp_rev["discordant_warning_only"], cmp_rev["discordant_probe_only"]) == (7, 1)
    assert cmp_rev["sign_test_two_sided_p"] == pytest.approx(0.0703, abs=1e-4)
    assert cmp_rev["effect_read"] is False

    # no discordance at all -> no p-value, no effect
    for i, r in enumerate(probe):
        r["verdict_raw"] = prod[i]["verdict_raw"]
    cmp_null = drv.paired_probe_comparison(prod, probe)
    assert cmp_null["sign_test_two_sided_p"] is None
    assert cmp_null["effect_read"] is False


def test_driver_refuses_a_manifest_of_the_wrong_shape(manifest):
    ok, why = drv.manifest_shape_ok(manifest)
    assert ok, why
    bad = [f for f in manifest if f["stratum"] != "S3"]
    ok, why = drv.manifest_shape_ok(bad)
    assert not ok and "expected 26" in why


# ===========================================================================
# D2 — audit determinism, invariants, and the two blocking predicates
# ===========================================================================

@pytest.fixture(scope="module")
def report() -> dict:
    return audit.build_report(include_rows=True, now="fixed")


def test_audit_is_deterministic(report):
    again = audit.build_report(include_rows=True, now="fixed")
    assert json.dumps(again, sort_keys=True) == json.dumps(report, sort_keys=True)


@pytest.mark.parametrize("seed", [0, 7, 99])
def test_audit_aggregates_are_invariant_under_shuffled_rows(loop_memory, seed):
    """Row order must not reach any aggregate. (The idea-ledger fold is a
    genuine event log and is order-DEPENDENT by construction — its
    canonical order is file order, which is why the audit uses
    workers.idea_ledger.load_state rather than a timestamp sort over a
    file with 37 duplicate-timestamp groups.)"""
    base = audit.build_rows(loop_memory)
    shuffled = list(loop_memory)
    random.Random(seed).shuffle(shuffled)
    got = audit.build_rows(shuffled)
    key = lambda rows: json.dumps(  # noqa: E731
        sorted(rows, key=lambda r: r["iteration_id"]), sort_keys=True
    )
    assert key(got) == key(base)
    assert json.dumps(audit.undecidable_census(got), sort_keys=True) == (
        json.dumps(audit.undecidable_census(base), sort_keys=True)
    )
    assert json.dumps(audit.production_reference_rates(got), sort_keys=True) == (
        json.dumps(audit.production_reference_rates(base), sort_keys=True)
    )


@pytest.mark.parametrize("hashseed", ["0", "1", "9999"])
def test_audit_is_invariant_under_pythonhashseed(hashseed):
    env = dict(os.environ, PYTHONHASHSEED=hashseed, MOCK_LLM="1")
    out = subprocess.run(
        [PY, "-c",
         "import sys, json, hashlib; sys.path.insert(0, '.');"
         "from bench.critic_cal import audit_overrides as a;"
         "r = a.build_report(include_rows=True, now='fixed');"
         "print(hashlib.sha256(json.dumps(r, sort_keys=True).encode()).hexdigest())"],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=300,
    )
    assert out.returncode == 0, out.stderr
    ref = hashlib.sha256(
        json.dumps(audit.build_report(include_rows=True, now="fixed"),
                   sort_keys=True).encode()
    ).hexdigest()
    assert out.stdout.strip() == ref


def test_audit_coverage_invariants_are_enforced_not_asserted(loop_memory):
    rows = audit.build_rows(loop_memory)
    rep = {
        "census": {"overall_by_class": [{"key": "NATIVE", "n": len(rows) - 1}]},
        "undecidable_census": audit.undecidable_census(rows),
    }
    with pytest.raises(audit.AuditInvariantError) as exc:
        audit.check_invariants(loop_memory, rows, rep)
    assert "sum to" in str(exc.value)


def test_audit_refuses_a_dropped_row(loop_memory):
    rows = audit.build_rows(loop_memory)[:-1]
    with pytest.raises(audit.AuditInvariantError) as exc:
        audit.check_invariants(loop_memory, rows, {"census": {}, "undecidable_census": {}})
    assert "rows read" in str(exc.value)


def test_audit_flags_an_unknown_override_prefix(loop_memory):
    rows = audit.build_rows(loop_memory)
    rows[0]["override_class"] = "OTHER"
    rows[0]["override_reason"] = "brand new seam shipped today"
    rep = {
        "census": {"overall_by_class": [{"key": "x", "n": len(rows)}]},
        "undecidable_census": audit.undecidable_census(rows),
    }
    with pytest.raises(audit.AuditInvariantError) as exc:
        audit.check_invariants(loop_memory, rows, rep)
    assert "prefix table" in str(exc.value)


def test_override_class_keys_on_prefix_never_substring():
    """A substring test for 'debate' mis-sorts skeptic rows whose own prose
    contains the word — two 07-06 rows do exactly that."""
    cls, _ = audit.classify_override({
        "verdict_overridden_from": "survives",
        "override_reason": "skeptic attack_verdict='refuted': the debate over "
                           "this mechanism is settled",
    })
    assert cls == "SKEPTIC"


def test_blocking_is_computed_on_both_predicates_and_named_apart(report):
    dn = report["downstream"]
    strict = dn["blocked_by_override_L1_ladder"]
    loose = dn["t2e_blocked_loose"]
    assert strict["n"] < loose["n"], "the loose bound must be the larger one"
    assert set(strict["ids"]) <= set(loose["ids"])
    assert len(loose["already_L0_for_other_reasons"]) == loose["n"] - strict["n"]
    assert "derive_level" in strict["predicate"]
    assert "UPPER BOUND" in loose["predicate"]


def test_undecidable_census_splits_native_by_pack_state(report):
    uc = report["undecidable_census"]
    assert uc["n_undecidable"] == 59
    native = {c["key"]: c["n"] for c in uc["native_by_pack_state"]}
    assert native["adequate"] + native["flagged"] == 29
    assert native["adequate"] < native["flagged"], (
        "the dominant NATIVE driver is flagged packs, not clean ones"
    )
    assert str(native["adequate"]) in uc["attribution_sentence"]


def test_cluster_reconstruction_has_no_ordering_ambiguity(report):
    assert report["clusters"]["reconstruction_disagreements"] == []
    assert report["clusters"]["n_open_clusters"] == 20


def test_audit_makes_zero_model_calls():
    """MEMORY_LOG is process-global and other tests in a full-suite run
    populate it, so measure the DELTA across the audit, not the absolute
    length — an absolute assertion here passes alone and fails in suite,
    which is a test defect, not a finding."""
    from agent_wrapper import wrapper as w
    before = len(w.MEMORY_LOG)
    rep = audit.build_report(include_rows=False, now="fixed")
    assert len(w.MEMORY_LOG) - before == 0
    assert rep["model_calls_made"] == 0
