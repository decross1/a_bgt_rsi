#!/usr/bin/env python3
"""
Day-4 end-of-day pre-stage: confirm the Semantic Scholar API key works.

Queries a known arxiv id and asserts the response carries a paper with the
expected title fragment. Exits non-zero on any failure (missing key,
network, rate-limit, unexpected payload).

    .venv/bin/python scripts/test_semantic_scholar.py
"""
import os
import sys
import urllib.request
import urllib.error
import json
from pathlib import Path


def _load_dotenv(path):
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


REPO = Path(__file__).resolve().parent.parent
_load_dotenv(REPO / ".env")

KEY = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip()
# "Attention Is All You Need" — a stable, well-indexed arXiv paper.
ARXIV_ID = "1706.03762"
EXPECTED_TITLE_FRAGMENT = "attention"

URL = ("https://api.semanticscholar.org/graph/v1/paper/"
       f"ARXIV:{ARXIV_ID}?fields=title,year,authors,abstract")


def main():
    if not KEY:
        print("FAIL: SEMANTIC_SCHOLAR_API_KEY not set (.env or env var)",
              file=sys.stderr)
        sys.exit(1)
    req = urllib.request.Request(URL, headers={"x-api-key": KEY})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        print(f"FAIL: HTTP {exc.code} {exc.reason}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)

    title = payload.get("title", "")
    if EXPECTED_TITLE_FRAGMENT not in title.lower():
        print(f"FAIL: title fragment {EXPECTED_TITLE_FRAGMENT!r} not in "
              f"returned title {title!r}", file=sys.stderr)
        sys.exit(1)
    print(f"PASS: arxiv:{ARXIV_ID} -> {title} ({payload.get('year')})")


if __name__ == "__main__":
    main()
