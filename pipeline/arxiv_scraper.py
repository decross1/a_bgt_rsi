#!/usr/bin/env python3
"""Day 5 arXiv pipeline -- stage 1 of 2: fetch recent abstracts.

Pulls recent papers in the arXiv categories cs.MA / cs.GT / econ.TH from
arXiv's public metadata interfaces and writes one JSON object per line to a
JSONL file. Stage 2 (pipeline/embed_and_store.py) embeds and stores them.

This is the "direct API + simple Python" fallback path the Day 5 plan
describes (recovery_path for the ML-Intern attempt).

Source decision -- DECISIONS.md D-027, human-authorized 2026-05-21. The
plan originally named the Semantic Scholar API, but S2 has no native
arXiv-category filter and lags arXiv-ID indexing by weeks: a 7-day window
yielded exactly 1 paper. arXiv's OAI-PMH interface has native category sets
and no indexing lag, so it is the primary source here. `semantic_scholar_id`
and `citation_count` are not available from arXiv metadata (citation_count is
~0 for brand-new papers regardless); the per-paper schema keeps both keys
(null / 0) so stage 2 is unchanged, and both can be backfilled later via
the Semantic Scholar paper/batch endpoint if a use surfaces.

Usage:
    python3 pipeline/arxiv_scraper.py \\
        --categories cs.MA,cs.GT,econ.TH \\
        --since-days 7 \\
        --output /tmp/papers_day5.jsonl

No API key is required. The primary source is arXiv's OAI-PMH interface,
which is intended for incremental category-set harvesting. The legacy Atom
search API is a fallback if a complete OAI-PMH harvest cannot be obtained.
The two sources are never combined: any partial source result is discarded,
so a failed page cannot be presented downstream as a fresh complete fetch.

Requests are serial and at least three seconds apart, as required by arXiv's
API terms. HTTP 429, HTTP 5xx, and network errors receive bounded exponential
backoff; Retry-After overrides the schedule when present. The cron driver
passes --jitter-seconds to decorrelate daily starts. A successful run can
write a provenance sidecar naming the interface that supplied the complete
result. Results are sorted newest-first.
"""
import argparse
import datetime as _dt
import json
import logging
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

log = logging.getLogger("arxiv_scraper")

# Official arXiv metadata endpoints.
_API_URL = "https://export.arxiv.org/api/query"
_OAI_URL = "https://oaipmh.arxiv.org/oai"
_SEARCH_SOURCE = "arxiv_search_api"
_OAI_SOURCE = "arxiv_oai_pmh"
_PROVENANCE_SCHEMA = "arxiv-fetch-provenance/v1"
_CATEGORY_PRIORITY = ("cs.GT", "econ.TH", "cs.MA")

# XML namespace prefixes in the arXiv Atom feed.
_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"
_OAI = "{http://www.openarchives.org/OAI/2.0/}"
_OAI_ARXIV = "{http://arxiv.org/OAI/arXiv/}"

# Descriptive User-Agent, per arXiv API etiquette.
_USER_AGENT = "a_bgt_rsi-research-apparatus/1.0 (+arxiv-pipeline)"

# Bounded retry keeps enough time inside the outer daily-job timeout to try
# the independent official fallback after one interface is unavailable.
_BACKOFF_SCHEDULE = (5, 15, 30, 60)

# Safety cap on a server-provided Retry-After (10 min). Prevents a
# pathological header value from stalling the cron job for hours.
_RETRY_AFTER_CAP_S = 600

# arXiv's API terms require no more than one request every three seconds
# across OAI-PMH, RSS, and the legacy query API. This process is serial.
_PAGE_SIZE = 100
_REQUEST_SPACING_S = 3.0
_REQUEST_TIMEOUT_S = 45

# Safety cap on pagination so a bad response never loops forever.
_MAX_PAGES = 30


class ArxivScraperError(RuntimeError):
    """Raised when the arXiv API cannot be reached or returns bad data."""


def _parse_retry_after(headers):
    """Return a positive integer seconds value from a Retry-After header.

    Handles the delta-seconds form only (an integer count of seconds);
    arXiv does not use the HTTP-date form in practice. Returns None for
    a missing, non-integer, zero, or negative value -- the caller falls
    back to the static backoff schedule when this returns None.
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


def _get_url_with_backoff(url, source):
    """GET one arXiv metadata URL with bounded, source-labelled retries."""
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    last_error = None
    retry_after = None  # server-suggested override for the next sleep
    for attempt in range(len(_BACKOFF_SCHEDULE) + 1):
        try:
            with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_S) as resp:
                try:
                    return resp.read().decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise ArxivScraperError(
                        f"{source} returned non-UTF-8 metadata"
                    ) from exc
        except urllib.error.HTTPError as exc:
            # 429 (rate limited) and 5xx are retriable; other 4xx are not.
            if exc.code != 429 and exc.code < 500:
                raise ArxivScraperError(
                    f"{source} returned non-retriable HTTP {exc.code}"
                ) from exc
            last_error = exc
            retry_after = _parse_retry_after(exc.headers) if exc.code == 429 else None
            if retry_after is not None:
                log.warning("source=%s HTTP %s (Retry-After: %ss)",
                            source, exc.code, retry_after)
            else:
                log.warning("source=%s HTTP %s", source, exc.code)
        except OSError as exc:  # URLError, TimeoutError, ConnectionError, ...
            last_error = exc
            retry_after = None
            log.warning("source=%s network error: %s", source, exc)

        if attempt < len(_BACKOFF_SCHEDULE):
            if retry_after is not None:
                delay = max(
                    _REQUEST_SPACING_S,
                    min(retry_after, _RETRY_AFTER_CAP_S),
                )
            else:
                delay = _BACKOFF_SCHEDULE[attempt]
            log.warning("source=%s backing off %ss before retry %d",
                        source, delay, attempt + 1)
            time.sleep(delay)

    raise ArxivScraperError(
        f"{source} request failed after {len(_BACKOFF_SCHEDULE)} retries"
    ) from last_error


def _get_with_backoff(params):
    """Compatibility wrapper for one legacy search-API page."""
    url = _API_URL + "?" + urllib.parse.urlencode(params)
    return _get_url_with_backoff(url, _SEARCH_SOURCE)


def _text(node, tag):
    """Stripped text of the first <tag> child of node, or '' if absent."""
    child = node.find(tag)
    return (child.text or "").strip() if child is not None and child.text else ""


def _matched_category(categories, target_categories):
    """Choose strategic/economic targets before the broader cs.MA scope."""
    # The curated-query compatibility path intentionally passes an empty
    # target set: its query already selected the papers, so retain the Atom
    # primary category (prepended by _normalize_entry) or first category.
    if not target_categories:
        return next(iter(categories), None)
    for category in _CATEGORY_PRIORITY:
        if category in target_categories and category in categories:
            return category
    return next((item for item in categories if item in target_categories), None)


def _normalize_entry(entry, target_categories):
    """Project an arXiv Atom <entry> onto the pipeline schema.

    Returns None when the entry carries no arXiv ID. `category` is the
    entry's first category that is one of the requested targets, so
    per-target counts stay meaningful even for cross-listed papers.
    """
    # <id> is e.g. http://arxiv.org/abs/2605.15049v1 -- strip the URL
    # prefix and the trailing vN so arxiv_id is the stable dedup key.
    raw_id = _text(entry, _ATOM + "id")
    if not raw_id or "/abs/" not in raw_id:
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
    matched = _matched_category(categories, target_categories)
    if matched is None:
        return None

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
        "category": matched,
        "publication_date": published[:10] if published else None,
    }


def _cutoff_date(since_days):
    return (_dt.datetime.now(_dt.timezone.utc)
            - _dt.timedelta(days=since_days)).date().isoformat()


def _fetch_search_api(categories, cutoff):
    """Return one complete recent-paper result from the legacy Atom API."""
    targets = set(categories)
    search_query = " OR ".join(f"cat:{c}" for c in categories)

    seen = set()
    deduped = []
    for page in range(_MAX_PAGES):
        if page:
            time.sleep(_REQUEST_SPACING_S)
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
                f"{_SEARCH_SOURCE} returned unparseable XML: {exc}"
            ) from exc
        entries = root.findall(_ATOM + "entry")
        if not entries:
            break

        kept = 0
        past_window = False
        for entry in entries:
            raw_id = _text(entry, _ATOM + "id")
            if "/api/errors#" in raw_id:
                message = _text(entry, _ATOM + "summary") or "Atom error entry"
                raise ArxivScraperError(
                    f"{_SEARCH_SOURCE} returned an error entry: {message}"
                )
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
    else:
        raise ArxivScraperError(
            f"{_SEARCH_SOURCE} hit the {_MAX_PAGES}-page completeness cap"
        )

    deduped.sort(key=lambda paper: (
        paper.get("publication_date") or "", paper["arxiv_id"]
    ), reverse=True)
    return deduped


def fetch_papers(categories, since_days):
    """Fetch a complete result from the legacy API (compatibility entrypoint)."""
    deduped = _fetch_search_api(categories, _cutoff_date(since_days))
    log.info("fetched %d unique papers across %d categories within %d days",
             len(deduped), len(categories), since_days)
    return deduped


def _oai_set_spec(category):
    """Map cs.MA to arXiv's documented OAI set form cs:cs:MA."""
    archive, separator, subject = category.partition(".")
    if not separator or not archive or not subject:
        raise ArxivScraperError(f"unsupported arXiv category for OAI: {category}")
    return f"{archive}:{archive}:{subject}"


def _normalize_oai_metadata(metadata, target_categories):
    """Project one OAI arXiv metadata element onto the pipeline schema."""
    arxiv_id = re.sub(r"v\d+$", "", _text(metadata, _OAI_ARXIV + "id"))
    created = _text(metadata, _OAI_ARXIV + "created")
    categories = _text(metadata, _OAI_ARXIV + "categories").split()
    matched = _matched_category(categories, target_categories)
    if not arxiv_id or not created or matched is None:
        return None

    authors = []
    authors_node = metadata.find(_OAI_ARXIV + "authors")
    if authors_node is not None:
        for author in authors_node.findall(_OAI_ARXIV + "author"):
            parts = [
                _text(author, _OAI_ARXIV + "forenames"),
                _text(author, _OAI_ARXIV + "keyname"),
                _text(author, _OAI_ARXIV + "suffix"),
            ]
            name = " ".join(part for part in parts if part)
            if name:
                authors.append(name)

    abstract = " ".join(_text(metadata, _OAI_ARXIV + "abstract").split())
    return {
        "title": " ".join(_text(metadata, _OAI_ARXIV + "title").split()),
        "abstract": abstract or None,
        "authors": authors,
        "arxiv_id": arxiv_id,
        "semantic_scholar_id": None,
        "citation_count": 0,
        "category": matched,
        "publication_date": created[:10],
    }


def _parse_oai_page(body, targets, cutoff):
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise ArxivScraperError(
            f"{_OAI_SOURCE} returned unparseable XML: {exc}"
        ) from exc

    error = root.find(_OAI + "error")
    if error is not None:
        code = error.get("code") or "unknown"
        message = " ".join((error.text or "").split())
        if code == "noRecordsMatch":
            return [], ""
        raise ArxivScraperError(
            f"{_OAI_SOURCE} returned OAI error {code}: {message}"
        )
    listing = root.find(_OAI + "ListRecords")
    if listing is None:
        raise ArxivScraperError(f"{_OAI_SOURCE} response omitted ListRecords")

    papers = []
    for record in listing.findall(_OAI + "record"):
        header = record.find(_OAI + "header")
        if header is None:
            raise ArxivScraperError(
                f"{_OAI_SOURCE} record omitted header"
            )
        metadata_wrapper = record.find(_OAI + "metadata")
        if metadata_wrapper is None:
            if header.get("status") == "deleted":
                continue
            raise ArxivScraperError(
                f"{_OAI_SOURCE} nondeleted record omitted metadata"
            )
        metadata = metadata_wrapper.find(_OAI_ARXIV + "arXiv")
        if metadata is None:
            raise ArxivScraperError(
                f"{_OAI_SOURCE} record omitted arXiv metadata"
            )
        paper = _normalize_oai_metadata(metadata, targets)
        if paper is not None and paper["publication_date"] >= cutoff:
            papers.append(paper)

    token_node = listing.find(_OAI + "resumptionToken")
    token = (token_node.text or "").strip() if token_node is not None else ""
    return papers, token


def _fetch_oai_pmh(categories, cutoff):
    """Harvest complete category sets changed since cutoff via OAI-PMH."""
    targets = set(categories)
    seen = set()
    deduped = []
    request_count = 0

    for category in categories:
        token = None
        for page in range(_MAX_PAGES):
            if request_count:
                time.sleep(_REQUEST_SPACING_S)
            if token:
                params = {"verb": "ListRecords", "resumptionToken": token}
            else:
                params = {
                    "verb": "ListRecords",
                    "from": cutoff,
                    "metadataPrefix": "arXiv",
                    "set": _oai_set_spec(category),
                }
            url = _OAI_URL + "?" + urllib.parse.urlencode(params)
            body = _get_url_with_backoff(url, _OAI_SOURCE)
            request_count += 1
            papers, token = _parse_oai_page(body, targets, cutoff)
            for paper in papers:
                if paper["arxiv_id"] not in seen:
                    seen.add(paper["arxiv_id"])
                    deduped.append(paper)
            log.info("OAI set %s page %d: %d in-window papers",
                     category, page + 1, len(papers))
            if not token:
                break
        else:
            raise ArxivScraperError(
                f"{_OAI_SOURCE} hit the {_MAX_PAGES}-page completeness cap"
            )

    deduped.sort(key=lambda paper: (
        paper.get("publication_date") or "", paper["arxiv_id"]
    ), reverse=True)
    return deduped


def fetch_papers_with_provenance(categories, since_days):
    """Fetch one complete result and identify the official interface used."""
    cutoff = _cutoff_date(since_days)
    fallback_from = None
    try:
        papers = _fetch_oai_pmh(categories, cutoff)
        source = _OAI_SOURCE
        endpoint = _OAI_URL
    except ArxivScraperError as exc:
        fallback_from = _OAI_SOURCE
        log.warning("source=%s failed; falling back to source=%s: %s",
                    _OAI_SOURCE, _SEARCH_SOURCE, exc)
        time.sleep(_REQUEST_SPACING_S)
        papers = _fetch_search_api(categories, cutoff)
        source = _SEARCH_SOURCE
        endpoint = _API_URL

    log.info("fetched %d unique papers across %d categories within %d days",
             len(papers), len(categories), since_days)
    provenance = {
        "schema": _PROVENANCE_SCHEMA,
        "source": source,
        "endpoint": endpoint,
        "fallback_from": fallback_from,
        "categories": list(categories),
        "since_days": since_days,
        "cutoff_date": cutoff,
        "paper_count": len(papers),
        "complete": True,
    }
    return papers, provenance


def write_jsonl(papers, output_path):
    """Write papers as JSONL -- one compact JSON object per line."""
    with open(output_path, "w", encoding="utf-8") as fh:
        for paper in papers:
            fh.write(json.dumps(paper, ensure_ascii=False) + "\n")
    log.info("wrote %d papers to %s", len(papers), output_path)


def write_provenance(provenance, output_path):
    """Write a compact source-provenance sidecar for the receipt producer."""
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(provenance, fh, sort_keys=True, separators=(",", ":"))
        fh.write("\n")


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
    parser.add_argument("--provenance-output",
                        help="optional destination for fetch-source provenance JSON")
    parser.add_argument("--jitter-seconds", type=int, default=0,
                        help="random startup delay in [0, N] seconds, to "
                             "decorrelate cron fires from the top-of-the-"
                             "minute stampede on arXiv's edge cache. "
                             "Default 0 keeps manual runs immediate.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")

    categories = [c.strip() for c in args.categories.split(",") if c.strip()]
    if not categories:
        parser.error("--categories produced no usable values")

    if args.jitter_seconds > 0:
        delay = random.uniform(0, args.jitter_seconds)
        log.info("jittering startup by %.1fs", delay)
        time.sleep(delay)

    papers, provenance = fetch_papers_with_provenance(categories, args.since_days)
    write_jsonl(papers, args.output)
    if args.provenance_output:
        write_provenance(provenance, args.provenance_output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
