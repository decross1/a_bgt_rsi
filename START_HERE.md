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

## 2. Where the project stands

For the current state across all workstreams (lit-pipe / UI / autonomy
/ applied), see [`LOOP_V0.md`](LOOP_V0.md) §"Current state (2026-06-14)".
For today's focus and the prior-session handoff, read the most recent
note in [`human/sessions/`](human/sessions/) (indexed in
[`human/sessions/INDEX.md`](human/sessions/INDEX.md)).

The operating model: one primary session at a time, plus at most one
concurrent UI session. The previous track-A/B/C/D / autonomy-tier
framework was retired on 2026-05-26 (see [`DECISIONS.md`](DECISIONS.md)
D-030); the retired docs live under [`archive/`](archive/).

---

## 3. Document map

Canonical doc map: see the "Where things live" table in
[`CLAUDE.md`](CLAUDE.md).

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
- Second model — excluded (D-033). The apparatus is single-model on
  Gemma 4 26B-A4B-NVFP4.
- The retired track/tier framework — references are in `archive/`,
  but the active model is one primary + one UI session.
