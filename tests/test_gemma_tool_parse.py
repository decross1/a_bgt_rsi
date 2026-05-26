"""Tests for agent_wrapper.gemma_tool_parse.

Test inputs include the actual leak samples we captured from
iter-009 and iter-010 — these are the real markup Gemma emits.
"""
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agent_wrapper.gemma_tool_parse import (
    GemmaToolCallParseError,
    parse_inline_tool_calls,
    split_narration_and_markup,
)


def test_no_markup_returns_empty():
    assert parse_inline_tool_calls("plain prose, no markup here") == []
    assert parse_inline_tool_calls("") == []
    assert parse_inline_tool_calls(None) == []  # type: ignore[arg-type]


def test_simple_single_string_arg():
    content = '<|tool_call>call:hypothesize{topic:<|"|>cooperation in repeated PD<|"|>}'
    out = parse_inline_tool_calls(content)
    assert len(out) == 1
    call = out[0]
    assert call["type"] == "function"
    assert call["function"]["name"] == "hypothesize"
    assert call["id"].startswith("synth-")
    args = json.loads(call["function"]["arguments"])
    assert args == {"topic": "cooperation in repeated PD"}


def test_multiple_args_mixed_types():
    content = (
        '<|tool_call>call:query_chroma{'
        'text:<|"|>folk theorem<|"|>,'
        'k:5'
        '}'
    )
    out = parse_inline_tool_calls(content)
    args = json.loads(out[0]["function"]["arguments"])
    assert args == {"text": "folk theorem", "k": 5}


def test_float_value():
    content = '<|tool_call>call:t{x:0.6253}'
    out = parse_inline_tool_calls(content)
    args = json.loads(out[0]["function"]["arguments"])
    assert args["x"] == 0.6253


def test_array_of_strings():
    content = '<|tool_call>call:t{items:[<|"|>a<|"|>,<|"|>b<|"|>,<|"|>c<|"|>]}'
    out = parse_inline_tool_calls(content)
    args = json.loads(out[0]["function"]["arguments"])
    assert args == {"items": ["a", "b", "c"]}


def test_empty_array():
    content = '<|tool_call>call:t{items:[]}'
    out = parse_inline_tool_calls(content)
    args = json.loads(out[0]["function"]["arguments"])
    assert args == {"items": []}


def test_empty_object():
    content = '<|tool_call>call:t{}'
    out = parse_inline_tool_calls(content)
    args = json.loads(out[0]["function"]["arguments"])
    assert args == {}


def test_nested_object():
    content = (
        '<|tool_call>call:t{'
        'meta:{author:<|"|>obs<|"|>,year:2024}'
        '}'
    )
    out = parse_inline_tool_calls(content)
    args = json.loads(out[0]["function"]["arguments"])
    assert args == {"meta": {"author": "obs", "year": 2024}}


def test_array_of_objects_like_neighbors():
    # The exact shape Gemma emits in iter-010's stuck call: a neighbors
    # list with multiple keys per object, some strings, some numbers.
    content = (
        '<|tool_call>call:novelty_classify{'
        'hypothesis_text:<|"|>some hypothesis<|"|>,'
        'neighbors:['
        '{doc_id:<|"|>osborne-1<|"|>,score:0.6,source_layer:<|"|>foundational<|"|>},'
        '{doc_id:<|"|>arxiv-2<|"|>,score:0.55,source_layer:<|"|>live_arxiv<|"|>}'
        ']'
        '}'
    )
    out = parse_inline_tool_calls(content)
    args = json.loads(out[0]["function"]["arguments"])
    assert args["hypothesis_text"] == "some hypothesis"
    assert len(args["neighbors"]) == 2
    assert args["neighbors"][0] == {
        "doc_id": "osborne-1", "score": 0.6, "source_layer": "foundational"
    }
    assert args["neighbors"][1]["score"] == 0.55


def test_actual_iter_010_leak_sample():
    """The real markup string captured from iter-010, with the prose
    narration prefix. Should parse cleanly."""
    content = (
        "I will now classify the novelty of the hypothesis...\n"
        "\n"
        '<|tool_call>call:novelty_classify{'
        'hypothesis_text:<|"|>LLM agents in a repeated Prisoner\'s Dilemma will exhibit higher cooperation rates when the interaction history is presented as a narrative summary compared to a chronological list of moves.<|"|>,'
        'neighbors:['
        '{chunk_text:<|"|>Large Language Models enable multi-agent systems...<|"|>,'
        'content_hash:<|"|>sha256:abc123<|"|>,'
        'doc_id:<|"|>2605.20548<|"|>,'
        'score:0.6253,'
        'source_layer:<|"|>live_arxiv<|"|>,'
        'title:<|"|>What Do Agents Communicate?<|"|>}'
        ']'
        '}'
    )
    out = parse_inline_tool_calls(content)
    assert len(out) == 1
    assert out[0]["function"]["name"] == "novelty_classify"
    args = json.loads(out[0]["function"]["arguments"])
    assert "LLM agents in a repeated Prisoner" in args["hypothesis_text"]
    assert len(args["neighbors"]) == 1
    n = args["neighbors"][0]
    assert n["doc_id"] == "2605.20548"
    assert n["score"] == 0.6253
    assert n["source_layer"] == "live_arxiv"


def test_split_narration_and_markup():
    content = (
        "I will now classify the novelty of the hypothesis.\n\n"
        '<|tool_call>call:novelty_classify{topic:<|"|>x<|"|>}'
    )
    narration, markup = split_narration_and_markup(content)
    assert narration == "I will now classify the novelty of the hypothesis."
    assert markup.startswith("<|tool_call>call:")


def test_split_narration_only_when_no_markup():
    narration, markup = split_narration_and_markup("just prose, no calls")
    assert narration == "just prose, no calls"
    assert markup == ""


def test_split_no_content_at_all():
    narration, markup = split_narration_and_markup("")
    assert narration == ""
    assert markup == ""


def test_malformed_markup_returns_empty():
    # Marker present but body never closes; should be tolerated.
    content = '<|tool_call>call:t{key:<|"|>open string never closes'
    out = parse_inline_tool_calls(content)
    assert out == []


def test_multiple_markers_in_one_content():
    # Rare but possible if Gemma emits two tool calls in one turn.
    content = (
        '<|tool_call>call:t1{a:1}'
        ' some prose '
        '<|tool_call>call:t2{b:2}'
    )
    out = parse_inline_tool_calls(content)
    assert len(out) == 2
    assert out[0]["function"]["name"] == "t1"
    assert out[1]["function"]["name"] == "t2"
    assert json.loads(out[0]["function"]["arguments"]) == {"a": 1}
    assert json.loads(out[1]["function"]["arguments"]) == {"b": 2}


def test_invalid_name_skips_marker():
    # Marker followed by a name with whitespace = not a real tool call.
    content = '<|tool_call>call:not a valid name{}'
    out = parse_inline_tool_calls(content)
    assert out == []


def test_boolean_and_null_values():
    content = '<|tool_call>call:t{a:true,b:false,c:null}'
    out = parse_inline_tool_calls(content)
    args = json.loads(out[0]["function"]["arguments"])
    assert args == {"a": True, "b": False, "c": None}


def test_synthesized_ids_are_unique():
    content = '<|tool_call>call:a{x:1} <|tool_call>call:b{y:2}'
    out = parse_inline_tool_calls(content)
    assert out[0]["id"] != out[1]["id"]
    assert out[0]["id"].startswith("synth-")


def test_handles_whitespace_inside_object():
    content = '<|tool_call>call:t{  key1 : 1 ,  key2 : 2  }'
    out = parse_inline_tool_calls(content)
    args = json.loads(out[0]["function"]["arguments"])
    assert args == {"key1": 1, "key2": 2}


def test_negative_number():
    content = '<|tool_call>call:t{x:-3.5}'
    out = parse_inline_tool_calls(content)
    args = json.loads(out[0]["function"]["arguments"])
    assert args["x"] == -3.5
