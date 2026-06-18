# Skill-signals contract — the apparatus-side runtime skill-friction stream (D-056, 2026-06-18)

This document is the **apparatus side** of the runtime skill-signals stream. It
is **self-contained** and cites only a_bgt_rsi's own rules — it must never
require reading a framework artifact to honor it. It was produced by an
adversarial review of a framework-side handoff; the review's two hard
inviolations are corrected here and the reconciliations are baked in.

> **Status: REVIEWED + reconciled. Implementation GATED** behind the human's go
> (see "Implementation"). Triggers (b) GAP and (c) MISUSE are clean and may ship
> first; trigger (a) is reframed below.

## What this is

A best-effort, append-only stream the a_bgt_rsi runtime emits when an agent hits
genuine friction with a **framework skill** (`run-log`, `validate`, `fallback`,
…). The framework reads it **read-only** on its own ingest pass and projects it
into its drift-detection lane. The apparatus's only job is to append a line and
keep going; it does **not** replace post-hoc `harvest` — it feeds it.

## The firewall — D-014 + CLAUDE.md rule 3 (NOT the framework's `BOUNDARY.md`)

The handoff cited the framework's `BOUNDARY.md` ("Two orchestrators, one word")
as the rule source. **That is wrong for this apparatus** on two counts: a_bgt_rsi
has no `BOUNDARY.md`, and **D-032** records that this project *consciously
diverges* from the framework's `BOUNDARY.md` (it installs the full skill set the
boundary doc recommends against). Requiring the apparatus to read a framework doc
to learn its own obligation is itself a soft firewall crossing. The governing
rules here are:

- **The apparatus writes ONLY `run_state/skill_signals.jsonl`.**
- **The framework reads it read-only, one direction.** The apparatus never reads,
  writes, or imports anything under `memory/brain/`, never imports framework
  projection code, never calls a framework script (**D-014**; CLAUDE.md §Dynamic
  Workflow discipline rule 3 — "the gemma/Nara runtime never reads the brain").
- **The emit path has zero dependency on any framework file** — no `BOUNDARY.md`
  read, no `ingest_apparatus.py`/`draft_proposals.py` call, no
  `memory/brain/drift_signals.jsonl` access, no framework import. The framework's
  ingest mechanics are documented below *as context only*; they are not paths the
  apparatus touches.

## Where + shape

`run_state/skill_signals.jsonl` — append-only, one JSON object per line, **never
edit a prior line** (the same ledger discipline as `week1.run.jsonl`, rule 6).
Runtime exhaust, gitignored, alongside the run log.

## Schema (emit these; do **NOT** emit `_source` — the framework adds it)

| Field | Required | Type / values | Notes |
|---|---|---|---|
| `timestamp` | yes | ISO 8601 | when the friction occurred |
| `agent` | yes | string | the actor, e.g. `workflow:<wf_id>/<role>` (matches rule 6 `agent`) |
| `skill` | yes | string | a framework skill name, validated against the **in-repo constant** below |
| `signal_class` | yes | `friction` \| `misuse` \| `gap` | see "When to emit" |
| `severity` | yes | `low` \| `med` \| `high` | the agent's honest read of impact |
| `evidence` | yes | string | concrete one-liner — what actually happened |
| `task_id` | yes | string | **shares the run-log row's `task_id`** for the same step |
| `invocation_ref` | no | `"<file>:L<n>"` | omit if unknown at emit time; never backfill |
| `expected` / `actual` / `suggested_fix` | no | string | optional hints for the triager |

## When to emit — RECONCILED triggers

Emit one non-blocking append at the friction moment, then keep going. Emitting is
**not a failure** and must never stop or gate the task.

- **(b) GAP** — a prescribed skill step is blocked by a missing dependency (a
  tool, file, or precondition the skill assumes but the apparatus lacks). *Clean —
  presupposes no status vocabulary.*
- **(c) MISUSE** — you substituted your own procedure because the skill mis-fit
  (recorded downstream as `diverged`; the original word is preserved in
  `evidence`). *Clean.*
- **(a) FRICTION — REFRAMED (hard inviolation in the original handoff).** The
  handoff defined friction as "a status that would fall outside the run-log enum
  (`started|passed|partial_pass|failed|aborted|halted|escalated|skipped`)." **That
  enum is the *framework's*, not a_bgt_rsi's.** This apparatus's run-log `status`
  is **open-vocabulary** (rule 6: the row shape is "a minimum, not a ceiling");
  `week1.run.jsonl` already carries 25+ distinct honest statuses (`completed`,
  `success`, `recovered`, `running`, `deferred`, …). **A non-framework-enum status
  is the EXPECTED, rule-6-blessed NORM and is NOT friction** — adopting the
  original trigger would (1) coerce status into a closed set (rule 4 violation) and
  (2) turn the apparatus's own normal logging into a friction firehose. Emit (a)
  **only** when the run-log skill's prescribed procedure genuinely *could not
  express* the step — i.e. you had to invent an ad-hoc status with no honest
  meaning because no value fit — framed as feedback **to the framework about its
  skill**, never as an apparatus self-constraint. **Resolution (D-056 + framework
  round-trip): trigger (a) is committed to this form (i)** — keep the friction class,
  fire ONLY on a genuine run-log-skill misfit, never on a non-framework-enum status.
  Form (ii) (per-status enum telemetry) is **explicitly REJECTED** (firehose + the
  rule-4 coercion this reframe refutes). **Phasing:** ship (b) GAP / (c) MISUSE first;
  add (a) under form (i) later — same schema, no schema re-review.

## The rule-7 swallow guard (no silent degraded path)

The emit is non-blocking and best-effort. To stay clear of rule 7 ("fallbacks are
explicit, logged… no silent degraded paths"):

- The `try/except` wraps **only** the `skill_signals` append.
- It **must never** wrap or mask the mandatory run-log write (rule 6). **The
  run-log row for the step is written FIRST and unconditionally**; `skill_signals`
  is supplementary.
- On emit failure, leave **one logged breadcrumb** — a run-log row (open-vocab
  status e.g. `skill_signal_emit_failed`) or stderr — so the degraded path is
  *logged, not silent*.
- The task never blocks either way.

## In-repo skill-name constant (no firewall crossing)

Validate `skill` against an **in-repo constant** sourced from CLAUDE.md rule 3's
`skill_subset` plus the framework-skill examples already named there:
`{run-log, validate, fallback, resume-state, gate-check, brain-recall}`. **Never
read a framework skill registry** to learn valid names. **Validation is
NON-DROPPING:** a `skill` not in the constant STILL emits the row (carrying
`skill_known: false` as an advisory) — never suppressed. This neutralizes the
staleness hazard: a framework skill rename can never cause apparatus-side data loss.
*Fallback only if the set drifts:* accept any non-empty `skill` string — framed
strictly as "we accept any non-empty string for OUR robustness," NOT "the framework
reconciles our names for us" (that would be an unverifiable framework dependency).

## D-048 no-live-artifacts wiring (hard precondition for implementation)

`emit_skill_signal` **must** resolve its target from a module-global
`SKILL_SIGNALS_PATH` at call time, and `tests/conftest.py`'s autouse
`_no_live_artifacts` fixture **must** be extended to `monkeypatch.setattr` that
global to `tmp_path`. Otherwise a full `pytest` run reopens exactly the
~210-live-row leak D-048 closed. **Acceptance: a full pytest run adds ZERO rows
to `run_state/skill_signals.jsonl`.**

## Apparatus-side acceptance (framework-side criteria excluded)

1. `run_state/skill_signals.jsonl` exists and is append-only (one valid JSON
   object per line, never edits a prior line).
2. Every row carries the required fields; `agent` in `workflow:<wf_id>/<role>`
   form; `signal_class` in the enum.
3. `task_id` corresponds to a step the agent actually ran this session and shares
   that step's run-log `task_id` (a *loose* join, not a strict foreign key —
   ~772 run-log rows carry `status=None` and many lack a clean `task_id`).
4. No row contains `_source`.
5. The emit path catches+swallows its own write errors (non-blocking) **and**
   never masks the mandatory run-log write; a breadcrumb is logged on failure.
6. No runtime brain access: no apparatus code under `orchestrator/`, `workers/`,
   `agent_wrapper/`, `scripts/` reads/writes/imports `memory/brain/`, imports
   framework projection code, or calls a framework script (D-014).
7. `skill` validated against the in-repo constant — no read of `agent_system/`.
8. `emit_skill_signal` is a single small one-append helper (rule 8) — no config,
   registry, schema-validation, or projection layer.
9. `skill_signals.jsonl` is covered by the D-048 `_no_live_artifacts` fixture.
10. The run-log row is written first and unconditionally; `skill_signals` is
    supplementary.
11. **Self-standing:** the build's validity depends on NOTHING in the framework's
    ingest/projection. Even if every framework assurance (ingest keys only on
    `signal_class`+`skill`; `task_id` optional; names match their registry) is false,
    the worst case is a row no one reads downstream — never a bad write or a rule
    violation. Framework assurances must never harden into apparatus dependencies.

> **Not apparatus acceptance:** the handoff's criterion "the framework ingest
> (`ingest_apparatus.py`) parses the live file" is **framework-side** and is
> dropped from the apparatus's acceptance set.

## Framework-side mechanics (context only — the apparatus touches none of this)

The framework, on its own pass, projects each row into an `apparatus_event`
narrative + a `source="runtime"` row in `memory/brain/drift_signals.jsonl` (the
`detected` lane), adds the `_source` field, and bubbles drift-class signals into
**DRAFT** proposals for human triage (never auto-enacted). `misuse` is recorded
as `diverged`. None of these paths are read, imported, or called by the apparatus.

## Implementation — (b)/(c) SHIPPED 2026-06-18 (human go)

`orchestrator/skill_signals.py` ships the single one-append helper
`emit_skill_signal(...)` (rule 8 — bounded; no framework) writing the schema above:
non-blocking swallow guard, NON-DROPPING skill-name validation, rule-4 enum rejection,
append-only, no `_source`. `tests/conftest.py` redirects `SKILL_SIGNALS_PATH` to
`tmp_path` (D-048) and `.gitignore` covers `run_state/skill_signals.jsonl`. The helper
accepts the full `signal_class` enum, so **(a) FRICTION under form (i) needs no schema
change** — only the call sites that decide *when* to emit (a) are deferred. Call sites
for (b) GAP / (c) MISUSE are added opportunistically as agents hit real friction; the
helper is now available to call. Tests: `tests/test_skill_signals.py`.
