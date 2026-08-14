"""Tests for workers.idea_projection — byte-stable ideas.md projection (P3/A4).

Hermetic + deterministic: pure functions over hand-built ledger-state dicts,
no files, no network, no model. The golden test pins the exact rendered bytes
with the LOCAL next-test-owed map forced (via monkeypatching the guarded
`_next_test_owed` seam to None), so the golden stays stable whether or not
the sibling `workers.evidence_ladder` module has landed.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from workers import idea_projection as ip


def _state() -> dict:
    """A representative reduced ledger state: 2 open, 2 killed, 1 surfaced,
    agenda items in both dict and list carrier shapes (+ one consumed)."""
    return {
        "cl-open-b": {
            "cluster_id": "cl-open-b",
            "status": "open",
            "evidence_level": "L2",
            "elite": {
                "claim": {"problem": "Vickrey bidder shading under budget caps",
                          "mechanism": "m", "predicted_effect": "e"},
                "iteration_id": "iter-001",
            },
            "members": ["iter-001"],
            "kill_reason": None,
            "reopening_condition": None,
            "origin": "loop",
            "last_event_ts": "2026-08-01T10:00:00Z",
        },
        "cl-open-a": {
            "cluster_id": "cl-open-a",
            "status": "open",
            "evidence_level": "L0",
            "elite": None,
            "topic": "Cournot capacity commitment with noisy signals",
            "members": [],
            "kill_reason": None,
            "reopening_condition": None,
            "origin": "coordinator_propose",
            "last_event_ts": "2026-08-02T09:00:00Z",
            "agenda": {"topic": "Cournot capacity commitment with noisy signals",
                       "source": "paper_gap", "status": "open"},
        },
        "cl-killed-a": {
            "cluster_id": "cl-killed-a",
            "status": "killed",
            "evidence_level": "L1",
            "elite": {"problem": "First-price reserve tuning beats VCG revenue",
                      "iteration_id": "iter-007"},
            "members": ["iter-007"],
            "kill_reason": {"code": "redteam_fatal_flaw",
                            "detail": "revenue equivalence violated by setup"},
            "reopening_condition": {"description": "an experiment_outcome with trials >= 30"},
            "origin": "loop",
            "last_event_ts": "2026-07-20T08:00:00Z",
        },
        "cl-killed-b": {
            "cluster_id": "cl-killed-b",
            "status": "killed",
            "evidence_level": "L0",
            "elite": None,
            "topic": "Zero-sum repeated matching pennies exploitability",
            "members": [],
            "kill_reason": {"code": "paper_niche"},
            "reopening_condition": None,
            "origin": "niche_seeded",
            "last_event_ts": "2026-07-25T08:00:00Z",
        },
        "cl-surfaced": {
            "cluster_id": "cl-surfaced",
            "status": "surfaced",
            "evidence_level": "L4",
            "elite": {"problem": "Surfaced finding not re-listed in Live work",
                      "iteration_id": "iter-011"},
            "members": ["iter-011"],
            "kill_reason": None,
            "reopening_condition": None,
            "origin": "loop",
            "last_event_ts": "2026-07-30T08:00:00Z",
            "agenda": [
                {"topic": "Follow-up: replication across tiers", "source": "meta_review"},
                {"topic": "Old consumed item", "source": "meta_review", "status": "consumed"},
            ],
        },
    }


GOLDEN = """\
# Ideas

## Live work

- Cournot capacity commitment with noisy signals · L0 · next: literature screen (relevance ok + novel + critique survives + redteam not fatal) · last touched 2026-08-02T09:00:00Z
- Vickrey bidder shading under budget caps · L2 · next: cross-tier comparison / replication evidence · last touched 2026-08-01T10:00:00Z

## Graveyard

- First-price reserve tuning beats VCG revenue · killed: redteam_fatal_flaw · reopen when: an experiment_outcome with trials >= 30
- Zero-sum repeated matching pennies exploitability · killed: paper_niche · reopen when: none recorded

## Agenda

- Cournot capacity commitment with noisy signals · source: paper_gap · cluster: cl-open-a
- Follow-up: replication across tiers · source: meta_review · cluster: cl-surfaced
"""


@pytest.fixture(autouse=True)
def _local_ladder_map(monkeypatch):
    """Force the local next-test-owed map so the golden is stable regardless
    of whether workers.evidence_ladder has landed in this checkout."""
    monkeypatch.setattr(ip, "_next_test_owed", None)


def test_golden_render():
    assert ip.render_ideas_md(_state()) == GOLDEN


def test_render_is_byte_stable_across_insertion_order():
    state = _state()
    # Same content, reversed insertion order + a JSON round-trip.
    shuffled = {k: copy.deepcopy(state[k]) for k in reversed(list(state))}
    roundtrip = json.loads(json.dumps(shuffled))
    a, b, c = ip.render_ideas_md(state), ip.render_ideas_md(shuffled), ip.render_ideas_md(roundtrip)
    assert a == b == c == GOLDEN
    assert ip.render_ideas_md(state) == a  # re-render of the same dict: identical


def test_empty_state_renders_placeholders():
    text = ip.render_ideas_md({})
    for section in ("## Live work", "## Graveyard", "## Agenda"):
        assert section in text
    assert text.count("(none)") == 3
    assert text.endswith("\n") and not text.endswith("\n\n")


def test_surfaced_cluster_not_in_live_or_graveyard():
    text = ip.render_ideas_md(_state())
    assert "Surfaced finding not re-listed" not in text


def test_evidence_ladder_import_used_when_present(monkeypatch):
    monkeypatch.setattr(ip, "_next_test_owed", lambda level: f"OWED<{level}>")
    text = ip.render_ideas_md(_state())
    assert "next: OWED<L2>" in text and "next: OWED<L0>" in text


def test_unknown_level_renders_explicitly_never_coerced():
    state = _state()
    state["cl-open-b"]["evidence_level"] = "L9"
    assert "unknown level 'L9'" in ip.render_ideas_md(state)


def test_agenda_topics_shape_and_consumed_skip():
    topics = ip.agenda_topics(_state())
    assert topics == [
        {"topic": "Cournot capacity commitment with noisy signals",
         "source": "paper_gap", "cluster_id": "cl-open-a"},
        {"topic": "Follow-up: replication across tiers",
         "source": "meta_review", "cluster_id": "cl-surfaced"},
    ]
    assert all(set(t) == {"topic", "source", "cluster_id"} for t in topics)


def test_agenda_topic_and_source_fallbacks():
    state = {
        "cl-x": {
            "cluster_id": "cl-x", "status": "open", "evidence_level": "L0",
            "elite": {"problem": "Fallback stem problem"}, "members": [],
            "kill_reason": None, "reopening_condition": None,
            "origin": "coordinator_propose", "last_event_ts": "t",
            "agenda": {},  # no topic, no source
        },
    }
    assert ip.agenda_topics(state) == [
        {"topic": "Fallback stem problem", "source": "coordinator_propose",
         "cluster_id": "cl-x"},
    ]


def test_conditioning_lines_adjacent_graveyard_plus_agenda():
    lines = ip.conditioning_lines(_state(), "reserve tuning in first-price auctions")
    killed = [l for l in lines if l.startswith("KILLED prior")]
    assert len(killed) == 1
    assert "cl-killed-a" in killed[0]
    assert "redteam_fatal_flaw" in killed[0]
    assert "reopen only if: an experiment_outcome with trials >= 30" in killed[0]
    agenda = [l for l in lines if l.startswith("AGENDA")]
    assert len(agenda) == 2 and "paper_gap" in agenda[0]


def test_conditioning_lines_off_topic_has_no_graveyard_lines():
    lines = ip.conditioning_lines(_state(), "quantum chromodynamics lattice spacing")
    assert not any(l.startswith("KILLED prior") for l in lines)
    assert all(l.startswith("AGENDA") for l in lines)


def test_conditioning_lines_caps_and_ordering():
    state = {}
    for i in range(8):
        cid = f"cl-k{i}"
        state[cid] = {
            "cluster_id": cid, "status": "killed", "evidence_level": "L0",
            "elite": None, "topic": f"reserve pricing variant number{i}",
            "members": [], "kill_reason": {"code": "dup"},
            "reopening_condition": None, "origin": "loop", "last_event_ts": "t",
        }
    lines = ip.conditioning_lines(state, "reserve pricing")
    killed = [l for l in lines if l.startswith("KILLED prior")]
    assert len(killed) == ip.GRAVEYARD_MATCH_CAP
    # Equal overlap -> deterministic cluster_id tiebreak.
    assert [f"cl-k{i}" in l for i, l in enumerate(killed)] == [True] * len(killed)


def test_stem_truncation_is_stable():
    long_problem = "word " * 40
    state = {
        "cl-long": {
            "cluster_id": "cl-long", "status": "open", "evidence_level": "L0",
            "elite": {"problem": long_problem}, "members": [],
            "kill_reason": None, "reopening_condition": None,
            "origin": "loop", "last_event_ts": "t",
        },
    }
    a = ip.render_ideas_md(state)
    assert a == ip.render_ideas_md(copy.deepcopy(state))
    stem_line = [l for l in a.splitlines() if l.startswith("- ")][0]
    stem = stem_line[2:].split(" · ")[0]
    assert len(stem) <= ip.STEM_MAX and stem.endswith("...")
