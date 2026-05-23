#!/usr/bin/env python3
"""Day-7 experiment runner — first synthetic-tier experiment.

Plays N rounds of repeated PD between the LLM player and each named
opponent, sequentially, through the Day-6 orchestrator (its first
real use; --via-orchestrator). Records per-round actions, payoffs,
and parse-failure events. Writes a summary + a per-round JSONL +
a cooperation-rate CSV for downstream analysis (quicklook).

Plan: 100 rounds × 5 opponents = 500 rounds total.
"""

import argparse
import csv
import json
import os
import sys
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from orchestrator.openclaw_runner import OrchestratorClient  # noqa: E402

KNOWN_OPPONENTS = ("tft", "grim_trigger", "all_c", "all_d", "mirror_llm")


def _build_task(*, opponent: str, n_rounds: int, temperature: float,
                rules_variant: str, task_id_prefix: str) -> dict:
    return {
        "task_id": f"{task_id_prefix}-{opponent}",
        "task_type": "play_pd_match",
        "payload": {
            "opponent": opponent,
            "n_rounds": n_rounds,
            "temperature": temperature,
            "rules_variant": rules_variant,
            "task_id": f"{task_id_prefix}-{opponent}",
        },
        "parent_request_id": None,
    }


def _write_per_round_jsonl(results, path):
    with open(path, "w") as f:
        for opp_result in results:
            opponent = opp_result["opponent"]
            for rec in opp_result["rounds"]:
                f.write(json.dumps({"opponent": opponent, **rec}) + "\n")


def _write_cooperation_csv(results, path):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "opponent", "n_rounds", "llm_coop_rate", "opp_coop_rate",
            "llm_mean_payoff", "opp_mean_payoff",
            "first_d_round_llm", "first_d_round_opp",
            "llm_parse_failures", "llm_default_d_plays",
        ])
        for r in results:
            w.writerow([
                r["opponent"], r["n_rounds"],
                f"{r['llm_coop_rate']:.4f}", f"{r['opp_coop_rate']:.4f}",
                f"{r['llm_mean_payoff']:.4f}", f"{r['opp_mean_payoff']:.4f}",
                r.get("first_d_round_llm"), r.get("first_d_round_opp"),
                r["llm_parse_failures"], r["llm_default_d_plays"],
            ])


def _print_progress(opponent, idx, total, status, elapsed_s, result):
    if status != "passed":
        print(f"  [{idx}/{total}] {opponent}: status={status}; aborting.")
        return
    print(
        f"  [{idx}/{total}] {opponent}: passed in {elapsed_s:.1f}s; "
        f"llm_coop={result['llm_coop_rate']:.3f}; "
        f"opp_coop={result['opp_coop_rate']:.3f}; "
        f"llm_payoff={result['llm_mean_payoff']:.2f}; "
        f"parse_fail={result['llm_parse_failures']}; "
        f"default_d={result['llm_default_d_plays']}"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--opponents", default=",".join(KNOWN_OPPONENTS))
    ap.add_argument("--rounds", type=int, default=100)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--jsonl-log", required=True)
    ap.add_argument("--via-orchestrator", action="store_true")
    ap.add_argument("--worker-timeout-s", type=int, default=600)
    ap.add_argument("--temperature", type=float, default=0.0,
                    help="LLM sampling temperature (default 0.0 = greedy decoding)")
    ap.add_argument("--rules-variant", default="baseline",
                    help="LLM rules prompt variant: baseline (default) or one of the "
                         "named diagnostic variants in llm_agent.RULES_VARIANTS")
    ap.add_argument("--task-id-prefix", default="exp001",
                    help="prefix for orchestrator task IDs (use exp001_7_1 for the Day-7.1 slip rerun)")
    args = ap.parse_args()

    opponents = [o.strip() for o in args.opponents.split(",") if o.strip()]
    unknown = [o for o in opponents if o not in KNOWN_OPPONENTS]
    if unknown:
        print(f"unknown opponent(s): {unknown}; known: {KNOWN_OPPONENTS}",
              file=sys.stderr)
        return 2

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    Path(args.jsonl_log).parent.mkdir(parents=True, exist_ok=True)

    orch = OrchestratorClient(
        worker_timeout_s=args.worker_timeout_s,
        wrapper_log_path=args.jsonl_log,
    ) if args.via_orchestrator else None

    print(f"exp001: {len(opponents)} opponents x {args.rounds} rounds "
          f"= {len(opponents) * args.rounds} rounds total; "
          f"via_orchestrator={args.via_orchestrator}")
    print(f"  output_dir = {out_dir}")
    print(f"  jsonl_log  = {args.jsonl_log}")

    t_start = time.perf_counter()
    results = []
    for i, opp in enumerate(opponents, start=1):
        task = _build_task(opponent=opp, n_rounds=args.rounds,
                           temperature=args.temperature,
                           rules_variant=args.rules_variant,
                           task_id_prefix=args.task_id_prefix)
        t0 = time.perf_counter()
        if orch is not None:
            out = orch.run_task(task)
        else:
            from workers.play_pd_match import play_match
            out = play_match(
                payload=task["payload"],
                log_path=args.jsonl_log,
                parent_request_id=str(uuid.uuid4()),
            )
        elapsed = time.perf_counter() - t0
        status = out.get("status")
        result = out.get("result") or {}
        _print_progress(opp, i, len(opponents), status, elapsed, result if status == "passed" else {})
        if status != "passed":
            print(f"errors: {out.get('errors')}", file=sys.stderr)
            return 3
        result["wall_clock_s"] = elapsed
        results.append(result)

    total_elapsed = time.perf_counter() - t_start
    summary = {
        "n_opponents": len(opponents),
        "rounds_per_opponent": args.rounds,
        "total_rounds": len(opponents) * args.rounds,
        "via_orchestrator": args.via_orchestrator,
        "temperature": args.temperature,
        "rules_variant": args.rules_variant,
        "task_id_prefix": args.task_id_prefix,
        "total_wall_clock_s": total_elapsed,
        "per_opponent": [
            {k: v for k, v in r.items() if k != "rounds"} for r in results
        ],
    }

    summary_path = out_dir / "summary.json"
    per_round_path = out_dir / "per_round.jsonl"
    coop_csv_path = out_dir / "cooperation_rates.csv"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    _write_per_round_jsonl(results, per_round_path)
    _write_cooperation_csv(results, coop_csv_path)

    print(
        f"\nexp001 complete: {summary['total_rounds']} rounds in "
        f"{total_elapsed:.1f}s; wrote {summary_path}, "
        f"{per_round_path}, {coop_csv_path}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
