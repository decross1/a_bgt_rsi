#!/usr/bin/env python3
"""Read-only audit of the independent-skeptic eligibility path.

This reports routing/measurement readiness from recorded metadata.  It does
not call a model, grade scientific quality, or write a ledger/artifact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from workers.retrieval_relevance import relevance  # noqa: E402


def _instant(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid RFC3339 timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include a UTC offset or Z")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _snapshot_jsonl(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read only the byte extent visible when the descriptor is opened."""
    digest = hashlib.sha256()
    data = bytearray()
    with path.open("rb") as handle:
        stat = os.fstat(handle.fileno())
        remaining = stat.st_size
        while remaining:
            chunk = handle.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            data.extend(chunk)
            digest.update(chunk)
            remaining -= len(chunk)

    rows: list[dict[str, Any]] = []
    invalid = 0
    for raw in bytes(data).splitlines():
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            invalid += 1
            continue
        if isinstance(row, dict):
            rows.append(row)
        else:
            invalid += 1
    return rows, {
        "path": str(path.resolve()),
        "captured_size_bytes": len(data),
        "opened_size_bytes": stat.st_size,
        "mtime_utc": _iso(datetime.fromtimestamp(stat.st_mtime, timezone.utc)),
        "sha256": digest.hexdigest(),
        "json_object_rows": len(rows),
        "invalid_or_nonobject_rows": invalid,
    }


def _row_time(row: dict[str, Any], *keys: str) -> datetime | None:
    for key in keys:
        raw = row.get(key)
        if isinstance(raw, str):
            try:
                return _instant(raw)
            except argparse.ArgumentTypeError:
                return None
    return None


def _within(ts: datetime | None, since: datetime, until: datetime) -> bool:
    return ts is not None and since <= ts <= until


def _counter(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items()))


def _audit_loops(rows: list[dict[str, Any]], since: datetime,
                 until: datetime) -> dict[str, Any]:
    selected = [
        row for row in rows
        if _within(_row_time(row, "ended_at", "timestamp"), since, until)
    ]
    verdicts: Counter[str] = Counter()
    relevance_states: Counter[str] = Counter()
    replay_states: Counter[str] = Counter()
    current_eligible = 0
    raw_survives_overridden = 0
    stored_outcome_replay_eligible = 0
    skeptic_rows = 0
    qwen38_skeptic_rows = 0
    replayed = 0

    for row in selected:
        critique = row.get("critique") or {}
        retrieval = row.get("retrieval") or {}
        stored_rel = retrieval.get("relevance") or {}
        verdict = str(critique.get("verdict") or "missing")
        low = critique.get("low_confidence")
        verdicts[verdict] += 1
        relevance_states[
            f"{stored_rel.get('category', 'missing')}|low={str(low).lower()}"
        ] += 1
        if verdict == "survives" and low is False:
            current_eligible += 1
        raw_survives = critique.get("verdict_overridden_from") == "survives"
        raw_survives_overridden += int(raw_survives)
        if critique.get("skeptic_verdict") is not None:
            skeptic_rows += 1
            qwen38_skeptic_rows += int(
                "qwen3.8" in str(critique.get("skeptic_model") or "").lower())

        hypothesis = (row.get("hypothesis") or {}).get("text")
        neighbors = retrieval.get("neighbors")
        if not isinstance(hypothesis, str):
            replay_states["not_replayable"] += 1
            continue
        # Counterfactual is exactly the existing primary-R0 advisory seam:
        # demote topicality="off" only.  Independent "off_independent"
        # remains gating.
        topicality = stored_rel.get("topicality")
        replay_topicality = None if topicality == "off" else topicality
        replay = relevance(
            neighbors,
            hypothesis,
            anchor_cosine=stored_rel.get("anchor_cosine"),
            topicality=replay_topicality,
        )
        replayed += 1
        replay_low = bool(replay.get("low_confidence"))
        replay_states[
            f"{replay.get('category', 'missing')}|low={str(replay_low).lower()}"
        ] += 1
        if raw_survives and not replay_low and replay.get("category") == "ok":
            stored_outcome_replay_eligible += 1

    return {
        "completed_rows": len(selected),
        "current_clean_survives_eligible": current_eligible,
        "verdict_counts": _counter(verdicts),
        "stored_relevance_counts": _counter(relevance_states),
        "raw_survives_overridden": raw_survives_overridden,
        "rows_with_skeptic_verdict": skeptic_rows,
        "rows_with_qwen38_skeptic_verdict": qwen38_skeptic_rows,
        "r0_advisory_replay": {
            "rows_replayed": replayed,
            "state_counts": _counter(replay_states),
            "stored_raw_survives_now_clean": stored_outcome_replay_eligible,
        },
    }


def _audit_calls(rows: list[dict[str, Any]], since: datetime,
                 until: datetime) -> dict[str, Any]:
    selected = [
        row for row in rows
        if _within(_row_time(row, "timestamp", "ts"), since, until)
    ]
    qwen = 0
    skeptic = 0
    backends: Counter[str] = Counter()
    for row in selected:
        backend = str(row.get("backend") or "missing")
        model = str(row.get("model") or "")
        caller = str(row.get("caller_tag") or "")
        backends[backend] += 1
        qwen += int(backend == "vllm-qwen" or "qwen" in model.lower())
        skeptic += int("skeptic" in caller.lower())
    return {
        "wrapper_calls": len(selected),
        "qwen_attributed_calls": qwen,
        "skeptic_tagged_calls": skeptic,
        "backend_counts": _counter(backends),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loop-memory", type=Path, required=True)
    parser.add_argument("--calls", type=Path, required=True)
    parser.add_argument("--since", type=_instant, required=True)
    parser.add_argument(
        "--until", type=_instant,
        help="inclusive RFC3339 end; defaults to one UTC instant frozen before reads",
    )
    args = parser.parse_args(argv)
    captured_at = datetime.now(timezone.utc)
    until = args.until or captured_at
    if until < args.since:
        parser.error("--until must be greater than or equal to --since")

    loop_rows, loop_source = _snapshot_jsonl(args.loop_memory)
    call_rows, call_source = _snapshot_jsonl(args.calls)
    report = {
        "report_type": "skeptic_route_readiness",
        "quality_benchmark": False,
        "read_only": True,
        "captured_at": _iso(captured_at),
        "window": {
            "since_inclusive": _iso(args.since),
            "until_inclusive": _iso(until),
        },
        "sources": {"loop_memory": loop_source, "calls": call_source},
        "implementation_sha256": {
            str(path.relative_to(REPO_ROOT)): hashlib.sha256(
                path.read_bytes()).hexdigest()
            for path in (
                Path(__file__).resolve(),
                REPO_ROOT / "workers" / "retrieval_relevance.py",
            )
        },
        "loop": _audit_loops(loop_rows, args.since, until),
        "calls": _audit_calls(call_rows, args.since, until),
    }
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
