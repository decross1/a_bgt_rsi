#!/usr/bin/env python3
"""
Day 6 task day6_block2_robustness_mini (part 2) -- malformed-input path.

Dispatches deliberately malformed tasks to the OrchestratorClient. The
orchestrator must REJECT each one cleanly: no exception, no hang, no
accepting bad input. A clean rejection is a returned worker_output dict
with status="error" and a non-empty `errors` list. The error records are
written to --output as JSONL.

    python3 tests/test_orchestrator_malformed_input.py --output logs/day6_malformed.jsonl

The plan calls for "1 worker with deliberately malformed input"; this
scaffold runs several malformed shapes (each is one dispatch) so the
rejection path is exercised broadly. Exits non-zero if ANY case crashes,
hangs-as-exception, is accepted, or yields a contract-invalid output.

Drafted by Track B on Day 3 against the contract in plan.yaml task
day6_block2_worker_contract. Until the Day 6 OrchestratorClient exists,
run with MOCK_LLM=1 to exercise this against MockOrchestratorClient. See
notes/track-b-day5-6-scaffolds.md. Track B never calls an LLM endpoint.
"""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))          # tests/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # repo root
from _orchestrator_contract import (  # noqa: E402
    MockOrchestratorClient, load_orchestrator_client, validate_worker_output,
)

# Each case: (label, malformed task). The orchestrator must reject all of
# them cleanly -- none should reach a worker or raise.
MALFORMED_CASES = [
    ("missing_task_id",
     {"task_type": "summarize_paper",
      "payload": {"arxiv_id": "2401.09001"}, "parent_request_id": None}),
    ("unknown_task_type",
     {"task_id": "bad-1", "task_type": "translate_paper",
      "payload": {"arxiv_id": "2401.09002"}, "parent_request_id": None}),
    ("payload_missing_arxiv_id",
     {"task_id": "bad-2", "task_type": "summarize_paper",
      "payload": {}, "parent_request_id": None}),
    ("payload_wrong_type",
     {"task_id": "bad-3", "task_type": "summarize_paper",
      "payload": "not-an-object", "parent_request_id": None}),
    ("not_an_object", "this is not a task dict at all"),
]


def get_client(orchestrator_log):
    """Return (client, mode). Prefers the real Day 6 OrchestratorClient;
    falls back to the mock only when it is genuinely absent AND
    MOCK_LLM=1. A real orchestrator that exists but fails to load is a
    hard failure -- never masked by the mock."""
    cls, load_err = load_orchestrator_client()
    if cls is not None:
        return cls(), "real"
    if load_err is not None:
        print(f"FAIL: {load_err}\nThe real orchestrator exists but is "
              "broken; refusing to fall back to the mock.", file=sys.stderr)
        sys.exit(2)
    if os.environ.get("MOCK_LLM"):
        log = orchestrator_log or os.path.join(
            tempfile.gettempdir(), "track_b_orchestrator_malformed.jsonl")
        Path(log).write_text("")  # fresh log per run
        return MockOrchestratorClient(log_path=log), "mock"
    print("FAIL: orchestrator/openclaw_runner.py does not exist yet "
          "(Day 6 builds it) and MOCK_LLM is unset. Run with MOCK_LLM=1 "
          "to exercise this scaffold.", file=sys.stderr)
    sys.exit(2)


def check_rejection(label, output):
    """Return a list of failure strings for one malformed dispatch. Empty
    list == the orchestrator rejected it cleanly and correctly."""
    fails = []
    if not isinstance(output, dict):
        return [f"{label}: run_task returned {type(output).__name__}, "
                f"not a worker_output dict"]
    if output.get("status") != "error":
        fails.append(f"{label}: status={output.get('status')!r}, "
                      f"expected 'error' (bad input was accepted?)")
    if not output.get("errors"):
        fails.append(f"{label}: `errors` is empty -- a rejection must "
                     f"explain itself")
    schema_errs = validate_worker_output(output)
    if schema_errs:
        fails.append(f"{label}: error output itself violates the worker "
                     f"contract: {'; '.join(schema_errs)}")
    return fails


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", default=os.path.join(
        tempfile.gettempdir(), "day6_malformed.jsonl"),
        help="JSONL path for the rejection (worker_output) records.")
    ap.add_argument("--orchestrator-log", default=None,
                    help="Mock-only: where the orchestrator JSONL chain is "
                         "written. The real client manages its own log.")
    args = ap.parse_args()

    client, mode = get_client(args.orchestrator_log)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    records, failures = [], []
    print(f"orchestrator: {mode}\n")
    for label, task in MALFORMED_CASES:
        try:
            output = client.run_task(task)
        except Exception as exc:  # the orchestrator must NOT crash
            failures.append(f"{label}: run_task raised "
                            f"{type(exc).__name__}: {exc} -- a malformed "
                            f"task must be rejected, not crash the orchestrator")
            print(f"  {label:26s} CRASHED  {type(exc).__name__}: {exc}")
            continue
        case_fails = check_rejection(label, output)
        failures.extend(case_fails)
        if isinstance(output, dict):
            records.append(output)
        flag = "ok" if not case_fails else "FAIL"
        print(f"  {label:26s} {flag:4s} "
              f"status={output.get('status') if isinstance(output, dict) else output!r}")

    with out.open("w") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")

    clean = len(MALFORMED_CASES) - len({f.split(':')[0] for f in failures})
    print(f"\nclean rejections: {clean}/{len(MALFORMED_CASES)}")
    print(f"records written : {out}")

    if failures:
        print("\nFAILURES:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        print("MALFORMED-INPUT CHECK FAILED", file=sys.stderr)
        sys.exit(1)
    print("PASS: every malformed task was rejected cleanly.")


if __name__ == "__main__":
    main()
