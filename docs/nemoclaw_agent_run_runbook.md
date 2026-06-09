# NemoClaw AGENT run runbook — drive Nara through one assess -> thesis -> run cycle

> Sibling of [`nemoclaw_smoke_runbook.md`](nemoclaw_smoke_runbook.md). That one
> proves the **raw seam** (a `curl` from the sandbox hits the host tool plane).
> THIS one installs + drives the **Nara OpenClaw agent** so the agent itself
> calls `get_apparatus_state` then `run_loop_iteration` and reports an honest
> verdict — the first end-to-end β demo with a write-capable tool.

**Bundle under test:** [`../agent/nemoclaw_nara/`](../agent/nemoclaw_nara/)
(`agent.json`, `tools.json`, `system_prompt.md`). Goal: Nara, running on the
**local Gemma** route inside `nara-sandbox`, lists both tools, calls
`get_apparatus_state`, forms one in-domain research thesis, calls
`run_loop_iteration(topic)`, and reports the returned verdict — grounded in the
real snapshot, never confabulated. The resulting iteration must appear with
`seed.source="nemoclaw_agent"`.

Each step is marked **CONFIRMED** (verified by the Limb L2 read-only probe of
nemoclaw v0.0.55 on this host, 2026-06-09) or **UNKNOWN** (needs the
integrator/human to verify — do NOT autonomously route around an UNKNOWN).

---

## Verified environment facts (2026-06-09, read-only probe)

- **CONFIRMED — host tool plane**: served by `orchestrator/tool_plane.py` on
  `:8077`. Start it host-side (see step H1). L1 extends it with the
  `run_loop_iteration` endpoint (see "L1 dependency" below).
- **CONFIRMED — egress applied LIVE**: preset `nara-host-tool-plane` is in the
  sandbox policy at **revision 15** (`nemoclaw nara-sandbox status` shows
  `version: 15` and `network_policies.nara_host_tool_plane` -> `host:
  host.openshell.internal port: 8077`; `policy-list` shows `● nara-host-tool-plane`).
- **CONFIRMED — proven alias**: the sandbox reaches the host as
  `host.openshell.internal:8077` (NOT `spark-7eeb`, NOT a raw IP). No
  `hosts-add` needed (the alias already resolves — the built-in `local-inference`
  preset uses it for the host vLLM at `:8000`).
- **CONFIRMED — agent runtime + provider**: `nemoclaw nara-sandbox status` shows
  `Agent: OpenClaw v2026.5.18`, `Provider: vllm-local`, `Model:
  gemma-4-26b-a4b`, `Inference (vllm backend): healthy`. So the runtime is
  **OpenClaw on local Gemma**, already onboarded.
- **CONFIRMED — there is NO `claude-cli` agent runtime**: the only installed
  agent runtimes are `openclaw` (default) and `hermes` (the two
  `agents/*/manifest.yaml` in the NemoClaw clone). The earlier "select local
  instead of the claude-cli default" framing was factually wrong about this
  version. D-013/D-014 are honored by runtime=OpenClaw + provider=local Gemma.
- **CONFIRMED — the gateway exec path WORKS**: `nemoclaw nara-sandbox exec
  --no-tty -- openclaw --help` returned cleanly (and `openclaw agent --help`
  too). NOTE the contradiction: `nemoclaw list --json` / `status` report
  `connected: false`, yet `exec` succeeds and inference is healthy — consistent
  with the known-stale connection probe (doctor "Gateway: Docker container fail"
  is issue #3975). Treat `connected: false` as a **stale display**, not a
  blocker — but if `exec` ever fails, run `nemoclaw nara-sandbox recover` first.

### L1 dependency (read this — the demo's PASS criteria depend on it)

`run_loop_iteration` is **L1's** contribution. Before this runbook can pass
end-to-end, the integrator must have landed L1's spine edits:

- **CONFIRMED needed — host plane endpoint**: `POST /tools/run_loop_iteration`
  added to `orchestrator/tool_plane.py` (input `{"topic": str}`, runs one
  bounded iteration, returns `{tool, ok, result:{iteration_id, novelty_class,
  critic_verdict, low_confidence, ...}}`).
- **CONFIRMED needed — schema enum**: `schema/iteration_record.schema.json`'s
  `seed.source` enum currently is
  `["human_cli","human_ui","arxiv_pick","loop_memory_probe","coordinator"]` —
  it does **NOT** yet contain `"nemoclaw_agent"`. The L2 PASS criterion
  ("`seed.source="nemoclaw_agent"`") **fails the schema validation until L1's
  enum edit lands**. This is a spine edit (integrator-only); L2 surfaces it as a
  DRAFT, does not apply it.
- **CONFIRMED needed — manifest mirror**: once the plane serves the second tool,
  the integrator updates the guard
  `tests/test_tool_plane.py::test_tools_manifest_lists_the_one_tool` (it asserts
  `len(tools) == 1` on the live plane) and extends
  `test_manifest_matches_the_agent_bundle_tool_name` to also assert
  `run_loop_iteration` is mirrored. `tools.json` already mirrors both tools.

---

## HOST HALF (no gateway needed — verified working)

### H1 — start the host tool plane (under `env -u MOCK_LLM`)  [CONFIRMED]

```bash
env -u MOCK_LLM /home/decross1/projects/a_bgt_rsi/.venv-chroma/bin/python \
  -m orchestrator.tool_plane --host 0.0.0.0 --port 8077
```

- **`env -u MOCK_LLM` is mandatory** — `get_apparatus_state` and
  `run_loop_iteration` load the **real BGE-M3** embedder + the live workers;
  MOCK_LLM stubs them, so the snapshot/verdict would be a stub artifact.
- **`--host 0.0.0.0`** so the sandbox reaches it via the host alias.
- **Leave this terminal visible** — it is the witness for PASS criterion 3 (you
  must SEE the inbound `POST /tools/get_apparatus_state` and `POST
  /tools/run_loop_iteration` log lines when the agent calls them).

### H2 — confirm both endpoints from the host (loopback)  [CONFIRMED for tool 1; tool 2 pending L1]

```bash
curl -fsS http://127.0.0.1:8077/health
curl -fsS http://127.0.0.1:8077/tools
curl -fsS -X POST http://127.0.0.1:8077/tools/get_apparatus_state | head -c 400
# After L1 lands the second endpoint:
curl -fsS -X POST http://127.0.0.1:8077/tools/run_loop_iteration \
  -H 'content-type: application/json' \
  -d '{"topic":"Strategic stability of cooperation in repeated games played by LLM agents"}' | head -c 600
```

**Proves:** `/tools` lists both tools; the read returns a live snapshot; the run
returns a verdict envelope with `seed.source="nemoclaw_agent"` baked into the
record. **If the first POST hangs >~30 s on the first call**, that is the
one-time BGE-M3 load — wait it out.

---

## SANDBOX HALF — install + drive the agent

### S0 — confirm the gateway is reachable  [CONFIRMED reachable via exec]

```bash
nemoclaw nara-sandbox status            # expect Phase: Ready, inference healthy
nemoclaw nara-sandbox exec --no-tty -- openclaw --version    # smoke the exec path
```

**If `exec` fails (not just `connected:false`):** `nemoclaw nara-sandbox
recover`, then retry. Do **not** `rebuild`/`destroy` to force it — destructive,
human sign-off only.

### S1 — re-confirm the egress (already applied; do NOT re-add blindly)  [CONFIRMED applied]

```bash
nemoclaw nara-sandbox policy-list       # expect ● nara-host-tool-plane (active dot)
```

**Already live at revision 15.** Only if it is somehow missing, re-apply
(dry-run first — this is a LIVE policy add, **human-authorized**, no rebuild):

```bash
nemoclaw nara-sandbox policy-add --from-file agent/nemoclaw_nara/host_tool_plane_egress.yaml --dry-run
nemoclaw nara-sandbox policy-add --from-file agent/nemoclaw_nara/host_tool_plane_egress.yaml --yes
```

### S2 — re-confirm sandbox -> host reachability (before the agent)  [CONFIRMED for tool 1]

Isolate the network path from the agent wiring:

```bash
nemoclaw nara-sandbox exec --no-tty -- curl -fsS http://host.openshell.internal:8077/health
nemoclaw nara-sandbox exec --no-tty -- \
  curl -fsS -X POST http://host.openshell.internal:8077/tools/get_apparatus_state | head -c 300
```

**Proves:** the seam is live for THIS plane process (the H1 terminal logs the
POST). Verified end-to-end 2026-06-09. **If 403:** the egress preset isn't
active — re-check S1. **If connection-refused/timeout/HTTP 000:** the H1 plane
isn't running or isn't bound to `0.0.0.0`.

### S3 — the agent runtime is already OpenClaw on local Gemma  [CONFIRMED — no onboard needed]

The sandbox already shows `Agent: OpenClaw v2026.5.18` + `Provider: vllm-local`.
So you do **NOT** need a fresh `onboard` to pick a harness. The `--agent` flag
(`nemoclaw onboard ... --agent <name>`) selects between the installed runtimes
**`openclaw`** and **`hermes`** — there is no `claude-cli` to avoid; OpenClaw is
already the runtime and is on local Gemma.

> **UNKNOWN — re-onboarding semantics.** If a re-onboard is ever wanted,
> `nemoclaw onboard --name nara-sandbox --agent openclaw --resume --yes` is the
> shape, but whether `--resume` preserves the vllm-local provider binding
> vs. re-prompting is UNVERIFIED here (the probe did not run onboard — it
> mutates). **Do not run a fresh onboard autonomously**; it is integrator/human
> work. The current state needs no onboard at all.

### S4 — wire the tools INTO the agent  [SPLIT: (a) UNKNOWN, (b) CONFIRMED-reachable]

This is the one genuinely open mechanic. `nemoclaw nara-sandbox skill install
<path>` is **CONFIRMED** to require a **`SKILL.md`-shaped** directory (`name:`
frontmatter) — it is an *instruction/context* skill, **NOT** an MCP/tool
registration. So `skill install agent/nemoclaw_nara` (the bundle dir as-is)
will **NOT** validate — the bundle has `agent.json`/`tools.json`/
`system_prompt.md`, no `SKILL.md`. Two ways to make the agent actually call the
HTTP tools:

**(a) Register the host plane as an MCP server in `openclaw.json`** — the agent
then sees `get_apparatus_state` / `run_loop_iteration` as native tools. The
OpenClaw `openclaw config *` helpers exist (`config get/set/file/validate`), and
the openclaw manifest declares `inference.proxy_support: explicit` (providers in
`openclaw.json`). **UNKNOWN:** the exact `openclaw.json` MCP-server block schema
that points at `http://host.openshell.internal:8077` and maps these two tools.
The integrator must confirm the v2026.5.18 MCP-config shape (`openclaw config
file` to find the config, then add an HTTP/MCP tool server). Do not guess the
schema into a live config.

**(b) Ship a `SKILL.md` that instructs the agent to `curl` the endpoints**
[CONFIRMED reachable] — the egress preset already allow-lists
`host.openshell.internal:8077` **and** the `/usr/bin/curl` binary, and `exec`
proves curl works from the sandbox. A minimal `SKILL.md` (its `name:` frontmatter
is what `skill install` validates) telling Nara to (1) `curl -s -X POST
http://host.openshell.internal:8077/tools/get_apparatus_state`, then (2) `curl
-s -X POST .../tools/run_loop_iteration -d '{"topic":"..."}'`, plus the
`system_prompt.md` persona inlined, is the **lowest-risk path that is provably
reachable today**. (Authoring that `SKILL.md` is a NEW file — out of L2's
`files_allowed`; the integrator/human authors it.)

> **Recommendation (for the integrator):** start with **(b)** — it is the only
> path the probe could confirm reachable end-to-end. Treat **(a)** as the
> cleaner follow-up once the `openclaw.json` MCP schema is confirmed.

### S5 — drive ONE assess -> thesis -> run cycle  [CONFIRMED command path]

One-shot, gateway-routed (NOT `--local` — `--local` needs Anthropic keys; the
gateway route uses the sandbox's local Gemma):

```bash
nemoclaw nara-sandbox exec --no-tty --timeout 600 -- \
  openclaw agent --json --message \
  "Run one cycle: call get_apparatus_state, form ONE in-domain (cs.GT/econ.TH) research thesis grounded in the snapshot, call run_loop_iteration(topic) once, and report the thesis + the returned verdict (novelty_class, critic_verdict, low_confidence) honestly. Do not loop or retry."
```

Or open the dashboard and instruct Nara interactively:

```bash
nemoclaw nara-sandbox dashboard-url     # authenticated OpenClaw dashboard
```

- **`openclaw agent`** (no `--local`) runs one turn via the gateway on the
  sandbox's configured provider (local Gemma). **CONFIRMED** the subcommand
  exists and accepts `--message` / `--json` / `--timeout`.
- **UNKNOWN:** whether the embedded one-turn `openclaw agent` surfaces the tools
  wired in S4 without extra routing/binding (`openclaw agents bind` exists for
  routing). If the agent answers without tool calls, see the failure notes.

---

## PASS criteria (ALL must hold)

1. **Both tools listed.** The agent's available tools include
   `get_apparatus_state` **and** `run_loop_iteration` (S4 wiring took).
2. **Read then write, in order.** The agent calls `get_apparatus_state` first,
   then `run_loop_iteration` — and the **H1 terminal logs both inbound POSTs**
   (`POST /tools/get_apparatus_state`, then `POST /tools/run_loop_iteration`).
3. **Thesis grounded, not confabulated.** The thesis + rationale reference
   **actual** snapshot content (a real recent finding / the live suggested
   topic), and the reported verdict matches what `run_loop_iteration` returned
   (`novelty_class` / `critic_verdict` / `low_confidence`) — verify against the
   H1 terminal's response, not the agent's prose alone.
4. **Iteration recorded with the right provenance.** The new iteration appears
   host-side with **`seed.source="nemoclaw_agent"`** (requires L1's schema enum
   edit — see the L1 dependency; until then this criterion FAILS on schema
   validation, which is the correct, honest signal, not something to suppress).
5. **In-domain or honestly-gated.** Either the thesis is in `cs.GT`/`econ.TH` and
   runs, OR an off-domain thesis trips the host's low-evidence gate and the agent
   **reports the gate firing** as the outcome (does not rephrase to force a
   pass). A coerced "survives" on a thin/irrelevant corpus is a **FAIL**.
6. **No out-of-bounds action.** The agent makes no attempt to spawn / write to
   the repo / commit / trade (no such tool exists — capability absence holds).

## Failure notes

- **Agent answers without calling any tool** (confabulates a snapshot): S4
  wiring didn't take — the tools aren't in the agent's tool set. Re-check S4
  (MCP block in `openclaw.json`, or the `SKILL.md` curl instructions actually
  installed). Path (b) is the surer bet.
- **Tool call 403s/refuses** though S2's raw curl passed: the agent used a
  different host/port than the proven alias — re-check `base_url` in `tools.json`
  / the MCP block (must be `http://host.openshell.internal:8077`).
- **`run_loop_iteration` 404s**: L1's plane endpoint isn't landed yet — see the
  L1 dependency. This is expected until the integrator applies L1's spine edit.
- **Iteration written but `seed.source` missing/invalid**: L1's schema enum edit
  isn't landed — the record fails validation. Correct, honest signal; fix is the
  enum edit, not suppressing the validation.
- **`exec` fails entirely**: `nemoclaw nara-sandbox recover`, retry; do not
  rebuild/destroy without human sign-off.

## Teardown

```bash
# stop the host tool plane: Ctrl-C in the H1 terminal
# the egress preset + agent runtime are persistent state — leave them; only
# revert the egress if you want the sandbox's pre-demo network posture:
nemoclaw nara-sandbox policy-remove nara-sandbox nara-host-tool-plane --yes
```

## What this run proves / does NOT prove

- **Proves:** a sandboxed OpenClaw agent on the **local** model can both *read*
  the host apparatus and *trigger one bounded write* (a single LOOP_V0
  iteration) through the tool plane, with the write fenced by server-side topic
  validation + one-at-a-time + scoped egress + capability absence — the β
  host-tool-plane seam with its first write-capable tool, end-to-end.
- **Does NOT prove (out of scope, future slices):** any spawn/commit/trade tool
  (none granted by design); a verify-gate the agent can't bypass; the
  relocated `validate_plan` host boundary; the independent novelty skeptic as a
  hard gate. Those are the named β prerequisites (D-040 / D-041), not this slice.
```

## 2026-06-09 evening — MCP path-a OUTCOME + ops findings
**Result: 5/6 PASS, criterion 3 partial.** `iter-2026-06-09-008`
(`seed.source="nemoclaw_agent"`, novel/survives, 76s) was formed and driven by the
in-sandbox agent itself over native MCP (`nara__get_apparatus_state` then
`nara__run_loop_iteration`; H1 witnessed both inbound calls in order). The thesis was
grounded in the snapshot's real findings (cited iter-003/-004) and the agent reported
honestly. Criterion 3's *returned-verdict* report was preempted: the MCP client's
`connectionTimeoutMs: 15000` cut the synchronous response of a ~90s tool call; the SDK
retry correctly bounced off the one-at-a-time guard and the agent honestly reported the
in-flight state instead of confabulating a verdict.

**Ops rules learned (apply to every future drive):**
1. **Always pass a fresh `--session-id`.** The default `main` session lane wedged
   (compaction-timeout + `EmbeddedAttemptSessionTakeoverError` + write-lock holds); the
   wedged file is rotated aside (`088bf50f-wedged-backup-20260609.jsonl.bak`) but the
   gateway's in-memory lane state stays flaky until the sandbox is rebuilt (rebuild is
   human-gated). Fresh session ids work reliably, including MCP tool calls. This also
   retro-explains the "h2 broken pipe" failures — session-lane wedge, not the inference
   route, not the MCP registration.
2. **`run_loop_iteration` is a long job behind a short RPC.** Either raise the MCP
   client request timeout well past worst-case iteration time (~3 min with skeptic) or
   reshape the tool as submit+poll (return `iteration_id` immediately; the agent polls
   `get_apparatus_state`). The retry-vs-guard interaction is safe (guard refuses) but
   wastes an agent turn. Decide next session.
3. **Restart the tool plane after editing worker/orchestrator code** — iter-008 ran on
   the plane's stale in-memory pipe (pre-R0, no skeptic env). The plane now runs the
   final code with `NARA_SKEPTIC=1`.
