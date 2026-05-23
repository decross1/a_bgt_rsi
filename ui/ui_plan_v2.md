# UI plan v2 — experiment results browser + live orchestrator graph (sketch)

> Planning artifact, not a build spec. Drafted by Track D during the
> r4 improvement pass to resolve `ui_plan.md` §9's second open question
> (whether to expose experiment-level views in v1). Decision: **defer
> to v2**; v1 stays a live dashboard + single-chain inspector. This
> file sketches what v2 would cover and, more importantly, the data
> contracts v2 needs that do not exist yet.
>
> The 2026-05-23 Day-7-EOD UI audit (`ui_plan.md` r10) added §5 below
> for the **live orchestrator graph view** — a request that surfaced
> only after the user ran a real multi-task workload against v1 and
> wanted a single visualization of orchestrator + spawned workers
> rather than the dashboard's tabular orchestrator queue.
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

---

## 5. Live orchestrator + workers graph (added by ui_plan.md r10)

Requested by the user during the 2026-05-23 Day-7-EOD UI audit, after
running the real PD experiment through Day-6's orchestrator. v1's
orchestrator queue is a vertical list of `(task_id, task_type, status)`
rows — fine for "what's running right now?" but it does not convey the
**parent/child topology** of an in-flight run (orchestrator dispatches
a task → spawns a worker → worker fires N wrapper calls → each call may
fan out to tools). For a multi-task experiment with 100s of rounds, a
node-link diagram is the right reading affordance.

### 5.1 What the view shows

Two view levels in one route, `/graph` (or `/experiment/:expId`):

- **Macro level** — orchestrator at center, one node per task it has
  dispatched, status-coloured (running amber, passed green, failed
  red, rejected red). Edges are parent_request_id chains. The graph
  updates live as new tasks fire (reusing the existing `/api/live`
  WebSocket). Hover a node: task_id + task_type + duration + worker_pid.
  Click a node: zoom to micro level.
- **Micro level** — picked node becomes the new root. Its children
  expand: wrapper calls → tool calls (when present) → model
  responses. Equivalent to today's chain inspector at `/chain/:taskId`,
  but rendered as a force-directed graph inside the same view rather
  than a separate route. Back-button returns to macro level.

Zoom is data zoom, not pixel zoom — the node set changes when the
user descends, the layout re-flows. Camera zoom (mouse-wheel pan/zoom)
is also on, for navigating large graphs at the macro level.

### 5.2 Data contracts

Three sources, all already present in v1:

1. `orchestrator.jsonl` — every dispatch / worker_invocation /
   orchestrator_receipt / orchestrator_reject line (Day-6+ schema).
2. The call-log glob (`logs/day*.jsonl` + `logs/exp*.jsonl`) — wrapper
   calls and tool calls.
3. `/api/live` WebSocket — for live updates without a full graph
   re-fetch.

A new endpoint `GET /api/graph?experiment_id=<id>&depth=<N>` returns
`{nodes: [...], edges: [...]}` derived from `LogStore` for an
experiment (or just `?since=<iso>` for a rolling-window view). Node
shape: `{id, kind, task_id, task_type, status, latency_ms,
worker_pid, timestamp, parent_id}`. Edge shape: `{source, target,
kind: "dispatch"|"call"|"tool"}`. Reuses the existing chain walker;
no new tailing machinery.

### 5.3 Library choice

Three real options:

- **`react-flow`** — React-native, supports custom nodes, has zoom +
  pan + minimap built in. Familiar React state model. The right
  default for our stack.
- **`cytoscape.js`** (with `react-cytoscapejs`) — heavier, more
  graph-theoretic, supports very large graphs (1000s of nodes) better
  than react-flow.
- **`vis-network`** — small footprint, but rough React integration.

For v2 v1 (the first ship), `react-flow` is the right choice — our
graphs are bounded (one experiment ≈ 5 opponents × 1 task each ×
100 wrapper calls ≈ ~500 nodes if we render every wrapper call at
once). The micro level shows ~10–50 nodes; the macro level shows
~5–50. Both well within react-flow's comfort zone.

Revisit `cytoscape.js` if a later experiment needs to render thousands
of nodes simultaneously — that crossover hasn't arrived.

### 5.4 What this is NOT

- Not a replacement for the tabular orchestrator queue on the
  dashboard — that view is the "what's running, briefly" affordance;
  the graph is the "what's the shape" affordance. Both ship.
- Not a 3D visualization, animated dial, or anything decorative
  (operating-contract rule 10: text-and-numbers tone applies to the
  graph too — node colour against documented thresholds; no splash).
- Not editable. The graph is a read-only projection of the JSONL
  state (rule 8: UI shows problems, does not remediate them).

### 5.5 Sequencing

Land **after** v1 is in production (UI v1 milestone clears — see
`ui_plan.md` §11). The v2 results browser (§2-4 above) and this graph
view can ship independently — they share zero code beyond the
existing `LogStore`. If the experiment-result schema lands first,
build §2-4 first; if the audience needs the visual first, build §5
first. Recommendation in the current state: §5 first, because the
experiment-result schema is still un-pinned (Track A's call, see
`notes/track-d-observations.md`), while the graph view's data
contracts already exist.
