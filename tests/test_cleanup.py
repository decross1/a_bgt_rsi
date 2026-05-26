"""Tests for agent_wrapper.cleanup.strip_channel_markup.

Inputs are the actual artifacts we've seen leak in iter-001..iter-008
plus a few defensive cases.
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agent_wrapper.cleanup import strip_channel_markup


def test_none_returns_none():
    assert strip_channel_markup(None) is None


def test_empty_returns_empty():
    assert strip_channel_markup("") == ""


def test_clean_text_unchanged():
    text = "The hypothesis is that cooperation rises with context-window size."
    assert strip_channel_markup(text) == text


def test_strips_closing_channel_token():
    raw = "<channel|>The initial research phase focused on retrieving foundational frameworks."
    assert strip_channel_markup(raw) == (
        "The initial research phase focused on retrieving foundational frameworks."
    )


def test_strips_opening_channel_token():
    raw = "<|channel>The retrieved literature confirms..."
    assert strip_channel_markup(raw) == "The retrieved literature confirms..."


def test_strips_full_double_token():
    raw = "<|channel|>Content here"
    assert strip_channel_markup(raw) == "Content here"


def test_strips_thought_label_with_channel_token():
    # Real leak from iter-006's narration log
    raw = "thought\n<channel|>"
    assert strip_channel_markup(raw) == ""


def test_strips_nested_channel_markup():
    # Real leak from iter-006's narration_log entry
    raw = "thought\n<|channel>thought\n<channel|>"
    assert strip_channel_markup(raw) == ""


def test_strips_thought_prefix_with_content():
    # Real leak from iter-008's nara_summary
    raw = (
        "thought\n"
        "<channel|>This iteration investigated the hypothesis that "
        "increasing context window size matters."
    )
    out = strip_channel_markup(raw)
    assert "thought" not in out.split("\n")[0]
    assert "<channel|>" not in out
    assert out.startswith("This iteration investigated")


def test_preserves_substantive_content():
    # The word "thought" inside normal prose must NOT be stripped.
    raw = "Schelling's *thought experiment* about coordination is well-known."
    out = strip_channel_markup(raw)
    assert "thought experiment" in out


def test_collapses_excess_blank_lines():
    raw = "Line 1\n\n\n\nLine 2"
    out = strip_channel_markup(raw)
    assert out == "Line 1\n\nLine 2"


def test_strips_analysis_variant():
    # Also seen with `analysis` channel in some Gemma builds
    raw = "<|analysis|>The retrieved evidence suggests..."
    out = strip_channel_markup(raw)
    assert out == "The retrieved evidence suggests..."


def test_strips_final_variant():
    raw = "<|final|>Conclusion: the claim survives."
    out = strip_channel_markup(raw)
    assert out == "Conclusion: the claim survives."


def test_does_not_touch_json():
    # JSON content with curly braces and quotes should pass through.
    raw = '<channel|>{"verdict": "survives", "rationale": "ok"}'
    out = strip_channel_markup(raw)
    assert out == '{"verdict": "survives", "rationale": "ok"}'


def test_strips_only_lone_thought_lines():
    # Standalone `thought` on its own line — stripped.
    # `thought` in a multi-word line — preserved.
    raw = (
        "thought\n"
        "The Folk Theorem implies cooperation is sustainable.\n"
        "This is a deep thought worth pursuing.\n"
    )
    out = strip_channel_markup(raw)
    assert out.split("\n")[0] == "The Folk Theorem implies cooperation is sustainable."
    assert "deep thought worth pursuing" in out


def test_non_string_passes_through():
    for x in (123, [1, 2, 3], {"k": "v"}, True):
        assert strip_channel_markup(x) == x
