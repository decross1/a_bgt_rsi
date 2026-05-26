# Glossary

> Stable terminology used across the docs. One entry per term; each
> entry points to the deepest canonical reference. If a term appears
> elsewhere with a different meaning, **this file wins** and the other
> usage is a bug to fix.
>
> **Update 2026-05-26.** The Track A/B/C/D parallel-execution framework
> and the three-tier autonomy machinery (`autonomous` / `soft_gate` /
> `hard_gate`) were retired (see [`DECISIONS.md`](DECISIONS.md) D-030).
> Their entries below are preserved as historical reference because
> they appear in the run log, prior journal entries, and decision
> records. Links to the canonical defining documents now point under
> [`archive/`](archive/). Do not treat these as active terminology —
> the active operating model is documented in [`CLAUDE.md`](CLAUDE.md).

---

## Apparatus & program

**apparatus v0** — Week 1 (Days 31–37) deliverable: a self-hosted
research loop on a single NVIDIA DGX Spark that can run one
synthetic-tier experiment whose result requires human review before
publication. The apparatus — not the findings — is the research
contribution of Phase 1. See [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md)
§1, [`ARCHITECTURE.md`](ARCHITECTURE.md) §1.

**Phase 0** — Days 1–30, pre-Week-1 preflight. Not committed
day-by-day to the repo; summarized in
[`human/days_01_30_recap.md`](human/days_01_30_recap.md).

**Phase 1** — The 90-day alignment phase. Days 1–90 of the multi-year
program. Goal: apparatus v0 + first synthetic-tier experiments +
public preprint by Day 90. Detailed in
[`PHASE_1_ROADMAP.md`](PHASE_1_ROADMAP.md).

**Phase 2** — Months 4–9. Loop v1 with autoresearch across synthetic
and semi-synthetic tiers. Adds Meta-review synthesis, Critic /
red-team, and experiment-outcome feedback to the intelligence loop
([`ARCHITECTURE.md`](ARCHITECTURE.md) §6). First real findings;
workshop papers.

**Phase 3** — Months 10–18. Applied-tier deployment (Polymarket
live; gated on CFTC compliance work). Conference submission.

**Phase 4** — Months 19–36. Meta-scientific synthesis; main paper /
thesis-equivalent artifact.

**Phase 5** — Months 37–60. Extension or second program.

**synthetic tier** — Classical games with known equilibria (PD, public
goods, coordination). Used for apparatus shakedown and ground-truth
calibration of the auto-evaluator. See [`ARCHITECTURE.md`](ARCHITECTURE.md)
§3.1.

**semi-synthetic tier** — Mechanism-design experiments without
analytic equilibria (auctions, matching). Phase 2+.
[`ARCHITECTURE.md`](ARCHITECTURE.md) §3.2.

**applied tier** — Polymarket (design-only in Phase 1; live in
Phase 3+). [`ARCHITECTURE.md`](ARCHITECTURE.md) §3.3.

---

## Daily cadence

**Block 1** — Daily 08:30–10:00. **Human-only**: foundational
reading + problem sets. The agent prints the reading, sets a timer,
and HALTS. See [`CLAUDE.md`](CLAUDE.md) inviolate rule 1.

**Block 2** — Daily 10:30–12:30. Agent-executable: today's apparatus
build tasks. Block 2 is **not blocked** on Block 1 (decoupled per
[`agent/autonomy.md`](agent/autonomy.md) §7). The human reads in
parallel and catches up via the UI.

**Block 3** — Daily 13:30–14:30. Mixed: reading + journal post. The
agent stubs the journal; the human writes prose.

**Ambient listening** — Daily 14:30–15:30. Human-only.

**End of day** — Daily 15:30–16:00. Track A commits, attests, and
pre-stages tomorrow.

---

## Tracks (concurrent worktrees)

**Track A — Main** — Critical-path Block 2 for the current day. Owns
`run_state/`, `logs/`, `bench/`, `chroma_db/`, `agent_wrapper/`, and
end-of-day commits. The only writer for state files. See
[`agent/orchestration.md`](agent/orchestration.md).

**Track B — Tests & schemas** — Drafts next-day(s) test scaffolds
and JSON schemas. Owns `tests/`, `schema/`. Dispatchable.

**Track C — Pipeline & ops** — Drafts self-contained scripts:
ingest, scraper, cron, inspect_run, strategy stubs, quicklook. Owns
`ingest/`, `pipeline/`, `cron/`, `scripts/`, `tools/`, `infra/`, and
specific experiment files. Dispatchable.

**Track D — UI** — Observability dashboard + call-chain inspector.
Owns `ui/` and `ui_plan.md`. Dispatchable. See
[`ui_plan.md`](ui_plan.md).

**dispatched agent** — A Claude Code session launched by the
orchestrator (not the human) via `dispatch_coding_agent.py` (Week 2
deliverable). Runs in its own worktree under the same claim protocol
as named tracks. See
[`agent/collision_protocol.md`](agent/collision_protocol.md) §5.

---

## Gates & autonomy

**autonomy tier** — Every task in `plan.yaml` carries one of three
tier values that determine its halt behavior:

- **`autonomous`** — Proceed; log every step; never halt within the
  tier's domain.
- **`soft_gate`** — Proceed; record an attestation request; allow
  rollback within the SLA window. Halts only if the human marks the
  attestation `rejected`.
- **`hard_gate`** — Halt at entry; record in `human_gates_pending`;
  wait for explicit attestation.

See [`agent/autonomy.md`](agent/autonomy.md) §1.

**hard checkpoint** — A task that, on validation failure, writes
`day_aborted` to the run log and halts the day. The next day is
gated on the prior day's success. Plan.yaml field:
`hard_checkpoint: true`. Functionally a `hard_gate` with extra
fail-mode semantics. See [`CLAUDE.md`](CLAUDE.md) inviolate rule 6.

**`[GATE]`** — Human-readable shorthand in
[`human/daily_plan.md`](human/daily_plan.md) for points where the
agent halts for human action. Corresponds to `hard_gate` tasks in
`plan.yaml`.

**human gate** — A blocker in `state.human_gates_pending`. Cleared
only by explicit human attestation, persisted across restarts. The
Day 7 publication review gate is the most important; never
auto-publish.

**SLA** — Per-tier time budget after which a gate auto-clears
(soft) or escalates (hard). Soft: 4h auto-clear with
`no_objection`. Hard: 48h escalate, stay halted. Block 1: no SLA.
See [`agent/autonomy.md`](agent/autonomy.md) §2.

**alignment evidence** — The retrospective-attested check that
gates phase-boundary advances. Decision parity ≤ 1 disagreement/wk,
no metric drift > 5%, run-log integrity 100%, claim-protocol clean.
Two consecutive weekly attestations required to advance. See
[`agent/autonomy.md`](agent/autonomy.md) §4.

**phase boundary** — A point at which task tier classifications
shift (e.g., Week-2 unlock moves determinism check from
`hard_gate` to `soft_gate`). Triggered by alignment evidence, not by
calendar.

---

## Concurrent agent coordination

**zone** — A named bundle of file globs owned by a primary track.
Defined in [`agent/ownership.yaml`](agent/ownership.yaml). Every file
in the repo maps to exactly one zone.

**dispatchable zone** — A zone whose `dispatchable: true` flag allows
orchestrator-dispatched coding agents to claim it. Non-dispatchable
zones (`orchestrator`, `state-file`, `bench-and-logs`, `chroma-store`)
are reserved for Track A.

**claim** — An append-only entry in `run_state/claims.jsonl`
declaring an agent's intent to write to a set of paths, with an
expiry. See [`agent/collision_protocol.md`](agent/collision_protocol.md) §1.

**release** — An append-only entry in `run_state/claims.jsonl`
declaring a previous claim closed. Mandatory on commit.

---

## Slip & roadmap

**slip** — A day that bled into the next. Tracked in the state file
as `current_subday` (e.g., `31.2` = second slip on day 31). Triggered
by hard-gate failure, hard-gate SLA expiry, same-day rework, or
human declaration. See [`PHASE_1_ROADMAP.md`](PHASE_1_ROADMAP.md) §2.1.

**week-N unlock** — A phase-boundary advance unlocking a set of
tier shifts. Named for the week in which alignment evidence
typically clears, not when the calendar arrives.

---

## Infra & versions

**Spark** — NVIDIA DGX Spark (GB10) workstation. SM12x architecture;
no native FP4 compute. See [`ARCHITECTURE.md`](ARCHITECTURE.md) §2.

**MARLIN backend** — The Marlin weight-only FP4 path in vLLM. Required
startup log: `Using 'MARLIN' NvFp4 MoE backend`. If CUTLASS_FP4 appears
instead, the `--moe-backend marlin` flag did not pick up — STOP. See
[`CLAUDE.md`](CLAUDE.md) inviolate rule 2.

**MTP** — Multi-Token Prediction. Speculative decoding enabled in
vLLM v0.21.0 (D-022) — boosted single-stream decode from 32 → 69
tok/s on Gemma 4.

**NVFP4** — 4-bit floating-point weight quantization. Path:
`/mnt/models/gemma-4-26b-a4b-nvfp4`. NOT BF16.

**BGE-M3** — `BAAI/bge-m3` embedding model used for ChromaDB. NOT
the ChromaDB default `all-MiniLM-L6-v2`.

---

## Pointers for unfamiliar terms

If a term used in the docs is **not** in this glossary and is not
defined inline:

1. Check [`DECISIONS.md`](DECISIONS.md) — many specialized terms
   were introduced in a decision record.
2. Check [`ARCHITECTURE.md`](ARCHITECTURE.md) — technical terms.
3. If neither: open a PR to add the term to this file. Don't
   guess; ask.
