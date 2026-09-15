# Research operations: known-opponent utility study

The previously activated September 14 campaign has one registered topic and
one exact linked iteration, so its topic queue is exhausted. Its manifest and
iteration record remain unchanged. The successor
`v2-known-opponent-utility-20260915` is separately registered at
[`research_campaign_v2_known_opponent_utility_20260915.json`](../experiments/research_campaign_v2_known_opponent_utility_20260915.json)
with manifest SHA
`c0b09e366bf7b8ffe7af58bf7b00e4c0fb7f33eb83a5111f2a465c12fc0be4f7`.
It has three distinct, eligible preregistered topics and one measured
model-behavior question. Registration does not activate it.

The operator first records an immutable closure receipt for the old campaign
using `schema/research_campaign_closure.schema.json`, archives the exact old
activation-pointer bytes/SHA, and atomically replaces
`run_state/active_research_campaign.json` with a new
`research-campaign-activation/v1` pointer naming the successor's ID, SHA,
current UTC activation time and actor. `load_active_campaign()` must validate
the new pointer before the first iteration. No historical iteration is
relinked by topic text or date. The ordinary Nara run should consume only the
first registered successor topic. Its novelty and critic result can remain
`paper_prior_exists` or undecidable without blocking an honest **applied
behavioral** pilot.

After one exact linked iteration, `project_research_ops_status()` proposes
`freeze_and_run_registered_empirical_study` before choosing a second topic.
The study is [preregistered](../experiments/PREREG_known_opponent_utility_response_2026-09-15.md)
as three disclosed opponent scripts × two declared utilities × two focal seat
blocks, 12 episodes and at most108 calls in900s. The existing
`optimal_control.py` computes the finite-horizon response and regret.
Use a current `validate_resident_qualification_files(..., require_passed=True)`
or `validate_flash_qualification_files(..., require_passed=True)` result with
an allowlisted `transport.LocalEndpoint` whose artifact SHA matches that
receipt. Freeze the endpoint, exact generation policy, seed, max64 output
tokens, ≤60s per-call timeout and the all-task manifest **before** any model
call:

```python
from experiments.known_opponent_utility import pilot

manifest = pilot.freeze_manifest(
    source_root=CANONICAL_SOURCE_ROOT,
    endpoint=QUALIFIED_LOCAL_ENDPOINT,
    registered_admission=EXACT_SHARED_VALIDATOR_RESULT,
    policy=REGISTERED_GENERATION_POLICY,
    seed=REGISTERED_SEED,
    max_tokens=64,
    per_call_timeout_s=30,
)
pilot._check_manifest(manifest)
# Write pilot._raw_json(manifest) + b"\n" with exclusive creation to an
# immutable study-plan child; record its exact raw SHA and controller source.
```

The model call is an operator-controlled, finite study window with existing
qualification, safety monitor and restoration checks. Call
`pilot.run_pilot(manifest, output=IMMUTABLE_RUN_CHILD,
admission_gate=EXACT_CURRENT_SHARED_VALIDATOR_CALL,
safety_check=LIVE_CONTROLLER_CHECK, cancel_event=CONTROLLER_CANCEL_EVENT)`.
The producer writes every attempted request, raw private SSE and public hash
receipt. It stops each episode at the first malformed action; unissued rounds
remain unknown and no full-horizon regret is invented for a prefix. An
unfinished schedule is a partial observation, not an admitted empirical pilot.

After exact restoration, run the read-only
`admission.validate_pilot(IMMUTABLE_RUN_CHILD)` from the frozen source version.
It replays private SSE, resolved requests, exact scripted history, action
parsing and complete-episode DP oracle. Only `admission_eligible=True` may
feed the existing LOOP_V0 result bridge. Its output is content-free and keeps
`scientific_novelty_claimed=False`. Select the **second still eligible**
preregistered topic and dry-run
`python -m experiments.known_opponent_utility.loop_bridge --pilot-output
IMMUTABLE_RUN_CHILD --topic-id topic-known-retain-utility-001 --dry-run`.
The same command with `--live` is a separate operator-controlled Nara
iteration; it requires the exact active manifest and complete loop source,
then calls ordinary `nara.run_iteration(experiment_outcome=...)`. The normal
novelty, critic, evidence ladder and human-valid gate adjudicate that record.
The third topic remains queued for a later frozen question or disposition.

The new `daily_arxiv_job.py` keeps overlapping three-day fetches and the
existing BGE-M3 embedder. It writes started/terminal receipts, retries/HTTP
failure codes, a SHA-bound last successful input cache and an explicit
`cache_reused_as_fresh=False`; a failed fetch does not inject cached papers
into today's collection. The existing 03:00 UTC cron entry can keep calling
`cron/daily-arxiv.sh` after integration. Today's 03:00 failure is displayed
from the older cron log as `fetch_failed_log_observed`, with raw log SHA and
`receipt_bound=False`. The first new successful/failing invocation starts
the stronger receipt chain; no result is invented for the legacy log.

The separate prospective H1 public BTCUSDT plan
`h1-btcusdt-rest-20260915-lab8h` covers18:05–20:05UTC with due21:15UTC.
It is a known-prior market-data application under its own plan/source/quote
gate. It can supply an external empirical continuation and ingestion health,
but its REST reference score is not a local-agent utility result, executable
paper fill, novelty proof or live-trade permission.
