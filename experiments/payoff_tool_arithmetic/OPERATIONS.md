# Native payoff-tool diagnostic: later execution

The prepared `qfn-followon-payoff-tool-20260915-a` window is **closed unissued**. Its `not-issued.json` records the coordinator lock refusal, zero model calls, no resident mutation, and no quality result. Keep its plan, window, public prestart witness, and closure receipt unchanged. Preparation refuses an existing output directory, and supervision refuses an existing reservation. The frozen supervisor predates the closure receipt and does not inspect `not-issued.json`, so operators must not pass this closed ID to `--run`. No automatic job is installed for this study.

Local model research is already authorized. A later evaluation needs a **new registered window ID**, a fresh preparation from the exact registered worktree, and a new public prestart witness before the first model request. The frozen source bundle includes the controller, runner, preregistration, calibration, transport, and resident lifecycle dependencies; changing any bound byte requires a new versioned plan/window, not a patch to the old one.

Use the registered worktree `/home/decross1/projects/a_bgt_rsi_worktrees/lab-payoff-tool-20260915` and canonical interpreter `/home/decross1/projects/a_bgt_rsi/.venv-chroma/bin/python`. Example ID `qfn-followon-payoff-tool-20260916-b` satisfies the controller's registered pattern. Replace it with the actual unique ID in the next window receipt. From that worktree, the commands are:

```bash
set -euo pipefail
cd /home/decross1/projects/a_bgt_rsi_worktrees/lab-payoff-tool-20260915
STUDY_ID=qfn-followon-payoff-tool-20260916-b
STUDY_PYTHON=/home/decross1/projects/a_bgt_rsi/.venv-chroma/bin/python
STUDY_OUTPUT=/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/lab-eight-hour/payoff-tool-study/$STUDY_ID
$STUDY_PYTHON -m bench.payoff_tool_study.controller --prepare --window-id "$STUDY_ID"
sha256sum "$STUDY_OUTPUT/plan.json" "$STUDY_OUTPUT/window.json"
git rev-parse HEAD
```

Prepare creates the private 0700 output child and freezes exact plan/window/source and resident-certificate hashes; it does not call a model. Publish a **new**, append-only public prestart witness that binds that ID, plan/window raw hashes, exact source commit, and a newly calculated latest-safe-start time. Commit the witness before `--run`, as with the earlier public witness; do not reuse its hashes or 23:25 cutoff. Check that the committed witness still matches the private bytes immediately before launch.

The nominal parent wall is 1,500 seconds, with a separate 300-second emergency recovery path. Allow additional process-cleanup and interruption-recovery slack in the explicit margin; 1,800 seconds is the ordinary budget sum, not a universal upper bound for every interrupted supervisor path. Set the new launch cutoff from its registered end time: `end - 1,800 seconds - explicit preflight/publication/validation margin`. For example, an end of 2026-09-16 00:09:45 UTC gives **23:39:45 UTC before any margin**; a safe recorded cutoff must be earlier. The worker's unchanged 600-second exact-restoration reserve is inside its supervised lifecycle, not an extra quality budget. The evaluator itself has a 600-second cap and eighteen declared slots, with conditional tool-final skips retained.

Just before launch, use the existing resource lease and `resource_probe(..., idle=True)` for an idle resident pair, adequate memory, unchanged container identities, and absent pause/active-run controls. If `.coordinator-cron.lock`, either weekly lock, or an endpoint request is busy **before supervisor reservation**, wait and recheck while this new window remains before its recorded cutoff; do not interrupt the coordinator. If the cutoff expires, close the window with a typed no-call receipt and prepare a different ID later. The worker rechecks under its own lease. The existing shared `resource_probe` requires **30 GiB available memory at admission**; the resident safety monitor enforces a **20 GiB floor** during the window. Neither threshold is relaxed here. Host swap/page-out is recorded as a resident diagnostic, not a standalone quality grade or automatic host-swap treatment.

The bounded idle/lease probe is:

```bash
$STUDY_PYTHON - <<'PY'
from pathlib import Path
from orchestrator.weekly_upgrade_trial import canonical_root, resource_lease, resource_probe

root = canonical_root(Path.cwd())
with resource_lease(root):
    print(resource_probe(root, idle=True))
PY
```

This probe reads resident queue metrics and registered container identities; the worker performs its own lease check again, so a later competing cycle still causes a visible refusal. When the new witness, lease, idle probe, and clock gate all pass, run and independently validate the new window in the **same shell** as the variable declarations:

```bash
set -euo pipefail
$STUDY_PYTHON -m bench.payoff_tool_study.controller --run --window "$STUDY_OUTPUT/window.json"
STUDY_ADMISSION_TEMP=$(mktemp "$STUDY_OUTPUT/.admission-XXXXXX")
if $STUDY_PYTHON -m bench.payoff_tool_study.controller --validate --window "$STUDY_OUTPUT/window.json" > "$STUDY_ADMISSION_TEMP"; then
  ln -T "$STUDY_ADMISSION_TEMP" "$STUDY_OUTPUT/admission.json"
  rm "$STUDY_ADMISSION_TEMP"
else
  rm -f "$STUDY_ADMISSION_TEMP"
  exit 1
fi
sha256sum "$STUDY_OUTPUT/admission.json"
```

`--run` owns the resident quiescence, bounded evaluation, and exact restoration. It returns nonzero for partial or aborted work. `--validate` is read-only and must pass the terminal window/restoration gate plus raw SSE and grade replay before any numeric result is displayed. Publish only the admitted content-free counts and their exact plan/run/admission hashes under a **new** public child; keep request text and raw streams private. Never overwrite a private receipt or public witness, and never convert a closed no-call or partial window into a completed score.

This protocol tests native parsed calculator invocation and exact payoff arithmetic. It does not itself test game strategy, trading execution, or model replacement.
