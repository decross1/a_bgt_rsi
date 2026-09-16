import json
import os

import pytest

from backend.research_application_agenda import DEFAULT_PATH, project_agenda


def test_checked_in_agenda_is_proposed_not_execution_or_trading_evidence():
    projected = project_agenda()
    assert projected["available"]
    assert len(projected["source_sha256"]) == 64
    agenda = projected["agenda"]
    assert agenda["execution_authorized"] is False
    assert agenda["data_entitlement_verified"] is False
    assert agenda["lanes"][0]["id"] == "options"
    assert all(row["status"] == "proposed" for row in agenda["next_agenda"])


def test_invalid_or_missing_agenda_is_not_replaced_with_invented_progress(tmp_path):
    path = tmp_path / "agenda.json"
    assert project_agenda(path)["agenda"] is None
    data = json.loads(DEFAULT_PATH.read_text())
    data["execution_authorized"] = True
    path.write_text(json.dumps(data))
    projected = project_agenda(path)
    assert not projected["available"]
    assert projected["agenda"] is None
    assert projected["source_sha256"] is None


def test_redirected_and_oversized_agenda_refuse(tmp_path):
    path = tmp_path / "agenda.json"
    path.symlink_to(DEFAULT_PATH)
    assert not project_agenda(path)["available"]
    path.unlink()
    path.write_text(" " * 32_769)
    assert not project_agenda(path)["available"]


def _agenda():
    return json.loads(DEFAULT_PATH.read_text())


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda data: data.update(research_question={"not": "renderable text"}),
            id="top-level-display-object",
        ),
        pytest.param(
            lambda data: data.update(unregistered_payload="not in schema"),
            id="extra-top-level-field",
        ),
        pytest.param(
            lambda data: data.update(agenda_id="../unsafe"),
            id="unsafe-agenda-id",
        ),
        pytest.param(
            lambda data: data.pop("history_policy"),
            id="missing-top-level-field",
        ),
        pytest.param(
            lambda data: data["lanes"][0].update(label={"not": "text"}),
            id="lane-display-object",
        ),
        pytest.param(
            lambda data: data["lanes"][0]["requirements"].append({"not": "text"}),
            id="requirement-object",
        ),
        pytest.param(
            lambda data: data["lanes"][0].update(source_ids=["missing_source"]),
            id="dangling-source-id",
        ),
        pytest.param(
            lambda data: data["lanes"].reverse(),
            id="lane-order-drift",
        ),
        pytest.param(
            lambda data: data["next_agenda"][0].update(
                deliverable={"not": "renderable text"}
            ),
            id="next-step-display-object",
        ),
        pytest.param(
            lambda data: data["next_agenda"][0].update(id="../unsafe"),
            id="unsafe-next-step-id",
        ),
        pytest.param(
            lambda data: data["sources"][0].update(title={"not": "text"}),
            id="source-display-object",
        ),
        pytest.param(
            lambda data: data["sources"][0].update(url="javascript:alert(1)"),
            id="unsafe-source-url",
        ),
        pytest.param(
            lambda data: data["sources"][0].update(url="https://bad host.test/x"),
            id="whitespace-source-url",
        ),
        pytest.param(
            lambda data: data["sources"][1].update(id=data["sources"][0]["id"]),
            id="duplicate-source-id",
        ),
        pytest.param(
            lambda data: data["sources"][0].update(accessed_at="2026-02-30"),
            id="invalid-source-date",
        ),
        pytest.param(
            lambda data: data.update(recorded_at="2026-09-16T04:00:10"),
            id="timestamp-without-utc-zone",
        ),
        pytest.param(
            lambda data: data.update(research_question="x" * 4_097),
            id="oversized-display-text",
        ),
    ],
)
def test_malformed_nested_agenda_values_are_withheld(tmp_path, mutate):
    path = tmp_path / "agenda.json"
    data = _agenda()
    mutate(data)
    path.write_text(json.dumps(data))
    assert project_agenda(path)["agenda"] is None


def test_duplicate_keys_nonfinite_values_and_invalid_utf8_are_withheld(tmp_path):
    path = tmp_path / "agenda.json"
    raw = DEFAULT_PATH.read_text()
    agenda_id = '"agenda_id": "mechanism-led-applications-20260916"'
    path.write_text(raw.replace(agenda_id, f"{agenda_id},\n  {agenda_id}", 1))
    assert project_agenda(path)["agenda"] is None

    data = _agenda()
    data["owner_direction"] = float("nan")
    path.write_text(json.dumps(data))
    assert project_agenda(path)["agenda"] is None

    path.write_bytes(b"\xff\xfe")
    assert project_agenda(path)["agenda"] is None


def test_nonregular_agenda_source_is_withheld(tmp_path):
    path = tmp_path / "agenda.json"
    os.mkfifo(path)
    assert project_agenda(path)["available"] is False
