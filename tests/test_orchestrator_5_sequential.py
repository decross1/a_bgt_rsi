#!/usr/bin/env python3
"""
Day 6 task day6_block2_robustness_mini (part 1) -- sequential success path.

Spawns 5 workers SEQUENTIALLY (concurrency is a Week 2 problem) via the
OrchestratorClient and asserts all 5 return status="passed". Per-task
timing is logged. The 5 worker_output records are written to --output as
JSONL (one record per line) so the Day 6 command chain and
tools/inspect_run.py can read them back.

    python3 tests/test_orchestrator_5_sequential.py --output logs/day6_5seq.jsonl

Exits non-zero if any task is not "passed" or any output violates the
worker contract, so the plan's `&&` chain short-circuits before the
malformed-input test.

Drafted by Track B on Day 3 against the contract in plan.yaml task
day6_block2_worker_contract. The real OrchestratorClient
(orchestrator/openclaw_runner.py) is built on Day 6; until then, run with
MOCK_LLM=1 to exercise this scaffold against MockOrchestratorClient. See
notes/track-b-day5-6-scaffolds.md. Track B never calls an LLM endpoint.
"""
import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))          # tests/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # repo root
from _orchestrator_contract import (  # noqa: E402
    MockOrchestratorClient, load_orchestrator_client, make_summarize_task,
    validate_worker_output,
)

# 5 distinct papers -- arbitrary arxiv_ids; the mock worker stubs the
# summary, the real Day 6 worker retrieves each from papers_recent.
TASKS = [
    ("seq-1", "2401.01001"),
    ("seq-2", "2401.01002"),
    ("seq-3", "2401.01003"),
    ("seq-4", "2401.01004"),
    ("seq-5", "2401.01005"),
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
            tempfile.gettempdir(), "track_b_orchestrator_5seq.jsonl")
        Path(log).write_text("")  # fresh log per run
        return MockOrchestratorClient(log_path=log), "mock"
    print("FAIL: orchestrator/openclaw_runner.py does not exist yet "
          "(Day 6 builds it) and MOCK_LLM is unset. Run with MOCK_LLM=1 "
          "to exercise this scaffold.", file=sys.stderr)
    sys.exit(2)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", default=os.path.join(
        tempfile.gettempdir(), "day6_5seq.jsonl"),
        help="JSONL path for the 5 worker_output records.")
    ap.add_argument("--orchestrator-log", default=None,
                    help="Mock-only: where the orchestrator JSONL chain is "
                         "written. The real client manages its own log.")
    args = ap.parse_args()

    client, mode = get_client(args.orchestrator_log)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    records, failures = [], []
    print(f"orchestrator: {mode}\n")
    for task_id, arxiv_id in TASKS:
        task = make_summarize_task(task_id, arxiv_id)
        t0 = time.perf_counter()
        try:
            output = client.run_task(task)
        except Exception as exc:  # the orchestrator must not crash
            failures.append(f"{task_id}: run_task raised {type(exc).__name__}: {exc}")
            print(f"  {task_id:8s} CRASHED  {type(exc).__name__}: {exc}")
            continue
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        status = output.get("status") if isinstance(output, dict) else None
        schema_errs = validate_worker_output(output)
        if status != "passed":
            failures.append(f"{task_id}: status={status!r} "
                             f"errors={output.get('errors') if isinstance(output, dict) else output}")
        if schema_errs:
            failures.append(f"{task_id}: output violates worker contract: "
                             f"{'; '.join(schema_errs)}")
        records.append(output)
        flag = "ok" if status == "passed" and not schema_errs else "FAIL"
        print(f"  {task_id:8s} {flag:4s} status={status!s:8s} {elapsed_ms:8.1f} ms")

    # Write the worker_output records (schema-valid; one per line).
    with out.open("w") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")

    passed = sum(1 for r in records
                 if isinstance(r, dict) and r.get("status") == "passed")
    print(f"\nsequential success: {passed}/5")
    print(f"records written   : {out}")

    if failures:
        print("\nFAILURES:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        print("5/5 SEQUENTIAL CHECK FAILED", file=sys.stderr)
        sys.exit(1)
    print("PASS: 5/5 workers succeeded sequentially.")


if __name__ == "__main__":
    main()
