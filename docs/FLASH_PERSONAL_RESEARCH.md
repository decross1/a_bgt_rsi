# Flash personal research session

The September 18 owner handoffs reopen Flash for interactive scientific and
programming work. The earlier closed benchmark windows and their grades are
unchanged. Passing every autonomous role is not a prerequisite for personal use.

**No Flash endpoint is currently claimed live.** Both final handover restarts
met the kernel-allocation hard stop before readiness, after earlier successful
serving sessions. Complete the coordinated host recovery in the results report
before another unchanged launch. Keep the original pair as the available
fallback; no production routing cutover was made.

The preferred recovery bundle is the pinned **NVIDIA/SGLang v5** setup: 32K
context, one request, FP32 recurrent state, BF16 KV, native NEXTN speculation
and file-backed PLE. It completed the full earlier comparison and restoration,
but its failed second start prevents a reliable current-host handover claim.
See the [results and recovery plan](FLASH_PERSONAL_RESULTS_20260918.md).

## Use a verified SGLang endpoint

When the monitored SGLang session is ready, use port **30080** and explicitly
select the backend (the generic client's historical default remains Mia):

```bash
cd /home/decross1/projects/a_bgt_rsi
env -u MOCK_LLM LOCAL_MODEL_TRACE_DIR=/home/decross1/projects/a_bgt_rsi/logs/model_traces \
  .venv-chroma/bin/python -m bench.flash_next_ab.personal_client \
  --backend sglang --policy medium --prompt-file /absolute/path/to/question.txt \
  --max-output-tokens 4096 --output-dir /absolute/path/to/a-new-answer-directory \
  --print-final
```

The served name is `nvidia/Qwen3.8-Flash-Next-NVFP4` at
`http://127.0.0.1:30080/v1`. Off is available for routine testable work; medium
is an explicit reasoning policy, not a correctness guarantee. The Now view
shows the process-bound active session and emitted stream. Check the dated
availability receipt in the results report: the service is a finite personal
session, with the original pair and Nara intentionally paused until restoration.

### Start or stop a guarded SGLang session

After the coordinated recovery window and verified resident restoration,
use a fresh numbered directory in the fixed v5 family. The following example
uses `003`; choose an unused three-digit suffix and a future UTC restoration
end time. Leave at least 20 minutes before the daily 03:00 UTC ingestion window.
The controller reserves the final 15 minutes for restoration and retains the
20 GiB memory floor and kernel fault checks. It uses the existing verified
checkpoint receipt rather than downloading or rehashing the full model.

```bash
cd /home/decross1/projects/a_bgt_rsi
.venv-chroma/bin/python \
  /home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-18/flash-personal-recovery/sglang-fallback-prep/sglang_session_s3_v5.py \
  --run \
  --output-dir /home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-18/flash-personal-recovery/sglang-fallback-prep/runtime/session-s3-readiness-v5-003 \
  --receipt /home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-18/flash-personal-recovery/sglang-fallback-prep/checkpoint-verification-bf16-20260918T2343Z/checkpoint-receipt.json \
  --receipt-sha256 0489e1741832e6be63267cb1a04a1eb05736d27038fe924ac50cf02bce108287 \
  --end-at REPLACE_WITH_FUTURE_UTC_TIME
```

Keep that controller running. To finish early, call the same pinned script with
`--request-stop --output-dir <the-active-session-directory> --reason owner_finished`.
Wait for `result.json` to report verified restoration and for the controller to
exit; the stop request itself is not proof of recovery. The pinned script has
SHA-256 `355d52f0311d8eff89d13b8c8a718fb3a0a6300084e6a6337a0e61fbd6fcd01e`.
Use an SSH forward for remote access to the loopback model port.

The remaining sections preserve the Mia comparison controls and recovery
instructions. Starting Mia again is a new diagnostic; do not infer that its
final failed startup was qualified for current use.

## Mia comparison: start and inspect

From the canonical checkout after this change is installed:

```bash
cd /home/decross1/projects/a_bgt_rsi
env -u MOCK_LLM .venv-chroma/bin/python -m bench.flash_next_ab.personal_session \
  --run --output-dir /home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-18/flash-personal-recovery/session-example-001 \
  --hours 4 --floor 20 --initial-profile mtp3-fp32-auto
```

Replace `session-example-001` with a fresh lowercase `session-*` directory. The supervisor retains the normal
resource locks, records the original resident IDs and Nara state, verifies model
files, pauses background callers and starts Flash. Do not run a second controller
against an occupied lease. `state.json` is an observation; verify the supervisor
PID/start identity and endpoint before interpreting a stale state as live work.
Keep this controller running in its terminal and make requests from a second
terminal once the live session reaches `phase: ready`. The historical parent
container-start-to-ready interval was about ten minutes, excluding model/PLE
checksum verification and resident shutdown. The final handover separately
spent about three minutes on verification before launching its worker; do not
treat the ten-minute value as total controller-to-ready time. Request latency
after loading is separate.

Daily ingestion starts at 03:00 UTC. Its BGE embedder currently defaults to CPU,
but still shares the Spark's physical memory. Concurrent peak memory with Flash
has not been measured. Schedule restoration before that job: allow the existing
15-minute restoration reserve plus five minutes of margin. A four-hour example
is a session duration, not permission to overlap the ingestion window. The
controller does not currently enforce this schedule boundary. After ingestion,
wait for its new terminal receipt and process exit before starting a fresh
session; a failed ingestion attempt must remain visibly failed.

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

Every listed arm sets `VLLM_QSA_EXACT_TOPK=1`. In the checksum-bound local QSA
source this masks blocks outside the visible range and uses `torch.topk` for the
QSA block selector. “Exact” describes that selector operation; it does not mean
dense-attention equivalence, deterministic end-to-end generation, or lossless
speculation. The exact generated source and patch are identified in the local
`flash-personal-recovery/runtime-audit.md`; the source patch
`patch_qsa_exact_topk.py` has SHA-256
`802f6564e514fe5a228738873570f9ce94c230f40d3a7c932cc5893e2147a010`.
The child build receipt separately binds its combined QSA operations module as
`625eb5c8e884c1ad4af730b14123d5f6d6afaf7afe550173aece8d7ec5a26470`;
that module retains the same exact-selector path.
The motivating persistent-top-k issue is
[vLLM #54521](https://github.com/vllm-project/vllm/issues/54521).

`--initial-profile` fixes one candidate specification for the entire session.
Profile commands may switch only among arms belonging to that same exact image;
they cannot hot-switch between parent and child. To compare auto and FP8 KV in
the child while holding BF16 recurrent state fixed, start a fresh second session:

```bash
env -u MOCK_LLM .venv-chroma/bin/python -m bench.flash_next_ab.personal_session \
  --run --output-dir /home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-18/flash-personal-recovery/session-fp8-example-001 \
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
profile. Its summary currently names the parent candidate request and sets
`runtime_profile_verified=false`; when calling a child profile, use the live
session state and launch receipts as the runtime provenance. Evaluation runners
bind the controller and container separately.

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

### Independently served NVIDIA/SGLang endpoint

The September 19 comparison also served the NVIDIA checkpoint through a
separately monitored SGLang session. It is the preferred recovery bundle and must
be started under its own controller; it is not concurrently resident with a
Mia personal session. The same client can address that fixed
loopback endpoint without labeling it as the Mia candidate:

```bash
env -u MOCK_LLM .venv-chroma/bin/python -m bench.flash_next_ab.personal_client \
  --backend sglang --policy medium --prompt-file /absolute/path/to/question.txt \
  --max-output-tokens 8192 --output-dir /absolute/path/to/a-new-answer-directory \
  --print-final
```

This selects `http://127.0.0.1:30080/v1` and the exact served name
`nvidia/Qwen3.8-Flash-Next-NVFP4`. It does not start a server. The CLI records the
requested endpoint/model and NVIDIA artifact identity, leaves the Mia candidate
specification empty, and still sets `runtime_profile_verified=false`. Use the
live controller receipts to establish serving precision and speculation.
Both nested vLLM and top-level SGLang reasoning-token usage are preserved.
The default `--backend mia` continues to use port 8012.

The Now dashboard follows the process-bound personal session. It displays the
actual Mia or SGLang endpoint on the existing Flash card, marks the resident pair
as intentionally paused, and resets its activity history when the candidate
changes. SGLang decode rates use differences in its decode-token counter;
prefill tokens are excluded. Its KV metric describes the full KV pool, while
prefix-hit and speculative-acceptance values describe the server's reporting
window. Unavailable counters remain unavailable. This operational display is
separate from model qualification or a change to the lab's normal routes.

### Resource limits

This new diagnostic allows at most 1,800 seconds per startup. The preferred
physical reserve remains 20 GiB; 12 GiB is only selectable as an explicit new
session declaration. Candidate cgroup swap and OOM remain hard failures, as do
unexpected exits/restarts, changed memory limits, sustained severe memory PSI,
driver/allocation errors and sustained unresponsiveness. The parent monitors
worker heartbeats and retains a separate restoration allowance.

The delivered controller also reads the kernel journal every 15 seconds during
startup and serving for new host NVIDIA allocation faults or Xid errors. It saves
that evidence separately and excludes earlier events from candidate attribution.
That timestamp filter is not evidence that an earlier host fault is resolved.
The unresolved same-boot allocation events in the final report require the
coordinated clean-host recovery before another launch. Unreadable journal
evidence triggers recovery. This closes a gap exposed by the independent
SGLang load; the historical Mia measurements used the earlier controller.
The stop is conservative: a host kernel event alone does not prove which
process caused it.

Host pageout is recorded with host counters, process RSS/swap, candidate cgroup
file/anonymous memory, and memory/I/O PSI. A PLE file fault is not anonymous
swap-out. Host pageout alone does not identify a candidate OOM or a quality loss.
The controller does not disable swap, drop caches or change host VM settings.
A preexisting root cron drops caches every 30 minutes independently of the
controller. Keep it unchanged for the proposed fresh-host comparison, record
its actual journal timestamps, and retain it as a possible timing confound.

To end the session and restore the original containers and Nara state, write
an atomic command in that session's directory (replace `session-example-001`):

```bash
python3 - <<'PY'
import json, os, uuid
from pathlib import Path

session = Path('/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-18/flash-personal-recovery/session-example-001')
command = {'id': f'owner-restore-{uuid.uuid4().hex}', 'action': 'restore'}
temporary = session / f'.command-{uuid.uuid4().hex}.tmp'
with temporary.open('x') as stream:
    json.dump(command, stream)
    stream.flush()
    os.fsync(stream.fileno())
os.replace(temporary, session / 'command.json')
PY
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
failures, and the next concrete improvement. The
[results report](FLASH_PERSONAL_RESULTS_20260918.md) records both completed
comparisons, the SGLang recovery profile, counterevidence and availability at
handoff. The useful personal endpoint remains the unfinished goal; selecting a
recovery profile does not establish live availability, general model superiority
or a permanent change to autonomous lab routing.
