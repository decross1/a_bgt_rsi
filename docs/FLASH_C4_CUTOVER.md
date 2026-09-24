# Flash C4 cutover: four running requests in the same 262K pool

Status: **prepared offline, not executed.** The owner runs this with the
meta-oracle. Nothing here has touched the live server. This runbook extends
[FLASH_C2_CUTOVER.md](FLASH_C2_CUTOVER.md): it takes the live server from
helper v8 (C1) straight to helper v10 (C4). Helper v9 (C2) stays in the prep
directory, byte-identical, as a fallback pin (§7).

**Goal.** Oracle, Nara and their subagents share Flash. Today the server runs
one request at a time (`max_running_requests 1`). This change lets it run
four, in the same 262,144-token pool. Context, KV pool, MTP (steps 3), BF16
KV, chunked prefill 2048, `mem_fraction_static` 0.83, floors, guard and
container limits stay the same. The one extra change is the mamba state pool,
from 16 to 24 slots. Without it SGLang would silently run four requests as
three (see "Why the mamba pool grows").

| Item | Live (v8, C1) | Fallback (v9, C2) | Prepared (v10, C4) |
| --- | --- | --- | --- |
| Helper | `sglang_session_s3_v8.py` `606d05f201b84b01441e6e23b98ed0c66c6a92faa81300b9d796bf54a2a4466c` | `sglang_session_s3_v9.py` `1be5d93b88bd26b6f8f8514088375df9c986d656d9aafffb8a838711b7d101b7` | `sglang_session_s3_v10.py` `e26d2aa2330a6c2e37c4629aa7074b6b7804f07f9239239bcf90f73244b90aa5` |
| Profile | `nextn-262k-c1-s3.json` `f0fbb6c09ff926dd17d8bb9787e1f52632e5fba9135431a3d01222be785a81bf` | `nextn-262k-c2-s3.json` `495f1f3c59f559185720257538646354a5995ab9ca82e042565ae989ca4452a3` | `nextn-262k-c4-m24-s3.json` `45546ef777af74a264d31e5b5cfd5b2f68f0bddf2954d4f243bd7ea9b3dae903` |
| Serve argv | `--max-running-requests 1`, `--cuda-graph-bs-decode 1`, `--max-mamba-cache-size 16` | `2`, `1 2`, `16` | `4`, `1 2 4`, `24` |
| Readiness | requested `max_running_requests` echo | same | echo **and** `internal_states[0].effective_max_running_requests_per_dp == 4` **and** `max_total_num_tokens == 262144` |

The C4 profile is the C1 profile with two values changed
(`max_running_requests` 1 to 4, `max_mamba_cache_size` 16 to 24). v10 is v9
with these edits, in `sglang-fallback-prep/sglang_session_s3_v9_to_v10.diff`:

- the `PROFILE` path and `PROFILE_SHA256`;
- `server_profile()` (live readiness) expects `max_running_requests 4` and
  `max_mamba_cache_size 24`;
- `server_profile()` also requires `max_total_num_tokens == 262144` and
  `internal_states[0].effective_max_running_requests_per_dp == 4` (an `int`),
  so a server that SGLang capped below four fails readiness instead of passing
  as C4;
- `run_session`'s launch record says `max_running_requests 4` and its
  qualification text names C4 and the mamba pool.

The adapter (`guard_uid1000_alloc_v5.py`), guard, sources lock, runtime locks
and control sources are unchanged, and v10 pins them at the same hashes as v8
and v9 (`test_sglang_session_s3_v10.py` in the prep dir checks this offline).

**Serve argv, checked offline** with the pinned `source/runtime`
(`load_profile` + `runtime.entrypoint.build_all`, the path `source/scripts/guard.py`
uses). The environment is identical for C1, C2 and C4. The full argv diff is
`sglang-fallback-prep/c4-serve-argv-c1-to-c4.diff`:

```diff
 --cuda-graph-bs-decode
 1
+2
+4
 ...
 --max-running-requests
-1
+4
 ...
 --max-mamba-cache-size
-16
+24
```

The entrypoint fixes the decode graph list as the powers of two up to
`max_running_requests` (`source/runtime/entrypoint.py:537`). It cannot be
chosen, and a batch of three pads to the bs=4 graph.

**Where the readiness keys come from** (pinned image
`lmsysorg/sglang:nightly-dev-20260907-30705c00`, read with `docker exec … grep`
only, paths under `/sgl-workspace/sglang/python/sglang/srt`):

- `managers/scheduler.py:4959`: `ret["effective_max_running_requests_per_dp"] = self.max_running_requests`,
  in `get_internal_state()`. `self.max_running_requests` is the worker's value
  after `resolve_max_num_reqs` (`scheduler.py:1146-1158`), and
  `/get_server_info` returns it as `internal_states[0]` (`entrypoints/http_server.py:822-833`).
- `managers/scheduler.py:1832`: `max_total_num_tokens` in the scheduler
  handshake, merged into the top level of `/get_server_info`.
- `mem_cache/kv_cache_configurator.py:2184-2221`: `resolve_max_num_reqs` caps
  running requests at `max_mamba_cache_size // mamba_ratio` and logs
  `max_running_requests is capped to %d by the mamba state …`. The ratio is 5
  on this build (3 base, `:168`, plus 2 for the overlap schedule's extra
  buffer).

The live v8 `server-info.json` (`runtime/resident-20260922T110543Z/`) carries
both keys: `max_total_num_tokens 262144` and
`internal_states[0].effective_max_running_requests_per_dp 1`.

**Why the mamba pool grows.** With `max_mamba_cache_size 16` the scheduler runs
at most 16 // 5 = 3 requests. A C4 launch with 16 slots would start, report
`max_running_requests 4` (the argument echo) and run three. v8's and v9's
readiness check would pass it. 20 slots is the minimum for four. 24 keeps
about 12 slots for radix-cached conversation tips after four running requests
take about 12 (3 each), which is roughly today's cache headroom. The validator
allows 4 to 64.

**Live path.** As for C2. The supervisor loads the helper. The helper runs
only the adapter, which wraps the pinned `source/scripts/guard.py`, which uses
the container `runtime` profile validator (it accepts 1, 2, 4 and 8 running
requests and 4 to 64 mamba slots). The `run_sglang_supplement_s3*.py`,
`sglang_session_s3.py` and practical, screen and canary runners are not
imported or executed by v8, v9 or v10. `source/scripts/runtime_context.py` is
only hash-checked on the resident path.

**Lab pins** (branch `claude/flash-c4-prep-20260924`, which also merges the
C2 prep branch):

- `orchestrator/flash_resident.py`: `BUNDLE`/`BUNDLE_SHA` to v10, the
  `selected()` profile digest to `45546ef7…`, and a new
  `BUNDLE_MAX_RUNNING_REQUESTS = 4`. `selected()` refuses a deployment whose
  count differs from the pinned profile's.
- `config/model_deployment.json`: `max_running_requests 4`,
  `profile_sha256 45546ef7…`. The document has no mamba field, and its schema
  admits none.
- `agent_wrapper/deployment.py`: `max_running_requests` must be an `int` in
  `{1, 2, 4}`, and the loaded deployment carries the declared value. Rolling
  back to C1 or C2 needs no code edit there. 3, 8, a bool, a string or a
  missing value fail closed.
- `tools/flash_concurrency_smoke.py`: sends N = the configured count of real
  streamed calls and passes only if the server reports N requested and N
  effective, `max_total_num_tokens` equals the configured context, and (for
  N > 1) all N streams decoded at one instant. It reports per-stream TTFT,
  decode time and rates, and how many stream pairs overlapped.

In the paths below, `REPO=/home/decross1/projects/a_bgt_rsi`,
`PREP=/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-18/flash-personal-recovery/sglang-fallback-prep`
and `INC=/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-18/flash-personal-recovery/c4-cutover-$(date -u +%Y%m%d)`.
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
   262K low-water is 16.8 GiB against the 10 GiB floor, and C4/M24 is
   estimated to cost about 2.2–2.45 GiB more (table below). The supervisor
   also enforces 104 GiB `MemAvailable` and 100 GiB `MemFree` before launch,
   after the stop.
   ```bash
   grep -E 'MemAvailable|MemFree' /proc/meminfo
   ```
6. **Pins intact.** No output means everything matches:
   ```bash
   cd "$PREP" && sha256sum -c --quiet - <<'EOF'
   606d05f201b84b01441e6e23b98ed0c66c6a92faa81300b9d796bf54a2a4466c  sglang_session_s3_v8.py
   1be5d93b88bd26b6f8f8514088375df9c986d656d9aafffb8a838711b7d101b7  sglang_session_s3_v9.py
   e26d2aa2330a6c2e37c4629aa7074b6b7804f07f9239239bcf90f73244b90aa5  sglang_session_s3_v10.py
   f0fbb6c09ff926dd17d8bb9787e1f52632e5fba9135431a3d01222be785a81bf  nextn-262k-c1-s3.json
   495f1f3c59f559185720257538646354a5995ab9ca82e042565ae989ca4452a3  nextn-262k-c2-s3.json
   45546ef777af74a264d31e5b5cfd5b2f68f0bddf2954d4f243bd7ea9b3dae903  nextn-262k-c4-m24-s3.json
   c2ee1dbf3eeaf7d69e4133825e2d4426c2e0e96c307dd1e1e314859deadbda73  guard_uid1000_alloc_v5.py
   EOF
   sha256sum -c --quiet c4-prep-sha256-after.txt   # whole prep dir except runtime/, as reviewed
   cd "$REPO"
   ```
7. **Main checkout clean for the touched files.** No output expected:
   ```bash
   git status --porcelain -- orchestrator/flash_resident.py config/model_deployment.json \
       agent_wrapper/deployment.py tests/test_flash_resident.py tests/test_flash_deployment_routing.py \
       tools/flash_concurrency_smoke.py tests/test_flash_concurrency_smoke.py
   git log --oneline -2 claude/flash-c4-prep-20260924    # the C4 commit on top of the C2 merge
   ```

## 1. Stop under v8 (before any merge)

Stop **before** merging. The unit's `ExecStopPost` runs `flash_resident cleanup`
from the checked-out code. If v10 were already pinned, cleanup would refuse
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

Move `artifact_dir` to `prior_artifact_dir`, so v10 neither re-validates nor
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
git branch --show-current; git log --oneline -1                   # record both in the receipt
git merge --ff-only claude/flash-c4-prep-20260924 || git merge --no-ff claude/flash-c4-prep-20260924
git log --oneline -3                                             # note the C4 commit and the C2 merge commit
.venv-chroma/bin/python -m orchestrator.flash_resident selected; echo "selected=$?"   # 0
MOCK_LLM=1 PYTHONDONTWRITEBYTECODE=1 .venv-chroma/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_flash_resident.py tests/test_flash_deployment_routing.py tests/test_flash_concurrency_smoke.py
.venv-chroma/bin/python tools/flash_concurrency_smoke.py --dry-run | grep -E 'configured|pass_rule'   # 4
```
The branch brings two commits: the C2 prep merge and the C4 commit on top.
The merge lands on whatever branch the live checkout has checked out. That
checkout carries other sessions' uncommitted edits, which the merge leaves
alone. If anything fails, undo the merge with `git reset --keep ORIG_HEAD`.
Never use `--hard`, because it would discard those edits. Then start v8 as in
§5. The handed-off state has no `artifact_dir`, so v8 starts without a handoff
refusal.

## 5. Start and wait for readiness

```bash
grep -E 'MemAvailable|MemFree' /proc/meminfo          # expect ~104+ GiB available with Flash down
env -u MOCK_LLM systemctl --user start flash-resident.service
# Cold 262K load is ~12.5 min (LoadEvictor runs until readiness; hard deadline 30 min).
for i in $(seq 1 60); do
  .venv-chroma/bin/python -m orchestrator.flash_resident check-ready && { echo READY; break; }
  python3 -c "import json;s=json.load(open('run_state/flash_resident.json'));print(s['phase'],s.get('error'))"
  ART=$(python3 -c "import json;print(json.load(open('run_state/flash_resident.json')).get('artifact_dir',''))")
  [ -f "$ART/readiness-last-diagnostic.json" ] && python3 -c "import json;d=json.load(open('$ART/readiness-last-diagnostic.json'));print(d.get('mismatch_key'),d.get('expected'),d.get('observed'))"
  sleep 30; done
```
Watch `journalctl --user -u flash-resident.service -f` in another terminal.
If the diagnostic shows a `mismatch_key` once the server answers (for example
`internal_states[0].effective_max_running_requests_per_dp` with observed `3`),
the server came up capped. Stop it at once (§8, operator stop) rather than
wait for the 30-minute latch.

The supervisor restarts `nara-daemon.service` at readiness, so the daemon
picks up the new deployment validator. If the UI backend reports a
deployment or profile mismatch, restart it:
`ui/scripts/ui-services.sh stop && ui/scripts/ui-services.sh start`.

## 6. Verify C4 and memory

```bash
curl -s --noproxy '*' http://127.0.0.1:30080/get_server_info | python3 -c "
import json,sys; d=json.load(sys.stdin)
print({k: d.get(k) for k in ('max_running_requests','max_mamba_cache_size','max_total_num_tokens','context_length','cuda_graph_bs_decode','max_req_input_len')})
print('effective', d['internal_states'][0].get('effective_max_running_requests_per_dp'))
print(d['internal_states'][0].get('memory_usage'))"
# expect max_running_requests 4, max_mamba_cache_size 24, max_total_num_tokens 262144,
#        cuda_graph_bs_decode [1, 2, 4], max_req_input_len 262138, effective 4
CID=$(python3 -c "import json;print(json.load(open('run_state/flash_resident.json'))['container_id'])")
docker logs "$CID" 2>&1 | grep -E 'capped to|Mamba Cache is allocated|intermediate_ssm_state_cache|KV Cache is allocated|max_running_requests=|avail mem=' | tail -10
# no 'capped to' line. C1 reference: ssm 1.79GB, intermediate_ssm_state_cache 0.84GB,
# KV 3.00+3.00GB (+0.25+0.25 draft), available_gpu_mem 23.95 GB.
# C4/M24 expected (source formula): ssm about 2.64GB, intermediate_ssm_state_cache about 2.11GB, KV unchanged.
.venv-chroma/bin/python tools/flash_concurrency_smoke.py > "$INC/smoke.json"; echo "smoke=$?"   # four real calls; 0 = all four overlapped under C4
python3 -c "import json;r=json.load(open('$INC/smoke.json'));print(r['server_checks']);print(r['overlapped'],r['overlap_s'],r['overlapping_pairs'],'/',r['pairs']);[print(x['stream'],x['ttft_s'],x['decode_s'],x['completion_tokens_per_s']) for x in r['requests']]"
ART=$(python3 -c "import json;print(json.load(open('run_state/flash_resident.json'))['artifact_dir'])")
python3 -c "
import json,sys
a=[json.loads(l)['host_memory_kib']['MemAvailable']/1024**2 for l in open('$ART/host-memory.jsonl')]
print('samples',len(a),'low-water GiB %.2f'%min(a[-360:]),'now %.2f'%a[-1])"
journalctl -k -b --since "-40 min" --no-pager | grep -cE 'NV_ERR|Xid'       # 0 expected
```
The low-water is the minimum over the last hour of 10 s samples, which
includes the smoke. Compare it with the C1 run's `minimum_mem_available_gib`
in `$INC/stopped-v8-state.json` (`monitor`) or its `host-memory.jsonl`
(C1 steady low-water: 16.8 GiB, measured).

## 7. Keep or roll back

**Keep** only if all of these hold:

- `check-ready` passed within 30 min.
- `/get_server_info` shows `max_running_requests 4`, `max_mamba_cache_size 24`,
  `max_total_num_tokens 262144`, `cuda_graph_bs_decode [1, 2, 4]`, and
  `internal_states[0].effective_max_running_requests_per_dp` **4**. The
  container log has no `capped to` line.
- The smoke exits 0 (all four streams overlapped; server checks all `ok`).
- The steady low-water is **≥ 12 GiB** (at least 2 GiB above the 10 GiB floor)
  and has fallen by **no more than 3 GiB** against the C1 run.
- There are no new `NV_ERR`/`Xid` kernel lines.

Then write `$INC/cutover-receipt.json` (template:
`../context-262k-cutover-20260922/cutover-receipt.json`) with the hashes
above, the merge commit, the smoke output and the memory numbers. The owner
then removes `run_state/pause_nara_lane` and `run_state/pause_coordinator`.
Keep watching the low-water for 24 h. If it falls below 12 GiB, roll back.

**Roll back to v8 (C1)** if any keep criterion fails and the service is not
latched (phase `ready` or `stopped`). The rollback mirrors the cutover:
```bash
env -u MOCK_LLM systemctl --user stop flash-resident.service       # cleanup runs under the v10 pin
python3 -c "import json;s=json.load(open('run_state/flash_resident.json'));print(s['phase'],s.get('cleanup'),s.get('stop_post_cleanup'))"
cp run_state/flash_resident.json "$INC/stopped-v10-state.json"
python3 - <<'EOF'
import json, pathlib
p = pathlib.Path('run_state/flash_resident.json'); s = json.loads(p.read_text())
assert s['phase'] == 'stopped' and s['bundle_sha256'].startswith('e26d2aa2'), s['phase']
s['prior_artifact_dir'] = s.pop('artifact_dir')
tmp = p.with_suffix('.tmp'); tmp.write_text(json.dumps(s, indent=2) + '\n'); tmp.replace(p)
EOF
# revert the lab pins, newest first: the C4 commit, then the C2 prep merge (its first parent is main)
git revert --no-edit <c4-commit>
git revert --no-edit -m 1 <c2-prep-merge-commit>
# (if §4 made its own --no-ff merge commit, revert that one instead: git revert --no-edit -m 1 <merge-commit>)
grep -n "sglang_session_s3_v8.py\|f0fbb6c0\|max_running_requests" orchestrator/flash_resident.py config/model_deployment.json
.venv-chroma/bin/python -m orchestrator.flash_resident selected; echo "selected=$?"   # 0
env -u MOCK_LLM systemctl --user start flash-resident.service       # ~12.5 min, then check-ready as in §5
```
After the second revert, `agent_wrapper/deployment.py` is back to C1's exact
check. That is expected, and C1 loads under it.

**Fall back to v9 (C2) instead** when C4 fails only on memory or throughput and
two lanes would fit. Run the same stop, archive and handoff (`e26d2aa2`), then
revert only the C4 commit:
```bash
git revert --no-edit <c4-commit>
grep -n "sglang_session_s3_v9.py\|495f1f3c" orchestrator/flash_resident.py config/model_deployment.json
.venv-chroma/bin/python -m orchestrator.flash_resident selected; echo "selected=$?"   # 0
```
Then start and verify as in the C2 runbook §5–§7 (`max_running_requests 2`,
`cuda_graph_bs_decode [1, 2]`). v9's readiness does not check the effective
key, but 16 // 5 = 3 ≥ 2, so C2 cannot be capped. Check it by hand anyway
(`effective` 2 in the §6 command).

v8, v9, their profiles and every other pinned file are byte-identical, and
nothing in the artifacts directory was modified. So either rollback is only
the reverse pin and handoff. It does not rebuild anything.

## 8. The boot latch (read before starting)

A start that fails after launch sets `phase: fault` with `launch_attempted`.
Causes include a kernel `NV_ERR_NO_MEMORY`/Xid line seen by the guard, the
host floor or PSI tripping, the candidate exiting, or readiness not matching
the expected profile within the 30-minute deadline. **That latches Flash off
for the rest of this boot.** Every later `start` exits 78
(`Flash fault is latched for this boot`), and **neither C4 nor a rollback can
start** until the latch is cleared. Nara and Oracle have no local model until
then.

If it latches:
1. Do not retry and do not edit the state yet. Capture the evidence:
   `cp run_state/flash_resident.json "$INC/v10-fault-state.json"`,
   `journalctl -k -b --no-pager | grep -E 'NV_ERR|Xid' > "$INC/kernel.txt"`,
   and the artifact dir's `readiness-last-diagnostic.json`, `guard.log`
   and `host-memory.jsonl`.
2. If the kernel log has a `system_mem.c` `NV_ERR` line or any Xid, the driver
   fault is real. That calls for an **owner-chosen reboot**. After the
   reboot, start whichever pin is merged (roll the pins back first if C4
   caused it).
3. If there is no driver fault (a readiness profile mismatch, a reserve or PSI
   stop, or only the known `mem_desc.c:1359` retry lines), **only the owner**
   may clear it, following the manual recovery in
   [FLASH_RESIDENT.md](FLASH_RESIDENT.md) ("Only on an explicit owner request
   ..."). Archive and write a receipt, set `phase` to `stopped`, do the
   handoff and pin rollback of §7, then start once and run `check-ready`.

A readiness mismatch is not detected quickly. `wait_ready` retries until the
30-minute deadline and then latches. The v10 mismatches to expect are
`internal_states[0].effective_max_running_requests_per_dp` (a capped
scheduler), `max_total_num_tokens` (a KV pool below 262,144) or
`max_running_requests`/`max_mamba_cache_size` (a wrong profile).
`readiness-last-diagnostic.json` in the artifact dir names the mismatched key
while it retries (the §5 loop prints it). If it shows `mismatch_key` during
the load, the owner can stop the service before the deadline
(`systemctl --user stop`). That is an operator stop, not a fault, so it does
not latch. Then roll back.

## Memory and throughput model

From the read-only investigation of the live container on 2026-09-24 (labels:
**source** = read from the pinned SGLang code, **measured** = live logs or
metrics, **estimated** = model, not measured). One linear-attention request
state across the 36 GDN layers is 0.1055 GiB (source).

Buffers that scale with concurrency (GiB; R = effective running requests,
M = `max_mamba_cache_size`, D = 4 draft tokens):

| buffer | formula | C1 (live) | C2 | C4 |
|---|---|---|---|---|
| intermediate_ssm, D=4 | S·(R+1)·D | **0.84** (measured) | 1.27 (+0.42) | 2.11 (+1.27) |
| ssm_state (mamba slots) | S·(M+1) | 1.79 (M=16, measured) | 1.79 (M=16) | 2.64 (M=24) |
| conv_state | about 2.4 MiB·(M+1) | 0.04 | 0.04 | 0.05 |
| intermediate_conv_window | about 5 MiB·(R+1) | 0.01 | 0.015 | 0.025 |
| req_to_token | (R+1)·1 MiB | ~0.002 | ~0.003 | ~0.005 |

Deltas against the live C1 (host `MemAvailable` falls about one for one on
unified memory; C1 steady low-water 16.8 GiB, measured):

| item | C2 (v9 fallback) | **C4, M=24 (v10)** |
|---|---|---|
| intermediate_ssm (source) | +0.42 | +1.27 |
| ssm/conv slots (source) | 0 | +0.85 |
| CUDA graphs (estimated) | +0.03–0.15 | +0.08–0.30 |
| conv_window, req_to_token, bs activations (source/estimated) | +0.01 | +0.02 |
| **total delta** | **+0.46–0.58** | **+2.2–2.45** |
| expected low-water (estimated) | **16.2–16.35** | **14.35–14.6** |
| expected aggregate decode (estimated) | about 47 tok/s | about 69 tok/s |
| expected per-stream decode (estimated) | about 24 tok/s | about 17 tok/s |

C1 single-stream decode is 33 tok/s (measured, mean accept length 3.21 per
verify). MTP steps 3 still pays at C4 (estimated 1.6× over no MTP). The
startup budget after weights was 23.2 GB with about 9 GB allocated at C1, so
the KV pool should still reach 262,144 tokens with the extra 2.1 GiB; the new
`max_total_num_tokens` readiness check fails closed if it does not.

## Risks

- **Memory (estimated, not measured).** No run of this image at more than one
  request exists in the artifacts. The table predicts a low-water of
  14.35–14.6 GiB, inside the keep criterion, but CUDA graph growth for
  bs [1, 2, 4] and padding cost are estimates.
- **Shared pool contention.** Four requests share 262,144 tokens. Today's
  Oracle traffic can hold about 210K tokens in one context. A second long
  request then queues, or decode growth forces `retract_decode`
  (`retraction_policy length`: fewest output tokens first), which re-prefills
  at about 1.6–2.2k tok/s (measured), so 100K tokens cost about a minute.
  Keep total resident context at or below about 240K with a **client-side**
  per-lane budget (the validator has no per-request cap). That budget is not
  part of this branch.
- **Radix mamba hits.** Each running request takes about 3 mamba slots out of
  the cache. M=24 leaves about 12 for cached tips at four running requests,
  roughly today's number. Hit rates should stay near today's 99.6% but are
  unmeasured at C4.
- **Per-request speed.** Four decodes share the GPU, so each is slower than it
  would be alone (about 17 versus 33 tok/s, estimated). Total throughput
  should roughly double. C4 only pays off if at least three requests are
  regularly concurrent. The smoke's timings are a first reading, not a
  benchmark.
- **Stale consumers.** Any long-running process that imported
  `agent_wrapper.deployment` keeps its old validator until restarted. The
  supervisor restarts `nara-daemon`. Restart the UI backend by hand if it
  misreports. The preregistered payoff studies (`experiments/payoff_*`) already
  fail closed on the 32K/20 GiB deployment, and they also hard-code
  `max_running_requests == 1`. Only the owner may amend them.
- **v10 `run_session` record.** As in v9, the evaluation-mode launch record
  still says `context_length 32768`. The resident never uses that path.
