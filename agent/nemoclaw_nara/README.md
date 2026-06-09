# `agent/nemoclaw_nara/` — the Nara-on-NemoClaw agent bundle (β groundwork)

**Status: DRAFT, not wired into a live sandbox.** Created 2026-06-09 (Limb D)
as the β groundwork for running Nara as an OpenClaw agent inside the
`nara-sandbox`, driving the unchanged host apparatus through a host-side tool
plane (`orchestrator/tool_plane.py`). Applying this bundle to a live sandbox is
**human/integrator** work gated on the gateway recovery — see
[`../../docs/nemoclaw_smoke_runbook.md`](../../docs/nemoclaw_smoke_runbook.md).

## Why this exists (the β re-frame)

The 2026-06-09 de-risk proved the sandbox is genuinely isolated: no `chromadb`,
no repo, no `/mnt`, 6 pip packages. So D-031's "NemoClawRuntime is a mechanical
worker swap" is **falsified** — β is a real *port*: package Nara as an OpenClaw
agent bundle (this dir) + a host-side tool plane around the unchanged Python.
The closed action menu becomes the OpenClaw tool allow-list (the γ permission
mechanism arriving early).

## Files

| File | What it is |
| --- | --- |
| `agent.json` | OpenClaw agent manifest — harness = **local Gemma** (NOT the default `claude-cli`; D-013/D-014), the single tool allow-list, the egress allow-rule the agent needs. |
| `system_prompt.md` | Nara's coordinator persona — assess → propose → stop, with the honesty rules. |
| `tools.json` | The tool manifest — a **static mirror** of `tool_plane.py`'s `GET /tools`. Exactly one read-only tool, `get_apparatus_state`. |

## Two load-bearing constraints baked in

1. **Local harness, never Claude.** The OpenClaw default agent harness is
   `claude-cli`. D-014 forbids the apparatus *runtime* from authenticating to
   Claude; D-013 pins the harness to the local model. `agent.json` selects the
   `vllm-local` / `gemma-4-26b-a4b` provider explicitly. On
   `nemoclaw onboard` / `rebuild`, pass `--agent` to pick the local harness.
2. **MUST-NOTs by capability absence.** The bundle grants exactly one
   read-only tool. No write / experiment / spawn / commit / trade tool is
   present, so the agent physically cannot do those — enforced by absence, not
   by a downstream schema check (per the 2026-06-09 autonomy-boundary finding).

## Placeholders to fill at apply time

`<HOST_HOSTNAME>` (the host's resolvable hostname — **not** a raw IP; the egress
SSRF guard 403s bare-IP literals) and `<PORT>` / `<TOOL_PLANE_PORT>` (the tool
plane's `--port`, default `8077`) appear in `agent.json` and `tools.json`. The
runbook says exactly where.
