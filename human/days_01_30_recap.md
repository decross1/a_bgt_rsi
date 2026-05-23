# Days 1–30 — Phase 0 (pre-flight) recap

> Stub of pre-Week-1 history. Not a day-by-day reconstruction; that
> information isn't recoverable from the repo. This file exists so the
> 90-day arc is documented end-to-end, not so Days 1–30 are re-lived.
>
> Authoritative source for **decisions** locked during Phase 0:
> [`../DECISIONS.md`](../DECISIONS.md) entries D-001 through D-018.

---

## 1. What Phase 0 was for

Three things, in order of importance:

1. **Provisioning the workstation.** The NVIDIA DGX Spark (GB10) was
   ordered, delivered, racked, and brought online. Network, UPS, and
   thermal environment were set up to spec (≥ 6" clearance on all
   sides, ambient ≤ 30 °C, switch-based networking — NOT USB-C, which
   is documented to cause flakiness).
2. **Pre-staging software and weights.** vLLM image pulled and
   verified; OpenShell cluster image pulled; Gemma 4 26B-A4B-NVFP4
   weights staged at `/mnt/models/gemma-4-26b-a4b-nvfp4`; BGE-M3
   weights at `/mnt/models/bge-m3`; books and third-party repos
   staged in `books/` and `clones/` (both gitignored).
3. **Making decisions that don't have to be remade.** D-001 through
   D-018 captured the rationale for every load-bearing choice
   (hardware, models, embedding model, version pins, file structure,
   logging discipline, fallback policy, etc.). The point of the
   decision log is so Phase 1 doesn't waste days re-arguing already-
   settled questions.

The researcher was also walking through the four
**failure-mode rehearsals** during Phase 0: NemoClaw fallback path,
CUTLASS_FP4 gibberish trap, CUDA 13.2 rollback, and filesystem-cache
remediation. These are all written up in
[`daily_plan.md`](daily_plan.md) §"Pre-flight" / "Failure-mode rehearsal".

---

## 2. Decisions locked pre-Week-1 (D-001 through D-018)

The decisions that were already made when Day 31 (Week 1, Day 1)
began. Cross-reference to [`../DECISIONS.md`](../DECISIONS.md) for
the full rationale and alternatives-considered for each.

| ID | Decision | Why it matters in Week 1+ |
|---|---|---|
| D-001 through D-005 | Foundational scope decisions (apparatus vs findings; tier ladder; hardware class; model class) | Frames every Week 1 + Phase 2 task: what we're building, why, how. |
| D-006 | Qwen 3.6 deferred to Week 2–3 | Week 1 runs single-model on Gemma 4; second model not introduced until alignment evidence accumulates. |
| D-007–D-010 | Stack choices (vLLM, BGE-M3 embedding, ChromaDB, OpenSpiel / GRA for game arenas) | Version pins are inviolate (CLAUDE.md rule 2). |
| D-011–D-014 | Logging discipline, append-only JSONL, integrity verifier | Day-2 schema authoring is hard-gate because the rest of Phase 1 depends on these contracts being right. |
| D-015–D-017 | Fallback policy (time-capped, logged), image-digest pinning, file-boundary discipline for concurrent tracks | Plan.yaml `fallbacks_taken` field; Track A/B/C/D ownership tables. |
| D-018 | Decision to skip Polymarket live in Phase 1 (design-only) | CFTC compliance work blocked from Week 1; revisited at Day-90 Phase-2-entry attestation. |

D-019 through D-027 land **inside** Week 1 and are recorded there
(MTP enablement, schema amendments, arXiv source switch, etc.).

---

## 3. What was NOT done in Phase 0

This is the list to be honest about — things that look like they should
have happened but didn't, because the decision was to defer them:

- **NemoClaw was not actually installed.** The decision (locked as a
  Day-1 fallback, D-021) was: attempt NemoClaw on Day 1; if it
  doesn't come up cleanly within the 90-min cap, fall back to plain
  Docker and revisit in Week 2+. Days 1 and 6 ran on the plain-Docker
  / multiprocessing fallback.
- **No actual model inference ran in Phase 0.** vLLM was pulled and
  smoke-tested with a hello-world only. Real benchmarks waited for
  Day 1's `day1_block2_bench` task.
- **No code was written for the apparatus itself.** All Phase 0 code
  staging was reading third-party repos, NOT writing the wrapper, the
  orchestrator, the pipelines, or the experiment harness. Day 1
  starts from a near-empty repo.
- **No reading was done past the Phase 1 syllabus.** Phase 0 reading
  was limited to the pre-flight syllabus (Osborne & Rubinstein
  Ch. 1–5, refreshers). The keystone reading (Cesa-Bianchi & Lugosi
  Ch. 1–2, the Multiplicative Weights derivation) was reserved for
  Week 1.

---

## 4. Known unknowns going into Day 31

The list of things that were *known to be unresolved* when Week 1
began, captured so the run log can be read against this list and we
can see which got resolved and how:

- **Will NemoClaw onboarding actually work?** (Resolved Day 1:
  fallback selected — D-021.)
- **Will single-stream Gemma 4 decode at usable tok/s?** (Resolved
  partially Day 1: 32 tok/s at NVFP4 baseline; later boosted to 69
  via MTP — D-022.)
- **Will Semantic Scholar's API have the recency we need for cs.MA /
  cs.GT / econ.TH?** (Resolved Day 5: no — S2 lags arXiv-ID indexing
  by weeks. Switched to arXiv API directly — D-027.)
- **Will OpenClaw + NemoClaw integration come together by Day 6?**
  (Partly resolved Day 6: NemoClaw still not installed, so OpenClaw
  ran on the Python multiprocessing fallback. NemoClaw + OpenClaw
  is a Week 2+ revisit.)
- **Will the tool-call invocation rate be high enough on Day 4 for
  the synthetic-tier experiment to be meaningful?** (Resolved Day 4:
  100% on the mock tool. Real test is Day 7.)
- **What's the actual baseline cooperation rate for Gemma 4 vs TFT?**
  (Open until Day 7. Pre-specified expected range: 60–95%.)
- **How load-bearing is the Block-1-as-precondition discipline?**
  (Surfaced post-Week-1: the precondition edge made the daily
  Block 1 gate Block 2, which is now *decoupled* per
  [`../agent/autonomy.md`](../agent/autonomy.md) §7. Phase 0 didn't
  surface this as an issue because Phase 0 had no Block 2.)

---

## 5. What Day 31 inherits from Phase 0

When Week 1 started, the repo was approximately this:

- `books/` and `clones/` staged, both gitignored.
- `.env.example` present; `.env` (with credentials) was created during
  pre-flight credential staging.
- `plan.yaml` present, with Day 1–7 tasks already specified.
- `CLAUDE.md`, `START_HERE.md`, `PROJECT_CONTEXT.md`, `ARCHITECTURE.md`,
  `DECISIONS.md` (with D-001…D-018) present.
- `run_state/week1.state.json` initialized with `current_day=day_1`,
  no completed tasks, no fallbacks, no gates pending.
- `run_state/week1.run.jsonl` empty.
- No `agent_wrapper/`, no `pipeline/`, no `orchestrator/`, no
  `experiments/`, no `chroma_db/`, no `tests/` of consequence.

By the time Week 1 finishes, all of those directories exist and are
populated. The arc from "near-empty" to "first synthetic-tier
experiment + publication-gate halt" is what Phase 0 set up but did
not start.

---

## 6. If you need to know more about Phase 0

- `notes/research/` — substantive pre-Week-1 artifacts (adversarial
  review notes from 2026-05-19 are the most consequential — they
  fed into D-024 / D-025).
- `notes/day1-setup.md` — minimal hardware bring-up log; written
  Day 1, references Phase 0 staging.
- `notes/day1-bench-debug.md` — Day 1 benchmark debug notes; pre-MTP.
- The user (the researcher) — for anything not captured above.

For everything from Day 31 forward, [`../current_day.md`](../current_day.md)
and `run_state/week1.run.jsonl` are authoritative.
