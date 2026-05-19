# UI plan v2 — experiment results browser (sketch)

> Planning artifact, not a build spec. Drafted by Track D during the
> r4 improvement pass to resolve `ui_plan.md` §9's second open question
> (whether to expose experiment-level views in v1). Decision: **defer
> to v2**; v1 stays a live dashboard + single-chain inspector. This
> file sketches what v2 would cover and, more importantly, the data
> contracts v2 needs that do not exist yet.
>
> Placed under `ui/` (not the repo root) to stay inside Track D's
> write boundary. One page; expand into a full plan when v2 starts.

## 1. Why it is not in v1

v1 answers two questions: *is the Spark healthy right now?* and *what
happened in this one call chain?* Both are answerable from telemetry
and the call log without understanding experiment semantics — the
inspector renders call records generically and never interprets a
result. An experiment results browser is a different product: it
**interprets** outcomes (cooperation rates, payoffs, who played whom).
That crosses the line `ui_plan.md` §2 and operating-contract rule 8
draw — the UI shows data, it does not derive findings. v2 is where
that line is deliberately, and visibly, redrawn.

## 2. What v2 would cover

A third route, `/experiments` and `/experiments/:expId`, alongside the
existing `/` and `/chain/:taskId`.

- **Experiment list.** One row per `exp###` run: experiment id, task
  type, round count, wall-clock span, completion status. Sourced from
  the `exp*.jsonl` glob already indexed by the backend.
- **Per-experiment cooperation rate.** For a repeated-game experiment,
  the fraction of rounds the apparatus's agent cooperated, shown as a
  single number plus a per-round strip (cooperate/defect over time).
  Trend matters more than the scalar — a rate that collapses at round
  N is the interesting signal.
- **Per-round behavior.** A round-by-round table: round index, agent
  action, opponent action, payoff, and a link to that round's call
  chain (`/chain/:taskId`) so a surprising round drops straight into
  the v1 inspector. This is the join that makes v2 worth building —
  results browser and call inspector become one workflow.
- **Opponent breakdown.** Cooperation rate and mean payoff bucketed by
  opponent identity / strategy, so "cooperates with tit-for-tat,
  defects against always-defect" is visible at a glance.
- **Cross-experiment compare.** A small table of cooperation rate and
  mean payoff across `exp001…exp00N` — the aggregate the researcher
  actually wants once more than one experiment exists.

No charts beyond the existing sparkline/strip vocabulary; no emoji; the
same text-and-numbers tone as v1 (`ui_plan.md` operating-contract
rule 10).

## 3. Data contracts v2 needs — and the gap

This is the real output of this sketch. v2 is blocked not on UI work
but on a contract that does not exist yet.

- **An experiment-result schema.** Today `exp*.jsonl` records are
  pinned only on the *structural* call-log fields (`request_id`,
  `parent_request_id`, `task_id`, `caller_tag`, timestamps — §4.2/§4.4).
  Nothing pins the *semantic* fields a results browser needs:
  experiment id, round index, agent action, opponent identity,
  opponent action, payoff. The chain inspector deliberately never
  reads these. v2 cannot be built until the apparatus commits an
  experiment-result schema (a `schema/experiment.schema.json` or an
  extension of the day-7 `exp###` contract). **Action for Track A
  (design-only, not Track D's to write):** decide whether experiment
  outcomes live as extra fields on the call-log lines, as a separate
  results file per experiment, or both. Filed in
  `notes/track-d-observations.md`.
- **Round linkage.** The per-round table's link to `/chain/:taskId`
  needs each round to map to a `task_id`. The fixture generator
  already models `exp001_round_07` as a task id of the form
  `exp{NNN}_round_{RR}` — if the apparatus follows that convention the
  linkage is free; if not, v2 needs an explicit round→task_id field.
- **Opponent identity.** Opponent strategy/identity must be a recorded
  field. If the apparatus only logs the prompt text, v2 would have to
  parse prompts to recover the opponent — fragile; better recorded.

## 4. Rough size

Backend: one new endpoint family (`/api/experiments`,
`/api/experiments/{id}`) reusing the existing `LogStore` glob + index;
no new tailing machinery. Frontend: one route, one list component, one
per-round table, reuse of `Sparkline`/strip and the existing
inspector link. Estimate ~2 Block 2's once the experiment-result
schema lands — comparable to a single v1 build step. The cost is
entirely in the contract, not the code.
