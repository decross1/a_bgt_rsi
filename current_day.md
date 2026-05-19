# Current day — day_2: Python wrapper + JSONL logging

_Active-day tracker. Authoritative plan: `plan.yaml`. State:
`run_state/week1.state.json`. Run log: `run_state/week1.run.jsonl`._

**Day goal:** Every Gemma 4 call goes through `wrapper.py`; every call
writes a schema-valid JSONL line; 50+ test calls captured; determinism
verified (T=0 and T=1/seed=42).

**Status as of 2026-05-19:** ✅ **Day 2 Block 2 complete; abort
resolved.** Tasks #1 (schema), #2 (wrapper), #3 (50-call sweep) all
pass. #3 first failed check #3 (aggregate 29.75 tok/s vs the 40 floor)
and aborted day_2; the abort was resolved by enabling MTP speculative
decoding (re-pin to `vllm/vllm-openai:v0.21.0` — D-022). The sweep
re-run scores aggregate **56.09 tok/s** with all 5 checks passing;
single-stream decode 32 → 69 tok/s. day_2 abort **LIFTED**
(human-attested, decross1, 2026-05-19).

**Day 2 COMPLETE (2026-05-19).** Block 3: reading (#4) + ambient (#6)
human-attested; journal (#5) stub at `journal/day2.md` — prose is the
human's to write + publish; end-of-day (#7) artifacts committed and
Day 3 pre-staged (`setup/day3_chroma.sh`). `current_day` advances to
`day_3` on the next session's resume — day_3 Block 1 is human-only (HALT).

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
| 3 | `day2_block2_50call_sweep` | **yes** (abort_day) | ✅ passed — re-run on MTP / v0.21.0; 5/5 checks pass, aggregate 56.09 tok/s. (First run 2026-05-18 failed #3 → aborted; resolved via D-022) |

**Resolution (2026-05-19) — MTP speculative decoding (D-022).**
Investigation (`scripts/analyze_day2_throughput.py`) established the
29.75 tok/s was a genuine weight-bandwidth-bound ceiling on the v0.20.0
stack, not a measurement artifact — so the fix had to be a real
throughput lever. Empirical image introspection found v0.20.0 ships no
Gemma 4 MTP support; v0.21.0 is the first vLLM release with PR #41745.
Re-pinned the image to `vllm/vllm-openai:v0.21.0` and enabled MTP
(`--speculative-config method=mtp`, official drafter). Result: decode
32.21 → 69.44 tok/s, sweep aggregate **56.09** (≥ 40), all 5 checks
pass, determinism intact. Launch script `setup/day2_vllm_serve_mtp.sh`;
bench `bench/mtp.csv`.

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
| 4 | `day2_block3_reading` | human-only, blocking | ✅ passed — human attestation (decross1) 2026-05-19 |
| 5 | `day2_block3_journal` | human-assisted | ✅ stub generated — `journal/day2.md`, data inserts pre-filled; prose + publication is the human's |
| 6 | `day2_ambient` | human-only | ✅ passed — human attestation (decross1) 2026-05-19 |
| 7 | `day2_end_of_day_artifacts` | agent-executable | ✅ passed — `logs/day2.jsonl` + journal + run_state committed; Day 3 pre-staged (`setup/day3_chroma.sh`) |

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
2. **MTP** — ENABLED 2026-05-19 (D-022); was deferred (D-019).
3. **vLLM image** re-pinned to `vllm/vllm-openai:v0.21.0` (D-022;
   was `:v0.20.0` / D-020); MTP speculative decoding enabled.

## Open items (human decision)

- ✅ Resolved 2026-05-19: the source plan `week1_days_31-37_plan.md` is
  not committed to the repo, so `plan.yaml` is now named the canonical
  plan across `START_HERE.md`, `CLAUDE.md`, `plan.yaml`, `README.md`,
  `HUMAN_PLAN.md`, and `AGENT_PLAN.md`. If the source doc is later
  added under `docs/sources/`, revisit which wins on conflict.
- ✅ Resolved 2026-05-19: the day_2 throughput abort — enabled MTP
  speculative decoding (re-pin to v0.21.0, D-022); the 50-call sweep
  re-run passes all 5 checks (aggregate 56.09 tok/s). Abort lifted,
  human-attested (decross1).

## Decisions log

- 2026-05-19: day_2 Block 3 + end-of-day. Reading (#4) and ambient (#6)
  human-attested complete (decross1). Journal (#5) stub generated at
  `journal/day2.md` — prose left to the human (human_assisted).
  End-of-day (#7): `logs/day2.jsonl` committed (verify_log_integrity=0),
  Day 3 pre-staged (`setup/day3_chroma.sh`; BGE-M3 weights confirmed at
  `/mnt/models/bge-m3`). **day_2 complete.**
- 2026-05-19: day_2 abort RESOLVED. Empirically found vLLM v0.20.0
  lacks Gemma 4 MTP (PR #41745); re-pinned to `vllm/vllm-openai:v0.21.0`
  and enabled MTP speculative decoding (D-022). 50-call sweep re-run:
  aggregate 56.09 tok/s, all 5 checks pass; decode 32 → 69 tok/s.
  day_2 abort lifted (human-attested, decross1).
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
