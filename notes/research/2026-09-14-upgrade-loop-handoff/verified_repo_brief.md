# Verified repo brief — a_bgt_rsi as of 2026-09-14 (main @ 1cb2303)

Everything below was checked against files / live services on 2026-09-14 by the primary Claude session. Cite by path.

## Production serving (cron/serve-models.sh, live docker ps, /v1/models)
- Image `vllm/vllm-openai:v0.21.0` (CLAUDE.md inviolate rule 2 — verbatim pin; changing it requires a DECISIONS.md entry + explicit owner ratification, it is NOT something a coding session may edit).
- vllm-gemma4 :8000 — gemma-4-26b-a4b NVFP4, `--moe-backend marlin`, MTP assistant `num_speculative_tokens=4`, `--max-model-len 32768`, `--max-num-batched-tokens 8192`, `--gpu-memory-utilization 0.30`, prefix caching, `--tool-call-parser gemma4`. Up 3 weeks.
- vllm-qwen :8001 — qwen3.8-27b-nvfp4-mtp (Inferact modelopt NVFP4 PTQ), `--language-model-only`, `--max-model-len 16384`, `--max-num-seqs 2`, `--kv-cache-dtype fp8`, `--gpu-memory-utilization 0.30`, `--reasoning-parser qwen3`, speculative `qwen3_5_mtp` n=3, `--tool-call-parser qwen3_coder`. Up 3 weeks.
- Host: 121 GiB unified; `free -g` now: used 81, available 40. D-057 rule: MemAvailable must stay >= 30 GiB with both resident; never thin the margin.
- docs/qwen38_role_setups.md: Qwen3.8 thinking ON by default at reasoning_effort=xhigh (levels xhigh/medium/low, per-request or template-settable); measured 3.8 decode ~16.5 tok/s vs Gemma+MTP 69.4 tok/s; empty-at-cap Gemma 0.13%, Qwen3.8 11.1% (n=45); STANDING TRAP: MTP + reasoning parser + guided/structured output drops `</think>` under the pin (vLLM #34650, fixed post-pin) — never adopt guided_json on the Qwen backend while pinned. Pin-amendment triggers listed there (§3).

## Wrapper sampling policy (agent_wrapper/wrapper.py)
- `call_sync` (line 178), `call_async` (217), `call_with_tools` (311) all default `temperature=0.0, top_p=1.0, seed=None`. Params logged per call to calls.jsonl via a 14-field schema validator (`_record`/`_emit`, `_VALIDATOR`).
- BUT the claim "temperature 0 everywhere" is FALSE at the call-site level. 17 call sites override ad hoc: workers/hypothesize.py:205 temp 0.7; workers/claim_extract.py:153 0.1; novelty_skeptic/novelty_classify/meta_review/refine_cycle/restate_skeptic/finding_promotion/subagent 0.2; orchestrator/self_improve.py 0.3; finding_session.py 0.3; lab_channel.py 0.4; coordinator.py:753 0.1. So the real state is: ad-hoc low temperatures, no named profiles, no reasoning_effort control for the LOCAL Qwen (only agent_wrapper/frontier_cli.py knows reasoning_effort, for Codex), and no per-role rationale recorded.
- tools/qwen_builder.sh (the D-066 packet builder) still defaults `QWEN_MODEL=qwen3.6-27b-nvfp4-mtp` (served name is qwen3.8-27b-nvfp4-mtp) and `QWEN_TEMPERATURE=0.2`, `QWEN_MAX_TOKENS=6144`, prompt cap sized to the 16K window. DRIFT.

## Existing frontier + self-improvement machinery (reuse, do not duplicate)
- agent_wrapper/frontier_cli.py `invoke_frontier(vendor, prompt, *, timeout_s, role, ledger_path=None)` — vendors "claude" (`claude -p --output-format json`, Max subscription; ANTHROPIC_API_KEY stripped from env) and "codex" (`codex exec --skip-git-repo-check --sandbox read-only -m gpt-5.6-sol -c model_reasoning_effort=max --json`, repo-owned CODEX_HOME=run_state/codex_home). Every call appends to run_state/frontier_calls.jsonl (2,338 rows). MOCK_LLM -> stub. Installed CLIs: claude 2.1.265, codex 0.154.0.
- D-061: frontier CLIs are FALSIFIERS ONLY — veto/annotate, never generate research content, never write loop_memory or the brain (annotate-only firewall). Frontier ToS gate G1 is CLEARED (run_state/frontier_tos_ratified exists).
- orchestrator/frontier_agenda.py + cron/weekly-frontier-agenda.sh: a weekly frontier pass ALREADY INSTALLED in crontab (`30 5 * * 0`), gate ladder = flock + ToS sentinel + pause file (run_state/pause_frontier), role `agenda_synthesist`, both vendors, appends proposals to memory/frontier_agenda.jsonl (43 rows), fail-open per vendor. This is the natural chassis for a weekly upgrade/performance loop: add a role + a ledger, clone the gate ladder.
- docs/self_improvement_loop.md (D-066): telemetry -> Gemma proposal -> frontier debate (<=3 rounds) -> red-first task packet (acceptance test written and RUN, emitted only if RED) -> orchestrator/packet_dispatcher.py dispatches to tools/qwen_builder.sh in an isolated worktree -> dispatcher re-runs the test + tools/premerge_check.sh -> primary session merges. Off by default (NARA_SELF_IMPROVE). Packet SDLC in docs/packet_sdlc.md, run_state/packets.jsonl.
- Other crons live: hourly cron/run-coordinator.sh, 5-min watchdog, daily arxiv 03:00, weekly chroma snapshot. cron/run-critic-eval.sh exists but is NOT installed.

## Existing eval assets (bench/)
- bench/critic_cal/ (build_manifest.py, manifest.jsonl, driver.py, audit_overrides.py, runs/) — the calibration-battery pattern (manifest + driver + runs dir).
- bench/critic_eval/qwen_ab.py + run_day9.py + stage3a_driver.py; bench/fp8_ab; bench/judge_cal; bench/redteam_cal; bench/readjudication; bench/debate_eval/adoption_20260816.json; bench/mtp.csv; bench/day3_needle.json; scripts/bench_tokens_per_sec.py.
- tests/fixtures/critic_eval_inputs.jsonl (20 Day-39 critic fixtures).
- Model roles are FIXED (G5): Gemma = sole generator/PI; Qwen = standing independent skeptic; frontier = falsifiers only. D-072: Qwen 3.8 qualification = matched A/B on digest-pinned eval runtime. D-076: R1a battery elected gemma-revised.

## Rules a coding session must honor (CLAUDE.md)
- Rule 6 logging: every executable task appends to run_state/week1.run.jsonl `{timestamp, task_id, agent, status, observable_actual, observable_expected, duration_ms, skill_used?}`.
- Rule 10: MOCK_LLM is set in the interactive shell; real runs need `env -u MOCK_LLM`; tests use `MOCK_LLM=1`.
- Rule 8: bounded codegen, ~100-line wrapper budget, no speculative abstraction.
- Rule 4: validations never coerced. Rule 7: fallbacks explicit, logged, time-capped. Human gates blocking.
- AGENTS.md: direct Codex repository-management sessions have standing Git/PR authority within assigned scope; scientific/runtime/production gates still apply.
- Spine files (orchestrator/nara.py, tool_registry.py, schema/iteration_record.schema.json) are single-integrator only.
