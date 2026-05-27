#!/usr/bin/env python3
"""
Unit tests for pipeline/arxiv_scraper.py.

The scraper sources papers from the arXiv API (DECISIONS.md D-027). These
tests run it against mocked arXiv Atom-feed responses (via unittest.mock --
no real network) and assert:

  * exponential backoff fires on HTTP 503 (sleeps along _BACKOFF_SCHEDULE
    then fails);
  * a non-retriable 4xx raises immediately with no backoff;
  * a 429 with a Retry-After header overrides the static schedule;
  * --jitter-seconds N inserts a random startup sleep in [0, N];
  * de-duplication on arxiv_id works, including across version suffixes;
  * the newest-first date window stops pagination and excludes old papers;
  * a page-1 failure propagates; a later-page failure returns partial results;
  * entries lacking an arXiv id are dropped;
  * the JSONL written by main() is well-formed with all required fields.

Run standalone:
    python3 tests/test_arxiv_scraper.py
or under pytest:
    pytest tests/test_arxiv_scraper.py
"""
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import arxiv_scraper  # noqa: E402

_REQUIRED_FIELDS = (
    "title", "abstract", "authors", "arxiv_id",
    "semantic_scholar_id", "citation_count", "category", "publication_date",
)

_TODAY = datetime.now(timezone.utc).date()
_IN_WINDOW = (_TODAY - timedelta(days=1)).isoformat()
_OUT_OF_WINDOW = (_TODAY - timedelta(days=60)).isoformat()


def _entry(arxiv_id, published=_IN_WINDOW, title="A Title",
           summary="An abstract.", authors=("Ada Lovelace", "Alan Turing"),
           primary="cs.GT", categories=("cs.GT",), with_id=True):
    """Build one arXiv Atom <entry> as XML text."""
    auth = "".join(f"<author><name>{a}</name></author>" for a in authors)
    cats = "".join(f'<category term="{c}"/>' for c in categories)
    id_el = f"<id>http://arxiv.org/abs/{arxiv_id}</id>" if with_id else ""
    return (f"<entry>{id_el}"
            f"<title>{title}</title><summary>{summary}</summary>"
            f"<published>{published}T12:00:00Z</published>"
            f"<updated>{published}T12:00:00Z</updated>"
            f"{auth}"
            f'<arxiv:primary_category term="{primary}"/>{cats}'
            f"</entry>")


def _feed(*entries):
    """Wrap entries in an arXiv Atom <feed> document."""
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<feed xmlns="http://www.w3.org/2005/Atom" '
            'xmlns:arxiv="http://arxiv.org/schemas/atom">'
            + "".join(entries) + '</feed>')


class _FakeResp:
    """Minimal context-manager stand-in for an http.client response."""

    def __init__(self, body):
        self._body = body.encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http_error(code, headers=None):
    return urllib.error.HTTPError("http://export.arxiv.org/api/query",
                                  code, f"HTTP {code}", headers, None)


class ExponentialBackoffTest(unittest.TestCase):

    def test_backoff_retries_429_timeout_503_then_succeeds(self):
        """429, a read timeout, then a 503 all retry; then success."""
        side_effects = [_http_error(429), TimeoutError("read timed out"),
                        _http_error(503),
                        _FakeResp(_feed(_entry("2605.00001")))]
        with mock.patch.object(arxiv_scraper.urllib.request, "urlopen",
                               side_effect=side_effects) as m_open, \
             mock.patch.object(arxiv_scraper.time, "sleep") as m_sleep:
            papers = arxiv_scraper.fetch_papers(["cs.GT"], since_days=7)

        self.assertEqual(m_open.call_count, 4)
        self.assertEqual([c.args[0] for c in m_sleep.call_args_list], [5, 15, 30])
        self.assertEqual([p["arxiv_id"] for p in papers], ["2605.00001"])

    def test_backoff_exhausts_and_raises(self):
        """Unrelenting 503s -- backoff walks _BACKOFF_SCHEDULE then gives up."""
        with mock.patch.object(arxiv_scraper.urllib.request, "urlopen",
                               side_effect=_http_error(503)), \
             mock.patch.object(arxiv_scraper.time, "sleep") as m_sleep:
            with self.assertRaises(arxiv_scraper.ArxivScraperError):
                arxiv_scraper.fetch_papers(["cs.GT"], since_days=7)

        self.assertEqual([c.args[0] for c in m_sleep.call_args_list],
                         list(arxiv_scraper._BACKOFF_SCHEDULE))

    def test_non_retriable_4xx_raises_immediately(self):
        """A 400 is not retriable -- it raises with no backoff sleeps."""
        with mock.patch.object(arxiv_scraper.urllib.request, "urlopen",
                               side_effect=_http_error(400)), \
             mock.patch.object(arxiv_scraper.time, "sleep") as m_sleep:
            with self.assertRaises(urllib.error.HTTPError):
                arxiv_scraper.fetch_papers(["cs.GT"], since_days=7)

        m_sleep.assert_not_called()

    def test_retry_after_header_overrides_schedule(self):
        """A 429 carrying Retry-After: N sleeps N (capped), not the schedule."""
        # First attempt: 429 with Retry-After: 7s. Second attempt: success.
        retry_429 = _http_error(429, headers={"Retry-After": "7"})
        feed = _feed(_entry("2605.00077"))
        with mock.patch.object(arxiv_scraper.urllib.request, "urlopen",
                               side_effect=[retry_429, _FakeResp(feed)]), \
             mock.patch.object(arxiv_scraper.time, "sleep") as m_sleep:
            papers = arxiv_scraper.fetch_papers(["cs.GT"], since_days=7)

        self.assertEqual([c.args[0] for c in m_sleep.call_args_list], [7])
        self.assertEqual([p["arxiv_id"] for p in papers], ["2605.00077"])

    def test_retry_after_is_capped(self):
        """A pathologically large Retry-After is clamped at _RETRY_AFTER_CAP_S."""
        big_429 = _http_error(429, headers={"Retry-After": "99999"})
        feed = _feed(_entry("2605.00078"))
        with mock.patch.object(arxiv_scraper.urllib.request, "urlopen",
                               side_effect=[big_429, _FakeResp(feed)]), \
             mock.patch.object(arxiv_scraper.time, "sleep") as m_sleep:
            arxiv_scraper.fetch_papers(["cs.GT"], since_days=7)

        self.assertEqual([c.args[0] for c in m_sleep.call_args_list],
                         [arxiv_scraper._RETRY_AFTER_CAP_S])

    def test_retry_after_falls_back_when_missing_or_invalid(self):
        """Missing/garbage Retry-After leaves the static schedule in effect."""
        bad = _http_error(429, headers={"Retry-After": "soon"})
        feed = _feed(_entry("2605.00079"))
        with mock.patch.object(arxiv_scraper.urllib.request, "urlopen",
                               side_effect=[bad, _FakeResp(feed)]), \
             mock.patch.object(arxiv_scraper.time, "sleep") as m_sleep:
            arxiv_scraper.fetch_papers(["cs.GT"], since_days=7)

        self.assertEqual([c.args[0] for c in m_sleep.call_args_list],
                         [arxiv_scraper._BACKOFF_SCHEDULE[0]])


class DedupAndNormalizeTest(unittest.TestCase):

    def test_dedup_on_arxiv_id_ignores_version_suffix(self):
        """Same id at v1 and v2 dedups to one; a distinct id is kept."""
        feed = _feed(_entry("2605.12345v1", title="Paper A v1"),
                     _entry("2605.12345v2", title="Paper A v2"),
                     _entry("2605.67890v1", title="Paper B"))
        with mock.patch.object(arxiv_scraper, "_get_with_backoff",
                               return_value=feed):
            papers = arxiv_scraper.fetch_papers(["cs.GT"], since_days=7)

        self.assertEqual(sorted(p["arxiv_id"] for p in papers),
                         ["2605.12345", "2605.67890"])

    def test_entry_without_arxiv_id_is_dropped(self):
        """An entry carrying no <id> is skipped; valid entries survive."""
        feed = _feed(_entry("ignored", with_id=False),
                     _entry("2605.55555"))
        with mock.patch.object(arxiv_scraper, "_get_with_backoff",
                               return_value=feed):
            papers = arxiv_scraper.fetch_papers(["cs.GT"], since_days=7)

        self.assertEqual([p["arxiv_id"] for p in papers], ["2605.55555"])

    def test_date_window_excludes_old_papers(self):
        """Newest-first: an out-of-window paper is excluded and stops paging."""
        feed = _feed(_entry("2605.20001", published=_IN_WINDOW),
                     _entry("2604.10002", published=_OUT_OF_WINDOW))
        with mock.patch.object(arxiv_scraper, "_get_with_backoff",
                               return_value=feed) as m_get:
            papers = arxiv_scraper.fetch_papers(["cs.GT"], since_days=7)

        self.assertEqual([p["arxiv_id"] for p in papers], ["2605.20001"])
        self.assertEqual(m_get.call_count, 1)  # paging stopped at the window

    def test_category_is_matched_target_for_cross_listed_paper(self):
        """A paper primary in cs.LG but cross-listed cs.MA records cs.MA."""
        feed = _feed(_entry("2605.30003", primary="cs.LG",
                            categories=("cs.LG", "cs.MA")))
        with mock.patch.object(arxiv_scraper, "_get_with_backoff",
                               return_value=feed):
            papers = arxiv_scraper.fetch_papers(["cs.MA", "cs.GT"],
                                                since_days=7)

        self.assertEqual(papers[0]["category"], "cs.MA")


class PartialResultsTest(unittest.TestCase):
    """Page 1 failures still raise; later-page failures keep what we have."""

    def test_page1_failure_propagates(self):
        """If the very first page fails, the error propagates unchanged."""
        err = arxiv_scraper.ArxivScraperError("boom")
        with mock.patch.object(arxiv_scraper, "_get_with_backoff",
                               side_effect=err):
            with self.assertRaises(arxiv_scraper.ArxivScraperError):
                arxiv_scraper.fetch_papers(["cs.GT"], since_days=7)

    def test_page2_failure_returns_partial_results(self):
        """Page 1 succeeds with a full page; page 2 fails -- keep page 1."""
        # Force pagination: shrink _PAGE_SIZE so a 2-entry page-1 triggers
        # a page-2 fetch (the loop pages while len(entries) >= _PAGE_SIZE).
        feed_p1 = _feed(_entry("2605.10001"), _entry("2605.10002"))
        err = arxiv_scraper.ArxivScraperError("page 2 throttled")
        with mock.patch.object(arxiv_scraper, "_PAGE_SIZE", 2), \
             mock.patch.object(arxiv_scraper, "_get_with_backoff",
                               side_effect=[feed_p1, err]), \
             mock.patch.object(arxiv_scraper.time, "sleep"):
            papers = arxiv_scraper.fetch_papers(["cs.GT"], since_days=7)

        self.assertEqual(sorted(p["arxiv_id"] for p in papers),
                         ["2605.10001", "2605.10002"])

    def test_page2_malformed_xml_returns_partial_results(self):
        """Page 1 succeeds; page 2 returns garbage XML -- keep page 1."""
        feed_p1 = _feed(_entry("2605.10003"), _entry("2605.10004"))
        with mock.patch.object(arxiv_scraper, "_PAGE_SIZE", 2), \
             mock.patch.object(arxiv_scraper, "_get_with_backoff",
                               side_effect=[feed_p1, "<not-xml>"]), \
             mock.patch.object(arxiv_scraper.time, "sleep"):
            papers = arxiv_scraper.fetch_papers(["cs.GT"], since_days=7)

        self.assertEqual(sorted(p["arxiv_id"] for p in papers),
                         ["2605.10003", "2605.10004"])

    def test_page1_malformed_xml_raises(self):
        """Page 1 garbage XML raises (no salvage possible)."""
        with mock.patch.object(arxiv_scraper, "_get_with_backoff",
                               return_value="<not-xml>"):
            with self.assertRaises(arxiv_scraper.ArxivScraperError):
                arxiv_scraper.fetch_papers(["cs.GT"], since_days=7)


class JitterTest(unittest.TestCase):

    def test_jitter_seconds_sleeps_random_uniform(self):
        """--jitter-seconds N calls random.uniform(0, N) and sleeps that much."""
        feed = _feed(_entry("2605.00099"))
        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "papers.jsonl")
            argv = ["--categories", "cs.GT",
                    "--since-days", "7",
                    "--jitter-seconds", "300",
                    "--output", out_path]
            with mock.patch.object(arxiv_scraper, "_get_with_backoff",
                                   return_value=feed), \
                 mock.patch.object(arxiv_scraper.random, "uniform",
                                   return_value=42.5) as m_uniform, \
                 mock.patch.object(arxiv_scraper.time, "sleep") as m_sleep:
                rc = arxiv_scraper.main(argv)

        self.assertEqual(rc, 0)
        m_uniform.assert_called_once_with(0, 300)
        # The jitter sleep is the only time.sleep invoked under a 1-page fetch.
        self.assertIn(42.5, [c.args[0] for c in m_sleep.call_args_list])

    def test_jitter_seconds_zero_is_no_op(self):
        """--jitter-seconds 0 (the default) does not sleep at startup."""
        feed = _feed(_entry("2605.00100"))
        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "papers.jsonl")
            argv = ["--categories", "cs.GT",
                    "--since-days", "7",
                    "--output", out_path]
            with mock.patch.object(arxiv_scraper, "_get_with_backoff",
                                   return_value=feed), \
                 mock.patch.object(arxiv_scraper.random, "uniform") as m_uniform, \
                 mock.patch.object(arxiv_scraper.time, "sleep") as m_sleep:
                arxiv_scraper.main(argv)

        m_uniform.assert_not_called()
        m_sleep.assert_not_called()


class JsonlOutputTest(unittest.TestCase):

    def test_main_writes_well_formed_jsonl(self):
        """main() writes one valid JSON object per line with all fields."""
        feed = _feed(_entry("2605.00010"), _entry("2605.00011"))
        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "papers.jsonl")
            argv = ["--categories", "cs.MA,cs.GT,econ.TH",
                    "--since-days", "7", "--output", out_path]
            with mock.patch.object(arxiv_scraper, "_get_with_backoff",
                                   return_value=feed):
                rc = arxiv_scraper.main(argv)

            self.assertEqual(rc, 0)
            lines = Path(out_path).read_text(encoding="utf-8").splitlines()

        self.assertEqual(len(lines), 2)
        for line in lines:
            paper = json.loads(line)  # raises if a line is not valid JSON
            for field in _REQUIRED_FIELDS:
                self.assertIn(field, paper)
            self.assertIsInstance(paper["authors"], list)
            self.assertTrue(paper["arxiv_id"])
            self.assertTrue(paper["abstract"])


if __name__ == "__main__":
    unittest.main()
