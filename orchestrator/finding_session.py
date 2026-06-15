"""Rubberbanding-session engine — LLM-grounded interrogation of a promoted finding.

A finding that survived the LOOP_V0 chain (novelty + adversarial critique + a
human gate) gets *promoted* into `memory/surfaced_findings.jsonl`. Promotion is
not the end of scrutiny: a human can sit down and interrogate the finding in a
multi-turn chat — push on it, try to break it, see whether it holds up or
"rubberbands" back under pressure. This module is that interrogation engine.

Why `call_sync`, NOT `run_subagent`: the sub-agent harness terminates on the
first valid JSON emission (it's built to extract one structured verdict). An
interrogation is an open-ended conversation, so we drive the wrapper's plain
chat completion directly and replay the transcript ourselves.

Backend: defaults to `vllm-qwen` so the defender is a *different* model than
the Gemma generator that produced the finding — the human isn't re-asking the
same weights to grade their own homework. Gemma is selectable per call.

Storage (append-only, stateless): one JSONL transcript per session at
`memory/finding_sessions/<finding_id>/<session_id>.jsonl`. Every call replays
the JSONL into a message stack — there is no in-process session object. Event
rows: system_seed | user | assistant | feedback | spawn | refine.

Three feedback paths on end_session, all LOGGED, none a silent mutation:
  (a) validated / rejected  -> gate_cli.append_feedback (valid/invalid) AND a
                               status-audit row to surfaced_findings.status.jsonl
  (b) spawn_topic           -> a row on finding_followups.jsonl (a queue; this
                               module does NOT run the loop)
  (c) refine                -> status in_review, refined claim carried in reason
We NEVER edit surfaced_findings.jsonl in place. Effective status = last audit
row for the finding_id.
"""
from __future__ import annotations

import argparse
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_wrapper.wrapper import call_sync, set_run_id
from orchestrator import active_run, gate_cli

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SURFACED = REPO_ROOT / "memory" / "surfaced_findings.jsonl"
DEFAULT_LOOP_MEMORY = REPO_ROOT / "memory" / "loop_memory.jsonl"
DEFAULT_SESSIONS_ROOT = REPO_ROOT / "memory" / "finding_sessions"
DEFAULT_STATUS_AUDIT = REPO_ROOT / "memory" / "surfaced_findings.status.jsonl"
DEFAULT_FOLLOWUPS = REPO_ROOT / "memory" / "finding_followups.jsonl"

CALLS_LOG_PATH = os.environ.get("LOOP_V0_CALLS_LOG", "logs/calls.jsonl")

DEFAULT_BACKEND = "vllm-qwen"
MAX_TURNS = 24

# Two-voice interrogation (additive to the single-defender path above).
# Gemma authored the findings, so Gemma DEFENDS (vllm-gemma); the standing
# independent skeptic Qwen ATTACKS (vllm-qwen) — D-044 independence: the
# interrogator must not be the authoring model. Each stance keeps its own
# seeded backend so they never collapse into the same judge.
DEFENDER_STANCE = "defender"
ATTACKER_STANCE = "attacker"
STANCES = (DEFENDER_STANCE, ATTACKER_STANCE)
STANCE_BACKEND = {DEFENDER_STANCE: "vllm-gemma", ATTACKER_STANCE: "vllm-qwen"}
# A two-voice turn may address one stance or BOTH (both = one turn).
ADDRESSEES = (DEFENDER_STANCE, ATTACKER_STANCE, "both")

OUTCOMES = ("validated", "rejected", "spawn_topic", "refine", "abandoned")
# Maps a terminal interrogation outcome to the loop_feedback verdict enum.
# Only validated/rejected feed the human-gate edge; the rest do not.
_OUTCOME_TO_VERDICT = {"validated": "valid", "rejected": "invalid"}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_jsonl(path: str | os.PathLike) -> list[dict[str, Any]]:
    """Read a JSONL file into a list of dicts. Missing file -> []. Skips blank
    and malformed lines (never crashes on a partial write)."""
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


def _append_jsonl(path: str | os.PathLike, row: dict[str, Any]) -> None:
    """Append-only single-row write (creates parent dirs on first call)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _session_path(finding_id: str, session_id: str, sessions_root) -> Path:
    return Path(sessions_root) / finding_id / f"{session_id}.jsonl"


def _load_finding(finding_id: str, surfaced_path) -> dict[str, Any]:
    """Find the surfaced_finding row by finding_id. Last write wins (the file
    is append-only). Raises KeyError if absent."""
    found = None
    for row in _read_jsonl(surfaced_path):
        if row.get("finding_id") == finding_id:
            found = row
    if found is None:
        raise KeyError(
            f"no surfaced_finding with finding_id={finding_id!r} in {surfaced_path}"
        )
    return found


def _join_iteration(iteration_id: str | None, loop_memory_path) -> dict[str, Any]:
    """Join the source iteration_record by iteration_id. Last write wins.
    Returns {} when the finding carries no iteration_id or no match exists —
    the seed degrades gracefully rather than failing the interrogation."""
    if not iteration_id:
        return {}
    found = {}
    for row in _read_jsonl(loop_memory_path):
        if row.get("iteration_id") == iteration_id:
            found = row
    return found


def _read_journal_text(record: dict[str, Any]) -> str:
    """Read the journal entry text for the iteration, if its path is present
    and the file exists. Missing -> '' (seed degrades gracefully)."""
    rel = record.get("journal_entry_path")
    if not rel:
        return ""
    p = Path(rel)
    if not p.is_absolute():
        p = REPO_ROOT / rel
    if not p.exists():
        return ""
    return p.read_text()


def _refutation_summaries(finding: dict[str, Any],
                          record: dict[str, Any]) -> list[str]:
    """Gather the adversarial attacks the finding already survived.

    Two sources, in priority order:
      1. an explicit `refutation_summaries` list on the surfaced_finding;
      2. the `redteam`/`critique` blocks on the source iteration_record
         (the skeptic critiques the loop already ran).
    Returns a de-duplicated list of non-empty strings."""
    out: list[str] = []
    explicit = finding.get("refutation_summaries")
    if isinstance(explicit, list):
        out.extend(s for s in explicit if isinstance(s, str) and s.strip())
    redteam = record.get("redteam")
    if isinstance(redteam, dict):
        crit = redteam.get("critique")
        if isinstance(crit, str) and crit.strip():
            verdict = redteam.get("verdict")
            out.append(f"[redteam verdict={verdict}] {crit.strip()}")
    critique = record.get("critique")
    if isinstance(critique, dict):
        rat = critique.get("rationale")
        if isinstance(rat, str) and rat.strip():
            verdict = critique.get("verdict")
            out.append(f"[literature-critic verdict={verdict}] {rat.strip()}")
    # De-dup, preserve order.
    seen: set[str] = set()
    deduped: list[str] = []
    for s in out:
        if s not in seen:
            seen.add(s)
            deduped.append(s)
    return deduped


def _build_seed(finding: dict[str, Any], record: dict[str, Any],
                journal_text: str, refutations: list[str]) -> str:
    """Compose the system-prompt SEED for the defender."""
    claim = (
        finding.get("claim")
        or finding.get("text")
        or (record.get("hypothesis") or {}).get("text")
        or "(no claim text on the surfaced finding)"
    )
    exp = record.get("experiment_outcome")
    evidence_lines: list[str] = []
    if isinstance(exp, dict):
        metric = exp.get("metric")
        value = exp.get("value")
        trials = exp.get("trials")
        summary = exp.get("summary")
        bits = []
        if metric is not None:
            bits.append(f"metric={metric}")
        if value is not None:
            bits.append(f"value={value}")
        if trials is not None:
            bits.append(f"trials={trials}")
        if bits:
            evidence_lines.append("Experiment outcome: " + ", ".join(str(b) for b in bits))
        if isinstance(summary, str) and summary.strip():
            evidence_lines.append("Experiment summary: " + summary.strip())
    nov = record.get("novelty")
    if isinstance(nov, dict) and nov.get("class"):
        evidence_lines.append(f"Novelty classification: {nov.get('class')}")

    refutation_block = (
        "\n".join(f"  {i + 1}. {r}" for i, r in enumerate(refutations))
        if refutations else "  (none recorded)"
    )
    evidence_block = "\n".join(f"  - {e}" for e in evidence_lines) or "  (no structured evidence captured)"
    journal_block = journal_text.strip()[:4000] if journal_text.strip() else "(no journal entry text)"

    return (
        "You are defending a PROMOTED research finding under human "
        "interrogation in the a_bgt_rsi apparatus.\n"
        "\n"
        "This finding already passed the loop's automated chain and a human "
        f"gate. {len(refutations)} skeptic attack(s) were mounted against it "
        "and it survived. The human is now sitting down to push on it harder, "
        "to see whether it holds up or rubberbands back under pressure.\n"
        "\n"
        "Your job is to defend it HONESTLY. Concede where the evidence is "
        "thin. Cite the specific metric, value, and trial-count when you make "
        "a claim of strength. Do NOT overclaim, do NOT invent evidence that is "
        "not in the record below, and do NOT restate the claim more strongly "
        "than the evidence supports.\n"
        "\n"
        f"THE CLAIM:\n  {claim}\n"
        "\n"
        f"EVIDENCE ON RECORD:\n{evidence_block}\n"
        "\n"
        f"ATTACKS ALREADY MOUNTED (and why it survived them):\n{refutation_block}\n"
        "\n"
        f"JOURNAL ENTRY:\n{journal_block}\n"
    )


def _build_skeptic_seed(finding: dict[str, Any], record: dict[str, Any],
                        journal_text: str, refutations: list[str]) -> str:
    """Compose the system-prompt SEED for the ATTACKER stance (Qwen).

    Analogous to `_build_seed` but framed to mount the strongest HONEST
    attack on the same claim. Fail-open in spirit with
    novelty_skeptic.attack(): the skeptic concedes only when the evidence
    forces it and NEVER fabricates a concession or invents evidence — an
    attack it cannot ground stays a stated uncertainty, not a false 'this
    holds' (the conversational mirror of attack()'s inconclusive-on-failure
    rule). The same claim/evidence/journal context blocks are shared so the
    two stances reason over the same record."""
    claim = (
        finding.get("claim")
        or finding.get("text")
        or (record.get("hypothesis") or {}).get("text")
        or "(no claim text on the surfaced finding)"
    )
    exp = record.get("experiment_outcome")
    evidence_lines: list[str] = []
    if isinstance(exp, dict):
        metric = exp.get("metric")
        value = exp.get("value")
        trials = exp.get("trials")
        summary = exp.get("summary")
        bits = []
        if metric is not None:
            bits.append(f"metric={metric}")
        if value is not None:
            bits.append(f"value={value}")
        if trials is not None:
            bits.append(f"trials={trials}")
        if bits:
            evidence_lines.append("Experiment outcome: " + ", ".join(str(b) for b in bits))
        if isinstance(summary, str) and summary.strip():
            evidence_lines.append("Experiment summary: " + summary.strip())
    nov = record.get("novelty")
    if isinstance(nov, dict) and nov.get("class"):
        evidence_lines.append(f"Novelty classification: {nov.get('class')}")

    refutation_block = (
        "\n".join(f"  {i + 1}. {r}" for i, r in enumerate(refutations))
        if refutations else "  (none recorded)"
    )
    evidence_block = "\n".join(f"  - {e}" for e in evidence_lines) or "  (no structured evidence captured)"
    journal_block = journal_text.strip()[:4000] if journal_text.strip() else "(no journal entry text)"

    return (
        "You are the INDEPENDENT SKEPTIC in the a_bgt_rsi apparatus — a "
        "DIFFERENT model from the one that generated this finding. The "
        "apparatus's own model authored and defends it; your job is to mount "
        "the strongest HONEST attack on the claim under human interrogation.\n"
        "\n"
        f"This finding already passed the loop's automated chain and a human "
        f"gate. {len(refutations)} skeptic attack(s) were mounted against it "
        "and it survived. Do not assume that settles it: the human wants the "
        "hardest remaining objection found.\n"
        "\n"
        "Attack it HONESTLY. Look for: thin or cherry-picked evidence, an "
        "over-stated claim the metric does not support, a confound the "
        "experiment did not rule out, or prior art the claim merely restates. "
        "Be specific — name the metric, value, or trial-count you are "
        "contesting. NEVER invent evidence that is not in the record below, "
        "and NEVER fabricate a concession that the claim holds: if you cannot "
        "ground an attack, say the evidence does not let you decide rather "
        "than conceding the point. A weak attack you cannot support is not an "
        "endorsement.\n"
        "\n"
        f"THE CLAIM (attack this):\n  {claim}\n"
        "\n"
        f"EVIDENCE ON RECORD:\n{evidence_block}\n"
        "\n"
        f"ATTACKS ALREADY MOUNTED (find a NEW or stronger one):\n{refutation_block}\n"
        "\n"
        f"JOURNAL ENTRY:\n{journal_block}\n"
    )


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #


def start_session(
    finding_id: str,
    *,
    backend: str = DEFAULT_BACKEND,
    surfaced_path: str | os.PathLike = DEFAULT_SURFACED,
    loop_memory_path: str | os.PathLike = DEFAULT_LOOP_MEMORY,
    sessions_root: str | os.PathLike = DEFAULT_SESSIONS_ROOT,
) -> dict[str, Any]:
    """Open a new interrogation session. Loads the surfaced finding, joins its
    source iteration_record, reads the journal entry + the adversarial
    refutation summaries, and writes a `system_seed` row. NO LLM call yet.

    Returns {session_id, finding}."""
    finding = _load_finding(finding_id, surfaced_path)
    # Promoted findings carry source_iteration_id (finding_promotion.py);
    # older/test rows carry iteration_id. Accept both — reading only
    # iteration_id silently dropped the source-iteration join (journal,
    # refutations) on every REAL promoted finding. Caught 2026-06-10.
    iteration_id = (finding.get("source_iteration_id")
                    or finding.get("iteration_id"))
    record = _join_iteration(iteration_id, loop_memory_path)
    journal_text = _read_journal_text(record)
    refutations = _refutation_summaries(finding, record)
    seed = _build_seed(finding, record, journal_text, refutations)

    session_id = "fs-" + uuid.uuid4().hex[:12]
    seed_row = {
        "type": "system_seed",
        "finding_id": finding_id,
        "session_id": session_id,
        "iteration_id": iteration_id,
        "backend": backend,
        "content": seed,
        "refutation_count": len(refutations),
        "at": _utcnow_iso(),
    }
    _append_jsonl(_session_path(finding_id, session_id, sessions_root), seed_row)
    return {"session_id": session_id, "finding": finding}


def start_two_voice_session(
    finding_id: str,
    *,
    surfaced_path: str | os.PathLike = DEFAULT_SURFACED,
    loop_memory_path: str | os.PathLike = DEFAULT_LOOP_MEMORY,
    sessions_root: str | os.PathLike = DEFAULT_SESSIONS_ROOT,
) -> dict[str, Any]:
    """Open a TWO-STANCE interrogation session: Gemma DEFENDS, Qwen ATTACKS.

    Additive to `start_session` (the single-defender path is unchanged). Loads
    the same finding context once and writes ONE `system_seed` row PER stance,
    each tagged with its `stance` and backend (defender=vllm-gemma honest
    defender; attacker=vllm-qwen honest skeptic). NO LLM call yet.

    Returns {session_id, finding, stances}."""
    finding = _load_finding(finding_id, surfaced_path)
    iteration_id = (finding.get("source_iteration_id")
                    or finding.get("iteration_id"))
    record = _join_iteration(iteration_id, loop_memory_path)
    journal_text = _read_journal_text(record)
    refutations = _refutation_summaries(finding, record)
    defender_seed = _build_seed(finding, record, journal_text, refutations)
    attacker_seed = _build_skeptic_seed(finding, record, journal_text, refutations)

    session_id = "fs-" + uuid.uuid4().hex[:12]
    now = _utcnow_iso()
    path = _session_path(finding_id, session_id, sessions_root)
    for stance, seed in ((DEFENDER_STANCE, defender_seed),
                         (ATTACKER_STANCE, attacker_seed)):
        _append_jsonl(path, {
            "type": "system_seed",
            "finding_id": finding_id,
            "session_id": session_id,
            "iteration_id": iteration_id,
            "stance": stance,
            "backend": STANCE_BACKEND[stance],
            "content": seed,
            "refutation_count": len(refutations),
            "at": now,
        })
    return {"session_id": session_id, "finding": finding, "stances": list(STANCES)}


def _replay_messages(rows: list[dict[str, Any]]) -> tuple[list[dict[str, str]], str | None]:
    """Replay a session transcript into an OpenAI message stack. Returns
    (messages, seed_backend). Only system_seed/user/assistant rows feed the
    chat stack; feedback/spawn/refine rows are audit-only."""
    messages: list[dict[str, str]] = []
    seed_backend: str | None = None
    for row in rows:
        rtype = row.get("type")
        if rtype == "system_seed":
            messages.append({"role": "system", "content": row.get("content", "")})
            seed_backend = row.get("backend")
        elif rtype == "user":
            messages.append({"role": "user", "content": row.get("content", "")})
        elif rtype == "assistant":
            messages.append({"role": "assistant", "content": row.get("content", "")})
    return messages, seed_backend


def _count_turns(rows: list[dict[str, Any]]) -> int:
    """A turn = one user message (each gets one assistant reply)."""
    return sum(1 for r in rows if r.get("type") == "user")


def session_turn(
    finding_id: str,
    session_id: str,
    user_msg: str,
    *,
    backend: str | None = None,
    sessions_root: str | os.PathLike = DEFAULT_SESSIONS_ROOT,
) -> dict[str, Any]:
    """One interrogation turn: replay -> append user -> call_sync -> append
    assistant. Stateless across calls (transcript is the only state).

    Bounded by MAX_TURNS: at the cap, returns an explicit cap reply and does
    NOT call the model (no silent continue). Returns {reply, request_id,
    turn_index}."""
    path = _session_path(finding_id, session_id, sessions_root)
    rows = _read_jsonl(path)
    if not rows or rows[0].get("type") != "system_seed":
        raise KeyError(
            f"no session transcript at {path} "
            f"(finding_id={finding_id!r}, session_id={session_id!r})"
        )

    prior_turns = _count_turns(rows)
    if prior_turns >= MAX_TURNS:
        cap_msg = (
            f"[session cap reached: {MAX_TURNS} turns] This interrogation has "
            "hit its bounded turn limit. End the session with a verdict "
            "(validate / reject / spawn / refine) rather than continuing."
        )
        return {"reply": cap_msg, "request_id": None, "turn_index": prior_turns}

    messages, seed_backend = _replay_messages(rows)
    messages.append({"role": "user", "content": user_msg})
    turn_index = prior_turns + 1

    # UI observability: announce this interrogation turn as the active run so
    # it shows in the UI like the other run modes. set_run_id stamps the
    # wrapper call below; both are cleared in finally (no stale state).
    run_id = f"finding_session_{session_id}"
    set_run_id(run_id)
    active_run.write_active_run(
        run_id, kind="ad_hoc", label=f"finding-session {finding_id}")
    use_backend = backend or seed_backend or DEFAULT_BACKEND
    try:
        record = call_sync(
            messages,
            temperature=0.3,
            top_p=0.9,
            max_tokens=1024,
            caller_tag="finding_session",
            log_path=CALLS_LOG_PATH,
            backend=use_backend,
        )
    finally:
        active_run.clear_active_run()
        set_run_id(None)
    reply = record.get("completion") or ""
    request_id = record.get("request_id")
    now = _utcnow_iso()

    _append_jsonl(path, {
        "type": "user", "finding_id": finding_id, "session_id": session_id,
        "turn_index": turn_index, "content": user_msg, "at": now,
    })
    _append_jsonl(path, {
        "type": "assistant", "finding_id": finding_id, "session_id": session_id,
        "turn_index": turn_index, "content": reply,
        "request_id": request_id, "backend": use_backend, "at": now,
    })
    return {"reply": reply, "request_id": request_id, "turn_index": turn_index}


# --------------------------------------------------------------------------- #
# Two-voice (defender + attacker) interrogation — additive                    #
# --------------------------------------------------------------------------- #


def _replay_stance_messages(
    rows: list[dict[str, Any]], stance: str
) -> tuple[list[dict[str, str]], str | None]:
    """Replay a two-voice transcript into a message stack for ONE stance.

    The stance's own `system_seed` is the system message; every `user` row
    (the shared human turns) is replayed, and only the `assistant` rows for
    THIS stance (each stance keeps its own answer thread). Returns
    (messages, seed_backend) — seed_backend is the stance's seeded backend."""
    messages: list[dict[str, str]] = []
    seed_backend: str | None = None
    for row in rows:
        rtype = row.get("type")
        if rtype == "system_seed" and row.get("stance") == stance:
            messages.append({"role": "system", "content": row.get("content", "")})
            seed_backend = row.get("backend")
        elif rtype == "user":
            messages.append({"role": "user", "content": row.get("content", "")})
        elif rtype == "assistant" and row.get("stance") == stance:
            messages.append({"role": "assistant", "content": row.get("content", "")})
    return messages, seed_backend


def _is_run_live(run_state_dir: str | os.PathLike | None = None) -> bool:
    """True when a live run is present (its foreground mirror exists).

    active_run.py exposes no public reader — the apparatus reads the mirror
    file directly (ui/backend/*). Mirror that: tolerant read of the mirror
    path; missing/malformed == idle. A test points this at a tmp dir."""
    mirror = (Path(run_state_dir) / "active_run.json"
              if run_state_dir is not None else active_run.ACTIVE_RUN_PATH)
    return active_run._read_json(mirror) is not None


def _stance_turn(
    path: Path, rows: list[dict[str, Any]], stance: str, user_msg: str,
    session_id: str, finding_id: str, turn_index: int, now: str,
) -> dict[str, Any]:
    """Run ONE stance's reply for a two-voice turn and append its assistant
    row (stance-tagged). Fail-open like novelty_skeptic.attack(): a call
    failure returns a stated, non-committal reply — NEVER a fabricated
    defense or (for the attacker) a fabricated concession that the claim
    holds. The caller appends the single shared `user` row."""
    messages, seed_backend = _replay_stance_messages(rows, stance)
    messages.append({"role": "user", "content": user_msg})
    use_backend = seed_backend or STANCE_BACKEND[stance]
    try:
        record = call_sync(
            messages,
            temperature=0.3,
            top_p=0.9,
            # 4096 (not 1024): the qwen attacker is a reasoning model whose
            # think block can consume the whole budget, leaving empty visible
            # content (real smoke 2026-06-15). A higher cap leaves room for the
            # answer; the gemma defender stops at its natural end well below it.
            max_tokens=4096,
            caller_tag=f"finding_session_{stance}",
            log_path=CALLS_LOG_PATH,
            backend=use_backend,
        )
        reply = record.get("completion") or ""
        request_id = record.get("request_id")
    except Exception as exc:
        # Non-committal, NEVER a fabricated concession/defense (rule 4 +
        # novelty_skeptic.attack discipline). The skeptic explicitly does
        # not read as "the claim holds" on failure.
        request_id = None
        reply = (
            f"[{stance} unavailable: {type(exc).__name__}: {exc}] "
            "No grounded response could be produced this turn; this is "
            "NOT a concession or an endorsement of the claim."
        )
    _append_jsonl(path, {
        "type": "assistant", "finding_id": finding_id, "session_id": session_id,
        "turn_index": turn_index, "stance": stance, "content": reply,
        "request_id": request_id, "backend": use_backend, "at": now,
    })
    return {"stance": stance, "reply": reply, "request_id": request_id}


def two_voice_turn(
    finding_id: str,
    session_id: str,
    user_msg: str,
    *,
    addressee: str = "both",
    sessions_root: str | os.PathLike = DEFAULT_SESSIONS_ROOT,
    run_state_dir: str | os.PathLike | None = None,
) -> dict[str, Any]:
    """One human-directed turn in a two-stance session, addressed at the
    defender, the attacker, or BOTH. Both-in-one-turn counts as ONE turn
    against MAX_TURNS. The addressee is recorded on the `user` row; each
    reply's `stance` is recorded on its `assistant` row.

    Bounded by MAX_TURNS (explicit cap reply, no model call past the limit —
    rule 7). Concurrency guard: if a live run is mid-flight, a warn is
    surfaced and the turn PROCEEDS (warn-and-proceed, not a hard block) so a
    human-paced turn never silently races a loop iteration.

    Returns {turn_index, addressee, warning, replies:[{stance,reply,...}]}."""
    if addressee not in ADDRESSEES:
        raise ValueError(f"addressee {addressee!r} is not one of {ADDRESSEES}")
    path = _session_path(finding_id, session_id, sessions_root)
    rows = _read_jsonl(path)
    if not rows or rows[0].get("type") != "system_seed" or "stance" not in rows[0]:
        raise KeyError(
            f"no two-voice session transcript at {path} "
            f"(finding_id={finding_id!r}, session_id={session_id!r})"
        )

    prior_turns = _count_turns(rows)
    if prior_turns >= MAX_TURNS:
        cap_msg = (
            f"[session cap reached: {MAX_TURNS} turns] This interrogation has "
            "hit its bounded turn limit. End the session with a verdict "
            "(validate / reject / spawn / refine) rather than continuing."
        )
        return {"turn_index": prior_turns, "addressee": addressee,
                "warning": None, "capped": True,
                "replies": [{"stance": None, "reply": cap_msg,
                             "request_id": None}]}

    # Concurrency guard: warn-and-proceed when a live run is mid-flight.
    warning = None
    if _is_run_live(run_state_dir):
        warning = (
            "a live run is mid-flight (run_state/active_run.json present); "
            "this cockpit turn shares the same models — proceeding, but it "
            "may contend with the running iteration."
        )

    turn_index = prior_turns + 1
    now = _utcnow_iso()
    # Record the shared human turn (the addressee lives here).
    _append_jsonl(path, {
        "type": "user", "finding_id": finding_id, "session_id": session_id,
        "turn_index": turn_index, "addressee": addressee,
        "content": user_msg, "at": now,
    })

    stances = STANCES if addressee == "both" else (addressee,)
    # UI observability: announce the turn as the active run (cleared in
    # finally). One registration spans both stance calls of this turn.
    run_id = f"finding_session_{session_id}"
    set_run_id(run_id)
    active_run.write_active_run(
        run_id, kind="ad_hoc", label=f"finding-session(2v) {finding_id}")
    try:
        replies = [
            _stance_turn(path, rows, stance, user_msg, session_id,
                         finding_id, turn_index, now)
            for stance in stances
        ]
    finally:
        active_run.clear_active_run()
        set_run_id(None)
    return {"turn_index": turn_index, "addressee": addressee,
            "warning": warning, "capped": False, "replies": replies}


def end_session(
    finding_id: str,
    session_id: str,
    *,
    outcome: str,
    note: str,
    gated_by: str = "human",
    new_topic: str | None = None,
    refined_claim: str | None = None,
    directive: str | None = None,
    sessions_root: str | os.PathLike = DEFAULT_SESSIONS_ROOT,
    feedback_path: str | os.PathLike = gate_cli.DEFAULT,
    status_audit_path: str | os.PathLike = DEFAULT_STATUS_AUDIT,
    followups_path: str | os.PathLike = DEFAULT_FOLLOWUPS,
) -> dict[str, Any]:
    """Close an interrogation session with a verdict. Three feedback paths,
    all logged, none a silent mutation of surfaced_findings.jsonl.

    outcome in {validated, rejected, spawn_topic, refine, abandoned}.
      validated/rejected -> loop_feedback row (valid/invalid) + status-audit row
      spawn_topic        -> finding_followups queue row (does NOT run the loop)
      refine             -> status-audit row status="in_review" (refined claim
                            in reason; the original surfaced row is preserved)
      abandoned          -> a session-local 'feedback' event only

    directive (optional, SEAM 3): a 'proceed to <next step>' instruction
    attached to a sign-off. Absent/empty == today's bare sign-off (the row
    is unchanged). Present == recorded on the session-local feedback event
    AND the verdict status-audit row (NOT the frozen loop_feedback row,
    whose schema is closed) so Nara's next planning session can consume it.

    Returns a dict describing what was written."""
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome {outcome!r} is not one of {OUTCOMES}")
    directive = directive.strip() if isinstance(directive, str) else None
    directive = directive or None  # empty/whitespace == absent

    path = _session_path(finding_id, session_id, sessions_root)
    rows = _read_jsonl(path)
    if not rows or rows[0].get("type") != "system_seed":
        raise KeyError(
            f"no session transcript at {path} "
            f"(finding_id={finding_id!r}, session_id={session_id!r})"
        )
    iteration_id = rows[0].get("iteration_id")
    now = _utcnow_iso()

    out: dict[str, Any] = {
        "finding_id": finding_id,
        "session_id": session_id,
        "outcome": outcome,
        "loop_feedback_row": None,
        "status_audit_row": None,
        "followup_row": None,
    }

    # Always record the close as a session-local event (full audit trail).
    feedback_event = {
        "type": "feedback", "finding_id": finding_id, "session_id": session_id,
        "outcome": outcome, "note": note, "gated_by": gated_by,
        "new_topic": new_topic, "refined_claim": refined_claim, "at": now,
    }
    if directive is not None:
        feedback_event["directive"] = directive
    _append_jsonl(path, feedback_event)

    if outcome in _OUTCOME_TO_VERDICT:
        verdict = _OUTCOME_TO_VERDICT[outcome]
        # (a) feed the human-gate edge against the SOURCE iteration. If the
        # finding carried no iteration_id we still record the status audit but
        # cannot write a loop_feedback row (its key is iteration_id).
        if iteration_id:
            out["loop_feedback_row"] = gate_cli.append_feedback(
                iteration_id, verdict, note, gated_by,
                path=Path(feedback_path), clock_iso=now,
            )
        status_row = {
            "finding_id": finding_id,
            "status": verdict,
            "changed_at": now,
            "changed_by": gated_by,
            "session_id": session_id,
            "reason": note,
        }
        if directive is not None:
            # SEAM 3 directive sign-off: carried on the audit row (the
            # loop_feedback schema is frozen/closed). Nara's planner reads
            # the status audit, so the directive surfaces there.
            status_row["directive"] = directive
        _append_jsonl(status_audit_path, status_row)
        out["status_audit_row"] = status_row

    elif outcome == "spawn_topic":
        # (b) enqueue a follow-up topic. Does NOT run the loop.
        followup_row = {
            "finding_id": finding_id,
            "session_id": session_id,
            "new_topic": new_topic or note,
            "queued_at": now,
            "queued_by": gated_by,
            "reason": note,
        }
        _append_jsonl(followups_path, followup_row)
        out["followup_row"] = followup_row
        # The act of spawning is itself a status change on the finding.
        status_row = {
            "finding_id": finding_id,
            "status": "spawn_topic",
            "changed_at": now,
            "changed_by": gated_by,
            "session_id": session_id,
            "reason": new_topic or note,
        }
        _append_jsonl(status_audit_path, status_row)
        out["status_audit_row"] = status_row

    elif outcome == "refine":
        # (c) mark in_review; carry the refined claim in the reason. The
        # original surfaced_findings.jsonl row is preserved untouched.
        reason = note
        if refined_claim:
            reason = f"refined_claim: {refined_claim}" + (f" | {note}" if note else "")
        status_row = {
            "finding_id": finding_id,
            "status": "in_review",
            "changed_at": now,
            "changed_by": gated_by,
            "session_id": session_id,
            "reason": reason,
        }
        _append_jsonl(status_audit_path, status_row)
        out["status_audit_row"] = status_row

    # outcome == "abandoned": session-local feedback event only (already written).
    return out


def effective_status(
    finding_id: str,
    *,
    status_audit_path: str | os.PathLike = DEFAULT_STATUS_AUDIT,
) -> str | None:
    """The effective status of a finding = the LAST status-audit row for it.
    None when the finding has no audit rows yet (still 'surfaced')."""
    last = None
    for row in _read_jsonl(status_audit_path):
        if row.get("finding_id") == finding_id:
            last = row.get("status")
    return last


# One-shot dispositions a human may record WITHOUT an interrogation
# session (D-046 write-back contract). validated/rejected route the
# human-gate edge exactly as end_session does; in_review parks the
# finding for a future session. spawn/refine stay session-only — they
# need the conversation.
QUICK_STATUSES = ("validated", "rejected", "in_review")


def set_status(
    finding_id: str,
    status: str,
    note: str,
    by: str = "human",
    *,
    directive: str | None = None,
    surfaced_path: str | os.PathLike | None = None,
    feedback_path: str | os.PathLike | None = None,
    status_audit_path: str | os.PathLike | None = None,
) -> dict[str, Any]:
    """One-shot finding disposition (no session transcript; D-046).

    Mirrors end_session's write paths with `session_id: None`:
      validated/rejected -> loop_feedback row (valid/invalid) against the
                            finding's source iteration + status-audit row
      in_review          -> status-audit row only
    Out-of-enum status / unknown finding / empty note are REJECTED —
    nothing is written (inviolate rule 4). Returns what was written.

    directive (optional, SEAM 3): a 'proceed to <next step>' instruction on
    a one-shot sign-off. Absent/empty == today's bare disposition (the row
    is unchanged). Present == recorded on the status-audit row (the
    loop_feedback row stays the frozen shape).
    """
    directive = directive.strip() if isinstance(directive, str) else None
    directive = directive or None
    surfaced_path = surfaced_path if surfaced_path is not None else DEFAULT_SURFACED
    feedback_path = feedback_path if feedback_path is not None else gate_cli.DEFAULT
    status_audit_path = (status_audit_path if status_audit_path is not None
                         else DEFAULT_STATUS_AUDIT)
    if status not in QUICK_STATUSES:
        raise ValueError(f"status {status!r} is not one of {QUICK_STATUSES}")
    if not note.strip():
        raise ValueError("note is required — the disposition needs a why")
    finding = _load_finding(finding_id, surfaced_path)  # KeyError if absent
    # Promoted findings carry source_iteration_id (finding_promotion.py);
    # older/test rows carry iteration_id. Accept both.
    iteration_id = (finding.get("source_iteration_id")
                    or finding.get("iteration_id"))
    now = _utcnow_iso()

    out: dict[str, Any] = {
        "finding_id": finding_id,
        "session_id": None,
        "outcome": status,
        "loop_feedback_row": None,
        "status_audit_row": None,
    }
    if status in _OUTCOME_TO_VERDICT:
        verdict = _OUTCOME_TO_VERDICT[status]
        if iteration_id:
            out["loop_feedback_row"] = gate_cli.append_feedback(
                iteration_id, verdict, note, by,
                path=Path(feedback_path), clock_iso=now,
            )
        audit_status = verdict
    else:
        audit_status = "in_review"
    status_row = {
        "finding_id": finding_id,
        "status": audit_status,
        "changed_at": now,
        "changed_by": by,
        "session_id": None,
        "reason": note,
    }
    if directive is not None:
        status_row["directive"] = directive  # SEAM 3 directive sign-off
    _append_jsonl(status_audit_path, status_row)
    out["status_audit_row"] = status_row
    return out


# --------------------------------------------------------------------------- #
# CLI REPL                                                                     #
# --------------------------------------------------------------------------- #


def _repl(argv: list[str] | None = None) -> int:
    """A bare interrogation REPL. The SAME functions back the UI API.

    Usage in-loop:
      start <finding_id>   open a session
      /validate <note>     close validated
      /reject <note>       close rejected
      /spawn <topic>       close spawn_topic
      /refine <claim>      close refine
      /quit                close abandoned and exit
      <anything else>      a turn (one user message)
    """
    p = argparse.ArgumentParser(description="Finding interrogation REPL.")
    p.add_argument("--backend", default=DEFAULT_BACKEND)
    args = p.parse_args(argv)

    finding_id: str | None = None
    session_id: str | None = None
    print("finding-session REPL. `start <finding_id>` then chat; "
          "/validate /reject /spawn /refine /quit.")
    while True:
        try:
            line = input("> ").strip()
        except EOFError:
            break
        if not line:
            continue
        if line.startswith("start "):
            fid = line[len("start "):].strip()
            try:
                opened = start_session(fid, backend=args.backend)
            except KeyError as exc:
                print(f"error: {exc}")
                continue
            finding_id, session_id = fid, opened["session_id"]
            print(f"opened session {session_id} for {fid}")
            continue
        if session_id is None or finding_id is None:
            print("no session — `start <finding_id>` first.")
            continue
        if line.startswith("/"):
            cmd, _, rest = line[1:].partition(" ")
            rest = rest.strip()
            if cmd == "quit":
                end_session(finding_id, session_id, outcome="abandoned", note=rest)
                print("abandoned.")
                break
            mapping = {
                "validate": ("validated", {"note": rest}),
                "reject": ("rejected", {"note": rest}),
                "spawn": ("spawn_topic", {"note": rest, "new_topic": rest}),
                "refine": ("refine", {"note": rest, "refined_claim": rest}),
            }
            if cmd not in mapping:
                print(f"unknown command /{cmd}")
                continue
            outcome, kw = mapping[cmd]
            res = end_session(finding_id, session_id, outcome=outcome, **kw)
            print(json.dumps(res, ensure_ascii=False, indent=2))
            finding_id, session_id = None, None
            continue
        res = session_turn(finding_id, session_id, line, backend=args.backend)
        print(f"[turn {res['turn_index']}] {res['reply']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI dispatch: `--set-status` runs the one-shot disposition (the
    D-046 blessed argv for the UI); anything else is the REPL."""
    import sys

    argv = list(sys.argv[1:]) if argv is None else list(argv)
    if "--set-status" in argv:
        p = argparse.ArgumentParser(
            description="One-shot finding disposition (D-046).")
        p.add_argument("--set-status", nargs=2,
                       metavar=("FINDING_ID", "STATUS"), required=True)
        p.add_argument("--note", required=True)
        p.add_argument("--by", default="human")
        # SEAM 3 directive sign-off: optional, clean SUPERSET of the existing
        # validated argv so the UI degrades to a bare sign-off when omitted.
        p.add_argument("--directive", default=None)
        args = p.parse_args(argv)
        fid, status = args.set_status
        try:
            out = set_status(fid, status, args.note, args.by,
                             directive=args.directive)
        except (KeyError, ValueError) as exc:
            print(f"rejected: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    return _repl(argv)


if __name__ == "__main__":
    raise SystemExit(main())
