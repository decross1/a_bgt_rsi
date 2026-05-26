"""Tests for orchestrator.tool_registry.

Each TOOL_SPECS entry:
- is a well-formed OpenAI function-tool spec
- references a callable in TOOL_REGISTRY by matching name
- has a JSON Schema for parameters

The registry is non-empty and contains the four Part-1 hello-world
tools.
"""
import sys
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from orchestrator.tool_registry import TOOL_REGISTRY, TOOL_SPECS, all_specs, known_names


EXPECTED_TOOLS = {
    "hypothesize",
    "retrieve_literature",
    "novelty_classify",
    "critic_loop_v0",
    "journal_writer",
}


def test_registry_contains_expected_tools():
    assert set(TOOL_REGISTRY) == EXPECTED_TOOLS


def test_each_spec_is_well_formed():
    for spec in TOOL_SPECS:
        assert spec.get("type") == "function"
        fn = spec.get("function")
        assert isinstance(fn, dict)
        assert "name" in fn and isinstance(fn["name"], str)
        assert "description" in fn and len(fn["description"]) > 10
        params = fn.get("parameters")
        assert isinstance(params, dict)
        # JSON Schema sanity: parameters must declare a type.
        assert params.get("type") == "object"
        # The parameters schema itself must be a valid JSON Schema.
        jsonschema.Draft7Validator.check_schema(params)


def test_spec_names_match_registry():
    spec_names = {spec["function"]["name"] for spec in TOOL_SPECS}
    assert spec_names == set(TOOL_REGISTRY)


def test_each_impl_accepts_parent_request_id_kwarg():
    """The runtime calls impls with parent_request_id=. If any impl
    rejects that kwarg, dispatch will fail at runtime. Smoke-check via
    signature inspection."""
    import inspect
    for name, impl in TOOL_REGISTRY.items():
        sig = inspect.signature(impl)
        params = sig.parameters
        has_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
        has_named = "parent_request_id" in params
        assert has_kwargs or has_named, (
            f"tool {name!r} must accept parent_request_id (named or **kwargs); "
            f"signature: {sig}"
        )


def test_helpers():
    assert sorted(known_names()) == sorted(EXPECTED_TOOLS)
    assert all_specs() == TOOL_SPECS
