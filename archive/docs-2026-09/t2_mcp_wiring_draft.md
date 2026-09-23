# T2 — MCP wiring draft: registering the host tool plane as native tools for the sandboxed OpenClaw main agent

Limb G probe report, 2026-06-09 evening (read-only probe; NOTHING was applied).
Sandbox OpenClaw version: **OpenClaw 2026.5.18 (50a2481)** (`openclaw --version` via
`nemoclaw nara-sandbox exec`). Active config file: `/sandbox/.openclaw/openclaw.json`
(`openclaw config file` prints `$OPENCLAW_HOME/.openclaw/openclaw.json`; `openclaw mcp show`
resolves it to `/sandbox/.openclaw/openclaw.json`).

## TL;DR

1. The authoritative config key is **`mcp.servers.<name>`** (top-level `mcp` block in
   `openclaw.json`). Remote servers use `{"url": ..., "transport": "sse"|"streamable-http",
   "headers": ..., "connectionTimeoutMs": ...}`. Confirmed from the live CLI's own JSON
   schema, the installed plugin-sdk type definitions, and the runtime code (sources quoted
   below). The embedded-Pi runtime that backs `openclaw agent --agent main` consumes
   `cfg.mcp.servers` directly.
2. MCP tools surface to the agent as **`<serverName>__<toolName>`** (separator `__`),
   so a server named `nara` yields `nara__get_apparatus_state` and
   `nara__run_loop_iteration`.
3. **BLOCKER (host-side, one patch):** OpenClaw's HTTP MCP client is the official
   `@modelcontextprotocol/sdk` client (`StreamableHTTPClientTransport` / `SSEClientTransport`)
   — it speaks MCP JSON-RPC, **not** the plane's bare REST contract. The live plane at
   `http://host.openshell.internal:8077` serves only `GET /health`, `GET /tools`,
   `POST /tools/<name>`; a probe `POST /mcp` (JSON-RPC `initialize`) returns
   `{"detail":"Not Found"}` (verified against `127.0.0.1:8077` on the host, same process).
   So the registration block is schema-confirmed but only becomes functional after
   `orchestrator/tool_plane.py` (an integrator file; DRAFT patch in the limb report)
   gains a small `POST /mcp` streamable-HTTP endpoint. No sandbox-side bridge script is
   needed (and none is recommended — the sandbox is the untrusted side).

---

## (a) Authoritative block shape + sources

### Source 1 — live CLI JSON schema (primary authority)

Command (read-only):

```
nemoclaw nara-sandbox exec --no-tty -- openclaw config schema
```

Output (2.5 MB; the top-level `properties.mcp` subtree, quoted verbatim with the
`codex` projection sub-block elided — it is Codex-only metadata):

```json
"mcp": {
  "type": "object",
  "properties": {
    "servers": {
      "type": "object",
      "propertyNames": { "type": "string" },
      "additionalProperties": {
        "type": "object",
        "properties": {
          "command":          { "type": "string" },
          "args":             { "type": "array", "items": { "type": "string" } },
          "env":              { "type": "object", "additionalProperties": { "anyOf": [
                                  {"type":"string"},{"type":"number"},{"type":"boolean"} ] } },
          "cwd":              { "type": "string" },
          "workingDirectory": { "type": "string" },
          "url":              { "type": "string", "format": "uri" },
          "transport":        { "anyOf": [ { "type": "string", "const": "sse" },
                                           { "type": "string", "const": "streamable-http" } ] },
          "headers":          { "type": "object", "additionalProperties": { "anyOf": [
                                  {"type":"string"},{"type":"number"},{"type":"boolean"} ] } },
          "codex":            { "...": "Codex app-server projection metadata (elided)" }
        },
        "additionalProperties": {}
      },
      "title": "MCP Servers",
      "description": "Named MCP server definitions. OpenClaw stores them in its own config and runtime adapters decide which transports are supported at execution time."
    },
    "sessionIdleTtlMs": {
      "type": "number", "minimum": 0,
      "title": "MCP Runtime Idle TTL",
      "description": "Idle TTL in milliseconds for session-scoped bundled MCP runtimes. Defaults to 10 minutes; set 0 to disable idle eviction."
    }
  },
  "additionalProperties": false,
  "title": "MCP",
  "description": "Global MCP server definitions managed by OpenClaw. Embedded Pi and other runtime adapters can consume these servers without storing them inside Pi-owned project settings."
}
```

(There is no other tool-server key: the only top-level schema keys matching
mcp/tool are `tools` — the allow/deny/profile **policy** block, not server
registration — and `mcp`.)

### Source 2 — installed plugin-sdk type definitions (same install the agent runs)

File (read inside the sandbox, read-only):
`/usr/local/lib/node_modules/openclaw/dist/plugin-sdk/src/config/types.mcp.d.ts`

```ts
export type McpServerConfig = {
    /** Stdio transport: command to spawn. */
    command?: string;
    /** Stdio transport: arguments for the command. */
    args?: string[];
    /** Environment variables passed to the server process (stdio only). */
    env?: Record<string, string | number | boolean>;
    /** Working directory for stdio server. */
    cwd?: string;
    /** Alias for cwd. */
    workingDirectory?: string;
    /** HTTP transport: URL of the remote MCP server (http or https). */
    url?: string;
    /** HTTP transport type for remote MCP servers. */
    transport?: "sse" | "streamable-http";
    /** HTTP transport: extra HTTP headers sent with every request. */
    headers?: Record<string, string | number | boolean>;
    /** Optional connection timeout in milliseconds. */
    connectionTimeoutMs?: number;
    /** Codex-specific projection controls for Codex app-server/runtime config. */
    codex?: McpServerCodexConfig;
    [key: string]: unknown;
};
export type McpConfig = {
    servers?: Record<string, McpServerConfig>;
    sessionIdleTtlMs?: number;
};
```

Note `connectionTimeoutMs` is accepted (typed) even though the JSON schema only
admits it via `additionalProperties: {}`.

### Source 3 — runtime code paths (proves the main agent consumes the block)

- `/usr/local/lib/node_modules/openclaw/dist/embedded-pi-mcp-OSbGOvSI.js`
  (`src/agents/embedded-pi-mcp.ts`): `loadEmbeddedPiMcpConfig` →
  `normalizeConfiguredMcpServers(params.cfg?.mcp?.servers)` — the **embedded Pi
  runtime (the `main` agent) reads `mcp.servers` directly**, merged over any
  plugin-bundled MCP servers.
- `/usr/local/lib/node_modules/openclaw/dist/pi-bundle-mcp-runtime-kBY5eAjg.js`
  (`src/agents/...mcp-runtime.ts`): transport resolution — explicit
  `transport: "streamable-http"` → `new StreamableHTTPClientTransport(new URL(resolved.url),
  {requestInit: ..., fetch: fetchStreamableHttpWithRedirectScrub})`; otherwise it
  falls back to trying SSE. Clients are the **official `@modelcontextprotocol/sdk`**
  (`sdk/client/streamable`, `sdk/client/sse`, `sdk/client/stdio`). On dispose a
  streamable-http session gets `terminateSession()` (an HTTP DELETE; a 405 is
  swallowed by `.catch(() => {})`).
- `/usr/local/lib/node_modules/openclaw/dist/` (pi-bundle-mcp-names, quoted from
  the dist bundle): `TOOL_NAME_SEPARATOR = "__"`,
  `buildSafeToolName → \`${params.serverName}__${candidateToolName}\``, server-name
  fragment sanitized to `[A-Za-z0-9_-]`, max 30 chars prefix, 64 total. So tool
  names surface as **`nara__get_apparatus_state`** / **`nara__run_loop_iteration`**.

### Source 4 — live CLI commands (2026.5.18)

`openclaw mcp --help` (via `nemoclaw nara-sandbox exec --no-tty`):

```
Commands:
  list        List configured MCP servers
  serve       Expose OpenClaw channels over MCP stdio
  set         Set one configured MCP server from a JSON object
  show        Show one configured MCP server or the full MCP config
  unset       Remove one configured MCP server
```

`openclaw mcp set --help`: `Usage: openclaw mcp set [options] <name> <value>` —
"JSON object, for example {"command":"uvx","args":["context7-mcp"]}".
Current state: `openclaw mcp show` → `MCP servers (/sandbox/.openclaw/openclaw.json): {}`.

Corroborating doc: https://docs.openclaw.ai/cli/mcp documents the same
`mcp.servers` key, `url` + `transport: "streamable-http"` for remote servers. The
docs site also describes `mcp add/configure/doctor/probe` subcommands that the
installed 2026.5.18 CLI does **not** have — treat the live CLI as the authority,
the docs page as the newer-version superset.

---

## (b) The exact registration block

`mcp.servers` entries must speak the MCP protocol. The plane's REST endpoints do
not (see blocker, §TL;DR-3); the block below targets the **`/mcp` endpoint the
integrator adds to `orchestrator/tool_plane.py`** (DRAFT patch delivered in the
limb report alongside this doc).

Block to merge into `/sandbox/.openclaw/openclaw.json` (top-level key):

```json
{
  "mcp": {
    "servers": {
      "nara": {
        "url": "http://host.openshell.internal:8077/mcp",
        "transport": "streamable-http",
        "connectionTimeoutMs": 15000
      }
    }
  }
}
```

- `host.openshell.internal:8077` is the proven alias (egress preset
  `nara-host-tool-plane`, policy v15; raw IP / hostname 403 under the SSRF guard).
- Server name `nara` → agent-visible tools `nara__get_apparatus_state`,
  `nara__run_loop_iteration`.
- `transport` is set explicitly: with it omitted the runtime resolves the entry
  as SSE first, which the plane will not serve.
- No agent-binding step is needed: embedded Pi merges `mcp.servers` for every
  agent (Source 3); the existing `tools` policy block (`{"toolSearch": true}`)
  has no `allow`/`deny` lists that would exclude the new names.

## (c) Apply / rollback / verify procedure (for the integrator — none of this was run)

### c.0 Pre-req: land the host-side `/mcp` endpoint first

1. Apply the DRAFT `tool_plane.py` patch (in the limb report) adding `POST /mcp`.
2. Restart the plane (it currently runs as host pid `2832381`,
   `.venv-chroma/bin/python -m orchestrator.tool_plane --port 8077`, cwd repo root):

   ```
   kill <tool_plane_pid>
   env -u MOCK_LLM .venv-chroma/bin/python -m orchestrator.tool_plane --port 8077
   ```

3. Host-side smoke (must return a `protocolVersion` result, not `{"detail":"Not Found"}`):

   ```
   curl -s -X POST http://127.0.0.1:8077/mcp -H 'Content-Type: application/json' \
     -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"probe","version":"0"}}}'
   curl -s -X POST http://127.0.0.1:8077/mcp -H 'Content-Type: application/json' \
     -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
   ```

### c.1 Backup the sandbox config

```
nemoclaw nara-sandbox exec --no-tty -- sh -c 'cp $HOME/.openclaw/openclaw.json $HOME/.openclaw/openclaw.json.pre-mcp-t2'
nemoclaw nara-sandbox exec --no-tty -- sh -c 'ls -la $HOME/.openclaw/openclaw.json.pre-mcp-t2'
```

### c.2 Register the server (one validated write)

```
nemoclaw nara-sandbox exec --no-tty -- openclaw mcp set nara '{"url":"http://host.openshell.internal:8077/mcp","transport":"streamable-http","connectionTimeoutMs":15000}'
```

(Equivalent alternative: `openclaw config patch --stdin` with the §(b) block —
patch merges objects recursively and validates before writing.)

### c.3 Validate + inspect

```
nemoclaw nara-sandbox exec --no-tty -- openclaw config validate
nemoclaw nara-sandbox exec --no-tty -- openclaw mcp list
nemoclaw nara-sandbox exec --no-tty -- openclaw mcp show nara
```

`config validate` must pass; `mcp show nara` must echo the §(b) entry.

### c.4 Restart the gateway so live sessions pick up the new catalog

MCP catalogs are session-scoped (fingerprinted per session config); a gateway
restart is the deterministic refresh:

```
nemoclaw nara-sandbox exec --no-tty -- openclaw gateway restart
nemoclaw nara-sandbox exec --no-tty -- openclaw gateway health
```

### c.5 Verify the agent sees both tools (PASS criterion 1)

```
nemoclaw nara-sandbox exec --no-tty --timeout 120 -- openclaw agent --agent main --json --message "List the exact names of every tool you can call right now. Do not call any tool."
```

Expect `nara__get_apparatus_state` and `nara__run_loop_iteration` in the reply
(note the `nara__` prefix — the runbook's bare names appear as the suffixes).
Caveat: `tools.toolSearch` is `true` in the current config, so the model may
surface tools via `tool_search_code` rather than a flat list; if the listing is
empty, ask it to search for "apparatus" tools before concluding the wiring
failed. Cross-check the H1 plane terminal: the MCP session `initialize` +
`tools/list` POSTs to `/mcp` are the wire-level witness.

### Rollback

```
nemoclaw nara-sandbox exec --no-tty -- sh -c 'cp $HOME/.openclaw/openclaw.json.pre-mcp-t2 $HOME/.openclaw/openclaw.json'
nemoclaw nara-sandbox exec --no-tty -- openclaw config validate
nemoclaw nara-sandbox exec --no-tty -- openclaw gateway restart
```

(Targeted alternative: `nemoclaw nara-sandbox exec --no-tty -- openclaw mcp unset nara`.)
Host side: revert the `tool_plane.py` patch and restart the plane (the REST
endpoints are unchanged by the patch either way).

## (d) The re-drive command (verbatim) + PASS criteria

```
nemoclaw nara-sandbox exec --no-tty --timeout 580 -- openclaw agent --agent main --json --message "Run one cycle: call get_apparatus_state, form ONE in-domain (cs.GT/econ.TH) research thesis grounded in the snapshot, call run_loop_iteration(topic) once, and report the thesis + the returned verdict (novelty_class, critic_verdict, low_confidence) honestly. Do not loop or retry."
```

PASS criteria, quoted verbatim from `docs/nemoclaw_agent_run_runbook.md`
("## PASS criteria (ALL must hold)"):

> 1. **Both tools listed.** The agent's available tools include
>    `get_apparatus_state` **and** `run_loop_iteration` (S4 wiring took).
> 2. **Read then write, in order.** The agent calls `get_apparatus_state` first,
>    then `run_loop_iteration` — and the **H1 terminal logs both inbound POSTs**
>    (`POST /tools/get_apparatus_state`, then `POST /tools/run_loop_iteration`).
> 3. **Thesis grounded, not confabulated.** The thesis + rationale reference
>    **actual** snapshot content (a real recent finding / the live suggested
>    topic), and the reported verdict matches what `run_loop_iteration` returned
>    (`novelty_class` / `critic_verdict` / `low_confidence`) — verify against the
>    H1 terminal's response, not the agent's prose alone.
> 4. **Iteration recorded with the right provenance.** The new iteration appears
>    host-side with **`seed.source="nemoclaw_agent"`** (requires L1's schema enum
>    edit — see the L1 dependency; until then this criterion FAILS on schema
>    validation, which is the correct, honest signal, not something to suppress).
> 5. **In-domain or honestly-gated.** Either the thesis is in `cs.GT`/`econ.TH` and
>    runs, OR an off-domain thesis trips the host's low-evidence gate and the agent
>    **reports the gate firing** as the outcome (does not rephrase to force a
>    pass). A coerced "survives" on a thin/irrelevant corpus is a **FAIL**.
> 6. **No out-of-bounds action.** The agent makes no attempt to spawn / write to
>    the repo / commit / trade (no such tool exists — capability absence holds).

MCP-transport adaptations (the criteria were written for the dead SKILL.md curl
path):

- Criterion 1: the names carry the `nara__` server prefix
  (`nara__get_apparatus_state`, `nara__run_loop_iteration`).
- Criterion 2: the H1 terminal logs `POST /mcp` JSON-RPC calls instead of
  `POST /tools/<name>`; the DRAFT `/mcp` handler logs the dispatched tool name
  per `tools/call` so the read-then-write order stays witnessable.

## Open items / honest unknowns

- Whether `tools.toolSearch: true` puts MCP tools behind `tool_search_code` for
  the gemma main agent (vs. listing them flat) was NOT verifiable read-only; c.5
  covers both outcomes.
- The docs-site `mcp` page documents extra per-server keys (`enabled`,
  `toolFilter`, `auth: "oauth"`, `supportsParallelToolCalls`) that the live
  2026.5.18 JSON schema only admits via `additionalProperties` — do not rely on
  them on this version; the §(b) block uses only schema-typed keys.
