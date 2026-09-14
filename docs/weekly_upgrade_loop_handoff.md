# Model / Runtime / Inference-Policy Upgrade Loop — Coding-Session Handoff

> **Implementation update, 2026-09-14:** the owner directed Codex to proceed
> and treat this review as another set of eyes. Start with the
> [implementation runbook](weekly_upgrade_implementation.md) for delivered
> commands, corrected findings, validation and remaining runtime gates.
> This document preserves the original review; its Session-0/owner-question
> ordering does not suspend the owner's later implementation authorization.

> **Research correction:** the later
> [runtime qualification](research/weekly-upgrade-2026-09-14/RUNTIME_CHALLENGER_QUALIFICATION.md)
> found a third-party long-context sweep. The historical “no context sweep
> exists” statements below are superseded. That measurement still uses a
> different target/runtime configuration and does not qualify a local cutover.
> Current local experiment outcomes are in the
> [live evaluation record](research/weekly-upgrade-2026-09-14/LIVE_EVALUATION_RECORD.md).

> **Owner decisions, 2026-09-14:** “Keep game theory; correct the generated
> topics.” “Subscription-only frontier sessions, with up to 2 Spark GPU-hours
> per week.” The [current accounting design](weekly_upgrade_implementation.md#owner-decisions-recorded-2026-09-14)
> sets one shared 120-minute weekly ceiling, including GPU-using preflight,
> failures and recovery. This answers the research-scope and budget questions;
> it does not activate paid calls, scheduling, runtime cutovers or broader data
> egress. Historical panels below are a backlog within that ceiling, not
> cumulative recurring allocations. Correct upstream topics; retain R0 and
> the already-ratified D-075 game-theory/social-choice scope.

**Prepared:** 2026-09-14 by the primary Claude session, from a five-way review
(Codex adversary via the repo frontier seam + three Claude research agents +
a Claude red team) of the 2026-09-13 draft. Sources and full reports:
[`notes/research/2026-09-14-upgrade-loop-handoff/`](../notes/research/2026-09-14-upgrade-loop-handoff/).
**State basis:** `main @ 1cb2303`, live servers checked 2026-09-14T03Z.
**Status:** implementation plan. Nothing here authorizes a production cutover,
a pin change, a role change, or a `CLAUDE.md` edit. Every gate in `CLAUDE.md`
stays in force. A direct Codex session executing this plan works under the
`AGENTS.md` standing authority for ordinary Git/PR delivery only.

---

## 0. Read this first

The draft's thesis — "the system runs everything at temperature 0, so unlock
the installed models before replacing them" — is **half right**. The
correction ordering below is what the coding sessions should act on.

1. **The Qwen skeptic seat is dark in production.** `vllm-qwen` received
   **zero** chat requests in the last 7 days (docker logs); its last request
   was 2026-09-06T02:34Z (two LAB006 packet calls). Logged Qwen calls by
   month: Jun 651 · Jul 23 · Aug 126 · **Sep 2**. The last production
   `skeptic_attack` was 2026-08-17, still under the `qwen3.6` label. The
   coordinator's `ACTIVITY_CLASS_OF` (`orchestrator/coordinator.py:99-108`)
   has no action that runs the L0→L1 literature/skeptic rung; the funnel
   holds 97 L0 + 3 L1 clusters; the last `evidence_level_changed` event is
   2026-08-24. Sub-agent critic/redteam/debate turns are additionally never
   persisted to `logs/calls.jsonl` (`orchestrator/subagent.py:228` passes
   `log_path=None`). **Every "unlock Qwen3.8" experiment is second-order
   until the seat fires.** Root cause is not established; it is Session 0.
2. **"Temperature 0 everywhere" is false.** The wrapper defaults are
   `0.0/1.0` (`agent_wrapper/wrapper.py:178,217,311`), but 17 call sites
   override: `hypothesize` already runs `0.7/0.95` and already generates
   1–3 candidates and self-selects; skeptics run `0.2/0.95`; planner `0.1`;
   dialog `0.3–0.4`. The real defect is **uninstrumented drift**: no named
   profiles, no per-call `reasoning_effort` control, no recorded rationale,
   and both models run **off-card** (Gemma card: `1.0/0.95/top_k 64` for all
   use; Qwen thinking: `1.0/0.95/top_k 20`).
3. **`reasoning_effort` already works at the pin — with the right values.**
   vLLM v0.21.0 accepts top-level `reasoning_effort` and merges it into
   `chat_template_kwargs` (verified in-container). The Qwen3.8 template
   accepts **only `xhigh | medium | low`** and raises on anything else; the
   default when unset is `xhigh`, so every skeptic call today already runs
   at xhigh implicitly. The draft's `none_or_low` / `medium_or_high` /
   `high` values would be HTTP 400 on `:8001`. Gemma's knob is different:
   `chat_template_kwargs={"enable_thinking": true}`, default off.
4. **The 64K lane cannot run as configured** (Gemma `--max-model-len 32768`,
   Qwen `16384`); widening is a Tier-S serve change with the unresolved
   #40756 MTP crash zone above ~26K. The "64–78 tok/s through 65K" figure is
   a conflation: the band is real for **short code/math prompts** on
   SGLang+DFlash2 (7 independent Spark recipes, 50–72 tok/s); prose is
   20–28; no recipe measured a context sweep; "65,536" is the sliced
   `lm_head` row count.
5. **The vLLM pin stays a pin.** Keep `v0.21.0` as the immutable production
   baseline; challengers run only as digest-pinned eval runtimes (D-072/D-073
   pattern) in owner-scheduled solo windows (a third server cannot co-reside:
   41 GiB available vs the 30 GiB D-057 margin). Facts that change the
   trigger list: #34650 (MTP + reasoning parser + structured output) is fixed
   from **v0.27.0**; #51812 ships in v0.28.0; **#40756 is still open**; new
   **#49918** (a prompt of exactly `1+K` tokens produces deterministic garbage
   on GDN-hybrid Qwen under any spec method) is unassessed at the pin.
   Latest stable is v0.29.0 (adds `--moe-backend b12x` for SM121, DFlash2,
   per-request acceptance stats).
6. **A weekly frontier "upgrade loop" must be an extension, not a second
   control plane.** A weekly frontier agenda cron is already installed
   (`30 5 * * 0`, `cron/weekly-frontier-agenda.sh`) and has produced **43
   proposals, 0 acted on** (`memory/frontier_agenda.jsonl`; the accept/dismiss
   status file has never been written). D-066 already turns telemetry into a
   red-first Tier-P packet. Frontier-as-**proposer** is outside D-061
   (falsifiers only) and needs a narrow owner amendment; otherwise Gemma
   proposes and frontier falsifies (D-066 polarity). Both Codex and the
   Claude red team reached this independently.
7. **Judge circularity is live, not hypothetical.** In the last 7 days the
   promotion screen made 570 frontier calls over **6 distinct prompts** (the
   hourly `promote_findings` re-screens every survivor with no cache); the
   methods reviewer (Claude) vetoed 197/197 near-misses. A ~10-line
   `prompt_sha256` cache in `orchestrator/finding_promotion.py:649-681` frees
   ~10 frontier wall-hours/week before any new loop is added.
8. **No external benchmark belongs in the weekly promotion gate.** The box
   is aarch64 with no x86 emulation (Terminal-Bench/SWE-bench Pro images
   cannot run), ~10 GiB sandbox headroom, 32K/16K windows. The weekly panel
   is the repo's own frozen fixtures (all exist today). Judge-free public
   anchors (SciCode-Verified, HypoSpace, MRCR, NoLiMa-Hard, ResearchBench
   ranking) enter as **shadows** after week-1 calibration; CORE-Bench and
   PaperBench are quarterly campaigns at most.

Optimization target, restated: **verified scientific/coding task success per
wall-clock and compute, subject to reliability, reproducibility and the
memory margin — reported as an independent pass/fail vector, never a
composite score.** Raw tokens/sec is a health metric only.

---

## 1. Verified production state (2026-09-14)

| Item | Value | Source |
|---|---|---|
| Image | `vllm/vllm-openai:v0.21.0` (inviolate rule 2; both containers up 3 weeks) | `cron/serve-models.sh:23`, `docker ps` |
| Gemma `:8000` | gemma-4-26b-a4b NVFP4, `--moe-backend marlin`, MTP assistant n=4, max-model-len 32768, batched 8192, util 0.30, prefix cache, `--tool-call-parser gemma4` | `serve-models.sh:27-42` |
| Qwen `:8001` | qwen3.8-27b-nvfp4-mtp (Inferact modelopt PTQ), language-model-only, max-model-len 16384, max-num-seqs 2, fp8 KV, util 0.30, `--reasoning-parser qwen3`, `qwen3_5_mtp` n=3, `--tool-call-parser qwen3_coder` | `serve-models.sh:47-63` |
| Memory | 121 GiB total; ~40 GiB available with both resident; D-057 floor 30 GiB | `free -g` |
| Traffic (24 h) | Gemma 512 chat requests; **Qwen 0** (0 in 7 days) | `docker logs` |
| Wrapper defaults | `temperature=0.0, top_p=1.0, seed=None` on `call_sync` / `call_async` / `call_with_tools`; params passed verbatim to the OpenAI SDK; nothing passes `extra_body` / `reasoning_effort` / `top_k` / `min_p` today | `agent_wrapper/wrapper.py:178-352`, `backends/vllm_openai.py:31-32` |
| Call ledger | `schema/calls.jsonl.schema.json` has `additionalProperties: false`; validated before write (`wrapper.py:41,161`); `schema/` is Tier S | `docs/packet_sdlc.md` |
| Drift | `tools/qwen_builder.sh:60` defaults `QWEN_MODEL=qwen3.6-27b-nvfp4-mtp`; `bench/critic_eval/qwen_ab.py:43` likewise; `cron/weekly-frontier-agenda.sh:69-75` comments say "not installed" but it is | — |
| Frontier seam | `invoke_frontier()` → `claude -p` (Max subscription, API key stripped) / `codex exec --sandbox read-only -m gpt-5.6-sol -c model_reasoning_effort=max` (isolated `run_state/codex_home`); 2,338 ledger rows; G1 ToS sentinel present | `agent_wrapper/frontier_cli.py` |
| Frontier health | ISO week 35: 177/177 Claude calls failed (OAuth expiry, invisible 10 days); Codex timeouts 26% in the last 7 days (92/348), p90 = the 180 s cap | `run_state/frontier_calls.jsonl` |
| Tests | 2,525 collected; 7 red in the eval instruments themselves (`test_critic_cal` ×4, `test_readjudication` ×3) | `docs/project_health_2026-09.md` |
| Reproducibility | Gemma is **not** byte-deterministic at temp 0 (9–10/12 same-prompt divergences, MoE-Marlin reduction order); Qwen is (0/8) | `docs/external_spark_brief_review_2026-08-17.md:122-133` |
| Local temperature evidence | `experiments/judge_calibration/results.json` (2026-08-18, 224 calls): verdict flip rate between temp 0.2 and 0.7 = **0.027**, precision 0.30 at both | `workers/idea_judge.py` |
| Worktrees | no `ui-session` worktree; 55 `lab/*`, `pkt/*`, `codex-team2` worktrees under `/tmp`; main checkout dirty (CLAUDE.md, DECISIONS.md D-078–081, LOOP_V1.md, README.md, START_HERE.md, docs/packet_sdlc.md, three ledgers, untracked AGENTS.md/.codex/notes) — **do not sweep these into session commits** | `git status` |

### Current call-site policy (30-day volumes; the "control arms")

| caller_tag | site | backend | T / top_p | cap | n · p50 lat · p50 out · at-cap | role |
|---|---|---|---|---|---|---|
| `nara.run_iteration` | `orchestrator/nara.py:636-647` (direct `be.create_chat`) | gemma | 0.0 / 1.0 | 1024 | 2480 · 1.7 s · 101 · 0.6% | PI orchestrator w/ tools (spine — no arm) |
| `coordinator.plan` | `orchestrator/coordinator.py:748-761` | gemma | 0.1 / 0.9 | 512 | 980 · 1.2 s · 48 · 0 | planner |
| `hypothesize` | `workers/hypothesize.py:203-212` | gemma | **0.7 / 0.95** | 512 | 506 · 2.8 s · 176 · 0 | generator (1–3 candidates, self-selects) |
| `topicality_check` | `orchestrator/topicality.py:102-111` | gemma | 0.0 / 1.0 | 256 | 490 · 0.8 s · 46 · 0 | gate classifier |
| `meta_review` | `workers/meta_review.py:211-220` | gemma | 0.2 / 0.9 | 512 | 303 | distiller |
| `novelty_classify` | `workers/novelty_classify.py:379-388` | gemma | 0.2 / 0.95 | 512 | 302 | classifier |
| `idea_judge` | `workers/idea_judge.py:193-205` | gemma | 0.2 / 0.95 | 384 | 224 | equivalence judge |
| `skeptic_attack` | `orchestrator/novelty_skeptic.py:243-255` | **qwen** | 0.2 / 0.95 (+xhigh implicit) | 6144/12288 | 116 · **86.5 s** · 1782 · 5.2% (all pre-08-17) | independent skeptic (D-044) |
| `restate_*` | `orchestrator/restate_skeptic.py:164-175,314-326` | qwen | 0.0 ; 0.2/0.95 | 3072 | 8 | restatement skeptic (test pin `tests/test_restate_skeptic.py:309-322`) |
| `lab_channel:*` | `orchestrator/lab_channel.py:359-370` | gemma | 0.4 / 0.9 | 700 | 15 | dialog |
| `finding_session*` | `orchestrator/finding_session.py:766-987` | qwen | 0.3 / 0.9 | 1024/4096 | 8 | human-facing dialog |
| `claim_extract_refine` / `refine_cycle` | `workers/claim_extract.py:145-157`, `workers/refine_cycle.py:210-220` | gemma | 0.1 ; 0.2 (seed 0) | 400/600 | — | extractor / reviser |
| `self_improve_*` | `orchestrator/self_improve.py:420-449` | gemma | 0.3 | 4000 | — | apparatus planner (dark) |
| sub-agents (`critic_loop_v0`, `redteam_critic`, `debate`, promotion vote) | `orchestrator/subagent.py:338-349` hardcodes 0.2; per-turn cap 1024 | per site | 0.2 / 1.0 | budget | **0 rows in ledger** | primary critic, redteam, debate |
| builder | `tools/qwen_builder.sh:59-64,185-195` (raw curl, bypasses wrapper) | `:8001` | 0.2 (+xhigh implicit) | 6144 | 2 packets 09-05 | D-066 builder |

Reference: [`notes/research/2026-09-14-upgrade-loop-handoff/repo_design_condensed.md`](../notes/research/2026-09-14-upgrade-loop-handoff/repo_design_condensed.md).

---

## 2. Scorecard of the originating analysis

| Claim | Verdict | Note |
|---|---|---|
| Wrapper defaults temp 0 / top_p 1 | TRUE at the wrapper; FALSE as system policy | 17 overrides; PI at 0.7 |
| Qwen3.8 recommends thinking 1.0/0.95, instruct 0.7/0.8 | TRUE for the 27B (plus top_k 20, min_p 0, presence 0 / 1.5) | [card](https://huggingface.co/Qwen/Qwen3.8-27B) — not Flash-Next-specific |
| Lower reasoning effort can make agentic tasks slower via retries | TRUE (hedged wording on the card) | — |
| Profile levels `none` / `high` for Qwen | FALSE | template accepts `xhigh|medium|low` |
| SGLang 0.5.19 added Qwen3.8 | PARTLY | day-0 images since 2026-08-12; 0.5.19 (09-05) is first tag with DFlash2 |
| Spark recipes moved to a September nightly for a zombie fix | PARTLY | one recipe (hasso5703); SGLang PR #35255 merged 09-04, not in 0.5.19; NVIDIA playbooks have no Qwen3.8 |
| 64–78 tok/s single-stream through 65K | PARTLY / FALSE on context | 50–72 on short code/math; prose 20–28; no context sweep exists |
| ScienceAgentBench Verified 102 tasks, corrected false negatives | TRUE (verified split 2026-04-30) | fix details undocumented |
| CORE-Bench v1.1/OOD 2026 follow-up | TRUE | v1.1 = 39 tasks, OOD = 19, frontier-saturated |
| ResearchBench ACL 2026 | PARTLY (Findings track) | CC-BY-NC-4.0 |
| PaperBench 8,316 items / 20 papers | TRUE | $66/paper judge, 12 h A10 runs |
| OpenAI: ~30% of SWE-Bench Pro tasks broken | TRUE (2026-07-08) | Verified also dropped by OpenAI 02-23 |
| METR: CLI scaffolds no better than eval scaffolds | TRUE (2026-02-13) | framing only |
| "#34650 fixed post-pin" | TRUE, now precise: first stable v0.27.0 | — |
| vLLM pin should stop being inviolate | REJECTED as written | keep the pin; add challenger-lane + trigger list (§7) |
| CTT / SUH / RSR as promotion metrics | REJECTED as promotion metrics | no noise floor; keep raw vector; RSR only as a repeat-stability report |
| Weekly OpenAI×Claude rubber-band as proposers | NEEDS D-061 AMENDMENT | otherwise Gemma proposes, frontier falsifies |

Full scorecards with URLs: `benchmark_research_condensed.md`,
`policy_runtime_research_condensed.md` in the notes directory.

---

## 3. What to build, in order

Each session: red tests first under `MOCK_LLM=1`; one real
`env -u MOCK_LLM` smoke; rule-6 rows via
`orchestrator.runtime.append_run_log`; framework `code-review` before
merge; **restart `nara_daemon` after any `orchestrator/` or
`agent_wrapper/` merge** (14 days of stale code ran undetected in August).
Work in a worktree from a recorded base commit; stage only assigned paths.

### Session 0 — diagnose before optimizing (half day, no new features)

1. **Why is the Qwen seat dark?** Trace `NARA_SKEPTIC=1` (set in
   `systemd/nara-daemon.service:31` and `cron/run-coordinator.sh:110`) from
   the coordinator's action classes to `novelty_skeptic.attack()`; determine
   whether the skeptic is unreachable (no L0→L1 action), gated by budget
   (380 `coordinator:budget_refusal` rows since 09-01), or failing silently.
   Record the finding in the session note and as a run-log row.
2. **Hand-run the L0→L1 literature/skeptic pass** on the 3 L1 + 10 oldest L0
   clusters in one `env -u MOCK_LLM` window; record survival and wall-clock
   per cluster. If it runs in minutes on the current config, inference speed
   is not the blocker and the draft's premise is falsified.
3. **Owner triage of the 43 inert agenda proposals** with
   `orchestrator/agenda_cli.py` (accept/dismiss). This establishes the
   meta-metric any weekly loop is judged by: *recommendations acted on /
   recommendations made*. Precedent is 0/43.
4. **Live `reasoning_effort` probe on `:8001`** (5 skeptic fixtures ×
   {xhigh (default), medium, low}, identical prompts): confirm which of the
   three mechanisms (top-level param / `extra_body.chat_template_kwargs` /
   serve default) changes output length; record tokens, wall, empty-at-cap,
   `</think>` presence. Never done (`docs/qwen38_role_setups.md` §7 item 6).
5. **Trigger check** for the challenger lane (§7): none is known to have
   fired today; write the result down so Session B is not scheduled on
   speculation.

### Session A0 — two quick wins (Tier P, ~40 lines, one PR)

- `orchestrator/finding_promotion.py:649-681`: cache screens by
  `prompt_sha256`; skip re-screening a vetoed candidate until its record
  changes. Red test: identical candidate → one frontier call per week, not
  per hour. Expected: ~10.9 → <1 frontier wall-hours/week.
- Persist sub-agent turns: pass `log_path=CALLS_LOG_PATH` at
  `workers/critic_loop_v0.py:700-710`, `workers/redteam_critic.py:248-256`,
  `workers/debate.py:253`. Red test: a sub-agent row lands in the calls log.

### Session A1 — inference profiles + drift fixes (~350 lines)

Ordered file list:

1. `tests/test_wrapper_profiles.py` (RED first): (a) `resolve("scientist",
   "vllm-gemma")` → `0.7/0.95`, no `reasoning_effort` kwarg; (b)
   `resolve("critic_medium","vllm-qwen")` → `reasoning_effort="medium"`
   reaches `create` (`call_args.kwargs`); (c) explicit kwargs beat the
   profile; (d) unknown profile → `KeyError`; Qwen `none|high|max|minimal` →
   `ValueError` (rule 4: never coerce); (e) legacy call still produces
   exactly `LEGACY_KEYS` (`tests/test_wrapper_retrieval_context.py:147-160`);
   (f) `WRAPPER_PROFILE_OVERRIDES` env applies only when no `profile=` is
   passed; (g) Qwen denylist refuses `response_format` / `guided_json` /
   `structured_outputs` in `extra_body` (vLLM #34650 trap under the pin);
   (h) sync / async / tools parity.
2. `agent_wrapper/profiles.py` (NEW, ~80 lines): flat `PROFILES` dict (§4)
   + `resolve(profile, backend_name, *, temperature=None, top_p=None,
   seed=None, reasoning_effort=None, extra_body=None) -> (params, extra)`.
   `params` = exactly the three logged keys; `extra` = `{}` unless a profile
   or explicit kwarg sets `reasoning_effort` / `extra_body`. Per-backend
   mapping: Qwen → SDK `reasoning_effort ∈ {low, medium, xhigh}`; Gemma →
   `extra_body={"chat_template_kwargs": {"enable_thinking": true}}` only for
   profiles declaring `gemma_thinking`; Anthropic backend → log-and-drop
   extras. Env override `WRAPPER_PROFILE_OVERRIDES='{"skeptic_attack":
   "critic_low"}'` (declared battery variable, same idiom as
   `NARA_ATTACK_MAX_TOKENS`).
3. `agent_wrapper/wrapper.py` (≤45 net lines): `profile=None,
   reasoning_effort=None, extra_body=None` on `:178-180`, `:217-220`,
   `:311-315`; temperature/top_p defaults become `None` sentinels;
   `resolve()` replaces `:190`, `:223`, `:342`; `**extra` into `:192-194`,
   `:225-227`, `:346-352`. Resolved defaults must stay byte-identical
   (`0.0/1.0`) when neither profile nor explicit value is given.
4. **Logging the resolved policy** — two lanes, owner picks (decision 9.1):
   - *Ratified:* add five optional fields to `schema/calls.jsonl.schema.json`
     (`profile`, `reasoning_effort`, `sampling_extra`, `finish_reason`,
     `reasoning_chars` — omitted when unset; validate against every
     historical row; D-043 precedent). Tier S: ratification row in
     `run_state/overrides.jsonl` or a DECISIONS entry **before merge**.
   - *Not yet ratified:* schema untouched; the bench harness records the
     resolved policy in its own artifacts (Codex's recommendation).
   `reasoning_chars` = `len(msg.reasoning or "")` — there is no reasoning
   token count in chat-completion usage at the pin.
5. `tests/test_qwen_builder.py` (+1 RED) → `tools/qwen_builder.sh:60`
   default `qwen3.8-27b-nvfp4-mtp` (assert it equals the `vllm-qwen`
   registry label in `wrapper.py:96-100`); optional `QWEN_REASONING_EFFORT`
   in the request body at `:185-195` (unset = no change). Fix the same drift
   note at `bench/critic_eval/qwen_ab.py:43` and
   `docs/self_improvement_loop.md:132`.
6. `docs/inference_profiles.md`: the table in §4, the per-backend mapping,
   the two template facts, and the rule that a **production default-profile
   change is an owner-gated service change**, never a packet.
7. Verify: full suite green; one `env -u MOCK_LLM call_sync(...,
   profile="critic_low", backend="vllm-qwen")` confirming `reasoning_effort`
   in the request and a non-zero `reasoning_chars`; run-log rows; `narrate`.

**Migrate zero production call sites in A1.** Four test stubs have explicit
keyword signatures and would `TypeError` on `profile=`
(`tests/test_hypothesize.py:23-25`, `test_meta_review.py:29`,
`test_exp004_mechanism_designer.py:165`, `test_exp006_design.py:43`).
Profiles are selected only by explicit `profile=` in new code or by the
harness override env.

### Session A2 — paired evaluation harness (~550 lines)

1. `tests/test_policy_ab.py` (RED): manifest determinism + sha; arm matrix
   shape `(profile, role, backend, repeat_idx)`; refuse under `MOCK_LLM`;
   paired stats on canned rows; artifact provenance fields; 115-minute hard
   stop yields `inconclusive`, never silent fixture deletion.
2. `bench/policy_ab/{__init__,manifest,driver,stats,summarize}.py`:
   template = `bench/critic_cal/driver.py` (pins `:72-100`, flock
   `run_state/.bench-vllm-gemma.lock` `:565-577` — extend to `:8001`,
   serving-identity probe `:593,669-684`, `MEMORY_LOG` dump `:688-696`),
   `bench/fp8_ab/driver.py:57-77` provenance (image digest, model revision,
   fixture sha, script sha, per-case seed), `bench/redteam_cal/driver.py`
   `apply_prompt_variant` for sub-agent overrides. Per-arm
   `LOOP_V0_CALLS_LOG` set **before** importing workers. `stats.py`: paired
   sign test + bootstrap CI, stdlib only. Do not hardcode `v0.21.0` in new
   lines (premerge `version-pin` check); read the tag at runtime.
3. `experiments/PREREG_policy_ab_E1_<date>.md` locked before the first real
   arm (§8).
4. Weekly panel manifest (§5) built from existing fixtures — zero model
   calls to build.

### Session B — weekly operational review (dark) + challenger scorer

Only after owner decisions 9.2–9.4. Spec in §6 and §7. Files:
`tests/test_upgrade_review.py` (RED), `orchestrator/upgrade_review.py`
(~250), one hook in `cron/weekly-frontier-agenda.sh` behind
`NARA_WEEKLY_UPGRADE=1` (Tier S edit, its own PR), `docs/upgrade_loop.md`,
`bench/runtime_ab/{manifest.json,score.py,driver.py}` +
`bench/runtime_ab/serve_scratch.sh --dry-run` (prints the exact `docker run`
with digest; never launches by default),
`docs/runbooks/runtime_challenger.md`.

---

## 4. Inference profiles (card-correct)

Controls encode **today's** values so the first A/B has a faithful control;
challengers encode the vendor cards. Numbers are experimental arms, not
policy. `top_k` / `min_p` / `presence_penalty` ride in `extra` (vLLM accepts
them at the pin).

| profile | T | top_p | extra | Qwen `reasoning_effort` | Gemma thinking | intended roles |
|---|---|---|---|---|---|---|
| `deterministic` (control) | 0.0 | 1.0 | — | — (template default xhigh) | off | extraction, gates, tool args, restate |
| `planner` (control) | 0.1 | 0.9 | — | — | off | coordinator.plan |
| `precise` (control) | 0.2 | 0.95 | — | — | off | classifiers, judge, meta_review, refine |
| `dialog` (control) | 0.3 | 0.9 | — | — | off | lab_channel, finding_session |
| `scientist` (control = current PI) | 0.7 | 0.95 | — | — | off | hypothesize |
| `critic_current` (control) | 0.2 | 0.95 | — | xhigh (explicit) | — | skeptic_attack, sub-agent critics |
| `critic_medium` | 0.2 | 0.95 | — | medium | — | skeptic seat arm |
| `critic_low` | 0.2 | 0.95 | — | low | — | skeptic seat arm (cost) |
| `qwen_card_thinking` | 1.0 | 0.95 | top_k 20, min_p 0 | xhigh | — | vendor point, skeptic/builder |
| `qwen_card_coding` | 0.6 | 0.95 | top_k 20 | medium | — | builder arm (Qwen3.6 "precise coding" point) |
| `gemma_card` | 1.0 | 0.95 | top_k 64 | — | off | vendor point, hypothesize arm |
| `gemma_card_thinking` | 1.0 | 0.95 | top_k 64 | — | **on** | hypothesize arm — run the 10-turn tool probe first (untested with tools + MTP) |
| `explore` | 1.0 | 0.95 | — | medium | off | E2 diversity arm only |

Rules baked into `resolve()`: Qwen values outside `{low, medium, xhigh}` →
`ValueError`; never send `enable_thinking=false` through the shipped 3.8
template (hard exception; use `reasoning_effort=low`); refuse guided /
structured output on the Qwen backend while pinned (#34650, fixed only from
v0.27.0); Anthropic backend drops extras with a log line.

---

## 5. Evaluation panel

Ground rules: one window under `run_state/pause_coordinator` with the D-057
preflight (≥30 GiB); frozen manifest with seed + content hash; paired (same
fixtures every week, both arms interleaved); Qwen at explicit
`reasoning_effort` with hard caps, **empty-at-cap counted as failure**; every
call logs the resolved policy; **determinism is defined as parsed-output
pass/fail agreement across repeats plus logged MTP acceptance counts, never
byte equality** (Gemma is not byte-deterministic; vLLM does not guarantee
stable logprobs). Week 1 is a calibration run: record actuals, trim in the
stated order. Every signal stands alone (rule 4); no composite may rescue a
failed gate.

### 5.1 Original weekly v1 panel proposal — row caps total 120 minutes

**Budget correction, 2026-09-14:** the seven row caps below sum to 120,
not the originally stated ~110/cap-115. Running every row to its cap leaves
no allowance for additional GPU-using preflight/recovery. Select and freeze
a smaller panel before calls within the shared weekly ceiling; the current
design allocation is 15 minutes of canaries, 90 minutes of one admitted trial,
and 15 minutes of overhead/reserve. These historical per-family rows are a
menu, not a weekly execution order or an implemented full benchmark suite.

| Function | Frozen set (n) | Measurements | Hard pass/fail | Cap |
|---|---|---|---|---|
| Tool/transport | `bench/fp8_ab/tool_probe.py` 10-turn script, once per model; `t06` is deliberately spec-invalid → diagnostic only, score the 9 valid turns | HTTP completion, parseability, exact tool name + args, replay survival, latency, `</think>` presence (Qwen) | all 9 valid turns 200 + parse; ≥8/9 exact; zero malformed replays; no per-fixture regression vs same-run incumbent | 15 min |
| Coding builder (Qwen) | CB01 = frozen `tasks/packets/PKT-EXAMPLE.json` edit task replayed in a pre-fix worktree; CB02 = sanitized self-contained generation task; explicit `QWEN_MODEL` | hidden-test result, out-of-scope writes, diff size, attempts, output tokens, wall-to-correct | both pass; zero scope violations; candidate solves ≥ incumbent and paired wall-to-correct not >10% worse | 30 min |
| Skeptic/critic (Qwen) | 6 sentinels from `experiments/lit_falsification_battery/cases.jsonl` (`novel_on_01_quant_lockin`, `redisc_on_01_tft_reciprocity`, `canary_on_01_ultimatum_plain`, `falsifiable_01_finite_pd_cooperate`, `falsifiable_02_dominant_tft`, `camo_off_04_raft_punishment`) × 3 repeats; cap 3072 | liveness, empty-at-cap, verdict anchors, RSR_2of3 (reported, not gating), tokens, wall | 6/6 complete with pinned anchors; zero empty-at-cap; anchor agreement ≥ control | 20 min |
| Redteam critic (Gemma) | `bench/redteam_cal/fixtures.jsonl` 24 (12 good / 12 bad) | D-076 bars unchanged | unscored ≤2; fatal-on-bad ≥75%; fatal-on-good ≤35% — each bar alone | 10 min |
| Hypothesis/PI (Gemma) | 12 fixed good/bad claim pairs derived from redteam fixtures + 4 fixed topics with a structural answer contract (intervention/condition, comparator, outcome, predicted direction) | pair choice, schema validity, four structural fields, invented source IDs | ≥10/12 pairs; 4/4 parseable; all four fields present; zero invented IDs. Novelty stays human-scored | 15 min |
| Long-context (both) | 4 frozen packs (2 × ~8K, 2 × ~14K tokens) built from `CLAUDE.md`, five decisions, `self_improvement_loop.md`, `qwen38_role_setups.md`, with planted facts + contradictions + citation IDs | atomic fact recall, contradiction detection, attribution, unsupported assertions, TTFT | all planted contradictions found; ≥95% facts; zero unsupported citations; 8/8 complete. **No 32K/64K weekly lane** | 20 min |
| Runtime health (both) | `scripts/bench_tokens_per_sec.py`: warm-up + 5 × 256-token prompts; `max_tokens=1` prefill probes at 4K/8K/14K; 3 seeded identical calls; `/metrics` acceptance; `MemAvailable` before/after; **add the #49918 `1+K`-token prompt fixture** | median decode, TTFT vs context, aggregate, parsed-output agreement, memory floor | every request completes; `MemAvailable ≥ 30 GiB`; no garbage on the `1+K` fixture | 10 min |

Also available for monthly depth: `bench/critic_cal/manifest.jsonl` (26,
~90 s/fixture), `bench/judge_cal/set_v2.jsonl` (74, md5-pinned),
`experiments/fixtures/critic_hypotheses/` (20; `PASS_RATE_BAR 0.80`), full
22-case skeptic ladder via `bench/critic_eval/stage3a_driver.py`.
Depth/shadow tasks replace other charged work; they do not add an allowance.

### 5.2 Weekly v2 shadows (after week-1 calibration; judge-free first)

| Anchor | Why | Weekly slice | Source |
|---|---|---|---|
| HypoSpace | set-valued hypothesis generation with deterministic validators (validity/uniqueness/recovery); offline; the only judge-free instrument for the "diversity" question | 10 instances (5 fixed + 5 rotating) | https://arxiv.org/abs/2510.15614 · https://github.com/CTT-Pavilion/_HypoSpace |
| OpenAI MRCR | MIT; 2/4/8 needles; bins from [4K,8K]; deterministic SequenceMatcher grading | 2- and 4-needle, bins ≤32K, 6/bin (Gemma); 2-needle ≤16K (Qwen) | https://huggingface.co/datasets/openai/mrcr |
| NoLiMa-Hard | minimal lexical overlap; vLLM supported; non-commercial (internal use only) | 10 pairs × {8K,16K,32K} Gemma, biweekly | https://github.com/adobe-research/NoLiMa |
| ResearchBench ranking / tiny | reference-based pairwise (1 GT vs 15 negatives); cheap; CC-BY-NC-4.0 | 1 paper/week from a frozen 26-paper rotation | https://aclanthology.org/2026.findings-acl.644/ |
| BFCL v4 offline slice | AST-scored; `--skip-server-setup` + local endpoint; note the 18.5% evaluator–human disagreement audit | 100 non-live + 50 live + 20 multi-turn (Gemma), biweekly | https://github.com/ShishirPatil/gorilla · https://arxiv.org/abs/2607.02577 |
| LiveCodeBench | 6 fixed problems, regression only (not contamination-free for an Aug-2026 model) | 6 | https://github.com/LiveCodeBench/LiveCodeBench |

Prerequisite: a separate eval venv (`inspect_ai`, `inspect_evals`,
`litellm`); Inspect drives any OpenAI-compatible server via
`VLLM_BASE_URL` / `openai-api/<provider>/<model>`
(https://inspect.aisi.org.uk/providers.html) but tool/reasoning parsing is
"model dependant".

### 5.3 Deeper benchmark backlog — no recurring budget authorized

The original 6–10 GPU-hour monthly proposal and multi-day quarterly runs exceed
the owner's selected two-hour weekly envelope. Keep these as backlog. A bounded
slice may replace a week's trial; any larger campaign needs a separately
authorized budget. Do not infer accumulated/carryover hours or permission to
pause production from this section.

Monthly: **SciCode-Verified** full (64 main / 287 subproblems; Apache 2.0;
judge-free; https://arxiv.org/abs/2608.04975,
https://github.com/flyingwagner/scicode-verified) — the best scientific-
coding anchor and absent from the draft; GPQA Diamond 198 × 3 repeats both
models (weekly deltas are noise: SE ≈ 2.5 pp); HLE-Verified gold 300
text-only with Qwen as grader; BFCL V1–V3 full local slice; MRCR all ≤32K
bins; NoLiMa 58; SWE-bench Verified mini (50; Epoch arm64 images,
best-effort); ResearchBench retrieval 50; HypoSpace 50; ScienceAgentBench
verified 20-task subset **only after an arm64 grading pilot** (harness
hardcodes `max_tokens=2000` and routes non-`gpt*` names to Bedrock → serve
under a `gpt*` alias with `OPENAI_BASE_URL`).

Quarterly at most: CORE-Bench v1.1 (39) + OOD (19) with internet for
installs, 1–2 days; PaperBench Code-Dev on 2 papers via Inspect (weakly
correlated with full PaperBench, per its authors).

### 5.4 Not realistic here, and why

Full PaperBench (12 h A10 runs, $66/paper judge); CORE-Bench weekly (45-min
tasks, internet, GPU capsules); Terminal-Bench 2.x and SWE-bench Pro (x86
images, no `qemu-user-static`, 2–4 GB/container; Pro ~30% broken); METR
(private); tau2 published-comparable pass^k (needs the gpt-4.1 simulator);
HLE full; BFCL v4 agentic (web search, snapshots); LongBench v2 and any 64K
lane under the current pins; ProjectionBench / SCOPE (data releases
unconfirmed).

### 5.5 Metrics

Report the vector, each with its own pass rule and CI:
`tool_reliability`, `coding_success`, `skeptic_anchor_agreement`,
`redteam_bars`, `hypothesis_contract`, `long_context_fidelity`,
`repeat_stability (RSR_2of3, reported)`, `wall_to_correct`,
`tokens_per_task`, `memory_floor`, `frontier_calls`,
`frontier_cost_usd: null` (the CLI ledger carries no tokens or billing —
record `null`, never zero), `human_interventions`. Composite throughput
metrics (CTT/SUH) may be computed retrospectively for reporting only and are
rejected as promotion criteria until a measured noise floor exists.

---

## 6. Weekly operational review (minimal, dark, extension of the agenda cron)

**Shape (Codex counter-proposal, adopted):**

```
existing lock / ToS-sentinel / pause gates
 → deterministic local snapshot (pure reads, hashed, redacted)
 → Codex `upgrade_proposer`  (exactly ONE smallest operational experiment)
 → Claude `upgrade_adversary` (identical snapshot + the immutable proposal; kill / revise / survives_to_owner_review)
 → local reducer (no LLM): drop malformed, hash-mismatched, evidence-free, unbounded, non-Tier-P, or killed items
 → inert ledger row → owner
```

No synthesis call, no rebuttal loop, no packet emission, no code generation,
no runtime launch, no automatic promotion. **2 frontier calls/week** (plus
the existing agenda's 2). Runtime and model surfaces are **trigger-driven**
(§7), not weekly; the weekly pass may only propose an `inference_policy` /
`scaffold` / `bench` experiment card.

**Reuse verbatim:** `invoke_frontier` (`agent_wrapper/frontier_cli.py:239-321`;
`role` is a free string), `_extract_json_object` (`workers/frontier_review.py`),
`_append_rows` / `load_agenda` / `accept_proposal` (`orchestrator/frontier_agenda.py:161-245`),
`self_improve.gather_evidence` (`orchestrator/self_improve.py:154-256`) for
bounded telemetry projections, the gate ladder in
`cron/weekly-frontier-agenda.sh:37-56`, `parse_prometheus`
(`ui/sampler/sources/vllm_metrics.py:34-52`, read-only import),
`runtime.append_run_log`.

**Snapshot** (hash every file; send full text only for small policy/code
files; never raw prompts/completions from `logs/calls.jsonl`): `HEAD` +
dirty paths; `cron/serve-models.sh` flags + `run_state/vllm_image.digest` +
live `/v1/models` + `/proc/meminfo`; the §1 call-site table rendered from
`profiles.PROFILES`; 7-day `logs/calls.jsonl` aggregates per `caller_tag`
(n, p50 latency, p50 in/out, at-cap, empty-at-cap); `frontier_calls.jsonl`
vendor health (a one-vendor week sets `independence_loss: true`); latest
artifact per `bench/*/runs`; prior weekly rows; the trigger list (§7) with
current status; extracts of D-061/D-066/D-072/D-074/D-076 with the whole-file
hash. **Web access:** `codex exec --sandbox read-only` has no network and
`claude -p` web access is not guaranteed — the analysts see only the
snapshot unless owner decision 9.4 enables web tools.

**Proposer output** (strict JSON, `additionalProperties: false`, flat —
nested schemas cause retry loops): `schema_version, week_id,
snapshot_sha256, proposal_id (wu-<sha8>), title, claim, repo_evidence[{path,
locator, sha256}], external_claims[{claim, url, status: SOURCE_VERIFIED |
UNVERIFIED}], change_surface[paths], tier (P|S|unknown), baseline{artifact,
metric, value}, candidate{single_delta}, experiment{fixture_ids, arms,
seeds, max_gpu_minutes, primary_metric, guardrails[], pass_rule},
falsifier, abort_conditions[], owner_gate_required: true`. An external
assertion without a source in the snapshot must be `UNVERIFIED` and cannot
be load-bearing.

**Adversary output:** `schema_version, week_id, snapshot_sha256,
proposal_id, verdict (kill | revise | survives_to_owner_review),
violated_rules[], objections[{claim, repo_evidence[], falsifier}],
cheapest_decisive_test, residual_risks[], external_claims[]`.

**Ledger:** tracked `bench/weekly_upgrade/ledger.jsonl` (append-only;
`memory/*.jsonl` is git-ignored) with events `snapshot_created,
proposal_received, adversary_reviewed, rejected, survives_to_owner_review`
(the job may write only these five) and `owner_accepted,
experiment_result` (human / harness only). `decision` defaults to
`NO_CHANGE`; anything else requires a `measurement_ref` to a `bench/*/runs`
artifact whose preregistered bar passed; `PROMOTE_PENDING_OWNER` is the
ceiling — no "promoted" state exists in code. Snapshots under
`bench/weekly_upgrade/snapshots/<ISO-week>.json`. Rule-6 rows for every
stage including gate refusals.

**Cron / kill switches:** no second scheduler — the existing
`30 5 * * 0 cron/weekly-frontier-agenda.sh` calls the review after the
agenda pass, only when `NARA_WEEKLY_UPGRADE=1` (Tier S edit, own PR, human
installs). `touch run_state/pause_frontier` halts both; only the owner
removes it; removing `run_state/frontier_tos_ratified` darkens all frontier
calls; single-instance `flock`; **no retries** — a missing/failed vendor
yields `inconclusive`. Raise the role's timeout above 180 s (Codex p90 hits
the cap today).

**Meta-metric, reported every week:** `acted_on / proposed` for both the
agenda and the review, and the cost of `NO_CHANGE` (frontier minutes, GPU
minutes, owner reading time). If the review's acted-on rate is 0 after 8
weeks, the loop is retired — same test the agenda currently fails.

**Data egress / ToS:** G1 was ratified for hypothesis/corpus text
(`LOOP_V1.md:322-325`). The snapshot sends serve flags, digests, memory
figures, aggregated telemetry and decision extracts — record a G1 scope
amendment row in `run_state/overrides.jsonl` naming what leaves the box.
Both vendors' docs point automation at API keys (Codex: "Use API key
authentication for programmatic Codex CLI workflows"; Anthropic: Pro/Max
limits "assume ordinary, individual usage"); a subscriber's own weekly cron
is neither named nor forbidden — **UNVERIFIED as clearance**. Metered
alternative: Fable 5.1 / Opus 5 with `web_search_20260209`, GPT-6 Astra or
o3-deep-research via Responses — under $1 per 30K-in/8K-out call, ~$3–10 per
week at the top tier, and it removes the ambiguity.

**Later owner decision:** subscription-only sessions. The metered alternative
above is an excluded historical proposal; its prices/model claims are not an
approved or newly verified implementation plan. The current manual transport
strips API-key routes. Subscription use does not itself activate unattended
cron or expand the snapshot's approved off-box contents.

---

## 7. Runtime challenger lane = trigger watchlist, not a schedule

Keep `vllm/vllm-openai:v0.21.0` as the immutable production baseline
(rollback point). Build only the endpoint-agnostic scorer
(`bench/runtime_ab/score.py`: provenance, liveness, tool probe, six
sentinels, TTFT, decode, memory, wall-to-correct — each an independent gate)
and a `--dry-run` launcher that prints the exact digest-pinned `docker run`
for `vllm-runtime-ab` on `:8002`. A live window (pause → preflight → launch
scratch → verify digest/model → sentinels → remaining tests → stop → restore
via the canonical launcher → verify MARLIN line + Qwen identity → postflight)
is owner-scheduled and replaces `vllm-qwen` in its memory slot
(`docs/qwen_fp8_windows_plan.md` "Window discipline").

Check monthly (and in every weekly snapshot); a fired trigger opens a
one-variable, same-weights A/B, never a cutover:

| Trigger | Status 2026-09-14 |
|---|---|
| Guided/structured output needed on the Qwen backend (#34650) | fix first stable in **v0.27.0**; not needed today → not fired |
| #40756 MTP illegal-memory-access reachable under the pin (>~26K cumulative) | issue still open upstream; local R4 soak never run → run the soak (Session A2 fixture), then decide |
| #49918 `1+K`-token prompt garbage reachable at the pin | unassessed → weekly fixture (§5.1) |
| #51812 GDN gate alignment (v0.28.0) | sub-noise at v0.21.0 per D-072; not fired |
| DFlash2 for Qwen3.8 on vLLM with an **NVFP4** target on GB10 | documented only with FP8 weights (which cannot co-reside under D-057) → not fired; UNVERIFIED for ≥0.28 |
| SGLang + NVFP4 + DFlash2 (D-073 track) | blocked on T1 (DSpark license) / T2 / T3 / T4; strongest documented stack (50–72 tok/s code, 20–28 prose; mem-fraction 0.80 to avoid earlyoom); post-09-04 nightly carries the abort fix (#35255) | 
| Gemma `--moe-backend b12x` (v0.29.0, SM121 native W4A4) vs pinned `marlin` | untested on Gemma 4 upstream → candidate for a Gemma A/B only |
| `nvidia/Qwen3.8-27B-NVFP4` (2026-09-08 ModelOpt export, MTP head included) vs the Inferact PTQ artifact | same-model quant swap; tested on GB300 only → WATCH |
| Qwen3.8-Flash-Next / Ling-3.0-flash as seat candidates | WATCH only; roles are fixed (G5); any lead-seat arm needs a decision entry first |

Promotion rule for any runtime candidate: identical weights, request bytes,
template, parser, MTP/KV config and scoring; no correctness/tool regression;
≥10% paired wall-to-correct or decode gain; TTFT regression ≤10%; memory
and provenance gates pass; three repeated paired runs; then a DECISIONS
entry + owner ratification of the pin amendment. Evaluation success alone
never authorizes a cutover.

---

## 8. Preregistered experiments (lock `experiments/PREREG_*.md` before any real arm)

| # | Question | Arms | Fixtures | Decides |
|---|---|---|---|---|
| E0 | Is the skeptic seat dark or unreachable, and does the L0→L1 rung run in minutes on the current config? | hand-run | 3 L1 + 10 oldest L0 clusters | whether inference speed is a blocker at all (Session 0) |
| E1a | Qwen `reasoning_effort` in the skeptic seat | `critic_current` (xhigh) vs `critic_medium` vs `critic_low`, identical serve/request | 6 sentinels × 3 repeats | empties, anchors, tokens, wall; the card's retry warning vs the 86 s p50 |
| E1b | Warmer critic (draft's `critic 0.7`) | Gemma redteam at 0.0 / 0.2 / 0.7 × 3 repeats | 24 redteam fixtures, D-076 bars unchanged | if agreement with temp-0 ≥0.9 the arm is pointless; if <0.9 it breaks the calibrated instrument — both are decisions |
| E1c | Vendor sampling point for the PI | `scientist` (0.7/0.95) vs `gemma_card` (1.0/0.95/64) vs `deterministic`, equal tokens | 12 frozen topics | structural validity + blinded survival through the literature pass |
| E2 | Diversity + selection | one long proposal vs three short + selection under **equal total tokens/wall** | 12 topics; HypoSpace 10 as the judge-free companion | kill before it reaches Qwen (16 tok/s, 11% empty-at-cap, judge precision 0.30) |
| E3 | Context | 8K vs 14K full-context vs retrieved/compacted on the 4 exact-answer packs | §5.1 packs | open a scratch 32K/64K window only if 14K loses required evidence |
| E4 | Runtime (same weights, same policy) | production `:8001` vs digest-pinned challenger `:8002` | smoke → tool probe → 6 sentinels → throughput | only after a §7 trigger fires |
| E5 | Model | best incumbent configuration vs candidate at its best preregistered, deployable configuration | full v1 panel | only after E1–E4; lead-seat arms need the G5 decision entry |

Noise floor first: 20 fixtures × 3 repeats at temp 0 on Gemma, report
parsed-output agreement; scrape `spec_decode_num_accepted_tokens_total` at
temp 0 vs 0.7 on identical prompts — if acceptance moves, E1 and E4 are
coupled and must be run jointly.

---

## 9. Owner decisions required (blocking where marked)

1. **Calls-schema bump** (five optional fields) — ratification row before the
   A1 merge, or choose artifact-only logging. *(A1 merge)*
2. **D-061 narrow amendment**: may a frontier model author *operational,
   non-research* experiment cards that never contain hypotheses, never enter
   loop memory / brain / idea ledger, never emit packets, never touch files
   or runtime, and stay inert until acceptance? If no → Gemma proposes,
   frontier falsifies. *(blocks Session B code)*
3. **G1 scope amendment** naming what the weekly snapshot may send off-box;
   and the subscription-CLI-in-cron question vs metered APIs. **Partly answered
   2026-09-14:** subscription-only frontier sessions; no metered fallback.
   Scheduling activation and broader off-box scope are separate decisions,
   not implied by the budget answer. *(Historical Session B question.)*
4. **Web tools for analysts** in scope of G1, or snapshot-only. *(B)*
5. **Tier of `agent_wrapper/`** — keep it packet-proof (recommended) and
   treat any production default-profile change as an owner-gated service
   change.
6. **Control-arm naming** — accept profile names that encode today's values
   (`precise`, `planner`, `dialog`, `critic_current`) alongside the vendor
   points.
7. **Weekly canary budget — answered 2026-09-14:** up to 120 Spark GPU-minutes
   per week for all weekly-upgrade work, not per experiment. Proposed accounting
   is separate from D-063's coordinator activity units, with shared physical
   resource coordination. The current controller does not enforce this weekly
   balance. See the current runbook for overhead and interruption accounting.
8. **Triage the 43 agenda proposals** via `agenda_cli` — sets the meta-metric
   baseline. *(Session 0)*
9. **Challenger engine** if a trigger fires: SGLang+DSpark (license
   unresolved) vs a newer vLLM tag by digest (`v0.27.x`+ carries #34650;
   `v0.29.0` carries b12x/DFlash2).
10. **Lead-seat (Qwen-as-PI) arm** — include in E5 only with a G5 decision
    entry, or defer.
11. **Sub-agent `log_path` fix** — land directly in A0 (recommended) or as
    the first D-066 packet.

---

## 10. Disagreements between the reviewers, and how each is settled

| Topic | Codex | Claude (design / red team) | Resolution |
|---|---|---|---|
| `reasoning_effort` in profiles | keep profiles to sampling only; effort is an experimental serve/request arm until probed live | the API is verified at the pin; map per backend | passthrough is implemented (cheap, verified) but **no production site uses it** until the Session-0 live probe proves the mechanism changes output |
| Schema change in A1 | do not edit `schema/`; log in artifacts | five optional fields, Tier-S ratified | owner decision 9.1; code is written so both lanes work |
| Loop shape | 2 calls, local reducer, no synthesis | 3 calls (proposer / adversary / cross) — or do not build it until the agenda has a consumer | 2-call shape, dark, only after decisions 9.2–9.3 and the agenda triage; 8-week meta-metric retirement rule |
| Ledger location | tracked `bench/weekly_upgrade/` | `memory/upgrade_agenda.jsonl` (gitignored) | tracked (`memory/` is gitignored; provenance wins) |
| Cadence for runtime/model | weekly review, mostly NO_CHANGE | trigger-driven, monthly human check | weekly = analysis + canaries + at most one policy card; runtime/model = triggers (§7) |
| Benchmarks | six-function private table only | private v1 + judge-free public shadows | v1 private now; shadows after week-1 calibration; external suites never gate |
| N=3 + selection | unmeasured tax; equal-budget trial | already exists inside `hypothesize`; kill on Gemma before Qwen | E2 on Gemma with HypoSpace companion; Qwen excluded |
| Composite metrics | reject until denominators fixed | no noise floor | reporting only; never promotion |

Cheapest experiments deciding each are listed in
`codex_adversary_report.md` §5 and `claude_red_team_condensed.md` §4.

---

## 11. Cut from the draft

Six-benchmark portfolio C–F as weekly gates; the three-round A→B→A frontier
review; the 12-field change schema in favor of the flat proposer card; the
7-gate ladder in favor of the existing `PREREG` pattern; CTT/SUH as
promotion metrics; weekly cadence for runtime/model surfaces; Session B's
challenger launch until a trigger fires; `explore` (1.0) and `critic` (0.7)
as production arms; the 64K lane; the JSON weekly-report contract in favor
of a ledger row + session-note subsection with a named reader.

---

## Appendix A — Reusable evaluation prompt v3 (replaces the 2026-09-13 v2)

```
# Local Scientific Model / Runtime / Inference-Policy Evaluation — v3 (2026-09-14)
Project: a_bgt_rsi. Hardware: ONE NVIDIA DGX Spark (GB10, aarch64, 128 GB unified,
~273 GB/s, CUDA 13.0, NO x86 emulation). Production: vllm/vllm-openai:v0.21.0,
Gemma 4 26B-A4B NVFP4 (generator; MARLIN; MTP n=4; 32K) + Qwen3.8-27B NVFP4
(skeptic/builder; fp8 KV; qwen3_5_mtp n=3; 16K; reasoning parser qwen3, template
levels xhigh|medium|low, default xhigh). Roles are FIXED (Gemma PI, Qwen skeptic,
frontier falsifiers). Verify all of this against cron/serve-models.sh, /v1/models,
docker ps and free -g before every evaluation; runtime evidence beats this prompt.

TARGET: verified scientific/coding task success per wall-clock and compute, subject
to reliability, reproducibility and MemAvailable >= 30 GiB with both residents.
Report an independent pass/fail vector; never a composite. tok/s is health only.

SEPARATE THE LAYERS and never attribute a gain across them: model weights;
quantization; serving runtime; decoding policy (temperature/top_p/top_k/min_p/
reasoning_effort/caps); scaffold (prompts, tools, candidates, selection, context).
A challenger never gets a better scaffold than the incumbent. Always include the
incumbent under its best preregistered configuration.

FIRST QUESTION: is the proposed gain available from the installed models via
decoding policy, reasoning effort, caps, context allocation, retrieval, or
selection? Test that before any new checkpoint.

PRIORITY: 1 hardware fit (co-residency under the margin; a third server needs a
solo window) -> 2 scientific capability on the repo's own labeled instruments
(redteam_cal 24, skeptic sentinels 6/22, critic_cal 26, judge_cal 74) and
judge-free public anchors (SciCode-Verified, HypoSpace, MRCR, NoLiMa-Hard,
ResearchBench ranking) -> 3 coding/agentic (frozen private packets; LCB
regression) -> 4 reliability (empty-at-cap, malformed tools, </think> drops,
stuck reasoning, cancellation, memory growth) -> 5 wall-to-correct and retries
-> 6 raw single-stream throughput at 2K/8K/16K (32K Gemma only; 64K is a
capability test requiring a serve change and the #40756 soak).

INFERENCE POLICY IS EVALUATED, NOT ASSUMED: arms = current production values
(controls), vendor-card values (Gemma 1.0/0.95/top_k 64; Qwen thinking
1.0/0.95/top_k 20; instruct 0.7/0.8/presence 1.5), and reasoning_effort
xhigh/medium/low for Qwen. By role. Stochastic arms need >= 3 repeats; report
parsed-output agreement, not byte equality (Gemma is not byte-deterministic at
temp 0; vLLM does not guarantee stable logprobs; MTP acceptance moves with
temperature).

RUNTIME: v0.21.0 is the immutable baseline. Candidates run only as digest-pinned
eval runtimes on :8002 with identical weights/template/parser/MTP/KV/request
bytes, sentinels first, hard stops on provenance/memory/error, exact restoration.
Promotion = no correctness/tool regression, >= 10% paired wall-to-correct or
decode gain, TTFT regression <= 10%, three repeated paired runs, then a DECISIONS
entry and owner ratification. Never adopt guided output on Qwen while pinned
(#34650 fixed only from v0.27.0). Known upstream: #40756 open; #49918 (1+K-token
prompt) unassessed.

KILL ATTEMPTS (all mandatory): memory; capability vs the incumbent's best
config; inference-policy (does the gain vanish when the incumbent gets the
same policy?); retry (does overthinking reduce completed tasks?); runtime
fragility (unpublished patch stacks, moving tags); quantization (deployable
quant, calibration provenance); context (does more context buy quality or
only latency?); speculation (batch~1 gains real? outputs correct?); provenance
(every artifact traceable); judge circularity (label-swap the judges).

DECISION LABELS: ADOPT | EVALUATE | WATCH | REJECT | RETAIN-INCUMBENT |
RUNTIME-UPGRADE | POLICY-UPGRADE. Start with the verdict, then: what is
running now; candidate config; memory; per-instrument results; optimal
inference settings by role; throughput at each context; deltas vs BOTH
residents; which layer produced the gain; smallest implementation change;
risks; exact triggers that would change the verdict. Label every external
claim SOURCE_VERIFIED (URL) or UNVERIFIED. Newer or faster is not an upgrade.
```

## Appendix B — Provenance

- Spawn ledger ids `upgrade-loop-20260914/{codex-upgrade-adversary,
  claude-bench-research, claude-policy-runtime-research, claude-repo-design,
  claude-red-team}` in `run_state/spawn.jsonl` (spawned + completed rows).
- Codex call: `run_state/frontier_calls.jsonl` role `upgrade_loop_adversary`,
  codex-cli 0.154.0, gpt-5.6-sol / max, 1,206 s, exit 0.
- Run-log row `upgrade-loop-handoff-2026-09-14/research-fanout` in
  `run_state/week1.run.jsonl`.
- All agents were read-only on the repo; no model serving was touched.
