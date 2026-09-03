# Adversarial systems review — September 2026

> Produced 2026-09-03 from the bounded Team 3 review at
> `56c1b3abae968c8288471b30946000c29ae6f228`. The review was read-only; no
> code, runtime state, or service was changed. Load-bearing counts were
> independently recomputed by the primary session.

## Executive verdict

The fixed nine-item corpus contains one present audit-integrity violation,
three material security/reliability/control failures, and five operability or
governance defects. The most urgent defect is not hypothetical: 161 rejected
`bubble_up` actions were nevertheless persisted as real human escalations and
their cycles were labeled `executed`. The next priorities are to close the UI
backend's unauthenticated all-interface mutation boundary and to stop repeated
three-minute frontier-review timeouts.

The review also corrected several preliminary claims. A budget-paced refusal
did not execute handlers as a dry run; its CLI label is false because the
refusal record omits `dry_run`. The UI transfer estimate is 0.78 GiB/hour for
one continuously open Cycles tab, not 1.59 GB/hour per tab. The documented
14-day stale daemon was historical rather than current, although no loaded-SHA
gate now prevents a recurrence. Network reachability beyond the host was not
established, so the UI issue is S1 rather than S0.

## Method and limits

The review covered execution and ledger truth; network and mutation
boundaries; scheduler, budget, and topic lifecycle; frontier reliability; UI
observability/data-plane scaling; and documentation, governance, and daemon
lifecycle. Findings were tested through three adversarial lenses:

- **real** — does current source plus reproduced output establish the claim?
- **material** — does it matter at one-box, one-human, at-most-60-units/day
  scale?
- **honest** — are the reproduction, window, qualification, and proposed fix
  stated without inflation?

Severity is S0 for a present integrity/security invariant violation, S1 for a
material control, reliability, or throughput failure, S2 for an operability or
trust defect without a demonstrated immediate destructive path, and S3 when
negligible at the operating scale. Effort ranges from E0 (localized patch and
test) through E3 (architectural work). Tier S means the change touches an
entrenched spine, runtime-state semantic, ratified workflow, or canonical
policy; Tier P is ordinary product/runtime implementation.

The original 1,800-second finder exceeded its budget before completing two dry
miss-hunt rounds. A 600-second recovery agent reconciled and refuted the fixed
nine-item corpus. This document is therefore complete for those nine items,
not an exhaustive claim that no other systems defects exist.

## Scout-map corrections

| Preliminary claim | Final disposition |
| --- | --- |
| 161 invalid bubbles were accepted and persisted | Confirmed more precisely: the handler outcomes errored, yet all 161 cycles stayed `executed`, had `bubble_run_ids`, and matching off-enum rows were persisted. |
| The UI was remotely exposed | All-interface bind, wildcard CORS, absent OpenAPI authentication, and 16 mutating routes were observed; off-host reachability was not established. |
| Budget-paced execution ran as a dry run | Corrected: no handler ran. Execute-mode refusal records omit `dry_run`, and the CLI defaults that absent field to `True`. |
| One topic repeated 61 times | Confirmed: after one agenda dispatch, the same `coordinator_propose` row drove 61 more successful runs and 183 ideation units. |
| Codex lost about 1.8 hours to timeouts | Corrected: the latest 51 Codex rows contain 33 three-minute timeouts totaling 1.650 hours; all 51 calls total 2.034 hours. |
| UI polling costs about 1.59 GB/hour | Corrected: the measured response implies 0.78 GiB/hour per continuously open Cycles tab or 1.56 GiB/hour for two. Experiments fetches cycles once rather than polling. |
| `START_HERE.md` is stale | Confirmed. |
| The daemon is currently 14 days stale | Corrected: that was a historical incident; the lifecycle still lacks a loaded-SHA/restart evidence gate. |
| The full-green gate conflicts with the accepted baseline | Confirmed as a policy contradiction, not evidence of a new regression. |

## Fix now

### F1 — Errored bubbles are persisted as real and their cycles remain executed

- **Location:** `orchestrator/coordinator.py:745-802,1209-1241,1245-1304`
- **Class:** S0 / E0 / Tier S; governed by CLAUDE rule 4 and D-046
- **Observed:** among 881 cycle rows, 161 contain an errored `bubble_up`
  outcome. All 161 still have cycle status `executed` and a nonempty
  `bubble_run_ids`; `memory/coordinator_bubbles.jsonl` contains 161 matching
  off-enum rows among 181 total rows.
- **Cause:** `handle_bubble_up` rejects invalid enums correctly, but
  `_collect_bubble_up` ignores its `executed` argument, collects the rejected
  planned action, and hands it to `_persist_bubble_up`. The cycle report then
  receives unconditional status `executed`.
- **Impact:** audit corruption has already occurred. Each new invalid plan can
  immediately create another false human-facing escalation.
- **Smallest fix:** collect and persist only bubbles whose matching dispatch
  outcome passed; give a cycle with an action error an explicit partial/error
  state; pin the negative path in tests.
- **Confidence/scout:** 0.99; extends the scout finding.

Reproduction:

```bash
jq -s '{cycles:length,
  bubble_error_cycles:([.[]|select(any(.outcomes[]?;.action=="bubble_up" and .status=="errored"))]|length),
  bubble_error_executed:([.[]|select(.status=="executed" and any(.outcomes[]?;.action=="bubble_up" and .status=="errored"))]|length),
  bubble_error_refs:([.[]|select(any(.outcomes[]?;.action=="bubble_up" and .status=="errored") and ((.bubble_run_ids//[])|length>0))]|length)}' \
  run_state/coordinator_cycles.jsonl
jq -s '{rows:length,off_enum:([.[]|select((.kind?!=null) and (.kind!="A") and (.kind!="B") and (.kind!="C"))]|length)}' \
  memory/coordinator_bubbles.jsonl
```

Refuters: **real stands** because source and joined ledgers agree; **material
stands at S0** because persisted audit state claims validation that failed;
**honest stands** because the finding distinguishes the failed bubble from
other successfully executed actions.

### F2 — Wildcard-CORS mutation API binds every interface without authentication

- **Location:** `ui/backend/run.sh:6`, `ui/backend/app.py:122-125,289-306`
- **Class:** S1 / E1 / Tier P; governed by D-046
- **Observed earlier in this session:** the Python listener was on
  `0.0.0.0:8700`; a hostile `Origin` received
  `access-control-allow-origin: *`; OpenAPI declared neither security nor a
  security scheme and exposed 16 POST routes.
- **Impact:** unauthorized mutation or process-launch risk is immediate if
  port 8700 is reachable by another principal. Firewall, LAN, Tailscale, and
  internet reachability were not established.
- **Smallest fix:** bind loopback by default, require explicit configuration
  for a remote bind, restrict CORS origins, and require authentication before
  any remote exposure.
- **Confidence/scout:** 0.92; confirms the mechanism while lowering severity.

Refuters: **real stands** on the observed listener/configuration/routes;
**material stands conditionally at S1**; **honest rejects any stronger claim of
proven internet exposure**.

### F5 — Recent Codex falsifier calls spend most wall time timing out

- **Location:** `agent_wrapper/frontier_cli.py:239-310`,
  `workers/frontier_review.py:72-74,218-266,305-306`
- **Class:** S1 / E1 / Tier P; governed by D-061
- **Observed:** the latest 51 `vendor=codex` ledger rows, from
  2026-09-02 12:04Z through 18:13Z, contain 33 exit-`-1` calls at approximately
  180 seconds. Timeout wall time is 5,940,919 ms (1.650 hours); all-call wall
  time is 7,323,141 ms (2.034 hours).
- **Impact:** every timeout blocks up to three minutes and yields a fail-open
  `inconclusive` review; 99 minutes in the measured window ended exactly at
  the timeout boundary.
- **Smallest fix:** add a short-lived circuit breaker after the existing
  consecutive-failure threshold, preserve explicit
  `inconclusive/vendor-down` evidence during cooldown, and evaluate a shorter
  timeout against observed successful latency.
- **Confidence/scout:** 0.98; verifies the scout with corrected totals.

Refuters: **real stands** because exit code and duration agree; **material
stands at S1** at 33/51; **honest stands** because null low-level verdicts were
not mislabeled as failures.

## Fix soon

### F6 — Cycles rereads and retransmits the full ledger every five seconds

- **Location:** `ui/backend/coordinator.py:28-76`,
  `ui/frontend/src/routes/Cycles.tsx:101-174`
- **Class:** S2 / E1 / Tier P; related to D-047 observability
- **Observed:** an earlier API snapshot was 1,164,784 bytes. At the five-second
  interval, that is 0.78 GiB/hour for one Cycles tab or 1.56 GiB/hour for two.
  The ledger later measured 881 rows and 1,217,316 bytes.
- **Impact:** immediate local parsing, allocation, and transfer overhead while
  the page is open, growing linearly with the append-only ledger.
- **Smallest fix:** bounded default page with `before`/cursor pagination or an
  incremental `since` feed, while preserving explicit access to old history.
- **Confidence/scout:** 0.98; corrects the units and excludes Experiments from
  repeated polling.

Refuters: **real stands** on full reads and the five-second timer; **material
caps at S2** on one local box; **honest stands with the correction that
Experiments performs only a one-time cycles fetch**.

### F7 — Startup guide directs operators into retired state and topology

- **Location:** `START_HERE.md:29-40,76-107`
- **Class:** S2 / E0 / Tier P; governed by D-037, D-063, and D-035/D-044/D-061
- **Observed:** the guide calls `LOOP_V0.md` current, describes one primary plus
  an optional UI session, labels continuous orchestration out of scope, and
  says a second model is excluded. `CLAUDE.md:223-237` instead permits the
  daemon and fixes Gemma, Qwen, and frontier roles.
- **Impact:** a new operator can adopt the wrong plan, concurrency model, and
  runtime assumptions immediately.
- **Smallest fix:** point to `LOOP_V1.md`, describe bounded Dynamic Workflows,
  and mirror the canonical current daemon/model topology.
- **Confidence/scout:** 0.99; verifies.

Refuters: **real stands** on direct textual contradictions; **material caps at
S2** because no downstream incident was demonstrated; **honest stands**
because these are presented as current instructions rather than history.

## Design questions for the owner

### F3 — Execute-mode budget refusals print `dry_run=True`

- **Location:** `orchestrator/coordinator.py:1013-1045,1355-1363`
- **Class:** S2 / E0 / Tier S; governed by D-063 and CLAUDE rule 6
- **Observed:** `cron/run-coordinator.sh` logs an execute launch, while multiple
  paced refusals print `status=daily_budget_paced ... dry_run=True`.
- **Cause:** refusal reports omit `dry_run`; the CLI uses
  `report.get("dry_run", True)`.
- **Impact:** each execute-mode budget refusal immediately emits a false mode
  label. The refusal itself is correct and no handler runs.
- **Smallest fix:** put the requested mode in every refusal record and remove
  the truthy presentation fallback.
- **Confidence/scout:** 0.99; corrects the preliminary causal claim.

Refuters: **real stands as a logging defect**; **material caps at S2** because
the gate behavior works; **honest rejects any claim that handlers executed**.

### F4 — Successful `coordinator_propose` topics are never consumed

- **Location:** `orchestrator/coordinator.py:333-415,1218-1219`
- **Class:** S1 / E1 / Tier S; governed by D-060
- **Observed:** the topic “Test-Time Collaborative Classification over
  Multi-Agent Networks” ran successfully 62 times from 2026-08-26 19:10Z
  through 2026-09-03 05:01Z: once from `agenda`, then 61 times from
  `coordinator_propose`. Those repeats cost 183 ideation units.
- **Cause:** `_topic_suggestions` rereads the last follow-up rows indefinitely;
  `_consume_agenda_topic` consumes only `source == "agenda"` rows that carry a
  `cluster_id`.
- **Impact:** the already-observed repeat cost exceeds three complete daily
  caps.
- **Smallest fix:** ratify success/retry semantics for machine-proposed
  follow-ups, append a consumed/claimed tombstone after successful dispatch,
  and exclude consumed rows during selection.
- **Confidence/scout:** 0.99; extends.

Refuters: **real stands** because the source transition separates this from
semantic similarity; **material stands at S1** on 183 units; **honest stands**
because the initial agenda execution is excluded from repeat cost.

### F8 — Daemon lifecycle has no loaded-SHA or restart-evidence gate

- **Location:** `systemd/nara-daemon.service:21-33`,
  `orchestrator/nara_daemon.py:408-419`, `human/sessions/2026-09-02.md:12-17`
- **Class:** S2 / E1 / Tier S; governed by D-063
- **Observed:** start logging records PID and heartbeat but no loaded Git SHA.
  The September 2 session documents a prior process that ran pre-`7dcc695`
  code for 14 days and produced 358 of 438 false stall signals before restart.
  No active code skew was established during this review.
- **Smallest fix:** snapshot and expose loaded SHA at daemon start and add a
  human-owned post-merge comparison/restart evidence gate for runtime changes.
- **Confidence/scout:** 0.94; corrects the current-state implication.

Refuters: **real stands as a missing control with a documented incident**;
**material caps at S2** because the current process was recently restarted;
**honest restricts the claim to lifecycle risk**.

### F9 — Canonical full-green policy conflicts with the accepted failure baseline

- **Location:** `CLAUDE.md:83-90,179-182`,
  `human/sessions/2026-09-02.md:57-68`
- **Class:** S2 / E0 / Tier S
- **Observed:** the canonical workflow gate requires the “full suite green,”
  while the approved session plan accepts comparison to a baseline of 12
  failed, 2,482 passed, and 2,496 collected tests.
- **Impact:** every merge must disregard either canonical wording or the
  session plan, leaving room to misclassify a regression as baseline.
- **Smallest fix:** ratify one rule: restore green before merging, or define a
  fingerprinted, expiring grandfather baseline that fails on every delta.
- **Confidence/scout:** 0.99; new.

Refuters: **real stands** on the written conflict; **material caps at S2**
because no new regression was attributed to it; **honest stands** because
documented failures remain failures rather than being relabeled green.

## Rankings and reconciliation

| Severity-first | Effort-first within severity bands |
| --- | --- |
| F1 | F1 |
| F2 | F2 |
| F4 | F5 |
| F5 | F4 |
| F3 | F3 |
| F7 | F7 |
| F9 | F9 |
| F6 | F6 |
| F8 | F8 |

F1 remains first because it is both present false state and E0. F2 precedes
the reliability defects because an unauthorized mutation path exists if the
listener is reachable, while the missing reachability evidence prevents S0.
F4 outranks F5 on demonstrated consumed budget, but F4 routes to owner design
because consumption semantics are Tier S. F5 remains fix-now because a
bounded cooldown need not change D-061's role contract. F3 and F9 remain
distinct producer-truth and policy-truth defects. No findings were merged.

## Owner triage (proposed)

| Priority | ID | One-line action | Bucket | Tier |
| --- | --- | --- | --- | --- |
| T1 | F1 | Persist only successfully executed bubbles and pin the error path. | fix-now | S |
| T2 | F2 | Decide the intended network boundary; default to loopback immediately. | fix-now | P |
| T3 | F5 | Add a timeout cooldown without hiding fail-open evidence. | fix-now | P |
| T4 | F4 | Ratify when a machine-proposed follow-up is consumed versus retried. | design | S |
| T5 | F3 | Make refusal mode explicit in records and CLI output. | design | S |
| T6 | F7 | Bring startup instructions onto LOOP_V1 and the current topology. | fix-soon | P |
| T7 | F6 | Add bounded or incremental cycles retrieval. | fix-soon | P |
| T8 | F8 | Ratify loaded-SHA and post-merge restart evidence requirements. | design | S |
| T9 | F9 | Ratify green-only versus fingerprinted grandfather-baseline policy. | design | S |

Nothing was auto-enqueued: under D-046, the owner files or authorizes these
actions.

## Open design questions

- Is port 8700 intended to be host-only, LAN-visible, or Tailscale-visible?
- Is a `coordinator_propose` item consumed after one successful iteration,
  after evidence advancement, or only after explicit human dismissal?
- Does D-061 permit an automatic cooldown after repeated vendor timeouts?
- Must a runtime-changing merge block until loaded SHA equals repository SHA?
- Are the 12 test failures temporary blockers or an explicitly grandfathered
  baseline?

## Verification tally

Primary-side checks passed independently:

- HEAD identity: `56c1b3abae968c8288471b30946000c29ae6f228`.
- All cited source anchors exist at that tree.
- Bubble counts: 881 cycles; 161 errored; 161 still marked executed; 161 with
  persistence references; 161 off-enum persisted rows.
- Topic counts: one agenda run plus 61 `coordinator_propose` repeats.
- Frontier window: 51 Codex rows; 33 timeout-like rows; 5,940,919 timeout ms;
  7,323,141 total ms.
- Cycles ledger: 881 rows and 1,217,316 bytes at verification time.
- Execute-mode/paced-refusal log pairs showing `dry_run=True` were present.

No finding was killed after refutation. F2, F3, F5, F6, and F8 were narrowed
or numerically corrected. Authentication, lifecycle, and frontier reliability
remain thin lanes, and the missing two-dry-round miss-hunt is the principal
coverage limitation.
