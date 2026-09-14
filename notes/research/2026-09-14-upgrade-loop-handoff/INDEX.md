# 2026-09-14 — upgrade-loop handoff: source reports

Deliverable: [`docs/weekly_upgrade_loop_handoff.md`](../../../docs/weekly_upgrade_loop_handoff.md).

| File | What |
|---|---|
| `draft_v2_input.md` | the 2026-09-13 draft that was reviewed (input) |
| `verified_repo_brief.md` | repo/live facts verified by the primary session before fan-out |
| `codex_adversary_report.md` + `codex_adversary_meta.json` | Codex (gpt-5.6-sol, effort max) via `invoke_frontier`, role `upgrade_loop_adversary`: kill list, repo corrections, counter-proposals, session scope |
| `claude_red_team_condensed.md` | Claude red team: 10 kills, cuts, missing items, ranked priorities, steelman |
| `repo_design_condensed.md` | file:line implementation design; in-container verification of vLLM 0.21.0 request fields and both chat templates |
| `benchmark_research_condensed.md` | benchmark landscape with URLs; aarch64/context constraints; weekly/monthly/quarterly recommendation |
| `policy_runtime_research_condensed.md` | Qwen/Gemma card values, reasoning_effort mechanics at the pin, SGLang/vLLM/TRT-LLM/Spark measurements, frontier ToS + pricing |

Spawn ledger ids: `upgrade-loop-20260914/*` in `run_state/spawn.jsonl`. All agents were read-only on the repo.
