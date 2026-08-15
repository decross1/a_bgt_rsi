"""GET /api/lab_todo tests (the lab's own queue).

Side-effect-free: the LEDGER + run_state paths point at tmp_path (the
test_ladder.py TestClient idiom) while ``loop_v0_repo`` points at the REAL
repo root, so the handler's lazy import runs the REAL reducer
(workers/idea_ledger.py) and the REAL projection (workers/idea_projection.py)
over the fixture events.

``assess_state`` is MONKEYPATCHED in the gap tests: its real implementation
folds in ``ladder_gaps(load_state(DEFAULT_IDEA_LEDGER))`` off the PRIMARY
checkout's ledger (a hard-coded path this endpoint cannot redirect), so a test
asserting on real gap text would read live apparatus state and decay. One test
deliberately does NOT patch it, to pin the production call wiring (kwarg names,
import path) without asserting volatile content.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app

# ui/backend/tests/test_lab_todo.py -> parents[3] == the repo root (carries
# orchestrator/ + workers/). The handler puts this on sys.path for its lazy
# imports; the tests need it up front to monkeypatch the module object.
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from orchestrator import coordinator as coordinator_mod  # noqa: E402

# The two "await human" gap shapes, spelled exactly as
# orchestrator/coordinator.py's assess_state emits them (and as
# nara_daemon.HUMAN_GAP_MARKERS matches them).
HUMAN_GAP_VERDICT = "3 recent iteration(s) await a human gate verdict"
HUMAN_GAP_REVIEW = "2 surfaced finding(s) await human review"
AGENT_GAP_LADDER = "4 open cluster(s) at L1 awaiting synthetic experiment"
AGENT_GAP_STALE = "loop has not iterated in 6 days"


def _client(tmp_path) -> TestClient:
    (tmp_path / "logs").mkdir(exist_ok=True)
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"current_day": "lab_todo"}), encoding="utf-8")
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
        # REAL repo root: the handler must import the real coordinator +
        # reducer + projection.
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


def _stub_gaps(monkeypatch, gaps: list[str]) -> None:
    """Pin assess_state to a fixed gap list (everything else empty)."""
    monkeypatch.setattr(
        coordinator_mod,
        "assess_state",
        lambda **kwargs: {"gaps": list(gaps)},
    )


def _block_coordinator_import(monkeypatch) -> None:
    """Reproduce the PRODUCTION venv: `from orchestrator import coordinator`
    raises ModuleNotFoundError('openai'). The module is already in sys.modules
    here, so the block has to happen at the __import__ hook — which is exactly
    where CPython dispatches the statement."""
    import builtins

    real_import = builtins.__import__

    def blocked(name, globals=None, locals=None, fromlist=(), level=0):
        if name.startswith("orchestrator.coordinator") or (
            name == "orchestrator" and "coordinator" in (fromlist or ())
        ):
            raise ModuleNotFoundError("No module named 'openai'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", blocked)


# Schema-valid fixture (validated against schema/idea_ledger.schema.json by
# the real load_state): two OPEN clusters sharing L1, one OPEN at L0, one
# killed on a redteam fatal flaw (refinable), one killed by a paper prior that
# has ALREADY been refined, one killed on a null experiment result (NOT
# refinable), and a pending agenda item.
FIXTURE_EVENTS = [
    # cl-a, cl-b: both open at L1 -> one owed group of 2.
    {"event_type": "cluster_created", "ts": "2026-08-01T00:00:00Z",
     "cluster_id": "cl-a", "member_id": "iter-001", "origin": "consolidation",
     "iteration_id": "iter-001",
     "claim": {"problem": "KV-cache eviction bias", "mechanism": "m",
               "predicted_effect": "p"}},
    {"event_type": "evidence_level_changed", "ts": "2026-08-02T00:00:00Z",
     "cluster_id": "cl-a", "evidence_level": "L1"},
    {"event_type": "cluster_created", "ts": "2026-08-01T01:00:00Z",
     "cluster_id": "cl-b", "member_id": "iter-002", "origin": "consolidation",
     "iteration_id": "iter-002",
     "claim": {"problem": "router entropy collapse", "mechanism": "m",
               "predicted_effect": "p"}},
    {"event_type": "evidence_level_changed", "ts": "2026-08-02T01:00:00Z",
     "cluster_id": "cl-b", "evidence_level": "L1"},
    # cl-c: open at L0 (default) + a pending agenda item.
    {"event_type": "cluster_created", "ts": "2026-08-01T02:00:00Z",
     "cluster_id": "cl-c", "member_id": "iter-003", "origin": "consolidation"},
    {"event_type": "agenda_item_added", "ts": "2026-08-04T00:00:00Z",
     "cluster_id": "cl-c", "topic": "probe the eviction schedule",
     "source": "paper_gap"},
    # cl-d: killed on a redteam fatal flaw, never refined -> a candidate.
    {"event_type": "cluster_created", "ts": "2026-08-01T03:00:00Z",
     "cluster_id": "cl-d", "member_id": "iter-004", "origin": "consolidation",
     "iteration_id": "iter-004",
     "claim": {"problem": "speculative decode drift", "mechanism": "m",
               "predicted_effect": "p"}},
    {"event_type": "cluster_killed", "ts": "2026-08-03T00:00:00Z",
     "cluster_id": "cl-d",
     "kill_reason": {"code": "redteam_fatal_flaw",
                     "evidence_key": "iteration:iter-004:redteam",
                     "detail": "redteam verdict fatal_flaw on iteration iter-004"},
     "reopening_condition": {"requires": "new_evidence",
                             "evidence_kind": "counterexample_run"}},
    # cl-e: a pre-closed paper niche (the reducer's own paper_prior_exists
    # kill) that has ALREADY been refined -> NOT a candidate.
    {"event_type": "niche_seeded", "ts": "2026-08-01T04:00:00Z",
     "cluster_id": "cl-e",
     "paper": {"arxiv_id": "2508.00001", "title": "Sparse MoE routing priors"}},
    {"event_type": "cluster_refined", "ts": "2026-08-05T00:00:00Z",
     "cluster_id": "cl-e", "round": 1,
     "refined_claim": "narrowed to long-context routing only"},
    # cl-f: killed on a null experiment result -> NOT refinable (died on a
    # RESULT, not a critique).
    {"event_type": "cluster_created", "ts": "2026-08-01T05:00:00Z",
     "cluster_id": "cl-f", "member_id": "iter-006", "origin": "consolidation"},
    {"event_type": "cluster_killed", "ts": "2026-08-03T02:00:00Z",
     "cluster_id": "cl-f",
     "kill_reason": {"code": "experiment_null_effect",
                     "evidence_key": "iteration:iter-006:experiment",
                     "detail": "no effect at n=200"},
     "reopening_condition": {"requires": "new_evidence",
                             "evidence_kind": "higher_powered_run"}},
]


def _write_ledger(tmp_path, lines: list[str]) -> None:
    memory = tmp_path / "coord_memory"
    memory.mkdir(parents=True, exist_ok=True)
    (memory / "idea_ledger.jsonl").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def test_lab_todo_absent_ledger_still_returns_gaps(tmp_path, monkeypatch):
    # A cold checkout has no ledger. That is NOT an error — the gaps still
    # ship, the ledger-derived lists are honestly empty (never a 500).
    _stub_gaps(monkeypatch, [AGENT_GAP_STALE, HUMAN_GAP_VERDICT])
    client = _client(tmp_path)
    resp = client.get("/api/lab_todo")
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent_gaps"] == [AGENT_GAP_STALE]
    assert body["human_gaps"] == [HUMAN_GAP_VERDICT]
    assert body["owed"] == []
    assert body["agenda"] == []
    assert body["refine_candidates"] == []
    assert body["generated_at"].endswith("Z")


def test_lab_todo_splits_gaps_by_the_human_markers(tmp_path, monkeypatch):
    # The split rule is nara_daemon's own (HUMAN_GAP_MARKERS): a gap carrying
    # "await a human gate verdict" or "await human review" is HUMAN-owed;
    # EVERYTHING else is agent-actionable. The two lists partition `gaps`.
    gaps = [AGENT_GAP_LADDER, HUMAN_GAP_VERDICT, AGENT_GAP_STALE,
            HUMAN_GAP_REVIEW]
    _stub_gaps(monkeypatch, gaps)
    client = _client(tmp_path)
    body = client.get("/api/lab_todo").json()

    assert body["agent_gaps"] == [AGENT_GAP_LADDER, AGENT_GAP_STALE]
    assert body["human_gaps"] == [HUMAN_GAP_VERDICT, HUMAN_GAP_REVIEW]
    # Exact complements — no gap is dropped, none is double-counted.
    assert sorted(body["agent_gaps"] + body["human_gaps"]) == sorted(gaps)


def test_lab_todo_gap_split_matches_the_daemon(tmp_path, monkeypatch):
    # The rule is the DAEMON's, not a second opinion: whatever work_exists
    # would treat as actionable is exactly this endpoint's agent_gaps.
    from orchestrator import nara_daemon

    gaps = [AGENT_GAP_LADDER, HUMAN_GAP_VERDICT, HUMAN_GAP_REVIEW]
    _stub_gaps(monkeypatch, gaps)
    client = _client(tmp_path)
    body = client.get("/api/lab_todo").json()
    assert body["agent_gaps"] == nara_daemon.agent_actionable_gaps(gaps)


def test_human_gap_markers_mirror_the_daemon():
    # lab_todo.py MIRRORS the markers rather than importing them (the daemon
    # is unimportable on the production ui/.venv — no `openai`). This is the
    # pin that makes the mirror safe: drift in the daemon fails HERE.
    from orchestrator import nara_daemon

    from backend.lab_todo import HUMAN_GAP_MARKERS

    assert HUMAN_GAP_MARKERS == nara_daemon.HUMAN_GAP_MARKERS


def test_lab_todo_falls_back_to_the_last_cycles_persisted_gaps(
    tmp_path, monkeypatch
):
    # The PRODUCTION path: the live :8700 backend runs from ui/.venv, where
    # `import orchestrator.coordinator` raises ModuleNotFoundError (it pulls
    # agent_wrapper.wrapper -> openai). The endpoint must still answer, from
    # the gaps the coordinator PERSISTED on its last cycle — and must SAY so.
    run_state = tmp_path / "coord_run_state"
    run_state.mkdir(parents=True, exist_ok=True)
    (run_state / "coordinator_cycles.jsonl").write_text(
        "\n".join([
            json.dumps({"timestamp": "2026-08-15T10:00:00Z", "run_id": "c1",
                        "planner_state": {"gaps": ["stale gap, older cycle"]}}),
            json.dumps({"timestamp": "2026-08-15T19:00:00Z", "run_id": "c2",
                        "planner_state": {"gaps": [AGENT_GAP_LADDER,
                                                   HUMAN_GAP_VERDICT]}}),
        ]) + "\n",
        encoding="utf-8",
    )
    _block_coordinator_import(monkeypatch)
    client = _client(tmp_path)
    body = client.get("/api/lab_todo").json()

    # NEWEST cycle's gaps, split by the same rule.
    assert body["agent_gaps"] == [AGENT_GAP_LADDER]
    assert body["human_gaps"] == [HUMAN_GAP_VERDICT]
    # The degraded path NAMES itself and dates itself (rule 7) — the UI must
    # be able to say "as of the last cycle", never imply the gaps are live.
    assert body["gaps_source"] == "last_cycle"
    assert body["gaps_as_of"] == "2026-08-15T19:00:00Z"


def test_lab_todo_gaps_unavailable_is_named_not_faked(tmp_path, monkeypatch):
    # Coordinator unimportable AND no cycle has ever persisted gaps: the
    # honest answer is "unavailable", never an empty list that reads as
    # "the lab has nothing to do".
    _block_coordinator_import(monkeypatch)
    client = _client(tmp_path)
    body = client.get("/api/lab_todo").json()
    assert body["gaps_source"] == "unavailable"
    assert body["agent_gaps"] == []
    assert body["human_gaps"] == []
    assert body["gaps_as_of"] is None


def test_lab_todo_live_path_is_named_and_undated(tmp_path, monkeypatch):
    _stub_gaps(monkeypatch, [AGENT_GAP_STALE])
    client = _client(tmp_path)
    body = client.get("/api/lab_todo").json()
    assert body["gaps_source"] == "assess_state"
    assert body["gaps_as_of"] is None  # live: as of generated_at


def test_lab_todo_groups_open_clusters_by_the_test_owed(tmp_path, monkeypatch):
    _stub_gaps(monkeypatch, [])
    client = _client(tmp_path)
    _write_ledger(tmp_path, [json.dumps(e) for e in FIXTURE_EVENTS])
    resp = client.get("/api/lab_todo")
    assert resp.status_code == 200
    body = resp.json()

    # Owed groups: rung-ordered, one per rung with OPEN clusters. (L4/L5
    # derive status "surfaced", so open groups top out at L3.)
    assert [g["rung"] for g in body["owed"]] == ["L0", "L1"]
    by_rung = {g["rung"]: g for g in body["owed"]}
    assert [c["cluster_id"] for c in by_rung["L1"]["clusters"]] == ["cl-a", "cl-b"]
    assert [c["cluster_id"] for c in by_rung["L0"]["clusters"]] == ["cl-c"]

    # The test text is the projection's own next-owed string (what ideas.md
    # shows), never a second wording invented here.
    from workers import idea_projection
    assert by_rung["L1"]["test"] == idea_projection._owed("L1")
    assert by_rung["L0"]["test"] == idea_projection._owed("L0")

    # Cluster rows carry the projection's stem + the ledger's own timestamp.
    a = by_rung["L1"]["clusters"][0]
    assert a["stem"] == "KV-cache eviction bias"
    assert a["last_event_ts"] == "2026-08-02T00:00:00Z"

    # Agenda is the projection's open-items view with provenance.
    assert body["agenda"] == [{"topic": "probe the eviction schedule",
                               "source": "paper_gap", "cluster_id": "cl-c"}]


def test_lab_todo_refine_candidates_are_critique_kills_never_refined(
    tmp_path, monkeypatch
):
    _stub_gaps(monkeypatch, [])
    client = _client(tmp_path)
    _write_ledger(tmp_path, [json.dumps(e) for e in FIXTURE_EVENTS])
    body = client.get("/api/lab_todo").json()

    # cl-d only: cl-e already has refine_history, cl-f died on a RESULT
    # (experiment_null_effect), which no re-articulation can argue away.
    assert body["refine_candidates"] == [
        {"cluster_id": "cl-d", "stem": "speculative decode drift",
         "kill_code": "redteam_fatal_flaw"},
    ]


def test_lab_todo_refine_candidates_are_capped_newest_first(tmp_path, monkeypatch):
    # The paper-seeded graveyard is thousands of pre-closed clusters; the
    # list is a CAPPED, newest-first slice, not the whole graveyard.
    _stub_gaps(monkeypatch, [])
    events = [
        {"event_type": "niche_seeded", "ts": f"2026-08-01T00:{i:02d}:00Z",
         "cluster_id": f"cl-p{i:02d}",
         "paper": {"arxiv_id": f"2508.{i:05d}", "title": f"paper {i}"}}
        for i in range(20)
    ]
    client = _client(tmp_path)
    _write_ledger(tmp_path, [json.dumps(e) for e in events])
    body = client.get("/api/lab_todo").json()

    ids = [c["cluster_id"] for c in body["refine_candidates"]]
    assert len(ids) == 12
    assert ids[0] == "cl-p19"   # newest last_event_ts first
    assert ids[-1] == "cl-p08"


def test_lab_todo_malformed_ledger_is_honest_500(tmp_path, monkeypatch):
    _stub_gaps(monkeypatch, [AGENT_GAP_STALE])
    client = _client(tmp_path)
    _write_ledger(tmp_path, [json.dumps(FIXTURE_EVENTS[0]), "{not json"])
    resp = client.get("/api/lab_todo")
    # A broken ledger is a LOUD failure — never a "thin but 200" payload that
    # would read as "the lab has nothing queued" (rule 4).
    assert resp.status_code == 500
    assert "idea_ledger unreadable" in resp.json()["detail"]


def test_lab_todo_schema_invalid_event_is_honest_500(tmp_path, monkeypatch):
    # Structurally-valid JSON that violates the event schema (unknown kill
    # code) is equally loud.
    _stub_gaps(monkeypatch, [])
    bad = dict(FIXTURE_EVENTS[7])
    bad["kill_reason"] = {"code": "vibes", "evidence_key": "x", "detail": "d"}
    client = _client(tmp_path)
    _write_ledger(
        tmp_path,
        [json.dumps(FIXTURE_EVENTS[6]), json.dumps(bad)],
    )
    resp = client.get("/api/lab_todo")
    assert resp.status_code == 500
    assert "idea_ledger unreadable" in resp.json()["detail"]


def test_lab_todo_real_assess_state_wiring(tmp_path):
    # NO monkeypatch: pins the production call (import path + kwarg names) so
    # a renamed parameter fails here instead of at :8700. Asserts only SHAPE —
    # the gap CONTENT is live apparatus state and would decay.
    client = _client(tmp_path)
    resp = client.get("/api/lab_todo")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["agent_gaps"], list)
    assert isinstance(body["human_gaps"], list)
    assert all(isinstance(g, str) for g in body["agent_gaps"] + body["human_gaps"])
