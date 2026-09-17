"""CPU-only producer tests for daily ingestion receipts and failed fetches."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pipeline import daily_arxiv_job as job

FIXED = datetime(2026, 9, 15, 3, 0, tzinfo=timezone.utc)
PAPERS = b'{"arxiv_id":"2609.12345","title":"Known mechanism"}\n'


def _provenance(paper_count: int = 1) -> dict:
    return {
        "schema": job.FETCH_PROVENANCE_SCHEMA,
        "source": "arxiv_oai_pmh",
        "endpoint": job.FETCH_ENDPOINTS["arxiv_oai_pmh"],
        "fallback_from": None,
        "categories": list(job.CATEGORIES),
        "since_days": job.SINCE_DAYS,
        "cutoff_date": "2026-09-12",
        "paper_count": paper_count,
        "complete": True,
    }


def _run(root: Path, *, fetch: job.CommandResult, embed: job.CommandResult | None = None,
         paper_bytes: bytes = PAPERS, provenance: dict | None = None,
         write_provenance: bool = True):
    calls: list[list[str]] = []

    def execute(argv: list[str], _timeout: int) -> job.CommandResult:
        calls.append(argv)
        if len(calls) == 1:
            if fetch.exit_code == 0:
                Path(argv[argv.index("--output") + 1]).write_bytes(paper_bytes)
                if write_provenance:
                    value = provenance if provenance is not None else _provenance(
                        len(paper_bytes.splitlines())
                    )
                    Path(argv[argv.index("--provenance-output") + 1]).write_bytes(
                        job._canon(value)
                    )
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
    assert first["fetch_provenance"]["source"] == "arxiv_oai_pmh"
    assert first["fetch_provenance_sha256"]
    first_terminal = root / "runs" / first["run_id"] / "terminal.json"
    assert first_terminal.stat().st_size < job.MAX_TERMINAL_BYTES
    pointer_before = (root / "last-success.json").read_bytes()
    failed, calls = _run(root, fetch=job.CommandResult(
        1, "HTTP 429 before retry 1\nHTTP 503 before retry 6\nHTTP 429"))
    assert failed["status"] == "fetch_failed"
    assert failed["failure_code"] == "arxiv_http_429_retry_exhausted"
    assert failed["fetch"] == {
        "retry_count_observed": 6,
        "http_codes_observed": ["429", "503"],
        "network_error_count": 0,
        "sources_attempted": [],
    }
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


def test_missing_or_mismatched_fetch_provenance_blocks_embedding(tmp_path):
    missing_root = tmp_path / "missing"
    missing, missing_calls = _run(
        missing_root, fetch=job.CommandResult(0, ""), write_provenance=False
    )
    assert missing["status"] == "fetch_failed" and len(missing_calls) == 1
    assert missing["input_sha256"] is None
    assert missing["fetch_provenance"] is None

    mismatch_root = tmp_path / "mismatch"
    bad_provenance = _provenance()
    bad_provenance["complete"] = False
    mismatch, mismatch_calls = _run(
        mismatch_root, fetch=job.CommandResult(0, ""), provenance=bad_provenance
    )
    assert mismatch["status"] == "fetch_failed" and len(mismatch_calls) == 1
    assert mismatch["failure_code"] == "IngestionError"
    assert mismatch["input_sha256"] is None


def test_search_fallback_provenance_is_accepted_and_bound_to_pointer(tmp_path):
    provenance = _provenance()
    provenance.update({
        "source": "arxiv_search_api",
        "endpoint": job.FETCH_ENDPOINTS["arxiv_search_api"],
        "fallback_from": "arxiv_oai_pmh",
    })
    receipt, _ = _run(
        tmp_path / "ingestion", fetch=job.CommandResult(0, ""),
        embed=job.CommandResult(0, ""), provenance=provenance,
    )
    pointer = json.loads(
        (tmp_path / "ingestion" / "last-success.json").read_text()
    )
    assert receipt["status"] == "succeeded"
    assert receipt["fetch_provenance"]["source"] == "arxiv_search_api"
    assert pointer["fetch_source"] == "arxiv_search_api"
