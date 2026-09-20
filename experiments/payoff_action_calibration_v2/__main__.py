"""Explicit freeze/run/replay commands; importing the package runs nothing."""

from __future__ import annotations

import argparse
import json
import signal
import threading

from . import design


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Permanently excluded native-tool v2 shakedown"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser(
        "freeze", help="freeze a new plan after runtime preflight; no model call"
    )
    freeze.add_argument("--plan", required=True)
    freeze.add_argument("--study-id", required=True)
    freeze.add_argument("--artifact-root", required=True)
    for name in ("run", "validate"):
        command = commands.add_parser(name)
        command.add_argument("--plan", required=True)
        command.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "freeze":
            value = design.make_plan(
                args.plan, study_id=args.study_id, artifact_root=args.artifact_root
            )
            result = {
                "schema_version": value["schema_version"],
                "study_id": value["study_id"],
                "declared_slots": len(value["declared_slots"]),
                "model_calls": 0,
            }
        elif args.command == "run":
            from .runner import run

            cancelled = threading.Event()
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, lambda *_: cancelled.set())
            result = run(args.plan, args.output, cancel_event=cancelled)
        else:
            from .replay import validate

            result = validate(args.plan, args.output)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 1 if args.command == "run" and result.get("status") == "aborted" else 0
    except (ValueError, OSError) as error:
        print(
            json.dumps(
                {
                    "status": "invalid",
                    "error_type": type(error).__name__,
                    "reason": str(error),
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
