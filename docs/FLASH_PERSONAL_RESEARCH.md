# Flash personal research session

The September 18 owner handoffs reopen Flash for interactive scientific and
programming work. The earlier closed benchmark windows and their grades are
unchanged. Passing every autonomous role is not a prerequisite for personal use.

The default runtime is the already qualified Mia optimized MTP3 / reduced
47,149-token draft vocabulary / V2 / FULL-decode bundle. It uses the existing
immutable image, weights and packed disk-backed PLE. A separate child image adds
the reviewed QSA FP8-KV implementation for a personal comparison. It has its own
specification, contract, container name and compile cache and remains
unqualified until a live run supplies evidence. Historical qualification is
prior evidence, not a new result for either precision change.

## Start and inspect

From the prepared checkout:

```bash
env -u MOCK_LLM .venv-chroma/bin/python -m bench.flash_next_ab.personal_session \
  --run --output-dir /home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-18/flash-personal-recovery/session-UNUSED \
  --hours 4 --floor 20 --initial-profile mtp3-fp32-auto
```

Use a fresh lowercase `session-*` directory. The supervisor retains the normal
resource locks, records the original resident IDs and Nara state, verifies model
files, pauses background callers and starts Flash. Do not run a second controller
against an occupied lease. `state.json` is an observation; verify the supervisor
PID/start identity and endpoint before interpreting a stale state as live work.

The first session is scheduled to finish before the next 03:00 UTC embedding
job. Longer sessions require coordinating that additional GPU caller too.

During a healthy warm session the OpenAI-compatible endpoint is
`http://127.0.0.1:8012/v1`, served name `qwen3.8-flash-next-mia`. The controller
does not change the lab's production routes. Nara and the resident pair remain
paused while this session owns memory. To access it from another computer, use
an SSH forward to this loopback port.

## Runtime and request changes

The controller's named arms are:

| Arm | Candidate image | MTP | Recurrent state | KV request | Decode graph width |
| --- | --- | --- | --- | --- | --- |
| `mtp3-fp32-auto` | qualified parent | 3 | FP32 | auto | 4 |
| `mtp0-fp32-auto` | qualified parent | 0 | FP32 | auto | 1 |
| `mtp3-bf16-auto` | qualified parent | 3 | BF16 | auto | 4 |
| `mtp3-bf16-child-auto` | QSA child | 3 | BF16 | auto | 4 |
| `mtp3-bf16-child-fp8` | QSA child | 3 | BF16 | FP8 | 4 |

The no-MTP graph width differs because a step produces one token instead of a
target token plus three draft tokens. Report that difference. Read startup logs
for the resolved KV precision. The qualified parent lacks the QSA FP8-KV path;
only the separately built child may receive `--kv-cache-dtype fp8`.

`--initial-profile` fixes one candidate specification for the entire session.
Profile commands may switch only among arms belonging to that same exact image;
they cannot hot-switch between parent and child. To compare auto and FP8 KV in
the child while holding BF16 recurrent state fixed, start a fresh second session:

```bash
env -u MOCK_LLM .venv-chroma/bin/python -m bench.flash_next_ab.personal_session \
  --run --output-dir /home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-18/flash-personal-recovery/session-fp8-UNUSED \
  --hours 4 --floor 20 --initial-profile mtp3-bf16-child-auto
```

After the child auto arm is ready and idle, switch within that session:

```json
{"id":"child-fp8-first","action":"profile","profile":"mtp3-bf16-child-fp8"}
```

The child specification is
`mia-925d7be6-mtp3-reduced47k-v2opt-fp8qsa-v1`, identity SHA-256
`f4b3efc23134878c1f8f29c8004c00b80c7d2f20b693840dd487808e61f671a4`,
and immutable image
`sha256:ba65a549de4dce8cab70f27c200e408b28470ea175fc8c301e27b4deb154fbed`.
It retains model path `/mnt/models/qwen3.8-flash-next-mia-925d7be6` and model
artifact SHA-256
`a40ce50173dd3aff54da88503894967e5248bbb927f9e4a91eff5a6a7270c168`.
Its dedicated compile cache is
`/home/decross1/projects/a_bgt_rsi_runtime_candidates/flash-next-20260914/compile-cache-mia-c0/qwen38-flash-next-mia-mtp3-reduced47k-fp8qsa-v1`.
The immutable launch contract is
`/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-18/flash-personal-recovery/fp8-runtime-build/launch-contract.mia-mtp3-reduced47k-fp8qsa.json`
(raw SHA-256
`8a6f5252ccf1f46ce68586ce04ee0a022a12566ede38b6532469ba5e52dc6e4f`).
The image build receipt at
`/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-18/flash-personal-recovery/fp8-runtime-build/build-receipt.json`
is 4,656 bytes with SHA-256
`3a75a795ec167885794a55de29e1a39e537fb0e953508ea9475cfce450e36ebc`.
The parent specification identity remains
`e71d3134f407cad3c288c21f9485c27352676dbb7de647c5b567777256702a50`.

Request policy changes do not restart the model. Use explicit thinking off for
simple extraction/tool turns and explicit medium effort for substantive tasks.
Give reasoning calls enough output capacity and time, while counting exhaustion,
repetition, parser errors and incorrect answers separately. Reasoning text alone
is not successful completion. Historical strict grades are never overwritten by
a new presentation adapter or practical coding harness.

The frozen personal panel intentionally omits `presence_penalty`.
[vLLM](https://docs.vllm.ai/en/stable/api/vllm/sampling_params/) therefore uses
`0.0`: this matches Qwen's thinking-mode recommendation, while the panel's
non-thinking arm is an experimental baseline rather than the
[Qwen recommendation](https://huggingface.co/Qwen/Qwen3.8-Flash-Next#api-usage)
of `1.5`. If direct-mode repetition appears, run `presence_penalty=1.5` as a
separately named request-policy diagnostic with matched tasks and seeds. Qwen
warns that higher values can cause language mixing and a small performance loss;
do not fold that diagnostic into already recorded primary arms.

Runtime changes use a fresh command ID in the session's `command.json`:

```json
{"id":"bf16-first","action":"profile","profile":"mtp3-bf16-auto"}
```

Write the JSON atomically, and wait for the new `ready` event. A busy candidate
refuses the switch; submit a new command ID after the current task completes.
The incumbent pair stays stopped across these serving changes.

## Resource policy and recovery

### Make a personal request

While the controller is ready, call the local endpoint with the supplied client:

```bash
env -u MOCK_LLM .venv-chroma/bin/python -m bench.flash_next_ab.personal_client \
  --policy medium --prompt-file /absolute/path/to/question.txt \
  --output-dir /absolute/path/to/a-new-answer-directory --print-final
```

Use `--policy off` for a short direct response. The output directory must be new
or empty. Completed answers print in the terminal; raw requests, streams,
separate reasoning/final channels, timing, usage and completion classifications
are saved alongside them. A timeout or unfinished response exits nonzero.
Input and output must fit the active 32K context; the medium policy allows up to
16K output, so reduce `--max-output-tokens` when sending a long paper. The CLI
checks the served model name but explicitly does not attest the active runtime
profile; evaluation runners additionally bind the controller and container.

This is an OpenAI-compatible local service; existing clients may use
`http://127.0.0.1:8012/v1` and model `qwen3.8-flash-next-mia`. Set thinking effort
explicitly rather than inheriting the checkpoint's `xhigh` default.

To expose this client's emitted stream in the Now dashboard, opt in with
`LOCAL_MODEL_TRACE_DIR=/home/decross1/projects/a_bgt_rsi/logs/model_traces` on
the client process. This requires the dashboard's `agent_wrapper.live_trace`
module. The observer writes private local snapshots at most twice per second;
it does not add fields to the model request or change grading. The UI separates
the prompt preview, emitted reasoning, tool arguments, final answer and terminal
status. It does not infer a trace for calls made by uninstrumented clients.
Keep tracing off for matched speed tests unless every arm uses it and the
measurement records that fact. The bounded UI view explicitly reports clipping;
the original raw SSE artifacts remain the complete diagnostic record.

### Resource limits

This new diagnostic allows at most 1,800 seconds per startup. The preferred
physical reserve remains 20 GiB; 12 GiB is only selectable as an explicit new
session declaration. Candidate cgroup swap and OOM remain hard failures, as do
unexpected exits/restarts, changed memory limits, sustained severe memory PSI,
driver/allocation errors and sustained unresponsiveness. The parent monitors
worker heartbeats and retains a separate restoration allowance.

Host pageout is recorded with host counters, process RSS/swap, candidate cgroup
file/anonymous memory, and memory/I/O PSI. A PLE file fault is not anonymous
swap-out. Host pageout alone does not identify a candidate OOM or a quality loss.
The controller does not disable swap, drop caches or change host VM settings.

To end the session and restore the original containers and Nara state, write:

```json
{"id":"owner-restore-1","action":"restore"}
```

The session deadline also restores automatically. Read `result.json` and verify
both resident health endpoints; an issued stop command alone does not prove
restoration. The watchdog sentinel is removed only after restoration is verified.
The original containers are started by captured IDs, never recreated.

## Results

The complete September 18 working artifacts, source snapshots, raw local
requests/responses and runtime observations live under
`a_bgt_rsi_v2_artifacts/2026-09-18/flash-personal-recovery/`. The final report must
name the actual useful profile and endpoint availability, ten practical task
outcomes, MTP on/off results, startup diagnosis, precision tradeoffs, remaining
failures, and the next concrete improvement. Until that report exists, this
document describes the session tools and does not claim model superiority.
