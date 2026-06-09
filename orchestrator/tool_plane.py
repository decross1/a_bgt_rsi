"""Minimal HOST-side tool plane — the β groundwork (D-031/D-008 amendment).

β = Nara packaged as an OpenClaw agent INSIDE the nara-sandbox, driving the
unchanged Python apparatus that stays HOST-side behind a thin tool API. The
2026-06-09 de-risk proved the sandbox is genuinely isolated (no chromadb / no
repo / no /mnt), so "exec our workers in the sandbox" is impossible; β is a
real port, host-tool-plane FIRST. THIS module is that first piece: ONE
read-only tool, `get_apparatus_state`, served over plain HTTP so a sandboxed
OpenClaw agent can fetch the apparatus snapshot through the NemoClaw gateway.

Scope discipline (inviolate rule 8 — resist abstraction):
  - exactly ONE tool, and it just wraps orchestrator.coordinator.assess_state
    (the same pure read the coordinator planner already digests);
  - read-only — no handler mutates anything; there is no write path here;
  - a tiny MCP-flavoured manifest (`GET /tools`) + a JSON-RPC-ish call endpoint
    (`POST /tools/get_apparatus_state`) so the OpenClaw bundle has a
    discoverable, stable contract to bind to;
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
from typing import Any, Callable

from fastapi import FastAPI

from orchestrator.coordinator import assess_state

# The single tool's stable name + a one-line description for the manifest.
TOOL_NAME = "get_apparatus_state"
TOOL_DESCRIPTION = (
    "Return a compact, read-only snapshot of the a_bgt_rsi research apparatus "
    "(in-flight run, recent loop findings, open threads, gaps, surfaced/pending "
    "findings, experiments, and one morning-loop topic suggestion). Pure read; "
    "mutates nothing."
)

# Default host bind. 0.0.0.0 so the NemoClaw sandbox can reach it via the host
# HOSTNAME (raw-IP is 403 by the egress SSRF guard — see the module docstring).
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8077


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


def create_app(
    *,
    assess: Callable[[], dict[str, Any]] = assess_state,
) -> FastAPI:
    """Build the FastAPI tool-plane app.

    `assess` is injectable so the test can pass a hermetic stub — the real
    default (`coordinator.assess_state`) loads Chroma via its topic-suggestion
    seam, which is NOT what a unit test should touch. The endpoints are pure
    pass-throughs; all apparatus logic stays in the unchanged coordinator.
    """
    app = FastAPI(title="a_bgt_rsi host tool plane", version="0")

    @app.get("/health")
    def health() -> dict[str, Any]:
        """Liveness probe — does NOT call assess (no Chroma load on a ping)."""
        return {"ok": True, "tools": [TOOL_NAME]}

    @app.get("/tools")
    def list_tools() -> dict[str, Any]:
        """MCP-style discovery: the one tool the sandbox agent may call."""
        return {"tools": [_tool_manifest()]}

    @app.post("/tools/" + TOOL_NAME)
    def call_get_apparatus_state() -> dict[str, Any]:
        """Invoke the one read-only tool: return the apparatus state snapshot.

        Wraps the result in a stable `{tool, ok, result}` envelope so the
        OpenClaw agent gets a predictable shape regardless of the snapshot's
        internal keys. assess_state never raises (pure tolerant reads), so this
        endpoint does not need a try/except — a degraded apparatus yields a
        thin-but-valid snapshot, never a 500.
        """
        return {"tool": TOOL_NAME, "ok": True, "result": assess()}

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
