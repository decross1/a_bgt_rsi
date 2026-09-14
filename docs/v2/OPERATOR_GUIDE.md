# Operator guide

This guide covers the deployed local apparatus as of 2026-09-14. Start with
read-only checks. Restart only the component whose behavior requires it, and
verify both the process and its public health/read-model boundary afterward.

## 1. Daily orientation

Open `http://127.0.0.1:5173/` on the Spark, or
[the Spark observatory](http://spark-7eeb:5173/) from a device that can reach it.
The sidebar groups the workspace by
intent:

| Page | Route | Use it for |
| --- | --- | --- |
| Now | `/` | Health, alerts, active and recent work |
| Research | `/ladder` | Evidence rungs, open claims, and next test owed |
| Record library | `/dossier` | Search and inspect durable research records |
| Evaluations | `/experiments` | Experiment execution and results |
| Operations | `/development` | Services, workers, runtime and maintenance state |
| Benchmark progress | `/benchmarks` | Weekly evaluations and current research-pipeline funnel |
| Conversation | `/channel` | Attributable lab messages and bounded actions |
| Calls | `/model-io` | Model requests, policies, usage, and terminal state |
| Trace history | `/cycles` | Coordinator cycles and step-level outcomes |
| Graph / request inspector | `/graph`, `/chain/req/:id` | Relationship and request-chain diagnosis |

The command palette and navigation use the same destinations. Legacy `/ideas`,
`/todo`, and `/coordinator` links redirect to Research, Record library, and Trace
history.

## 2. Health check

Run these before changing a service:

```bash
cd /home/decross1/projects/a_bgt_rsi
ui/scripts/ui-services.sh status
systemctl --user show nara-daemon.service \
  -p ActiveState -p SubState -p MainPID -p ExecMainStartTimestamp
curl -fsS http://127.0.0.1:8700/api/health
curl -fsS http://127.0.0.1:8000/v1/models
curl -fsS http://127.0.0.1:8001/v1/models
```

Expected model IDs are `gemma-4-26b-a4b` and
`qwen3.8-27b-nvfp4-mtp`. A listening port alone does not prove that a model is
ready. Confirm the model list and inspect its container log when model behavior
is in question.

Useful process checks:

```bash
systemctl --user status nara-daemon.service --no-pager
journalctl --user -u nara-daemon.service -n 100 --no-pager
crontab -l
ss -ltnp | rg ':(5173|8700|8000|8001)\b'
docker ps --filter name=vllm-gemma4 --filter name=vllm-qwen
```

Service logs:

```text
logs/nara-daemon.log
logs/coordinator-cron.log
logs/frontier-cron.log
logs/watchdog.log
ui/logs/services/backend.log
ui/logs/services/vite.log
ui/logs/services/sampler.log
```

A pre-existing loop alert is an apparatus state to investigate. Its presence on
a newly changed page does not by itself mean that page failed.

## 3. Read benchmark progression correctly

Use `/benchmarks` to answer two different questions.

### Weekly apparatus evaluation

The weekly section separates:

- a review decision from a benchmark execution;
- transport returns from objective task success;
- recorded operator summaries from scientific ground truth;
- charged Spark allowance from observed run duration;
- one-week baselines from comparable multi-week trends;
- absent measurements from measured zero.

`No upgrade established` means the evidence does not establish an upgrade. It
does not mean every candidate was worse. A family is comparable only when the
suite, fixtures/inputs, graders, declared attempts, and budget bindings produce
the same cohort fingerprint. Do not compare bars across heterogeneous benchmark
families or changed cohorts.

Expand a family to inspect arm configuration, denominators, timeouts,
uncertainty metric, comparison basis, hashes, and interpretation limits. Correct
Task Throughput and Reliable Success Rate are meaningful only when their exact
objective denominators exist.

### Research follow-through

The selected-campaign panel follows the campaign across week boundaries,
starting at its validated activation boundary. The legacy corrected-topic view
retains its separate cutoff. It shows conversion through:

```text
topic attempt -> dispatch -> iteration -> scope -> L1+ evidence
              -> skeptic -> L4 -> explicit human L5
```

`Not yet observed` means the bounded source window contains no eligible record.
It is not a failed run. Follow the coverage rows and qualifications before
interpreting funnel counts. Expanded details expose source availability, bounded
read hashes, malformed-row counts, cutoff identity, and the exact join contract
without revealing private topic or model payloads.

The funnel is an operational measurement. Scientific support for a thesis lives
in the Research, Record library, and Evaluations pages.

## 4. Pause and resume

### Research coordinator

Soft pause prevents new coordinator work while leaving the daemon resident:

```bash
touch /home/decross1/projects/a_bgt_rsi/run_state/pause_coordinator
```

Verify the next pass refuses in `logs/nara-daemon.log` or
`logs/coordinator-cron.log`. Anyone may create this safety file. Only the human
removes it to resume:

```bash
rm /home/decross1/projects/a_bgt_rsi/run_state/pause_coordinator
```

### Frontier and weekly maintenance

Pause all frontier work:

```bash
touch /home/decross1/projects/a_bgt_rsi/run_state/pause_frontier
```

Pause only the weekly upgrade cycle while retaining other frontier behavior:

```bash
touch /home/decross1/projects/a_bgt_rsi/run_state/pause_weekly_upgrade
```

The human removes either pause file when resuming. A pause refusal exits cleanly
and is the designed state.

### Hard-stop Nara

Use a hard stop when the process itself must be absent:

```bash
systemctl --user stop nara-daemon.service
systemctl --user status nara-daemon.service --no-pager
```

A later restart is a runtime action:

```bash
systemctl --user restart nara-daemon.service
systemctl --user show nara-daemon.service \
  -p ActiveState -p SubState -p MainPID -p ExecMainStartTimestamp
```

Confirm `WorkingDirectory` and `ExecStart` still point at the canonical checkout
before treating the restart as adoption of new code.

## 5. UI recovery

[`ui/scripts/ui-services.sh`](../../ui/scripts/ui-services.sh) manages the UI
backend, frontend, and sampler.

Read-only status:

```bash
ui/scripts/ui-services.sh status
```

`ensure` starts only a component that is down and otherwise remains quiet. It is
also run by cron every two minutes:

```bash
ui/scripts/ui-services.sh ensure
```

`start` first stops all three UI components and then relaunches them. Do not use
it for a targeted backend refresh.

### Targeted backend restart

First identify the one listener:

```bash
lsof -nP -iTCP:8700 -sTCP:LISTEN
```

After confirming the PID belongs to the canonical FastAPI process, stop that PID
and let `ensure` restore only the missing backend:

```bash
kill "$(lsof -tiTCP:8700 -sTCP:LISTEN)"
ui/scripts/ui-services.sh ensure
curl -fsS --retry 30 --retry-delay 1 --retry-connrefused \
  http://127.0.0.1:8700/api/health
```

The frontend is a long-running Vite process and normally observes source changes
through HMR. Restart it only if the actual frontend process or module graph is
stale. The sampler does not need a restart for backend-only changes.

Because cron may run `ensure` during recovery, re-check the listener PID and
process working directory after the operation.

## 6. Model service recovery

The watchdog checks every five minutes and runs `docker start` only for the
existing `vllm-gemma4` and `vllm-qwen` containers. It does not re-create or
change them. An A/B container named `vllm-qwen-ab` deliberately makes the
watchdog stand down.

Inspect before acting:

```bash
docker ps -a --filter name=vllm-gemma4 --filter name=vllm-qwen
docker logs --tail 100 vllm-gemma4
docker logs --tail 100 vllm-qwen
```

Starting an existing stopped container is different from running
`cron/serve-models.sh`: the launcher removes and recreates containers from the
current production configuration. Use the launcher only for an authorized
configuration adoption or recovery that requires recreation, then verify:

- exact `/v1/models` IDs;
- Gemma's MARLIN backend log;
- Qwen reasoning and tool parser behavior;
- both containers resident together;
- the 30 GiB `MemAvailable` guard;
- a known tool/reasoning smoke and rollback point.

Do not lower the memory margin to make a configuration fit.

## 7. Weekly upgrade operation

The installed cron owner runs Sunday at 05:30 UTC. With the current empty trial
manifest it performs the review lane only:

1. capture the production and evidence snapshot;
2. use no more than two subscription frontier calls;
3. obtain independent proposal and adversarial analysis;
4. record a structured weekly decision and source provenance;
5. stop without automatically rerunning benchmarks or promoting production.

A trial runs only when its exact checked-in manifest is supplied and admitted by
the controller. All trials share a hard 120-minute Spark allowance per UTC ISO
week. The budget journal includes controller wall charges and any explicit
prior-use debit; it is not a GPU-utilization meter.

Inspect the public projection:

```bash
curl -fsS http://127.0.0.1:8700/api/weekly_upgrade/progress \
  | python3 -m json.tool
```

Inspect raw/private artifacts only from the canonical local paths recorded in
receipts, and do not publish their payloads. The dashboard intentionally exposes
sanitized summaries and cryptographic provenance instead.

A weekly report does not authorize a model, runtime, inference-policy, scaffold,
or prompt cutover. Promotion needs a concrete reviewed change, matched evidence,
a rollback, and the authority required by the affected production contract.

## 8. Human research actions

Use the UI or the existing narrow CLI/API seam for a verdict or follow-up. Before
writing:

1. open the complete record and its evidence level;
2. verify the iteration/finding ID;
3. inspect the next test owed and provisional flags;
4. distinguish L4 automatic qualification from L5 human validation;
5. submit one explicit action;
6. reload the projection and verify the append-only receipt.

Never infer a human verdict from a note, a model summary, an absence of objection,
or a transport success.

## 9. Diagnosing a stalled research path

Follow the data in order:

1. `/development` and `/cycles`: did a coordinator cycle execute or no-op?
2. cycle receipt: was a research step attempted, refused, timed out, or returned?
3. `/model-io`: did the model call use the intended backend/profile and return a
   protocol-valid result?
4. `memory/loop_memory.jsonl`: is the exact dispatched iteration ID present?
5. `/ladder`: what evidence rung and next test were derived?
6. promotion near-miss/surfaced finding: was there a recorded disposition?
7. `memory/loop_feedback.jsonl`: is there an explicit human verdict?
8. `/benchmarks`: does the bounded research funnel report a missing or ambiguous
   link and the responsible source hash?

Do not join stages by matching topic text. Use IDs and recorded digests.

## 10. Delivery and rollback

Before adoption:

```bash
git status --short
git diff --check
git log -1 --oneline
```

Run the checks appropriate to the changed surface. Preserve unrelated dirty
files and record the public commit, canonical integration commit, pre-deployment
service identities, and relevant source hashes.

Prefer a normal revert of the delivered commit over a destructive history
rewrite. After a code rollback, reload only the affected service and repeat its
health/read-model smoke. Model/runtime rollback additionally restores the prior
immutable container image/configuration and rechecks co-resident memory.

A complete deployment receipt answers:

- what commit and files were adopted;
- which process was reloaded, if any;
- what remained untouched;
- which tests and live checks passed;
- what source/configuration identities were observed;
- how to return to the previous state.


## 11. Campaign lifecycle

The declaration in `experiments/research_campaign_v2_agentic_game_theory_20260914.json`
is immutable. Its `prepared` value is declaration metadata, not the live state.
The runtime pointer is `run_state/active_research_campaign.json` and contains:

```json
{
  "schema_version": "research-campaign-activation/v1",
  "campaign_id": "v2-agentic-game-theory-20260914",
  "campaign_manifest_sha256": "3357cb3a7b4bcc2c45af991e186c7f19abfa27ec0e18d1d172f9a03e2fd0f4dd",
  "activated_at": "<actual UTC activation time>",
  "activated_by": "<attributable operator>"
}
```

Write that pointer only as part of an authorized adoption after schema/hash
validation. Both daemon and hourly coordinator resolve it. An optional
`NARA_RESEARCH_CAMPAIGN` environment value can assert the selected ID, but cannot
activate a campaign by itself or override the pointer. A mismatch refuses work.
Preserve any previous pointer and record the actual service/code identities in
`run_state/v2_preparation/deployment_receipt.json`.

For rollback, restore the recorded prior pointer (or remove this operator-created
pointer if it was previously absent), then reload only the affected service.
Keep all campaign-tagged evidence. Rollback does not remove a human pause or
backfill old records. A permanent closure uses a separate hash-bound receipt in
`run_state/research_campaign_closures/` conforming to the closure schema. A
closed campaign refuses new execution while its historical records remain
available. Never edit the declaration to change its lifecycle.

The current controlled model-game study is not registered for execution.
Additional studies need separate immutable registration receipts bound to the
campaign, or a new explicit campaign revision. Campaign-qualified experiment
and refinement writers remain deferred; the current runtime admits ordinary
research iterations, matching finding promotion, bounded bubbles and no-ops.
