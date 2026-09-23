import json
import os
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend import daily_ops_agents as agents_module
from backend import daily_ops_bridge as bridge_module
from backend.daily_ops_bridge import DailyOpsBridge

SESSION = "01a0bbce-8fe5-7290-8ea6-2f247da2115e"
WORKER_SESSION = "4143e484-35c9-497c-8edf-c01be99fb373"
NOW = datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc)
REVISION = "2026-09-20"
WORKER_DEADLINE = datetime(2026, 9, 20, 16, 2, 48, tzinfo=timezone.utc)
WORKER_ADMISSION_DEADLINE = WORKER_DEADLINE - timedelta(seconds=630)


def _iso(value=NOW):
    return value.isoformat().replace("+00:00", "Z")


def _private(path: Path):
    path.mkdir(parents=True, mode=0o700)
    path.chmod(0o700)
    return path


def _json(path: Path, value, *, mode=0o600):
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")
    path.chmod(mode)


def _install_plan(root: Path, items=None, name="2026-09-20.json"):
    """A daily plan of record in the real contract shape (docs/META_ORACLE_DAILY_LOOP.md §3)."""
    plans = root / "run_state" / "daily_plans"
    plans.mkdir(parents=True, exist_ok=True)
    plan = {
        "date": name[:10], "week_alignment": "G0 first.",
        "bottlenecks": [{"what": "Nothing selects the next focus.", "evidence": "x",
                         "cost_of_leaving_it": "y"}],
        "items": items or [
            {"id": "d1", "owner": "oracle", "lane": "oracle_dev", "goal": "G7.1",
             "repo": "a_bgt_rsi", "title": "Lane precheck", "why_today": "Retro finding.",
             "allowed_write_paths": ["orchestrator/nara_lane.py"], "acceptance": "Tests pass.",
             "depends_on": [], "flash_minutes": 10},
            {"id": "d2", "owner": "nara", "lane": "nara_dev", "goal": "G7.1",
             "repo": "a_bgt_rsi", "title": "Lab state packet", "why_today": "Stops drift.",
             "allowed_write_paths": ["tools/lab_state_packet.py"], "acceptance": "Tests pass.",
             "depends_on": ["d1"], "flash_minutes": 10},
        ],
    }
    (plans / name).write_text(json.dumps(plan))
    return plan


@pytest.fixture()
def relay(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge_module, "_now", lambda: NOW)
    _install_plan(tmp_path)
    state = _private(tmp_path / "state")
    private = _private(tmp_path / "private")
    mailbox = _private(tmp_path / "mailbox")
    for name in ("inbox", "processing", "processed", "failed", "outbox"):
        _private(mailbox / name)
    _json(private / "owner.key", "k" * 48)
    # _token expects the raw token rather than a JSON string.
    (private / "owner.key").write_text("k" * 48 + "\n", encoding="ascii")
    (private / "owner.key").chmod(0o600)
    _json(mailbox / "latest-status.json", {
        "schema_version": 1, "status": "active", "session_id": SESSION,
        "pending_count": 0, "updated_at": _iso(),
        "capabilities": {"review_scope": True, "durable_review_scope": True},
    })
    # The retired sealed-agenda path stays an accepted config key and is never read.
    planner = private / "planner.json"
    config = {
        "private_root": str(private), "mailbox_root": str(mailbox),
        "session_id": SESSION, "allowed_origins": ["http://10.0.0.73:5173"],
        "planner_latest": str(planner),
    }
    return {
        "bridge": DailyOpsBridge(state, config, process_lister=list, pi_sessions=tmp_path / "pi"), "state": state,
        "private": private, "mailbox": mailbox, "config": config,
    }


def _request(*, token="k" * 48, origin="http://10.0.0.73:5173"):
    headers = []
    if token is not None:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    return Request({"type": "http", "method": "POST", "path": "/api/daily-ops/messages",
                    "headers": headers, "query_string": b"", "server": ("test", 80),
                    "client": ("10.0.0.4", 4000), "scheme": "http"})


def _payload(*, request_id=None, text="What blocks the next gate?",
             intent="question", revision=None):
    value = {"request_id": request_id or str(uuid.uuid4()), "target": "oracle",
             "intent": intent, "text": text}
    if revision is not None:
        value["expected_plan_revision"] = revision
    return value


def _receipt(relay, request_id, *, status, text=None, mailbox=None, session_id=SESSION):
    value = {"schema_version": 1, "id": "owner-ui-" + request_id,
             "session_id": session_id, "status": status, "updated_at": _iso()}
    if text is not None:
        value["visible_final_text"] = text
    target = mailbox or relay["mailbox"]
    _json(target / "outbox" / ("owner-ui-" + request_id + ".json"), value)


def _bounded_relay(relay):
    mailbox = _private(relay["private"].parent / "bounded-mailbox")
    for name in ("inbox", "processing", "processed", "failed", "outbox", "review-drafts"):
        _private(mailbox / name)
    _json(mailbox / "latest-status.json", {
        "schema_version": 1, "status": "active", "session_id": WORKER_SESSION,
        "pending_count": 0, "updated_at": _iso(),
        "capabilities": {"review_scope": True, "durable_review_scope": True},
    })
    controller = _private(relay["private"].parent / "bounded-controller")
    status_path = controller / "ui-worker-status.json"
    _json(status_path, {
        "schema_version": "oracle-bounded-ui-worker-status/v1",
        "status": "ready", "admission_open": True, "updated_at": _iso(),
        "availability_ends_at": _iso(WORKER_DEADLINE),
        "admission_ends_at": _iso(WORKER_ADMISSION_DEADLINE),
        "session_id": WORKER_SESSION, "mailbox_root": str(mailbox),
        "summary_read_path": str(relay["state"] / "daily_ops_summary.json"),
        "instance_kind": "bounded_ui_responder",
        "responder_label": "Oracle bounded UI responder",
        "client_label": "Headless Pi client", "max_owner_turns": 12,
        "owner_turns_seen": 0, "turns_remaining": 12,
        "active_envelope_id": None, "reason": None,
    })
    config = {
        **relay["config"], "mailbox_root": str(mailbox), "session_id": WORKER_SESSION,
        "instance_kind": "bounded_ui_responder",
        "responder_label": "Oracle bounded UI responder",
        "client_label": "Headless Pi client",
        "availability_ends_at": _iso(WORKER_DEADLINE),
        "worker_status_path": str(status_path),
        "legacy_recipient": {
            "mailbox_root": str(relay["mailbox"]), "session_id": SESSION,
            "instance_kind": "canonical_oracle", "responder_label": "Oracle",
            "client_label": "Pi client",
        },
    }
    return {
        **relay, "bridge": DailyOpsBridge(relay["state"], config),
        "mailbox": mailbox, "worker_status": status_path, "config": config,
    }


def _force_refresh(relay):
    relay["bridge"]._last_refresh = 0.0
    relay["bridge"].refresh()
    return [json.loads(line) for line in
            (relay["state"] / "daily_ops_messages.jsonl").read_text().splitlines()]


def test_authorization_requires_exact_bearer_and_allowed_browser_origin(relay):
    bridge = relay["bridge"]
    assert bridge.authorize(_request()) is True
    assert bridge.authorize(_request(token="wrong" * 10)) is False
    assert bridge.authorize(_request(token=None)) is False
    assert bridge.authorize(_request(origin="http://evil.invalid")) is False
    # Non-browser local clients may omit Origin but still need the exact token.
    assert bridge.authorize(_request(origin=None)) is True


def test_route_writes_one_advisory_envelope_and_idempotent_duplicate(relay):
    payload = _payload()
    first = relay["bridge"].route(payload)
    second = relay["bridge"].route(payload)
    envelope_path = relay["mailbox"] / "inbox" / ("owner-ui-" + payload["request_id"] + ".json")
    envelope = json.loads(envelope_path.read_text())

    assert first == {"request_id": payload["request_id"], "status": "queued",
                     "accepted_at": _iso(), "duplicate": False,
                     "expected_plan_revision": None}
    assert second["duplicate"] is True
    assert envelope["authority"] == "advisory_only"
    assert envelope["approval_required"] is False
    assert envelope["session_id"] == SESSION
    assert payload["text"] in envelope["text"]
    assert envelope["review_scope"] == {
        "read_paths": [str(relay["state"] / "daily_ops_summary.json")],
        "draft_path": str(relay["mailbox"] / "review-drafts" / ("owner-ui-" + payload["request_id"] + ".md")),
    }
    assert len(list((relay["mailbox"] / "inbox").glob("*.json"))) == 1


def test_refresh_projects_the_live_plan_not_the_retired_curated_sources(relay):
    # Retired hand-curated sources may still exist on disk; none of them is read.
    _json(relay["state"] / "daily_ops_brief.json", {"schema_version": "daily-ops-summary/v1"})
    _json(relay["state"] / "daily_ops_work_plan.json", {"cards": []})

    relay["bridge"].refresh()
    summary = json.loads((relay["state"] / "daily_ops_summary.json").read_text())

    assert summary["schema_version"] == "daily-ops-summary/v3"
    assert summary["generated_at"] == _iso()
    assert summary["current_plan_revision"] == REVISION
    assert summary["daily_plan"]["bottlenecks"] == ["Nothing selects the next focus."]
    assert summary["daily_plan"]["review"] is None
    assert [(i["id"], i["status"]) for i in summary["work_items"]] == [
        ("d1", "not_started"), ("d2", "not_started")]
    assert summary["research_focus"]["status"] == "none"
    assert not any("could not be verified" in warning for warning in summary["warnings"])
    assert "goals" not in summary and "work_cards" not in summary


def test_route_decision_queues_plan_bound_advice_and_is_idempotent(relay):
    payload = {
        "request_id": str(uuid.uuid4()), "target_kind": "agenda",
        "target_id": REVISION, "action": "modify",
        "expected_plan_revision": REVISION,
        "note": "Drop d2 until d1 merges.",
    }

    first = relay["bridge"].route_decision(payload)
    second = relay["bridge"].route_decision(payload)
    envelope = json.loads((
        relay["mailbox"] / "inbox" / ("owner-ui-" + payload["request_id"] + ".json")
    ).read_text())

    assert first == {
        "request_id": payload["request_id"], "status": "queued",
        "accepted_at": _iso(), "duplicate": False,
        "target_kind": "agenda", "target_id": REVISION,
        "action": "modify", "expected_plan_revision": REVISION,
        "execution_available": False,
    }
    assert second["duplicate"] is True
    assert envelope["authority"] == "advisory_only"
    assert envelope["approval_required"] is False
    assert f"Request a corrected draft for daily plan {REVISION}" in envelope["text"]
    assert "do not treat it as approval" in envelope["text"]
    assert f"bound to plan revision {REVISION}" in envelope["text"]


def test_maximum_decision_note_fits_existing_message_and_envelope_bounds(relay):
    payload = {
        "request_id": str(uuid.uuid4()), "target_kind": "work_card",
        "target_id": "d2", "action": "modify",
        "expected_plan_revision": REVISION, "note": "x" * 3000,
    }

    receipt = relay["bridge"].route_decision(payload)

    assert receipt["status"] == "queued"
    envelope = json.loads((
        relay["mailbox"] / "inbox" / ("owner-ui-" + payload["request_id"] + ".json")
    ).read_text())
    assert "daily plan item d2" in envelope["text"]
    assert len(envelope["text"].encode("utf-8")) <= bridge_module.MAX_ENVELOPE_TEXT_BYTES


@pytest.mark.parametrize("mutation", [
    lambda value: value.update(expected_plan_revision="2026-09-19"),
    lambda value: value.update(target_id="d9"),
    lambda value: value.update(action="reprioritize", target_kind="agenda", priority="now"),
    lambda value: value.update(target_kind="agenda", target_id="2026-09-19"),
])
def test_route_decision_rejects_stale_or_unsupported_target_before_queue(
    relay, mutation,
):
    payload = {
        "request_id": str(uuid.uuid4()), "target_kind": "work_card",
        "target_id": "d1", "action": "skip",
        "expected_plan_revision": REVISION,
    }
    mutation(payload)

    with pytest.raises(HTTPException) as caught:
        relay["bridge"].route_decision(payload)

    assert caught.value.status_code in {409, 422}
    assert list((relay["mailbox"] / "inbox").glob("*.json")) == []
    assert list(relay["bridge"].requests.glob("*.json")) == []


def test_a_newer_plan_revision_retires_the_old_binding(relay, tmp_path):
    _install_plan(tmp_path, name="2026-09-20-r2.json")
    assert relay["bridge"]._plan_revision() == "2026-09-20-r2"
    with pytest.raises(HTTPException) as caught:
        relay["bridge"].route(_payload(intent="change_request", revision=REVISION))
    assert caught.value.status_code == 409
    (tmp_path / "run_state" / "daily_plans" / "2026-09-20-r2.json").write_text("{broken")
    assert relay["bridge"]._plan_revision() is None


def test_bounded_responder_requires_ready_empty_worker_and_projects_honest_identity(relay):
    bounded = _bounded_relay(relay)
    bounded["bridge"].refresh()
    summary = json.loads((bounded["state"] / "daily_ops_summary.json").read_text())

    assert summary["agents"]["oracle"]["label"] == "Oracle bounded UI responder"
    assert summary["agents"]["pi_client"]["label"] == "Headless Pi client"
    assert summary["agents"]["oracle"]["relay"]["source"] == (
        "Oracle bounded UI responder mailbox heartbeat"
    )
    assert "Temporary summary-only responder" in summary["agents"]["oracle"]["relay"]["detail"]
    assert _iso(WORKER_DEADLINE) in summary["agents"]["oracle"]["relay"]["detail"]

    worker_status = json.loads(bounded["worker_status"].read_text())
    worker_status.update(status="working", admission_open=False,
                         active_envelope_id="owner-ui-in-flight")
    _json(bounded["worker_status"], worker_status)
    bounded["bridge"]._last_refresh = 0.0
    bounded["bridge"].refresh()
    working_summary = json.loads((bounded["state"] / "daily_ops_summary.json").read_text())
    assert working_summary["agents"]["oracle"]["relay"]["status"] == "working"
    assert "new requests are paused" in working_summary["agents"]["oracle"]["relay"]["detail"]
    with pytest.raises(HTTPException) as caught:
        bounded["bridge"].route(_payload())
    assert caught.value.status_code == 503
    assert not list(bounded["bridge"].requests.glob("*.json"))

    worker_status.update(status="ready", admission_open=True,
                         active_envelope_id=None)
    _json(bounded["worker_status"], worker_status)
    heartbeat = json.loads((bounded["mailbox"] / "latest-status.json").read_text())
    heartbeat["pending_count"] = 1
    _json(bounded["mailbox"] / "latest-status.json", heartbeat)
    with pytest.raises(HTTPException) as caught:
        bounded["bridge"].route(_payload())
    assert caught.value.status_code == 503
    assert not list(bounded["bridge"].requests.glob("*.json"))


def test_bounded_responder_requires_explicit_canonical_legacy_binding(relay):
    bounded = _bounded_relay(relay)
    config = dict(bounded["config"])
    config.pop("legacy_recipient")

    with pytest.raises(ValueError, match="identity and availability"):
        DailyOpsBridge(relay["state"], config)


def test_bounded_responder_binds_history_to_accepting_mailbox_across_route_switch(relay):
    bounded = _bounded_relay(relay)
    payload = _payload()
    bounded["bridge"].route(payload)
    envelope = bounded["mailbox"] / "inbox" / ("owner-ui-" + payload["request_id"] + ".json")
    admission = bounded["mailbox"] / "admission" / envelope.name
    assert admission.read_bytes() == envelope.read_bytes()
    assert admission.stat().st_mode & 0o777 == 0o600
    envelope_value = json.loads(envelope.read_text())
    assert "You are the temporary Oracle bounded UI responder" in envelope_value["text"]
    assert "summary-only context" in envelope_value["text"]
    assert "no more than 200 words" in envelope_value["text"]
    assert "do not claim the memory or authority of canonical" in envelope_value["text"]
    record = json.loads((bounded["bridge"].requests / (payload["request_id"] + ".json")).read_text())
    assert record["recipient"] == {
        "mailbox_root": str(bounded["mailbox"]),
        "session_id": WORKER_SESSION,
        "instance_kind": "bounded_ui_responder",
        "responder_label": "Oracle bounded UI responder",
        "client_label": "Headless Pi client",
    }
    _receipt(bounded, payload["request_id"], status="completed",
             text="The bounded summary identifies the next gate.",
             mailbox=bounded["mailbox"], session_id=WORKER_SESSION)

    canonical = DailyOpsBridge(relay["state"], relay["config"])
    canonical.refresh()
    summary = json.loads((relay["state"] / "daily_ops_summary.json").read_text())
    rows = [json.loads(line) for line in
            (relay["state"] / "daily_ops_messages.jsonl").read_text().splitlines()]
    reply = next(row for row in rows if row.get("in_reply_to") == payload["request_id"])

    assert summary["agents"]["oracle"]["label"] == "Oracle"
    assert reply["actor"] == "oracle"
    assert reply["responder_label"] == "Oracle bounded UI responder"
    assert reply["text"] == "The bounded summary identifies the next gate."


def test_bounded_duplicate_requires_exact_immutable_admission_envelope(relay):
    bounded = _bounded_relay(relay)
    payload = _payload()
    bounded["bridge"].route(payload)
    admission = (bounded["mailbox"] / "admission" /
                 ("owner-ui-" + payload["request_id"] + ".json"))
    admission.write_bytes(admission.read_bytes() + b" ")

    with pytest.raises(HTTPException) as caught:
        bounded["bridge"].route(payload)
    assert caught.value.status_code == 503
    assert "admission does not match" in caught.value.detail


def test_bounded_publication_never_exposes_temp_files_in_scanned_queues(relay, monkeypatch):
    bounded = _bounded_relay(relay)
    observed = []
    real_fsync = bridge_module.os.fsync

    def observe_fsync(fd):
        observed.append({
            directory: sorted(path.name for path in (bounded["mailbox"] / directory).iterdir())
            for directory in ("admission", "inbox")
        })
        return real_fsync(fd)

    monkeypatch.setattr(bridge_module.os, "fsync", observe_fsync)
    payload = _payload()
    bounded["bridge"].route(payload)

    assert observed
    assert all(
        not any(name.startswith(".") for name in snapshot[directory])
        for snapshot in observed for directory in ("admission", "inbox")
    )
    assert not list((bounded["mailbox"] / ".relay-staging").iterdir())


def test_delivered_duplicate_after_route_switch_acknowledges_without_requeue(relay):
    bounded = _bounded_relay(relay)
    payload = _payload()
    bounded["bridge"].route(payload)
    worker_envelope = bounded["mailbox"] / "inbox" / ("owner-ui-" + payload["request_id"] + ".json")
    original = worker_envelope.read_bytes()
    admission = bounded["mailbox"] / "admission" / worker_envelope.name
    worker_envelope.unlink()
    _receipt(
        bounded, payload["request_id"], status="completed",
        text="The bounded response was delivered.", mailbox=bounded["mailbox"],
        session_id=WORKER_SESSION,
    )

    canonical = DailyOpsBridge(relay["state"], relay["config"])
    duplicate = canonical.route(payload)

    assert duplicate["duplicate"] is True
    assert admission.read_bytes() == original
    assert not worker_envelope.exists()
    assert not (relay["mailbox"] / "inbox" / worker_envelope.name).exists()


def test_archive_only_duplicate_never_requeues_to_inactive_bounded_route(relay):
    bounded = _bounded_relay(relay)
    payload = _payload()
    bounded["bridge"].route(payload)
    name = "owner-ui-" + payload["request_id"] + ".json"
    archive = bounded["mailbox"] / "admission" / name
    original = archive.read_bytes()
    (bounded["mailbox"] / "inbox" / name).unlink()

    canonical = DailyOpsBridge(relay["state"], relay["config"])
    with pytest.raises(HTTPException) as caught:
        canonical.route(payload)

    assert caught.value.status_code == 409
    assert "inactive responder" in caught.value.detail
    assert archive.read_bytes() == original
    assert not (bounded["mailbox"] / "inbox" / name).exists()


def test_duplicate_without_evidence_never_requeues_to_inactive_bounded_route(relay):
    bounded = _bounded_relay(relay)
    payload = _payload()
    bounded["bridge"].route(payload)
    name = "owner-ui-" + payload["request_id"] + ".json"
    (bounded["mailbox"] / "inbox" / name).unlink()
    (bounded["mailbox"] / "admission" / name).unlink()

    canonical = DailyOpsBridge(relay["state"], relay["config"])
    with pytest.raises(HTTPException) as caught:
        canonical.route(payload)

    assert caught.value.status_code == 409
    assert "inactive responder" in caught.value.detail
    assert not (bounded["mailbox"] / "inbox" / name).exists()
    assert not (relay["mailbox"] / "inbox" / name).exists()


def test_archive_only_duplicate_republishes_inbox_for_current_ready_responder(relay):
    bounded = _bounded_relay(relay)
    payload = _payload()
    bounded["bridge"].route(payload)
    name = "owner-ui-" + payload["request_id"] + ".json"
    archive = bounded["mailbox"] / "admission" / name
    original = archive.read_bytes()
    original_stat = archive.stat()
    (bounded["mailbox"] / "inbox" / name).unlink()

    duplicate = bounded["bridge"].route(payload)

    assert duplicate["duplicate"] is True
    assert (bounded["mailbox"] / "inbox" / name).read_bytes() == original
    assert archive.read_bytes() == original
    assert (archive.stat().st_ino, archive.stat().st_mtime_ns) == (
        original_stat.st_ino, original_stat.st_mtime_ns,
    )


def test_claim_window_duplicate_does_not_publish_second_inbox_copy(relay):
    bounded = _bounded_relay(relay)
    payload = _payload()
    bounded["bridge"].route(payload)
    name = "owner-ui-" + payload["request_id"] + ".json"
    inbox = bounded["mailbox"] / "inbox" / name
    claim = bounded["mailbox"] / "processing" / (
        name + ".1234.aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa.claim"
    )
    inbox.rename(claim)
    original = claim.read_bytes()

    duplicate = bounded["bridge"].route(payload)

    assert duplicate["duplicate"] is True
    assert claim.read_bytes() == original
    assert not inbox.exists()


@pytest.mark.parametrize("phase", ["dispatched", "active"])
def test_marker_only_duplicate_does_not_publish_second_inbox_copy(relay, phase):
    bounded = _bounded_relay(relay)
    payload = _payload()
    bounded["bridge"].route(payload)
    name = "owner-ui-" + payload["request_id"] + ".json"
    inbox = bounded["mailbox"] / "inbox" / name
    envelope = json.loads(inbox.read_text())
    inbox.unlink()
    _json(bounded["mailbox"] / "active-review-scope.json", {
        "schema_version": 1, "session_id": WORKER_SESSION,
        "envelope_id": envelope["id"], "kind": envelope["kind"],
        "phase": phase, "review_scope": envelope["review_scope"],
    })

    duplicate = bounded["bridge"].route(payload)

    assert duplicate["duplicate"] is True
    assert not inbox.exists()


def test_duplicate_without_evidence_requeues_only_to_current_ready_bounded_route(relay):
    bounded = _bounded_relay(relay)
    payload = _payload()
    bounded["bridge"].route(payload)
    name = "owner-ui-" + payload["request_id"] + ".json"
    original = (bounded["mailbox"] / "admission" / name).read_bytes()
    (bounded["mailbox"] / "inbox" / name).unlink()
    (bounded["mailbox"] / "admission" / name).unlink()

    duplicate = bounded["bridge"].route(payload)

    assert duplicate["duplicate"] is True
    assert (bounded["mailbox"] / "admission" / name).read_bytes() == original
    assert (bounded["mailbox"] / "inbox" / name).read_bytes() == original


def test_bounded_responder_rejects_stale_or_expired_controller_status(relay, monkeypatch):
    bounded = _bounded_relay(relay)
    worker_status = json.loads(bounded["worker_status"].read_text())
    worker_status["updated_at"] = _iso(NOW - timedelta(seconds=31))
    _json(bounded["worker_status"], worker_status)
    with pytest.raises(HTTPException) as stale:
        bounded["bridge"].route(_payload())
    assert stale.value.status_code == 503

    worker_status["updated_at"] = _iso()
    _json(bounded["worker_status"], worker_status)
    monkeypatch.setattr(bridge_module, "_now", lambda: WORKER_DEADLINE)
    with pytest.raises(HTTPException) as expired:
        bounded["bridge"].route(_payload())
    assert expired.value.status_code == 503


def test_bounded_responder_closes_admission_without_full_turn_budget(relay, monkeypatch):
    bounded = _bounded_relay(relay)
    worker_status = json.loads(bounded["worker_status"].read_text())
    worker_status["updated_at"] = _iso(WORKER_ADMISSION_DEADLINE)
    _json(bounded["worker_status"], worker_status)
    heartbeat = json.loads((bounded["mailbox"] / "latest-status.json").read_text())
    heartbeat["updated_at"] = _iso(WORKER_ADMISSION_DEADLINE)
    _json(bounded["mailbox"] / "latest-status.json", heartbeat)
    monkeypatch.setattr(bridge_module, "_now", lambda: WORKER_ADMISSION_DEADLINE)

    with pytest.raises(HTTPException) as caught:
        bounded["bridge"].route(_payload())
    assert caught.value.status_code == 503
    assert "full turn and cleanup" in caught.value.detail
    assert not list(bounded["bridge"].requests.glob("*.json"))

    bounded["bridge"]._last_refresh = 0.0
    bounded["bridge"].refresh()
    summary = json.loads((bounded["state"] / "daily_ops_summary.json").read_text())
    assert summary["agents"]["oracle"]["relay"]["status"] == "waiting"
    assert "no longer has time for a full owner turn" in summary["agents"]["oracle"]["relay"]["detail"]


def test_bounded_duplicate_replay_requires_full_turn_budget(relay, monkeypatch):
    bounded = _bounded_relay(relay)
    payload = _payload()
    bounded["bridge"].route(payload)
    name = "owner-ui-" + payload["request_id"] + ".json"
    (bounded["mailbox"] / "inbox" / name).unlink()
    (bounded["mailbox"] / "admission" / name).unlink()
    record_path = bounded["bridge"].requests / (payload["request_id"] + ".json")
    record = json.loads(record_path.read_text())
    record["expires_at"] = _iso(WORKER_DEADLINE)
    _json(record_path, record)

    worker_status = json.loads(bounded["worker_status"].read_text())
    worker_status["updated_at"] = _iso(WORKER_ADMISSION_DEADLINE)
    _json(bounded["worker_status"], worker_status)
    heartbeat = json.loads((bounded["mailbox"] / "latest-status.json").read_text())
    heartbeat["updated_at"] = _iso(WORKER_ADMISSION_DEADLINE)
    _json(bounded["mailbox"] / "latest-status.json", heartbeat)
    monkeypatch.setattr(bridge_module, "_now", lambda: WORKER_ADMISSION_DEADLINE)

    with pytest.raises(HTTPException) as caught:
        bounded["bridge"].route(payload)
    assert caught.value.status_code == 503
    assert "full turn and cleanup" in caught.value.detail
    assert not (bounded["mailbox"] / "admission" / name).exists()
    assert not (bounded["mailbox"] / "inbox" / name).exists()


def test_fresh_admission_rechecks_cutoff_before_first_durable_write(relay, monkeypatch):
    bounded = _bounded_relay(relay)
    before_cutoff = WORKER_ADMISSION_DEADLINE - timedelta(microseconds=1)
    worker_status = json.loads(bounded["worker_status"].read_text())
    worker_status["updated_at"] = _iso(before_cutoff - timedelta(seconds=1))
    _json(bounded["worker_status"], worker_status)
    heartbeat = json.loads((bounded["mailbox"] / "latest-status.json").read_text())
    heartbeat["updated_at"] = _iso(before_cutoff - timedelta(seconds=1))
    _json(bounded["mailbox"] / "latest-status.json", heartbeat)
    clock = iter((before_cutoff, WORKER_ADMISSION_DEADLINE))
    monkeypatch.setattr(bridge_module, "_now", lambda: next(clock))
    payload = _payload()

    with pytest.raises(HTTPException) as caught:
        bounded["bridge"].route(payload)
    assert caught.value.status_code == 503
    assert "full turn and cleanup" in caught.value.detail
    name = "owner-ui-" + payload["request_id"] + ".json"
    assert not (bounded["bridge"].requests / (payload["request_id"] + ".json")).exists()
    assert not (bounded["mailbox"] / "admission" / name).exists()
    assert not (bounded["mailbox"] / "inbox" / name).exists()


def test_archive_replay_rechecks_cutoff_before_inbox_publication(relay, monkeypatch):
    bounded = _bounded_relay(relay)
    payload = _payload()
    bounded["bridge"].route(payload)
    name = "owner-ui-" + payload["request_id"] + ".json"
    inbox = bounded["mailbox"] / "inbox" / name
    inbox.unlink()
    record_path = bounded["bridge"].requests / (payload["request_id"] + ".json")
    record = json.loads(record_path.read_text())
    record["expires_at"] = _iso(WORKER_DEADLINE)
    _json(record_path, record)

    before_cutoff = WORKER_ADMISSION_DEADLINE - timedelta(microseconds=1)
    worker_status = json.loads(bounded["worker_status"].read_text())
    worker_status["updated_at"] = _iso(before_cutoff - timedelta(seconds=1))
    _json(bounded["worker_status"], worker_status)
    heartbeat = json.loads((bounded["mailbox"] / "latest-status.json").read_text())
    heartbeat["updated_at"] = _iso(before_cutoff - timedelta(seconds=1))
    _json(bounded["mailbox"] / "latest-status.json", heartbeat)
    clock = iter((before_cutoff, WORKER_ADMISSION_DEADLINE))
    monkeypatch.setattr(bridge_module, "_now", lambda: next(clock))

    with pytest.raises(HTTPException) as caught:
        bounded["bridge"].route(payload)
    assert caught.value.status_code == 503
    assert "full turn and cleanup" in caught.value.detail
    assert not inbox.exists()


def test_bounded_responder_closes_double_post_race_until_terminal_receipt(relay):
    bounded = _bounded_relay(relay)
    first = _payload()
    second = _payload()

    accepted = bounded["bridge"].route(first)
    assert accepted["duplicate"] is False

    # The controller and extension status files have intentionally not moved
    # yet.  The bridge's own durable request record closes this observation
    # gap so another request cannot enter the one-active-turn worker.
    with pytest.raises(HTTPException) as caught:
        bounded["bridge"].route(second)
    assert caught.value.status_code == 503
    assert "unresolved owner request" in caught.value.detail
    assert not (bounded["bridge"].requests / (second["request_id"] + ".json")).exists()
    assert not (bounded["mailbox"] / "inbox" /
                ("owner-ui-" + second["request_id"] + ".json")).exists()

    retry = bounded["bridge"].route(first)
    assert retry["duplicate"] is True

    _receipt(bounded, first["request_id"], status="completed",
             text="The first bounded turn is complete.",
             mailbox=bounded["mailbox"], session_id=WORKER_SESSION)
    assert bounded["bridge"].route(second)["status"] == "queued"


def test_oversized_final_envelope_never_persists_or_poison_later_request(relay):
    bounded = _bounded_relay(relay)
    oversized = _payload(text="🧠" * 2_000)

    with pytest.raises(HTTPException) as caught:
        bounded["bridge"].route(oversized)
    assert caught.value.status_code == 422
    assert "envelope text byte limit" in caught.value.detail
    name = "owner-ui-" + oversized["request_id"] + ".json"
    assert not (bounded["bridge"].requests / (oversized["request_id"] + ".json")).exists()
    assert not (bounded["mailbox"] / "admission" / name).exists()
    assert not (bounded["mailbox"] / "inbox" / name).exists()

    valid = _payload(text="\\" * 4_096)
    receipt = bounded["bridge"].route(valid)
    assert receipt["status"] == "queued"
    assert (bounded["bridge"].requests / (valid["request_id"] + ".json")).exists()


@pytest.mark.parametrize("capabilities", [
    None,
    {"review_scope": True},
    {"durable_review_scope": True},
    {"review_scope": False, "durable_review_scope": True},
    {"review_scope": True, "durable_review_scope": False},
])
def test_owner_request_requires_scoped_and_durable_mailbox_enforcement(relay, capabilities):
    status_path = relay["mailbox"] / "latest-status.json"
    value = json.loads(status_path.read_text())
    if capabilities is None:
        value.pop("capabilities")
    else:
        value["capabilities"] = capabilities
    _json(status_path, value)
    with pytest.raises(HTTPException) as caught:
        relay["bridge"].route(_payload())
    assert caught.value.status_code == 503
    assert "update must be loaded" in caught.value.detail
    assert list(relay["bridge"].requests.iterdir()) == []
    assert list((relay["mailbox"] / "inbox").iterdir()) == []

    relay["bridge"]._last_refresh = 0.0
    relay["bridge"].refresh()
    summary = json.loads((relay["state"] / "daily_ops_summary.json").read_text())
    assert summary["agents"]["oracle"]["relay"]["status"] == "degraded"
    assert summary["agents"]["pi_client"]["relay"]["status"] == "degraded"
    assert "update must be loaded" in summary["agents"]["oracle"]["relay"]["detail"]


def test_same_request_id_with_changed_payload_conflicts(relay):
    payload = _payload()
    relay["bridge"].route(payload)
    with pytest.raises(HTTPException) as caught:
        relay["bridge"].route({**payload, "text": "different"})
    assert caught.value.status_code == 409


def test_change_request_is_bound_to_current_unexpired_revision(relay):
    payload = _payload(intent="change_request", revision="c" * 64)
    with pytest.raises(HTTPException) as caught:
        relay["bridge"].route(payload)
    assert caught.value.status_code == 409
    assert not list((relay["bridge"].requests).glob("*.json"))

    accepted = relay["bridge"].route({**payload, "expected_plan_revision": REVISION})
    assert accepted["expected_plan_revision"] == REVISION


def test_durable_request_without_envelope_is_replayed_exactly(relay):
    payload = _payload()
    relay["bridge"].route(payload)
    envelope = relay["mailbox"] / "inbox" / ("owner-ui-" + payload["request_id"] + ".json")
    original = envelope.read_bytes()
    envelope.unlink()

    receipt = relay["bridge"].route(payload)
    assert receipt["duplicate"] is True
    assert envelope.read_bytes() == original


def test_encoded_mailbox_limit_rejects_before_durable_request(relay):
    payload = _payload(text="🧠" * 4096)
    with pytest.raises(HTTPException) as caught:
        relay["bridge"].route(payload)
    assert caught.value.status_code == 422
    assert not (relay["bridge"].requests / (payload["request_id"] + ".json")).exists()
    assert not (relay["mailbox"] / "inbox" /
                ("owner-ui-" + payload["request_id"] + ".json")).exists()


@pytest.mark.parametrize(
    ("mailbox_status", "expected_status", "expected_actor", "expected_intent"),
    [
        ("submitted", "delivered", "system", "receipt"),
        ("running", "delivered", "system", "receipt"),
        ("dispatch_error", "failed", "system", "receipt"),
        ("processing_failed", "failed", "system", "receipt"),
    ],
)
def test_real_mailbox_states_project_without_inventing_completion(
    relay, mailbox_status, expected_status, expected_actor, expected_intent,
):
    payload = _payload()
    relay["bridge"].route(payload)
    _receipt(relay, payload["request_id"], status=mailbox_status)
    rows = _force_refresh(relay)
    response_rows = [row for row in rows if row.get("in_reply_to") == payload["request_id"]]
    assert len(response_rows) == 1
    assert response_rows[0]["status"] == expected_status
    assert response_rows[0]["actor"] == expected_actor
    assert response_rows[0]["intent"] == expected_intent
    assert "complete" not in response_rows[0]["text"].lower()


def test_dispatching_before_send_does_not_claim_delivery(relay):
    payload = _payload()
    relay["bridge"].route(payload)
    _receipt(relay, payload["request_id"], status="dispatching")
    rows = _force_refresh(relay)
    assert [row for row in rows if row.get("in_reply_to") == payload["request_id"]] == []


def test_completed_turn_requires_visible_answer_to_project_oracle_reply(relay):
    payload = _payload()
    relay["bridge"].route(payload)
    _receipt(relay, payload["request_id"], status="completed",
             text="The fresh replay is the next gate.")
    rows = _force_refresh(relay)
    reply = next(row for row in rows if row.get("in_reply_to") == payload["request_id"])
    assert (reply["actor"], reply["intent"], reply["status"]) == (
        "oracle", "reply", "acknowledged")
    assert reply["text"] == "The fresh replay is the next gate."


def test_completed_turn_without_visible_answer_is_delivery_only(relay):
    payload = _payload()
    relay["bridge"].route(payload)
    _receipt(relay, payload["request_id"], status="completed", text="")
    rows = _force_refresh(relay)
    receipt = next(row for row in rows if row.get("in_reply_to") == payload["request_id"])
    assert (receipt["actor"], receipt["intent"], receipt["status"]) == (
        "system", "receipt", "delivered")
    assert "No task completion is inferred" in receipt["text"]


def test_legacy_request_without_recipient_binding_uses_configured_target(relay):
    ident = str(uuid.uuid4())
    record = {
        "payload": _payload(request_id=ident), "accepted_at": _iso(),
        "expires_at": _iso(NOW + timedelta(hours=6)),
        "envelope_id": "owner-ui-" + ident,
    }
    _json(relay["bridge"].requests / (ident + ".json"), record)
    _receipt(relay, ident, status="completed", text="Legacy reply remains visible.")

    rows = _force_refresh(relay)
    reply = next(row for row in rows if row.get("in_reply_to") == ident)
    assert reply["responder_label"] == "Oracle"
    assert reply["text"] == "Legacy reply remains visible."


def test_bounded_route_keeps_legacy_history_bound_to_canonical_oracle(relay):
    ident = str(uuid.uuid4())
    record = {
        "payload": _payload(request_id=ident), "accepted_at": _iso(),
        "expires_at": _iso(NOW + timedelta(hours=6)),
        "envelope_id": "owner-ui-" + ident,
    }
    _json(relay["bridge"].requests / (ident + ".json"), record)
    _receipt(relay, ident, status="completed", text="Canonical history remains visible.")

    bounded = _bounded_relay(relay)
    rows = _force_refresh(bounded)
    owner = next(row for row in rows if row["request_id"] == ident)
    reply = next(row for row in rows if row.get("in_reply_to") == ident)

    assert owner["responder_label"] == "Oracle"
    assert reply["responder_label"] == "Oracle"
    assert reply["text"] == "Canonical history remains visible."


@pytest.mark.parametrize(
    ("status", "expected"),
    [("active", "idle"), ("running", "working"), ("processing_blocked", "degraded")],
)
def test_live_mailbox_states_are_observed_without_calling_work_offline(relay, status, expected):
    _json(relay["mailbox"] / "latest-status.json", {
        "schema_version": 1, "status": status, "session_id": SESSION,
        "pending_count": 1 if status != "active" else 0, "updated_at": _iso(),
        "capabilities": {"review_scope": True, "durable_review_scope": True},
    })
    relay["bridge"]._last_refresh = 0.0
    relay["bridge"].refresh()
    summary = json.loads((relay["state"] / "daily_ops_summary.json").read_text())
    assert summary["agents"]["oracle"]["relay"]["status"] == expected
    assert summary["agents"]["pi_client"]["relay"]["status"] == expected


def test_refresh_generated_at_is_the_projection_time_and_plan_keeps_its_own(relay, tmp_path):
    written = (NOW - timedelta(days=1)).timestamp()
    os.utime(tmp_path / "run_state" / "daily_plans" / "2026-09-20.json", (written, written))

    _force_refresh(relay)
    summary = json.loads((relay["state"] / "daily_ops_summary.json").read_text())

    assert summary["generated_at"] == _iso()
    assert summary["daily_plan"]["written_at"] == _iso(NOW - timedelta(days=1))
    assert summary["sources"]["plan"] == _iso(NOW - timedelta(days=1))
    assert summary["agents"]["nara"]["observed_at"] == _iso()


def test_running_mailbox_can_queue_but_processing_block_refuses(relay):
    _json(relay["mailbox"] / "latest-status.json", {
        "schema_version": 1, "status": "running", "session_id": SESSION,
        "pending_count": 1, "updated_at": _iso(),
        "capabilities": {"review_scope": True, "durable_review_scope": True},
    })
    queued = _payload()
    assert relay["bridge"].route(queued)["status"] == "queued"

    _json(relay["mailbox"] / "latest-status.json", {
        "schema_version": 1, "status": "processing_blocked", "session_id": SESSION,
        "pending_count": 1, "updated_at": _iso(),
        "capabilities": {"review_scope": True, "durable_review_scope": True},
    })
    blocked = _payload()
    with pytest.raises(HTTPException) as caught:
        relay["bridge"].route(blocked)
    assert caught.value.status_code == 503
    assert not (relay["bridge"].requests / (blocked["request_id"] + ".json")).exists()


def test_nara_observation_uses_fixed_systemd_query_and_cache(relay, monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, "active\n", "")

    monkeypatch.setattr(agents_module.subprocess, "run", run)
    first = relay["bridge"]._observe_nara()
    second = relay["bridge"]._observe_nara()
    assert first == second
    assert first["status"] == "online"
    assert calls == [([
        "/usr/bin/systemctl", "--user", "show", "nara-daemon.service",
        "--property=ActiveState", "--value",
    ], {"capture_output": True, "text": True, "timeout": 1, "check": False})]


def test_focus_comes_from_project_focus_and_its_failure_is_shown(relay, monkeypatch):
    from backend import daily_ops_live
    monkeypatch.setattr(daily_ops_live, "_project_focus", lambda repo: {
        "status": "selected", "focus_id": "fresh-focus", "title": "Fresh thesis",
        "stage": "needs_clean_refinement", "next_action": "Refine it.",
        "intake_policy": "focus_before_new_topics", "selected_at": "2026-09-20T08:00:00+00:00"})
    _force_refresh(relay)
    focus = json.loads((relay["state"] / "daily_ops_summary.json").read_text())["research_focus"]
    assert (focus["status"], focus["focus_id"], focus["intake_policy"]) == (
        "selected", "fresh-focus", "focus_before_new_topics")
    assert focus["selected_at"] == "2026-09-20T08:00:00Z"

    def broken(repo):
        raise RuntimeError("receipt hash differs")
    monkeypatch.setattr(daily_ops_live, "_project_focus", broken)
    _force_refresh(relay)
    focus = json.loads((relay["state"] / "daily_ops_summary.json").read_text())["research_focus"]
    assert focus["status"] == "source_invalid" and "receipt hash differs" in focus["reason"]


def test_projection_is_bounded_to_fifty_requests_and_one_hundred_rows(relay):
    requests = relay["bridge"].requests
    for ordinal in range(60):
        ident = str(uuid.UUID(int=ordinal + 1))
        record = {"payload": _payload(request_id=ident),
                  "accepted_at": _iso(NOW + timedelta(seconds=ordinal)),
                  "expires_at": _iso(NOW + timedelta(hours=6)),
                  "envelope_id": "owner-ui-" + ident}
        _json(requests / (ident + ".json"), record)
        _receipt(relay, ident, status="completed", text=f"reply {ordinal}")
    rows = _force_refresh(relay)
    assert len(rows) == 100
    owner_ids = {row["request_id"] for row in rows if row["actor"] == "owner"}
    assert len(owner_ids) == 50


def test_refresh_failure_after_durable_enqueue_does_not_turn_post_into_failure(relay, monkeypatch):
    payload = _payload()

    def fail_refresh():
        raise ValueError("projection source broke after enqueue")

    monkeypatch.setattr(relay["bridge"], "refresh", fail_refresh)
    receipt = relay["bridge"].route(payload)
    assert receipt["status"] == "queued"
    assert (relay["bridge"].requests / (payload["request_id"] + ".json")).exists()
    assert (relay["mailbox"] / "inbox" /
            ("owner-ui-" + payload["request_id"] + ".json")).exists()


def test_agent_cards_come_from_live_sources_and_the_relay_only_gates_messaging(relay, tmp_path):
    # A live oversight mailbox no longer makes the daily-loop Oracle look active.
    _force_refresh(relay)
    agents = json.loads((relay["state"] / "daily_ops_summary.json").read_text())["agents"]
    assert agents["oracle"]["relay"]["status"] == "idle"
    assert agents["oracle"]["status"] == "unknown"
    assert agents["pi_client"]["status"] == "offline"
    assert agents["meta_oracle"]["label"] == "Meta-oracle (Claude)"

    # A running daily-loop phase makes the card working even with the relay down.
    (tmp_path / "logs" / "oracle_daily").mkdir(parents=True)
    relay["bridge"]._process_lister = lambda: [{
        "pid": 9, "ppid": 1, "tty": 0, "cwd": "/",
        "argv": ["bash", "/x/scripts/oracle-daily", "work"]}]
    (relay["mailbox"] / "latest-status.json").unlink()
    _force_refresh(relay)
    agents = json.loads((relay["state"] / "daily_ops_summary.json").read_text())["agents"]
    assert agents["oracle"]["status"] == "working"
    assert agents["oracle"]["relay"]["status"] == "offline"
    assert agents["oracle"]["relay"]["detail"] == "Mailbox is unavailable or stale."
