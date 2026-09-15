# Follow-on window commands

Run these from `/home/decross1/projects/a_bgt_rsi_worktrees/flash-followon-20260915` with `.venv-chroma/bin/python`. The original 126-cell pair and its registered checkout stay unchanged. Source preparation makes no model calls; `--plan` checks the frozen supervisor inputs without launching services. `--run` starts the monitored window and restores the prior services. Each cohort needs its own distinct window receipt.

For the first admitted C0 Mia and resident diagnostic windows, choose one unused ID and an ordered context prefix. This example includes 2K and 8K; append `,16384` only if the controller deadline is still sufficient. Flash runs thinking seed 71, fresh market seed 107, MTP0 controls, decode diagnostic, then context. The resident arm runs matched thinking and market, then context.

```bash
cd /home/decross1/projects/a_bgt_rsi_worktrees/flash-followon-20260915
FOLLOWON_ID=qfn-followon-c0-pilot-20260915-a
RESEARCH=/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/qwen-flash-next-research/evaluation
.venv-chroma/bin/python -m bench.flash_next_ab.followon_prepare --window-id "$FOLLOWON_ID" --cohort flash --context-bands 2048,8192
.venv-chroma/bin/python -m bench.flash_next_ab.followon_prepare --window-id "$FOLLOWON_ID" --cohort resident --context-bands 2048,8192
.venv-chroma/bin/python -m bench.flash_next_ab.extended_lifecycle --plan --eval-plan "$RESEARCH/followon-window-plans/$FOLLOWON_ID.flash.json" --output-dir "$RESEARCH/followon-runs/$FOLLOWON_ID.flash"
.venv-chroma/bin/python -m bench.flash_next_ab.resident_evaluation_window --plan --eval-plan "$RESEARCH/followon-window-plans/$FOLLOWON_ID.resident.json" --output-dir "$RESEARCH/followon-runs/$FOLLOWON_ID.resident"
```

After both read-only plans pass, run each cohort separately through its supervisor:

```bash
.venv-chroma/bin/python -m bench.flash_next_ab.resident_evaluation_window --run --eval-plan "$RESEARCH/followon-window-plans/$FOLLOWON_ID.resident.json" --output-dir "$RESEARCH/followon-runs/$FOLLOWON_ID.resident"
.venv-chroma/bin/python -m bench.flash_next_ab.extended_lifecycle --run --eval-plan "$RESEARCH/followon-window-plans/$FOLLOWON_ID.flash.json" --output-dir "$RESEARCH/followon-runs/$FOLLOWON_ID.flash"
```

A completed diagnostic window requires exact final restoration and terminal admission; individual task timeouts remain measured failures in its denominator. This C0 diagnostic does not establish a selected v5 profile or a production promotion.

A reduced optimized MTP3 or native 69,632 profile must first pass its own v5 qualification and terminal canary gate. The parent publisher refuses any unadmitted qualification and never replaces an existing source:

```bash
V5_RUN=qfn-mia-mtp3-red47k-example
.venv-chroma/bin/python -m bench.flash_next_ab.followon_v5_parent --qualification-run "$V5_RUN"
V5_PARENT=/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/qwen-flash-next-research/evaluation/followon-qualified-parents/$V5_RUN.json
REPAIR_ID=qfn-followon-selected-repair-20260915-a
.venv-chroma/bin/python -m bench.flash_next_ab.followon_repair_prepare --window-id "$REPAIR_ID" --cohort flash --v5-parent "$V5_PARENT"
.venv-chroma/bin/python -m bench.flash_next_ab.followon_repair_prepare --window-id "$REPAIR_ID" --cohort resident --v5-parent "$V5_PARENT"
.venv-chroma/bin/python -m bench.flash_next_ab.extended_lifecycle --plan --eval-plan "$RESEARCH/followon-window-plans/$REPAIR_ID.flash.json" --output-dir "$RESEARCH/followon-runs/$REPAIR_ID.flash"
.venv-chroma/bin/python -m bench.flash_next_ab.resident_evaluation_window --plan --eval-plan "$RESEARCH/followon-window-plans/$REPAIR_ID.resident.json" --output-dir "$RESEARCH/followon-runs/$REPAIR_ID.resident"
```

After both plans pass, supervise the resident and then Flash repairs separately with the same commands and `--run` in place of `--plan`.

The selected repair source freezes 22 original topic, historical, and portfolio coding tasks for native Gemma and 44 explicit Flash off/medium controls from those same tasks. Medium is exploratory and model-native sampling differs; report these comparisons accordingly. The native long-context form is separate and Flash-only, requiring a passed literal 69,632-token v5 parent:

```bash
NATIVE_ID=qfn-followon-native-context-20260915-a
.venv-chroma/bin/python -m bench.flash_next_ab.followon_repair_prepare --kind native_context --window-id "$NATIVE_ID" --cohort flash --v5-parent "$V5_PARENT"
.venv-chroma/bin/python -m bench.flash_next_ab.extended_lifecycle --plan --eval-plan "$RESEARCH/followon-window-plans/$NATIVE_ID.flash.json" --output-dir "$RESEARCH/followon-runs/$NATIVE_ID.flash"
```

After plan admission, the native window uses the same Flash supervisor command with `--run` in place of `--plan`.

The native form measures 12 supported source packets at 32K and 12 at 64K inside a distinct supervised window. A server flag or qualification canary alone does not count as task quality evidence.
