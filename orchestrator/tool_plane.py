"""Minimal HOST-side tool plane — the β groundwork (D-031/D-008 amendment).

β = Nara packaged as an OpenClaw agent INSIDE the nara-sandbox, driving the
unchanged Python apparatus that stays HOST-side behind a thin tool API. The
2026-06-09 de-risk proved the sandbox is genuinely isolated (no chromadb / no
repo / no /mnt), so "exec our workers in the sandbox" is impossible; β is a
real port, host-tool-plane FIRST. THIS module is that piece: a read-only tool
`get_apparatus_state` (snapshot) PLUS the first write/compute tool
`run_loop_iteration` (triggers a HOST-side LOOP_V0 iteration on host GPU),
served over plain HTTP so a sandboxed OpenClaw agent can drive the apparatus
through the NemoClaw gateway.

Scope discipline (inviolate rule 8 — resist abstraction):
  - two tools: `get_apparatus_state` wraps orchestrator.coordinator.assess_state
    (a pure read), and `run_loop_iteration` wraps orchestrator.nara.run_iteration
    (the one compute path the sandbox may trigger);
  - `run_loop_iteration` is the FIRST tool that drives host GPU compute, so the
    boundary is enforced SERVER-SIDE here (the sandbox is untrusted): topic
    validation + a one-at-a-time guard. Neither handler ever raises out to a
    500 — a bad request returns {"ok": false, "error": ...} with HTTP 200,
    mirroring the never-raises discipline get_apparatus_state already relies on;
  - a tiny MCP-flavoured manifest (`GET /tools`) + JSON-RPC-ish call endpoints
    (`POST /tools/<name>`) so the OpenClaw bundle has a discoverable, stable
    contract to bind to;
  - does NOT import ui/ (ui/backend/app.py is a read-side precedent only, and is
    off-limits to the primary session's tool plane — it must live outside ui/).

Networking note (CORRECTED + PROVEN 2026-06-09): the sandbox reaches the host via
OpenShell's host alias **`host.openshell.internal`** (NOT the host's hostname
`spark-7eeb`, NOT a raw IP — those 403 under the egress/SSRF guard). It already
resolves inside the sandbox (the built-in `local-inference` preset uses it for
the host vLLM at :8000). So bind on 0.0.0.0 and add a `policy-add` egress rule for
`host.openshell.internal:8077` (agent/nemoclaw_nara/host_tool_plane_egress.yaml);
the sandbox then reaches this at http://host.openshell.internal:8077. Verified
end-to-end — see docs/nemoclaw_smoke_runbook.md.

Run (host side, real apparatus):
    env -u MOCK_LLM .venv-chroma/bin/python -m orchestrator.tool_plane --port 8077
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

from fastapi import Body, FastAPI, Response

from orchestrator.coordinator import assess_state
from orchestrator.nara import run_iteration as _run_iteration
from orchestrator.runtime import set_current_agent

# The read-only tool's stable name + a one-line description for the manifest.
TOOL_NAME = "get_apparatus_state"
TOOL_DESCRIPTION = (
    "Return a compact, read-only snapshot of the a_bgt_rsi research apparatus "
    "(in-flight run, recent loop findings, open threads, gaps, surfaced/pending "
    "findings, experiments, and one morning-loop topic suggestion). Pure read; "
    "mutates nothing."
)

# The first compute/write tool: trigger one HOST-side LOOP_V0 iteration.
RUN_TOOL_NAME = "run_loop_iteration"
RUN_TOOL_DESCRIPTION = (
    "Trigger ONE LOOP_V0 research iteration on the host (hypothesize -> "
    "retrieve_literature -> novelty_classify -> critic_loop_v0 -> "
    "journal_writer) for the given topic, returning the iteration's id, "
    "novelty class, critic verdict, low-confidence flag, and journal path. "
    "Runs host GPU compute; one iteration at a time."
)

# Server-side topic gate (the boundary is HERE, not in the untrusted sandbox).
MAX_TOPIC_LEN = 200

# The live-run marker nara writes for the duration of an iteration. Its mere
# existence means an iteration (or other run) is in flight — the basis for the
# default one-at-a-time guard.
_REPO_ROOT = Path(__file__).resolve().parent.parent
ACTIVE_RUN_PATH = _REPO_ROOT / "run_state" / "active_run.json"


def _default_iteration_in_flight() -> bool:
    """True iff a run is already active (run_state/active_run.json exists).

    Read-only existence check — mirrors active_run.py's "absent == idle"
    contract. nara.run_iteration writes this file at start and clears it in a
    finally, so it is the host-side single source of truth for in-flight."""
    return ACTIVE_RUN_PATH.exists()

# Default host bind. 0.0.0.0 so the NemoClaw sandbox can reach it via the host
# HOSTNAME (raw-IP is 403 by the egress SSRF guard — see the module docstring).
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8077

# MCP protocol revision this plane answers `initialize` with (streamable-HTTP,
# JSON responses only — no SSE stream; the official SDK client accepts both).
MCP_PROTOCOL_VERSION = "2025-03-26"


def _tool_manifest() -> dict[str, Any]:
    """The OpenClaw/MCP-flavoured manifest for the one exposed tool.

    `input_schema` is an empty-properties object: get_apparatus_state takes no
    arguments (it is a pure snapshot read). Shape mirrors an MCP `tools/list`
    entry so the agent bundle's tool manifest can be a thin static mirror of it.
    """
    return {
        "name": TOOL_NAME,
        "description": TOOL_DESCRIPTION,
        "input_schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    }


def _run_tool_manifest() -> dict[str, Any]:
    """Manifest entry for run_loop_iteration: one required `topic` string.

    `additionalProperties: False` is part of the contract the agent bundle
    mirrors — the sandbox sends ONLY `{"topic": ...}`; the server re-validates
    the topic regardless (the bundle schema is a hint, not the guard)."""
    return {
        "name": RUN_TOOL_NAME,
        "description": RUN_TOOL_DESCRIPTION,
        "input_schema": {
            "type": "object",
            "properties": {"topic": {"type": "string"}},
            "required": ["topic"],
            "additionalProperties": False,
        },
    }


def create_app(
    *,
    assess: Callable[[], dict[str, Any]] = assess_state,
    run_iteration: Callable[..., dict[str, Any]] = _run_iteration,
    iteration_in_flight: Callable[[], bool] = _default_iteration_in_flight,
) -> FastAPI:
    """Build the FastAPI tool-plane app.

    `assess` and `run_iteration` are injectable so the test can pass hermetic
    stubs — the real defaults load Chroma / a model, which a unit test must NOT
    touch. `iteration_in_flight` is the one-at-a-time predicate (default: does
    run_state/active_run.json exist); injectable so the test drives both the
    idle and busy branches without the filesystem. The read endpoint is a pure
    pass-through; the run endpoint adds only the server-side boundary (topic
    gate + one-at-a-time), all apparatus logic staying in the unchanged
    coordinator/nara.
    """
    app = FastAPI(title="a_bgt_rsi host tool plane", version="0")

    @app.get("/health")
    def health() -> dict[str, Any]:
        """Liveness probe — does NOT call assess (no Chroma load on a ping)."""
        return {"ok": True, "tools": [TOOL_NAME, RUN_TOOL_NAME]}

    @app.get("/tools")
    def list_tools() -> dict[str, Any]:
        """MCP-style discovery: the tools the sandbox agent may call."""
        return {"tools": [_tool_manifest(), _run_tool_manifest()]}

    @app.post("/tools/" + TOOL_NAME)
    def call_get_apparatus_state() -> dict[str, Any]:
        """Invoke the read-only tool: return the apparatus state snapshot.

        Wraps the result in a stable `{tool, ok, result}` envelope so the
        OpenClaw agent gets a predictable shape regardless of the snapshot's
        internal keys. assess_state never raises (pure tolerant reads), so this
        endpoint does not need a try/except — a degraded apparatus yields a
        thin-but-valid snapshot, never a 500.
        """
        return {"tool": TOOL_NAME, "ok": True, "result": assess()}

    @app.post("/tools/" + RUN_TOOL_NAME)
    def call_run_loop_iteration(
        body: dict[str, Any] = Body(default={}),
    ) -> dict[str, Any]:
        """Trigger ONE host-side LOOP_V0 iteration. SERVER-SIDE GATED.

        This is the first tool a sandboxed (untrusted) agent can use to spend
        host GPU compute, so the boundary lives HERE, not in the sandbox:
          * topic must be a non-empty string after strip(), <= MAX_TOPIC_LEN;
          * one iteration at a time (refuse while one is in flight).
        A rejected request returns HTTP 200 with {ok: false, error: ...} (never
        a 500 — mirrors the never-raises discipline of the read tool). On a
        valid request we call run_iteration(source="nemoclaw_agent") and extract
        the small result envelope the agent needs from the iteration_record.
        """
        topic = body.get("topic") if isinstance(body, dict) else None
        if not isinstance(topic, str):
            return {"tool": RUN_TOOL_NAME, "ok": False, "error": "topic_must_be_string"}
        topic = topic.strip()
        if not topic:
            return {"tool": RUN_TOOL_NAME, "ok": False, "error": "topic_empty"}
        if len(topic) > MAX_TOPIC_LEN:
            return {
                "tool": RUN_TOOL_NAME, "ok": False,
                "error": f"topic_too_long_max_{MAX_TOPIC_LEN}",
            }
        if iteration_in_flight():
            return {"tool": RUN_TOOL_NAME, "ok": False, "error": "iteration_in_flight"}

        # D-043 attribution: run-log rows emitted during a sandbox-agent-driven
        # iteration must carry agent="nemoclaw_agent", not inherit the default
        # "nara". finally-reset so the identity never outlives this request.
        set_current_agent("nemoclaw_agent")
        try:
            record = run_iteration(topic, source="nemoclaw_agent")
        finally:
            set_current_agent(None)
        novelty = record.get("novelty") or {}
        critique = record.get("critique") or {}
        low_confidence = bool(
            novelty.get("low_confidence") or critique.get("low_confidence")
        )
        return {
            "tool": RUN_TOOL_NAME,
            "ok": True,
            "result": {
                "iteration_id":       record.get("iteration_id"),
                "novelty_class":      novelty.get("class"),
                "critic_verdict":     critique.get("verdict"),
                "low_confidence":     low_confidence,
                "journal_entry_path": record.get("journal_entry_path"),
            },
        }

    @app.post("/mcp")
    def mcp_endpoint(payload: dict[str, Any] = Body(...)) -> Any:
        """MCP streamable-HTTP endpoint (JSON-RPC 2.0, plain-JSON responses).

        OpenClaw 2026.5.18 registers remote MCP servers via mcp.servers
        {url, transport: "streamable-http"} and connects with the official
        @modelcontextprotocol/sdk client, which speaks JSON-RPC — the bare
        REST endpoints above are not consumable by it. This handler wraps the
        SAME two gated closures; no new capability, same server-side boundary.
        Notifications (no id) get 202; unknown methods get -32601; tool errors
        surface as isError content, never a 500 (never-raises discipline).
        """
        method = payload.get("method") if isinstance(payload, dict) else None
        msg_id = payload.get("id") if isinstance(payload, dict) else None
        params = payload.get("params") if isinstance(payload, dict) else None
        params = params if isinstance(params, dict) else {}
        if msg_id is None:  # notification (e.g. notifications/initialized)
            return Response(status_code=202)

        def _result(result: dict[str, Any]) -> dict[str, Any]:
            return {"jsonrpc": "2.0", "id": msg_id, "result": result}

        if method == "initialize":
            return _result({
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "a_bgt_rsi-tool-plane", "version": "0"},
            })
        if method == "ping":
            return _result({})
        if method == "tools/list":
            # MCP spells the schema key inputSchema (the REST manifest uses
            # the Anthropic-style input_schema) — remap, content identical.
            tools = []
            for m in (_tool_manifest(), _run_tool_manifest()):
                tools.append({
                    "name": m["name"],
                    "description": m["description"],
                    "inputSchema": m["input_schema"],
                })
            return _result({"tools": tools})
        if method == "tools/call":
            name = params.get("name")
            args = params.get("arguments")
            args = args if isinstance(args, dict) else {}
            print(f"mcp tools/call -> {name}", flush=True)  # H1 order witness (T2 PASS criterion 2)
            try:
                if name == TOOL_NAME:
                    out = call_get_apparatus_state()
                elif name == RUN_TOOL_NAME:
                    out = call_run_loop_iteration(body=args)
                else:
                    return {
                        "jsonrpc": "2.0", "id": msg_id,
                        "error": {"code": -32602, "message": f"unknown tool: {name}"},
                    }
            except Exception as exc:  # never-raises discipline: isError, not 500
                out = {"tool": name, "ok": False,
                       "error": f"{type(exc).__name__}: {exc}"}
            return _result({
                "content": [{"type": "text", "text": json.dumps(out)}],
                "isError": not out.get("ok", False),
            })
        return {
            "jsonrpc": "2.0", "id": msg_id,
            "error": {"code": -32601, "message": f"method not found: {method}"},
        }

    return app


# Module-level app for `uvicorn orchestrator.tool_plane:app` if preferred over
# the CLI. Uses the real (Chroma-loading) assess_state by design — this is the
# host-side production binding, not a test.
app = create_app()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m orchestrator.tool_plane",
        description=(
            "Minimal HOST-side tool plane exposing the one read-only tool "
            "get_apparatus_state for a sandboxed OpenClaw/Nara agent (β groundwork)."
        ),
    )
    p.add_argument("--host", default=DEFAULT_HOST,
                   help=f"Bind host (default {DEFAULT_HOST}; 0.0.0.0 so the "
                        "sandbox reaches it via the host hostname).")
    p.add_argument("--port", type=int, default=DEFAULT_PORT,
                   help=f"Bind port (default {DEFAULT_PORT}).")
    args = p.parse_args(argv)

    import uvicorn  # local import: only needed when actually serving
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
