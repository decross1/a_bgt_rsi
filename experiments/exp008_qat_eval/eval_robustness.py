#!/usr/bin/env python3
# EVAL-ONLY benchmark. Scratch container :8002 ONLY. NEVER the production :8000.
"""exp008 — robustness sweep for the QAT-vs-pin eval.

This is the ROBUSTNESS half of the exp008 eval. The headline quality metrics
(novelty agreement, calibration error, tool-call adherence) are measured under
GREEDY decoding (temperature 0). Robustness asks a different question: when we
re-ask the *same* hypothesis under a small set of seed/prompt variations, does
an arm's verdict hold, or does it wobble? We report, per arm:

  - the MODAL verdict across the sweep (the verdict the arm lands on most often)
  - the modal SHARE (modal_count / total) — 1.0 means perfectly stable
  - the per-arm VARIANCE of the numeric score the verdict is read off of

Each hypothesis carries its own ``decide(text) -> (verdict, score)`` reader, so
this harness is mechanism-agnostic: it just sweeps, reads, and tallies.

SAFETY (CLAUDE.md inviolate rules):
  - EVAL-ONLY. This never swaps the production pin and never calls the
    production :8000 endpoint. Real runs target the SCRATCH container on
    :8002 (see serve_qat.sh), one request at a time.
  - Eval calls log to ``experiments/exp008_qat_eval/runs/*.jsonl`` ONLY,
    never to production ``logs/calls.jsonl``.
  - Quality is measured greedy (temperature 0). The sweep DELIBERATELY varies
    seed and prompt phrasing to probe stability — that variation is the
    measurement, not noise to be averaged into a quality number.

Offline by default. Under ``MOCK_LLM`` (the default shell env) the model call
is a deterministic stub keyed on (arm, seed, prompt) — no live model, no
network — so the full sweep runs with no GPU. For a real sweep, prefix with
``env -u MOCK_LLM`` and point ``--base-url`` at the scratch :8002 endpoint.

Reproduce (offline smoke, MOCK_LLM default):
    ./.venv-chroma/bin/python \\
        experiments/exp008_qat_eval/eval_robustness.py --arm pin

Real sweep (scratch container only):
    env -u MOCK_LLM ./.venv-chroma/bin/python \\
        experiments/exp008_qat_eval/eval_robustness.py \\
        --arm qat --base-url http://localhost:8002/v1
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import pvariance
from typing import Callable

EXP_DIR = Path(__file__).resolve().parent
RUNS_DIR = EXP_DIR / "runs"

# Guardrail: the production endpoint. A real sweep must NEVER point here.
_PRODUCTION_PORT = ":8000"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# --- Hypotheses ------------------------------------------------------------
#
# A hypothesis is a small probe with a deterministic READER that maps the
# model's completion to (verdict, numeric_score). The reader is what makes the
# verdict reproducible offline and keeps this harness mechanism-agnostic.

def _read_yes_no(text: str) -> tuple[str, float]:
    """Read a YES/NO verdict and a confidence score from the completion.

    score is the fraction of the (lowercased) completion that leans YES, used
    only to compute the per-arm variance of the sweep. The verdict is the sign.
    """
    t = (text or "").lower()
    yes = t.count("yes")
    no = t.count("no")
    total = yes + no
    if total == 0:
        return ("ABSTAIN", 0.5)
    score = yes / total
    return (("YES" if score >= 0.5 else "NO"), score)


HYPOTHESES: list[dict] = [
    {
        "id": "h1_truthful_dominant",
        "prompt": "In a sealed-bid second-price (Vickrey) auction, is truthful "
                  "bidding a dominant strategy? Answer YES or NO, then explain.",
        "decide": _read_yes_no,
    },
    {
        "id": "h2_first_price_truthful",
        "prompt": "In a sealed-bid FIRST-price auction, is bidding your true "
                  "value a dominant strategy? Answer YES or NO, then explain.",
        "decide": _read_yes_no,
    },
    {
        "id": "h3_revenue_equivalence",
        "prompt": "Under the revenue-equivalence theorem's assumptions, do the "
                  "first-price and second-price auctions yield the same "
                  "expected revenue? Answer YES or NO, then explain.",
        "decide": _read_yes_no,
    },
    {
        "id": "h4_dominant_needs_knowledge",
        "prompt": "Does playing a dominant strategy require knowing the other "
                  "bidders' valuations? Answer YES or NO, then explain.",
        "decide": _read_yes_no,
    },
]


# A small bank of neutral prompt-phrasing wrappers. Varying the phrasing (along
# with the seed) is the robustness probe: a stable arm gives the same verdict
# regardless of which wrapper framed the question.
_PROMPT_WRAPPERS: list[Callable[[str], str]] = [
    lambda q: q,
    lambda q: f"Question: {q}",
    lambda q: f"Consider the following carefully.\n\n{q}",
    lambda q: f"{q}\n\nThink step by step before you answer.",
]


def _stub_completion(arm: str, prompt: str, seed: int) -> str:
    """Deterministic offline model stub keyed on (arm, prompt, seed).

    Emits a short completion containing YES/NO tokens so the readers produce a
    verdict with no live model and no network. The (arm, seed) keying gives a
    little cross-seed wobble so the variance/modal machinery is exercised.
    """
    key = f"{arm}|{prompt}|{seed}".encode("utf-8")
    digest = hashlib.sha256(key).hexdigest()
    frac = int(digest[:8], 16) / 0xFFFFFFFF
    if frac >= 0.5:
        body = "yes. " + "yes " * 3
    else:
        body = "no. " + "no " * 3
    return f"mock_stub({arm},seed={seed}): {body}"


def _live_completion(prompt: str, *, base_url: str, model: str, seed: int) -> str:
    """One greedy (temperature 0) completion from the SCRATCH endpoint.

    Imported lazily so the offline path (MOCK_LLM) needs no openai client.
    One request at a time — the caller loops serially.
    """
    if _PRODUCTION_PORT in base_url:
        raise SystemExit(
            f"REFUSING to run: base_url {base_url!r} points at the production "
            f"endpoint ({_PRODUCTION_PORT}). exp008 is EVAL-ONLY against the "
            "scratch container on :8002."
        )
    from openai import OpenAI  # lazy import; offline path never needs it

    client = OpenAI(base_url=base_url, api_key=os.environ.get("OPENAI_API_KEY", "EMPTY"))
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,  # greedy: quality is greedy; the sweep varies seed/prompt
        seed=seed,
        max_tokens=256,
    )
    return resp.choices[0].message.content or ""


def sweep_arm(
    arm: str,
    *,
    hypotheses: list[dict],
    seeds: list[int],
    wrappers: list[Callable[[str], str]],
    completer: Callable[[str, int], str],
) -> dict:
    """Run the seed x prompt sweep for one arm and return its summary + rows.

    For every (hypothesis, seed, prompt-wrapper) we get a completion, read a
    (verdict, score), and tally. Per hypothesis we report the modal verdict, the
    modal share, and the variance of the read-off score across the sweep.
    """
    per_hypo: list[dict] = []
    rows: list[dict] = []
    for h in hypotheses:
        verdicts: list[str] = []
        scores: list[float] = []
        for seed in seeds:
            for wi, wrap in enumerate(wrappers):
                prompt = wrap(h["prompt"])
                completion = completer(prompt, seed)
                verdict, score = h["decide"](completion)
                verdicts.append(verdict)
                scores.append(score)
                rows.append({
                    "arm": arm,
                    "hypothesis_id": h["id"],
                    "seed": seed,
                    "wrapper_idx": wi,
                    "verdict": verdict,
                    "score": score,
                })
        counts = Counter(verdicts)
        modal_verdict, modal_count = counts.most_common(1)[0]
        total = len(verdicts)
        per_hypo.append({
            "hypothesis_id": h["id"],
            "n": total,
            "modal_verdict": modal_verdict,
            "modal_count": modal_count,
            "modal_share": (modal_count / total) if total else 0.0,
            "score_variance": pvariance(scores) if len(scores) > 1 else 0.0,
            "verdict_counts": dict(counts),
        })

    # Arm-level rollup: mean modal share and max per-hypothesis variance.
    shares = [h["modal_share"] for h in per_hypo]
    variances = [h["score_variance"] for h in per_hypo]
    summary = {
        "arm": arm,
        "metric": "robustness",
        "n_hypotheses": len(per_hypo),
        "n_per_hypothesis": len(seeds) * len(wrappers),
        "mean_modal_share": (sum(shares) / len(shares)) if shares else 0.0,
        "max_score_variance": max(variances) if variances else 0.0,
        "per_hypothesis": per_hypo,
    }
    return {"summary": summary, "rows": rows}


def _write_jsonl(path: Path, summary: dict, rows: list[dict]) -> None:
    """Write the robustness JSONL: one summary row (kind=summary) then detail.

    analyze.py reads kind=summary rows; the detail rows are kept for audit.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fh:
        fh.write(json.dumps({"kind": "summary", **summary}) + "\n")
        for r in rows:
            fh.write(json.dumps({"kind": "detail", **r}) + "\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="exp008 robustness sweep (EVAL-ONLY)")
    p.add_argument("--arm", required=True,
                   help="arm label, e.g. 'pin' (production pin) or 'qat'")
    p.add_argument("--seeds", type=str, default="1,2,3",
                   help="comma-separated seeds for the sweep (default 1,2,3)")
    p.add_argument("--base-url", type=str, default=None,
                   help="scratch endpoint base url (real runs only; MUST be :8002, "
                        "NEVER :8000)")
    p.add_argument("--model", type=str, default="gemma-4-26b-a4b-nvfp4",
                   help="model id for the scratch endpoint (real runs only)")
    p.add_argument("--out", type=str, default=None,
                   help="output JSONL path (default runs/robustness_<arm>.jsonl)")
    args = p.parse_args(argv)

    mock = bool(os.environ.get("MOCK_LLM"))
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    out_path = Path(args.out) if args.out else RUNS_DIR / f"robustness_{args.arm}.jsonl"

    if mock:
        def completer(prompt: str, seed: int) -> str:
            return _stub_completion(args.arm, prompt, seed)
    else:
        if not args.base_url:
            raise SystemExit(
                "real run needs --base-url (the scratch :8002 endpoint). "
                "exp008 is EVAL-ONLY; never the production :8000."
            )
        base_url = args.base_url
        model = args.model

        def completer(prompt: str, seed: int) -> str:
            return _live_completion(prompt, base_url=base_url, model=model, seed=seed)

    print(f"=== exp008 robustness sweep arm={args.arm} mock={mock} "
          f"seeds={seeds} at {_utcnow_iso()} ===", flush=True)
    t0 = time.perf_counter()
    result = sweep_arm(
        args.arm,
        hypotheses=HYPOTHESES,
        seeds=seeds,
        wrappers=_PROMPT_WRAPPERS,
        completer=completer,
    )
    wall_s = time.perf_counter() - t0

    _write_jsonl(out_path, result["summary"], result["rows"])
    s = result["summary"]
    print(f"wrote {out_path}", flush=True)
    print(f"arm={args.arm} mean_modal_share={s['mean_modal_share']:.3f} "
          f"max_score_variance={s['max_score_variance']:.4f} "
          f"({s['n_hypotheses']} hypotheses x {s['n_per_hypothesis']} probes, "
          f"{wall_s:.1f}s)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
