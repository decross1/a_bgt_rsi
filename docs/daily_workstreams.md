# Daily workstreams — the research day Nara runs

The designed daily cadence of the apparatus, layer by layer: who triggers each
layer, the exact command, what it writes, what the UI shows, and which
guardrail bounds it. **Read the status tags honestly** — as of 2026-06-10 the
spine of this day (the scheduled coordinator cycles) is shipped **DARK**:
built, gated, NOT in crontab. The continuous-orchestrator guardrail
(CLAUDE.md out-of-scope) stands until the human ratifies **D-049**; until
then the coordinator runs only when a human triggers it, and the supervised
soak driver is the one sanctioned multi-cycle exception.

Status tags: **LIVE** (in crontab or routinely runnable today) ·
**LIVE, per-command** (works today, human-triggered, single-shot) ·
**DARK** (shipped, fails closed, awaiting D-049) ·
**LANDING 2026-06-10** (this session's WS-1/WS-3 work — verify in the tree
before relying on it).

## 0. The control surface (read first)

| Lever | Who sets it | Effect |
|---|---|---|
| `run_state/d049_ratified` | **HUMAN ONLY** — creating it IS ratifying D-049 | arms `cron/run-coordinator.sh` (gate 2) |
| `run_state/pause_coordinator` | anyone may `touch`; only the human removes | halts the cron runway AND the soak driver before the next cycle; **nothing bypasses it** |
| `--i-am-supervising` (soak only) | the human at the terminal | substitutes for the ratification sentinel ONLY — a watching human is the pre-D-049 exception |
| `run_state/.coordinator-cron.lock` | `flock`, automatic | at most one cron cycle in flight |
| `preflight_mem_guard 25` | automatic (sourced from `experiments/exp008_qat_eval/preflight_mem.sh`) | refuses launch unless MemAvailable ≥ 25 GiB + the guard's 30 GiB OS margin (GB10 unified pool; the Qwen skeptic may load) |

## 1. 03:00 — arXiv ingest  [LIVE]

- **Trigger:** cron, installed: `0 3 * * * …/cron/daily-arxiv.sh`.
- **Command:** `cron/daily-arxiv.sh` — scrapes cs.MA / cs.GT / econ.TH
  (3-day self-healing window), embeds with BGE-M3, appends to ChromaDB.
- **Artifacts:** `chroma_db/` collection `papers_recent` (deduped on
  arxiv_id); log at `~/cron-daily-arxiv.log`.
- **UI:** not rendered directly; surfaces downstream as the morning topic
  suggestion (`orchestrator/morning_topic.py` prefers the newest paper) and
  as novelty/lit evidence inside iteration cards.
- **Guardrails:** `env -u MOCK_LLM` baked in (rule 10); read-only arXiv API.

## 2. Morning — coordinator cycle  [DARK until D-049; LIVE, per-command]

One `assess → plan → validate → dispatch` cycle (`orchestrator/coordinator.py`).
The binary stays single-shot; cron supplies the cadence — that is exactly the
line D-049 must ratify before the schedule goes live.

- **Trigger (designed):** cron `0 9,15 * * *` via `cron/run-coordinator.sh` —
  **NOT INSTALLED**; the script fails closed without the sentinel.
- **Trigger (today):** a human runs one cycle, which the guardrail permits:
  - dry-run (plan only, no dispatch, default):
    `env -u MOCK_LLM .venv-chroma/bin/python -m orchestrator.coordinator --once`
  - real cycle (what cron will run):
    `env -u MOCK_LLM NARA_SKEPTIC=1 .venv-chroma/bin/python -m orchestrator.coordinator --once --execute --budget 6`
  - flags verified against the argparse: `--once`, `--execute`,
    `--budget N` (default 6), `--backend`, `--model`.
- **Assess** reads instrumentation only (never raises): in-flight run, recent
  findings, open threads, gaps, surfaced-pending findings, experiment census,
  morning-topic suggestions. **LANDING 2026-06-10 (WS-1):** `finding_followups`
  topics (spawn/refine outcomes from finding sessions) and the
  ungated-iteration count join the snapshot.
- **Plan** is one low-temperature LLM call constrained to the fixed menu in
  `orchestrator/coordinator_actions.py` — off-menu/malformed/over-budget plans
  are rejected and replanned (≤ 2 replans), never executed. Menu today:
  `run_loop_iteration` (cost 3) · `promote_findings` (2) · `bubble_up` (1) ·
  `noop` (0). **LANDING 2026-06-10 (WS-1):** `run_experiment` (thesis →
  experiment via the autoresearch driver) and `forecast_markets` (exp007
  paper sweep — design-only, no trading action exists on the menu).
- **Artifacts:** `run_state/coordinator_cycles.jsonl` (full cycle report),
  `memory/coordinator_bubbles.jsonl` (executed bubble_ups),
  `run_state/active_runs/<run_id>.json` (D-047 registry, heartbeat),
  `logs/calls.jsonl` + `run_state/week1.run.jsonl` rows.
- **UI:** Now board (active runs + heartbeat), coordinator cycle health
  signals, Gemma + Qwen health panels (skeptic backend is `vllm-qwen`).
- **Guardrails:** the four launch gates in §0; dry-run by default; constrained
  action space; budget cap; `--once` only (no loop/watch mode exists).

## 3. Midday — the human block  [LIVE]

The human-in-the-loop half of the day. Write-backs go through the D-046
blessed CLIs (`docs/human_writeback_contract.md`); the UI attestation forms
that wrap them landed 2026-06-10 (`run_state/attestations.jsonl`).

- **Gate verdicts** (Step-8 review of finished iterations):
  `python -m orchestrator.gate_cli --iteration-id <id> --verdict valid|invalid|needs_revision [--note "…"] [--gated-by human]`
  → appends `memory/loop_feedback.jsonl`. UI: attestation form on the
  iteration card; gated/ungated status on the card.
- **Finding interrogation** (REPL over a promoted finding):
  `env -u MOCK_LLM python -m orchestrator.finding_session` then
  `start <finding_id>`, chat, close with `/validate` `/reject`
  `/spawn <topic>` `/refine <claim>` `/quit`. One-shot disposition:
  `python -m orchestrator.finding_session --set-status <finding_id> <status> --note "…"`.
  → updates `memory/surfaced_findings.jsonl` + session transcript.
- **Defer-to-dev-session queue** (triage, also a CLAUDE.md startup step):
  `python -m orchestrator.todo_cli list-deferred` · `ack --bubble-run-id <id>` ·
  `defer --kind <k> --ref-id <id> --note "…"` · `close --ref-id <id>`
  → `memory/coordinator_acks.jsonl`, `memory/dev_session_queue.jsonl`.
- **Guardrails:** verdict/status enums are frozen (invalid input rejected,
  nothing written); the human's prose is the human's (rule 9).

## 4. Afternoon — routing survivors + the Polymarket paper workstream

- **Thesis → experiment routing  [LIVE, per-command].** When a surviving
  thesis routes to a built experiment, one command drives run → analyze →
  bridge into a LOOP_V0 iteration (see `docs/AUTORESEARCH.md`):
  `env -u MOCK_LLM python -m orchestrator.autoresearch --tier synthetic --experiment exp003_vickrey_rediscovery --live`
  (tiers: `synthetic` | `semi_synthetic`; `applied` is rejected by design).
  One invocation = one experiment → one bridged iteration, then exit.
  Once WS-1 lands, the coordinator can request the same path via the
  `run_experiment` menu action — same driver, same single-shot semantics.
- **Polymarket paper workstream  [sweep LIVE, per-command; edge analysis +
  memo LANDING 2026-06-10 (WS-3)].** Design-only per the CFTC guardrail:
  paper forecasts, read-only public Gamma API, **no orders, no wallets, no
  authenticated endpoints, no live trading** — the disclaimer heads every
  exp007 file.
  1. Sweep ~20 resolved markets:
     `env -u MOCK_LLM ./.venv-chroma/bin/python experiments/exp007_polymarket/run.py --n 20 --live-data`
     → `experiments/exp007_polymarket/results/forecasts.jsonl`.
  2. Score offline (Brier / BSS vs the market-implied prior):
     `./.venv-chroma/bin/python experiments/exp007_polymarket/analyze.py`.
  3. Edge analysis + strategy **memo** (paper document, not a strategy that
     executes): exp007 `edge_analysis.py` + memo writer — WS-3, this session.
- **UI:** bridged iterations render as cards (`experiment_outcome` block,
  steps[] timeline); exp007 runs appear in the registry while live.

## 5. Evening — supervised soak  [SUPERVISED EXCEPTION]

Extra cycles while a human watches — the only sanctioned way to run multiple
coordinator cycles before D-049:

```
tools/coordinator_soak.sh --cycles 3 --interval-s 600 --budget 6 --i-am-supervising
```

- Same gates as cron per cycle (pause file + mem guard re-checked every
  cycle); `--i-am-supervising` bypasses ONLY the ratification sentinel.
  Without the flag and without the sentinel it refuses (exit 1).
- Foreground only; INT/TERM stops cleanly after the current cycle's
  bookkeeping. One JSON line per cycle → `logs/coordinator-soak.log`.
- **UI:** each cycle shows up exactly like a morning cycle (registry +
  cycle log); the soak adds no new data shape.

## 6. Weekly

- **ChromaDB snapshot  [LIVE]:** cron, installed:
  `30 4 * * 0 …/cron/snapshot-chroma.sh` → `~/backups/a_bgt_rsi-chroma/`
  (keeps 12; off-host destination still undecided).
- **Lit-falsification battery re-run  [LIVE, per-command]:** after any
  lit-pipe change, and weekly while the D-045 residuals stay open
  (restatement routing, skeptic off-domain attack — see DECISIONS.md D-045):
  `env -u MOCK_LLM .venv-chroma/bin/python -m experiments.lit_falsification_battery.battery`
  → report under `experiments/lit_falsification_battery/runs/`. Validations
  report pass/fail per case; near-misses are never coerced (rule 4).

## What ratification day changes (and what it does not)

D-049, once the human ratifies it, changes exactly two things: the crontab
gains the `run-coordinator.sh` line, and the human creates
`run_state/d049_ratified`. Nothing else moves — the gates, budget, action
menu, pause file, and logging are already in force DARK. Everything in §§1,
3, 4, 6 is live today without D-049; §2-on-cron and unsupervised §5 are not,
and refuse on their own.
