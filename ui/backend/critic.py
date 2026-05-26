"""Critic-invocation surface for the dashboard (ui_plan.md §11.3 Phase-2
prerequisite — "hypothesis generation timeline … the critic's verdict").

Day-9 (W2-01) ships `workers/critic.py`. The Track-C Day-9 cron wraps
it and appends one JSONL record per invocation to
`logs/critic_eval.jsonl`. This module reads that log + the Track-C
fixture set (`experiments/fixtures/critic_hypotheses/*.json`) and
computes the rolling flag-rate, per-fixture matchup, and recent-runs
list that `CriticPanel.tsx` renders.

Read-only — no execute affordances (operating-contract rule 8). Mirrors
`ui/backend/unlock.py` shape: one consolidated payload with each
section independently `available=true/false` so the dashboard can
render partial state when the log or fixtures are not yet present.

We do NOT import `experiments.fixtures.loader` — that module lives in
Track C's zone and Track D cannot take a runtime dependency on it.
Instead we glob the fixture JSON files directly; the only fields we
need are documented in `experiments/fixtures/README.md`.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# A critic-eval record is considered renderable when these are present.
# Track A's `workers/critic.py` lands on Day 9 and finalizes the full
# shape; the UI keeps the required set minimal so a schema addition
# does not break rendering.
CRITIC_RECORD_REQUIRED = ("timestamp", "hypothesis_id", "flag_decision")

VALID_FLAG_DECISIONS = {"flawed", "sound"}


def _iter_jsonl(path: Path) -> Iterable[Tuple[int, Optional[Dict[str, Any]]]]:
    """Yield (line_no, parsed_or_None). None means malformed JSON."""
    if not path.exists():
        return
    try:
        with open(path, encoding="utf-8") as fh:
            for line_no, raw in enumerate(fh, 1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    yield line_no, json.loads(raw)
                except json.JSONDecodeError:
                    yield line_no, None
    except OSError:
        return


def _rolling_cutoff(now_iso: Optional[str], days: int) -> Optional[str]:
    if not now_iso or not days:
        return None
    try:
        now = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    cutoff = (now - timedelta(days=days)).astimezone(timezone.utc)
    return cutoff.isoformat().replace("+00:00", "Z")


def _excerpt(text: Any, max_chars: int = 280) -> str:
    """Truncate a critique to a single-paragraph excerpt for the panel.

    The full critique is potentially long (the critic agent writes
    paragraphs); the panel renders a one-line excerpt so 50 rows fit.
    """
    if not isinstance(text, str):
        return ""
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1].rstrip() + "…"


def _target_hits(critique: Any, targets: List[str]) -> List[str]:
    """Return the subset of `targets` that appear as a case-insensitive
    substring inside `critique`. Loose by design — the fixture README
    documents targets as "substrings/concepts a substantive critique
    should hit" (experiments/fixtures/README.md §"Fixture schema").
    """
    if not isinstance(critique, str) or not isinstance(targets, list):
        return []
    haystack = critique.lower()
    hits = []
    for target in targets:
        if isinstance(target, str) and target and target.lower() in haystack:
            hits.append(target)
    return hits


def load_critic_fixtures(fixtures_dir: Path) -> Dict[str, Dict[str, Any]]:
    """Load the critic_hypotheses fixture set, keyed by `id`.

    Returns {} when the directory is absent (e.g., Track C has not yet
    landed the fixtures in a worktree we can read). The fixture shape
    we depend on: `id`, `ground_truth_label`, `expected_critique_targets`,
    `injected_flaw_type`, `severity`, `domain`.
    """
    fixtures: Dict[str, Dict[str, Any]] = {}
    if not fixtures_dir.exists() or not fixtures_dir.is_dir():
        return fixtures
    for path in sorted(fixtures_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        fid = data.get("id")
        if isinstance(fid, str) and fid:
            fixtures[fid] = data
    return fixtures


def parse_critic_log(log_path: Path) -> Dict[str, Any]:
    """Read `logs/critic_eval.jsonl` into a list of records + malformed-line
    locations. The full file is parsed (these logs are append-only and
    small — one entry per critic invocation, not per token).
    """
    path = Path(log_path)
    if not path.exists():
        return {"available": False, "records": [], "malformed_lines": [],
                "total_lines": 0}
    records: List[Dict[str, Any]] = []
    malformed: List[int] = []
    for line_no, record in _iter_jsonl(path):
        if record is None:
            malformed.append(line_no)
            continue
        if any(k not in record for k in CRITIC_RECORD_REQUIRED):
            malformed.append(line_no)
            continue
        records.append(record)
    return {"available": True, "records": records,
            "malformed_lines": malformed,
            "total_lines": len(records) + len(malformed)}


def compute_recent_runs(records: List[Dict[str, Any]],
                        fixtures: Dict[str, Dict[str, Any]],
                        limit: int = 50) -> List[Dict[str, Any]]:
    """Return the latest `limit` runs, newest last (consistent with the
    JSONL append order). Each row carries the render-ready fields the
    panel needs: hypothesis_id, flag_decision, critique excerpt, and
    the `target_hits` / `target_count` against the fixture's expected
    critique targets.
    """
    capped = max(1, min(limit, 50))
    tail = records[-capped:] if len(records) > capped else list(records)
    rows: List[Dict[str, Any]] = []
    for rec in tail:
        hid = rec.get("hypothesis_id")
        fixture = fixtures.get(hid) if isinstance(hid, str) else None
        targets = (fixture.get("expected_critique_targets") if fixture else []) or []
        hits = _target_hits(rec.get("critique"), targets)
        decision = rec.get("flag_decision")
        rows.append({
            "timestamp": rec.get("timestamp"),
            "hypothesis_id": hid,
            "flag_decision": decision if decision in VALID_FLAG_DECISIONS else None,
            "ground_truth_label": fixture.get("ground_truth_label") if fixture else None,
            "domain": fixture.get("domain") if fixture else None,
            "severity": fixture.get("severity") if fixture else None,
            "injected_flaw_type":
                fixture.get("injected_flaw_type") if fixture else None,
            "critique_excerpt": _excerpt(rec.get("critique")),
            "target_hits": hits,
            "target_count": len(targets),
            "model": rec.get("model"),
            "latency_ms": rec.get("latency_ms"),
        })
    return rows


def compute_flag_rate(records: List[Dict[str, Any]],
                      rolling_window_days: int = 7,
                      now_iso: Optional[str] = None) -> Dict[str, Any]:
    """Rolling flag-rate across the window.

    flag_rate = (# flagged "flawed") / (total decisions in window).
    "Sound" baseline fixtures should NOT be flagged — a high flag-rate
    is fine ONLY if it tracks the underlying mix of flawed:sound in the
    fixture pool. The matchup table (compute_fixture_matchup) is the
    confusion-matrix-style view that contextualizes the rate.
    """
    cutoff = _rolling_cutoff(now_iso, rolling_window_days)
    flawed = sound = total = 0
    for rec in records:
        decision = rec.get("flag_decision")
        if decision not in VALID_FLAG_DECISIONS:
            continue
        ts = rec.get("timestamp")
        if cutoff and isinstance(ts, str) and ts < cutoff:
            continue
        total += 1
        if decision == "flawed":
            flawed += 1
        else:
            sound += 1
    rate = (flawed / total) if total else None
    return {"window_days": rolling_window_days, "total": total,
            "flawed_count": flawed, "sound_count": sound, "flag_rate": rate}


def compute_fixture_matchup(records: List[Dict[str, Any]],
                            fixtures: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Per-fixture matchup table: most-recent decision vs ground truth.

    For each fixture-ID seen in the log, the matchup uses the LATEST
    decision (the critic may be re-run as the agent improves). A
    fixture present in the fixture set but never run shows
    `decision=None` so the panel renders an "unrun" badge.

    Aggregates: TP/FP/TN/FN counts where positive class = "flawed"
    (i.e. the critic correctly flagging a flawed hypothesis is TP).
    Accuracy is computed from the matchup, not from per-run records,
    so re-runs don't double-count.
    """
    by_fixture: Dict[str, Dict[str, Any]] = {}
    for rec in records:
        hid = rec.get("hypothesis_id")
        decision = rec.get("flag_decision")
        if not isinstance(hid, str) or decision not in VALID_FLAG_DECISIONS:
            continue
        prior = by_fixture.get(hid)
        if prior and (rec.get("timestamp") or "") < (prior.get("timestamp") or ""):
            continue
        by_fixture[hid] = rec
    rows: List[Dict[str, Any]] = []
    tp = fp = tn = fn = unrun = unknown_fixture = 0
    for fid, fixture in sorted(fixtures.items()):
        rec = by_fixture.get(fid)
        decision = rec.get("flag_decision") if rec else None
        gt = fixture.get("ground_truth_label")
        targets = fixture.get("expected_critique_targets") or []
        hits = _target_hits(rec.get("critique") if rec else None, targets)
        outcome = _classify(decision, gt)
        if outcome == "TP":
            tp += 1
        elif outcome == "FP":
            fp += 1
        elif outcome == "TN":
            tn += 1
        elif outcome == "FN":
            fn += 1
        elif outcome == "unrun":
            unrun += 1
        rows.append({
            "fixture_id": fid,
            "ground_truth_label": gt,
            "injected_flaw_type": fixture.get("injected_flaw_type"),
            "severity": fixture.get("severity"),
            "domain": fixture.get("domain"),
            "decision": decision,
            "outcome": outcome,
            "target_hits": hits,
            "target_count": len(targets),
            "latest_run_ts": rec.get("timestamp") if rec else None,
        })
    # Fixtures absent from the fixture set but present in the log
    # (e.g. ad-hoc hypothesis IDs) show up as "unknown_fixture" rows so
    # the panel surfaces them rather than silently dropping.
    for hid in sorted(set(by_fixture) - set(fixtures)):
        rec = by_fixture[hid]
        unknown_fixture += 1
        rows.append({
            "fixture_id": hid,
            "ground_truth_label": None,
            "injected_flaw_type": None,
            "severity": None,
            "domain": None,
            "decision": rec.get("flag_decision"),
            "outcome": "unknown_fixture",
            "target_hits": [],
            "target_count": 0,
            "latest_run_ts": rec.get("timestamp"),
        })
    scored = tp + fp + tn + fn
    accuracy = ((tp + tn) / scored) if scored else None
    return {"rows": rows, "counts": {"TP": tp, "FP": fp, "TN": tn, "FN": fn,
                                     "unrun": unrun,
                                     "unknown_fixture": unknown_fixture},
            "accuracy": accuracy, "scored": scored,
            "total_fixtures": len(fixtures)}


def _classify(decision: Optional[str], ground_truth: Optional[str]) -> str:
    """Return TP / FP / TN / FN / unrun / unknown_truth."""
    if decision is None:
        return "unrun"
    if ground_truth not in {"flawed", "sound"}:
        return "unknown_truth"
    if decision == "flawed" and ground_truth == "flawed":
        return "TP"
    if decision == "flawed" and ground_truth == "sound":
        return "FP"
    if decision == "sound" and ground_truth == "sound":
        return "TN"
    return "FN"  # decision == "sound" and ground_truth == "flawed"


def compute_critic_summary(log_path: Path, fixtures_dir: Path,
                           limit: int = 50,
                           rolling_window_days: int = 7,
                           now_iso: Optional[str] = None) -> Dict[str, Any]:
    """Consolidated /api/critic_summary payload.

    Sections (each independently `available=true/false`):
      - `recent_runs`     — latest N invocations (≤50) for the panel rows
      - `flag_rate`       — rolling window aggregate
      - `fixture_matchup` — per-fixture confusion-matrix-style table
    """
    log_state = parse_critic_log(Path(log_path))
    fixtures = load_critic_fixtures(Path(fixtures_dir))
    records = log_state["records"]
    fixtures_section = {
        "available": bool(fixtures),
        "total": len(fixtures),
    }
    recent_runs_section = {
        "available": log_state["available"],
        "limit": max(1, min(limit, 50)),
        "rows": compute_recent_runs(records, fixtures, limit=limit)
            if log_state["available"] else [],
        "malformed_lines": log_state["malformed_lines"],
        "total_runs": len(records),
    }
    flag_rate_section = {
        "available": log_state["available"],
        **compute_flag_rate(records, rolling_window_days=rolling_window_days,
                            now_iso=now_iso),
    }
    matchup_section = {
        "available": log_state["available"] and bool(fixtures),
        **compute_fixture_matchup(records, fixtures),
    }
    return {
        "milestone": "critic_invocations",
        "fixtures": fixtures_section,
        "recent_runs": recent_runs_section,
        "flag_rate": flag_rate_section,
        "fixture_matchup": matchup_section,
    }
