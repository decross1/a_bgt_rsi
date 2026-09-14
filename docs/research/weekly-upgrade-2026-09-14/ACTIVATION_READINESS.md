# Weekly upgrade loop activation readiness

**Prepared:** 2026-09-14
**Current decision:** **NOT READY TO ACTIVATE**
**Deployment state:** No schedule, service, or model call was changed while preparing this artifact.

This is the owner runbook for activating the weekly upgrade loop after the
implementation has been reviewed, merged publicly, adopted into the canonical
private checkout, and validated there. Activation replaces one firing of the
existing weekly frontier agenda with one bounded two-provider review. It does
not create another cron job and cannot promote a model, runtime, policy, or
code change.

## Actual owner and runtime state

- The existing crontab owner is `30 5 * * 0`, Sunday at 05:30 UTC, and invokes
  `/home/decross1/projects/a_bgt_rsi/cron/weekly-frontier-agenda.sh`.
- The script owns `run_state/.frontier-agenda-cron.lock`. The weekly cycle
  inherits and validates that same locked file descriptor.
- `NARA_WEEKLY_UPGRADE` is currently absent, so the new branch is **off**.
  With the flag absent or `0`, the existing frontier agenda behavior runs.
- With `NARA_WEEKLY_UPGRADE=1`, the firing runs the weekly cycle **instead of**
  the legacy agenda. It does not add agenda calls to the cycle's two frontier
  review attempts.
- `nara-daemon.service` is a **user** service. It is active with PID `818128`
  and has been loaded since 2026-09-02. It therefore does not yet cooperate
  with code added after that start. Any eventual reload must use
  `systemctl --user`; a system/global unit is not the owner.

## Activation prerequisites

Keep the loop off until every item has a recorded artifact or exact Git SHA:

1. The implementation branch passes its focused and full repository checks.
2. The public PR is merged and its exact `origin/main` SHA is recorded here.
3. The public merge is safely adopted into canonical private `main`, preserving
   private history and unrelated tracked/untracked session work; record the
   local-only adoption SHA here.
4. `orchestrator.weekly_upgrade_cycle --check` passes from the canonical
   checkout using the intended output root and source-fetch configuration.
5. One authorized manual review cycle is complete or has a terminal,
   non-replayable failure receipt. If a trial is selected, its fixed manifest,
   trial journal, budget receipt, and evaluation receipt must all bind.
6. The owner reviews the current 120-minute weekly Spark ledger and confirms
   that no same-week reservation is active or missing from the canonical
   journal.
7. The active user daemon is restarted only after the adopted code is ready,
   then its readiness/health evidence is recorded.

Evidence to fill after the parent session completes integration:

```text
public_merge_sha: PENDING
canonical_adoption_sha: PENDING
full_test_result: PENDING
manual_cycle_result: PENDING
canonical_readiness_result: PENDING
nara_user_service_reload: PENDING OWNER ACTION
```

## Read-only canonical readiness check

This validates Git state, the ToS sentinel, pause controls, subscription CLI
authentication, exact source configuration, output isolation, budgets, week
boundary, and any existing canonical week claim. It performs no frontier model
request, source fetch, or local GPU trial.

```bash
cd /home/decross1/projects/a_bgt_rsi
env -u MOCK_LLM \
  FRONTIER_CODEX_MODEL=gpt-6-astra \
  FRONTIER_CODEX_EFFORT=xhigh \
  FRONTIER_CLAUDE_MODEL=claude-opus-5 \
  .venv-chroma/bin/python -m orchestrator.weekly_upgrade_cycle \
    --check \
    --repo-root /home/decross1/projects/a_bgt_rsi \
    --output-root /home/decross1/projects/a_bgt_rsi_weekly_upgrade_runs \
    --fetch-config bench/weekly_upgrade_eval/sources.json \
    --frontier-call-budget 2 \
    --review-deadline-s 600 \
    --call-timeout-s 300 \
    --cycle-deadline-s 3300 \
    --fetch-deadline-s 60 \
    --max-gpu-minutes 120
```

The requested model names are explicit pins for this activation record. The
cycle also records actual model IDs from provider receipts; it does not claim
that an alias is the latest model.

## One authorized manual review cycle

Run this only after the readiness check passes. GNU `timeout` is the independent
wall-clock backstop; the Python controller converts `TERM` into cleanup so its
detached subscription CLI process group is reaped.

```bash
cd /home/decross1/projects/a_bgt_rsi
env -u MOCK_LLM \
  FRONTIER_CODEX_MODEL=gpt-6-astra \
  FRONTIER_CODEX_EFFORT=xhigh \
  FRONTIER_CLAUDE_MODEL=claude-opus-5 \
  timeout --signal=TERM --kill-after=10s 3320s \
  .venv-chroma/bin/python -m orchestrator.weekly_upgrade_cycle \
    --run \
    --repo-root /home/decross1/projects/a_bgt_rsi \
    --output-root /home/decross1/projects/a_bgt_rsi_weekly_upgrade_runs \
    --fetch-config bench/weekly_upgrade_eval/sources.json \
    --frontier-call-budget 2 \
    --review-deadline-s 600 \
    --call-timeout-s 300 \
    --cycle-deadline-s 3300 \
    --fetch-deadline-s 60 \
    --max-gpu-minutes 120
```

This is review-only unless an exact registered `--trial-manifest` is added. A
`CONTINUE_TRIAL` review without that option terminates as
`AWAITING_TRIAL_ACTIVATION` and consumes no Spark trial budget.

## Scheduled activation choices

Use `crontab -e` and replace the existing Sunday line. Do not add a second
line. The first activation should use review-only mode:

```cron
30 5 * * 0 NARA_WEEKLY_UPGRADE=1 FRONTIER_CODEX_MODEL=gpt-6-astra FRONTIER_CODEX_EFFORT=xhigh FRONTIER_CLAUDE_MODEL=claude-opus-5 /home/decross1/projects/a_bgt_rsi/cron/weekly-frontier-agenda.sh
```

For a reviewed fixed-manifest lane, replace that same line with one that adds
the exact registered manifest:

```cron
30 5 * * 0 NARA_WEEKLY_UPGRADE=1 NARA_WEEKLY_UPGRADE_TRIAL_MANIFEST=experiments/weekly_upgrade_game_science_dev_v0_2026-09-14.json FRONTIER_CODEX_MODEL=gpt-6-astra FRONTIER_CODEX_EFFORT=xhigh FRONTIER_CLAUDE_MODEL=claude-opus-5 /home/decross1/projects/a_bgt_rsi/cron/weekly-frontier-agenda.sh
```

That value is a persistent **allowlist**, not a one-time execution approval.
Each ISO week still requires fresh source evidence, a new immutable two-provider
review, `CONTINUE_TRIAL`, and an experiment card matching the registered
manifest, hash, full fixture set, seeds, and budget. Because trial IDs include
the ISO week, the same fixed manifest may be evaluated again in a later week.
Use review-only mode if repeated cross-week evaluation is not intended.

The cron path fixes these limits:

- exactly two subscription frontier attempts for the weekly review;
- no API-key or paid-provider fallback;
- at most 120 Spark GPU-minutes per UTC ISO week across canonical trial
  reservations;
- 300 seconds per frontier call, 600 seconds for review, 60 seconds for source
  refresh, 3,300 seconds internal cycle deadline, and a 3,320-second outer
  backstop;
- no automatic production promotion.

## User-service reload after canonical adoption

Inspect the actual user unit immediately before the owner action:

```bash
systemctl --user show nara-daemon.service \
  -p ActiveState -p SubState -p MainPID -p ExecMainStartTimestamp
```

After the owner approves activation and the canonical checkout contains the
adopted code, reload only the user-owned service:

```bash
systemctl --user restart nara-daemon.service
systemctl --user is-active nara-daemon.service
systemctl --user show nara-daemon.service \
  -p ActiveState -p SubState -p MainPID -p ExecMainStartTimestamp
journalctl --user -u nara-daemon.service --since "10 minutes ago" --no-pager
```

Do not use `sudo systemctl`, `systemctl` without `--user`, or start a second
daemon. A failed restart is a deployment failure: keep the weekly hook off and
restore the prior user-service state before considering cron activation.

## Stop, pause, and recovery

The pause files are checked before work; active subscription calls also poll
the relevant pause controls and kill their owned process group when stopped.

```bash
# Stop the weekly upgrade branch while retaining the legacy agenda when disabled.
touch /home/decross1/projects/a_bgt_rsi/run_state/pause_weekly_upgrade

# Stop all frontier maintenance at the existing cron gate.
touch /home/decross1/projects/a_bgt_rsi/run_state/pause_frontier

# Prevent an admitted local-GPU trial from starting or continuing.
touch /home/decross1/projects/a_bgt_rsi/run_state/pause_coordinator
```

The owner may remove a pause only after inspecting the terminal receipts and
confirming that no matching CLI or trial process remains:

```bash
rm /home/decross1/projects/a_bgt_rsi/run_state/pause_weekly_upgrade
rm /home/decross1/projects/a_bgt_rsi/run_state/pause_frontier
rm /home/decross1/projects/a_bgt_rsi/run_state/pause_coordinator
```

Recovery rules are intentionally conservative:

- Re-run with the same output root and unchanged plan. A canonical ISO-week
  claim rejects a second output root, preventing duplicate review calls.
- A reserved frontier call without a validated response is never repeated.
- A reserved source fetch without durable evidence is never automatically
  repeated. Existing hash-bound evidence can finish its receipt without a new
  fetch.
- A trial resumes only through its canonical journal, exact output binding,
  process identity checks, shared resource locks, and budget ledger. An
  uncertain interrupted trial is fully charged and never replayed.
- Never delete or edit cycle claims, reservation receipts, trial journals, or
  the budget ledger to force a retry. Record the failure and wait for a newly
  preregistered next-week run or repair the controller under review.

## Rollback

To return the scheduled owner to its prior behavior, replace the cron line with
the exact original line (remove the environment prefix; do not add another
entry):

```cron
30 5 * * 0 /home/decross1/projects/a_bgt_rsi/cron/weekly-frontier-agenda.sh
```

Pausing is faster and preserves evidence. Code rollback must use the recorded
public merge and canonical adoption SHAs, preserve private history, and must
not rewrite canonical `main`.

## Owner decision

Activation should be approved only after the pending evidence block at the top
is filled with exact results and the final diff is reviewable. The recommended
first scheduled state is review-only. A persistent fixed-manifest allowlist is
appropriate only after its manual execution and receipt chain have passed.
