"""Read-only lab audit CLI and inert, content-addressed exposure annotation.

Run with ``python -m tools.audit_claim_binding``. Neither this CLI nor its
manifest is used by Nara's runtime. Quarantine here is an evidence annotation,
not a kill, rejection, acceptance, level change or execution gate.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

from tools.claim_binding_audit import (
    ApparatusAuditInputError, audit_claim_bindings,
)

ROOT = Path(__file__).resolve().parent.parent
LOOP_MEMORY = ROOT / "memory/loop_memory.jsonl"
CALL_LOG = ROOT / "logs/calls.jsonl"


def exposure_manifest(report: dict) -> dict:
    """Preserve exact iteration membership; byte identity is not authentication."""
    rows = report["iterations"]
    statuses = ("bound", "mismatch", "unverifiable")
    ids = [row["iteration_id"] for row in rows]
    if not rows or len(ids) != len(set(ids)) or any(row["status"] not in statuses for row in rows):
        raise ApparatusAuditInputError("invalid exposure membership")
    counts = {s: sum(row["status"] == s for row in rows) for s in statuses}
    if report["aggregate"]["iterations"] != len(rows) or report["aggregate"]["iteration_status"] != counts:
        raise ApparatusAuditInputError("exposure aggregate does not match membership")
    sources = {name: {k: source[k] for k in ("sha256", "bytes", "records", "prefix_mode")}
               for name, source in report["sources"].items()}
    payload = {
        "schema": "https://a-bgt-rsi.local/claim-exposure/v1",
        "method": report["policy"],
        "auditor_sha256": "sha256:" + sha256((ROOT / "tools/claim_binding_audit.py").read_bytes()).hexdigest(),
        "source_cursors": sources,
        "authority_effect": "none",
        "use": "inert derived exposure; no runtime gate or research disposition",
        "source_authentication": "not provided",
        "aggregate": {"iterations": len(rows), "iteration_status": counts},
        "iterations": [
            {"iteration_id": row["iteration_id"], "binding_status": row["status"],
             "evidence_quarantined": row["status"] != "bound",
             "research_disposition": "unchanged",
             "source_row": row["loop_memory_line"],
             "source_row_sha256": row["loop_memory_record_sha256"],
             "canonical_hypothesis": row["canonical_hypothesis"],
             "wrapper_call_ids": row["wrapper_call_ids"]}
            for row in rows
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    return {"manifest_sha256": "sha256:" + sha256(encoded).hexdigest(), "manifest": payload}


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    # Retain the source CLI spelling for its transplanted regression corpus.
    if args[:1] == ["apparatus-audit"]:
        args.pop(0)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loop-memory", type=Path, default=LOOP_MEMORY)
    parser.add_argument("--call-log", type=Path, default=CALL_LOG)
    parser.add_argument("--loop-prefix-bytes", type=int)
    parser.add_argument("--call-prefix-bytes", type=int)
    parser.add_argument("--expected-loop-sha256")
    parser.add_argument("--expected-call-sha256")
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--details", action="store_true")
    output.add_argument("--exposure", action="store_true")
    ns = parser.parse_args(args)
    try:
        report = audit_claim_bindings(
            ns.loop_memory, ns.call_log,
            loop_memory_bytes=ns.loop_prefix_bytes,
            call_log_bytes=ns.call_prefix_bytes,
            expected_loop_memory_sha256=ns.expected_loop_sha256,
            expected_call_log_sha256=ns.expected_call_sha256)
        if ns.exposure:
            result = exposure_manifest(report)
        elif ns.details:
            result = report
        else:
            result = {k: v for k, v in report.items() if k != "iterations"}
    except (ApparatusAuditInputError, OSError) as exc:
        print(f"apparatus audit input invalid: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
