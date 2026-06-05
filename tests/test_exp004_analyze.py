"""Unit tests for experiments/exp004_combinatorial_auction/analyze.py.

MOCK_LLM-safe: analyze is pure-Python (reads a trials.jsonl fixture, writes
summary.md/json). No LLM dependency. The load-bearing assertions:

  - a clean mechanism (truthful bids, no parse failures) -> verdict YES
  - a high-parse-failure mechanism -> verdict INVALID (NOT YES), even though
    its residuals are ~0 (bid:=valuation default would falsely read truthful).
    This is carryover #4: a high parse-failure run must never silently pass.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.exp004_combinatorial_auction import analyze


def _clean_block() -> dict:
    # All residuals within eps=5, no parse failures -> truthful.
    return {
        "bids": [{"(0,)": 30.0, "(1,)": 20.0, "(0, 1)": 55.0}],
        "residuals": [1.0, -2.0, 0.0, 3.0, -1.0, 0.5],
        "reasonings": ["truthful bid is dominant", "compute marginal value"],
        "allocative_efficiency": 0.98,
        "revenue": 42.0,
    }


def _parse_fail_block() -> dict:
    # Residuals are ~0 (would FALSELY read as truthful) but most bidder calls
    # are parse failures -> the gate must force INVALID.
    return {
        "bids": [{"(0,)": 30.0, "(1,)": 20.0, "(0, 1)": 55.0}],
        "residuals": [0.0, 0.0, 0.0, 0.0],
        "reasonings": [
            "parse_failure: no tool call",
            "parse_failure: malformed json",
            "parse_failure: empty",
            "ok actual reasoning",
        ],
        "allocative_efficiency": 1.0,
        "revenue": 10.0,
    }


def _write_fixture(path: Path) -> None:
    rows = [
        {
            "trial": i,
            "valuations": [{"(0,)": 29.0, "(1,)": 22.0, "(0, 1)": 55.0}],
            "mechanisms": {
                "clean_mech": _clean_block(),
                "parsefail_mech": _parse_fail_block(),
            },
        }
        for i in range(5)
    ]
    with open(path, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


class AnalyzeVerdicts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "trials.jsonl"
        _write_fixture(self.path)
        rows = analyze._load_rows(self.path)
        self.summary = analyze.build_summary(rows)
        self.by_name = {m["mechanism"]: m for m in self.summary["per_mechanism"]}

    def tearDown(self):
        self.tmp.cleanup()

    def test_n_trials(self):
        self.assertEqual(self.summary["n_trials"], 5)

    def test_clean_mechanism_is_yes(self):
        m = self.by_name["clean_mech"]
        self.assertEqual(m["verdict"], "YES")
        self.assertGreaterEqual(m["truthful_fraction"], 0.75)
        self.assertEqual(m["parse_failure_rate"], 0.0)

    def test_parse_failure_mechanism_is_invalid_not_yes(self):
        m = self.by_name["parsefail_mech"]
        self.assertEqual(m["verdict"], "INVALID")
        self.assertNotEqual(m["verdict"], "YES")
        # parse_failure_rate = 3/4 = 0.75 > 0.25 gate.
        self.assertGreater(m["parse_failure_rate"], analyze.PARSE_FAILURE_GATE)
        # Residuals alone would have read as truthful — the gate overrode it.
        self.assertGreaterEqual(m["truthful_fraction"], 0.75)

    def test_summary_json_schema(self):
        pub = analyze._public_summary(self.summary)
        self.assertIn("per_mechanism", pub)
        self.assertEqual(pub["n_trials"], 5)
        for entry in pub["per_mechanism"]:
            self.assertEqual(
                set(entry.keys()),
                {
                    "mechanism",
                    "truthful_fraction",
                    "mean_efficiency",
                    "mean_revenue",
                    "parse_failure_rate",
                    "verdict",
                },
            )

    def test_main_writes_both_artifacts(self):
        # Point the module paths at the tmp dir and run main end-to-end.
        tmp_dir = Path(self.tmp.name)
        orig = (analyze.TRIALS_PATH, analyze.SUMMARY_MD_PATH, analyze.SUMMARY_JSON_PATH)
        analyze.TRIALS_PATH = self.path
        analyze.SUMMARY_MD_PATH = tmp_dir / "summary.md"
        analyze.SUMMARY_JSON_PATH = tmp_dir / "summary.json"
        try:
            rc = analyze.main()
        finally:
            (analyze.TRIALS_PATH, analyze.SUMMARY_MD_PATH,
             analyze.SUMMARY_JSON_PATH) = orig
        self.assertEqual(rc, 0)
        self.assertTrue((tmp_dir / "summary.md").exists())
        loaded = json.loads((tmp_dir / "summary.json").read_text())
        self.assertEqual(loaded["n_trials"], 5)


if __name__ == "__main__":
    unittest.main()
