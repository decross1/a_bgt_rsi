#!/usr/bin/env python3
"""
Day 4 task -- tool-call robustness sweep (plan.yaml day4_block2_robustness).

Re-runs the prisoner's-dilemma prompt N times at temperature=0.3 and reports
the tool-invocation rate: the fraction of runs in which the model called
get_payoff_matrix at least once rather than answering from parametric memory.
The rate is written to run_state/week1.state.json metric_log.day4_tool_call_invocation_rate.

A rate below 0.8 is a FINDING to characterize, not a bug to silently fix
(plan.yaml's robustness-as-first-class principle).

    .venv/bin/python tests/test_tool_call_robustness.py --n 5 --temperature 0.3 \
        --output logs/day4_robust.jsonl

Owned by Track A (Day 4).
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jsonschema import Draft202012Validator

from agent_wrapper.wrapper import call_with_tools, ToolCallError, verify_log_integrity  # noqa: E402
from tests.test_tool_call_e2e import PD_MESSAGES, TOOLS  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO / "schema" / "calls.jsonl.schema.json"
STATE_PATH = REPO / "run_state" / "week1.state.json"
_VALIDATOR = Draft202012Validator(json.loads(SCHEMA_PATH.read_text()))


def _run_invoked_tool(records):
    """A run invoked the tool if any of its records fed a tool result back."""
    return any(
        any(m["role"] == "tool" for m in rec["prompt_messages"])
        for rec in records
    )


def _read_jsonl(path):
    return [json.loads(l) for l in Path(path).read_text().splitlines() if l]


def _update_state_metric(metric_value):
    """Atomically merge day4_tool_call_invocation_rate into state metric_log."""
    state = json.loads(STATE_PATH.read_text())
    state.setdefault("metric_log", {})["day4_tool_call_invocation_rate"] = metric_value
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--temperature", type=float, default=0.3)
    ap.add_argument("--output", default="logs/day4_robust.jsonl")
    ap.add_argument("--max-tokens", type=int, default=512)
    args = ap.parse_args()

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("")

    invoked_count = 0
    run_record_counts = []
    tool_errors = 0
    for i in range(args.n):
        before = sum(1 for _ in out.open()) if out.exists() else 0
        try:
            chain = call_with_tools(
                PD_MESSAGES, TOOLS,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
                caller_tag=f"test_tool_call_robustness/run{i}",
                log_path=str(out),
            )
        except ToolCallError as exc:
            # We do NOT silently retry. Note the error and keep going so we
            # measure the full rate over N trials.
            tool_errors += 1
            print(f"  run {i + 1}/{args.n}: ToolCallError ({exc})")
            run_record_counts.append("err")
            continue
        run_records = _read_jsonl(out)[before:]
        run_record_counts.append(len(run_records))
        invoked = _run_invoked_tool(run_records)
        invoked_count += int(invoked)
        print(f"  run {i + 1}/{args.n}: {'tool invoked' if invoked else 'no tool'} "
              f"({len(run_records)} record(s))")

    rate = invoked_count / args.n if args.n else 0.0

    malformed = verify_log_integrity(str(out))

    print(f"\nruns                : {args.n}  @ temperature={args.temperature}")
    print(f"tool invocations    : {invoked_count}")
    print(f"tool-invocation rate: {rate:.2f}")
    print(f"tool errors raised  : {tool_errors}")
    print(f"records written     : {sum(1 for _ in out.open())}  (malformed: {malformed})")

    _update_state_metric(rate)
    print(f"wrote metric_log.day4_tool_call_invocation_rate={rate:.2f} -> {STATE_PATH}")

    if malformed:
        print("MALFORMED RECORDS WRITTEN", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
