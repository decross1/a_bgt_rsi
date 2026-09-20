import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from backend.daily_ops_agenda import read_pending_agenda

CREATED = "2098-09-20T06:16:10.891526Z"
EXPIRES = "2098-09-21T06:16:10.891526Z"
FOCUS_BEFORE = "2098-09-20T05:00:00Z"
FOCUS_AFTER = "2098-09-20T06:50:57Z"
AGENDA_ID = "oracle-manual-20980920T061610891526Z"


def _payload(task_count=3):
    return {
        "version": 1,
        "authority": "proposal_only",
        "objective": "Review a bounded proposal for the selected research thesis.",
        "workspace": "/home/tester/projects/a_bgt_rsi",
        "mode": "read",
        "context": {
            "context_sha256": "a" * 64,
            "release_sha256": "b" * 64,
            "schedule_slot": "manual-20980920T061610891526Z",
        },
        "model": {
            "endpoint": "http://127.0.0.1:30080/v1",
            "model_id": "nvidia/Qwen3.8-Flash-Next-NVFP4",
            "context_tokens": 32768,
            "max_output_tokens": 1024,
            "timeout_seconds": 180,
        },
        "budget": {
            "max_tasks": task_count,
            "max_turns": 6,
            "max_tool_calls": 12,
            "episode_seconds": 300,
        },
        "tasks": [
            {
                "id": f"task-{index + 1}",
                "title": f"Review task {index + 1}",
                "why_now": f"Reason {index + 1} is source-bound.",
                "artifact": f"Artifact {index + 1}",
                "validation": f"Validation {index + 1}",
                "owner": "Oracle" if index % 2 == 0 else "Codex",
            }
            for index in range(task_count)
        ],
    }


def _canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _revision(payload, *, agenda_id=AGENDA_ID, created=CREATED, expires=EXPIRES):
    envelope = {
        "version": 1,
        "agenda_id": agenda_id,
        "created_at": created,
        "expires_at": expires,
        "payload": payload,
    }
    return hashlib.sha256(_canonical(envelope)).hexdigest()


def _write_state(tmp_path: Path, *, payload=None, created=CREATED, expires=EXPIRES,
                 row_schema=1, latest_schema="oracle-daily-proposal-cycle/v1",
                 agenda_id=AGENDA_ID):
    payload = payload or _payload()
    revision = _revision(payload, agenda_id=agenda_id, created=created, expires=expires)
    root = tmp_path / "planner"
    database = root / "agendas" / "planning.sqlite3"
    database.parent.mkdir(parents=True)
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "CREATE TABLE agenda_proposals ("
            "agenda_id TEXT NOT NULL, revision_sha256 TEXT NOT NULL, "
            "payload_json TEXT NOT NULL, created_at TEXT NOT NULL, "
            "expires_at TEXT NOT NULL, envelope_sha256 TEXT NOT NULL, "
            "proposal_schema_version INTEGER NOT NULL, "
            "PRIMARY KEY (agenda_id, revision_sha256))"
        )
        connection.execute(
            "INSERT INTO agenda_proposals VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                agenda_id,
                revision,
                _canonical(payload).decode("ascii"),
                created,
                expires,
                revision,
                row_schema,
            ),
        )
        connection.commit()
    finally:
        connection.close()
    latest = root / "latest.json"
    latest.write_text(json.dumps({
        "schema_version": latest_schema,
        "status": "pending_owner_review",
        "execution_enabled": False,
        "owner_approval": "absent",
        "agenda_id": agenda_id,
        "revision_sha256": revision,
        "expires_at": expires.replace("Z", "+00:00"),
    }), encoding="utf-8")
    return latest, database, revision


def test_projects_one_exact_hash_verified_non_executable_decision(tmp_path):
    latest, _database, revision = _write_state(tmp_path)

    result = read_pending_agenda(latest, FOCUS_BEFORE)

    assert result["revision"] == revision
    assert result["warnings"] == []
    assert result["agenda_id"] == AGENDA_ID
    assert result["decision"] == {
        "id": f"agenda-{revision[:16]}",
        "agenda_id": AGENDA_ID,
        "revision": revision,
        "title": "Review the proposed research agenda",
        "what": "Review a bounded proposal for the selected research thesis.",
        "reason": (
            "The sealed proposal has not received an exact-revision semantic review. "
            "Review or request an amendment; no execution is available from this card."
        ),
        "disposition": "review_required",
        "approval_required": False,
        "approve_enabled": False,
        "execution_available": False,
        "actions": ["modify", "skip"],
        "task_titles": ["Review task 1", "Review task 2", "Review task 3"],
        "source": f"Oracle proposal {AGENDA_ID}; sealed revision {revision}",
        "observed_at": CREATED,
    }


def test_marks_proposal_created_before_focus_as_amend_required(tmp_path):
    latest, _database, revision = _write_state(tmp_path)

    result = read_pending_agenda(latest, FOCUS_AFTER)

    assert result["revision"] == revision
    assert result["warnings"] == []
    assert result["decision"]["disposition"] == "amend_required"
    assert result["decision"]["approve_enabled"] is False
    assert "predates the selected research focus" in result["decision"]["reason"]


def test_expired_proposal_has_no_revision_or_task_binding(tmp_path):
    latest, _database, _revision = _write_state(
        tmp_path,
        created="2020-09-20T06:16:10Z",
        expires="2020-09-21T06:16:10Z",
    )

    result = read_pending_agenda(latest, "2020-09-20T06:50:57Z")

    assert result["revision"] is None
    assert result["decision"] is None
    assert result["warnings"] == [
        (
            "Pending Oracle agenda expired at 2020-09-21T06:16:10Z; "
            "no plan revision or decision is active."
        )
    ]


def test_tampered_payload_fails_closed_without_touching_database(tmp_path):
    latest, database, _revision = _write_state(tmp_path)
    connection = sqlite3.connect(database)
    try:
        value = _payload()
        value["tasks"][0]["title"] = "Changed after sealing"
        connection.execute(
            "UPDATE agenda_proposals SET payload_json = ?",
            (_canonical(value).decode("ascii"),),
        )
        connection.commit()
    finally:
        connection.close()
    before = hashlib.sha256(database.read_bytes()).hexdigest()

    result = read_pending_agenda(latest, FOCUS_BEFORE)

    assert result == {
        "revision": None,
        "agenda_id": None,
        "decision": None,
        "warnings": [
            (
                "Pending Oracle agenda could not be verified; no plan revision or "
                "action binding is available."
            )
        ],
    }
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("mutation", [
    "row_schema",
    "latest_schema",
    "payload_schema",
])
def test_unknown_schema_fails_closed(tmp_path, mutation):
    kwargs = {}
    if mutation == "row_schema":
        kwargs["row_schema"] = 0
    elif mutation == "latest_schema":
        kwargs["latest_schema"] = "oracle-daily-proposal-cycle/v2"
    else:
        payload = _payload()
        payload["version"] = 2
        kwargs["payload"] = payload
    latest, _database, _revision = _write_state(tmp_path, **kwargs)

    result = read_pending_agenda(latest, FOCUS_BEFORE)

    assert result["revision"] is None
    assert result["decision"] is None
    assert result["warnings"] and "could not be verified" in result["warnings"][0]


def test_valid_seal_remains_readable_when_runtime_policy_fields_change(tmp_path):
    payload = _payload()
    payload["model"] = {
        "endpoint": "http://127.0.0.1:39999/v1",
        "model_id": "future-local-research-model",
        "context_tokens": 65536,
        "max_output_tokens": 4096,
        "timeout_seconds": 900,
    }
    payload["budget"] = {"future_policy": "owned-by-planner"}
    payload["new_informational_field"] = {"preserved_in_digest": True}
    latest, _database, revision = _write_state(tmp_path, payload=payload)

    result = read_pending_agenda(latest, FOCUS_BEFORE)

    assert result["revision"] == revision
    assert len(result["decision"]["task_titles"]) == 3
    assert result["warnings"] == []


def test_sqlite_source_and_projection_are_bounded(tmp_path):
    latest, database, _revision = _write_state(tmp_path, payload=_payload(task_count=5))

    projected = read_pending_agenda(latest, FOCUS_BEFORE)

    assert len(projected["decision"]["task_titles"]) == 3
    assert projected["warnings"] == [
        "Pending Oracle agenda contains 5 tasks; only the first 3 task titles are shown."
    ]

    with database.open("r+b") as stream:
        stream.truncate(8 * 1024 * 1024 + 1)
    rejected = read_pending_agenda(latest, FOCUS_BEFORE)
    assert rejected["revision"] is None
    assert rejected["decision"] is None
    assert "could not be verified" in rejected["warnings"][0]


def test_missing_latest_means_no_pending_agenda(tmp_path):
    assert read_pending_agenda(tmp_path / "missing.json", FOCUS_BEFORE) == {
        "agenda_id": None,
        "revision": None,
        "decision": None,
        "warnings": [],
    }
