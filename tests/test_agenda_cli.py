"""Tests for orchestrator.agenda_cli — the HUMAN acceptance step (GAP 1).

Hermetic: every path (agenda, status audit, idea ledger) is injectable and
pinned under tmp_path; no repo file is touched and no subprocess is spawned
(``main`` is driven with an argv LIST, the shape ui/backend execs).

Pinned behaviors:
  - accept writes BOTH rows and they are schema-valid: the idea-ledger events
    survive ``workers.idea_ledger.load_state`` (the real reducer) and land a
    PENDING agenda item with source ``frontier_proposed``; the audit row
    carries {proposal_id, status, ts, note, agent_id};
  - a proposal with no cluster_id gets a fresh ``cl-<proposal_id>`` cluster
    OPENED first (cluster_created, origin manual) — an agenda item on an
    unknown cluster would make the reducer raise for every reader;
  - a proposal NAMING an existing cluster lands on it with NO cluster_created;
  - dismiss writes the audit row ONLY — the ledger is byte-identical;
  - every refusal writes NOTHING: a bad verb (argparse exit 2), an unknown
    proposal id, a blank note, a blank topic override, a second accept, and a
    proposal naming a KILLED cluster (the evidence-keyed reopen gate — accept
    is not a way around `cluster_reopened`);
  - the duplicate-accept guard is a check-then-act and holds under CONCURRENT
    accepts (the flock): two processes racing one proposal yield exactly one
    agenda item and one audit row;
  - the proposals file is never edited in place; effective status is the LAST
    audit row (last-row-wins).
"""
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from orchestrator import agenda_cli
from workers.idea_ledger import load_state


PROPOSAL = {
    "proposal_id": "fa-4b8a1c85",
    "proposed_by": "frontier:claude",
    "topic": "Run the two L1 synthetic experiments as a paired batch",
    "rationale": "They are the only two ideas that survived the gates.",
    "status": "proposed",
    "ts": "2026-08-18T04:56:07.929187Z",
}

CODEX_PROPOSAL = {**PROPOSAL, "proposal_id": "fa-deadbeef",
                  "proposed_by": "frontier:codex",
                  "topic": "Characterize the redteam fatal-flaw distribution"}

DISTILLED_PROPOSAL = {**PROPOSAL, "proposal_id": "fa-d15111ed",
                      "proposed_by": "distilled:gemma",
                      "topic": "Drain the stale L0 cohort"}

LEDGER_CLUSTER = {
    "event_type": "cluster_created", "ts": "2026-08-01T00:00:00Z",
    "cluster_id": "cl-existing", "origin": "consolidation",
    "member_id": "iter-001",
}

# A graveyard cluster: created, then KILLED with the evidence-keyed reopening
# condition the reducer enforces (`articulated_delta`). This is the shape of
# the 89 redteam-killed clusters whose ONLY legitimate route back is a
# `cluster_reopened` event carrying that evidence_kind.
KILLED_CREATE = {
    "event_type": "cluster_created", "ts": "2026-08-01T00:00:00Z",
    "cluster_id": "cl-dead", "origin": "iteration", "member_id": "iter-dead",
}
KILLED_KILL = {
    "event_type": "cluster_killed", "ts": "2026-08-02T00:00:00Z",
    "cluster_id": "cl-dead",
    "kill_reason": {"code": "redteam_fatal_flaw",
                    "evidence_key": "iteration:iter-dead:redteam",
                    "detail": "redteam verdict fatal_flaw on iteration iter-dead"},
    "reopening_condition": {"requires": "new_evidence",
                            "evidence_kind": "articulated_delta"},
}
KILLED_REOPEN = {
    "event_type": "cluster_reopened", "ts": "2026-08-03T00:00:00Z",
    "cluster_id": "cl-dead",
    "evidence": {"evidence_kind": "articulated_delta",
                 "evidence_key": "iteration:iter-new:delta",
                 "detail": "the delta is the noisy-signal variant, not the killed claim"},
}


def _write(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows),
                    encoding="utf-8")
    return path


@pytest.fixture()
def paths(tmp_path):
    """{agenda, status, ledger} pinned under tmp_path. The agenda carries the
    three proposed_by families (frontier:claude / frontier:codex /
    distilled:*); the ledger carries one pre-existing cluster."""
    agenda = _write(tmp_path / "frontier_agenda.jsonl",
                    [PROPOSAL, CODEX_PROPOSAL, DISTILLED_PROPOSAL])
    ledger = _write(tmp_path / "idea_ledger.jsonl", [LEDGER_CLUSTER])
    return {"agenda": agenda, "status": tmp_path / "status.jsonl",
            "ledger": ledger}


def _argv(verb: str, paths: dict, *rest: str) -> list[str]:
    """The argv LIST shape ui/backend execs: `<verb> --flag value …`."""
    return [verb, *rest, "--agenda", str(paths["agenda"]),
            "--status", str(paths["status"]), "--ledger", str(paths["ledger"])]


def _lines(path: Path) -> list[dict]:
    if not Path(path).exists():
        return []
    return [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]


# ─── accept: both rows, schema-valid, reducible ──────────────────────────

def test_accept_writes_ledger_events_and_audit_row(paths, capsys):
    rc = agenda_cli.main(_argv(
        "accept", paths, "--proposal-id", "fa-4b8a1c85",
        "--note", "the two L1s are the only live experiments", "--by", "human:ui"))
    assert rc == 0

    events = _lines(paths["ledger"])
    # The pre-existing cluster + the two events this accept appended.
    assert [e["event_type"] for e in events[1:]] == [
        "cluster_created", "agenda_item_added"]
    created, added = events[1], events[2]
    assert created["cluster_id"] == "cl-fa-4b8a1c85"
    assert created["origin"] == "manual"
    assert created["member_id"] == "fa-4b8a1c85"
    assert added["source"] == "frontier_proposed"
    assert added["topic"] == PROPOSAL["topic"]

    # The REAL reducer accepts the file: a pending agenda item on the cluster.
    state = load_state(paths["ledger"])
    cluster = state["cl-fa-4b8a1c85"]
    assert cluster["agenda"] == [{"topic": PROPOSAL["topic"],
                                  "source": "frontier_proposed",
                                  "status": "pending",
                                  "ts": added["ts"]}]

    [audit] = _lines(paths["status"])
    assert audit["proposal_id"] == "fa-4b8a1c85"
    assert audit["status"] == "accepted"
    assert audit["agent_id"] == "human:ui"
    assert audit["note"] == "the two L1s are the only live experiments"
    assert audit["ts"].endswith("Z")
    assert audit["cluster_id"] == "cl-fa-4b8a1c85"

    # The proposals file is NEVER edited in place.
    assert _lines(paths["agenda"]) == [PROPOSAL, CODEX_PROPOSAL,
                                       DISTILLED_PROPOSAL]
    assert json.loads(capsys.readouterr().out)["status"] == "accepted"


def test_topic_override_is_what_lands_on_the_agenda(paths):
    assert agenda_cli.main(_argv(
        "accept", paths, "--proposal-id", "fa-deadbeef",
        "--topic-override", "narrower: cluster the 41 redteam kills by code",
        "--note", "scoped down")) == 0
    state = load_state(paths["ledger"])
    [item] = state["cl-fa-deadbeef"]["agenda"]
    assert item["topic"] == "narrower: cluster the 41 redteam kills by code"


def test_any_proposed_by_family_accepts_the_same_way(paths):
    for pid in ("fa-4b8a1c85", "fa-deadbeef", "fa-d15111ed"):
        assert agenda_cli.main(_argv(
            "accept", paths, "--proposal-id", pid, "--note", "n")) == 0
    state = load_state(paths["ledger"])
    for pid in ("fa-4b8a1c85", "fa-deadbeef", "fa-d15111ed"):
        assert state[f"cl-{pid}"]["agenda"][0]["source"] == "frontier_proposed"


def test_proposal_carrying_an_existing_cluster_id_adds_no_cluster(paths):
    _write(paths["agenda"], [{**PROPOSAL, "cluster_id": "cl-existing"}])
    assert agenda_cli.main(_argv(
        "accept", paths, "--proposal-id", "fa-4b8a1c85", "--note", "n")) == 0
    events = _lines(paths["ledger"])
    assert [e["event_type"] for e in events] == ["cluster_created",
                                                 "agenda_item_added"]
    assert events[1]["cluster_id"] == "cl-existing"


def test_proposal_naming_an_absent_cluster_is_refused_writing_nothing(paths, capsys):
    _write(paths["agenda"], [{**PROPOSAL, "cluster_id": "cl-nope"}])
    before = paths["ledger"].read_bytes()
    assert agenda_cli.main(_argv(
        "accept", paths, "--proposal-id", "fa-4b8a1c85", "--note", "n")) == 1
    assert paths["ledger"].read_bytes() == before
    assert not paths["status"].exists()
    assert "not in" in capsys.readouterr().err


# ─── the reopen gate: accept never resurrects a KILLED cluster ───────────
# A killed cluster's only route back is a `cluster_reopened` event carrying
# the evidence_kind recorded at kill time (workers/idea_ledger.py RAISES on a
# mismatch). An agenda item is not evidence and clears no kill — so accepting
# a proposal onto a killed cluster would put the graveyard direction at the
# HEAD of the coordinator's topic list with no reopen event at all. Both
# layers are pinned here and in tests/test_idea_projection.py.

def test_accept_refuses_a_killed_cluster_writing_nothing(paths, capsys):
    _write(paths["ledger"], [KILLED_CREATE, KILLED_KILL])
    _write(paths["agenda"], [{**PROPOSAL, "cluster_id": "cl-dead"}])
    before = paths["ledger"].read_bytes()

    assert agenda_cli.main(_argv("accept", paths, "--proposal-id",
                                 "fa-4b8a1c85", "--note", "resurrect it")) == 1

    # Nothing written: no ledger byte, no audit row.
    assert paths["ledger"].read_bytes() == before
    assert not paths["status"].exists()
    # The cluster is still dead and still un-reopened.
    state = load_state(paths["ledger"])
    assert state["cl-dead"]["status"] == "killed"
    assert state["cl-dead"]["agenda"] == []
    # The message names the LEGITIMATE route, with the recorded evidence_kind.
    err = capsys.readouterr().err
    assert "KILLED" in err
    assert "cluster_reopened" in err
    assert "articulated_delta" in err


def test_accept_refuses_a_killed_cluster_reached_by_the_derived_id(paths, capsys):
    """The `cl-<proposal_id>` fallback target can be killed too — the gate is
    on the cluster the item would land on, not on whether it was NAMED."""
    _write(paths["ledger"], [
        {**KILLED_CREATE, "cluster_id": "cl-fa-4b8a1c85"},
        {**KILLED_KILL, "cluster_id": "cl-fa-4b8a1c85"},
    ])
    before = paths["ledger"].read_bytes()
    assert agenda_cli.main(_argv("accept", paths, "--proposal-id",
                                 "fa-4b8a1c85", "--note", "n")) == 1
    assert paths["ledger"].read_bytes() == before
    assert not paths["status"].exists()
    assert "KILLED" in capsys.readouterr().err


def test_accept_lands_once_the_evidence_keyed_reopen_HAS_landed(paths):
    """The gate is not a wall: after a real `cluster_reopened` carrying the
    recorded evidence_kind, the same accept goes through. The governance is
    routed, not blocked."""
    _write(paths["ledger"], [KILLED_CREATE, KILLED_KILL, KILLED_REOPEN])
    _write(paths["agenda"], [{**PROPOSAL, "cluster_id": "cl-dead"}])
    assert agenda_cli.main(_argv("accept", paths, "--proposal-id",
                                 "fa-4b8a1c85", "--note", "delta articulated")) == 0
    state = load_state(paths["ledger"])
    assert state["cl-dead"]["status"] == "open"
    assert state["cl-dead"]["agenda"][0]["source"] == "frontier_proposed"


# ─── the duplicate-accept guard is check-then-act: it needs the lock ──────

def test_concurrent_accepts_yield_exactly_one_agenda_item(paths, tmp_path):
    """Two PROCESSES race the same proposal. Without the flock both read
    `proposed`, both pass the duplicate guard, and both append — the exact
    duplicate the guard exists to stop (the coordinator would run the topic
    twice). With it, one wins and the other refuses."""
    driver = tmp_path / "race.py"
    driver.write_text(textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {str(REPO_ROOT)!r})
        from orchestrator import agenda_cli
        time.sleep(float(sys.argv[1]))       # line the two starts up
        sys.exit(agenda_cli.main([
            "accept", "--proposal-id", "fa-4b8a1c85", "--note", "race",
            "--agenda", {str(paths['agenda'])!r},
            "--status", {str(paths['status'])!r},
            "--ledger", {str(paths['ledger'])!r}]))
    """), encoding="utf-8")

    procs = [subprocess.Popen([sys.executable, str(driver), "0.25"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
             for _ in range(2)]
    codes = sorted(p.wait(timeout=60) for p in procs)

    assert codes == [0, 1], "exactly one accept must win"
    added = [e for e in _lines(paths["ledger"])
             if e["event_type"] == "agenda_item_added"]
    assert len(added) == 1
    assert len(_lines(paths["status"])) == 1
    assert len(load_state(paths["ledger"])["cl-fa-4b8a1c85"]["agenda"]) == 1


# ─── dismiss: audit only ─────────────────────────────────────────────────

def test_dismiss_writes_audit_row_only(paths):
    before = paths["ledger"].read_bytes()
    assert agenda_cli.main(_argv(
        "dismiss", paths, "--proposal-id", "fa-deadbeef",
        "--note", "graveyard analysis, not a research topic")) == 0
    assert paths["ledger"].read_bytes() == before   # ledger untouched
    [audit] = _lines(paths["status"])
    assert audit == {"proposal_id": "fa-deadbeef", "status": "dismissed",
                     "ts": audit["ts"], "note": audit["note"],
                     "agent_id": "human:cli"}


def test_dismissed_proposal_can_still_be_accepted_later(paths):
    assert agenda_cli.main(_argv("dismiss", paths, "--proposal-id",
                                 "fa-deadbeef", "--note", "no")) == 0
    assert agenda_cli.main(_argv("accept", paths, "--proposal-id",
                                 "fa-deadbeef", "--note", "changed my mind")) == 0
    rows = _lines(paths["status"])
    assert [r["status"] for r in rows] == ["dismissed", "accepted"]
    assert agenda_cli.load_status(paths["status"])["fa-deadbeef"]["status"] == (
        "accepted")


# ─── refusals write NOTHING ──────────────────────────────────────────────

def test_out_of_enum_verb_writes_nothing(paths):
    before = paths["ledger"].read_bytes()
    with pytest.raises(SystemExit) as exc:
        agenda_cli.main(_argv("approve", paths, "--proposal-id", "fa-4b8a1c85",
                              "--note", "n"))
    assert exc.value.code == 2                    # argparse rejection
    assert paths["ledger"].read_bytes() == before
    assert not paths["status"].exists()


@pytest.mark.parametrize("verb", ["accept", "dismiss"])
def test_unknown_proposal_id_is_refused_writing_nothing(paths, verb, capsys):
    before = paths["ledger"].read_bytes()
    assert agenda_cli.main(_argv(verb, paths, "--proposal-id", "fa-ffffffff",
                                 "--note", "n")) == 1
    assert paths["ledger"].read_bytes() == before
    assert not paths["status"].exists()
    assert "no proposal" in capsys.readouterr().err


@pytest.mark.parametrize("verb", ["accept", "dismiss"])
def test_blank_note_is_refused_writing_nothing(paths, verb):
    before = paths["ledger"].read_bytes()
    assert agenda_cli.main(_argv(verb, paths, "--proposal-id", "fa-4b8a1c85",
                                 "--note", "   ")) == 1
    assert paths["ledger"].read_bytes() == before
    assert not paths["status"].exists()


def test_blank_topic_override_is_refused_writing_nothing(paths):
    before = paths["ledger"].read_bytes()
    assert agenda_cli.main(_argv(
        "accept", paths, "--proposal-id", "fa-4b8a1c85",
        "--topic-override", "  ", "--note", "n")) == 1
    assert paths["ledger"].read_bytes() == before
    assert not paths["status"].exists()


def test_second_accept_is_refused_writing_nothing(paths, capsys):
    assert agenda_cli.main(_argv("accept", paths, "--proposal-id",
                                 "fa-4b8a1c85", "--note", "n")) == 0
    after_first = paths["ledger"].read_bytes()
    audit_rows = len(_lines(paths["status"]))
    assert agenda_cli.main(_argv("accept", paths, "--proposal-id",
                                 "fa-4b8a1c85", "--note", "again")) == 1
    assert paths["ledger"].read_bytes() == after_first
    assert len(_lines(paths["status"])) == audit_rows
    assert "already accepted" in capsys.readouterr().err


def test_a_broken_ledger_refuses_loudly_and_writes_nothing(paths, capsys):
    paths["ledger"].write_text("{not json\n", encoding="utf-8")
    assert agenda_cli.main(_argv("accept", paths, "--proposal-id",
                                 "fa-4b8a1c85", "--note", "n")) == 1
    assert paths["ledger"].read_text() == "{not json\n"
    assert not paths["status"].exists()
    assert "rejected:" in capsys.readouterr().err


# ─── the status join the UI reads ────────────────────────────────────────

def test_effective_status_is_the_last_audit_row(paths):
    assert agenda_cli.effective_status(PROPOSAL, None) == "proposed"
    assert agenda_cli.effective_status(
        PROPOSAL, {"status": "dismissed"}) == "dismissed"
    # An audit row with an out-of-enum status is NOT believed (rule 4).
    assert agenda_cli.effective_status(
        PROPOSAL, {"status": "maybe"}) == "proposed"


def test_load_status_skips_out_of_enum_rows(paths):
    _write(paths["status"], [
        {"proposal_id": "fa-4b8a1c85", "status": "accepted", "ts": "t",
         "note": "n", "agent_id": "human:ui"},
        {"proposal_id": "fa-4b8a1c85", "status": "sortof", "ts": "t",
         "note": "n", "agent_id": "human:ui"},
    ])
    assert agenda_cli.load_status(paths["status"])[
        "fa-4b8a1c85"]["status"] == "accepted"
