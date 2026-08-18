"""LOOP_V0 step 5 worker — critic_loop_v0 (sub-agent dispatch, Path-B).

Falsifies the hypothesis against the retrieved literature. As of the
Path-B migration this worker is no longer a single LLM call — it
dispatches a bounded sub-agent that:

  - has its own conversation context (separate from Nara's)
  - has a focused critic system prompt
  - can OPTIONALLY call `query_chroma` to pull additional evidence
    beyond the initial retrieval if it identifies a gap
  - runs 2-6 turns with a 90s wall budget
  - returns the same {verdict, rationale, contradicting_paper_id}
    payload Nara consumes

Output shape (worker contract) is unchanged from the pre-Path-B
implementation — the tool registry doesn't notice. New fields are
added under `result` for observability:
  - `subagent_turns_used` — how many turns the sub-agent took
  - `subagent_wall_seconds` — total wall-clock time inside the sub-agent
  - `subagent_status` — passed | timeout | schema_mismatch | error

The file `workers/critic.py` (Day-9 salvage, Phase-2 contract) and
this file (`critic_loop_v0`) stay separately importable — different
verdict enums, different intended use.
"""
from __future__ import annotations

import os
import time
from typing import Any

from agent_wrapper.backends import get_backend
from agent_wrapper.cleanup import strip_channel_markup
from agent_wrapper.wrapper import DEFAULT_BACKEND
from orchestrator import iteration_cache
from orchestrator.chroma_query import query_top_k
from orchestrator.subagent import (
    SubAgentBudget,
    SubAgentResult,
    run_subagent,
)


# The critic sub-agent's OWN verdict enum. "refuted" is deliberately NOT
# here — it enters the critique verdict only via the D-075 R3b skeptic
# override (a defender concession / verified single-shot refutation),
# never from the critic model itself.
ALLOWED_VERDICTS = ("survives", "falsified", "restated", "malformed", "undecidable")

# D-075 R3b: the noise-vs-legit split for a skeptic "inconclusive" comes
# from RECORDED evidence only — the debate's stop_reason, or the
# single-shot rationale prefix stamped by novelty_skeptic.attack() when
# the model output was unparseable/off-enum. Never inferred.
# `defender_error` and the pre-turn `error` stop are included alongside
# the D-075-named `challenger_error`: all three are error stops recorded
# by the debate engine, not epistemic outcomes (reported at build time —
# D-075 names only challenger_error explicitly).
DEBATE_INFRA_STOP_REASONS = ("challenger_error", "defender_error", "error")
SINGLE_SHOT_INFRA_RATIONALE_PREFIX = "(unparseable or off-enum"

# Caps on the debate transcript copied into the iteration record (D-065).
# The full transcript stays in workers.debate's return value; the record
# carries a bounded excerpt so loop_memory rows stay readable.
DEBATE_TRANSCRIPT_TURNS = 6
DEBATE_TURN_TEXT_CHARS = 600


CRITIC_AGENT_SYSTEM_PROMPT = (
    "You are the CRITIC sub-agent in the a_bgt_rsi research apparatus.\n"
    "\n"
    "Your job: attempt to FALSIFY a research hypothesis using only the\n"
    "retrieved literature you'll be given, plus optionally additional\n"
    "chunks you fetch yourself via the `query_chroma` tool. Do NOT invoke\n"
    "knowledge from outside the retrieved set. Do NOT run experiments.\n"
    "Your judgment must be defensible against the cited literature.\n"
    "\n"
    "You have one tool available:\n"
    "  - `query_chroma(text, k=10)` — fetches additional nearest-neighbor\n"
    "    chunks from the local foundational + live-arXiv knowledge base.\n"
    "    Use this sparingly — at most once or twice — when the initial\n"
    "    neighbors don't cover an angle you need to evaluate. Each call\n"
    "    returns the same shape you got initially. NOT every iteration\n"
    "    needs additional retrieval.\n"
    "\n"
    "Follow this ORDERED decision procedure. Earlier steps take precedence\n"
    "over later ones — do not skip ahead:\n"
    "\n"
    "  STEP 1 — RESTATEMENT CHECK. Does any retrieved neighbor (initial or\n"
    "    fetched) ALREADY STATE the content of this claim — same phenomenon,\n"
    "    same direction, no new mechanism or boundary condition? If yes,\n"
    '    the verdict is "restated"; cite that neighbor in\n'
    "    `contradicting_paper_id` and STOP.\n"
    "  STEP 2 — CONTRADICTION CHECK. Does any retrieved chunk directly\n"
    '    contradict the claim? If yes, the verdict is "falsified"; cite the\n'
    "    contradicting neighbor and STOP.\n"
    "  STEP 3 — only if steps 1 AND 2 both come up empty may you answer\n"
    '    "survives". A "survives" rationale MUST name the closest retrieved\n'
    "    neighbor by doc_id and state WHY that neighbor does NOT already\n"
    "    state the claim. When the corpus simply does not address the\n"
    "    claim's specific subject but the claim is well-formed, on-domain,\n"
    '    and falsifiable, the verdict IS "survives" — your job here is\n'
    "    restatement and contradiction; an INDEPENDENT skeptic model\n"
    '    attacks every "survives" afterwards, so do not retreat to\n'
    '    "undecidable" merely because the corpus is silent on the subject.\n'
    '    Reserve "undecidable" for retrieval flagged off-topic/inadequate\n'
    "    or claims you cannot evaluate at all.\n"
    "\n"
    "The five verdicts (restatement is checked BEFORE survival):\n"
    '  - "restated"    — the claim restates a known result in the retrieved\n'
    "                     set; it adds no new content. Cite the neighbor.\n"
    '  - "falsified"   — at least one retrieved chunk directly contradicts.\n'
    "                     Cite which one in `contradicting_paper_id`.\n"
    '  - "survives"    — passed steps 1 AND 2 against on-topic retrieval;\n'
    "                     the rationale names the closest neighbor and says\n"
    "                     why it does not already state the claim.\n"
    '  - "undecidable" — the retrieved literature (initial + fetched) is\n'
    "                     too thin or off-topic to run steps 1-2 honestly;\n"
    "                     no verdict can be defended either way.\n"
    '  - "malformed"   — the claim is incoherent, ill-defined, or not a\n'
    "                     real game-theory / learning-in-games question.\n"
    "\n"
    "Be intellectually honest: `survives` is a legitimate answer when the\n"
    "literature is ON-TOPIC and still fails to contradict the claim. But if\n"
    "the retrieved neighbors are topically IRRELEVANT to the claim, you CANNOT\n"
    "say `survives` — absence of contradiction in an off-topic corpus is not\n"
    'survival; answer "undecidable" instead.\n'
    "\n"
    "When you've made your judgment, emit a FINAL assistant message that\n"
    "is STRICT JSON, nothing else — no prose, no markdown fences, no\n"
    "channel markers. Schema:\n"
    "{\n"
    '  "verdict": "restated" | "falsified" | "survives" | "undecidable" | "malformed",\n'
    '  "rationale": "<2-4 sentences citing specific neighbors where relevant>",\n'
    '  "contradicting_paper_id": "<doc_id of the contradicting/restated neighbor>" | null\n'
    "}\n"
    "\n"
    '`contradicting_paper_id` is non-null ONLY for "falsified" or "restated".\n'
    "It MUST be a doc_id from the neighbors you've seen (initial + any\n"
    "additional retrievals)."
)


_CRITIC_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["verdict", "rationale"],
    "properties": {
        "verdict": {
            "type": "string",
            "enum": list(ALLOWED_VERDICTS),
        },
        "rationale": {"type": "string"},
        "contradicting_paper_id": {"type": ["string", "null"]},
    },
    "additionalProperties": True,
}


# Tool the critic sub-agent may call. Same `query_chroma` Nara uses,
# but exposed as a sub-agent-scoped capability.
_QUERY_CHROMA_TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "query_chroma",
        "description": (
            "Query the local Chroma knowledge base for additional nearest "
            "neighbors beyond the initial retrieval. Use sparingly. Returns "
            "the same {k, neighbors} shape as the initial retrieval."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Search text (e.g. a focused sub-claim).",
                },
                "k": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "description": "Number of neighbors to return (default 10).",
                },
            },
            "required": ["text"],
        },
    },
}


def _format_neighbors(neighbors: list[dict]) -> str:
    """Compact human-readable neighbor list for the user prompt."""
    if not neighbors:
        return "(none)"
    lines = []
    for i, n in enumerate(neighbors, 1):
        doc_id = n.get("doc_id", "?")
        score = n.get("score")
        title = n.get("title") or "(untitled)"
        source = n.get("source_layer", "?")
        chunk = (n.get("chunk_text") or "").replace("\n", " ").replace("\r", " ").strip()
        if len(chunk) > 600:
            chunk = chunk[:600] + "…"
        score_str = f"{score:.3f}" if isinstance(score, (int, float)) else "?"
        lines.append(
            f"[{i}] doc_id={doc_id!r}  score={score_str}  source={source}  "
            f"title={title!r}\n    {chunk}"
        )
    return "\n".join(lines)


def _post_validate(payload: dict, valid_doc_ids: set[str]) -> tuple[dict, list[str]]:
    """Enforce the same consistency guards the old one-shot critic had:
    - contradicting_paper_id must be in the seen doc_ids when present
    - contradicting_paper_id must be None for survives/malformed verdicts

    The sub-agent's schema validation guarantees verdict ∈ ALLOWED_VERDICTS
    already; this layer only enforces cross-field invariants."""
    warnings: list[str] = []
    verdict = payload.get("verdict")
    rationale = strip_channel_markup(payload.get("rationale") or "")[:2000]
    contra = payload.get("contradicting_paper_id")
    if isinstance(contra, str):
        contra = contra.strip() or None
        if contra and valid_doc_ids and contra not in valid_doc_ids:
            warnings.append(
                f"contradicting_paper_id={contra!r} not in seen neighbors; nulling"
            )
            contra = None
    elif contra is not None:
        warnings.append("contradicting_paper_id not a string or null; nulling")
        contra = None
    if verdict in ("survives", "malformed", "undecidable") and contra is not None:
        warnings.append(
            f"contradicting_paper_id set on verdict={verdict!r}; nulling per schema"
        )
        contra = None
    return (
        {
            "verdict": verdict,
            "rationale": rationale,
            "contradicting_paper_id": contra,
        },
        warnings,
    )


def _configured_skeptic_backend() -> str:
    """Backend name the skeptics are CONFIGURED to run on (same env +
    default as orchestrator.novelty_skeptic / restate_skeptic). Used to
    tag provenance on the paths where no resolved backend comes back —
    a crash, or an attack() that omits the field."""
    return os.environ.get("NARA_SKEPTIC_BACKEND", "vllm-qwen")


def _run_single_attack(
    result: dict, hypothesis_text: str, iteration_id: str | None
) -> tuple[bool, str | None, str | None]:
    """The single-shot skeptic exchange (D-041/D-044 attack()).

    Returns (ran, override_reason, disposition). ran=False means the seam
    was a no-op (module absent / no attack()) and the caller must not act.
    Mutates `result` in place with the verdict AND the skeptic's own
    provenance.

    `disposition` is the D-075 R3b mapping instruction, classified HERE,
    next to the recorded evidence (the attack's rationale prefix):
      "refuted"     — attack said 'refuted' with a verified citation;
      "undecidable" — legitimate uncertainty (a parseable 'inconclusive',
                      or a defensive 'refuted' that arrived uncited);
      "infra"       — the '(unparseable or off-enum' rationale prefix:
                      infra noise, never a downgrade;
      None          — nothing to act on (survives_attack / crash).
    """
    try:
        from orchestrator import novelty_skeptic  # lazy: module may not exist yet
    except ImportError:
        return (False, None, None)
    attack = getattr(novelty_skeptic, "attack", None)
    if not callable(attack):
        return (False, None, None)
    t0 = time.perf_counter()
    try:
        out = attack(hypothesis_text, iteration_id=iteration_id) or {}
    except Exception as exc:  # a skeptic crash is recorded, never fatal
        result["skeptic_verdict"] = f"error: {type(exc).__name__}: {exc}"[:200]
        result["skeptic_backend"] = _configured_skeptic_backend()
        result["skeptic_model"] = None
        result["skeptic_wall_seconds"] = round(time.perf_counter() - t0, 3)
        return (True, None, None)
    attack_verdict = out.get("attack_verdict")
    result["skeptic_verdict"] = attack_verdict
    # D-065: the SKEPTIC's own provenance. `subagent_backend`/`_model`
    # above describe the CRITIC sub-agent (gemma by default), so without
    # these fields a record cannot show whether the independent Qwen or
    # the same-weights Gemma judged the claim — the D-041/D-044
    # independence claim was unverifiable from the record. attack() has
    # always returned backend/model; only the carry-through was missing.
    result["skeptic_backend"] = out.get("backend") or _configured_skeptic_backend()
    result["skeptic_model"] = out.get("model") or None
    # Measured HERE, not returned by attack(): the single-shot attack has
    # no turn/wall accounting of its own (one call_sync).
    result["skeptic_wall_seconds"] = round(time.perf_counter() - t0, 3)

    # D-075 R3b classification, from the attack's own recorded evidence.
    rationale = out.get("rationale") if isinstance(out.get("rationale"), str) else ""
    cited = out.get("contradicting_doc_id")
    if attack_verdict == "refuted" and isinstance(cited, str) and cited.strip():
        # attack() only ever returns 'refuted' with a doc_id it verified
        # against its own retrieval — information-preserving, harsher.
        disposition = "refuted"
    elif attack_verdict == "refuted":
        # Defensive: an uncited 'refuted' (a nonconforming attack impl —
        # the real attack() downgrades these itself). No verified citation
        # means the harsher mapping is not earned; pre-D-075 behavior.
        disposition = "undecidable"
    elif attack_verdict == "inconclusive":
        disposition = (
            "infra"
            if rationale.startswith(SINGLE_SHOT_INFRA_RATIONALE_PREFIX)
            else "undecidable"  # legitimate, parseable uncertainty
        )
    else:
        disposition = None  # survives_attack / off-enum: caller acts on nothing
    return (
        True,
        f"skeptic attack_verdict={attack_verdict!r}: " + rationale[:300],
        disposition,
    )


def _run_debate_exchange(
    result: dict, hypothesis_text: str, iteration_id: str | None
) -> tuple[bool, str | None, str | None]:
    """The NARA_DEBATE=1 variant of the skeptic exchange (D-065).

    Replaces the single-shot attack with workers.debate's bounded
    multi-turn exchange (challenger on the independent backend, defender
    on the apparatus's own). The terminal verdict keeps riding on
    `skeptic_verdict` for backward compatibility; the model-tagged
    transcript lands additively under `debate`. Same (ran, reason,
    disposition) contract as _run_single_attack; here the D-075 R3b
    classification reads the debate's recorded stop_reason:
      "refuted"     — stop_reason 'defender_conceded': the apparatus's
                      own model conceded the claim;
      "undecidable" — legitimate uncertainty ('round_cap'/'converged');
      "infra"       — an error stop (DEBATE_INFRA_STOP_REASONS): noise,
                      never a downgrade;
      None          — nothing to act on (challenger conceded / crash).
    """
    try:
        from workers import debate as debate_mod  # lazy: dark by default
    except ImportError:
        return (False, None, None)
    try:
        out = debate_mod.debate(
            hypothesis_text, None, iteration_id=iteration_id
        ) or {}
    except Exception as exc:  # a debate crash is recorded, never fatal
        result["skeptic_verdict"] = f"error: {type(exc).__name__}: {exc}"[:200]
        result["skeptic_backend"] = _configured_skeptic_backend()
        result["skeptic_model"] = None
        return (True, None, None)

    transcript = [
        {**t, "text": str(t.get("text") or "")[:DEBATE_TURN_TEXT_CHARS]}
        for t in (out.get("transcript") or [])[:DEBATE_TRANSCRIPT_TURNS]
        if isinstance(t, dict)
    ]
    verdict = out.get("verdict")
    result["skeptic_verdict"] = verdict
    # The CHALLENGER is the skeptic in a debate, so its tag is what
    # `skeptic_backend`/`skeptic_model` mean here; the defender's tag
    # rides on its own transcript turns.
    challenger_turns = [t for t in transcript if t.get("role") == "challenger"]
    last_challenger = challenger_turns[-1] if challenger_turns else {}
    result["skeptic_backend"] = (
        last_challenger.get("backend") or _configured_skeptic_backend()
    )
    result["skeptic_model"] = last_challenger.get("model") or None
    result["skeptic_wall_seconds"] = round(
        sum(
            t.get("wall_seconds") or 0.0
            for t in transcript
            if isinstance(t.get("wall_seconds"), (int, float))
        ),
        3,
    )
    result["debate"] = {
        "verdict":     verdict,
        "rounds":      out.get("rounds"),
        "stop_reason": out.get("stop_reason"),
        "transcript":  transcript,
    }

    # D-075 R3b classification, from the debate's own recorded stop_reason
    # (which the record block above carries — the evidence stays auditable).
    stop_reason = out.get("stop_reason")
    if verdict == "refuted" and stop_reason == "defender_conceded":
        disposition = "refuted"
    elif verdict == "refuted":
        # Defensive: debate() has no other route to 'refuted'. Without the
        # recorded concession the harsher mapping is not earned.
        disposition = "undecidable"
    elif verdict == "inconclusive":
        disposition = (
            "infra" if stop_reason in DEBATE_INFRA_STOP_REASONS
            else "undecidable"  # round_cap / converged: legitimate uncertainty
        )
    else:
        disposition = None  # survives_debate / off-enum: caller acts on nothing
    return (
        True,
        f"debate verdict={verdict!r} after {out.get('rounds')} round(s) "
        f"(stop_reason={stop_reason!r}): "
        + (transcript[-1].get("text") if transcript else "")[:300],
        disposition,
    )


def _maybe_run_skeptic(
    result: dict, hypothesis_text: str, iteration_id: str | None
) -> None:
    """Optional adversarial second-channel check (β skeptic-gate seam, D-041).

    Called only when the FINAL verdict is "survives" and low_confidence is
    false. The skeptic does its OWN retrieval, breaking the shared-neighbor
    blind spot (novelty + critic reading one neighbor set is not independent
    corroboration). Gated OFF by default: env NARA_SKEPTIC must be "1" and
    orchestrator.novelty_skeptic must exist and export attack(); otherwise
    this is a no-op. Mutates `result` in place.

    Env NARA_DEBATE=1 (inside an armed NARA_SKEPTIC=1 seam) swaps the
    single-shot attack for the bounded multi-turn debate (D-065). Unset —
    the default — the exchange is byte-identical to the pre-D-065 path
    apart from the additive skeptic_* provenance tags.

    D-075 R3b verdict mapping (was: refuted AND inconclusive both →
    'undecidable'; infra noise also downgraded):
      (a) a refutation the exchange can attest (defender conceded / a
          verified single-shot citation) → critique verdict 'refuted' —
          information-preserving, harsher;
      (b) legitimate uncertainty → 'undecidable', as before;
      (c) infra noise (recorded stop_reason / rationale prefix) NEVER
          overrides — the critic's own verdict stands and the failure is
          recorded in the non-gating `skeptic_infra_error` flag.
    """
    if os.environ.get("NARA_SKEPTIC", "0") != "1":
        return
    if os.environ.get("NARA_DEBATE", "0") == "1":
        ran, override_reason, disposition = _run_debate_exchange(
            result, hypothesis_text, iteration_id
        )
    else:
        ran, override_reason, disposition = _run_single_attack(
            result, hypothesis_text, iteration_id
        )
    if not ran:
        return
    if disposition == "infra":
        # D-075 R3b(c): logged, not scored. Non-gating by construction —
        # nothing downstream reads this flag as a verdict.
        result["skeptic_infra_error"] = True
        return
    if disposition in ("refuted", "undecidable") and override_reason:
        result["verdict_overridden_from"] = result.get("verdict")
        result["override_reason"] = override_reason
        result["verdict"] = disposition


def _maybe_run_restate_skeptic(
    result: dict,
    hypothesis_text: str,
    iteration_id: str | None,
    novelty_class: str | None,
    novelty_top_id: str | None,
) -> None:
    """Optional restatement-skeptic check (residual-2 seam).

    Fires only when novelty already judged the hypothesis a rediscovery
    yet the critic verdict is "survives" or "undecidable" — the
    disagreement the 2026-06-09 battery left unresolved on 4 cases. The
    attack canonicalizes the claim, retrieves fresh, and judges
    restatement under the two-axis transfer rule. Gated OFF by default:
    env NARA_RESTATE_SKEPTIC must be "1" and orchestrator.restate_skeptic
    must exist and export restate_attack(); otherwise this is a no-op.
    Fail-open: every failure path leaves the verdict unchanged — the
    verdict moves (to "restated", with full provenance) ONLY on a
    doc-grounded "restated". Mutates `result` in place.
    """
    if os.environ.get("NARA_RESTATE_SKEPTIC", "0") != "1":
        return
    if novelty_class != "rediscovery":
        return
    if result.get("verdict") not in ("survives", "undecidable"):
        return
    try:
        from orchestrator import restate_skeptic  # lazy: module may not exist yet
    except ImportError:
        return
    restate_attack = getattr(restate_skeptic, "restate_attack", None)
    if not callable(restate_attack):
        return
    t0 = time.perf_counter()
    try:
        out = restate_attack(
            hypothesis_text, iteration_id=iteration_id,
            novelty_top_neighbor_id=novelty_top_id,
        ) or {}
    except Exception as exc:  # a skeptic crash is recorded, never fatal
        result["restate_verdict"] = f"error: {type(exc).__name__}: {exc}"[:200]
        result["restate_backend"] = _configured_skeptic_backend()
        result["restate_model"] = None
        result["restate_wall_seconds"] = round(time.perf_counter() - t0, 3)
        return
    restate_verdict = out.get("restate_verdict")
    result["restate_verdict"] = restate_verdict
    # D-065 provenance, same hole as the survives-attack skeptic:
    # restate_attack() has always returned backend/model (default
    # vllm-qwen via NARA_SKEPTIC_BACKEND); only the carry-through was missing.
    result["restate_backend"] = out.get("backend") or _configured_skeptic_backend()
    result["restate_model"] = out.get("model") or None
    result["restate_wall_seconds"] = round(time.perf_counter() - t0, 3)
    if restate_verdict == "restated" and out.get("restating_doc_id"):
        result["verdict_overridden_from"] = result.get("verdict")
        result["override_reason"] = (
            f"restatement skeptic ({out.get('backend')}): "
            + (out.get("rationale") or "")[:300]
        )
        result["contradicting_paper_id"] = out.get("restating_doc_id")
        result["verdict"] = "restated"


def critic_loop_v0(
    hypothesis_text: str,
    iteration_id: str,
    *,
    parent_request_id: str | None = None,
    budget: SubAgentBudget | None = None,
) -> dict[str, Any]:
    """Falsify the hypothesis via a bounded sub-agent.

    Reads `neighbors` from the per-iteration cache by `iteration_id`
    (reference-passing refactor). Same contract as before; Nara now
    passes `iteration_id` instead of inlining the neighbors list.

    Returns:
    ```
    {
        "status": "passed" | "error",
        "result": {
            "verdict": "survives" | "falsified" | "restated" | "malformed"
                       | "undecidable"
                       | "refuted",  # D-075 R3b: skeptic-override only —
                                     # never emitted by the critic itself
            "rationale": str,
            "contradicting_paper_id": str | None,
            "subagent_turns_used": int,
            "subagent_wall_seconds": float,
            "subagent_status": "passed" | "timeout" | "schema_mismatch" | "error",
            # only when a deterministic override fired (coverage bar,
            # low-confidence hard rule, skeptic refutation, or
            # restatement-skeptic flip):
            "verdict_overridden_from": str,
            "override_reason": str,
            # only when the skeptic exchange failed on INFRA NOISE (D-075
            # R3b(c): debate error stop / unparseable single-shot output) —
            # non-gating; the critic's own verdict stands:
            "skeptic_infra_error": True,
            # only when the skeptic seam ran (env NARA_SKEPTIC=1). The
            # backend/model are the SKEPTIC's own (D-065) — distinct from
            # subagent_backend/_model, which describe the critic:
            "skeptic_verdict": str | None,
            "skeptic_backend": str,
            "skeptic_model": str | None,
            "skeptic_wall_seconds": float,
            # only when the debate variant ran (NARA_SKEPTIC=1 AND
            # NARA_DEBATE=1) — bounded multi-turn transcript, every turn
            # tagged with the backend/model that produced it:
            "debate": {"verdict", "rounds", "stop_reason", "transcript"},
            # only when the restatement-skeptic seam ran (env
            # NARA_RESTATE_SKEPTIC=1, novelty=rediscovery, clean
            # survives/undecidable):
            "restate_verdict": str | None,
            "restate_backend": str,
            "restate_model": str | None,
            "restate_wall_seconds": float,
        } | None,
        "errors": [str, ...],
        "wrapper_request_id": str | None,
        "parent_request_id": str | None,
    }
    ```
    """
    if not isinstance(hypothesis_text, str) or not hypothesis_text.strip():
        return {
            "status": "error",
            "result": None,
            "errors": ["hypothesis_text is required and must be non-empty"],
            "wrapper_request_id": None,
            "parent_request_id": parent_request_id,
        }
    if not isinstance(iteration_id, str) or not iteration_id.strip():
        return {
            "status": "error",
            "result": None,
            "errors": ["iteration_id is required and must be a non-empty string"],
            "wrapper_request_id": None,
            "parent_request_id": parent_request_id,
        }
    try:
        retrieval = iteration_cache.read_entry(iteration_id, "retrieval")
    except KeyError as exc:
        return {
            "status": "error",
            "result": None,
            "errors": [f"iteration cache miss for retrieval: {exc}"],
            "wrapper_request_id": None,
            "parent_request_id": parent_request_id,
        }
    neighbors = (retrieval.get("result") or {}).get("neighbors") or []
    if not isinstance(neighbors, list):
        return {
            "status": "error",
            "result": None,
            "errors": [
                f"cached retrieval.result.neighbors is not a list "
                f"(got {type(neighbors).__name__})"
            ],
            "wrapper_request_id": None,
            "parent_request_id": parent_request_id,
        }

    # Track every doc_id the sub-agent could possibly have seen (initial
    # neighbors + any fetched via query_chroma). Used for post-validation
    # of the cited doc_id.
    seen_doc_ids: set[str] = {
        n.get("doc_id") for n in neighbors if isinstance(n.get("doc_id"), str)
    }

    # Wrap query_chroma so the sub-agent's mid-flight retrievals get
    # their doc_ids added to the seen set.
    def _query_chroma_for_subagent(text: str, k: int = 10, *, parent_request_id=None):
        result = query_top_k(text, k=k, parent_request_id=parent_request_id)
        if result.get("status") == "passed":
            for n in result["result"].get("neighbors", []):
                d = n.get("doc_id")
                if isinstance(d, str):
                    seen_doc_ids.add(d)
        return result

    # Topical-relevance gate (rule 4): if the orchestrator flagged the retrieval
    # as thin/off-topic, warn the sub-agent and stamp low_confidence so a bare
    # 'survives' is never trusted on an irrelevant corpus (incl. the fallbacks).
    rel = (retrieval.get("result") or {}).get("relevance") or {}
    rel_low = bool(rel.get("low_confidence"))
    relevance_warning = (
        f"\nRETRIEVAL RELEVANCE WARNING: {rel.get('reason') or 'thin/off-topic retrieval'}. "
        "The retrieved neighbors may be topically irrelevant to this hypothesis. "
        "Absence of contradiction in an off-topic corpus is NOT 'survives' — say so "
        "and flag low confidence.\n" if rel_low else ""
    )

    # Novelty-context injection: if novelty_classify already judged this a
    # rediscovery, tell the critic — the restatement check (STEP 1) should
    # confront that judgment head-on. Tolerate absence (novelty may not have
    # run, or the cache key may be missing on legacy iterations).
    novelty_class = None
    novelty_top_id = None
    try:
        nov_entry = iteration_cache.read_entry(iteration_id, "novelty")
        nov_res = (nov_entry.get("result") or {})
        novelty_class = nov_res.get("class")
        novelty_top_id = nov_res.get("top_neighbor_id")
    except Exception:
        pass
    novelty_note = (
        "\nNOVELTY CONTEXT: the novelty classifier judged this hypothesis a "
        f"REDISCOVERY of {novelty_top_id or 'a retrieved neighbor'}. If you "
        "agree the retrieved set already states it, the correct verdict is "
        "'restated', not 'survives'.\n"
        if novelty_class == "rediscovery" else ""
    )

    user_prompt = (
        f"Hypothesis:\n{hypothesis_text.strip()}\n\n"
        f"Initial retrieved neighbors ({len(neighbors)}):\n"
        f"{_format_neighbors(neighbors)}\n{relevance_warning}{novelty_note}\n"
        "Decide your verdict. If the initial neighbors are sufficient,\n"
        "emit the final JSON now. If you genuinely need to check a\n"
        "specific angle, call `query_chroma` with a focused query first."
    )

    # Phase-3 critic-flip: when CRITIC_BACKEND is set, route the
    # sub-agent's LLM calls to that backend instead of inheriting Nara's.
    # The Co-Scientist insight (D-035) — having the critic on a different
    # model than the generator — is implemented as an operational env var
    # so flipping back is also free.
    critic_backend = os.environ.get("CRITIC_BACKEND") or None
    resolved_be = get_backend(critic_backend or DEFAULT_BACKEND)

    sa_result: SubAgentResult = run_subagent(
        name="critic_loop_v0",
        system_prompt=CRITIC_AGENT_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        expected_output_schema=_CRITIC_OUTPUT_SCHEMA,
        tools=[{"spec": _QUERY_CHROMA_TOOL_SPEC, "impl": _query_chroma_for_subagent}],
        tool_dispatch={"query_chroma": _query_chroma_for_subagent},
        budget=budget or SubAgentBudget(max_turns=6, max_wall_seconds=90.0),
        parent_request_id=parent_request_id,
        backend=critic_backend,
    )

    # Sub-agent telemetry surfaces in the worker output so the
    # iteration_record can carry it (and the UI can render it).
    # subagent_backend/subagent_model flow up through Nara into
    # active_iteration.json so the divergence chip lights up when the
    # critic is flipped off the orchestrator default.
    observability = {
        "subagent_turns_used":   sa_result.turns_used,
        "subagent_wall_seconds": round(sa_result.wall_seconds, 3),
        "subagent_status":       sa_result.status,
        "subagent_backend":      resolved_be.name,
        "subagent_model":        resolved_be.default_model,
        # Rule 4: stamp low_confidence on EVERY branch (passed + the three
        # 'survives'-defaulting fallbacks) so 'survives' is never trusted bare
        # on topically-irrelevant retrieval.
        "low_confidence":        rel_low,
    }

    if sa_result.status == "passed":
        validated, warnings = _post_validate(sa_result.result or {}, seen_doc_ids)
        validated.update(observability)

        # Coverage-adequacy bar (rule 4): "not contradicted" is only
        # "survives" when the retrieval was adequate to check. The cached
        # relevance result carries a `category` (Limb A); anything but "ok"
        # makes a raw 'survives' undecidable. A missing category field
        # (legacy cached rows) is treated as ok.
        if validated.get("verdict") == "survives":
            category = rel.get("category")
            if category is not None and category != "ok":
                reason = rel.get("reason") or f"relevance category {category!r}"
                validated["verdict_overridden_from"] = "survives"
                validated["override_reason"] = (
                    f"relevance category {category!r} != 'ok': {reason}"
                )
                validated["rationale"] = (
                    f"(coverage-inadequate retrieval override: {reason}) "
                    + (validated.get("rationale") or "")
                )
                validated["verdict"] = "undecidable"
            elif rel_low:
                # Hard rule: low_confidence retrieval can never yield survives.
                reason = rel.get("reason") or "low-confidence retrieval"
                validated["verdict_overridden_from"] = "survives"
                validated["override_reason"] = (
                    f"relevance low_confidence is true: {reason}"
                )
                validated["rationale"] = (
                    f"(coverage-inadequate retrieval override: {reason}) "
                    + (validated.get("rationale") or "")
                )
                validated["verdict"] = "undecidable"

        # Restatement-skeptic seam (residual 2): novelty said rediscovery,
        # the critic said survives/undecidable — confront the disagreement
        # with a canonicalize-then-retrieve restatement attack. Guarded to
        # CLEAN retrieval only (a verdict on gated retrieval is never
        # promoted); a flip to 'restated' also stops the survives-attack
        # below from firing and dissolves the consistency warning.
        if not rel_low and rel.get("category") in (None, "ok"):
            _maybe_run_restate_skeptic(
                validated, hypothesis_text, iteration_id,
                novelty_class, novelty_top_id,
            )

        # β skeptic-gate seam (D-041): independent-retrieval attack on a
        # clean 'survives'. No-op unless NARA_SKEPTIC=1 and the module exists.
        if validated.get("verdict") == "survives" and not rel_low:
            _maybe_run_skeptic(validated, hypothesis_text, iteration_id)

        # Novelty/critic consistency check: a final 'survives' on a
        # hypothesis novelty called a rediscovery is flagged, never flipped
        # (a deterministic flip would propagate novelty errors).
        if validated.get("verdict") == "survives" and novelty_class == "rediscovery":
            warnings = warnings + [
                "consistency_warning: novelty_classify judged this a rediscovery"
                f" of {novelty_top_id or 'a retrieved neighbor'} but the critic"
                " verdict is 'survives' — one of the two is wrong"
            ]

        return {
            "status": "passed",
            "result": validated,
            "errors": warnings,
            "wrapper_request_id": (
                sa_result.wrapper_call_ids[-1] if sa_result.wrapper_call_ids else None
            ),
            "parent_request_id": parent_request_id,
        }

    if sa_result.status == "schema_mismatch":
        # Fail closed to "undecidable" — a sub-agent failure is NEVER
        # evidence of survival (the pre-T1b 'survives' default let three
        # on-domain rediscoveries through the battery unchallenged).
        # Surface the raw payload + status so the human knows the
        # sub-agent failed.
        raw = sa_result.result if isinstance(sa_result.result, dict) else None
        fallback = {
            "verdict": "undecidable",
            "rationale": (
                "(sub-agent emitted schema-mismatched output; defaulting to "
                "undecidable — a sub-agent failure is not evidence of survival) "
                + str(raw)[:500]
            ),
            "contradicting_paper_id": None,
            **observability,
        }
        return {
            "status": "passed",
            "result": fallback,
            "errors": ["sub-agent schema mismatch; verdict defaulted to 'undecidable'"]
                       + sa_result.errors,
            "wrapper_request_id": (
                sa_result.wrapper_call_ids[-1] if sa_result.wrapper_call_ids else None
            ),
            "parent_request_id": parent_request_id,
        }

    if sa_result.status == "timeout":
        return {
            "status": "passed",
            "result": {
                "verdict": "undecidable",
                "rationale": (
                    f"(sub-agent budget exceeded after {sa_result.turns_used} turns; "
                    "defaulting to undecidable — a sub-agent failure is not "
                    "evidence of survival)"
                ),
                "contradicting_paper_id": None,
                **observability,
            },
            "errors": ["sub-agent timeout; verdict defaulted to 'undecidable'"]
                       + sa_result.errors,
            "wrapper_request_id": (
                sa_result.wrapper_call_ids[-1] if sa_result.wrapper_call_ids else None
            ),
            "parent_request_id": parent_request_id,
        }

    # sa_result.status == "error"
    return {
        "status": "error",
        "result": None,
        "errors": sa_result.errors,
        "wrapper_request_id": (
            sa_result.wrapper_call_ids[-1] if sa_result.wrapper_call_ids else None
        ),
        "parent_request_id": parent_request_id,
    }


if __name__ == "__main__":
    # Smoke against real Chroma + Gemma. Stages retrieval into the cache
    # under a synthetic iteration_id, then calls the worker by id —
    # mirrors how Nara wires this in production.
    import json
    from workers.retrieve_literature import retrieve_literature
    hyp = (
        "In finitely repeated Prisoner's Dilemma with known horizon, "
        "rational players defect on every round by backward induction."
    )
    iter_id = "smoke-critic-loop-v0"
    r = retrieve_literature(hyp, k=5)
    iteration_cache.write_entry(iter_id, "retrieval", r)
    out = critic_loop_v0(hyp, iter_id, parent_request_id="smoke")
    print(json.dumps(out, indent=2))
