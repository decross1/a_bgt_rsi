"""Append-only, source-bound topics for an ongoing research campaign.

The immutable campaign manifest defines the scope.  This registry only adds
exact topic identities backed by a verified daily arXiv ingestion receipt.
Every reader validates every receipt; a damaged registry fails closed instead
of looking like an empty queue.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_RELATIVE = ("run_state", "research_topic_registry")
RECEIPT_SCHEMA_VERSION = "research-topic-registration/v1"
REGISTERED_SOURCE = "campaign_registered"
SOURCE_KIND = "daily_arxiv_paper"
# Owner, 2026-09-23: no daily topic limit by default (Nara's model is local and
# free). TOPIC_DAILY_CAP=<n> restores one. The one-unconsumed-topic rule and
# MAX_RECEIPTS still pace registration.
MAX_REGISTRATIONS_PER_UTC_DAY = int(os.environ.get("TOPIC_DAILY_CAP", "0"))
MAX_PENDING_TOPICS = 1
MAX_RECEIPTS = 512
MAX_RECEIPT_BYTES = 16_000
MAX_CLOCK_SKEW = timedelta(minutes=5)

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CAMPAIGN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,79}$")
TOPIC_ID_RE = CAMPAIGN_ID_RE
ARXIV_BASE_ID_RE = re.compile(
    r"(?:[0-9]{4}\.[0-9]{4,5}|[a-z-]+(?:\.[A-Z]{2})?/[0-9]{7})\Z"
)
INGESTION_RUN_ID_RE = re.compile(
    r"daily-arxiv-[0-9]{8}T[0-9]{6}Z-[0-9]+-[0-9a-f]{8}\Z"
)
SOURCE_FIELDS = frozenset(
    {
        "kind",
        "id",
        "sha256",
        "ingestion_run_id",
        "ingestion_input_sha256",
        "ingestion_terminal_sha256",
    }
)
RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "campaign_id",
        "campaign_manifest_sha256",
        "research_question_id",
        "research_question_sha256",
        "topic_id",
        "text",
        "text_sha256",
        "source",
        "registered_at",
        "registered_by",
    }
)


def _error(message: str) -> ValueError:
    # Imported lazily so research_campaign.load_campaign can load this module
    # after it has established the manifest's private identity fields.
    from orchestrator.research_campaign import CampaignError

    return CampaignError(message)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise _error("topic registration is not canonical JSON") from exc
    return (encoded + "\n").encode("utf-8")


def _strict_json(raw: bytes, *, where: str) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise _error(f"duplicate field in {where}")
            result[key] = value
        return result

    def reject_constant(_value: str) -> None:
        raise _error(f"non-finite value in {where}")

    try:
        value = json.loads(
            raw,
            object_pairs_hook=unique,
            parse_constant=reject_constant,
        )
    except UnicodeDecodeError as exc:
        raise _error(f"{where} is not UTF-8 JSON") from exc
    except json.JSONDecodeError as exc:
        raise _error(f"{where} is not strict JSON") from exc
    if not isinstance(value, dict):
        raise _error(f"{where} is not an object")
    return value


def _utc(value: datetime | None) -> datetime:
    current = datetime.now(timezone.utc) if value is None else value
    if not isinstance(current, datetime) or current.tzinfo is None:
        raise _error("topic registration time needs a timezone")
    try:
        return current.astimezone(timezone.utc)
    except (TypeError, ValueError) as exc:
        raise _error("topic registration time is invalid") from exc


def _parse_timestamp(value: Any, *, where: str) -> datetime:
    if not isinstance(value, str):
        raise _error(f"{where} is not a timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _error(f"{where} is not a valid timestamp") from exc
    if parsed.tzinfo is None:
        raise _error(f"{where} has no timezone")
    return parsed.astimezone(timezone.utc)


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _campaign_root(campaign: Mapping[str, Any], repo_root: Path | None) -> Path:
    selected = repo_root if repo_root is not None else campaign.get("_repo_root")
    if selected is None:
        selected = REPO_ROOT
    try:
        return Path(selected).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise _error("topic registry repository root is unavailable") from exc


def _campaign_identity(campaign: Mapping[str, Any]) -> tuple[str, str]:
    campaign_id = campaign.get("campaign_id")
    manifest_sha = campaign.get("_manifest_sha256")
    if (
        not isinstance(campaign_id, str)
        or CAMPAIGN_ID_RE.fullmatch(campaign_id) is None
        or not isinstance(manifest_sha, str)
        or SHA256_RE.fullmatch(manifest_sha) is None
    ):
        raise _error("topic registry campaign identity is incomplete")
    return campaign_id, manifest_sha


@contextmanager
def _open_registry_directory(
    repo_root: Path,
    campaign_id: str,
    *,
    create: bool,
) -> Iterator[int | None]:
    """Open each directory component without following symbolic links."""
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    descriptors: list[int] = []
    try:
        try:
            descriptors.append(os.open(repo_root, flags | nofollow))
        except OSError as exc:
            raise _error("topic registry root cannot be opened safely") from exc
        for component in (*REGISTRY_RELATIVE, campaign_id):
            parent_fd = descriptors[-1]
            try:
                child_fd = os.open(component, flags | nofollow, dir_fd=parent_fd)
            except FileNotFoundError:
                if not create:
                    yield None
                    return
                try:
                    os.mkdir(component, mode=0o700, dir_fd=parent_fd)
                    os.fsync(parent_fd)
                except FileExistsError:
                    pass
                except OSError as exc:
                    raise _error("topic registry directory cannot be created safely") from exc
                try:
                    child_fd = os.open(component, flags | nofollow, dir_fd=parent_fd)
                except OSError as exc:
                    raise _error("topic registry directory cannot be opened safely") from exc
            except OSError as exc:
                raise _error("topic registry directory is redirected or invalid") from exc
            descriptors.append(child_fd)
        yield descriptors[-1]
    finally:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass


def _read_receipt(directory_fd: int, filename: str) -> bytes:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(filename, flags, dir_fd=directory_fd)
    except OSError as exc:
        raise _error("topic registration receipt cannot be opened safely") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_RECEIPT_BYTES:
            raise _error("topic registration receipt is non-regular or oversized")
        chunks: list[bytes] = []
        remaining = MAX_RECEIPT_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 8192))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            len(raw) != before.st_size
            or len(raw) > MAX_RECEIPT_BYTES
            or (before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_ino, after.st_size, after.st_mtime_ns)
        ):
            raise _error("topic registration receipt changed during read")
        return raw
    finally:
        os.close(descriptor)


def _validate_source(source: Any) -> dict[str, str]:
    if not isinstance(source, dict) or set(source) != SOURCE_FIELDS:
        raise _error("topic registration source identity is incomplete")
    if not all(isinstance(value, str) for value in source.values()):
        raise _error("topic registration source fields must be strings")
    if source["kind"] != SOURCE_KIND:
        raise _error("topic registration source kind is not supported")
    if ARXIV_BASE_ID_RE.fullmatch(source["id"]) is None:
        raise _error("topic registration source id is not an arXiv base id")
    if INGESTION_RUN_ID_RE.fullmatch(source["ingestion_run_id"]) is None:
        raise _error("topic registration ingestion run id is invalid")
    for field in (
        "sha256",
        "ingestion_input_sha256",
        "ingestion_terminal_sha256",
    ):
        if SHA256_RE.fullmatch(source[field]) is None:
            raise _error(f"topic registration {field} is invalid")
    return copy.deepcopy(source)


def _revalidate_current_source(
    topic: str,
    source: Mapping[str, str],
    *,
    repo_root: Path,
    now: datetime,
) -> None:
    """Require the writer's source to survive the pure verified-source read."""
    from orchestrator.daily_research import literature_candidates

    candidates = literature_candidates(repo_root=repo_root, now=now)
    if not isinstance(candidates, list) or not any(
        isinstance(candidate, dict)
        and candidate.get("topic") == topic
        and candidate.get("source") == dict(source)
        for candidate in candidates
    ):
        raise _error(
            "topic registration source is not one exact currently verified "
            "literature candidate"
        )


def _topic_id(
    campaign_id: str,
    manifest_sha: str,
    text_sha: str,
    source: Mapping[str, str],
) -> str:
    identity = {
        "campaign_id": campaign_id,
        "campaign_manifest_sha256": manifest_sha,
        "text_sha256": text_sha,
        "source": dict(source),
    }
    digest = _sha256(_canonical(identity))
    return f"topic-registered-{digest[:24]}"


def _validate_receipt(
    value: dict[str, Any],
    raw: bytes,
    *,
    filename: str,
    campaign: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any]:
    campaign_id, manifest_sha = _campaign_identity(campaign)
    question = campaign.get("research_question")
    if not isinstance(question, Mapping):
        raise _error("topic registry campaign question is incomplete")
    if set(value) != RECEIPT_FIELDS:
        raise _error("topic registration receipt fields differ")
    scalar_fields = RECEIPT_FIELDS - {"source"}
    if not all(isinstance(value[field], str) for field in scalar_fields):
        raise _error("topic registration receipt fields must be strings")
    if value["schema_version"] != RECEIPT_SCHEMA_VERSION:
        raise _error("topic registration receipt schema differs")
    if (
        value["campaign_id"] != campaign_id
        or value["campaign_manifest_sha256"] != manifest_sha
        or value["research_question_id"] != question.get("question_id")
        or value["research_question_sha256"] != question.get("text_sha256")
    ):
        raise _error("topic registration receipt campaign identity differs")
    topic_text = value["text"]
    if not topic_text or len(topic_text) > 2000 or topic_text.strip() != topic_text:
        raise _error("topic registration text is empty, oversized, or padded")
    text_sha = _sha256(topic_text.encode("utf-8"))
    if value["text_sha256"] != text_sha:
        raise _error("topic registration text hash differs")
    source = _validate_source(value["source"])
    expected_topic_id = _topic_id(campaign_id, manifest_sha, text_sha, source)
    if (
        TOPIC_ID_RE.fullmatch(value["topic_id"]) is None
        or value["topic_id"] != expected_topic_id
        or filename != f"{expected_topic_id}.json"
    ):
        raise _error("topic registration id or filename differs")
    if not value["registered_by"] or len(value["registered_by"]) > 120:
        raise _error("topic registration actor is invalid")
    registered_at = _parse_timestamp(
        value["registered_at"], where="topic registration timestamp"
    )
    opened_at = _parse_timestamp(
        campaign.get("opened_at"), where="campaign opening timestamp"
    )
    if registered_at < opened_at:
        raise _error("topic registration predates campaign opening")
    if registered_at > now + MAX_CLOCK_SKEW:
        raise _error("topic registration timestamp is in the future")
    return {
        "topic_id": value["topic_id"],
        "text": topic_text,
        "text_sha256": text_sha,
        "source": REGISTERED_SOURCE,
        "topic_registration_sha256": _sha256(raw),
        "registration_source": source,
        "registered_at": value["registered_at"],
    }


def load_registered_topics(
    campaign: Mapping[str, Any],
    *,
    repo_root: Path | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Read and validate every append-only registration for one campaign."""
    policy = campaign.get("topic_policy")
    if not isinstance(policy, Mapping):
        raise _error("topic registry campaign policy is incomplete")
    if policy.get("mode") != "registered_exploratory":
        return []
    observed = _utc(now)
    campaign_id, _manifest_sha = _campaign_identity(campaign)
    root = _campaign_root(campaign, repo_root)
    topics: list[dict[str, Any]] = []
    with _open_registry_directory(root, campaign_id, create=False) as directory_fd:
        if directory_fd is None:
            return []
        try:
            filenames = sorted(os.listdir(directory_fd))
        except OSError as exc:
            raise _error("topic registry directory cannot be listed safely") from exc
        if len(filenames) > MAX_RECEIPTS:
            raise _error("topic registry exceeds its receipt cap")
        for filename in filenames:
            if (
                not isinstance(filename, str)
                or not filename.endswith(".json")
                or TOPIC_ID_RE.fullmatch(filename[:-5]) is None
            ):
                raise _error("topic registry contains an unexpected entry")
            raw = _read_receipt(directory_fd, filename)
            receipt = _strict_json(raw, where=f"topic registration {filename}")
            topics.append(
                _validate_receipt(
                    receipt,
                    raw,
                    filename=filename,
                    campaign=campaign,
                    now=observed,
                )
            )

    declared = policy.get("topics")
    if not isinstance(declared, list):
        raise _error("topic registry declared topic list is invalid")
    ids = [topic.get("topic_id") for topic in declared if isinstance(topic, Mapping)]
    texts = [topic.get("text") for topic in declared if isinstance(topic, Mapping)]
    hashes = [topic.get("text_sha256") for topic in declared if isinstance(topic, Mapping)]
    sources: set[tuple[str, str]] = set()
    for topic in topics:
        source = topic["registration_source"]
        source_key = (source["kind"], source["id"])
        if (
            topic["topic_id"] in ids
            or topic["text"] in texts
            or topic["text_sha256"] in hashes
            or source_key in sources
        ):
            raise _error("topic registry contains a duplicate topic or source")
        ids.append(topic["topic_id"])
        texts.append(topic["text"])
        hashes.append(topic["text_sha256"])
        sources.add(source_key)
    return sorted(topics, key=lambda item: (item["registered_at"], item["topic_id"]))


def _link(campaign: Mapping[str, Any], topic: Mapping[str, Any]) -> dict[str, str]:
    question = campaign["research_question"]
    link = {
        "schema_version": "research-campaign-link/v1",
        "campaign_id": campaign["campaign_id"],
        "campaign_manifest_sha256": campaign["_manifest_sha256"],
        "research_question_id": question["question_id"],
        "research_question_sha256": question["text_sha256"],
        "topic_id": topic["topic_id"],
        "topic_sha256": topic["text_sha256"],
    }
    registration_sha = topic.get("topic_registration_sha256")
    if isinstance(registration_sha, str):
        link["topic_registration_sha256"] = registration_sha
    return link


def _is_consumed(
    campaign: Mapping[str, Any],
    topic: Mapping[str, Any],
    loop_rows: Sequence[dict[str, Any]],
) -> bool:
    expected = _link(campaign, topic)
    for row in loop_rows:
        if not isinstance(row, dict) or row.get("campaign") != expected:
            continue
        if "registered_at" in topic and "started_at" in row:
            try:
                started_at = _parse_timestamp(row["started_at"], where="record start")
                registered_at = _parse_timestamp(
                    topic["registered_at"], where="topic registration timestamp"
                )
            except ValueError:
                continue
            if started_at < registered_at:
                continue
        return True
    return False


def _write_new(directory_fd: int, filename: str, raw: bytes) -> None:
    flags = (
        os.O_CREAT
        | os.O_EXCL
        | os.O_WRONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(filename, flags, 0o600, dir_fd=directory_fd)
    except FileExistsError as exc:
        raise _error("topic registration receipt already exists") from exc
    except OSError as exc:
        raise _error("topic registration receipt cannot be created safely") from exc
    try:
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            if written <= 0:
                raise OSError("short topic registration write")
            offset += written
        os.fsync(descriptor)
    except BaseException:
        try:
            os.unlink(filename, dir_fd=directory_fd)
        except OSError:
            pass
        raise
    finally:
        os.close(descriptor)
    os.fsync(directory_fd)


def register_topic(
    campaign: dict[str, Any],
    topic: str,
    *,
    source: Mapping[str, str],
    loop_rows: Sequence[dict[str, Any]],
    now: datetime | None = None,
    repo_root: Path | None = None,
    registered_by: str = "daily_replenisher",
) -> dict[str, Any]:
    """Append one source-bound topic after daily and pending-cap checks."""
    policy = campaign.get("topic_policy")
    if not isinstance(policy, Mapping) or policy.get("mode") != "registered_exploratory":
        raise _error("topic registration requires a registered exploratory campaign")
    if not isinstance(topic, str) or not topic or len(topic) > 2000:
        raise _error("topic registration text is empty or oversized")
    if topic.strip() != topic:
        raise _error("topic registration text has surrounding whitespace")
    if (
        not isinstance(loop_rows, Sequence)
        or isinstance(loop_rows, (str, bytes, bytearray))
    ):
        raise _error("topic registration loop rows are invalid")
    if not isinstance(registered_by, str) or not registered_by or len(registered_by) > 120:
        raise _error("topic registration actor is invalid")

    observed = _utc(now)
    root = _campaign_root(campaign, repo_root)
    campaign_id, manifest_sha = _campaign_identity(campaign)
    registration_source = _validate_source(dict(source) if isinstance(source, Mapping) else source)
    registered = load_registered_topics(campaign, repo_root=root, now=observed)
    declared = policy.get("topics")
    if not isinstance(declared, list):
        raise _error("topic registry declared topic list is invalid")
    combined = [copy.deepcopy(item) for item in declared] + registered
    text_sha = _sha256(topic.encode("utf-8"))
    if any(
        item.get("text") == topic or item.get("text_sha256") == text_sha
        for item in combined
        if isinstance(item, Mapping)
    ):
        raise _error("topic registration duplicates an existing topic")
    if any(
        item.get("registration_source", {}).get("kind") == registration_source["kind"]
        and item.get("registration_source", {}).get("id") == registration_source["id"]
        for item in registered
    ):
        raise _error("topic registration duplicates an existing source")
    _revalidate_current_source(
        topic,
        registration_source,
        repo_root=root,
        now=observed,
    )
    if MAX_REGISTRATIONS_PER_UTC_DAY > 0 and sum(
        _parse_timestamp(item["registered_at"], where="topic registration timestamp").date()
        == observed.date()
        for item in registered
    ) >= MAX_REGISTRATIONS_PER_UTC_DAY:
        raise _error("topic registration daily cap reached")
    pending = sum(
        not _is_consumed(campaign, item, loop_rows)
        for item in combined
        if isinstance(item, Mapping)
    )
    if pending >= MAX_PENDING_TOPICS:
        raise _error("topic registration pending cap reached")

    topic_id = _topic_id(campaign_id, manifest_sha, text_sha, registration_source)
    question = campaign["research_question"]
    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "campaign_id": campaign_id,
        "campaign_manifest_sha256": manifest_sha,
        "research_question_id": question["question_id"],
        "research_question_sha256": question["text_sha256"],
        "topic_id": topic_id,
        "text": topic,
        "text_sha256": text_sha,
        "source": registration_source,
        "registered_at": _stamp(observed),
        "registered_by": registered_by,
    }
    raw = _canonical(receipt)
    filename = f"{topic_id}.json"
    projection = _validate_receipt(
        receipt,
        raw,
        filename=filename,
        campaign=campaign,
        now=observed,
    )
    with _open_registry_directory(root, campaign_id, create=True) as directory_fd:
        if directory_fd is None:  # pragma: no cover - create=True invariant
            raise _error("topic registry directory was not created")
        _write_new(directory_fd, filename, raw)
    campaign["_registered_topics"] = registered + [copy.deepcopy(projection)]
    return projection


__all__ = [
    "MAX_PENDING_TOPICS",
    "MAX_REGISTRATIONS_PER_UTC_DAY",
    "RECEIPT_SCHEMA_VERSION",
    "REGISTERED_SOURCE",
    "SOURCE_KIND",
    "load_registered_topics",
    "register_topic",
]
