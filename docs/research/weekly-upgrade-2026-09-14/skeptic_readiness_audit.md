# Qwen builder drift and skeptic-readiness audit

**Observed:** 2026-09-14T04:44Z

**Scope:** read-only inspection of the canonical call, iteration, and run-log
ledgers plus a pure replay of the recorded retrieval-relevance inputs. No
model call, scientific-record write, service change, or promotion occurred.

The root's later [machine-readable seven-day replay](skeptic_readiness_report.json)
reproduces 59 blocked rows, 59 clean counterfactual relevance results, and 14
recorded raw-survives overrides in that smaller window. It binds both source
bytes and audit/relevance implementation hashes. These counterfactual results
are eligibility measurements, not scientific correctness judgments.

## Decision

The Qwen skeptic is wired and both checked-in production launch definitions
configure it as armed. Code and ledger inspection do not prove the environment
of the process that is running now. Regardless, current recorded traffic cannot
reach the seam: every one of the 59 completed iteration records from 2026-09-07
through the snapshot was marked `low_confidence=true`, and none could satisfy
the clean-`survives` precondition. This is an upstream eligibility blockade,
not merely sparse skeptic traffic.

The active Qwen builder also had real model drift. Its implicit model was still
Qwen3.6 while the `vllm-qwen` registry default is Qwen3.8. The accompanying
patch makes the builder inherit `VLLM_QWEN_MODEL`, fall back to the registry's
current Qwen3.8 name, and retain `QWEN_MODEL` as the highest-precedence explicit
builder/challenger override. Historical model-A labels in
`bench/critic_eval/qwen_ab.py` remain unchanged because they identify the model
that actually produced that historical arm.

## Code-backed path and prerequisites

The active path is:

```text
coordinator / daemon
  -> Nara dispatches critic_loop_v0
  -> Gemma critic sub-agent returns a verdict
  -> retrieval coverage may override survives to undecidable
  -> only final survives + low_confidence=false reaches _maybe_run_skeptic
  -> NARA_SKEPTIC=1 selects the skeptic seam
  -> NARA_DEBATE=1 selects bounded debate
  -> challenger defaults to vllm-qwen / Qwen3.8
```

The decisive conditions are visible in code:

- `cron/run-coordinator.sh:95-111` and `systemd/nara-daemon.service:25-33`
  declare `NARA_SKEPTIC=1` and `NARA_DEBATE=1`. This establishes the
  checked-in launch configuration, not the active process environment.
- `workers/critic_loop_v0.py:733-762` converts a raw `survives` to
  `undecidable` when retrieval is not category `ok` or is low-confidence.
- `workers/critic_loop_v0.py:776-779` calls the skeptic only after that
  conversion, when the final verdict still equals `survives` and
  `low_confidence` is false.
- `workers/critic_loop_v0.py:419-466` applies the environment gate and chooses
  debate versus a single-shot attack.
- `agent_wrapper/backends/qwen_vllm.py:25-34` resolves the active registry
  model from `VLLM_QWEN_MODEL`, currently falling back to
  `qwen3.8-27b-nvfp4-mtp`.

This also distinguishes the independent skeptic from the ordinary critic.
`critic_loop_v0` itself is a Gemma sub-agent unless `CRITIC_BACKEND` is set;
Qwen sits behind the conditional post-critic seam. Seeing
`subagent=critic_loop_v0, backend=vllm-gemma` is therefore expected and does
not show that the independent skeptic ran.

## Frozen metadata findings

The canonical files were read at the timestamp above. Their snapshot hashes
were:

| Source | SHA-256 |
|---|---|
| `logs/calls.jsonl` | `9356d32696023d4b68581ac3bf63439c59eaf0556a2222ccc9fc4c5b4922e51b` |
| `memory/loop_memory.jsonl` | `920bcee938672310327d9f29a93a65598d663c1bd59f1966e7b3484599e5b167` |
| `run_state/week1.run.jsonl` | `512eecce57f7423144148e1a43dd09b4d32ba654db5b34a6b7eb19d57c85adcd` |

Observed aggregates:

| Window / signal | Result |
|---|---:|
| Wrapper calls from 2026-09-07 through snapshot | 959 |
| Those calls attributed to `vllm-qwen` or a Qwen model | 0 |
| Completed loop-memory rows in the same window | 59 |
| `off_domain`, `low_confidence=true` rows | 59 |
| Final `undecidable` / `restated` rows | 54 / 5 |
| Rows since 2026-08-27 | 147 |
| `off_domain`, `low_confidence=true` rows since 2026-08-27 | 146 |
| Raw `survives` changed to `undecidable` by that gate since 2026-08-27 | 43 |
| Historical rows carrying a skeptic verdict | 62 |
| Historical skeptic rows attributed to Qwen3.8 | 23 |
| Last loop-memory skeptic verdict | 2026-08-25T07:41:15Z |
| Last Qwen-attributed wrapper call of any role | 2026-09-05T06:32:27Z |

The last Qwen call was a bounded lab packet, so it shows that Qwen3.8 was
reachable then. It does not establish service health at this snapshot. The
absence of recent skeptic calls also does not imply a backend failure: no
recent record passed the eligibility predicate that would attempt one.

The recent block is specifically R0 topicality. All 59 rows in the seven-day
window carry `topicality="off"`, `category="off_domain"`, and
`rule_fired="R0"`. This occurs before the independent skeptic. The repository
already contains an inactive counterfactual seam:
`workers/retrieval_relevance.py:391-412` makes `NARA_R0_ADVISORY=1` retain the
primary topicality result as an advisory while letting the lexical/cosine
ladder determine confidence. Neither checked-in launcher declares that setting.

## Scope mismatch must be tested before demoting the gate

A root follow-up inspected the primary gate itself. In the same seven-day
window, all 89 calls tagged `topicality_check` contained parseable JSON with
`domain="off"`. These include extra checks within iterations, so their count
is not the 59 completed-iteration denominator. This is not evidence of a
parser failure silently mapping missing output to rejection.

`orchestrator/topicality.py` explicitly admits game theory and learning in
games, while excluding claims primarily about ML infrastructure/distributed
systems. The six most recent recorded hypotheses instead concern collaborative
classification, network convergence and robustness. The sampled rejection
reasons identify that distinction. These observations support a **possible
topic-generation/domain-contract mismatch**, rather than proving an erroneous
classifier. No raw hypothesis or retrieved paper text is republished here.

The owner has been asked whether the intended scope remains game theory or
includes collaborative ML. If it remains game theory, first fix or constrain
the upstream topic/proposal route. If the broader ML topic is intended,
evaluate a revised explicit domain contract with both positive anchors and
off-topic traps. Neither branch justifies declaring all newly admitted rows
scientifically valid. The R0-advisory replay below is a diagnostic counterfactual,
not a recommended blanket bypass.

## What pure snapshot/replay can and cannot diagnose

A pure replay is sufficient to diagnose the dormant route without writing live
memory. Re-running only the pure `retrieval_relevance.relevance()` function on
the 147 frozen rows since 2026-08-27, with their stored neighbors, hypotheses,
and anchor cosine but with primary R0 demoted, produced:

- 145 rows replayed as `category=ok, low_confidence=false`;
- 1 remained `off_domain, low_confidence=true` under the lexical gate;
- 1 remained `empty, low_confidence=true` because its retrieval was absent.

That result locates the blockade at R0 and proves the stored evidence is rich
enough to compute counterfactual eligibility. It does **not** establish that
145 live critics would return `survives`: the original low-confidence warning
was part of their prompt. Nor can replay measure Qwen's current availability,
debate outcome, latency, or quality. The 43 recorded raw-`survives` overrides
are the strongest replay candidates, not 43 counterfactual scientific wins.

The read-only result is reproducible as JSON with the frozen upper bound:

```bash
.venv-chroma/bin/python tools/audit_skeptic_readiness.py \
  --loop-memory /home/decross1/projects/a_bgt_rsi/memory/loop_memory.jsonl \
  --calls /home/decross1/projects/a_bgt_rsi/logs/calls.jsonl \
  --since 2026-08-27T00:00:00Z \
  --until 2026-09-14T04:44:00Z
```

The command hashes the byte extent visible when each input descriptor opens,
reports invalid rows, and writes only its JSON result to stdout. It is a route
readiness audit, explicitly not a model-quality benchmark.

## Next bounded experiment

Run an isolated shadow experiment; do not change cron, systemd, or canonical
ledgers.

1. Freeze and hash 12 records from the 2026-08-27--2026-09-14 snapshot:
   six with `verdict_overridden_from="survives"` and six whose critic directly
   returned `undecidable`. Preserve the hypothesis, retrieval neighbors,
   relevance fields, and novelty record.
2. Redirect the iteration cache, wrapper-call log, run log, and all output to a
   temporary experiment directory. The existing iteration-cache module has no
   environment override, so the harness must set its `CACHE_ROOT` explicitly;
   setting only `LOOP_V0_CALLS_LOG` is insufficient to guarantee isolation.
3. Run paired AB/BA critic replays with the same evidence and deterministic
   Gemma critic policy:
   - A: current R0 behavior;
   - B: `NARA_R0_ADVISORY=1`, with all other critic inputs fixed.
4. First stop after the no-GPU pure replay and a three-record live canary.
   For the canary use the single-shot route (`NARA_SKEPTIC=1`,
   `NARA_DEBATE=0`, `NARA_SKEPTIC_BACKEND=vllm-qwen`) and label that deliberate
   departure. Its purpose is to verify eligibility, attribution, structured
   output, timeout handling, and isolated logging—not to promote a policy.
5. Continue to all 12 only if the canary produces Qwen-attributed receipts,
   no malformed outputs, no deadline or memory failure, and write
   instrumentation attributes every replay write to the isolated experiment
   roots. Do not use unchanged canonical-ledger hashes as the write-isolation
   test: those ledgers may legitimately grow concurrently. Cap the canary at
   15 GPU minutes and the full single-shot panel at 45 GPU minutes.
6. Separately run one production-shape `NARA_DEBATE=1` canary under a killed
   subprocess with a preregistered wall deadline. A six-round debate advertises
   per-turn budgets large enough that it should not be silently squeezed into
   the single-shot budget.

Primary measures are route-eligibility rate, Qwen receipt rate, structured
completion rate, critic/skeptic verdict transitions, wall-clock, and whether
the result changes any downstream eligibility. This experiment measures the
effect of R0 demotion and restores skeptic observability; it does not authorize
R0 demotion in production or make a scientific claim from replayed records.
