"""LOOP_V1 P2 — weekly frontier agenda-synthesis seam (D-061 family).

The idea-ledger projection (`workers.idea_projection.render_ideas_md`) is the
INPUT; both frontier vendors are asked — through an INJECTED ``invoke_fn``
whose signature matches ``agent_wrapper.frontier_cli.invoke_frontier`` — to
propose next research topics. Proposals are APPENDED to
``memory/frontier_agenda.jsonl`` as:

    {"proposal_id": "fa-<sha8>", "proposed_by": "frontier:<vendor>",
     "topic": ..., "rationale": ..., "status": "proposed", "ts": ...}

ANNOTATE-ONLY FIREWALL (D-061): this module NEVER writes
``memory/idea_ledger.jsonl`` or loop_memory. A proposal is inert until a
separate human/primary action accepts it; ``accept_proposal`` flips status by
APPENDING a superseding row (append-only, last-row-wins — the loop_feedback
convention), never by rewriting.

FAIL-OPEN SEAM (matches frontier_review's posture): a vendor's invoke error
or unparseable answer yields [] for THAT vendor, logged — a frontier outage
must not block anything local. An EMPTY ledger state is the one refusal:
``build_projection`` renders an honest "no ledger state" doc and
``synthesize`` returns [] without calling any vendor (there is nothing to
synthesize an agenda from; burning frontier calls on it would be noise).

CLI: ``python -m orchestrator.frontier_agenda --once [--dry-run]`` — one
synthesis pass over the real ledger; ``--dry-run`` prints proposals and
writes nothing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from workers.idea_ledger import DEFAULT_LEDGER as IDEA_LEDGER_PATH, load_state
from workers.idea_projection import render_ideas_md

log = logging.getLogger("frontier_agenda")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_AGENDA = REPO_ROOT / "memory" / "frontier_agenda.jsonl"

VENDORS = ("claude", "codex")
ROLE = "agenda_synthesist"
DEFAULT_TIMEOUT_S = 180   # frontier CLIs are slow full model turns
PROPOSALS_PER_VENDOR_CAP = 5

EMPTY_LEDGER_DOC = (
    "# Ideas\n\n"
    "no ledger state — memory/idea_ledger.jsonl has no clusters yet.\n"
    "Agenda synthesis refuses to call frontier vendors on an empty ledger:\n"
    "there is nothing to synthesize from, and an unconditioned proposal\n"
    "list would be noise, not agenda.\n"
)

PROPOSAL_PROMPT = (
    "You are a research-agenda synthesist reviewing the idea-ledger "
    "projection of a small autonomous research loop (game-theory/mechanism "
    "sandbox experiments on a local model). Below is its current ideas.md: "
    "live work with evidence levels, a graveyard of killed directions, and "
    "open agenda items.\n\n"
    "Propose 1-{cap} NEW research topics this loop should take up next. "
    "Ground each in the projection: extend live work, honor graveyard kill "
    "reasons (do not re-propose a killed direction unless its reopening "
    "condition is plausibly met), fill gaps the agenda misses.\n\n"
    "Answer with STRICT JSON only — no prose before or after, no markdown "
    "fences. Schema: a JSON list of objects, each\n"
    '{{"topic": "<one-line research topic>",\n'
    '  "rationale": "<2-4 sentences grounding it in the projection>"}}\n\n'
    "Current projection:\n{projection}"
).replace("{cap}", str(PROPOSALS_PER_VENDOR_CAP), 1)


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_projection(state: dict) -> str:
    """Deterministic projection text for the proposal prompt — delegates to
    idea_projection.render_ideas_md. An empty state renders the honest
    no-ledger-state doc (and synthesize will refuse to call vendors)."""
    if not state:
        return EMPTY_LEDGER_DOC
    return render_ideas_md(state)


def _extract_json_list(text: str) -> list | None:
    """Balanced-bracket extractor for the first top-level JSON list in
    ``text`` (vendors sometimes wrap answers in prose/fences despite the
    strict-JSON instruction). None on any failure — never a guess."""
    if not isinstance(text, str):
        return None
    start = text.find("[")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
                return parsed if isinstance(parsed, list) else None
    return None


def _vendor_proposals(vendor: str, text: str, ts: str) -> list[dict]:
    """Parse one vendor's answer into proposal rows. Any parse failure or
    malformed item -> dropped and logged (fail-open, per-vendor)."""
    items = _extract_json_list(text)
    if items is None:
        log.warning("frontier_agenda: %s answer unparseable as JSON list; "
                    "0 proposals from this vendor (fail-open)", vendor)
        return []
    out: list[dict] = []
    for item in items[:PROPOSALS_PER_VENDOR_CAP]:
        topic = item.get("topic") if isinstance(item, dict) else None
        rationale = item.get("rationale") if isinstance(item, dict) else None
        if not (isinstance(topic, str) and topic.strip()
                and isinstance(rationale, str) and rationale.strip()):
            log.warning("frontier_agenda: %s item missing topic/rationale, "
                        "dropped: %r", vendor, item)
            continue
        digest = hashlib.sha256(
            f"{vendor}\n{topic.strip()}\n{rationale.strip()}".encode("utf-8")
        ).hexdigest()[:8]
        out.append({
            "proposal_id": f"fa-{digest}",
            "proposed_by": f"frontier:{vendor}",
            "topic": topic.strip(),
            "rationale": rationale.strip(),
            "status": "proposed",
            "ts": ts,
        })
    return out


def _append_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def synthesize(
    state: dict,
    invoke_fn: Callable[..., dict],
    *,
    agenda_path: str | Path = DEFAULT_AGENDA,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    dry_run: bool = False,
) -> list[dict]:
    """One synthesis pass: projection -> both vendors -> proposal rows
    appended to the agenda file (unless dry_run). Returns the proposals.
    Empty ledger state -> [] and NO vendor call. Per-vendor failures are
    logged and yield [] for that vendor only."""
    if not state:
        log.warning("frontier_agenda: empty ledger state — refusing to call "
                    "vendors; no proposals")
        return []
    prompt = PROPOSAL_PROMPT.format(projection=build_projection(state))
    ts = _now_utc_iso()
    proposals: list[dict] = []
    for vendor in VENDORS:
        try:
            result = invoke_fn(vendor, prompt, timeout_s=timeout_s, role=ROLE)
        except Exception as exc:  # fail-open seam: one vendor down != halt
            log.warning("frontier_agenda: %s invoke raised %s; 0 proposals "
                        "from this vendor (fail-open)", vendor, exc)
            continue
        if result.get("error"):
            log.warning("frontier_agenda: %s invoke error %r; 0 proposals "
                        "from this vendor (fail-open)", vendor, result["error"])
            continue
        proposals.extend(_vendor_proposals(vendor, result.get("text", ""), ts))
    if proposals and not dry_run:
        _append_rows(Path(agenda_path), proposals)
    return proposals


def load_agenda(path: str | Path = DEFAULT_AGENDA) -> dict[str, dict]:
    """Reduce the append-only agenda file to {proposal_id: latest row}
    (last-row-wins, the loop_feedback convention). Missing file -> {}."""
    p = Path(path)
    if not p.exists():
        return {}
    out: dict[str, dict] = {}
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            pid = row.get("proposal_id")
            if isinstance(pid, str):
                out[pid] = row
    return out


def accept_proposal(proposal_id: str,
                    path: str | Path = DEFAULT_AGENDA) -> dict:
    """Flip a proposal to accepted by APPENDING a superseding row (the file
    is never rewritten). Raises ValueError on an unknown proposal_id —
    acceptance of nothing is never coerced into a row."""
    latest = load_agenda(path).get(proposal_id)
    if latest is None:
        raise ValueError(
            f"accept_proposal: no proposal {proposal_id!r} in {path}"
        )
    superseding = {**latest, "status": "accepted", "ts": _now_utc_iso()}
    _append_rows(Path(path), [superseding])
    return superseding


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(name)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(
        description="Weekly frontier agenda synthesis (projection -> both "
                    "vendors -> memory/frontier_agenda.jsonl).")
    p.add_argument("--once", action="store_true",
                   help="Run one synthesis pass over the real ledger.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print proposals; write nothing.")
    p.add_argument("--ledger", default=str(IDEA_LEDGER_PATH),
                   help="Idea-ledger path (default: memory/idea_ledger.jsonl).")
    p.add_argument("--agenda", default=str(DEFAULT_AGENDA),
                   help="Agenda file (default: memory/frontier_agenda.jsonl).")
    args = p.parse_args(argv)
    if not args.once:
        p.print_help(sys.stderr)
        return 2
    from agent_wrapper.frontier_cli import invoke_frontier
    state = load_state(args.ledger) if Path(args.ledger).exists() else {}
    proposals = synthesize(state, invoke_frontier,
                           agenda_path=args.agenda, dry_run=args.dry_run)
    for row in proposals:
        print(json.dumps(row, ensure_ascii=False))
    print(f"frontier_agenda: {len(proposals)} proposal(s)"
          f"{' (dry-run, nothing written)' if args.dry_run else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
