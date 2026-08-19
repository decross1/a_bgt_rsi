"""Run driver — D1 critic calibration battery (one arm per process).

Prereg: experiments/PREREG_critic_cal_2026-08-19.md (v2). The driver reads
ONLY bench/critic_cal/manifest.jsonl; every constant, bar and denominator
below is pinned by the prereg and none is resolved at run time.

Arms
  production                 26 fixtures (S1 10 + S2 8 + S3 8). Production
                             as deployed: CRITIC_BACKEND=vllm-gemma, the
                             CRITIC_AGENT_SYSTEM_PROMPT in
                             workers/critic_loop_v0.py, budgets
                             max_turns=6 / max_wall_seconds=90.0, and the
                             three override seams explicitly OFF.
  warning-suppressed-probe   8 fixtures (S3 only), replayed with the
                             recorded relevance block mutated so the
                             RETRIEVAL RELEVANCE WARNING does NOT fire.
                             OWNER-ELECTED and NOT production-faithful:
                             it is the only way to separate DETECTION
                             from OBEDIENCE, since every genuinely
                             insufficient pack in the record carries the
                             warning. Labelled a PROBE everywhere it is
                             reported.

Production seam (verified, not assumed): the critic reads its neighbors
from the per-iteration cache, never from the caller —
workers/critic_loop_v0.py:610 read_entry(iteration_id, "retrieval") and
:619 retrieval["result"]["neighbors"]. Faithful replay is therefore SEED
THE CACHE, THEN CALL BY ID, which is exactly the staging pattern the
worker's own __main__ smoke uses (:862-876).

  seam := workers.critic_loop_v0.critic_loop_v0(hypothesis_text,
          iteration_id, parent_request_id=..., budget=SubAgentBudget(
          max_turns=6, max_wall_seconds=90.0))

CACHE WRITE — a NAMED EXCEPTION. The driver writes
run_state/iteration_cache/critcal-<fixture_id>/{retrieval,novelty}.json.
That is a live shared surface, so the namespace is pinned: the only
enumerator of the cache root is
experiments/lit_falsification_battery/calibrate_anchor.py:80, which globs
"iter-*", and ui/backend/iteration_journey.py joins on real
iteration_ids. "critcal-" collides with neither. The directories are
RETAINED after the run as reproducibility artifacts.

Refusals (never coerced):
  exit 2  MOCK_LLM is set — a stubbed run is silently meaningless
  exit 3  the vllm-gemma bench lock is held by another battery
  exit 4  manifest fails its shape check (26 rows, 10/8/8 strata)
  exit 5  --arm warning-suppressed-probe without --probe-ratified

Usage:
  env -u MOCK_LLM .venv-chroma/bin/python -m bench.critic_cal.driver \\
      --arm production --out bench/critic_cal/runs/production.json
"""
from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
MANIFEST_PATH = HERE / "manifest.jsonl"
LOCK_PATH = REPO_ROOT / "run_state" / ".bench-vllm-gemma.lock"

PREREG = "experiments/PREREG_critic_cal_2026-08-19.md"

# ── Prereg-pinned constants ────────────────────────────────────────────────
BACKEND = "vllm-gemma"
BUDGET_MAX_TURNS = 6
BUDGET_MAX_WALL_SECONDS = 90.0
# The one deliberate divergence from production, named and asserted in the
# artifact rather than inherited: D1's question is about the PRIMARY critic,
# and the skeptic/debate seams ARE the override chain, which D2 measures
# deterministically over 59 real rows at zero call cost.
ENV_PINS = {"NARA_SKEPTIC": "0", "NARA_DEBATE": "0", "NARA_RESTATE_SKEPTIC": "0"}

EXPECTED_STRATA = {"S1": 10, "S2": 8, "S3": 8}
EXPECTED_TOTAL = 26

DECISIVE_VERDICTS = ("survives", "restated", "falsified", "refuted")

ARMS = {
    "production": {"strata": ("S1", "S2", "S3"), "suppress_warning": False},
    "warning-suppressed-probe": {"strata": ("S3",), "suppress_warning": True},
}

# Bars — LOCKED, independent (inviolate rule 4), integer thresholds.
V1_MAX_NON_SUBSTANTIVE = 2
C1_MIN_UNDECIDABLE_S3 = 2   # NOT a rubber stamp
C2_MAX_UNDECIDABLE_S2 = 4   # NOT a condemner

# Production reference rates, measured from memory/loop_memory.jsonl by
# bench/critic_cal/audit_overrides.py and PINNED here so the report reads
# every estimate against the record instead of against an intuition.
REF_NATIVE_UNDECIDABLE_ADEQUATE_ALLTIME = (10, 120)
REF_NATIVE_UNDECIDABLE_ADEQUATE_AUGUST = (7, 52)
REF_RAW_UNDECIDABLE_ON_FLAGGED = (19, 36)

VOID_SEMANTICS = (
    "Void means: report the failure, report the arm as VOID, and stop. It "
    "does NOT mean re-thresholding, re-running until it passes, or "
    "explaining it away as an unlucky fixture set. Re-runs are capped at "
    "EXACTLY ONE, permitted only for a V2 serving-identity void or an "
    "infrastructure abort, and when a re-run happens BOTH runs and BOTH "
    "artifacts are reported."
)

CAVEAT = (
    "This battery measures REPRODUCIBILITY and DEGENERACY, not accuracy. No "
    "non-circular correctness label exists at usable N: the human gate "
    "ledger holds 7 rows / 6 iteration_ids and exactly 1 merit-defensible "
    "positive critic label, all June-register. C1 and C2 together kill the "
    "two degenerate instruments with certainty (an always-undecidable "
    "instrument fails C2 with P=1.0; a never-undecidable one fails C1 with "
    "P=1.0) but a uniform 4-way guesser passes the pair with P=0.62, so the "
    "pair is a DEGENERACY GUARD and never an endorsement. E1/E2/E3 are "
    "ESTIMATES with exact Clopper-Pearson intervals and carry no pass/fail."
)

ATTRIBUTION_SENTENCE = (
    "MANDATORY ATTRIBUTION: of the 59 undecidable rows in the record, 10 are "
    "NATIVE on an adequate pack (this battery's S1 census — the ONLY "
    "population it speaks to), 19 are NATIVE on a pack the apparatus itself "
    "flagged, where the critic's own prompt instructs it to say undecidable, "
    "and 30 were OVERRIDDEN after the critic had already said 'survives'. "
    "Nothing in this report is a statement about the other 49."
)


# ---------------------------------------------------------------------------
# Exact Clopper-Pearson — the unit-tested implementation from R1a, reused
# rather than re-derived.
# ---------------------------------------------------------------------------
from bench.redteam_cal.driver import clopper_pearson  # noqa: E402


def _binom_le(x: int, n: int, p: float) -> float:
    return sum(math.comb(n, k) * p**k * (1 - p) ** (n - k) for k in range(0, x + 1))


def _two_sided_sign_p(b: int, c: int) -> float | None:
    """Exact two-sided binomial p on discordant pairs (paired probe)."""
    n = b + c
    if n == 0:
        return None
    k = min(b, c)
    return min(1.0, 2.0 * _binom_le(k, n, 0.5))


def paired_probe_comparison(production_rows: list[dict], probe_rows: list[dict]) -> dict:
    """PRE-STATED comparison of the production arm's S3 against the
    warning-suppressed probe arm, on the SAME 8 fixtures.

    The question it exists for: on a flagged pack, is 'undecidable'
    DETECTION (the critic reads the pack and finds nothing bearing) or
    OBEDIENCE (the critic is following the RETRIEVAL RELEVANCE WARNING
    printed in its own prompt)? Every genuinely insufficient pack in the
    record carries that warning, so no history-only fixture can separate
    the two — this probe is the only separator, and it is NOT
    production-faithful.

    Reading rule, fixed in advance: an effect is read ONLY when the exact
    two-sided sign test on DISCORDANT pairs is p < 0.05. The sign test
    conditions on discordance, so at 8 paired fixtures that means at least
    SIX discordant pairs ALL moving the same way (6-0 -> p=0.0313;
    5-0 -> p=0.0625, NOT an effect), and ANY reversal kills it (7-1 ->
    p=0.0703, NOT an effect; 6-1 -> p=0.1250). The probe is underpowered
    by construction and says so.
    """
    prod = {r["fixture_id"]: r for r in production_rows if r["stratum"] == "S3"}
    prob = {r["fixture_id"]: r for r in probe_rows if r["stratum"] == "S3"}
    shared = sorted(set(prod) & set(prob))
    b = c = concordant = 0
    for fid in shared:
        p_und = prod[fid]["verdict_raw"] == "undecidable"
        q_und = prob[fid]["verdict_raw"] == "undecidable"
        if p_und and not q_und:
            b += 1
        elif q_und and not p_und:
            c += 1
        else:
            concordant += 1
    p_value = _two_sided_sign_p(b, c)
    return {
        "n_paired_fixtures": len(shared),
        "fixture_ids": shared,
        "undecidable_with_warning": sum(
            1 for f in shared if prod[f]["verdict_raw"] == "undecidable"
        ),
        "undecidable_without_warning": sum(
            1 for f in shared if prob[f]["verdict_raw"] == "undecidable"
        ),
        "discordant_warning_only": b,
        "discordant_probe_only": c,
        "concordant": concordant,
        "sign_test_two_sided_p": p_value,
        "effect_read": bool(p_value is not None and p_value < 0.05),
        "reading_rule": (
            "An effect is read ONLY at p < 0.05 on the exact two-sided sign "
            "test over DISCORDANT pairs. At 8 paired fixtures that needs at "
            "least 6 discordant pairs ALL in one direction (6-0 -> p=0.0313; "
            "5-0 -> p=0.0625, NOT an effect), and any reversal kills it "
            "(7-1 -> p=0.0703, NOT an effect). Underpowered by construction; "
            "a null here licenses nothing."
        ),
    }


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def load_manifest(path: Path = MANIFEST_PATH) -> list[dict]:
    rows = []
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def manifest_shape_ok(fixtures: list[dict]) -> tuple[bool, str]:
    counts = {s: sum(1 for f in fixtures if f["stratum"] == s) for s in EXPECTED_STRATA}
    if len(fixtures) != EXPECTED_TOTAL or counts != EXPECTED_STRATA:
        return False, (
            f"{len(fixtures)} rows, strata {counts}; expected {EXPECTED_TOTAL} "
            f"and {EXPECTED_STRATA}"
        )
    return True, "ok"


# ---------------------------------------------------------------------------
# Verdict recording semantics — three fields, never coerced
# ---------------------------------------------------------------------------

def undecidable_kind(result: dict, worker_status: str) -> str | None:
    """substantive | schema_mismatch | timeout | worker_error, or None when
    the returned verdict is not undecidable.

    Exists because critic_loop_v0.py:801-848 makes 'undecidable' BOTH a
    substantive verdict AND the failure sink. A failure-sink undecidable
    scored as a judgment would let a broken instrument look merely cautious.
    """
    if worker_status != "passed":
        return "worker_error"
    if result.get("verdict") != "undecidable":
        return None
    status = result.get("subagent_status")
    if status == "schema_mismatch":
        return "schema_mismatch"
    if status == "timeout":
        return "timeout"
    if status == "passed":
        return "substantive"
    return "unknown"


def suppress_warning(envelope: dict) -> dict:
    """PROBE ONLY. Return a copy of the retrieval envelope whose relevance
    block cannot fire the RETRIEVAL RELEVANCE WARNING or the coverage
    override. Everything else — every neighbor, every score, every
    chunk_text — is byte-identical to the recorded pack."""
    env = copy.deepcopy(envelope)
    rel = (env.get("result") or {}).get("relevance")
    if isinstance(rel, dict):
        rel["low_confidence"] = False
        rel["category"] = "ok"
        rel["probe_mutation"] = (
            "warning-suppressed-probe: low_confidence forced False and "
            "category forced 'ok'; NOT production-faithful"
        )
    return env


# ---------------------------------------------------------------------------
# Bars — pure, unit-tested on synthetic rows
# ---------------------------------------------------------------------------

def evaluate(rows: list[dict], arm: str) -> dict:
    """Run-validity bars FIRST, then the discrimination bars, then the
    estimates. Each bar stands alone; a near miss is a failure."""
    non_sub = [
        r for r in rows
        if r["worker_status"] != "passed"
        or (r["undecidable_kind"] not in (None, "substantive"))
    ]
    v1 = {
        "name": "V1_parse_health",
        "hard": True,
        "voids_arm_on_fail": True,
        "n_non_substantive": len(non_sub),
        "cap": V1_MAX_NON_SUBSTANTIVE,
        "n_calls": len(rows),
        "ids": sorted(r["fixture_id"] for r in non_sub),
        "pass": len(non_sub) <= V1_MAX_NON_SUBSTANTIVE,
        "note": (
            "Historical base rate 153 passed / 2 schema_mismatch / 1 null "
            "across 156 recorded critic calls. Any worker_status != 'passed' "
            "is a DRIVER DEFECT (every exclusion happens at manifest-build "
            "time), reported as such and never as a finding."
        ),
    }

    def _strat(s: str) -> list[dict]:
        # Discrimination bars score SUBSTANTIVE rows only. A failure-sink
        # undecidable (schema_mismatch / timeout / worker_error) is charged
        # to V1 and never to a discrimination numerator — scoring it as a
        # judgment would let a broken instrument look merely cautious.
        return [
            r for r in rows
            if r["stratum"] == s
            and r["undecidable_kind"] in (None, "substantive")
        ]

    s1, s2, s3 = _strat("S1"), _strat("S2"), _strat("S3")

    bars: dict = {"V1": v1}
    estimates: dict = {}

    if "S3" in ARMS[arm]["strata"] and not ARMS[arm]["suppress_warning"]:
        k = sum(1 for r in s3 if r["verdict_raw"] == "undecidable")
        bars["C1"] = {
            "name": "C1_not_a_rubber_stamp",
            "hard": False,
            "scored_on": "verdict_raw, S3 (flagged-pack) fixtures",
            "k": k, "n": len(s3), "threshold": f">= {C1_MIN_UNDECIDABLE_S3}",
            "ci95": list(clopper_pearson(k, len(s3))) if s3 else None,
            "pass": bool(s3) and k >= C1_MIN_UNDECIDABLE_S3,
            "reference": {
                "recorded_raw_undecidable_on_all_flagged_rows":
                    list(REF_RAW_UNDECIDABLE_ON_FLAGGED),
                "false_void_at_reference_rate": 0.0246,
            },
            "note": (
                "DEGENERACY GUARD ONLY. It detects an instrument that never "
                "reaches for 'undecidable' even when the pack is flagged. It "
                "cannot detect partial under-obedience, and it cannot "
                "separate DETECTION from OBEDIENCE — every genuinely "
                "insufficient pack in the record carries the warning, which "
                "is what the warning-suppressed probe arm exists to address."
            ),
        }
        estimates["E3_raw_undecidable_on_flagged"] = {
            "k": k, "n": len(s3),
            "ci95": list(clopper_pearson(k, len(s3))) if s3 else None,
            "reference": list(REF_RAW_UNDECIDABLE_ON_FLAGGED),
            "reference_ci95": list(clopper_pearson(*REF_RAW_UNDECIDABLE_ON_FLAGGED)),
            "pass_fail": None,
        }

    if "S2" in ARMS[arm]["strata"]:
        k = sum(1 for r in s2 if r["verdict_raw"] == "undecidable")
        bars["C2"] = {
            "name": "C2_not_a_condemner",
            "hard": False,
            "scored_on": "verdict_raw, S2 (decisive-adequate) fixtures",
            "k": k, "n": len(s2), "threshold": f"<= {C2_MAX_UNDECIDABLE_S2}",
            "ci95": list(clopper_pearson(k, len(s2))) if s2 else None,
            "pass": bool(s2) and k <= C2_MAX_UNDECIDABLE_S2,
            "reference": {
                "native_undecidable_on_adequate_alltime":
                    list(REF_NATIVE_UNDECIDABLE_ADEQUATE_ALLTIME),
                "native_undecidable_on_adequate_august":
                    list(REF_NATIVE_UNDECIDABLE_ADEQUATE_AUGUST),
                "false_void_at_0.135": 0.0018,
            },
            "note": (
                "DEGENERACY GUARD ONLY. These 8 rows were DECIDED by this "
                "same instrument on this same pack, so the reference "
                "expectation is near zero; the threshold sits far above it "
                "deliberately, to catch a condemner rather than to certify "
                "calibration."
            ),
        }
        agree = sum(1 for r in s2 if r["verdict_raw"] == r["recorded_verdict_raw"])
        estimates["E2_self_consistency_on_decided_rows"] = {
            "k": agree, "n": len(s2),
            "ci95": list(clopper_pearson(agree, len(s2))) if s2 else None,
            "pass_fail": None,
            "note": (
                "Agreement with the SAME instrument's earlier verdict on the "
                "SAME pack. Self-consistency, NOT accuracy."
            ),
        }

    if "S1" in ARMS[arm]["strata"]:
        decisive = sum(1 for r in s1 if r["verdict_raw"] in DECISIVE_VERDICTS)
        estimates["E1_recorded_undecidable_replays_decisive"] = {
            "k": decisive, "n": len(s1),
            "ci95": list(clopper_pearson(decisive, len(s1))) if s1 else None,
            "pass_fail": None,
            "population": "CENSUS of all 10 native-undecidable-on-adequate rows",
            "pre_stated_reading": {
                ">=7 of 10": "the recorded undecidables are substantially NOT "
                             "STABLE; the remedy is a stability fix "
                             "(self-consistency / retry-on-undecidable), not a "
                             "prompt rewrite and not retrieval",
                "<=3 of 10": "the recorded undecidables are the instrument's "
                             "STABLE position; the remedy is prompt semantics "
                             "or retrieval, and a retry would only re-confirm",
                "4-6 of 10": "INDETERMINATE at n=10. Report the interval and "
                             "stop. No remedy is licensed.",
            },
            "note": (
                "S1 is a CENSUS, so the interval expresses the critic's "
                "CALL-LEVEL stochasticity, not sampling error over rows. The "
                "3-vs-7 intervals overlap on [0.347, 0.653]; these are "
                "directional readings, never significance claims."
            ),
        }

    all_bars_pass = all(b["pass"] for b in bars.values())
    return {
        "arm": arm,
        "n_rows": len(rows),
        "attribution": ATTRIBUTION_SENTENCE,
        "run_validity": {"V1": v1},
        "bars": bars,
        "estimates": estimates,
        "arm_void": not v1["pass"],
        "all_bars_pass": all_bars_pass,
        "void_semantics": VOID_SEMANTICS,
        "statistics_caveat": CAVEAT,
        "confusion_recorded_vs_replayed": _confusion(rows),
        "by_stratum": {
            s: _stratum_summary([r for r in rows if r["stratum"] == s])
            for s in sorted({r["stratum"] for r in rows})
        },
        "mid_flight_retrieval": {
            "n_inferred": sum(1 for r in rows if r["mid_flight_retrieval_inferred"]),
            "n_rows": len(rows),
            "ids": sorted(
                r["fixture_id"] for r in rows if r["mid_flight_retrieval_inferred"]
            ),
            "note": (
                "Inferred from subagent_turns_used >= 2 (the second turn is "
                "the tool-call turn). Replay is NOT hermetic: query_chroma "
                "hits TODAY's corpus, which the arxiv cron mutates. Rows are "
                "reported as a split and are NEVER excluded from a "
                "denominator — excluding them after seeing verdicts is the "
                "move the readjudication prereg forbids. If this fires on "
                "> 50% of calls the drift exposure is material and belongs in "
                "the headline, not a footnote."
            ),
            "material_drift_exposure": (
                sum(1 for r in rows if r["mid_flight_retrieval_inferred"]) * 2
                > len(rows)
            ),
        },
    }


def _stratum_summary(rows: list[dict]) -> dict:
    out: dict = {"n": len(rows), "verdict_raw": {}, "verdict_final": {}}
    for r in rows:
        out["verdict_raw"][str(r["verdict_raw"])] = (
            out["verdict_raw"].get(str(r["verdict_raw"]), 0) + 1
        )
        out["verdict_final"][str(r["verdict_final"])] = (
            out["verdict_final"].get(str(r["verdict_final"]), 0) + 1
        )
    out["verdict_raw"] = dict(sorted(out["verdict_raw"].items()))
    out["verdict_final"] = dict(sorted(out["verdict_final"].items()))
    return out


def _confusion(rows: list[dict]) -> list[dict]:
    cell: dict[tuple[str, str], int] = {}
    for r in rows:
        key = (str(r["recorded_verdict_raw"]), str(r["verdict_raw"]))
        cell[key] = cell.get(key, 0) + 1
    return [
        {"recorded_verdict_raw": k[0], "replayed_verdict_raw": k[1], "n": v}
        for k, v in sorted(cell.items())
    ]


# ---------------------------------------------------------------------------
# Provenance helpers
# ---------------------------------------------------------------------------

def _git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
    except Exception:
        return None


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except Exception:
        return None


def resolve_base_url(backend, wrapper_mod) -> str | None:
    """The vllm-gemma Backend object exposes no base_url of its own — it
    delegates to agent_wrapper.wrapper's module-level client, whose BASE_URL
    is the served endpoint. Resolve in that order and never guess."""
    for attr in ("base_url", "api_base", "_base_url"):
        val = getattr(backend, attr, None)
        if val:
            return str(val)
    return getattr(wrapper_mod, "BASE_URL", None)


def _probe_models(base: str | None) -> dict:
    """V2 serving identity — /v1/models before and after the arm. A silently
    re-seated backend is otherwise indistinguishable from a finding, and
    this repo has been bitten by exactly that."""
    import urllib.request
    if not base:
        return {"ok": False, "error": "could not resolve a base_url to probe"}
    url = base.rstrip("/") + "/models"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            payload = json.loads(resp.read().decode())
        return {"ok": True, "url": url,
                "served_models": sorted(
                    str(d.get("id")) for d in (payload.get("data") or [])
                )}
    except Exception as exc:
        return {"ok": False, "url": url, "error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Arm runner
# ---------------------------------------------------------------------------

def anchor_out(out_path: Path) -> Path:
    """--out is ANCHORED TO REPO_ROOT. A relative --out crashed a battery
    AFTER its calls were spent (R1a: relative_to(REPO_ROOT) raised at the
    artifact write). Anchoring is total and happens before anything else in
    the run can fail."""
    return out_path if out_path.is_absolute() else REPO_ROOT / out_path


def run_arm(arm: str, out_path: Path, limit: int | None) -> int:
    out_path = anchor_out(out_path)

    fixtures = load_manifest()
    ok, why = manifest_shape_ok(fixtures)
    if not ok:
        print(f"REFUSING (exit 4): manifest shape check failed — {why}",
              file=sys.stderr)
        return 4

    # Backend contention guard. There is no repo-wide lock covering
    # vllm-gemma (cron/run-coordinator.sh flocks the coordinator only, and
    # bench drivers take none), so this driver CREATES one. Stated as new
    # work, not as an existing mechanism: until the other bench drivers
    # adopt it, it protects against a second CRITIC battery only.
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_fh = LOCK_PATH.open("w")
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print(f"REFUSING (exit 3): {LOCK_PATH} is held by another bench run.",
              file=sys.stderr)
        return 3

    cfg = ARMS[arm]
    os.environ["CRITIC_BACKEND"] = BACKEND
    for k, v in ENV_PINS.items():
        os.environ[k] = v

    sys.path.insert(0, str(REPO_ROOT))
    from agent_wrapper import wrapper as wrapper_mod
    from agent_wrapper.backends import get_backend
    from orchestrator import iteration_cache
    from orchestrator.subagent import SubAgentBudget
    from workers import critic_loop_v0 as critic_mod

    backend = get_backend(BACKEND)
    base_url = resolve_base_url(backend, wrapper_mod)
    probe_before = _probe_models(base_url)

    todo = [f for f in fixtures if f["stratum"] in cfg["strata"]]
    todo.sort(key=lambda f: (f["order_key"], f["fixture_id"]))
    if limit:
        todo = todo[:limit]

    budget = SubAgentBudget(
        max_turns=BUDGET_MAX_TURNS, max_wall_seconds=BUDGET_MAX_WALL_SECONDS
    )
    prompt_in_effect = critic_mod.CRITIC_AGENT_SYSTEM_PROMPT
    started_at = _utcnow()
    rows = []

    for fx in todo:
        cache_id = fx["cache_iteration_id"]
        env = fx["retrieval_envelope"]
        if cfg["suppress_warning"]:
            env = suppress_warning(env)
        iteration_cache.write_entry(cache_id, "retrieval", env)
        if fx.get("novelty_envelope"):
            iteration_cache.write_entry(cache_id, "novelty", fx["novelty_envelope"])

        t0 = time.perf_counter()
        out = critic_mod.critic_loop_v0(
            fx["hypothesis_text"], cache_id,
            parent_request_id=f"critic-cal-{arm}", budget=budget,
        )
        wall_s = round(time.perf_counter() - t0, 3)
        status = out.get("status")
        res = out.get("result") or {}
        verdict_final = res.get("verdict")
        verdict_raw = res.get("verdict_overridden_from") or verdict_final
        turns = res.get("subagent_turns_used")
        row = {
            "fixture_id": fx["fixture_id"],
            "iteration_id": fx["iteration_id"],
            "stratum": fx["stratum"],
            "order_key": fx["order_key"],
            "era": fx["era"],
            "cache_iteration_id": cache_id,
            "pack_sha256": fx["pack"]["pack_sha256"],
            "envelope_sha256_replayed": hashlib.sha256(
                json.dumps(env, sort_keys=True, ensure_ascii=True).encode()
            ).hexdigest(),
            "neighbor_doc_ids": fx["pack"]["neighbor_doc_ids"],
            "relevance_warning_fired": bool(
                ((env.get("result") or {}).get("relevance") or {}).get("low_confidence")
            ),
            "novelty_context_fired": fx["prompt_shape"]["novelty_context_fires"],
            "recorded_verdict_raw": fx["recorded"]["verdict_raw"],
            "recorded_verdict_final": fx["recorded"]["verdict_final"],
            "worker_status": status,
            "verdict_raw": verdict_raw,
            "verdict_final": verdict_final,
            "verdict_overridden_from": res.get("verdict_overridden_from"),
            "override_reason": res.get("override_reason"),
            "undecidable_kind": undecidable_kind(res, status),
            "contradicting_paper_id": res.get("contradicting_paper_id"),
            "rationale_digest": (res.get("rationale") or "")[:240],
            "subagent_status": res.get("subagent_status"),
            "subagent_turns_used": turns,
            "subagent_wall_seconds": res.get("subagent_wall_seconds"),
            "subagent_backend": res.get("subagent_backend"),
            "subagent_model_DECLARED": res.get("subagent_model"),
            "mid_flight_retrieval_inferred": bool(turns and turns >= 2),
            "wall_s": wall_s,
            "wrapper_request_id": out.get("wrapper_request_id"),
            "errors": out.get("errors") or [],
        }
        rows.append(row)
        print(f"  {fx['fixture_id']:34s} {fx['stratum']} "
              f"rec={str(fx['recorded']['verdict_raw']):12s} -> "
              f"{str(verdict_raw):12s} ({wall_s:.1f}s)")

    ended_at = _utcnow()
    probe_after = _probe_models(base_url)
    v2_pass = (
        probe_before.get("ok") and probe_after.get("ok")
        and probe_before.get("served_models") == probe_after.get("served_models")
    )

    evaluation = evaluate(rows, arm)
    evaluation["run_validity"]["V2"] = {
        "name": "V2_serving_identity",
        "hard": True,
        "voids_arm_on_fail": True,
        "probe_before": probe_before,
        "probe_after": probe_after,
        "pass": bool(v2_pass),
    }
    if not v2_pass:
        evaluation["arm_void"] = True

    out_path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    calls_dump_path = out_path.parent / f"calls_{arm}_{stamp}.jsonl"
    try:
        with calls_dump_path.open("w") as fh:
            for rec in wrapper_mod.MEMORY_LOG:
                fh.write(json.dumps(rec) + "\n")
    except Exception as exc:
        print(f"warning: calls-log dump failed: {exc}", file=sys.stderr)
        calls_dump_path = None

    artifact = {
        "prereg": PREREG,
        "deliverable": "D1 — critic calibration battery",
        "arm": arm,
        "arm_is_probe": cfg["suppress_warning"],
        "provenance": {
            "git_commit": _git_commit(),
            "manifest_path": str(MANIFEST_PATH.relative_to(REPO_ROOT)),
            "manifest_sha256": hashlib.sha256(
                MANIFEST_PATH.read_bytes()).hexdigest(),
            "prompt_source": "workers.critic_loop_v0.CRITIC_AGENT_SYSTEM_PROMPT",
            "prompt_sha256": hashlib.sha256(prompt_in_effect.encode()).hexdigest(),
            "backend": BACKEND,
            "backend_default_model": getattr(backend, "default_model", None),
            "backend_base_url": base_url,
            "budget": {
                "max_turns": BUDGET_MAX_TURNS,
                "max_wall_seconds": BUDGET_MAX_WALL_SECONDS,
            },
            "env_pins_asserted": {k: os.environ.get(k) for k in ENV_PINS},
            "env_pins_expected": dict(ENV_PINS),
            "critic_backend_env": os.environ.get("CRITIC_BACKEND"),
            "mock_llm_present": "MOCK_LLM" in os.environ,
            "vllm_image_digest": _read_text(REPO_ROOT / "run_state" / "vllm_image.digest"),
            "wrapper_model_version": getattr(wrapper_mod, "MODEL_VERSION", None),
            "invocation_seam": (
                "workers.critic_loop_v0.critic_loop_v0(hypothesis_text, "
                "iteration_id, parent_request_id=..., budget=SubAgentBudget("
                f"max_turns={BUDGET_MAX_TURNS}, "
                f"max_wall_seconds={BUDGET_MAX_WALL_SECONDS})) — the critic "
                "reads its pack from run_state/iteration_cache/<iteration_id>/"
                "retrieval.json (critic_loop_v0.py:610,619), so replay = seed "
                "the cache then call by id"
            ),
            "cache_write_exception": (
                "This driver WRITES run_state/iteration_cache/critcal-<fixture_id>/"
                " — a named exception to 'the battery writes nothing to "
                "run_state/'. The namespace cannot collide: the only cache-root "
                "enumerator globs 'iter-*'. Directories are RETAINED as "
                "reproducibility artifacts."
            ),
            "seam_divergence_from_production": (
                "NARA_SKEPTIC / NARA_DEBATE / NARA_RESTATE_SKEPTIC are pinned "
                "to 0. Production cron runs NARA_SKEPTIC=1 NARA_DEBATE=1 "
                "(NARA_RESTATE_SKEPTIC is dark in production too). This is a "
                "named, logged departure (inviolate rule 7): the override "
                "chain is D2's subject and is measured there over 59 real rows "
                "at zero call cost. The coverage override INSIDE critic_loop_v0 "
                "still fires unconditionally — that is production behavior and "
                "stays on, which is why every row records raw AND final."
            ),
        },
        "started_at": started_at,
        "ended_at": ended_at,
        "limit": limit,
        "n_calls": len(rows),
        "calls_log_dump": (
            str(calls_dump_path.relative_to(REPO_ROOT))
            if calls_dump_path and calls_dump_path.is_relative_to(REPO_ROOT)
            else (str(calls_dump_path) if calls_dump_path else None)
        ),
        "evaluation": evaluation,
        "rows": rows,
    }
    if limit:
        artifact["note"] = (
            f"PARTIAL RUN (--limit {limit}): bars are only meaningful on the "
            "full stratum denominators frozen in the manifest."
        )
    out_path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")

    _print_bars(evaluation)
    print(f"\nartifact -> {out_path}")
    return 0


def _print_bars(ev: dict) -> None:
    print("\n" + "=" * 74)
    print(ev["attribution"])
    print("=" * 74)
    print("\nRUN-VALIDITY BARS (evaluated FIRST; failing either VOIDS the arm)")
    for name in ("V1", "V2"):
        b = ev["run_validity"].get(name)
        if b:
            print(f"  {name} {b['name']:24s} pass={b['pass']}")
    if ev["arm_void"]:
        print("\n  *** ARM VOID *** " + ev["void_semantics"])
        return
    print("\nDISCRIMINATION BARS (degeneracy guards)")
    for name in sorted(k for k in ev["bars"] if k != "V1"):
        b = ev["bars"][name]
        print(f"  {name} {b['name']:24s} {b['k']}/{b['n']} "
              f"{b['threshold']:>6s}  pass={b['pass']}  ci95={b['ci95']}")
    print("\nESTIMATES (no pass/fail)")
    for name in sorted(ev["estimates"]):
        e = ev["estimates"][name]
        print(f"  {name}: {e['k']}/{e['n']}  ci95={e['ci95']}")
    print("\n" + ev["statistics_caveat"])


def main(argv: list[str] | None = None) -> int:
    # Refusal FIRST, before any repo import: MOCK_LLM stubs the embedders
    # and a stubbed run is silently meaningless (inviolate rule 10).
    if "MOCK_LLM" in os.environ:
        print(
            "REFUSING (exit 2): MOCK_LLM is set — this driver makes real "
            "critic calls only. Re-run with `env -u MOCK_LLM`.",
            file=sys.stderr,
        )
        return 2

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--arm", required=True, choices=sorted(ARMS))
    ap.add_argument("--out", required=True,
                    help="artifact path; relative paths anchor to REPO_ROOT")
    ap.add_argument("--limit", type=int, default=None,
                    help="run only the first N fixtures (smoke)")
    ap.add_argument("--probe-ratified", action="store_true",
                    help="required for --arm warning-suppressed-probe: the "
                         "probe is owner-elected at lock and is NOT "
                         "production-faithful")
    args = ap.parse_args(argv)

    if args.arm == "warning-suppressed-probe" and not args.probe_ratified:
        print(
            "REFUSING (exit 5): the warning-suppressed probe is an "
            "owner-elected, NOT-production-faithful arm. Re-run with "
            "--probe-ratified once the owner has elected it at lock.",
            file=sys.stderr,
        )
        return 5

    return run_arm(args.arm, Path(args.out), args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
