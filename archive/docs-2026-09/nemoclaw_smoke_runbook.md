# NemoClaw smoke runbook — sandbox → host `get_apparatus_state`

> ## ✓ PROVEN 2026-06-09 — use this, NOT the spark-7eeb/hosts-add steps below
> The host is reachable from the sandbox as **`host.openshell.internal`** (NOT the
> host's hostname `spark-7eeb`, NOT a raw IP) — it already resolves inside the
> sandbox (it's how the built-in `local-inference` preset reaches the host vLLM at
> `:8000`). So **no `hosts-add` is needed** — only a `policy-add` for the tool-plane
> port. Verified end-to-end: a sandbox `POST get_apparatus_state` returned the live
> apparatus snapshot.
> ```bash
> # 1. host: start the tool plane (binds 0.0.0.0:8077)
> env -u MOCK_LLM .venv-chroma/bin/python -m orchestrator.tool_plane --port 8077
> # 2. host: open the egress (LIVE policy add — no rebuild; dry-run first; reversible via policy-remove)
> nemoclaw nara-sandbox policy-add --from-file agent/nemoclaw_nara/host_tool_plane_egress.yaml --dry-run
> nemoclaw nara-sandbox policy-add --from-file agent/nemoclaw_nara/host_tool_plane_egress.yaml --yes
> # 3. smoke the seam from the sandbox
> nemoclaw nara-sandbox exec --no-tty -- curl -s http://host.openshell.internal:8077/health
> nemoclaw nara-sandbox exec --no-tty -- curl -s -X POST http://host.openshell.internal:8077/tools/get_apparatus_state
> ```
> CORRECTIONS to the original runbook below (Limb D's probe was partly stale):
> `spark-7eeb`+`hosts-add` is WRONG (that hostname isn't what the egress/SSRF guard
> keys on → 403); `policy-add`/`policy-list`/`hosts-add` ARE v0.0.55 CLI commands;
> `policy-add` applies LIVE (bumps the policy version) and does NOT rebuild the
> sandbox. The `doctor` "Gateway: Docker container fail" is the known-stale probe
> (#3975) — the gateway is fine.

**Goal.** Prove, end-to-end, that the Nara OpenClaw agent **inside** the
`nara-sandbox` can call ONE host-side tool — `get_apparatus_state`, served by
`orchestrator/tool_plane.py` — **through the NemoClaw gateway**, and get back the
apparatus snapshot. This is the first demonstrable slice of β (Nara as a sandbox
agent driving the unchanged host apparatus behind a tool plane).

**Status / gating.** The end-to-end sandbox→host call is **GATED on the human
recovering the gateway** (`nemoclaw nara-sandbox recover`). The gateway `:18789`
is down (`connected: false` in `nemoclaw list --json`, confirming the
2026-06-09 de-risk). The **host half** of this runbook (steps H1–H2) is fully
verified working today; the **sandbox half** (steps S1–S5) needs the recovered
gateway. Run every step in order; each step states what it proves and what to
do if it fails.

**Verified environment facts (this host, 2026-06-09):**
- Host hostname: **`spark-7eeb`**. LAN IP `10.0.0.73`; docker bridge gw `172.17.0.1`.
- nemoclaw **v0.0.55**. Sandbox `nara-sandbox`, provider `vllm-local`, model
  `gemma-4-26b-a4b`, `dashboardPort: 18789`, `agent: null`, `connected: false`.
- Existing sandbox policy presets include `local-inference` (the host vLLM route
  via the egress proxy at `10.200.0.1:3128`) — but **no** allow-rule for the
  host tool plane yet.

---

## CORRECTION to the prior cycle's claim (read this first)

A prior probe reported that **`policy-add` is NOT a v0.0.55 CLI command**. That
is **wrong** — verified against the installed binary. v0.0.55 lists, verbatim:

```
nemoclaw <name> policy-add   Add a network or filesystem policy preset (--yes, -y, --dry-run, --from-file <path>, --from-dir <path>)
nemoclaw <name> hosts-add    Add a sandbox /etc/hosts alias <hostname> <ip> [--dry-run]
```

So adding a host endpoint to the egress allow-list is a **first-class CLI
operation** (`policy-add --from-file <egress.yaml>`), and the hostname-vs-IP
nuance is solved by `hosts-add` (an `/etc/hosts` alias inside the sandbox). No
blueprint hand-edit is required for this slice. Both commands support `--dry-run`
— always dry-run first. (`policy-add` mutates + may rebuild the sandbox, so it
is **human-authorized**, per the next-session handoff.)

---

## The hostname-vs-IP nuance (why this runbook is fiddly)

Limb D's prior probe proved: from inside the sandbox, a request to the host on
`:8000` returns **HTTP 200 via the host HOSTNAME** but **403 via the raw host
IP**. NemoClaw's egress / SSRF guard keys its allow decision on the **hostname**,
not the resolved IP. Consequences, baked into every step below:

1. The agent must reach the tool plane by a **hostname** (`spark-7eeb`), never a
   bare IP literal — both `agent/nemoclaw_nara/agent.json` and `tools.json` use
   a `<HOST_HOSTNAME>` placeholder for exactly this reason.
2. The sandbox must be able to **resolve** that hostname to the host. Use
   `hosts-add` to plant an `/etc/hosts` alias (`spark-7eeb` → the host IP the
   sandbox can route to).
3. The egress allow-rule (`policy-add`) must permit `spark-7eeb:<PORT>`.

---

## HOST HALF (verified working today — no gateway needed)

### H1 — start the host tool plane (under `env -u MOCK_LLM`)

```bash
env -u MOCK_LLM /home/decross1/projects/a_bgt_rsi/.venv-chroma/bin/python \
  -m orchestrator.tool_plane --host 0.0.0.0 --port 8077
```

- **`env -u MOCK_LLM` is mandatory.** `get_apparatus_state` → `assess_state` →
  the morning-topic seam loads the **real BGE-M3** embedder (MOCK_LLM stubs
  embedders). Without stripping `MOCK_LLM` the snapshot is a stubbed-embedder
  artifact, not the live apparatus. (`/health` and `/tools` do NOT load Chroma —
  only the POST does.)
- **`--host 0.0.0.0`** so the sandbox can reach it via the host hostname.
- Leave this running in its own terminal for the rest of the runbook.

### H2 — confirm the host endpoints from the host (loopback)

```bash
curl -fsS http://127.0.0.1:8077/health
curl -fsS http://127.0.0.1:8077/tools
curl -fsS -X POST http://127.0.0.1:8077/tools/get_apparatus_state | head -c 400
```

**Proves:** the tool plane serves the manifest and returns a real snapshot
(`{"tool":"get_apparatus_state","ok":true,"result":{...live findings...}}`).
**Verified 2026-06-09:** `/health` → `{"ok":true,...}`; POST returned live
`recent_findings`. If the POST hangs >~30 s on first call, that is the one-time
BGE-M3 model load — wait it out; subsequent calls are fast.

---

## SANDBOX HALF (gated on the recovered gateway)

### S0 — (HUMAN, BLOCKING) recover the gateway

```bash
nemoclaw nara-sandbox recover            # restart gateway + dashboard port-forward
nemoclaw nara-sandbox status             # expect gateway live / NIM healthy
nemoclaw nara-sandbox doctor --json      # deeper health; gateway :18789 reachable
```

**Proves:** `:18789` has a listener again (de-risk found it dead). **If it stays
dead:** stop and escalate — every step below needs it. Do **not** `rebuild` /
`destroy` to force it without human sign-off (destructive).

### S1 — plant the host hostname inside the sandbox (`hosts-add`)

First pick the host IP the **sandbox** can route to. Try the docker bridge
gateway first (`172.17.0.1`), fall back to the LAN IP (`10.0.0.73`):

```bash
nemoclaw nara-sandbox hosts-add nara-sandbox spark-7eeb 172.17.0.1 --dry-run
nemoclaw nara-sandbox hosts-add nara-sandbox spark-7eeb 172.17.0.1
nemoclaw nara-sandbox hosts-list
```

**Proves:** the sandbox now resolves `spark-7eeb` → the host. **Why a hostname
at all:** the egress guard 403s bare IPs (see the nuance section). **If the
bridge IP is unreachable from the sandbox** (network mode dependent), redo with
`10.0.0.73`; verify in S3's reachability probe.

### S2 — (HUMAN-AUTHORIZED) add the egress allow-rule (`policy-add`)

Author a one-file custom preset allowing `spark-7eeb:8077`, dry-run it, then
apply. A minimal egress preset (adjust to the v0.0.55 preset schema that
`policy-list` / an existing built-in preset reveals — dump a known preset first
to copy its exact shape):

```bash
# Inspect an existing preset's exact YAML shape to mirror it:
nemoclaw nara-sandbox policy-list

cat > /tmp/egress-tool-plane.yaml <<'YAML'
# Custom egress allow-rule: permit the sandbox agent to reach the HOST tool
# plane (get_apparatus_state). Hostname, NOT IP (egress guard keys on hostname).
name: tool-plane-egress
kind: network
egress:
  allow:
    - host: spark-7eeb
      port: 8077
YAML

nemoclaw nara-sandbox policy-add nara-sandbox --from-file /tmp/egress-tool-plane.yaml --dry-run
nemoclaw nara-sandbox policy-add nara-sandbox --from-file /tmp/egress-tool-plane.yaml --yes
nemoclaw nara-sandbox policy-list      # confirm tool-plane-egress is applied
```

**Proves:** the proxy will now permit `spark-7eeb:8077`. **Caveat:** if the
`--dry-run` patch shows the preset schema differs from the YAML above, copy the
exact field names from a built-in preset's dump and re-author. **Destructive
note:** `policy-add` may rebuild the sandbox — this is the step that needs human
authorization; do not run it autonomously.

### S3 — prove sandbox → host reachability with a raw curl (before the agent)

Isolate the network path from the agent wiring. From inside the sandbox:

```bash
nemoclaw nara-sandbox exec --no-tty -- curl -fsS http://spark-7eeb:8077/health
nemoclaw nara-sandbox exec --no-tty -- \
  curl -fsS -X POST http://spark-7eeb:8077/tools/get_apparatus_state | head -c 300
```

**Proves:** the egress allow-rule + hosts alias work and the host plane is
reachable from inside the sandbox (expect the same `{"ok":true,...}` /
snapshot). **This is the crux step** — it is the v0.0.55 analogue of the
de-risk's "sandbox→host:8000 = 200 via hostname" probe, now against the tool
plane. **If 403:** the egress rule didn't take — re-check S2 (hostname spelled
exactly, preset actually applied). **If connection-refused / timeout:** the
hosts alias points at an IP the sandbox can't route to — redo S1 with the other
host IP. **If HTTP 000:** no route at all (the de-risk's network-isolation
signature) — the host IP is wrong for the sandbox's network namespace.

### S4 — install the Nara agent bundle into the sandbox

The bundle is `agent/nemoclaw_nara/` (manifest `agent.json`, prompt
`system_prompt.md`, tools `tools.json`). Before installing, fill the placeholders
in `agent.json` + `tools.json`: `<HOST_HOSTNAME>` → `spark-7eeb`, `<PORT>` /
`<TOOL_PLANE_PORT>` → `8077`. Then onboard the agent with the **local harness**
(NOT the default `claude-cli` — D-013/D-014):

```bash
# Select the local-inference harness explicitly via --agent (the sandbox's
# `agent` field is currently null; the default would be claude-cli which both
# violates D-014 and is non-functional here — no Anthropic creds).
nemoclaw onboard --name nara-sandbox --agent <local-inference-harness-name> --resume --yes

# Deploy the tool manifest / skill into the sandbox:
nemoclaw nara-sandbox skill install /home/decross1/projects/a_bgt_rsi/agent/nemoclaw_nara
```

**Proves:** the agent runtime is the local Gemma route and the one tool is
registered. **Confirm the harness name** with `nemoclaw onboard --help` / the
agent-runtime list — `<local-inference-harness-name>` is a placeholder for the
v0.0.55 local-model agent identifier (NOT `claude-cli`). **If onboard only
offers claude-cli:** stop and escalate — the D-013/D-014 reconciliation is a
human decision, not something to route around.

### S5 — drive the end-to-end smoke (the actual proof)

Open the OpenClaw dashboard for the sandbox and have the Nara agent run one
assess cycle, OR exec a one-shot agent turn:

```bash
nemoclaw nara-sandbox dashboard-url        # authenticated OpenClaw dashboard
# In the dashboard (or a one-shot agent invocation), instruct Nara:
#   "Call get_apparatus_state and summarize the apparatus snapshot."
```

**PASS criteria (all must hold):**
1. The agent **lists** `get_apparatus_state` as an available tool.
2. The agent **calls** it and the tool plane (terminal from H1) logs the
   inbound `POST /tools/get_apparatus_state`.
3. The agent's summary is **grounded in the real snapshot** (names actual recent
   findings / the suggested topic from the live apparatus) — not confabulated.
4. The agent makes **no** attempt to write / run / spawn / trade (it has no such
   tool; capability-absence holds).

**If the agent answers without calling the tool** (confabulates a snapshot):
the tool isn't wired into its manifest — re-check S4 + the placeholder fill in
`tools.json`. **If the call 403s/refuses** even though S3's raw curl passed: the
agent is using a different host/port than the curl — re-check the filled
`base_url` in `tools.json`.

---

## Teardown / cleanup

```bash
# stop the host tool plane: Ctrl-C in the H1 terminal
nemoclaw nara-sandbox policy-remove nara-sandbox tool-plane-egress --yes   # if reverting egress
nemoclaw nara-sandbox hosts-remove nara-sandbox spark-7eeb                 # if reverting the alias
```

Leaving the egress rule + hosts alias in place is fine for iterating; remove
them if you want the sandbox back to its pre-smoke network posture.

## What this smoke does and does NOT prove

- **Does prove:** a sandboxed OpenClaw agent on the **local** model can reach the
  **host** apparatus through one read-only tool via the gateway — the β
  host-tool-plane seam, end-to-end.
- **Does NOT prove (out of scope, future slices):** any write/experiment/spawn
  tool (none granted by design); the relocated `validate_plan` host boundary; a
  verify-gate the agent can't bypass; the independent novelty skeptic. Those are
  the named β prerequisites (D-040 / D-041), not this slice.
