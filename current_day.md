# Current day — day_2: Python wrapper + JSONL logging

_Active-day tracker. Authoritative plan: `plan.yaml`. State:
`run_state/week1.state.json`. Run log: `run_state/week1.run.jsonl`._

**Day goal:** Every Gemma 4 call goes through `wrapper.py`; every call
writes a schema-valid JSONL line; 50+ test calls captured; determinism
verified (T=0 and T=1/seed=42).

**Status as of 2026-05-18:** ⛔ **Day 2 ABORTED.** Block 2 tasks #1
(schema) and #2 (wrapper) passed; #3 (50-call sweep) failed validation
check #3 — aggregate throughput 29.75 tok/s vs the 40 floor (4 of 5
checks passed; determinism + logging are clean). HUMAN DECISION
(decross1): the abort is **not** lifted — tok/s ≥ 40 is treated as
truly blocking. **Day 3 is gated** until throughput is tuned to ≥ 40
and the sweep re-run passes all 5 checks. Block 3 (#4–#7) does not run.
Next work: investigate/tune vLLM throughput, then re-run
`day2_block2_50call_sweep`.

**Failure mode / recovery:** vLLM stops responding (thermal? OOM?) →
cache-clear, restart container, check thermal log; if recurring, cap
KV cache to ~30 GB.

## Wall-clock windows

| Block | Window |
|-------|--------|
| Block 1 — Foundations | 08:30–10:00 |
| Block 2 — Build | 10:30–12:30 |
| Block 3 — Read/Write | 13:30–14:30 |
| Ambient | 14:30–15:30 |
| End of day | 15:30–16:00 |

## Block 1 — Foundations (human-only, NO AI)

> HALT. Reading: O&R *A Course in Game Theory* Ch. 6 §6.4–6.5 + start
> Ch. 7 (subgame perfect equilibrium, one-deviation principle).
> Problem set: O&R 6.7, 6.10, 7.1 — pen and paper, by hand. Derive the
> one-deviation principle by hand.
> Claude does not assist, summarize, or solve. Mark complete only after
> the time window elapses (human attestation).

| Task | Type | Status |
|------|------|--------|
| `day2_block1_reading` | human-only, blocking | ✅ passed — human attestation (decross1) 2026-05-18 |
| `day2_block1_problemset` | human-only | ✅ passed — human attestation (decross1) 2026-05-18 |

## Block 2 — Build (agent-executable)

| # | Task | Hard checkpoint | Status |
|---|------|-----------------|--------|
| 1 | `day2_block2_jsonl_schema` | **yes** | ✅ passed — `schema/calls.jsonl.schema.json` + `tests/example_call.jsonl`; all 3 checks pass |
| 2 | `day2_block2_wrapper_implementation` | no | ✅ passed — `agent_wrapper/wrapper.py` (~100 LOC); 3 import checks pass via `.venv/bin/python` |
| 3 | `day2_block2_50call_sweep` | **yes** (abort_day) | ❌ FAILED — 4/5 checks pass; #3 tok/s 29.75 < 40. **day_2 ABORTED** |

**Investigation (`scripts/analyze_day2_throughput.py`):** the 29.75
tok/s is genuine, not a short-completion artifact. Linear fit
`latency_ms = 59.7 + 31.15·output_tokens` → 60 ms fixed overhead,
decode-only rate **32.10 tok/s**; longest completions also plateau at
~31.7. Structural GB10/FP4 ceiling, matching Day-1's 32.03. The 40
floor (and the [80,130] band) assume MTP speculative decoding, which
is deferred to Week 2+ (D-019).

**⏸️ PENDING HUMAN DECISION (next session):** resolve the day_2 abort —
(a) accept ~32 tok/s as the structural baseline + lift the abort +
flag `plan.yaml`'s MTP-dependent 40 floor / [80,130] band for
correction, or (b) pull MTP forward from Week 2 to actually reach ≥40.

Notes:
- Task #1 is `command: null` — schema authoring is the human's; the
  agent only validates the output (valid JSON Schema, 14 required
  fields, jq parses an example line).
- Task #2 is `agent_assisted` / `command: null` — agent prepares
  scaffolding; the human (or a sub-agent with file-write authority)
  writes the implementation. Resist abstraction — ~100-line code
  budget. `agent_wrapper/wrapper.py` already exists from Day-1
  pre-staging; reconcile against the locked schema before extending.
- Task #3 `on_failure: abort_day` — a determinism divergence halts the
  day; Day 3 does not start until it is fixed.

## Block 3 / end of day

| # | Task | Type | Status |
|---|------|------|--------|
| 4 | `day2_block3_reading` | human-only, blocking | ⏳ pending — Melanie Mitchell on Sakana + one Twitter thread |
| 5 | `day2_block3_journal` | human-assisted | ⏳ pending — public post 200–300 words; agent stubs with data inserts |
| 6 | `day2_ambient` | human-only | ⏳ pending — EconTalk: Al Roth on market design |
| 7 | `day2_end_of_day_artifacts` | agent-executable | ⏳ pending — commit artifacts; pre-stage Day 3 |

## Validation gates (Day 2)

- **#1 schema:** valid JSON Schema (Draft 2020-12); `required` array
  has all 14 fields; `jq` parses `tests/example_call.jsonl`.
- **#3 sweep:** `wc -l logs/day2.jsonl` = 50; `verify_log_integrity`
  returns 0; aggregate decode tok/s ≥ 40; 3 identical completions at
  T=0; 3 identical completions at T=1/seed=42.
- **#7 end-of-day:** files committed + clean tree; `verify_log_integrity`
  = 0; `journal/index.md` updated; Day 3 pre-staged
  (`setup/day3_chroma.sh` queued, BGE-M3 weights at `/mnt/models/bge-m3`).

## Carried in from Day 1

1. **tok/s 32 vs plan floor 40** — accepted as the Day-1 baseline
   (cause assessed structural: GB10 SM12x has no native FP4). Day 2's
   #3 sweep re-checks an *aggregate* tok/s ≥ 40 floor — watch this; it
   may surface the same shortfall.
2. **MTP** — deferred to Week 2+ (D-019).
3. **vLLM image** re-pinned to `vllm/vllm-openai:v0.20.0` (D-020).

## Open items (human decision)

- The authoritative source plan `week1_days_31-37_plan.md` referenced
  by `CLAUDE.md` / `plan.yaml` is **not in the repo**. Commit it, or
  amend the contract to name `plan.yaml` canonical.
- Uncommitted post-Day-1 working-tree edits: `DECISIONS.md`,
  `notes/day1-bench-debug.md`, `scripts/bench_tokens_per_sec.py` —
  decide whether to commit before Day 2 artifacts land.

## Decisions log

- 2026-05-19: day_2 Block 2 — #1 schema + #2 wrapper passed; #3
  50-call sweep failed validation check #3 (tok/s 29.75 < 40), other
  4 checks passed. `day_2` aborted (hard checkpoint). Human chose to
  treat #3 as blocking; throughput investigation
  (`scripts/analyze_day2_throughput.py`) confirmed ~32 tok/s is a
  structural GB10/FP4 ceiling. Resolution deferred to next session.
- 2026-05-18: created project venv `.venv` (gitignored) and installed
  `requirements.txt` (openai 2.37.0, jsonschema 4.26.0, pydantic 2.13.4,
  requests 2.34.2). The plan's bare `python3` commands lack these deps;
  per human decision, Day-2 Python commands run as `.venv/bin/python`.
- 2026-05-18: `current_day` advanced `day_1` → `day_2` on resume
  (`resume-state`). All 12 Day-1 tasks complete (#10 skipped via the
  NemoClaw → plain-Docker fallback branch). State transition logged to
  `week1.run.jsonl`. Resume point: `day2_block1_reading` — HALTED at
  Block 1 per Inviolate Rule 1 (No Block 1).
