# P4 — Topic auto-generation design (the closed-loop autonomy keystone)

> Produced 2026-06-30 by a dynamic workflow (`wf_348ded4c-e13`, 10 agents:
> understand → 3 diverse designs → adversarial judge → synthesis). This is a
> **reviewable design for a future P4 session** — NOT yet built. Decisions
> recorded 2026-06-30 (owner: Q1–2; agent best-judgment: Q3–7) + a real
> BGE-M3 falsifier run (below); **build-ready**. Full transcript:
> `tasks/w2x1bbzn6.output`.

## The honest headline

The "topic auto-generation keystone" is really a **dedup keystone**, not an
LLM-generation problem. At the current scale all three marquee LLM mechanisms are
weak or inert:

- **Gap-ranking is near-random at n=66** loop_memory rows (`gap = 1 − max_sim` is
  near-uniform; earns its keep only at n≈150).
- **The "independent Qwen screen" is inert at the topic seam** — `novelty_skeptic.attack`
  is a *hypothesis* refuter that returns `inconclusive` on a vague topic phrase
  (`novelty_skeptic.py:90-91`). It bites the hypothesis seam (D-044), not the topic seam.
- So **v0's real value** is (a) **BGE-M3 representational dedup** that fixes the live
  5×/3× near-duplicate pathology in the current backlog, and (b) a **budgeted,
  non-generative** topic source the coordinator can fire itself instead of waiting on a
  human `spawn_topic`.

It defuses the **same-model novelty echo** structurally: topics are **extracted external
arXiv titles, never Gemma generations**. Gemma stays out of the generative loop-closing
position; the trusted novelty gate stays downstream on the *hypothesis* (where the Qwen
skeptic is real).

## Recommendation: gap-mining (Approach A) as a thin non-generative selector + dedup keystone

| design | overall | feasibility | same-model risk (lower=safer) | testability | verdict |
|---|---|---|---|---|---|
| coordinator-proposer | 4.0 | 4 | 2 | 5 | conditional — edge bought by an **inert** Qwen screen; strip it → Gemma free-generates (worse on echo) |
| **gap-mining** ✅ | 3.7 | 4 | **2** | **5** | conditional — **wins the same-model axis**; topic = external title, never a generation |
| novelty-frontier | 3.0 | 3 | 3 | 4 | conditional — `novelty_axes` in only **14/66** rows → signature move starves; `survives` anchor re-imports echo (31/40 survives are Gemma self-critique) |

Pick gap-mining; the dedup is the payload, the gap *ranking* is latent until the corpus grows.

## Grafts (fold in from the runners-up)
1. **τ_dup calibrated on the 5+3 backlog clusters as labeled data** — don't guess the
   dedup threshold; set it so each known cluster collapses to ≤1 survivor (falsifiable offline).
2. **Cluster-exclusion-at-source** — refuse to *target* a gap whose nearest backlog region
   is a saturated cluster (decline a 6th public-goods / 4th fictitious-play topic at anchor choice).
3. **`topic_proposals.jsonl` provenance ledger** — append every candidate (kept + dropped,
   with dedup margins); the ARCH §6 / D-033 logged-human-sample seam.
4. **`origin` tag + `_topic_suggestions` fix (required)** — mined rows write to the same
   `finding_followups.jsonl` the planner *prefers* (human-spawned); tag them
   `origin:"coordinator_propose"` and add ~4 lines at `coordinator.py:237-240` so they rank as a
   non-preferred source, not masquerading as human follow-ups.

Dropped/demoted: the Qwen topic-screen as a *gate* (inert) — keep only as an optional
non-gating ledger annotation (D-052 advisory-not-gate precedent).

## Build plan (concrete; worker norm 120–390 lines)
**New files:**
- `workers/mine_paper_gap.py` (~180–230L): `_load_prior_hyp_vectors` (embed+cache),
  `_sample_recent_papers` (`coll.get(...)`), `_gap_scores` (cosine max), `_dedup` (the keystone,
  ~55L), `mine_paper_gap` (orchestrate+emit). `MOCK_LLM` → deterministic stub.
- `tests/test_mine_paper_gap.py` — done-condition: green under `MOCK_LLM`.
- `run_state/loop_memory_embeddings.json` — content-hash-keyed embedding cache.
- `memory/topic_proposals.jsonl` — provenance ledger (`finding_followups.jsonl` does not exist
  yet — worker creates it; consumer at `coordinator.py:237-240` tolerates a missing file).

**Coordinator hook (no spine surgery for v0):**
- `coordinator_actions.py:160` — `ACTIONS["mine_paper_gap"]` (`cost:1`, optional `{n,max_emit}`,
  `handler_ref` → `handle_mine_paper_gap`). Flows through `known_actions()` + generic `validate_plan`.
- `coordinator.py` — `handle_mine_paper_gap` (~30–40L) after `handle_forecast_markets` (~:593);
  one dispatch line (:610-617); one motivating sentence in `_planner_system_prompt` (:379-412);
  the `_topic_suggestions` origin-tag fix (:237-240).
- Budgeted action (NOT an assess source): inherits all gates (kill-switch, D-049 sentinel,
  30 GiB memory preflight, flock). cost:1 co-occurs with `run_loop_iteration` under budget=6.

**The dedup keystone (`_dedup`, before any topic emits):** exact re-seed skip → intra-batch
greedy cluster suppression (fixes the live 5×/3×) → candidate-vs-corpus cosine ≥ τ_dup →
density-aware target exclusion → lexical Jaccard (GT-stopwords stripped) → pending-queue dedup.

**Schema decision:** do **NOT** add `paper_gap` to the `seed.source` enum in v0 —
`_run_loop_iteration` hardcodes `source="coordinator"` (`coordinator.py:603`), so the enum
change is a no-op unless we also thread `source=` through `run_iteration` + revalidate
`journal_writer` (a spine edit). v0 carries `paper_gap` provenance in the ledger only.

## Smallest falsifying experiment (zero model spend)
**Keystone falsifier (offline, repo data):** inject the 8 labeled backlog near-dups as
candidate topics, run **only** `_dedup` (BGE-M3 + lexical, no Gemma/Qwen). **PASS iff each
cluster collapses to ≤1 survivor** (≥4/5 and ≥2/3 flagged). **FALSIFIED if known dups survive**
→ the approach amplifies the very pathology it exists to prevent; stop before any budget. This
run also *fixes* τ_dup. Companion cut: hand-label top-gap vs bottom-gap papers (expect weak
separation at n=66 — the honest signal to ship dedup-only and defer gap-ranking).

## Falsifier result (run 2026-06-30, real BGE-M3 — zero model paging)

Ran the keystone falsifier on the 21 live backlog claims. **The single-cosine τ_dup graft does
NOT cleanly work; the multi-layer dedup does.**
- 3 title-stem clusters: public-goods+noisy-observation **×6 (intra-cosine 1.000 — identical
  restatements)**, public-goods ×2 (0.929), coordination+fictitious-play ×2 (0.875).
- Cross-DISTINCT max cosine: **0.938**.
- **No clean τ separates them:** lowest intra-cluster (0.875) < highest cross-distinct (0.938),
  margin **−0.063**. A τ low enough to catch the reworded coordination pair (≤0.875) false-flags
  distinct findings; a τ high enough to preserve distinct (>0.938) misses the reworded clusters.

**Implication (refines the design):** cosine τ_dup is ONE weak layer, not the keystone. Set it
**high (~0.97)** to catch only near-identical restatements (the ×6 at 1.000). The **reworded**
near-dups share long prose stems, so the **lexical Jaccard layer** (already in `_dedup`) is what
actually separates them from distinct findings. The layered dedup survives the falsifier; the
single threshold does not — exactly what the zero-cost falsifier exists to catch before any build.

## Decisions (2026-06-30)

1. **Ship v0?** → **SHIP the keystone** *(owner)*. Dedup + non-generative selector now; gap-ranking
   latent until n≈150. The near-dup pile-up is live (cron promotes clusters every 12h).
2. **Schema provenance** → **`source="coordinator"` + ledger-only `paper_gap` for v0** *(owner)*;
   prepare the threaded-`source=` v1 in the next couple of sessions.
3. **τ_dup / dedup mechanism** → *(agent, grounded by the falsifier)* **Do NOT rely on a tuned
   cosine τ_dup** — it can't separate reworded near-dups from distinct findings at this scale. Set
   cosine τ_dup **high (~0.97, near-identical only)**; make the **lexical Jaccard + intra-batch
   greedy + density-aware** layers load-bearing. Log τ_dup as tunable, not the gate. Keeps the
   design's multi-layer `_dedup`; drops graft #1's "calibrate τ on the clusters" as primary.
4. **BGE-M3 blind spot** → *(agent)* **Confirmed: topic-gen SELECTS, never scores novelty.** The
   downstream Qwen skeptic (own retrieval, D-044) + the loop's `novelty_classify` stay the novelty
   authority. The falsifier reinforces it — BGE-M3 cosine can't even separate dups cleanly, so it's
   a selection heuristic only.
5. **Confabulation cap** → *(agent)* **Cap via the existing on-domain anchor** — a seed must be
   in-domain (cs.MA/cs.GT/econ.TH) AND a gap, not merely maximally far; always pass the abstract as
   grounding. Reject "gaps" that are only off-scope/nonsense.
6. **`anchor_cosine` MOCK_LLM gap** → *(agent)* **Accept smoke-only** for the on-domain gate
   (genuinely embedding-dependent); unit-test the rest of `_dedup` with deterministic stub vectors;
   cover the gate with one real `env -u MOCK_LLM` smoke.
7. **Qwen advisory annotation** → *(agent)* **CUT from v0.** Inert at the topic seam (critique +
   falsifier); pages Qwen for little signal under the 30 GiB margin. v0 = dedup + selector, no Qwen
   at the topic seam; the downstream hypothesis-level skeptic is untouched. Revisit only on need.

**Status:** **build-ready** for a future P4 session (dedup-keystone v0). A `DECISIONS.md` entry is
filed at build time; the agent-judgment calls (3–7) are defaults the owner may override then.
