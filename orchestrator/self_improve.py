"""LOOP_V1 D-066 self-improvement PLANNER — the lab plans its own next fix.

Owner's mechanism (verbatim intent): "get the orchestrator to go through a
debate loop with frontier intelligence to plan an improvement on the system
itself, something small, and this then gets broken down enough into a
development task that can be shipped to qwen or an organization of
developers."

Pipeline — every stage an injectable seam; NOTHING here dispatches:

  gather_evidence()  PURE reads of the lab's OWN telemetry (run-log failures,
                     health signals, loop alert, coordinator cycle repeats,
                     near-miss reasons, daemon idle/backoff). A missing file
                     degrades to "[unavailable: <path>]" — never invented.
  propose()          ONE Gemma call -> strict JSON: one SMALL Tier-P
                     improvement grounded in a NAMED signal and expressible as
                     a currently-FAILING pytest module whose source the
                     proposer authors. Unparseable output RAISES.
  review()           the debate: feasibility_reviewer (claude: smallest change?
                     genuinely falsifiable test?) vs risk_scope_reviewer
                     (codex: Tier S? scope creep? duplication? dependency?),
                     combined by the same ladder + cross-run disagreement
                     protocol as workers.frontier_review.screen_candidate.
  plan_improvement() gather -> propose -> review -> (not-pass) revise ->
                     review, bounded by MAX_IMPROVE_ROUNDS = 3 (HARD; an
                     out-of-band max_rounds RAISES, never clamps). Exhaustion
                     returns {"emitted": false, ...} WITH the transcript.
  emit_packet()      refuses any path outside Tier P; writes the acceptance
                     test; RUNS it; emits ONLY when it is actually RED (pytest
                     rc 1). Red-first is PROVEN here, not asserted. Then the
                     packet (schema/task_packet.schema.json) + an
                     authorize_fix row consume_authorize_fix_queue reads.

ONLY "pass" proceeds to emit. A frontier "inconclusive" is treated like a
veto here — the DELIBERATE inverse of frontier_review's fail-open posture,
because this screen guards the apparatus modifying ITSELF, not a promotion.

Entrenchment (docs/packet_sdlc.md, RATIFIED 2026-08-15): Tier P
(workers/ tools/ tests/ docs/ bench/ experiments/) is the ONLY proposable
scope. Tier S — spine, schema/, run_state/, CLAUDE.md, DECISIONS.md,
cron/, agent/, ui/, version pins — is human-ratified and refused
mechanically at emit, every offending path named. A path in NEITHER list
(e.g. orchestrator/) is UNTIERED and refused too: an auto-proposer widening
its own blast radius is exactly what this gate exists to prevent.

MOCK_LLM: the default proposer/reviser return a deterministic stub; an
un-injected invoke_fn RAISES rather than spawn real frontier CLIs (mirrors
workers.refine_cycle). CLI: python -m orchestrator.self_improve [--dry-run]
[--max-rounds N<=3] [--emit]; --dry-run writes NONE of this module's
artifacts (no test file, no packet, no queue row, no run-log row).
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import jsonschema

from workers.frontier_review import ALLOWED_VERDICTS, _extract_json_object

REPO_ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = REPO_ROOT / ".venv-chroma" / "bin" / "python"
SCHEMA_PATH = REPO_ROOT / "schema" / "task_packet.schema.json"

DEFAULT_RUN_LOG = REPO_ROOT / "run_state" / "week1.run.jsonl"
DEFAULT_HEALTH = REPO_ROOT / "run_state" / "health_signals.jsonl"
DEFAULT_ALERT = REPO_ROOT / "run_state" / "loop_alert.json"
DEFAULT_CYCLES = REPO_ROOT / "run_state" / "coordinator_cycles.jsonl"
DEFAULT_NEAR_MISS = REPO_ROOT / "memory" / "promotion_near_misses.jsonl"
DEFAULT_DAEMON_LOG = REPO_ROOT / "logs" / "nara-daemon.log"
DEFAULT_QUEUE = REPO_ROOT / "memory" / "authorize_fix_queue.jsonl"
DEFAULT_PACKETS_DIR = REPO_ROOT / "tasks" / "packets"
DEFAULT_TESTS_DIR = REPO_ROOT / "tests"

AGENT_NAME = "self_improve"

# HARD cap on review rounds (out-of-band values RAISE, never clamp).
MAX_IMPROVE_ROUNDS = 3
# A proposal carries a COMPLETE pytest module in `acceptance_test_source`, so
# it is long by construction. At 2000 the 2026-08-16 runs began returning JSON
# that simply stopped mid-object, which surfaces as "not a JSON object" — a
# parse complaint that hides a capacity problem. Sized against the served 32k
# window, not guessed.
PROPOSAL_MAX_TOKENS = 4000
SECTION_LIMIT = 8              # per-section cap in the evidence dict
RUN_LOG_SCAN_LINES = 2000
NEAR_MISS_SCAN_LINES = 400
CYCLE_REPEAT_WINDOW = 24
RED_CHECK_TIMEOUT_S = 900
# Run-log statuses that carry improvement signal (documented, not ad hoc).
FAILURE_STATUSES = ("failed", "fallback", "error", "timeout")

# --- entrenchment tiers (docs/packet_sdlc.md, ratified 2026-08-15) ---------
TIER_P_PREFIXES = ("workers/", "tools/", "tests/", "docs/", "bench/",
                   "experiments/")
TIER_S_EXACT = ("orchestrator/nara.py", "orchestrator/tool_registry.py",
                "CLAUDE.md", "DECISIONS.md", "ARCHITECTURE.md",
                "cron/serve-models.sh")
TIER_S_PREFIXES = ("schema/", "run_state/", "agent/", "ui/", "cron/")
# Canonical pin strings (ARCHITECTURE.md §2 / tools/premerge_check.sh).
VERSION_PIN_STRINGS = ("v0.21.0", "gemma-4-26b-a4b-nvfp4", "cluster:0.0.13")

_TEST_PATH_RE = re.compile(r"^tests/test_[A-Za-z0-9_]+\.py$")
PROPOSAL_FIELDS = ("title", "problem", "change", "rationale", "files_in_scope",
                   "acceptance_test_path", "acceptance_test_intent",
                   "acceptance_test_source", "risk")


class ScopeRefusal(ValueError):
    """A proposal reaching outside Tier P. Raised at emit, every offending
    path named — the mechanical half of the entrenchment tiers."""


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _rows(path: str | Path, scan: int) -> list[dict] | None:
    """Last `scan` JSONL rows, or None when the file is absent (the caller
    turns None into an "[unavailable: ...]" marker). Malformed lines are
    skipped on read; nothing is ever rewritten."""
    p = Path(path)
    if not p.exists():
        return None
    out: list[dict] = []
    for line in p.read_text(errors="replace").splitlines()[-scan:]:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _trim(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


# ── stage 1: evidence ────────────────────────────────────────────────────────

def gather_evidence(
    *,
    run_log_path: str | Path | None = None,
    health_path: str | Path | None = None,
    alert_path: str | Path | None = None,
    cycles_path: str | Path | None = None,
    near_miss_path: str | Path | None = None,
    daemon_log_path: str | Path | None = None,
    limit: int = SECTION_LIMIT,
) -> dict[str, Any]:
    """PURE reads of the lab's telemetry — no LLM, no writes.

    Returns {"failures", "health", "alert", "cycles", "cycle_repeats",
    "near_misses", "daemon", "unavailable", "digest"}; every list capped at
    `limit`. A missing source contributes "[unavailable: <path>]" to
    `unavailable` and an EMPTY section — the absence is reported, never
    papered over (rule 4)."""
    paths = {
        "run_log": Path(run_log_path or DEFAULT_RUN_LOG),
        "health": Path(health_path or DEFAULT_HEALTH),
        "alert": Path(alert_path or DEFAULT_ALERT),
        "cycles": Path(cycles_path or DEFAULT_CYCLES),
        "near_miss": Path(near_miss_path or DEFAULT_NEAR_MISS),
        "daemon": Path(daemon_log_path or DEFAULT_DAEMON_LOG),
    }
    ev: dict[str, Any] = {"failures": [], "health": [], "alert": None,
                          "cycles": [], "cycle_repeats": [], "near_misses": [],
                          "daemon": [], "unavailable": []}

    def read(key: str, scan: int) -> list[dict]:
        """Rows, or [] plus an honest marker — absence is never papered over."""
        rows = _rows(paths[key], scan)
        if rows is None:
            ev["unavailable"].append(f"[unavailable: {paths[key]}]")
            return []
        return rows

    ev["failures"] = [
        {"task_id": _trim(r.get("task_id") or r.get("event_type"), 80),
         "agent": _trim(r.get("agent"), 40), "status": r.get("status"),
         "observable_actual": _trim(r.get("observable_actual"), 240)}
        for r in read("run_log", RUN_LOG_SCAN_LINES)
        if r.get("status") in FAILURE_STATUSES][-limit:]

    health = read("health", RUN_LOG_SCAN_LINES)
    keyed = [(str(r.get("signal")), str(r.get("severity"))) for r in health]
    latest = dict(zip(keyed, health))
    ev["health"] = [
        {"signal": sig, "severity": sev, "count": n,
         "last_ts": _trim(latest[(sig, sev)].get("timestamp"), 40),
         "last_detail": _trim(latest[(sig, sev)].get("detail"), 200)}
        for (sig, sev), n in Counter(keyed).most_common(limit)]

    if not paths["alert"].exists():
        ev["unavailable"].append(f"[unavailable: {paths['alert']}]")
    else:
        try:
            alert = json.loads(paths["alert"].read_text())
        except json.JSONDecodeError:
            alert = None
        if isinstance(alert, dict):
            reasons = alert.get("reasons")
            ev["alert"] = {
                "level": _trim(alert.get("level"), 20),
                "reasons": [_trim(r, 80) for r in reasons[:limit]]
                if isinstance(reasons, list) else [],
                "updated_at": _trim(alert.get("updated_at"), 40)}
        else:
            ev["unavailable"].append(f"[unparseable: {paths['alert']}]")

    def actions(row: dict) -> list[str]:
        plan = row.get("plan")
        return [str(s.get("action")) for s in plan
                if isinstance(s, dict)] if isinstance(plan, list) else []

    cycles = read("cycles", CYCLE_REPEAT_WINDOW)
    ev["cycles"] = [
        {"run_id": _trim(r.get("run_id"), 40), "status": _trim(r.get("status"), 30),
         "actions": actions(r),
         "promoted": len(r["promoted_finding_ids"])
         if isinstance(r.get("promoted_finding_ids"), list) else 0}
        for r in cycles[-limit:]]
    ev["cycle_repeats"] = [
        {"signature": sig, "count": n} for sig, n in Counter(
            f"status={r.get('status')} plan={','.join(actions(r)) or 'none'}"
            for r in cycles).most_common(limit) if n > 1]

    ev["near_misses"] = [
        {"reason": reason, "count": n} for reason, n in Counter(
            _trim(r.get("reason"), 160)
            for r in read("near_miss", NEAR_MISS_SCAN_LINES)
            if r.get("reason")).most_common(limit)]

    if not paths["daemon"].exists():
        ev["unavailable"].append(f"[unavailable: {paths['daemon']}]")
    else:
        ev["daemon"] = [
            ln.strip()[:200] for ln in
            paths["daemon"].read_text(errors="replace").splitlines()[-500:]
            if any(tok in ln for tok in ("idle", "backoff", "WARN"))][-limit:]

    ev["digest"] = _render_digest(ev)
    return ev


INVENTORY_DIRS = ("workers", "tools", "orchestrator", "agent_wrapper")


def repo_inventory(root: str | Path | None = None) -> str:
    """A deterministic map of the modules a proposal may name, and the public
    top-level symbols each really exports.

    The 2026-08-16 live runs failed three rounds in a row because the proposer
    invented plausible-but-absent names (``workers/qwen_worker.py``, an
    ``AgentWrapper`` class, a ``call_sync(prompt=...)`` signature). An
    acceptance test written against a symbol that does not exist fails today
    for the WRONG reason (ImportError) and can be made green by a shim the
    runtime never calls — which is exactly the red-first loophole the
    reviewers kept closing. Grounding is cheaper than three review rounds.

    Pure AST read (never imports the modules); an unreadable file is skipped
    rather than guessed at. Shell scripts are listed by path only — they have
    no symbols to enumerate."""
    base = Path(root) if root is not None else REPO_ROOT
    lines: list[str] = []
    for d in INVENTORY_DIRS:
        for path in sorted((base / d).rglob("*.py")):
            try:
                tree = ast.parse(path.read_text())
            except (OSError, SyntaxError):
                continue
            names = [n.name for n in tree.body
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                                       ast.ClassDef))
                     and not n.name.startswith("_")]
            rel = path.relative_to(base).as_posix()
            lines.append(f"  {rel}: {', '.join(names) if names else '(no public symbols)'}")
    for path in sorted((base / "tools").glob("*.sh")):
        lines.append(f"  {path.relative_to(base).as_posix()}: (shell script)")
    if not lines:
        return "REPO INVENTORY: (unavailable — nothing readable under "
    return ("REPO INVENTORY — every module you may name, with the PUBLIC "
            "top-level symbols it actually exports:\n" + "\n".join(lines))


def _render_digest(ev: dict[str, Any]) -> str:
    """Compact prompt-ready rendering of the evidence dict."""
    alert = ev["alert"]
    out = ["EVIDENCE DIGEST — the lab's own telemetry (self-improvement planner)",
           f"loop_alert: level={alert['level']} "
           f"reasons={', '.join(alert['reasons']) or 'none'} "
           f"(updated {alert['updated_at']})" if alert else "loop_alert: (none read)"]

    def block(header: str, items: list[str]) -> None:
        out.append(header)
        out.extend(items or ["  (none)"])

    block(f"run-log failures ({len(ev['failures'])}):",
          [f"  - [{f['status']}] {f['task_id']} (agent={f['agent']}): "
           f"{f['observable_actual']}" for f in ev["failures"]])
    # Framing, learned the hard way (2026-08-16): three consecutive rounds
    # were lost to the proposer reading a DETECTOR FIRING as the defect —
    # "the loop_stalled signal says the loop stalled, so let us build stall
    # detection", when the signal's existence proves the detector already
    # works. A signal is the apparatus noticing; the defect is the condition.
    out.append("READING THESE SIGNALS: a health signal or a detector's "
               "detail string is the apparatus WORKING — it noticed. The "
               "defect to fix is the CONDITION it reports, never the "
               "reporting. If your change would build or 'ensure' the thing "
               "that produced the line you quoted, you have misread it.")
    block(f"health signals ({len(ev['health'])}):",
          [f"  - {h['signal']} [{h['severity']}] x{h['count']} — last "
           f"{h['last_ts']} — {h['last_detail']}" for h in ev["health"]])
    block(f"coordinator cycles (last {len(ev['cycles'])}):",
          [f"  - {c['run_id']} status={c['status']} "
           f"actions={','.join(c['actions']) or 'none'} promoted={c['promoted']}"
           for c in ev["cycles"]])
    if ev["cycle_repeats"]:
        block("repeated cycle signatures (a loop repeating itself):",
              [f"  - {r['signature']} x{r['count']}" for r in ev["cycle_repeats"]])
    block("promotion near-miss reasons (most frequent):",
          [f"  - {n['reason']} x{n['count']}" for n in ev["near_misses"]])
    if ev["daemon"]:
        block("daemon idle/backoff lines:", [f"  - {ln}" for ln in ev["daemon"]])
    if ev["unavailable"]:
        block("unavailable sources (reported, not invented):",
              [f"  - {m}" for m in ev["unavailable"]])
    return "\n".join(out)


# ── stage 2: propose / revise (Gemma, strict JSON) ───────────────────────────

_PROPOSAL_SCHEMA_BLOCK = (
    "Answer with STRICT JSON only — no prose before or after, no markdown "
    "fences. Schema:\n"
    "{\n"
    '  "title": "<= 12 words naming the improvement",\n'
    '  "problem": "the ONE evidence signal this fixes, quoted from the digest",\n'
    '  "change": "what a coding agent will actually do, concretely",\n'
    '  "rationale": "why this change addresses that signal",\n'
    '  "files_in_scope": ["repo-relative path", ...],\n'
    '  "acceptance_test_path": "tests/test_<name>.py",\n'
    '  "acceptance_test_intent": "what the test asserts and why it fails today",\n'
    '  "acceptance_test_source": "the COMPLETE pytest module source",\n'
    '  "risk": "what could go wrong and how it is bounded"\n'
    "}"
)
_PROPOSE_SYSTEM = (
    "You are the SELF-IMPROVEMENT PLANNER of a research apparatus. Propose "
    "exactly ONE SMALL improvement to the apparatus ITSELF, grounded in the "
    "supplied evidence — name in `problem` WHICH signal from the digest "
    "motivates it. Hard constraints:\n"
    "  - Tier P ONLY: files_in_scope may name paths under workers/, tools/, "
    "tests/, docs/, bench/, experiments/ and NOTHING else. The shared spine "
    "(orchestrator/nara.py, orchestrator/tool_registry.py), schema/, "
    "run_state/, ui/, agent/, CLAUDE.md, DECISIONS.md, cron/, and every "
    "pinned version string are human-ratified and FORBIDDEN.\n"
    "  - It must be expressible as a SINGLE currently-FAILING pytest module "
    "that a builder makes pass. Author that module in "
    "acceptance_test_source: real, importable, self-contained, hermetic "
    "(no network, no model calls), and RED today for the right reason — it "
    "must fail because the improvement is missing, not because of a typo.\n"
    "  - Smallest change that fixes the named signal. No speculative "
    "abstraction, no new dependency, no refactor riding along, no rewrite.\n"
    "  - At most 3 files in scope.\n"
    "  - GROUNDING (hard): every module path, function, class and call signature you name — in the change, in files_in_scope, and in the acceptance test — MUST appear in the REPO INVENTORY supplied below. Do NOT invent a module or a class because the name sounds right. If the fix you want needs a symbol that is not in the inventory, propose a DIFFERENT fix. A test that fails with ImportError, AttributeError or TypeError is failing for the WRONG reason and will be rejected.\n\n"
    + _PROPOSAL_SCHEMA_BLOCK
)
_REVISE_SYSTEM = (
    "You revise a self-improvement proposal under two reviewers' critiques. "
    "Address EVERY critique concretely: shrink the change if scope was the "
    "objection, tighten or rewrite the acceptance test if falsifiability was, "
    "and move out of any forbidden path named. Keep the same evidence signal "
    "unless a reviewer showed it was misread. Return the FULL revised "
    "proposal.\n\n" + _PROPOSAL_SCHEMA_BLOCK
)


def _stub_proposal(digest: str) -> dict[str, Any]:
    """Deterministic MOCK_LLM proposal (hermeticity, not intelligence): a
    Tier-P doc-check whose acceptance test is red until the file exists."""
    signal = next((ln.strip() for ln in digest.splitlines()
                   if ln.strip().startswith("- ")), "(no signal line)")[:200]
    return {
        "title": "record the self-improvement evidence signal",
        "problem": f"MOCK_LLM stub proposal anchored on: {signal}",
        "change": "add docs/self_improve_signal.md naming the top signal",
        "rationale": "deterministic stub — the real proposer runs unmocked",
        "files_in_scope": ["docs/self_improve_signal.md"],
        "acceptance_test_path": "tests/test_self_improve_signal_doc.py",
        "acceptance_test_intent": "the signal doc exists and names a signal",
        "acceptance_test_source": (
            "from pathlib import Path\n\n\n"
            "def test_signal_doc_exists():\n"
            "    p = Path(__file__).resolve().parent.parent / "
            '"docs" / "self_improve_signal.md"\n'
            "    assert p.exists(), f\"missing {p}\"\n"
        ),
        "risk": "none — documentation only; revert by deleting the file",
    }


def _default_propose(digest: str) -> str:
    if os.environ.get("MOCK_LLM"):
        return json.dumps(_stub_proposal(digest))
    from agent_wrapper.wrapper import call_sync
    record = call_sync(
        [{"role": "system", "content": _PROPOSE_SYSTEM},
         {"role": "user", "content": (f"{digest}\n\n{repo_inventory()}\n\n"
                                      "Return the JSON object.")}],
        temperature=0.3, seed=0, max_tokens=PROPOSAL_MAX_TOKENS,
        caller_tag="self_improve_propose",
    )
    return record.get("completion") or ""


def _default_revise(proposal: dict, critiques: str, round_no: int) -> str:
    if os.environ.get("MOCK_LLM"):
        revised = dict(proposal)
        revised["title"] = f"{proposal['title']} (r{round_no})"
        revised["rationale"] = (
            f"{proposal['rationale']} [r{round_no}: {critiques[:200]}]")
        return json.dumps(revised)
    from agent_wrapper.wrapper import call_sync
    record = call_sync(
        [{"role": "system", "content": _REVISE_SYSTEM},
         {"role": "user", "content": (
             f"Proposal (revision round {round_no}):\n"
             f"{json.dumps(proposal, ensure_ascii=False, indent=2)}\n\n"
             f"Reviewer critiques:\n{critiques}\n\n"
             f"{repo_inventory()}\n\n"
             "Return the revised JSON object.")}],
        temperature=0.3, seed=0, max_tokens=PROPOSAL_MAX_TOKENS,
        caller_tag="self_improve_revise",
    )
    return record.get("completion") or ""


def _parse_proposal(text: str) -> dict[str, Any]:
    """Strict parse of a proposal. Any defect RAISES ValueError naming the
    offending field — a malformed proposal is never coerced into a stub."""
    payload = _extract_json_object(text if isinstance(text, str) else "")
    if not isinstance(payload, dict):
        raw = text if isinstance(text, str) else ""
        # Name the likely cause instead of blaming the parser: an opening
        # brace with no balanced close is a completion that ran out of tokens,
        # not a model that answered in prose.
        hint = (" — the text opens a JSON object that never closes, i.e. the "
                f"completion was cut off (max_tokens={PROPOSAL_MAX_TOKENS})"
                if "{" in raw and raw.count("{") > raw.count("}") else "")
        raise ValueError(
            "self_improve: proposal output is not a JSON object — refusing to "
            f"substitute a stub (rule 4){hint}. Raw head: {_trim(raw, 300)!r}")
    out: dict[str, Any] = {}
    for field in PROPOSAL_FIELDS:
        value = payload.get(field)
        if field == "files_in_scope":
            if not (isinstance(value, list) and value
                    and all(isinstance(v, str) and v.strip() for v in value)):
                raise ValueError(
                    "self_improve: files_in_scope must be a non-empty list of "
                    f"non-empty strings, got {value!r}")
            if len(value) > 6:
                raise ValueError(
                    f"self_improve: files_in_scope names {len(value)} files — "
                    "a SMALL improvement touches at most 6")
            out[field] = [v.strip() for v in value]
            continue
        if not (isinstance(value, str) and value.strip()):
            raise ValueError(
                f"self_improve: proposal field {field!r} missing or empty "
                f"(got {value!r})")
        out[field] = value.strip()
    if not _TEST_PATH_RE.match(out["acceptance_test_path"]):
        raise ValueError(
            f"self_improve: acceptance_test_path "
            f"{out['acceptance_test_path']!r} must match tests/test_<name>.py")
    if "def test_" not in out["acceptance_test_source"]:
        raise ValueError(
            "self_improve: acceptance_test_source defines no test function — "
            "a module with no test cannot be red for the right reason")
    return out


def propose(evidence: dict, *, propose_fn: Callable[[str], str] | None = None
            ) -> dict[str, Any]:
    """ONE proposal from the evidence digest. `propose_fn(digest) -> raw text`
    is the injectable model seam (default: MOCK_LLM stub, else one low-temp
    call_sync). Parse failure RAISES (never a silent stub)."""
    digest = evidence.get("digest") if isinstance(evidence, dict) else None
    if not (isinstance(digest, str) and digest.strip()):
        raise ValueError(
            "self_improve: evidence carries no digest — refusing to propose "
            "an improvement grounded in nothing (rule 4)")
    return _parse_proposal((propose_fn or _default_propose)(digest))


def revise(proposal: dict, screen: dict, round_no: int, *,
           revise_fn: Callable[..., str] | None = None) -> dict[str, Any]:
    """One revision carrying BOTH reviewers' critiques (refine_cycle shape)."""
    return _parse_proposal(
        (revise_fn or _default_revise)(proposal, _critiques(screen), round_no))


# ── stage 3: the frontier debate ─────────────────────────────────────────────

_STRICT_VERDICT_BLOCK = (
    "Answer with STRICT JSON only — no prose before or after, no markdown "
    "fences. Schema:\n"
    '{"verdict": "veto" | "pass" | "inconclusive",\n'
    ' "reasoning": "<2-6 sentences grounded in the proposal>"}\n'
    'Use "veto" only for an affirmative, articulable defect; "inconclusive" '
    "when you cannot tell. Never veto on vagueness alone."
)
REVIEW_ROLES = ("feasibility_reviewer", "risk_scope_reviewer")
ROLE_VENDOR_DEFAULTS = {"feasibility_reviewer": "claude",
                        "risk_scope_reviewer": "codex"}
_ROLE_VENDOR_ENV = {"feasibility_reviewer": "SELF_IMPROVE_FEASIBILITY_VENDOR",
                    "risk_scope_reviewer": "SELF_IMPROVE_RISK_VENDOR"}
DEFAULT_TIMEOUT_S = 180
ROLE_PROMPTS = {
    "feasibility_reviewer": (
        "You are the FEASIBILITY_REVIEWER in a research apparatus's frontier "
        "critic tier — a falsifier, never a generator. The apparatus has "
        "proposed ONE small change to ITSELF, to be executed by a coding "
        "agent under a bounded packet. Your ONLY job is feasibility and "
        "smallness:\n"
        "  - Is this the SMALLEST change that fixes the NAMED signal, or a "
        "rewrite wearing a small hat?\n"
        "  - Is the acceptance test genuinely FALSIFIABLE and scoped — would "
        "it fail today for the right reason and pass ONLY if the change is "
        "really made? Could it be made green by a no-op, by deleting "
        "behavior, or by editing the test itself?\n"
        "  - Are the named files sufficient to make it pass, with no hidden "
        "dependency on a file outside scope?\n"
        'Verdict "veto" = a specific, named defect. "pass" = none found. '
        '"inconclusive" = you cannot judge from what is given.\n\n'
        + _STRICT_VERDICT_BLOCK),
    "risk_scope_reviewer": (
        "You are the RISK_SCOPE_REVIEWER in a research apparatus's frontier "
        "critic tier — a falsifier, never a generator. The apparatus has "
        "proposed ONE small change to ITSELF. Your ONLY job is blast "
        "radius:\n"
        "  - Does it touch Tier S — orchestrator/nara.py, "
        "orchestrator/tool_registry.py, schema/, run_state/, ui/, agent/, "
        "CLAUDE.md, DECISIONS.md, cron/, or a pinned version string? Those "
        "are human-ratified; an agent may never propose them.\n"
        "  - Does it widen scope beyond the one named signal, add a "
        "dependency or package, or add speculative abstraction for a "
        "hypothetical future?\n"
        "  - Does it DUPLICATE machinery the apparatus already has?\n"
        'Verdict "veto" = a specific, named scope/risk defect. "pass" = none '
        'found. "inconclusive" = you cannot judge.\n\n'
        + _STRICT_VERDICT_BLOCK),
}


def role_vendor(role: str) -> str:
    if role not in ROLE_VENDOR_DEFAULTS:
        raise ValueError(f"unknown review role: {role!r} (not in {REVIEW_ROLES})")
    return os.environ.get(_ROLE_VENDOR_ENV[role]) or ROLE_VENDOR_DEFAULTS[role]


def _proposal_block(proposal: dict) -> str:
    lines = []
    for key in PROPOSAL_FIELDS:
        if key == "acceptance_test_source":
            continue
        value = proposal.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            value = json.dumps(value, default=str)
        lines.append(f"{key}: {value}")
    source = str(proposal.get("acceptance_test_source") or "")
    lines.append(f"acceptance_test_source:\n{source[:2500]}")
    return "\n".join(lines)


def _inconclusive(role: str, vendor: str, reason: str) -> dict[str, Any]:
    return {"verdict": "inconclusive", "reasoning": reason, "role": role,
            "vendor": vendor, "parse_ok": False}


def _review_role(role: str, proposal: dict, invoke_fn: Callable[..., dict], *,
                 vendor: str | None = None, timeout_s: int | None = None
                 ) -> dict[str, Any]:
    """ONE role review through the injected frontier seam — mirrors
    workers.frontier_review.review_role (whose prompts are bound to its own
    two roles): every failure path resolves to "inconclusive", never a
    veto."""
    if role not in ROLE_PROMPTS:
        raise ValueError(f"unknown review role: {role!r} (not in {REVIEW_ROLES})")
    vendor = vendor or role_vendor(role)
    if timeout_s is None:
        timeout_s = int(os.environ.get("SELF_IMPROVE_REVIEW_TIMEOUT_S",
                                       str(DEFAULT_TIMEOUT_S)))
    prompt = (f"{ROLE_PROMPTS[role]}\n\nProposed self-improvement:\n"
              f"{_proposal_block(proposal)}")
    try:
        rec = invoke_fn(vendor, prompt, timeout_s=timeout_s, role=role)
    except Exception as exc:  # noqa: BLE001 — outage must not fake a verdict
        return _inconclusive(role, vendor,
                             f"frontier invoke raised: {type(exc).__name__}: {exc}")
    if not isinstance(rec, dict):
        return _inconclusive(role, vendor,
                             f"frontier invoke returned {type(rec).__name__}")
    if rec.get("error"):
        return _inconclusive(role, vendor, f"frontier invoke error: {rec['error']}")
    if rec.get("exit_code") not in (0, None):
        return _inconclusive(role, vendor,
                             f"frontier CLI exit_code={rec.get('exit_code')}")
    payload = _extract_json_object(rec.get("text") or "")
    if not isinstance(payload, dict):
        return _inconclusive(
            role, vendor,
            f"unparseable frontier output: {_trim(rec.get('text'), 300)}")
    verdict = payload.get("verdict")
    if verdict not in ALLOWED_VERDICTS:
        return _inconclusive(
            role, vendor,
            f"off-enum verdict {verdict!r} (not in {ALLOWED_VERDICTS})")
    reasoning = payload.get("reasoning")
    return {"verdict": verdict,
            "reasoning": (reasoning if isinstance(reasoning, str) else "").strip()[:4000],
            "role": role, "vendor": vendor, "parse_ok": True}


def review(proposal: dict, *, invoke_fn: Callable[..., dict] | None = None,
           timeout_s: int | None = None) -> dict[str, Any]:
    """The debate: both roles, combined by frontier_review's ladder.

    both veto -> veto; both pass -> pass; veto+inconclusive -> veto;
    pass+inconclusive -> pass; both inconclusive -> inconclusive. One veto +
    one pass -> cross-run the VETOING role once on the other's vendor: cross
    veto -> "veto"; cross pass/inconclusive -> "inconclusive", escalated."""
    if invoke_fn is None:
        if os.environ.get("MOCK_LLM"):
            raise ValueError(
                "self_improve: MOCK_LLM is set and no invoke_fn was injected — "
                "refusing to spawn real frontier CLIs (MOCK_LLM discipline)")
        from agent_wrapper.frontier_cli import invoke_frontier
        invoke_fn = invoke_frontier
    feas = _review_role("feasibility_reviewer", proposal, invoke_fn,
                        timeout_s=timeout_s)
    risk = _review_role("risk_scope_reviewer", proposal, invoke_fn,
                        timeout_s=timeout_s)
    verdicts = {feas["verdict"], risk["verdict"]}
    if verdicts == {"veto", "pass"}:
        vetoer, other = ((feas, risk) if feas["verdict"] == "veto"
                         else (risk, feas))
        cross = _review_role(vetoer["role"], proposal, invoke_fn,
                             vendor=other["vendor"], timeout_s=timeout_s)
        vetoer["cross_run"] = cross
        if cross["verdict"] == "veto":
            return {"verdict": "veto", "feasibility": feas, "risk_scope": risk,
                    "escalated": False}
        return {"verdict": "inconclusive", "feasibility": feas,
                "risk_scope": risk, "escalated": True}
    if "veto" in verdicts:
        overall = "veto"
    elif "pass" in verdicts:
        overall = "pass"
    else:
        overall = "inconclusive"
    return {"verdict": overall, "feasibility": feas, "risk_scope": risk,
            "escalated": False}


def _critiques(screen: dict) -> str:
    """Both reviewers' verdicts + reasoning, joined for the reviser."""
    parts = []
    for key in ("feasibility", "risk_scope"):
        rev = screen.get(key) or {}
        parts.append(f"- {rev.get('role') or key} ({rev.get('verdict')}): "
                     f"{_trim(rev.get('reasoning'), 600) or '(no reasoning)'}")
    return "\n".join(parts)


# ── stage 4: scope gate + emit ───────────────────────────────────────────────

def _rel_path(entry: str) -> str | None:
    """Repo-relative POSIX path, or None when the entry escapes the repo."""
    raw = str(entry).strip()
    if not raw:
        return None
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = REPO_ROOT / candidate
    try:
        return candidate.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return None


def scope_violations(paths: list[str]) -> list[dict[str, str]]:
    """Mechanical Tier check over proposed paths. Returns one record per
    offending entry: {"path", "tier", "reason"} — an ALLOW-list on Tier P, so
    a path in neither tier is refused as untiered rather than assumed safe."""
    out: list[dict[str, str]] = []
    for entry in paths:
        rel = _rel_path(entry)
        if rel is None:
            out.append({"path": str(entry), "tier": "outside-repo",
                        "reason": "resolves outside the repository root"})
            continue
        if rel in TIER_S_EXACT or any(rel == p.rstrip("/") or rel.startswith(p)
                                      for p in TIER_S_PREFIXES):
            out.append({"path": rel, "tier": "S",
                        "reason": "Tier S — human-ratified, never auto-proposed"})
            continue
        if not any(rel.startswith(p) for p in TIER_P_PREFIXES):
            out.append({"path": rel, "tier": "untiered",
                        "reason": f"outside Tier P {TIER_P_PREFIXES}"})
    return out


def _slug(title: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-")[:40].strip("-") or "improvement"


def _default_run_test(test_path: Path) -> tuple[int, str]:
    """MOCK_LLM=1 <abs venv python> -m pytest <path> -x -q. Returns
    (returncode, output); a timeout is rc 124 — decidedly not red."""
    env = dict(os.environ, MOCK_LLM="1")
    try:
        proc = subprocess.run(
            [str(VENV_PYTHON), "-m", "pytest", str(test_path), "-x", "-q"],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
            timeout=RED_CHECK_TIMEOUT_S, env=env)
    except subprocess.TimeoutExpired:
        return 124, f"acceptance test timed out after {RED_CHECK_TIMEOUT_S}s"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _build_packet(proposal: dict, packet_id: str, test_rel: str) -> dict:
    in_scope = [p for p in proposal["files_in_scope"] if p != test_rel]
    if not in_scope:
        raise ValueError(
            "self_improve: files_in_scope names only the acceptance test — a "
            "packet with nothing to edit can never pass (rule 4)")
    objective = (f"{proposal['title']}. Problem: {proposal['problem']} "
                 f"Change: {proposal['change']} Acceptance: "
                 f"{proposal['acceptance_test_intent']}")[:2000]
    return {
        "task_id": packet_id,
        "objective": objective,
        "files_in_scope": in_scope,
        "files_out_of_scope": [
            test_rel, "orchestrator/nara.py", "orchestrator/tool_registry.py",
            "schema/", "run_state/", "ui/", "agent/", "CLAUDE.md",
            "DECISIONS.md", "cron/serve-models.sh"],
        "preconditions": [f"test -f {test_rel}", "git rev-parse HEAD"],
        "acceptance_criteria": {
            "test_cmd": f"MOCK_LLM=1 {VENV_PYTHON} -m pytest {test_rel} -x -q",
            "must_fail_before": True},
        "budgets": {"max_attempts": 2, "wall_clock_minutes": 20,
                    "max_diff_lines": 200},
        "forbidden_actions": [
            "git push", "git commit on main",
            f"editing or deleting the acceptance test {test_rel}",
            "editing any file outside files_in_scope",
            "touching Tier S paths (spine, schema/, run_state/, CLAUDE.md, "
            "DECISIONS.md, cron/serve-models.sh) or any pinned version string",
            "installing or upgrading packages"],
        "rollback": {
            "branch_delete": True,
            "notes": (f"Delete {test_rel} to abandon. The acceptance test is "
                      "emitted UNCOMMITTED into the main checkout — the "
                      "primary session must COMMIT it before dispatch or the "
                      "packet worktree will not contain it.")},
    }


def emit_packet(proposal: dict, *, packets_dir: str | Path | None = None,
                tests_dir: str | Path | None = None,
                queue_path: str | Path | None = None,
                run_test: Callable[[Path], tuple[int, str]] | None = None,
                dry_run: bool = False,
                run_log: Callable[..., None] | None = None) -> dict[str, Any]:
    """Scope-gate, PROVE red, then emit the packet + the queue row.

    Raises ScopeRefusal when any proposed path (or the acceptance test path)
    leaves Tier P, or when a pinned version string appears in the change or
    the test source. Emits ONLY when the freshly written acceptance test
    returns pytest exit code 1 (test failures); any other code — 0 (passes),
    2 (collection error), 5 (nothing collected) — removes the file and
    returns {"emitted": false, "reason": "acceptance test is not red..."}."""
    t0 = time.perf_counter()
    test_rel = proposal["acceptance_test_path"]
    violations = scope_violations(list(proposal["files_in_scope"]) + [test_rel])
    if violations:
        raise ScopeRefusal(
            "self_improve: proposal leaves Tier P — refusing to emit. "
            + "; ".join(f"{v['path']} ({v['tier']}: {v['reason']})"
                        for v in violations))
    haystack = f"{proposal['change']}\n{proposal['acceptance_test_source']}"
    pins = [pin for pin in VERSION_PIN_STRINGS if pin in haystack]
    if pins:
        raise ScopeRefusal(
            f"self_improve: proposal carries pinned version string(s) {pins} — "
            "version pins are Tier S and verbatim (inviolate rule 2)")

    packet_id = f"PKT-SELF-{_slug(proposal['title'])}"
    packet = _build_packet(proposal, packet_id, test_rel)
    report: dict[str, Any] = {"emitted": False, "reason": None,
                              "packet_id": packet_id, "scope_ok": True,
                              "packet_path": None, "test_path": None,
                              "test_rc": None, "queue_row": None}
    if dry_run:
        report["reason"] = "dry_run: scope checks passed; nothing written"
        return report

    def log(status: str, actual: str) -> None:
        fn = run_log
        if fn is None:
            from orchestrator import runtime
            fn = runtime.append_run_log
        fn({"task_id": f"self_improve:{packet_id}", "status": status,
            "observable_actual": actual,
            "observable_expected": "acceptance test RED (pytest rc=1), packet emitted",
            "duration_ms": round((time.perf_counter() - t0) * 1000.0, 3)},
           agent=AGENT_NAME)

    tests_root = Path(tests_dir) if tests_dir is not None else DEFAULT_TESTS_DIR
    packets_root = (Path(packets_dir) if packets_dir is not None
                    else DEFAULT_PACKETS_DIR)
    test_file = tests_root / Path(test_rel).name
    packet_file = packets_root / f"{packet_id}.json"
    for existing, what in ((test_file, "acceptance test"),
                           (packet_file, "packet")):
        if existing.exists():
            raise ValueError(
                f"self_improve: {what} {existing} already exists — refusing to "
                "clobber prior work")

    # Validate BEFORE writing anything: a packet that cannot validate must not
    # leave a stray red test behind in tests/.
    jsonschema.validate(instance=packet,
                        schema=json.loads(SCHEMA_PATH.read_text()))
    tests_root.mkdir(parents=True, exist_ok=True)
    test_file.write_text(proposal["acceptance_test_source"])
    report["test_path"] = str(test_file)
    rc, output = (run_test or _default_run_test)(test_file)
    report["test_rc"] = rc
    if rc != 1:
        test_file.unlink(missing_ok=True)
        report["test_path"] = None
        report["reason"] = (
            "acceptance test is not red" if rc == 0 else
            f"acceptance test is not red: pytest exit code {rc} "
            "(collection/usage error, not a test failure)")
        log("refused", f"{report['reason']}; output tail: {_trim(output, 300)}")
        return report

    packets_root.mkdir(parents=True, exist_ok=True)
    packet_file.write_text(json.dumps(packet, indent=2, ensure_ascii=False) + "\n")
    report["packet_path"] = str(packet_file)

    queue_file = Path(queue_path) if queue_path is not None else DEFAULT_QUEUE
    row = {"ref_id": packet_id, "outcome": "authorize_fix", "status": "enqueued",
           "note": (f"self-improvement packet emitted by {AGENT_NAME}; "
                    f"acceptance test proven RED (pytest rc=1) at plan time"),
           "authorized_by": AGENT_NAME, "authorized_at": _utcnow_iso(),
           "packet": packet}
    queue_file.parent.mkdir(parents=True, exist_ok=True)
    with open(queue_file, "a") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    report.update({"emitted": True, "queue_row": row,
                   "reason": "acceptance test RED; packet emitted"})
    log("passed", f"emitted {packet_id} with RED acceptance test {test_rel}")
    return report


# ── the loop ─────────────────────────────────────────────────────────────────

def plan_improvement(
    *,
    max_rounds: int = MAX_IMPROVE_ROUNDS,
    evidence: dict | None = None,
    evidence_kwargs: dict | None = None,
    propose_fn: Callable[[str], str] | None = None,
    revise_fn: Callable[..., str] | None = None,
    invoke_fn: Callable[..., dict] | None = None,
    emit: bool = False,
    dry_run: bool = False,
    packets_dir: str | Path | None = None,
    tests_dir: str | Path | None = None,
    queue_path: str | Path | None = None,
    run_test: Callable[[Path], tuple[int, str]] | None = None,
    run_log: Callable[..., None] | None = None,
) -> dict[str, Any]:
    """gather -> propose -> review -> (not-pass) revise -> review, capped at
    MAX_IMPROVE_ROUNDS. Only an affirmative "pass" proceeds to emit; anything
    else (veto OR inconclusive) revises, and exhaustion returns
    {"emitted": false, "reason": ...} with the full transcript."""
    if not (isinstance(max_rounds, int) and 1 <= max_rounds <= MAX_IMPROVE_ROUNDS):
        raise ValueError(
            f"self_improve: max_rounds={max_rounds!r} outside 1.."
            f"{MAX_IMPROVE_ROUNDS} — the cap is hard, never clamped (rule 4)")
    t0 = time.perf_counter()

    def log(status: str, actual: str) -> None:
        if dry_run:
            return
        fn = run_log
        if fn is None:
            from orchestrator import runtime
            fn = runtime.append_run_log
        fn({"task_id": "self_improve:plan", "status": status,
            "observable_actual": actual,
            "observable_expected": "one reviewed Tier-P improvement proposal",
            "duration_ms": round((time.perf_counter() - t0) * 1000.0, 3)},
           agent=AGENT_NAME)

    if evidence is None:
        evidence = gather_evidence(**(evidence_kwargs or {}))
    log("passed", f"evidence: {len(evidence.get('failures') or [])} failures, "
                  f"{len(evidence.get('health') or [])} health signals, "
                  f"{len(evidence.get('unavailable') or [])} unavailable sources")

    proposal = propose(evidence, propose_fn=propose_fn)
    log("passed", f"proposed: {_trim(proposal['title'], 120)}")

    transcript: list[dict[str, Any]] = []
    approved = False
    rounds_used = 0
    for round_no in range(1, max_rounds + 1):
        rounds_used = round_no
        screen = review(proposal, invoke_fn=invoke_fn)
        transcript.append({
            "round": round_no, "verdict": screen["verdict"],
            "escalated": screen.get("escalated", False),
            "title": proposal["title"], "critiques": _critiques(screen)})
        log("passed" if screen["verdict"] == "pass" else "failed",
            f"review round {round_no}: verdict={screen['verdict']}")
        if screen["verdict"] == "pass":
            approved = True
            break
        if round_no < max_rounds:
            proposal = revise(proposal, screen, round_no, revise_fn=revise_fn)

    report: dict[str, Any] = {
        "approved": approved, "rounds_used": rounds_used,
        "max_rounds": max_rounds, "proposal": proposal,
        "transcript": transcript, "evidence_digest": evidence.get("digest"),
        "emitted": False, "reason": None, "dry_run": dry_run,
    }
    if not approved:
        report["reason"] = (
            f"no frontier pass in {rounds_used} round(s) (final verdict="
            f"{transcript[-1]['verdict'] if transcript else 'none'}) — an "
            "unreviewed packet is never emitted")
        log("refused", report["reason"])
        return report
    if dry_run:
        report["reason"] = "dry_run: reviewed and approved; nothing written"
        return report
    if not emit:
        report["reason"] = "approved; emit not requested (--emit to write)"
        return report
    report["emit"] = emit_packet(
        proposal, packets_dir=packets_dir, tests_dir=tests_dir,
        queue_path=queue_path, run_test=run_test, run_log=run_log)
    report["emitted"] = report["emit"]["emitted"]
    report["reason"] = report["emit"]["reason"]
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="D-066 self-improvement planner: mine the lab's telemetry, "
                    "propose ONE small Tier-P improvement, debate it with two "
                    "frontier falsifiers, and emit a red-first task packet.")
    parser.add_argument("--dry-run", action="store_true",
                        help="gather + propose + review and print the plan; "
                             "write nothing (no test file, packet, queue row, "
                             "or run-log row)")
    parser.add_argument("--max-rounds", type=int, default=MAX_IMPROVE_ROUNDS,
                        help=f"review rounds (hard cap {MAX_IMPROVE_ROUNDS}; "
                             "higher values raise)")
    parser.add_argument("--emit", action="store_true",
                        help="on a frontier pass, write the acceptance test, "
                             "prove it RED, and emit the packet + queue row")
    args = parser.parse_args(argv)
    report = plan_improvement(max_rounds=args.max_rounds, emit=args.emit,
                              dry_run=args.dry_run)
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
