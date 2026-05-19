#!/usr/bin/env python3
"""
Day 5 arXiv pipeline -- stage 1 of 2: scrape recent abstracts.

Pulls recent papers in the arXiv categories cs.MA / cs.GT / econ.TH from
the Semantic Scholar Graph API and writes one JSON object per line to a
JSONL file. Stage 2 (pipeline/embed_and_store.py) embeds and stores them.

This is the "direct Semantic Scholar API + simple Python" fallback path
the Day 5 plan describes (recovery_path for the ML-Intern attempt) --
slightly less smart than ML-Intern, but it always works.

Usage:
    python3 pipeline/arxiv_scraper.py \\
        --categories cs.MA,cs.GT,econ.TH \\
        --since-days 7 \\
        --output /tmp/papers_day5.jsonl

Auth: reads SEMANTIC_SCHOLAR_API_KEY from the environment. With a key the
shared-pool limit is replaced by a 1 RPS dedicated allowance; without one
the script still runs against the shared 5000-req/5-min pool. Either way
exponential backoff (1s -> 2s -> 4s -> 8s -> fail) is applied to 429 and
5xx responses, as current Semantic Scholar policy requires.

Note on category filtering: Semantic Scholar has no native arXiv-category
filter, so each category is mapped to a representative free-text query
(see _CATEGORY_QUERIES) and results are kept only when they carry an
ArXiv external ID. The originating category is recorded on each paper.
"""
import argparse
import datetime as _dt
import json
import logging
import os
import sys
import time

import requests

log = logging.getLogger("arxiv_scraper")

# Semantic Scholar Graph API -- bulk paper search endpoint.
_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"
_FIELDS = "title,abstract,authors,externalIds,citationCount,publicationDate"

# arXiv categories have no direct Semantic Scholar filter; map each to a
# representative query. Override by passing categories not listed here --
# unknown categories fall back to using the raw category string as query.
_CATEGORY_QUERIES = {
    "cs.MA": "multiagent systems",
    "cs.GT": "algorithmic game theory",
    "econ.TH": "economic theory",
}

# Exponential backoff: sleep these many seconds after successive failures,
# then give up. 1 -> 2 -> 4 -> 8 -> fail.
_BACKOFF_SCHEDULE = (1, 2, 4, 8)

# Polite spacing between successful requests (S2 keyed allowance is ~1 RPS).
_REQUEST_SPACING_S = 1.0

# Safety cap on pagination so a bad token never loops forever.
_MAX_PAGES_PER_CATEGORY = 20


class ArxivScraperError(RuntimeError):
    """Raised when the Semantic Scholar API cannot be reached."""


def _get_with_backoff(params, headers):
    """GET _SEARCH_URL with exponential backoff on 429 / 5xx / network errors.

    Retriable failures sleep 1, 2, 4, 8 seconds across successive attempts
    and then raise. Non-retriable HTTP errors (e.g. 400, 403) raise at once.
    """
    last_error = None
    for attempt in range(len(_BACKOFF_SCHEDULE) + 1):
        resp = None
        try:
            resp = requests.get(_SEARCH_URL, params=params, headers=headers, timeout=30)
        except requests.RequestException as exc:  # connection/timeout/DNS
            last_error = exc
            log.warning("network error contacting Semantic Scholar: %s", exc)

        if resp is not None and resp.status_code == 200:
            return resp.json()

        if resp is not None:
            retriable = resp.status_code == 429 or resp.status_code >= 500
            if not retriable:
                # 4xx that won't fix itself -- surface immediately.
                resp.raise_for_status()
            last_error = ArxivScraperError(
                f"Semantic Scholar returned HTTP {resp.status_code}"
            )
            log.warning("Semantic Scholar returned HTTP %s", resp.status_code)

        if attempt < len(_BACKOFF_SCHEDULE):
            delay = _BACKOFF_SCHEDULE[attempt]
            log.warning("backing off %ss before retry %d", delay, attempt + 1)
            time.sleep(delay)

    raise ArxivScraperError(
        "Semantic Scholar API request failed after "
        f"{len(_BACKOFF_SCHEDULE)} retries"
    ) from last_error


def _normalize_paper(raw, category):
    """Project a raw Semantic Scholar record onto the pipeline schema.

    Returns None when the record carries no arXiv ID (arxiv_id is the
    dedup key and is required downstream).
    """
    external_ids = raw.get("externalIds") or {}
    arxiv_id = external_ids.get("ArXiv")
    if not arxiv_id:
        return None
    authors = [a.get("name", "") for a in (raw.get("authors") or []) if a.get("name")]
    return {
        "title": raw.get("title") or "",
        "abstract": raw.get("abstract"),  # may be None; stage 2 skips those
        "authors": authors,
        "arxiv_id": arxiv_id,
        "semantic_scholar_id": raw.get("paperId"),
        "citation_count": raw.get("citationCount") or 0,
        "category": category,
        "publication_date": raw.get("publicationDate"),
    }


def _search_category(category, date_range, headers):
    """Page through every result for one category, normalized."""
    query = _CATEGORY_QUERIES.get(category, category)
    params = {
        "query": query,
        "fields": _FIELDS,
        "publicationDateOrYear": date_range,
    }
    papers = []
    token = None
    for page in range(_MAX_PAGES_PER_CATEGORY):
        if token:
            params = dict(params, token=token)
        body = _get_with_backoff(params, headers)
        for raw in body.get("data") or []:
            paper = _normalize_paper(raw, category)
            if paper is not None:
                papers.append(paper)
        token = body.get("token")
        if not token:
            break
        time.sleep(_REQUEST_SPACING_S)  # be polite between pages
    else:
        log.warning("category %s hit the %d-page cap", category, _MAX_PAGES_PER_CATEGORY)
    log.info("category %s: %d papers with an arXiv ID", category, len(papers))
    return papers


def fetch_papers(categories, since_days, api_key=None):
    """Fetch and de-duplicate recent papers across the given categories.

    Dedup key is arxiv_id; the first occurrence wins. Returns a list of
    dicts conforming to the pipeline schema (see _normalize_paper).
    """
    today = _dt.date.today()
    start = today - _dt.timedelta(days=since_days)
    date_range = f"{start.isoformat()}:{today.isoformat()}"
    headers = {"x-api-key": api_key} if api_key else {}

    seen = set()
    deduped = []
    for category in categories:
        for paper in _search_category(category, date_range, headers):
            arxiv_id = paper["arxiv_id"]
            if arxiv_id in seen:
                continue
            seen.add(arxiv_id)
            deduped.append(paper)
        time.sleep(_REQUEST_SPACING_S)  # spacing between categories
    log.info("fetched %d unique papers across %d categories",
             len(deduped), len(categories))
    return deduped


def write_jsonl(papers, output_path):
    """Write papers as JSONL -- one compact JSON object per line."""
    with open(output_path, "w", encoding="utf-8") as fh:
        for paper in papers:
            fh.write(json.dumps(paper, ensure_ascii=False) + "\n")
    log.info("wrote %d papers to %s", len(papers), output_path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--categories", required=True,
                        help="comma-separated arXiv categories, e.g. cs.MA,cs.GT,econ.TH")
    parser.add_argument("--since-days", type=int, required=True,
                        help="how many days back to search (7 for first run, 1 for cron)")
    parser.add_argument("--output", required=True,
                        help="destination JSONL path")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    categories = [c.strip() for c in args.categories.split(",") if c.strip()]
    if not categories:
        parser.error("--categories produced no usable values")

    api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
    if not api_key:
        log.warning("SEMANTIC_SCHOLAR_API_KEY not set -- using the shared rate pool")

    papers = fetch_papers(categories, args.since_days, api_key)
    write_jsonl(papers, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
