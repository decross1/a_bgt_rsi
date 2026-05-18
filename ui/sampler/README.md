# Sampler

Telemetry daemon for the orchestrator dashboard. Samples GPU, host,
vLLM, and per-process metrics once per second and appends one JSON
object per sample to `ui/logs/telemetry.jsonl`. See `ui_plan.md` §5.1.

It is **read-only** with respect to the apparatus: it observes
`nvidia-smi`, the vLLM `/metrics` endpoint, `psutil`, and
`/sys/class/thermal`, and writes only under `ui/`.

## Run

```sh
pip install -r ui/requirements-ui.txt
ui/sampler/run.sh                      # 1 Hz, default paths
ui/sampler/run.sh --interval 2         # other options below
```

`run.sh` just `exec`s the module. Restart-on-failure is the caller's
job — wrap it in systemd, supervisor, or `while true; do ...; done`.

Options (`python3 -m sampler.sampler --help`):

| Flag | Default | Notes |
|---|---|---|
| `--output` | `ui/logs/telemetry.jsonl` | output JSONL path |
| `--vllm-url` | `http://localhost:8000/metrics` | vLLM Prometheus endpoint |
| `--interval` | `1.0` | seconds between samples |
| `--max-samples` | (none) | stop after N samples; otherwise runs forever |

## Output

One line per sample, conforming to `ui/schema/telemetry.jsonl.schema.json`.
`gpu` / `host` / `vllm` are object-or-null — a source that fails to read
is written as `null` and the reason recorded in `read_errors`. The file
grows ~50–90 MB/day at 1 Hz; add rotation before long unattended runs.

## Tests

```sh
pytest ui/sampler/tests
```

- `test_schema.py` — runs the sampler briefly, asserts every line
  validates against the schema.
- `test_missing_sources.py` — with `nvidia-smi` absent and vLLM
  unreachable, asserts lines still validate with `read_errors` populated.

## Notes / known limitations

- Single-GPU assumption (the Spark's GB10); multi-GPU samples index 0.
- `nvidia-smi` reporting `[N/A]` for `power.draw` nulls the whole `gpu`
  object for that sample.
- Counter-derived fields (`tokens_per_sec_decode`, `mtp_*`) are `null`
  on the first sample and just after a vLLM restart (counter reset).
- vLLM `/metrics` field names drift between releases; the scraper
  matches candidate names — extend the lists in `sources/vllm_metrics.py`
  if a release renames a metric.
