"""LOOP_V0 Slice-2 worker — ml_intern.

The automated counterpart to the manual "Track B" foundational-literature
backfill. When `retrieve_literature` escalates (weak retrieval signal AND
narrow foundational coverage — see its `result.escalation`), this worker
fetches topic-relevant papers from the Semantic Scholar Graph API, embeds
their abstracts with BGE-M3, and stores them in a NEW Chroma collection
`ml_intern_fetched` — separate from the curated `papers_recent` /
foundational collections so an automated, unreviewed pull never pollutes
the human-curated stores.

Reuse (imported verbatim, NOT reimplemented) from
`pipeline.embed_and_store`: `get_embedder`, `dedupe`, `get_collection`,
`store`. The retry/backoff PATTERN mirrors
`pipeline.arxiv_scraper._get_with_backoff` (a different transport — this
worker uses `requests` against the Semantic Scholar API, not the arXiv
Atom feed).

The query is distilled deterministically (no LLM): the hypothesis is
truncated to roughly its first sentence / 280 chars.

Worker contract: `ml_intern(...)` NEVER raises (inviolate rule 7). The
whole body is wrapped so any failure — missing API key, S2 unreachable,
embed/store error — returns the standard error envelope instead.
"""
from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import requests

from pipeline.embed_and_store import dedupe, get_collection, get_embedder, store

log = logging.getLogger("ml_intern")

# Semantic Scholar Graph API — paper search endpoint. (DECISIONS D-027
# rejected S2 for the *recent-arXiv* pull because of indexing lag; here
# the job is the opposite — topic-relevant foundational backfill — where
# S2's citation graph and broad corpus are the right source.)
_S2_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
_S2_FIELDS = "paperId,externalIds,title,abstract,authors,year,citationCount"

# Hard cap on the page S2 will return regardless of caller `limit`.
_S2_LIMIT_CAP = 25

# Backoff schedule (seconds) on retriable failures (HTTP 429 / 5xx /
# network OSError), mirroring arxiv_scraper's pattern. Exhaustion raises
# MLInternFetchError, which the worker body converts to an error envelope.
_BACKOFF_SCHEDULE = (5, 15, 30, 60)
# The wall cap must be able to SPEND the schedule it declares. At 90.0 the
# final 60s backoff could never be taken: the 2026-08-16T04:00Z cycle burned
# 5+15+30 = 50s, found 50+60 > 90, and abandoned — advertising four retries
# while structurally permitting three. S2 throttles the search endpoint in
# bursts that outlast 50s (that cycle 429'd four times running while 18:00,
# 19:00, 22:00 and 02:00 recovered after one or two), so the missing retry is
# exactly the one that matters. Cap = the full schedule + a request-round-trip
# allowance; still a HARD cap (rule 7), just an honest one.
_DEFAULT_WALL_CAP_S = float(sum(_BACKOFF_SCHEDULE) + 70)

# Safety cap on a server-provided Retry-After (10 min) so a pathological
# header value can't stall the worker past any reasonable wall cap.
_RETRY_AFTER_CAP_S = 600

# Distilled-query truncation budget.
_QUERY_MAX_CHARS = 280

# Default BGE-M3 weights and Chroma store locations.
_DEFAULT_BGE_M3_WEIGHTS = "/mnt/models/bge-m3"
_REPO_ROOT = Path(__file__).resolve().parent.parent


class MLInternFetchError(RuntimeError):
    """Raised when the Semantic Scholar API cannot be reached or keeps
    returning retriable failures past the backoff schedule. Caught inside
    the worker body and converted to an error envelope; never surfaced to
    the caller as an exception."""


# Generic glue + hypothesis-framing words. Dropping them lets the salient
# content terms (a method's name + its subject) lead the short query instead
# of the method/framing preamble that the old "first N words" approach grabbed.
_QUERY_STOPWORDS = frozenset(
    "a an the of for to in on at by with and or but is are be been being this "
    "that these those it its as from into between where when which than then so "
    "we our their your my his her not no".split()
)
_QUERY_FRAMING = frozenset(
    "optimizes optimize optimizing minimizing minimize maximizing maximize "
    "measured measure measures reduction reduce reducing increase increasing "
    "improves improve improving approach method using based proposes propose "
    "hypothesis hypothesize distribution divergence value values standard".split()
)
_QUERY_MAX_TERMS = 6


def _distill_query(hypothesis_text: str) -> str:
    """Deterministically reduce a hypothesis to a SHORT keyword query.

    S2's /paper/search is keyword-AND relevance and SATURATES TO total=0 past
    ~10-12 terms (live-verified 2026-06-09: the full 39-term FASE hypothesis ->
    HTTP 200/total=0; a 4-term topic query -> thousands incl. the relevant prior
    art). The old "first sentence / 280 chars" distillation fed the whole 39-term
    sentence and returned nothing. So: strip punctuation/parens/quotes, drop
    stopwords + generic framing words, and keep the first few DISTINCTIVE content
    words (which, with framing removed, are the topic — e.g. a method name + its
    subject). No LLM, no network; deterministic. Capped at `_QUERY_MAX_TERMS`.

    NOTE (follow-up, logged): an even better route queries S2 by the SEED PAPER's
    title/arXiv id (sidesteps a confabulated hypothesis); that needs the seed
    handle plumbed through nara -> ml_intern and only applies to arxiv_pick seeds.
    """
    seen: set[str] = set()
    out: list[str] = []
    for tok in re.findall(r"[A-Za-z0-9]+", hypothesis_text):
        low = tok.lower()
        if len(low) <= 1 or low in _QUERY_STOPWORDS or low in _QUERY_FRAMING:
            continue
        if low in seen:
            continue
        seen.add(low)
        out.append(tok)
        if len(out) >= _QUERY_MAX_TERMS:
            break
    return " ".join(out)


def _parse_retry_after(headers: Any) -> int | None:
    """Positive integer seconds from a Retry-After header, else None.

    Handles the delta-seconds form only (S2 does not use the HTTP-date
    form). Returns None for missing / non-integer / non-positive values so
    the caller falls back to the static backoff schedule.
    """
    if headers is None:
        return None
    raw = headers.get("Retry-After") if hasattr(headers, "get") else None
    if raw is None:
        return None
    try:
        seconds = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None


def _s2_search(query: str, *, limit: int, wall_cap_s: float) -> list[dict]:
    """GET the S2 paper-search endpoint with backoff; return raw items.

    Single page only. Backs off along `_BACKOFF_SCHEDULE` on HTTP 429 /
    5xx / network OSError, honoring a (capped) Retry-After. Non-429 4xx
    raise MLInternFetchError immediately (they will not fix themselves).
    Tracks elapsed wall time against `wall_cap_s` and abandons rather than
    sleeping past it. Raises MLInternFetchError on exhaustion / abandon.

    The API key is read from SEMANTIC_SCHOLAR_API_KEY; a missing or empty
    key raises MLInternFetchError (the worker body turns this into an
    error envelope so the worker still never raises to its caller).
    """
    api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
    if not api_key:
        raise MLInternFetchError(
            "SEMANTIC_SCHOLAR_API_KEY is unset or empty; cannot query S2"
        )

    params = {
        "query": query,
        "limit": min(limit, _S2_LIMIT_CAP),
        "fields": _S2_FIELDS,
    }
    headers = {"x-api-key": api_key}

    start = time.monotonic()
    last_error: Exception | None = None
    retry_after: int | None = None
    for attempt in range(len(_BACKOFF_SCHEDULE) + 1):
        try:
            resp = requests.get(
                _S2_SEARCH_URL, params=params, headers=headers, timeout=60
            )
        except OSError as exc:  # ConnectionError, Timeout (subclass OSError), ...
            last_error = exc
            retry_after = None
            log.warning("network error contacting Semantic Scholar: %s", exc)
        else:
            status = resp.status_code
            if status == 200:
                return (resp.json() or {}).get("data") or []
            if status != 429 and status < 500:
                # Non-retriable client error -- will not fix itself.
                raise MLInternFetchError(
                    f"Semantic Scholar returned HTTP {status} (non-retriable)"
                )
            last_error = MLInternFetchError(
                f"Semantic Scholar returned HTTP {status}"
            )
            retry_after = _parse_retry_after(resp.headers) if status == 429 else None
            log.warning("Semantic Scholar returned HTTP %s", status)

        if attempt < len(_BACKOFF_SCHEDULE):
            delay = (
                min(retry_after, _RETRY_AFTER_CAP_S)
                if retry_after is not None
                else _BACKOFF_SCHEDULE[attempt]
            )
            elapsed = time.monotonic() - start
            if elapsed + delay > wall_cap_s:
                raise MLInternFetchError(
                    f"abandoning S2 fetch: next backoff ({delay}s) would "
                    f"exceed wall cap ({wall_cap_s}s)"
                ) from last_error
            log.warning("backing off %ss before retry %d", delay, attempt + 1)
            time.sleep(delay)

    raise MLInternFetchError(
        f"Semantic Scholar request failed after {len(_BACKOFF_SCHEDULE)} retries"
    ) from last_error


def _map_s2_paper(item: dict) -> dict:
    """Project a Semantic Scholar paper onto the embed_and_store schema.

    DEDUP ID RULE (load-bearing): arxiv_id is the paper's real ArXiv id
    when S2 carries one, otherwise a synthetic stable id `s2:<paperId>`.
    This lets non-arXiv papers flow through the verbatim-reused `dedupe`
    (which keys on arxiv_id and drops id-less / null-abstract papers)
    WITHOUT modifying dedupe or store.
    """
    external = item.get("externalIds") or {}
    arxiv_id = external.get("ArXiv") or f"s2:{item['paperId']}"
    year = item.get("year")
    authors = [
        a.get("name")
        for a in (item.get("authors") or [])
        if a.get("name")
    ]
    return {
        "title": item.get("title") or "",
        "abstract": item.get("abstract"),  # may be null; dedupe drops those
        "authors": authors,
        "arxiv_id": arxiv_id,
        "semantic_scholar_id": item["paperId"],
        "citation_count": item.get("citationCount", 0),
        "category": "",
        "publication_date": f"{year}-01-01" if year else None,
    }


def ml_intern(
    hypothesis_text: str,
    iteration_id: str,
    *,
    parent_request_id: str | None = None,
    limit: int = 20,
    wall_cap_s: float = _DEFAULT_WALL_CAP_S,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Fetch S2 papers for an escalated hypothesis, embed + store them.

    Args:
        hypothesis_text: the hypothesis whose retrieval escalated.
        iteration_id: the LOOP_V0 iteration this escalation came from;
            echoed back as `result.escalated_from`.
        parent_request_id: threaded through the worker envelope.
        limit: requested S2 page size (capped at 25).
        wall_cap_s: total wall budget for the S2 fetch (backoff-aware).
        db_path: Chroma persistent-store dir; defaults to `<repo>/chroma_db`.

    Returns the standard worker envelope. On success `result` is
    `{query, papers_fetched, papers_stored, collection: 'ml_intern_fetched',
    escalated_from: iteration_id}`. NEVER raises (inviolate rule 7): every
    failure path — empty hypothesis, missing API key, S2 down, embed/store
    error — returns `{status: 'error', result: None, errors: [...]}`.
    """
    try:
        if not isinstance(hypothesis_text, str) or not hypothesis_text.strip():
            return {
                "status": "error",
                "result": None,
                "errors": ["hypothesis_text is required and must be non-empty"],
                "parent_request_id": parent_request_id,
            }

        query = _distill_query(hypothesis_text)
        items = _s2_search(query, limit=limit, wall_cap_s=wall_cap_s)
        papers = [_map_s2_paper(item) for item in items]
        papers_fetched = len(papers)

        weights_path = os.environ.get("BGE_M3_WEIGHTS", _DEFAULT_BGE_M3_WEIGHTS)
        embedder = get_embedder(weights_path)
        store_dir = db_path or str(_REPO_ROOT / "chroma_db")
        collection = get_collection(store_dir, "ml_intern_fetched", embedder)

        existing_ids = collection.get()["ids"]
        kept, _, _, _ = dedupe(papers, existing_ids)
        papers_stored = store(collection, kept, embedder)

        return {
            "status": "passed",
            "result": {
                "query": query,
                "papers_fetched": papers_fetched,
                "papers_stored": papers_stored,
                "collection": "ml_intern_fetched",
                "escalated_from": iteration_id,
            },
            "errors": [],
            "parent_request_id": parent_request_id,
        }
    except Exception as exc:  # noqa: BLE001 -- worker must never raise (rule 7)
        log.warning("ml_intern failed: %s", exc)
        return {
            "status": "error",
            "result": None,
            "errors": [f"{type(exc).__name__}: {exc}"],
            "parent_request_id": parent_request_id,
        }
