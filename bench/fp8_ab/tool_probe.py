"""Deterministic 10-turn tool-call probe (D-072 Window B step 3; role_setups R5).

Spec: docs/qwen_fp8_windows_plan.md — "the 10-turn scripted tool-call
session against :8002 (structured tool_calls arrays? JSON-string argument
replay?), identical script both arms."

Determinism: the conversation history each turn is SYNTHESIZED from the
script below — model output is classified and recorded, never fed back —
so every request's bytes are identical across arms by construction
(script_sha256 in the artifact proves the script identity).

The trap: turn t06's request replays turn t05's assistant tool call with
`function.arguments` as a JSON STRING — the known Qwen 3.8 chat-template
TypeError trap (templates that iterate arguments as a mapping TypeError
on a str, surfacing as an HTTP 4xx/5xx). Every other replay renders
arguments as a dict (the shape the qwen3_coder parser emits). A template
blow-up on t06 is recorded per-turn as DATA; the probe continues.

Per turn it records: response shape (structured tool_calls array |
XML-in-content | absent), arguments parseability, latency, HTTP status.
The XML case reuses the battery's balanced-brace extractor
(workers.novelty_skeptic._extract_json_object) — no forked parser.

Run (real window):
  env -u MOCK_LLM .venv-chroma/bin/python -m bench.fp8_ab.tool_probe \
    --endpoint http://127.0.0.1:8002/v1 --model qwen3.8-27b-fp8 \
    --arm-label fp8_38 --image-digest sha256:... --model-revision 017b...
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bench.fp8_ab.driver import (  # noqa: E402
    RUNS_DIR, TEMPERATURE, TOP_P, _default_http, write_artifact)
from workers.novelty_skeptic import _extract_json_object  # noqa: E402

DEFAULT_SEED_BASE = 20260818
PROBE_MAX_TOKENS = 1024   # tool turns are short; headroom for the
                          # reasoning channel the qwen3 parser splits off
PROBE_TIMEOUT_S = 120.0
FIXED_TIME = "2026-08-18T00:00:00Z"

SYSTEM_PROMPT = (
    "You are a tool-using assistant. Satisfy every user request by calling "
    "the provided tools; reply with tool calls whenever a tool applies."
)

TOOLS = [
    {"type": "function", "function": {
        "name": "get_time",
        "description": "Return the current UTC time as an ISO-8601 string.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "add_numbers",
        "description": "Add two numbers and return their sum.",
        "parameters": {"type": "object", "properties": {
            "a": {"type": "number"}, "b": {"type": "number"}},
            "required": ["a", "b"]}}},
    {"type": "function", "function": {
        "name": "echo",
        "description": "Echo the provided text back verbatim.",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string"}}, "required": ["text"]}}},
]


def _force(name: str) -> dict:
    return {"type": "function", "function": {"name": name}}


# The fixed script. `expect` drives BOTH the forced tool_choice and the
# synthesized history exchange (assistant tool_calls + tool results).
# t08 is the multi-tool turn: tool_choice "required" (forcing one NAME
# would preclude two calls); the user text demands both in one response.
TURNS = [
    {"name": "t01_get_time", "expect": [["get_time", {}]],
     "user": "What is the current UTC time? Call get_time."},
    {"name": "t02_add_small", "expect": [["add_numbers", {"a": 2, "b": 3}]],
     "user": "Add 2 and 3 with add_numbers."},
    {"name": "t03_echo_plain", "expect": [["echo", {"text": "alpha"}]],
     "user": "Echo the word: alpha"},
    {"name": "t04_add_negative",
     "expect": [["add_numbers", {"a": -7.5, "b": 2.25}]],
     "user": "Add -7.5 and 2.25 with add_numbers."},
    {"name": "t05_echo_unicode",
     "expect": [["echo", {"text": "καλημέρα κόσμε ✓"}]],
     "user": "Echo exactly: καλημέρα κόσμε ✓"},
    {"name": "t06_string_args_replay",
     "expect": [["echo", {"text": "replay-trap"}]],
     "user": "Echo exactly: replay-trap"},
    {"name": "t07_add_large",
     "expect": [["add_numbers", {"a": 123456789, "b": 987654321}]],
     "user": "Add 123456789 and 987654321 with add_numbers."},
    {"name": "t08_multi_tool", "multi": True,
     "expect": [["get_time", {}], ["echo", {"text": "done"}]],
     "user": "In ONE response make TWO tool calls: get_time, and echo the "
             "word done."},
    {"name": "t09_echo_json_payload",
     "expect": [["echo", {"text": "{\"k\": [1, 2, 3]}"}]],
     "user": "Echo exactly this string: {\"k\": [1, 2, 3]}"},
    {"name": "t10_add_floats",
     "expect": [["add_numbers", {"a": 0.5, "b": 0.25}]],
     "user": "Add 0.5 and 0.25 with add_numbers."},
]

# The trap coordinates (0-based): building the REQUEST for turn 5 (t06),
# the replayed exchange of turn 4 (t05) carries arguments as a JSON STRING.
# Isolated to that one request — turns 7-10 replay t05 as a dict again.
TRAP_REQUEST_TURN = 5
TRAP_REPLAYED_TURN = 4


def _tool_result(tool: str, args: dict) -> str:
    if tool == "get_time":
        return FIXED_TIME
    if tool == "add_numbers":
        return json.dumps({"sum": args["a"] + args["b"]})
    if tool == "echo":
        return args["text"]
    raise ValueError(f"unknown scripted tool: {tool}")


def script_sha256() -> str:
    canon = json.dumps(
        [SYSTEM_PROMPT, TOOLS, TURNS, TRAP_REQUEST_TURN, TRAP_REPLAYED_TURN],
        sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def build_messages(turn_index: int) -> list[dict]:
    """The full scripted message list for turn `turn_index` (0-based)."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for j in range(turn_index):
        turn = TURNS[j]
        messages.append({"role": "user", "content": turn["user"]})
        as_string = (turn_index == TRAP_REQUEST_TURN
                     and j == TRAP_REPLAYED_TURN)
        tool_calls, results = [], []
        for k, (tool, args) in enumerate(turn["expect"]):
            call_id = f"call_fp8ab_{j + 1:02d}_{k}"
            tool_calls.append({
                "id": call_id, "type": "function",
                "function": {"name": tool,
                             "arguments": (json.dumps(args) if as_string
                                           else args)}})
            results.append({"role": "tool", "tool_call_id": call_id,
                            "content": _tool_result(tool, args)})
        messages.append({"role": "assistant", "content": "",
                         "tool_calls": tool_calls})
        messages.extend(results)
    messages.append({"role": "user", "content": TURNS[turn_index]["user"]})
    return messages


# Content markers that flag tool-call markup leaked into the text channel.
XML_MARKERS = ("<tool_call", "<function_call", "<function=", "<tools>")


def classify_response(message) -> dict:
    """-> {"shape": structured|xml_in_content|absent,
           "arguments_parseable": bool|None, "calls": [...]}"""
    if not isinstance(message, dict):
        return {"shape": "absent", "arguments_parseable": None, "calls": []}
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list) and tool_calls:
        calls, parseable = [], True
        for tc in tool_calls:
            fn = (tc or {}).get("function") or {}
            raw = fn.get("arguments")
            if isinstance(raw, dict):
                ok = True
            elif isinstance(raw, str):
                try:
                    ok = isinstance(json.loads(raw), dict)
                except (json.JSONDecodeError, ValueError):
                    ok = False
            else:
                ok = False
            parseable = parseable and ok
            calls.append({"name": fn.get("name"),
                          "arguments_raw": (raw if isinstance(raw, str)
                                            else json.dumps(raw)),
                          "parseable": ok})
        return {"shape": "structured", "arguments_parseable": parseable,
                "calls": calls}
    content = message.get("content") or ""
    if isinstance(content, str) and any(m in content for m in XML_MARKERS):
        payload = _extract_json_object(content)
        return {"shape": "xml_in_content",
                "arguments_parseable": isinstance(payload, dict),
                "calls": [{"content_head": content[:300]}]}
    return {"shape": "absent", "arguments_parseable": None, "calls": []}


def run_probe(arm_label: str, model: str, endpoint: str,
              image_digest: str = "", model_revision: str = "",
              seed_base: int = DEFAULT_SEED_BASE, http=None,
              clock=time.perf_counter) -> dict:
    http = http or _default_http
    url = endpoint.rstrip("/") + "/chat/completions"
    turns_out = []
    for i, turn in enumerate(TURNS):
        payload = {
            "model": model,
            "messages": build_messages(i),
            "tools": TOOLS,
            "tool_choice": ("required" if turn.get("multi")
                            else _force(turn["expect"][0][0])),
            "temperature": TEMPERATURE, "top_p": TOP_P,
            "max_tokens": PROBE_MAX_TOKENS, "seed": seed_base + i,
        }
        rec = {"turn": i + 1, "name": turn["name"],
               "expected_tools": [t for t, _ in turn["expect"]],
               "tool_choice": payload["tool_choice"],
               "string_args_trap": i == TRAP_REQUEST_TURN}
        t0 = clock()
        try:
            status, body = http("POST", url, payload, PROBE_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001 — probe records, continues
            rec.update({"latency_s": round(clock() - t0, 3),
                        "http_status": None, "shape": "absent",
                        "arguments_parseable": None, "calls": [],
                        "error": f"{type(exc).__name__}: {exc}"})
            turns_out.append(rec)
            continue
        rec["latency_s"] = round(clock() - t0, 3)
        rec["http_status"] = status
        if status != 200 or not isinstance(body, dict):
            body_text = body if isinstance(body, str) else json.dumps(body)
            rec.update({"shape": "absent", "arguments_parseable": None,
                        "calls": [],
                        "error": f"HTTP {status}: {body_text[:300]}"})
            turns_out.append(rec)
            continue
        try:
            message = body["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            message = None
        rec.update(classify_response(message))
        rec["error"] = None
        turns_out.append(rec)
        print(f"[{i + 1:2}/10] {turn['name']:24} -> {rec['shape']} "
              f"(parseable={rec['arguments_parseable']}, "
              f"{rec['latency_s']}s)", flush=True)

    shapes = [t["shape"] for t in turns_out]
    return {
        "schema": "fp8_ab.toolprobe.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "arm_label": arm_label,
        "provenance": {
            "image_digest": image_digest, "model_revision": model_revision,
            "endpoint": endpoint, "served_model": model,
            "script_sha256": script_sha256(), "seed_base": seed_base,
            "sampling": {"temperature": TEMPERATURE, "top_p": TOP_P,
                         "max_tokens": PROBE_MAX_TOKENS},
            "string_trap": {"request_turn": TURNS[TRAP_REQUEST_TURN]["name"],
                            "replayed_turn": TURNS[TRAP_REPLAYED_TURN]["name"]},
        },
        "turns": turns_out,
        "summary": {
            "structured": shapes.count("structured"),
            "xml_in_content": shapes.count("xml_in_content"),
            "absent": shapes.count("absent"),
            "http_errors": sum(1 for t in turns_out if t.get("error")),
            "arguments_parseable": sum(
                1 for t in turns_out if t.get("arguments_parseable")),
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Deterministic 10-turn tool-call probe (D-072 Window B)")
    ap.add_argument("--endpoint", default="http://127.0.0.1:8002/v1")
    ap.add_argument("--model", required=True)
    ap.add_argument("--arm-label", required=True)
    ap.add_argument("--image-digest", required=True)
    ap.add_argument("--model-revision", required=True)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED_BASE)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    if os.environ.get("MOCK_LLM"):
        print("REFUSE: MOCK_LLM is set — this probe targets a real serve; "
              "re-run with `env -u MOCK_LLM` (CLAUDE.md rule 10).")
        return 2

    artifact = run_probe(args.arm_label, args.model, args.endpoint,
                         image_digest=args.image_digest,
                         model_revision=args.model_revision,
                         seed_base=args.seed)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = (Path(args.out) if args.out
           else RUNS_DIR / f"toolprobe_{args.arm_label}_{stamp}.json")
    write_artifact(artifact, out)
    print(json.dumps(artifact["summary"], indent=1))
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
