# START HERE — a_bgt_rsi

> **Read this first.** This is the single orientation document for the
> repository. It tells you what the project is, where it stands right
> now, which document answers which question, and where to go next.

---

## 1. What this is

`a_bgt_rsi` is **Phase 1** of a multi-year research program. Phase 1
is the **90-day alignment phase** (Days 1–90). The repo currently
covers Days 31–37 (Week 1) in executable detail, with the rest of
Phase 1 mapped at varying granularity in
[`PHASE_1_ROADMAP.md`](PHASE_1_ROADMAP.md).

The goal of **Week 1** is **"apparatus v0"**: a self-hosted research
loop on a single NVIDIA DGX Spark that, by the end of Day 7, can run
**one synthetic-tier experiment** (repeated Prisoner's Dilemma against
fixed strategies) whose result requires human review before
publication. The apparatus — not the findings — is the research
contribution.

Field of application: game theory, behavioral game theory, learning in
games. Full background in [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md);
the architecture in [`ARCHITECTURE.md`](ARCHITECTURE.md).

**Day ladder.** Day 1 hardware + vLLM serving · Day 2 wrapper + JSONL
logging · Day 3 ChromaDB + textbook ingest · Day 4 first tool call ·
Day 5 arXiv pipeline · Day 6 orchestrator + first worker · Day 7
first PD experiment + retrospective. Beyond Day 7, see
[`PHASE_1_ROADMAP.md`](PHASE_1_ROADMAP.md).

---

## 2. Where the project stands

_As of 2026-05-23. The live tracker is [`current_day.md`](current_day.md);
the authoritative state is `run_state/week1.state.json`._

- **Days 1–6 — complete.** Hardware + vLLM serving (Day 1), Python
  wrapper + JSONL logging (Day 2), ChromaDB + textbook ingest (Day 3),
  Day 3.5 schema amendments, first tool call (Day 4), arXiv pipeline
  → 138 papers in `papers_recent` (Day 5; D-027 — switched
  S2 → arXiv), OpenClaw orchestrator on multiprocessing fallback +
  inspect_run + cron enabled (Day 6).
- **Day 7 — imminent.** Repeated PD experiment + retrospective.
- **Documentation restructure — in progress (this commit).** Split by
  audience (`human/` and `agent/` directories); autonomy framework
  introduced; 30-day roadmap added; Block 1 decoupled from Block 2
  in `plan.yaml` (prospective from Day 7+).

---

## 3. Document map — which file answers which question

### Top-level orientation & operating

| If you need… | Read |
| --- | --- |
| Orientation, current state (this file) | [`START_HERE.md`](START_HERE.md) |
| Operating contract for agent sessions | [`CLAUDE.md`](CLAUDE.md) |
| The canonical task plan — tasks, validations, checkpoints | `plan.yaml` |
| What's being worked on right now | [`current_day.md`](current_day.md) |
| The 30/60/90-day arc | [`PHASE_1_ROADMAP.md`](PHASE_1_ROADMAP.md) |
| Terminology reference | [`GLOSSARY.md`](GLOSSARY.md) |

### Reference & architecture

| If you need… | Read |
| --- | --- |
| Project background and rationale | [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md) |
| How the apparatus is built, architecturally | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| Why a decision was made the way it was | [`DECISIONS.md`](DECISIONS.md) (D-001 … D-027) |
| Telemetry dashboard + observability plan | [`ui_plan.md`](ui_plan.md) |

### Audience-segregated

| If you are… | Read |
| --- | --- |
| The human researcher running your daily blocks | [`human/daily_plan.md`](human/daily_plan.md) |
| Reading Phase 1 chapters at your own pace | [`human/learning_track.md`](human/learning_track.md) |
| Looking up the Phase 1 reading list | [`human/reading_list.md`](human/reading_list.md) |
| Drafting / committing a weekly attestation | [`human/retrospectives/`](human/retrospectives/) |
| An agent (Claude Code) starting a session | [`CLAUDE.md`](CLAUDE.md) + [`agent/autonomy.md`](agent/autonomy.md) |
| Looking up your tier semantics and SLAs | [`agent/autonomy.md`](agent/autonomy.md) |
| Looking up which paths you may write to | [`agent/ownership.yaml`](agent/ownership.yaml) |
| Following the claim/lock protocol | [`agent/collision_protocol.md`](agent/collision_protocol.md) |
| Launching a track's worktree | [`agent/orchestration.md`](agent/orchestration.md) + [`agent/prompts/`](agent/prompts/) |

### State and history

| If you need… | Read |
| --- | --- |
| Resume state / run log | `run_state/week1.state.json`, `run_state/week1.run.jsonl` |
| Soft-gate attestations | `run_state/attestations.jsonl` |
| Hard-gate escalations | `run_state/escalations.jsonl` |
| Active claim/lock entries | `run_state/claims.jsonl` |
| Pre-Week-1 history | [`human/days_01_30_recap.md`](human/days_01_30_recap.md) |

**Authority.** `plan.yaml` is the **canonical** plan: where any summary
document disagrees with it on task content, `plan.yaml` wins.
[`CLAUDE.md`](CLAUDE.md) is canonical for inviolate rules.
[`agent/autonomy.md`](agent/autonomy.md) is canonical for tier
semantics. [`agent/ownership.yaml`](agent/ownership.yaml) is canonical
for file-zone mapping. [`DECISIONS.md`](DECISIONS.md) records why —
the most recent decision wins over an older one it supersedes.

---

## 4. Inviolate rules (the short version)

The full contract is [`CLAUDE.md`](CLAUDE.md); the autonomy framework
is [`agent/autonomy.md`](agent/autonomy.md); the canonical version
pins are [`ARCHITECTURE.md`](ARCHITECTURE.md) §2. The rules that
never bend:

1. **No Block 1.** Block 1 tasks are `hard_gate` / no-SLA / human-only.
   Print reading + problem set, HALT.
2. **Version pins are verbatim.** Canonical in `ARCHITECTURE.md` §2.
3. **Human gates are blocking.** Day 7 publication review never
   auto-clears.
4. **Validations are never silently coerced.**
5. **State file is authoritative on resume.**
6. **Hard-gate failures abort the day.**
7. **Fallbacks are explicit, logged, and time-capped.**
8. **Logging is mandatory.**
9. **Code-generation is bounded** (~100 lines for the wrapper).
10. **The retrospective is the human's.**

These all live in full in [`CLAUDE.md`](CLAUDE.md).

---

## 5. How to start a session

### Track A (Main)

```bash
env -u MOCK_LLM claude --worktree dayN-main
```

Reading order in the session: `CLAUDE.md` → `agent/autonomy.md` →
`agent/ownership.yaml` → `plan.yaml` (today's section) →
`agent/orchestration.md` → `run_state/week1.state.json`. Resume at
first incomplete task. Honor `human_gates_pending`. Log every
executable task.

The full Track A prompt is in
[`agent/prompts/track_a.md`](agent/prompts/track_a.md).

### Tracks B, C, D (side worktrees)

Each track has its own scoped prompt and narrower file boundaries:

- [`agent/prompts/track_b.md`](agent/prompts/track_b.md) — Tests & schemas
- [`agent/prompts/track_c.md`](agent/prompts/track_c.md) — Pipeline & ops
- [`agent/prompts/track_d.md`](agent/prompts/track_d.md) — UI

### Dispatched coding agents (Week 2+)

Orchestrator-launched via `agent_wrapper/dispatch_coding_agent.py`
(Day-39 deliverable). Template at
[`agent/prompts/dispatched_task.md`](agent/prompts/dispatched_task.md).

---

## 6. Out of scope for Week 1

Polymarket API calls (design-only) · autoresearch overnight runs
(Week 2+) · a second model (Qwen 3.6, Week 2–3) · concurrency in
workers (sequential only on Day 6) · a fully autonomous loop · fine-
tuning · Week 2 planning **execution** (a separate task — do not
begin it after the Day 7 retrospective even if asked).

Week 2 planning **content** is detailed in
[`PHASE_1_ROADMAP.md`](PHASE_1_ROADMAP.md) §5 — read it, don't
execute on it until Day 38.
