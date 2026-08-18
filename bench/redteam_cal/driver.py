"""Run driver — D-075 R1a redteam calibration battery (one arm per process).

Prereg: experiments/PREREG_redteam_cal_2026-08-18.md (v2). ALL THREE ARMS
RUN TO COMPLETION on all 24 fixtures; arm ORDER matters only at adoption
evaluation, which is the integrator's job — this driver runs exactly one
arm per invocation (which is also what gives the prereg's fresh
interpreter + per-arm calls-log isolation for free: the redteam
sub-agent's wrapper turns land in agent_wrapper.wrapper.MEMORY_LOG for
this process only, and are dumped per-arm next to the artifact).

Arms:
  gemma-current  CRITIC_BACKEND=vllm-gemma, production prompt as deployed
  gemma-revised  CRITIC_BACKEND=vllm-gemma, prompt from revised_prompt.txt
  qwen38         CRITIC_BACKEND=vllm-qwen (qwen3.8-27b-nvfp4-mtp),
                 production prompt

Production seam: workers.redteam_critic.redteam_critic(hypothesis_text,
iteration_id, parent_request_id=...) — hypothesis_text alone, exactly as
orchestrator/nara.py:944 invokes it. Budgets are PINNED here per the
prereg (max_turns=3, max_wall_seconds=45.0 — the production values,
passed explicitly rather than resolved at run time).

Prompt-injection seam (gemma-revised), documented: the worker reads the
module global REDTEAM_AGENT_SYSTEM_PROMPT at call time, so a
monkeypatch-style constant override on the imported module
(``rt_mod.REDTEAM_AGENT_SYSTEM_PROMPT = <revised>``) is the least
invasive injection — the same override style the unit tests already use
for run_subagent; no production code change; the module supports no env
var for the prompt. `apply_prompt_variant` below is that seam.

Refusals (never coerced):
  exit 2  MOCK_LLM is set in the environment (stubbed run would be
          silently meaningless — run with `env -u MOCK_LLM`)
  exit 3  qwen38 arm resolved a backend whose registered model is not
          the pinned qwen3.8-27b-nvfp4-mtp (registry drift = driver bug,
          never a finding)
  exit 4  fixtures.jsonl fails the 24-row / 12-12 sanity check

Usage:
  env -u MOCK_LLM .venv-chroma/bin/python -m bench.redteam_cal.driver \
      --arm gemma-current --out bench/redteam_cal/runs/gemma-current.json
"""
from __future__ import annotations

import argparse
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
FIXTURES_PATH = HERE / "fixtures.jsonl"
REVISED_PROMPT_PATH = HERE / "revised_prompt.txt"
DEFAULT_RUNS_DIR = HERE / "runs"

PREREG = "experiments/PREREG_redteam_cal_2026-08-18.md"

ARMS = {
    "gemma-current": {"backend": "vllm-gemma", "prompt_variant": "production"},
    "gemma-revised": {"backend": "vllm-gemma", "prompt_variant": "revised"},
    "qwen38": {"backend": "vllm-qwen", "prompt_variant": "production"},
}
QWEN_PINNED_MODEL = "qwen3.8-27b-nvfp4-mtp"

# Prereg-pinned budgets (production values, pinned — not resolved at run time).
BUDGET_MAX_TURNS = 3
BUDGET_MAX_WALL_SECONDS = 45.0

CAVEAT = (
    "At n=12/class a zero-discrimination coin passes bars 2 AND 3 with "
    "~1.4% probability per arm and a weak 60/40 instrument with ~10% — "
    "this battery discriminates condemners and coins from calibrated "
    "instruments, not strong from mediocre ones."
)
BAR4_NOTE = (
    "REPORTED, not load-bearing: bars 2 AND 3 at their thresholds already "
    "imply a >=40-point good/bad gap; this diagnostic can never bind."
)


# ---------------------------------------------------------------------------
# Exact Clopper-Pearson CI (pure stdlib; n <= 24 so exact binomial sums
# via math.comb + bisection are cheap and dependency-free)
# ---------------------------------------------------------------------------

def _binom_sf_geq(x: int, n: int, p: float) -> float:
    """P(X >= x) for X ~ Binomial(n, p)."""
    return sum(math.comb(n, k) * p**k * (1 - p) ** (n - k) for k in range(x, n + 1))


def _binom_cdf_leq(x: int, n: int, p: float) -> float:
    """P(X <= x) for X ~ Binomial(n, p)."""
    return sum(math.comb(n, k) * p**k * (1 - p) ** (n - k) for k in range(0, x + 1))


def _bisect(f, lo: float, hi: float, iters: int = 100) -> float:
    """Root of monotone f on [lo, hi] with f(lo), f(hi) opposite signs."""
    flo = f(lo)
    for _ in range(iters):
        mid = (lo + hi) / 2.0
        fmid = f(mid)
        if (flo < 0) == (fmid < 0):
            lo, flo = mid, fmid
        else:
            hi = mid
    return (lo + hi) / 2.0


def clopper_pearson(x: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    """Exact (Clopper-Pearson) two-sided (1-alpha) CI for a binomial rate."""
    if n == 0:
        return (0.0, 1.0)
    if not (0 <= x <= n):
        raise ValueError(f"x={x} out of range for n={n}")
    lower = 0.0 if x == 0 else _bisect(
        lambda p: _binom_sf_geq(x, n, p) - alpha / 2.0, 0.0, 1.0
    )
    upper = 1.0 if x == n else _bisect(
        lambda p: (alpha / 2.0) - _binom_cdf_leq(x, n, p), 0.0, 1.0
    )
    return (lower, upper)


# ---------------------------------------------------------------------------
# Bar math (pure; unit-tested on synthetic fixtures)
# ---------------------------------------------------------------------------

def _class_confusion(rows: list[dict]) -> dict:
    out: dict[str, dict] = {}
    for r in rows:
        cls = r.get("provenance_class", "unknown")
        c = out.setdefault(
            cls, {"n": 0, "fatal_flaw": 0, "proceed": 0, "unscored": 0}
        )
        c["n"] += 1
        if r["unscored"]:
            c["unscored"] += 1
        elif r["verdict"] == "fatal_flaw":
            c["fatal_flaw"] += 1
        else:
            c["proceed"] += 1
    return out


def evaluate(rows: list[dict]) -> dict:
    """Per-bar evaluation of one arm's per-fixture rows.

    Bars are LOCKED and INDEPENDENT (inviolate rule 4) — each is
    reported on its own; no near-miss is ever coerced. Unscored rows
    are excluded from discrimination denominators and reported as
    integers (bar 1)."""
    good = [r for r in rows if r["label"] == "known_good"]
    bad = [r for r in rows if r["label"] == "known_bad"]
    n_unscored = sum(1 for r in rows if r["unscored"])

    parsed_good = [r for r in good if not r["unscored"]]
    parsed_bad = [r for r in bad if not r["unscored"]]
    fatal_good = sum(1 for r in parsed_good if r["verdict"] == "fatal_flaw")
    fatal_bad = sum(1 for r in parsed_bad if r["verdict"] == "fatal_flaw")
    n_pg, n_pb = len(parsed_good), len(parsed_bad)

    bar1 = {
        "name": "parse_health",
        "unscored": n_unscored,
        "cap": 2,
        "pass": n_unscored <= 2,
    }
    # Integer arithmetic at the thresholds — no float edge at 75%/35%.
    bar2 = {
        "name": "catches_the_bad",
        "fatal": fatal_bad,
        "parsed": n_pb,
        "rate": (fatal_bad / n_pb) if n_pb else None,
        "ci95": list(clopper_pearson(fatal_bad, n_pb)) if n_pb else None,
        "threshold": "fatal_flaw on >= 75% of parsed known-bad",
        "pass": bool(n_pb and fatal_bad * 100 >= 75 * n_pb),
    }
    bar3 = {
        "name": "passes_the_good",
        "fatal": fatal_good,
        "parsed": n_pg,
        "rate": (fatal_good / n_pg) if n_pg else None,
        "ci95": list(clopper_pearson(fatal_good, n_pg)) if n_pg else None,
        "threshold": "fatal_flaw on <= 35% of parsed known-good",
        "pass": bool(n_pg and fatal_good * 100 <= 35 * n_pg),
    }
    gap = (
        (fatal_bad / n_pb) - (fatal_good / n_pg) if (n_pb and n_pg) else None
    )
    bar4 = {
        "name": "gap",
        "load_bearing": False,
        "gap_points": (round(gap * 100, 3) if gap is not None else None),
        "note": BAR4_NOTE,
    }
    return {
        "n_rows": len(rows),
        "n_known_good": len(good),
        "n_known_bad": len(bad),
        "n_unscored": n_unscored,
        "bars": {"bar1": bar1, "bar2": bar2, "bar3": bar3, "bar4": bar4},
        "all_load_bearing_bars_pass": bool(
            bar1["pass"] and bar2["pass"] and bar3["pass"]
        ),
        "confusion": {
            "known_good_by_provenance": _class_confusion(good),
            # Informational — the prereg requires the known-good split;
            # the known-bad split rides along for symmetry.
            "known_bad_by_provenance": _class_confusion(bad),
        },
        "statistics_caveat": CAVEAT,
    }


# ---------------------------------------------------------------------------
# Prompt-injection seam (gemma-revised)
# ---------------------------------------------------------------------------

def load_revised_prompt() -> str:
    """The frozen revision, byte-for-byte from revised_prompt.txt minus
    the file's single trailing newline (the production constant has no
    trailing newline)."""
    text = REVISED_PROMPT_PATH.read_text()
    return text[:-1] if text.endswith("\n") else text


def apply_prompt_variant(rt_mod, variant: str) -> str:
    """Install the prompt for `variant` on the imported worker module and
    return the prompt text now in effect.

    Seam: workers.redteam_critic reads the module global
    REDTEAM_AGENT_SYSTEM_PROMPT at call time inside redteam_critic(), so
    overriding the constant on the module object (monkeypatch-style) is
    the least-invasive injection — no production code change, no env var
    (the module supports none for the prompt)."""
    if variant == "revised":
        rt_mod.REDTEAM_AGENT_SYSTEM_PROMPT = load_revised_prompt()
    return rt_mod.REDTEAM_AGENT_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Arm runner
# ---------------------------------------------------------------------------

def load_fixtures() -> list[dict]:
    rows = []
    with FIXTURES_PATH.open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


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


def run_arm(arm: str, out_path: Path, limit: int | None) -> int:
    # A relative --out crashed the artifact write on the first live run
    # (relative_to(REPO_ROOT) at the calls_log_dump field raised ValueError
    # AFTER the calls were spent); anchor once, up front.
    if not out_path.is_absolute():
        out_path = REPO_ROOT / out_path
    cfg = ARMS[arm]
    os.environ["CRITIC_BACKEND"] = cfg["backend"]

    # Deferred imports: after the MOCK_LLM refusal, after CRITIC_BACKEND set.
    sys.path.insert(0, str(REPO_ROOT))
    from agent_wrapper import wrapper as wrapper_mod
    from agent_wrapper.backends import get_backend
    from orchestrator.subagent import SubAgentBudget
    from workers import redteam_critic as rt_mod

    if arm == "qwen38":
        be = get_backend(cfg["backend"])
        if be.default_model != QWEN_PINNED_MODEL:
            print(
                f"REFUSING (exit 3): backend {cfg['backend']!r} registers "
                f"model {be.default_model!r}, prereg pins {QWEN_PINNED_MODEL!r}"
                " — registry drift is a driver bug, never a finding.",
                file=sys.stderr,
            )
            return 3

    prompt_in_effect = apply_prompt_variant(rt_mod, cfg["prompt_variant"])

    fixtures = load_fixtures()
    n_good = sum(1 for f in fixtures if f["label"] == "known_good")
    n_bad = sum(1 for f in fixtures if f["label"] == "known_bad")
    if len(fixtures) != 24 or n_good != 12 or n_bad != 12:
        print(
            f"REFUSING (exit 4): fixtures.jsonl integrity check failed "
            f"({len(fixtures)} rows, {n_good}/{n_bad} split; expected 24, "
            "12/12).",
            file=sys.stderr,
        )
        return 4

    todo = fixtures[:limit] if limit else fixtures
    budget = SubAgentBudget(
        max_turns=BUDGET_MAX_TURNS, max_wall_seconds=BUDGET_MAX_WALL_SECONDS
    )
    started_at = _utcnow()
    rows = []
    for fx in todo:
        t0 = time.perf_counter()
        out = rt_mod.redteam_critic(
            fx["hypothesis_text"],
            f"redteam-cal-{arm}-{fx['id']}",
            parent_request_id=f"redteam-cal-{arm}",
            budget=budget,
        )
        wall_s = round(time.perf_counter() - t0, 3)
        res = out.get("result") or {}
        verdict = res.get("verdict") if out.get("status") == "passed" else None
        if verdict not in ("fatal_flaw", "proceed", "unscored"):
            verdict = "unscored"  # defensive; recorded honestly below
        row = {
            "id": fx["id"],
            "label": fx["label"],
            "provenance_class": fx["provenance"]["class"],
            "verdict": verdict,
            "confidence": res.get("confidence"),
            "critique_digest": (res.get("critique") or "")[:240],
            "wall_s": wall_s,
            "unscored": verdict == "unscored",
            "subagent_status": res.get("subagent_status"),
            "subagent_backend": res.get("subagent_backend"),
            "subagent_model": res.get("subagent_model"),
            "subagent_wall_seconds": res.get("subagent_wall_seconds"),
            "errors": out.get("errors") or [],
        }
        rows.append(row)
        print(
            f"  {fx['id']:22s} {fx['label']:10s} -> {verdict:10s} "
            f"({wall_s:.1f}s)"
        )

    ended_at = _utcnow()
    evaluation = evaluate(rows)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    calls_dump_path = None
    try:  # per-arm calls-log dump (redteam sub-agent turns log in-memory)
        calls_dump_path = out_path.parent / f"calls_{arm}_{stamp}.jsonl"
        with calls_dump_path.open("w") as fh:
            for rec in wrapper_mod.MEMORY_LOG:
                fh.write(json.dumps(rec) + "\n")
    except Exception as exc:  # best-effort; the artifact says so
        print(f"warning: calls-log dump failed: {exc}", file=sys.stderr)
        calls_dump_path = None

    artifact = {
        "prereg": PREREG,
        "arm": arm,
        "backend": cfg["backend"],
        "prompt_variant": cfg["prompt_variant"],
        "prompt_sha256": hashlib.sha256(
            prompt_in_effect.encode()
        ).hexdigest(),
        "fixtures_path": str(FIXTURES_PATH.relative_to(REPO_ROOT)),
        "fixtures_sha256": hashlib.sha256(
            FIXTURES_PATH.read_bytes()
        ).hexdigest(),
        "budget": {
            "max_turns": BUDGET_MAX_TURNS,
            "max_wall_seconds": BUDGET_MAX_WALL_SECONDS,
        },
        "invocation_seam": (
            "workers.redteam_critic.redteam_critic(hypothesis_text, "
            "iteration_id, parent_request_id=...) — production-faithful "
            "per orchestrator/nara.py:944"
        ),
        "git_commit": _git_commit(),
        "started_at": started_at,
        "ended_at": ended_at,
        "limit": limit,
        "n_fixtures_run": len(rows),
        "calls_log_dump": (
            # repo-relative when inside the repo; absolute otherwise — an
            # out-of-repo --out must never crash AFTER the calls are spent
            # (review catch; same class as the relative-path crash).
            (str(calls_dump_path.relative_to(REPO_ROOT))
             if calls_dump_path.is_relative_to(REPO_ROOT)
             else str(calls_dump_path))
            if calls_dump_path else None
        ),
        "rows": rows,
        "evaluation": evaluation,
    }
    if limit:
        artifact["note"] = (
            f"PARTIAL RUN (--limit {limit}): bars are only meaningful on "
            "the full 24-fixture matrix."
        )
    out_path.write_text(json.dumps(artifact, indent=2) + "\n")
    print(f"\nartifact -> {out_path}")
    b = evaluation["bars"]
    print(
        f"bar1 parse_health : unscored={b['bar1']['unscored']}/24 "
        f"pass={b['bar1']['pass']}\n"
        f"bar2 catches_bad  : {b['bar2']['fatal']}/{b['bar2']['parsed']} "
        f"pass={b['bar2']['pass']} ci95={b['bar2']['ci95']}\n"
        f"bar3 passes_good  : {b['bar3']['fatal']}/{b['bar3']['parsed']} "
        f"pass={b['bar3']['pass']} ci95={b['bar3']['ci95']}\n"
        f"bar4 gap (report) : {b['bar4']['gap_points']} points"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    # Refusal FIRST, before any repo import: a MOCK_LLM run is stubbed
    # and silently meaningless (inviolate rule 10 — real runs use
    # `env -u MOCK_LLM`).
    if "MOCK_LLM" in os.environ:
        print(
            "REFUSING (exit 2): MOCK_LLM is set — this driver makes real "
            "redteam calls only. Re-run with `env -u MOCK_LLM`.",
            file=sys.stderr,
        )
        return 2

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--arm", required=True, choices=sorted(ARMS))
    ap.add_argument("--limit", type=int, default=None,
                    help="run only the first N fixtures (smoke)")
    ap.add_argument("--out", required=True,
                    help="artifact path (convention: bench/redteam_cal/runs/)")
    args = ap.parse_args(argv)
    return run_arm(args.arm, Path(args.out), args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
