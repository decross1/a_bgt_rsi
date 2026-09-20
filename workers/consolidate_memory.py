"""Worker: consolidate_memory — one-shot idempotent migration CLI (LOOP_V1 P1,
agent A7). Folds the historical corpus (memory/loop_memory.jsonl +
memory/surfaced_findings.jsonl) into idea-ledger events: clusters near-dup
claims, derives each cluster's evidence rung, kills redteam-fatal clusters
programmatically, seeds paper niches for rediscoveries, and archives near-dup
non-elite members. **Dry-run is the DEFAULT** — nothing is written until
`--execute` — because the dry-run summary is a blocking human gate (G2).

Discipline:
  * Source files (loop_memory / surfaced_findings) are NEVER rewritten or
    deleted from — the migration is append-only into the idea ledger +
    memory/idea_archive.jsonl.
  * Clustering reuses the P4 dedup layers from workers.mine_paper_gap: the
    lexical-Jaccard layer is LOAD-BEARING (the falsifier proved cosine alone
    cannot collapse reworded near-dups); cosine >= TAU_DUP catches
    near-identical restatements only.
  * Rung derivation is delegated to workers.evidence_ladder.derive_level
    (pure Python, never coerced); leaked-JSON-blob claims are repaired via
    workers.claim_extract.extract_claim; events are appended via
    workers.idea_ledger.append_event. All three resolve lazily and are
    injectable for hermetic tests (`*_fn` kwargs).
  * Idempotent: member ids already present in the ledger's
    cluster_created/member_added events are skipped, so a second `--execute`
    appends ZERO events (test-pinned).
  * A malformed source row is never projected as evidence and never stalls a
    later valid row. It gets one content-free, source-hash-bound record in the
    separate consolidation quarantine; retries deduplicate by failure id.
  * D-075 R4 (owner-ratified): fresh items are matched against EXISTING
    open (not-killed) ledger clusters — same prefilter layers, same
    thresholds as intra-batch — BEFORE any new cluster is minted; a refill
    near-dup member_adds to the original instead of founding a duplicate
    (the 08-18 case: 3 duplicate clusters minted next to their open
    originals). Killed clusters are never matched — re-entry into a killed
    niche stays accept_candidate's evidence-keyed job.
  * Missing input files RAISE (rule 7 — a missing corpus is not a silent
    empty migration); an out-of-enum rung from derive_level RAISES (rule 4).
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import stat
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

from orchestrator import runtime
from workers.idea_ledger import (
    kill_reason_from_redteam,
    reduce_events,
    reopening_condition,
)
from workers.mine_paper_gap import (
    JACCARD_DUP,
    TAU_DUP,
    _append_jsonl,
    _cosine,
    _embed_texts,
    _lexical_overlap,
    _read_jsonl,
    _utcnow,
)
from workers.retrieval_relevance import _tokenize

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOOP_MEMORY = REPO_ROOT / "memory" / "loop_memory.jsonl"
DEFAULT_SURFACED = REPO_ROOT / "memory" / "surfaced_findings.jsonl"
DEFAULT_FEEDBACK = REPO_ROOT / "memory" / "loop_feedback.jsonl"
DEFAULT_LEDGER = REPO_ROOT / "memory" / "idea_ledger.jsonl"
DEFAULT_ARCHIVE = REPO_ROOT / "memory" / "idea_archive.jsonl"
DEFAULT_QUARANTINE = REPO_ROOT / "memory" / "consolidation_quarantine.jsonl"

LEVELS = ("L0", "L1", "L2", "L3", "L4", "L5")
_MEMBER_EVENTS = ("cluster_created", "member_added")
_NEAR_DUP_LAYERS = ("lexical_jaccard", "cosine_tau_dup")
_EXCERPT = 240
_QUARANTINE_SCHEMA = "consolidation-quarantine/v1"
_QUARANTINE_DISPOSITION = "quarantined_not_projected"
_QUARANTINE_SCIENTIFIC_EFFECT = "none"
_FAILURE_MESSAGE_LIMIT = 240
_SOURCE_FILE_MAX_BYTES = 64 * 1024 * 1024
_SOURCE_LINE_MAX_BYTES = 4 * 1024 * 1024
_FAILURE_REASON_CODES = frozenset({
    "invalid_source_encoding",
    "invalid_source_json",
    "non_object_source_json",
    "source_line_too_large",
    "missing_iteration_id",
    "unrecoverable_hypothesis_blob",
    "empty_research_surface",
    "missing_finding_id",
    "unresolvable_claim_source",
    "unrecoverable_finding_blob",
    "empty_finding_surface",
})


class ConsolidationBusyError(RuntimeError):
    """Another execute pass owns the target ledger's consolidation lock."""


class _StrictJSONError(ValueError):
    """A source row violates the strict JSON contract."""


@dataclass(frozen=True)
class _SourceRecord:
    row: dict[str, Any]
    record_ordinal: int
    source_row_sha256: str


@dataclass(frozen=True)
class _SourceRead:
    records: list[_SourceRecord]
    failures: list[dict[str, Any]]
    nonblank_rows: int


# ── Lazy seams for parallel-built contract modules (injectable in tests). ────
def _default_derive_level(repo_root: Path = REPO_ROOT) -> Callable:
    from orchestrator.experiment_admission import derive_verified_level
    return partial(derive_verified_level, repo_root=repo_root)


def _default_extract_claim() -> Callable:
    from workers.claim_extract import extract_claim
    # A historical read-model rebuild must not generate new scientific prose
    # or issue model requests just to recover an old structured envelope.
    return partial(extract_claim, refine=False)


def _default_append_event() -> Callable:
    from workers.idea_ledger import append_event
    return append_event


def _is_leaked_blob(text: str) -> bool:
    """True when a claim/hypothesis surface is a leaked JSON blob (the model
    emitted its raw structured scratchpad instead of prose). Full parses count;
    so does a truncated blob that opens like a JSON object."""
    t = (text or "").strip()
    if not t.startswith(("{", "[")):
        return False
    try:
        parsed = json.loads(t)
        return isinstance(parsed, (dict, list))
    except json.JSONDecodeError:
        return bool(re.match(r'^[{\[]\s*"', t))


def _repaired_surface(claim: dict[str, Any], iteration_id: str) -> str:
    parts = [claim.get(k) for k in ("problem", "mechanism", "predicted_effect")]
    parts = [p.strip() for p in parts if isinstance(p, str) and p.strip()]
    if not parts:
        raise ValueError(
            f"consolidate_memory: claim_extract returned an empty claim for "
            f"{iteration_id} — cannot repair a leaked blob with nothing (rule 4)."
        )
    return " — ".join(parts)


def _is_quarantinable_claim_error(error: ValueError) -> bool:
    """Only documented source-shape failures may become quarantine receipts."""
    message = str(error)
    return message.startswith(
        (
            "claim_extract: leaked-JSON-blob claim is unrecoverable",
            "consolidate_memory: claim_extract returned an empty claim",
        )
    )


def _canonical_row_sha256(row: dict[str, Any]) -> str:
    """Canonical object digest retained for non-source callers.

    Source provenance must use :func:`_source_line_sha256` instead: parsing and
    re-serializing erases duplicate keys, spacing, and other bytes that identify
    the physical JSONL record.
    """
    payload = json.dumps(
        row,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _source_line_sha256(raw_line: bytes) -> str:
    """Digest exact physical-line content bytes (the LF delimiter is excluded)."""
    return hashlib.sha256(raw_line).hexdigest()


def _strict_object(text: str) -> dict[str, Any]:
    """Decode one JSON object, rejecting duplicate keys and non-finite values."""
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        obj: dict[str, Any] = {}
        for key, value in pairs:
            if key in obj:
                raise _StrictJSONError("duplicate JSON object key")
            obj[key] = value
        return obj

    def reject_constant(_value: str) -> Any:
        raise _StrictJSONError("non-finite JSON number")

    value = json.loads(
        text,
        object_pairs_hook=object_pairs,
        parse_constant=reject_constant,
    )
    if not isinstance(value, dict):
        raise TypeError("source JSON value is not an object")
    return value


def _physical_lines(payload: bytes) -> Iterator[tuple[int, bytes]]:
    """Yield 1-based physical LF-delimited lines without inventing an EOF row.

    The delimiter itself is excluded from the yielded content. Every real blank
    line still advances the ordinal, including blank lines before valid rows.
    CR bytes in CRLF files remain part of the exact line content and digest.
    """
    if not payload:
        return
    start = 0
    ordinal = 1
    while start < len(payload):
        end = payload.find(b"\n", start)
        if end < 0:
            yield ordinal, payload[start:]
            return
        yield ordinal, payload[start:end]
        start = end + 1
        ordinal += 1


def _read_source_jsonl(
    path: Path,
    *,
    source_kind: str,
    observed_at: str,
) -> _SourceRead:
    """Bounded strict source read with byte-exact, physical-line provenance.

    Malformed content becomes a content-free quarantine receipt and scanning
    continues. File-system failures and whole-file bound violations stay loud;
    they are infrastructure failures, not scientific source rows.
    """
    with path.open("rb") as stream:
        payload = stream.read(_SOURCE_FILE_MAX_BYTES + 1)
    if len(payload) > _SOURCE_FILE_MAX_BYTES:
        raise ValueError(
            f"consolidate_memory: {source_kind} exceeds the bounded source read"
        )

    records: list[_SourceRecord] = []
    failures: list[dict[str, Any]] = []
    nonblank_rows = 0
    for ordinal, raw_line in _physical_lines(payload):
        if not raw_line.strip():
            continue
        nonblank_rows += 1
        row_sha256 = _source_line_sha256(raw_line)
        if len(raw_line) > _SOURCE_LINE_MAX_BYTES:
            failures.append(_quarantine_record(
                source_kind=source_kind,
                source_path=path,
                record_ordinal=ordinal,
                source_row_sha256=row_sha256,
                source_id=None,
                reason_code="source_line_too_large",
                message="source row exceeds the per-record byte bound",
                error=None,
                observed_at=observed_at,
            ))
            continue
        try:
            text = raw_line.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            failures.append(_quarantine_record(
                source_kind=source_kind,
                source_path=path,
                record_ordinal=ordinal,
                source_row_sha256=row_sha256,
                source_id=None,
                reason_code="invalid_source_encoding",
                message="source row is not valid UTF-8",
                error=exc,
                observed_at=observed_at,
            ))
            continue
        try:
            row = _strict_object(text)
        except TypeError as exc:
            failures.append(_quarantine_record(
                source_kind=source_kind,
                source_path=path,
                record_ordinal=ordinal,
                source_row_sha256=row_sha256,
                source_id=None,
                reason_code="non_object_source_json",
                message="source row is not a JSON object",
                error=exc,
                observed_at=observed_at,
            ))
            continue
        except (json.JSONDecodeError, _StrictJSONError) as exc:
            failures.append(_quarantine_record(
                source_kind=source_kind,
                source_path=path,
                record_ordinal=ordinal,
                source_row_sha256=row_sha256,
                source_id=None,
                reason_code="invalid_source_json",
                message="source row is not valid strict JSON",
                error=exc,
                observed_at=observed_at,
            ))
            continue
        records.append(_SourceRecord(
            row=row,
            record_ordinal=ordinal,
            source_row_sha256=row_sha256,
        ))
    return _SourceRead(
        records=records,
        failures=failures,
        nonblank_rows=nonblank_rows,
    )


def _source_path(path: Path) -> str:
    """Use a stable repo-relative path when possible, else the exact path."""
    resolved = path.resolve()
    try:
        value = resolved.relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        value = str(resolved)
    if len(value) > 1024:
        raise ValueError("consolidate_memory: source path exceeds quarantine bound")
    return value


def _quarantine_record(
    *,
    source_kind: str,
    source_path: Path,
    record_ordinal: int,
    source_row_sha256: str,
    source_id: str | None,
    reason_code: str,
    message: str,
    error: Exception | None,
    observed_at: str,
) -> dict[str, Any]:
    """Build a bounded, content-free failure receipt for one source row.

    The source-row digest binds the exact private record. Research prose is not
    copied into the receipt, and the receipt never enters the scientific idea
    ledger. ``failure_id`` includes the stable record ordinal so two identical
    malformed rows remain separately accountable while retries remain
    idempotent.
    """
    stable_source_path = _source_path(source_path)
    identity = json.dumps(
        {
            "schema_version": _QUARANTINE_SCHEMA,
            "source_kind": source_kind,
            "source_path": stable_source_path,
            "record_ordinal": record_ordinal,
            "source_row_sha256": source_row_sha256,
            "reason_code": reason_code,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    failure_id = f"cq-{hashlib.sha256(identity).hexdigest()}"
    bounded_message = " ".join(message.split())[:_FAILURE_MESSAGE_LIMIT]
    record = {
        "schema_version": _QUARANTINE_SCHEMA,
        "failure_id": failure_id,
        "observed_at": observed_at,
        "source": {
            "kind": source_kind,
            "path": stable_source_path,
            "record_ordinal": record_ordinal,
            "source_id": source_id,
            "source_row_sha256": source_row_sha256,
        },
        "reason": {
            "code": reason_code,
            "error_type": type(error).__name__ if error is not None else None,
            "message": bounded_message,
        },
        "disposition": _QUARANTINE_DISPOSITION,
        "scientific_effect": _QUARANTINE_SCIENTIFIC_EFFECT,
    }
    _validate_quarantine_record(record)
    return record


def _validate_quarantine_record(row: dict[str, Any]) -> None:
    """Validate the accountability receipt independently of its producer."""
    if set(row) != {
        "schema_version",
        "failure_id",
        "observed_at",
        "source",
        "reason",
        "disposition",
        "scientific_effect",
    }:
        raise ValueError("consolidate_memory: quarantine receipt fields differ")
    if (
        row.get("schema_version") != _QUARANTINE_SCHEMA
        or row.get("disposition") != _QUARANTINE_DISPOSITION
        or row.get("scientific_effect") != _QUARANTINE_SCIENTIFIC_EFFECT
    ):
        raise ValueError("consolidate_memory: quarantine receipt contract differs")
    observed_at = row.get("observed_at")
    if not isinstance(observed_at, str) or not observed_at or len(observed_at) > 64:
        raise ValueError("consolidate_memory: quarantine timestamp is malformed")

    source = row.get("source")
    if not isinstance(source, dict) or set(source) != {
        "kind",
        "path",
        "record_ordinal",
        "source_id",
        "source_row_sha256",
    }:
        raise ValueError("consolidate_memory: quarantine source fields differ")
    if source.get("kind") not in {"loop_memory", "surfaced_findings"}:
        raise ValueError("consolidate_memory: quarantine source kind differs")
    source_path = source.get("path")
    source_id = source.get("source_id")
    ordinal = source.get("record_ordinal")
    row_sha256 = source.get("source_row_sha256")
    if not isinstance(source_path, str) or not source_path or len(source_path) > 1024:
        raise ValueError("consolidate_memory: quarantine source path is malformed")
    if source_id is not None and (
        not isinstance(source_id, str) or not source_id or len(source_id) > 240
    ):
        raise ValueError("consolidate_memory: quarantine source id is malformed")
    if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 1:
        raise ValueError("consolidate_memory: quarantine ordinal is malformed")
    if not isinstance(row_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", row_sha256) is None:
        raise ValueError("consolidate_memory: quarantine source digest is malformed")

    reason = row.get("reason")
    if not isinstance(reason, dict) or set(reason) != {
        "code",
        "error_type",
        "message",
    }:
        raise ValueError("consolidate_memory: quarantine reason fields differ")
    if reason.get("code") not in _FAILURE_REASON_CODES:
        raise ValueError("consolidate_memory: quarantine reason code differs")
    error_type = reason.get("error_type")
    if error_type is not None and (
        not isinstance(error_type, str) or not error_type or len(error_type) > 120
    ):
        raise ValueError("consolidate_memory: quarantine error type is malformed")
    message = reason.get("message")
    if (
        not isinstance(message, str)
        or not message
        or len(message) > _FAILURE_MESSAGE_LIMIT
    ):
        raise ValueError("consolidate_memory: quarantine message is malformed")

    expected_identity = json.dumps(
        {
            "schema_version": _QUARANTINE_SCHEMA,
            "source_kind": source["kind"],
            "source_path": source["path"],
            "record_ordinal": ordinal,
            "source_row_sha256": row_sha256,
            "reason_code": reason["code"],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    expected_id = f"cq-{hashlib.sha256(expected_identity).hexdigest()}"
    if row.get("failure_id") != expected_id:
        raise ValueError("consolidate_memory: quarantine failure id differs")


def _load_quarantine_ids(path: Path) -> set[str]:
    """Read prior receipts strictly; corrupted accountability cannot look empty."""
    if not path.exists():
        return set()
    ids: set[str] = set()
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"consolidate_memory: quarantine row {line_number} is invalid JSON"
            ) from exc
        if not isinstance(row, dict):
            raise TypeError(
                f"consolidate_memory: quarantine row {line_number} is malformed"
            )
        try:
            _validate_quarantine_record(row)
        except ValueError as exc:
            raise ValueError(
                f"consolidate_memory: quarantine row {line_number} is malformed"
            ) from exc
        failure_id = row["failure_id"]
        if failure_id in ids:
            raise ValueError(
                f"consolidate_memory: quarantine row {line_number} duplicates a failure id"
            )
        ids.add(failure_id)
    return ids


def _build_items(
    loop_records: list[_SourceRecord],
    surfaced_records: list[_SourceRecord],
    extract_claim_fn: Callable,
    *,
    loop_memory_path: Path,
    surfaced_path: Path,
    observed_at: str,
) -> tuple[list[dict], list[str], list[dict]]:
    """Flatten both corpora into cluster items {id, kind, row, source_row,
    text}. Leaked-blob claims are repaired via claim_extract (counted).

    Known source-data failures are isolated into explicit quarantine receipts;
    unexpected code/infrastructure errors still raise. A quarantined row is not
    silently skipped: it is source-bound and has no idea-ledger side effect.
    """
    by_iter = {
        iid: record.row
        for record in loop_records
        for row in (record.row,)
        if isinstance((iid := row.get("iteration_id")), str) and iid
    }
    repaired: list[str] = []
    items: list[dict] = []
    failures: list[dict] = []

    for record in loop_records:
        row = record.row
        ordinal = record.record_ordinal
        iid = row.get("iteration_id")
        if not isinstance(iid, str) or not iid:
            failures.append(_quarantine_record(
                source_kind="loop_memory",
                source_path=loop_memory_path,
                record_ordinal=ordinal,
                source_row_sha256=record.source_row_sha256,
                source_id=None,
                reason_code="missing_iteration_id",
                message="source record lacks a non-empty iteration_id",
                error=None,
                observed_at=observed_at,
            ))
            continue
        hyp = row.get("hypothesis") if isinstance(row.get("hypothesis"), dict) else {}
        text = hyp.get("text") if isinstance(hyp.get("text"), str) else ""
        topic = ""
        if isinstance(row.get("seed"), dict):
            candidate_topic = row["seed"].get("topic")
            topic = candidate_topic if isinstance(candidate_topic, str) else ""
        if text.strip() and _is_leaked_blob(text):
            try:
                text = _repaired_surface(extract_claim_fn(row), iid)
            except ValueError as exc:
                if not _is_quarantinable_claim_error(exc):
                    raise
                failures.append(_quarantine_record(
                    source_kind="loop_memory",
                    source_path=loop_memory_path,
                    record_ordinal=ordinal,
                    source_row_sha256=record.source_row_sha256,
                    source_id=iid,
                    reason_code="unrecoverable_hypothesis_blob",
                    message="structured hypothesis output could not be recovered",
                    error=exc,
                    observed_at=observed_at,
                ))
                continue
            repaired.append(iid)
        if not text.strip():
            text = topic
        if not text.strip():
            failures.append(_quarantine_record(
                source_kind="loop_memory",
                source_path=loop_memory_path,
                record_ordinal=ordinal,
                source_row_sha256=record.source_row_sha256,
                source_id=iid,
                reason_code="empty_research_surface",
                message="source record has no hypothesis text or seed topic",
                error=None,
                observed_at=observed_at,
            ))
            continue
        items.append({"id": iid, "kind": "loop", "row": row, "source_row": row,
                      "text": (text + " " + topic).strip()})

    for record in surfaced_records:
        row = record.row
        ordinal = record.record_ordinal
        fid = row.get("finding_id")
        if not isinstance(fid, str) or not fid:
            failures.append(_quarantine_record(
                source_kind="surfaced_findings",
                source_path=surfaced_path,
                record_ordinal=ordinal,
                source_row_sha256=record.source_row_sha256,
                source_id=None,
                reason_code="missing_finding_id",
                message="source record lacks a non-empty finding_id",
                error=None,
                observed_at=observed_at,
            ))
            continue
        src_id = row.get("source_iteration_id")
        src = by_iter.get(src_id) if isinstance(src_id, str) else None
        text = row.get("claim") if isinstance(row.get("claim"), str) else ""
        if not text.strip():
            text = row.get("title") if isinstance(row.get("title"), str) else ""
        if text.strip() and _is_leaked_blob(text):
            if src is None:
                failures.append(_quarantine_record(
                    source_kind="surfaced_findings",
                    source_path=surfaced_path,
                    record_ordinal=ordinal,
                    source_row_sha256=record.source_row_sha256,
                    source_id=fid,
                    reason_code="unresolvable_claim_source",
                    message="structured finding claim has no resolvable source iteration",
                    error=None,
                    observed_at=observed_at,
                ))
                continue
            try:
                text = _repaired_surface(extract_claim_fn(src), fid)
            except ValueError as exc:
                if not _is_quarantinable_claim_error(exc):
                    raise
                failures.append(_quarantine_record(
                    source_kind="surfaced_findings",
                    source_path=surfaced_path,
                    record_ordinal=ordinal,
                    source_row_sha256=record.source_row_sha256,
                    source_id=fid,
                    reason_code="unrecoverable_finding_blob",
                    message="structured finding claim could not be recovered",
                    error=exc,
                    observed_at=observed_at,
                ))
                continue
            repaired.append(fid)
        if not text.strip():
            failures.append(_quarantine_record(
                source_kind="surfaced_findings",
                source_path=surfaced_path,
                record_ordinal=ordinal,
                source_row_sha256=record.source_row_sha256,
                source_id=fid,
                reason_code="empty_finding_surface",
                message="source finding has neither claim nor title",
                error=None,
                observed_at=observed_at,
            ))
            continue
        items.append({"id": fid, "kind": "surfaced", "row": row,
                      "source_row": src, "source_id": src_id, "text": text.strip()})
    return items, repaired, failures


def _match_cluster(item: dict, clusters: list[dict]) -> tuple[dict | None, dict | None]:
    """First cluster the item near-dups into, via the load-bearing lexical
    layer then the near-identical-only cosine layer. None = founds its own."""
    for cl in clusters:
        lex = max((_lexical_overlap(item["tokens"], m["text"]) for m in cl["members"]),
                  default=0.0)
        if lex >= JACCARD_DUP:
            return cl, {"layer": "lexical_jaccard", "score": round(lex, 4)}
        cos = max((_cosine(item.get("vector"), m.get("vector")) for m in cl["members"]),
                  default=0.0)
        if cos >= TAU_DUP:
            return cl, {"layer": "cosine_tau_dup", "score": round(cos, 4)}
    return None, None


def _existing_open_clusters(ledger_events: list[dict],
                            all_items: list[dict]) -> list[dict]:
    """The D-075 R4 matching pool: EXISTING not-killed clusters reduced from
    the ledger, carrying every member text recoverable from the corpora
    (ledger events do not store texts; the source corpora do, and every
    ledger member id is by definition an already-processed corpus id).
    Killed clusters are EXCLUDED — a fresh dup of a killed cluster founds
    its own cluster and faces its own signals; silent member_added into a
    dead niche would bypass evidence-keyed reopening (rule 4)."""
    if not ledger_events:
        return []
    text_by_id = {i["id"]: i["text"] for i in all_items}
    pool: list[dict] = []
    for cid, c in reduce_events(ledger_events).items():
        if c["status"] == "killed":
            continue
        members = [{"text": text_by_id[m]} for m in c["members"] if m in text_by_id]
        if members:
            pool.append({"cluster_id": cid, "existing": True, "members": members})
    return pool


def _cluster_items(items: list[dict], existing: list[dict] | None = None) -> list[dict]:
    """Greedy clustering in corpus order. EXISTING open ledger clusters (when
    supplied) sit FIRST in the match order — D-075 R4: a fresh near-dup of an
    already-minted cluster joins it instead of founding a duplicate, through
    the SAME layers at the SAME thresholds as intra-batch. A surfaced finding
    attaches to its source iteration's cluster directly (same evidence, not a
    near-dup); everything else goes through the dedup layers. Returns the
    existing clusters (with any fresh joiners appended) plus the new ones."""
    existing = existing or []
    ex_members = [m for cl in existing for m in cl["members"]]
    # One embed batch for fresh + existing texts: same vector space per call.
    vecs = _embed_texts([i["text"] for i in items] + [m["text"] for m in ex_members])
    for item, vec in zip(items, vecs[:len(items)]):
        item["vector"] = vec
        item["tokens"] = _tokenize(item["text"])
    for m, vec in zip(ex_members, vecs[len(items):]):
        m["vector"] = vec
    clusters: list[dict] = list(existing)
    member_cluster: dict[str, dict] = {}
    for item in items:
        target, how = None, None
        src_id = item.get("source_id")
        if item["kind"] == "surfaced" and src_id in member_cluster:
            target, how = member_cluster[src_id], {"layer": "source_iteration", "score": None}
        else:
            target, how = _match_cluster(item, clusters)
        if target is None:
            target = {"cluster_id": f"cl-{item['id']}", "members": []}
            clusters.append(target)
            how = {"layer": "founder", "score": None}
        item["joined_via"] = how
        target["members"].append(item)
        member_cluster[item["id"]] = target
    return clusters


def _derive_member_level(item: dict, feedback_by_iter: dict, cluster: dict,
                         derive_level_fn: Callable) -> dict:
    """Rung for one member. Loop rows carry no adversarial block themselves —
    a surfaced sibling for the same iteration supplies it; a surfaced item
    without a resolvable source derives from its own row."""
    row = item["source_row"] if item["source_row"] is not None else item["row"]
    iid = row.get("iteration_id") or item["id"]
    adv = None
    for m in cluster["members"]:
        if m["kind"] == "surfaced" and m.get("source_id") == iid \
                and isinstance(m["row"].get("adversarial"), dict):
            adv = m["row"]["adversarial"]
            break
    if adv is None and isinstance(item["row"].get("adversarial"), dict):
        adv = item["row"]["adversarial"]
    derived = derive_level_fn(row, feedback_by_iter.get(iid), adv, [])
    level = derived.get("level")
    if level not in LEVELS:
        raise ValueError(f"consolidate_memory: derive_level returned "
                         f"{level!r} for {item['id']} — not in {LEVELS} (rule 4).")
    return derived


def _accept_reason(via: dict) -> str:
    return via["layer"] + (f":{via['score']:.3f}"
                           if isinstance(via.get("score"), float) else "")


def _plan_existing_merges(clusters: list[dict], ts: str) -> tuple[list[dict], list[dict], list[dict]]:
    """member_added events + archive rows for fresh items that matched an
    EXISTING open ledger cluster (D-075 R4). NEVER a cluster_created, and no
    kill / elite / rung re-derivation — the cluster's standing state is the
    ledger's; this only records the new member. Near-dup joiners archive with
    the same reason as intra-batch near-dups (their text lives in the archive,
    not the ledger); source-attached surfaced members do not archive."""
    events: list[dict] = []
    archive: list[dict] = []
    merges: list[dict] = []
    for cl in clusters:
        for m in cl["members"]:
            if "id" not in m:
                continue  # pre-existing ledger member (text/vector only)
            via = m["joined_via"]
            events.append({"event_type": "member_added", "ts": ts,
                           "cluster_id": cl["cluster_id"], "member_id": m["id"],
                           "accept_reason": _accept_reason(via)})
            if via["layer"] in _NEAR_DUP_LAYERS:
                archive.append({"archived_at": ts, "cluster_id": cl["cluster_id"],
                                "member_id": m["id"], "kind": m["kind"],
                                "text": m["text"], "joined_via": via,
                                "reason": "near_dup_non_elite"})
            merges.append({"cluster_id": cl["cluster_id"], "member_id": m["id"],
                           "layer": via["layer"], "score": via.get("score")})
    return events, archive, merges


def _cluster_verdicts(elite_row: dict) -> tuple[str | None, str | None]:
    rt = elite_row.get("redteam") if isinstance(elite_row.get("redteam"), dict) else {}
    nv = elite_row.get("novelty") if isinstance(elite_row.get("novelty"), dict) else {}
    nclass = nv.get("class") or elite_row.get("novelty_class")
    return rt.get("verdict"), nclass


def _plan_cluster(cluster: dict, feedback_by_iter: dict, derive_level_fn: Callable,
                  ts: str) -> tuple[list[dict], list[dict], dict]:
    """Events + archive rows + facts for one cluster. Elite = highest-rung
    member (ties -> corpus order). Kill/niche is programmatic from the elite's
    signals: redteam fatal_flaw kills; novelty rediscovery seeds a paper niche."""
    for item in cluster["members"]:
        item["derived"] = _derive_member_level(item, feedback_by_iter, cluster,
                                               derive_level_fn)
    elite = max(cluster["members"], key=lambda m: LEVELS.index(m["derived"]["level"]))
    level = elite["derived"]["level"]
    cid = cluster["cluster_id"]
    founder, rest = cluster["members"][0], cluster["members"][1:]

    # Events use the idea_ledger schema shapes verbatim (schema/idea_ledger
    # .schema.json, additionalProperties:false) so the real write path —
    # idea_ledger.append_event, which validates — accepts them. Member texts
    # live in the archive rows, not the ledger.
    events = [{"event_type": "cluster_created", "ts": ts, "cluster_id": cid,
               "member_id": founder["id"], "origin": "consolidation",
               **({"iteration_id": founder["id"]} if founder["kind"] == "loop" else {})}]
    archive: list[dict] = []
    for m in rest:
        events.append({"event_type": "member_added", "ts": ts, "cluster_id": cid,
                       "member_id": m["id"],
                       **({"as_elite": True} if m is elite else {}),
                       "accept_reason": _accept_reason(m["joined_via"])})
    for m in cluster["members"]:
        if m is not elite and m["joined_via"]["layer"] in _NEAR_DUP_LAYERS:
            archive.append({"archived_at": ts, "cluster_id": cid,
                            "member_id": m["id"], "kind": m["kind"],
                            "text": m["text"], "joined_via": m["joined_via"],
                            "reason": "near_dup_non_elite"})
    if level != "L0":
        events.append({"event_type": "evidence_level_changed", "ts": ts,
                       "cluster_id": cid, "evidence_level": level,
                       "basis": f"evidence_ladder:{elite['id']}"})

    elite_row = elite["source_row"] if elite["source_row"] is not None else elite["row"]
    rt_verdict, nclass = _cluster_verdicts(elite_row)
    status, niche = "open", False
    if rt_verdict == "fatal_flaw":
        status = "killed"
        events.append({"event_type": "cluster_killed", "ts": ts, "cluster_id": cid,
                       "kill_reason": kill_reason_from_redteam(elite_row),
                       "reopening_condition": reopening_condition(
                           "redteam_proceed_on_revision")})
    elif nclass == "rediscovery":
        # A rediscovery closes THIS cluster with the paper-prior kill code
        # (niche_seeded creates a NEW paper niche and would collide with the
        # cluster_created above — the reducer forbids duplicate creates).
        status = "killed"
        niche = True
        iid = elite_row.get("iteration_id") or elite["id"]
        rationale = (elite_row.get("novelty") or {}).get("rationale") or ""
        events.append({"event_type": "cluster_killed", "ts": ts, "cluster_id": cid,
                       "kill_reason": {"code": "paper_prior_exists",
                                       "evidence_key": f"iteration:{iid}:novelty",
                                       "detail": rationale[:_EXCERPT]
                                                 or f"novelty class rediscovery on {iid}"},
                       "reopening_condition": reopening_condition("articulated_delta")})
    return events, archive, {"cluster_id": cid, "level": level, "status": status,
                             "niche": niche, "elite_id": elite["id"],
                             "size": len(cluster["members"])}


def _print_summary(report: dict) -> None:
    mode = ("DRY-RUN — nothing written; re-run with --execute"
            if report["dry_run"] else "EXECUTE — events appended")
    rungs = " ".join(f"{lvl}={report['rungs'].get(lvl, 0)}" for lvl in LEVELS)
    lines = [
        f"== consolidate_memory [{mode}] ==",
        (
            f"  rows                loop={report['loop_rows']} "
            f"surfaced={report['surfaced_rows']} "
            f"already_processed={report['skipped_already_processed']}"
        ),
        f"  clusters            {report['clusters']}",
        f"  merged into existing {report['merged_into_existing']}",
        f"  rungs               {rungs}",
        f"  killed (planned)    {report['killed']}",
        f"  paper niches        {report['paper_niches']}",
        (
            f"  archive rows        "
            f"{report['archived'] if not report['dry_run'] else report['archive_planned']}"
        ),
        f"  claims repaired     {report['claims_repaired']}",
        (
            f"  quarantined rows    planned={report['quarantine_planned']} "
            f"appended={report['quarantine_appended']} "
            f"already_recorded={report['quarantine_already_recorded']}"
        ),
        (
            f"  events {'appended' if not report['dry_run'] else 'planned '}     "
            f"{report['events_appended'] if not report['dry_run'] else report['events_planned']}"
        ),
    ]
    print("\n".join(lines))


def _execute_lock_path(ledger_path: Path) -> Path:
    """Return one canonical sidecar lock keyed by the target ledger location."""
    target = ledger_path.expanduser().resolve(strict=False)
    return target.with_name(f".{target.name}.consolidate.lock")


@contextlib.contextmanager
def _execute_lock(ledger_path: Path) -> Iterator[None]:
    """Own the read/dedupe/write transaction or fail immediately.

    Dry-runs never enter this context and therefore create no lock artifact.
    A regular, non-symlink sidecar prevents two CLI execute passes from both
    reading the same pre-append ledger state and projecting duplicate events.
    """
    lock_path = _execute_lock_path(ledger_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock_path, flags, 0o600)
    lock = os.fdopen(descriptor, "a+")
    acquired = False
    try:
        if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode):
            raise ValueError(
                "consolidate_memory: execute lock is not a regular file"
            )
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError as exc:
            raise ConsolidationBusyError(
                f"consolidate_memory: another execute pass owns {lock_path}"
            ) from exc
        yield
    finally:
        if acquired:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def _consolidate_once(
    *,
    loop_memory_path: str | Path | None = None,
    surfaced_path: str | Path | None = None,
    feedback_path: str | Path | None = None,
    ledger_path: str | Path | None = None,
    archive_path: str | Path | None = None,
    quarantine_path: str | Path | None = None,
    execute: bool = False,
    derive_level_fn: Callable | None = None,
    extract_claim_fn: Callable | None = None,
    append_event_fn: Callable | None = None,
) -> dict[str, Any]:
    """Run the migration. Dry-run (default) computes and prints the human-gate
    summary and writes NOTHING. `execute=True` appends explicit source-bound
    quarantine receipts for malformed rows, then idea-ledger events + archive
    rows for valid rows. Source corpora are never modified. Idempotent by
    failure id and member id."""
    t0 = time.perf_counter()
    loop_memory_path = Path(loop_memory_path or DEFAULT_LOOP_MEMORY)
    surfaced_path = Path(surfaced_path or DEFAULT_SURFACED)
    feedback_path = Path(feedback_path or DEFAULT_FEEDBACK)
    ledger_path = Path(ledger_path or DEFAULT_LEDGER)
    archive_path = Path(archive_path or DEFAULT_ARCHIVE)
    quarantine_path = Path(quarantine_path or DEFAULT_QUARANTINE)
    derive_level_fn = derive_level_fn or _default_derive_level(loop_memory_path.parent.parent)
    extract_claim_fn = extract_claim_fn or _default_extract_claim()
    append_event_fn = append_event_fn or _default_append_event()

    for p, name in ((loop_memory_path, "loop_memory"), (surfaced_path, "surfaced_findings")):
        if not p.exists():
            raise FileNotFoundError(
                f"consolidate_memory: {name} missing at {p} — cannot migrate an "
                f"absent corpus (rule 7: no silent empty migration).")

    ts = _utcnow()
    loop_source = _read_source_jsonl(
        loop_memory_path,
        source_kind="loop_memory",
        observed_at=ts,
    )
    surfaced_source = _read_source_jsonl(
        surfaced_path,
        source_kind="surfaced_findings",
        observed_at=ts,
    )
    feedback_by_iter = {r["iteration_id"]: r for r in _read_jsonl(feedback_path)
                        if isinstance(r.get("iteration_id"), str)}

    items, repaired, shape_failures = _build_items(
        loop_source.records,
        surfaced_source.records,
        extract_claim_fn,
        loop_memory_path=loop_memory_path,
        surfaced_path=surfaced_path,
        observed_at=ts,
    )
    failures = sorted(
        loop_source.failures + surfaced_source.failures + shape_failures,
        key=lambda row: (
            0 if row["source"]["kind"] == "loop_memory" else 1,
            row["source"]["record_ordinal"],
        ),
    )
    prior_failure_ids = _load_quarantine_ids(quarantine_path)
    new_failures = [
        row for row in failures if row["failure_id"] not in prior_failure_ids
    ]
    ledger_events = _read_jsonl(ledger_path)
    processed = {e.get("member_id") for e in ledger_events
                 if e.get("event_type") in _MEMBER_EVENTS}
    fresh = [i for i in items if i["id"] not in processed]
    skipped = len(items) - len(fresh)

    # D-075 R4: existing open clusters are matched BEFORE any minting.
    pool = _existing_open_clusters(ledger_events, items) if fresh else []

    new_events: list[dict] = []
    archive: list[dict] = []
    facts: list[dict] = []
    existing_hit: list[dict] = []
    for cluster in _cluster_items(fresh, existing=pool):
        if cluster.get("existing"):
            if any("id" in m for m in cluster["members"]):
                existing_hit.append(cluster)
            continue
        ev, ar, fact = _plan_cluster(cluster, feedback_by_iter, derive_level_fn, ts)
        new_events.extend(ev)
        archive.extend(ar)
        facts.append(fact)
    merge_events, merge_archive, merges = _plan_existing_merges(existing_hit, ts)
    events = merge_events + new_events
    archive = merge_archive + archive

    appended = 0
    quarantine_appended = 0
    if execute:
        # Accountability lands before the valid projection. A crash after this
        # point is retry-safe by deterministic failure/member identities.
        for row in new_failures:
            _append_jsonl(quarantine_path, row)
            quarantine_appended += 1
        for ev in events:
            append_event_fn(ledger_path, ev)
            appended += 1
        for row in archive:
            _append_jsonl(archive_path, row)

    rungs: dict[str, int] = {}
    for f in facts:
        rungs[f["level"]] = rungs.get(f["level"], 0) + 1
    report = {
        "dry_run": not execute,
        "loop_rows": loop_source.nonblank_rows,
        "surfaced_rows": surfaced_source.nonblank_rows,
        "skipped_already_processed": skipped,
        "clusters": len(facts),
        "merged_into_existing": len(merges),
        "existing_merges": merges,
        "rungs": rungs,
        "killed": sum(1 for f in facts if f["status"] == "killed"),
        "paper_niches": sum(1 for f in facts if f["niche"]),
        "archived": len(archive) if execute else 0,
        "archive_planned": len(archive),
        "claims_repaired": len(repaired),
        "repaired_ids": repaired,
        "quarantined_rows": len(failures),
        "quarantine_planned": len(new_failures),
        "quarantine_appended": quarantine_appended,
        "quarantine_already_recorded": len(failures) - len(new_failures),
        "quarantine_failures": failures,
        "events_planned": len(events),
        "events_appended": appended,
        "cluster_facts": facts,
    }
    _print_summary(report)
    if execute:
        runtime.append_run_log({
            "task_id": "consolidate_memory",
            "status": "passed",
            "observable_actual": f"mode={'execute' if execute else 'dry_run'} "
                                 f"clusters={report['clusters']} "
                                 f"merged={report['merged_into_existing']} "
                                 f"killed={report['killed']} "
                                 f"quarantined={report['quarantined_rows']} "
                                 f"quarantine_appended={quarantine_appended} "
                                 f"events_appended={appended} skipped={skipped}",
            "observable_expected": "idempotent append-only migration; dry-run writes nothing",
            "duration_ms": round((time.perf_counter() - t0) * 1000.0, 3),
        })
    return report


def consolidate(
    *,
    loop_memory_path: str | Path | None = None,
    surfaced_path: str | Path | None = None,
    feedback_path: str | Path | None = None,
    ledger_path: str | Path | None = None,
    archive_path: str | Path | None = None,
    quarantine_path: str | Path | None = None,
    execute: bool = False,
    derive_level_fn: Callable | None = None,
    extract_claim_fn: Callable | None = None,
    append_event_fn: Callable | None = None,
) -> dict[str, Any]:
    """Run one dry or execute consolidation pass.

    Execute owns one nonblocking ledger-keyed lock across every source read,
    dedupe decision, and append. Dry-run remains a side-effect-free read and
    deliberately does not create the sidecar lock.
    """
    normalized_ledger = Path(ledger_path or DEFAULT_LEDGER)
    lock = _execute_lock(normalized_ledger) if execute else contextlib.nullcontext()
    with lock:
        return _consolidate_once(
            loop_memory_path=loop_memory_path,
            surfaced_path=surfaced_path,
            feedback_path=feedback_path,
            ledger_path=normalized_ledger,
            archive_path=archive_path,
            quarantine_path=quarantine_path,
            execute=execute,
            derive_level_fn=derive_level_fn,
            extract_claim_fn=extract_claim_fn,
            append_event_fn=append_event_fn,
        )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="One-shot idempotent consolidation of loop_memory + "
                    "surfaced_findings into idea-ledger events. DRY-RUN by "
                    "default; the summary is the G2 human-gate artifact.")
    ap.add_argument("--execute", action="store_true",
                    help="write events + archive rows (default: dry-run, no writes)")
    ap.add_argument("--loop-memory", default=None)
    ap.add_argument("--surfaced", default=None)
    ap.add_argument("--feedback", default=None)
    ap.add_argument("--ledger", default=None)
    ap.add_argument("--archive", default=None)
    ap.add_argument("--quarantine", default=None)
    args = ap.parse_args(argv)
    consolidate(loop_memory_path=args.loop_memory, surfaced_path=args.surfaced,
                feedback_path=args.feedback, ledger_path=args.ledger,
                archive_path=args.archive, quarantine_path=args.quarantine,
                execute=args.execute)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
