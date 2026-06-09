# `agent/nemoclaw_nara/` — the Nara-on-NemoClaw agent bundle (β groundwork)

**Status: 2-tool slice. Seam PROVEN; agent not yet driven end-to-end.** The
sandbox->host tool-plane seam is proven (a sandbox `POST get_apparatus_state`
returned the live snapshot, 2026-06-09). This bundle upgrades Nara from the
read-only slice to a **runnable research agent**: it assesses the apparatus,
forms one research thesis, runs it via one bounded host iteration, and reports
the verdict. Installing + driving it in the live sandbox is **human/integrator**
work — see [`../../docs/nemoclaw_agent_run_runbook.md`](../../docs/nemoclaw_agent_run_runbook.md).

## Why this exists (the β re-frame)

The 2026-06-09 de-risk proved the sandbox is genuinely isolated (no `chromadb`,
no repo, no `/mnt`). So D-031's "NemoClawRuntime is a mechanical worker swap" is
**falsified** — β is a real *port*: package Nara as an OpenClaw agent bundle
(this dir) + a host-side tool plane (`orchestrator/tool_plane.py`) around the
unchanged Python. The closed action menu becomes the OpenClaw tool allow-list
(the γ permission mechanism, arriving early).

## Files

| File | What it is |
| --- | --- |
| `agent.json` | OpenClaw agent manifest — agent runtime = **OpenClaw** on the sandbox's **local Gemma** provider (`vllm-local`/`gemma-4-26b-a4b`); the 2-tool allow-list; the (live) egress allow-rule. |
| `system_prompt.md` | Nara's research persona — assess -> form ONE thesis -> run it via `run_loop_iteration` -> report the verdict honestly -> stop, with the honesty rules. |
| `tools.json` | The tool manifest — a **static mirror** of `tool_plane.py`'s `GET /tools`. TWO tools: `get_apparatus_state` (read) + `run_loop_iteration` (the one write-capable tool). |
| `host_tool_plane_egress.yaml` | The egress preset (`nara-host-tool-plane`) — applied LIVE at policy revision 15. |

## The 2-tool slice and its security boundary

The bundle grants exactly two tools:

1. **`get_apparatus_state`** — read-only snapshot. Mutates nothing.
2. **`run_loop_iteration(topic)`** — the **one write-capable** tool. It triggers
   **exactly one** bounded LOOP_V0 iteration (hypothesize -> retrieve ->
   novelty -> critic -> journal) and nothing else. The iteration record is
   stamped `seed.source="nemoclaw_agent"`.

The write is bounded by a **three-part, all-server-side** boundary:

- **Topic validation + low-evidence gate** — the host validates the topic; an
  off-domain or thin-evidence topic trips a low-evidence gate (a correct signal,
  not a failure). The agent cannot bypass it from the sandbox.
- **One-at-a-time** — the host enforces a single in-flight iteration.
- **Scoped egress** — the `nara-host-tool-plane` preset lets the agent reach
  `host.openshell.internal:8077` and nothing else on the host.

And the dangerous capabilities are absent by construction: **no** spawn / write-
to-repo / commit / trade tool is in `tool_allow_list` or `tools.json`, so the
agent physically cannot do those — enforced by absence, not by a downstream
schema check.

## Two load-bearing facts (corrected 2026-06-09, Limb L2)

1. **Runtime = OpenClaw on local Gemma — there is no `claude-cli` runtime.** A
   probe of nemoclaw v0.0.55 found the only installed agent runtimes are
   `openclaw` (default) and `hermes`; **no `claude-cli` runtime exists** (the
   earlier "avoid the claude-cli default" framing was wrong about this version).
   D-013/D-014 are satisfied by: agent runtime = OpenClaw, **inference** provider
   = the sandbox's already-set `vllm-local`/`gemma-4-26b-a4b`. The trap to avoid
   is `openclaw agent --local` (it "requires model provider API keys in your
   shell" — the Claude path); the **gateway-routed** `openclaw agent` (no
   `--local`) uses the local Gemma route.
2. **Proven host alias.** The sandbox reaches the host as
   **`host.openshell.internal:8077`** (NOT `spark-7eeb`, NOT a raw IP — those
   403 under the egress/SSRF guard). `base_url` in `tools.json` and the egress
   rule in `agent.json` are wired to this proven alias; the egress preset is
   applied LIVE (policy revision 15).

## Open wiring question (for the integrator)

`nemoclaw skill install` deploys a **`SKILL.md`-shaped** skill (instruction
context with `name:` frontmatter), **not** an MCP/tool registration. Two ways to
make the agent actually *call* these HTTP tools — both documented in the runbook;
the integrator picks one:

- **(a)** register the host plane as an MCP server in the sandbox's
  `openclaw.json` (the agent then sees the tools natively) — *exact schema
  UNKNOWN, integrator to confirm*; or
- **(b)** ship a `SKILL.md` that instructs the agent to reach the tools via
  `curl http://host.openshell.internal:8077/...` — the egress + the `curl`
  binary are already allow-listed in the preset (*CONFIRMED reachable*).
