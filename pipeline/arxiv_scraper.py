#!/usr/bin/env python3
"""
Day 5 arXiv pipeline -- stage 1 of 2: scrape recent abstracts.

Pulls recent papers in the arXiv categories cs.MA / cs.GT / econ.TH straight
from the public arXiv API (the export.arxiv.org Atom feed) and writes one
JSON object per line to a JSONL file. Stage 2 (pipeline/embed_and_store.py)
embeds and stores them.

This is the "direct API + simple Python" fallback path the Day 5 plan
describes (recovery_path for the ML-Intern attempt).

Source decision -- DECISIONS.md D-027, human-authorized 2026-05-21. The
plan originally named the Semantic Scholar API, but S2 has no native
arXiv-category filter and lags arXiv-ID indexing by weeks: a 7-day window
yielded exactly 1 paper. The arXiv API has a native `cat:` filter and no
indexing lag, so it is the source here. `semantic_scholar_id` and
`citation_count` are not available from the arXiv API (citation_count is
~0 for brand-new papers regardless); the per-paper schema keeps both keys
(null / 0) so stage 2 is unchanged, and both can be backfilled later via
the Semantic Scholar paper/batch endpoint if a use surfaces.

Usage:
    python3 pipeline/arxiv_scraper.py \\
        --categories cs.MA,cs.GT,econ.TH \\
        --since-days 7 \\
        --output /tmp/papers_day5.jsonl

No API key required -- the arXiv API is public. Exponential backoff
(5 -> 15 -> 30 -> 60s -> fail) is applied to HTTP 429, HTTP 5xx, and
network errors -- arXiv rate-limits readily with 429s that clear within
~30s of spaced retries. A polite delay separates successive page
requests, per arXiv API etiquette. Results are sorted newest-first;
pagination stops once papers fall outside the --since-days window.
"""
import argparse
import datetime as _dt
import json
import logging
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

log = logging.getLogger("arxiv_scraper")

# arXiv API -- Atom-feed query endpoint. https avoids a 301 redirect hop.
_API_URL = "https://export.arxiv.org/api/query"

# XML namespace prefixes in the arXiv Atom feed.
_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"

# Descriptive User-Agent, per arXiv API etiquette.
_USER_AGENT = "a_bgt_rsi-research-apparatus/1.0 (+arxiv-pipeline)"

# Exponential backoff: sleep these seconds after successive failures,
# then give up. 5 -> 15 -> 30 -> 60 -> fail -- tuned for arXiv's 429
# rate-limiting, which clears within ~30s of spaced retries.
_BACKOFF_SCHEDULE = (5, 15, 30, 60)

# Papers per page, and polite spacing between page requests -- 5s stays
# clear of arXiv's 429 throttle (its guidance asks for a few seconds).
_PAGE_SIZE = 100
_REQUEST_SPACING_S = 5.0

# Safety cap on pagination so a bad response never loops forever.
_MAX_PAGES = 30


class ArxivScraperError(RuntimeError):
    """Raised when the arXiv API cannot be reached or returns bad data."""


def _get_with_backoff(params):
    """GET the arXiv API with exponential backoff on 429 / 5xx / network.

    Retriable failures (HTTP 429, HTTP 5xx, network errors) sleep
    5, 15, 30, 60 seconds across successive attempts and then raise
    ArxivScraperError. Non-retriable HTTP errors (4xx other than 429)
    raise immediately. Returns the response body as Atom XML text.
    """
    url = _API_URL + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    last_error = None
    for attempt in range(len(_BACKOFF_SCHEDULE) + 1):
        try:
            with urllib.request.urlopen(request, timeout=60) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            # 429 (rate limited) and 5xx are retriable; other 4xx are not.
            if exc.code != 429 and exc.code < 500:
                raise  # will not fix itself -- surface immediately
            last_error = exc
            log.warning("arXiv API returned HTTP %s", exc.code)
        except OSError as exc:  # URLError, TimeoutError, ConnectionError, ...
            last_error = exc
            log.warning("network error contacting arXiv: %s", exc)

        if attempt < len(_BACKOFF_SCHEDULE):
            delay = _BACKOFF_SCHEDULE[attempt]
            log.warning("backing off %ss before retry %d", delay, attempt + 1)
            time.sleep(delay)

    raise ArxivScraperError(
        f"arXiv API request failed after {len(_BACKOFF_SCHEDULE)} retries"
    ) from last_error


def _text(node, tag):
    """Stripped text of the first <tag> child of node, or '' if absent."""
    child = node.find(tag)
    return (child.text or "").strip() if child is not None and child.text else ""


def _normalize_entry(entry, target_categories):
    """Project an arXiv Atom <entry> onto the pipeline schema.

    Returns None when the entry carries no arXiv ID. `category` is the
    entry's first category that is one of the requested targets, so
    per-target counts stay meaningful even for cross-listed papers.
    """
    # <id> is e.g. http://arxiv.org/abs/2605.15049v1 -- strip the URL
    # prefix and the trailing vN so arxiv_id is the stable dedup key.
    raw_id = _text(entry, _ATOM + "id")
    if not raw_id:
        return None
    arxiv_id = re.sub(r"v\d+$", "", raw_id.rsplit("/abs/", 1)[-1])
    if not arxiv_id:
        return None

    categories = [c.get("term") for c in entry.findall(_ATOM + "category")
                  if c.get("term")]
    primary = entry.find(_ARXIV + "primary_category")
    primary_term = primary.get("term") if primary is not None else None
    if primary_term:
        categories = [primary_term] + categories
    matched = next((c for c in categories if c in target_categories), None)

    abstract = " ".join(_text(entry, _ATOM + "summary").split())
    published = _text(entry, _ATOM + "published")
    return {
        "title": " ".join(_text(entry, _ATOM + "title").split()),
        "abstract": abstract or None,   # may be None; stage 2 skips those
        "authors": [name for name in
                    (_text(a, _ATOM + "name")
                     for a in entry.findall(_ATOM + "author")) if name],
        "arxiv_id": arxiv_id,
        "semantic_scholar_id": None,    # not provided by the arXiv API
        "citation_count": 0,            # not provided; ~0 for new papers
        "category": matched or primary_term or "",
        "publication_date": published[:10] if published else None,
    }


def fetch_papers(categories, since_days):
    """Fetch and de-duplicate recent papers across the given categories.

    Queries the arXiv API for `cat:A OR cat:B OR ...` sorted newest-first,
    pages until entries fall outside the since_days window, and dedups on
    arxiv_id (first occurrence wins). Returns a list of dicts conforming
    to the pipeline schema (see _normalize_entry).
    """
    cutoff = (_dt.datetime.now(_dt.timezone.utc)
              - _dt.timedelta(days=since_days)).date().isoformat()
    targets = set(categories)
    search_query = " OR ".join(f"cat:{c}" for c in categories)

    seen = set()
    deduped = []
    for page in range(_MAX_PAGES):
        body = _get_with_backoff({
            "search_query": search_query,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "start": page * _PAGE_SIZE,
            "max_results": _PAGE_SIZE,
        })
        try:
            root = ET.fromstring(body)
        except ET.ParseError as exc:
            raise ArxivScraperError(
                f"arXiv API returned unparseable XML: {exc}") from exc
        entries = root.findall(_ATOM + "entry")
        if not entries:
            break

        kept = 0
        past_window = False
        for entry in entries:
            paper = _normalize_entry(entry, targets)
            if paper is None:
                continue
            pub = paper["publication_date"]
            if pub and pub < cutoff:
                past_window = True  # feed is newest-first -- the rest are older
                continue
            arxiv_id = paper["arxiv_id"]
            if arxiv_id in seen:
                continue
            seen.add(arxiv_id)
            deduped.append(paper)
            kept += 1
        log.info("page %d: %d entries, %d kept in-window",
                 page + 1, len(entries), kept)
        if past_window or len(entries) < _PAGE_SIZE:
            break
        time.sleep(_REQUEST_SPACING_S)  # be polite between pages
    else:
        log.warning("hit the %d-page pagination cap", _MAX_PAGES)

    log.info("fetched %d unique papers across %d categories within %d days",
             len(deduped), len(categories), since_days)
    return deduped


def write_jsonl(papers, output_path):
    """Write papers as JSONL -- one compact JSON object per line."""
    with open(output_path, "w", encoding="utf-8") as fh:
        for paper in papers:
            fh.write(json.dumps(paper, ensure_ascii=False) + "\n")
    log.info("wrote %d papers to %s", len(papers), output_path)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--categories", required=True,
                        help="comma-separated arXiv categories, e.g. cs.MA,cs.GT,econ.TH")
    parser.add_argument("--since-days", type=int, required=True,
                        help="how many days back to search (7 for first run, 1 for cron)")
    parser.add_argument("--output", required=True,
                        help="destination JSONL path")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")

    categories = [c.strip() for c in args.categories.split(",") if c.strip()]
    if not categories:
        parser.error("--categories produced no usable values")

    papers = fetch_papers(categories, args.since_days)
    write_jsonl(papers, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
