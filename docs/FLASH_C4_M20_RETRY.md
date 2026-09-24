# Flash C4-M20 attended retry

Status: **prepared and published offline; live qualification not yet
performed.** This is a single forward pin from restored C1 commit
`0765aaf3d10b4e6138852de54614b49b5d46328b`. It does not merge the rejected
C4/M24 or C2 prep commits.

## Evidence and bounded hypothesis

The 2026-09-24 C4/M24 trial requested a 262,144-token pool but SGLang exposed
only 260,800 tokens. Helper v10 rejected `max_total_num_tokens`, the operator
stopped before the boot fault latch, no four-stream smoke was run, and C1 was
restored ready. Preserve that negative result:

- `c4-cutover-20260924/cutover-receipt.json`:
  `30e73a953d84cff72992c406c181a142cb3f64c7cbdecc83e9a32bd91cd772a0`
- rejected v10 readiness diagnostic:
  `40726403d87018c8b472b27f479b97e7c32989c52e9c1ee8959d4a9591cf07eb`
- rejected v10 final log:
  `5112d23c50e0abfa790cf5fb8900b8183d489ff895452dd8bcab1db6975e3b7e`

The bounded retry changes the Mamba cache from 24 to 20 slots. Twenty is the
minimum admitted by the observed SGLang `max_mamba_cache_size // 5` cap for
four running requests. The hypothesis is that returning four slots to the
memory budget will recover the missing KV-token margin. This is inferred, not
yet observed; only the live gates below qualify it.

Everything else stays pinned: R4, context and requested pool 262,144,
`mem_fraction_static=0.83`, BF16 KV, speculative steps 3, chunked prefill 2048,
and decode graphs `[1, 2, 4]`. Helper v11 requires requested R4, effective R4,
M20, exact `max_total_num_tokens=262144`, and the existing exact serving
profile before readiness.

## Immutable candidate

These review artifacts are published in `sglang-fallback-prep/`. Before each
use, verify `sha256sum -c c4-m20-v11-sha256.txt`. The narrow manifest
intentionally excludes `runtime/`, caches, bytecode and unrelated prep-tree
files.

| Artifact | SHA-256 |
| --- | --- |
| `nextn-262k-c4-m20-s3.json` | `01436b7e2c515f2414b1693675d07a1de4504728455adc94f1e15da45c31007d` |
| `sglang_session_s3_v11.py` | `7cf10c6d0776583100f848ae24b7573c88dbf74558a3761e0f1f630c8165ad40` |
| `sglang_session_s3_v10_to_v11.diff` | `6f2de9a0e03a39f144578952bcede897ddc9c04bbdeb96339a0688156460f066` |
| `test_sglang_session_s3_v11.py` | `f5c92cb55c4beef2313463edb321d59d390263ec180e2bf11fcf8d1d9b2b52d8` |
| `c4-m20-v11-sha256.txt` | `73267824b1271ade682a545d397347d04e9d92df5722f8ce995d2aa27c51cad0` |

Run the external offline test from a scratch working directory:

```bash
PREP=/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-18/flash-personal-recovery/sglang-fallback-prep
cd /tmp
PYTHONDONTWRITEBYTECODE=1 \
  /home/decross1/projects/a_bgt_rsi/.venv-chroma/bin/python -m pytest -q \
  -p no:cacheprovider "$PREP/test_sglang_session_s3_v11.py"
```

Before the live stop, record the candidate commit as `V11_PIN_COMMIT`; it must
be the one clean forward pin on base `0765aaf`. Run `flash_resident selected`
and the focused repository tests after the artifacts are published.

## Preconditions and stop budget

The owner must remain available for the attended window. Confirm C1 is ready
and idle, Nara/coordinator work is quiescent, and no planner phase is due. The
two pause markers pre-existed this retry and must be preserved, not removed.
Archive the C1 state, touched source files and their hashes before mutation.

Stop C1 under v8 before applying `V11_PIN_COMMIT`. Require `phase=stopped`, an
empty owned-container/port check, and successful cleanup. Move the stopped
state's `artifact_dir` to `prior_artifact_dir` for the helper handoff.

After stop and cache eviction, proceed only if both conditions hold
immediately:

- `MemAvailable >= 104 GiB`
- `MemFree >= 100 GiB`

Do not consume the supervisor's possible 35-minute prelaunch wait. The
attended window must retain enough time for a second approximately 12.5-minute
C1 cold boot if rollback is needed.

## Qualification

Apply only `V11_PIN_COMMIT`, rerun `selected` and focused tests, start the
resident, and monitor every 30 seconds. Stop immediately if a readiness
diagnostic reports any mismatch. Do not run the stream smoke before readiness.

At readiness, `/get_server_info` must show all of:

- `context_length == 262144`
- `max_total_num_tokens == 262144`
- `max_running_requests == 4`
- `internal_states[0].effective_max_running_requests_per_dp == 4`
- `max_mamba_cache_size == 20`
- `mem_fraction_static == 0.83`
- `cuda_graph_bs_decode == [1, 2, 4]`

Then run the already-reviewed hardened smoke, binding it explicitly to the
live candidate deployment rather than the quality worktree's M24 config:

```bash
QUALITY=/home/decross1/projects/a_bgt_rsi_worktrees/flash-c4-quality-20260924
REPO=/home/decross1/projects/a_bgt_rsi
"$REPO/.venv-chroma/bin/python" "$QUALITY/tools/flash_concurrency_smoke.py" \
  --deployment "$REPO/config/model_deployment.json"
```

The reviewed tool is commit `70fbb82cd6364f773e2c6c7792582345fbc16d0d`,
SHA-256 `51a4ed5045fca3bea94ded879e0461d0dfdfa543f4864c435e00bf200959a7b5`.
It must report four complete SSE streams, requested/effective R4, exact pool,
and real decode overlap. Separately retain the M20 server-info check because
the smoke does not validate the Mamba field.

Keep C4-M20 only if readiness and smoke pass, the post-smoke host-memory
low-water is at least 12 GiB and no more than 3 GiB below the measured C1
reference, and there are no new kernel `NV_ERR`/`Xid` records. Archive the
server info, smoke JSON, host-memory window, kernel query, exact Git/artifact
hashes and final decision in a new receipt.

## Rollback and fault boundary

For a clean mismatch or failed keep gate: stop under v11, require clean
cleanup, archive the stopped v11 state, move its `artifact_dir` to
`prior_artifact_dir`, revert only `V11_PIN_COMMIT`, verify `selected` binds C1,
and restart v8. Never reset or revert the historical v10/M24 evidence. Verify
C1 requested/effective R1 and its exact 262,144-token pool, then record the
rollback receipt.

If the service enters `phase=fault` or the boot latch arms, do not retry,
clear state, or improvise a restart. Capture the specific fault and ask the
owner for a new decision. The existing authorization for this attended retry
does not predetermine recovery from an as-yet-unseen fault.
