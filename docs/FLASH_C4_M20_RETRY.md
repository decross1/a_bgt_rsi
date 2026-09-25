# Flash C4-M20 minimum-pool attended retry

## Status and authority boundary

**Observed current process state (2026-09-25):** `flash-resident.service` has
been active since `2026-09-24 08:21:43 UTC`. Its matching start time and the
recorded cutover receipt make the current C4 guarded-profile identity an
**inference**, not a fresh lifecycle inspection. The recorded attended result is
`/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-18/flash-personal-recovery/c4-min224-cutover-20260924T0818Z/cutover-receipt.json` (SHA-256
`4511cabeba2ca3e71a4f8c2c1c9965fea90006b1d030cb901643e683f3008315`).
That receipt is a **synthesized receipt binding observed-classified evidence**
for the September 24 cutover; its recorded decision is explicitly `proposed`.
This document does not create live-operation authority.

No new C4 cutover, restart, or traffic expansion is qualified by this status
update. The current operating direction is to wait for an interactive Claude
attended window before any new live C4 action. A service `active/running`
observation establishes residency only; it does not substitute for a fresh
preflight, attended authorization, or a new receipt after a future restart.

**Historical state:** v12 was published and independently tested offline before
the September 24 attended cutover. The release is one combined forward pin
from the verified C1 rollback commit
`08827e74857416406ed9dad58364607f12cc9b27`. It incorporates the reviewed
M20 and minimum-pool changes. The rejected strict-pool commit
`001b57ede172466e9aab04b30b0f084f93af434e` remains in history but was
reverted; it is not an intermediate live tree in this cutover.
The already-published v11 files remain immutable.

### Observed September 24 attended result, and remaining limits

The above receipt records the forward commit
`a958f91c3493814944df7b7ee061c6cc0e981595`, 262,144 context tokens, a
237,440-token realized pool (above the 229,376-token minimum), requested and
effective R4, and Mamba cache 20. It binds
`c4-server-info.json` (SHA-256
`c399e3bd511565f39b3977abaaa1211e24d540c4c493dee77e6233508fa8bee3`) and
`c4-four-stream-smoke.json` (SHA-256
`8ac02d745537ec9f686865aafee44f842aa4c718f090a28f7cb25e1a48de3117`), both
in that exact artifact directory. Two short four-stream runs completed with
overlapping generation windows and no scheduler retractions; the same directory
contains `metrics-before.txt` (SHA-256
`824bc591a67027ce35e10118efc4e555b5a739e8506e7bc3aa3470f56e3b1c85`) and
`metrics-after.txt` (SHA-256
`d4e763454059239114740cde275e64d9d14121c3944d1427f68b20447da1844e`).

This is **not yet qualification** for four concurrent near-200K contexts,
mixed long-load traffic, benchmark paths that use `runtime_context.py`, or
overlapping long clients. Maintain K=1 for Nara/other overlapping calls and
permit only one near-196K client at a time until representative mixed-load
testing has a separately reviewed receipt.

## Evidence and bounded policy change

The 2026-09-24 C4/M24 trial requested a 262,144-token pool but SGLang exposed
260,800 tokens. Helper v10 rejected `max_total_num_tokens`, the operator stopped
before the boot fault latch, no four-stream smoke was run, and C1 was restored
ready. Preserve that negative result:

- `c4-cutover-20260924/cutover-receipt.json`:
  `30e73a953d84cff72992c406c181a142cb3f64c7cbdecc83e9a32bd91cd772a0`
- rejected v10 readiness diagnostic:
  `40726403d87018c8b472b27f479b97e7c32989c52e9c1ee8959d4a9591cf07eb`
- rejected v10 final log:
  `5112d23c50e0abfa790cf5fb8900b8183d489ff895452dd8bcab1db6975e3b7e`

A later M20 launch reported a 244,288-token realized pool, versus 260,800 for
M24. Claude coordination mailbox sequence 130 identifies launch-time unified
memory variation as the leading explanation. That causal explanation is
inferred, not established: this runbook does **not** claim M20 recovered or
reduced the pool. This bounded retry retains M20 to isolate the new readiness
policy from another serving-config change. M24 is a separate alternative, not
an unreviewed switch inside this trial.

The owner changed the readiness policy for the realized scheduler pool to a
minimum of `224 * 1024 = 229376` tokens. Pi is configured to begin compaction
at 196,608 input tokens, but its maximum output adds 16,384; a single turn can
therefore reserve about 212,992 tokens. This is a policy threshold, not evidence
that four long-context requests fit. The realized pool is shared, and the
server's advertised maximum input length must be checked against the realized
pool rather than inferred from the 262,144 context window. Before normal lab
traffic resumes, the coordinator must keep one long-context client at a time
or enforce an aggregate token budget that includes outputs.

Everything else remains exact: requested R4, effective R4, context and requested
pool 262,144, Mamba cache 20, `mem_fraction_static=0.83`, BF16 KV, speculative
steps 3, chunked prefill 2048, and decode graphs `[1, 2, 4]`. Helper v12 changes
only the realized `max_total_num_tokens` gate from equality to a strict-integer
lower bound. Missing, Boolean, string, and below-bound values fail closed.

## Immutable candidate

The following new files are published without replacing earlier files in
`sglang-fallback-prep/`. Before use, verify from that directory with
`sha256sum -c c4-m20-min224-v12-sha256.txt`. The manifest intentionally excludes
`runtime/`, caches, bytecode, and unrelated prep-tree files.

| Artifact | SHA-256 |
| --- | --- |
| `nextn-262k-c4-m20-min224-s3.json` | `f96ac48d2005e0dc8d6a9dc0b54c612ee7223c3c825913da9f7f267e0c624b34` |
| `sglang_session_s3_v12.py` | `c746c3abebddf53f1dea8e84d26cc1844469f1583c1a197e964831bf69a9aa39` |
| `sglang_session_s3_v11_to_v12.diff` | `57eeb852a689617bb80a20349ca3efb57e3b828dba98380d16cea362ebd7540e` |
| `test_sglang_session_s3_v12.py` | `fe3d80d61474c8f81ceb3e3636efb69a509c9d007786ebfa182b099b9a33eee2` |
| `flash_concurrency_smoke_min224_v1.py` | `26e2d9b5901aa52e0445673d0effbc3abb7ae5a83d10bbaa041745f8e2c21f05` |
| `test_flash_concurrency_smoke_min224_v1.py` | `da8ba90ef4e4f42f5c486d87e2fbf337bcdf70bca77c6673f8f0caf0a06a2b75` |
| `c4-m20-min224-v12-sha256.txt` | `49423d37f4ccfd91879baf9cbc0180e99f17274d8a67b73917b5153a122a8a82` |

The smoke is derived from reviewed quality-tool commit
`70fbb82cd6364f773e2c6c7792582345fbc16d0d`, whose original tool SHA-256 is
`51a4ed5045fca3bea94ded879e0461d0dfdfa543f4864c435e00bf200959a7b5`.
The published copy additionally checks exact reported context/requested pool and
the minimum realized-pool boundary. It loads deployment policy from the exact
repository named by `A_BGT_RSI_SMOKE_REPO`, defaulting to the canonical checkout.

For historical reproducibility, run the external offline tests from a scratch
working directory:

```bash
PREP=/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-18/flash-personal-recovery/sglang-fallback-prep
REPO=/home/decross1/projects/a_bgt_rsi
CANDIDATE=/tmp/a_bgt_rsi-flash-c4-min224-forward-20260924
cd /tmp
PYTHONDONTWRITEBYTECODE=1 \
  "$REPO/.venv-chroma/bin/python" -m pytest -q -p no:cacheprovider \
  "$PREP/test_sglang_session_s3_v12.py"
A_BGT_RSI_SMOKE_REPO="$CANDIDATE" PYTHONDONTWRITEBYTECODE=1 \
  "$REPO/.venv-chroma/bin/python" -m pytest -q -p no:cacheprovider \
  "$PREP/test_flash_concurrency_smoke_min224_v1.py"
```

The smoke fixture had to bind the reviewed C4 candidate before the historical
live merge, when the canonical checkout was deliberately still C1. This is
historical fixture-binding evidence, not a prescribed invocation for a future
restart.

## HISTORICAL ONLY: September 24 C1-to-C4 cutover record

**This entire section is historical evidence, never a current action plan.** It
describes the September 24 transition when C1 was resident and
`V12_PIN_COMMIT` had not yet been applied. The current C4 forward commit
`a958f91c3493814944df7b7ee061c6cc0e981595` is an ancestor of the current
checkout `9fc48c9b66ac5ebc1da03635272f4cecebc64545`; therefore these historical
instructions must not be used to stop C1, apply V12, or alter the resident C4
service.

Any future restart needs a fresh reviewed plan based on the current C4 state
and a new interactive-Claude attended decision. That plan must independently
select its candidate, preflight, qualification gates, and rollback path; it may
cite this record as evidence but cannot execute this record as a runbook.

### Historical preconditions and stop budget

The September 24 delegated live coordinator was available for the attended
window, confirmed C1 ready and idle with Nara/coordinator work quiescent, and
preserved the two pause markers. It archived C1 state, touched source files,
and their hashes before mutation.

The historical cutover stopped C1 under v8 before applying `V12_PIN_COMMIT`,
required `phase=stopped`, an empty owned-container/port check, and successful
cleanup, then moved the stopped state's `artifact_dir` to `prior_artifact_dir`
for the helper handoff.

After the historical stop and cache eviction, the procedure required both of
the following immediately:

- `MemAvailable >= 104 GiB`
- `MemFree >= 100 GiB`

The historical attended window retained enough time for a second approximately
12.5-minute C1 cold boot if rollback was needed. Pool variation between boots
remains a material risk for any plan that is separately reviewed in the future.

### Historical qualification record

The historical procedure applied `V12_PIN_COMMIT`, reran `selected` and focused
tests, started the resident, and monitored every 30 seconds. It did not run
stream smoke before readiness.

At historical readiness, `/get_server_info` showed all of:

- `context_length == 262144`
- requested `max_total_tokens == 262144`
- realized `max_total_num_tokens >= 229376`
- `max_req_input_len == min(context_length - 1, max_total_num_tokens - 1) - 5`
  (the pinned `runtime_context.py` rule; 229,370 at the minimum pool)
- `max_running_requests == 4`
- `internal_states[0].effective_max_running_requests_per_dp == 4`
- `max_mamba_cache_size == 20`
- `mem_fraction_static == 0.83`
- `cuda_graph_bs_decode == [1, 2, 4]`

The pinned `source/scripts/runtime_context.py` capture helper was not used as a
C4 validator because it still admits only C1 and a full 262,144-token realized
pool. The historical trial inspected the full live server-info response
directly. The ordinary resident/Pi/Nara path does not call this helper, but
external promotion/comparison benchmarks that do remain paused until adapted
and tested.

The following command records the historical hardened-smoke invocation. **Do
not run it as a current C4 procedure**; any future plan must specify and review
its own invocation, binding both code loader and deployment argument explicitly
to its selected checkout:

```bash
PREP=/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-18/flash-personal-recovery/sglang-fallback-prep
REPO=/home/decross1/projects/a_bgt_rsi
A_BGT_RSI_SMOKE_REPO="$REPO" \
  "$REPO/.venv-chroma/bin/python" \
  "$PREP/flash_concurrency_smoke_min224_v1.py" \
  --deployment "$REPO/config/model_deployment.json"
```

The historical smoke required four complete SSE streams, exact requested and
effective R4, exact 262,144 context and requested pool, a realized pool of at
least 229,376, real four-way decode overlap, and no increase in retracted
requests. It retained the `max_req_input_len`, M20, `.83`, and graph server-info
checks because the smoke did not validate those fields. The smoke used short
prompts and did not prove four near-200K requests fit or exclude a retraction
between first and last token.

The historical keep decision required a post-smoke host-memory low-water of at
least 12 GiB and no more than 3 GiB below the measured C1 reference, no new
kernel `NV_ERR`/`Xid` records or scheduler retractions, and a full new receipt.
Before historical lab resume, the pause-marker safeguards verified
`reserveTokens=65536` in both Pi settings files, one long-context client at a
time, and initially K=1 for overlapping Nara/other calls. Those recorded guards
do not prove a representative mixed-load test.

## Historical rollback evidence and future fault boundary

For the historical C1-to-C4 procedure only, a clean mismatch or failed keep
gate stopped v12, required clean cleanup, archived the stopped v12 state, moved
its `artifact_dir` to `prior_artifact_dir`, and reverted only `V12_PIN_COMMIT`.
That restored the reviewed v8/C1 source and deployment, not the rejected
strict-v11 C4 pin. The historical rollback checks bound v8 helper SHA
`606d05f201b84b01441e6e23b98ed0c66c6a92faa81300b9d796bf54a2a4466c` and C1
profile SHA `f0fbb6c09ff926dd17d8bb9787e1f52632e5fba9135431a3d01222be785a81bf`.
Never reset or rewrite the historical v10/M24 or v11/M20 evidence.

If the service enters `phase=fault` or the boot latch arms, do not retry, clear
state, or improvise a restart. Capture the specific fault and obtain an
interactive-Claude decision plus a fresh reviewed current-C4 plan. The
attended-retry authorization does not predetermine recovery from an as-yet-unseen
fault.
