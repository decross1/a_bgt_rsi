"""Regression pins for machine follow-up consumption and topic provenance.

All state is synthetic and tmp_path-backed. No model, live queue, or scientific
ledger is touched.
"""
from __future__ import annotations

import json

from orchestrator import coordinator as co
from orchestrator import coordinator_cycle_log as ccl
from workers.idea_ledger import append_event


TS = "2026-09-14T00:00:00Z"


def _write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def _machine(topic: str, arxiv_id: str) -> dict:
    return {
        "new_topic": topic,
        "origin": "coordinator_propose",
        "provenance": "paper_gap",
        "arxiv_id": arxiv_id,
    }


def _stub_morning(monkeypatch) -> None:
    monkeypatch.setattr(
        co,
        "pick_morning_topic",
        lambda loop_memory_path=None: ("fresh arxiv option", "arxiv_pick"),
    )


def _cycle_receipt(
    topic: str,
    *,
    iteration_id: str = "iter-synthetic",
    status: str = "passed",
    step_id: str = "step-synthetic",
    request_digest: str = "sha256:synthetic",
) -> dict:
    return {
        "status": "executed",
        "dispatched_iteration_id": iteration_id,
        "plan": [{
            "action": "run_loop_iteration",
            "args": {"topic": topic},
            "step_id": step_id,
            "request_digest": request_digest,
        }],
        "outcomes": [{
            "action": "run_loop_iteration",
            "status": status,
            "step_id": step_id,
            "request_digest": request_digest,
        }],
    }


def test_consumed_paper_agenda_receipt_suppresses_duplicate_machine_row(
    tmp_path, monkeypatch,
):
    agenda_topic = "synthetic paper agenda topic"
    machine_topic = "derived machine follow-up"
    arxiv_id = "2609.00001"
    ledger = tmp_path / "idea_ledger.jsonl"
    append_event(ledger, {
        "event_type": "niche_seeded", "ts": TS,
        "cluster_id": "cl-paper-2609.00001",
        "paper": {"arxiv_id": arxiv_id, "title": agenda_topic},
    })
    append_event(ledger, {
        "event_type": "agenda_item_added", "ts": TS,
        "cluster_id": "cl-paper-2609.00001", "topic": agenda_topic,
        "source": "paper_gap",
    })
    append_event(ledger, {
        "event_type": "agenda_item_consumed", "ts": TS,
        "cluster_id": "cl-paper-2609.00001", "topic": agenda_topic,
    })
    followups = tmp_path / "finding_followups.jsonl"
    _write_jsonl(followups, [
        # Consumption evidence applies only to machine proposals. A human can
        # deliberately request the same topic again and must retain control.
        {
            "new_topic": machine_topic,
            "origin": "finding_session",
            "arxiv_id": arxiv_id,
        },
        # Suppressed by the consumed exact topic.
        _machine(agenda_topic, "2609.00999"),
        # The same paper ID with different wording is not exact durable
        # evidence and therefore remains eligible.
        _machine(machine_topic, arxiv_id),
    ])
    _stub_morning(monkeypatch)

    out = co._topic_suggestions(
        tmp_path / "loop_memory.jsonl",
        followups_path=followups,
        idea_ledger_path=ledger,
        cycles_path=tmp_path / "missing-cycles.jsonl",
    )

    assert out == [
        {"topic": machine_topic, "source": "finding_followup"},
        {"topic": machine_topic, "source": "coordinator_propose"},
        {"topic": "fresh arxiv option", "source": "arxiv_pick"},
    ]


def test_only_successful_cycle_receipt_suppresses_machine_topic(
    tmp_path, monkeypatch,
):
    completed = "completed machine topic"
    finalized_only = "finalized but incomplete machine topic"
    failed = "failed machine topic"
    followups = tmp_path / "finding_followups.jsonl"
    _write_jsonl(followups, [
        _machine(finalized_only, "2609.00002"),
        _machine(failed, "2609.00006"),
        _machine(completed, "2609.00003"),
    ])
    loop_memory = tmp_path / "loop_memory.jsonl"
    _write_jsonl(loop_memory, [
        # A schema-shaped finalized row is not a success receipt: Nara can
        # append one after depth exhaustion, skipped work, or fallback
        # journaling. With no successful coordinator receipt it stays queued.
        {
            "iteration_id": "iter-finalized-only", "ended_at": TS,
            "seed": {
                "topic": finalized_only,
                "source": "coordinator",
            },
        },
    ])
    cycles = tmp_path / "coordinator_cycles.jsonl"
    errored = _cycle_receipt(failed, iteration_id="iter-failed", status="errored")
    # A real cycle receipt is the durable success evidence. Topic matching is
    # whitespace-stable but otherwise exact.
    succeeded = _cycle_receipt(
        "  completed   machine topic\n", iteration_id="iter-completed",
    )
    _write_jsonl(cycles, [errored, succeeded])
    _stub_morning(monkeypatch)

    out = co._topic_suggestions(
        loop_memory,
        followups_path=followups,
        idea_ledger_path=tmp_path / "missing-ledger.jsonl",
        cycles_path=cycles,
    )

    assert out == [
        {"topic": finalized_only, "source": "coordinator_propose"},
        {"topic": failed, "source": "coordinator_propose"},
        {"topic": "fresh arxiv option", "source": "arxiv_pick"},
    ]


def test_cycle_evidence_fails_closed_on_ambiguous_or_mismatched_receipts():
    valid = _cycle_receipt("valid topic", iteration_id="iter-valid")
    duplicate_outcome = _cycle_receipt(
        "ambiguous topic", iteration_id="iter-ambiguous",
    )
    duplicate_outcome["outcomes"].append({
        "action": "run_loop_iteration",
        "status": "errored",
        "step_id": "step-synthetic",
        "request_digest": "sha256:synthetic",
    })
    mismatched_identity = _cycle_receipt(
        "mismatched topic", iteration_id="iter-mismatch",
    )
    mismatched_identity["outcomes"][0]["request_digest"] = "sha256:different"

    topics = co._handled_machine_topic_evidence(
        [valid, duplicate_outcome, mismatched_identity], {},
    )

    assert topics == {"valid topic"}


def test_filter_precedes_cap_and_never_consumes_human_followup(
    tmp_path, monkeypatch,
):
    human = "human requested follow-up"
    stale_a = "handled machine topic a"
    stale_b = "handled machine topic b"
    followups = tmp_path / "finding_followups.jsonl"
    _write_jsonl(followups, [
        {"new_topic": human, "origin": "finding_session"},
        _machine(stale_a, "2609.00004"),
        _machine(stale_b, "2609.00005"),
    ])
    cycles = tmp_path / "coordinator_cycles.jsonl"
    _write_jsonl(cycles, [
        _cycle_receipt(stale_a, iteration_id="iter-a", step_id="step-a"),
        _cycle_receipt(stale_b, iteration_id="iter-b", step_id="step-b"),
        # Even an exact success receipt must not consume a HUMAN follow-up.
        _cycle_receipt(human, iteration_id="iter-human", step_id="step-human"),
    ])
    _stub_morning(monkeypatch)

    out = co._topic_suggestions(
        tmp_path / "loop_memory.jsonl",
        followups_path=followups,
        idea_ledger_path=tmp_path / "missing-ledger.jsonl",
        cycles_path=cycles,
    )

    assert out == [
        {"topic": human, "source": "finding_followup"},
        {"topic": "fresh arxiv option", "source": "arxiv_pick"},
    ]


def test_cycle_log_attributes_source_of_actual_nonfirst_topic():
    report = {
        "run_id": "coordinator-source-test",
        "status": "executed",
        "plan": [{
            "name": "run_loop_iteration", "cost": 3,
            "args": {"topic": "selected second topic"},
        }],
        "executed": [],
        "state": {"topic_suggestions": [
            {"topic": "first agenda topic", "source": "agenda"},
            {"topic": "selected second topic", "source": "coordinator_propose"},
            {"topic": "fresh arxiv option", "source": "arxiv_pick"},
        ]},
    }

    row = ccl.cycle_row_from_report(report, timestamp=TS)

    assert row["topic"] == "selected second topic"
    assert row["topic_source"] == "coordinator_propose"


def test_cycle_log_does_not_misattribute_unmatched_planned_topic():
    report = {
        "run_id": "coordinator-source-unknown",
        "status": "planned",
        "plan": [{
            "name": "run_loop_iteration", "cost": 3,
            "args": {"topic": "unmatched planned topic"},
        }],
        "executed": [],
        "state": {"topic_suggestions": [
            {"topic": "different topic", "source": "agenda"},
        ]},
    }

    row = ccl.cycle_row_from_report(report, timestamp=TS)

    assert row["topic"] == "unmatched planned topic"
    assert row["topic_source"] is None


def test_cycle_log_does_not_guess_between_conflicting_sources_for_same_topic():
    report = {
        "run_id": "coordinator-source-ambiguous",
        "status": "planned",
        "plan": [{
            "name": "run_loop_iteration", "cost": 3,
            "args": {"topic": "duplicated topic"},
        }],
        "executed": [],
        "state": {"topic_suggestions": [
            {"topic": "duplicated topic", "source": "agenda"},
            {"topic": "duplicated topic", "source": "coordinator_propose"},
        ]},
    }

    row = ccl.cycle_row_from_report(report, timestamp=TS)

    assert row["topic"] == "duplicated topic"
    assert row["topic_source"] is None
