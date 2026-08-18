"""Tests — D-075 R1a redteam calibration battery (bench/redteam_cal).

Prereg: experiments/PREREG_redteam_cal_2026-08-18.md (v2). Covered here,
all under MOCK_LLM=1 with zero LLM calls:

- manifest integrity: 24 rows, 12/12 split, non-empty merit rationales,
  register band on constructed rows, >=2 rescuable mechanism clauses,
  7 distinct planted-flaw classes, banned-provenance exclusions (no
  exp-null / Verdict=NO / novelty-only material; near-dup dropped),
  resolution reproducibility (build_fixtures determinism + tamper refusal);
- driver bar math on synthetic fixtures (pass / fail / coin / boundary /
  unscored-exclusion cases) + exact Clopper-Pearson CI spot checks
  against independently computed (scipy) reference values;
- the gemma-revised prompt-swap seam (module-constant override reaches
  run_subagent's system_prompt) + byte-compatibility of the revised
  prompt's JSON output contract;
- driver refusal (exit 2) when MOCK_LLM is set.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from bench.redteam_cal import build_fixtures as bf
from bench.redteam_cal import driver
from orchestrator.subagent import SubAgentResult

FIXTURES_PATH = REPO_ROOT / "bench" / "redteam_cal" / "fixtures.jsonl"
DRIVER_PATH = REPO_ROOT / "bench" / "redteam_cal" / "driver.py"


@pytest.fixture(scope="module")
def manifest():
    return bf.load_manifest(FIXTURES_PATH)


# ── manifest integrity ──────────────────────────────────────────────


def test_manifest_shape_24_rows_12_12(manifest):
    assert len(manifest) == 24
    n_good = sum(1 for r in manifest if r["label"] == "known_good")
    n_bad = sum(1 for r in manifest if r["label"] == "known_bad")
    assert (n_good, n_bad) == (12, 12)
    assert len({r["id"] for r in manifest}) == 24


def test_manifest_required_keys_and_rationales(manifest):
    for r in manifest:
        assert set(r) == {
            "id", "hypothesis_text", "label", "provenance", "label_rationale"
        }, r["id"]
        assert r["label"] in ("known_good", "known_bad")
        assert r["hypothesis_text"].strip()
        # Every rationale is a substantive merit defense, never empty.
        assert len(r["label_rationale"].strip()) >= 40, r["id"]
        assert r["provenance"]["class"] in (
            "real-historical", "battery", "constructed"
        )


def test_register_band_on_constructed_rows(manifest):
    constructed = [
        r for r in manifest if r["provenance"]["class"] == "constructed"
    ]
    assert len(constructed) == 13  # 6 sound + 7 planted-flaw
    for r in constructed:
        wc = bf.word_count(r["hypothesis_text"])
        assert 25 <= wc <= 45, f"{r['id']}: {wc} words outside 25-45 band"


def test_constructed_sound_mechanism_clauses(manifest):
    cons_good = [
        r for r in manifest
        if r["label"] == "known_good"
        and r["provenance"]["class"] == "constructed"
    ]
    assert len(cons_good) == 6
    flagged = [
        r for r in cons_good
        if r["provenance"].get("mechanism_clause_rescuable") is True
    ]
    assert len(flagged) >= 2
    for r in flagged:
        text = r["hypothesis_text"].lower()
        assert any(m in text for m in ("because", "via", "rather than")), r["id"]


def test_seven_distinct_planted_flaw_classes(manifest):
    cons_bad = [
        r for r in manifest
        if r["label"] == "known_bad"
        and r["provenance"]["class"] == "constructed"
    ]
    assert len(cons_bad) == 7
    classes = [r["provenance"]["flaw_class"] for r in cons_bad]
    assert len(set(classes)) == 7, f"classes not distinct: {classes}"
    for r in cons_bad:
        assert r["label_rationale"].startswith("Planted flaw class:"), r["id"]


# Prereg exclusions: novelty-only vetoes, L0 no-evidence-record vetoes,
# and empirical Verdict=NO refutations are BANNED from the manifest —
# a cleanly refuted claim was demonstrably testable (proceed-class).
BANNED_SOURCE_IDS = {
    # near-duplicate proceed dropped per prereg pin
    "iter-2026-06-09-006",
    # empirical Verdict=NO refutations (exp-null direction of the ban)
    "iter-2026-06-05-006", "iter-2026-06-10-001", "iter-2026-06-10-002",
    "iter-2026-08-17-008", "iter-2026-08-17-009", "iter-2026-08-17-011",
    # frontier-screen entries NOT pinned as intrinsic kills
    "cl-iter-2026-05-26-008", "cl-iter-2026-05-26-009",
    "cl-iter-2026-05-27-002", "cl-iter-2026-06-05-002",
    "cl-iter-2026-07-13-001", "cl-iter-2026-07-15-001",
}

EXPECTED_SOURCE_IDS = {
    "iter-2026-06-09-005", "iter-2026-06-19-012", "iter-2026-05-27-028",
    "novel_on_01_quant_lockin", "novel_on_02_critic_flip_model",
    "novel_on_03_levelk_quantal_bridge",
    "iter-2026-08-18-005",
    "cl-iter-2026-06-05-005", "cl-iter-2026-05-27-004",
    "nonsense_01_word_salad", "nonsense_02_not_a_question",
}


def test_banned_provenance_exclusions(manifest):
    source_ids = {
        r["provenance"]["source_id"]
        for r in manifest if "source_id" in r["provenance"]
    }
    assert source_ids == EXPECTED_SOURCE_IDS
    assert not (source_ids & BANNED_SOURCE_IDS)
    # Teeth: the banned records' actual hypothesis TEXTS are absent —
    # no exp-null / Verdict=NO claim rides in under any label.
    lm = {}
    with (REPO_ROOT / "memory" / "loop_memory.jsonl").open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                rec = json.loads(line)
                lm[rec.get("iteration_id")] = rec
    banned_texts = set()
    for bid in BANNED_SOURCE_IDS:
        rec = lm.get(bid.removeprefix("cl-"))
        if rec:
            t = ((rec.get("hypothesis") or {}).get("text") or "").strip()
            if t:
                banned_texts.add(t)
    assert banned_texts  # the ban list must have real teeth
    fixture_texts = {r["hypothesis_text"] for r in manifest}
    assert not (fixture_texts & banned_texts)


def test_resolution_reproducibility_determinism(manifest):
    # Fresh resolution from the source stores == the frozen file, twice.
    fresh_a = bf.build_manifest()
    fresh_b = bf.build_manifest()
    assert fresh_a == fresh_b == manifest
    # Byte-level: serializing the fresh build reproduces the file exactly.
    assert bf.serialize(fresh_a) == FIXTURES_PATH.read_text()


def test_verify_manifest_refuses_on_tamper(manifest):
    tampered = json.loads(json.dumps(manifest))
    tampered[0]["hypothesis_text"] += " TAMPERED"
    with pytest.raises(bf.ResolutionError):
        bf.verify_manifest(tampered)


# ── driver bar math (synthetic fixtures) ────────────────────────────


def _rows(bad_fatal, bad_proceed, good_fatal, good_proceed,
          bad_unscored=0, good_unscored=0, cls="constructed"):
    rows = []
    spec = [
        ("known_bad", "fatal_flaw", bad_fatal),
        ("known_bad", "proceed", bad_proceed),
        ("known_bad", "unscored", bad_unscored),
        ("known_good", "fatal_flaw", good_fatal),
        ("known_good", "proceed", good_proceed),
        ("known_good", "unscored", good_unscored),
    ]
    i = 0
    for label, verdict, n in spec:
        for _ in range(n):
            rows.append({
                "id": f"syn-{i:02d}", "label": label,
                "provenance_class": cls, "verdict": verdict,
                "unscored": verdict == "unscored",
            })
            i += 1
    return rows


def test_bar_math_perfect_arm():
    ev = driver.evaluate(_rows(12, 0, 0, 12))
    b = ev["bars"]
    assert b["bar1"]["pass"] and b["bar1"]["unscored"] == 0
    assert b["bar2"]["pass"] and b["bar2"]["fatal"] == 12 and b["bar2"]["rate"] == 1.0
    assert b["bar3"]["pass"] and b["bar3"]["fatal"] == 0 and b["bar3"]["rate"] == 0.0
    assert b["bar4"]["gap_points"] == 100.0
    assert b["bar4"]["load_bearing"] is False
    assert ev["all_load_bearing_bars_pass"] is True


def test_bar_math_condemner_fails_bar3():
    ev = driver.evaluate(_rows(12, 0, 12, 0))
    b = ev["bars"]
    assert b["bar2"]["pass"] is True
    assert b["bar3"]["pass"] is False
    assert ev["all_load_bearing_bars_pass"] is False


def test_bar_math_coin_fails_both_discrimination_bars():
    ev = driver.evaluate(_rows(6, 6, 6, 6))
    b = ev["bars"]
    assert b["bar1"]["pass"] is True
    assert b["bar2"]["pass"] is False  # 50% < 75%
    assert b["bar3"]["pass"] is False  # 50% > 35%
    assert b["bar4"]["gap_points"] == 0.0


def test_bar_math_exact_boundaries():
    # 9/12 = 75% known-bad fatal -> bar2 passes AT the threshold.
    ev = driver.evaluate(_rows(9, 3, 4, 8))
    assert ev["bars"]["bar2"]["pass"] is True
    # 4/12 = 33.3% known-good fatal -> bar3 passes; 5/12 = 41.7% fails.
    assert ev["bars"]["bar3"]["pass"] is True
    ev2 = driver.evaluate(_rows(9, 3, 5, 7))
    assert ev2["bars"]["bar3"]["pass"] is False
    # 8/12 = 66.7% known-bad -> bar2 fails just under threshold.
    ev3 = driver.evaluate(_rows(8, 4, 0, 12))
    assert ev3["bars"]["bar2"]["pass"] is False


def test_bar_math_unscored_excluded_and_bars_independent():
    # 3 unscored bad + 1 unscored good = 4 > 2 -> bar1 FAILS, while
    # bar2 evaluates on the parsed denominator (7/9 = 77.8% -> pass):
    # rule 4 — bars stand alone, no coercion in either direction.
    ev = driver.evaluate(_rows(7, 2, 0, 11, bad_unscored=3, good_unscored=1))
    b = ev["bars"]
    assert ev["n_unscored"] == 4 and b["bar1"]["pass"] is False
    assert b["bar2"]["parsed"] == 9 and b["bar2"]["fatal"] == 7
    assert b["bar2"]["pass"] is True
    assert b["bar3"]["parsed"] == 11 and b["bar3"]["pass"] is True
    assert ev["all_load_bearing_bars_pass"] is False


def test_confusion_split_by_provenance():
    rows = (
        _rows(0, 2, 1, 1, cls="real-historical")
        + _rows(1, 0, 0, 2, cls="battery")
        + _rows(2, 1, 1, 2, good_unscored=1, cls="constructed")
    )
    ev = driver.evaluate(rows)
    good = ev["confusion"]["known_good_by_provenance"]
    assert good["real-historical"] == {
        "n": 2, "fatal_flaw": 1, "proceed": 1, "unscored": 0
    }
    assert good["battery"] == {
        "n": 2, "fatal_flaw": 0, "proceed": 2, "unscored": 0
    }
    assert good["constructed"] == {
        "n": 4, "fatal_flaw": 1, "proceed": 2, "unscored": 1
    }
    bad = ev["confusion"]["known_bad_by_provenance"]
    assert bad["battery"] == {
        "n": 1, "fatal_flaw": 1, "proceed": 0, "unscored": 0
    }


def test_clopper_pearson_spot_values():
    # Reference values computed independently with scipy.stats.beta
    # (.venv-chroma, scipy 1.17.1): beta.ppf CP closed form.
    cases = {
        (0, 12): (0.0, 0.264648),
        (12, 12): (0.735352, 1.0),
        (9, 12): (0.428142, 0.945139),
        (4, 12): (0.099246, 0.651124),
        (6, 12): (0.210945, 0.789055),
        (7, 20): (0.153909, 0.592189),
    }
    for (x, n), (lo_ref, hi_ref) in cases.items():
        lo, hi = driver.clopper_pearson(x, n)
        assert abs(lo - lo_ref) < 1e-4, (x, n, lo)
        assert abs(hi - hi_ref) < 1e-4, (x, n, hi)
    assert driver.clopper_pearson(0, 0) == (0.0, 1.0)


# ── prompt-swap seam ────────────────────────────────────────────────


def _capture_run_subagent(captured):
    def stub(**kwargs):
        captured.update(kwargs)
        return SubAgentResult(
            status="passed",
            result={"verdict": "proceed", "critique": "ok",
                    "suggested_revision": None, "confidence": 0.5},
            errors=[], wrapper_call_ids=["sa-rid-1"],
            turns_used=1, wall_seconds=0.1, output_tokens_used=10,
        )
    return stub


def test_prompt_swap_seam(monkeypatch):
    from workers import redteam_critic as rt_mod
    original = rt_mod.REDTEAM_AGENT_SYSTEM_PROMPT
    # Register teardown restore BEFORE the driver override mutates it.
    monkeypatch.setattr(rt_mod, "REDTEAM_AGENT_SYSTEM_PROMPT", original)
    captured = {}
    monkeypatch.setattr(rt_mod, "run_subagent", _capture_run_subagent(captured))

    # production variant: constant untouched, worker sends it verbatim.
    assert driver.apply_prompt_variant(rt_mod, "production") == original
    rt_mod.redteam_critic("some hypothesis", "iter-seam-1")
    assert captured["system_prompt"] == original

    # revised variant: the module-constant override reaches run_subagent.
    revised = driver.apply_prompt_variant(rt_mod, "revised")
    assert revised == driver.load_revised_prompt()
    # R1a adoption 2026-08-18: the battery elected gemma-revised, so the
    # production constant IS the revised text now (byte-identical — the
    # swap asserted sha256 against the winning arm's artifact). Before
    # adoption this asserted revised != original.
    assert revised == original
    rt_mod.redteam_critic("some hypothesis", "iter-seam-2")
    assert captured["system_prompt"] == revised

    # Third leg (review catch): with revised == original post-adoption, the
    # two legs above are tautological about the SEAM itself — prove the
    # module-constant override still reaches run_subagent with a sentinel.
    monkeypatch.setattr(rt_mod, "REDTEAM_AGENT_SYSTEM_PROMPT",
                        "SENTINEL-PROMPT-FOR-SEAM-TEST")
    rt_mod.redteam_critic("some hypothesis", "iter-seam-3")
    assert captured["system_prompt"] == "SENTINEL-PROMPT-FOR-SEAM-TEST"


def test_revised_prompt_output_contract_byte_compatible():
    from workers import redteam_critic as rt_mod
    production = rt_mod.REDTEAM_AGENT_SYSTEM_PROMPT
    revised = driver.load_revised_prompt()
    # The production JSON output contract (from the strict-JSON emission
    # instruction to the end) must appear VERBATIM in the revision.
    marker = "When you've judged, emit a FINAL assistant message"
    contract = production[production.index(marker):]
    assert contract in revised
    # And both prompts end on the same non-null rule.
    assert revised.endswith('`suggested_revision` is non-null ONLY for "fatal_flaw".')


# ── MOCK_LLM refusal ────────────────────────────────────────────────


def test_driver_refuses_when_mock_llm_set(tmp_path):
    env = dict(os.environ)
    env["MOCK_LLM"] = "1"
    proc = subprocess.run(
        [sys.executable, str(DRIVER_PATH),
         "--arm", "gemma-current", "--out", str(tmp_path / "out.json")],
        capture_output=True, text=True, env=env, cwd=REPO_ROOT, timeout=60,
    )
    assert proc.returncode == 2
    assert "MOCK_LLM" in proc.stderr
    assert not (tmp_path / "out.json").exists()
