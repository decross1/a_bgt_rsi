# Qwen 3.8 role setups — research synthesis (2026-08-16)

> Produced by two dynamic-workflow research squads run 2026-08-16 ~22:30Z
> (7-agent repo-evidence sweep + 8-agent web/repo setup sweep; spawn ledger
> `qwen38-swap-evidence-wf_df622cd2`, `qwen38-setup-research-wf_7d5f03e1`).
> Every external claim below was web-sourced on 2026-08-16 or is marked
> UNVERIFIED. Companion doc: [`qwen38_upgrade_checklist.md`](qwen38_upgrade_checklist.md)
> (the cutover instrument). Nothing here changes any pin or gate: cutover
> stays behind G6, pins are verbatim (inviolate rule 2).

## 0. The generator-swap question, settled on evidence

Asked: should Qwen 3.8 replace **Gemma** as generator/PI (not merely replace
3.6 in the skeptic seat)? Finding: **no repo document ever proposed or
rejected this explicitly** — but the scoping is deliberate and multiply
recorded: the G5 fixed-roles ratification (`run_state/overrides.jsonl` row 2)
landed the *same day* as G6 3.8-acquisition approval (row 3); LOOP_V1 P5
scopes the battery to "the roles Qwen actually plays"; the checklist's
cutover mechanics touch only the `vllm-qwen` slot.

A steelman of the swap was run against the full evidence dump. Six of ten
pro-swap arguments are **refuted by measured evidence**:

- Skeptic-seat evidence (19/22) says nothing about generation; even that
  battery FAILED its kill check and stages 3b/3c/3d never ran.
- Call-volume/throughput asymmetry: the generator seat carries 76% of logged
  calls (2,399/3,140) at a measured 69.4 tok/s (Gemma+MTP); 3.8 measured
  ~16.5 tok/s and needs a 12× token budget for equivalent output
  (512 vs 6144, `orchestrator/novelty_skeptic.py:69-70`).
- Empty-at-cap follows the model: Gemma 0.13% (3/2,399), Qwen3.6 3.88%
  (27/696, all exactly at caps), Qwen3.8 11.1% (5/45) — it would relocate
  into the highest-volume seat.
- Gemma's inline-tool-call quirk is mitigated and non-firing:
  `loop_v0_synth_tool_call` fired **0 times** in retained logs; residual is
  ~1.4 reprompts/iteration.
- One-model consolidation breaks D-041's independence bar (the persona
  argument transfers verbatim to Qwen-persona).
- The generator's output contract is short/structured (refine = one 600-token
  low-temp call) — the worst shape for a thinking-by-default model.

Four arguments **survive as unmeasured hypotheses** (honest list): raw
capability per token (dense 27B vs ~3.8B-active MoE); 3.8-vs-Gemma generation
quality (never compared); the audit value of a legible reasoning-trace PI;
seat-*swap* independence (Gemma-attacks-Qwen is structurally valid but voids
every direction-specific validation — D-044 3/3, D-065/D-071 debate, D-070
sizing — and restarts them from zero). The honest instrument for these is the
lead-seat battery in §5, not a cutover.

## 1. Ground truth: the Qwen 3.8 release

- Two open-weight variants: **Qwen3.8-2.4T-A95B** (MoE, 95B active,
  text-only, custom "qwen3.8-max" license) and **Qwen3.8-27B** (dense,
  multimodal VL, **Apache 2.0**). No small-MoE variant exists.
- 27B `config.json` is **byte-for-byte the same serving shape as 3.6**:
  `Qwen3_5ForConditionalGeneration`, 64 layers (48 linear-attention +
  16 full-attention), 4 KV heads × 256 head_dim, native ctx 262,144,
  `mtp_num_hidden_layers=1`. All gains are post-training (long-horizon
  agentic RL). Thinking on by default at `reasoning_effort=xhigh`
  (levels: xhigh/medium/low, per-request or template-settable).
- Official card deltas vs 3.6-27B (vendor harnesses; directional):
  SWE-bench Pro 61.7 vs 53.5 · Terminal Bench 2.1 73.0 vs 63.4 ·
  LiveCodeBench v6 90.3 vs 83.9 · OSWorld-Verified 84.3 vs 63.9 ·
  Agents' Last Exam 20.4 vs 10.6 · GPQA Diamond 89.2 vs 87.8.
  **No BFCL/tau-bench rows exist for the 27B** (searches conflate the
  unrelated Qwen3-8B); card agentic evals ran under the Claude Code harness,
  not an OpenAI-tools loop.

## 2. QAT verdict: PTQ is the only path, and it's already on disk

- **No official or NVIDIA QAT/QAD checkpoint of 3.8 exists** (HF
  `author=nvidia` query returns zero; NVIDIA's Qwen NVFP4 line stops at 3.6;
  Qwen ships only BF16 + FP8 of 3.8).
- NVIDIA's own QAD report: plain QAT is often **worse than PTQ on RL-trained
  models** (AceReason AIME25: 58.7 PTQ vs 46.1 QAT vs 62.0 QAD); QAD needs
  0.3–6B training tokens on multi-GPU — not a GB10 job.
- The acquired **Inferact/Qwen3.8-27B-NVFP4** (modelopt NVFP4 PTQ, MTP shard
  present) is the exact checkpoint named in vLLM's official single-Blackwell
  recipe and was proven ALIVE in window #2. **Keep it; do not re-quantize.**
  Both production Qwen checkpoints (3.6 sakamakismile, 3.8 Inferact) are
  PTQ — record this in D-0zz. UNVERIFIED: Inferact's calibration recipe
  (card is one line); its quality evidence is our own window #2.
- `experiments/exp008_qat_eval` was Gemma-only and INSUFFICIENT — no local
  QAT claim transfers to Qwen.

## 3. MTP verdict under the v0.21.0 pin

- `qwen3_5_mtp` is in v0.21.0's `MTPModelTypes` (verified at the tag source);
  3.8's MTP head is trained at block size 3 → **keep
  `{"method":"qwen3_5_mtp","num_speculative_tokens":3}`** — matches the
  official recipe and window #2. The recipe's generic `"mtp"` auto-resolves
  to the same implementation; it is a serve-flag fallback, never a pin issue.
- Published GB10 measurement (0.26.x nightly — UNVERIFIED under the pin):
  MTP ≈ doubles 3.8-27B decode (11.4 → 23.6 tok/s at n=3; n=5 peak +5%
  costs TTFT — don't raise n). Acceptance ~65% and **rises on long
  generations** (68–71%) — MTP pays more in agent loops.
- fp8 KV + MTP is the *safer* pairing (vLLM #46088 cross-sequence corruption
  hit only non-fp8 KV).
- **Standing trap:** MTP + reasoning parser + structured output silently
  drops `</think>` under the pin (vLLM #34650; fix PR #44993 merged
  2026-07-23, post-pin). We are immune only because the wrapper has no
  `guided_json` — never adopt guided output on the Qwen backend while pinned.
- Pin amendment buys nothing today. Triggers that would justify pricing one:
  guided output on Qwen; >16k contexts if the #40756 soak fails (§6 R4);
  chasing the last ~5–10% decode (n=5/DFlash, v0.25.0+). Any amendment must
  re-clear BOTH residents (Gemma MARLIN + CUDA 13.0).

## 4. Memory ledger + three sized configs (measured, not estimated)

Pool = 121.68 GiB (MemTotal). Gemma @0.30 = 36.5 GiB (18.9 weights +
12.06 KV + 0.6 graphs + ~5 overhead). Qwen3.6 @0.25 = 30.4 GiB (18.65 +
6.92 KV @94,742 tok fp8). Measured effective KV cost **76.6 KiB/token**
(hybrid-allocator padding included — the derived 32 KiB/token figure is
wrong for planning; measured wins). 3.8 weights are **+5.5 GiB** vs 3.6
(~24.2 GiB loaded est. under `--language-model-only` — verify against the
"Model loading took X GiB" boot line). MemAvailable with both resident
today: ~49 GiB; margin 30 GiB, never thinned (D-057).

| Config | util | max-model-len | KV | Concurrency | Pred. MemAvailable |
|---|---|---|---|---|---|
| **1 — co-resident skeptic** (cutover shape) | 0.25→**0.30** | 16,384 | 7.1 GiB ≈ 97k tok | 5.9× (matches 3.6 today) | ≈43 GiB (+13 cushion) |
| **2 — co-resident dev agent** | **0.35** | **131,072** | 13.2 GiB ≈ 181k tok | 1.38× @128k (2.8× @64k) | ≈37 GiB (+7 cushion) |
| **3 — solo max** (Gemma stopped) | **0.60** | **262,144** (native) | 43.6 GiB ≈ 597k tok | 2.28× @262k | ≈40 GiB |

- **Do NOT ship 3.8 at 0.25 beyond 16k**: arithmetic leaves 1.0–1.5 GiB KV
  (~1× concurrency) — window #2 booted on the fail line.
- 0.40 co-resident and 0.65 solo were computed and REJECTED (zero cushion
  against the UMA boot trap). 1M-ctx YaRN does not fit any margin-respecting
  config (~74 GiB KV for one sequence).
- GB10 gotcha: vLLM's boot check uses `cudaMemGetInfo`, which ignores
  reclaimable page cache on UMA (vLLM #35313) — `drop_caches` before a solo
  boot; 24.6 GiB of just-read weight files will be sitting in cache.
- Every util raise is D-057-gated: preflight before, `preflight_mem.sh 0`
  with both up after, Gemma MARLIN line re-verified. If more is needed
  co-resident, the alternative is trimming Gemma 0.30→0.25 by owner
  ratification — never the margin.

## 5. Setup A — dev agent (Tier-S serve edit, human-ratified)

Config 2 above plus, relative to window #2's proven flags, exactly three
deltas: util 0.25→0.35, max-model-len 16384→131072, and
`--default-chat-template-kwargs '{"reasoning_effort":"low"}'` (flag verified
present in v0.21.0's `cli_args.py` — no pin change).

- **reasoning_effort is the single highest-leverage knob**: xhigh (the
  template default) is the community-confirmed cause of "token exhaustion,
  zero content" — our exact 3/23 window-#2 signature.
- Sampling per the official card (thinking mode): temp 1.0 / top_p 0.95 /
  top_k 20 / presence 0.0; client `max_tokens ≥ 8192`. The repo's skeptic
  temp 0.2 is off-card for this family; don't reuse it here.
- Parser: start `qwen3_coder`; pre-planned escapes: empty `tool_calls` with
  populated reasoning = vLLM #39056 (call swallowed in `<think>`) → lower
  effort or switch to `qwen3_xml` (registered in v0.21.0, community-reported
  more stable at 27B); multi-turn TypeError on JSON-string tool args = the
  shipped 3.8 chat template → fixed template via `--chat-template`
  (froggeric). **Never** pass `enable_thinking=false` through the shipped
  template (hard exception) — use `reasoning_effort`.
- Harness: point an OpenAI-compatible CLI at `http://127.0.0.1:8001/v1`,
  model `qwen3.8-27b-nvfp4-mtp`; match the harness's advertised context to
  `--max-model-len`. vLLM route preferred over ollama-coder (NVFP4+MTP is
  the proven fast path, one serving stack). This is a dev-tool use, distinct
  from the runtime skeptic seat; frontier CLIs stay falsifiers-only (D-061).
- `--enable-prefix-caching`: test-first (hybrid-GDN acceptance under v0.21.0
  UNVERIFIED; near-useless below the ~528-token block regardless, #40696).

## 6. Setup B — lab lead (experiment design, NOT a cutover)

**Governance gate first (blocking):** a Qwen-as-lead run violates the G5
fixed-roles guardrail as written. It requires an owner-ratified decision
entry declaring the experiment window and an explicit temporary
re-assignment of skeptic independence (Gemma and/or the D-061 frontier
falsifiers check Qwen-authored claims) — otherwise D-033-lineage
independence inverts silently. Sequence: settle the skeptic-seat kill-check
window first; a model that can't hold its current seat makes the lead
experiment moot.

- Serve: config-1 shape at **0.30 / max-model-len 32768** (matches Gemma's
  window; measured orchestration transcripts run median 5.8k / max 7.1k
  input tokens) + `reasoning_effort=low` for the window. Both servers up;
  workers stay on Gemma.
- **Zero-code seam:** `run_iteration(topic, backend="vllm-qwen")` swaps only
  the orchestration brain. Baseline: 27 Gemma iterations since 08-10
  (~7.4 turns/iter, ~1.4 reprompts/iter, median 1.6 s/turn).
- **Everything generator-defining is UNMEASURED for Qwen** — no repo path
  has ever passed `tools=` to vllm-qwen (the :8001 tool parser is configured
  but unexercised): tool_calls emission, 5-step chain adherence, two-slot
  narration+tool_call, survival at temp 0.0 under the 1024-token turn cap,
  malformed-args rate, inline-format emissions (the Gemma synth parser will
  NOT catch a Qwen-format blob), creativity at 0.7, wall time, tok/s.
- **Battery:** Stage A cap-smoke (3 iterations, as-is; starvation at 1024 is
  a FINDING, then one declared time-capped variant — never a silent retune).
  Stage B chain adherence (N≥10, all metrics already logged in
  `calls.jsonl` + run log). Stage C temperature arms (repo 0.0 vs vendor
  1.0/0.95) + push Qwen hypotheses through the unchanged downstream funnel.
  Pass criteria fixed before the run (rule 4).
- **Economics is the likeliest disqualifier**: 7.4 turns × 83–140 s/call ≈
  10–17 min/iteration vs Gemma's <1 min — unfundable at D-063's always-on
  cap-60 cadence without measured mitigation. Battery reports tok/s and
  min/iteration as first-class results; D-063 sizing gets re-derived, not
  assumed.

## 7. Risk-ranked experiment queue (cheapest resolver each)

1. **3.8 kill check** (blocks G6): one gated window, ≥ the 3 cap-empty cases
   at cap 12288 (calls-log verified non-empty this time — the earlier 12288
   retry logged zero calls and is void); optional second arm at
   `reasoning_effort=medium` to record which knob moved.
2. **No A-side control**: run 3.6 through the FIXED stage3a driver in the
   same window; schedule 3b/3c/3d there too (serve swap dominates cost).
3. **Memory envelopes rest on an estimated 24.2 GiB load**: boot each
   profile once; the boot lines are the acceptance test.
4. **128k profile crosses the open MTP crash zone** (vLLM #40756, ~26k,
   status under the pin UNVERIFIED): synthetic long-generation soak
   30k→130k during the acceptance boot; on crash, cap at 16–24k and price a
   pin amendment then.
5. **OpenAI tool seam unexercised on Qwen**: 10-turn scripted tool session
   against :8001 (structured arrays? JSON-string replay? low vs xhigh?).
6. **reasoning_effort knob unproven live**: one serve with `low` + 3-case
   re-run, measuring output lengths vs xhigh.
7. **Lead-seat economics**: battery stage A with tok/s captured.
8. **No local Qwen tok/s or MTP acceptance ever measured**: add token counts
   to the next window's driver; scrape
   `vllm:spec_decode_num_accepted_tokens_total` (ui/sampler already computes
   the ratio). Settles n=2 vs n=3 with data.
9. **Prefix caching on hybrid GDN**: pass the flag once at boot; drop if
   rejected.
10. **Structured-output trap** (#34650): guard note only; amendment triggers
    listed in §3.
11. **Governance**: write the lead-experiment decision entry BEFORE stage A.

## 8. Hygiene items surfaced by the sweeps

- **DECISIONS.md contains no 3.8 entry at all** — both windows, the
  retraction, and the dead pin-amendment verdict live only in the checklist,
  session notes, and commit messages. File the D-0zz scoping before memory
  fades (it should also record: both Qwen checkpoints are PTQ; window #1 may
  only ever be cited as a retracted instrument-bug record).
- **D-070 numeric corrections** (re-measured from the ledger): attack-site
  loss was **3/48, not 4/48** (one case was truncated-JSON, not empty);
  pre-fix p90 was 2,861/3,072 (93% of cap), p95 at cap — "p90 sat AT the
  cap" slightly overstates. Direction/conclusion unchanged. DECISIONS.md is
  append-only; correct via the D-0zz entry or a dated note.
- **Checklist line ~303 duration conflict**: describes D-044's 2026-06-09
  validation as "~2 min"; the run log records 415 s. Run-log row is primary;
  fix the checklist line when D-0zz is filed.
- An **uncited third stage-3a artifact** exists
  (`stage3a_..._20260815T063602Z.json`, 22 cases in 54 s — calls errored
  before reaching the model); keep it labeled as a non-run.

## Standing UNVERIFIED list

Inferact calibration recipe; exact 27B release date (~Aug 14, third-party)
and 27.8B param count; v0.21.0 release date; first vLLM release containing
PR #44993; n=5 vs n=3 under the pin; exact 3.8 loaded footprint; whether the
pin's boot check is exactly the #35313 path; exact Ollama 27B tag;
BFCL/tau-bench for 3.8-27B (absent upstream). None block the plans above.
