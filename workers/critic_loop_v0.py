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


ALLOWED_VERDICTS = ("survives", "falsified", "restated", "malformed")


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
    "Return ONE of four verdicts:\n"
    '  - "survives"   — no retrieved chunk (initial or fetched) directly\n'
    "                    contradicts the claim. Well-formed hypothesis,\n"
    "                    not yet defeated.\n"
    '  - "falsified"  — at least one retrieved chunk directly contradicts.\n'
    "                    Cite which one in `contradicting_paper_id`.\n"
    '  - "restated"   — the claim restates a known result in the retrieved\n'
    "                    set; it adds no new content.\n"
    '  - "malformed"  — the claim is incoherent, ill-defined, or not a\n'
    "                    real game-theory / learning-in-games question.\n"
    "\n"
    "Be intellectually honest: `survives` is a legitimate answer when the\n"
    "literature simply doesn't address the claim. `restated` is reserved\n"
    "for claims that the retrieved set proves redundant.\n"
    "\n"
    "When you've made your judgment, emit a FINAL assistant message that\n"
    "is STRICT JSON, nothing else — no prose, no markdown fences, no\n"
    "channel markers. Schema:\n"
    "{\n"
    '  "verdict": "survives" | "falsified" | "restated" | "malformed",\n'
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
    if verdict in ("survives", "malformed") and contra is not None:
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
            "verdict": "survives" | "falsified" | "restated" | "malformed",
            "rationale": str,
            "contradicting_paper_id": str | None,
            "subagent_turns_used": int,
            "subagent_wall_seconds": float,
            "subagent_status": "passed" | "timeout" | "schema_mismatch" | "error",
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

    user_prompt = (
        f"Hypothesis:\n{hypothesis_text.strip()}\n\n"
        f"Initial retrieved neighbors ({len(neighbors)}):\n"
        f"{_format_neighbors(neighbors)}\n\n"
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
    }

    if sa_result.status == "passed":
        validated, warnings = _post_validate(sa_result.result or {}, seen_doc_ids)
        validated.update(observability)
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
        # Fall back to "survives" (absence-of-evidence isn't evidence-of-absence),
        # but surface the raw payload + status so the human knows the
        # sub-agent failed.
        raw = sa_result.result if isinstance(sa_result.result, dict) else None
        fallback = {
            "verdict": "survives",
            "rationale": (
                "(sub-agent emitted schema-mismatched output; defaulting to survives) "
                + str(raw)[:500]
            ),
            "contradicting_paper_id": None,
            **observability,
        }
        return {
            "status": "passed",
            "result": fallback,
            "errors": ["sub-agent schema mismatch; verdict defaulted to 'survives'"]
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
                "verdict": "survives",
                "rationale": (
                    f"(sub-agent budget exceeded after {sa_result.turns_used} turns; "
                    "defaulting to survives)"
                ),
                "contradicting_paper_id": None,
                **observability,
            },
            "errors": ["sub-agent timeout; verdict defaulted to 'survives'"]
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
