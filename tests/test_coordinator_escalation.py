"""Tests for the generalized coordinator escalation (seam 2).

Covers the ADDITIVE generalization of the coordinator bubble into a generic
escalation: the legacy finding-id bubble {finding_ids, note} stays valid and
keeps surfacing; a generic {question, context, kind, allowed_actions}
escalation persists; kind/allowed_actions validate fail-closed (rule 4 — an
off-enum value is an honest error, never a silent coercion); and the A+B-only
count contract excludes read-receipts (kind C).

Offline + MOCK_LLM-safe: no model call is made (we exercise the handler /
persist / collect / count directly, plus the dispatch loop with a scripted
plan via a call_sync stub). All writes go to tmp_path; real memory/ and
run_state/ are never touched (active_run stubbed).
"""
from __future__ import annotations

import builtins
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

import orchestrator.coordinator as coord

REPO_ROOT = Path(__file__).resolve().parent.parent
ESCALATION_SCHEMA = json.loads(
    (REPO_ROOT / "schema" / "escalation.schema.json").read_text()
)


# ── fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _stub_active_run(monkeypatch):
    """Never touch run_state/active_run.json from a test (mirrors
    test_coordinator)."""
    monkeypatch.setattr(coord.active_run, "write_active_run",
                        lambda *a, **k: {"run_id": a[0] if a else "x"})
    monkeypatch.setattr(coord.active_run, "update_active_run",
                        lambda *a, **k: None)
    monkeypatch.setattr(coord.active_run, "clear_active_run", lambda: None)
    monkeypatch.setattr(coord, "set_run_id", lambda _x: None)


def _read_rows(path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def _request_digest(request: dict) -> str:
    payload = json.dumps(
        request, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _evidenced_bubble(
    step_id: str, *, question: str = "Should the owner review this?",
) -> tuple[dict, dict]:
    args = {
        "finding_ids": ["sf-exact"],
        "question": question,
        "kind": "A",
        "allowed_actions": ["sign_off", "reject"],
    }
    request = {"action": "bubble_up", "args": args}
    digest = _request_digest(request)
    step = {
        "name": "bubble_up", "args": args, "cost": 1,
        "handler_ref": "orchestrator.coordinator:handle_bubble_up",
        "step_id": step_id, "request_digest": digest,
    }
    outcome = {
        "action": "bubble_up", "status": "passed",
        "step_id": step_id, "request_digest": digest,
        "request": json.loads(json.dumps(request)),
        "result": {"status": "passed", "result": dict(args)},
    }
    return step, outcome


# ── handler: legacy form back-compat ──────────────────────────────────────


def test_handle_bubble_up_legacy_finding_ids_still_passes():
    out = coord.handle_bubble_up(finding_ids=["sf-001", "sf-002"], note="look")
    assert out["status"] == "passed"
    assert out["result"]["finding_ids"] == ["sf-001", "sf-002"]
    assert out["result"]["note"] == "look"
    # generic fields default to None on a legacy call.
    assert out["result"]["kind"] is None
    assert out["result"]["question"] is None


def test_handle_bubble_up_generic_escalation_passes():
    out = coord.handle_bubble_up(
        question="Is exp009 Cournot collusion topical for the loop?",
        context="novelty=novel, critic=survives, but no human verdict yet",
        kind="A",
        allowed_actions=["sign_off", "reject", "refine_defer"],
    )
    assert out["status"] == "passed"
    r = out["result"]
    assert r["question"].startswith("Is exp009")
    assert r["kind"] == "A"
    assert r["allowed_actions"] == ["sign_off", "reject", "refine_defer"]
    assert r["finding_ids"] == []  # no finding ids on a pure generic escalation


def test_handle_bubble_up_preserves_all_existing_kinds_and_resolutions():
    resolutions = [
        "sign_off", "reject", "refine_defer", "refine_authorize_fix",
        "spawn_topic", "abstain",
    ]
    for kind in ("A", "B", "C"):
        args = {
            "question": f"Resolve escalation {kind}?",
            "kind": kind,
            "allowed_actions": list(resolutions),
        }
        original = json.loads(json.dumps(args))
        out = coord.handle_bubble_up(**args)
        assert out["status"] == "passed"
        assert out["result"]["question"] == args["question"]
        assert out["result"]["kind"] == kind
        assert out["result"]["allowed_actions"] == resolutions
        assert args == original


def test_handle_bubble_up_empty_is_rejected():
    """rule 4 — never fabricate a surfacing: no finding_ids AND no question."""
    with pytest.raises(ValueError):
        coord.handle_bubble_up()
    with pytest.raises(ValueError):
        coord.handle_bubble_up(question="   ")  # whitespace-only is empty
    with pytest.raises(ValueError, match="question must be non-empty"):
        coord.handle_bubble_up(finding_ids=["sf-legacy"], question="")


def test_handle_bubble_up_preserves_valid_payload_coexistence():
    legacy = coord.handle_bubble_up(
        finding_ids=["sf-legacy"], question="   ",
    )
    assert legacy["result"]["finding_ids"] == ["sf-legacy"]
    assert legacy["result"]["question"] == "   "

    generic = coord.handle_bubble_up(
        finding_ids=[], question="A substantive generic question?",
    )
    assert generic["result"]["finding_ids"] == []
    assert generic["result"]["question"] == "A substantive generic question?"


# ── handler: fail-closed validation (rule 4) ──────────────────────────────


def test_handle_bubble_up_unknown_kind_raises():
    with pytest.raises(ValueError):
        coord.handle_bubble_up(question="q", kind="Z")


def test_handle_bubble_up_offenum_allowed_action_raises():
    with pytest.raises(ValueError):
        coord.handle_bubble_up(
            question="q", kind="A", allowed_actions=["sign_off", "delete_repo"],
        )


def test_planner_menu_handler_and_persisted_schema_share_literal_enums():
    from orchestrator.coordinator_actions import (
        ACTIONS,
        ALLOWED_ESCALATION_ACTIONS,
        ESCALATION_KINDS,
    )

    bubble_schema = ACTIONS["bubble_up"]["arg_schema"]["properties"]
    assert bubble_schema["question"]["minLength"] == (
        ESCALATION_SCHEMA["properties"]["question"]["minLength"]
    ) == 1
    assert bubble_schema["kind"]["enum"] == list(ESCALATION_KINDS)
    assert bubble_schema["allowed_actions"]["items"]["enum"] == list(
        ALLOWED_ESCALATION_ACTIONS
    )
    assert ESCALATION_SCHEMA["properties"]["kind"]["enum"] == list(
        ESCALATION_KINDS
    )
    assert ESCALATION_SCHEMA["properties"]["allowed_actions"]["items"][
        "enum"
    ] == list(ALLOWED_ESCALATION_ACTIONS)
    assert coord.ESCALATION_KINDS is ESCALATION_KINDS
    assert coord.ALLOWED_ESCALATION_ACTIONS is ALLOWED_ESCALATION_ACTIONS
    assert "A = judgment" in bubble_schema["kind"]["description"]
    assert "B = blocking-halt" in bubble_schema["kind"]["description"]
    assert "C = read-receipt" in bubble_schema["kind"]["description"]


def test_planner_and_handler_both_reject_whitespace_only_generic_payload():
    from orchestrator.coordinator_actions import validate_plan

    args = {"question": "   ", "kind": "A", "allowed_actions": ["reject"]}
    verdict = validate_plan([{"action": "bubble_up", "args": args}], budget=1)
    assert verdict["ok"] is False
    assert any("non-empty" in error for error in verdict["errors"])
    with pytest.raises(ValueError, match="non-empty question"):
        coord.handle_bubble_up(**args)


# ── persistence: legacy + generic, back-compat on-disk shape ──────────────


def test_persist_legacy_bubble_keeps_ui_reader_fields(tmp_path):
    """The legacy on-disk shape stays compatible with the UI reader
    (human_todo._bubble_ack_items consumes run_id/timestamp/note)."""
    bubbles = [{"finding_ids": ["sf-009"], "note": "review me"}]
    p = tmp_path / "coordinator_bubbles.jsonl"
    coord._persist_bubble_up(bubbles, run_id="coordinator_abc", path=p)
    rows = _read_rows(p)
    assert len(rows) == 1
    row = rows[0]
    assert row["run_id"] == "coordinator_abc"
    assert row["finding_ids"] == ["sf-009"]
    assert row["note"] == "review me"
    assert "timestamp" in row
    # A legacy bubble carries NO empty generic keys (additive-only write).
    assert "kind" not in row
    assert "question" not in row
    Draft7Validator(ESCALATION_SCHEMA).validate(row)


def test_persist_generic_escalation_writes_four_fields(tmp_path):
    bubbles = [{
        "finding_ids": [],
        "note": None,
        "question": "Should we run the real Cournot trials?",
        "context": "synthetic results look strong",
        "kind": "A",
        "allowed_actions": ["sign_off", "refine_authorize_fix"],
    }]
    p = tmp_path / "coordinator_bubbles.jsonl"
    coord._persist_bubble_up(bubbles, run_id="coordinator_def", path=p)
    row = _read_rows(p)[0]
    assert row["question"] == "Should we run the real Cournot trials?"
    assert row["context"] == "synthetic results look strong"
    assert row["kind"] == "A"
    assert row["allowed_actions"] == ["sign_off", "refine_authorize_fix"]
    # back-compat fields present too.
    assert row["run_id"] == "coordinator_def"
    assert "timestamp" in row
    Draft7Validator(ESCALATION_SCHEMA).validate(row)


# ── schema: both forms valid, off-enum invalid ────────────────────────────


def test_schema_accepts_legacy_and_generic_forms():
    v = Draft7Validator(ESCALATION_SCHEMA)
    legacy = {
        "run_id": "coordinator_1", "timestamp": "2026-06-14T00:00:00Z",
        "finding_ids": ["sf-1"], "note": "n",
    }
    generic = {
        "run_id": "coordinator_2", "timestamp": "2026-06-14T00:00:00Z",
        "question": "q?", "context": "c", "kind": "B",
        "allowed_actions": ["reject", "abstain"],
    }
    v.validate(legacy)
    v.validate(generic)


def test_schema_rejects_offenum_kind_and_action():
    v = Draft7Validator(ESCALATION_SCHEMA)
    bad_kind = {
        "run_id": "r", "timestamp": "2026-06-14T00:00:00Z",
        "question": "q", "kind": "Z",
    }
    bad_action = {
        "run_id": "r", "timestamp": "2026-06-14T00:00:00Z",
        "question": "q", "kind": "A", "allowed_actions": ["nuke"],
    }
    assert v.iter_errors(bad_kind)
    assert list(v.iter_errors(bad_kind))
    assert list(v.iter_errors(bad_action))
    # run_id is required by the schema (the persist always stamps it).
    assert list(v.iter_errors({"timestamp": "2026-06-14T00:00:00Z"}))


# ── the A+B-only count contract (excludes C) ──────────────────────────────


def test_count_actionable_escalations_excludes_read_receipts(tmp_path):
    p = tmp_path / "coordinator_bubbles.jsonl"
    rows = [
        # legacy finding-id bubble: no `kind` -> taxonomy C -> NOT counted.
        {"run_id": "r1", "timestamp": "t", "finding_ids": ["sf-1"], "note": "n"},
        # explicit read-receipt -> NOT counted.
        {"run_id": "r2", "timestamp": "t", "question": "ack?", "kind": "C"},
        # judgment -> counted.
        {"run_id": "r3", "timestamp": "t", "question": "decide?", "kind": "A"},
        # blocking-halt -> counted.
        {"run_id": "r4", "timestamp": "t", "question": "halt?", "kind": "B"},
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert coord.count_actionable_escalations(path=p) == 2


def test_count_actionable_escalations_missing_file_is_zero(tmp_path):
    assert coord.count_actionable_escalations(path=tmp_path / "nope.jsonl") == 0


# ── collect -> persist -> count pipeline (the seam-2 path I own) ──────────


def test_collect_carries_generic_fields_then_persists_and_counts(tmp_path):
    """The part of the path seam 2 owns: a validated plan with a generic
    bubble_up flows _collect_bubble_up -> _persist_bubble_up ->
    count_actionable_escalations. (The plan->validator step is gated by
    coordinator_actions.bubble_up arg_schema, which is OUT OF this seam's
    contract — see the discrepancy test below.)"""
    validated = [{
        "name": "bubble_up",
        "args": {
            "finding_ids": ["sf-iter-x"],
            "question": "Is iter-x worth promoting?",
            "kind": "A",
            "allowed_actions": ["sign_off", "reject"],
        },
    }]
    collected = coord._collect_bubble_up(validated, executed=None)
    assert collected[0]["question"] == "Is iter-x worth promoting?"
    assert collected[0]["kind"] == "A"

    p = tmp_path / "coordinator_bubbles.jsonl"
    coord._persist_bubble_up(collected, run_id="coordinator_e2e", path=p)
    row = _read_rows(p)[0]
    assert row["kind"] == "A"
    assert row["question"] == "Is iter-x worth promoting?"
    assert row["allowed_actions"] == ["sign_off", "reject"]
    assert row["finding_ids"] == ["sf-iter-x"]
    Draft7Validator(ESCALATION_SCHEMA).validate(row)
    assert coord.count_actionable_escalations(path=p) == 1


def test_validator_accepts_generic_bubble_args():
    """Seam 2 closed end-to-end (2026-06-15): the planner CAN emit a generic
    {question, context, kind, allowed_actions} bubble_up. coordinator_actions
    .bubble_up accepts the legacy finding-id form OR the generic escalation
    form (anyOf finding_ids|question), and admission shares the handler's
    literal kind/allowed_actions contract. (Was the DISCREPANCY pin.)"""
    from orchestrator.coordinator_actions import validate_plan
    # a well-formed generic escalation validates at the planner gate
    generic_plan = [{
        "action": "bubble_up",
        "args": {"question": "is the PD cooperation result robust?",
                 "kind": "A", "allowed_actions": ["sign_off", "reject"]},
    }]
    assert validate_plan(generic_plan, budget=6)["ok"] is True
    # the legacy finding-id bubble still validates (back-compat)
    legacy_plan = [{"action": "bubble_up", "args": {"finding_ids": ["f1"]}}]
    assert validate_plan(legacy_plan, budget=6)["ok"] is True
    # an empty bubble (neither finding_ids nor question) is still rejected
    empty_plan = [{"action": "bubble_up", "args": {"note": "no payload"}}]
    assert validate_plan(empty_plan, budget=6)["ok"] is False


# ── T05: exact-step collection + truthful append receipts ────────────────


@pytest.mark.parametrize("failed_index", [0, 1])
def test_t05_duplicate_bubbles_bind_only_the_exact_passed_step(
    monkeypatch, tmp_path, failed_index,
):
    """Falsifier 1: equal requests cannot borrow a sibling step's success."""
    raw_step = {
        "action": "bubble_up",
        "args": {
            "finding_ids": ["sf-duplicate"],
            "question": "Review the duplicate request?",
            "kind": "A",
            "allowed_actions": ["sign_off", "reject"],
        },
    }
    monkeypatch.setattr(coord, "assess_state", lambda **_kwargs: {
        "topic_suggestions": [], "recent_findings": [],
    })
    monkeypatch.setattr(coord, "plan", lambda *_args, **_kwargs: [
        json.loads(json.dumps(raw_step)), json.loads(json.dumps(raw_step)),
    ])
    monkeypatch.setattr(coord, "_daily_spent_by_class", lambda **_kwargs: {})
    monkeypatch.setattr(coord, "_charge_daily_ledger", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(coord.coordinator_cycle_log, "write_coordinator_cycle",
                        lambda report: report)
    monkeypatch.setattr(coord.coordinator_cycle_log, "emit_health_signals",
                        lambda report: [])
    bubbles_path = tmp_path / "coordinator_bubbles.jsonl"
    monkeypatch.setattr(coord, "DEFAULT_COORDINATOR_BUBBLES", bubbles_path)

    calls = 0

    def _handler(**kwargs):
        nonlocal calls
        index = calls
        calls += 1
        if index == failed_index:
            raise RuntimeError("scripted handler failure")
        return coord.handle_bubble_up(**kwargs)

    report = coord._coordinator_cycle(
        run_id="coordinator_exact_pair",
        budget=6,
        dry_run=False,
        execute_handlers={"bubble_up": _handler},
        backend=None,
        model=None,
        loop_memory_path="unused-loop-memory",
        surfaced_path="unused-surfaced",
        feedback_path="unused-feedback",
        active_run_path="unused-active-run",
    )

    assert report["status"] == "executed"  # attempted lifecycle is unchanged
    assert [row["status"] for row in report["executed"]] == (
        ["error", "passed"] if failed_index == 0 else ["passed", "error"]
    )
    step_ids = [step["step_id"] for step in report["plan"]]
    assert step_ids == [
        "coordinator_exact_pair:step:0", "coordinator_exact_pair:step:1",
    ]
    assert len(set(step_ids)) == 2
    # Identical requests have the same content digest; occurrence identity is
    # carried separately by step_id.
    assert report["plan"][0]["request_digest"] == report["plan"][1][
        "request_digest"
    ]
    assert [row["step_id"] for row in report["executed"]] == step_ids
    passed_step_id = step_ids[1 - failed_index]
    assert [bubble["step_id"] for bubble in report["bubble_up"]] == [
        passed_step_id
    ]
    assert [receipt["step_id"] for receipt in report["bubble_receipts"]] == [
        passed_step_id
    ]
    assert report["bubble_receipts"][0]["status"] == "persisted"
    rows = _read_rows(bubbles_path)
    assert len(rows) == 1
    assert rows[0]["step_id"] == passed_step_id


@pytest.mark.parametrize(
    ("outer_status", "handler_status"),
    [
        ("error", None),
        ("skipped", None),
        ("passed", "error"),
        ("passed", "failed"),
        ("passed", "skipped"),
    ],
)
def test_t05_failed_skipped_or_failed_envelope_persists_no_row(
    tmp_path, outer_status, handler_status,
):
    """Falsifier 2: only an exact, affirmatively passed handler qualifies."""
    step, outcome = _evidenced_bubble("coordinator_failed:step:0")
    outcome["status"] = outer_status
    if outer_status != "passed":
        outcome.pop("result")
        outcome["reason"] = "scripted non-success"
    else:
        outcome["result"]["status"] = handler_status

    bubbles = coord._collect_bubble_up([step], executed=[outcome])
    assert bubbles == []
    path = tmp_path / "coordinator_bubbles.jsonl"
    assert coord._persist_bubble_up(
        bubbles, run_id="coordinator_failed", path=path,
    ) == []
    assert not path.exists()


@pytest.mark.parametrize("failure", ["short_write", "flush", "fsync", "close"])
def test_t05_append_boundary_failure_is_explicit_and_has_no_durable_id(
    monkeypatch, tmp_path, failure,
):
    """Falsifier 3: partial/flush/fsync/close uncertainty never mints an ID."""
    step, outcome = _evidenced_bubble("coordinator_append_fail:step:0")
    bubbles = coord._collect_bubble_up([step], executed=[outcome])
    assert len(bubbles) == 1

    class BoundaryFile:
        def seek(self, _offset, _whence=0):
            return 0

        def tell(self):
            return 0  # private empty-file preflight; fault belongs to append

        def read(self, _size=-1):
            return b""

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            if exc_type is not None:
                return False
            self.close()
            return False

        def write(self, payload):
            if failure == "short_write":
                return len(payload) - 1
            return len(payload)

        def flush(self):
            if failure == "flush":
                raise OSError("scripted flush failure")

        def fileno(self):
            return 71

        def close(self):
            if failure == "close":
                raise OSError("scripted close failure")

    monkeypatch.setattr(builtins, "open", lambda *_args, **_kwargs: BoundaryFile())

    def _fsync(_fd):
        if failure == "fsync":
            raise OSError("scripted fsync failure")

    monkeypatch.setattr(coord.os, "fsync", _fsync)
    receipts = coord._persist_bubble_up(
        bubbles,
        run_id="coordinator_append_fail",
        path=tmp_path / "coordinator_bubbles.jsonl",
    )
    assert len(receipts) == 1
    assert receipts[0]["status"] == "error"
    assert receipts[0]["durability"] == "unknown"
    assert "bubble_run_id" not in receipts[0]
    assert receipts[0]["step_id"] == "coordinator_append_fail:step:0"
    expected_error = {
        "short_write": "short append", "flush": "scripted flush failure",
        "fsync": "scripted fsync failure", "close": "scripted close failure",
    }[failure]
    assert expected_error in receipts[0]["error"]


def test_t05_success_receipt_and_row_bind_the_exact_request(tmp_path):
    """Falsifier 5: append success is exact, schema-valid, and mismatch-closed."""
    step, outcome = _evidenced_bubble("coordinator_exact:step:0")
    bubbles = coord._collect_bubble_up([step], executed=[outcome])
    path = tmp_path / "coordinator_bubbles.jsonl"
    receipts = coord._persist_bubble_up(
        bubbles, run_id="coordinator_exact", path=path,
    )
    assert receipts == [{
        "status": "persisted",
        "step_id": "coordinator_exact:step:0",
        "request_digest": step["request_digest"],
        "request": outcome["request"],
        "bubble_run_id": "coordinator_exact",
    }]
    row = _read_rows(path)[0]
    assert row["step_id"] == receipts[0]["step_id"]
    assert row["request_digest"] == receipts[0]["request_digest"]
    assert row["request"] == outcome["request"]
    assert row["question"] == outcome["request"]["args"]["question"]
    assert {"run_id", "timestamp", "finding_ids", "note"} <= row.keys()
    Draft7Validator(ESCALATION_SCHEMA).validate(row)

    # Top-level metadata is never allowed to describe a different request.
    mismatched = json.loads(json.dumps(bubbles[0]))
    mismatched["question"] = "different payload"
    mismatch_receipts = coord._persist_bubble_up(
        [mismatched], run_id="coordinator_exact", path=path,
    )
    assert mismatch_receipts[0]["status"] == "error"
    assert mismatch_receipts[0]["durability"] == "not_persisted"
    assert "bubble_run_id" not in mismatch_receipts[0]
    assert len(_read_rows(path)) == 1


def test_invalid_escalation_exhausts_replans_without_dispatch_charge_or_persist(
    monkeypatch,
):
    """A rejected escalation stays wholly above the execution/persistence seam."""
    invalid_plan = [{
        "action": "bubble_up",
        "args": {
            "finding_ids": ["iter-2026-09-07-001"],
            "question": "Please review these pending iterations.",
            "kind": "finding_review",
            "allowed_actions": ["promote_findings"],
        },
    }]
    plan_calls: list[str | None] = []

    def _plan(*_args, extra_guidance=None, **_kwargs):
        plan_calls.append(extra_guidance)
        return invalid_plan

    def _forbidden(*_args, **_kwargs):
        raise AssertionError("invalid plan crossed the admission boundary")

    cycle_rows: list[dict] = []
    monkeypatch.setattr(coord, "assess_state", lambda **_kwargs: {
        "topic_suggestions": [], "recent_findings": [],
    })
    monkeypatch.setattr(coord, "plan", _plan)
    monkeypatch.setattr(coord, "_charge_daily_ledger", _forbidden)
    monkeypatch.setattr(coord, "_persist_bubble_up", _forbidden)
    monkeypatch.setattr(
        coord.coordinator_cycle_log,
        "write_coordinator_cycle",
        lambda report: cycle_rows.append(report),
    )

    report = coord._coordinator_cycle(
        run_id="coordinator_invalid_escalation",
        budget=6,
        dry_run=False,
        execute_handlers={"bubble_up": _forbidden},
        backend=None,
        model=None,
        loop_memory_path="unused-loop-memory",
        surfaced_path="unused-surfaced",
        feedback_path="unused-feedback",
        active_run_path="unused-active-run",
    )

    assert report["status"] == "no_valid_plan"
    assert report["plan"] == []
    assert report["executed"] == []
    assert report["bubble_up"] == []
    assert len(plan_calls) == coord._MAX_REPLANS + 1
    assert len(report["attempts"]) == coord._MAX_REPLANS + 1
    assert plan_calls[0] is None
    assert all("finding_review" in guidance for guidance in plan_calls[1:])
    assert cycle_rows == [report]


@pytest.mark.parametrize("old_tail", [
    b'{"run_id":"legacy","timestamp":"2026-01-01T00:00:00Z"}',
    b'{"run_id":"partial',
])
def test_t05_unterminated_tail_refuses_append_and_preserves_history(tmp_path, old_tail):
    """A completed or partial old tail must not swallow the next JSON row."""
    pairs = [_evidenced_bubble(f"coordinator_tail:step:{i}") for i in range(2)]
    bubbles = coord._collect_bubble_up(
        [pair[0] for pair in pairs], executed=[pair[1] for pair in pairs],
    )
    path = tmp_path / "coordinator_bubbles.jsonl"
    path.write_bytes(old_tail)
    receipts = coord._persist_bubble_up(bubbles, run_id="coordinator_tail", path=path)
    assert [receipt["status"] for receipt in receipts] == ["error", "not_attempted"]
    assert receipts[0]["durability"] == "not_persisted"
    assert "unterminated final line" in receipts[0]["error"]
    assert all("bubble_run_id" not in receipt for receipt in receipts)
    assert path.read_bytes() == old_tail
    assert not any(row.get("run_id") == "coordinator_tail" for row in coord._read_jsonl(path))


def test_t05_newline_history_and_unicode_append_remain_reader_compatible(tmp_path):
    step, outcome = _evidenced_bubble(
        "coordinator_unicode:step:0", question="Review λ and 🙂?",
    )
    bubbles = coord._collect_bubble_up([step], executed=[outcome])
    path = tmp_path / "coordinator_bubbles.jsonl"
    prefix = b'{"run_id":"legacy","timestamp":"2026-01-01T00:00:00Z"}\n'
    path.write_bytes(prefix)
    receipts = coord._persist_bubble_up(bubbles, run_id="coordinator_unicode", path=path)
    assert receipts[0]["status"] == "persisted"
    assert path.read_bytes().startswith(prefix)
    rows = coord._read_jsonl(path)
    assert len(rows) == 2
    assert rows[1]["question"] == "Review λ and 🙂?"
    assert rows[1]["request_digest"] == step["request_digest"]
    Draft7Validator(ESCALATION_SCHEMA).validate(rows[1])
