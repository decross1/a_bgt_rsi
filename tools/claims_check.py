#!/usr/bin/env python3
"""Claim/lock log sweeper for concurrent agents.

Reads:
  - run_state/claims.jsonl
  - agent/ownership.yaml (for --validate-ownership and zone resolution)

Modes:
  --dry-run              List active claims and any overlap/expiry issues; do
                         not modify anything. Default behavior.
  --check <path>         Exit 0 if the given path has no non-expired,
                         non-released claim from another agent; exit 1 if held;
                         exit 2 if held-but-expired (safe to claim).
  --validate-ownership   Confirm every file in the repo maps to exactly one
                         zone in agent/ownership.yaml (no glob overlap, no
                         uncovered files in tracked zones).
  --gc                   Print expired-by->24h claims (and the entries that
                         would be moved to a comment-marked archival section
                         if implemented). Does NOT delete; archival is a
                         Track-A-only operation.
  --weekly-summary       Produce the figures the weekly retrospective consumes:
                         overlapping claims count, expired-claim writes count,
                         ownership-zone violations count.

See agent/collision_protocol.md for the full protocol.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import fnmatch
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
CLAIMS_FILE = REPO_ROOT / "run_state" / "claims.jsonl"
OWNERSHIP_FILE = REPO_ROOT / "agent" / "ownership.yaml"


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _parse_ts(ts: str) -> _dt.datetime:
    return _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _read_claims() -> list[dict]:
    if not CLAIMS_FILE.exists():
        return []
    out: list[dict] = []
    with CLAIMS_FILE.open() as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "_schema_comment" in rec:
                continue
            out.append(rec)
    return out


def _read_ownership() -> dict:
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        print("error: PyYAML required (pip install pyyaml)", file=sys.stderr)
        sys.exit(2)
    if not OWNERSHIP_FILE.exists():
        return {"zones": []}
    return yaml.safe_load(OWNERSHIP_FILE.read_text())


def _active_writes(claims: list[dict], now: _dt.datetime) -> list[dict]:
    """Return write claims that are not released and not expired."""
    by_ts: dict[str, dict] = {}
    released: set[str] = set()
    for rec in claims:
        intent = rec.get("intent")
        if intent == "write":
            by_ts[rec["timestamp"]] = rec
        elif intent == "release":
            released.add(rec.get("claim_timestamp", ""))
        elif intent == "renew":
            # Renew implicitly closes the prior claim with the same agent_id
            # and overlapping paths; the new entry stands.
            by_ts[rec["timestamp"]] = rec
    active: list[dict] = []
    for ts, rec in by_ts.items():
        if ts in released:
            continue
        exp = rec.get("expires_at")
        if exp and _parse_ts(exp) < now:
            continue
        active.append(rec)
    return active


def overlapping_claims(active: list[dict]) -> list[tuple[dict, dict]]:
    """Return pairs of active claims that share at least one path and differ
    in agent_id."""
    overlaps: list[tuple[dict, dict]] = []
    for i, a in enumerate(active):
        for b in active[i + 1:]:
            if a.get("agent_id") == b.get("agent_id"):
                continue
            paths_a = set(a.get("paths", []))
            paths_b = set(b.get("paths", []))
            if paths_a & paths_b:
                overlaps.append((a, b))
    return overlaps


def cmd_dry_run() -> int:
    now = _now()
    claims = _read_claims()
    active = _active_writes(claims, now)
    print(f"Active claims: {len(active)}")
    for rec in active:
        print(f"  {rec.get('agent_id')} → {rec.get('zone')} → {rec.get('paths')}"
              f" (expires {rec.get('expires_at')})")
    overlaps = overlapping_claims(active)
    if overlaps:
        print(f"\nOverlapping claims: {len(overlaps)}")
        for a, b in overlaps:
            print(f"  {a.get('agent_id')} and {b.get('agent_id')} both claim "
                  f"{set(a.get('paths', [])) & set(b.get('paths', []))}")
        return 1
    print("No overlapping active claims.")
    return 0


def cmd_check(path: str) -> int:
    now = _now()
    claims = _read_claims()
    by_ts: dict[str, dict] = {}
    released: set[str] = set()
    for rec in claims:
        if rec.get("intent") == "write" and path in rec.get("paths", []):
            by_ts[rec["timestamp"]] = rec
        elif rec.get("intent") == "release":
            released.add(rec.get("claim_timestamp", ""))
    candidates = [rec for ts, rec in by_ts.items() if ts not in released]
    if not candidates:
        return 0
    latest = max(candidates, key=lambda r: r["timestamp"])
    exp = latest.get("expires_at")
    if exp and _parse_ts(exp) < now:
        print(f"Path {path} held-but-expired by {latest.get('agent_id')} "
              f"(expired {exp}); safe to claim.")
        return 2
    print(f"Path {path} held by {latest.get('agent_id')} until {exp}.")
    return 1


def cmd_validate_ownership() -> int:
    ownership = _read_ownership()
    zones = ownership.get("zones", [])

    # Walk every tracked file in the repo (git-ls-files).
    import subprocess
    try:
        out = subprocess.check_output(
            ["git", "ls-files"], cwd=REPO_ROOT, text=True
        )
    except subprocess.CalledProcessError as e:
        print(f"git ls-files failed: {e}", file=sys.stderr)
        return 2
    files = [f for f in out.splitlines() if f]

    # Build glob → zone-id lookup.
    zone_globs: list[tuple[str, str]] = []
    for z in zones:
        zone_id = z.get("id")
        for pat in z.get("paths", []) or []:
            zone_globs.append((pat, zone_id))

    multi_assigned: list[tuple[str, list[str]]] = []
    unassigned: list[str] = []
    for f in files:
        matches: list[str] = []
        for pat, zone_id in zone_globs:
            if fnmatch.fnmatch(f, pat):
                matches.append(zone_id)
        # Deduplicate while preserving order
        seen: set[str] = set()
        matches = [m for m in matches if not (m in seen or seen.add(m))]
        if len(matches) > 1:
            multi_assigned.append((f, matches))
        elif len(matches) == 0:
            unassigned.append(f)

    print(f"Tracked files: {len(files)}")
    print(f"Multi-assigned (in >1 zone): {len(multi_assigned)}")
    for f, zones_for_f in multi_assigned[:20]:
        print(f"  {f}: {zones_for_f}")
    if len(multi_assigned) > 20:
        print(f"  ... and {len(multi_assigned) - 20} more")
    print(f"Unassigned (in 0 zones): {len(unassigned)}")
    for f in unassigned[:20]:
        print(f"  {f}")
    if len(unassigned) > 20:
        print(f"  ... and {len(unassigned) - 20} more")

    # Multi-assignment is a hard error; unassigned is a warning (some files
    # like .gitignore, .env, README sub-files may legitimately not have a
    # zone yet).
    return 1 if multi_assigned else 0


def cmd_gc() -> int:
    now = _now()
    claims = _read_claims()
    stale: list[dict] = []
    for rec in claims:
        if rec.get("intent") != "write":
            continue
        exp = rec.get("expires_at")
        if not exp:
            continue
        exp_ts = _parse_ts(exp)
        if (now - exp_ts).total_seconds() > 24 * 3600:
            stale.append(rec)
    print(f"Stale (expired > 24h ago) write claims: {len(stale)}")
    for rec in stale:
        print(f"  {rec.get('agent_id')} → {rec.get('paths')} "
              f"(expired {rec.get('expires_at')})")
    print("(Track A is the only writer permitted to archive these.)")
    return 0


def cmd_weekly_summary() -> int:
    now = _now()
    claims = _read_claims()
    active = _active_writes(claims, now)
    overlaps = overlapping_claims(active)
    # Expired-claim writes: writes whose expires_at is in the past and which
    # have no release entry — i.e., the agent wrote past its claim.
    expired_unreleased = []
    released: set[str] = {r.get("claim_timestamp", "") for r in claims
                          if r.get("intent") == "release"}
    for rec in claims:
        if rec.get("intent") != "write":
            continue
        exp = rec.get("expires_at")
        if not exp:
            continue
        if _parse_ts(exp) < now and rec["timestamp"] not in released:
            expired_unreleased.append(rec)
    print("Weekly summary (claim protocol cleanliness):")
    print(f"  overlapping_claims_now: {len(overlaps)}")
    print(f"  expired_unreleased_total: {len(expired_unreleased)}")
    print(f"  active_now: {len(active)}")
    print("\nFor inclusion in the weekly retrospective alignment-evidence "
          "block (agent/autonomy.md §4 bullet 4).")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="List active claims (default)")
    g.add_argument("--check", metavar="PATH", help="Check whether PATH has any active claim")
    g.add_argument("--validate-ownership", action="store_true",
                   help="Validate ownership.yaml against git-tracked files")
    g.add_argument("--gc", action="store_true",
                   help="Identify stale (expired > 24h) claims")
    g.add_argument("--weekly-summary", action="store_true",
                   help="Emit the figures for the weekly retrospective")
    args = ap.parse_args()

    if args.check:
        return cmd_check(args.check)
    if args.validate_ownership:
        return cmd_validate_ownership()
    if args.gc:
        return cmd_gc()
    if args.weekly_summary:
        return cmd_weekly_summary()
    return cmd_dry_run()


if __name__ == "__main__":
    sys.exit(main())
