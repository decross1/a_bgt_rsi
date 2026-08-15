"""Worker: critique-refine cycle over one idea-ledger cluster (D-064).

Owner's mechanism (verbatim intent): "a cycle where both chat/claude as
people vetting the idea give feedback on how to improve/where to go, nara
refines, and the cycle of critique goes again, maybe we limit this to 5
times before an IDEA gets killed."

One cycle = up to MAX_REFINE_ROUNDS rounds; each round:
  1. current claim = latest refined claim, else the elite's claim record,
     else a loop_memory join by member id (the F1 triage driver's join
     pattern — clusters carry bare member ids; text lives in loop_memory).
  2. screen through BOTH frontier reviewers (frontier_review.
     screen_candidate: methods + novelty).
  3. "pass" -> STOP, improved=True. Refinement NEVER auto-promotes: no
     evidence_level_changed event, ever — the cluster stays at (or, when
     reopened, returns to) its honest rung. A killed cluster reopens ONLY
     when its reopening_condition.evidence_kind is "articulated_delta" —
     the kind a frontier pass on a refined claim honestly evidences (no
     subsuming prior found); any other kind (e.g. "experiment_rerun") is
     NOT satisfied by a screen pass — reopen skipped + reported, never
     forged (rule 4).
  4. "veto"/"inconclusive" -> both reviewers' reasoning +
     closest_prior_work become improvement feedback; `refine_fn` revises
     the claim (default: one low-temp call_sync; deterministic transform
     under MOCK_LLM).
  5. append `cluster_refined` {round, feedback_digest, refined_claim}.
After the final round without a pass: cluster_killed — paper_prior_exists
when the final novelty review VETOED citing concrete prior, else
adversarial_refuted with the final critique head; either way
reopening_condition("articulated_delta") so a later passing refinement
can reopen. MAX_REFINE_ROUNDS = 5 is a HARD cap: max_rounds outside 1..5
RAISES, never clamped — a 6th round is impossible by construction.

Seams: `invoke_fn` (frontier_cli.invoke_frontier signature; under
MOCK_LLM an un-injected invoke_fn RAISES rather than spawn real CLIs) and
`refine_fn(claim_text, feedback, round_no) -> str`. CLI: python -m
workers.refine_cycle --cluster-id ID [--dry-run] [--max-rounds N<=5]
[--ledger PATH]; --dry-run resolves the starting claim and reports the
plan — invokes nothing, writes nothing. Run log: one row per round + a
terminal kill row, agent "refine_cycle" (rule 6).
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from workers import frontier_review
from workers.idea_ledger import (
    _claim_text,
    append_event,
    load_state,
    reopening_condition,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LEDGER = REPO_ROOT / "memory" / "idea_ledger.jsonl"
DEFAULT_LOOP_MEMORY = REPO_ROOT / "memory" / "loop_memory.jsonl"

# HARD cap (D-064, owner-set: "maybe we limit this to 5 times before an
# IDEA gets killed"). Test-pinned; values above it RAISE, never clamp.
MAX_REFINE_ROUNDS = 5

REFINED_CLAIM_MAX_CHARS = 1200   # cluster_refined.refined_claim cap
FEEDBACK_HEAD_CHARS = 160        # per-reviewer head inside feedback_digest
FEEDBACK_DIGEST_MAX_CHARS = 600

# The one evidence_kind a frontier pass on a REFINED claim can honestly
# satisfy when reopening a killed cluster (module docstring, step 3).
_REOPENABLE_KIND = "articulated_delta"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Missing file -> []; blank/malformed lines skipped (mirrors
    workers.meta_review._read_jsonl — loop_memory is read-only here)."""
    p = Path(path)
    if not p.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _log_row(cluster_id: str, status: str, actual: str, t0: float) -> None:
    """One run-log row, agent 'refine_cycle' (rule 6). Call-time import so
    the conftest RUN_LOG_PATH patch applies."""
    from orchestrator import runtime
    runtime.append_run_log({
        "task_id": f"refine_cycle:{cluster_id}",
        "status": status,
        "observable_actual": actual,
        "observable_expected": "frontier pass",
        "duration_ms": round((time.perf_counter() - t0) * 1000.0, 3),
    }, agent="refine_cycle")


def resolve_claim(cluster: dict[str, Any],
                  loop_memory_path: str | Path) -> tuple[str, str]:
    """(claim_text, source): latest refined claim -> elite claim record ->
    loop_memory join by member id. No surface at all RAISES — refining
    nothing would be fabrication (rule 4)."""
    refined = cluster.get("refined_claim")
    if isinstance(refined, str) and refined.strip():
        return refined.strip(), "refined_claim"
    elite = cluster.get("elite")
    if elite is not None:
        text = _claim_text(elite)
        if text:
            return text, "elite_claim"
    members = set(cluster.get("members") or [])
    for row in _read_jsonl(loop_memory_path):
        if row.get("iteration_id") not in members:
            continue
        hyp = row.get("hypothesis")
        text = hyp.get("text") if isinstance(hyp, dict) else None
        if isinstance(text, str) and text.strip():
            return text.strip(), f"loop_memory:{row['iteration_id']}"
        seed = row.get("seed")
        topic = seed.get("topic") if isinstance(seed, dict) else None
        if isinstance(topic, str) and topic.strip():
            return topic.strip(), f"loop_memory:{row['iteration_id']}:topic"
    raise ValueError(
        f"refine_cycle: cluster {cluster.get('cluster_id')!r} has no claim "
        f"surface (no refined claim, no elite claim, no loop_memory join) — "
        f"refusing to refine nothing (rule 4)."
    )


def _extract_feedback(screen: dict[str, Any]) -> list[dict[str, Any]]:
    """BOTH reviewers' reasoning + closest_prior_work as improvement
    feedback (the vetting people's 'how to improve / where to go')."""
    items = []
    for key in ("methods", "novelty"):
        rev = screen.get(key) or {}
        items.append({
            "role": rev.get("role") or f"{key}_reviewer",
            "verdict": rev.get("verdict"),
            "reasoning": rev.get("reasoning") or "",
            "closest_prior_work": rev.get("closest_prior_work"),
        })
    return items


def _feedback_digest(feedback: list[dict[str, Any]]) -> str:
    """Short joined critique heads for the cluster_refined event."""
    parts = []
    for item in feedback:
        head = " ".join((item["reasoning"] or "").split())[:FEEDBACK_HEAD_CHARS]
        part = f"{item['role']}[{item['verdict']}]: {head or '(no reasoning)'}"
        prior = item.get("closest_prior_work")
        if isinstance(prior, str) and prior.strip():
            part += f" | prior: {prior.strip()[:120]}"
        parts.append(part)
    return " || ".join(parts)[:FEEDBACK_DIGEST_MAX_CHARS]


def _critique_head(feedback: list[dict[str, Any]]) -> str:
    """Leading critique head (kill-detail material): first vetoing
    reviewer's reasoning head, else the first non-empty one."""
    ordered = sorted(feedback, key=lambda f: f.get("verdict") != "veto")
    for item in ordered:
        head = " ".join((item["reasoning"] or "").split())[:FEEDBACK_HEAD_CHARS]
        if head:
            return head
    return "(no reviewer reasoning returned)"


_REFINE_SYSTEM = (
    "You revise research claims under reviewer critique. Given a claim and "
    "the reviewers' critiques, return ONLY the revised claim text — no "
    "preamble, no JSON, no markdown. Revise the claim to address each "
    "critique concretely; when prior work is cited, state the concrete "
    "delta the revised claim has over that cited prior. Keep it a single "
    "falsifiable claim; do not invent evidence the critiques did not grant."
)


def _default_refine(claim_text: str, feedback: list[dict[str, Any]],
                    round_no: int) -> str:
    """Default reviser: deterministic transform under MOCK_LLM (hermetic),
    otherwise ONE low-temp call_sync to Gemma."""
    if os.environ.get("MOCK_LLM"):
        head = _critique_head(feedback)
        return (f"{claim_text} [r{round_no} revision addressing: {head}]"
                )[:REFINED_CLAIM_MAX_CHARS]
    from agent_wrapper.wrapper import call_sync
    critique_block = "\n".join(
        f"- {f['role']} ({f['verdict']}): {f['reasoning'] or '(none)'}"
        + (f" [closest prior: {f['closest_prior_work']}]"
           if f.get("closest_prior_work") else "")
        for f in feedback
    )
    record = call_sync(
        [
            {"role": "system", "content": _REFINE_SYSTEM},
            {"role": "user", "content": (
                f"Claim (refine round {round_no}):\n{claim_text}\n\n"
                f"Reviewer critiques:\n{critique_block}\n\n"
                "Return the revised claim text."
            )},
        ],
        temperature=0.2, seed=0, max_tokens=600, caller_tag="refine_cycle",
    )
    text = (record.get("completion") or "").strip()
    if not text:
        raise ValueError("refine_cycle: refinement returned empty text")
    return text


def refine_cluster(
    cluster_id: str,
    *,
    ledger_path: str | Path | None = None,
    loop_memory_path: str | Path | None = None,
    invoke_fn: Callable[..., dict] | None = None,
    refine_fn: Callable[[str, list, int], str] | None = None,
    max_rounds: int = MAX_REFINE_ROUNDS,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run one critique-refine cycle over `cluster_id` (module docstring
    has the mechanism). Report: {"cluster_id", "improved", "rounds_used",
    "max_rounds", "starting_claim", "claim_source", "final_claim",
    "rounds": [{"round", "verdict", "feedback_digest", "refined_claim"}],
    "killed", "kill_reason", "reopened", "reopen_skipped",
    "events_appended", "dry_run"}."""
    if not (isinstance(max_rounds, int) and 1 <= max_rounds <= MAX_REFINE_ROUNDS):
        raise ValueError(
            f"refine_cycle: max_rounds={max_rounds!r} outside 1.."
            f"{MAX_REFINE_ROUNDS} — the cap is hard, never clamped (rule 4).")
    ledger_path = Path(ledger_path) if ledger_path is not None else DEFAULT_LEDGER
    loop_memory_path = (Path(loop_memory_path) if loop_memory_path is not None
                        else DEFAULT_LOOP_MEMORY)

    cluster = load_state(ledger_path).get(cluster_id)
    if cluster is None:
        raise ValueError(
            f"refine_cycle: unknown cluster {cluster_id!r} in {ledger_path}")
    starting_claim, claim_source = resolve_claim(cluster, loop_memory_path)

    report: dict[str, Any] = {
        "cluster_id": cluster_id, "improved": False, "rounds_used": 0,
        "max_rounds": max_rounds, "starting_claim": starting_claim,
        "claim_source": claim_source, "final_claim": starting_claim,
        "rounds": [], "killed": False, "kill_reason": None,
        "reopened": False, "reopen_skipped": None,
        "events_appended": [], "dry_run": dry_run,
    }
    if dry_run:  # plan only: nothing invoked, nothing written
        return report

    if invoke_fn is None:
        if os.environ.get("MOCK_LLM"):
            raise ValueError(
                "refine_cycle: MOCK_LLM is set and no invoke_fn was injected "
                "— refusing to spawn real frontier CLIs (MOCK_LLM discipline; "
                "run with env -u MOCK_LLM or inject invoke_fn).")
        from agent_wrapper.frontier_cli import invoke_frontier
        invoke_fn = invoke_frontier
    if refine_fn is None:
        refine_fn = _default_refine

    was_killed = cluster.get("status") == "killed"
    current = starting_claim
    final_screen: dict[str, Any] | None = None

    for round_no in range(1, max_rounds + 1):
        t0 = time.perf_counter()
        screen = frontier_review.screen_candidate(
            {"cluster_id": cluster_id, "claim": current,
             "evidence_level": cluster.get("evidence_level"),
             "refine_round": round_no},
            invoke_fn)
        final_screen = screen
        verdict = screen.get("verdict")
        report["rounds_used"] = round_no

        if verdict == "pass":
            report["improved"] = True
            report["rounds"].append({"round": round_no, "verdict": "pass",
                                     "feedback_digest": None,
                                     "refined_claim": None})
            _log_row(cluster_id, "passed",
                     f"round {round_no}: frontier verdict pass", t0)
            break

        feedback = _extract_feedback(screen)
        digest = _feedback_digest(feedback)
        refined = refine_fn(current, feedback, round_no)
        if not (isinstance(refined, str) and refined.strip()):
            raise ValueError(
                "refine_cycle: refine_fn returned no text — an empty "
                "revision is never a refinement (rule 4).")
        refined = refined.strip()[:REFINED_CLAIM_MAX_CHARS]
        event = {"event_type": "cluster_refined", "ts": _utcnow(),
                 "cluster_id": cluster_id, "round": round_no,
                 "feedback_digest": digest, "refined_claim": refined}
        append_event(ledger_path, event)
        report["events_appended"].append(event)
        report["rounds"].append({"round": round_no, "verdict": verdict,
                                 "feedback_digest": digest,
                                 "refined_claim": refined})
        _log_row(cluster_id, "refined",
                 f"round {round_no}: frontier verdict {verdict}; claim revised",
                 t0)
        current = refined
        report["final_claim"] = current

    if report["improved"]:
        if was_killed:
            want = (cluster.get("reopening_condition") or {}).get("evidence_kind")
            if want == _REOPENABLE_KIND:
                reopen = {
                    "event_type": "cluster_reopened", "ts": _utcnow(),
                    "cluster_id": cluster_id,
                    "evidence": {
                        "evidence_kind": want,
                        "evidence_key":
                            f"frontier:refine_cycle:round{report['rounds_used']}",
                        "detail": (
                            f"refined claim passed both frontier reviewers at "
                            f"round {report['rounds_used']} (claim source: "
                            f"{claim_source})"),
                    },
                }
                append_event(ledger_path, reopen)
                report["events_appended"].append(reopen)
                report["reopened"] = True
            else:
                # A screen pass is not evidence of kind `want` — skipping is
                # honest; forging the kind would be coercion (rule 4).
                report["reopen_skipped"] = (
                    f"reopening_condition requires evidence_kind {want!r}; a "
                    f"frontier screen pass only evidences "
                    f"{_REOPENABLE_KIND!r} — reopen not forged (rule 4)")
        return report

    # Exhausted every round without a pass -> kill (the owner's limit).
    t0 = time.perf_counter()
    novelty = (final_screen or {}).get("novelty") or {}
    prior = novelty.get("closest_prior_work")
    evidence_key = f"frontier:refine_cycle:round{report['rounds_used']}"
    if novelty.get("verdict") == "veto" and isinstance(prior, str) and prior.strip():
        kill_reason = {
            "code": "paper_prior_exists", "evidence_key": evidence_key,
            "detail": (
                f"refine cycle exhausted ({report['rounds_used']} rounds); "
                f"final novelty review cites prior: {prior.strip()[:300]}"),
        }
    else:
        kill_reason = {
            "code": "adversarial_refuted", "evidence_key": evidence_key,
            "detail": (
                f"refine cycle exhausted ({report['rounds_used']} rounds) "
                f"without a frontier pass; final critique: "
                f"{_critique_head(_extract_feedback(final_screen or {}))}"),
        }
    kill_event = {"event_type": "cluster_killed", "ts": _utcnow(),
                  "cluster_id": cluster_id, "kill_reason": kill_reason,
                  "reopening_condition": reopening_condition(_REOPENABLE_KIND)}
    append_event(ledger_path, kill_event)
    report["events_appended"].append(kill_event)
    report["killed"] = True
    report["kill_reason"] = kill_reason
    _log_row(cluster_id, "killed",
             f"killed after {report['rounds_used']} rounds "
             f"(code={kill_reason['code']})", t0)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="D-064 critique-refine cycle over one idea-ledger "
                    "cluster (max 5 rounds, then kill).")
    parser.add_argument("--cluster-id", required=True)
    parser.add_argument("--dry-run", action="store_true",
                        help="resolve the starting claim and report the plan; "
                             "invoke nothing, write nothing")
    parser.add_argument("--max-rounds", type=int, default=MAX_REFINE_ROUNDS,
                        help=f"rounds before the kill (hard cap "
                             f"{MAX_REFINE_ROUNDS}; higher values raise)")
    parser.add_argument("--ledger", default=None,
                        help="idea-ledger path (default: memory/idea_ledger.jsonl)")
    args = parser.parse_args(argv)
    report = refine_cluster(args.cluster_id, ledger_path=args.ledger,
                            max_rounds=args.max_rounds, dry_run=args.dry_run)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
