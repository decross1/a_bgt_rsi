# Weekly upgrade evaluation canary

This package runs a small, paired A/B canary for inference-policy changes. It
is an evidence instrument, not a production controller or promotion gate.

The bundled manifest contains twelve objective task templates:

- three exact game-theory calculations;
- four critic classifications, balanced between `fatal_flaw` and `proceed`;
- three closed-packet evidence-attribution tasks; and
- two semantic tool-use tasks backed by deterministic in-process tools.

The panel deliberately does not score scientific novelty, broad research
quality, or coding-agent performance. A seeded variation of one prompt is not
treated as an independent task template.

The bundled Qwen arms use a deliberately tight 384-token cap. This makes
liveness and empty-at-cap behavior visible; it also means the bundled result
must not be represented as a model-quality sweep. A larger preregistered study
needs a separately justified generation budget.

Each arm may freeze a signed 64-bit `seed`. The bundled control and candidate
both use `0`. Older manifests without the field remain valid and leave the
wrapper seed unset; a JSON `null` does the same.

Inspect the complete frozen plan without model calls or writes:

```bash
python3 -m bench.weekly_upgrade_eval.runner \
  --plan \
  --manifest bench/weekly_upgrade_eval/fixtures.json
```

For a real local-server run, copy and preregister the manifest first. Then use
a new artifact directory and an explicit whole-run budget:

```bash
env -u MOCK_LLM python3 -m bench.weekly_upgrade_eval.runner \
  --run \
  --manifest /path/to/preregistered-manifest.json \
  --output-dir /path/to/new-run-directory \
  --runtime-budget-s 1800
```

The run command refuses when `MOCK_LLM` is set, when the output directory
already exists, or when the output is under the repository's live `logs/`,
`memory/`, or `run_state/` trees. The wrapper and worker-activity logs are
redirected into the requested output directory. The harness never starts or
stops services, changes a role, writes a decision, or promotes an arm.

Every request gets the smaller of the arm's request timeout and the remaining
monotonic whole-run budget. There are no retries. A timeout, transport error,
or budget-skipped cell remains a failed planned outcome and makes the run
incomplete. The final `run.json` includes:

- the manifest, run-configuration, task-input, task-grader, and harness hashes;
- the exact alternating `AB/BA` execution order;
- resolved model/runtime provenance from wrapper records;
- every planned arm/task cell, including unrun and failed cells;
- failure-inclusive pass rates and correct-task throughput; and
- paired descriptive bootstrap intervals and a descriptive sign test.

The bootstrap resamples whole task templates. Its interval is not a confidence
claim about a broader task population, and no statistic in the artifact is an
automatic promotion threshold.
