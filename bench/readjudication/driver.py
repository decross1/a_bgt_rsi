"""Run driver — graveyard re-adjudication battery (D-076 follow-on).

Prereg: experiments/PREREG_readjudication_2026-08-19.md (v2, LOCKED).

ONE ARM PER PROCESS (`--arm old|new`), R1a precedent. The arms are BLOCKED,
not interleaved: `agent_wrapper.wrapper.MEMORY_LOG` is process-global, so a
one-process design cannot give per-arm calls-log isolation, and a fresh
interpreter per arm is what makes the prompt injection unambiguous. What
blocking costs — row-level temporal pairing — is bought back by the serving
guarantees below, which are observations rather than beliefs (prereg §4.2).

Serving is CHECKED, never assumed (prereg §2, F2 fix). The worker's returned
`subagent_model` is `resolved_be.default_model`, i.e. `wrapper.MODEL`, i.e.
`os.environ.get("VLLM_MODEL", "gemma-4-26b-a4b")` — a PROCESS CONSTANT that is
byte-identical on every row by construction and therefore cannot detect a
serving change. This driver instead:
  1. probes the endpoint's own ``/v1/models`` before the first call and after
     the last (the pattern ui/backend/served_models.py exists for — that
     module was written because "the card title was a hardcoded string ...
     printing a belief, not an observation");
  2. asserts, PER ROW, the served name the SERVER reported — the wrapper
     record's ``model`` field is ``resp.model`` (agent_wrapper/wrapper.py:125,
     orchestrator/subagent.py:175), joined to the row by the worker's
     ``wrapper_request_id``;
  3. pins the vLLM image digest (run_state/vllm_image.digest) in provenance.

Both prompt shas are asserted BEFORE the first call AND again before EVERY
row (F1 fix): a silently reverted injection seam — module re-imported, stale
module reference — is otherwise invisible to bars that only bind in the
too-permissive direction.

Refusals (never coerced; each is a hard exit, no degraded continuation):
  exit  2  MOCK_LLM set in run mode (a stubbed run is silently meaningless)
  exit  3  resolved vllm-gemma default_model != the pinned model
  exit  4  manifest sha / row-count / kind-count mismatch vs the lock
  exit  5  fixtures.jsonl sha mismatch vs the lock
  exit  6  OLD prompt sha mismatch (frozen file, or the module global at a row)
  exit  7  NEW prompt sha mismatch (live module, or the module global at a row)
  exit  8  a row's SERVER-REPORTED model != the pinned model (serving change)
  exit  9  a /v1/models probe failed or reported a different served id
  exit 10  mode misuse (exactly one of --arm / --evaluate-pair is required)
  exit 11  the 75-minute wall cap fired (PARTIAL artifact, uninterpretable)

Usage:
  env -u MOCK_LLM .venv-chroma/bin/python -m bench.readjudication.driver \
      --arm old --out bench/readjudication/runs/old.json
  env -u MOCK_LLM .venv-chroma/bin/python -m bench.readjudication.driver \
      --arm new --out bench/readjudication/runs/new.json
  .venv-chroma/bin/python -m bench.readjudication.driver \
      --evaluate-pair <old.json> <new.json> --out bench/readjudication/runs/eval.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Reuse, don't reimplement: the exact Clopper-Pearson used by R1a and already
# unit-tested there (prereg §7). Import is stdlib-only and side-effect free.
from bench.redteam_cal.driver import (  # noqa: E402
    _binom_cdf_leq,
    clopper_pearson,
)

PREREG = "experiments/PREREG_readjudication_2026-08-19.md"

MANIFEST_PATH = HERE / "manifest.jsonl"
OLD_PROMPT_PATH = HERE / "old_prompt.txt"
FIXTURES_PATH = REPO_ROOT / "bench" / "redteam_cal" / "fixtures.jsonl"
IMAGE_DIGEST_PATH = REPO_ROOT / "run_state" / "vllm_image.digest"

# ── LOCKED constants. Nothing below resolves at run time (prereg §2). ──
LOCKED_MANIFEST_SHA256 = (
    "7ec63389ca9a0a9f789f28631e9adb8b5360aaa0842590f84843d3a9664b64f0"
)
LOCKED_MANIFEST_COUNTS = {"target": 88, "control": 24, "sidecar": 2}
LOCKED_FIXTURES_SHA256 = (
    "1f8b738c509528a3e56549c851b482bcc1d36ee8aea3f97961f628b14e31cce4"
)
OLD_PROMPT_SHA256 = (
    "3433ac5d862d9e749f00455b0ed1d0b422b743c50202cb6fe45774c1445ae0bc"
)
NEW_PROMPT_SHA256 = (
    "7d44820d99f71485b0734ad4362cb95212c0f327481c7de043d8079cc3f52dba"
)
ARM_PROMPT_SHA = {"old": OLD_PROMPT_SHA256, "new": NEW_PROMPT_SHA256}
ARM_EXIT = {"old": 6, "new": 7}

CRITIC_BACKEND = "vllm-gemma"
PINNED_MODEL = "gemma-4-26b-a4b"
GEMMA_URL = os.environ.get("VLLM_GEMMA_URL", "http://localhost:8000")
PROBE_TIMEOUT_S = 5.0

BUDGET_MAX_TURNS = 3
BUDGET_MAX_WALL_SECONDS = 45.0
WALL_CAP_SECONDS = 75 * 60  # prereg §6 slip rule; abort, never extend

# Q3 replicate (prereg §7.3): a SECOND new-arm draw on the first 20 targets
# by ascending order_key, run as a separate final pass. Descriptive only.
REPLICATE_N = 20

# ── Bars (prereg §4.3). Integer arithmetic at every threshold. ──
C1_MIN_FATAL_KNOWN_BAD = 6          # of 12, unscored counts against
C4_MAX_FATAL_PCT_KNOWN_GOOD = 35    # of PARSED, R1a adoption bar 3 verbatim
C2_MIN_FATAL_PCT_KNOWN_GOOD = 50    # of PARSED, old arm
C2_MIN_PARSED = 5                   # below this C2 is NOT EVALUABLE
C3A_MAX_UNSCORED_TARGETS = 13       # of 88 (15%)
C3B_MAX_UNSCORED_CONTROLS = 4       # of 24
PHI_INTERVAL_TRIGGER = 4            # target unscored above this -> interval only

# L4: row-level replication against the R1a run one day earlier — identical
# 24 fixtures, identical prompt shas, identical backend.
R1A_REFERENCE = {
    "old": {
        "path": "bench/redteam_cal/runs/gemma-current_20260818T060805Z.json",
        "sha256":
            "d1cf0e3c4135e8ae9a4a498a32cc1d760108db661a88517e172145ac734fc6d2",
        "prompt_sha256": OLD_PROMPT_SHA256,
    },
    "new": {
        "path": "bench/redteam_cal/runs/gemma-revised_20260818T061029Z.json",
        "sha256":
            "92e628224e33803061df8ef7f75dbad25ff0d7e26c608753cbab266ae79a11ae",
        "prompt_sha256": NEW_PROMPT_SHA256,
    },
}

SEAM_NOTE = (
    "workers.redteam_critic.redteam_critic(hypothesis_text, iteration_id, "
    "parent_request_id=..., budget=...) — hypothesis text alone, exactly as "
    "orchestrator/nara.py invokes it; prompt injected by module-global "
    "override (rt_mod.REDTEAM_AGENT_SYSTEM_PROMPT), the same seam "
    "bench/redteam_cal/driver.py::apply_prompt_variant documents."
)
CAVEAT = (
    "At n=12/class a zero-discrimination coin passes R1a's bars 2 AND 3 with "
    "~1.4% probability and a weak 60/40 instrument with ~10%. This battery "
    "inherits that bound in full and CANNOT reduce it: every claim it makes "
    "is relative to an instrument whose quality is bounded at n=12/class. "
    "Nothing here is evidence about the NEW instrument's accuracy."
)


# ---------------------------------------------------------------------------
# provenance helpers
# ---------------------------------------------------------------------------

def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _git_commit():
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
    except Exception:
        return None


def probe_served_model(url: str = GEMMA_URL, *, timeout: float = PROBE_TIMEOUT_S,
                       opener=urllib.request.urlopen) -> dict:
    """Ask the endpoint's own /v1/models what it is serving. Never raises.

    Pattern (not code) from ui/backend/served_models.py::probe — importing
    that module would drag FastAPI into a bench driver."""
    target = f"{url.rstrip('/')}/v1/models"
    try:
        with opener(target, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TypeError) as exc:
        return {"url": url, "model": None, "probed_at": _utcnow(),
                "error": f"{type(exc).__name__}: {exc}"}
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        return {"url": url, "model": None, "probed_at": _utcnow(),
                "error": "unexpected /v1/models payload shape"}
    model = data[0].get("id")
    if not isinstance(model, str) or not model.strip():
        return {"url": url, "model": None, "probed_at": _utcnow(),
                "error": "no model id in payload"}
    return {"url": url, "model": model.strip(), "probed_at": _utcnow(),
            "error": None}


def load_old_prompt(path: Path = OLD_PROMPT_PATH) -> str:
    """The frozen pre-swap constant, minus the file's single trailing newline
    (the production constant carries none) — the same convention
    bench/redteam_cal/driver.py::load_revised_prompt uses."""
    text = path.read_text()
    return text[:-1] if text.endswith("\n") else text


def load_manifest(path: Path = MANIFEST_PATH):
    from bench.readjudication.build_manifest import load_manifest as _load
    return _load(path)


# ---------------------------------------------------------------------------
# Per-arm evaluation — run-validity bars FIRST (prereg §4.3)
# ---------------------------------------------------------------------------

def _counts(rows: list) -> dict:
    return {
        "n": len(rows),
        "fatal_flaw": sum(1 for r in rows if r["verdict"] == "fatal_flaw"),
        "proceed": sum(1 for r in rows if r["verdict"] == "proceed"),
        "unscored": sum(1 for r in rows if r["verdict"] == "unscored"),
    }


def _rate_block(x: int, n: int) -> dict:
    return {
        "x": x, "n": n,
        "rate": (x / n) if n else None,
        "ci95": list(clopper_pearson(x, n)) if n else None,
    }


def r1a_replication(rows: list, arm: str) -> dict:
    """L4: row-level verdict replication against the R1a run (n=24, CP95).

    Same 24 fixtures, same prompt sha, same backend, one day apart — a far
    sharper fidelity check than the aggregate bars, and an independent second
    detector for a silently reverted arm. REQUIRED reported statistic;
    descriptive (it gates nothing)."""
    ref = R1A_REFERENCE[arm]
    ref_path = REPO_ROOT / ref["path"]
    out = {"reference": ref["path"], "reference_sha256_expected": ref["sha256"]}
    try:
        ref_sha = _sha256_file(ref_path)
        artifact = json.loads(ref_path.read_text())
    except OSError as exc:
        out["error"] = f"reference unreadable: {exc}"
        return out
    out["reference_sha256_observed"] = ref_sha
    out["reference_sha256_match"] = (ref_sha == ref["sha256"])
    out["reference_prompt_sha256"] = artifact.get("prompt_sha256")
    out["prompt_sha256_match"] = (
        artifact.get("prompt_sha256") == ref["prompt_sha256"]
    )
    prior = {r["id"]: r["verdict"] for r in artifact.get("rows") or []}
    controls = [r for r in rows if r["kind"] == "control" and r["row_id"] in prior]
    agree = sum(1 for r in controls if r["verdict"] == prior[r["row_id"]])
    out["agreement"] = _rate_block(agree, len(controls))
    out["disagreements"] = sorted(
        ({"row_id": r["row_id"], "r1a": prior[r["row_id"]],
          "now": r["verdict"]}
         for r in controls if r["verdict"] != prior[r["row_id"]]),
        key=lambda d: d["row_id"],
    )
    return out


def _replicate_agreement(rows: list) -> dict:
    """Q3 (prereg §7.3): verdict agreement between the FIRST new-arm draw and
    the separate final replicate pass, on the locked 20-row subsample.
    DESCRIPTIVE — it never enters phi, which uses the first draw only."""
    first = {r["row_id"]: r["verdict"] for r in rows if r["kind"] == "target"}
    reps = [r for r in rows if r["kind"] == "replicate"]
    if not reps:
        return {"n": 0, "note": "no replicate pass in this artifact"}
    agree = sum(1 for r in reps if first.get(r["row_id"]) == r["verdict"])
    out = _rate_block(agree, len(reps))
    out["disagreements"] = sorted(
        ({"row_id": r["row_id"], "draw1": first.get(r["row_id"]),
          "draw2": r["verdict"]}
         for r in reps if first.get(r["row_id"]) != r["verdict"]),
        key=lambda d: d["row_id"],
    )
    out["note"] = "descriptive; the primary statistic uses draw 1 only"
    return out


def evaluate_arm(rows: list, arm: str) -> dict:
    """Bars first, then rates. Every bar stands on its own (inviolate rule 4);
    a near miss is a failure, never a rounded pass."""
    main = [r for r in rows if r["kind"] in ("target", "control")]
    targets = [r for r in main if r["kind"] == "target"]
    controls = [r for r in main if r["kind"] == "control"]
    good = [r for r in controls if r["label"] == "known_good"]
    bad = [r for r in controls if r["label"] == "known_bad"]
    parsed_good = [r for r in good if r["verdict"] != "unscored"]
    parsed_bad = [r for r in bad if r["verdict"] != "unscored"]
    fatal_good = sum(1 for r in parsed_good if r["verdict"] == "fatal_flaw")
    fatal_bad_all = sum(1 for r in bad if r["verdict"] == "fatal_flaw")
    fatal_bad_parsed = sum(1 for r in parsed_bad if r["verdict"] == "fatal_flaw")

    bars: dict = {}
    if arm == "new":
        # C1 — NEW catches the bad. Denominator is ALL 12 known-bad rows:
        # unscored counts AGAINST (prereg §5), the harsher polarity.
        bars["C1_new_catches_bad"] = {
            "hard": True, "scope": "run validity",
            "fatal": fatal_bad_all, "n": len(bad),
            "threshold": f"fatal_flaw on >= {C1_MIN_FATAL_KNOWN_BAD} of "
                         f"{len(bad)} known-bad (unscored counts against)",
            "pass": fatal_bad_all >= C1_MIN_FATAL_KNOWN_BAD,
            "ci95": list(clopper_pearson(fatal_bad_all, len(bad)))
            if bad else None,
        }
        # C4 — NEW does not condemn the good. R1a adoption bar 3 verbatim
        # (<=35% of PARSED known-good), the bar this prompt was adopted on.
        # This is the ONLY bar with power against a silently reverted NEW arm.
        bars["C4_new_passes_good"] = {
            "hard": True, "scope": "run validity",
            "fatal": fatal_good, "parsed": len(parsed_good),
            "threshold": f"fatal_flaw on <= {C4_MAX_FATAL_PCT_KNOWN_GOOD}% of "
                         "parsed known-good (R1a adoption bar 3)",
            "pass": bool(len(parsed_good)
                         and fatal_good * 100
                         <= C4_MAX_FATAL_PCT_KNOWN_GOOD * len(parsed_good)),
            "evaluable": bool(parsed_good),
            "ci95": list(clopper_pearson(fatal_good, len(parsed_good)))
            if parsed_good else None,
            "secondary_all_rows": _rate_block(
                sum(1 for r in good if r["verdict"] == "fatal_flaw"), len(good)
            ),
        }
        n_uns_t = sum(1 for r in targets if r["verdict"] == "unscored")
        n_uns_c = sum(1 for r in controls if r["verdict"] == "unscored")
        # C3 is SPLIT (F5 fix): pooling 113 rows let a target-concentrated
        # parse regression consume up to 17 target verdicts and still pass.
        bars["C3a_parse_health_targets"] = {
            "hard": True, "scope": "run validity",
            "unscored": n_uns_t, "n": len(targets),
            "cap": C3A_MAX_UNSCORED_TARGETS,
            "pass": n_uns_t <= C3A_MAX_UNSCORED_TARGETS,
        }
        bars["C3b_parse_health_controls"] = {
            "hard": True, "scope": "run validity",
            "unscored": n_uns_c, "n": len(controls),
            "cap": C3B_MAX_UNSCORED_CONTROLS,
            "pass": n_uns_c <= C3B_MAX_UNSCORED_CONTROLS,
        }
    else:
        # C2 — OLD still condemns the good. Gates the ATTRIBUTION claim only
        # (prereg §4.3): the NEW arm's verdicts survive its failure as a fresh
        # adjudication. NOT evaluable below 5 parsed rows.
        evaluable = len(parsed_good) >= C2_MIN_PARSED
        bars["C2_old_condemns_good"] = {
            "hard": True, "scope": "attribution claim only",
            "fatal": fatal_good, "parsed": len(parsed_good),
            "threshold": f"fatal_flaw on >= {C2_MIN_FATAL_PCT_KNOWN_GOOD}% of "
                         f"parsed known-good (>= {C2_MIN_PARSED} parsed to be "
                         "evaluable)",
            "evaluable": evaluable,
            "pass": bool(evaluable and fatal_good * 100
                         >= C2_MIN_FATAL_PCT_KNOWN_GOOD * len(parsed_good)),
            "ci95": list(clopper_pearson(fatal_good, len(parsed_good)))
            if parsed_good else None,
        }
        # NO bar on the OLD arm's parse health: the old prompt demonstrably
        # fails parse on sound claims (5/12 known-good unscored in R1a, 23/122
        # in production). That is a property of the instrument under study.
        bars["old_parse_health_REPORTED_ONLY"] = {
            "hard": False,
            "unscored_targets": sum(1 for r in targets
                                    if r["verdict"] == "unscored"),
            "unscored_controls": sum(1 for r in controls
                                     if r["verdict"] == "unscored"),
            "note": "reported, never a bar — see prereg §4.3",
        }

    hard = [b for b in bars.values() if b.get("hard")]
    run_valid = all(b["pass"] for b in hard if b["scope"] == "run validity")

    return {
        "arm": arm,
        "run_validity": {
            "all_hard_run_validity_bars_pass": run_valid,
            "void": (arm == "new" and not run_valid),
            "note": "A VOID run reports the control table, the bars and the "
                    "serving provenance, and NO flip rate at all (prereg "
                    "§4.3). Re-thresholding is not available.",
        },
        "bars": bars,
        "counts": {
            "targets": _counts(targets),
            "controls_known_good": _counts(good),
            "controls_known_bad": _counts(bad),
            "sidecars_EXPLORATORY": _counts(
                [r for r in rows if r["kind"] == "sidecar"]
            ),
        },
        # F4 anchors, same-run: the comparators phi must be read against.
        "same_run_proceed_rates": {
            "known_bad_controls": _rate_block(
                sum(1 for r in bad if r["verdict"] == "proceed"), len(bad)),
            "known_good_controls": _rate_block(
                sum(1 for r in good if r["verdict"] == "proceed"), len(good)),
            "known_bad_controls_parsed": _rate_block(
                sum(1 for r in parsed_bad if r["verdict"] == "proceed"),
                len(parsed_bad)),
        },
        "confusion_by_provenance_class": {
            cls: _counts([r for r in controls
                          if r.get("provenance_class") == cls])
            for cls in sorted({r.get("provenance_class") for r in controls}
                              - {None})
        },
        "q3_replicate_agreement": _replicate_agreement(rows),
        "r1a_replication": r1a_replication(rows, arm),
        "fatal_bad_parsed_REPORTED": _rate_block(fatal_bad_parsed,
                                                 len(parsed_bad)),
        "statistics_caveat": CAVEAT,
    }


# ---------------------------------------------------------------------------
# Cross-arm evaluation (prereg §7)
# ---------------------------------------------------------------------------

def _mcnemar_exact(a: int, d: int) -> float:
    """Two-sided exact binomial (sign) test on the discordant pairs."""
    n = a + d
    if n == 0:
        return 1.0
    tail = 1.0 - _binom_cdf_leq(max(a, d) - 1, n, 0.5)
    return min(1.0, 2.0 * tail)


def _overlap(ci_a, ci_b) -> bool:
    if not ci_a or not ci_b:
        return True
    return not (ci_a[1] < ci_b[0] or ci_b[1] < ci_a[0])


def evaluate_pair(old_artifact: dict, new_artifact: dict) -> dict:
    """phi, the 2x2, kappa_old, McNemar, the R partition and the pre-stated
    reading gates. Pure — takes two run artifacts, makes no calls."""
    old_rows = {r["row_id"]: r for r in old_artifact["rows"]}
    new_rows = {r["row_id"]: r for r in new_artifact["rows"]}
    ids = sorted(rid for rid, r in new_rows.items() if r["kind"] == "target")
    N = len(ids)

    v_new = {rid: new_rows[rid]["verdict"] for rid in ids}
    v_old = {rid: old_rows[rid]["verdict"] for rid in ids if rid in old_rows}

    proceeds = [rid for rid in ids if v_new[rid] == "proceed"]
    unscored_new = [rid for rid in ids if v_new[rid] == "unscored"]
    # phi — the flip rate. Denominator is the FULL locked target set; an
    # unscored row is a NON-proceed (prereg §5): the battery fails toward
    # keeping the kill. Always reported as the honest bound pair (F5 fix).
    phi_low = len(proceeds) / N if N else None
    phi_high = (len(proceeds) + len(unscored_new)) / N if N else None
    parsed_new = [rid for rid in ids if v_new[rid] != "unscored"]
    phi = {
        "numerator": len(proceeds), "denominator": N,
        "point": phi_low,
        "interval_bound": [phi_low, phi_high],
        "ci95": list(clopper_pearson(len(proceeds), N)) if N else None,
        "unscored_on_targets": len(unscored_new),
        "point_estimate_quotable_alone": len(unscored_new) <= PHI_INTERVAL_TRIGGER,
        "reporting_rule": (
            f"With more than {PHI_INTERVAL_TRIGGER} unscored target rows the "
            "point estimate MAY NOT be quoted alone — report "
            "[proceeds/N, (proceeds+unscored)/N]. Pre-committed."
        ),
        "denominator_note": (
            f"phi is over the {N} TARGET rows = the re-adjudicable "
            "redteam-code kills. The report prints all three denominators "
            "once (prereg §7.1) so the number cannot travel with the largest."
        ),
        "phi_parsed_SECONDARY_upper_bound": _rate_block(
            len(proceeds), len(parsed_new)),
    }

    # 2x2 over rows where BOTH arms scored.
    A = [rid for rid in ids if v_old.get(rid) == "fatal_flaw"
         and v_new[rid] == "proceed"]
    B = [rid for rid in ids if v_old.get(rid) == "proceed"
         and v_new[rid] == "proceed"]
    C = [rid for rid in ids if v_old.get(rid) == "fatal_flaw"
         and v_new[rid] == "fatal_flaw"]
    D = [rid for rid in ids if v_old.get(rid) == "proceed"
         and v_new[rid] == "fatal_flaw"]
    U = [rid for rid in ids
         if rid not in set(A) | set(B) | set(C) | set(D)]
    # F3(iii): U is unprintable in the draft even though it drives the
    # disposition. Decompose it by NEW verdict.
    u_by_new = {
        verdict: sorted(rid for rid in U if v_new[rid] == verdict)
        for verdict in ("proceed", "fatal_flaw", "unscored")
    }
    u_old_unscored_new_proceed = sorted(
        rid for rid in U
        if v_old.get(rid) == "unscored" and v_new[rid] == "proceed"
    )

    # kappa_old — PRIMARY polarity is all-N with unscored as NON-reproduction,
    # mirroring the historical fail-open (F3(ii)): an OLD-arm unscored TODAY
    # is the same event that historically meant "proceed, no kill". This is
    # the same polarity phi already uses; the parsed-only figure is the
    # secondary upper bound, never the headline.
    old_fatal = sum(1 for rid in ids if v_old.get(rid) == "fatal_flaw")
    old_scored = sum(1 for rid in ids
                     if v_old.get(rid) in ("fatal_flaw", "proceed"))
    kappa_old = {
        "primary_all_rows": _rate_block(old_fatal, N),
        "secondary_parsed_only_UPPER_BOUND": _rate_block(old_fatal, old_scored),
        "unscored_on_targets": sum(1 for rid in ids
                                   if v_old.get(rid) == "unscored"),
        "polarity_note": (
            "Primary counts OLD-unscored as NON-reproduction. Historically a "
            "sub-agent schema_mismatch FAIL-OPENED to 'proceed' (the pre-R1b "
            "worker; 6ddcce5 remapped it to 'unscored' on 2026-08-18T05:28Z, "
            "AFTER the last target), so an OLD-arm unscored today IS the "
            "event that then meant 'no kill'."
        ),
        "selection_note": (
            "kappa_old is a retest CONDITIONED ON THE SELECTING DRAW: every "
            "target carries retries_used=2, i.e. the old instrument parsed "
            "AND condemned three times running (a parse failure at T0/T1 "
            "would have fail-opened to proceed and SPARED the cluster). It is "
            "therefore biased UPWARD, toward the prompt-attribution reading."
        ),
    }

    mcnemar_p = _mcnemar_exact(len(A), len(D))

    # F4: phi has to be read against the SAME-RUN comparators. A PARTIAL /
    # uninterpretable NEW artifact has none — refuse rather than invent them.
    new_eval = (new_artifact.get("evaluation") or {}).get(
        "same_run_proceed_rates")
    if new_eval is None:
        raise ValueError(
            "the NEW artifact carries no same-run control rates (PARTIAL or "
            "uninterpretable run) — phi has no pre-stated comparator, so no "
            "cross-arm evaluation is produced (prereg §7.1)"
        )
    bad_rate = new_eval["known_bad_controls"]
    good_rate = new_eval["known_good_controls"]
    phi_ci = phi["ci95"]
    attribution_available = not _overlap(phi_ci, bad_rate["ci95"])
    comparators = {
        "new_proceed_known_bad_controls": bad_rate,
        "new_proceed_known_good_controls": good_rate,
        "phi_minus_known_bad_proceed": (
            (phi_low - bad_rate["rate"])
            if (phi_low is not None and bad_rate["rate"] is not None) else None
        ),
        "phi_minus_known_good_proceed": (
            (phi_low - good_rate["rate"])
            if (phi_low is not None and good_rate["rate"] is not None) else None
        ),
        "prompt_attribution_reading_available": attribution_available,
        "gate": (
            "The 'the graveyard was a prompt artifact' reading is "
            "UNAVAILABLE when phi's CP95 overlaps the same-run NEW-arm "
            "proceed rate on KNOWN-BAD controls: the instrument would be "
            "proceeding on the graveyard at a rate indistinguishable from "
            "its rate on claims we labelled bad. Pre-stated."
        ),
        "post_swap_production_kills": {
            "iterations_since_swap_at_lock": 6,
            "kills_since_swap_at_lock": 0,
            "note": "REQUIRED context alongside phi (prereg §7.1): since the "
                    "2026-08-18T06:45Z swap the NEW instrument has proceeded "
                    "on 6/6 production iterations with retries_used=0 — it "
                    "has not killed anything in live production. Re-measure "
                    "at report time and print the current figure.",
        },
    }

    # F6: R is partitioned EXHAUSTIVELY. R = A u B u (U n R).
    R_partition = {
        "A_prompt_attributable_flip": sorted(A),
        "B_kill_not_reproducible_by_own_instrument": sorted(B),
        "U_and_R_old_arm_unscored": u_by_new["proceed"],
        "sizes": {"A": len(A), "B": len(B),
                  "U_and_R": len(u_by_new["proceed"])},
        "identity_holds": len(A) + len(B) + len(u_by_new["proceed"])
        == len(proceeds),
    }

    def _split(keyfn):
        out: dict = {}
        for rid in ids:
            k = str(keyfn(new_rows[rid]))
            b = out.setdefault(k, {"n": 0, "proceed": 0})
            b["n"] += 1
            b["proceed"] += int(v_new[rid] == "proceed")
        return {
            k: {**v, "rate": v["proceed"] / v["n"],
                "ci95": list(clopper_pearson(v["proceed"], v["n"]))}
            for k, v in sorted(out.items())
        }

    return {
        "prereg": PREREG,
        "N_targets": N,
        "phi": phi,
        "two_by_two": {
            "A_old_fatal_new_proceed": len(A),
            "B_old_proceed_new_proceed": len(B),
            "C_old_fatal_new_fatal": len(C),
            "D_old_proceed_new_fatal": len(D),
            "U_either_arm_unscored": len(U),
            "U_by_new_verdict": {k: len(v) for k, v in u_by_new.items()},
            "U_old_unscored_and_new_proceed": len(u_old_unscored_new_proceed),
            "identity_holds":
                len(A) + len(B) + len(C) + len(D) + len(U) == N,
        },
        "kappa_old": kappa_old,
        "mcnemar_exact_two_sided": {
            "A": len(A), "D": len(D), "p": mcnemar_p,
            "A_over_A_plus_D": _rate_block(len(A), len(A) + len(D)),
            "note": "Real teeth only when the discordance is lopsided: "
                    "A=20,D=2 -> p=1.2e-4; A=10,D=3 -> p=0.09. Stated in "
                    "advance so a null is not spun.",
        },
        "phi_comparators": comparators,
        "R_partition": R_partition,
        "splits_DESCRIPTIVE_no_multiplicity_correction": {
            "by_era": _split(lambda r: r.get("era")),
            "by_historical_confidence":
                _split(lambda r: r.get("historical_confidence")),
            "by_cluster_member_count":
                _split(lambda r: r.get("cluster_member_count")),
        },
        "multi_member_caveat": (
            "For multi-member clusters the evidence covers ONLY the founding "
            "member's text — a single re-adjudicated claim, not the cluster."
        ),
        "statistics_caveat": CAVEAT,
    }


# ---------------------------------------------------------------------------
# Arm runner
# ---------------------------------------------------------------------------

def _assert(cond: bool, exit_code: int, message: str):
    if not cond:
        print(f"REFUSING (exit {exit_code}): {message}", file=sys.stderr)
        return exit_code
    return 0


def run_arm(arm: str, out_path: Path, limit: int | None = None) -> int:
    # A relative --out crashed the R1a artifact write AFTER its calls were
    # spent. Anchor once, up front, before anything expensive.
    if not out_path.is_absolute():
        out_path = REPO_ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rc = _assert(MANIFEST_PATH.exists(), 4, f"{MANIFEST_PATH} is missing")
    if rc:
        return rc
    manifest_sha = _sha256_file(MANIFEST_PATH)
    rc = _assert(manifest_sha == LOCKED_MANIFEST_SHA256, 4,
                 f"manifest sha256 {manifest_sha} != locked "
                 f"{LOCKED_MANIFEST_SHA256}")
    if rc:
        return rc
    meta, rows = load_manifest(MANIFEST_PATH)
    kinds = {k: sum(1 for r in rows if r["kind"] == k)
             for k in LOCKED_MANIFEST_COUNTS}
    rc = _assert(kinds == LOCKED_MANIFEST_COUNTS, 4,
                 f"manifest row kinds {kinds} != locked "
                 f"{LOCKED_MANIFEST_COUNTS}")
    if rc:
        return rc

    fixtures_sha = _sha256_file(FIXTURES_PATH)
    rc = _assert(fixtures_sha == LOCKED_FIXTURES_SHA256, 5,
                 f"fixtures.jsonl sha256 {fixtures_sha} != locked "
                 f"{LOCKED_FIXTURES_SHA256}")
    if rc:
        return rc

    os.environ["CRITIC_BACKEND"] = CRITIC_BACKEND
    # Deferred imports: after the MOCK_LLM refusal, after CRITIC_BACKEND set.
    from agent_wrapper import wrapper as wrapper_mod
    from agent_wrapper.backends import get_backend
    from orchestrator.subagent import SubAgentBudget
    from workers import redteam_critic as rt_mod

    be = get_backend(CRITIC_BACKEND)
    rc = _assert(be.default_model == PINNED_MODEL, 3,
                 f"backend {CRITIC_BACKEND!r} registers model "
                 f"{be.default_model!r}, prereg pins {PINNED_MODEL!r} — "
                 "registry drift is a driver bug, never a finding")
    if rc:
        return rc

    # Install the arm's prompt and ASSERT its sha before any call.
    if arm == "old":
        rt_mod.REDTEAM_AGENT_SYSTEM_PROMPT = load_old_prompt()
    prompt_sha = _sha256_text(rt_mod.REDTEAM_AGENT_SYSTEM_PROMPT)
    rc = _assert(prompt_sha == ARM_PROMPT_SHA[arm], ARM_EXIT[arm],
                 f"{arm}-arm prompt sha256 {prompt_sha} != pinned "
                 f"{ARM_PROMPT_SHA[arm]}")
    if rc:
        return rc

    # F2: what the SERVER says, before the first call.
    probe_before = probe_served_model()
    rc = _assert(probe_before["model"] == PINNED_MODEL, 9,
                 f"/v1/models probe says {probe_before['model']!r} "
                 f"(error={probe_before['error']!r}), prereg pins "
                 f"{PINNED_MODEL!r}")
    if rc:
        return rc

    todo = rows[:limit] if limit else rows
    budget = SubAgentBudget(max_turns=BUDGET_MAX_TURNS,
                            max_wall_seconds=BUDGET_MAX_WALL_SECONDS)
    started_at = _utcnow()
    t_run = time.monotonic()
    out_rows: list[dict] = []
    aborted = None

    def _emit_artifact(probe_after, calls_dump, note=None):
        artifact = {
            "prereg": PREREG,
            "arm": arm,
            "backend": CRITIC_BACKEND,
            "prompt_sha256": prompt_sha,
            "prompt_source": ("bench/readjudication/old_prompt.txt (frozen; "
                              "recovered from git 7780898^ by AST extraction)"
                              if arm == "old" else
                              "workers.redteam_critic.REDTEAM_AGENT_SYSTEM_"
                              "PROMPT (live production module)"),
            "manifest_path": "bench/readjudication/manifest.jsonl",
            "manifest_sha256": manifest_sha,
            "manifest_meta": meta,
            "fixtures_sha256": fixtures_sha,
            "budget": {"max_turns": BUDGET_MAX_TURNS,
                       "max_wall_seconds": BUDGET_MAX_WALL_SECONDS},
            "invocation_seam": SEAM_NOTE,
            "pinned_model": PINNED_MODEL,
            "served_model_probe_before": probe_before,
            "served_model_probe_after": probe_after,
            "vllm_image_digest": (
                IMAGE_DIGEST_PATH.read_text().strip()
                if IMAGE_DIGEST_PATH.exists() else None
            ),
            "wrapper_model_version": wrapper_mod.MODEL_VERSION,
            "git_commit": _git_commit(),
            "started_at": started_at,
            "ended_at": _utcnow(),
            "limit": limit,
            "n_rows_run": len(out_rows),
            "calls_log_dump": calls_dump,
            "calls_log_note": (
                "workers.redteam_critic passes no log_path to run_subagent, "
                "so sub-agent turns land in agent_wrapper.wrapper.MEMORY_LOG "
                "(in-memory) — dumped here per RUN and joinable to rows by "
                "wrapper_request_id. History's redteam prompts were never "
                "written to disk (logs/calls.jsonl holds ZERO "
                "subagent.redteam_critic records); see prereg §3.2."
            ),
            "rows": out_rows,
        }
        if aborted:
            artifact["PARTIAL"] = aborted
            artifact["evaluation"] = {
                "uninterpretable": True, "reason": aborted}
        else:
            artifact["evaluation"] = evaluate_arm(out_rows, arm)
        if note:
            artifact["note"] = note
        out_path.write_text(json.dumps(artifact, indent=2) + "\n")
        return artifact

    def _dump_calls():
        try:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            path = out_path.parent / f"calls_{arm}_{stamp}.jsonl"
            with path.open("w") as fh:
                for rec in wrapper_mod.MEMORY_LOG:
                    fh.write(json.dumps(rec) + "\n")
            return (str(path.relative_to(REPO_ROOT))
                    if path.is_relative_to(REPO_ROOT) else str(path))
        except Exception as exc:
            print(f"warning: calls-log dump failed: {exc}", file=sys.stderr)
            return None

    def _observed_model(rid):
        """The SERVER-reported model for this row: the wrapper record's
        `model` field (= resp.model), joined by wrapper_request_id."""
        if not rid:
            return None
        for rec in reversed(wrapper_mod.MEMORY_LOG):
            if rec.get("request_id") == rid:
                return rec.get("model")
        return None

    for mrow in todo:
        # F1: the per-row prompt sha is ASSERTED, not merely recorded. A
        # silently reverted seam is otherwise invisible until the numbers.
        row_sha = _sha256_text(rt_mod.REDTEAM_AGENT_SYSTEM_PROMPT)
        if row_sha != ARM_PROMPT_SHA[arm]:
            aborted = (f"prompt sha drifted mid-run at row "
                       f"{mrow['row_id']}: {row_sha}")
            print(f"REFUSING (exit {ARM_EXIT[arm]}): {aborted}",
                  file=sys.stderr)
            _emit_artifact(probe_served_model(), _dump_calls())
            return ARM_EXIT[arm]

        if time.monotonic() - t_run > WALL_CAP_SECONDS:
            aborted = (f"wall cap {WALL_CAP_SECONDS}s exceeded after "
                       f"{len(out_rows)} rows — abort, never extend "
                       "(inviolate rule 7; extending is a slip-ladder "
                       "decision that returns to the owner)")
            print(f"REFUSING (exit 11): {aborted}", file=sys.stderr)
            _emit_artifact(probe_served_model(), _dump_calls())
            return 11

        t0 = time.perf_counter()
        out = rt_mod.redteam_critic(
            mrow["claim_text"],
            f"readjud-{arm}-{mrow['row_id']}",
            parent_request_id=f"readjud-{arm}",
            budget=budget,
        )
        wall_s = round(time.perf_counter() - t0, 3)
        res = out.get("result") or {}
        verdict = res.get("verdict") if out.get("status") == "passed" else None
        if verdict not in ("fatal_flaw", "proceed", "unscored"):
            # `error` (invalid input) is impossible — empty text is excluded
            # at manifest-build time — so it is a DRIVER DEFECT, not a
            # finding. Recorded honestly and treated as unscored (never
            # proceed).
            verdict = "unscored"
        rid = out.get("wrapper_request_id")
        observed = _observed_model(rid)
        row = {
            "row_id": mrow["row_id"],
            "kind": mrow["kind"],
            "order_key": mrow["order_key"],
            "cluster_id": mrow.get("cluster_id"),
            "founding_iteration": mrow.get("founding_iteration"),
            "claim_sha256": mrow["claim_sha256"],
            "label": mrow.get("label"),
            "provenance_class": mrow.get("provenance_class"),
            "variant": mrow.get("variant"),
            "era": mrow.get("era"),
            "historical_confidence": mrow.get("historical_confidence"),
            "cluster_member_count": mrow.get("cluster_member_count"),
            "arm": arm,
            "prompt_sha256_at_call": row_sha,
            "verdict": verdict,
            "worker_status": out.get("status"),
            "confidence": res.get("confidence"),
            "critique_digest": (res.get("critique") or "")[:240],
            "wall_s": wall_s,
            "call_ts": _utcnow(),
            "wrapper_request_id": rid,
            "subagent_status": res.get("subagent_status"),
            "subagent_backend": res.get("subagent_backend"),
            # NOTE: a process constant (wrapper.MODEL) — kept for continuity
            # with the historical records, NEVER used as a serving check.
            "subagent_model_DECLARED": res.get("subagent_model"),
            "served_model_OBSERVED": observed,
            "errors": out.get("errors") or [],
        }
        out_rows.append(row)
        print(f"  {mrow['row_id']:26s} {mrow['kind']:8s} -> {verdict:10s} "
              f"({wall_s:.1f}s)")

        if observed is not None and observed != PINNED_MODEL:
            aborted = (f"row {mrow['row_id']}: server reported model "
                       f"{observed!r} != pinned {PINNED_MODEL!r} — a serving "
                       "change mid-run breaks the pairing")
            print(f"REFUSING (exit 8): {aborted}", file=sys.stderr)
            _emit_artifact(probe_served_model(), _dump_calls())
            return 8

    # Q3 replicate — a SECOND new-arm draw on the first REPLICATE_N targets by
    # ascending order_key, as a separate final pass. Descriptive; the primary
    # statistic uses the FIRST draw only (pre-stated, prereg §7.3).
    if arm == "new" and not limit:
        replicate_ids = [r["row_id"] for r in rows if r["kind"] == "target"][
            :REPLICATE_N]
        by_id = {r["row_id"]: r for r in rows}
        for rid_ in replicate_ids:
            mrow = by_id[rid_]
            t0 = time.perf_counter()
            out = rt_mod.redteam_critic(
                mrow["claim_text"], f"readjud-{arm}-replicate-{rid_}",
                parent_request_id=f"readjud-{arm}-replicate", budget=budget,
            )
            res = out.get("result") or {}
            verdict = res.get("verdict") if out.get("status") == "passed" else None
            if verdict not in ("fatal_flaw", "proceed", "unscored"):
                verdict = "unscored"
            out_rows.append({
                "row_id": rid_, "kind": "replicate", "arm": arm,
                "prompt_sha256_at_call":
                    _sha256_text(rt_mod.REDTEAM_AGENT_SYSTEM_PROMPT),
                "verdict": verdict,
                "wall_s": round(time.perf_counter() - t0, 3),
                "call_ts": _utcnow(),
                "wrapper_request_id": out.get("wrapper_request_id"),
                "served_model_OBSERVED":
                    _observed_model(out.get("wrapper_request_id")),
            })
            print(f"  [replicate] {rid_:26s} -> {verdict}")

    probe_after = probe_served_model()
    calls_dump = _dump_calls()
    note = None
    if limit:
        note = (f"PARTIAL RUN (--limit {limit}): the bars are only meaningful "
                "on the full locked manifest.")
    artifact = _emit_artifact(probe_after, calls_dump, note)

    if probe_after["model"] != PINNED_MODEL:
        print(f"REFUSING (exit 9): post-run /v1/models probe says "
              f"{probe_after['model']!r} != pinned {PINNED_MODEL!r} — the "
              "serving stack changed under the run", file=sys.stderr)
        return 9

    print(f"\nartifact -> {out_path}")
    ev = artifact["evaluation"]
    for name, bar in ev["bars"].items():
        print(f"  {name}: {json.dumps({k: v for k, v in bar.items() if k in ('fatal', 'unscored', 'n', 'parsed', 'cap', 'pass', 'evaluable')})}")
    print(f"  run_validity: {ev['run_validity']}")
    print(f"  r1a replication (n=24): {ev['r1a_replication'].get('agreement')}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--arm", choices=("old", "new"))
    ap.add_argument("--evaluate-pair", nargs=2,
                    metavar=("OLD_ARTIFACT", "NEW_ARTIFACT"),
                    help="cross-arm evaluation; makes NO calls")
    ap.add_argument("--limit", type=int, default=None,
                    help="run only the first N manifest rows (smoke)")
    ap.add_argument("--out", required=True,
                    help="artifact path (convention: bench/readjudication/runs/)")
    args = ap.parse_args(argv)

    if bool(args.arm) == bool(args.evaluate_pair):
        print("REFUSING (exit 10): pass exactly one of --arm / "
              "--evaluate-pair.", file=sys.stderr)
        return 10

    if args.evaluate_pair:
        out_path = Path(args.out)
        if not out_path.is_absolute():
            out_path = REPO_ROOT / out_path
        old_art = json.loads(Path(args.evaluate_pair[0]).read_text())
        new_art = json.loads(Path(args.evaluate_pair[1]).read_text())
        result = evaluate_pair(old_art, new_art)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=2) + "\n")
        print(f"evaluation -> {out_path}")
        return 0

    # Refusal before ANY repo import or call (inviolate rule 10): a MOCK_LLM
    # run is stubbed and silently meaningless.
    if "MOCK_LLM" in os.environ:
        print("REFUSING (exit 2): MOCK_LLM is set — this driver makes real "
              "redteam calls only. Re-run with `env -u MOCK_LLM`.",
              file=sys.stderr)
        return 2

    return run_arm(args.arm, Path(args.out), args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
