"""Tool registry for Nara.

Two parallel data structures:

- `TOOL_REGISTRY: dict[str, Callable]` — the dispatch table the
  Runtime uses to actually execute a tool.

- `TOOL_SPECS: list[dict]` — OpenAI-style function-call specs the LLM
  sees when it decides which tool to invoke. Each spec's `name` must
  match a key in TOOL_REGISTRY.

LOOP_V0 Part-2 toolbelt (as of 2026-05-26): the five workers that
implement the literature-only cognitive chain. The Part-1 hello-world
tools (summarize_paper, play_pd_match, query_chroma,
journal_writer_stub) stay as importable modules under workers/ +
orchestrator/, but are NOT registered here — Nara's belt has the
LOOP_V0 five and only those.
"""
from __future__ import annotations

from typing import Callable

from workers.hypothesize import hypothesize as _hypothesize
from workers.retrieve_literature import retrieve_literature as _retrieve_literature
from workers.novelty_classify import novelty_classify as _novelty_classify
from workers.critic_loop_v0 import critic_loop_v0 as _critic_loop_v0
from workers.journal_writer import journal_writer as _journal_writer


TOOL_REGISTRY: dict[str, Callable] = {
    "hypothesize":         _hypothesize,
    "retrieve_literature": _retrieve_literature,
    "novelty_classify":    _novelty_classify,
    "critic_loop_v0":      _critic_loop_v0,
    "journal_writer":      _journal_writer,
}


_NEIGHBOR_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "doc_id":       {"type": "string"},
        "content_hash": {"type": ["string", "null"]},
        "score":        {"type": "number"},
        "chunk_text":   {"type": "string"},
        "source_layer": {"type": "string"},
        "title":        {"type": ["string", "null"]},
    },
    "required": ["doc_id", "score", "source_layer"],
    "additionalProperties": True,
}


TOOL_SPECS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "hypothesize",
            "description": (
                "STEP 1 of the LOOP_V0 chain. Generate 1-3 candidate "
                "research hypotheses from a topic in game theory / "
                "behavioral game theory / learning in games, and pick "
                "the most specific. Returns {text, candidates_considered, "
                "all_candidates}."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Research topic as a sentence or paragraph.",
                    },
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "retrieve_literature",
            "description": (
                "STEP 2 of the LOOP_V0 chain. Query the local knowledge "
                "base (foundational textbook chunks + live arXiv) for the "
                "top-K most semantically similar prior results to the "
                "hypothesis. Returns {k, neighbors: [...]} where each "
                "neighbor has doc_id, score, chunk_text, source_layer, "
                "and title."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "hypothesis_text": {
                        "type": "string",
                        "description": "The hypothesis text from STEP 1's `text` field — pass verbatim.",
                    },
                    "k": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "description": "Number of neighbors to return (default 10).",
                    },
                },
                "required": ["hypothesis_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "novelty_classify",
            "description": (
                "STEP 3 of the LOOP_V0 chain. Classify the hypothesis "
                "against the retrieved neighbors into one of "
                "{novel, rediscovery, nonsense, unclear} with rationale "
                "and the doc_id of the most-similar neighbor."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "hypothesis_text": {
                        "type": "string",
                        "description": "Hypothesis text from STEP 1 — pass verbatim.",
                    },
                    "neighbors": {
                        "type": "array",
                        "items": _NEIGHBOR_ITEM_SCHEMA,
                        "description": "The neighbors array from STEP 2's `neighbors` field — pass verbatim.",
                    },
                },
                "required": ["hypothesis_text", "neighbors"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "critic_loop_v0",
            "description": (
                "STEP 4 of the LOOP_V0 chain. Attempt to falsify the "
                "hypothesis using ONLY the retrieved neighbors. Returns "
                "one of {survives, falsified, restated, malformed} with "
                "a rationale and (for falsified/restated) the doc_id of "
                "the contradicting neighbor."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "hypothesis_text": {
                        "type": "string",
                        "description": "Hypothesis text from STEP 1 — pass verbatim.",
                    },
                    "neighbors": {
                        "type": "array",
                        "items": _NEIGHBOR_ITEM_SCHEMA,
                        "description": "The same neighbors array passed to novelty_classify — pass verbatim.",
                    },
                },
                "required": ["hypothesis_text", "neighbors"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "journal_writer",
            "description": (
                "STEP 5 of the LOOP_V0 chain (always last). Write a "
                "markdown journal entry to journal/iterations/NNN.md "
                "with hypothesis, retrieval, novelty, critique, and "
                "your final summary. The orchestrator appends the "
                "structured iteration_record to memory/loop_memory.jsonl "
                "after this returns."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "The original research topic.",
                    },
                    "hypothesis": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "candidates_considered": {"type": "integer"},
                            "all_candidates": {
                                "type": "array", "items": {"type": "string"}
                            },
                        },
                        "required": ["text"],
                        "description": "The full STEP 1 result — pass verbatim.",
                    },
                    "retrieval": {
                        "type": "object",
                        "properties": {
                            "k": {"type": "integer"},
                            "neighbors": {
                                "type": "array", "items": _NEIGHBOR_ITEM_SCHEMA,
                            },
                        },
                        "required": ["k", "neighbors"],
                        "description": "The full STEP 2 result — pass verbatim.",
                    },
                    "novelty": {
                        "type": "object",
                        "properties": {
                            "class": {
                                "type": "string",
                                "enum": ["novel", "rediscovery", "nonsense", "unclear"],
                            },
                            "rationale": {"type": "string"},
                            "top_neighbor_id": {"type": ["string", "null"]},
                        },
                        "required": ["class"],
                        "description": "The full STEP 3 result — pass verbatim.",
                    },
                    "critique": {
                        "type": "object",
                        "properties": {
                            "verdict": {
                                "type": "string",
                                "enum": ["survives", "falsified", "restated", "malformed"],
                            },
                            "rationale": {"type": "string"},
                            "contradicting_paper_id": {"type": ["string", "null"]},
                        },
                        "required": ["verdict"],
                        "description": "The full STEP 4 result — pass verbatim.",
                    },
                    "nara_summary": {
                        "type": "string",
                        "description": "Your one- or two-paragraph human-readable summary of the iteration.",
                    },
                },
                "required": ["topic", "hypothesis", "retrieval", "novelty", "critique", "nara_summary"],
            },
        },
    },
]


def all_specs() -> list[dict]:
    """Return the OpenAI tool-call specs Nara sees."""
    return TOOL_SPECS


def known_names() -> list[str]:
    return list(TOOL_REGISTRY.keys())
