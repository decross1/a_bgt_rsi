# DATA_SHAPES — the contract between producers and the UI

Single reference for every data shape the **UI consumes**, plus a **changelog** of
shape changes. The primary session updates this whenever a producer's shape changes;
the **UI session reads it** (linked from `agent/prompts/ui_session.md`) instead of
reverse-engineering producers. This exists because a 2026-06-05 `ui/` reconcile was
made painful by undocumented Loop-v1 + experiment-summary shape drift.

**Rule (primary session):** any change to a shape below — a new `iteration_record`
field, a new endpoint payload, a new/changed experiment `summary.json` — gets a dated
**Changelog** entry here in the same commit that ships the producer change.

---

## 1. Loop schemas (canonical = the JSON Schema files; this doc only summarizes + dates)

| Shape | Canonical schema | Consumed by |
|---|---|---|
| `iteration_record` (one `memory/loop_memory.jsonl` row) | `schema/iteration_record.schema.json` | resolved-iterations list, iteration detail |
| `active_iteration` (`run_state/active_iteration.json`) | `schema/active_iteration.schema.json` | active-iteration panel |
| `loop_feedback` (one `memory/loop_feedback.jsonl` row) | `schema/loop_feedback.schema.json` | gate status / human-verdict surfacing |
| wrapper calls (`logs/calls.jsonl`) | `schema/calls.jsonl.schema.json` | call-chain inspector |
| events (`run_state/week1.run.jsonl`) | `schema/events.jsonl.schema.json` | activity / event stream |
| worker result contract | `schema/worker_contract.schema.json` | n/a (internal) |

**`iteration_record` — optional blocks the UI should render when present** (added Loop v1,
2026-06-05; all OPTIONAL, never in top-level `required`, so old rows stay valid):
- `meta_review`: `{ conditioning_bullets: string[] (3–5), rows_considered: int }`
- `redteam`: `{ verdict: "fatal_flaw"|"proceed", retries_used: int, critique?, confidence?, subagent_* }`
- `gate_status`: `"pending"|"valid"|"invalid"|"needs_revision"` (string)
- `experiment_outcome`: `{ experiment_id, metric, value: number|object, trials?, summary?, results_path? }`
- `cross_tier_comparison`: `{ claim, mechanism_a|rung_1, mechanism_b|rung_2, agreement: bool, diagnostic_note }`

`loop_feedback` row: `{ iteration_id, verdict: "valid"|"invalid"|"needs_revision", note, gated_at, gated_by }`.

## 2. Experiment result shapes (NO JSON Schema — this doc is the only reference)

Experiments are **heterogeneous** by design; the UI's experiments feature detects artifacts
per `results/` dir. Document each here.

- **exp001_repeated_pd** → `results/summary.json`:
  `{ n_opponents, rounds_per_opponent, per_opponent: [{ opponent, llm_coop_rate, opp_coop_rate, llm_mean_payoff, ... }] }`
- **exp003_vickrey_rediscovery** → `results/summary.md` (markdown, no json): verdict line `**Verdict: YES|NO**`, `Truthful fraction at eps=5.0: N/M (P%)`.
- **exp004_combinatorial_auction** → `results/summary.json`:
  `{ n_trials, per_mechanism: [{ mechanism, truthful_fraction, mean_efficiency, mean_revenue, parse_failure_rate, verdict }] }`
- **exp005_mechanism_aware** → `results/summary.json`:
  `{ n_trials, per_mechanism: [{ mechanism, truthful_fraction, mean_signed_residual, parse_failure_rate, verdict }] }`
  — note **`mean_signed_residual`** (shading signal), and NO `mean_efficiency`/`mean_revenue` (differs from exp004).
- **exp006_mechanism_design** → `results/summary.json`:
  `{ n_trials, designer_mean_efficiency, feasibility_rate, matches_vcg_rate, verdict }` — flat (no `per_mechanism`).

UI guidance: do not assume a uniform experiment-summary shape. Probe keys; render
`per_mechanism` as a table when present, else the flat metrics; treat `verdict ∈ {YES,NO,INVALID}`.

---

## Changelog

- **2026-06-05** — Loop v1 added optional `iteration_record` blocks `meta_review`, `redteam`,
  `gate_status` (+ `cross_tier_comparison`); new `loop_feedback.jsonl` + `schema/loop_feedback.schema.json`.
- **2026-06-05** — New experiment summaries: `exp004` (`per_mechanism` with `mean_efficiency`/`mean_revenue`),
  `exp005` (`per_mechanism` with `mean_signed_residual`), `exp006` (flat `designer_mean_efficiency`/`feasibility_rate`).
- **2026-06-05** — This doc created. Autoresearch/tier work appends here as shapes change.
