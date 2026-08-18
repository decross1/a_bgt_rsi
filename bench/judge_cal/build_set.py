"""bench/judge_cal/build_set.py — deterministic generator for the judge-calibration set v2.

Builds `bench/judge_cal/set_v2.jsonl` (LOOP_V1 P3 "Judge calibration"): labeled
claim pairs whose ground truth is the KNOWN restatement clusters —

  * lexical clusters over `memory/loop_memory.jsonl` claim texts (symmetric
    token-jaccard >= idea_judge.GROUND_TRUTH_JACCARD, union-find), and
  * the historical consolidation clusters recorded as events in
    `memory/idea_ledger.jsonl` (cluster_created / member_added co-membership),

union-found together into ground-truth components. Buckets:

  positives         — intra-component pairs (same-cluster members), biggest
                      clusters first, capped at TARGET_POSITIVES;
  hard_negatives    — top cross-component pairs by the SAME lexical-jaccard
                      prefilter layer `workers/idea_ledger.accept_candidate`
                      uses (mine_paper_gap._lexical_overlap, imported not
                      forked), symmetrized as max of both directions;
  random_negatives  — seeded-random remaining cross-component pairs.

Fully deterministic (SEED = 20260818): no LLM, no embeddings, no clock.
Rows carry {"a", "b", "label"} exactly as `workers.idea_judge.calibrate`
consumes them, plus provenance (bucket, cluster ids, scores); `load_set()`
regroups the file into the exact dict shape `build_calibration_pairs`
returns, so the CLI's labeled-pair loop can consume it directly.

Hygiene (counted, never silent): a "claim" whose first character is '{' or
'[' is a leaked structured payload (multi-candidate JSON blobs exist in the
historical corpus), not a natural-language claim — dropped from the universe.

Run:  .venv-chroma/bin/python bench/judge_cal/build_set.py
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from workers.idea_judge import GROUND_TRUTH_JACCARD, _jaccard  # noqa: E402
from workers.mine_paper_gap import _lexical_overlap, _read_jsonl  # noqa: E402
from workers.retrieval_relevance import _tokenize  # noqa: E402

SEED = 20260818  # pre-registered; the set is byte-reproducible from the corpora
TARGET_POSITIVES = 50
TARGET_HARD_NEGATIVES = 30
TARGET_RANDOM_NEGATIVES = 20

DEFAULT_LOOP_MEMORY = REPO_ROOT / "memory" / "loop_memory.jsonl"
DEFAULT_IDEA_LEDGER = REPO_ROOT / "memory" / "idea_ledger.jsonl"
DEFAULT_OUT = REPO_ROOT / "bench" / "judge_cal" / "set_v2.jsonl"

LEDGER_MEMBER_EVENTS = ("cluster_created", "member_added")
BUCKETS = ("positives", "hard_negatives", "random_negatives")


def load_claim_corpus(loop_memory_path: str | Path) -> tuple[list[str], dict[str, int], int]:
    """(texts, iteration_id -> text index, n_dropped_structured).

    Extraction mirrors workers.idea_judge._load_claim_texts (hypothesis.text,
    fallback seed.topic, first-occurrence dedup) — re-stated here only because
    that helper does not expose the iteration-id map the ledger edges need.
    RAISES FileNotFoundError on a missing corpus (an absent corpus is never a
    silent empty set — rule 7)."""
    p = Path(loop_memory_path)
    if not p.exists():
        raise FileNotFoundError(f"build_set: loop_memory missing at {p}")
    texts: list[str] = []
    idx_of_text: dict[str, int] = {}
    iter_to_idx: dict[str, int] = {}
    dropped = 0
    for row in _read_jsonl(p):
        hyp = row.get("hypothesis")
        text = hyp.get("text") if isinstance(hyp, dict) else None
        if not (isinstance(text, str) and text.strip()):
            seed = row.get("seed") if isinstance(row.get("seed"), dict) else {}
            text = seed.get("topic") if isinstance(seed.get("topic"), str) else None
        if not (isinstance(text, str) and text.strip()):
            continue
        text = text.strip()
        if text[0] in "{[":  # leaked structured payload, not a claim
            dropped += 1
            continue
        if text not in idx_of_text:
            idx_of_text[text] = len(texts)
            texts.append(text)
        it = row.get("iteration_id")
        if isinstance(it, str) and it and it not in iter_to_idx:
            iter_to_idx[it] = idx_of_text[text]
    return texts, iter_to_idx, dropped


def ground_truth_components(
    texts: list[str],
    iter_to_idx: dict[str, int],
    idea_ledger_path: str | Path,
) -> list[list[int]]:
    """Union-find components over two edge kinds:
      (a) symmetric token-jaccard >= GROUND_TRUTH_JACCARD (the idea_judge bar);
      (b) co-membership in an idea_ledger cluster (cluster_created/member_added).
    Returns components (singletons included), biggest first, members ascending."""
    lp = Path(idea_ledger_path)
    if not lp.exists():
        raise FileNotFoundError(f"build_set: idea_ledger missing at {lp}")

    parent = list(range(len(texts)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[max(ri, rj)] = min(ri, rj)

    tokens = [_tokenize(t) for t in texts]
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            if _jaccard(tokens[i], tokens[j]) >= GROUND_TRUTH_JACCARD:
                union(i, j)

    ledger_members: dict[str, list[int]] = {}
    for e in _read_jsonl(lp):
        if e.get("event_type") not in LEDGER_MEMBER_EVENTS:
            continue
        cid, mid = e.get("cluster_id"), e.get("member_id")
        if cid and isinstance(mid, str) and mid in iter_to_idx:
            ledger_members.setdefault(cid, []).append(iter_to_idx[mid])
    for members in ledger_members.values():
        for a, b in zip(members, members[1:]):
            union(a, b)

    groups: dict[int, list[int]] = {}
    for i in range(len(texts)):
        groups.setdefault(find(i), []).append(i)
    return sorted(groups.values(), key=lambda c: (-len(c), c[0]))


def build_rows(
    loop_memory_path: str | Path = DEFAULT_LOOP_MEMORY,
    idea_ledger_path: str | Path = DEFAULT_IDEA_LEDGER,
    *,
    seed: int = SEED,
) -> list[dict]:
    """The full labeled set, deterministic for fixed inputs + seed."""
    texts, iter_to_idx, _dropped = load_claim_corpus(loop_memory_path)
    comps = ground_truth_components(texts, iter_to_idx, idea_ledger_path)
    cluster_of = {i: ci for ci, members in enumerate(comps) for i in members}
    tokens = [_tokenize(t) for t in texts]

    def sym_overlap(i: int, j: int) -> float:
        # The idea_ledger/mine_paper_gap prefilter layer is directional
        # (candidate tokens found in reference); symmetrize with max.
        return max(_lexical_overlap(tokens[i], texts[j]),
                   _lexical_overlap(tokens[j], texts[i]))

    positives: list[tuple[int, int, int]] = []  # (component, i, j)
    for ci, members in enumerate(comps):  # comps are biggest-first
        if len(members) < 2:
            continue
        for x in range(len(members)):
            for y in range(x + 1, len(members)):
                positives.append((ci, members[x], members[y]))
    positives = positives[:TARGET_POSITIVES]

    cross: list[tuple[float, int, int]] = []
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            if cluster_of[i] == cluster_of[j]:
                continue
            cross.append((sym_overlap(i, j), i, j))
    cross.sort(key=lambda t: (-t[0], t[1], t[2]))
    hard = cross[:TARGET_HARD_NEGATIVES]
    rest = cross[TARGET_HARD_NEGATIVES:]
    rng = random.Random(seed)
    rand = sorted(rng.sample(rest, min(TARGET_RANDOM_NEGATIVES, len(rest))),
                  key=lambda t: (t[1], t[2]))

    rows: list[dict] = []

    def add(bucket: str, label: str, i: int, j: int, score: float) -> None:
        rows.append({
            "pair_id": f"v2-{len(rows):03d}",
            "bucket": bucket,
            "label": label,
            "a": texts[i],
            "b": texts[j],
            "cluster_a": f"gt-{cluster_of[i]:03d}",
            "cluster_b": f"gt-{cluster_of[j]:03d}",
            "jaccard": round(_jaccard(tokens[i], tokens[j]), 4),
            "prefilter_overlap": round(score, 4),
        })

    for _ci, i, j in positives:
        add("positives", "equivalent", i, j, sym_overlap(i, j))
    for score, i, j in hard:
        add("hard_negatives", "not_equivalent", i, j, score)
    for score, i, j in rand:
        add("random_negatives", "not_equivalent", i, j, score)
    return rows


def write_set(rows: list[dict], out_path: str | Path = DEFAULT_OUT) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )
    return out


def load_set(path: str | Path = DEFAULT_OUT) -> dict[str, list[dict[str, str]]]:
    """Regroup set_v2.jsonl into the EXACT shape
    workers.idea_judge.build_calibration_pairs returns —
    {"positives": [...], "hard_negatives": [...], "random_negatives": [...]},
    each item {"a", "b", "label"} — directly consumable by the calibrate()
    labeled-pair loop."""
    out: dict[str, list[dict[str, str]]] = {b: [] for b in BUCKETS}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        out[row["bucket"]].append(
            {"a": row["a"], "b": row["b"], "label": row["label"]})
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bench/judge_cal/build_set.py",
        description="Deterministic judge-calibration set v2 generator (seed 20260818).",
    )
    parser.add_argument("--loop-memory", default=str(DEFAULT_LOOP_MEMORY))
    parser.add_argument("--idea-ledger", default=str(DEFAULT_IDEA_LEDGER))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args(argv)

    texts, iter_to_idx, dropped = load_claim_corpus(args.loop_memory)
    comps = ground_truth_components(texts, iter_to_idx, args.idea_ledger)
    rows = build_rows(args.loop_memory, args.idea_ledger, seed=args.seed)
    out = write_set(rows, args.out)
    counts = {b: sum(1 for r in rows if r["bucket"] == b) for b in BUCKETS}
    print(json.dumps({
        "out": str(out),
        "seed": args.seed,
        "texts": len(texts),
        "dropped_structured": dropped,
        "component_sizes_ge2": [len(c) for c in comps if len(c) >= 2],
        "counts": counts,
        "total": len(rows),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
