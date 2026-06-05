# DESIGN-ONLY paper forecasting; NO live trading (CLAUDE.md CFTC guardrail).
"""Offline unit tests for experiments/exp007_polymarket/market_data.py.

Fully offline: ``requests.get`` is monkeypatched with a canned Gamma
response, and a committed fixture exercises the same normalization path.
No live model, no real network. Asserts:
  - YES price -> implied_prob in [0, 1]
  - resolved / outcome parsed (YES-won, NO-won, open)
  - a network error raises MarketDataError without crashing
  - read-only: no POST/order/trade/wallet/auth symbols in the source
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.exp007_polymarket import market_data as md

FIXTURE = (
    REPO_ROOT
    / "experiments"
    / "exp007_polymarket"
    / "fixtures"
    / "gamma_markets_sample.json"
)

# A canned Gamma /markets response (raw upstream shape).
CANNED = [
    {
        "id": "abc123",
        "question": "Will X happen?",
        "outcomes": "[\"Yes\", \"No\"]",
        "outcomePrices": "[\"0.62\", \"0.38\"]",
        "closed": False,
        "category": "Politics",
        "endDate": "2026-12-31T00:00:00Z",
    },
    {
        "id": "won",
        "question": "Resolved YES market?",
        "outcomes": "[\"Yes\", \"No\"]",
        "outcomePrices": "[\"1.0\", \"0.0\"]",
        "closed": True,
        "resolvedOutcomeIndex": 0,
        "category": "Sports",
        "endDate": "2026-01-01T00:00:00Z",
    },
    {
        "id": "lost",
        "question": "Resolved NO market?",
        "outcomes": "[\"Yes\", \"No\"]",
        "outcomePrices": "[\"0.0\", \"1.0\"]",
        "closed": True,
        "category": "Sports",
        "endDate": "2026-01-02T00:00:00Z",
    },
]


class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")

    def json(self):
        return self._payload


class FetchMarkets(unittest.TestCase):
    def setUp(self):
        self._orig_get = requests.get

    def tearDown(self):
        requests.get = self._orig_get

    def test_get_is_read_only_and_normalizes(self):
        captured = {}

        def fake_get(url, params=None, timeout=None):
            captured["url"] = url
            captured["params"] = params
            captured["timeout"] = timeout
            return _FakeResponse(CANNED)

        requests.get = fake_get
        markets = md.fetch_markets(limit=3, closed=True, timeout_s=7)

        # Read-only GET against the public Gamma endpoint, params passed through.
        self.assertEqual(captured["url"], md.GAMMA_MARKETS_URL)
        self.assertEqual(captured["params"]["limit"], 3)
        self.assertEqual(captured["params"]["closed"], "true")
        self.assertEqual(captured["timeout"], 7)

        self.assertEqual(len(markets), 3)

    def test_price_maps_to_implied_prob_in_unit_interval(self):
        requests.get = lambda url, params=None, timeout=None: _FakeResponse(CANNED)
        m = md.fetch_markets()[0]
        self.assertEqual(m["market_id"], "abc123")
        self.assertEqual(m["question"], "Will X happen?")
        self.assertAlmostEqual(m["implied_prob"], 0.62)
        self.assertTrue(0.0 <= m["implied_prob"] <= 1.0)
        self.assertFalse(m["resolved"])
        self.assertIsNone(m["outcome"])
        self.assertEqual(m["category"], "Politics")

    def test_resolved_yes_and_no_parsed(self):
        requests.get = lambda url, params=None, timeout=None: _FakeResponse(CANNED)
        markets = md.fetch_markets()
        won = next(m for m in markets if m["market_id"] == "won")
        lost = next(m for m in markets if m["market_id"] == "lost")
        self.assertTrue(won["resolved"])
        self.assertEqual(won["outcome"], 1.0)
        self.assertTrue(lost["resolved"])
        self.assertEqual(lost["outcome"], 0.0)

    def test_network_error_raises_market_data_error(self):
        def boom(url, params=None, timeout=None):
            raise requests.ConnectionError("no network")

        requests.get = boom
        with self.assertRaises(md.MarketDataError):
            md.fetch_markets()

    def test_http_error_status_raises_market_data_error(self):
        requests.get = lambda url, params=None, timeout=None: _FakeResponse(
            None, status=503
        )
        with self.assertRaises(md.MarketDataError):
            md.fetch_markets()

    def test_non_list_payload_raises_market_data_error(self):
        requests.get = lambda url, params=None, timeout=None: _FakeResponse(
            {"error": "rate limited"}
        )
        with self.assertRaises(md.MarketDataError):
            md.fetch_markets()


class LoadFixture(unittest.TestCase):
    def test_fixture_normalizes_offline(self):
        markets = md.load_fixture(str(FIXTURE))
        self.assertEqual(len(markets), 4)
        by_id = {m["market_id"]: m for m in markets}

        yes = by_id["0xresolved_yes"]
        self.assertTrue(yes["resolved"])
        self.assertEqual(yes["outcome"], 1.0)
        self.assertTrue(0.0 <= yes["implied_prob"] <= 1.0)

        no = by_id["0xresolved_no"]
        self.assertTrue(no["resolved"])
        self.assertEqual(no["outcome"], 0.0)

        # Open market: implied_prob from bid/ask midpoint, not resolved.
        mid = by_id["0xopen_midpoint"]
        self.assertFalse(mid["resolved"])
        self.assertIsNone(mid["outcome"])
        self.assertAlmostEqual(mid["implied_prob"], 0.62)

        # Sparse market: missing fields tolerated, no crash.
        sparse = by_id["0xsparse"]
        self.assertIsNone(sparse["implied_prob"])
        self.assertFalse(sparse["resolved"])
        self.assertIsNone(sparse["category"])

    def test_missing_fixture_raises_market_data_error(self):
        with self.assertRaises(md.MarketDataError):
            md.load_fixture(str(REPO_ROOT / "no" / "such" / "file.json"))


class ReadOnlyGuard(unittest.TestCase):
    """Static guard: the source has no trading/auth *call surface*.

    Scans only executable code lines (comments and docstring prose are
    excluded), so the disclaimer banner -- which legitimately says "no
    wallet, no private key" -- does not trip the guard. We assert against
    concrete call/identifier patterns that would only appear in real
    order-placing or authenticated code.
    """

    def test_code_lines_have_no_trading_or_auth_calls(self):
        import io
        import tokenize

        src_path = (
            REPO_ROOT / "experiments" / "exp007_polymarket" / "market_data.py"
        )
        src = src_path.read_text()

        # Strip comments and string literals (docstrings) via the tokenizer,
        # leaving only real code tokens to inspect.
        code_tokens = []
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            code_tokens.append(tok.string)
        code = " ".join(code_tokens).lower()

        for forbidden in (
            "requests.post",
            "requests.put",
            "requests.delete",
            "requests.patch",
            "private_key",
            "privatekey",
            "wallet",
            "sign_transaction",
            "signtransaction",
            "place_order",
            "place_trade",
            "submit_order",
            "authorization",
            "api_key",
            "apikey",
            "bearer",
            "secret",
        ):
            self.assertNotIn(
                forbidden,
                code,
                f"forbidden trading/auth token present in code: {forbidden}",
            )

        # The only HTTP verb used is GET.
        self.assertIn("requests.get", src)


if __name__ == "__main__":
    unittest.main()
