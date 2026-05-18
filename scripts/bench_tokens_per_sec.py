#!/usr/bin/env python3
"""day1_block2_bench — single-stream tokens/sec micro-benchmark.

Hits an OpenAI-compatible vLLM endpoint with N prompts and records the
decode tokens/sec per prompt to a CSV (header + one row per prompt).
Stdlib only — no extra dependencies.

Usage:
  python3 scripts/bench_tokens_per_sec.py \
    --endpoint http://localhost:8000/v1 --model gemma-4-26b-a4b \
    --num-prompts 5 --max-tokens 256 --output bench/day1.csv
"""
import argparse
import csv
import json
import statistics
import time
import urllib.request

PROMPTS = [
    "Explain the prisoner's dilemma in three sentences.",
    "Write a Python function that returns the nth Fibonacci number.",
    "Summarize the difference between a Nash equilibrium and a Pareto optimum.",
    "List five classic problems studied in evolutionary game theory.",
    "Describe tit-for-tat and why it performs well in repeated games.",
]


def bench_one(endpoint, model, prompt, max_tokens):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
    }).encode()
    req = urllib.request.Request(
        endpoint.rstrip("/") + "/chat/completions",
        data=body, headers={"Content-Type": "application/json"})
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=180) as r:
        resp = json.load(r)
    elapsed = time.monotonic() - t0
    ct = resp["usage"]["completion_tokens"]
    return ct, elapsed, (ct / elapsed if elapsed > 0 else 0.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default="http://localhost:8000/v1")
    ap.add_argument("--model", required=True)
    ap.add_argument("--num-prompts", type=int, default=5)
    ap.add_argument("--max-tokens", type=int, default=256)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    rows = []
    for i in range(args.num_prompts):
        prompt = PROMPTS[i % len(PROMPTS)]
        ct, elapsed, tps = bench_one(args.endpoint, args.model, prompt,
                                     args.max_tokens)
        print(f"prompt {i}: {ct} tok in {elapsed:.2f}s -> {tps:.1f} tok/s")
        rows.append((i, ct, round(elapsed, 3), round(tps, 2)))

    with open(args.output, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["prompt_idx", "completion_tokens", "elapsed_s",
                    "decode_tok_per_s"])
        w.writerows(rows)

    median = statistics.median(r[3] for r in rows)
    print(f"\nmedian decode tok/s: {median:.2f}  "
          f"(n={len(rows)}, written to {args.output})")


if __name__ == "__main__":
    main()
