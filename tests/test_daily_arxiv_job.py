"""CPU-only producer tests for daily ingestion receipts and failed fetches."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pipeline import daily_arxiv_job as job

FIXED = datetime(2026, 9, 15, 3, 0, tzinfo=timezone.utc)
PAPERS = b'{"arxiv_id":"2609.12345","title":"Known mechanism"}\n'


def _run(root: Path, *, fetch: job.CommandResult, embed: job.CommandResult | None = None,
         paper_bytes: bytes = PAPERS):
    calls: list[list[str]] = []

    def execute(argv: list[str], _timeout: int) -> job.CommandResult:
        calls.append(argv)
        if len(calls) == 1:
            if fetch.exit_code == 0:
                Path(argv[argv.index("--output") + 1]).write_bytes(paper_bytes)
            return fetch
        assert embed is not None
        return embed

    receipt = job.run_job(state_root=root, executor=execute, now=lambda: FIXED,
                          python="/registered/python")
    return receipt, calls


def test_failed_429_attempt_is_durable_and_prior_cache_is_not_used_as_fresh(tmp_path):
    root = tmp_path / "ingestion"
    first, first_calls = _run(root, fetch=job.CommandResult(0, ""),
                              embed=job.CommandResult(0, ""))
    assert first["status"] == "succeeded" and len(first_calls) == 2
    pointer_before = (root / "last-success.json").read_bytes()
    failed, calls = _run(root, fetch=job.CommandResult(
        1, "HTTP 429 before retry 1\nHTTP 503 before retry 6\nHTTP 429"))
    assert failed["status"] == "fetch_failed"
    assert failed["failure_code"] == "arxiv_http_429_retry_exhausted"
    assert failed["fetch"] == {"retry_count_observed": 6,
                               "http_codes_observed": ["429", "503"]}
    assert failed["input_sha256"] is None and failed["embed_attempted"] is False
    assert len(calls) == 1
    assert (root / "last-success.json").read_bytes() == pointer_before
    assert json.loads((root / "runs" / failed["run_id"] / "terminal.json").read_bytes()) == failed
    assert job._last_success(root)["run_id"] == first["run_id"]


def test_fetch_success_with_embed_timeout_retains_input_but_not_last_success(tmp_path):
    root = tmp_path / "ingestion"
    failed, calls = _run(root, fetch=job.CommandResult(0, ""),
                         embed=job.CommandResult(None, "", timed_out=True))
    assert len(calls) == 2
    assert failed["status"] == "embed_failed"
    assert failed["failure_code"] == "embed_timeout"
    assert failed["input_sha256"] == job._sha(PAPERS)
    assert failed["embed_attempted"] is True
    assert not (root / "last-success.json").exists()
    assert (root / "cache" / f"{job._sha(PAPERS)}.jsonl").read_bytes() == PAPERS


def test_broken_last_success_terminal_is_unknown_and_blocks_new_work(tmp_path):
    root = tmp_path / "ingestion"
    first, _ = _run(root, fetch=job.CommandResult(0, ""),
                    embed=job.CommandResult(0, ""))
    (root / "runs" / first["run_id"] / "terminal.json").unlink()
    with pytest.raises((job.IngestionError, OSError)):
        _run(root, fetch=job.CommandResult(1, "HTTP 429"))


def test_invalid_or_duplicate_fetched_rows_are_not_a_success(tmp_path):
    root = tmp_path / "ingestion"
    bad = PAPERS + PAPERS
    receipt, calls = _run(root, fetch=job.CommandResult(0, ""), paper_bytes=bad)
    assert receipt["status"] == "fetch_failed" and len(calls) == 1
    assert receipt["failure_code"] == "IngestionError"
    assert receipt["paper_count"] is None
    assert not (root / "last-success.json").exists()
