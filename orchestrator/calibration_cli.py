"""Pre-verdict calibration writer of record (P4, ARCH §6.5.4).

The `/todo` cockpit captures a PRE-VERDICT calibration: a free-text
prediction + a confidence scalar in [0,1], typed by the human BEFORE the
verdict form unlocks, against a surfaced finding (ref_id). This CLI is its
writer of record (D-046: the CLI writes; ui/backend only execs the argv).
It validates and appends ONE `calibration_entry` event to
run_state/events.jsonl (ARCH §6.5.4 names a calibration_entry event in the
run-log JSONL; events.jsonl is the typed-event log the schema was minted for).

Inviolate rule 4 (validations NEVER coerced): confidence out of [0,1] is
REJECTED with a nonzero exit and NOTHING written — never clamped (contrast
the UI's UX-only clamp; the CLI is authoritative). Empty prediction, empty
ref-id, and bool-as-confidence are likewise rejected. Inviolate rule 6:
append-only ('a' mode). Inviolate rule 8: this module writes ONLY this one
row type — no generic events writer (that is the integrator's call).

Mirrors orchestrator/gate_cli.py + orchestrator/authorize_fix.py: REPO_ROOT,
a parametrized DEFAULT path, _utcnow_iso, jsonschema validate-then-append,
'rejected:' to stderr + return 1, the appended row printed as JSON on stdout.

This writer validates against schema/calibration_pre_verdict.schema.json. The
spine schema/events.jsonl.schema.json — which already owned event_type
'calibration_entry' for the INCOMPATIBLE post-experiment shape — was reconciled
in D-055 with an additive 'pre_verdict' oneOf branch, so a pre-verdict row now
validates against BOTH this focused schema and the events.jsonl spine schema.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "schema" / "calibration_pre_verdict.schema.json"
DEFAULT = REPO_ROOT / "run_state" / "events.jsonl"

_SCHEMA = json.loads(SCHEMA_PATH.read_text())
_VALIDATOR = jsonschema.Draft7Validator(_SCHEMA)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def append_calibration(
    ref_id: str,
    prediction: str,
    confidence: float,
    by: str = "human",
    *,
    path: Path = DEFAULT,
    clock_iso: str | None = None,
) -> dict:
    """Build, schema-validate, and append one pre-verdict calibration_entry.

    Returns the appended row. Raises ValueError (writing NOTHING) when:
      - confidence is a bool (bool is an int subclass — guarded explicitly,
        mirroring the cockpit's isinstance(.., bool) guard),
      - confidence is not a real finite number (NaN / Infinity rejected before
        they reach json.dumps),
      - confidence is outside the closed interval [0,1] (REJECTED, NEVER
        clamped — inviolate rule 4),
      - prediction is empty / whitespace-only,
      - ref_id is empty / whitespace-only.
    Each check stands alone (rule 4): no near-miss is banded into a pass.
    """
    if isinstance(confidence, bool):
        raise ValueError("confidence must be a number in [0,1], not a bool")
    if not isinstance(confidence, (int, float)) or not math.isfinite(confidence):
        raise ValueError(f"confidence must be a finite number (got {confidence!r})")
    if not (0.0 <= confidence <= 1.0):
        raise ValueError(
            f"confidence must be in [0,1] (got {confidence!r}); "
            "out-of-range is rejected, never clamped"
        )
    if not ref_id.strip():
        raise ValueError("ref_id must be non-empty")
    if not prediction.strip():
        raise ValueError("prediction must be non-empty")
    if not by.strip():
        raise ValueError("by must be non-empty")

    row = {
        "event_type": "calibration_entry",
        "phase": "pre_verdict",
        "timestamp": clock_iso or _utcnow_iso(),
        "ref_id": ref_id,
        "prediction": prediction,
        "confidence": float(confidence),
        "by": by,
    }
    errs = list(_VALIDATOR.iter_errors(row))
    if errs:
        raise ValueError(
            f"calibration_entry row invalid: {errs[0].message} "
            f"(path: {list(errs[0].absolute_path)})"
        )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def main(argv: list[str] | None = None) -> int:
    # The subcommand token 'calibration' is load-bearing: it matches the argv
    # the cockpit stub already echoes (ui/backend/todo_cockpit.py), so the
    # integrator swaps the stub body for an exec of this argv with zero churn.
    p = argparse.ArgumentParser(
        description="Record a pre-verdict calibration_entry (ARCH §6.5.4)."
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    p_cal = sub.add_parser(
        "calibration", help="append one pre-verdict calibration_entry event"
    )
    p_cal.add_argument("--ref-id", required=True)
    p_cal.add_argument("--prediction", required=True)
    # type=float => argparse rejects a non-numeric token at parse time (exit 2).
    p_cal.add_argument("--confidence", required=True, type=float)
    p_cal.add_argument("--by", default="human")
    args = p.parse_args(argv)

    try:
        row = append_calibration(
            args.ref_id, args.prediction, args.confidence, args.by, path=DEFAULT
        )
    except ValueError as exc:
        print(f"rejected: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(row, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
