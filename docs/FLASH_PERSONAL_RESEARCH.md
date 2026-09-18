# Flash personal research session

The September 18 owner handoffs reopen Flash for interactive scientific and
programming work. The earlier closed benchmark windows and their grades are
unchanged. Passing every autonomous role is not a prerequisite for personal use.

The starting runtime is the already qualified Mia optimized MTP3 / reduced
47,149-token draft vocabulary / V2 / FULL-decode bundle. It uses the existing
immutable image, weights and packed disk-backed PLE. A new session measures its
actual behavior; historical qualification is prior evidence, not a new result.

## Start and inspect

From the prepared checkout:

```bash
env -u MOCK_LLM .venv-chroma/bin/python -m bench.flash_next_ab.personal_session \
  --run --output-dir /home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-18/flash-personal-recovery/session-UNUSED \
  --hours 4 --floor 20
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

| Arm | MTP | Recurrent state | KV request | Decode graph width |
| --- | --- | --- | --- | --- |
| `mtp3-fp32-auto` | 3 | FP32 | auto | 4 |
| `mtp0-fp32-auto` | 0 | FP32 | auto | 1 |
| `mtp3-bf16-auto` | 3 | BF16 | auto | 4 |

The no-MTP graph width differs because a step produces one token instead of a
target token plus three draft tokens. Report that difference. Read startup logs
for the resolved KV precision. The installed image lacks the QSA FP8-KV path;
testing FP8 requires the separately built and identified child runtime.

Request policy changes do not restart the model. Use explicit thinking off for
simple extraction/tool turns and explicit medium effort for substantive tasks.
Give reasoning calls enough output capacity and time, while counting exhaustion,
repetition, parser errors and incorrect answers separately. Reasoning text alone
is not successful completion. Historical strict grades are never overwritten by
a new presentation adapter or practical coding harness.

Runtime changes use a fresh command ID in the session's `command.json`:

```json
{"id":"bf16-first","action":"profile","profile":"mtp3-bf16-auto"}
```

Write the JSON atomically, and wait for the new `ready` event. A busy candidate
refuses the switch; submit a new command ID after the current task completes.
The incumbent pair stays stopped across these serving changes.

## Resource policy and recovery

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
