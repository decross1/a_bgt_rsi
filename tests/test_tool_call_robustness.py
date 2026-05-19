#!/usr/bin/env python3
"""
Day 4 task -- tool-call robustness sweep.

Runs the prisoner's-dilemma prompt through call_with_tools N times at a
fixed temperature and reports the tool-invocation rate: the fraction of
runs in which the model actually called the tool (rather than answering
from parametric knowledge). All call records are written to a JSONL log.

    MOCK_LLM=1 python tests/test_tool_call_robustness.py \
        --n 5 --temperature 0.7 --output logs/tool_call_robustness.jsonl

MOCK_LLM=1 reuses the hardcoded chain from test_tool_call_e2e, so every
mock run invokes the tool -- the mock rate is deterministically 1.0. The
rate only becomes informative against the real model: that is the point
of running at temperature > 0.

call_with_tools has NO published signature yet. Assumptions are tagged
`DAY4-CONTRACT`. See notes/track-b-day3-4-scaffolds.md.

A run counts as a tool invocation if any of its call records carries a
message with role "tool" -- a schema-grounded signal that does not
depend on call_with_tools' (still unspecified) return shape.

Owned by Track B (tests). Does not touch run_state/; never calls vLLM
directly -- the real path delegates to the wrapper.
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Reuse the prompt, tools, mock chain and schema helpers from the e2e test.
from test_tool_call_e2e import (  # noqa: E402
    PD_MESSAGES, PD_TOOLS, _check_record, _load_validator, mock_tool_chain,
)

MOCK = bool(os.environ.get("MOCK_LLM"))

try:  # DAY4-CONTRACT: agent_wrapper.wrapper.call_with_tools
    from agent_wrapper.wrapper import call_with_tools  # noqa: E402
    _HAVE_REAL = True
except Exception:
    call_with_tools = None
    _HAVE_REAL = False


def _read_jsonl(path):
    with open(path) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _run_invoked_tool(records):
    """A run invoked the tool if any of its records fed a tool result back."""
    return any(
        any(m["role"] == "tool" for m in rec["prompt_messages"])
        for rec in records
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=5, help="Number of runs (default 5).")
    ap.add_argument("--temperature", type=float, default=0.7,
                    help="Sampling temperature for every run (default 0.7).")
    ap.add_argument("--output", default="logs/tool_call_robustness.jsonl",
                    help="JSONL path for all call records across all runs.")
    ap.add_argument("--min-rate", type=float, default=None,
                    help="If set, exit non-zero when the tool-invocation rate "
                         "falls below this threshold. Default: report only.")
    args = ap.parse_args()

    if not MOCK and not _HAVE_REAL:
        print("call_with_tools is not implemented yet (Day 4). "
              "Re-run with MOCK_LLM=1 to exercise this scaffold.", file=sys.stderr)
        sys.exit(1)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("")  # truncate -- a re-run starts clean

    if MOCK:
        print(f"MOCK_LLM=1 -- {args.n} deterministic runs (mock always invokes)")

    invocations = 0
    for i in range(args.n):
        before = sum(1 for _ in out.open())
        if MOCK:
            recs = mock_tool_chain(args.temperature,
                                   caller_tag=f"test_tool_call_robustness/run{i}")
            with out.open("a") as fh:
                for rec in recs:
                    fh.write(json.dumps(rec) + "\n")
        else:
            # DAY4-CONTRACT: real call appends its chain records to log_path.
            call_with_tools(PD_MESSAGES, PD_TOOLS, temperature=args.temperature,
                            caller_tag=f"test_tool_call_robustness/run{i}",
                            log_path=str(out))
        run_records = _read_jsonl(out)[before:]
        invoked = _run_invoked_tool(run_records)
        invocations += invoked
        print(f"  run {i + 1}/{args.n}: {'tool invoked' if invoked else 'no tool'} "
              f"({len(run_records)} record(s))")

    rate = invocations / args.n if args.n else 0.0

    # Validate every record that was written.
    validator = _load_validator()
    malformed = 0
    for rec in _read_jsonl(out):
        try:
            _check_record(rec, validator)
        except Exception as exc:
            malformed += 1
            print(f"  [warn] malformed record: {exc}", file=sys.stderr)

    print(f"\nruns                : {args.n}  @ temperature={args.temperature}")
    print(f"tool invocations    : {invocations}")
    print(f"tool-invocation rate: {rate:.2f}")
    print(f"records written     : {sum(1 for _ in out.open())}  (malformed: {malformed})")

    if malformed:
        print("MALFORMED RECORDS WRITTEN", file=sys.stderr)
        sys.exit(1)
    if args.min_rate is not None and rate < args.min_rate:
        print(f"TOOL-INVOCATION RATE {rate:.2f} BELOW --min-rate {args.min_rate}",
              file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
