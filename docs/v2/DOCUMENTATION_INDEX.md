# Documentation index

This index separates current entry points, binding operating contracts,
preparation plans, research evidence, and retained history. A document's newest
file date does not make every statement in it a production fact.

## Status labels

- **Current entry point:** intended first read for people and sessions.
- **Active contract:** governs the deployed repository or runtime within its
  stated authority.
- **Preparation:** proposes or organizes work that is not yet the live contract.
- **Evidence/report:** records a bounded observation; conclusions apply only to
  its declared cohort and date.
- **Historical:** preserved context, no longer current execution direction.
- **Human-owned:** content or judgment that automation must not invent.

## Start here

| Document | Status | Use |
| --- | --- | --- |
| [`../../README.md`](../../README.md) | Current entry point | Project purpose, deployed snapshot, UI and repository map |
| [`../../START_HERE.md`](../../START_HERE.md) | Current entry point | Reading order, truth hierarchy, current session checklist |
| [`OPERATOR_GUIDE.md`](OPERATOR_GUIDE.md) | Current entry point | Health, UI interpretation, pause, recovery, weekly review and rollback |
| [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md) | Current entry point | Dated deployed architecture and explicitly labeled v2 target |

## Active contracts and decisions

| Document | Status | Authority |
| --- | --- | --- |
| checkout-local `AGENTS.md` | Active contract | Codex repository-maintenance authority and boundaries |
| [`../../CLAUDE.md`](../../CLAUDE.md) | Active contract | Claude runtime/scientific operating constraints and session rules |
| [`../../DECISIONS.md`](../../DECISIONS.md) | Active contract | Accepted rationale; a later decision supersedes the earlier decision it names |
| [`../../cron/serve-models.sh`](../../cron/serve-models.sh) | Active executable contract | Production model container configuration |
| [`../../systemd/nara-daemon.service`](../../systemd/nara-daemon.service) | Active executable contract | Installed Nara service shape; verify the installed user unit before acting |
| [`../../schema/`](../../schema/) | Active data contracts | Versioned schemas for covered public records |

An active contract governs only its stated subject. Git maintenance authority
does not create scientific, unrelated service-restart, scientific-publication, live-trading, or model
cutover authority.

## V2 foundation and research preparation

| Document | Status | Use |
| --- | --- | --- |
| [`../../LOOP_V2.md`](../../LOOP_V2.md) | Current plan | V2 foundation, research lifecycle, data rules, activation evidence and study gates |
| [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) | Preparation | Authorized engineering/evaluation envelope and Spark budget |
| [`research/PRODUCT_ARCHITECTURE_AUDIT.md`](research/PRODUCT_ARCHITECTURE_AUDIT.md) | Evidence/report | Internal product, service, data-model, and journey audit dated 2026-09-14 |
| [`BENCHMARK_FINDINGS.md`](BENCHMARK_FINDINGS.md) | Evidence/report | Four measured followthrough trials, failure categories, and limits |
| [`research/CROSS_REVIEW.md`](research/CROSS_REVIEW.md) | Evidence/report | Claude design critique and engineering corrections |
| [`research/DATA_MODEL_AUDIT.md`](research/DATA_MODEL_AUDIT.md) | Evidence/report | Campaign identity, activation, lineage classification, and legacy-isolation contract |
| [`research/ENGINEERING_AUDIT.md`](research/ENGINEERING_AUDIT.md) | Evidence/report | Active-path and dead-code audit with retirement evidence |
| [`research/EXTERNAL_CONTEXT.md`](research/EXTERNAL_CONTEXT.md) | Evidence/report | Bounded literature screen for the next game-theory campaign |
| [`RESEARCH_ARCHIVE.md`](RESEARCH_ARCHIVE.md) | Evidence/report | Verified v0/v1 archive manifest identity and retrieval procedure |
| [`V0_V1_LEARNINGS.md`](V0_V1_LEARNINGS.md) | Historical analysis | Retained lessons used to shape v2; not a live runtime contract |

`LOOP_V2.md` describes the foundation and later study gates separately. Canonical
activation/deployment receipts establish runtime adoption. A registered study,
CPU check, or reviewer memo does not establish model-game execution or a
validated scientific finding.

## Evaluation and implementation evidence

| Location | Status | Use |
| --- | --- | --- |
| [`../../experiments/`](../../experiments/) | Evidence/report | Preregistrations, manifests, fixtures, and retained outcomes |
| [`../../bench/`](../../bench/) | Active code + evidence | Evaluation runners, graders, and checked-in task definitions |
| [`../../run_state/`](../../run_state/) | Runtime evidence | Activation, budget, cycle, packet, and deployment receipts; many files are machine-local or append-only |
| [`../../memory/`](../../memory/) | Research evidence | Append-only iteration, idea, finding, near-miss, and feedback ledgers plus projections |
| [`../../logs/`](../../logs/) | Runtime evidence | Model and service events; treat bounded windows and source identity explicitly |
| [`../../ui/notes/`](../../ui/notes/) | Evidence/report | Dated implementation and delivery notes for the local observatory |

A report describes its named snapshot. Re-check current code, source hashes, and
live health before using it for an operational assertion.

The prepared first v2 campaign is bound by
[`../../experiments/PREREG_agentic_game_theory_v2_calibration_2026-09-14.md`](../../experiments/PREREG_agentic_game_theory_v2_calibration_2026-09-14.md)
and
[`../../experiments/agentic_game_theory_v2_calibration_2026-09-14.json`](../../experiments/agentic_game_theory_v2_calibration_2026-09-14.json).
Its 324 CPU simulation records represent 81 scripted-policy assignments under
four invariance conditions, not 324 independent behavior samples. The zero
model calls establish a harness baseline, not an LLM research result.
The narrowed first model-study design is described in
[`../../experiments/PREREG_agentic_game_theory_v2_best_response_controls_2026-09-14.md`](../../experiments/PREREG_agentic_game_theory_v2_best_response_controls_2026-09-14.md).
It remains a preparation artifact until its declared gates and evidence
requirements are satisfied.

## Historical program documents

| Document | Status | Retained value |
| --- | --- | --- |
| [`../../LOOP_V1.md`](../../LOOP_V1.md) | Historical build record | Evidence-ladder, memory, frontier, and micro-organization restructure |
| [`../../LOOP_V0.md`](../../LOOP_V0.md) | Historical build record | First literature-only loop slice and its implementation journey |
| [`../weekly_upgrade_loop_handoff.md`](../weekly_upgrade_loop_handoff.md) | Historical implementation input | Original weekly-loop proposal; current behavior comes from code, receipts and the v2 operator guide |
| [`../../PROJECT_CONTEXT.md`](../../PROJECT_CONTEXT.md) | Historical | Original program and hardware context |
| [`../../docs/diagrams/`](../diagrams/) | Historical conceptual specification | May 2026 v5 architecture/intelligence-loop snapshot |
| [`../../GLOSSARY.md`](../../GLOSSARY.md) | Historical/partial | Older terminology; verify terms against current code and front doors |
| [`../../archive/`](../../archive/) | Historical | Retired implementations and prior governance artifacts |

The front-door files before the v2 documentation rewrite are available at Git
reference `3c443e6`. The wider verified archive, including research and human
records, is described in [`RESEARCH_ARCHIVE.md`](RESEARCH_ARCHIVE.md). Archive
coverage proves byte preservation and hashes; it does not assert that every file
was scientifically reviewed.

## Human-owned material

| Location | Status | Boundary |
| --- | --- | --- |
| [`../../human/sessions/`](../../human/sessions/) | Human-owned collaboration record | Session context; dated notes can become stale |
| [`../../human/learning_track.md`](../../human/learning_track.md) | Human-owned | Reading and problem-set rail |
| [`../../human/retrospectives/`](../../human/retrospectives/) | Human-owned | Automation does not author the researcher's retrospective voice |
| [`../../journal/`](../../journal/) | Mixed evidence/human record | Verify authorship and source record before interpreting prose |
| `memory/loop_feedback.jsonl` | Human verdict source | Only an explicit recorded human verdict can earn L5 |

## Agent-facing material

| Document | Status | Use |
| --- | --- | --- |
| [`../../agent/README.md`](../../agent/README.md) | Current index | Agent launch-document map and authority boundary |
| [`../../agent/prompts/main.md`](../../agent/prompts/main.md) | Compatibility prompt | Session launch aid; root contracts/front doors supersede stale plan pointers |
| [`../../agent/prompts/ui_session.md`](../../agent/prompts/ui_session.md) | Compatibility prompt | Historical bounded UI-session profile; current assigned scope controls |

## Conflict resolution

For a concrete question, apply:

1. explicit current human instruction;
2. the operating contract that governs the actor/action;
3. the latest accepted decision for the design choice;
4. current executable code and validated immutable receipts;
5. live read-only service evidence;
6. explanatory and historical documentation.

Report a conflict instead of silently choosing the more convenient statement.
Missing data remains missing. A newer candidate report does not override a
validated deployment receipt, and a projection timestamp does not become the
recorded-at time of its sources.
