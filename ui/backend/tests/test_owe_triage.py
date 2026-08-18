"""Owe-card triage enrichment tests (owner ask 2026-08-18: make "What you
owe" legible — action phrase, what approval means, vet-first bullets, and
documented superseded/observable heuristics off memory/idea_ledger.jsonl).

Fixture-driven and side-effect-free (tmp_path only, mirrors
test_human_todo.py). The pins:

- H-KILL: an item whose cluster has a ``cluster_killed`` ledger event tags
  ``likely_superseded`` — and stays LISTED and COUNTED (a tag never
  dismisses).
- self-cited kills (evidence_key names the item's own iteration/experiment)
  say so in the reason.
- H-OBS: bubble_ack / stale_active_run tag ``observable``.
- a fresh item with no supersession signal tags ``valid``.
- derived fields ride the live endpoint additively; the frozen item keys
  are untouched.
- an absent or garbled ledger never 500s and never strips the queue.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.owe_triage import enrich_items

_ITEM_KEYS = {"kind", "id", "title", "since", "detail", "resolve_command"}


def _client(tmp_path) -> TestClient:
    """TestClient with every path at tmp_path (test_human_todo idiom)."""
    (tmp_path / "logs").mkdir(exist_ok=True)
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"current_day": "owe_triage"}), encoding="utf-8")
    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text("", encoding="utf-8")
    bench = tmp_path / "day1.csv"
    bench.write_text(
        "prompt_idx,completion_tokens,elapsed_s,decode_tok_per_s\n0,256,8.0,32.0\n",
        encoding="utf-8",
    )
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    loop_run_state = tmp_path / "loop_run_state"
    loop_run_state.mkdir(exist_ok=True)
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir(exist_ok=True)
    return TestClient(create_app(
        logs_dir=tmp_path / "logs",
        telemetry_file=telemetry,
        state_file=state,
        bench_csv=bench,
        mtp_csv=tmp_path / "mtp.csv",
        loop_v0_repo=repo,
        loop_v0_run_state=loop_run_state,
        loop_v0_journal=journal_dir,
        loop_v0_memory=tmp_path / "loop_memory.jsonl",
        coordinator_run_state=tmp_path / "coord_run_state",
        coordinator_memory=tmp_path / "coord_memory",
    ))


def _write_jsonl(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r) if not isinstance(r, str) else r for r in rows)
        + "\n",
        encoding="utf-8",
    )


def _gate_item(item_id: str, **extra) -> dict:
    item = {
        "kind": "gate_verdict", "id": item_id, "title": f"topic of {item_id}",
        "since": "2026-06-05T20:00:00Z", "detail": "awaiting verdict",
        "resolve_command": "gate_cli ...",
    }
    item.update(extra)
    return item


# --- unit: the heuristics on fixtures -------------------------------------

def test_killed_cluster_item_tags_likely_superseded(tmp_path):
    _write_jsonl(tmp_path / "idea_ledger.jsonl", [
        {"event_type": "cluster_created", "ts": "2026-08-15T01:00:00Z",
         "cluster_id": "cl-iter-A", "member_id": "iter-A",
         "iteration_id": "iter-A", "origin": "consolidation"},
        {"event_type": "cluster_killed", "ts": "2026-08-15T01:00:00Z",
         "cluster_id": "cl-iter-A",
         "kill_reason": {"code": "redteam_fatal_flaw",
                         "evidence_key": "iteration:iter-A:redteam",
                         "detail": "redteam verdict fatal_flaw"}},
    ])
    items = [_gate_item("iter-A", redteam_verdict="fatal_flaw")]
    enrich_items(items, tmp_path)
    [item] = items  # still listed — the tag never removes
    assert item["triage"] == "likely_superseded"
    assert "cl-iter-A" in item["triage_reason"]
    assert "redteam_fatal_flaw" in item["triage_reason"]
    # The kill cites the item's own iteration — the reason must say so.
    assert "own record" in item["triage_reason"]
    assert item["cluster"]["killed"] is True
    assert item["cluster"]["kill_code"] == "redteam_fatal_flaw"


def test_member_of_another_killed_cluster_tags_superseded(tmp_path):
    """The iter-2026-06-19-011 shape: folded as a member into ANOTHER
    iteration's cluster, which was then killed on THAT iteration's evidence
    (not self-cited)."""
    _write_jsonl(tmp_path / "idea_ledger.jsonl", [
        {"event_type": "cluster_created", "ts": "2026-08-15T01:00:00Z",
         "cluster_id": "cl-iter-A", "member_id": "iter-A",
         "iteration_id": "iter-A"},
        {"event_type": "member_added", "ts": "2026-08-15T01:00:00Z",
         "cluster_id": "cl-iter-A", "member_id": "iter-B",
         "accept_reason": "lexical_jaccard:0.690"},
        {"event_type": "cluster_killed", "ts": "2026-08-15T01:00:00Z",
         "cluster_id": "cl-iter-A",
         "kill_reason": {"code": "redteam_fatal_flaw",
                         "evidence_key": "iteration:iter-A:redteam",
                         "detail": "fatal flaw on iter-A"}},
    ])
    items = [_gate_item("iter-B")]
    enrich_items(items, tmp_path)
    assert items[0]["triage"] == "likely_superseded"
    assert "cl-iter-A" in items[0]["triage_reason"]
    # Not self-cited: iter-B is not in the evidence key.
    assert "own record" not in items[0]["triage_reason"]


def test_experiment_consumed_kill_names_the_self_citation(tmp_path):
    """The iter-2026-08-17-008 shape: the cluster was killed CITING this
    iteration's own experiment outcome (experiment_null_effect) — the reason
    says the loop already consumed the result."""
    _write_jsonl(tmp_path / "idea_ledger.jsonl", [
        {"event_type": "cluster_created", "ts": "2026-07-13T00:00:00Z",
         "cluster_id": "cl-old", "member_id": "iter-old",
         "iteration_id": "iter-old"},
        {"event_type": "member_added", "ts": "2026-08-17T03:32:00Z",
         "cluster_id": "cl-old", "member_id": "iter-fresh",
         "accept_reason": "bridged_experiment:PREREG"},
        {"event_type": "cluster_killed", "ts": "2026-08-17T03:32:00Z",
         "cluster_id": "cl-old",
         "kill_reason": {"code": "experiment_null_effect",
                         "evidence_key":
                             "iteration:exp010_audit:experiment_outcome",
                         "detail": "predicted effect not found"}},
    ])
    items = [_gate_item("iter-fresh", experiment_id="exp010_audit")]
    enrich_items(items, tmp_path)
    assert items[0]["triage"] == "likely_superseded"
    assert "experiment_null_effect" in items[0]["triage_reason"]
    assert "already" in items[0]["triage_reason"]  # consumed — verdict ratifies/contests


def test_fresh_item_with_live_or_no_cluster_is_valid(tmp_path):
    _write_jsonl(tmp_path / "idea_ledger.jsonl", [
        {"event_type": "cluster_created", "ts": "2026-08-18T00:00:00Z",
         "cluster_id": "cl-iter-C", "member_id": "iter-C",
         "iteration_id": "iter-C"},
    ])
    items = [
        _gate_item("iter-C"),      # cluster exists, not killed
        _gate_item("iter-D"),      # no ledger trace at all
    ]
    enrich_items(items, tmp_path)
    assert items[0]["triage"] == "valid"
    assert items[0]["cluster"]["killed"] is False
    assert items[1]["triage"] == "valid"
    assert "cluster" not in items[1]
    for item in items:
        assert "live ask" in item["triage_reason"]


def test_observable_kinds_tag_observable(tmp_path):
    items = [
        {"kind": "bubble_ack", "id": "coordinator_x", "title": "note",
         "since": "", "detail": "", "resolve_command": ""},
        {"kind": "stale_active_run", "id": "active_run", "title": "stale",
         "since": "", "detail": "", "resolve_command": ""},
    ]
    enrich_items(items, tmp_path)  # no ledger file at all
    for item in items:
        assert item["triage"] == "observable"
        assert "not an approval" in item["triage_reason"]


def test_action_doing_means_and_vet_are_derived(tmp_path):
    _write_jsonl(tmp_path / "idea_ledger.jsonl", [
        {"event_type": "cluster_created", "ts": "2026-08-15T01:00:00Z",
         "cluster_id": "cl-iter-A", "member_id": "iter-A",
         "iteration_id": "iter-A"},
        {"event_type": "cluster_killed", "ts": "2026-08-15T01:00:00Z",
         "cluster_id": "cl-iter-A",
         "kill_reason": {"code": "redteam_fatal_flaw",
                         "evidence_key": "iteration:iter-A:redteam",
                         "detail": "d"}},
    ])
    items = [_gate_item(
        "iter-A", redteam_verdict="fatal_flaw", experiment_id="exp004",
        metric="vcg_truthful_fraction", metric_value=0.965, trials=40,
    )]
    enrich_items(items, tmp_path)
    [item] = items
    assert item["action"] == "Record a gate verdict on iter-A"
    assert "valid, invalid, or needs revision" in item["doing"]
    assert "loop_feedback.jsonl" in item["approval_means"]
    # Vet bullets come from the item's OWN record: redteam, metric, kill.
    vet = item["vet"]
    assert 2 <= len(vet) <= 3
    assert any("fatal_flaw" in b for b in vet)
    assert any("vcg_truthful_fraction = 0.965" in b for b in vet)
    assert any("cl-iter-A" in b for b in vet)


def test_finding_review_vet_names_the_evidence_level(tmp_path):
    items = [{
        "kind": "finding_review", "id": "sf-x", "title": "f", "since": "",
        "detail": "", "resolve_command": "", "evidence_level": "L1",
    }]
    enrich_items(items, tmp_path)
    assert items[0]["action"] == "Review + disposition finding sf-x"
    assert any("L1 only" in b for b in items[0]["vet"])
    assert items[0]["triage"] == "valid"


@pytest.mark.parametrize("seed", range(6))
def test_dup_relink_member_always_joins_the_open_cluster(tmp_path, seed):
    """B2 regression (2026-08-18): a member in TWO clusters — a killed
    superseded_duplicate self-cluster AND the open surviving cluster it was
    relinked into (the live d075_r4_dup_relink pattern on
    iter-2026-08-18-001/002/003) — must ALWAYS join to the OPEN cluster.
    The rule is last-membership-event-wins in ledger file order
    (owe_triage.membership_from_rows), now the ONE join BOTH modules
    consume; human_todo's old set-union walk mapped such members
    PYTHONHASHSEED-dependently. Shuffled insertion of the independent event
    groups simulates that seed variance: the winner must never move."""
    from backend import human_todo, owe_triage

    rng = random.Random(seed)
    members = [f"iter-2026-08-18-{n:03d}" for n in (1, 2, 3, 4, 5)]
    originals = {m: f"cl-orig-{i}" for i, m in enumerate(members)}
    # Original surviving clusters first (the strict reducer requires the
    # relink target to exist before its member_added).
    head = [
        {"event_type": "cluster_created", "ts": "2026-05-26T00:00:00Z",
         "cluster_id": originals[m], "member_id": f"founder-{i}",
         "origin": "consolidation"}
        for i, m in enumerate(members)
    ]
    rng.shuffle(head)
    # Per-member dup groups: dup self-cluster created, member relinked to
    # the ORIGINAL, dup killed superseded_duplicate. Intra-group order is
    # the live ledger's invariant (relink AFTER the dup's create); the
    # groups themselves land in a seed-shuffled order.
    groups = []
    for m in members:
        dup = f"cl-{m}"
        groups.append([
            {"event_type": "cluster_created", "ts": "2026-08-18T01:00:00Z",
             "cluster_id": dup, "member_id": m, "origin": "consolidation",
             "iteration_id": m},
            {"event_type": "member_added", "ts": "2026-08-18T05:28:19Z",
             "cluster_id": originals[m], "member_id": m,
             "accept_reason": "d075_r4_dup_relink"},
            {"event_type": "cluster_killed", "ts": "2026-08-18T05:28:19Z",
             "cluster_id": dup,
             "kill_reason": {"code": "superseded_duplicate",
                             "evidence_key": f"cluster:{originals[m]}",
                             "detail":
                                 f"superseded duplicate of {originals[m]}"},
             "reopening_condition": {"requires": "new_evidence",
                                     "evidence_kind": "articulated_delta"}},
        ])
    rng.shuffle(groups)
    events = head + [ev for group in groups for ev in group]
    _write_jsonl(tmp_path / "idea_ledger.jsonl", events)

    membership, _kills = owe_triage._ledger_index(tmp_path)
    member_of, clusters = human_todo._ledger_clusters(tmp_path)
    # ONE join, shared: the two modules cannot disagree.
    assert member_of == membership
    for m in members:
        assert membership[m] == originals[m]  # the OPEN cluster wins
        assert clusters[originals[m]]["killed"] is False
        assert clusters[f"cl-{m}"]["killed"] is True
    # And the triage tag reads the open cluster: a live ask, not superseded.
    items = [_gate_item(m) for m in members]
    enrich_items(items, tmp_path)
    for item in items:
        assert item["triage"] == "valid", item["id"]
        assert item["cluster"]["cluster_id"] == originals[item["id"]]
        assert item["cluster"]["killed"] is False


def test_reopened_cluster_is_not_tagged_superseded(tmp_path):
    """cluster_reopened clears the kill in the tolerant scan (2026-08-18
    fix — the old docstring falsely claimed no reopen event type exists)."""
    _write_jsonl(tmp_path / "idea_ledger.jsonl", [
        {"event_type": "cluster_created", "ts": "2026-08-15T01:00:00Z",
         "cluster_id": "cl-iter-R", "member_id": "iter-R",
         "iteration_id": "iter-R", "origin": "consolidation"},
        {"event_type": "cluster_killed", "ts": "2026-08-15T01:14:25Z",
         "cluster_id": "cl-iter-R",
         "kill_reason": {"code": "redteam_fatal_flaw",
                         "evidence_key": "iteration:iter-R:redteam",
                         "detail": "fatal"},
         "reopening_condition": {"requires": "new_evidence",
                                 "evidence_kind": "redteam_proceed_on_revision"}},
        {"event_type": "cluster_reopened", "ts": "2026-08-16T00:00:00Z",
         "cluster_id": "cl-iter-R",
         "evidence": {"evidence_kind": "redteam_proceed_on_revision"}},
    ])
    items = [_gate_item("iter-R")]
    enrich_items(items, tmp_path)
    assert items[0]["triage"] == "valid"
    assert items[0]["cluster"]["killed"] is False
    assert items[0]["cluster"]["kill_code"] is None


def test_self_citation_requires_exact_evidence_key_segment(tmp_path):
    """2026-08-18 fix: 'iter-Z' substring-matched 'cluster:cl-iter-Z' and
    falsely claimed the kill cited the item's own record. The match is now
    exact on ':'-split segments."""
    _write_jsonl(tmp_path / "idea_ledger.jsonl", [
        {"event_type": "cluster_created", "ts": "2026-08-15T01:00:00Z",
         "cluster_id": "cl-iter-Z", "member_id": "iter-Z",
         "iteration_id": "iter-Z", "origin": "consolidation"},
        {"event_type": "cluster_killed", "ts": "2026-08-15T01:14:25Z",
         "cluster_id": "cl-iter-Z",
         "kill_reason": {"code": "superseded_duplicate",
                         "evidence_key": "cluster:cl-iter-Z",
                         "detail": "dup"},
         "reopening_condition": {"requires": "new_evidence",
                                 "evidence_kind": "articulated_delta"}},
    ])
    items = [_gate_item("iter-Z")]
    enrich_items(items, tmp_path)
    assert items[0]["triage"] == "likely_superseded"
    assert "own record" not in items[0]["triage_reason"]  # not self-cited
    # An exact segment still reads as self-cited (control).
    _write_jsonl(tmp_path / "idea_ledger.jsonl", [
        {"event_type": "cluster_created", "ts": "2026-08-15T01:00:00Z",
         "cluster_id": "cl-iter-Z", "member_id": "iter-Z",
         "iteration_id": "iter-Z", "origin": "consolidation"},
        {"event_type": "cluster_killed", "ts": "2026-08-15T01:14:25Z",
         "cluster_id": "cl-iter-Z",
         "kill_reason": {"code": "redteam_fatal_flaw",
                         "evidence_key": "iteration:iter-Z:redteam",
                         "detail": "fatal"},
         "reopening_condition": {"requires": "new_evidence",
                                 "evidence_kind": "redteam_proceed_on_revision"}},
    ])
    items = [_gate_item("iter-Z")]
    enrich_items(items, tmp_path)
    assert "own record" in items[0]["triage_reason"]


def test_garbled_ledger_never_strips_the_queue(tmp_path):
    _write_jsonl(tmp_path / "idea_ledger.jsonl", [
        "not-json", "42",
        {"event_type": "cluster_killed"},              # no cluster_id
        {"cluster_id": "cl-x"},                        # no event_type
        {"event_type": "cluster_killed", "cluster_id": "cl-y",
         "kill_reason": "not-a-dict"},                 # tolerated shape
    ])
    items = [_gate_item("iter-A")]
    enrich_items(items, tmp_path)
    assert items[0]["triage"] == "valid"
    assert items[0]["id"] == "iter-A"


# --- endpoint: the derived fields ride /api/human_todo additively ----------

def test_endpoint_carries_derived_fields_additively(tmp_path):
    client = _client(tmp_path)
    _write_jsonl(tmp_path / "coord_memory" / "loop_memory.jsonl", [
        {"iteration_id": "iter-K", "gate_status": "pending",
         "ended_at": "2026-06-05T20:00:00Z",
         "seed": {"topic": "killed-cluster topic"},
         "redteam": {"verdict": "fatal_flaw", "rationale": "r"},
         "experiment_outcome": {"experiment_id": "exp004",
                                "metric": "m", "value": 0.5, "trials": 12}},
        {"iteration_id": "iter-F", "gate_status": "pending",
         "ended_at": "2026-08-18T01:00:00Z",
         "seed": {"topic": "fresh topic"},
         "experiment_outcome": {"experiment_id": "exp999",
                                "metric": "x", "value": 1.0}},
    ])
    _write_jsonl(tmp_path / "coord_memory" / "idea_ledger.jsonl", [
        {"event_type": "cluster_created", "ts": "2026-08-15T01:00:00Z",
         "cluster_id": "cl-iter-K", "member_id": "iter-K",
         "iteration_id": "iter-K"},
        {"event_type": "cluster_killed", "ts": "2026-08-15T01:00:00Z",
         "cluster_id": "cl-iter-K",
         "kill_reason": {"code": "redteam_fatal_flaw",
                         "evidence_key": "iteration:iter-K:redteam",
                         "detail": "fatal"}},
    ])
    body = client.get("/api/human_todo").json()
    by_id = {i["id"]: i for i in body["items"]}
    assert set(by_id) == {"iter-K", "iter-F"}
    # Frozen keys intact on every item (additive contract).
    for item in by_id.values():
        assert _ITEM_KEYS <= set(item)
        assert item["kind"] == "gate_verdict"
    killed, fresh = by_id["iter-K"], by_id["iter-F"]
    assert killed["triage"] == "likely_superseded"
    assert killed["action"] == "Record a gate verdict on iter-K"
    assert killed["redteam_verdict"] == "fatal_flaw"
    # The pointed pass (2026-08-18 #2, human_todo._point_gate_verdicts)
    # overrides the generic vet on the endpoint path: the experiment fact
    # now renders as a discrimination probe, values inline.
    assert any("does m=0.5 actually discriminate" in b for b in killed["vet"])
    assert fresh["triage"] == "valid"
    # Both stay counted — tags never dismiss.
    assert body["counts"]["gate_verdict"] == 2
