"""Optional read-only integration checks against the canonical cycle ledger.

The in-process app uses the same default data paths as the deployed backend.
Assertions follow the current action/provenance contract, without pinning row
counts, historical topic sources or a single latest study. No research data is
written. Clean checkouts skip checks that require the gitignored live ledger;
isolated source/error cases remain covered by test_coordinator.py.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import backend.app as app_module
from backend.app import create_app
from backend.coordinator import _read_jsonl

# The real, gitignored apparatus artifacts the merged backend reads. Pulled from
# the module constants (not re-hardcoded) so this test follows the same source
# of truth as the served app and survives a path change.
_CYCLES_PATH = app_module.DEFAULT_COORDINATOR_RUN_STATE / "coordinator_cycles.jsonl"

# Keys the frontend ``CoordinatorCycle`` type reads as non-optional
# (ui/frontend/src/types/schemas.ts). The card crashes / mis-renders if a real
# row is missing any of these, so every live row must carry them.
_REQUIRED_CYCLE_KEYS = (
    "timestamp",
    "run_id",
    "agent",
    "topic",
    "topic_source",
    "plan",
    "outcomes",
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    """The merged app over the REAL primary-checkout data (no path overrides)."""
    return TestClient(create_app())


# ─── /cycles — the 13 real rows the Coordinator view renders ───────────────


def test_cycles_endpoint_shape_against_real_data(client):
    resp = client.get("/api/coordinator/cycles")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"cycles"}
    assert isinstance(body["cycles"], list)


@pytest.mark.skipif(
    not _CYCLES_PATH.exists(),
    reason=f"real coordinator_cycles.jsonl absent ({_CYCLES_PATH}); gitignored",
)
def test_cycles_returns_every_real_row_newest_first(client):
    """/cycles serves exactly the rows on disk, newest-first by timestamp."""
    on_disk = _read_jsonl(_CYCLES_PATH)
    assert on_disk, "real coordinator_cycles.jsonl exists but parsed to 0 rows"

    cycles = client.get("/api/coordinator/cycles").json()["cycles"]
    # Every well-formed on-disk row is served (the endpoint skips only malformed
    # JSON lines, of which the real file has none).
    assert len(cycles) == len(on_disk)

    timestamps = [c["timestamp"] for c in cycles]
    assert timestamps == sorted(timestamps, reverse=True), "not newest-first"


@pytest.mark.skipif(
    not _CYCLES_PATH.exists(),
    reason=f"real coordinator_cycles.jsonl absent ({_CYCLES_PATH}); gitignored",
)
def test_every_real_cycle_has_the_keys_the_card_reads(client):
    """Each real row carries every non-optional CoordinatorCycle key — the
    Coordinator card reads these unconditionally."""
    cycles = client.get("/api/coordinator/cycles").json()["cycles"]
    for c in cycles:
        missing = [k for k in _REQUIRED_CYCLE_KEYS if k not in c]
        assert not missing, f"cycle {c.get('run_id')!r} missing keys {missing}"
        # The list-typed fields the card maps over must actually be lists, so a
        # `.map` never throws on a real row.
        assert isinstance(c["plan"], list)
        assert isinstance(c["outcomes"], list)
        assert isinstance(c.get("promoted_finding_ids", []), list)
        assert isinstance(c.get("bubble_run_ids", []), list)
        for step in c["plan"]:
            assert "action" in step  # CoordinatorPlanStep.action is required


@pytest.mark.skipif(
    not _CYCLES_PATH.exists(),
    reason=f"real coordinator_cycles.jsonl absent ({_CYCLES_PATH}); gitignored",
)
def test_real_errored_outcomes_carry_an_error_string(client):
    """The headline 'make absence legible' contract: a failed dispatch is a row,
    and an ``errored`` outcome carries a non-empty ``error`` so the red row shows
    *why*. Cohort-variant: the 2026-06-09 file held 2 such outcomes (RuntimeError:
    boom); the D-048 purge removed them, so this may assert over zero rows —
    vacuously green is the honest read of a clean cohort."""
    cycles = client.get("/api/coordinator/cycles").json()["cycles"]
    errored = [
        o
        for c in cycles
        for o in c["outcomes"]
        if o.get("status") == "errored"
    ]
    for o in errored:
        assert "action" in o  # CoordinatorOutcome.action is required
        assert isinstance(o.get("error"), str) and o["error"], (
            "an errored outcome must carry a non-empty error string so the "
            "failed-dispatch row renders the reason, not a silent gap"
        )


@pytest.mark.skipif(
    not _CYCLES_PATH.exists(),
    reason=f"real coordinator_cycles.jsonl absent ({_CYCLES_PATH}); gitignored",
)
def test_live_cycle_provenance_snapshot(client):
    """Pins the live-cohort provenance invariants: every real cycle is
    coordinator-authored with a KNOWN topic provenance. The old pin here —
    ``all(topic_source == "arxiv_pick")`` — was a 2026-06-09 snapshot that
    rotted when D-060 agenda-first went live (2026-08 cron cycles carry
    ``topic_source="agenda"``); per this module's own no-rotting-pins rule the
    invariant is now membership in the coordinator's suggestion-source enum
    (orchestrator/coordinator.py suggest sources + morning_topic seed.source),
    not a single hardcoded value. The errored sub-cohort is VARIANT —
    the 2026-06-09 snapshot held 2 ``RuntimeError: boom`` dispatch failures,
    which the 2026-06-10 D-048 purge removed — so instead of pinning a count
    that rots with the data, assert the failed-dispatch field semantics on
    whatever errored rows exist. An empty errored cohort is the honest
    post-purge state, never a fabricated expectation of failure."""
    known_topic_sources = {
        "campaign_preregistered",  # V2 exact immutable campaign topic
        "campaign_registered",  # source-bound topic registry receipt
        "agenda",  # D-060 agenda-first (idea-ledger agenda items lead)
        "finding_followup",  # queued human follow-up topics
        "coordinator_propose",  # P4 machine-mined rows (never human-masked)
        "arxiv_pick",  # morning pick primary (newest papers_recent title)
        "loop_memory_probe",  # morning pick fallback / gap angle
    }
    cycles = client.get("/api/coordinator/cycles").json()["cycles"]
    assert cycles, "expected ≥1 real coordinator cycle"
    assert all(c["agent"] == "coordinator" for c in cycles)
    # A cycle that never got to choose a topic has no topic_source, and that
    # is the honest value: the 2026-08-16 ledger carries nine
    # daily_budget_exhausted rows written before the refusal was moved out of
    # the cycle log. Topicless cycles may inspect existing promotion candidates
    # or escalate existing pending gates; neither dispatches new topic-dependent
    # research. Validate those actual action contracts rather than a stale list
    # of actions observed in one snapshot.
    for c in cycles:
        if c["topic_source"] is None:
            assert c.get("topic") is None
            for step in c.get("plan") or []:
                assert step.get("action") in {"noop", "bubble_up", "promote_findings"}, (
                    f"cycle {c.get('run_id')} planned {step.get('action')!r} "
                    "without a topic_source"
                )
                args = step.get("args", {})
                if step["action"] == "noop":
                    reason = args.get("reason")
                    assert isinstance(reason, str) and reason.strip()
                elif step["action"] == "promote_findings":
                    assert set(args) <= {"max_candidates"}
                    if "max_candidates" in args:
                        assert type(args["max_candidates"]) is int
                        assert args["max_candidates"] >= 1
                else:
                    from orchestrator.coordinator_actions import validate_bubble_up_args
                    validate_bubble_up_args(**{key: args.get(key) for key in
                                               ("finding_ids", "question", "kind", "allowed_actions")})
            for outcome in c.get("outcomes") or []:
                assert outcome.get("action") in {"noop", "bubble_up", "promote_findings"}, (
                    f"cycle {c.get('run_id')} reported "
                    f"{outcome.get('action')!r} without a topic_source"
                )
                if outcome.get("action") in {"bubble_up", "promote_findings"}:
                    assert any(outcome.get("request") == {"action": step["action"], "args": step["args"]}
                               for step in c.get("plan") or []
                               if step.get("action") == outcome["action"])
            continue
        assert c["topic_source"] in known_topic_sources
        if c["topic_source"] in {"campaign_preregistered", "campaign_registered"}:
            from orchestrator.research_campaign import load_campaign, record_matches
            assert isinstance(c.get("campaign"), dict)
            # The endpoint reads the canonical live ledger, so registered
            # topics must be joined against that checkout's private registry,
            # not this source worktree's empty run_state directory.
            campaign = load_campaign(
                c["campaign"]["campaign_id"],
                repo_root=_CYCLES_PATH.parent.parent,
            )
            assert record_matches(c, campaign)
    errored = [
        o for c in cycles for o in c["outcomes"] if o.get("status") == "errored"
    ]
    # When a failed dispatch IS present it must be legible: an action plus a
    # non-empty error string (the make-absence-legible contract).
    for o in errored:
        assert "action" in o
        assert isinstance(o.get("error"), str) and o["error"]


# (The findings / bubbles / health_signals / active validation cases died
# with those endpoints in UI simplification S3 — /api/coordinator/cycles is
# the one surviving coordinator endpoint; the D-047 registry serves the live
# run.)
