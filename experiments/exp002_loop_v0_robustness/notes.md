# exp002 — LOOP_V0 robustness battery — notes

Phase-2 candidate A per `human/retrospectives/2026-05-27-session.md` § 6.

Re-runs the three Phase-2 topics **5× each** to check verdict stability
under the chain's default sampling variance. Same prompts, same Gemma
backend, same expanded Chroma (10 collections). No seed plumbing — the
chain's `temperature=0.7` (hypothesize) and `temperature=0.2` (critic
sub-agent) produce real per-run variance.

## Files

- `runner.py` — drives 15 iterations via `orchestrator.nara.run_iteration`,
  writes per-iteration capture to `results.jsonl`. Uses `source="loop_memory_probe"`
  (the iteration_record schema's enum value for programmatic batch runs).
- `aggregate.py` — reads `results.jsonl`, groups by topic, writes
  `results.md` with verdict-distribution tables per topic.
- `results.jsonl` — raw per-iteration capture.
- `results.md` — aggregated machine-written tables.
- `notes.md` (this file) — factual headlines + reflection anchors (reflective
  prose is the human's per CLAUDE.md inviolate rule #9).

## Reproducing

```
env -u MOCK_LLM ./.venv-chroma/bin/python experiments/exp002_loop_v0_robustness/runner.py
./.venv-chroma/bin/python experiments/exp002_loop_v0_robustness/aggregate.py
```

Wall-clock: ~7 minutes for 15 iterations + seconds for the aggregator.

---

## Headline findings (factual)

**Verdict stability: 15/15 stable across all three topics.**

| Topic | Verdict (5/5) | Top citation stability |
|---|---|---|
| 1 — open Bayesian PGG | `novel/survives` | top neighbor `2605.23513` on 4/5 runs (arXiv introspection-dynamics paper); 1/5 null |
| 2 — rediscovery probe | `rediscovery/survives` | top neighbor `blume_1995-chunk-92` on **5/5** runs |
| 3 — deliberately-wrong PD | `nonsense/falsified` | contradicting paper `osborne_rubinstein-chunk-852` on **5/5** runs |

**Wall-clock variance**:
- Topic 1: 29.5 ± 3.6 s
- Topic 2: 26.2 ± 1.1 s (tightest)
- Topic 3: 28.1 ± 6.8 s (loosest — the two runs with hypothesize's JSON-blob leak ran longer)

**Hypothesize parser fragility on Topic 3** (latent bug, observed 2/5 runs):
- 2 of 5 Topic-3 runs had hypothesize's `text` field set to the raw `{"candidates": [...], "chosen": "..."}` JSON blob instead of the parsed `chosen` text.
- Same shape as the failure on `iter-2026-05-27-005` earlier in the session.
- **The chain RECOVERS in all 5 cases** — novelty + critic produce correct verdicts (`nonsense/falsified` with backward-induction citation) even when the hypothesis_text is malformed.
- Downstream workers (novelty / critic) parse the text loosely enough that the JSON-blob form doesn't break them.

**Same-document-citation stability** (the strongest signal):
- Topic 2: every one of 5 runs cited `blume_1995-chunk-92` as the top novelty neighbor.
- Topic 3: every one of 5 runs cited `osborne_rubinstein-chunk-852` as the critic's contradicting paper.
- Retrieval + ranking are deterministic enough that the SAME chunk is identified as the relevant prior result on every fresh run.

## Reflection anchors (human writes the prose)

_(Reflective prose is the human's per CLAUDE.md inviolate rule #9. Anchors below for the human to react to in `human/retrospectives/2026-05-27-session.md` § 3–5, not as prose for me to write.)_

- 15/15 verdict stability + 10/10 citation stability on Topics 2 + 3 is a strong robustness signal. The single-sample verdicts from iter-010/011/012 weren't lucky draws. **Worth deciding**: is this enough robustness evidence to call LOOP_V0 exit criterion #4 ("at least one useful enough to keep going"), OR is more variation (prompt paraphrases, model swaps) needed?
- Topic 1's top-neighbor wobble (4/5 vs 1/5 null) is the only stochastic gap. Modest. Could be the result of novelty_classify occasionally NOT having a top_neighbor strong enough to cite. Not a verdict instability.
- The hypothesize parser failure on 2/5 Topic-3 runs is a latent bug that's been quietly visible since iter-005. The chain's downstream-worker robustness is what's saving it. **Worth deciding**: is the parser fix a follow-up, or is "the chain is robust to upstream malformation" itself a feature worth keeping?
- The robustness evidence reframes D-036's already-strong claim: not just "the critic-flip doesn't matter on these topics" but "the apparatus produces stable verdicts on these topics period — with or without the critic flip."

## What this unblocks for Phase 2 / B

- The single-sample verdicts from today are now load-bearing evidence — the apparatus produces reproducible reads on these three topics. Phase 2 / B (semi-synthetic tier) can proceed with confidence that LOOP_V0's verdict pipeline isn't a flaky base to build on.
- The hypothesize parser fragility is a worth-it-soon fix but doesn't block B.
- If you wanted, an A-extension slice could vary prompt paraphrases or backend models — the harness in `runner.py` is small enough to extend.
