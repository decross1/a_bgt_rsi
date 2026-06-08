# D-040 autonomy contract — RATIFIED (source draft)

> **STATUS: RATIFIED 2026-06-08 by the human; effective at β.**
> D-040 now lives in [`DECISIONS.md`](../../DECISIONS.md) as the authoritative
> entry, and the `CLAUDE.md` out-of-scope continuous-orchestrator guardrail has
> been amended to point at it. The contract takes effect **only at β** (it
> governs unattended Nara once Nara is packaged as the always-on OpenClaw
> agent); until β it grants no operative autonomy and the
> continuous-orchestrator guardrail stands unchanged. This file is retained as
> the source draft the ratified entry was pasted from — `DECISIONS.md` D-040 is
> authoritative if the two ever diverge. Authorship: a workflow subagent
> drafted this text; the human performed the ratification itself (the
> `DECISIONS.md` paste and the `CLAUDE.md` amendment).

---

## D-040 — Unattended Nara autonomy contract (effective at β; amends the continuous-orchestrator guardrail)

**Status.** DRAFT — pending human ratification at β. NOT in effect. Both this
entry and the `CLAUDE.md` out-of-scope guardrail amendment it depends on are
human-gated and must be cleared explicitly by the human before any unattended
Nara run.

**Date drafted.** 2026-06-08. Formalized from the autonomy contract in
`human/sessions/2026-06-08.md` (lines 14–20) and the α→β→γ build path (line 12).

**Amends (on ratification).** The `CLAUDE.md` out-of-scope guardrail
"Continuous-running orchestrator — not yet; LOOP_V0 is single-shot,
human-triggered iterations." This contract is the instrument that lifts that
guardrail — but **only at β, only when the human ratifies, and only within the
bounds below.** The guardrail stays fully in force until then; the α coordinator
brain shipped 2026-06-08 deliberately stayed host-side, non-continuous, opt-in,
default dry-run precisely so it landed under the *current* (un-amended) rules.

**Context.** β packages Nara as an always-on OpenClaw **agent** in the
`nara-sandbox` NemoClaw runtime — NOT a worker-runtime swap. The 2026-06-08
probe finding established that the sandbox is genuinely isolated (our repo/venv
are not in it; Python 3.13 vs host 3.12; the model is reachable only via
OpenClaw's provider routing), so NemoClaw runs OpenClaw agents, not our
in-process Python workers. β therefore = "package Nara as the OpenClaw agent,"
which is what makes a *continuous* Nara a real proposition and is why the
guardrail amendment is needed now and not earlier. (See the D-031/D-008 update
also pending from 2026-06-08.)

**Decision.** When ratified, unattended (scheduled, always-on) Nara operates
under the following bounded contract. Nara essentially **inherits the
human-session operating discipline** — every inviolate rule in `CLAUDE.md`
binds Nara exactly as it binds a primary session.

### Unattended Nara MAY:

1. **Plan** — on a schedule, assess whole-system health and in-flight
   experiments (reading the 2026-06-06 instrumentation:
   `active_run` / `worker_activity` / `surfaced_findings` — Nara's "eyes"),
   generate hypotheses, and plan the day.
2. **Run experiments / loop iterations** — execute LOOP_V0 iterations and
   experiment runs within its constraints.
3. **Spawn agents** — critic / review / analysis sub-agents (and coding agents
   under the same discipline) to do bounded work.
4. **Build new tools and improve the system within constraints** — additive,
   bounded work consistent with the bounded-codegen rule (inviolate rule 8).
5. **Do LIMITED commit/push** — only behind the verify gate (tests green +
   `code-review` + a real smoke). Default destination is a `nara/auto/*`
   branch. **Merges to `main` remain human.**
6. **Bubble up proposals** — surface applied/trade IDEAS and proposals through
   the messaging channels (the bubble-up mechanism), for the human to act on.

### Unattended Nara MUST NOT:

1. **Execute live trades.** Live trading is human-only (consistent with the
   Polymarket design-only guardrail / D-018). Trade IDEAS may be bubbled up;
   execution may not.
2. **Widen its own or its sub-agents' permissions beyond a granted preset.**
   Permission presets are the constrained-autonomy mechanism (this is the seam
   γ builds on); Nara may not self-escalate or grant a sub-agent more than a
   subset of its own granted preset.
3. **Bypass the verify gate.** No commit/push without tests-green + the review
   + smoke gate; no degraded/silent path around it (inviolate rule 7).
4. **Touch inviolate pins or guardrails.** Version pins (inviolate rule 2),
   human gates (rule 3), validations-never-coerced (rule 4), mandatory logging
   (rule 6), and the remaining out-of-scope guardrails stand. Nara does not
   edit `CLAUDE.md` / `DECISIONS.md` or the inviolate-rule set itself.

**Alternatives considered.**

1. **Keep the hard continuous-orchestrator ban; never go always-on.** Rejected:
   it forecloses the user's central β→γ vision (Nara as a secure, always-on
   OpenClaw agent) without retiring the *real* protection — which is the
   discipline, not the single-shot triggering. The α slice already showed the
   apparatus's discipline can be enforced mechanically (the constrained action
   menu + `validate_plan`), so "continuous" need not mean "unbounded."
2. **Go always-on with no formal contract (implicit trust).** Rejected: it
   violates the apparatus's whole premise. Autonomy without a written,
   ratified MAY/MUST-NOT boundary is exactly what the guardrail exists to
   prevent.
3. **The chosen path: a written, human-ratified, preset-bounded contract that
   amends the guardrail at β and inherits every inviolate rule.**

**Rationale.** The continuous-orchestrator guardrail was written for a
single-shot LOOP_V0 with no constrained-action enforcement and no isolated
runtime. β changes both conditions: (a) the α coordinator's
`coordinator_actions.validate_plan` proved a planner can be held to a fixed,
budgeted action menu where off-menu / over-budget / bad-arg plans are *rejected,
never executed* (verified independently 2026-06-08); and (b) NemoClaw provides
a genuinely isolated sandbox with permission presets as the autonomy lever. With
those in place, "continuous" is no longer synonymous with "unbounded," so the
guardrail can be *amended* (not revoked) to permit a disciplined always-on Nara —
in the same spirit as D-037 amending D-030 for Dynamic Workflows: when a bounded,
observable mechanism handles the failure modes an old prohibition guarded
against, amend the prohibition rather than let it cap the capability.

**What does NOT change.** Live-trade prohibition (human-only); version pins;
human gates blocking; validations never coerced; mandatory run-logging; the
single-model constraint (D-033); MOCK_LLM discipline. `main` merges stay human.
Nara cannot amend its own contract.

**Reversibility.** High by design. The amendment is one paragraph in
`CLAUDE.md`; revert it and Nara returns to single-shot, human-triggered
operation. The permission presets are the throttle — tighten or revoke a preset
to narrow Nara's authority without code changes. No data migration.

**Dependencies / sequencing.** Blocked on **β** (Nara packaged as the always-on
OpenClaw agent in `nara-sandbox`). γ (permission-scoped NemoClaw sub-agents,
`docs/specs/gamma_permission_scoped_subagents.md`) builds on this contract's
preset mechanism. The pending D-031/D-008 update (sandbox-isolation finding) is
a companion to this entry.

**Ratification gate (HUMAN-ONLY).** To put this in force the human must, in one
attended action: (1) paste this entry into `DECISIONS.md` as D-040, and
(2) amend the `CLAUDE.md` out-of-scope continuous-orchestrator guardrail to point
at D-040. Until both are done, this contract is inert and the guardrail stands
unamended.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
