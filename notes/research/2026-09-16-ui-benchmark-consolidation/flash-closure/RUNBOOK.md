# Flash diversity-cap closure runbook

Status: prepared and unissued. The only prepared file in the new private window is `window.json`. Do not launch before 04:15 UTC, before the H1 due observation and coordinator/resource review are clear, or without the root coordinator assigning the model window.

The immutable inputs are:

- source root: `/home/decross1/projects/a_bgt_rsi_worktrees/lab-diversity-cap-20260915` at `e77a89257efaa6933efee8b4a50ca7241f7d853e`
- interpreter: `/home/decross1/projects/a_bgt_rsi/.venv-chroma/bin/python`
- plan: `/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/lab-eight-hour/mia-diversity-cap-paired-v1.plan.json`, SHA-256 `f1250b9c1965f9be99790153f63263c4240ed88aca44fc535abb7d8130c90f45`
- new window: `/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/lab-eight-hour/model-windows/qfn-ab-lab-diversity-cap-closure-20260916-b.flash/window.json`, SHA-256 `cb2e98c4c70d9017cc9a15997f6f687d1ed3b74479879dd127bc7dc763b2cc98`
- controller source-bundle SHA-256: `7d4cfb46cc44f6c6caaa0acdf5841c4c3e97c574913541a8c53b7b3b78d01ef4`

The normal supervisor wall is 4,500 seconds. Its worker reserves the final 600 seconds for restoration. A separate emergency restoration can use another 600 seconds, making the approximate operational worst case 5,100 seconds. The latest safe start is 09:56 UTC, preserving twenty minutes for replay and reporting before the 11:41 UTC closure deadline. If the run has not started by 09:56, close it as unissued.

Immediately before launch, verify the exact prepared bytes, source, clock, resident idle state, and resource lease. This probe is read-only and releases the lease; the worker repeats it under its own lease.

```bash
set -euo pipefail
cd /home/decross1/projects/a_bgt_rsi_worktrees/lab-diversity-cap-20260915
STUDY_PYTHON=/home/decross1/projects/a_bgt_rsi/.venv-chroma/bin/python
STUDY_PLAN=/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/lab-eight-hour/mia-diversity-cap-paired-v1.plan.json
STUDY_WINDOW=/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/lab-eight-hour/model-windows/qfn-ab-lab-diversity-cap-closure-20260916-b.flash/window.json
test "$(date -u +%s)" -ge "$(date -u -d '2026-09-16 04:15:00 UTC' +%s)"
test "$(date -u +%s)" -lt "$(date -u -d '2026-09-16 09:56:00 UTC' +%s)"
test "$(sha256sum "$STUDY_PLAN" | cut -d' ' -f1)" = f1250b9c1965f9be99790153f63263c4240ed88aca44fc535abb7d8130c90f45
test "$(sha256sum "$STUDY_WINDOW" | cut -d' ' -f1)" = cb2e98c4c70d9017cc9a15997f6f687d1ed3b74479879dd127bc7dc763b2cc98
test "$(git rev-parse HEAD)" = e77a89257efaa6933efee8b4a50ca7241f7d853e
git diff --quiet -- . ':!AGENTS.md' ':!.codex' ':!.venv-chroma'
test "$(find "$(dirname "$STUDY_WINDOW")" -maxdepth 1 -type f -printf '%f\n')" = window.json
$STUDY_PYTHON - <<'PY'
from pathlib import Path
from bench.flash_next_ab.lab_window import load_window
from orchestrator.weekly_upgrade_trial import canonical_root, resource_lease, resource_probe

window = Path('/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/lab-eight-hour/model-windows/qfn-ab-lab-diversity-cap-closure-20260916-b.flash/window.json')
document, parent = load_window(window)
assert document['window_id'] == 'qfn-ab-lab-diversity-cap-closure-20260916-b'
assert document['runtime_budget_s'] == 2200
assert document['wall_s'] == 4500
assert parent.spec.spec_id == 'mia-925d7be6-mtp3-reduced47k-v2opt-v1'
root = canonical_root(Path('/home/decross1/projects/a_bgt_rsi'))
with resource_lease(root):
    probe = resource_probe(root, idle=True)
assert probe['mem_available_gib'] >= 30
print(probe)
PY
```

After the root coordinator confirms the lease window, launch exactly once:

```bash
set -euo pipefail
cd /home/decross1/projects/a_bgt_rsi_worktrees/lab-diversity-cap-20260915
STUDY_PYTHON=/home/decross1/projects/a_bgt_rsi/.venv-chroma/bin/python
STUDY_WINDOW=/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/lab-eight-hour/model-windows/qfn-ab-lab-diversity-cap-closure-20260916-b.flash/window.json
$STUDY_PYTHON -m bench.flash_next_ab.lab_window --run --window "$STUDY_WINDOW"
```

The command returns zero only for a completed evaluator and verified restoration. It returns nonzero for every abort or partial result. Do not repeat it: `supervision-reservation.json` makes this window single-use.

For a zero exit, publish the independent content-free replay once. This replays all 40 private streams, grades, controller closure, cgroup/no-swap evidence, exact restoration, and supervisor status before releasing counts.

```bash
set -euo pipefail
cd /home/decross1/projects/a_bgt_rsi_worktrees/lab-diversity-cap-20260915
STUDY_PYTHON=/home/decross1/projects/a_bgt_rsi/.venv-chroma/bin/python
STUDY_WINDOW=/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/lab-eight-hour/model-windows/qfn-ab-lab-diversity-cap-closure-20260916-b.flash/window.json
STUDY_PUBLIC=/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/lab-eight-hour/mia-diversity-cap-closure-20260916-b.public.json
test ! -e "$STUDY_PUBLIC"
$STUDY_PYTHON -m bench.flash_next_ab.lab_eval_diversity_cap --window "$STUDY_WINDOW" --publish-replay "$STUDY_PUBLIC"
sha256sum "$STUDY_PUBLIC"
```

For a nonzero exit, preserve every receipt and classify the attempt as aborted or invalid from the terminal controller evidence. Do not publish numeric quality counts, do not invoke `--run` again, and do not prepare a third cap attempt.

Startup can abort again even with the current idle baseline. The main paths are a busy canonical lease; an active pause/run or nonempty resident queue; less than 30 GiB available at admission; candidate name or port collision; source, weight, image, runtime, or launch drift; failure to observe sixty seconds of zero pageout before mutation; Nara or resident quiescence failure; candidate cgroup identity, 96 GiB memory cap, zero-swap, OOM, restart, or process-liveness failure; host pageout reaching 512 MiB in five seconds, 2 GiB in sixty seconds, or 4 GiB total during startup; less than 20 GiB available under supervision; a load exceeding 1,500 seconds; failure to observe a fresh sixty-second zero-pageout interval after readiness; probe/canary failure; or a monitor sample gap over ten seconds. These checks remain unchanged. A successful independent replay is stricter during evaluation and requires zero host pageout in every evaluation sample.
