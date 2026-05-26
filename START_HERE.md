# START HERE — a_bgt_rsi

> **Read this first.** This is the single orientation document for the
> repository. It tells you what the project is, where it stands, which
> document answers which question, and where to go next.

---

## 1. What this is

`a_bgt_rsi` is a self-hosted research apparatus on a single NVIDIA
DGX Spark. The goal: amplify one human researcher's work in game
theory, behavioral game theory, and learning in games. The apparatus —
not any particular finding — is the research contribution under test.

The canonical specification is in the system diagrams under
[`docs/diagrams/`](docs/diagrams/) (`architecture_v5.svg`,
`intelligence_loop_v5.svg`). Read them. The prose elaboration is
[`ARCHITECTURE.md`](ARCHITECTURE.md); the intellectual program is
[`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md).

Field of application: game theory, behavioral game theory, learning
in games. The system is a workflow amplifier, not a frontier-lab
automation system, not a recursive self-improver, not a theorem
prover.

---

## 2. Where the project stands (2026-05-26)

### What's built and exercised

- `agent_wrapper/` — vLLM OpenAI-API wrapper with schema validation
  (329 LOC, exercised across 8 days of work).
- `orchestrator/` — sequential multiprocess orchestrator with causal
  chain logging (292 LOC).
- `workers/` — two workers: `summarize_paper`, `play_pd_match`.
- `pipeline/` — arXiv ingest + BGE-M3 embed → Chroma (138 papers
  ingested).
- `ingest/` — textbook chunking + ingest.
- `chroma_db/` — live vector store (~31 MB; foundational + live layers).
- `tests/` — 4,786 LOC test suite.
- `ui/` — React/FastAPI observability stack (Day-8 verification gate
  cleared). Being extended for the loop-iteration view; see
  [`agent/prompts/ui_session.md`](agent/prompts/ui_session.md).
- One real experiment ran end-to-end: repeated Prisoner's Dilemma vs.
  TfT / Grim / All-C / All-D / Mirror-LLM, 4× replication. Logged in
  `experiments/exp001_repeated_pd/`.

### What's not yet built

The eight-step intelligence loop in
[`docs/diagrams/intelligence_loop_v5.svg`](docs/diagrams/intelligence_loop_v5.svg)
has not yet run end-to-end as a chained iteration. Steps with no code
today:

- Step 2 (hypothesis generation)
- Step 4 (robustness battery)
- Step 5 (cross-tier replication)
- Step 6 (novelty evaluation) — the diagrams call this out as a
  sub-research-problem in its own right
- Layer 3 of the knowledge base (loop memory of past assessments)

### What's active right now

The active build plan is [`LOOP_V0.md`](LOOP_V0.md): the
literature-only slice of the intelligence loop. The current session
focus is the most recent note in [`human/sessions/`](human/sessions/).

### Operating model

One primary session at a time, plus at most one concurrent UI session.
The previous track-A/B/C/D / autonomy-tier framework was retired on
2026-05-26 (see [`DECISIONS.md`](DECISIONS.md) D-030); the retired
docs live under [`archive/`](archive/).

---

## 3. Document map

### Top-level orientation & operating

| If you need… | Read |
| --- | --- |
| Orientation (this file) | [`START_HERE.md`](START_HERE.md) |
| Operating contract for sessions | [`CLAUDE.md`](CLAUDE.md) |
| Active build plan | [`LOOP_V0.md`](LOOP_V0.md) |
| Today's session focus / handoff | most recent in [`human/sessions/`](human/sessions/) |
| Terminology | [`GLOSSARY.md`](GLOSSARY.md) |

### Reference & architecture

| If you need… | Read |
| --- | --- |
| Project background, why this exists | [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md) |
| Apparatus architecture, version pins | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| System diagrams (canonical spec) | [`docs/diagrams/`](docs/diagrams/) |
| Why a decision was made | [`DECISIONS.md`](DECISIONS.md) |
| Telemetry / observability plan | [`ui_plan.md`](ui_plan.md) |

### Sessions

| If you are… | Read |
| --- | --- |
| Starting the primary session | [`CLAUDE.md`](CLAUDE.md) → [`LOOP_V0.md`](LOOP_V0.md) → today's session note |
| Starting the UI session | [`agent/prompts/ui_session.md`](agent/prompts/ui_session.md) |

### State and history

| If you need… | Read |
| --- | --- |
| Resume state, completed-task history | `run_state/week1.state.json` |
| Run log (append-only history) | `run_state/week1.run.jsonl` |
| Past daily journal entries | [`journal/`](journal/) |
| Retired track/tier scaffolding (read-only) | [`archive/`](archive/) |
| Pre-Week-1 history | [`human/days_01_30_recap.md`](human/days_01_30_recap.md) |

**Authority.** [`docs/diagrams/`](docs/diagrams/) is canonical for the
system spec — when prose disagrees with the diagrams, the diagrams
win. [`CLAUDE.md`](CLAUDE.md) is canonical for operating rules.
[`DECISIONS.md`](DECISIONS.md) records why — the most recent decision
wins over an older one it supersedes. [`ARCHITECTURE.md`](ARCHITECTURE.md)
is canonical for version pins.

---

## 4. Inviolate rules (the short version)

The full text is in [`CLAUDE.md`](CLAUDE.md). The rules that never bend:

1. **No Block 1 help.** Block 1 readings are human-only.
2. **Version pins are verbatim** (see `ARCHITECTURE.md` §2).
3. **Human gates are blocking.**
4. **Validations are never silently coerced.**
5. **State file is authoritative on resume.**
6. **Logging is mandatory.**
7. **Fallbacks are explicit, logged, and time-capped.**
8. **Code-generation is bounded** (resist abstraction; ~100-line budget
   for wrapper-style components).
9. **The retrospective and research-journal prose are the human's.**
10. **`MOCK_LLM` discipline** — strip the env var for real runs.

---

## 5. How to start a session

### Primary session

```bash
env -u MOCK_LLM claude
```

Then read in order: [`CLAUDE.md`](CLAUDE.md) → [`LOOP_V0.md`](LOOP_V0.md) →
the most recent `human/sessions/YYYY-MM-DD.md`. If no session note
exists for today, the first job is to agree on one with the human and
write it.

### UI session (concurrent, optional)

```bash
env -u MOCK_LLM claude --worktree ui-session
```

Then read [`agent/prompts/ui_session.md`](agent/prompts/ui_session.md).
Writes only to `ui/` + `ui_plan.md`. Prints `UI READY TO MERGE` when
done.

---

## 6. Out of scope

- Polymarket live trading (design-only until CFTC compliance work).
- Continuous-running orchestrator (LOOP_V0 is single-shot, human-triggered).
- Fine-tuning / training runs.
- Second model (Qwen 3.6) until LOOP_V0 is exercised.
- The retired track/tier framework — references are in `archive/`,
  but the active model is one primary + one UI session.
