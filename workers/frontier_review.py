"""Frontier critic tier — methods + novelty reviewers over subscription CLIs.

LOOP_V1 P2 (D-061, executing the D-041 skeptic-ladder step 3): the frontier
tier is a FALSIFIER, never a generator. Two role reviews screen a promotion
candidate at the L1->L2 boundary:

  - methods_reviewer  — soundness: confounds, missing controls, whether the
                        claimed mechanism could produce the claimed effect.
  - novelty_reviewer  — closest prior work: is this already done / published,
                        and what is the nearest existing result.

Each review is ONE frontier call through an INJECTED `invoke_fn` whose
signature matches `agent_wrapper.frontier_cli.invoke_frontier`:

    invoke_fn(vendor, prompt, *, timeout_s, role, ledger_path=None)
      -> {"text", "vendor", "cli_version", "duration_ms", "exit_code", "error"}

This module never imports frontier_cli (seam stays injectable/testable;
MOCK_LLM is irrelevant here — hermeticity lives in the injected fn). The
reviewer must answer STRICT JSON:

    {"verdict": "veto" | "pass" | "inconclusive",
     "reasoning": "<grounded explanation>",
     "closest_prior_work": "<citation-ish string>" | null}

FAIL-OPEN SEAM (test-pinned): ANY failure — invoke error, non-zero exit,
exception, unparseable output, off-enum verdict — resolves to
"inconclusive", NEVER "veto". A frontier outage must not block the local
loop; the screen only blocks on an affirmative, parseable veto. This is the
inverse of the local skeptic's fail-closed posture and is deliberate: the
frontier is an OPTIONAL extra filter, not a load-bearing gate.

Role->vendor routing (env-overridable):
    methods_reviewer -> "claude"  (FRONTIER_METHODS_VENDOR)
    novelty_reviewer -> "codex"   (FRONTIER_NOVELTY_VENDOR)

Disagreement protocol in `screen_candidate` (one veto + one pass): the
VETOING role is cross-run ONCE on the other role's vendor. Cross-run also
vetoes -> the veto is vendor-independent -> final "veto". Cross-run passes
or is inconclusive -> the veto did not replicate -> persistent disagreement
-> final "inconclusive" with escalated=True (the caller owns writing the
escalation row; this worker stays pure — no file I/O).

Verdict combination ladder (no cross-run cases):
    both veto                 -> veto
    both pass                 -> pass
    veto + inconclusive       -> veto   (a veto stands unless contested)
    pass + inconclusive       -> pass   (fail-open: outage never blocks)
    both inconclusive         -> inconclusive
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable


ALLOWED_VERDICTS = ("veto", "pass", "inconclusive")

ROLES = ("methods_reviewer", "novelty_reviewer")

# Default role -> vendor map (LOOP_V1 P2: Claude=methods / Codex=novelty).
ROLE_VENDOR_DEFAULTS = {
    "methods_reviewer": "claude",
    "novelty_reviewer": "codex",
}
_ROLE_VENDOR_ENV = {
    "methods_reviewer": "FRONTIER_METHODS_VENDOR",
    "novelty_reviewer": "FRONTIER_NOVELTY_VENDOR",
}

# Frontier CLIs are slow (full model turns over a subprocess); generous cap,
# env-overridable without a code change.
DEFAULT_TIMEOUT_S = 180

# Candidate fields surfaced verbatim in the prompt, in this order (matches
# schema/surfaced_finding.schema.json); anything else rides in the JSON tail.
_PROMPT_FIELDS = ("finding_id", "source_iteration_id", "title", "claim",
                  "novelty_class", "evidence")

_STRICT_JSON_SCHEMA = (
    "Answer with STRICT JSON only — no prose before or after, no markdown "
    "fences. Schema:\n"
    "{\n"
    '  "verdict": "veto" | "pass" | "inconclusive",\n'
    '  "reasoning": "<2-6 sentences grounded in the candidate>",\n'
    '  "closest_prior_work": "<author/venue/year or title of the nearest '
    'existing result>" | null\n'
    "}\n"
    'Use "veto" only for an affirmative, articulable defect; "inconclusive" '
    "when you cannot tell. Never veto on vagueness alone."
)

ROLE_PROMPTS = {
    "methods_reviewer": (
        "You are the METHODS_REVIEWER in a research apparatus's frontier "
        "critic tier — a falsifier, never a generator. A local loop produced "
        "the candidate finding below and wants to promote it up its evidence "
        "ladder. Your ONLY job is methodological soundness:\n"
        "  - Could the described mechanism actually produce the claimed "
        "effect, or is there a confound that explains it more cheaply?\n"
        "  - What controls are MISSING (baselines, ablations, randomization, "
        "sample size) that the claim silently depends on?\n"
        "  - Is the evidence cited actually capable of supporting the claim "
        "as stated?\n"
        'Verdict "veto" = a specific, named methodological defect makes the '
        'claim unsound as stated. "pass" = no disqualifying defect found. '
        '"inconclusive" = you cannot judge from what is given.\n\n'
        + _STRICT_JSON_SCHEMA
    ),
    "novelty_reviewer": (
        "You are the NOVELTY_REVIEWER in a research apparatus's frontier "
        "critic tier — a falsifier, never a generator. A local loop produced "
        "the candidate finding below and believes it is novel. Your ONLY job "
        "is prior work:\n"
        "  - What is the CLOSEST existing result (paper, textbook result, "
        "well-known folklore) to this claim? Name it as specifically as you "
        "can in closest_prior_work.\n"
        "  - Is this claim already done — a restatement, a special case, or "
        "a trivial corollary of that prior work?\n"
        'Verdict "veto" = the claim is substantively already established in '
        'prior work you can name. "pass" = you know of no prior work that '
        'subsumes it. "inconclusive" = you cannot tell. Always fill '
        "closest_prior_work with your best candidate even on a pass, or null "
        "if you have none.\n\n"
        + _STRICT_JSON_SCHEMA
    ),
}


def role_vendor(role: str) -> str:
    """Resolve the vendor for a role: env override, else the default map."""
    if role not in ROLE_VENDOR_DEFAULTS:
        raise ValueError(f"unknown frontier role: {role!r} (not in {ROLES})")
    return os.environ.get(_ROLE_VENDOR_ENV[role]) or ROLE_VENDOR_DEFAULTS[role]


def _candidate_block(candidate: dict) -> str:
    """Render the candidate for the prompt: known fields first, verbatim,
    then the full record as a truncated JSON tail (nothing hidden from the
    reviewer, nothing hallucinated on its behalf)."""
    lines = []
    for key in _PROMPT_FIELDS:
        val = candidate.get(key)
        if val is not None:
            if not isinstance(val, str):
                val = json.dumps(val, default=str)
            lines.append(f"{key}: {val}")
    try:
        tail = json.dumps(candidate, default=str, sort_keys=True)
    except (TypeError, ValueError):
        tail = repr(candidate)
    if len(tail) > 6000:
        tail = tail[:6000] + "…(truncated)"
    lines.append(f"full record (JSON): {tail}")
    return "\n".join(lines)


def build_prompt(role: str, candidate: dict) -> str:
    """Role instructions + rendered candidate. Raises on an unknown role
    (a caller bug, not a frontier failure — never coerced)."""
    if role not in ROLE_PROMPTS:
        raise ValueError(f"unknown frontier role: {role!r} (not in {ROLES})")
    return f"{ROLE_PROMPTS[role]}\n\nCandidate finding:\n{_candidate_block(candidate)}"


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Balanced-brace extractor — same one novelty_skeptic/hypothesize use.
    Kept self-contained per the bounded-codegen rule."""
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


def _inconclusive(role: str, vendor: str, reason: str,
                  raw_text: str | None = None) -> dict[str, Any]:
    """The fail-open terminal: every failure path lands here, labelled with
    an honest reason. NEVER a veto."""
    return {
        "verdict": "inconclusive",
        "reasoning": reason if raw_text is None
        else f"{reason} Raw output (truncated): {raw_text[:500]}",
        "closest_prior_work": None,
        "role": role,
        "vendor": vendor,
        "parse_ok": False,
    }


def review_role(
    role: str,
    candidate: dict,
    invoke_fn: Callable[..., dict],
    *,
    vendor: str | None = None,
    timeout_s: int | None = None,
) -> dict[str, Any]:
    """Run ONE role review through the injected frontier seam.

    Returns:
        {"verdict": "veto"|"pass"|"inconclusive", "reasoning": str,
         "closest_prior_work": str | None, "role": str, "vendor": str,
         "parse_ok": bool}

    parse_ok=False marks every fail-open path (invoke error/exception,
    non-zero exit, unparseable output, off-enum verdict) — all of which
    resolve to "inconclusive", never "veto".
    """
    vendor = vendor or role_vendor(role)
    prompt = build_prompt(role, candidate)
    if timeout_s is None:
        timeout_s = int(os.environ.get("FRONTIER_REVIEW_TIMEOUT_S",
                                       str(DEFAULT_TIMEOUT_S)))
    try:
        rec = invoke_fn(vendor, prompt, timeout_s=timeout_s, role=role)
    except Exception as exc:  # fail-open: outage must not block the loop
        return _inconclusive(
            role, vendor,
            f"frontier invoke raised: {type(exc).__name__}: {exc}.")
    if not isinstance(rec, dict):
        return _inconclusive(
            role, vendor,
            f"frontier invoke returned {type(rec).__name__}, not a dict.")
    if rec.get("error"):
        return _inconclusive(role, vendor,
                             f"frontier invoke error: {rec['error']}.")
    if rec.get("exit_code") not in (0, None):
        return _inconclusive(
            role, vendor,
            f"frontier CLI exit_code={rec.get('exit_code')}.")

    payload = _extract_json_object(rec.get("text") or "")
    if not isinstance(payload, dict):
        return _inconclusive(role, vendor, "unparseable frontier output.",
                             raw_text=rec.get("text") or "")
    verdict = payload.get("verdict")
    if verdict not in ALLOWED_VERDICTS:
        # Off-enum is NEVER coerced to a nearby verdict (rule 4).
        return _inconclusive(
            role, vendor,
            f"off-enum verdict {verdict!r} (not in {ALLOWED_VERDICTS}).",
            raw_text=rec.get("text") or "")
    reasoning = payload.get("reasoning")
    if not isinstance(reasoning, str):
        reasoning = ""
    prior = payload.get("closest_prior_work")
    if prior is not None and not isinstance(prior, str):
        prior = None  # invalid type nulled, verdict untouched
    return {
        "verdict": verdict,
        "reasoning": reasoning.strip()[:4000],
        "closest_prior_work": (prior.strip() or None) if prior else None,
        "role": role,
        "vendor": vendor,
        "parse_ok": True,
    }


def screen_candidate(candidate: dict, invoke_fn) -> dict[str, Any]:
    """Screen one promotion candidate through both frontier roles.

    Returns:
        {"verdict": "veto"|"pass"|"inconclusive",
         "methods": {...review_role record...},
         "novelty": {...review_role record...},
         "escalated": bool}

    Combination ladder (module docstring has the rationale):
        both veto -> veto; both pass -> pass;
        veto+inconclusive -> veto; pass+inconclusive -> pass;
        both inconclusive -> inconclusive.
    One veto + one pass -> cross-run the VETOING role once on the other
    role's vendor (record attached under that role's "cross_run" key):
    cross veto -> "veto"; cross pass/inconclusive -> "inconclusive" with
    escalated=True (persistent cross-vendor disagreement).
    """
    methods = review_role("methods_reviewer", candidate, invoke_fn)
    novelty = review_role("novelty_reviewer", candidate, invoke_fn)
    verdicts = {methods["verdict"], novelty["verdict"]}

    if verdicts == {"veto", "pass"}:
        # Cross-run the disagreeing (vetoing) role on the other role's vendor.
        vetoer, other = ((methods, novelty) if methods["verdict"] == "veto"
                         else (novelty, methods))
        cross = review_role(vetoer["role"], candidate, invoke_fn,
                            vendor=other["vendor"])
        vetoer["cross_run"] = cross
        if cross["verdict"] == "veto":
            # Vendor-independent veto: confirmed.
            return {"verdict": "veto", "methods": methods,
                    "novelty": novelty, "escalated": False}
        # Cross-run passed or was inconclusive: the veto did not replicate.
        return {"verdict": "inconclusive", "methods": methods,
                "novelty": novelty, "escalated": True}

    if "veto" in verdicts:
        overall = "veto"          # veto+veto or veto+inconclusive
    elif "pass" in verdicts:
        overall = "pass"          # pass+pass or pass+inconclusive
    else:
        overall = "inconclusive"  # both inconclusive
    return {"verdict": overall, "methods": methods, "novelty": novelty,
            "escalated": False}
