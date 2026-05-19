#!/usr/bin/env python3
"""
Day 4 task -- end-to-end tool-call check.

Runs the prisoner's-dilemma prompt through call_with_tools and confirms
the run produces exactly two schema-valid JSONL records linked by
parent_request_id: the call where the model emits a tool call, and the
follow-up call that consumes the tool result and summarizes.

    MOCK_LLM=1 python tests/test_tool_call_e2e.py --output logs/tool_call_e2e.jsonl

MOCK_LLM=1 returns a hardcoded tool call + summary so this scaffold is
authorable and testable before Day 4's call_with_tools exists. Without
MOCK_LLM the test imports the real call_with_tools from the wrapper.

call_with_tools has NO published signature yet (the wrapper docstring
only reserves the name for Day 4). This file assumes a contract; every
assumption is tagged `DAY4-CONTRACT` -- grep for it. If Day 4 lands a
different shape, update the tagged lines. See
notes/track-b-day3-4-scaffolds.md.

Owned by Track B (tests). Does not touch run_state/; never calls vLLM
directly -- the real path delegates to the wrapper.
"""
import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MOCK = bool(os.environ.get("MOCK_LLM"))

# Real call_with_tools may not exist yet (Day 4). Import defensively so
# the mock path stays runnable on a pre-Day-4 branch.
try:  # DAY4-CONTRACT: function lives at agent_wrapper.wrapper.call_with_tools
    from agent_wrapper.wrapper import call_with_tools  # noqa: E402
    _HAVE_REAL = True
except Exception:  # ImportError, or wrapper stub / missing schema file
    call_with_tools = None
    _HAVE_REAL = False


# --------------------------------------------------------------------------
# Prisoner's dilemma prompt + tool
# --------------------------------------------------------------------------
PD_SYSTEM = (
    "You are a game-theory assistant. Use the provided tools to compute "
    "concrete payoffs before you answer."
)
PD_USER = (
    "Two suspects are interrogated separately in the prisoner's dilemma. "
    "Determine the prison sentence each receives when both choose to defect, "
    "then state which strategy is dominant and why. Call the prisoner_payoff "
    "tool to get the numbers before you answer."
)
PD_MESSAGES = [
    {"role": "system", "content": PD_SYSTEM},
    {"role": "user", "content": PD_USER},
]

# Classic prisoner's dilemma payoff table: years served by (a, b).
_PAYOFF = {
    ("cooperate", "cooperate"): (1, 1),
    ("cooperate", "defect"): (3, 0),
    ("defect", "cooperate"): (0, 3),
    ("defect", "defect"): (2, 2),
}


def prisoner_payoff(player_a, player_b):
    """Return prison sentences (years) for each prisoner given both choices."""
    years_a, years_b = _PAYOFF[(player_a, player_b)]
    return {"player_a_years": years_a, "player_b_years": years_b}


_PD_TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "prisoner_payoff",
        "description": "Prison sentence in years for each prisoner given both choices.",
        "parameters": {
            "type": "object",
            "properties": {
                "player_a": {"type": "string", "enum": ["cooperate", "defect"]},
                "player_b": {"type": "string", "enum": ["cooperate", "defect"]},
            },
            "required": ["player_a", "player_b"],
        },
    },
}
# DAY4-CONTRACT: call_with_tools(messages, tools, ...) expects `tools` as a
# list of {"spec": <openai-tool-schema>, "impl": <callable>}.
PD_TOOLS = [{"spec": _PD_TOOL_SPEC, "impl": prisoner_payoff}]


# --------------------------------------------------------------------------
# Schema validation -- validate against schema/calls.jsonl.schema.json if
# present (Track A owns it); structural check only if it is not.
# --------------------------------------------------------------------------
_REQUIRED_FIELDS = [
    "timestamp", "request_id", "model", "model_version", "temperature",
    "top_p", "seed", "prompt_messages", "completion", "usage", "latency_ms",
    "host_metadata", "caller_tag", "parent_request_id",
]


def _load_validator():
    schema_path = (Path(__file__).resolve().parent.parent
                   / "schema" / "calls.jsonl.schema.json")
    try:
        import jsonschema
        return jsonschema.Draft202012Validator(json.loads(schema_path.read_text()))
    except Exception as exc:
        print(f"  [warn] call schema not validated ({exc}); structural check only",
              file=sys.stderr)
        return None


def _check_record(rec, validator):
    if validator is not None:
        validator.validate(rec)
    else:
        missing = [f for f in _REQUIRED_FIELDS if f not in rec]
        assert not missing, f"record missing fields: {missing}"


# --------------------------------------------------------------------------
# Mock tool-call chain -- two schema-valid records linked by parent_request_id.
# --------------------------------------------------------------------------
def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _approx_tokens(text):
    return len(text.split())


def _mock_record(messages, completion, *, caller_tag, parent_request_id,
                 temperature, request_id=None):
    return {
        "timestamp": _now(),
        "request_id": request_id or str(uuid.uuid4()),
        "model": "gemma-4-26b-a4b",
        "model_version": "MOCK-no-gpu",
        "temperature": temperature,
        "top_p": 1.0,
        "seed": None,
        "prompt_messages": [{"role": m["role"], "content": m["content"]}
                            for m in messages],
        "completion": completion,
        "usage": {
            "input_tokens": sum(_approx_tokens(m["content"]) for m in messages),
            "output_tokens": _approx_tokens(completion),
        },
        "latency_ms": 0.0,
        "host_metadata": {"cuda_driver": "13.0",
                          "vllm_image_tag": "vllm/vllm-openai:v0.20.0"},
        "caller_tag": caller_tag,
        "parent_request_id": parent_request_id,
    }


def mock_tool_chain(temperature, caller_tag="test_tool_call_e2e"):
    """Simulate one call_with_tools run: model emits a tool call, the tool
    runs, the result is fed back, the model summarizes. Returns 2 records."""
    # Turn 1: the model decides to call the tool.
    tool_call_text = ('TOOL_CALL prisoner_payoff '
                      '{"player_a": "defect", "player_b": "defect"}')
    rec1 = _mock_record(PD_MESSAGES, tool_call_text,
                        caller_tag=f"{caller_tag}/step1",
                        parent_request_id=None, temperature=temperature)

    # The tool executes against the same impl the real path would use.
    tool_result = prisoner_payoff("defect", "defect")

    # Turn 2: assistant tool-call turn + tool result fed back; model summarizes.
    # Tool results travel in prompt_messages under role "tool" -- the call
    # schema's role enum allows it; there is no separate tool_calls field.
    followup = PD_MESSAGES + [
        {"role": "assistant", "content": tool_call_text},
        {"role": "tool", "content": json.dumps(tool_result)},
    ]
    summary = (
        "When both prisoners defect, each serves 2 years. Defection is the "
        "dominant strategy: whatever the other prisoner does, defecting yields "
        "a sentence no longer than cooperating -- and shorter if the other "
        "cooperates -- even though mutual cooperation (1 year each) is jointly "
        "better than mutual defection."
    )
    rec2 = _mock_record(followup, summary,
                        caller_tag=f"{caller_tag}/step2",
                        parent_request_id=rec1["request_id"],
                        temperature=temperature)
    return [rec1, rec2]


def _read_jsonl(path):
    with open(path) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", default="logs/tool_call_e2e.jsonl",
                    help="JSONL path for the two call records.")
    ap.add_argument("--temperature", type=float, default=0.0)
    args = ap.parse_args()

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("")  # truncate -- a re-run starts clean

    if MOCK:
        print("MOCK_LLM=1 -- using hardcoded tool call + summary")
        records = mock_tool_chain(args.temperature)
        with out.open("a") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")
    else:
        if not _HAVE_REAL:
            print("call_with_tools is not implemented yet (Day 4). "
                  "Re-run with MOCK_LLM=1 to exercise this scaffold.",
                  file=sys.stderr)
            sys.exit(1)
        # DAY4-CONTRACT: real call writes its own chain records to log_path.
        call_with_tools(PD_MESSAGES, PD_TOOLS, temperature=args.temperature,
                        caller_tag="test_tool_call_e2e", log_path=str(out))
        records = _read_jsonl(out)

    # ---- Checks (each reported independently; the test gates on all). ----
    validator = _load_validator()
    failures = []

    if len(records) != 2:
        failures.append(f"expected 2 JSONL records, got {len(records)}")

    for i, rec in enumerate(records):
        try:
            _check_record(rec, validator)
        except Exception as exc:
            failures.append(f"record {i} invalid: {exc}")

    if len(records) == 2:
        parent, child = records
        if parent["parent_request_id"] is not None:
            failures.append("first record should have parent_request_id == null")
        if child["parent_request_id"] != parent["request_id"]:
            failures.append("second record's parent_request_id does not match "
                             "the first record's request_id")
        else:
            print(f"chain linked: {parent['request_id']} -> {child['request_id']}")
        tool_turn = any(m["role"] == "tool" for m in child["prompt_messages"])
        if not tool_turn:
            failures.append("second record carries no tool-result message")

    if failures:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        sys.exit(1)
    print(f"PASS: 2 linked schema-valid records written to {out}")


if __name__ == "__main__":
    main()
