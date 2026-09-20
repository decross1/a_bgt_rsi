import json

import pytest

from backend.daily_ops_work_plan import read_work_plan

REVISION = "1" * 64
FOCUS = "2" * 64
NOW = "2026-09-20T15:30:00Z"


def _agenda():
    return {
        "agenda_id": "oracle-2026-09-20-0800-America_Los_Angeles",
        "revision": REVISION,
        "decision": {
            "id": f"agenda-{REVISION[:16]}",
            "agenda_id": "oracle-2026-09-20-0800-America_Los_Angeles",
            "revision": REVISION,
            "title": "Review the proposed research agenda",
            "what": "Review the sealed proposal.",
            "reason": "Semantic review has not been projected.",
            "disposition": "review_required",
            "approval_required": False,
            "approve_enabled": False,
            "execution_available": False,
            "actions": ["modify", "skip"],
            "task_titles": ["Old task one", "Old task two", "Old task three"],
            "source": "verified sealed proposal",
            "observed_at": NOW,
        },
        "warnings": [],
    }


def _card(ident, *, owner="codex", depends_on=None, score=9):
    return {
        "id": ident,
        "title": f"Card {ident}",
        "what": "Perform one bounded routine development step.",
        "benefit": "Closes an engineering gate without claiming scientific benefit.",
        "cost": {
            "summary": "Estimated 2–4 engineering hours; 0 model/GPU hours.",
            "kind": "estimate",
            "basis": "Reviewer planning estimate; not measured spend.",
        },
        "conviction": {
            "score": score,
            "kind": "estimate",
            "basis": "Worth-doing judgment, not a probability or scientific score.",
        },
        "worth_time": {
            "recommendation": "do_now" if not depends_on else "after_dependency",
            "basis": "The dependency order is explicit in the reviewed plan.",
        },
        "status": "authorized",
        "owner": owner,
        "depends_on": depends_on or [],
    }


def _plan():
    return {
        "schema_version": "daily-ops-work-plan/v1",
        "agenda_id": _agenda()["agenda_id"],
        "revision": REVISION,
        "focus_receipt_sha256": FOCUS,
        "observed_at": NOW,
        "disposition": "amend_required",
        "decision_title": "Correction needed before agenda review",
        "decision_summary": "Request a corrected replacement for the stale proposal.",
        "decision_reason": "Two sealed tasks are unrelated or use inherited evidence.",
        "source": "exact-revision semantic and owner-card review",
        "cards": [
            _card("runner"),
            _card("replay", depends_on=["runner"]),
            _card("shakedown", owner="oracle", depends_on=["replay"], score=8),
        ],
    }


def _write(tmp_path, value):
    path = tmp_path / "daily_ops_work_plan.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_projects_three_focus_and_revision_bound_routine_cards(tmp_path):
    result = read_work_plan(
        _write(tmp_path, _plan()), agenda=_agenda(), focus_receipt_sha256=FOCUS,
    )

    assert result["warnings"] == []
    assert [card["id"] for card in result["work_cards"]] == [
        "runner", "replay", "shakedown",
    ]
    first = result["work_cards"][0]
    assert first["approval_required"] is False
    assert first["actions"] == ["modify", "skip", "reprioritize"]
    assert first["conviction"] == {
        "score": 9, "kind": "estimate",
        "basis": "Worth-doing judgment, not a probability or scientific score.",
    }
    assert result["work_cards"][2]["depends_on"] == ["replay"]
    decision = result["agenda_decision"]
    assert decision["revision"] == REVISION
    assert decision["disposition"] == "amend_required"
    assert decision["approval_required"] is False
    assert decision["approve_enabled"] is False
    assert decision["execution_available"] is False
    assert decision["actions"] == ["modify", "skip"]


@pytest.mark.parametrize("field,value", [
    ("revision", "3" * 64),
    ("focus_receipt_sha256", "4" * 64),
    ("agenda_id", "different-agenda"),
])
def test_mismatched_curated_source_never_survives_revision_or_focus_change(
    tmp_path, field, value,
):
    plan = _plan()
    plan[field] = value
    agenda = _agenda()

    result = read_work_plan(
        _write(tmp_path, plan), agenda=agenda, focus_receipt_sha256=FOCUS,
    )

    assert result["work_cards"] == []
    assert result["agenda_decision"] == agenda["decision"]
    assert result["warnings"] == [
        "Reviewed daily work cards do not match the current agenda and research focus; they were not shown."
    ]


@pytest.mark.parametrize("mutation", [
    lambda plan: plan["cards"][0]["conviction"].update(score=90),
    lambda plan: plan["cards"][0]["conviction"].update(
        score=9, kind="unrated",
    ),
    lambda plan: plan["cards"][0].update(depends_on=["later"]),
    lambda plan: plan["cards"].append(_card("fourth")),
    lambda plan: plan["cards"][0]["cost"].update(kind="guess"),
])
def test_invalid_or_unordered_estimates_fail_closed(tmp_path, mutation):
    plan = _plan()
    mutation(plan)

    result = read_work_plan(
        _write(tmp_path, plan), agenda=_agenda(), focus_receipt_sha256=FOCUS,
    )

    assert result["work_cards"] == []
    assert result["agenda_decision"]["disposition"] == "review_required"
    assert result["agenda_decision"]["approve_enabled"] is False


def test_missing_curated_plan_is_honest_unrated_fallback(tmp_path):
    agenda = _agenda()
    result = read_work_plan(
        tmp_path / "missing.json", agenda=agenda, focus_receipt_sha256=FOCUS,
    )
    assert result == {
        "work_cards": [], "agenda_decision": agenda["decision"], "warnings": [],
    }


def test_symlinked_curated_plan_is_rejected(tmp_path):
    source = _write(tmp_path, _plan())
    link = tmp_path / "linked.json"
    link.symlink_to(source)
    result = read_work_plan(link, agenda=_agenda(), focus_receipt_sha256=FOCUS)
    assert result["work_cards"] == []
    assert result["warnings"]
