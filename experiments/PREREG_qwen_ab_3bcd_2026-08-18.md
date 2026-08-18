# Pre-registration — Qwen A/B battery stages 3b/3c/3d (2026-08-18)

Status: **LOCKED at the commit carrying this line** (v2 — every required fix
from the adversarial critique `sprint-critic-3bcd` applied; v1 was
FIX-REQUIRED on four fatal flaws: unresolvable 3c fixtures, two
unfalsifiable gates, the missing backend re-register seam, and a void
commit reference to a gitignored file). Completes the D-0zz battery table
(3a done for both models 2026-08-17 at cap 12288). Owner authorization: the
4-hour sprint directive of 2026-08-18. Rules 4/7 bind.

## Common (both arms, identical driver)

- 3.6 arm = production serving co-resident; 3.8 arm =
  `qwen3.8-27b-nvfp4-mtp` served in the :8001 slot on the PRODUCTION image
  v0.21.0, canonical flags (window-C pattern: pause file, preflight,
  restore, MARLIN re-verify). The pause file is up for BOTH arms (the 3.6
  arm competes with live cycles otherwise).
- **Backend re-register seam (the 2026-08-15 false-FAIL killer):** the
  driver takes the served-model label as its arm argument, re-registers
  backend `vllm-qwen` with that label BEFORE any site call (stage3a
  pattern, `bench/critic_eval/stage3a_driver.py:33-41`), and records
  `GET :8001/v1/models` id in the run artifact. A model-name 400 is a
  driver bug, never a 3.8 finding.
- **Calls-log isolation:** driver sets
  `LOOP_V0_CALLS_LOG=bench/qwen_ab_3bcd/runs/<arm>.calls.jsonl` BEFORE
  importing `orchestrator.finding_promotion` / `finding_session` /
  `restate_skeptic` (CALLS_LOG_PATH binds at import time in all three).
  Liveness metrics are computed from that per-arm log; **empty-at-cap** :=
  a row with empty completion AND `usage.output_tokens == max_tokens`.
- Identical driver, fixtures, and caps across arms; single sample per
  fixture (the sites expose no seed control; temperatures are hardcoded at
  the sites — stated, not hidden). `NARA_ATTACK_MAX_TOKENS` is irrelevant
  to these sites (only stage-3a's attack() reads it) and stays unset.
- Precedence note: THIS prereg's criteria supersede the checklist's D-0zz
  table row wording for 3b ("quorum kept; no unadjudicated flips") — vote
  agreement is reported data here, not a gate; the memo is filled against
  the criteria below.

## 3b — finding_promotion multi-vote battery

- Fixtures: the 3 most recent rows in `memory/surfaced_findings.jsonl`
  with complete promotion-vote blocks **as of the build-time snapshot**
  (the file is gitignored; the builder records
  `sha256(memory/surfaced_findings.jsonl)` plus the finding_ids and
  source_iteration_ids in its build report — they resolve today to
  `sf-iter-2026-07-15-001`, `sf-iter-2026-07-30-001`,
  `sf-iter-2026-08-04-001`, all with loop_memory rows present; historical
  votes ride along as the comparison column).
- Seam (pinned): per candidate the driver calls
  `finding_promotion._adversarial_vote(row, _claim_text(row), n_skeptics=3,
  backend="vllm-qwen", parent_request_id=<bench id>)` — **NOT**
  `promote_findings()`, which writes surfaced_findings.jsonl,
  run_state/active_run.json, and the idea ledger. `_adversarial_vote`
  writes nothing but the calls log. Production budgets as configured:
  max_turns=4, max_tokens_per_turn=6144, max_tokens_total=16000,
  max_wall_seconds=800.0.
- LOCKED criteria per arm: (i) liveness = parseable-verdict fraction over
  skeptic slots run (tally `qwen_failures==0` per candidate); (ii) zero
  empty-at-cap rows (per the Common definition); (iii) reported
  non-gating: votes vs the historical record, calls/vote vs the D-070 12.5
  baseline, wall/vote.
- **A/B gate:** evaluated over candidates completed in BOTH arms:
  3.8 liveness ≥ 3.6 liveness AND 3.8 empty-at-cap == 0.
- Time cap (rule 7): **60 min per arm** (worst case one candidate = 3 ×
  800 s wall); on cap, completed candidates are the arm's result, partial
  stated.

## 3c — two-voice attacker spot-run

- Fixtures: the SAME 3 pinned surfaced findings as 3b
  (`start_two_voice_session` resolves finding_ids natively — the
  adoption-eval file lacks claim text for 2 of 3 cases and is not used).
- Run (pinned entry points, state redirected):
  `start_two_voice_session(finding_id, surfaced_path=<real file>,
  loop_memory_path=<real file>,
  sessions_root=bench/qwen_ab_3bcd/runs/sessions/)` then ONE
  `two_voice_turn(finding_id, session_id, <PINNED verbatim user_msg — the
  driver embeds one fixed attack-opening prompt used for all fixtures and
  both arms>, addressee="attacker", sessions_root=<same>)`. Sessions never
  touch `memory/finding_sessions/`. Known transient: two_voice_turn writes
  run_state/active_run.json and clears it in `finally` — acceptable under
  the pause file, stated here.
- LOCKED criteria per arm: (i) attacker reply has non-empty visible
  content after `strip_channel_markup` on 3/3; (ii) zero replies equal to
  the `[attacker unavailable: ...]` fail-open string; (iii) empty-at-cap
  == 0 in the arm's calls log for `caller_tag=finding_session_attacker`
  (max_tokens=4096 — the known Qwen think-block starvation mode).
- **A/B gate:** 3.8 non-empty count ≥ 3.6 non-empty count. Voice
  distinctness is demoted to a reported human spot-check (not a gate — it
  could not fail as previously written). Time cap: 15 min per arm.

## 3d — restate hook

- Fixtures (**4/4**, verbatim ids): `redisc_on_01_tft_reciprocity`,
  `redisc_on_03_quantal_response`, `canary_on_01_ultimatum_plain`,
  `canary_on_02_hawkdove_ess` — hypothesis fields from
  `experiments/lit_falsification_battery/cases.jsonl` (the checklist §3d
  residual-2 set; v1's "2/2" contradicted its own fixture reference).
- Run (pinned): `orchestrator.restate_skeptic.restate_attack(
  hypothesis_text=<case hypothesis>, iteration_id=None,
  backend="vllm-qwen", novelty_top_neighbor_id=None)` — no production
  writes (calls log only); `.venv-chroma` python, `env -u MOCK_LLM`.
- LOCKED criteria per arm (operationalized so they CAN fail — the return
  value fail-opens everything to in-enum `inconclusive`, so it cannot
  gate): (i) canonicalize leg parses iff returned `canonical_statement` is
  non-null, 4/4; (ii) judge leg parses iff the arm's calls-log row for
  `caller_tag=restate_judge` contains a JSON object with `restate_verdict`
  in the enum, 4/4 — measured from the calls log, never from the
  fail-open return. Reported non-gating: agreement with historical
  verdicts; output-token utilization vs the RESTATE_MAX_TOKENS=3072 cap
  (first 3.8 data on the D-070 residual).
- **A/B gate:** 3.8 parse count ≥ 3.6 parse count per leg. Time cap:
  30 min per arm (worst case 8 legs × ~190 s at the 3072 cap ≈ 25 min).

## Overall

Stage results fill the D-0zz table (this prereg's wording supersedes the
table's 3b row). The battery A/B verdict is LIVENESS-shaped by design —
quality was adjudicated by 3a + the matched-FP8 comparison. A 3.8 arm ≥
3.6 on every locked gate, with 3a already ALL-PASS, completes the evidence
for the cutover memo; any 3.8 < 3.6 on a locked gate is stated and the
cutover recommendation withheld. Drivers: disjoint new files under
`bench/qwen_ab_3bcd/` + tests, MOCK-refusing CLIs, artifacts to
`bench/qwen_ab_3bcd/runs/` with full provenance (served-model id from
/v1/models, image, flags, fixture ids, per-arm calls-log path).
