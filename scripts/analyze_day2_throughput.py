#!/usr/bin/env python3
"""
Investigation: why did day2_block2_50call_sweep check #3 fail (29.75 tok/s)?

Question under test: is 29.75 tok/s a genuine throughput ceiling, or an
artifact of measuring decode speed on calls dominated by fixed per-call
overhead (prefill + network) -- i.e. the many tiny-completion prompts?

Method: latency_ms = overhead + output_tokens / decode_rate. A linear fit
of latency_ms against output_tokens separates the fixed per-call overhead
(intercept) from the marginal cost per decoded token (slope) -- giving a
decode rate that does NOT depend on how long each completion happened to be.

Run: .venv/bin/python scripts/analyze_day2_throughput.py
"""
import json
from collections import defaultdict
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "logs" / "day2.jsonl"
recs = [json.loads(l) for l in LOG.read_text().splitlines() if l.strip()]


def tps(out_tokens, latency_ms):
    return out_tokens / (latency_ms / 1000.0) if latency_ms else 0.0


# --- Aggregate, as the plan's check #3 computes it -------------------------
tot_out = sum(r["usage"]["output_tokens"] for r in recs)
tot_lat = sum(r["latency_ms"] for r in recs) / 1000.0
print(f"records              : {len(recs)}")
print(f"plan check #3 aggregate: {tot_out / tot_lat:.2f} tok/s  (floor 40)\n")

# --- tok/s bucketed by completion length -----------------------------------
buckets = [(1, 5), (6, 20), (21, 100), (101, 256)]
print(f"{'output_tokens':>14} | {'calls':>5} | {'mean tok/s':>10} | {'mean out':>8}")
for lo, hi in buckets:
    grp = [r for r in recs if lo <= r["usage"]["output_tokens"] <= hi]
    if not grp:
        continue
    mean_tps = sum(tps(r["usage"]["output_tokens"], r["latency_ms"]) for r in grp) / len(grp)
    mean_out = sum(r["usage"]["output_tokens"] for r in grp) / len(grp)
    print(f"{lo:>6}-{hi:<7} | {len(grp):>5} | {mean_tps:>10.2f} | {mean_out:>8.1f}")

# --- per-temperature and per-category --------------------------------------
def grouped(keyfn, label):
    g = defaultdict(list)
    for r in recs:
        g[keyfn(r)].append(r)
    print(f"\n{label:>14} | {'calls':>5} | {'agg tok/s':>9}")
    for k in sorted(g):
        grp = g[k]
        o = sum(r["usage"]["output_tokens"] for r in grp)
        s = sum(r["latency_ms"] for r in grp) / 1000.0
        print(f"{str(k):>14} | {len(grp):>5} | {o / s:>9.2f}")

grouped(lambda r: r["temperature"], "temperature")
grouped(lambda r: r["caller_tag"].split("/")[-1], "category")

# --- linear fit: latency_ms = a + b * output_tokens ------------------------
xs = [r["usage"]["output_tokens"] for r in recs]
ys = [r["latency_ms"] for r in recs]
n = len(xs)
sx, sy = sum(xs), sum(ys)
sxx = sum(x * x for x in xs)
sxy = sum(x * y for x, y in zip(xs, ys))
b = (n * sxy - sx * sy) / (n * sxx - sx * sx)   # ms per decoded token
a = (sy - b * sx) / n                            # fixed per-call overhead, ms
print(f"\n--- linear fit  latency_ms = {a:.1f} + {b:.2f} * output_tokens ---")
print(f"fixed per-call overhead : {a:.0f} ms   (prefill + network + first token)")
print(f"marginal decode cost    : {b:.2f} ms/token")
print(f"DECODE-ONLY throughput  : {1000.0 / b:.2f} tok/s   (overhead removed)")

longest = max(recs, key=lambda r: r["usage"]["output_tokens"])
print(f"\nlongest completion: {longest['usage']['output_tokens']} tokens "
      f"-> {tps(longest['usage']['output_tokens'], longest['latency_ms']):.2f} tok/s")
