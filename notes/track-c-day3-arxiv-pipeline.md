# Track C — Day 3: Day 5 arXiv pipeline draft

Drafted ahead of Day 5 (`day5_block2_pipeline_implementation`). These are
the "direct Semantic Scholar API + simple Python" fallback path the Day 5
plan specifies as the recovery for a failed ML-Intern install.

## Deliverables

- `pipeline/arxiv_scraper.py` — stage 1: scrape recent abstracts to JSONL.
- `pipeline/embed_and_store.py` — stage 2: embed abstracts, store in ChromaDB.
- `tests/test_arxiv_scraper.py` — 6 tests, all pass (`python3 -m unittest
  tests.test_arxiv_scraper`).

## Decisions / things Track A should know

- **No native arXiv-category filter on Semantic Scholar.** S2 has no
  cs.MA/cs.GT/econ.TH filter, so each category maps to a representative
  free-text query (`_CATEGORY_QUERIES`) and results are kept only when
  they carry an `externalIds.ArXiv` id. Originating category is recorded
  per paper. If ML-Intern is used instead this is moot; if the fallback
  is taken, expect recall/precision to be approximate — verify the ≥30 /
  ≥50 paper counts against the plan's manual arxiv.org cross-check.

- **Backoff is 1→2→4→8→fail** on 429 / 5xx / network errors (5 attempts).
  Non-retriable 4xx (400/403) raise immediately. Verified by the tests.

- **Embedding model is BGE-M3, dense vectors, 1024-dim.** Real loader
  uses `FlagEmbedding.BGEM3FlagModel` (lazy import). If Track A
  standardized on sentence-transformers for BGE-M3 instead, swap
  `_BGEM3Embedder` — the `encode(texts) -> list[list[float]]` contract is
  all the rest of the file depends on.

- **Embeddings are passed to ChromaDB explicitly** on `collection.add()`,
  so the collection never silently falls back to all-MiniLM-L6-v2.
  Collection metadata carries `embedding_model: "BGE-M3"`.

- **Dedup** is on `arxiv_id`, in two places: within the scraper output,
  and in `embed_and_store` against ids already in the collection (cron-safe).
  `embed_and_store.dedupe()` also drops papers with no abstract.

- **`--db-path`** defaults to `chroma_db`; Track A owns that store. Track C
  did not create or touch it — verified only via the mock embedder and
  unit tests.

## Not done / open for Track A

- BGE-M3 and ChromaDB were never invoked for real (GPU + store belong to
  Track A). `embed_and_store.py` is import-clean without either installed.
- The category→query mapping is a guess; tune queries if Day 5 first-run
  paper counts come in low.
- No cron wrapper written — `--since-days 1` is the intended daily value;
  a `cron/*.sh` wrapper can be added when Track A wires up scheduling.
