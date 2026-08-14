"""Tests for workers/idea_ledger.py + schema/idea_ledger.schema.json (LOOP_V1
P3, agent A3). Hermetic: tmp_path ledgers, monkeypatched embed seam, no
network, no real model calls."""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from jsonschema import Draft202012Validator

from workers import idea_ledger, mine_paper_gap

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "schema" / "idea_ledger.schema.json"

TS = "2026-08-14T12:00:00Z"


def _claim(n: str = "a") -> dict:
    return {
        "problem": f"problem {n}",
        "mechanism": f"mechanism {n}",
        "predicted_effect": f"effect {n}",
        "evidence_ref": {"iteration_id": f"iter-{n}"},
    }


def _created(cid="cl-001", member="iter-a", claim=True) -> dict:
    ev = {"event_type": "cluster_created", "ts": TS, "cluster_id": cid,
          "origin": "iteration", "member_id": member}
    if claim:
        ev["claim"] = _claim()
    return ev


def _killed(cid="cl-001", kind="replication") -> dict:
    return {
        "event_type": "cluster_killed", "ts": TS, "cluster_id": cid,
        "kill_reason": {"code": "redteam_fatal_flaw",
                        "evidence_key": "iteration:iter-a:redteam",
                        "detail": "redteam verdict fatal_flaw on iteration iter-a"},
        "reopening_condition": {"requires": "new_evidence", "evidence_kind": kind},
    }


# ── schema ───────────────────────────────────────────────────────────────────

def test_schema_self_validates():
    Draft202012Validator.check_schema(json.loads(SCHEMA_PATH.read_text()))


def test_schema_accepts_every_event_type():
    events = [
        _created(),
        {"event_type": "member_added", "ts": TS, "cluster_id": "cl-001",
         "member_id": "iter-b", "claim": _claim("b"), "as_elite": True,
         "accept_reason": "judge verdict better_with_delta over elite"},
        {"event_type": "evidence_level_changed", "ts": TS, "cluster_id": "cl-001",
         "evidence_level": "L2", "basis": "evidence_ladder:iter-b"},
        _killed(),
        {"event_type": "cluster_reopened", "ts": TS, "cluster_id": "cl-001",
         "evidence": {"evidence_kind": "replication", "detail": "replicated at tier 2"}},
        {"event_type": "niche_seeded", "ts": TS, "cluster_id": "cl-p1",
         "paper": {"arxiv_id": "2508.01234", "title": "A paper title"}},
        {"event_type": "agenda_item_added", "ts": TS, "cluster_id": "cl-001",
         "topic": "explore x", "source": "paper_gap"},
        {"event_type": "agenda_item_consumed", "ts": TS, "cluster_id": "cl-001",
         "topic": "explore x", "consumed_by": "iter-c"},
    ]
    for ev in events:
        idea_ledger.validate_event(ev)


@pytest.mark.parametrize("bad", [
    {"event_type": "cluster_surfaced", "ts": TS, "cluster_id": "c"},  # unknown type
    {"event_type": "cluster_created", "ts": TS, "cluster_id": "c"},   # missing origin/member
    {"event_type": "evidence_level_changed", "ts": TS, "cluster_id": "c",
     "evidence_level": "L9"},                                          # bad rung
    {"event_type": "cluster_killed", "ts": TS, "cluster_id": "c",
     "kill_reason": {"code": "llm_said_so", "evidence_key": "x", "detail": "d"},
     "reopening_condition": {"requires": "new_evidence", "evidence_kind": "k"}},  # non-enum code
    {"event_type": "cluster_killed", "ts": TS, "cluster_id": "c",
     "kill_reason": {"code": "redteam_fatal_flaw", "evidence_key": "x", "detail": "d"},
     "reopening_condition": {"requires": "hope", "evidence_kind": "k"}},  # bad requires
    {"event_type": "agenda_item_added", "ts": TS, "cluster_id": "c",
     "topic": "t", "source": "vibes"},                                 # non-enum source
])
def test_schema_rejects_malformed(bad):
    with pytest.raises(jsonschema.ValidationError):
        idea_ledger.validate_event(bad)


def test_append_event_validates_before_writing(tmp_path):
    path = tmp_path / "ledger.jsonl"
    with pytest.raises(jsonschema.ValidationError):
        idea_ledger.append_event(path, {"event_type": "nope", "ts": TS, "cluster_id": "c"})
    assert not path.exists()  # invalid event never touches the file


# ── round-trip + reducer ─────────────────────────────────────────────────────

def test_round_trip_and_state_shape(tmp_path):
    path = tmp_path / "ledger.jsonl"
    idea_ledger.append_event(path, _created())
    idea_ledger.append_event(path, {
        "event_type": "member_added", "ts": TS, "cluster_id": "cl-001",
        "member_id": "iter-b"})
    idea_ledger.append_event(path, {
        "event_type": "evidence_level_changed", "ts": TS, "cluster_id": "cl-001",
        "evidence_level": "L2"})
    state = idea_ledger.load_state(path)
    c = state["cl-001"]
    assert c["cluster_id"] == "cl-001"
    assert c["status"] == "open"
    assert c["evidence_level"] == "L2"
    assert c["members"] == ["iter-a", "iter-b"]
    assert c["elite"] == {"claim": _claim(), "iteration_id": "iter-a"}
    assert c["kill_reason"] is None
    assert c["reopening_condition"] is None
    assert c["origin"] == "iteration"
    assert c["last_event_ts"] == TS


def test_determinism_same_events_same_state(tmp_path):
    path = tmp_path / "ledger.jsonl"
    for ev in [_created(), _killed(),
               {"event_type": "cluster_reopened", "ts": TS, "cluster_id": "cl-001",
                "evidence": {"evidence_kind": "replication"}}]:
        idea_ledger.append_event(path, ev)
    a = idea_ledger.load_state(path)
    b = idea_ledger.load_state(path)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_reducer_is_pure_no_input_mutation():
    events = [_created(), _killed()]
    frozen = json.dumps(events, sort_keys=True)
    idea_ledger.reduce_events(events)
    assert json.dumps(events, sort_keys=True) == frozen


def test_missing_ledger_is_cold_start(tmp_path):
    assert idea_ledger.load_state(tmp_path / "absent.jsonl") == {}


def test_malformed_line_raises(tmp_path):
    path = tmp_path / "ledger.jsonl"
    path.write_text("{not json\n")
    with pytest.raises(ValueError, match="malformed JSON"):
        idea_ledger.load_state(path)


def test_event_for_unknown_cluster_raises():
    with pytest.raises(ValueError, match="unknown cluster"):
        idea_ledger.reduce_events([
            {"event_type": "member_added", "ts": TS, "cluster_id": "ghost",
             "member_id": "iter-x"}])


def test_as_elite_promotes_and_requires_claim():
    events = [_created(), {
        "event_type": "member_added", "ts": TS, "cluster_id": "cl-001",
        "member_id": "iter-b", "claim": _claim("b"), "as_elite": True}]
    state = idea_ledger.reduce_events(events)
    assert state["cl-001"]["elite"] == {"claim": _claim("b"), "iteration_id": "iter-b"}
    with pytest.raises(ValueError, match="as_elite without a claim"):
        idea_ledger.reduce_events([_created(), {
            "event_type": "member_added", "ts": TS, "cluster_id": "cl-001",
            "member_id": "iter-c", "as_elite": True}])


def test_surfaced_status_derives_from_l4_plus():
    for level, status in [("L3", "open"), ("L4", "surfaced"), ("L5", "surfaced")]:
        state = idea_ledger.reduce_events([_created(), {
            "event_type": "evidence_level_changed", "ts": TS,
            "cluster_id": "cl-001", "evidence_level": level}])
        assert state["cl-001"]["status"] == status


# ── kill / reopen ────────────────────────────────────────────────────────────

def test_kill_then_matching_reopen():
    killed = idea_ledger.reduce_events([_created(), _killed(kind="replication")])
    c = killed["cl-001"]
    assert c["status"] == "killed"
    assert c["kill_reason"]["code"] == "redteam_fatal_flaw"
    assert c["reopening_condition"] == {"requires": "new_evidence",
                                        "evidence_kind": "replication"}
    reopened = idea_ledger.reduce_events([
        _created(), _killed(kind="replication"),
        {"event_type": "cluster_reopened", "ts": TS, "cluster_id": "cl-001",
         "evidence": {"evidence_kind": "replication"}}])
    c = reopened["cl-001"]
    assert c["status"] == "open"
    assert c["kill_reason"] is None and c["reopening_condition"] is None


def test_mismatched_reopen_refused():
    with pytest.raises(ValueError, match="does not match"):
        idea_ledger.reduce_events([
            _created(), _killed(kind="replication"),
            {"event_type": "cluster_reopened", "ts": TS, "cluster_id": "cl-001",
             "evidence": {"evidence_kind": "articulated_delta"}}])


def test_reopen_on_live_cluster_refused():
    with pytest.raises(ValueError, match="non-killed"):
        idea_ledger.reduce_events([
            _created(),
            {"event_type": "cluster_reopened", "ts": TS, "cluster_id": "cl-001",
             "evidence": {"evidence_kind": "replication"}}])


def test_niche_seeded_is_pre_closed_paper_niche():
    state = idea_ledger.reduce_events([{
        "event_type": "niche_seeded", "ts": TS, "cluster_id": "cl-p1",
        "paper": {"arxiv_id": "2508.01234", "title": "A paper title"}}])
    c = state["cl-p1"]
    assert c["status"] == "killed"
    assert c["origin"] == "paper_seed"
    assert c["kill_reason"]["code"] == "paper_prior_exists"
    assert c["kill_reason"]["evidence_key"] == "papers_recent:2508.01234"
    assert c["reopening_condition"]["evidence_kind"] == "articulated_delta"


# ── agenda events ────────────────────────────────────────────────────────────

def test_agenda_add_then_consume():
    state = idea_ledger.reduce_events([
        _created(),
        {"event_type": "agenda_item_added", "ts": TS, "cluster_id": "cl-001",
         "topic": "explore x", "source": "paper_gap"},
        {"event_type": "agenda_item_consumed", "ts": TS, "cluster_id": "cl-001",
         "topic": "explore x"}])
    assert state["cl-001"]["agenda"] == [
        {"topic": "explore x", "source": "paper_gap", "status": "consumed", "ts": TS}]
    with pytest.raises(ValueError, match="no pending item"):
        idea_ledger.reduce_events([
            _created(),
            {"event_type": "agenda_item_consumed", "ts": TS, "cluster_id": "cl-001",
             "topic": "never added"}])


# ── kill_reason builders (enum codes, never coerced) ─────────────────────────

def test_kill_reason_from_redteam():
    kr = idea_ledger.kill_reason_from_redteam(
        {"iteration_id": "iter-9", "redteam": {"verdict": "fatal_flaw"}})
    assert kr == {"code": "redteam_fatal_flaw",
                  "evidence_key": "iteration:iter-9:redteam",
                  "detail": "redteam verdict fatal_flaw on iteration iter-9"}
    assert kr["code"] in idea_ledger.KILL_CODES
    with pytest.raises(ValueError, match="refusing"):
        idea_ledger.kill_reason_from_redteam(
            {"iteration_id": "iter-9", "redteam": {"verdict": "proceed"}})


def test_kill_reason_from_adversarial():
    kr = idea_ledger.kill_reason_from_adversarial(
        {"iteration_id": "iter-9", "survived": False, "votes": "0/3"})
    assert kr["code"] == "adversarial_refuted"
    assert kr["evidence_key"] == "iteration:iter-9:adversarial"
    with pytest.raises(ValueError, match="refusing"):
        idea_ledger.kill_reason_from_adversarial({"iteration_id": "iter-9", "survived": True})


def test_kill_reason_from_experiment():
    invalid = idea_ledger.kill_reason_from_experiment(
        {"iteration_id": "iter-9", "summary": "INVALID: trials diverged"})
    assert invalid["code"] == "experiment_invalid"
    null = idea_ledger.kill_reason_from_experiment(
        {"iteration_id": "iter-9", "summary": "ok", "effect_confirmed": False, "trials": 40})
    assert null["code"] == "experiment_null_effect"
    with pytest.raises(ValueError, match="refusing"):
        idea_ledger.kill_reason_from_experiment(
            {"iteration_id": "iter-9", "summary": "ok", "effect_confirmed": True})


def test_builders_emit_schema_valid_kill_reasons(tmp_path):
    kr = idea_ledger.kill_reason_from_redteam(
        {"iteration_id": "iter-9", "redteam": {"verdict": "fatal_flaw"}})
    ev = {"event_type": "cluster_killed", "ts": TS, "cluster_id": "cl-001",
          "kill_reason": kr,
          "reopening_condition": idea_ledger.reopening_condition("replication")}
    idea_ledger.validate_event(ev)


def test_reopening_condition_builder():
    assert idea_ledger.reopening_condition("articulated_delta") == {
        "requires": "new_evidence", "evidence_kind": "articulated_delta"}
    with pytest.raises(ValueError):
        idea_ledger.reopening_condition("")


# ── MAP-Elites accept_candidate ──────────────────────────────────────────────

def _cluster_with_elite(status="open"):
    return {
        "cluster_id": "cl-001", "status": status, "evidence_level": "L1",
        "elite": {"claim": {
            "problem": "auction bidders overbid under uncertainty",
            "mechanism": "risk aversion inflates marginal valuation",
            "predicted_effect": "overbidding grows with variance"},
            "iteration_id": "iter-a"},
        "members": ["iter-a"], "kill_reason": None, "reopening_condition": None,
        "origin": "iteration", "last_event_ts": TS, "agenda": [],
    }


def _orthogonal_embeds(monkeypatch):
    monkeypatch.setattr(mine_paper_gap, "_embed_texts",
                        lambda texts: [[1.0, 0.0], [0.0, 1.0]][:len(texts)])


def test_accept_empty_niche(monkeypatch):
    cluster = _cluster_with_elite()
    cluster["elite"] = None
    out = idea_ledger.accept_candidate({"text": "anything at all"}, cluster)
    assert out["accepted"] is True and "empty niche" in out["reason"]


def test_reject_lexical_restatement_prefilter_only(monkeypatch):
    # Candidate restates the elite verbatim -> lexical Jaccard fires before
    # any embed (embed seam poisoned to prove it is not reached).
    monkeypatch.setattr(mine_paper_gap, "_embed_texts",
                        lambda texts: pytest.fail("embed must not run on a lexical dup"))
    cand = {"problem": "auction bidders overbid under uncertainty",
            "mechanism": "risk aversion inflates marginal valuation",
            "predicted_effect": "overbidding grows with variance"}
    out = idea_ledger.accept_candidate(cand, _cluster_with_elite())
    assert out["accepted"] is False and "lexical_jaccard" in out["reason"]


def test_reject_cosine_near_identical(monkeypatch):
    # Lexically disjoint but embedding-identical -> cosine_tau_dup fires.
    monkeypatch.setattr(mine_paper_gap, "_embed_texts",
                        lambda texts: [[1.0, 0.0] for _ in texts])
    out = idea_ledger.accept_candidate(
        {"text": "totally different vocabulary here"}, _cluster_with_elite())
    assert out["accepted"] is False and "cosine_tau_dup" in out["reason"]


def test_accept_distinct_prefilter_only(monkeypatch):
    _orthogonal_embeds(monkeypatch)
    out = idea_ledger.accept_candidate(
        {"text": "bargaining delay signals patience asymmetries"},
        _cluster_with_elite())
    assert out["accepted"] is True and "distinct" in out["reason"]


def test_judge_better_with_delta_overrides_prefilter_dup(monkeypatch):
    monkeypatch.setattr(mine_paper_gap, "_embed_texts",
                        lambda texts: [[1.0, 0.0] for _ in texts])
    calls = []

    def judge(a, b):
        calls.append((a, b))
        return {"verdict": "better_with_delta", "delta": "adds boundary condition",
                "confidence": 0.9}

    out = idea_ledger.accept_candidate(
        {"text": "different words same idea"}, _cluster_with_elite(), judge_fn=judge)
    assert out["accepted"] is True and "better_with_delta" in out["reason"]
    assert len(calls) == 1


def test_judge_equivalent_rejects_even_when_prefilter_distinct(monkeypatch):
    _orthogonal_embeds(monkeypatch)
    out = idea_ledger.accept_candidate(
        {"text": "a fresh looking restatement"}, _cluster_with_elite(),
        judge_fn=lambda a, b: {"verdict": "equivalent", "delta": "", "confidence": 0.95})
    assert out["accepted"] is False and "equivalent" in out["reason"]


def test_judge_invalid_verdict_raises(monkeypatch):
    _orthogonal_embeds(monkeypatch)
    with pytest.raises(ValueError, match="invalid verdict"):
        idea_ledger.accept_candidate(
            {"text": "whatever"}, _cluster_with_elite(),
            judge_fn=lambda a, b: {"verdict": "sort_of_better"})


def test_killed_niche_requires_articulated_delta(monkeypatch):
    killed = _cluster_with_elite(status="killed")
    killed["kill_reason"] = {"code": "paper_prior_exists",
                             "evidence_key": "papers_recent:2508.01234",
                             "detail": "pre-closed paper niche: A paper title"}
    # No judge -> refused outright.
    out = idea_ledger.accept_candidate({"text": "rediscovery attempt"}, killed)
    assert out["accepted"] is False and "killed niche" in out["reason"]
    # Judge articulates a delta -> admitted.
    out = idea_ledger.accept_candidate(
        {"text": "rediscovery with a delta"}, killed,
        judge_fn=lambda a, b: {"verdict": "better_with_delta", "delta": "d", "confidence": 0.8})
    assert out["accepted"] is True
    # Judge says equivalent -> still refused.
    out = idea_ledger.accept_candidate(
        {"text": "plain rediscovery"}, killed,
        judge_fn=lambda a, b: {"verdict": "equivalent", "delta": "", "confidence": 0.9})
    assert out["accepted"] is False


def test_candidate_without_text_raises():
    with pytest.raises(ValueError, match="no claim/text"):
        idea_ledger.accept_candidate({}, _cluster_with_elite())
