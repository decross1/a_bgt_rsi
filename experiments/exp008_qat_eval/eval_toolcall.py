#!/usr/bin/env python3
"""exp008 / quality eval — TOOL-CALL ADHERENCE (the binding-relevant metric).

Measures the fraction of an arm's completions that emit a tool_call the loop
can actually dispatch. Gemma 4 stochastically emits its custom inline
`<|tool_call>` markup that vLLM's parser misses; the loop bridges that with
`agent_wrapper.gemma_tool_parse`. A QAT arm that degrades tool-call fidelity
breaks the serial spine, so this is exactly the binding metric.

We import the REAL bridging parser (do NOT reimplement) and count a
completion as adherent if EITHER the response carries native OpenAI
tool_calls OR the inline parser recovers at least one tool_call from the
text content.

EVAL-ONLY. Routes the model call through a scratch backend pointed at the
arm's endpoint (never the production :8000), logs to runs/toolcall_<arm>.jsonl,
and never touches run_state/ or the production calls log. Greedy decoding
(temperature 0), one request at a time.

CLI: same arm/config/endpoint/model surface as eval_novelty.py. With no
endpoint the script makes NO live call (safe under MOCK_LLM).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

EXP_DIR = Path(__file__).resolve().parent
REPO_ROOT = EXP_DIR.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

RUNS_DIR = EXP_DIR / "runs"

# A small fixed prompt set that should elicit exactly one tool_call each. The
# tool names match real LOOP_V0 workers so the arm is exercised on the loop's
# actual vocabulary. System message instructs a single tool call; greedy
# decoding keeps it reproducible.
TOOL_SYSTEM_PROMPT = (
    "You are the NARA orchestrator in the a_bgt_rsi research apparatus. "
    "For the user's request, emit EXACTLY ONE tool call to the named worker "
    "and nothing else."
)

PROMPT_SET = [
    {
        "id": "retrieve_literature",
        "user": (
            "Retrieve the top-5 nearest neighbors for the hypothesis: "
            "'Tit-for-tat dominates iterated Prisoner's Dilemma.' "
            "Call the retrieve_literature tool."
        ),
    },
    {
        "id": "novelty_classify",
        "user": (
            "Classify the novelty of the current hypothesis against the "
            "retrieved neighbors. Call the novelty_classify tool."
        ),
    },
    {
        "id": "hypothesize",
        "user": (
            "Generate one new hypothesis in behavioral game theory. "
            "Call the hypothesize tool."
        ),
    },
    {
        "id": "critique",
        "user": (
            "Critique the current hypothesis for soundness and scope. "
            "Call the critique tool."
        ),
    },
]


def _register_arm_backend(endpoint: str, model: str | None) -> str:
    """Register an OpenAI-compat scratch backend for the arm. NEVER :8000."""
    from agent_wrapper.backends.ollama_openai import OllamaBackend
    from agent_wrapper.wrapper import register_backend

    if ":8000" in endpoint:
        raise ValueError(
            f"refusing arm endpoint {endpoint!r}: :8000 is the production "
            "endpoint and is off-limits to this eval"
        )
    name = "exp008-qat-arm"
    register_backend(
        OllamaBackend(
            name=name,
            base_url=endpoint,
            model=model or "qat-eval-model",
            model_version=f"exp008-qat/{model or 'qat-eval-model'}",
        )
    )
    return name


def is_parseable_toolcall(record: dict) -> tuple[bool, int]:
    """Decide whether a completion record carries a dispatchable tool_call.

    Returns (adherent, n_parsed). A completion is adherent if the bridging
    parser recovers >=1 inline tool_call from the completion text, OR the
    record already logged a native tool_call (the wrapper serializes native
    tool_calls into the completion field as JSON; the inline parser will not
    match that, so we also accept a native-shaped tool_calls payload).
    """
    from agent_wrapper.gemma_tool_parse import parse_inline_tool_calls

    completion = record.get("completion") or ""
    parsed = parse_inline_tool_calls(completion)
    if parsed:
        return True, len(parsed)
    # Native path: call_with_tools serializes OpenAI tool_calls into the
    # completion as a JSON array of {id,type,function:{name,arguments}}.
    try:
        payload = json.loads(completion)
    except (json.JSONDecodeError, TypeError):
        return False, 0
    if isinstance(payload, list) and payload and all(
        isinstance(tc, dict) and "function" in tc for tc in payload
    ):
        return True, len(payload)
    return False, 0


def run_eval(
    *,
    arm: str,
    caller,
    prompts: list[dict] = PROMPT_SET,
    backend: str | None,
    model: str | None,
    runs_dir: Path = RUNS_DIR,
) -> dict:
    """Drive each prompt through the arm and count parseable tool_calls.

    `caller(messages, **kwargs) -> record` is injected (the real
    wrapper.call_sync in production, a stub in tests). Writes one row per
    (arm, prompt) and returns aggregate metrics.
    """
    runs_dir.mkdir(parents=True, exist_ok=True)
    out_path = runs_dir / f"toolcall_{arm}.jsonl"
    rows: list[dict] = []
    with open(out_path, "w") as fh:
        for p in prompts:
            messages = [
                {"role": "system", "content": TOOL_SYSTEM_PROMPT},
                {"role": "user", "content": p["user"]},
            ]
            kwargs = {
                "temperature": 0.0,
                "caller_tag": "exp008_toolcall",
                "max_tokens": 256,
            }
            if backend is not None:
                kwargs["backend"] = backend
            if model is not None:
                kwargs["model"] = model
            record = caller(messages, **kwargs)
            adherent, n_parsed = is_parseable_toolcall(record)
            row = {
                "timestamp": datetime.now(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
                "arm": arm,
                "prompt_id": p["id"],
                "adherent": adherent,
                "n_tool_calls": n_parsed,
                "wrapper_request_id": record.get("request_id"),
            }
            rows.append(row)
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    n = len(rows)
    adherent_n = sum(1 for r in rows if r["adherent"])
    return {
        "n": n,
        "adherent": adherent_n,
        "adherence_rate": (adherent_n / n) if n else 0.0,
        "per_prompt": rows,
    }


def _resolve_endpoint(args) -> tuple[str | None, str | None]:
    endpoint = args.endpoint
    model = args.model
    if args.config:
        cfg = json.loads(Path(args.config).read_text())
        endpoint = endpoint or cfg.get("endpoint")
        model = model or cfg.get("model")
    return endpoint, model


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="exp008 tool-call adherence eval")
    ap.add_argument("--arm", required=True, help="arm label")
    ap.add_argument("--config", help="JSON config with endpoint/model")
    ap.add_argument("--endpoint", help="OpenAI-compat base url for the arm")
    ap.add_argument("--model", help="served-model-name for the arm")
    args = ap.parse_args(argv)

    endpoint, model = _resolve_endpoint(args)
    if not endpoint:
        print(
            json.dumps(
                {
                    "arm": args.arm,
                    "status": "offline",
                    "note": (
                        "no endpoint given; no live call made. Pass --endpoint "
                        "or --config with an endpoint to run the arm."
                    ),
                    "n_prompts": len(PROMPT_SET),
                }
            )
        )
        return 0

    backend = _register_arm_backend(endpoint, model)
    from agent_wrapper.wrapper import call_sync

    metrics = run_eval(
        arm=args.arm,
        caller=call_sync,
        backend=backend,
        model=model,
    )
    print(
        json.dumps(
            {
                "arm": args.arm,
                "endpoint": endpoint,
                "adherence_rate": metrics["adherence_rate"],
                "adherent": metrics["adherent"],
                "n": metrics["n"],
                "out": str(RUNS_DIR / f"toolcall_{args.arm}.jsonl"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
