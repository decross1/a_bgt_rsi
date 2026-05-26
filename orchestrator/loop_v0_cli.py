"""CLI entry for LOOP_V0 Part 1 hello-world.

Usage:
  env -u MOCK_LLM ./.venv-chroma/bin/python -m orchestrator.loop_v0_cli \
      --topic "Tit-for-Tat dominance in repeated Prisoner's Dilemma"

Prints a small banner, instantiates PyRuntime, calls
`nara.run_iteration`, and prints the resulting journal entry path.
The UI session triggers this same module via subprocess.Popen — the
CLI is the single triggerable entry point for both human and UI.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from orchestrator.nara import run_iteration
from orchestrator.runtime import PyRuntime


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="orchestrator.loop_v0_cli",
        description=(
            "Run one LOOP_V0 hello-world iteration: Nara picks a tool, "
            "narrates, journals."
        ),
    )
    ap.add_argument(
        "--topic", required=True,
        help="Research topic (a sentence). Nara consumes this as the seed.",
    )
    ap.add_argument(
        "--source", default="human_cli",
        choices=["human_cli", "human_ui"],
        help="Where this invocation originated; recorded in iteration_record.seed.source.",
    )
    args = ap.parse_args()

    print("=" * 72)
    print(" Nara — LOOP_V0 Part 1 hello-world")
    print("=" * 72)
    print(f" Topic: {args.topic}")
    print(f" Source: {args.source}")
    print(f" Runtime: PyRuntime (NemoClawRuntime deferred — see DECISIONS.md D-031)")
    print("=" * 72)
    print()

    runtime = PyRuntime()
    record = run_iteration(args.topic, runtime=runtime, source=args.source)

    print()
    print("=" * 72)
    print(" Iteration complete")
    print("=" * 72)
    print(f" iteration_id:       {record['iteration_id']}")
    print(f" tools called:       {', '.join(record['tool_calls_made']) or '(none)'}")
    print(f" journal entry:      {record['journal_entry_path']}")
    print(f" loop_memory row:    memory/loop_memory.jsonl (appended)")
    print(f" wrapper calls:      {len(record['wrapper_call_ids'])}")
    print()
    print(" Nara's summary:")
    print(" " + "-" * 70)
    for line in (record.get("nara_summary") or "(empty)").splitlines():
        print(f" {line}")
    print(" " + "-" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
