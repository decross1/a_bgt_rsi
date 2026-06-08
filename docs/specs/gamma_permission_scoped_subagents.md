# γ spec — permission-scoped NemoClaw sub-agents

> **STATUS: SPEC DRAFT.** This describes the γ stage of the α→β→γ build path
> from `human/sessions/2026-06-08.md` (line 12). γ is **blocked on β** and on
> the ratification of the D-040 autonomy contract
> (`human/drafts/D-040-autonomy-contract.md`). Nothing here is built or in
> effect. This spec does not invent autonomy beyond the 2026-06-08 session note;
> it formalizes the "graduate to permission-scoped NemoClaw sub-agents" idea
> stated there.

## 1. Purpose

γ is the stage where Nara's sub-agents **graduate from LLM personas to
permission-scoped NemoClaw sub-agents**. Today (and at β), a sub-agent
(critic / review / analysis / coding) is an *LLM persona*: it is constrained by
prompt and by Nara's orchestration, but it runs inside Nara's own authority. γ
makes the constraint **mechanical and runtime-enforced**: a graduated sub-agent
runs in NemoClaw under a **permission preset** that is a *subset* of Nara's own
granted policy. Permission presets are "the constrained-autonomy mechanism"
named in the session note (line 10); γ is where they are applied at the
sub-agent boundary.

## 2. Build-path position and dependencies

- **α (done, 2026-06-08).** Coordinator brain on the host: constrained action
  menu + `validate_plan`, opt-in, non-continuous, default dry-run. Proves the
  planner can be held to a bounded, budgeted action menu.
- **β (next).** Nara packaged as the always-on OpenClaw **agent** in
  `nara-sandbox` (NOT a worker-runtime swap — the sandbox is isolated; see the
  2026-06-08 probe finding and the pending D-031/D-008 update). The D-040
  autonomy contract is ratified here.
- **γ (this spec) — BLOCKED ON β.** Sub-agents graduate to permission-scoped
  NemoClaw sub-agents via Nara-granted policy subsets.

**Hard dependencies (all must hold before γ work begins):**

1. **β complete** — Nara is a running OpenClaw agent in NemoClaw, not just a
   host-side coordinator.
2. **D-040 ratified** — the autonomy contract is in `DECISIONS.md` and the
   `CLAUDE.md` guardrail is amended. γ inherits D-040's MUST-NOT list; without
   it there is no granted policy for a subset to be drawn from.
3. **NemoClaw permission-preset primitive available** — γ assumes NemoClaw
   exposes per-sub-agent / per-sandbox permission presets that Nara can select
   from when spawning a sub-agent. (Confirm the exact mechanism NemoClaw
   v0.0.55 / OpenClaw expose; see open questions.)

## 3. The permission-preset mechanism

The core invariant: **a graduated sub-agent's preset is always a subset of
Nara's own granted preset. Subset-only, monotonically narrowing down the spawn
tree. No sub-agent can hold an authority Nara does not hold, and no spawn may
widen a preset** (this is D-040's MUST-NOT #2, enforced at the runtime
boundary rather than by prompt).

Sketch of the mechanism:

1. **Preset catalog.** A small, named set of permission presets (e.g.
   `read-only-analysis`, `critic`, `review`, `coding-scratch`), each declaring
   what a sub-agent in that preset MAY do: which tools/skills, which filesystem
   zones, whether it may commit (and to which `nara/auto/*`-style branch),
   network/egress scope, and a resource/budget cap. Presets are the unit of
   grant; Nara picks one per spawned sub-agent.
2. **Grant = subset selection.** When Nara spawns a sub-agent it grants a preset
   that is `⊆` its own preset. A validation step (the γ analogue of α's
   `validate_plan`) rejects any grant that is not a subset — off-catalog,
   over-budget, or widening grants are **rejected, never executed**, mirroring
   the α guardrail core.
3. **Runtime enforcement.** Because the sub-agent runs as its own
   permission-scoped NemoClaw session, the preset is enforced by the sandbox
   runtime, not merely by Nara's good behavior. A coding sub-agent in
   `coding-scratch` physically cannot reach beyond its zone or commit to `main`.
4. **Default-deny.** Anything not explicitly in the granted preset is denied.
   Presets start minimal and widen only by human-edited catalog change (never by
   an agent).
5. **Audit.** Every grant logs (preset name, parent agent, sub-agent id,
   subset-check result) as first-class run-log entries, consistent with
   inviolate rule 6 and D-040's logging inheritance.

## 4. Graduation: persona → permission-scoped sub-agent

A persona "graduates" when its work needs runtime-enforced isolation rather than
prompt-level constraint — e.g. a coding sub-agent that writes and runs code, or
any sub-agent whose blast radius warrants sandbox-level containment. Graduation
maps the persona to a catalog preset and spawns it as its own NemoClaw session
under that preset. Personas that are purely advisory (and stay within Nara's own
authority) need not graduate; γ is opt-in per sub-agent, not a wholesale
migration.

## 5. Relationship to existing apparatus

- **Inherits the α pattern.** The subset-check is the γ analogue of
  `coordinator_actions.validate_plan`: a constrained-grant validator that never
  raises and never executes a bad grant.
- **Inherits D-040.** A graduated sub-agent operates strictly inside Nara's
  D-040 authority, narrowed by its preset. The MUST-NOTs (no live trades, no
  permission-widening, no verify-gate bypass, no touching pins/guardrails)
  apply to every sub-agent, transitively.
- **Spawn-contract.** Graduation should reuse the existing `spawn-contract`
  discipline (exact files, done-condition, skill subset, authority cap, budget,
  reporting, escalation) — the preset is the runtime enforcement *of* a
  spawn-contract.

## 6. Open questions

1. **NemoClaw preset primitive — exact shape?** Does NemoClaw v0.0.55 / the
   baked OpenClaw expose per-sub-agent permission presets natively, or must γ
   implement scoping above the gateway (separate sandboxes per preset, egress
   policy per sub-agent)? This determines whether γ is configuration or new
   infrastructure.
2. **Preset catalog contents.** What is the minimal initial catalog
   (`read-only-analysis`, `critic`, `review`, `coding-scratch`?) and exactly
   what each MAY do? Needs human authoring — presets are human-edited, never
   agent-edited.
3. **Subset semantics.** How is "preset ⊆ preset" defined and checked across
   heterogeneous dimensions (tools, fs zones, commit rights, egress, budget)?
   Is it a per-dimension containment check?
4. **Sub-agent commit/branch model.** Do graduated coding sub-agents commit to
   their own `nara/auto/<subagent>/*` branches that Nara then aggregates behind
   the verify gate? How does this compose with D-040's "merges to main are
   human"?
5. **Spawn depth / fan-out bounds.** What caps the spawn tree (depth, concurrent
   sub-agents) at runtime, analogous to the Dynamic Workflow 16/1000 bounds?
6. **Revocation / kill-switch.** How does the human (or Nara) revoke a granted
   preset mid-run and tear down a misbehaving sub-agent's NemoClaw session?
7. **Persona-vs-graduated boundary.** Concrete criteria for when a persona MUST
   graduate vs MAY stay an in-Nara-authority persona.
