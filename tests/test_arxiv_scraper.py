#!/usr/bin/env python3
"""
Unit tests for pipeline/arxiv_scraper.py.

Runs the scraper against mocked Semantic Scholar responses (via
unittest.mock -- no `responses` dependency, no real network) and asserts:

  * exponential backoff fires on HTTP 429 (sleeps 1, 2, 4, 8 then fails);
  * de-duplication on arxiv_id works across categories;
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
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import arxiv_scraper  # noqa: E402

_REQUIRED_FIELDS = (
    "title", "abstract", "authors",
    "arxiv_id", "semantic_scholar_id", "citation_count",
)


class FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = body or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise arxiv_scraper.requests.HTTPError(f"HTTP {self.status_code}")


def _raw_paper(arxiv_id, paper_id=None, title="A Title", abstract="An abstract."):
    """Build one raw Semantic Scholar record carrying an arXiv external ID."""
    return {
        "paperId": paper_id or f"s2-{arxiv_id}",
        "title": title,
        "abstract": abstract,
        "authors": [{"name": "Ada Lovelace"}, {"name": "Alan Turing"}],
        "externalIds": {"ArXiv": arxiv_id},
        "citationCount": 7,
        "publicationDate": "2026-05-15",
    }


def _s2_body(papers, token=None):
    """Wrap raw records in the bulk-search response envelope."""
    return {"total": len(papers), "token": token, "data": papers}


class ExponentialBackoffTest(unittest.TestCase):

    def test_backoff_fires_on_429_then_succeeds(self):
        """Two 429s, then a 200 -- backoff sleeps 1s then 2s and recovers."""
        responses = [
            FakeResponse(429),
            FakeResponse(429),
            FakeResponse(200, _s2_body([_raw_paper("2405.00001")])),
        ]
        with mock.patch.object(arxiv_scraper.requests, "get",
                               side_effect=responses) as m_get, \
             mock.patch.object(arxiv_scraper.time, "sleep") as m_sleep:
            papers = arxiv_scraper.fetch_papers(["cs.MA"], since_days=7)

        self.assertEqual(m_get.call_count, 3)
        # The first two sleeps are the backoff delays; any later sleep is
        # the polite inter-request spacing, which is not under test here.
        sleeps = [c.args[0] for c in m_sleep.call_args_list]
        self.assertEqual(sleeps[:2], [1, 2])
        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0]["arxiv_id"], "2405.00001")

    def test_backoff_exhausts_and_raises(self):
        """Unrelenting 429s -- backoff sleeps 1, 2, 4, 8 then gives up."""
        with mock.patch.object(arxiv_scraper.requests, "get",
                               return_value=FakeResponse(429)), \
             mock.patch.object(arxiv_scraper.time, "sleep") as m_sleep:
            with self.assertRaises(arxiv_scraper.ArxivScraperError):
                arxiv_scraper.fetch_papers(["cs.GT"], since_days=7)

        self.assertEqual([c.args[0] for c in m_sleep.call_args_list], [1, 2, 4, 8])

    def test_non_retriable_status_raises_immediately(self):
        """A 400 is not retriable -- it raises with no backoff sleeps."""
        with mock.patch.object(arxiv_scraper.requests, "get",
                               return_value=FakeResponse(400)), \
             mock.patch.object(arxiv_scraper.time, "sleep") as m_sleep:
            with self.assertRaises(arxiv_scraper.requests.HTTPError):
                arxiv_scraper.fetch_papers(["cs.GT"], since_days=7)

        m_sleep.assert_not_called()


class DedupTest(unittest.TestCase):

    def test_dedup_across_categories(self):
        """The same arxiv_id seen in two categories appears once."""
        shared = _raw_paper("2405.12345", title="Shared paper")
        unique = _raw_paper("2405.99999", title="Unique paper")
        responses = [
            FakeResponse(200, _s2_body([shared])),          # cs.MA page
            FakeResponse(200, _s2_body([shared, unique])),  # cs.GT page
        ]
        with mock.patch.object(arxiv_scraper.requests, "get",
                               side_effect=responses), \
             mock.patch.object(arxiv_scraper.time, "sleep"):
            papers = arxiv_scraper.fetch_papers(["cs.MA", "cs.GT"], since_days=7)

        ids = sorted(p["arxiv_id"] for p in papers)
        self.assertEqual(ids, ["2405.12345", "2405.99999"])

    def test_records_without_arxiv_id_are_dropped(self):
        """Records lacking an ArXiv external ID are skipped entirely."""
        no_arxiv = {"paperId": "s2-x", "title": "No arXiv id",
                    "abstract": "x", "authors": [], "externalIds": {},
                    "citationCount": 0}
        body = _s2_body([no_arxiv, _raw_paper("2405.55555")])
        with mock.patch.object(arxiv_scraper.requests, "get",
                               return_value=FakeResponse(200, body)), \
             mock.patch.object(arxiv_scraper.time, "sleep"):
            papers = arxiv_scraper.fetch_papers(["cs.MA"], since_days=7)

        self.assertEqual([p["arxiv_id"] for p in papers], ["2405.55555"])


class JsonlOutputTest(unittest.TestCase):

    def test_main_writes_well_formed_jsonl(self):
        """main() writes one valid JSON object per line with all fields."""
        body = _s2_body([_raw_paper("2405.00010"), _raw_paper("2405.00011")])
        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "papers.jsonl")
            argv = ["--categories", "cs.MA,cs.GT,econ.TH",
                    "--since-days", "7", "--output", out_path]
            with mock.patch.object(arxiv_scraper.requests, "get",
                                   return_value=FakeResponse(200, body)), \
                 mock.patch.object(arxiv_scraper.time, "sleep"):
                rc = arxiv_scraper.main(argv)

            self.assertEqual(rc, 0)
            lines = Path(out_path).read_text(encoding="utf-8").splitlines()

        # Three categories each return the same two papers -> deduped to 2.
        self.assertEqual(len(lines), 2)
        for line in lines:
            paper = json.loads(line)  # raises if a line is not valid JSON
            for field in _REQUIRED_FIELDS:
                self.assertIn(field, paper)
            self.assertIsInstance(paper["authors"], list)
            self.assertTrue(paper["arxiv_id"])


if __name__ == "__main__":
    unittest.main()
