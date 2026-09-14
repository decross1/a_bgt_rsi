"""Bounded campaign registry and exact lineage helpers for research v2.

Campaign membership is explicit. A record without a complete link remains
legacy/unlinked; neither timestamps nor similar topic text can promote it into
a campaign. Literature and explicitly matched negative-memory evidence may be
shared, while research outcomes remain scoped to their recorded campaign.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import jsonschema

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "schema" / "research_campaign.schema.json"
ACTIVATION_SCHEMA_PATH = (
    REPO_ROOT / "schema" / "research_campaign_activation.schema.json"
)
CLOSURE_SCHEMA_PATH = REPO_ROOT / "schema" / "research_campaign_closure.schema.json"
DEFAULT_ACTIVATION_PATH = REPO_ROOT / "run_state" / "active_research_campaign.json"
DEFAULT_CLOSURE_DIR = REPO_ROOT / "run_state" / "research_campaign_closures"
DEFAULT_CAMPAIGN_ID = "v2-agentic-game-theory-20260914"
DEFAULT_CAMPAIGN_MANIFEST = (
    REPO_ROOT / "experiments" / "research_campaign_v2_agentic_game_theory_20260914.json"
)
CAMPAIGN_MANIFESTS: Mapping[str, str] = {
    DEFAULT_CAMPAIGN_ID: (
        "experiments/research_campaign_v2_agentic_game_theory_20260914.json"
    ),
}
MAX_MANIFEST_BYTES = 128_000
MAX_REFERENCED_BYTES = 512_000
MAX_CLOCK_SKEW = timedelta(minutes=5)
LINK_SCHEMA_VERSION = "research-campaign-link/v1"
LINK_FIELDS = frozenset(
    {
        "schema_version",
        "campaign_id",
        "campaign_manifest_sha256",
        "research_question_id",
        "research_question_sha256",
        "topic_id",
        "topic_sha256",
    }
)


class CampaignError(ValueError):
    """A campaign declaration or link is malformed or unbound."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _timestamp(value: str, *, where: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise CampaignError(f"{where} is not a valid timestamp") from exc
    if parsed.tzinfo is None:
        raise CampaignError(f"{where} has no timezone")
    return parsed.astimezone(timezone.utc)


def _read_regular(root: Path, relative: str, *, limit: int) -> tuple[Path, bytes]:
    """Read one contained regular file without following redirected paths."""
    if not isinstance(relative, str) or not relative or len(relative) > 240:
        raise CampaignError("campaign artifact path is invalid")
    raw = root / relative
    try:
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise CampaignError("campaign artifact leaves the repository")
        cursor = root
        for part in relative_path.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise CampaignError("campaign artifact uses a redirected path")
        resolved_root = root.resolve(strict=True)
        resolved = raw.resolve(strict=True)
        resolved.relative_to(resolved_root)
        stat = resolved.stat()
        if not resolved.is_file() or stat.st_size > limit:
            raise CampaignError(
                "campaign artifact is absent, non-regular, or oversized"
            )
        with resolved.open("rb") as handle:
            data = handle.read(limit + 1)
    except CampaignError:
        raise
    except (OSError, ValueError) as exc:
        raise CampaignError("campaign artifact cannot be read safely") from exc
    if len(data) > limit:
        raise CampaignError("campaign artifact exceeds its read bound")
    return resolved, data


def _strict_json(data: bytes, *, where: str) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise CampaignError(f"duplicate field in {where}")
            result[key] = value
        return result

    try:
        value = json.loads(data, object_pairs_hook=unique)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CampaignError(f"{where} is not strict JSON") from exc
    if not isinstance(value, dict):
        raise CampaignError(f"{where} is not an object")
    return value


def _schema(repo_root: Path) -> dict[str, Any]:
    relative = "schema/research_campaign.schema.json"
    _path, data = _read_regular(repo_root, relative, limit=MAX_MANIFEST_BYTES)
    return _strict_json(data, where="campaign schema")


def validate_campaign(
    value: dict[str, Any],
    *,
    repo_root: Path = REPO_ROOT,
) -> None:
    """Validate structure, derived hashes, uniqueness, and referenced files."""
    try:
        validator = jsonschema.Draft202012Validator(
            _schema(repo_root),
            format_checker=jsonschema.FormatChecker(),
        )
        errors = sorted(
            validator.iter_errors(value),
            key=lambda error: list(error.path),
        )
    except jsonschema.SchemaError as exc:
        raise CampaignError("research campaign schema is invalid") from exc
    if errors:
        raise CampaignError(
            f"research campaign fails schema: {errors[0].message} "
            f"at {list(errors[0].absolute_path)}"
        )

    question = value["research_question"]
    if _sha256(question["text"].encode("utf-8")) != question["text_sha256"]:
        raise CampaignError("research question hash differs")
    topics = value["topic_policy"]["topics"]
    topic_ids = [topic["topic_id"] for topic in topics]
    if len(topic_ids) != len(set(topic_ids)):
        raise CampaignError("campaign topic ids are duplicated")
    topic_texts = [topic["text"] for topic in topics]
    if len(topic_texts) != len(set(topic_texts)):
        raise CampaignError("campaign topic texts are duplicated")
    topic_hashes = [topic["text_sha256"] for topic in topics]
    if len(topic_hashes) != len(set(topic_hashes)):
        raise CampaignError("campaign topic hashes are duplicated")
    for topic in topics:
        if _sha256(topic["text"].encode("utf-8")) != topic["text_sha256"]:
            raise CampaignError(f"campaign topic hash differs for {topic['topic_id']}")

    studies = value["study_manifests"]
    study_ids = [study["study_id"] for study in studies]
    if len(study_ids) != len(set(study_ids)):
        raise CampaignError("campaign study ids are duplicated")
    for study in studies:
        _manifest_path, manifest_bytes = _read_regular(
            repo_root,
            study["path"],
            limit=MAX_REFERENCED_BYTES,
        )
        if _sha256(manifest_bytes) != study["sha256"]:
            raise CampaignError(f"study manifest hash differs for {study['study_id']}")
        study_manifest = _strict_json(
            manifest_bytes,
            where=f"study manifest {study['study_id']}",
        )
        if (
            study_manifest.get("campaign_id") != value["campaign_id"]
            or study_manifest.get("study_id") != study["study_id"]
        ):
            raise CampaignError(
                f"study manifest identity differs for {study['study_id']}"
            )
        _prereg_path, prereg_bytes = _read_regular(
            repo_root,
            study["preregistration_path"],
            limit=MAX_REFERENCED_BYTES,
        )
        if _sha256(prereg_bytes) != study["preregistration_sha256"]:
            raise CampaignError(
                f"study preregistration hash differs for {study['study_id']}"
            )

    admitted = set(value["campaign_actions"]["admitted"])
    deferred = set(value["campaign_actions"]["deferred"])
    if admitted & deferred or admitted | deferred != {
        "run_loop_iteration",
        "promote_findings",
        "bubble_up",
        "noop",
        "run_experiment",
        "forecast_markets",
        "mine_paper_gap",
        "refine_idea",
        "improve_system",
    }:
        raise CampaignError("campaign action partition is incomplete or overlapping")


def load_campaign(
    campaign_id: str = DEFAULT_CAMPAIGN_ID,
    *,
    repo_root: Path = REPO_ROOT,
    registry: Mapping[str, str] = CAMPAIGN_MANIFESTS,
) -> dict[str, Any]:
    """Load one registered immutable campaign with private derived metadata."""
    relative = registry.get(campaign_id)
    if relative is None:
        raise CampaignError(f"unknown research campaign {campaign_id!r}")
    path, data = _read_regular(repo_root, relative, limit=MAX_MANIFEST_BYTES)
    value = _strict_json(data, where="campaign manifest")
    validate_campaign(value, repo_root=repo_root)
    if value.get("campaign_id") != campaign_id:
        raise CampaignError("campaign registry key and manifest identity differ")
    result = copy.deepcopy(value)
    result["_manifest_sha256"] = _sha256(data)
    result["_path"] = path
    return result


def public_campaign(campaign: dict[str, Any]) -> dict[str, Any]:
    """Return the manifest without loader-private filesystem metadata."""
    return copy.deepcopy(
        {key: value for key, value in campaign.items() if not key.startswith("_")}
    )


def _activation_schema(repo_root: Path) -> dict[str, Any]:
    _path, data = _read_regular(
        repo_root,
        "schema/research_campaign_activation.schema.json",
        limit=MAX_MANIFEST_BYTES,
    )
    return _strict_json(data, where="campaign activation schema")


def _closure_schema(repo_root: Path) -> dict[str, Any]:
    _path, data = _read_regular(
        repo_root,
        "schema/research_campaign_closure.schema.json",
        limit=MAX_MANIFEST_BYTES,
    )
    return _strict_json(data, where="campaign closure schema")


def _read_activation(path: Path) -> bytes:
    """Read the fixed pointer path with a hard byte bound and no redirects."""
    try:
        if path.is_symlink():
            raise CampaignError("campaign activation pointer is redirected")
        stat = path.stat()
        if not path.is_file() or stat.st_size > MAX_MANIFEST_BYTES:
            raise CampaignError("campaign activation pointer is not a bounded file")
        with path.open("rb") as handle:
            data = handle.read(MAX_MANIFEST_BYTES + 1)
    except CampaignError:
        raise
    except OSError as exc:
        raise CampaignError(
            "campaign activation pointer cannot be read safely"
        ) from exc
    if len(data) > MAX_MANIFEST_BYTES:
        raise CampaignError("campaign activation pointer exceeds its read bound")
    return data


def load_active_campaign(
    *,
    repo_root: Path = REPO_ROOT,
    activation_path: Path | None = None,
    env_campaign_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Resolve the single canonical runtime pointer, or the legacy mode.

    The environment variable can assert the expected active campaign but can
    never activate one by itself. A mismatch, malformed pointer, or changed
    manifest fails closed before any research/model action.
    """
    default_path = (
        DEFAULT_ACTIVATION_PATH
        if repo_root == REPO_ROOT
        else repo_root / "run_state" / "active_research_campaign.json"
    )
    path = activation_path or default_path
    env_value = (
        os.environ.get("NARA_RESEARCH_CAMPAIGN", "").strip()
        if env_campaign_id is None
        else env_campaign_id.strip()
    )
    # ``Path.exists`` follows links and would misclassify a dangling activation
    # symlink as an absent pointer, silently reopening the legacy cohort.
    if not os.path.lexists(path):
        if env_value:
            raise CampaignError(
                "NARA_RESEARCH_CAMPAIGN is set without an activation pointer"
            )
        return None
    canonical_path = repo_root / "run_state" / "active_research_campaign.json"
    if path == canonical_path:
        _resolved, activation_bytes = _read_regular(
            repo_root,
            "run_state/active_research_campaign.json",
            limit=MAX_MANIFEST_BYTES,
        )
    else:
        activation_bytes = _read_activation(path)
    value = _strict_json(
        activation_bytes,
        where="campaign activation pointer",
    )
    validator = jsonschema.Draft202012Validator(
        _activation_schema(repo_root),
        format_checker=jsonschema.FormatChecker(),
    )
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.path))
    if errors:
        raise CampaignError(
            f"campaign activation pointer fails schema: {errors[0].message}"
        )
    if env_value and env_value != value["campaign_id"]:
        raise CampaignError("campaign environment and activation pointer differ")
    campaign = load_campaign(value["campaign_id"], repo_root=repo_root)
    if value["campaign_manifest_sha256"] != campaign["_manifest_sha256"]:
        raise CampaignError("campaign activation pointer manifest hash differs")
    activation_time = _timestamp(value["activated_at"], where="campaign activation")
    opened_at = _timestamp(campaign["opened_at"], where="campaign opening")
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if activation_time < opened_at:
        raise CampaignError("campaign activation predates its immutable declaration")
    if activation_time > current_time + MAX_CLOCK_SKEW:
        raise CampaignError("campaign activation timestamp is in the future")

    closure_relative = (
        "run_state/research_campaign_closures/"
        f"{campaign['campaign_id']}.json"
    )
    closure_path = repo_root / closure_relative
    if os.path.lexists(closure_path):
        _closure_path, closure_bytes = _read_regular(
            repo_root,
            closure_relative,
            limit=MAX_MANIFEST_BYTES,
        )
        closure = _strict_json(closure_bytes, where="campaign closure receipt")
        closure_validator = jsonschema.Draft202012Validator(
            _closure_schema(repo_root),
            format_checker=jsonschema.FormatChecker(),
        )
        closure_errors = sorted(
            closure_validator.iter_errors(closure),
            key=lambda error: list(error.path),
        )
        if closure_errors:
            raise CampaignError(
                "campaign closure receipt fails schema: "
                f"{closure_errors[0].message}"
            )
        if (
            closure["campaign_id"] != campaign["campaign_id"]
            or closure["campaign_manifest_sha256"] != campaign["_manifest_sha256"]
        ):
            raise CampaignError("campaign closure receipt identity differs")
        closure_time = _timestamp(closure["closed_at"], where="campaign closure")
        if closure_time < activation_time:
            raise CampaignError("campaign closure predates activation")
        if closure_time > current_time + MAX_CLOCK_SKEW:
            raise CampaignError("campaign closure timestamp is in the future")
        raise CampaignError("research campaign is closed")
    result = copy.deepcopy(campaign)
    result["_activation"] = copy.deepcopy(value)
    return result


def ensure_active(campaign: dict[str, Any]) -> None:
    """Require the canonical activation pointer to bind this exact manifest."""
    active = load_active_campaign()
    if active is None or (active["campaign_id"], active["_manifest_sha256"]) != (
        campaign.get("campaign_id"),
        campaign.get("_manifest_sha256"),
    ):
        raise CampaignError("research campaign is not the active campaign")


def campaign_context(campaign: dict[str, Any]) -> dict[str, Any]:
    """Bounded public identity/policy projected into coordinator records."""
    question = campaign["research_question"]
    return {
        "schema_version": "research-campaign-context/v1",
        "campaign_id": campaign["campaign_id"],
        "title": campaign["title"],
        "status": campaign["status"],
        "opened_at": campaign["opened_at"],
        "campaign_manifest_sha256": campaign["_manifest_sha256"],
        "research_question": {
            "question_id": question["question_id"],
            "text": question["text"],
            "text_sha256": question["text_sha256"],
        },
        "campaign_actions": copy.deepcopy(campaign["campaign_actions"]),
    }


def bind_topic(campaign: dict[str, Any], topic_text: str) -> dict[str, str]:
    """Build an exact campaign link for a preregistered topic text."""
    if not isinstance(topic_text, str):
        raise CampaignError("campaign topic must be text")
    matches = [
        topic
        for topic in campaign["topic_policy"]["topics"]
        if topic["text"] == topic_text
    ]
    if len(matches) != 1:
        raise CampaignError("topic is not one exact preregistered campaign seed")
    topic = matches[0]
    question = campaign["research_question"]
    return {
        "schema_version": LINK_SCHEMA_VERSION,
        "campaign_id": campaign["campaign_id"],
        "campaign_manifest_sha256": campaign["_manifest_sha256"],
        "research_question_id": question["question_id"],
        "research_question_sha256": question["text_sha256"],
        "topic_id": topic["topic_id"],
        "topic_sha256": topic["text_sha256"],
    }


def classify_record(record: Any, campaign: dict[str, Any]) -> str:
    """Classify lineage without inferring membership from time or prose."""
    if not isinstance(record, dict):
        return "malformed_record"
    link = record.get("campaign")
    if link is None:
        return "unlinked_legacy"
    if (
        not isinstance(link, dict)
        or set(link) != LINK_FIELDS
        or not all(isinstance(value, str) for value in link.values())
    ):
        return "malformed_campaign_link"
    if link.get("campaign_id") != campaign["campaign_id"]:
        return "different_campaign"
    expected = [
        bind_topic(campaign, topic["text"])
        for topic in campaign["topic_policy"]["topics"]
    ]
    return (
        "explicit_match"
        if any(link == expected_link for expected_link in expected)
        else "campaign_link_mismatch"
    )


def record_matches(record: Any, campaign: dict[str, Any]) -> bool:
    return classify_record(record, campaign) == "explicit_match"


def unique_matching_records(
    records: list[dict[str, Any]],
    campaign: dict[str, Any],
    *,
    identity_field: str,
) -> list[dict[str, Any]]:
    """Return exact members whose non-empty identity is globally unique.

    Identity counts cover every source row, including legacy and other-campaign
    records. Otherwise an exact row could inherit feedback or near-miss data
    through an identifier that is ambiguous across cohorts.
    """
    counts: dict[str, int] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        identity = record.get(identity_field)
        if isinstance(identity, str) and identity:
            counts[identity] = counts.get(identity, 0) + 1
    return [
        record
        for record in records
        if record_matches(record, campaign)
        and isinstance(record.get(identity_field), str)
        and counts.get(record[identity_field]) == 1
    ]


def available_topics(
    campaign: dict[str, Any],
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Project exact seeds without replaying a topic already linked to a record."""
    completed = {
        record["campaign"]["topic_id"]
        for record in records
        if record_matches(record, campaign)
    }
    return [
        {
            "topic": topic["text"],
            "source": "campaign_preregistered",
            "campaign_id": campaign["campaign_id"],
            "topic_id": topic["topic_id"],
            "topic_sha256": topic["text_sha256"],
            "campaign": bind_topic(campaign, topic["text"]),
        }
        for topic in campaign["topic_policy"]["topics"]
        if topic["topic_id"] not in completed
    ]


__all__ = [
    "CAMPAIGN_MANIFESTS",
    "DEFAULT_ACTIVATION_PATH",
    "DEFAULT_CAMPAIGN_ID",
    "DEFAULT_CAMPAIGN_MANIFEST",
    "LINK_FIELDS",
    "LINK_SCHEMA_VERSION",
    "CampaignError",
    "available_topics",
    "bind_topic",
    "campaign_context",
    "classify_record",
    "ensure_active",
    "load_active_campaign",
    "load_campaign",
    "public_campaign",
    "record_matches",
    "unique_matching_records",
    "validate_campaign",
]
