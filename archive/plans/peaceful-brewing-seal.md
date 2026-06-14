> Imported from ~/.claude/plans/peaceful-brewing-seal.md on 2026-06-14; scratch original; reference-only.

# Phase 2 / Loop v1 — trajectory + Slice 1 (Vickrey rediscovery)

## Where the apparatus actually is right now (2026-05-27 EOD)

| Component | State |
|---|---|
| LOOP_V0 Tier-3 cognitive chain (literature loop) | **live** — Phase 1-3 done this session |
| Tier-1 synthetic sandbox (exp001 PD) | **live but standalone** — runs outside the loop, not dispatched by Nara |
| Tier-2 semi-synthetic sandbox | **not built** — this plan |
| **ML-Intern (smolagents literature pipeline)** | **NOT installed.** Day-5 plan archived (`archive/notes/day5_ml_intern_plan.md`); only `pipeline/arxiv_scraper.py` survives as the recovery-path fallback |
| **Karpathy's autoresearch** (`github.com/karpathy/autoresearch`) | **NOT installed.** D-009: Week-2+ tool, never landed |
| Pi coding-agent harness (D-013) | **NOT installed.** Workers today use direct vLLM calls via `agent_wrapper.wrapper`, not Pi |
| `experiment_outcome` schema field (ARCHITECTURE.md §4.4) | **NOT built.** Phase-2 addition |

So your question — *"will we be using ML-Intern smolagents and Karpathy's autoresearch?"* — is actually asking *"when in the trajectory do we install these?"* Both are part of Phase 2 / Loop v1; neither is current capability; both are *deliberate* future slices.

## Phase 2 / Loop v1 — proposed 4-slice trajectory

This is the path from "today" to "the full v5 loop diagram operational." Each slice is reviewable + commit-table on its own.

| Slice | What lands | Tools touched | Effort | Architecture refs |
|---|---|---|---|---|
| **1 — Tier-2 MVP (this plan)** | Manual Vickrey-rediscovery experiment + `experiment_outcome` schema + LOOP_V0 evaluation of the finding | new `experiments/exp003_vickrey_rediscovery/`; `schema/iteration_record.schema.json` extension; manual topic-seed bridge | **5–8 hrs** | ARCH §3.2 Rung 1 |
| **2 — ML-Intern install + retrieve_literature augmentation** | smolagents pipeline installed; `retrieve_literature` worker dispatches ML-Intern when local Chroma top-K scores are weak; Semantic Scholar API key + arXiv API + citation-graph traversal land embedded chunks into `papers_recent` | new `workers/ml_intern.py`; `orchestrator/chroma_query.py` threshold-gated escalation; `requirements-ui.txt`+repo deps for smolagents; Semantic Scholar API config | **1–2 days** | ARCH §4.3 + §5.4 |
| **3 — Karpathy autoresearch install + Nara-dispatchable** | Clone `github.com/karpathy/autoresearch` into the repo; wrap as a `run_autoresearch` tool in `tool_registry.py`; demo by running exp003 as a bandit-driven sweep over prompt variations / temperatures / bidder counts | new `experiments/exp003_*/autoresearch_sweep.py` calling the canonical `train.py`; new tool spec; GPU scheduling against vllm-gemma (likely vllm sleep-mode during training runs) | **2–3 days** | ARCH §5.4 + D-009 |
| **4 — Full Loop v1: Nara drives Tier-2 end-to-end** | Step 1.5 (meta-review from loop_memory), Step 2.5 (red-team critic falsifies hypothesis *before* experiment), Step 5 (cross-tier replication), Step 6 sandbox-tier dispatch all wired. Nara: hypothesizes → red-teams → retrieves (Chroma + ML-Intern) → dispatches exp003 (manual) or autoresearch (training) → reads outcome → re-evaluates novelty + critique with experimental evidence | `orchestrator/nara.py` prompt + chain extension; new workers for Step 1.5 / 2.5 / 5; `experiment_outcome` plumbed through full chain | **~1 week** | ARCH §6 (full v5 loop, Phase-2 additions) |

## How it works at end-state (after Slice 4)

```
Human types research question
  │
  ▼
Step 1.5 — Meta-review:                     workers/meta_review.py
  Read last N loop_memory entries,
  distill 3–5 conditioning bullets
  │
  ▼
Step 2 — Hypothesize                        workers/hypothesize.py (today)
  Pick candidate hypothesis (mechanism-engaged per 652b0ef)
  │
  ▼
Step 2.5 — Red-team:                        workers/red_team_critic.py
  Try to falsify the hypothesis using
  literature alone, before any experiment.
  If falsified → log, return.
  Bounded retries ≤ 2.
  │
  ▼
Step 3 — Retrieve literature                workers/retrieve_literature.py (today)
  Chroma top-K. If max(scores) < threshold,
  dispatch ML-Intern for deeper lookup    ───▶ workers/ml_intern.py
  (citation graph, Semantic Scholar).        (Slice 2)
  │
  ▼
Step 4 — Robustness battery (sandbox)       experiments/exp002 pattern
  Run hypothesis evaluation N times with    (today's exp002 generalized
  prompt / seed / model variations           into a reusable worker)
  │
  ▼
Step 5 — Cross-tier replication:            workers/cross_tier_replicate.py
  Does the Tier-2 finding match what
  Tier-3 literature already knows?
  │
  ▼
Step 6 — Sandbox tier (if hypothesis        workers/run_auction_experiment.py
  needs experimental evidence):              (Slice 1)
    Tier-1 synthetic   → exp001 pattern
    Tier-2 semi-synth  → exp003 pattern
    If training needed →  run_autoresearch ─▶ orchestrator dispatches
                                              karpathy/autoresearch
                                              (Slice 3)
  │
  ▼
Step 7 — Novelty + critic (with experimental evidence)
  workers/novelty_classify.py + workers/critic_loop_v0.py (today)
  │
  ▼
Step 8 — Human gate                         (Phase-2 addition, Slice 4)
  Human reads journal entry, dispositions →
  feedback edge into loop_memory.jsonl
  Re-conditions Step 1.5 next iteration.
```

Today's session built **Steps 2 / 3 / 7** (and the substrate underneath them: multi-backend, reference-passing, model attribution, robustness verification). Slice 1 of this plan adds **Step 6 (Tier-2 sandbox)** + the `experiment_outcome` bridge. Slice 2 adds Step 3's ML-Intern escalation. Slice 3 adds Step 6's autoresearch dispatch. Slice 4 wires Steps 1.5, 2.5, 5, 8 — the orchestration glue that turns the parts into Loop v1.

## Why "Slice 1 first" rather than "install ML-Intern first" or "install autoresearch first"

- **Install ML-Intern first** would give the literature loop a stronger signal — but ML-Intern's value is only visible *when invoked*, and without a Tier-2 experiment generating new topics, there's nothing for it to evaluate that the existing arXiv scrape doesn't already cover.
- **Install autoresearch first** would let exp003 explore prompt-space via bandits from day one — but Karpathy's autoresearch is fundamentally a *training-loop* tool (one `train.py`, 5-minute experiments, bandit keep/discard). Vickrey is pure inference; the autoresearch wrapper would be awkward over a non-training workload. Better fit: install autoresearch when we have a hypothesis that actually needs training (e.g., "fine-tune a small head to predict bidder type from prompt").
- **Slice 1 first** surfaces the *concrete contracts* Slices 2/3/4 need to satisfy: what does `experiment_outcome` look like? what fields does Nara thread? where does the Tier-2/Tier-3 evidence-merge happen? Build the smallest end-to-end thing; design the rest against it.

## Slice 1 in detail (the only one this plan commits to)

### What this slice produces

1. **`experiments/exp003_vickrey_rediscovery/`** — multi-agent sealed-bid second-price auction. 4 LLM bidders with private valuations U[0, 100]; auctioneer collects bids, computes winner + payment; 50 trials of independent valuations. Measure: do bidders converge on truthful bidding (the dominant strategy)?

2. **`schema/iteration_record.schema.json` extension** — add optional `experiment_outcome` field (the contract Slices 2-4 will plumb through). Records cross-tier evidence: which experiment produced this iteration's evidence, what metric, what value.

3. **Tier-2 → Tier-3 bridge (manual)** — after exp003 runs, generate the topic seed *"LLM bidders converge to truthful bidding in repeated sealed-bid second-price auctions"* and run a LOOP_V0 iteration on it. Capture whether `novelty` flags `rediscovery` (it should, citing Camerer BGT and/or any auction-theory neighbor) and whether `critic` engages with the Vickrey theorem. The experiment's outcome becomes the iteration_record's `experiment_outcome` field.

### File layout

| Path | What |
|---|---|
| `experiments/exp003_vickrey_rediscovery/bidder.py` | NEW — LLM bidder; `compute_bid(private_valuation) → (bid, reasoning, raw)`. Reuses `agent_wrapper.wrapper.call_sync`. **Neutral prompt** (no priming with the dominant-strategy result). |
| `experiments/exp003_vickrey_rediscovery/auctioneer.py` | NEW — pure-Python sealed-bid 2nd-price auctioneer (~50 LOC). Highest bid wins; winner pays second-highest. Tie-break uniform random. |
| `experiments/exp003_vickrey_rediscovery/run.py` | NEW — driver. 50 trials × 4 fresh valuations + bidders each. Writes `results/trials.jsonl`. |
| `experiments/exp003_vickrey_rediscovery/analyze.py` | NEW — aggregator → `results/summary.md` with bid–valuation residual histogram + verdict on Vickrey rediscovery. |
| `experiments/exp003_vickrey_rediscovery/loop_bridge.py` | NEW — generate the topic seed from results, run a LOOP_V0 iteration, capture the verdict alongside the experimental outcome. |
| `experiments/exp003_vickrey_rediscovery/notes.md` | NEW — factual headlines + reflection anchors (CLAUDE.md rule #9). |
| `schema/iteration_record.schema.json` | EXTEND — add optional `experiment_outcome` field (additive; existing records validate unchanged). |
| `orchestrator/nara.py` | MINIMAL — accept an `experiment_outcome` kwarg on `run_iteration` so `loop_bridge.py` can pass it through to the iteration_record. |

### Reuse / no reuse

- **Reused** from exp001: `agent_wrapper.wrapper.call_sync` pattern, JSONL row-per-trial result format, exp001's `llm_agent.py` prompt-history threading (adapted to bid-history).
- **Reused** from this session: `orchestrator.nara.run_iteration` (for `loop_bridge.py`), the expanded Chroma collections (10 collections including Camerer BGT — the auction-relevant prior art).
- **Not reused**: `workers/play_pd_match.py` — too 2-player-shaped for the N-bidder auction structure; fresh `auctioneer.py` is cleaner than parameterizing PD logic.

### Verification

- `./.venv-chroma/bin/python experiments/exp003_vickrey_rediscovery/run.py` completes 50 trials without error. Wall-clock ≤ 30 min.
- `analyze.py` produces a `summary.md` with explicit Vickrey-rediscovery verdict (e.g., *"YES — 42/50 trials had ≥3/4 bidders within ε=5 of truthful"* or *"NO — bidders systematically shade by ~15% of valuation"*).
- `schema/iteration_record.schema.json` extension validates against the existing iteration_record fixtures + the new fixture exercising `experiment_outcome`.
- `loop_bridge.py` runs end-to-end: produces an iteration_record with the new field populated.
- Unit tests for `auctioneer.py` (sealed-bid 2nd-price is purely mechanical; tie-break uniform random).

### Out of scope (deliberately)

- ML-Intern install (Slice 2).
- Karpathy autoresearch install (Slice 3).
- Nara driving the experiment (Slice 4 / Phase 2 / Loop v1 proper).
- Step 1.5 meta-review, Step 2.5 red-team critic, Step 5 cross-tier replication (Slice 4).
- Rung-2+ auctions (first-price, English, combinatorial).
- Learning across trials.

## Execution strategy: Slice 1 + Slice 2 in parallel, with delegation

Combined commitment per the human's call: **Slice 1 + Slice 2 in this session**. Estimated combined effort 1.5–3 days. Slice 3 (autoresearch) and Slice 4 (full Loop v1) stay as deliberate follow-up slices for next session(s).

### Phase 1 — primary session lands the shared dependencies (~30 min)

These touch core schema and orchestrator surface; primary keeps them. Both delegated slices below need at least the first to be on `main`.

1. **`schema/iteration_record.schema.json`** — add optional `experiment_outcome` field (additive; existing records validate unchanged). One sample fixture exercising the new field.
2. **`orchestrator/nara.py`** — `run_iteration` accepts an optional `experiment_outcome=` kwarg; if present, threads into the final iteration_record. Default None preserves existing behavior.
3. **Commit + push** the schema + Nara extension as one slice so both delegated agents start from a clean main with the contract landed.

### Phase 2 — two parallel delegated builder agents

Once Phase 1 is on `main`, spawn TWO `builder` sub-agents simultaneously, each in its own worktree (the same delegation pattern used twice today for UI work). File-scope boundaries below prevent conflicts.

**Builder Agent α — Slice 1 (Vickrey experiment + LOOP_V0 bridge)**

- **Scope**: `experiments/exp003_vickrey_rediscovery/` ONLY
- **Files**: `bidder.py`, `auctioneer.py`, `run.py`, `analyze.py`, `loop_bridge.py`, `notes.md`, results subdirectory
- **Tests**: unit tests for `auctioneer.py` (pure math + tie-break); smoke for `bidder.py` (stub call_sync)
- **Acceptance**: 50-trial run produces `results/summary.md` with explicit Vickrey-rediscovery verdict + `loop_bridge.py` produces one iteration_record with `experiment_outcome` populated
- **Effort estimate for agent**: ~4–5 hours
- **Branch base**: `main` after Phase 1's schema+nara commit

**Builder Agent β — Slice 2 (ML-Intern install + retrieve_literature augmentation)**

- **Scope**: `workers/ml_intern.py` (new), `workers/retrieve_literature.py` (modify), `requirements.txt` / `requirements-ui.txt` for smolagents, possibly `pipeline/` for citation-graph helpers if needed
- **Spec**: Install `smolagents` (HuggingFace). New `workers/ml_intern.py` worker that, given a hypothesis text, queries Semantic Scholar API + walks citation graphs + returns extracted abstracts/methodology snippets as a list of structured chunks. Modify `workers/retrieve_literature.py` to dispatch ML-Intern when local Chroma's top-K max score is below a threshold (e.g., 0.55). When ML-Intern fetches new content, embed via BGE-M3 + append to a new Chroma collection (`ml_intern_fetched` or similar) so subsequent queries reuse the cache
- **API**: Semantic Scholar API is free with rate limits — no key required for the basic tier. ML-Intern uses Claude API for reasoning per ARCHITECTURE.md §5.4; in Phase 1 budget that's the substrate's `anthropic` backend (already wired)
- **Tests**: unit tests for the threshold-gated dispatch; smoke for the Semantic Scholar fetcher (stubbed)
- **Acceptance**: a query that previously returned only weak Osborne-Rubinstein neighbors (e.g., a Vickrey-shaped query) surfaces fresh Semantic Scholar references; embedded chunks are queryable from Chroma on the next pass
- **Effort estimate for agent**: ~1 day (the bigger of the two)
- **Branch base**: `main` after Phase 1's schema+nara commit
- **Note**: this slice may surface "Anthropic credit balance" as a blocker — flag if it does (D-035 noted credits were zero earlier this session)

**No file overlap between α and β.** α is `experiments/exp003_*/` + the schema fixture (which Phase 1 already committed). β is `workers/` + `requirements*`. Both pull from the same `main` after Phase 1.

### Phase 3 — primary session merges + reviews

For each delegated agent in turn:

1. Verify diff is scoped to declared paths (catch any "agent edited main by accident" slips like the two we saw today).
2. Run `/code-review` on the diff vs `main`.
3. Merge with `git merge --no-ff` (preserves slice provenance).
4. Run full test sweep + LOOP_V0 smoke to confirm no regression.
5. Push.

If `/code-review` flags blocking issues, send the agent corrections via `SendMessage` rather than re-spawning.

### Phase 4 — integration smoke

After both slices land:

1. Run `experiments/exp003_vickrey_rediscovery/run.py` + `analyze.py` → produces `summary.md` with Vickrey-rediscovery verdict.
2. Run `loop_bridge.py` → produces an iteration_record with `experiment_outcome` populated AND retrieval-step neighbors that include ML-Intern-fetched content (proving the threshold-gated escalation fires on an auction-shaped query).
3. Read the journal entry. Did novelty correctly classify the finding? Did the critic engage with auction-theory literature surfaced by ML-Intern?

### Operating-contract notes

- Both builder agents work in worktrees per `Agent({isolation: "worktree"})`. The UI-only restriction does NOT apply (those rules cover `ui/`; we're in `experiments/` and `workers/`).
- Today's delegation pattern surfaced two repeatable agent slips: editing main by accident, and forking from a stale base. Both are catchable post-hoc (cherry-pick + revert if needed). Brief both agents on these failure modes.

## What this plan deliberately defers

- **Slice 3 (Karpathy autoresearch install)** — separate session, separate slice. Awkward fit for Vickrey (training-loop-shaped tool over inference-only experiment).
- **Slice 4 (full Loop v1)** — Nara driving Tier-2 experiments end-to-end via dispatched workers + autoresearch. Architecturally the biggest commitment; ~1 week. After Slice 3 lands so all the tools are available.
- **Step 1.5 meta-review / Step 2.5 red-team critic / Step 5 cross-tier replication / Step 8 human-gate feedback** — Phase-2 loop additions per ARCHITECTURE.md §6. Part of Slice 4.

