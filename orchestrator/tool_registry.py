"""Tool registry for Nara.

Two parallel data structures:

- `TOOL_REGISTRY: dict[str, Callable]` — the dispatch table the
  Runtime uses to actually execute a tool.

- `TOOL_SPECS: list[dict]` — OpenAI-style function-call specs the LLM
  sees when it decides which tool to invoke. Each spec's `name` must
  match a key in TOOL_REGISTRY.

Today's tools are the existing capabilities of the apparatus, exposed
to Nara for the hello-world iteration. Part 2 adds the five LOOP_V0
workers (hypothesize, retrieve_literature, novelty_classify,
critic_loop_v0, journal_writer).
"""
from __future__ import annotations

from typing import Callable

from workers.summarize_paper import summarize as _summarize
from workers.play_pd_match import play_match as _play_match
from orchestrator.chroma_query import query_top_k as _query_chroma
from orchestrator.journal_stub import journal_writer_stub as _journal_stub


TOOL_REGISTRY: dict[str, Callable] = {
    "summarize_paper":     _summarize,
    "play_pd_match":       _play_match,
    "query_chroma":        _query_chroma,
    "journal_writer_stub": _journal_stub,
}


TOOL_SPECS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "summarize_paper",
            "description": (
                "Summarize a paper from the local arXiv corpus by its "
                "arXiv ID. Returns a short structured summary including "
                "key claim, method, and evidence type."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "arxiv_id": {
                        "type": "string",
                        "description": "The arXiv ID, e.g. '2605.15049'.",
                    },
                },
                "required": ["arxiv_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "play_pd_match",
            "description": (
                "Play a single repeated Prisoner's Dilemma match between "
                "the local Gemma 4 LLM and a named opponent strategy. "
                "Returns the per-round history and aggregate cooperation rate."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "opponent": {
                        "type": "string",
                        "enum": ["tft", "grim", "all_c", "all_d", "mirror_llm"],
                        "description": "Opponent strategy.",
                    },
                    "rounds": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 200,
                        "description": "Number of rounds.",
                    },
                },
                "required": ["opponent", "rounds"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_chroma",
            "description": (
                "Query the local Chroma vector store for the top-K most "
                "semantically similar chunks across both the foundational "
                "(textbook) and live-arXiv collections. Returns neighbors "
                "with doc_id, content_hash (SHA-256 of chunk text), score, "
                "source_layer, and a title where available."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The query text (a claim or topic).",
                    },
                    "k": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "description": "How many neighbors to return (default 10).",
                    },
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "journal_writer_stub",
            "description": (
                "Finalize the current iteration. Validates an "
                "iteration_record against the schema, appends one row to "
                "memory/loop_memory.jsonl, and writes a markdown entry "
                "to journal/iterations/NNN.md. Always call this last."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": (
                            "One- or two-paragraph human-readable summary "
                            "of what was found in this iteration."
                        ),
                    },
                    "tool_calls_made": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of tool names you called this iteration.",
                    },
                },
                "required": ["summary", "tool_calls_made"],
            },
        },
    },
]


def all_specs() -> list[dict]:
    """Return the OpenAI tool-call specs Nara sees."""
    return TOOL_SPECS


def known_names() -> list[str]:
    return list(TOOL_REGISTRY.keys())
