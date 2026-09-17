# Daily research operation

The daily lab has two independent inputs: the 03:00 UTC literature job and the
event-driven/hourly research coordinator. A healthy service does not prove
either produces research. Check `/api/research_ops_status` and the Research
work status card for source ingestion, available topics, actual dispatch, and
the last linked iteration separately.

## September 17 recovery

The previous utility-mechanism campaign had three exact topics. All were used
on September 15. It was a finite research cohort, but hourly automation kept
trying to plan after it was exhausted. There was no active replenishment path.
Separately, the daily arXiv search feed repeatedly returned rate-limit and
network errors. Schedules and model servers were running throughout.

The frozen campaigns and their studies remain unchanged. The new
`v2-daily-agentic-game-theory-20260917` campaign admits ongoing **exploratory**
literature work. It does not authorize empirical study execution, change an
evidence rung, or establish a trading result.

## Sources and queue

1. `cron/daily-arxiv.sh` fetches a three-day overlapping window from arXiv's
   official OAI-PMH category sets. The legacy search API is a complete-result
   fallback. Partial results from different interfaces are never combined.
2. Serial requests respect the three-second minimum interval, including
   retries. Started/terminal receipts bind the actual interface, provenance
   sidecar, fetched input hash, and successful embedding. A failed fetch does
   not relabel a previous cache as a fresh success.
3. The coordinator reads only a successfully embedded, verified source run
   no more than seven days old. It prefers the source's game-theory category
   when cross-listed. A `cs.MA` label alone is insufficient: its title/abstract
   must also identify a strategic or mechanism question. Nara's independent
   domain gate still evaluates the generated hypothesis.
4. Before dispatch, the coordinator registers an exact topic and its paper,
   ingestion, and campaign hashes. Registration receipts are append-only
   files under `run_state/research_topic_registry/<campaign_id>/`. Their digest
   is carried into the iteration's campaign link.
5. At most three topics may be registered per UTC day, with at most one
   unconsumed topic. The same arXiv base identifier or topic text cannot be
   recycled by a later fetch. The existing action budgets remain in force.
6. The daemon watches fresh-ingestion and campaign activation pointers. Its
   pure work check can discover a new source; only the gated coordinator pass
   registers and dispatches it under the shared execution lock.

The registry is bounded to 512 receipts. Review or succeed the campaign before
that limit; do not delete receipts belonging to recorded iterations. A damaged
registry refuses classification instead of becoming an apparently empty queue.

## Honest idle and evidence debt

- `queue_starved`: no unused, verified source is available.
- `daily_topic_limit`: today's three registrations have been used.
- `topic_source_unavailable`: the source or consumption ledger cannot be read
  and verified.
- `topic_registration_refused`: registration validation failed, including a
  changed ingestion source between discovery and registration.
- `activity_budget_limited`: the remaining daily action share cannot fund an
  iteration; the registered topic remains pending for the next allowance.

These outcomes write coordinator receipts without calling the planner. They
are not completed research. A valid topic ID selected by the planner resolves
only to its exact available registered text; consumed or invented IDs remain
invalid. For this routine daily intake, the coordinator creates the exact
registered request directly and records `plan_origin=registered_daily_queue`.
There are no model planner attempts; the ordinary validator, action budget,
Nara hypothesis/domain checks, and independent criticism still run. Nara
rechecks the campaign and registration link before model work. Frozen studies
and other existing planning paths retain their current planning behavior.

The operations view separately exposes L1/L2 candidates that owe a synthetic
test or replication. Those require a separately frozen study and analysis plan.
Daily exploratory output is not evidence that those experiments happened.

## Verification and recovery

Inspect the latest terminal ingestion receipt and its last-success pointer.
Then inspect a completed `memory/loop_memory.jsonl` row, its topic registration,
retrieval/criticism fields, and journal entry. A coordinator plan or an active
model call alone does not prove completion.

The normal entrypoints remain:

```bash
cron/daily-arxiv.sh
cron/run-coordinator.sh
systemctl --user status nara-daemon.service
.venv-chroma/bin/python -m orchestrator.research_ops_status --plan
```

Do not remove the pause file or bypass ratification, memory, daily-budget, or
research gates to make a check green. Correct the source failure or register a
new scoped campaign when a finite study is finished. Retain previous campaign
pointers/receipts and source records for provenance.

arXiv documents the [OAI-PMH harvesting interface](https://info.arxiv.org/help/oa/index.html)
and [legacy API terms](https://info.arxiv.org/help/api/tou.html).
