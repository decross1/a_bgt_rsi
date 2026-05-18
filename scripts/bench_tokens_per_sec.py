#!/usr/bin/env python3
"""day1_block2_bench — single-stream decode benchmark for the vLLM endpoint.

Measures the TRUE decode rate, not end-to-end throughput. The earlier
version divided completion_tokens by the whole HTTP wall time (queue +
prefill + network + decode) and labelled the result "decode tok/s" — it
was actually end-to-end throughput. See notes/day1-bench-debug.md
(Finding 1).

This version:
  - streams the response and timestamps the first and last token;
    decode tok/s = (completion_tokens - 1) / (t_last - t_first)
  - reports TTFT (time to first token) separately
  - runs one warmup request and discards it
  - pins ignore_eos so every sample is exactly --max-tokens long
  - reports median + min/max/stddev across prompts
  - cross-checks the client measurement against the server's own
    /metrics histograms (inter_token_latency, time_to_first_token)

Modes:
  (default)        single-stream decode sweep at one prompt/output size
  --sweep-context  decode rate vs prompt length (E2): 256, 4k, 16k, 64k

Stdlib only — no extra dependencies.

Usage:
  python3 scripts/bench_tokens_per_sec.py \
    --endpoint http://localhost:8000/v1 --model gemma-4-26b-a4b \
    --num-prompts 5 --max-tokens 256 --output bench/day1.csv

  python3 scripts/bench_tokens_per_sec.py \
    --endpoint http://localhost:8000/v1 --model gemma-4-26b-a4b \
    --sweep-context --max-tokens 256
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

# Filler used to pad a prompt toward a target token length (E2 sweep).
# The actual prompt length is always measured server-side and reported,
# never assumed from this estimate.
FILLER = ("Game theory studies strategic interaction among rational agents. "
          "The passage below is background context for the question. ")

# Histogram series scraped from /metrics for the server-side cross-check.
_METRIC_KEYS = (
    "vllm:inter_token_latency_seconds_sum",
    "vllm:inter_token_latency_seconds_count",
    "vllm:time_to_first_token_seconds_sum",
    "vllm:time_to_first_token_seconds_count",
)


def bench_one(endpoint, model, prompt, max_tokens):
    """Stream one completion; return a dict of timing measurements.

    decode_tps is the inter-token rate: the first token carries prefill
    cost (TTFT) and is excluded, so the rate is over completion_tokens-1
    tokens generated between t_first and t_last.
    """
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "min_tokens": max_tokens,   # vLLM extension: floor on output length
        "ignore_eos": True,         # vLLM extension: every sample == max_tokens
        "temperature": 0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }).encode()
    req = urllib.request.Request(
        endpoint.rstrip("/") + "/chat/completions",
        data=body, headers={"Content-Type": "application/json"})

    t0 = time.monotonic()
    t_first = t_last = None
    chunks = 0
    prompt_tokens = completion_tokens = None
    with urllib.request.urlopen(req, timeout=600) as r:
        for raw in r:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            obj = json.loads(payload)
            usage = obj.get("usage")
            if usage:
                prompt_tokens = usage.get("prompt_tokens")
                completion_tokens = usage.get("completion_tokens")
            for ch in obj.get("choices", []):
                if ch.get("delta", {}).get("content"):
                    now = time.monotonic()
                    if t_first is None:
                        t_first = now
                    t_last = now
                    chunks += 1
    t_end = time.monotonic()

    ct = completion_tokens if completion_tokens else chunks
    decode_s = (t_last - t_first) if (t_first and t_last) else 0.0
    decode_tps = ((ct - 1) / decode_s) if (decode_s > 0 and ct > 1) else 0.0
    ttft = (t_first - t0) if t_first else 0.0
    e2e_s = t_end - t0
    return {
        "prompt_tokens": prompt_tokens or 0,
        "completion_tokens": ct,
        "ttft_s": ttft,
        "decode_s": decode_s,
        "decode_tps": decode_tps,
        "e2e_tps": (ct / e2e_s) if e2e_s > 0 else 0.0,
    }


def scrape_metrics(metrics_url):
    """Return {series: float} for the histogram sum/count series we use."""
    out = {}
    try:
        with urllib.request.urlopen(metrics_url, timeout=10) as r:
            for raw in r:
                line = raw.decode("utf-8").strip()
                if not line or line.startswith("#"):
                    continue
                name, _, val = line.partition(" ")
                base = name.split("{", 1)[0]
                if base in _METRIC_KEYS:
                    out[base] = out.get(base, 0.0) + float(val)
    except Exception as e:                       # noqa: BLE001 - best-effort
        print(f"  (/metrics cross-check unavailable: {e})")
    return out


def crosscheck(before, after):
    """Server-side decode tok/s and TTFT from the /metrics delta over the run."""
    def d(k):
        return after.get(k, 0.0) - before.get(k, 0.0)
    itl_sum, itl_cnt = d(_METRIC_KEYS[0]), d(_METRIC_KEYS[1])
    ttft_sum, ttft_cnt = d(_METRIC_KEYS[2]), d(_METRIC_KEYS[3])
    decode_tps = (itl_cnt / itl_sum) if itl_sum > 0 else 0.0
    ttft = (ttft_sum / ttft_cnt) if ttft_cnt > 0 else 0.0
    return decode_tps, ttft


def _summary(values):
    """median / min / max / stddev for a list of floats."""
    if not values:
        return 0.0, 0.0, 0.0, 0.0
    sd = statistics.stdev(values) if len(values) > 1 else 0.0
    return statistics.median(values), min(values), max(values), sd


def padded_prompt(target_tokens, salt):
    """Build a prompt that approximates target_tokens (actual length is
    measured server-side, never trusted from this estimate)."""
    reps = max(1, target_tokens // 28)           # ~28 tok per FILLER repeat
    return (f"[ctx {salt}] {FILLER * reps}\n\nUsing the passage above, "
            "explain in detail why cooperation can be stable in repeated games.")


def run_prompts(args, prompts, warmup_tokens):
    """One warmup (discarded) + the measured prompts. Returns (rows, xcheck)."""
    print(f"  warmup ...", flush=True)
    bench_one(args.endpoint, args.model, prompts[0], warmup_tokens)
    before = scrape_metrics(args.metrics_url)
    rows = []
    for i, prompt in enumerate(prompts):
        m = bench_one(args.endpoint, args.model, prompt, args.max_tokens)
        print(f"  prompt {i}: prompt_tok={m['prompt_tokens']} "
              f"completion_tok={m['completion_tokens']}  "
              f"ttft={m['ttft_s']:.3f}s  decode={m['decode_tps']:.2f} tok/s  "
              f"(e2e {m['e2e_tps']:.2f})")
        rows.append(m)
    return rows, crosscheck(before, scrape_metrics(args.metrics_url))


def mode_single(args):
    prompts = [PROMPTS[i % len(PROMPTS)] for i in range(args.num_prompts)]
    print(f"=== decode benchmark (single-stream) — {len(prompts)} prompts, "
          f"max_tokens={args.max_tokens} ===")
    rows, (srv_tps, srv_ttft) = run_prompts(args, prompts,
                                            min(args.max_tokens, 64))
    with open(args.output, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["prompt_idx", "prompt_tokens", "completion_tokens",
                    "ttft_s", "decode_tok_per_s", "e2e_tok_per_s"])
        for i, m in enumerate(rows):
            w.writerow([i, m["prompt_tokens"], m["completion_tokens"],
                        round(m["ttft_s"], 4), round(m["decode_tps"], 2),
                        round(m["e2e_tps"], 2)])

    med, lo, hi, sd = _summary([m["decode_tps"] for m in rows])
    ttft_med, *_ = _summary([m["ttft_s"] for m in rows])
    e2e_med, *_ = _summary([m["e2e_tps"] for m in rows])
    print(f"\nmedian decode tok/s : {med:.2f}   (true inter-token rate)")
    print(f"  min / max         : {lo:.2f} / {hi:.2f}    stddev: {sd:.3f}")
    print(f"median TTFT         : {ttft_med:.3f} s")
    print(f"median end-to-end   : {e2e_med:.2f} tok/s   "
          f"(incl. prefill+TTFT — NOT the decode rate)")
    if srv_tps:
        print(f"server /metrics     : decode {srv_tps:.2f} tok/s, "
              f"TTFT {srv_ttft:.3f} s   (independent cross-check)")
    print(f"written to {args.output}  (n={len(rows)})")


def mode_sweep(args):
    lengths = args.sweep_lengths
    print(f"=== decode-rate vs context-length sweep — lengths {lengths}, "
          f"max_tokens={args.max_tokens} ===")
    with open(args.output, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["target_prompt_tokens", "actual_prompt_tokens",
                    "completion_tokens", "ttft_s", "decode_tok_per_s"])
        for L in lengths:
            print(f"-- target context {L} tokens --")
            prompts = [padded_prompt(L, f"{L}.{i}")
                       for i in range(args.num_prompts)]
            rows, _ = run_prompts(args, prompts, min(args.max_tokens, 64))
            med, lo, hi, sd = _summary([m["decode_tps"] for m in rows])
            act, *_ = _summary([float(m["prompt_tokens"]) for m in rows])
            ttft_med, *_ = _summary([m["ttft_s"] for m in rows])
            for m in rows:
                w.writerow([L, m["prompt_tokens"], m["completion_tokens"],
                            round(m["ttft_s"], 4), round(m["decode_tps"], 2)])
            print(f"   actual prompt_tok~{act:.0f}  decode median "
                  f"{med:.2f} tok/s (min/max {lo:.2f}/{hi:.2f}, sd {sd:.3f})  "
                  f"ttft {ttft_med:.3f}s")
    print(f"\nwritten to {args.output}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default="http://localhost:8000/v1")
    ap.add_argument("--metrics-url", default="http://localhost:8000/metrics")
    ap.add_argument("--model", required=True)
    ap.add_argument("--num-prompts", type=int, default=5)
    ap.add_argument("--max-tokens", type=int, default=256)
    ap.add_argument("--sweep-context", action="store_true",
                    help="run the decode-rate vs context-length sweep (E2)")
    ap.add_argument("--sweep-lengths", type=int, nargs="+",
                    default=[256, 4096, 16384, 65536],
                    help="prompt token lengths for --sweep-context")
    ap.add_argument("--output", default=None,
                    help="CSV path (default: bench/day1.csv, or "
                         "bench/context_sweep.csv in sweep mode)")
    args = ap.parse_args()
    if args.output is None:
        args.output = ("bench/context_sweep.csv" if args.sweep_context
                       else "bench/day1.csv")

    if args.sweep_context:
        mode_sweep(args)
    else:
        mode_single(args)


if __name__ == "__main__":
    main()
