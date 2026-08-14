"""Worker: idea_judge — LLM equivalence judge for idea-ledger candidates (P3/A5).

`judge_pair(claim_a, claim_b)` asks the local model whether two claim texts are
the same idea, a strictly better restatement, or distinct:
    {"verdict": "equivalent"|"better_with_delta"|"distinct",
     "delta": str, "confidence": float}

The judge is the INJECTED seam behind `workers/idea_ledger.accept_candidate`
(prefilter-only until calibration passes — LOOP_V1 P3). It NEVER activates on
vibes: `--calibrate` scores it against lexical ground truth (the known
loop_memory restatement clusters) under pre-registered bars, each checked
independently and never coerced; `judge_active(results)` refuses activation
unless every bar passes.

MOCK_LLM: `judge_pair` returns a deterministic lexical-overlap stub, clearly
labeled — never a fabricated model verdict. Unparseable/invalid real-model
output RAISES (no silent fallback verdict); the calibration harness counts
those failures against the judge instead of hiding them.

Calibration CLI:
    .venv-chroma/bin/python -m workers.idea_judge --calibrate [--dry-run]
Builds labeled pairs from loop_memory (positives = intra-cluster pairs of the
big lexical clusters; hard negatives = cross-cluster cosine neighbors; random
negatives), runs judge_pair both orders x 2 temps, scores vs lexical ground
truth, writes experiments/judge_calibration/results.json (dry-run writes
nothing).
"""
from __future__ import annotations

import argparse
import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from agent_wrapper.wrapper import call_sync
from orchestrator import runtime
from workers.mine_paper_gap import _cosine, _embed_texts, _read_jsonl
from workers.retrieval_relevance import _tokenize

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOOP_MEMORY = REPO_ROOT / "memory" / "loop_memory.jsonl"
DEFAULT_RESULTS_PATH = REPO_ROOT / "experiments" / "judge_calibration" / "results.json"
CALLS_LOG_PATH = os.environ.get("LOOP_V0_CALLS_LOG", "logs/calls.jsonl")

VERDICTS = ("equivalent", "better_with_delta", "distinct")

# ── Pre-registered calibration bars (LOOP_V1 P3 — module constants, each
# checked INDEPENDENTLY via passes(); never coerced; fail -> prefilter-only
# stands and the judge stays advisory). ──────────────────────────────────────
EQUIV_PRECISION_MIN = 0.90
EQUIV_RECALL_MIN = 0.80
FALSE_EQUIV_MAX = 0.10
SYMMETRY_DISAGREE_MAX = 0.10
VERDICT_FLIP_MAX = 0.15

# Calibration-set construction constants.
CALIBRATION_TEMPS = (0.2, 0.7)   # each pair judged both orders at each temp
GROUND_TRUTH_JACCARD = 0.6       # lexical cluster edge threshold (ground truth)
MIN_CLUSTER_SIZE = 4             # "big" clusters only (known sizes 10/8/7/4)
MAX_POSITIVES = 50
MAX_HARD_NEGATIVES = 30
MAX_RANDOM_NEGATIVES = 20

# MOCK_LLM lexical-stub thresholds (deterministic, symmetric; NOT a model).
MOCK_EQUIV_JACCARD = 0.6
MOCK_DELTA_JACCARD = 0.25


JUDGE_SYSTEM_PROMPT = (
    "You are the IDEA_JUDGE worker in the a_bgt_rsi research apparatus.\n"
    "\n"
    "Given two research-claim texts A and B, judge whether they state the\n"
    "SAME idea. Verdicts:\n"
    '  "equivalent"       — same problem, same mechanism, same predicted\n'
    "    effect; wording differences only.\n"
    '  "better_with_delta" — the same core idea, but B adds a concrete,\n'
    "    articulable improvement over A (sharper mechanism, stronger or more\n"
    "    falsifiable prediction, broader scope). State the delta.\n"
    '  "distinct"         — different problem, mechanism, or predicted\n'
    "    effect. Surface-level topical overlap is NOT equivalence.\n"
    "\n"
    "Calibration rules:\n"
    "  - Shared jargon or a shared game/setting alone does NOT make two\n"
    "    claims equivalent — the mechanism and predicted effect must match.\n"
    "  - A restatement with trivial rewording is equivalent, not better.\n"
    '  - When honestly unsure, prefer "distinct" with low confidence over a\n'
    "    fabricated equivalence.\n"
    "\n"
    "Output STRICT JSON, nothing else — no prose, no markdown fences.\n"
    "Schema:\n"
    "{\n"
    '  "verdict": "equivalent" | "better_with_delta" | "distinct",\n'
    '  "delta": "<the concrete improvement for better_with_delta; else \'\'>",\n'
    '  "confidence": <float 0.0-1.0>\n'
    "}"
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _jaccard(a_tokens: set[str], b_tokens: set[str]) -> float:
    """Symmetric token Jaccard. Empty union -> 0.0."""
    if not a_tokens or not b_tokens:
        return 0.0
    return len(a_tokens & b_tokens) / len(a_tokens | b_tokens)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Balanced-brace JSON extractor (same pattern as novelty_classify.py —
    kept local so the worker stays self-contained)."""
    if not isinstance(text, str):
        return None
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _mock_judge(claim_a: str, claim_b: str) -> dict[str, Any]:
    """Deterministic lexical-overlap stub for MOCK_LLM — symmetric in its
    verdict, clearly labeled, NEVER a fabricated model judgment."""
    jac = _jaccard(_tokenize(claim_a), _tokenize(claim_b))
    if jac >= MOCK_EQUIV_JACCARD:
        verdict, conf = "equivalent", jac
    elif jac >= MOCK_DELTA_JACCARD:
        verdict, conf = "better_with_delta", jac
    else:
        verdict, conf = "distinct", 1.0 - jac
    return {
        "verdict": verdict,
        "delta": f"(MOCK_LLM lexical stub; token jaccard={jac:.3f} — not a model verdict)",
        "confidence": round(conf, 4),
    }


def judge_pair(
    claim_a: str,
    claim_b: str,
    *,
    temperature: float = 0.2,
    model: str | None = None,
    log_path: str | None = None,
    parent_request_id: str | None = None,
) -> dict[str, Any]:
    """Judge whether two claim texts state the same idea.

    Returns {"verdict": "equivalent"|"better_with_delta"|"distinct",
             "delta": str, "confidence": float}.

    RAISES ValueError on empty input or on unparseable/invalid model output —
    a verdict is never fabricated from a failed call (rule 4/7).
    MOCK_LLM -> deterministic lexical stub.
    """
    for name, val in (("claim_a", claim_a), ("claim_b", claim_b)):
        if not isinstance(val, str) or not val.strip():
            raise ValueError(f"idea_judge.judge_pair: {name} must be a non-empty string")

    if os.environ.get("MOCK_LLM"):
        return _mock_judge(claim_a, claim_b)

    user_content = f"Claim A:\n{claim_a.strip()}\n\nClaim B:\n{claim_b.strip()}"
    record = call_sync(
        [
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=temperature,
        top_p=0.95,
        max_tokens=384,
        caller_tag="idea_judge",
        parent_request_id=parent_request_id,
        log_path=log_path or CALLS_LOG_PATH,
        model=model,
    )
    completion = record.get("completion") or ""
    payload = _extract_json_object(completion)
    if not isinstance(payload, dict):
        raise ValueError(
            f"idea_judge: unparseable model output (no JSON object): {completion[:300]!r}"
        )
    verdict = payload.get("verdict")
    if verdict not in VERDICTS:
        raise ValueError(f"idea_judge: verdict {verdict!r} not in {VERDICTS}")
    delta = payload.get("delta", "")
    if delta is None:
        delta = ""
    if not isinstance(delta, str):
        raise ValueError(f"idea_judge: delta must be a string, got {type(delta).__name__}")
    confidence = payload.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) \
            or not (0.0 <= float(confidence) <= 1.0):
        raise ValueError(f"idea_judge: confidence {confidence!r} not a float in [0,1]")
    return {"verdict": verdict, "delta": delta.strip(), "confidence": float(confidence)}


# ── Pre-registered bar checks ────────────────────────────────────────────────

_CHECK_SPECS = (
    # (metric key, threshold, direction)  direction ">=" means pass when value >= threshold
    ("equiv_precision", EQUIV_PRECISION_MIN, ">="),
    ("equiv_recall", EQUIV_RECALL_MIN, ">="),
    ("false_equiv_rate", FALSE_EQUIV_MAX, "<="),
    ("symmetry_disagree_rate", SYMMETRY_DISAGREE_MAX, "<="),
    ("verdict_flip_rate", VERDICT_FLIP_MAX, "<="),
)


def passes(metrics: dict) -> dict[str, Any]:
    """Check each pre-registered bar INDEPENDENTLY (rule 4 — never coerced).
    A missing or non-numeric metric FAILS its check: missing signal never
    passes. Returns {"checks": {name: {value, threshold, direction, pass}},
    "all_pass": bool}."""
    checks: dict[str, dict[str, Any]] = {}
    metrics = metrics if isinstance(metrics, dict) else {}
    for key, threshold, direction in _CHECK_SPECS:
        value = metrics.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            ok = (value >= threshold) if direction == ">=" else (value <= threshold)
        else:
            ok = False  # missing/None/non-numeric — never a pass
        checks[key] = {
            "value": value if isinstance(value, (int, float)) and not isinstance(value, bool) else None,
            "threshold": threshold,
            "direction": direction,
            "pass": bool(ok),
        }
    return {"checks": checks, "all_pass": all(c["pass"] for c in checks.values())}


def judge_active(results: dict) -> bool:
    """True ONLY when a calibration results dict clears every pre-registered
    bar. Recomputes from results["metrics"] — a stored all_pass flag is never
    trusted. Anything malformed or below any bar -> False (refuse activation;
    prefilter-only stands)."""
    if not isinstance(results, dict):
        return False
    return passes(results.get("metrics") or {})["all_pass"]


# ── Calibration-set construction ─────────────────────────────────────────────

def _load_claim_texts(loop_memory_path: str | Path) -> list[str]:
    """Distinct hypothesis texts (fallback: seed.topic) from loop_memory.
    RAISES FileNotFoundError when the file is missing (rule 7 — an absent
    corpus is not a silent empty calibration set)."""
    p = Path(loop_memory_path)
    if not p.exists():
        raise FileNotFoundError(
            f"idea_judge: loop_memory missing at {p} — cannot build a "
            f"calibration set from an absent corpus (rule 7)."
        )
    texts: list[str] = []
    seen: set[str] = set()
    for row in _read_jsonl(p):
        hyp = row.get("hypothesis")
        text = hyp.get("text") if isinstance(hyp, dict) else None
        if not (isinstance(text, str) and text.strip()):
            seed = row.get("seed") if isinstance(row.get("seed"), dict) else {}
            text = seed.get("topic") if isinstance(seed.get("topic"), str) else None
        if not (isinstance(text, str) and text.strip()):
            continue
        t = text.strip()
        if t in seen:
            continue
        seen.add(t)
        texts.append(t)
    return texts


def _lexical_clusters(texts: list[str]) -> list[list[int]]:
    """Union-find clusters over pairwise token-jaccard >= GROUND_TRUTH_JACCARD.
    Returns index clusters (singletons included), largest first."""
    tokens = [_tokenize(t) for t in texts]
    parent = list(range(len(texts)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            if _jaccard(tokens[i], tokens[j]) >= GROUND_TRUTH_JACCARD:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[rj] = ri
    groups: dict[int, list[int]] = {}
    for i in range(len(texts)):
        groups.setdefault(find(i), []).append(i)
    return sorted(groups.values(), key=len, reverse=True)


def build_calibration_pairs(
    loop_memory_path: str | Path,
    *,
    seed: int = 0,
) -> dict[str, list[dict[str, str]]]:
    """Labeled pairs vs lexical ground truth:
      positives        — intra-cluster pairs of the big (>= MIN_CLUSTER_SIZE)
                         lexical clusters, capped at MAX_POSITIVES;
      hard_negatives   — top cross-cluster pairs by embedding cosine, capped
                         at MAX_HARD_NEGATIVES;
      random_negatives — seeded-random remaining cross-cluster pairs, capped
                         at MAX_RANDOM_NEGATIVES.
    Each pair: {"a": str, "b": str, "label": "equivalent"|"not_equivalent"}."""
    texts = _load_claim_texts(loop_memory_path)
    clusters = _lexical_clusters(texts)
    cluster_of = {i: ci for ci, members in enumerate(clusters) for i in members}

    positives: list[dict[str, str]] = []
    for members in clusters:
        if len(members) < MIN_CLUSTER_SIZE:
            continue
        for x in range(len(members)):
            for y in range(x + 1, len(members)):
                positives.append({
                    "a": texts[members[x]], "b": texts[members[y]],
                    "label": "equivalent",
                })
    positives = positives[:MAX_POSITIVES]

    vectors = _embed_texts(texts)
    cross: list[tuple[float, int, int]] = []
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            if cluster_of[i] == cluster_of[j]:
                continue
            cross.append((_cosine(vectors[i], vectors[j]), i, j))
    cross.sort(key=lambda t: t[0], reverse=True)

    hard = [{"a": texts[i], "b": texts[j], "label": "not_equivalent"}
            for _, i, j in cross[:MAX_HARD_NEGATIVES]]
    rest = cross[MAX_HARD_NEGATIVES:]
    rng = random.Random(seed)
    picked = rng.sample(rest, min(MAX_RANDOM_NEGATIVES, len(rest)))
    rand = [{"a": texts[i], "b": texts[j], "label": "not_equivalent"}
            for _, i, j in picked]
    return {"positives": positives, "hard_negatives": hard, "random_negatives": rand}


# ── Calibration run + scoring ────────────────────────────────────────────────

def _score_calls(pair_calls: list[dict]) -> dict[str, Any]:
    """Score judged calls vs lexical ground truth. Each entry:
    {"label", "temp", "order", "verdict" (str|None — None = parse failure)}.
    A None verdict counts as NOT-equivalent (a recall miss on positives) and
    as instability for symmetry/flip — failures count against the judge,
    never hidden. Undefined rates -> None (which passes() then fails)."""
    tp = fn = fp = neg_calls = 0
    for c in pair_calls:
        if c["label"] == "equivalent":
            if c["verdict"] == "equivalent":
                tp += 1
            else:
                fn += 1
        else:
            neg_calls += 1
            if c["verdict"] == "equivalent":
                fp += 1

    by_key: dict[tuple, dict[str, Any]] = {}
    for c in pair_calls:
        by_key[(c["pair_id"], c["temp"], c["order"])] = c["verdict"]

    pair_ids = sorted({c["pair_id"] for c in pair_calls})
    temps = sorted({c["temp"] for c in pair_calls})
    sym_total = sym_disagree = 0
    for pid in pair_ids:
        for t in temps:
            va = by_key.get((pid, t, "ab"))
            vb = by_key.get((pid, t, "ba"))
            sym_total += 1
            if va is None or vb is None or va != vb:
                sym_disagree += 1
    flip_total = flip = 0
    if len(temps) >= 2:
        t0, t1 = temps[0], temps[1]
        for pid in pair_ids:
            for order in ("ab", "ba"):
                v0 = by_key.get((pid, t0, order))
                v1 = by_key.get((pid, t1, order))
                flip_total += 1
                if v0 is None or v1 is None or v0 != v1:
                    flip += 1

    def _rate(num: int, den: int) -> float | None:
        return round(num / den, 4) if den else None

    return {
        "equiv_precision": _rate(tp, tp + fp),
        "equiv_recall": _rate(tp, tp + fn),
        "false_equiv_rate": _rate(fp, neg_calls),
        "symmetry_disagree_rate": _rate(sym_disagree, sym_total),
        "verdict_flip_rate": _rate(flip, flip_total),
    }


def calibrate(
    loop_memory_path: str | Path | None = None,
    *,
    results_path: str | Path | None = None,
    dry_run: bool = False,
    seed: int = 0,
    temps: tuple[float, ...] = CALIBRATION_TEMPS,
    judge_fn: Callable[..., dict] | None = None,
) -> dict[str, Any]:
    """Build labeled pairs, run the judge both orders x each temp, score vs
    lexical ground truth, and (unless dry_run) write results_path + append a
    run-log row. Returns the results dict either way. judge_fn is a test seam
    (defaults to judge_pair); a judge call that RAISES ValueError is recorded
    as a parse failure (verdict None) and scored against the judge."""
    t0 = time.perf_counter()
    loop_memory_path = loop_memory_path or DEFAULT_LOOP_MEMORY
    results_path = Path(results_path) if results_path is not None else DEFAULT_RESULTS_PATH
    judge = judge_fn or judge_pair

    pairs = build_calibration_pairs(loop_memory_path, seed=seed)
    labeled = (
        [(p, "positives") for p in pairs["positives"]]
        + [(p, "hard_negatives") for p in pairs["hard_negatives"]]
        + [(p, "random_negatives") for p in pairs["random_negatives"]]
    )

    pair_calls: list[dict[str, Any]] = []
    parse_failures = 0
    for pid, (pair, _bucket) in enumerate(labeled):
        for temp in temps:
            for order, (a, b) in (("ab", (pair["a"], pair["b"])),
                                  ("ba", (pair["b"], pair["a"]))):
                try:
                    verdict = judge(a, b, temperature=temp)["verdict"]
                except ValueError:
                    verdict = None
                    parse_failures += 1
                pair_calls.append({
                    "pair_id": pid, "label": pair["label"],
                    "temp": temp, "order": order, "verdict": verdict,
                })

    metrics = _score_calls(pair_calls)
    check = passes(metrics)
    results = {
        "generated_at": _utcnow(),
        "loop_memory_path": str(loop_memory_path),
        "mock_llm": bool(os.environ.get("MOCK_LLM")),
        "temps": list(temps),
        "seed": seed,
        "counts": {
            "positives": len(pairs["positives"]),
            "hard_negatives": len(pairs["hard_negatives"]),
            "random_negatives": len(pairs["random_negatives"]),
            "calls": len(pair_calls),
            "parse_failures": parse_failures,
        },
        "metrics": metrics,
        "checks": check["checks"],
        "all_pass": check["all_pass"],
    }
    if dry_run:
        return results
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")
    runtime.append_run_log({
        "task_id": "idea_judge_calibrate",
        "status": "passed",
        "observable_actual": (
            f"calls={len(pair_calls)} parse_failures={parse_failures} "
            f"all_pass={check['all_pass']} metrics={metrics}"
        ),
        "observable_expected": (
            f"precision>={EQUIV_PRECISION_MIN} recall>={EQUIV_RECALL_MIN} "
            f"false_equiv<={FALSE_EQUIV_MAX} symmetry<={SYMMETRY_DISAGREE_MAX} "
            f"flip<={VERDICT_FLIP_MAX}"
        ),
        "duration_ms": round((time.perf_counter() - t0) * 1000.0, 3),
    })
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="workers.idea_judge",
        description="Idea-equivalence judge calibration CLI.",
    )
    parser.add_argument("--calibrate", action="store_true",
                        help="build labeled pairs, judge, score, write results.json")
    parser.add_argument("--dry-run", action="store_true",
                        help="print results only; write nothing")
    parser.add_argument("--loop-memory", default=None,
                        help=f"loop_memory path (default {DEFAULT_LOOP_MEMORY})")
    parser.add_argument("--results", default=None,
                        help=f"results path (default {DEFAULT_RESULTS_PATH})")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    if not args.calibrate:
        parser.error("--calibrate is required (this CLI only calibrates)")
    results = calibrate(
        args.loop_memory,
        results_path=args.results,
        dry_run=args.dry_run,
        seed=args.seed,
    )
    print(json.dumps(results, indent=2, ensure_ascii=False))
    if not args.dry_run:
        print(f"\nwrote {args.results or DEFAULT_RESULTS_PATH}")
    print(f"judge_active: {judge_active(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
