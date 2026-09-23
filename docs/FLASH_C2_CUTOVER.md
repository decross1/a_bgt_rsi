# Flash C2 cutover: two running requests in the same 262K pool

Status: **prepared offline, not executed.** The owner runs this with the
meta-oracle. Nothing here has touched the live server.

**Goal.** Oracle and Nara share Flash. Today the server runs one request at a
time (`max_running_requests 1`). This change lets it run two, in the same
262,144-token pool. The KV pool, context, MTP, BF16 KV, mamba cache, floors,
guard and container limits stay the same.

| Item | Live (v8, C1) | Prepared (v9, C2) |
| --- | --- | --- |
| Helper | `sglang_session_s3_v8.py` `606d05f201b84b01441e6e23b98ed0c66c6a92faa81300b9d796bf54a2a4466c` | `sglang_session_s3_v9.py` `1be5d93b88bd26b6f8f8514088375df9c986d656d9aafffb8a838711b7d101b7` |
| Profile | `nextn-262k-c1-s3.json` `f0fbb6c09ff926dd17d8bb9787e1f52632e5fba9135431a3d01222be785a81bf` | `nextn-262k-c2-s3.json` `495f1f3c59f559185720257538646354a5995ab9ca82e042565ae989ca4452a3` |
| Serve argv | `--max-running-requests 1`, `--cuda-graph-bs-decode 1` | `--max-running-requests 2`, `--cuda-graph-bs-decode 1 2` |
| Lab pins | `flash_resident.BUNDLE/BUNDLE_SHA`, `selected()` profile sha, `config/model_deployment.json` (`max_running_requests`, `profile_sha256`), `agent_wrapper/deployment.py` exact `max_running_requests` | the same fields on branch `claude/flash-c2-prep-20260923` |

The profiles differ by one byte (`1` to `2`). v9 is v8 with five edited
lines: the `PROFILE` path, `PROFILE_SHA256`, `max_running_requests` in
`server_profile()` (live readiness) and in `run_session`'s launch record, and
that record's qualification text. The diff is
`sglang-fallback-prep/sglang_session_s3_v8_to_v9.diff`. The only change the
pinned container entrypoint makes to the serve argv is the pair shown above,
checked offline with the pinned `runtime.entrypoint.build_all`. The adapter
(`guard_uid1000_alloc_v5.py`), guard, sources lock and control sources are
unchanged, and v9 pins them at the same hashes.

**Live path.** The supervisor loads the helper. The helper runs only the
adapter, which wraps the pinned `source/scripts/guard.py`, which uses the
container `runtime` profile validator (it accepts 1, 2, 4 and 8). The
`run_sglang_supplement_s3*.py`, `sglang_session_s3.py` and practical, screen
and canary runners are not imported or executed by v8 or v9, so their C1
`exact_policy` blocks were left alone. `source/scripts/runtime_context.py`
(`"this comparison contract is C1"`) is only hash-checked on the resident
path. It runs only inside `run_session`, the evaluation mode the resident
never uses.

In the paths below, `REPO=/home/decross1/projects/a_bgt_rsi`,
`PREP=/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-18/flash-personal-recovery/sglang-fallback-prep`
and `INC=/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-18/flash-personal-recovery/c2-cutover-$(date -u +%Y%m%d)`.
Run the commands from `$REPO` in a shell where `MOCK_LLM` is unset for the
service commands (`env -u MOCK_LLM`).

## 0. Preconditions (all must hold; otherwise do not start)

1. **Owner present** for the whole window, about 30 minutes. A fault
   latches for the boot, and only the owner can clear it.
2. **No Oracle or meta-oracle phase running**, and none due in the next
   45 minutes:
   ```bash
   systemctl --user list-timers --no-pager          # oracle-daily-planning: 15:00 / 01:00 UTC
   systemctl --user is-active oracle-daily-planning.service   # must not be "active"/"activating"
   pgrep -af 'meta_oracle_run|oracle-daily|claude -p|pi -p' || echo none   # only this cutover's own session may appear
   ```
3. **Nara lane idle, and loops paused for the window.** The owner does this,
   and only the owner removes the files afterwards:
   ```bash
   systemctl --user is-active nara-lane.service      # must be "inactive"
   touch run_state/pause_nara_lane run_state/pause_coordinator
   ```
4. **Flash idle and healthy on v8:**
   ```bash
   .venv-chroma/bin/python -m orchestrator.flash_resident check-ready; echo "ready=$?"   # 0
   curl -s --noproxy '*' http://127.0.0.1:30080/metrics | grep -E '^sglang:num_(running|queue)_reqs'  # all 0
   python3 -c "import json;s=json.load(open('run_state/flash_resident.json'));print(s['phase'],s['bundle_sha256'][:8])"  # ready 606d05f2
   ```
5. **Memory.** While Flash is up, `MemAvailable` ≥ **16 GiB**. The live v8
   262K low-water is 16.8 GiB against the 10 GiB floor, and C2 is estimated
   to cost about 0.5–1.2 GiB more (see Risks). The supervisor also enforces
   104 GiB `MemAvailable` and 100 GiB `MemFree` before launch, after the stop.
   ```bash
   grep -E 'MemAvailable|MemFree' /proc/meminfo
   ```
6. **Pins intact.** No output means everything matches:
   ```bash
   cd "$PREP" && sha256sum -c --quiet - <<'EOF'
   606d05f201b84b01441e6e23b98ed0c66c6a92faa81300b9d796bf54a2a4466c  sglang_session_s3_v8.py
   1be5d93b88bd26b6f8f8514088375df9c986d656d9aafffb8a838711b7d101b7  sglang_session_s3_v9.py
   f0fbb6c09ff926dd17d8bb9787e1f52632e5fba9135431a3d01222be785a81bf  nextn-262k-c1-s3.json
   495f1f3c59f559185720257538646354a5995ab9ca82e042565ae989ca4452a3  nextn-262k-c2-s3.json
   c2ee1dbf3eeaf7d69e4133825e2d4426c2e0e96c307dd1e1e314859deadbda73  guard_uid1000_alloc_v5.py
   EOF
   cd "$REPO"
   ```
7. **Main checkout clean for the touched files.** No output expected:
   ```bash
   git status --porcelain -- orchestrator/flash_resident.py config/model_deployment.json \
       agent_wrapper/deployment.py tests/test_flash_resident.py tests/test_flash_deployment_routing.py
   git log --oneline -1 claude/flash-c2-prep-20260923
   ```

## 1. Stop under v8 (before any merge)

Stop **before** merging. The unit's `ExecStopPost` runs `flash_resident cleanup`
from the checked-out code. If v9 were already pinned, cleanup would refuse
with `helper handoff required` and leave the owned container to be removed by
hand.

```bash
env -u MOCK_LLM systemctl --user stop flash-resident.service     # drains callers, up to 900 s
systemctl --user is-active flash-resident.service                # inactive
python3 -c "import json;s=json.load(open('run_state/flash_resident.json'));print(s['phase'],s.get('error'),s.get('cleanup'),s.get('stop_post_cleanup'))"
docker ps --filter name=qwen38fn- --format '{{.ID}} {{.Names}}'  # empty
ss -ltn '( sport = :30080 )' | tail -n +2                        # empty
```
Proceed only if the phase is `stopped` and the cleanup is `removed` or
`already_removed`. If the phase is `fault`, stop here and see §8.

## 2. Archive

```bash
mkdir -p "$INC"
cp run_state/flash_resident.json "$INC/stopped-v8-state.json"
for f in orchestrator/flash_resident.py config/model_deployment.json agent_wrapper/deployment.py \
         tests/test_flash_resident.py tests/test_flash_deployment_routing.py; do
  cp "$f" "$INC/$(echo "$f" | sed 's#/#__#g').before"; done
sha256sum "$INC"/* > "$INC/archive.sha256"
```

## 3. Helper handoff (state file)

Move `artifact_dir` to `prior_artifact_dir`, so v9 neither re-validates nor
cleans the v8 run:
```bash
python3 - <<'EOF'
import json, pathlib
p = pathlib.Path('run_state/flash_resident.json'); s = json.loads(p.read_text())
assert s['phase'] == 'stopped' and s['bundle_sha256'].startswith('606d05f2'), s['phase']
s['prior_artifact_dir'] = s.pop('artifact_dir')
tmp = p.with_suffix('.tmp'); tmp.write_text(json.dumps(s, indent=2) + '\n'); tmp.replace(p)
print('handoff ok', s['prior_artifact_dir'])
EOF
```

## 4. Merge the pins

```bash
git merge --ff-only claude/flash-c2-prep-20260923 || git merge --no-ff claude/flash-c2-prep-20260923
.venv-chroma/bin/python -m orchestrator.flash_resident selected; echo "selected=$?"   # 0
MOCK_LLM=1 PYTHONDONTWRITEBYTECODE=1 .venv-chroma/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_flash_resident.py tests/test_flash_deployment_routing.py tests/test_flash_concurrency_smoke.py
```
The merge lands on whatever branch the live checkout has checked out
(`git branch --show-current`). That checkout carries other sessions'
uncommitted edits, which the merge leaves alone. If anything fails, undo the
merge with `git reset --keep ORIG_HEAD`. Never use `--hard`, because it would
discard those edits. Then start v8 as in §5. The handed-off state has no
`artifact_dir`, so v8 starts without a handoff refusal.

## 5. Start and wait for readiness

```bash
grep -E 'MemAvailable|MemFree' /proc/meminfo          # expect ~104+ GiB available with Flash down
env -u MOCK_LLM systemctl --user start flash-resident.service
# Cold 262K load is ~12.5 min (LoadEvictor runs until readiness; hard deadline 30 min).
for i in $(seq 1 60); do
  .venv-chroma/bin/python -m orchestrator.flash_resident check-ready && { echo READY; break; }
  python3 -c "import json;s=json.load(open('run_state/flash_resident.json'));print(s['phase'],s.get('error'))"
  sleep 30; done
```
Watch `journalctl --user -u flash-resident.service -f` in another terminal.
The supervisor restarts `nara-daemon.service` at readiness, so the daemon
picks up the new deployment validator. If the UI backend reports a
deployment or profile mismatch, restart it:
`ui/scripts/ui-services.sh stop && ui/scripts/ui-services.sh start`.

## 6. Verify C2 and memory

```bash
curl -s --noproxy '*' http://127.0.0.1:30080/get_server_info | python3 -c "
import json,sys; d=json.load(sys.stdin)
print({k: d.get(k) for k in ('max_running_requests','max_total_num_tokens','context_length','cuda_graph_bs_decode','max_req_input_len')})
print(d['internal_states'][0].get('memory_usage'))"
# expect max_running_requests 2, max_total_num_tokens 262144, cuda_graph_bs_decode [1, 2], max_req_input_len 262138
CID=$(python3 -c "import json;print(json.load(open('run_state/flash_resident.json'))['container_id'])")
docker logs "$CID" 2>&1 | grep -E 'Mamba Cache is allocated|KV Cache is allocated|max_running_requests=|avail mem=' | tail -8
# C1 reference: ssm 1.79GB, intermediate_ssm_state_cache 0.84GB, KV 3.00+3.00GB (+0.25+0.25 draft), available_gpu_mem 23.95 GB
.venv-chroma/bin/python tools/flash_concurrency_smoke.py; echo "smoke=$?"   # two real calls; 0 = overlapped under C2
ART=$(python3 -c "import json;print(json.load(open('run_state/flash_resident.json'))['artifact_dir'])")
python3 -c "
import json,sys
a=[json.loads(l)['host_memory_kib']['MemAvailable']/1024**2 for l in open('$ART/host-memory.jsonl')]
print('samples',len(a),'low-water GiB %.2f'%min(a[-360:]),'now %.2f'%a[-1])"
journalctl -k -b --since "-40 min" --no-pager | grep -cE 'NV_ERR|Xid'       # 0 expected
```
The low-water is the minimum over the last hour of 10 s samples, which
includes the smoke. Compare it with the C1 run's `minimum_mem_available_gib`
in `$INC/stopped-v8-state.json` (`monitor`) or its `host-memory.jsonl`.

## 7. Keep or roll back

**Keep** only if all of these hold. `check-ready` passed within 30 min.
`/get_server_info` shows `max_running_requests 2`, `max_total_num_tokens 262144`
and `cuda_graph_bs_decode [1, 2]`. The smoke exits 0. The steady low-water is
≥ 12 GiB (at least 2 GiB above the 10 GiB floor) and has fallen by no more than
2 GiB against the C1 run. There are no new `NV_ERR`/`Xid` kernel lines. Then
write `$INC/cutover-receipt.json` (template:
`../context-262k-cutover-20260922/cutover-receipt.json`) with the hashes
above, the merge commit, the smoke output and the memory numbers. The owner
then removes `run_state/pause_nara_lane` and `run_state/pause_coordinator`.
Keep watching the low-water for 24 h. If it falls below 12 GiB, roll back.

**Roll back** if any keep criterion fails and the service is not latched
(phase `ready` or `stopped`). The rollback mirrors the cutover:
```bash
env -u MOCK_LLM systemctl --user stop flash-resident.service       # cleanup runs under the v9 pin
python3 -c "import json;s=json.load(open('run_state/flash_resident.json'));print(s['phase'],s.get('cleanup'),s.get('stop_post_cleanup'))"
cp run_state/flash_resident.json "$INC/stopped-v9-state.json"
python3 - <<'EOF'
import json, pathlib
p = pathlib.Path('run_state/flash_resident.json'); s = json.loads(p.read_text())
assert s['phase'] == 'stopped' and s['bundle_sha256'].startswith('1be5d93b'), s['phase']
s['prior_artifact_dir'] = s.pop('artifact_dir')
tmp = p.with_suffix('.tmp'); tmp.write_text(json.dumps(s, indent=2) + '\n'); tmp.replace(p)
EOF
# revert the lab pins: v8 bundle/sha, f0fbb6c0 profile, max_running_requests 1 (config + validator + tests)
git revert --no-edit -m 1 <merge-commit>     # or, for a fast-forward merge: git revert --no-edit <c2-commit>
grep -n "sglang_session_s3_v8.py\|f0fbb6c0" orchestrator/flash_resident.py config/model_deployment.json
.venv-chroma/bin/python -m orchestrator.flash_resident selected; echo "selected=$?"   # 0
env -u MOCK_LLM systemctl --user start flash-resident.service       # ~12.5 min, then check-ready as in §5
```
v8, its profile and every other pinned file are byte-identical, and nothing
in the artifacts directory was modified. So the rollback is only the reverse
pin and handoff. It does not rebuild anything.

## 8. The boot latch (read before starting)

A start that fails after launch sets `phase: fault` with `launch_attempted`.
Causes include a kernel `NV_ERR_NO_MEMORY`/Xid line seen by the guard, the
host floor or PSI tripping, the candidate exiting, or readiness not matching
the expected profile within the 30-minute deadline. **That latches Flash off
for the rest of this boot.** Every later `start` exits 78
(`Flash fault is latched for this boot`), and **neither C2 nor the v8 rollback
can start** until the latch is cleared. Nara and Oracle have no local model
until then.

If it latches:
1. Do not retry and do not edit the state yet. Capture the evidence:
   `cp run_state/flash_resident.json "$INC/v9-fault-state.json"`,
   `journalctl -k -b --no-pager | grep -E 'NV_ERR|Xid' > "$INC/kernel.txt"`,
   and the artifact dir's `readiness-last-diagnostic.json`, `guard.log`
   and `host-memory.jsonl`.
2. If the kernel log has a `system_mem.c` `NV_ERR` line or any Xid, the driver
   fault is real. That calls for an **owner-chosen reboot**. After the
   reboot, start whichever pin is merged (roll the pins back to v8 first if C2
   caused it).
3. If there is no driver fault (a readiness profile mismatch, a reserve or PSI
   stop, or only the known `mem_desc.c:1359` retry lines), **only the owner**
   may clear it, following the manual recovery in
   [FLASH_RESIDENT.md](FLASH_RESIDENT.md) ("Only on an explicit owner request
   ..."). Archive and write a receipt, set `phase` to `stopped`, do the
   handoff and pin rollback of §7, then start once and run `check-ready`.

A readiness mismatch (for example, if the server reports a
`max_running_requests` other than 2) is not detected quickly. `wait_ready`
retries until the 30-minute deadline and then latches.
`readiness-last-diagnostic.json` in the artifact dir names the mismatched key
while it retries. If it shows `mismatch_key` during the load, the owner can stop
the service before the deadline (`systemctl --user stop`). That is an operator
stop, not a fault, so it does not latch. Then roll back.

## Risks

- **Memory (estimated, not measured).** The token pool is fixed at 262,144,
  and the mamba pool is fixed by `max_mamba_cache_size 16` (ssm 1.79 GB,
  unchanged). What grows with running requests:
  - The speculative-verify `intermediate_ssm_state_cache`. It is 0.84 GB at
    C1. One state is 36 linear-attention layers × 48 heads × 128×128 × fp32
    ≈ 108 MiB, so 0.84 GB is about 8 states. That fits 4 draft tokens × 2
    request slots, which is an inference: the SGLang sizing code is inside the
    image and was not read. At C2 it should be 1.27–1.69 GB (3 or 4 slots),
    which adds **0.4–0.85 GB**.
  - One more decode CUDA graph (batch 2) for target-verify and draft-decode.
    The C1 graphs cost 0.157 + 0.127 GB, so this adds about **0.1–0.3 GB**.
  - `req_to_token` rows (1 MiB per slot) and batch-2 decode activations,
    which are negligible.

  The total is about **+0.5–1.2 GiB** of unified memory, which reduces host
  `MemAvailable` one for one. That is against a C1 steady low-water of
  16.8 GiB and a 10 GiB floor. The startup budget after weights was 23.2 GB
  with about 9 GB allocated, so the KV pool should still reach 262,144 tokens.
  §6 checks `max_total_num_tokens` because v9's readiness check compares only
  the requested `max_total_tokens`.
- **Shared pool contention.** Both requests share 262,144 tokens. Today's
  traffic holds about 210K tokens in one context ("full token usage 0.80").
  A second long request can then be queued, or retracted and re-prefilled
  (`retraction_policy length`), which is slower than today's plain queueing.
  A single request can still use the full 262,138-token input limit.
- **Per-request speed.** Two decodes share the GPU, so each is slower than it
  would be alone. Total throughput should rise. The smoke's timings give a
  first reading. This is not a benchmark.
- **Stale consumers.** Any long-running process that imported
  `agent_wrapper.deployment` keeps the C1 validator until restarted. The
  supervisor restarts `nara-daemon`. Restart the UI backend by hand if it
  misreports. The preregistered payoff studies (`experiments/payoff_*`) already
  fail closed on the 32K/20 GiB deployment, and they also hard-code
  `max_running_requests == 1`. Only the owner may amend them.
- **v9 `run_session` record.** v9's `run_session` launch record still says
  `context_length 32768`, a line inherited unchanged from v8. That path is the
  evaluation mode and the resident never uses it. It was left as is to keep
  the diff minimal.
