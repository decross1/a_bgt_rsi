#!/usr/bin/env python3
"""
Day 4 end-to-end tool-call test (plan.yaml day4_block2_e2e_test).

Sends a prisoner's-dilemma prompt through agent_wrapper.wrapper.call_with_tools
against the live vLLM endpoint. Expects:

  1. Two linked JSONL records in logs/day4_e2e.jsonl: turn 1 (model emits a
     get_payoff_matrix tool_call) and turn 2 (model summarizes the result).
  2. The tool_calls.arguments string parses as JSON and validates against
     tools/mock_payoffs.schema.json's function.parameters subschema.
  3. The final assistant message contains all of 3, 3 / 0, 5 / 5, 0 / 1, 1
     -- i.e. the model surfaced the tool result instead of guessing.

Each check is reported independently; the test exits non-zero on any failure.

Usage:
    .venv/bin/python tests/test_tool_call_e2e.py --output logs/day4_e2e.jsonl

Owned by Track A (Day 4). Reads tools/mock_payoffs.py + .schema.json.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jsonschema import Draft202012Validator

from agent_wrapper.wrapper import call_with_tools, verify_log_integrity  # noqa: E402
from tools.mock_payoffs import get_payoff_matrix  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
TOOL_SCHEMA = json.loads((REPO / "tools" / "mock_payoffs.schema.json").read_text())

PD_SYSTEM = (
    "You are a game-theory assistant with access to a payoff-matrix tool. "
    "You MUST call the get_payoff_matrix tool to look up matrices before you "
    "answer; do not state any payoff numbers from memory."
)
PD_USER = (
    "What is the payoff matrix for the prisoner's dilemma? Use the available "
    "tool to look it up, then state all four payoff pairs in your answer."
)
PD_MESSAGES = [
    {"role": "system", "content": PD_SYSTEM},
    {"role": "user", "content": PD_USER},
]

TOOLS = [{"spec": TOOL_SCHEMA, "impl": get_payoff_matrix}]

# Plan-stipulated payoff pairs. Accept both comma-form ("3,3", "3, 3") and the
# bare two-number adjacency form ("3 3"), since formatting wobbles by model.
EXPECTED_PAYOFFS = [(3, 3), (0, 5), (5, 0), (1, 1)]


def _has_pair(text, a, b):
    # Match "3,3" / "3, 3" / "(3, 3)" / "3 and 3".
    return bool(re.search(
        rf"\b{a}\s*,\s*{b}\b|\b{a}\s*and\s*{b}\b|\(\s*{a}\s*,\s*{b}\s*\)", text
    ))


def _read_jsonl(path):
    return [json.loads(l) for l in Path(path).read_text().splitlines() if l]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", default="logs/day4_e2e.jsonl")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--max-tokens", type=int, default=512)
    args = ap.parse_args()

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("")  # truncate -- a re-run starts clean

    chain = call_with_tools(
        PD_MESSAGES, TOOLS,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        caller_tag="test_tool_call_e2e",
        log_path=str(out),
    )

    records = _read_jsonl(out)
    failures = []

    # Check 1: two linked JSONL entries.
    if len(records) != 2:
        failures.append(f"expected exactly 2 records, got {len(records)} "
                        f"(in-memory chain length={len(chain)})")
    else:
        parent, child = records
        if parent["parent_request_id"] is not None:
            failures.append("first record's parent_request_id should be null")
        if child["parent_request_id"] != parent["request_id"]:
            failures.append("second record's parent_request_id does not match "
                            "first record's request_id")
        else:
            print(f"chain: {parent['request_id']} -> {child['request_id']}")

    # Check 2: tool_calls.arguments parse + validate against the tool schema.
    if records:
        first_completion = records[0]["completion"]
        try:
            tcs = json.loads(first_completion)
        except json.JSONDecodeError as exc:
            failures.append(f"first record completion is not JSON: {exc}")
            tcs = None
        if not isinstance(tcs, list) or not tcs:
            failures.append("first record completion is not a non-empty "
                            "tool_calls list (model may not have called the tool)")
        else:
            tc = tcs[0]
            try:
                args_obj = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError as exc:
                failures.append(f"tool_calls[0].function.arguments not JSON: {exc}")
                args_obj = None
            if args_obj is not None:
                v = Draft202012Validator(TOOL_SCHEMA["function"]["parameters"])
                errs = list(v.iter_errors(args_obj))
                if errs:
                    failures.append(f"tool_calls[0].function.arguments fails "
                                    f"schema: {errs[0].message}; args={args_obj!r}")
                else:
                    print(f"tool args validated: {args_obj}")

    # Check 3: the final assistant message contains all four PD payoff pairs.
    if len(records) >= 2:
        final = records[-1]["completion"]
        missing = [pair for pair in EXPECTED_PAYOFFS
                   if not _has_pair(final, *pair)]
        if missing:
            failures.append(f"final answer missing payoff pair(s): {missing} "
                            f"(final={final!r})")
        else:
            print("final answer mentions all four payoff pairs")

    # Schema integrity on the persisted log.
    malformed = verify_log_integrity(str(out))
    if malformed:
        failures.append(f"{malformed} malformed records in {out}")

    if failures:
        print("\nFAIL:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        sys.exit(1)
    print(f"\nPASS: 2 linked schema-valid records in {out}")


if __name__ == "__main__":
    main()
