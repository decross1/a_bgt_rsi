"""Outcome-4 writer of record: authorize an autonomous fix (seams 3+4, D-046).

The `/todo` cockpit's six resolution outcomes (docs/todo_cockpit_seam_plan.md)
include outcome 4 — "Refine: authorize an autonomous fix". This CLI is its
writer of record. It does NOT dispatch anything: it ENQUEUES a full
spawn-contract for an autonomous fix into an append-only queue
(`memory/authorize_fix_queue.jsonl`) that a LATER dev session consumes.

The two boundaries this preserves are load-bearing:

  - **Merge-gate invariant.** An enqueue authorizes the *work*, never an
    unreviewed merge. Stage-(i) flow (the only flow shipped): approve ->
    enqueue here -> a human-driven primary session dispatches a coding agent
    under the spawn-contract skill (live ledger run_state/spawn.jsonl) ->
    the agent returns a branch + tests + report -> the primary merges under
    the framework code-review + full-suite + smoke gate. Nothing dispatches
    at approve time.
  - **D-014 runtime firewall.** The Gemma/Nara RUNTIME does not dispatch
    coding agents; dispatch is dev-time. Writing an enqueue row is not a
    dispatch, so this CLI does not cross the firewall. Stage-(ii) (an
    autonomous dispatcher consuming these rows) is the documented TARGET,
    NOT built here — and is gated by an explicit future D-014 annotation.

The enqueue row carries the FULL spawn-contract block (per the spawn-contract
skill / CLAUDE.md Dynamic Workflow rule 3) so a future stage-(ii) dispatcher
reads the SAME rows with no schema migration. We write to a NEW queue file,
NOT run_state/spawn.jsonl — that ledger is the LIVE spawn record, written at
actual dispatch, not at enqueue.

Mirrors orchestrator/todo_cli.py and orchestrator/gate_cli.py: validate-then-
append, append-only open mode, out-of-enum / empty-required REJECTED with a
nonzero exit and NOTHING written (CLAUDE.md inviolate rule 4). Fail-closed
like orchestrator/novelty_skeptic.attack(): an unresolvable ref-id never
fabricates an enqueue, the way the skeptic never fabricates a concession.
The CLI prints the enqueued contract JSON on success so a calling UI can
surface it verbatim (D-046 success semantics).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
QUEUE_PATH = REPO_ROOT / "memory" / "authorize_fix_queue.jsonl"

# The uncertainty surfaces a --ref-id may name. A ref-id "resolves" when it
# matches a known item on one of these (the same items outcomes 1-3 act on):
#   - a promoted finding (finding_id in surfaced_findings.jsonl), or
#   - an open dev-session deferral (ref_id in dev_session_queue.jsonl), or
#   - a coordinator escalation (run_id/finding id in coordinator_bubbles.jsonl).
# Read-only resolution; we never write these. Resolving against the live
# surfaces (not a free-form string) is the validation gate: an unknown ref-id
# is rejected, never enqueued (rule 4 / fail-closed).
SURFACED_PATH = REPO_ROOT / "memory" / "surfaced_findings.jsonl"
DEFER_PATH = REPO_ROOT / "memory" / "dev_session_queue.jsonl"
BUBBLES_PATH = REPO_ROOT / "memory" / "coordinator_bubbles.jsonl"

# Default spawn-contract scaffold for a UI-authorized fix. The skill_subset is
# the build-agent core (CLAUDE.md Dynamic Workflow rule 3); authority_cap and
# self_gating_rules encode the merge-gate + firewall in the row itself so a
# future stage-(ii) dispatcher inherits them with no schema change. budget is
# real (rule: a spawn with no budget is forbidden — spawn-contract skill).
DEFAULT_SKILL_SUBSET = [
    "resume-state", "gate-check", "validate", "run-log", "fallback",
    "brain-recall",
]
DEFAULT_BUDGET = {"wall_time_seconds": 1800, "iterations": None, "cost_usd": None}
DEFAULT_AUTHORITY_CAP = (
    "Create only the NEW files named by the contract + their tests; no edits "
    "to the shared spine (orchestrator/nara.py, tool_registry.py, "
    "iteration_record.schema.json), run_state/, or ui/. Open a branch; do NOT "
    "merge — the primary session is the single merge/commit authority and the "
    "framework code-review + full-suite + real smoke gate is not bypassed."
)
DEFAULT_SELF_GATING = (
    "Halt on any action outside skill_subset or authority_cap; halt before any "
    "merge or irreversible action and escalate. Dispatch is dev-time only "
    "(D-014 runtime firewall): the Gemma/Nara runtime never runs this work."
)
DEFAULT_REPORTING = (
    "Return a branch name + the green test command + a report (files touched, "
    "what changed, back-compat note); the dispatching dev session reconciles "
    "and merges under the gate. Closes the run_state/spawn.jsonl ledger line."
)
DEFAULT_ESCALATION = (
    "If the fix cannot proceed, set the spawn ledger status to escalated and "
    "leave result.child_summary explaining why; do not partial-merge."
)
DEFAULT_DONE_CONDITION = (
    "The authorized fix is implemented in NEW files with a test green under "
    "MOCK_LLM=1; existing tests stay green (back-compat); reviewed by the "
    "framework code-review skill before merge."
)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue  # malformed line: skip on read, never rewrite
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _ref_resolves(
    ref_id: str,
    *,
    surfaced_path: Path,
    defer_path: Path,
    bubbles_path: Path,
) -> bool:
    """True if ref_id names a known finding / deferral / coordinator bubble.

    Read-only across the three uncertainty surfaces. A coordinator bubble may
    carry the id either as its own run_id or inside its finding_ids list.
    """
    for row in _read_rows(surfaced_path):
        if row.get("finding_id") == ref_id:
            return True
    for row in _read_rows(defer_path):
        if row.get("ref_id") == ref_id:
            return True
    for row in _read_rows(bubbles_path):
        if row.get("run_id") == ref_id:
            return True
        fids = row.get("finding_ids")
        if isinstance(fids, list) and ref_id in fids:
            return True
    return False


def authorize_fix(
    ref_id: str,
    task: str,
    note: str,
    by: str = "human",
    *,
    path: Path | None = None,
    surfaced_path: Path | None = None,
    defer_path: Path | None = None,
    bubbles_path: Path | None = None,
    clock_iso: str | None = None,
) -> dict:
    """Validate, build, and append one full-spawn-contract enqueue row.

    Raises ValueError (writing NOTHING) when a required field is empty or the
    ref-id does not resolve to a known uncertainty item — the validation gate
    fails closed, never fabricating an enqueue for an unknown target (mirrors
    novelty_skeptic.attack()'s never-a-fabricated-pass discipline).

    path / *_path = None resolve to the module attributes at CALL time (not
    def time) so tests can monkeypatch them — same pattern as todo_cli.
    """
    path = Path(path) if path is not None else QUEUE_PATH
    surfaced_path = Path(surfaced_path) if surfaced_path is not None else SURFACED_PATH
    defer_path = Path(defer_path) if defer_path is not None else DEFER_PATH
    bubbles_path = Path(bubbles_path) if bubbles_path is not None else BUBBLES_PATH

    if not ref_id.strip():
        raise ValueError("ref_id must be non-empty")
    if not task.strip():
        raise ValueError("task is required — the fix's task_statement")
    if not note.strip():
        raise ValueError("note is required — say why this fix is authorized")
    if not _ref_resolves(
        ref_id.strip(),
        surfaced_path=surfaced_path,
        defer_path=defer_path,
        bubbles_path=bubbles_path,
    ):
        raise ValueError(
            f"ref_id {ref_id!r} resolves to no known finding, deferral, or "
            "coordinator bubble; refusing to enqueue an unanchored fix"
        )

    now = clock_iso or _utcnow_iso()
    # Full spawn-contract block (spawn-contract skill / Dynamic Workflow rule
    # 3). state_basis is HEAD-at-dispatch: the dispatching dev session forks
    # from the then-current commit, recorded on the live ledger at dispatch.
    contract = {
        "task_statement": task.strip(),
        "done_condition": DEFAULT_DONE_CONDITION,
        "state_basis": "HEAD@dispatch",
        "skill_subset": list(DEFAULT_SKILL_SUBSET),
        "authority_cap": DEFAULT_AUTHORITY_CAP,
        "budget": dict(DEFAULT_BUDGET),
        "self_gating_rules": DEFAULT_SELF_GATING,
        "reporting_format": DEFAULT_REPORTING,
        "escalation_path": DEFAULT_ESCALATION,
    }
    row = {
        "ref_id": ref_id.strip(),
        "outcome": "authorize_fix",
        "status": "enqueued",
        "note": note.strip(),
        "authorized_by": by,
        "authorized_at": now,
        "contract": contract,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def main(argv: list[str] | None = None) -> int:
    # The documented argv (docs/todo_cockpit_seam_plan.md seam 3) is
    # `PY -m orchestrator.authorize_fix authorize-fix --ref-id ...` — a
    # subcommand token, matching the sibling writer-of-record todo_cli. The
    # UI backend execs this exact argv (D-046), so the token is load-bearing.
    p = argparse.ArgumentParser(
        description="Authorize an autonomous fix (outcome 4): enqueue a "
        "spawn-contract for the next dev session. Does NOT dispatch.")
    sub = p.add_subparsers(dest="cmd", required=True)
    p_auth = sub.add_parser(
        "authorize-fix", help="enqueue a spawn-contract for outcome 4")
    p_auth.add_argument("--ref-id", required=True)
    p_auth.add_argument("--task", required=True,
                        help="the fix's task_statement (non-empty)")
    p_auth.add_argument("--note", required=True,
                        help="why this fix is authorized (non-empty)")
    p_auth.add_argument("--by", default="human")
    args = p.parse_args(argv)
    try:
        row = authorize_fix(args.ref_id, args.task, args.note, args.by)
    except ValueError as exc:
        print(f"rejected: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(row, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
