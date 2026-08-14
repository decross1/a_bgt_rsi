"""Finding-promotion pipeline — multi-threshold gate + cross-model adversarial vote.

The loop produces many iterations; only a few are worth a human's scarce
attention. This pipeline is the funnel:

  1. CHEAP THRESHOLD GATE (pure Python, every candidate). Rejects on
     novelty class, critic verdict, a human "invalid" verdict, or a weak/
     INVALID experiment outcome. Every rejection becomes a near_miss with
     a reason — never a silent drop. `max_candidates` is applied AFTER the
     gate, capping how many survivors pay for the expensive vote.

  2. CROSS-MODEL ADVERSARIAL MULTI-VOTE (survivors only). n_skeptics
     INDEPENDENT Qwen skeptics (a different model family than the Gemma
     that generated the finding — the anti-D-036 lever against same-model
     agreement) each attack the claim AND its evidence, LICENSED to use
     outside knowledge (NOT retrieval-bounded). A finding is promoted iff a
     quorum returned a verdict and only a minority refuted. Qwen failures
     (timeout / schema_mismatch / error) are counted and observable; they
     are NOT counted as refuted, and an unmet quorum yields a near_miss
     (inconclusive), never a silent promote.

  3. SYNTHESIS. One cheap Gemma call_sync drafts why_it_matters /
     what_would_change_it. On any failure it falls back to a deterministic
     stub — synthesis never blocks a promotion.

Idempotent: finding_id = "sf-" + source_iteration_id; already-surfaced ids
are skipped. Each promoted finding is schema-validated then appended to
surfaced_path. dry_run skips the write.

Reuses: orchestrator.subagent.run_subagent (backend="vllm-qwen") for the
skeptics; agent_wrapper.wrapper.call_sync for synthesis; the loop_memory
tail-read + loop_feedback join pattern from workers.meta_review.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema

from agent_wrapper.backends import get_backend
from agent_wrapper.wrapper import DEFAULT_BACKEND, call_sync, set_run_id
from orchestrator import active_run
from orchestrator.subagent import SubAgentBudget, run_subagent

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOOP_MEMORY = REPO_ROOT / "memory" / "loop_memory.jsonl"
DEFAULT_FEEDBACK = REPO_ROOT / "memory" / "loop_feedback.jsonl"
DEFAULT_SURFACED = REPO_ROOT / "memory" / "surfaced_findings.jsonl"
SCHEMA_PATH = REPO_ROOT / "schema" / "surfaced_finding.schema.json"

_SCHEMA = json.loads(SCHEMA_PATH.read_text())
_VALIDATOR = jsonschema.Draft7Validator(_SCHEMA)

CALLS_LOG_PATH = os.environ.get("LOOP_V0_CALLS_LOG", "logs/calls.jsonl")


def _frontier_screen_enabled() -> bool:
    """D-061: when NARA_FRONTIER_SCREEN=1 the frontier opposed-jobs review
    (Claude=methods / Codex=novelty) runs as a VETO stage between the cheap
    gate and the local Qwen vote. A veto is an attention filter: it near-misses
    the candidate with both reviews attached; survivors carry the reviews as
    an annotation. DARK by default — unset leaves the funnel frontier-free.
    (The retired NARA_PROMOTION_VOTE_ADVISORY flip is superseded by the
    evidence ladder, D-059: the vote is now the L3->L4 rung, neither a binary
    gate nor a non-gating advisory.)"""
    return os.environ.get("NARA_FRONTIER_SCREEN") == "1"


def _max_candidates_override(max_candidates: int | None) -> int | None:
    """D-053: NARA_PROMOTION_MAX_CANDIDATES, when set to a valid int, lifts/
    overrides the caller's max_candidates cap (for the cost-bounded cargo
    experiment). Unset or unparseable -> the caller's value unchanged (DARK
    default). Never silently coerces a bad value — a non-int env is ignored,
    not clamped."""
    raw = os.environ.get("NARA_PROMOTION_MAX_CANDIDATES")
    if raw is None or raw.strip() == "":
        return max_candidates
    try:
        return int(raw)
    except ValueError:
        return max_candidates

# A finding's experiment evidence must clear this trial floor to be
# trustworthy enough to surface (matches the loop's "trials>=30" bar).
MIN_TRIALS = 30

# "Surprising-vs-theory" detector: a NO verdict or a signed residual in the
# experiment summary means the result ran against expectation, which is
# exactly what makes an "unclear" novelty worth surfacing.
_SURPRISE_RE = re.compile(r"Verdict=NO|signed_residual", re.IGNORECASE)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_jsonl(path: str | os.PathLike) -> list[dict[str, Any]]:
    """Read a JSONL file into a list of dicts. Missing file -> []. Skips
    blank and malformed lines (mirrors workers.meta_review._read_jsonl)."""
    rows: list[dict[str, Any]] = []
    p = Path(path)
    if not p.exists():
        return rows
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


def _sub(row: dict[str, Any], key: str) -> dict[str, Any]:
    """row[key] when it's a dict, else {}. Loop-memory leaves stage fields
    None until that stage has run (mirrors workers.meta_review._sub)."""
    v = row.get(key)
    return v if isinstance(v, dict) else {}


DEFAULT_IDEA_LEDGER = REPO_ROOT / "memory" / "idea_ledger.jsonl"
_LEDGER_STATE_CACHE: dict[str, Any] = {}


def _ledger_cluster_for(iteration_id: str) -> str | None:
    """cluster_id whose members include this iteration, or None. A missing/
    unreadable ledger is a legitimate pre-consolidation state — fail-open to
    None (the finding still records evidence_level; only the cluster join is
    absent). Cached per (path, mtime) so the loop doesn't re-reduce."""
    path = DEFAULT_IDEA_LEDGER
    try:
        key = f"{path}:{path.stat().st_mtime_ns}"
    except OSError:
        return None
    if key not in _LEDGER_STATE_CACHE:
        try:
            from workers.idea_ledger import load_state
            _LEDGER_STATE_CACHE.clear()
            _LEDGER_STATE_CACHE[key] = load_state(path)
        except Exception:
            return None
    state = _LEDGER_STATE_CACHE[key]
    for cid, cluster in state.items():
        if iteration_id in (cluster.get("members") or []):
            return cid
    return None


def _record_level_event(iteration_id: str, level: str, errors: list[str]) -> None:
    """Append an evidence_level_changed event for the promoted iteration's
    cluster. No cluster (pre-consolidation) -> no-op; a write failure is
    RECORDED in errors (explicit, never silent) but doesn't block promotion."""
    cid = _ledger_cluster_for(iteration_id)
    if cid is None:
        return
    try:
        from workers.idea_ledger import append_event
        append_event(DEFAULT_IDEA_LEDGER, {
            "event_type": "evidence_level_changed",
            "ts": _utcnow_iso(),
            "cluster_id": cid,
            "evidence_level": level,
            "basis": f"promotion:{iteration_id}",
        })
        _LEDGER_STATE_CACHE.clear()
    except Exception as exc:
        errors.append(f"{iteration_id}: idea-ledger level event failed: {exc}")


# ── 1. cheap threshold gate ──────────────────────────────────────────


def _passes_threshold(
    row: dict[str, Any], human_verdict: str | None
) -> tuple[bool, str | None]:
    """Pure-Python gate, D-059: the cheap gate IS the evidence ladder.

    Pass conditions:
      - no human "invalid" verdict on this iteration, AND
      - derivable evidence level >= L1 (literature-consistent: relevance ok,
        novelty novel — or unclear + surprising-vs-theory, which the ladder's
        L1 rung itself admits — critique survives, redteam != fatal_flaw:
        the ladder consults the negative signals the old threshold ignored).
    """
    from workers.evidence_ladder import LEVELS, derive_level

    if human_verdict == "invalid":
        return False, "human verdict is 'invalid'"

    feedback_row = {"verdict": human_verdict} if human_verdict else None
    derived = derive_level(row, feedback_row, None, [])
    if LEVELS.index(derived["level"]) >= LEVELS.index("L1"):
        return True, None
    missing = "; ".join(derived["missing_for_next"]) or "below L1"
    return False, f"evidence ladder {derived['level']} < L1 ({missing})"


# ── 2. cross-model adversarial multi-vote ────────────────────────────


SKEPTIC_SYSTEM_PROMPT = (
    "You are an INDEPENDENT adversarial skeptic in the a_bgt_rsi research\n"
    "apparatus. A claim and its supporting evidence are presented to you.\n"
    "They were produced by a DIFFERENT model; your job is to try to REFUTE\n"
    "them, not to agree.\n"
    "\n"
    "You are EXPLICITLY LICENSED TO USE YOUR OWN OUTSIDE KNOWLEDGE — known\n"
    "theorems, established results, standard methodology. You are NOT bound\n"
    "to the retrieved literature or to what the claim's authors saw. Bring\n"
    "everything you know to bear.\n"
    "\n"
    "Attack the claim AND the evidence directly. Concretely ask:\n"
    "  - MIS-MEASUREMENT: does the metric actually measure the claimed\n"
    "    quantity, or something else?\n"
    "  - WITHIN-NOISE: given the number of trials, is the effect plausibly\n"
    "    just sampling noise?\n"
    "  - CONFOUND: is there an artifact — e.g. a parse failure, a leaked\n"
    "    prompt, a degenerate baseline — that manufactures the result?\n"
    "  - CONTRADICTION: does the claim contradict a known theorem or a\n"
    "    well-established empirical finding?\n"
    "\n"
    "If after your strongest attack the claim still stands, say so honestly.\n"
    "A skeptic who refutes everything is as useless as one who agrees with\n"
    "everything.\n"
    "\n"
    "Emit a FINAL assistant message that is STRICT JSON, nothing else — no\n"
    "prose, no markdown fences, no channel markers. Schema:\n"
    "{\n"
    '  "verdict": "refuted" | "stands",\n'
    '  "attack": "<2-4 sentences: the strongest attack you mounted>",\n'
    '  "confidence": <float 0.0-1.0>\n'
    "}\n"
)

_SKEPTIC_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["verdict", "attack", "confidence"],
    "properties": {
        "verdict": {"type": "string", "enum": ["refuted", "stands"]},
        "attack": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
    "additionalProperties": True,
}


def _skeptic_user_prompt(row: dict[str, Any], claim: str) -> str:
    novelty = _sub(row, "novelty")
    critique = _sub(row, "critique")
    exp = _sub(row, "experiment_outcome")
    parts = [
        f"CLAIM:\n{claim}",
        "",
        f"Novelty classification: {novelty.get('class')!r} — "
        f"{str(novelty.get('rationale') or '')[:600]}",
        f"Automated critic verdict: {critique.get('verdict')!r} — "
        f"{str(critique.get('rationale') or '')[:600]}",
    ]
    if exp:
        parts += [
            "",
            "EXPERIMENT EVIDENCE:",
            f"  experiment_id: {exp.get('experiment_id')}",
            f"  metric: {exp.get('metric')}  value: {exp.get('value')}",
            f"  trials: {exp.get('trials')}",
            f"  summary: {str(exp.get('summary') or '')[:600]}",
        ]
    parts += ["", "Mount your strongest attack, then emit the final JSON verdict."]
    return "\n".join(parts)


def _adversarial_vote(
    row: dict[str, Any],
    claim: str,
    *,
    n_skeptics: int,
    backend: str,
    parent_request_id: str | None,
) -> dict[str, Any]:
    """Run n_skeptics independent Qwen skeptics. Returns a tally dict:

      {n_voting, n_refuted, adversarial_margin, survived, qwen_failures,
       refutation_summaries}

    - A skeptic that returns a valid verdict counts toward n_voting.
    - A "refuted" verdict counts toward n_refuted (and its attack is kept).
    - A failure (timeout / schema_mismatch / error / missing-verdict) counts
      toward qwen_failures and is NOT a refutation.
    - quorum = majority of n_skeptics (floor(n/2)+1). survived iff
      n_voting >= quorum AND minority refuted (2 * n_refuted < n_voting).
    - adversarial_margin = n_voting - 2 * n_refuted.
    """
    user_prompt = _skeptic_user_prompt(row, claim)
    # Qwen3.6 is a reasoning model served with --reasoning-parser: its
    # chain-of-thought consumes the per-turn token budget before the final
    # JSON, so the default 1024 truncates the {verdict,attack,confidence}
    # answer. Give it headroom + an extra turn for the repair-retry, and a
    # wider wall budget for the slower 27B reasoning model.
    budget = SubAgentBudget(
        max_turns=4, max_wall_seconds=240.0, max_tokens_per_turn=3072
    )

    n_voting = 0
    n_refuted = 0
    qwen_failures = 0
    refutation_summaries: list[str] = []

    for i in range(n_skeptics):
        sa = run_subagent(
            name=f"finding_skeptic_{i + 1}",
            system_prompt=SKEPTIC_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            expected_output_schema=_SKEPTIC_OUTPUT_SCHEMA,
            budget=budget,
            parent_request_id=parent_request_id,
            backend=backend,
            log_path=CALLS_LOG_PATH,
        )
        if sa.status != "passed" or not isinstance(sa.result, dict):
            qwen_failures += 1
            continue
        verdict = sa.result.get("verdict")
        if verdict not in ("refuted", "stands"):
            qwen_failures += 1
            continue
        n_voting += 1
        if verdict == "refuted":
            n_refuted += 1
            attack = str(sa.result.get("attack") or "").strip()
            if attack:
                refutation_summaries.append(attack[:1000])

    quorum = n_skeptics // 2 + 1
    margin = n_voting - 2 * n_refuted
    survived = n_voting >= quorum and (2 * n_refuted < n_voting)

    return {
        "n_voting": n_voting,
        "n_refuted": n_refuted,
        "adversarial_margin": margin,
        "survived": survived,
        "qwen_failures": qwen_failures,
        "refutation_summaries": refutation_summaries,
        "quorum": quorum,
    }


# ── 3. synthesis (cheap Gemma call, deterministic fallback) ──────────


_SYNTH_SYSTEM_PROMPT = (
    "You are the FINDING-SYNTHESIS worker in the a_bgt_rsi apparatus. Given a\n"
    "research claim and its evidence, write two short fields for a human\n"
    "reviewer:\n"
    "  - why_it_matters: one or two sentences on why this finding is worth a\n"
    "    human's attention.\n"
    "  - what_would_change_it: one or two sentences on the single piece of\n"
    "    evidence that would most change the verdict.\n"
    "\n"
    "Output STRICT JSON, nothing else — no prose, no fences, no channel\n"
    "markers. Schema:\n"
    "{\n"
    '  "why_it_matters": "<string>",\n'
    '  "what_would_change_it": "<string>"\n'
    "}\n"
)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Balanced-brace JSON scanner (mirrors workers.meta_review)."""
    if not isinstance(text, str):
        return None
    start = text.find("{")
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
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _synthesize(
    claim: str, row: dict[str, Any], *, parent_request_id: str | None
) -> tuple[str, str]:
    """ONE cheap Gemma call for why_it_matters / what_would_change_it.
    Any failure -> deterministic fallback. Synthesis never blocks promotion."""
    fallback_why = (
        f"Survived the cross-model adversarial vote: {claim[:200]}"
    )
    fallback_change = (
        "A direct refutation surviving an independent adversarial replication, "
        "or a human 'invalid' verdict on the iteration."
    )
    user = (
        f"CLAIM:\n{claim}\n\n"
        f"Novelty: {_sub(row, 'novelty').get('class')!r}. "
        f"Critic: {_sub(row, 'critique').get('verdict')!r}.\n"
    )
    exp = _sub(row, "experiment_outcome")
    if exp:
        user += (
            f"Experiment {exp.get('experiment_id')}: "
            f"{str(exp.get('summary') or '')[:400]}\n"
        )
    user += "\nWrite the two fields as strict JSON."

    try:
        record = call_sync(
            [
                {"role": "system", "content": _SYNTH_SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            top_p=0.9,
            max_tokens=256,
            caller_tag="finding_promotion.synthesize",
            parent_request_id=parent_request_id,
            log_path=CALLS_LOG_PATH,
        )
    except Exception:
        return fallback_why, fallback_change

    payload = _extract_json_object(record.get("completion") or "")
    if not isinstance(payload, dict):
        return fallback_why, fallback_change
    why = payload.get("why_it_matters")
    change = payload.get("what_would_change_it")
    why = why.strip() if isinstance(why, str) and why.strip() else fallback_why
    change = (
        change.strip()
        if isinstance(change, str) and change.strip()
        else fallback_change
    )
    return why, change


# ── candidate field extraction ───────────────────────────────────────


def _claim_text(row: dict[str, Any]) -> str:
    hyp = _sub(row, "hypothesis").get("text")
    if isinstance(hyp, str) and hyp.strip():
        return hyp.strip()
    topic = _sub(row, "seed").get("topic")
    if isinstance(topic, str) and topic.strip():
        return topic.strip()
    return "(no hypothesis text)"


def _title_text(row: dict[str, Any]) -> str:
    topic = _sub(row, "seed").get("topic")
    if isinstance(topic, str) and topic.strip():
        return topic.strip()[:200]
    return _claim_text(row)[:200]


# ── orchestration ────────────────────────────────────────────────────


def promote_findings(
    *,
    loop_memory_path: str | os.PathLike = DEFAULT_LOOP_MEMORY,
    feedback_path: str | os.PathLike = DEFAULT_FEEDBACK,
    surfaced_path: str | os.PathLike = DEFAULT_SURFACED,
    since: str | None = None,
    max_candidates: int | None = None,
    n_skeptics: int = 3,
    backend: str = "vllm-qwen",
    dry_run: bool = False,
    parent_request_id: str | None = None,
) -> dict[str, Any]:
    """Run the full promotion funnel. Returns:

    ```
    {
        "promoted": [<surfaced_finding row>, ...],
        "examined": int,
        "near_misses": [{"source_iteration_id", "reason", "stage"}, ...],
        "skipped_already_surfaced": int,
        "qwen_failures": int,        # summed across all voted candidates
        "errors": [str, ...],
    }
    ```

    Never silent-drops (every reject is a near_miss) and never silent-promotes
    (an unmet quorum is inconclusive -> near_miss).
    """
    # UI observability: announce this promotion pass as the active run so it
    # shows in the UI like the other run modes. set_run_id stamps every wrapper
    # call (synthesis + the Qwen skeptics) in this pass; cleared in finally.
    run_id = f"promote_findings_{uuid.uuid4().hex[:8]}"
    set_run_id(run_id)
    active_run.write_active_run(run_id, kind="ad_hoc", label="promote_findings")
    try:
        return _promote_findings(
            loop_memory_path=loop_memory_path,
            feedback_path=feedback_path,
            surfaced_path=surfaced_path,
            since=since,
            max_candidates=max_candidates,
            n_skeptics=n_skeptics,
            backend=backend,
            dry_run=dry_run,
            parent_request_id=parent_request_id,
        )
    finally:
        active_run.clear_active_run()
        set_run_id(None)


def _promote_findings(
    *,
    loop_memory_path: str | os.PathLike,
    feedback_path: str | os.PathLike,
    surfaced_path: str | os.PathLike,
    since: str | None,
    max_candidates: int | None,
    n_skeptics: int,
    backend: str,
    dry_run: bool,
    parent_request_id: str | None,
) -> dict[str, Any]:
    """Inner funnel body. See promote_findings for the contract."""
    rows = _read_jsonl(loop_memory_path)
    feedback = {
        f["iteration_id"]: f
        for f in _read_jsonl(feedback_path)
        if isinstance(f.get("iteration_id"), str)
    }
    # Health rows feed derive_level's `provisional` marker (e.g. a finding
    # whose L1 rests on a blind external search carries
    # external_search_blind). Resolved at call time via the cycle-log module
    # attr so the conftest tmp-path patch applies (2026-08-14 review: this
    # was previously always [] — the marker could never reach a finding).
    try:
        from orchestrator import coordinator_cycle_log as _ccl
        health_rows = _read_jsonl(_ccl.DEFAULT_HEALTH_PATH)
    except Exception:
        health_rows = []
    already = {
        r.get("finding_id")
        for r in _read_jsonl(surfaced_path)
        if isinstance(r.get("finding_id"), str)
    }

    promoted: list[dict[str, Any]] = []
    near_misses: list[dict[str, Any]] = []
    errors: list[str] = []
    examined = 0
    skipped_already_surfaced = 0
    total_qwen_failures = 0

    # ── pass A: cheap gate over every candidate (apply `since` filter) ──
    survivors: list[dict[str, Any]] = []
    for row in rows:
        iid = row.get("iteration_id")
        if not isinstance(iid, str) or not iid:
            continue
        if since is not None and iid < since:
            continue
        examined += 1

        if ("sf-" + iid) in already:
            skipped_already_surfaced += 1
            continue

        human_verdict = (feedback.get(iid) or {}).get("verdict")
        passes, reason = _passes_threshold(row, human_verdict)
        if not passes:
            near_misses.append(
                {"source_iteration_id": iid, "reason": reason, "stage": "threshold"}
            )
            continue
        survivors.append(row)

    # Cap AFTER the gate — load-bearing: this bounds the expensive Qwen vote.
    # D-053: NARA_PROMOTION_MAX_CANDIDATES (when set) lifts/overrides the cap
    # for the cargo experiment; unset = the caller's value (DARK default).
    max_candidates = _max_candidates_override(max_candidates)
    if max_candidates is not None and max_candidates >= 0:
        capped = survivors[max_candidates:]
        survivors = survivors[:max_candidates]
        for row in capped:
            near_misses.append({
                "source_iteration_id": row.get("iteration_id"),
                "reason": f"capped by max_candidates={max_candidates}",
                "stage": "threshold",
            })

    resolved_be = get_backend(backend or DEFAULT_BACKEND)

    # ── pass A2 (D-061, env-gated dark): frontier opposed-jobs veto ──
    # A veto is an attention filter, not evidence: it removes the candidate
    # from this pass with both reviews attached; survivors carry the reviews
    # as an annotation. Inconclusive/outage NEVER blocks (fail-open seam).
    frontier_reviews: dict[str, dict[str, Any]] = {}
    if _frontier_screen_enabled() and survivors:
        from agent_wrapper.frontier_cli import invoke_frontier
        from workers.frontier_review import screen_candidate
        still: list[dict[str, Any]] = []
        for row in survivors:
            iid = row["iteration_id"]
            try:
                screen = screen_candidate(
                    {"iteration_id": iid, "claim": _claim_text(row),
                     "novelty": _sub(row, "novelty"),
                     "critique": _sub(row, "critique"),
                     "experiment_outcome": _sub(row, "experiment_outcome") or None},
                    invoke_frontier,
                )
            except Exception as exc:  # outage = no veto, logged, never a block
                errors.append(f"{iid}: frontier screen error (fail-open): {exc}")
                still.append(row)
                continue
            if screen.get("verdict") == "veto":
                basis = ((screen.get("methods") or {}).get("reasoning")
                         or (screen.get("novelty") or {}).get("reasoning")
                         or "no reasoning returned")
                near_misses.append({
                    "source_iteration_id": iid,
                    "reason": f"frontier opposed-jobs veto: {str(basis)[:200]}",
                    "stage": "frontier",
                    "frontier_screen": screen,
                })
                continue
            frontier_reviews[iid] = screen
            still.append(row)
        survivors = still

    # ── pass B: adversarial multi-vote over survivors (D-059: the vote IS
    # the L3->L4 rung test — it runs ONLY on candidates already at L3, and
    # surfacing requires the post-vote derived level to reach L4+, which
    # consults BOTH previously-ignored negatives: the vote outcome and
    # redteam.verdict. Below-L3 candidates are near-missed with the exact
    # test they owe — the coordinator's ladder-gap signal). ──
    from workers.evidence_ladder import derive_level, next_test_owed

    for row in survivors:
        iid = row["iteration_id"]
        claim = _claim_text(row)

        pre = derive_level(row, feedback.get(iid), None, health_rows)
        if pre["level"] != "L3":
            missing = "; ".join(pre["missing_for_next"]) or "unmet rungs"
            near_misses.append({
                "source_iteration_id": iid,
                "reason": (
                    f"evidence ladder {pre['level']} < L3 — adversarial vote "
                    f"deferred (owes: {next_test_owed(pre['level'])}; "
                    f"missing: {missing})"
                ),
                "stage": "ladder",
            })
            continue

        tally = _adversarial_vote(
            row,
            claim,
            n_skeptics=n_skeptics,
            backend=backend,
            parent_request_id=parent_request_id,
        )
        total_qwen_failures += tally["qwen_failures"]

        if tally["n_voting"] < tally["quorum"]:
            near_misses.append({
                "source_iteration_id": iid,
                "reason": (
                    f"inconclusive: quorum unmet "
                    f"(n_voting={tally['n_voting']} < quorum={tally['quorum']}, "
                    f"qwen_failures={tally['qwen_failures']})"
                ),
                "stage": "adversarial",
            })
            continue
        if not tally["survived"]:
            near_misses.append({
                "source_iteration_id": iid,
                "reason": (
                    f"refuted by adversarial vote "
                    f"(n_refuted={tally['n_refuted']} of n_voting={tally['n_voting']}, "
                    f"margin={tally['adversarial_margin']})"
                ),
                "stage": "adversarial",
            })
            continue

        derived = derive_level(
            row,
            feedback.get(iid),
            {"survived": tally["survived"]},
            health_rows,
        )
        if derived["level"] not in ("L4", "L5"):
            near_misses.append({
                "source_iteration_id": iid,
                "reason": (
                    f"evidence ladder {derived['level']} < L4 "
                    f"({'; '.join(derived['missing_for_next']) or 'unmet rungs'})"
                ),
                "stage": "ladder",
            })
            continue

        # Promote: only true L4+ survivors reach here.
        why, change = _synthesize(claim, row, parent_request_id=parent_request_id)
        exp = _sub(row, "experiment_outcome")
        finding = {
            "finding_id": "sf-" + iid,
            "source_iteration_id": iid,
            "title": _title_text(row),
            "claim": claim,
            "tier": None,
            "evidence": {
                "journal_entry_path": row.get("journal_entry_path") or "",
                "results_path": exp.get("results_path") if exp else None,
                "experiment_outcome": exp or None,
                "critic_rationale": str(_sub(row, "critique").get("rationale") or ""),
                "novelty_rationale": str(_sub(row, "novelty").get("rationale") or ""),
                "human_verdict": (feedback.get(iid) or {}).get("verdict"),
            },
            "novelty_class": _sub(row, "novelty").get("class"),
            "critic_verdict": _sub(row, "critique").get("verdict"),
            "adversarial": {
                "model": resolved_be.default_model,
                "backend": resolved_be.name,
                "n_skeptics": n_skeptics,
                "n_voting": tally["n_voting"],
                "n_refuted": tally["n_refuted"],
                "adversarial_margin": tally["adversarial_margin"],
                "survived": tally["survived"],
                "qwen_failures": tally["qwen_failures"],
                "refutation_summaries": tally["refutation_summaries"],
            },
            "why_it_matters": why,
            "what_would_change_it": change,
            "promoted_at": _utcnow_iso(),
            "status": "surfaced",
            # D-059/D-060 additive fields (surfaced_finding schema keeps
            # additionalProperties: true — no schema edit needed).
            "evidence_level": derived["level"],
            "cluster_id": _ledger_cluster_for(iid),
        }
        if derived.get("provisional"):
            finding["evidence_provisional"] = derived["provisional"]
        if iid in frontier_reviews:
            finding["frontier_screen"] = frontier_reviews[iid]

        errs = list(_VALIDATOR.iter_errors(finding))
        if errs:
            errors.append(
                f"{iid}: surfaced_finding failed schema validation: "
                f"{errs[0].message} (path: {list(errs[0].absolute_path)})"
            )
            near_misses.append({
                "source_iteration_id": iid,
                "reason": f"schema validation failed: {errs[0].message}",
                "stage": "schema",
            })
            continue

        if not dry_run:
            sp = Path(surfaced_path)
            sp.parent.mkdir(parents=True, exist_ok=True)
            with open(sp, "a") as fh:
                fh.write(json.dumps(finding, ensure_ascii=False) + "\n")
            _record_level_event(iid, derived["level"], errors)
        already.add(finding["finding_id"])
        promoted.append(finding)

    return {
        "promoted": promoted,
        "examined": examined,
        "near_misses": near_misses,
        "skipped_already_surfaced": skipped_already_surfaced,
        "qwen_failures": total_qwen_failures,
        "errors": errors,
    }


# ── CLI ──────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Promote loop findings through the multi-threshold + "
                    "cross-model adversarial vote funnel."
    )
    p.add_argument("--since", default=None,
                   help="Only consider iterations with id >= this value.")
    p.add_argument("--max-candidates", type=int, default=None,
                   help="Cap survivors sent to the expensive vote (applied "
                        "AFTER the cheap gate).")
    p.add_argument("--n-skeptics", type=int, default=3)
    p.add_argument("--backend", default="vllm-qwen")
    p.add_argument("--dry-run", action="store_true",
                   help="Run the funnel but do not write to surfaced_path.")
    p.add_argument("--show-near-misses", action="store_true",
                   help="Print the near-miss list (with reasons).")
    args = p.parse_args(argv)

    out = promote_findings(
        since=args.since,
        max_candidates=args.max_candidates,
        n_skeptics=args.n_skeptics,
        backend=args.backend,
        dry_run=args.dry_run,
    )

    print(
        f"examined={out['examined']} "
        f"promoted={len(out['promoted'])} "
        f"near_misses={len(out['near_misses'])} "
        f"skipped_already_surfaced={out['skipped_already_surfaced']} "
        f"qwen_failures={out['qwen_failures']}"
    )
    for f in out["promoted"]:
        print(f"  PROMOTED {f['finding_id']}: {f['title']} "
              f"(margin={f['adversarial']['adversarial_margin']})")
    if args.show_near_misses or not out["promoted"]:
        for nm in out["near_misses"]:
            print(f"  near_miss [{nm['stage']}] {nm['source_iteration_id']}: "
                  f"{nm['reason']}")
    for e in out["errors"]:
        print(f"  ERROR: {e}", file=sys.stderr)
    # Exit 0 even on 0 promoted — near-misses are informational, not failures.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
