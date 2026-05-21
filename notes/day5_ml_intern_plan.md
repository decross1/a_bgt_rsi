# Day 5 — ML-Intern install plan

**Decision: attempt — fall back to direct Semantic Scholar API after a
45-minute install cap.**

## Why "attempt"

ML-Intern is the per-source program preference because it returns
richer paper metadata than the raw Semantic Scholar `paper/{id}`
endpoint (related papers, citation-graph context). For the rest of
Week 1's literature use (BGE-M3 embedding + Chroma upsert) those
extras would only help.

## Why a 45-minute cap (fallback path)

`plan.yaml` day_5 failure_mode is "ML-Intern install fails on ARM64",
and `CLAUDE.md` inviolate rule 7 lists "ML-Intern → direct Semantic
Scholar API (45-min cap, Day 5)" as the time-capped, logged fallback.
The plain Semantic Scholar HTTP API is known-working: pre-stage probe
on Day 4 EOD already returned a paper for arxiv id `1706.03762`
("Attention Is All You Need"), and the API key in `.env` is valid.

## Selection record (filled after the router fired)

| Step | Status | Notes |
| ---- | ------ | ----- |
| Resolve the ML-Intern source | DONE | the plan's `git clone <url>` placeholder resolved via the `ml-intern` PyPI metadata to `github.com/huggingface/ml-intern` |
| ML-Intern install probe on ARM64 | FAIL | repo does not match the plan's assumed surface — no `requirements.txt` (uses `pyproject.toml`/`uv`), no `examples/` dir, and it is a FastAPI web app (MongoDB/Slack/sandbox), not a callable literature-query library |
| Fall back to direct API (45-min cap) | DONE | failed fast (~4 min, well under the cap); `state.fallbacks_taken.day5_ml_intern = "direct_api"` |

## Resolution (2026-05-21)

The router probe failed in ~4 minutes and the direct-API fallback was
taken. The direct path was then itself re-sourced: the pre-staged
Semantic Scholar API returned only 1 arXiv-tagged paper for the 7-day
window (S2 lags arXiv-ID indexing by weeks), so the scraper was switched
to the arXiv API — see **DECISIONS.md D-027**. Final result: 138 papers
ingested into `papers_recent`.

## Direct-API fallback shape (already pre-staged)

`scripts/test_semantic_scholar.py` validated end-to-end on Day 4 EOD
(2026-05-20). The Day-5 ingest path would call:

    GET https://api.semanticscholar.org/graph/v1/paper/search
        ?query=<cs.MA|cs.GT|econ.TH terms>&limit=100
        &fields=title,abstract,authors,year,externalIds,venue

then BGE-M3 embed the (title + abstract) and upsert into the
`papers_recent` Chroma collection per Day-3 ingest patterns.
