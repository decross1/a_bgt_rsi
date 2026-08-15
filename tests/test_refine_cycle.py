"""Tests for workers/refine_cycle.py (D-064 critique-refine cycle).

Hermetic by construction: tmp_path ledgers, injected invoke_fn (the
frontier seam — no subprocess, no network) and injected refine_fn (no
model call). The two MOCK_LLM-specific behaviors are pinned with
monkeypatch.setenv, so the suite is green whether or not the shell set
MOCK_LLM.

Pinned behaviors:
  - MAX_REFINE_ROUNDS == 5 is a HARD cap: max_rounds above it raises, a
    6th round is impossible by construction (the canned screen factory
    would IndexError past round 5).
  - pass at round N stops the cycle; a killed cluster reopens ONLY when
    its reopening_condition.evidence_kind is 'articulated_delta'.
  - refinement NEVER auto-promotes (evidence_level untouched).
  - kill-after-5 selects paper_prior_exists (final novelty veto citing
    prior) vs adversarial_refuted (anything else).
  - every appended event is schema-valid and the reducer accepts it.
  - CLI --dry-run writes nothing (no ledger events, no run-log rows).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from workers import idea_ledger
from workers import refine_cycle as rc

CID = "cl-001"
TS = "2026-08-15T12:00:00Z"

CLAIM = {"problem": "problem a", "mechanism": "mechanism a",
         "predicted_effect": "effect a"}
CLAIM_TEXT = "problem a mechanism a effect a"

# One injected reviser everywhere a refine can occur — the default
# refine_fn would make a REAL call_sync when MOCK_LLM is unset.
REFINE = lambda claim, feedback, rnd: f"{claim} [r{rnd}]"  # noqa: E731


def _created(cid=CID, member="iter-a", claim=True, level="L1"):
    ev = {"event_type": "cluster_created", "ts": TS, "cluster_id": cid,
          "origin": "iteration", "member_id": member, "evidence_level": level}
    if claim:
        ev["claim"] = dict(CLAIM)
    return ev


def _killed(cid=CID, kind="articulated_delta"):
    return {
        "event_type": "cluster_killed", "ts": TS, "cluster_id": cid,
        "kill_reason": {"code": "redteam_fatal_flaw",
                        "evidence_key": "iteration:iter-a:redteam",
                        "detail": "redteam verdict fatal_flaw on iter-a"},
        "reopening_condition": {"requires": "new_evidence",
                                "evidence_kind": kind},
    }


def _ledger(tmp_path, events) -> Path:
    path = tmp_path / "idea_ledger.jsonl"
    for ev in events:
        idea_ledger.append_event(path, ev)
    return path


def make_screens(rounds, calls=None):
    """Canned invoke_fn: `rounds[i]` = {"methods": (verdict, reasoning,
    prior), "novelty": (...)} for screen i. Indexing past the last screen
    raises IndexError — the structural no-6th-round guard."""
    idx = {"screen": 0}

    def invoke(vendor, prompt, *, timeout_s, role, ledger_path=None):
        spec = rounds[idx["screen"]][role.replace("_reviewer", "")]
        verdict, reasoning, prior = spec
        if calls is not None:
            calls.append((idx["screen"], vendor, role, prompt))
        if role == "novelty_reviewer":  # second call of a screen
            idx["screen"] += 1
        return {"text": json.dumps({"verdict": verdict, "reasoning": reasoning,
                                    "closest_prior_work": prior}),
                "vendor": vendor, "cli_version": "t", "duration_ms": 1,
                "exit_code": 0, "error": None}
    return invoke


VETO_ROUND = {"methods": ("veto", "missing ablation control", None),
              "novelty": ("veto", "already established", "Smith et al. 2019")}
PASS_ROUND = {"methods": ("pass", "mechanism is sound", None),
              "novelty": ("pass", "no subsuming prior", None)}
ADVERSARIAL_ROUND = {"methods": ("veto", "confound: context length", None),
                     "novelty": ("inconclusive", "", None)}


# ── the hard cap ─────────────────────────────────────────────────────────────

def test_max_refine_rounds_is_five():
    assert rc.MAX_REFINE_ROUNDS == 5


@pytest.mark.parametrize("bad", [0, -1, 6, 7, "5", None, 5.0])
def test_max_rounds_outside_cap_raises_never_clamped(tmp_path, bad):
    path = _ledger(tmp_path, [_created()])
    calls = []
    with pytest.raises(ValueError):
        rc.refine_cluster(CID, ledger_path=path, max_rounds=bad,
                          invoke_fn=make_screens([], calls), refine_fn=REFINE)
    assert calls == []  # rejected before any frontier call


def test_kill_after_five_rounds_hard_cap(tmp_path):
    path = _ledger(tmp_path, [_created()])
    calls = []
    # Exactly 5 screens available: a 6th would IndexError.
    invoke = make_screens([VETO_ROUND] * 5, calls)
    refines = []

    def refine(claim, feedback, rnd):
        refines.append(rnd)
        return f"{claim} [r{rnd}]"

    report = rc.refine_cluster(CID, ledger_path=path, invoke_fn=invoke,
                               refine_fn=refine)
    assert report["improved"] is False
    assert report["killed"] is True
    assert report["rounds_used"] == 5
    assert refines == [1, 2, 3, 4, 5]
    assert len(calls) == 10  # 2 reviewers x 5 screens, no 6th round
    types = [e["event_type"] for e in report["events_appended"]]
    assert types == ["cluster_refined"] * 5 + ["cluster_killed"]
    assert [e["round"] for e in report["events_appended"][:5]] == [1, 2, 3, 4, 5]


# ── pass-at-round-N stop + reopen path ───────────────────────────────────────

def test_pass_at_round_one_writes_nothing(tmp_path):
    path = _ledger(tmp_path, [_created()])
    before = path.read_bytes()
    report = rc.refine_cluster(CID, ledger_path=path,
                               invoke_fn=make_screens([PASS_ROUND]),
                               refine_fn=REFINE)
    assert report["improved"] is True
    assert report["rounds_used"] == 1
    assert report["events_appended"] == []
    assert path.read_bytes() == before  # open cluster + instant pass: no events


def test_pass_at_round_n_stops(tmp_path):
    path = _ledger(tmp_path, [_created()])
    report = rc.refine_cluster(
        CID, ledger_path=path,
        invoke_fn=make_screens([VETO_ROUND, VETO_ROUND, PASS_ROUND]),
        refine_fn=REFINE)
    assert report["improved"] is True
    assert report["killed"] is False
    assert report["rounds_used"] == 3
    types = [e["event_type"] for e in report["events_appended"]]
    assert types == ["cluster_refined", "cluster_refined"]
    assert report["final_claim"] == f"{CLAIM_TEXT} [r1] [r2]"


def test_pass_on_killed_cluster_reopens_with_matching_kind(tmp_path):
    path = _ledger(tmp_path, [_created(), _killed(kind="articulated_delta")])
    report = rc.refine_cluster(CID, ledger_path=path,
                               invoke_fn=make_screens([PASS_ROUND]),
                               refine_fn=REFINE)
    assert report["improved"] is True
    assert report["reopened"] is True
    reopen = report["events_appended"][-1]
    assert reopen["event_type"] == "cluster_reopened"
    assert reopen["evidence"]["evidence_kind"] == "articulated_delta"
    assert reopen["evidence"]["evidence_key"] == "frontier:refine_cycle:round1"
    state = idea_ledger.load_state(path)
    assert state[CID]["status"] == "open"
    assert state[CID]["kill_reason"] is None


def test_pass_on_killed_cluster_wrong_kind_skips_reopen(tmp_path):
    path = _ledger(tmp_path, [_created(), _killed(kind="experiment_rerun")])
    report = rc.refine_cluster(CID, ledger_path=path,
                               invoke_fn=make_screens([PASS_ROUND]),
                               refine_fn=REFINE)
    assert report["improved"] is True
    assert report["reopened"] is False
    assert "experiment_rerun" in report["reopen_skipped"]
    assert report["events_appended"] == []  # the reopen is never forged
    assert idea_ledger.load_state(path)[CID]["status"] == "killed"


# ── never-auto-promote pin ───────────────────────────────────────────────────

def test_refinement_never_changes_evidence_level(tmp_path):
    path = _ledger(tmp_path, [_created(level="L1")])
    report = rc.refine_cluster(
        CID, ledger_path=path,
        invoke_fn=make_screens([VETO_ROUND, PASS_ROUND]), refine_fn=REFINE)
    assert report["improved"] is True
    assert {e["event_type"] for e in report["events_appended"]} == {"cluster_refined"}
    assert idea_ledger.load_state(path)[CID]["evidence_level"] == "L1"


def test_kill_path_never_changes_evidence_level(tmp_path):
    path = _ledger(tmp_path, [_created(level="L2")])
    rc.refine_cluster(CID, ledger_path=path,
                      invoke_fn=make_screens([ADVERSARIAL_ROUND] * 5),
                      refine_fn=REFINE)
    state = idea_ledger.load_state(path)
    assert state[CID]["evidence_level"] == "L2"
    assert state[CID]["status"] == "killed"


# ── kill-code selection ──────────────────────────────────────────────────────

def test_kill_code_paper_prior_when_final_novelty_veto_cites_prior(tmp_path):
    path = _ledger(tmp_path, [_created()])
    report = rc.refine_cluster(CID, ledger_path=path,
                               invoke_fn=make_screens([VETO_ROUND] * 5),
                               refine_fn=REFINE)
    kr = report["kill_reason"]
    assert kr["code"] == "paper_prior_exists"
    assert kr["evidence_key"] == "frontier:refine_cycle:round5"
    assert "Smith et al. 2019" in kr["detail"]
    assert report["events_appended"][-1]["reopening_condition"] == {
        "requires": "new_evidence", "evidence_kind": "articulated_delta"}


def test_kill_code_adversarial_when_no_concrete_prior(tmp_path):
    path = _ledger(tmp_path, [_created()])
    report = rc.refine_cluster(CID, ledger_path=path,
                               invoke_fn=make_screens([ADVERSARIAL_ROUND] * 5),
                               refine_fn=REFINE)
    kr = report["kill_reason"]
    assert kr["code"] == "adversarial_refuted"
    assert kr["evidence_key"] == "frontier:refine_cycle:round5"
    assert "confound: context length" in kr["detail"]  # the final critique head


# ── event schema validity + reducer acceptance ───────────────────────────────

def test_every_appended_event_is_schema_valid_and_reducible(tmp_path):
    path = _ledger(tmp_path, [_created()])
    report = rc.refine_cluster(CID, ledger_path=path,
                               invoke_fn=make_screens([VETO_ROUND] * 5),
                               refine_fn=REFINE)
    for ev in report["events_appended"]:
        idea_ledger.validate_event(ev)  # raises on invalid
    state = idea_ledger.load_state(path)  # reducer accepts cluster_refined
    assert state[CID]["refined_claim"] == report["final_claim"]
    assert [h["round"] for h in state[CID]["refine_history"]] == [1, 2, 3, 4, 5]
    assert state[CID]["refine_history"][0]["feedback_digest"]


@pytest.mark.parametrize("bad", [
    {"event_type": "cluster_refined", "ts": TS, "cluster_id": CID,
     "round": 0, "refined_claim": "x"},                    # round below 1
    {"event_type": "cluster_refined", "ts": TS, "cluster_id": CID,
     "round": 6, "refined_claim": "x"},                    # round above cap
    {"event_type": "cluster_refined", "ts": TS, "cluster_id": CID,
     "round": 1},                                          # missing claim
    {"event_type": "cluster_refined", "ts": TS, "cluster_id": CID,
     "round": 1, "refined_claim": ""},                     # empty claim
    {"event_type": "cluster_refined", "ts": TS, "cluster_id": CID,
     "round": 1, "refined_claim": "x", "extra": True},     # additionalProps
])
def test_schema_rejects_malformed_cluster_refined(bad):
    with pytest.raises(Exception):
        idea_ledger.validate_event(bad)


def test_refined_claim_capped_at_1200_chars(tmp_path):
    path = _ledger(tmp_path, [_created()])
    report = rc.refine_cluster(
        CID, ledger_path=path,
        invoke_fn=make_screens([VETO_ROUND, PASS_ROUND]),
        refine_fn=lambda claim, fb, rnd: "z" * 5000)
    ev = report["events_appended"][0]
    assert len(ev["refined_claim"]) == rc.REFINED_CLAIM_MAX_CHARS
    idea_ledger.validate_event(ev)


# ── claim resolution (latest refined -> elite -> loop_memory join) ───────────

def test_cycle_resumes_from_latest_refined_claim(tmp_path):
    path = _ledger(tmp_path, [
        _created(),
        {"event_type": "cluster_refined", "ts": TS, "cluster_id": CID,
         "round": 1, "refined_claim": "previously refined text",
         "feedback_digest": "d"},
    ])
    calls = []
    report = rc.refine_cluster(CID, ledger_path=path,
                               invoke_fn=make_screens([PASS_ROUND], calls),
                               refine_fn=REFINE)
    assert report["claim_source"] == "refined_claim"
    assert report["starting_claim"] == "previously refined text"
    assert "previously refined text" in calls[0][3]  # surfaced in the prompt


def test_claim_joins_loop_memory_by_member_id(tmp_path):
    path = _ledger(tmp_path, [_created(claim=False, member="iter-x")])
    lm = tmp_path / "loop_memory.jsonl"
    lm.write_text(json.dumps({
        "iteration_id": "iter-x",
        "hypothesis": {"text": "hypothesis text from loop memory"},
    }) + "\n")
    calls = []
    report = rc.refine_cluster(CID, ledger_path=path, loop_memory_path=lm,
                               invoke_fn=make_screens([PASS_ROUND], calls),
                               refine_fn=REFINE)
    assert report["claim_source"] == "loop_memory:iter-x"
    assert "hypothesis text from loop memory" in calls[0][3]


def test_no_claim_surface_raises(tmp_path):
    path = _ledger(tmp_path, [_created(claim=False)])
    with pytest.raises(ValueError, match="no claim surface"):
        rc.refine_cluster(CID, ledger_path=path,
                          loop_memory_path=tmp_path / "absent.jsonl",
                          invoke_fn=make_screens([]), refine_fn=REFINE)


def test_unknown_cluster_raises(tmp_path):
    path = _ledger(tmp_path, [_created()])
    with pytest.raises(ValueError, match="unknown cluster"):
        rc.refine_cluster("cl-nope", ledger_path=path,
                          invoke_fn=make_screens([]), refine_fn=REFINE)


# ── MOCK_LLM discipline ──────────────────────────────────────────────────────

def test_mock_llm_refuses_uninjected_invoke_fn(tmp_path, monkeypatch):
    monkeypatch.setenv("MOCK_LLM", "1")
    path = _ledger(tmp_path, [_created()])
    with pytest.raises(ValueError, match="MOCK_LLM"):
        rc.refine_cluster(CID, ledger_path=path, refine_fn=REFINE)


def test_default_refine_under_mock_is_deterministic(monkeypatch):
    monkeypatch.setenv("MOCK_LLM", "1")
    feedback = [{"role": "methods_reviewer", "verdict": "veto",
                 "reasoning": "missing control", "closest_prior_work": None}]
    a = rc._default_refine("the claim", feedback, 2)
    b = rc._default_refine("the claim", feedback, 2)
    assert a == b
    assert "the claim" in a and "missing control" in a


# ── run log ──────────────────────────────────────────────────────────────────

def test_run_log_rows_per_round_agent_refine_cycle(tmp_path):
    # conftest's autouse fixture redirects the run log to tmp_path.
    path = _ledger(tmp_path, [_created()])
    rc.refine_cluster(CID, ledger_path=path,
                      invoke_fn=make_screens([VETO_ROUND, PASS_ROUND]),
                      refine_fn=REFINE)
    rows = [json.loads(l) for l in
            (tmp_path / "week1.run.jsonl").read_text().splitlines()]
    assert [r["status"] for r in rows] == ["refined", "passed"]
    for r in rows:
        assert r["agent"] == "refine_cycle"
        assert r["task_id"] == f"refine_cycle:{CID}"
        assert set(r) >= {"timestamp", "task_id", "agent", "status",
                          "observable_actual", "observable_expected",
                          "duration_ms"}


def test_run_log_kill_row_after_exhaustion(tmp_path):
    path = _ledger(tmp_path, [_created()])
    rc.refine_cluster(CID, ledger_path=path,
                      invoke_fn=make_screens([ADVERSARIAL_ROUND] * 5),
                      refine_fn=REFINE)
    rows = [json.loads(l) for l in
            (tmp_path / "week1.run.jsonl").read_text().splitlines()]
    assert [r["status"] for r in rows] == ["refined"] * 5 + ["killed"]


# ── CLI ──────────────────────────────────────────────────────────────────────

def test_cli_dry_run_writes_nothing(tmp_path, capsys):
    path = _ledger(tmp_path, [_created()])
    before = path.read_bytes()
    rcode = rc.main(["--cluster-id", CID, "--ledger", str(path), "--dry-run"])
    assert rcode == 0
    report = json.loads(capsys.readouterr().out)
    assert report["dry_run"] is True
    assert report["starting_claim"] == CLAIM_TEXT
    assert report["events_appended"] == []
    assert path.read_bytes() == before               # no ledger writes
    assert not (tmp_path / "week1.run.jsonl").exists()  # no run-log rows


def test_cli_max_rounds_over_cap_raises(tmp_path):
    path = _ledger(tmp_path, [_created()])
    with pytest.raises(ValueError):
        rc.main(["--cluster-id", CID, "--ledger", str(path),
                 "--max-rounds", "6", "--dry-run"])
