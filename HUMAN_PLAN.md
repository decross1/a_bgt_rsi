# Human Plan — Week 1 (Days 31–37)

> Everything in this file is **yours to do**. The agents will not execute,
> assist, summarize, derive, or solve any of it. The agent execution plan
> lives in `AGENT_PLAN.md`; the canonical machine-readable plan is
> `plan.yaml`. The original source plan `week1_days_31-37_plan.md` is not
> yet committed to the repo; `plan.yaml` is canonical for task content.
>
> **The rule that does not bend:** Block 1 (foundations) is human-only,
> every day. No AI assistance. Pen and paper. If you find yourself
> reaching for the agent during Block 1, close the laptop.

## How to use this document

Each day section has four blocks:

1. **Pre-day (evening before)** — anything you need ready before you sit
   down tomorrow morning.
2. **Block 1 — Foundations (08:30–10:00, human-only).** Reading and
   problem set. Pen, paper, no agent.
3. **Block 2 manual touchpoints (10:30–12:30).** The agent runs Block 2
   on its own track, but specific steps require you (physical actions,
   Dashboard clicks, human attestations, pre-computed safeguards).
   Each is flagged with a wall-clock window inside Block 2.
4. **Block 3 — Read + Journal (13:30–14:30).** Your reading and your
   public post. The agent generates a data-filled stub; you write the
   prose.
5. **Ambient listening (14:30–15:30).** Walk. No notes.
6. **End-of-day (15:30–16:00).** Human attestations the agent needs to
   close the day.

Items tagged **`[GATE]`** are blocking: the agent will stop and wait for
your explicit acknowledgment before proceeding.

---

## Pre-flight (before Day 1) — 48-hour lead time

Do these **before the Spark arrives** or at least before Day 1 morning.
The agent's `preflight_*` tasks verify these and refuse to proceed if any
are missing.

### Credentials (start the Semantic Scholar application 48 hours out)

| Credential | Where to apply | Time |
| --- | --- | --- |
| Semantic Scholar API key | <https://www.semanticscholar.org/product/api> | **24–48 hr turnaround — apply first** |
| Anthropic API key | console.anthropic.com | minutes |
| HuggingFace token (read scope) | huggingface.co/settings/tokens | minutes |
| GitHub PAT | github.com/settings/tokens | minutes |
| NVIDIA build.nvidia.com API key | build.nvidia.com | minutes |

Once you have all five, copy `.env.example` to `.env` and fill them in.
Set `DGX_SPARK_LAN_IP` after the Spark is on your network.

### Physical and software pre-staging

- [ ] Desk/shelf with **6"+ clearance on all sides**, ambient ≤ 30 °C.
- [ ] UPS or surge protector inline.
- [ ] Network on a switch (NOT USB-C — documented to cause flakiness).
- [ ] Books downloaded to `books/` (gitignored): Osborne & Rubinstein,
  Weibull, Cesa-Bianchi & Lugosi, Camerer, Fudenberg & Levine. PDFs only;
  Day 3 ingests O&R first.
- [ ] Third-party repos cloned into `clones/` (gitignored):
  `NVIDIA/dgx-spark-playbooks`, `matt-langston/autoresearch`,
  `google-deepmind/open_spiel`, the Game Reasoning Arena repo.
- [ ] Weights pre-staged on the Spark (or on a USB to copy over):
  Gemma 4 26B-A4B-NVFP4 (~12 GB) → `/mnt/models/gemma-4-26b-a4b-nvfp4`;
  BGE-M3 (~1–2 GB) → `/mnt/models/bge-m3`.
- [ ] Bookmarks file confirms the **inviolate version pins**:
  - `vllm/vllm-openai:v0.21.0` (NOT `:gemma4`, `:gemma4-cu130`, or
    `:v0.20.0` — see `DECISIONS.md` D-022; v0.21.0 enables Gemma 4 MTP)
  - `ghcr.io/nvidia/openshell/cluster:0.0.13`

### Failure-mode rehearsal (15 min each, written notes private)

Walk through these mentally **before Day 1**:

1. **NemoClaw gateway start failure** → plain Docker fallback (Day 1).
2. **vLLM throws "Failed to run cutlass FP4 gemm"** → wrong image tag,
   fix and retry.
3. **Filesystem cache fills memory** → cron `drop_caches` every 30 min.
4. **CUDA auto-updates to 13.2** → roll back via Dashboard
   **before any inference** (gibberish on low-bit quants).

When you've done all four walkthroughs, mark the agent's
`preflight_failure_walkthroughs` task complete in your session.

---

## Day 1 — Hardware online, stack verified (T+0)

### Pre-day (evening before)

- [ ] Re-verify the pre-flight checklist above is complete.
- [ ] Phone charged; you may need to share a Dashboard screen photo if
  something looks off.

### Block 1 — Foundations (08:30–10:00, no AI)

- [ ] **Reading:** Osborne & Rubinstein, *A Course in Game Theory*,
  Ch. 6 §6.1–6.3 (extensive games with perfect information; Nash and
  subgame-perfect equilibrium intro).
- [ ] **Problem set:** O&R 6.1, 6.2, 6.3 — by hand. Bridges Phase 1
  weeks 1–4 (strategic-form) into the repeated-game machinery you'll
  need on Day 7.
- [ ] Mark `day1_block1_reading` complete in the agent session when the
  90 minutes have elapsed and you've attempted the problems.

### Block 2 manual touchpoints (10:30–12:30)

These slot **inside** the agent's Block 2 run. The agent will halt at
each and wait for you.

- [ ] **`[GATE]` 10:30–10:50 — Unbox and place.** Physical setup. The
  agent waits, then verifies the DGX Dashboard is reachable. After
  placement, confirm with the agent:
  - Power LED is solid.
  - Fan is at low RPM (audible but not loud).
  - Dashboard reachable via the IP you set in `.env`.
- [ ] **`[GATE]` 10:50–11:20 — Firmware baseline.** The agent prepares
  the verification command, but firmware updates and the auto-update
  lock happen via the Dashboard UI — that's you.
  - Settings → Updates → apply ALL pending firmware (Jan 2026 thermal,
    Feb 2026 ConnectX-7 idle, April 2026 release).
  - Settings → Updates → **Manual approval only.**
  - **Verify CUDA reads 13.0.** If it reads 13.2, **roll back via
    Dashboard before any inference.** CUDA 13.2 produces gibberish on
    low-bit quantized models. This is the single most important manual
    check of the entire week.
- [ ] **11:20–12:00 — Agent-led:** Docker config, vLLM pull and serve,
  micro-bench. You're watching for the **MARLIN backend log line** in
  startup logs. The agent will surface it; if it shows `CUTLASS_FP4`
  instead, the agent will stop and escalate to you. Don't override.
- [ ] **12:00–12:30 — Agent-led:** NemoClaw onboarding attempt
  (90-min cap). May overflow into 16:00–18:00; if it does, the agent
  will fall back to plain Docker and log the decision.

### Block 3 — Reading and journal (13:30–14:30)

- [ ] **Reading:** Lu et al. 2024, *The AI Scientist* (Sakana), pp. 1–12.
- [ ] **Journal post (200–500 words):** "Day 1 of the apparatus — what I
  shipped, what I'm afraid will break." The agent will hand you a stub
  with today's metrics pre-filled (median tok/s, NemoClaw status, vLLM
  image tag actually used). You write the prose.
- [ ] **Private notes (NOT in public post):** exact error messages,
  exact config lines, GB10 idiosyncrasies you discovered.

### Ambient listening (14:30–15:30)

- [ ] Dwarkesh Patel — most recent episode with someone on agent
  infrastructure. Walk. No notes.

### End-of-day (15:30–16:00)

- [ ] If NemoClaw is still chasing at 16:00, **stop**. Do not let setup
  eat tomorrow's Block 1.
- [ ] When the agent prompts, attest in the session that the public
  journal URL is on the index. Agent commits artifacts.

---

## Day 2 — Python wrapper + JSONL logging (T+1)

### Pre-day (evening before)

- [ ] Glance at the JSONL field list in the agent's
  `agent_wrapper/wrapper.py` docstring. You'll be authoring the schema
  on paper first thing in Block 2.

### Block 1 — Foundations (08:30–10:00, no AI)

- [ ] **Reading:** O&R Ch. 6 §6.4–6.5 + start Ch. 7 (subgame perfect
  equilibrium, one-deviation principle).
- [ ] **Problem set:** O&R 6.7, 6.10, 7.1. Derive the one-deviation
  principle by hand — it's one of those things you have to derive once
  to actually understand.
- [ ] Mark `day2_block1_reading` complete.

### Block 2 manual touchpoints (10:30–12:30)

- [ ] **`[GATE]` 10:30–11:00 — JSONL schema authoring.** Write the
  schema on paper first, then have the agent commit it as
  `schema/calls.jsonl.schema.json`. Required fields (14 total) are in
  `plan.yaml` task `day2_block2_jsonl_schema`. **This is a hard
  checkpoint** — get it right; the rest of the week's reproducibility
  depends on it.
- [ ] **11:00–12:00 — Agent-led:** wrapper implementation. You're
  not writing code; you're confirming the agent's resisting abstraction.
  Code budget: ~100 lines. If the agent proposes a base class
  hierarchy, push back.
- [ ] **`[GATE]` 12:00–12:30 — Determinism check review.** The agent
  runs 50 calls including 3-trial determinism checks at T=0 and at
  T=1, seed=42. If determinism fails, **do not let the agent paper
  over it.** Pause. Investigate vLLM launch flags, wrapper seed
  passthrough, and identical request bodies across trials. This is a
  hard checkpoint and aborts the day on failure.

### Block 3 — Reading and journal (13:30–14:30)

- [ ] **Reading:** Critical response to Sakana — Melanie Mitchell's
  blog post + one selected Twitter thread (e.g., Matt Welsh).
- [ ] **Journal post (200–300 words):** "What does it mean for a
  research apparatus to 'work'? Reading Sakana skeptics on Day 2."
  Agent stub will include malformed-count and determinism pass/fail.
- [ ] **Private notes:** your own taxonomy of failure modes; which apply
  to your design and which don't.

### Ambient listening

- [ ] EconTalk with Al Roth on market design.

### End-of-day

- [ ] Attest journal URL on index. Agent commits.

---

## Day 3 — ChromaDB + BGE-M3 + first textbook ingest (T+2)

### Pre-day (evening before)

- [ ] Confirm `books/osborne_rubinstein.pdf` is present and the file is
  not OCR-garbled (open it, eyeball a math-heavy page).

### Block 1 — Foundations (08:30–10:00, no AI)

- [ ] **Reading:** Weibull, *Evolutionary Game Theory*, Ch. 1 §1.1–1.4
  (population states, evolutionary stability, ESS). Weibull is denser
  than Osborne — if the algebra needs slow checking, spend Block 1 on
  §1.1–1.2 alone.
- [ ] **Problem set:** Weibull 1.1, 1.2, 1.3.
- [ ] Mark complete.

### Block 2 manual touchpoints (10:30–12:30)

- [ ] **10:30–10:50 — Agent-led:** ChromaDB install with BGE-M3 (hard
  checkpoint). Watch for the embedding-function metadata. If it says
  `all-MiniLM-L6-v2` instead of `BGE-M3`, **do not let the agent
  proceed** — that default drops retrieval accuracy to 0.4–0.6 at 4K
  chars.
- [ ] **10:50–11:30 — Agent-led + your eye on the regex:** chunking
  script. The equation-guard regex is the part that matters; the agent
  dry-runs on Ch. 1 and shows you 5 random chunks. **Verify by eye that
  no chunk has a broken `$...$` or unmatched `\begin{equation}`.**
- [ ] **11:30–12:00 — Agent-led:** full ingest of O&R.
- [ ] **`[GATE]` 12:00–12:30 — Needle benchmark sanity check.** Target
  score ≥ 0.85 (BGE-M3 expected ~0.92). Score < 0.7 triggers
  investigation — do not advance to Day 4 with a broken retrieval layer.

### Block 3 — Reading and journal

- [ ] **Reading:** Hart & Mas-Colell 2000, *A Simple Adaptive Procedure
  Leading to Correlated Equilibrium*. Sets up MW intuition for Day 6.
- [ ] **Journal post (200–300 words):** "Reading the textbook into the
  loop — what gets preserved, what gets compressed."
- [ ] **Private notes:** specific retrieval failures observed; hypotheses
  for each.

### Ambient listening

- [ ] ML Street Talk or The Gradient — recent episode on RAG / agents.

### End-of-day

- [ ] Attest journal URL. Agent commits (chroma_db/ is gitignored;
  manifest.json IS tracked).

---

## Day 4 — First tool call (T+3)

### Pre-day

- [ ] On paper, write down the three mock payoff matrices the agent will
  hardcode tomorrow: prisoner's dilemma `(3,3),(0,5),(5,0),(1,1)`, stag
  hunt, matching pennies. (You should know these cold from Block 1
  work.)

### Block 1 — Foundations (08:30–10:00, no AI)

- [ ] **Reading:** Weibull Ch. 1 §1.5–end + Ch. 2 §2.1 (replicator
  dynamics intro).
- [ ] **Problem set:** **Derive replicator dynamics for hawk-dove BY
  HAND.** This is a program-listed Phase 1 problem set item — today is
  the right day for it.
- [ ] Mark complete.

### Block 2 manual touchpoints (10:30–12:30)

- [ ] **10:30–11:00 — Agent-led:** mock tool definition. You eyeball
  the schema and the three matrices match what you wrote down last
  night.
- [ ] **11:00–11:45 — Agent-led:** wrapper extension for tool calls
  (`call_with_tools`, max depth 3). **Confirm the agent surfaces
  malformed JSON rather than silently retrying.** You need to SEE the
  failure rate today.
- [ ] **11:45–12:20 — Agent-led:** E2E test and robustness micro-test.
  The tool-invocation rate is the headline metric. A rate < 80% is a
  **finding** to characterize, not a bug to silently fix. Do not let
  the agent jump to `guided_json` until you've measured the gap.

### Block 3 — Reading and journal

- [ ] **Reading:** Camerer Ch. 4 §4.1–4.2 (learning models, EWA intro).
- [ ] **Journal post (200–400 words):** "First tool call — and the gap
  between 'works' and 'works reliably.'" Agent stub includes the
  invocation rate and one full chain's `request_id`.
- [ ] **Private notes:** prompt-tuning ideas; whether `guided_json` is
  worth the complexity.

### Ambient listening

- [ ] Complexity Podcast on evolution of cooperation. Pairs with this
  morning's replicator content.

### End-of-day

- [ ] Attest journal URL. Agent commits.

---

## Day 5 — arXiv pipeline → ChromaDB (T+4)

### Pre-day

- [ ] **ML-Intern decision.** Read `notes/day5_ml_intern_plan.md` (the
  agent staged it Day 4 evening) and decide: attempt ML-Intern, or skip
  direct to fallback? The agent will respect your written decision. If
  in doubt, attempt — it has a 45-min hard cap before falling back.

### Block 1 — Foundations (08:30–10:00, no AI)

- [ ] **Reading:** Cesa-Bianchi & Lugosi, *Prediction, Learning, and
  Games*, Ch. 1 §1.1–1.4 (Hannan consistency, regret framework).
- [ ] **Problem set:** C-B & L Ex. 1.1, 1.2 — internalize the regret
  bound's proof structure. You'll prove MW formally tomorrow.
- [ ] Mark complete.

### Block 2 manual touchpoints (10:30–12:30)

- [ ] **10:30–11:15 — Agent-led with 45-min hard cap:** ML-Intern
  attempt (if you chose that path). If 45 min elapses without a working
  hello-world, the agent falls back automatically.
- [ ] **11:15–12:15 — Agent-led:** pipeline implementation. You're
  watching for the BGE-M3 embedding (NOT default), the exponential
  backoff (required by Semantic Scholar policy), and dedup on
  `arxiv_id`.
- [ ] **`[GATE]` 12:15–12:30 — Manual cross-check.** Pick 2 random
  papers from the ingest and verify they exist on arxiv.org by ID. If
  any is hallucinated, stop and investigate before retrieval test.
- [ ] **12:25–12:30 — Agent-led:** retrieval test. You attest whether
  ≥1 of the top-3 is genuinely relevant.

### Block 3 — Reading and journal

- [ ] **Reading:** Aher, Arriaga & Kalai 2023, *Using LLMs to Replicate
  Human Subject Studies* — directly relevant to Day 7.
- [ ] **Journal post (200–400 words):** "Pipe arXiv into the loop —
  first findings about my own field." Pick 1–2 papers from today's
  pipeline; write what you learned.
- [ ] **Private notes:** forecast about which directions in recent
  literature will dead-end.

### Ambient listening

- [ ] Rationally Speaking or similar on epistemics.

### End-of-day

- [ ] Attest journal URL. Agent commits. Cron is staged but **not yet
  enabled** — Day 6 enables it.

---

## Day 6 — OpenClaw orchestrator + first worker (T+5)

> **This is the keystone Block 1 of the week. Protect it ruthlessly.**

### Pre-day

- [ ] On paper, sketch the worker contract input/output shape. You'll
  formalize it as JSON Schema tomorrow morning, and the agent's task
  validates against your shape.

### Block 1 — Foundations (08:30–10:00, no AI) — KEYSTONE

- [ ] **Reading:** C-B & L Ch. 1 §1.5–end + Ch. 2 §2.1–2.3
  (Multiplicative Weights derivation).
- [ ] **Problem set: Implement Multiplicative Weights from scratch on
  paper — write the algorithm, prove the regret bound.** Do NOT look at
  code. Do NOT look at course notes. Derive it. This is the keystone
  problem of the no-regret content and it is on the program's Phase 1
  problem set list, scheduled for this period.
- [ ] Mark complete.

### Block 2 manual touchpoints (10:30–12:30)

- [ ] **`[GATE]` 10:30–10:50 — Worker contract schema.** You author it
  (input: `task_id, task_type, payload, parent_request_id`; output:
  `task_id, status, result, errors, jsonl_log_path`). The agent
  validates. Hard checkpoint — every architectural promise about agents
  downstream hinges on this contract being right now.
- [ ] **10:50–11:30 — Agent-led:** orchestrator router → primary or
  fallback. Day 6 + NemoClaw is the most-untested integration in the
  architecture; the agent will fall back to multiprocessing if needed.
  Do not let it spend more than ~30 min fighting NemoClaw.
- [ ] **11:30–12:00 — Agent-led:** 5-worker sequential robustness +
  malformed-input rejection. Hard checkpoint — Day 7 cannot run on a
  flaky orchestrator.
- [ ] **12:00–12:30 — Agent-led:** `inspect_run.py` CLI. You ask it for
  the full chain on one task and verify all four levels print
  (orchestrator → worker → wrapper → vLLM call).

### Block 3 — Reading and journal

- [ ] **Reading:** Horton 2023, *Large Language Models as Simulated
  Economic Agents* (homo silicus) — required reading for tomorrow.
- [ ] **Journal post (200–400 words):** "Day 6 — orchestrator + worker,
  the smallest possible loop." Include one diagram (ASCII or SVG) of
  the call chain.
- [ ] **Private notes:** architectural decisions you regret; Week 2
  planning items derived from regrets.

### Ambient listening

- [ ] ML Street Talk or Dwarkesh recent episode on multi-agent systems.

### End-of-day

- [ ] Attest journal URL. Agent commits and **enables the arXiv cron**
  (03:00 nightly).

---

## Day 7 — First synthetic-tier experiment + retrospective (T+6)

### Pre-day

- [ ] On paper, sketch the four fixed strategies (TFT, grim trigger,
  all-C, all-D) — even though Day 4 evening's side worktree already
  drafted them as code, you should have walked through the logic
  yourself.

### Block 1 — Foundations (08:30–10:00, no AI)

- [ ] **Reading:** Camerer Ch. 4 §4.3 (cognitive hierarchy + level-k
  for repeated games) + Fudenberg & Levine Ch. 1 §1.1–1.2
  (learning-in-games framing).
- [ ] **Problem set:** finish MW proof from Day 6 if not complete;
  otherwise Camerer 4.1, 4.2.
- [ ] **TODAY IS EXPERIMENT DAY.** Do NOT let impatience to start it eat
  the foundations block. This is the program's principle.
- [ ] Mark complete.

### Block 2 manual touchpoints (10:30–12:30)

- [ ] **10:30–10:50 — Agent-led:** OpenSpiel + GRA up (hard checkpoint).
  You attest the random-vs-random sanity check looks like ~50%.
- [ ] **`[GATE]` 10:50–11:20 — Prompt contamination check.** The LLM
  agent's prompt must NOT contain strings like "tit-for-tat", "grim
  trigger", "all-C", "all-D". The agent greps for these and shows you
  the result. **Read the actual prompt yourself before approving.**
  Hard checkpoint.
- [ ] **`[GATE]` 11:20–11:30 — Pre-compute expected range.** Write down
  on paper your expected cooperation rate range for LLM vs. TFT, *before*
  the run starts. Source's published range is roughly 60–95% over 100
  rounds. The agent will compare actual vs. your range after the run.
  This is the silent-model-misconfiguration safeguard. Save the paper.
- [ ] **11:30–12:10 — Agent-led:** 500-round experiment (100 × 5
  opponents). ~20–40 min runtime depending on tok/s.
- [ ] **`[GATE]` 12:10–12:30 — Result sanity check.** Compare the
  LLM-vs-TFT actual rate to your pre-written range. If OUTSIDE the
  range, **do not declare success.** Investigate: re-check the vLLM
  startup log for MARLIN backend, look at parse-failure events, inspect
  prompt drift. The hard checkpoint fires automatically here, but you're
  the human safeguard.

### Block 3 — Weekly synthesis (13:30–14:30, longer than usual)

- [ ] **Reading:** 30-min skim of one paper from this week's arXiv
  pipeline directly related to today's experiment.
- [ ] **Journal post (600–1000 words, longer this week):** "Apparatus
  v0 — Week 1, what worked, what didn't." Hardware online, stack stable
  (or not — be honest), 7 specific things that took longer than planned,
  what the first PD run produced **(PRELIMINARY — explicit caveat that
  you haven't reviewed the data carefully yet)**, what you'll change for
  Week 2.
- [ ] **`[GATE]` Publication review.** The agent **will not auto-publish
  results.** Today's post is the retrospective with a preliminary
  caveat banner around the experiment numbers. The results announcement
  happens on a later day, after you review:
  - `logs/exp001.jsonl` integrity
  - cooperation rates against your pre-computed expected range
  - parse-failure events
  - whether the LLM tracked opponents in per-round logs

### Ambient listening

- [ ] A keynote on game theory + LLMs from a recent venue (Simons,
  NeurIPS workshop, AAMAS) — sets frame for Week 2.

### End-of-day (16:00–16:30)

- [ ] Attest weekly synthesis URL on index.
- [ ] **Retrospective with pen and notebook (30 min).** The agent will
  print the six questions and append your answers to the run log. The
  agent does NOT write, summarize, or interpret. Questions:
  1. What I shipped (every artifact, chronologically).
  2. What broke (every error, every workaround that survived as code,
     every "I'll fix this later" that didn't get fixed).
  3. What surprised me (3× as long, 0.3× as long).
  4. What I changed in the plan vs. the original day-1 design.
  5. Where Week 1 deviates from the research program document.
  6. What Week 2 needs to do — top 5 priorities, each with a
     one-sentence success criterion.
- [ ] Agent records this is the input to Week 2 planning. **Week 2
  planning is a separate task and not run today.**

---

## Cross-cutting rules for you

- **Block 1 is sacred.** If a day's Block 2 overruns, take the slack
  budget (30 min between Block 2 and Block 3), then cut Block 3 if
  needed. **Never** cut Block 1.
- **You are the only one writing to `run_state/`.** When you attest
  something to the agent, that's a state-file update. Side worktrees
  (Tracks B and C, see `AGENT_PLAN.md`) must not write here.
- **You are the only one who can clear a `[GATE]`.** Especially the Day
  7 publication review gate. The agent will halt and wait; do not
  encourage it to "just publish now."
- **Hard checkpoints abort the day.** If a hard checkpoint fails, the
  agent will write `day_aborted` to the run log and stop. The next
  day's Block 2 is gated on the prior day's success. Don't override.
- **Version pins are inviolate.** If you find yourself thinking "the
  `:gemma4` tag should also work," stop and re-read the failure-mode
  rehearsal notes.
- **The retrospective is yours.** The agent prints questions and
  records your answers. It does not write, summarize, or interpret.

## What you are explicitly NOT doing in Week 1

- No Polymarket API calls (design-only in Phase 1).
- No autoresearch overnight runs (Week 2+).
- No second model — Qwen 3.6 deferred to Week 2–3.
- No concurrency in workers (sequential only on Day 6).
- No fully autonomous loop — Day 7 result requires your review.
- No fine-tuning.
- No Week 2 planning (separate task, post-retrospective).
