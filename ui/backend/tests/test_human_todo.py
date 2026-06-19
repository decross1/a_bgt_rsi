"""Human-TODO endpoint tests (B3 of observability_reconciliation_plan.md).

Side-effect-free: no real CLI invocation, no real run_state/memory writes —
every path points at tmp_path (mirrors test_coordinator.py's
TestClient-against-tmp_path idiom). One live-ish module at the bottom points
the coordinator dirs READ-ONLY at the real primary checkout and asserts
cohort-invariant truths (>= 1 pending gate verdict; every item shape-complete)
without hardcoding row counts that rot as the apparatus appends.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.human_todo import KINDS

_PRIMARY_REPO = Path("/home/decross1/projects/a_bgt_rsi")
_ITEM_KEYS = {"kind", "id", "title", "since", "detail", "resolve_command"}


def _client(tmp_path) -> TestClient:
    """Build a TestClient that points every path at tmp_path.

    Pins the non-coordinator paths at benign tmp fixtures (as test_coordinator
    does) and points the coordinator run_state/memory dirs — which human_todo
    shares — at tmp dirs so we control the data files under test.
    """
    (tmp_path / "logs").mkdir(exist_ok=True)
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"current_day": "human_todo"}), encoding="utf-8")
    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text("", encoding="utf-8")
    bench = tmp_path / "day1.csv"
    bench.write_text(
        "prompt_idx,completion_tokens,elapsed_s,decode_tok_per_s\n0,256,8.0,32.0\n",
        encoding="utf-8",
    )
    mtp = tmp_path / "mtp.csv"

    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    loop_run_state = tmp_path / "loop_run_state"
    loop_run_state.mkdir(exist_ok=True)
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir(exist_ok=True)
    loop_memory = tmp_path / "loop_memory.jsonl"

    # The dirs under test are intentionally NOT pre-created — the
    # empty-everything test relies on absent files being tolerated.
    coord_run_state = tmp_path / "coord_run_state"
    coord_memory = tmp_path / "coord_memory"

    app = create_app(
        logs_dir=tmp_path / "logs",
        telemetry_file=telemetry,
        state_file=state,
        bench_csv=bench,
        mtp_csv=mtp,
        loop_v0_repo=repo,
        loop_v0_run_state=loop_run_state,
        loop_v0_journal=journal_dir,
        loop_v0_memory=loop_memory,
        coordinator_run_state=coord_run_state,
        coordinator_memory=coord_memory,
    )
    return TestClient(app)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# ─── empty everything ──────────────────────────────────────────────────


def test_empty_everything_returns_no_items_and_zero_counts(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/human_todo")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["counts"] == {kind: 0 for kind in KINDS}


# ─── gate_verdict ──────────────────────────────────────────────────────


def test_pending_gate_without_feedback_appears(tmp_path):
    client = _client(tmp_path)
    _write_jsonl(tmp_path / "coord_memory" / "loop_memory.jsonl", [
        {
            "iteration_id": "iter-2026-06-09-001",
            "ended_at": "2026-06-09T18:08:00Z",
            "gate_status": "pending",
            "seed": {"topic": "Risk-dominance under history transparency"},
            # Experiment-bearing -> a blocking gate_verdict item.
            "experiment_outcome": {"verdict": "supports", "delta": 0.12},
        },
        # Non-pending row must NOT appear.
        {
            "iteration_id": "iter-2026-06-09-002",
            "ended_at": "2026-06-09T19:00:00Z",
            "seed": {"topic": "no gate_status at all"},
        },
    ])
    body = client.get("/api/human_todo").json()
    assert body["counts"]["gate_verdict"] == 1
    [item] = body["items"]
    assert item["kind"] == "gate_verdict"
    assert item["id"] == "iter-2026-06-09-001"
    assert item["title"] == "Risk-dominance under history transparency"
    assert item["since"] == "2026-06-09T18:08:00Z"
    # The resolve command is the EXACT gate_cli invocation shape (flags per
    # orchestrator/gate_cli.py argparse; enum per loop_feedback.schema.json).
    assert "-m orchestrator.gate_cli" in item["resolve_command"]
    assert "--iteration-id iter-2026-06-09-001" in item["resolve_command"]
    assert "--verdict" in item["resolve_command"]
    for verdict in ("valid", "invalid", "needs_revision"):
        assert verdict in item["resolve_command"]


def test_pending_gate_disappears_once_feedback_row_exists(tmp_path):
    client = _client(tmp_path)
    _write_jsonl(tmp_path / "coord_memory" / "loop_memory.jsonl", [
        {
            "iteration_id": "iter-2026-06-09-001",
            "ended_at": "2026-06-09T18:08:00Z",
            "gate_status": "pending",
            "seed": {"topic": "soon to be gated"},
            # Experiment-bearing so the loop_feedback row — not the eo guard —
            # is what removes it from the inbox.
            "experiment_outcome": {"verdict": "supports"},
        },
    ])
    _write_jsonl(tmp_path / "coord_memory" / "loop_feedback.jsonl", [
        {
            "iteration_id": "iter-2026-06-09-001",
            "verdict": "valid",
            "note": "",
            "gated_at": "2026-06-09T20:00:00Z",
            "gated_by": "decross1",
        },
    ])
    body = client.get("/api/human_todo").json()
    assert body["items"] == []
    assert body["counts"]["gate_verdict"] == 0


# ─── gate_verdict: experiment_outcome discriminator ────────────────────
# Only experiment/applied-stage iterations (a usable experiment_outcome
# dict) are gated; literature-stage pending rows auto-advance and are
# dropped from the blocking inbox (still observable via /api/loop_v0/iterations).


def test_pending_gate_with_experiment_outcome_surfaces(tmp_path):
    client = _client(tmp_path)
    _write_jsonl(tmp_path / "coord_memory" / "loop_memory.jsonl", [
        {"iteration_id": "iter-exp-001", "gate_status": "pending",
         "ended_at": "2026-06-09T18:00:00Z", "seed": {"topic": "experiment-stage"},
         "experiment_outcome": {"verdict": "supports", "delta": 0.2}},
    ])
    body = client.get("/api/human_todo").json()
    assert body["counts"]["gate_verdict"] == 1
    [item] = body["items"]
    assert item["id"] == "iter-exp-001"


def test_pending_gate_without_experiment_outcome_does_not_surface(tmp_path):
    client = _client(tmp_path)
    _write_jsonl(tmp_path / "coord_memory" / "loop_memory.jsonl", [
        # Literature-stage: pending, no loop_feedback, but no experiment_outcome
        # -> auto-advances, never blocks the inbox.
        {"iteration_id": "iter-lit-001", "gate_status": "pending",
         "ended_at": "2026-06-09T18:00:00Z", "seed": {"topic": "literature-stage"}},
    ])
    body = client.get("/api/human_todo").json()
    assert body["counts"]["gate_verdict"] == 0
    assert body["items"] == []


def test_pending_gate_with_non_dict_or_empty_experiment_outcome_does_not_surface(tmp_path):
    client = _client(tmp_path)
    _write_jsonl(tmp_path / "coord_memory" / "loop_memory.jsonl", [
        # Empty dict: not a usable outcome.
        {"iteration_id": "iter-empty", "gate_status": "pending",
         "ended_at": "2026-06-09T18:00:00Z", "seed": {"topic": "empty eo"},
         "experiment_outcome": {}},
        # Non-dict (string): not a usable outcome.
        {"iteration_id": "iter-str", "gate_status": "pending",
         "ended_at": "2026-06-09T18:00:00Z", "seed": {"topic": "string eo"},
         "experiment_outcome": "supports"},
        # Non-dict (null): not a usable outcome.
        {"iteration_id": "iter-null", "gate_status": "pending",
         "ended_at": "2026-06-09T18:00:00Z", "seed": {"topic": "null eo"},
         "experiment_outcome": None},
    ])
    body = client.get("/api/human_todo").json()
    assert body["counts"]["gate_verdict"] == 0
    assert body["items"] == []


# ─── finding_review (status-audit override) ────────────────────────────


def test_finding_status_audit_override_respected(tmp_path):
    client = _client(tmp_path)
    _write_jsonl(tmp_path / "coord_memory" / "surfaced_findings.jsonl", [
        # Base surfaced, no override -> appears.
        {"finding_id": "sf-001", "title": "still awaiting review",
         "promoted_at": "2026-06-08T10:00:00Z", "status": "surfaced"},
        # Base surfaced, last audit row closes it -> gone.
        {"finding_id": "sf-002", "title": "already validated",
         "promoted_at": "2026-06-08T11:00:00Z", "status": "surfaced"},
        # Base surfaced, audit flip-flops, LAST row is in_review -> appears.
        {"finding_id": "sf-003", "title": "reopened for refinement",
         "promoted_at": "2026-06-08T12:00:00Z", "status": "surfaced"},
    ])
    _write_jsonl(
        tmp_path / "coord_memory" / "surfaced_findings.status.jsonl", [
            {"finding_id": "sf-002", "status": "valid",
             "changed_at": "2026-06-08T13:00:00Z"},
            {"finding_id": "sf-003", "status": "invalid",
             "changed_at": "2026-06-08T13:30:00Z"},
            # LAST row per finding_id wins.
            {"finding_id": "sf-003", "status": "in_review",
             "changed_at": "2026-06-08T14:00:00Z"},
        ])
    body = client.get("/api/human_todo").json()
    assert body["counts"]["finding_review"] == 2
    ids = [i["id"] for i in body["items"]]
    assert ids == ["sf-001", "sf-003"]  # oldest-first by promoted_at
    by_id = {i["id"]: i for i in body["items"]}
    assert by_id["sf-001"]["title"] == "still awaiting review"
    assert "in_review" in by_id["sf-003"]["detail"]
    assert "-m orchestrator.finding_session" in by_id["sf-001"]["resolve_command"]
    assert "start sf-001" in by_id["sf-001"]["resolve_command"]


# ─── bubble_ack ────────────────────────────────────────────────────────


def test_unacked_bubble_appears_and_acked_bubble_does_not(tmp_path):
    client = _client(tmp_path)
    _write_jsonl(tmp_path / "coord_memory" / "coordinator_bubbles.jsonl", [
        {"timestamp": "2026-06-09T10:06:00Z", "run_id": "cyc-001",
         "note": "eyeball this off-domain retrieval"},
        {"timestamp": "2026-06-09T11:35:00Z", "run_id": "cyc-002",
         "note": "ml-intern returned 0 papers"},
    ])
    _write_jsonl(tmp_path / "coord_memory" / "coordinator_acks.jsonl", [
        {"bubble_run_id": "cyc-001", "ack_by": "decross1",
         "ts": "2026-06-09T12:00:00Z"},
    ])
    body = client.get("/api/human_todo").json()
    assert body["counts"]["bubble_ack"] == 1
    [item] = body["items"]
    assert item["id"] == "cyc-002"
    assert item["title"] == "ml-intern returned 0 papers"
    assert "pending main-session blessing" in item["resolve_command"]


# ─── stale_active_run ──────────────────────────────────────────────────


def _write_active_run(tmp_path, payload: dict) -> None:
    path = tmp_path / "coord_run_state" / "active_run.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_stale_active_run_detected(tmp_path):
    client = _client(tmp_path)
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    _write_active_run(tmp_path, {
        "kind": "coordinator", "run_id": "cyc-leak",
        "started_at": _iso(old), "step_started_at": _iso(old),
    })
    body = client.get("/api/human_todo").json()
    assert body["counts"]["stale_active_run"] == 1
    [item] = body["items"]
    assert item["kind"] == "stale_active_run"
    assert item["title"] == (
        "investigate/clear stale active_run — possible lock-leak")


def test_fresh_active_run_is_not_a_todo(tmp_path):
    client = _client(tmp_path)
    now = datetime.now(timezone.utc)
    _write_active_run(tmp_path, {
        "kind": "coordinator", "run_id": "cyc-live",
        # started long ago but the CURRENT step is fresh: the freshest of the
        # two timestamps governs staleness.
        "started_at": _iso(now - timedelta(hours=3)),
        "step_started_at": _iso(now - timedelta(minutes=1)),
    })
    body = client.get("/api/human_todo").json()
    assert body["counts"]["stale_active_run"] == 0


def test_malformed_active_run_timestamps_are_not_stale(tmp_path):
    client = _client(tmp_path)
    _write_active_run(tmp_path, {
        "kind": "coordinator", "run_id": "cyc-garbled",
        "started_at": "not-a-timestamp", "step_started_at": None,
    })
    body = client.get("/api/human_todo").json()
    assert body["counts"]["stale_active_run"] == 0
    assert body["items"] == []


# ─── state_gate ────────────────────────────────────────────────────────


def test_state_gates_coerce_strings_and_objects(tmp_path):
    client = _client(tmp_path)
    path = tmp_path / "coord_run_state" / "week1.state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "human_gates_pending": [
            "review the day-3 retrospective",
            {"id": "gate-7", "title": "approve the lit-pipe rerun",
             "since": "2026-06-07T09:00:00Z"},
        ],
    }), encoding="utf-8")
    body = client.get("/api/human_todo").json()
    assert body["counts"]["state_gate"] == 2
    titles = {i["title"] for i in body["items"]}
    assert "review the day-3 retrospective" in titles
    assert "approve the lit-pipe rerun" in titles
    assert all(i["kind"] == "state_gate" for i in body["items"])


# ─── malformed lines + garbled files never 500 ─────────────────────────


def test_malformed_jsonl_lines_skipped(tmp_path):
    client = _client(tmp_path)
    path = tmp_path / "coord_memory" / "loop_memory.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"iteration_id":"iter-2026-06-09-001","gate_status":"pending",'
        '"ended_at":"2026-06-09T18:00:00Z","seed":{"topic":"survives noise"},'
        '"experiment_outcome":{"verdict":"supports"}}\n'
        "not-json-and-should-be-skipped\n"
        "42\n"  # valid JSON but not a row record
        '{"iteration_id":"iter-2026-06-09-002","gate_status":"pending"\n',
        encoding="utf-8",
    )
    body = client.get("/api/human_todo").json()
    assert body["counts"]["gate_verdict"] == 1
    assert body["items"][0]["id"] == "iter-2026-06-09-001"


def test_garbled_state_and_active_files_never_500(tmp_path):
    client = _client(tmp_path)
    run_state = tmp_path / "coord_run_state"
    run_state.mkdir(parents=True, exist_ok=True)
    (run_state / "active_run.json").write_text("{not json", encoding="utf-8")
    (run_state / "week1.state.json").write_text("[}", encoding="utf-8")
    resp = client.get("/api/human_todo")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


# ─── ordering ──────────────────────────────────────────────────────────


def test_items_sorted_oldest_first_across_kinds(tmp_path):
    client = _client(tmp_path)
    _write_jsonl(tmp_path / "coord_memory" / "loop_memory.jsonl", [
        {"iteration_id": "iter-2026-06-09-001", "gate_status": "pending",
         "ended_at": "2026-06-09T18:00:00Z", "seed": {"topic": "newer gate"},
         "experiment_outcome": {"verdict": "supports"}},
    ])
    _write_jsonl(tmp_path / "coord_memory" / "coordinator_bubbles.jsonl", [
        {"timestamp": "2026-06-08T10:00:00Z", "run_id": "cyc-old",
         "note": "older bubble"},
    ])
    body = client.get("/api/human_todo").json()
    assert [i["kind"] for i in body["items"]] == ["bubble_ack", "gate_verdict"]
    assert body["counts"]["gate_verdict"] == 1
    assert body["counts"]["bubble_ack"] == 1


# ─── live-ish: REAL primary-checkout dirs, read-only ───────────────────


def test_live_real_data_has_pending_gate_items_with_required_keys(tmp_path):
    """Cohort-invariant, count-agnostic live check: the real apparatus has
    >= 1 iteration awaiting a human gate verdict (11 at authoring time), and
    every composed item carries the full item shape. Read-only on the
    primary checkout; skips if the live artifact is absent (gitignored)."""
    live_memory = _PRIMARY_REPO / "memory"
    live_run_state = _PRIMARY_REPO / "run_state"
    if not (live_memory / "loop_memory.jsonl").exists():
        pytest.skip("live loop_memory.jsonl absent in this checkout")

    (tmp_path / "logs").mkdir(exist_ok=True)
    state = tmp_path / "state.json"
    state.write_text("{}", encoding="utf-8")
    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text("", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    app = create_app(
        logs_dir=tmp_path / "logs",
        telemetry_file=telemetry,
        state_file=state,
        bench_csv=tmp_path / "day1.csv",
        mtp_csv=tmp_path / "mtp.csv",
        loop_v0_repo=repo,
        loop_v0_run_state=tmp_path / "loop_run_state",
        loop_v0_journal=tmp_path / "journal",
        loop_v0_memory=tmp_path / "loop_memory.jsonl",
        coordinator_run_state=live_run_state,
        coordinator_memory=live_memory,
    )
    client = TestClient(app)
    resp = client.get("/api/human_todo")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body["counts"]) == set(KINDS)
    gate_items = [i for i in body["items"] if i["kind"] == "gate_verdict"]
    assert len(gate_items) >= 1
    assert body["counts"]["gate_verdict"] == len(gate_items)
    for item in body["items"]:
        assert _ITEM_KEYS <= set(item), f"item missing keys: {item}"
        assert item["kind"] in KINDS
        assert isinstance(item["title"], str) and item["title"]
        assert isinstance(item["resolve_command"], str) and item["resolve_command"]
    # Oldest-first ordering holds on live data too.
    sinces = [i["since"] for i in body["items"]]
    assert sinces == sorted(sinces)


# ─── dev-session deferrals (D-046 additive fold) ───────────────────────
# memory/dev_session_queue.jsonl is folded by ref_id, LAST status wins
# (defer appends status:"open", close appends status:"closed"). An item
# whose ref_id has an open deferral is tagged deferred: true (+ the
# deferral note/by/at) — STILL listed, STILL counted. No existing keys
# change on untagged items.


def _pending_gate_rows(tmp_path) -> None:
    _write_jsonl(tmp_path / "coord_memory" / "loop_memory.jsonl", [
        {"iteration_id": "iter-2026-06-09-001", "gate_status": "pending",
         "ended_at": "2026-06-09T18:00:00Z",
         "seed": {"topic": "deferral fold subject"},
         "experiment_outcome": {"verdict": "supports"}},
    ])


def test_open_deferral_tags_item_still_listed_and_counted(tmp_path):
    client = _client(tmp_path)
    _pending_gate_rows(tmp_path)
    _write_jsonl(tmp_path / "coord_memory" / "dev_session_queue.jsonl", [
        {"ref_id": "iter-2026-06-09-001", "kind": "gate_verdict",
         "note": "needs the primary session's judgement", "status": "open",
         "attested_by": "human:ui", "deferred_at": "2026-06-10T09:00:00Z"},
    ])
    body = client.get("/api/human_todo").json()
    # A deferral assigns the work; it does not resolve the item.
    assert body["counts"]["gate_verdict"] == 1
    [item] = body["items"]
    assert item["id"] == "iter-2026-06-09-001"
    assert item["deferred"] is True
    assert item["deferral"] == {
        "note": "needs the primary session's judgement",
        "by": "human:ui",
        "at": "2026-06-10T09:00:00Z",
    }
    # Existing item keys are intact alongside the additive tag.
    assert _ITEM_KEYS <= set(item)


def test_deferral_fold_last_status_wins_closed_untags(tmp_path):
    client = _client(tmp_path)
    _pending_gate_rows(tmp_path)
    _write_jsonl(tmp_path / "coord_memory" / "dev_session_queue.jsonl", [
        {"ref_id": "iter-2026-06-09-001", "kind": "gate_verdict",
         "note": "park it", "status": "open", "attested_by": "human:ui",
         "deferred_at": "2026-06-10T09:00:00Z"},
        {"ref_id": "iter-2026-06-09-001", "status": "closed",
         "note": "handled in dev session", "closed_by": "human",
         "closed_at": "2026-06-10T10:00:00Z"},
    ])
    body = client.get("/api/human_todo").json()
    # Item still pending (no loop_feedback row) but no longer deferred.
    assert body["counts"]["gate_verdict"] == 1
    [item] = body["items"]
    assert "deferred" not in item
    assert "deferral" not in item


def test_deferral_fold_reopen_after_close_wins_with_freshest_note(tmp_path):
    client = _client(tmp_path)
    _pending_gate_rows(tmp_path)
    _write_jsonl(tmp_path / "coord_memory" / "dev_session_queue.jsonl", [
        {"ref_id": "iter-2026-06-09-001", "kind": "gate_verdict",
         "note": "first deferral", "status": "open",
         "attested_by": "human:ui", "deferred_at": "2026-06-10T09:00:00Z"},
        {"ref_id": "iter-2026-06-09-001", "status": "closed",
         "note": "thought it was done", "closed_by": "human",
         "closed_at": "2026-06-10T10:00:00Z"},
        {"ref_id": "iter-2026-06-09-001", "kind": "gate_verdict",
         "note": "reopened — still unresolved", "status": "open",
         "attested_by": "human:ui", "deferred_at": "2026-06-10T11:00:00Z"},
    ])
    body = client.get("/api/human_todo").json()
    [item] = body["items"]
    assert item["deferred"] is True
    assert item["deferral"]["note"] == "reopened — still unresolved"
    assert item["deferral"]["at"] == "2026-06-10T11:00:00Z"


def test_deferral_tags_non_gate_kinds_too(tmp_path):
    client = _client(tmp_path)
    _write_jsonl(tmp_path / "coord_memory" / "coordinator_bubbles.jsonl", [
        {"timestamp": "2026-06-09T10:06:00Z", "run_id": "cyc-007",
         "note": "eyeball this retrieval"},
    ])
    _write_jsonl(tmp_path / "coord_memory" / "dev_session_queue.jsonl", [
        {"ref_id": "cyc-007", "kind": "bubble_ack",
         "note": "ack after the rerun", "status": "open",
         "attested_by": "human:ui", "deferred_at": "2026-06-10T09:30:00Z"},
    ])
    body = client.get("/api/human_todo").json()
    assert body["counts"]["bubble_ack"] == 1
    [item] = body["items"]
    assert item["kind"] == "bubble_ack"
    assert item["deferred"] is True
    assert item["deferral"]["by"] == "human:ui"


def test_deferral_for_unknown_ref_id_is_ignored(tmp_path):
    client = _client(tmp_path)
    _pending_gate_rows(tmp_path)
    _write_jsonl(tmp_path / "coord_memory" / "dev_session_queue.jsonl", [
        {"ref_id": "no-such-item", "kind": "finding_review",
         "note": "orphan deferral", "status": "open",
         "attested_by": "human:ui", "deferred_at": "2026-06-10T09:00:00Z"},
    ])
    body = client.get("/api/human_todo").json()
    assert body["counts"]["gate_verdict"] == 1
    [item] = body["items"]
    assert "deferred" not in item    # the orphan tags nothing


def test_undeferred_items_gain_no_new_keys(tmp_path):
    """No existing keys change — and items WITHOUT an open deferral keep
    exactly the pre-fold shape (the additive keys appear only on tagged
    items)."""
    client = _client(tmp_path)
    _pending_gate_rows(tmp_path)
    # An absent dev_session_queue.jsonl is the common live case.
    body = client.get("/api/human_todo").json()
    [item] = body["items"]
    assert set(item) == _ITEM_KEYS


def test_malformed_dev_queue_rows_never_500(tmp_path):
    client = _client(tmp_path)
    _pending_gate_rows(tmp_path)
    path = tmp_path / "coord_memory" / "dev_session_queue.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "not-json\n"
        "42\n"                                   # JSON, but not a row record
        '{"status": "open", "note": "row with no ref_id"}\n'
        '{"ref_id": "", "status": "open"}\n'     # empty ref_id: skipped
        '{"ref_id": "iter-2026-06-09-001", "status": "wat"}\n'  # unknown status
        '{"ref_id": "iter-2026-06-09-001", "kind": "gate_verdict",'
        ' "note": "survives noise", "status": "open",'
        ' "attested_by": "human:ui", "deferred_at": "2026-06-10T09:00:00Z"}\n',
        encoding="utf-8",
    )
    resp = client.get("/api/human_todo")
    assert resp.status_code == 200
    [item] = resp.json()["items"]
    assert item["deferred"] is True
    assert item["deferral"]["note"] == "survives noise"
