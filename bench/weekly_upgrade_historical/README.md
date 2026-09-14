# Public-historical repair panel

This runner measures six bounded repairs at authentic public repository failure
seams. It is a first descriptive baseline, not an A/B comparison. Because the
tasks and their historical fixes are public, the result is explicitly
`public_historical` and `contamination_resistant=false`.

The candidate sees only a scrubbed behavior contract and the exact base version
of one Python file. The original `weekly-upgrade-historical-repair/v2` contract
requires one JSON object containing a unified diff for that registered path.
The versioned `weekly-upgrade-historical-repair-patch-wire/v1` follow-up keeps
the same tasks, model policy, sandbox, graders, and budgets but requires the
completion itself to be one raw unified diff. Neither contract strips, repairs,
or extracts a candidate response. The runner exports a small source allowlist
from the base commit after generation, applies the patch with a one-file
boundary, installs a grader that was never included in the model packet, and
runs that grader inside a content-addressed bubblewrap sandbox with no network
or GPU visibility.

“Hidden” here means hidden from the model request. Generated Python and the
read-only grader later share a sandbox filesystem, so this is not a
cryptographic hidden-code boundary against a deliberately hostile program. A
separate trusted supervisor receives pytest hook reports over a private pipe;
the score ignores candidate stdout and requires the terminal hook receipt.
Printing a fake pytest summary or exiting early therefore cannot earn credit.

Planning is read-only:

```bash
.venv-chroma/bin/python -m bench.weekly_upgrade_historical.runner \
  --plan \
  --manifest experiments/weekly_historical_coding_panel_v2_2026-09-14.json
```

Plan the raw-patch follow-up with:

```bash
.venv-chroma/bin/python -m bench.weekly_upgrade_historical.runner \
  --plan \
  --manifest experiments/weekly_historical_coding_patch_wire_v1_2026-09-14.json
```

The weekly controller owns live execution. Its registered command contract is:

```bash
python -m bench.weekly_upgrade_historical.runner \
  --run --manifest MANIFEST --output-dir FRESH_OUTPUT \
  --runtime-budget-s 1020
```

The output is a closed evidence graph: `manifest.snapshot.json`, `run.json`,
`raw_attempts.jsonl`, `outcomes.jsonl`, `calls.jsonl`, and
`worker_activity.jsonl`. The last two come from the shared wrapper. Raw model
text stays in the private run artifact and is never projected by the progress
API; scored outcomes contain hashes, bounded counts, and status codes only.
