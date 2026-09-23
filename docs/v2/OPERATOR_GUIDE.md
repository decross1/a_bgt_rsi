# Operator guide

This guide covers the local apparatus and the 2026-09-20 progression repair. Start with
read-only checks. Restart only the component whose behavior requires it, and
verify both the process and its public health/read-model boundary afterward.

## 1. Daily orientation

For the ongoing source-bound exploratory queue, ingestion receipts, daily
limits, and honest idle outcomes, see [Daily research operation](DAILY_RESEARCH_OPERATIONS.md).

Open `http://127.0.0.1:5173/` on the Spark, or
[the Spark observatory](http://spark-7eeb:5173/) from a device that can reach it.
The sidebar groups the workspace by
intent:

| Page | Route | Use it for |
| --- | --- | --- |
| Now | `/` | Health, alerts, active and recent work |
| Research | `/ladder` | Current questions, evidence, criticism, recorded learning, and the next research agenda |
| Record library | `/dossier` | Search durable records; a dossier has one opening summary and an expandable pipeline |
| Evaluations | `/experiments` | Experiment execution and results, with historical work explicitly scoped |
| Operations | `/development` | Services, workers, runtime and maintenance state |
| Benchmarks | `/benchmarks` | The frozen regression canary, admitted references, and comparable dated results |
| Conversation | `/channel` | Attributable lab messages and bounded actions |
| Calls | `/model-io` | Model requests, policies, usage, and terminal state |
| Trace history | `/cycles` | Coordinator cycles and step-level outcomes |
| Request inspector | `/chain/req/:id` | Request-chain diagnosis when the referenced call is available |

The command palette and navigation use the same destinations. Legacy `/ideas`,
`/todo`, and `/coordinator` links redirect to Research, Record library, and Trace
history. The former disconnected graph at `/graph` redirects to Trace history.
Cycles and the record library paginate instead of rendering their entire
histories. Evaluations no longer embeds a second copy of the coordinator log.

Iteration titles describe the source question; identifiers such as
`iter-2026-09-15-007` remain available as secondary provenance. A descriptive
title is not a claim that the hypothesis was validated. The dossier separates
model commentary, observed execution, and measured scientific support.

### Focus versus browsing

The **Research focus** card on Now and Research names the lab's durable priority,
its next required artifact, current blocker, and work owner. **Browse thesis**
changes only the record being inspected. Selecting a historical seed does not
activate its old campaign, authorize a study, or inherit its evidence level.
Damaged structured output is displayed as an unassessed source requiring claim
refinement.

The focus receipt lives under `run_state/research_focus/`, selected by the
atomic `run_state/active_research_focus.json` pointer. With
`focus_before_new_topics`, the exploratory coordinator holds new topic intake
until the focus policy is explicitly changed. Ingestion and independently
eligible promotion work remain available. A `focus_pending` cycle is an honest
hold, not completed research. The focus's named next action must be carried out
by its assigned owner; a focus selection does not itself schedule an experiment.

Progress has two distinct checks: whether a study was prepared and executed
correctly, and whether its result supports the scientific claim. Arithmetic or
tool-interface diagnostics can unblock study preparation without earning L2.
Do not count model calls or game rounds as independent experimental units.

Failed hypothesis generation receives one bounded structured-output retry.
If that also fails, the iteration stops before downstream research. Historical
malformed rows receive source-bound receipts in
`memory/consolidation_quarantine.jsonl`; consolidation still projects later
valid rows. Quarantine receipts are operational evidence and never ladder credit.

## 2. Health check

Run these before changing a service:

```bash
cd /home/decross1/projects/a_bgt_rsi
ui/scripts/ui-services.sh status
systemctl --user show nara-daemon.service \
  -p ActiveState -p SubState -p MainPID -p ExecMainStartTimestamp
curl -fsS http://127.0.0.1:8700/api/health
curl -fsS http://127.0.0.1:30080/v1/models
curl -fsS http://127.0.0.1:30080/health
```

The selected production model is `nvidia/Qwen3.8-Flash-Next-NVFP4`, as bound in
`config/model_deployment.json`. The legacy Gemma/Qwen pair is intentionally
stopped. A missing legacy endpoint is not a Flash outage. Confirm the exact
model identity, live deployment readiness, and container state; a listening port
alone does not prove readiness. Process identity checks must run in the host
namespace: a restricted development sandbox can hide healthy host processes.

Useful process checks:

```bash
systemctl --user status nara-daemon.service --no-pager
journalctl --user -u nara-daemon.service -n 100 --no-pager
crontab -l
ss -ltnp | rg ':(5173|8700|30080)\b'
python3 -m orchestrator.flash_resident check-ready
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

Use `/benchmarks` for the current measurement program. Its initial release has
18 capability units and three actor–tool–critic harness workflows per arm.
The definition, task inputs, graders and resource ceilings are frozen together;
the first review boundary is **2026-10-14 00:00 UTC**. This is a small regression
canary, not a broad scientific-intelligence score or a full production-pipeline
evaluation. Public benchmark suites are candidates for separately versioned
extensions; the current core does not claim to have run them.

Scores appear only after the run's raw replay and independent resource/recovery
admission bind the same definition, manifest and receipt bytes. Missing,
unissued, invalid and withheld attempts are gaps, not zero scores. A previous
successful run must not make a newer failed attempt look complete.

The dated history retains each arm's route, inference policy, source identity,
wall time and per-construct result. Matched comparisons require the same frozen
release and comparison cohort. Strategic mechanisms remain separate. There is
no aggregate score across science, code, tool use and strategic behavior.
Small-panel deltas are descriptive; a one-item win is not a population estimate.

Open **Evidence archive** (`/benchmarks?view=evidence`) for the earlier Flash,
context, cap, role, weekly and pipeline records. Historical results retain their
original denominators; they are not retroactively inserted into the new core.

### Weekly apparatus evaluation

The archived weekly section separates:

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

### Cadence and follow-through

The existing hook is **Sunday at 05:30 UTC**, in review-only mode. A review
report is not evidence that a benchmark ran. The empty trial-manifest setting
does not authorize an automatic model switch. Normal weekly maintenance has
120 Spark minutes; the owner's unrestricted local allowance for this one-time
qualification session does not silently alter that recurring budget.

At each review, inspect the newest admitted reference, new failure clusters and
upstream evidence. Preregister one justified change, preserve the reference
configuration, run matched tasks, and retain both successful and aborted
receipts. A changed fixture, grader, inference policy or harness must be named
in the comparison. Release expiry requires a recorded review before new runs.
Most reviews should leave production unchanged.

The Sunday cycle report now carries a `stable_benchmark` section with the
current frozen release, receipt-verified grader outputs, review boundary, and a
manual next-run preregistration recipe. Receipt admission proves the registered
execution/replay/supervision chain; consult the versioned measurement review
before treating any row as a valid task measurement. The section never grants
promotion authority. It also keeps the small canary separate from monthly or
triggered public-benchmark rotations.

Release 1.0.0 is currently `commissioning_only`; its
[measurement review](../benchmarks/measurement_reviews/75de9dc0dc324a4559332f88ae6e5ae861ba0d6f683334d85395d082bbaf04df.json)
records the task-contract defects corrected prospectively in release 1.1.0. The
[active catalog](../benchmarks/program_catalog.json) selects 1.1.0; use the
Benchmarks release selector to inspect the 1.0.0 archive. Keep its recorded
numbers and receipts unchanged, and do not compare scores across releases.

The application agenda in Research is proposed work, not an active trading
strategy. It starts from game-theoretic mechanisms and data requirements:
options are the preferred investigation, prediction markets an alternative,
and crypto requires an explicit mechanism fit. See
[the application research agenda](APPLICATION_RESEARCH_AGENDA.md). Completed
Bitcoin reference studies remain historical evidence; their capture and polling
timers were retired after closure on 2026-09-16. No order placement is enabled.

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

### Nara lane

The Nara lane (`orchestrator/nara_lane.py`, `nara-lane.service` /
`nara-lane.path` / `nara-lane.timer`) runs Nara's own code changes inside a
bwrap sandbox and lands them on `nara/<id>` branches for review; the review
gate is `config/nara_lane.json`.

```bash
touch /home/decross1/projects/a_bgt_rsi/run_state/pause_nara_lane
```

pauses the lane while leaving the research coordinator (`pause_coordinator`)
unaffected. Only the human removes it to resume:

```bash
rm /home/decross1/projects/a_bgt_rsi/run_state/pause_nara_lane
```

See [`docs/ORACLE_NARA_MAILBOX.md`](../ORACLE_NARA_MAILBOX.md).

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

The deployed resident is Flash (`flash-resident.service`); the prior
Gemma/Qwen pair is stopped and is a rollback path only (§6.2).

### 6.1 Flash resident recovery

```bash
systemctl --user status flash-resident.service --no-pager
journalctl --user -u flash-resident.service -n 100 --no-pager
.venv-chroma/bin/python -m orchestrator.flash_resident check-ready
curl -fsS http://127.0.0.1:30080/v1/models
```

`check-ready` performs read-only admission (supervisor boot/PID/heartbeat,
exact served model, available host memory) and is the supported check — do
not substitute the old pair-specific health check. The supervisor takes the
shared lab locks only while changing services, stopping Nara during the
transition and resuming it after readiness; both Nara and cron check actual
Flash readiness on every pass. Preserve the 10 GiB host reserve (helper v8) —
do not lower it to make a model fit. Full recovery detail, including the
NVIDIA CDI boot-ordering fix and the swap-limit repair, is in
[`docs/FLASH_RESIDENT.md`](../FLASH_RESIDENT.md).

An owner-selected rollback requires stopping Flash first, removing the Flash
deployment selection and restoring the old client routes, then starting the
retained pair containers per §6.2. The watchdog refuses pair startup while
any owned Flash container remains running.

### 6.2 Rollback: the Gemma/Qwen pair (stopped 2026-09-19)

The watchdog checks every five minutes and runs `docker start` only for the
existing `vllm-gemma4` and `vllm-qwen` containers when the pair is the active
selection. It does not re-create or change them. An A/B container named
`vllm-qwen-ab` deliberately makes the watchdog stand down.

Inspect before acting:

```bash
docker ps -a --filter name=vllm-gemma4 --filter name=vllm-qwen
docker logs --tail 100 vllm-gemma4
docker logs --tail 100 vllm-qwen
```

Starting an existing stopped container is different from running
`cron/serve-models.sh`: the launcher removes and recreates containers from the
prior production configuration. Use the launcher only for an authorized
rollback that requires recreation, then verify:

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

The read-only benchmark observation appears at:

```text
/home/decross1/projects/a_bgt_rsi_weekly_upgrade_runs/<ISO-WEEK>/cycle_report.json
```

For a newly created ISO-week review it is also copied into
`review/weekly_report.json`. A completed provider review stays immutable. If the
Sunday owner revisits the same ISO week, as it will on September 20 after the
September 14 `2026-W38` review, `cycle_report.json` refreshes the benchmark
observation while the two provider calls remain unrepeated. Check it with:

```bash
python3 - <<'PY'
import json
from pathlib import Path

week = "2026-W38"
path = Path("/home/decross1/projects/a_bgt_rsi_weekly_upgrade_runs") / week / "cycle_report.json"
print(json.dumps(json.loads(path.read_text())["stable_benchmark"], indent=2))
PY
```

`next_run_preregistration` is a recipe, not an action queue. It permits no paid
API call, automatic scheduling, inference, or runtime change. Before the release
review boundary, prepare a fresh comparison registration and lifecycle plan in
source control. At the boundary, record an explicit unchanged-definition
extension or publish a new semantic release. Task/oracle corrections require a
new release; the original receipts remain visible under their original version.

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
