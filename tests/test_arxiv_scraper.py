#!/usr/bin/env python3
"""
Unit tests for pipeline/arxiv_scraper.py.

The scraper sources papers from official arXiv metadata interfaces
(DECISIONS.md D-027). These tests use mocked XML responses only and assert:

  * exponential backoff fires on HTTP 503 (sleeps along _BACKOFF_SCHEDULE
    then fails);
  * a non-retriable 4xx raises immediately with no backoff;
  * a 429 with a Retry-After header overrides the static schedule;
  * --jitter-seconds N inserts a random startup sleep in [0, N];
  * de-duplication on arxiv_id works, including across version suffixes;
  * the newest-first date window stops pagination and excludes old papers;
  * no failed later page is returned as a complete fresh result;
  * OAI-PMH category-set results normalize and de-duplicate correctly;
  * legacy API fallback has distinct source provenance;
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


def _paper(arxiv_id):
    return {
        "title": f"Paper {arxiv_id}",
        "abstract": "An abstract.",
        "authors": ["Ada Lovelace"],
        "arxiv_id": arxiv_id,
        "semantic_scholar_id": None,
        "citation_count": 0,
        "category": "cs.GT",
        "publication_date": _IN_WINDOW,
    }


def _provenance(paper_count=1, source="arxiv_oai_pmh"):
    fallback = None if source == "arxiv_oai_pmh" else "arxiv_oai_pmh"
    endpoint = (arxiv_scraper._OAI_URL if source == "arxiv_oai_pmh"
                else arxiv_scraper._API_URL)
    return {
        "schema": arxiv_scraper._PROVENANCE_SCHEMA,
        "source": source,
        "endpoint": endpoint,
        "fallback_from": fallback,
        "categories": ["cs.GT"],
        "since_days": 7,
        "cutoff_date": arxiv_scraper._cutoff_date(7),
        "paper_count": paper_count,
        "complete": True,
    }


def _oai_record(arxiv_id, created=_IN_WINDOW,
                categories="cs.GT", title="An OAI Paper"):
    return (
        '<record><header><identifier>oai:arXiv.org:' + arxiv_id + '</identifier>'
        f'<datestamp>{created}</datestamp></header><metadata>'
        '<arXiv xmlns="http://arxiv.org/OAI/arXiv/">'
        f'<id>{arxiv_id}</id><created>{created}</created>'
        '<authors><author><keyname>Lovelace</keyname>'
        '<forenames>Ada</forenames></author></authors>'
        f'<title>{title}</title><categories>{categories}</categories>'
        '<abstract>An OAI abstract.</abstract></arXiv></metadata></record>'
    )


def _oai_response(*records, token=""):
    token_xml = f"<resumptionToken>{token}</resumptionToken>" if token else ""
    return (
        '<?xml version="1.0"?><OAI-PMH '
        'xmlns="http://www.openarchives.org/OAI/2.0/">'
        '<ListRecords>' + "".join(records) + token_xml
        + '</ListRecords></OAI-PMH>'
    )


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
            with self.assertRaises(arxiv_scraper.ArxivScraperError):
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

    def test_short_retry_after_still_respects_global_request_spacing(self):
        retry_429 = _http_error(429, headers={"Retry-After": "1"})
        feed = _feed(_entry("2605.00080"))
        with mock.patch.object(arxiv_scraper.urllib.request, "urlopen",
                               side_effect=[retry_429, _FakeResp(feed)]), \
             mock.patch.object(arxiv_scraper.time, "sleep") as m_sleep:
            arxiv_scraper.fetch_papers(["cs.GT"], since_days=7)

        m_sleep.assert_called_once_with(arxiv_scraper._REQUEST_SPACING_S)

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

    def test_strategic_category_wins_over_cs_ma_cross_list(self):
        feed = _feed(_entry("2605.30004", primary="cs.MA",
                            categories=("cs.MA", "cs.GT")))
        with mock.patch.object(arxiv_scraper, "_get_with_backoff",
                               return_value=feed):
            papers = arxiv_scraper.fetch_papers(["cs.MA", "cs.GT"],
                                                since_days=7)

        self.assertEqual(papers[0]["category"], "cs.GT")


class CompleteResultsTest(unittest.TestCase):
    """A failed page always invalidates that source's entire result."""

    def test_page1_failure_propagates(self):
        """If the very first page fails, the error propagates unchanged."""
        err = arxiv_scraper.ArxivScraperError("boom")
        with mock.patch.object(arxiv_scraper, "_get_with_backoff",
                               side_effect=err):
            with self.assertRaises(arxiv_scraper.ArxivScraperError):
                arxiv_scraper.fetch_papers(["cs.GT"], since_days=7)

    def test_page2_failure_does_not_return_partial_results(self):
        """Page 1 succeeds but page 2 fails, so the source result fails."""
        # Force pagination: shrink _PAGE_SIZE so a 2-entry page-1 triggers
        # a page-2 fetch (the loop pages while len(entries) >= _PAGE_SIZE).
        feed_p1 = _feed(_entry("2605.10001"), _entry("2605.10002"))
        err = arxiv_scraper.ArxivScraperError("page 2 throttled")
        with mock.patch.object(arxiv_scraper, "_PAGE_SIZE", 2), \
             mock.patch.object(arxiv_scraper, "_get_with_backoff",
                               side_effect=[feed_p1, err]), \
             mock.patch.object(arxiv_scraper.time, "sleep"):
            with self.assertRaises(arxiv_scraper.ArxivScraperError):
                arxiv_scraper.fetch_papers(["cs.GT"], since_days=7)

    def test_page2_malformed_xml_does_not_return_partial_results(self):
        """Page 1 succeeds but page 2 is malformed, so the result fails."""
        feed_p1 = _feed(_entry("2605.10003"), _entry("2605.10004"))
        with mock.patch.object(arxiv_scraper, "_PAGE_SIZE", 2), \
             mock.patch.object(arxiv_scraper, "_get_with_backoff",
                               side_effect=[feed_p1, "<not-xml>"]), \
             mock.patch.object(arxiv_scraper.time, "sleep"):
            with self.assertRaises(arxiv_scraper.ArxivScraperError):
                arxiv_scraper.fetch_papers(["cs.GT"], since_days=7)

    def test_page1_malformed_xml_raises(self):
        """Page 1 garbage XML raises (no salvage possible)."""
        with mock.patch.object(arxiv_scraper, "_get_with_backoff",
                               return_value="<not-xml>"):
            with self.assertRaises(arxiv_scraper.ArxivScraperError):
                arxiv_scraper.fetch_papers(["cs.GT"], since_days=7)


class OaiSourceTest(unittest.TestCase):

    def test_oai_category_sets_normalize_deduplicate_and_space_requests(self):
        duplicate = _oai_record("2605.30001", categories="cs.MA cs.GT")
        second = _oai_record("2605.30002", categories="econ.TH")
        responses = [
            _oai_response(duplicate),
            _oai_response(duplicate),
            _oai_response(second),
        ]
        with mock.patch.object(arxiv_scraper, "_get_url_with_backoff",
                               side_effect=responses) as m_get, \
             mock.patch.object(arxiv_scraper.time, "sleep") as m_sleep:
            papers = arxiv_scraper._fetch_oai_pmh(
                ["cs.MA", "cs.GT", "econ.TH"], _OUT_OF_WINDOW
            )

        self.assertEqual([p["arxiv_id"] for p in papers],
                         ["2605.30002", "2605.30001"])
        self.assertEqual(papers[1]["authors"], ["Ada Lovelace"])
        self.assertEqual(papers[1]["category"], "cs.GT")
        self.assertEqual(m_get.call_count, 3)
        self.assertEqual([call.args[0] for call in m_sleep.call_args_list],
                         [arxiv_scraper._REQUEST_SPACING_S] * 2)
        urls = [call.args[0] for call in m_get.call_args_list]
        self.assertIn("set=cs%3Acs%3AMA", urls[0])
        self.assertIn("set=cs%3Acs%3AGT", urls[1])
        self.assertIn("set=econ%3Aecon%3ATH", urls[2])

    def test_oai_resumption_token_is_exhausted_before_success(self):
        first = _oai_response(_oai_record("2605.31001"), token="next token")
        second = _oai_response(_oai_record("2605.31002"))
        with mock.patch.object(arxiv_scraper, "_get_url_with_backoff",
                               side_effect=[first, second]) as m_get, \
             mock.patch.object(arxiv_scraper.time, "sleep"):
            papers = arxiv_scraper._fetch_oai_pmh(["cs.GT"], _OUT_OF_WINDOW)

        self.assertEqual(len(papers), 2)
        self.assertIn("resumptionToken=next+token", m_get.call_args_list[1].args[0])

    def test_oai_no_records_match_is_a_complete_empty_set(self):
        body = ('<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">'
                '<error code="noRecordsMatch">none</error></OAI-PMH>')
        papers, token = arxiv_scraper._parse_oai_page(
            body, {"cs.GT"}, _IN_WINDOW
        )
        self.assertEqual((papers, token), ([], ""))

    def test_oai_explicitly_deleted_record_is_skipped(self):
        deleted = (
            '<record><header status="deleted">'
            '<identifier>oai:arXiv.org:2605.31998</identifier>'
            f'<datestamp>{_IN_WINDOW}</datestamp></header></record>'
        )
        papers, token = arxiv_scraper._parse_oai_page(
            _oai_response(deleted), {"cs.GT"}, _OUT_OF_WINDOW
        )
        self.assertEqual((papers, token), ([], ""))

    def test_oai_nondeleted_record_without_metadata_fails_completeness(self):
        malformed = (
            '<record><header>'
            '<identifier>oai:arXiv.org:2605.31999</identifier>'
            f'<datestamp>{_IN_WINDOW}</datestamp></header></record>'
        )
        with self.assertRaisesRegex(
            arxiv_scraper.ArxivScraperError,
            "nondeleted record omitted metadata",
        ):
            arxiv_scraper._parse_oai_page(
                _oai_response(malformed), {"cs.GT"}, _OUT_OF_WINDOW
            )

    def test_complete_search_fallback_has_distinct_provenance(self):
        with mock.patch.object(
            arxiv_scraper, "_fetch_oai_pmh",
            side_effect=arxiv_scraper.ArxivScraperError("OAI unavailable"),
        ), mock.patch.object(
            arxiv_scraper, "_fetch_search_api", return_value=[_paper("2605.32001")]
        ) as m_search, mock.patch.object(arxiv_scraper.time, "sleep") as m_sleep:
            papers, provenance = arxiv_scraper.fetch_papers_with_provenance(
                ["cs.GT"], 7
            )

        self.assertEqual([paper["arxiv_id"] for paper in papers], ["2605.32001"])
        self.assertEqual(provenance["source"], "arxiv_search_api")
        self.assertEqual(provenance["fallback_from"], "arxiv_oai_pmh")
        self.assertTrue(provenance["complete"])
        m_search.assert_called_once()
        m_sleep.assert_called_once_with(arxiv_scraper._REQUEST_SPACING_S)


class JitterTest(unittest.TestCase):

    def test_jitter_seconds_sleeps_random_uniform(self):
        """--jitter-seconds N calls random.uniform(0, N) and sleeps that much."""
        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "papers.jsonl")
            argv = ["--categories", "cs.GT",
                    "--since-days", "7",
                    "--jitter-seconds", "300",
                    "--output", out_path]
            with mock.patch.object(arxiv_scraper, "fetch_papers_with_provenance",
                                   return_value=([_paper("2605.00099")],
                                                 _provenance())), \
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
        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "papers.jsonl")
            argv = ["--categories", "cs.GT",
                    "--since-days", "7",
                    "--output", out_path]
            with mock.patch.object(arxiv_scraper, "fetch_papers_with_provenance",
                                   return_value=([_paper("2605.00100")],
                                                 _provenance())), \
                 mock.patch.object(arxiv_scraper.random, "uniform") as m_uniform, \
                 mock.patch.object(arxiv_scraper.time, "sleep") as m_sleep:
                arxiv_scraper.main(argv)

        m_uniform.assert_not_called()
        m_sleep.assert_not_called()


class JsonlOutputTest(unittest.TestCase):

    def test_main_writes_well_formed_jsonl(self):
        """main() writes one valid JSON object per line with all fields."""
        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "papers.jsonl")
            provenance_path = os.path.join(tmp, "provenance.json")
            argv = ["--categories", "cs.MA,cs.GT,econ.TH",
                    "--since-days", "7", "--output", out_path,
                    "--provenance-output", provenance_path]
            provenance = _provenance(paper_count=2)
            provenance["categories"] = ["cs.MA", "cs.GT", "econ.TH"]
            with mock.patch.object(arxiv_scraper, "fetch_papers_with_provenance",
                                   return_value=([_paper("2605.00010"),
                                                  _paper("2605.00011")],
                                                 provenance)):
                rc = arxiv_scraper.main(argv)

            self.assertEqual(rc, 0)
            lines = Path(out_path).read_text(encoding="utf-8").splitlines()
            written_provenance = json.loads(Path(provenance_path).read_text())

        self.assertEqual(len(lines), 2)
        for line in lines:
            paper = json.loads(line)  # raises if a line is not valid JSON
            for field in _REQUIRED_FIELDS:
                self.assertIn(field, paper)
            self.assertIsInstance(paper["authors"], list)
            self.assertTrue(paper["arxiv_id"])
            self.assertTrue(paper["abstract"])
        self.assertEqual(written_provenance, provenance)


if __name__ == "__main__":
    unittest.main()
