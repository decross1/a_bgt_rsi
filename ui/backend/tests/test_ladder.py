"""GET /api/ladder tests (UI simplification S1).

Side-effect-free: the LEDGER path points at tmp_path (the
test_loop_alert.py TestClient idiom), while ``loop_v0_repo`` points at
the REAL repo root so the handler's lazy import runs the REAL reducer
(workers/idea_ledger.py) over the fixture events — the projection under
test is the production one, not a stub. Covers: absent ledger = 204,
happy reduction (clusters / histogram / counts / agenda / next_owed),
and a malformed ledger = honest 500 (rule 4, never coerced).
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app

# ui/backend/tests/test_ladder.py -> parents[3] == the repo root (carries
# workers/). The handler puts this on sys.path for its lazy import.
REPO_ROOT = Path(__file__).resolve().parents[3]


def _client(tmp_path) -> TestClient:
    (tmp_path / "logs").mkdir(exist_ok=True)
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"current_day": "ladder"}), encoding="utf-8")
    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text("", encoding="utf-8")
    bench = tmp_path / "day1.csv"
    bench.write_text(
        "prompt_idx,completion_tokens,elapsed_s,decode_tok_per_s\n0,256,8.0,32.0\n",
        encoding="utf-8",
    )
    loop_run_state = tmp_path / "loop_run_state"
    loop_run_state.mkdir(exist_ok=True)
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir(exist_ok=True)

    app = create_app(
        logs_dir=tmp_path / "logs",
        telemetry_file=telemetry,
        state_file=state,
        bench_csv=bench,
        mtp_csv=tmp_path / "mtp.csv",
        # REAL repo root: the ladder handler must import the real reducer.
        loop_v0_repo=REPO_ROOT,
        loop_v0_run_state=loop_run_state,
        loop_v0_journal=journal_dir,
        loop_v0_memory=tmp_path / "loop_memory.jsonl",
        # Dirs intentionally NOT pre-created: the absent-ledger test relies
        # on that.
        coordinator_run_state=tmp_path / "coord_run_state",
        coordinator_memory=tmp_path / "coord_memory",
    )
    return TestClient(app)


# Schema-valid event fixture (validated against schema/idea_ledger.schema.json
# by the real load_state): one surfaced L4 cluster with an elite claim, one
# killed cluster with an evidence-keyed reopening condition, one open cluster
# carrying a pending agenda item.
FIXTURE_EVENTS = [
    {"event_type": "cluster_created", "ts": "2026-08-01T00:00:00Z",
     "cluster_id": "cl-a", "member_id": "iter-001", "origin": "consolidation",
     "iteration_id": "iter-001",
     "claim": {"problem": "KV-cache eviction bias", "mechanism": "m",
               "predicted_effect": "p"}},
    {"event_type": "evidence_level_changed", "ts": "2026-08-02T00:00:00Z",
     "cluster_id": "cl-a", "evidence_level": "L4"},
    {"event_type": "cluster_created", "ts": "2026-08-01T01:00:00Z",
     "cluster_id": "cl-b", "member_id": "iter-002", "origin": "consolidation"},
    {"event_type": "cluster_killed", "ts": "2026-08-03T00:00:00Z",
     "cluster_id": "cl-b",
     "kill_reason": {"code": "redteam_fatal_flaw",
                     "evidence_key": "iteration:iter-002:redteam",
                     "detail": "redteam verdict fatal_flaw on iteration iter-002"},
     "reopening_condition": {"requires": "new_evidence",
                             "evidence_kind": "counterexample_run"}},
    {"event_type": "cluster_created", "ts": "2026-08-01T02:00:00Z",
     "cluster_id": "cl-c", "member_id": "iter-003", "origin": "consolidation"},
    {"event_type": "agenda_item_added", "ts": "2026-08-04T00:00:00Z",
     "cluster_id": "cl-c", "topic": "probe the eviction schedule",
     "source": "paper_gap"},
]


def _write_ledger(tmp_path, lines: list[str]) -> None:
    memory = tmp_path / "coord_memory"
    memory.mkdir(parents=True, exist_ok=True)
    (memory / "idea_ledger.jsonl").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def _write_sources(
    tmp_path,
    iterations: list[dict],
    *,
    surfaced: list[dict] | None = None,
    feedback: list[dict] | None = None,
) -> None:
    memory = tmp_path / "coord_memory"
    memory.mkdir(parents=True, exist_ok=True)
    for name, rows in (
        ("loop_memory.jsonl", iterations),
        ("surfaced_findings.jsonl", surfaced or []),
        ("loop_feedback.jsonl", feedback or []),
    ):
        (memory / name).write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )


def test_ladder_absent_is_204(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/ladder")
    assert resp.status_code == 204


def test_ladder_reduces_fixture_ledger(tmp_path):
    client = _client(tmp_path)
    _write_ledger(tmp_path, [json.dumps(e) for e in FIXTURE_EVENTS])
    _write_sources(
        tmp_path,
        [
            {
                "iteration_id": "iter-001",
                "hypothesis": {"text": "A bounded legacy test claim."},
                "retrieval": {"relevance": {"low_confidence": False}},
                "novelty": {"class": "novel"},
                "critique": {"verdict": "survives"},
                "redteam": {"verdict": "proceed"},
                "experiment_outcome": {
                    "trials": 30, "summary": "Recorded synthetic result."
                },
                "cross_tier_comparison": {"replicated": True},
            },
            {"iteration_id": "iter-002", "hypothesis": {"text": "Killed."}},
            {"iteration_id": "iter-003", "hypothesis": {"text": "Open."}},
        ],
        surfaced=[{
            "finding_id": "sf-iter-001",
            "source_iteration_id": "iter-001",
            "promoted_at": "2026-08-02T00:00:00Z",
            "adversarial": {"survived": True},
        }],
    )
    resp = client.get("/api/ladder")
    assert resp.status_code == 200
    body = resp.json()

    # Clusters: sorted by cluster_id, one row each, projection fields present.
    by_id = {c["cluster_id"]: c for c in body["clusters"]}
    assert list(by_id) == ["cl-a", "cl-b", "cl-c"]

    a = by_id["cl-a"]
    assert a["status"] == "surfaced"
    assert a["evidence_level"] == "L4"
    assert a["historical_evidence_level"] == "L4"
    assert a["evidence_qualification"] == {
        "status": "rederived",
        "exact_source_count": 1,
        "unresolved_member_count": 0,
        "provisional": [],
    }
    assert a["claim_source_status"] == "legacy_unverified"
    assert a["stem"] == "KV-cache eviction bias"  # elite claim's problem
    assert a["member_count"] == 1
    # The member IDS ship too (R1 peek panel links iteration-shaped members
    # onward to /dossier/:id) — member_count stays their length.
    assert a["members"] == ["iter-001"]
    assert a["origin"] == "consolidation"
    assert a["kill_reason"] is None

    b = by_id["cl-b"]
    assert b["status"] == "killed"
    assert b["kill_reason"]["code"] == "redteam_fatal_flaw"
    assert b["reopening_condition"]["evidence_kind"] == "counterexample_run"

    c = by_id["cl-c"]
    assert c["status"] == "open"
    assert c["open_agenda_count"] == 1

    # Counts + histogram (histogram is live rungs only — killed excluded).
    assert body["counts"] == {"open": 1, "surfaced": 1, "killed": 1}
    assert body["histogram"] == {"L0": 1, "L1": 0, "L2": 0, "L3": 0,
                                 "L4": 1, "L5": 0}

    # Agenda: the projection's open-items view with provenance.
    assert body["agenda"] == [{"topic": "probe the eviction schedule",
                               "source": "paper_gap", "cluster_id": "cl-c"}]

    # next_owed names a test for every rung (the histogram's labels).
    assert sorted(body["next_owed"]) == ["L0", "L1", "L2", "L3", "L4", "L5"]
    assert all(isinstance(v, str) and v for v in body["next_owed"].values())


def test_ladder_rederives_stale_v2_rung_and_labels_recovered_source(tmp_path):
    client = _client(tmp_path)
    events = [
        {
            "event_type": "cluster_created",
            "ts": "2026-09-15T00:00:00Z",
            "cluster_id": "cl-raw",
            "member_id": "iter-raw",
            "origin": "consolidation",
        },
        {
            "event_type": "evidence_level_changed",
            "ts": "2026-09-15T00:01:00Z",
            "cluster_id": "cl-raw",
            "evidence_level": "L1",
        },
    ]
    _write_ledger(tmp_path, [json.dumps(event) for event in events])
    _write_sources(tmp_path, [{
        "iteration_id": "iter-raw",
        "campaign": {"schema_version": "research-campaign-link/v1"},
        "hypothesis": {
            "text": '{"chosen":"Readable recovered claim","candidates":["x"]}',
            "candidates_considered": 1,
        },
        "retrieval": {"relevance": {"low_confidence": False}},
        "novelty": {"class": "novel"},
        "critique": {"verdict": "survives"},
    }])

    body = client.get("/api/ladder").json()
    cluster = body["clusters"][0]
    assert cluster["historical_evidence_level"] == "L1"
    assert cluster["evidence_level"] == "L0"
    assert cluster["historical_status"] == "open"
    assert cluster["status"] == "open"
    assert cluster["claim_source_status"] == "v2_contract_invalid"
    assert cluster["evidence_qualification"]["status"] == "rederived"
    assert body["histogram"] == {
        "L0": 1, "L1": 0, "L2": 0, "L3": 0, "L4": 0, "L5": 0,
    }


def test_ladder_duplicate_member_source_has_no_effective_rung(tmp_path):
    client = _client(tmp_path)
    _write_ledger(tmp_path, [json.dumps({
        "event_type": "cluster_created",
        "ts": "2026-09-15T00:00:00Z",
        "cluster_id": "cl-ambiguous",
        "member_id": "iter-duplicate",
        "origin": "consolidation",
        "evidence_level": "L1",
    })])
    _write_sources(tmp_path, [
        {"iteration_id": "iter-duplicate", "hypothesis": {"text": "first"}},
        {"iteration_id": "iter-duplicate", "hypothesis": {"text": "second"}},
    ])

    cluster = client.get("/api/ladder").json()["clusters"][0]
    assert cluster["historical_evidence_level"] == "L1"
    assert cluster["evidence_level"] is None
    assert cluster["evidence_qualification"] == {
        "status": "source_ambiguous",
        "exact_source_count": 0,
        "unresolved_member_count": 1,
        "provisional": [],
    }


def test_ladder_duplicate_finding_cannot_donate_adversarial_rung(tmp_path):
    client = _client(tmp_path)
    _write_ledger(tmp_path, [
        json.dumps({
            "event_type": "cluster_created",
            "ts": "2026-08-01T00:00:00Z",
            "cluster_id": "cl-duplicate-finding",
            "member_id": "iter-duplicate-finding",
            "origin": "consolidation",
        }),
        json.dumps({
            "event_type": "evidence_level_changed",
            "ts": "2026-08-02T00:00:00Z",
            "cluster_id": "cl-duplicate-finding",
            "evidence_level": "L4",
        }),
    ])
    _write_sources(
        tmp_path,
        [{
            "iteration_id": "iter-duplicate-finding",
            "hypothesis": {"text": "A bounded legacy test claim."},
            "retrieval": {"relevance": {"low_confidence": False}},
            "novelty": {"class": "novel"},
            "critique": {"verdict": "survives"},
            "redteam": {"verdict": "proceed"},
            "experiment_outcome": {"trials": 30, "summary": "Recorded."},
            "cross_tier_comparison": {"replicated": True},
        }],
        surfaced=[
            {
                "finding_id": "sf-iter-duplicate-finding",
                "source_iteration_id": "iter-duplicate-finding",
                "promoted_at": "2026-08-02T00:00:00Z",
                "adversarial": {"survived": True},
            },
            {
                "finding_id": "sf-iter-duplicate-finding",
                "source_iteration_id": "iter-duplicate-finding",
                "promoted_at": "2026-08-02T00:01:00Z",
                "adversarial": {"survived": True},
            },
        ],
    )

    cluster = client.get("/api/ladder").json()["clusters"][0]
    assert cluster["historical_evidence_level"] == "L4"
    assert cluster["evidence_level"] == "L3"
    assert cluster["status"] == "open"


def test_ladder_malformed_ledger_is_honest_500(tmp_path):
    client = _client(tmp_path)
    _write_ledger(tmp_path, [json.dumps(FIXTURE_EVENTS[0]), "{not json"])
    resp = client.get("/api/ladder")
    assert resp.status_code == 500
    assert "idea_ledger unreadable" in resp.json()["detail"]


def test_ladder_schema_invalid_event_is_honest_500(tmp_path):
    # A structurally-valid JSON line that violates the event schema (unknown
    # kill code) must be a LOUD 500, never a silently thinner state (rule 4).
    bad = dict(FIXTURE_EVENTS[3])
    bad["kill_reason"] = {"code": "vibes", "evidence_key": "x", "detail": "d"}
    client = _client(tmp_path)
    _write_ledger(
        tmp_path,
        [json.dumps(FIXTURE_EVENTS[0]), json.dumps(FIXTURE_EVENTS[2]),
         json.dumps(bad)],
    )
    resp = client.get("/api/ladder")
    assert resp.status_code == 500
    assert "idea_ledger unreadable" in resp.json()["detail"]
