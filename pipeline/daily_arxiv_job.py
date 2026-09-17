"""Receipt-bound daily arXiv fetch and embed job.

The last successful input is a cache for provenance and recovery diagnosis,
never a replacement for a failed current fetch. A run writes a started receipt
before network/model work and a terminal receipt after each stage. A missing
terminal receipt means interrupted/unknown, not success.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_ROOT = REPO_ROOT / "run_state" / "arxiv_ingestion"
SCRAPER = REPO_ROOT / "pipeline" / "arxiv_scraper.py"
EMBEDDER = REPO_ROOT / "pipeline" / "embed_and_store.py"
WEIGHTS = Path("/mnt/models/bge-m3")
DB_PATH = REPO_ROOT / "chroma_db"
CATEGORIES = ("cs.MA", "cs.GT", "econ.TH")
SINCE_DAYS = 3
JITTER_SECONDS = 300
FETCH_TIMEOUT_S = 1500
EMBED_TIMEOUT_S = 900
MAX_INPUT_BYTES = 16_000_000
MAX_PROVENANCE_BYTES = 4096
MAX_TERMINAL_BYTES = 8192
MAX_PAPERS = 5000
MAX_LOG_BYTES = 128_000
MAX_RUNS_SCAN = 400
SCHEMA = "arxiv-daily-ingestion-attempt/v1"
LAST_SUCCESS_SCHEMA = "arxiv-daily-last-success/v1"
FETCH_PROVENANCE_SCHEMA = "arxiv-fetch-provenance/v1"
FETCH_ENDPOINTS = {
    "arxiv_oai_pmh": "https://oaipmh.arxiv.org/oai",
    "arxiv_search_api": "https://export.arxiv.org/api/query",
}
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
RUN_RE = re.compile(r"^daily-arxiv-[0-9]{8}T[0-9]{6}Z-[0-9]+-[0-9a-f]{8}$")


class IngestionError(RuntimeError):
    pass


@dataclass(frozen=True)
class CommandResult:
    exit_code: int | None
    stderr: str
    timed_out: bool = False


def _canon(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_regular(path: Path, limit: int) -> bytes:
    parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0), dir_fd=parent_fd)
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
                raise IngestionError("ingestion receipt/cache is redirected or oversized")
            raw = os.read(fd, limit + 1)
            after = os.fstat(fd)
            if len(raw) != before.st_size or len(raw) > limit or (
                before.st_ino, before.st_size, before.st_mtime_ns
            ) != (
                after.st_ino, after.st_size, after.st_mtime_ns
            ):
                raise IngestionError("ingestion receipt/cache changed during read")
            return raw
        finally:
            os.close(fd)
    finally:
        os.close(parent_fd)


def _write_new(path: Path, raw: bytes) -> None:
    fd = os.open(
        path,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        with os.fdopen(fd, "wb", closefd=False) as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
    finally:
        os.close(fd)


def _replace_pointer(root: Path, value: dict, run_id: str) -> None:
    temp = root / f"last-success.{run_id}.tmp"
    _write_new(temp, _canon(value))
    os.replace(temp, root / "last-success.json")
    dirfd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(dirfd)
    finally:
        os.close(dirfd)


def _execute(argv: list[str], timeout_s: int) -> CommandResult:
    env = os.environ.copy()
    env.pop("MOCK_LLM", None)
    try:
        result = subprocess.run(
            argv,
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(None, str(exc.stderr or "")[:MAX_LOG_BYTES], True)
    if len(result.stderr.encode()) > MAX_LOG_BYTES or len(result.stdout.encode()) > MAX_LOG_BYTES:
        raise IngestionError("ingestion stage log exceeded its bound")
    return CommandResult(result.returncode, result.stderr)


def _failure_code(result: CommandResult, stage: str) -> str:
    if result.timed_out:
        return f"{stage}_timeout"
    if stage == "fetch":
        codes = re.findall(r"HTTP ([45][0-9]{2})\b", result.stderr)
        if codes:
            code = codes[-1]
            suffix = "retry_exhausted" if code == "429" or code.startswith("5") else "error"
            return f"arxiv_http_{code}_{suffix}"
        if "network error" in result.stderr and "request failed after" in result.stderr:
            return "arxiv_network_retry_exhausted"
    return f"{stage}_error"


def _retry_observations(stderr: str) -> dict:
    retries = [int(item) for item in re.findall(r"before retry ([0-9]+)\b", stderr)]
    codes = sorted(set(re.findall(r"HTTP ([45][0-9]{2})\b", stderr)))
    attempted = []
    for source in re.findall(r"source=(arxiv_oai_pmh|arxiv_search_api)\b", stderr):
        if source not in attempted:
            attempted.append(source)
    return {
        "retry_count_observed": max(retries, default=0),
        "http_codes_observed": codes,
        "network_error_count": stderr.count("network error"),
        "sources_attempted": attempted,
    }


def _input_receipt(raw: bytes) -> dict:
    if len(raw) > MAX_INPUT_BYTES:
        raise IngestionError("fetched paper input exceeded its byte cap")
    lines = raw.splitlines()
    if len(lines) > MAX_PAPERS:
        raise IngestionError("fetched paper input exceeded its paper cap")
    ids: set[str] = set()
    for line in lines:
        if not line or len(line) > 64_000:
            raise IngestionError("fetched paper JSONL has an empty/oversized row")
        try:
            item = json.loads(line)
        except (ValueError, UnicodeDecodeError) as exc:
            raise IngestionError("fetched paper JSONL is malformed") from exc
        paper_id = item.get("arxiv_id") if isinstance(item, dict) else None
        if not isinstance(paper_id, str) or not paper_id or paper_id in ids:
            raise IngestionError("fetched paper IDs are missing/duplicated")
        ids.add(paper_id)
    return {"input_sha256": _sha(raw), "input_bytes": len(raw), "paper_count": len(lines)}


def _fetch_provenance(raw: bytes, input_info: dict, started_at: datetime) -> dict:
    """Validate the scraper sidecar before fetched rows may reach embedding."""
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise IngestionError("fetch provenance is malformed") from exc
    source = value.get("source") if isinstance(value, dict) else None
    expected_cutoff = (started_at.astimezone(timezone.utc).date()
                       - timedelta(days=SINCE_DAYS)).isoformat()
    fallback_from = value.get("fallback_from") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or value.get("schema") != FETCH_PROVENANCE_SCHEMA
        or source not in FETCH_ENDPOINTS
        or value.get("endpoint") != FETCH_ENDPOINTS.get(source)
        or value.get("categories") != list(CATEGORIES)
        or value.get("since_days") != SINCE_DAYS
        or value.get("cutoff_date") != expected_cutoff
        or value.get("paper_count") != input_info["paper_count"]
        or value.get("complete") is not True
        or (source == "arxiv_oai_pmh" and fallback_from is not None)
        or (source == "arxiv_search_api" and fallback_from != "arxiv_oai_pmh")
    ):
        raise IngestionError("fetch provenance does not match this complete run")
    return value


def _last_success(root: Path) -> dict | None:
    path = root / "last-success.json"
    if not os.path.lexists(path):
        return None
    raw = _read_regular(path, 4096)
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise IngestionError("last-success pointer is malformed") from exc
    if (
        not isinstance(value, dict)
        or value.get("schema") != LAST_SUCCESS_SCHEMA
        or not isinstance(value.get("run_id"), str)
        or not RUN_RE.fullmatch(value["run_id"])
        or not SHA_RE.fullmatch(str(value.get("input_sha256")))
        or not SHA_RE.fullmatch(str(value.get("terminal_sha256")))
        or value.get("fetch_source") not in FETCH_ENDPOINTS
        or value.get("cache_relpath") != f"cache/{value['input_sha256']}.jsonl"
    ):
        raise IngestionError("last-success pointer identity is malformed")
    cache = _read_regular(root / value["cache_relpath"], MAX_INPUT_BYTES)
    if _sha(cache) != value["input_sha256"]:
        raise IngestionError("last-success cache SHA drifted")
    info = _input_receipt(cache)
    if info["paper_count"] != value.get("paper_count"):
        raise IngestionError("last-success cache paper count drifted")
    terminal = root / "runs" / value["run_id"] / "terminal.json"
    terminal_raw = _read_regular(terminal, MAX_TERMINAL_BYTES)
    if _sha(terminal_raw) != value["terminal_sha256"]:
        raise IngestionError("last-success terminal SHA drifted")
    receipt = json.loads(terminal_raw)
    if (receipt.get("schema") != SCHEMA or receipt.get("run_id") != value["run_id"]
            or receipt.get("status") != "succeeded"
            or receipt.get("input_sha256") != value["input_sha256"]
            or receipt.get("finished_at") != value.get("finished_at")
            or not isinstance(receipt.get("fetch_provenance"), dict)
            or receipt["fetch_provenance"].get("source") != value["fetch_source"]):
        raise IngestionError("last-success pointer differs from terminal receipt")
    provenance_raw = _read_regular(
        terminal.parent / "fetch-provenance.json", MAX_PROVENANCE_BYTES
    )
    try:
        provenance = json.loads(provenance_raw)
    except ValueError as exc:
        raise IngestionError("last-success fetch provenance is malformed") from exc
    if (_sha(provenance_raw) != receipt.get("fetch_provenance_sha256")
            or provenance != receipt["fetch_provenance"]):
        raise IngestionError("last-success fetch provenance drifted")
    return value


def run_job(
    *,
    state_root: Path = STATE_ROOT,
    executor: Callable[[list[str], int], CommandResult] = _execute,
    now: Callable[[], datetime] = _utc_now,
    python: str = sys.executable,
) -> dict:
    """Run fixed fetch→embed stages, preserving all failed attempts."""
    for path in (state_root, state_root / "runs", state_root / "cache"):
        if os.path.lexists(path):
            if path.is_symlink() or not path.is_dir():
                raise IngestionError("ingestion state directory is redirected")
        else:
            path.mkdir(mode=0o700)
    prior = _last_success(state_root)
    started_at = now()
    run_id = f"daily-arxiv-{started_at:%Y%m%dT%H%M%SZ}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    child = state_root / "runs" / run_id
    child.mkdir(mode=0o700)
    sources = {
        "job_sha256": _sha(Path(__file__).read_bytes()),
        "scraper_sha256": _sha(_read_regular(SCRAPER, 512_000)),
        "embedder_sha256": _sha(_read_regular(EMBEDDER, 512_000)),
    }
    started = {
        "schema": SCHEMA,
        "run_id": run_id,
        "started_at": _stamp(started_at),
        "categories": list(CATEGORIES),
        "since_days": SINCE_DAYS,
        "jitter_seconds_max": JITTER_SECONDS,
        "fetch_source_plan": ["arxiv_oai_pmh", "arxiv_search_api"],
        "mock_llm_unset": True,
        "sources": sources,
        "last_success_before_sha256": _sha(_canon(prior)) if prior else None,
    }
    started_raw = _canon(started)
    _write_new(child / "started.json", started_raw)
    input_path = child / "papers.jsonl"
    provenance_path = child / "fetch-provenance.json"
    fetch_argv = [
        python, str(SCRAPER), "--categories", ",".join(CATEGORIES),
        "--since-days", str(SINCE_DAYS), "--jitter-seconds", str(JITTER_SECONDS),
        "--output", str(input_path), "--provenance-output", str(provenance_path),
    ]
    status = "fetch_failed"
    failure_code: str | None = None
    input_info = {"input_sha256": None, "input_bytes": None, "paper_count": None}
    fetch_detail = {
        "retry_count_observed": 0,
        "http_codes_observed": [],
        "network_error_count": 0,
        "sources_attempted": [],
    }
    fetch_provenance = None
    fetch_provenance_sha256 = None
    embed_attempted = False
    try:
        fetch = executor(fetch_argv, FETCH_TIMEOUT_S)
        fetch_detail = _retry_observations(fetch.stderr)
        if fetch.exit_code != 0:
            failure_code = _failure_code(fetch, "fetch")
        else:
            raw = _read_regular(input_path, MAX_INPUT_BYTES)
            candidate_info = _input_receipt(raw)
            provenance_raw = _read_regular(provenance_path, MAX_PROVENANCE_BYTES)
            fetch_provenance = _fetch_provenance(
                provenance_raw, candidate_info, started_at
            )
            fetch_provenance_sha256 = _sha(provenance_raw)
            input_info = candidate_info
            cache = state_root / "cache" / f"{input_info['input_sha256']}.jsonl"
            if os.path.lexists(cache):
                if _sha(_read_regular(cache, MAX_INPUT_BYTES)) != input_info["input_sha256"]:
                    raise IngestionError("existing paper cache differs from fetched SHA")
            else:
                _write_new(cache, raw)
            embed_argv = [
                python, str(EMBEDDER), "--input", str(input_path),
                "--collection", "papers_recent", "--bge-m3-weights", str(WEIGHTS),
                "--db-path", str(DB_PATH),
            ]
            embed_attempted = True
            embed = executor(embed_argv, EMBED_TIMEOUT_S)
            if embed.exit_code == 0:
                status = "succeeded"
            else:
                status = "embed_failed"
                failure_code = _failure_code(embed, "embed")
    except (IngestionError, OSError, ValueError) as exc:
        failure_code = type(exc).__name__
        if input_info["input_sha256"] is not None:
            status = "embed_failed"
    terminal = {
        "schema": SCHEMA,
        "run_id": run_id,
        "started_sha256": _sha(started_raw),
        "finished_at": _stamp(now()),
        "status": status,
        "failure_code": failure_code,
        "fetch": fetch_detail,
        "fetch_provenance": fetch_provenance,
        "fetch_provenance_sha256": fetch_provenance_sha256,
        **input_info,
        "cache_reused_as_fresh": False,
        "embed_attempted": embed_attempted,
        "last_success_before_sha256": started["last_success_before_sha256"],
    }
    terminal_raw = _canon(terminal)
    _write_new(child / "terminal.json", terminal_raw)
    if status == "succeeded":
        pointer = {
            "schema": LAST_SUCCESS_SCHEMA,
            "run_id": run_id,
            "finished_at": terminal["finished_at"],
            "input_sha256": input_info["input_sha256"],
            "paper_count": input_info["paper_count"],
            "fetch_source": fetch_provenance["source"],
            "cache_relpath": f"cache/{input_info['input_sha256']}.jsonl",
            "terminal_sha256": _sha(terminal_raw),
        }
        _replace_pointer(state_root, pointer, run_id)
    return terminal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--plan", action="store_true")
    group.add_argument("--run", action="store_true")
    args = parser.parse_args(argv)
    if args.plan:
        print(json.dumps({
            "schema": SCHEMA, "categories": CATEGORIES, "since_days": SINCE_DAYS,
            "jitter_seconds_max": JITTER_SECONDS, "fetch_timeout_s": FETCH_TIMEOUT_S,
            "embed_timeout_s": EMBED_TIMEOUT_S, "cache_reused_as_fresh": False,
            "fetch_source_plan": ("arxiv_oai_pmh", "arxiv_search_api"),
            "network_calls": 0, "model_calls": 0,
        }, sort_keys=True))
        return 0
    receipt = run_job()
    print(json.dumps({
        "run_id": receipt["run_id"], "status": receipt["status"],
        "failure_code": receipt["failure_code"], "paper_count": receipt["paper_count"],
    }, sort_keys=True))
    return 0 if receipt["status"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
