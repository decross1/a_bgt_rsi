# Flash-Next paired research evaluation

Compare the existing Gemma/Qwen role bundle with one qualified Flash-Next
checkpoint serving all seven local roles. This is a comparison of deployable
systems: model, quantization, runtime, native sampling and speculation settings
are recorded. A difference is not automatically attributable to weights alone.
Production promotion is not part of this runner.

The first admitted candidate is Mia C0-MIA-S1, run
`qfn-mia-c0-20260915-0602`; see the
[qualification runbook](FLASH_NEXT_QUALIFICATION_RUNBOOK.md). NVIDIA remains a
separate candidate whose previous recorder-failed attempt is not admissible.

## Frozen portfolio

| Family | Task/condition/repetition cells per cohort |
| --- | ---: |
| Objective protocol and reasoning fixtures | 24 |
| Game-theory topic scope | 48 |
| Context evidence | 4 |
| Research portfolio | 16 |
| Diversity and selection | 10 |
| Role-specific reasoning effort | 18 |
| Historical repository repairs | 6 |
| Total | 126 |

The full matrix permits up to 145 model calls and 10,430 seconds per cohort.
Historical repairs execute in disposable, restricted environments. These are
public development fixtures, not hidden scientific discovery ground truth.
The dedicated 2K/8K/16K/32K/64K placement and thinking sweeps are separate
follow-on experiments; four context cells do not establish 64K capability.

## Register before either cohort

Create a new pair ID under `qfn-ab-*`. Use `manifest.make_arm_receipt` to bind
all resident roles to their qualified models and every Flash role to
`flash_next_mia` with the successful Mia receipt's artifact/runtime hashes.
`manifest.build_plan` creates the full matrix. Require exactly 126 cells.
`declared_cells` controls task order; JSON object member order is irrelevant.

Save immutable files below the research artifact root's
`evaluation/window-plans/`:

- `<pair>.benchmark.json`: full paired plan and source/adapter fingerprints;
- `<pair>.resident.window.json`: resident qualification and artifact references;
- `<pair>.flash.window.json`: exact Mia result, plan, raw contract and snapshot references.

Each window records raw file hashes, a 14,400-second invocation ceiling,
600 seconds reserved for restoration, the 10,430-second model-work allowance,
a 20 GiB host reserve, and uncapped local-research accounting. Use a fresh pair
ID for changed plans. Never modify a completed or failed attempt in place.

The lifecycle plans also bind the code-owned launcher and source bundle.
Freeze those source files through both cohorts. Preserve the executed source
revision and admission receipt for historical replay; a later checkout's
inability to replay an old source bundle is not a failed model result.

## Execute sequentially

From the registered Flash worktree, first run each controller with `--plan`
and inspect its exact source, model, output, budget and recovery bindings.
The following commands show the registered locations; set `flash_pair` to the
new, already prepared pair ID before use.

```bash
flash_pair=qfn-ab-mia-c0-20260915-a
flash_artifacts=/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/qwen-flash-next-research

env -u MOCK_LLM -u OPENAI_API_KEY -u ANTHROPIC_API_KEY \
  .venv-chroma/bin/python -m bench.flash_next_ab.resident_evaluation_window \
  --plan --eval-plan "$flash_artifacts/evaluation/window-plans/$flash_pair.resident.window.json" \
  --output-dir "$flash_artifacts/evaluation/runs/$flash_pair.resident"

env -u MOCK_LLM -u OPENAI_API_KEY -u ANTHROPIC_API_KEY \
  .venv-chroma/bin/python -m bench.flash_next_ab.extended_lifecycle \
  --plan --eval-plan "$flash_artifacts/evaluation/window-plans/$flash_pair.flash.window.json" \
  --output-dir "$flash_artifacts/evaluation/runs/$flash_pair.flash"
```

After review, use `--run` in place of `--plan`, first for the resident cohort,
then for Flash after the resident supervisor has closed and restoration has
passed. Plan mode does not launch models. Do not overlap unrelated benchmarks,
model builds, downloads or source edits with either measurement window.

The resident controller keeps both original model containers running, pauses
Nara behind the resource lease and a stopped watchdog sentinel, and restores
Nara's captured activity afterward. It never stops or recreates the residents.

The Flash controller owns the entire swap: lease, source/model verification,
original-service capture, Nara pause, sequential resident stop, candidate boot,
fresh ready quiet interval and three exact probes, full task panel, then exact
original-service restoration and sentinel removal. Its parent supervises the
absolute deadline and recovery. Do not manually restart a model while that
controller is active.

## Long-window resource policy

The long cohort is a distinct preregistered profile, not a retrospective change
to any C0 qualification. It retains the 20 GiB available-memory floor, zero
candidate cgroup swap/OOM, exact identity/restart checks, one-second sampling,
and a ten-second maximum sampling gap. The fresh ready interval requires
60 seconds without host swap-out growth.

During the extended serving phase, host paging bursts abort at 512 MiB in
five seconds or 2 GiB in sixty seconds. Whole-cohort host pageout, page-in,
and PSI are diagnostics; the tiny three-probe C0 cumulative paging allowance
is not reused for a multi-hour cohort. An independent API-health/frontend
HTTP observer runs every five seconds with a two-second request timeout;
two failed ticks within thirty seconds abort the candidate window. Its failure
is operational evidence, not proof of a model capability or hardware-fit loss.

The owner's separate 12 GiB absolute-reserve option is not enabled by this
profile. The 120-minute weekly maintenance ledger remains unchanged; these
owner-authorized local R&D windows are recorded separately and make no paid
frontier API calls.

## Completion and comparison

A harness finishing its tasks is pending evidence until the supervisor exits
and exact restoration is verified. Both `validate_completed_resident_window`
and `validate_completed_flash_window` must pass before pairing/export. The
combined `validate_completed_pair` requires the same immutable benchmark plan.

Admission checks the actual produced files: all declared cells in order,
request/response provenance including private raw SSE, memory and identity
observations, supervisor identity/deadline, ordered usage records, and final
restoration. Task timeouts and errors remain attempted failures in the
performance denominator. A cancelled or unfinished cohort is incomplete and
must not be reported as a smaller successful evaluation.

Report success and reliable completion by family, correctness failures,
structured-output failures, timeouts, task wall-clock, tokens, calls and
retries. Separate server startup/restoration from warm task throughput, and
also report the full operational window cost. Do not export private responses
into the dashboard. A complete development-panel comparison is evidence for
further evaluation; retain uncertainty about hidden tasks, long contexts,
repeatability and real end-to-end research outcomes.
