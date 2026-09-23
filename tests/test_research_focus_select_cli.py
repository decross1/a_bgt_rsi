"""`research_focus select` - the CLI half of G0.2, under D-084 section 4.1.

select_focus() landed with G0.1 (lab main 03c88d1) under compare-and-swap, but
nothing outside its own test called it and main() offered only `status` and
`close`, so no focus can be selected. Every check here runs the CLI against a
temp repo, so none of them writes the live run_state/research_focus/ or the live
pointer: this item ships the machine piece and does not select a focus.

The three required flags are the D-084 section 4.1 path - the G0.2 row says the
selection is "callable by Oracle after a meta review" - and `--authority` is
resolved against the repo's mailbox, not merely required, per review
claude-bfc06cece11638c0.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess

import pytest

from orchestrator import daily_research
from orchestrator import research_campaign
from orchestrator import research_focus as focus
from orchestrator import oracle_mailbox as mailbox


SELECTED_FOCUS = "focus-payoff-horizon"      # what `select` in select() below asks for
SELECTED_ITERATION = "iter-2026-09-15-007"   # a review must name both to bind


def head_of(root) -> str:
    """The fixture repo's HEAD sha, recorded by make_selectable at creation."""
    return (root / "GIT_HEAD_SHA").read_text().strip()


@pytest.fixture
def source(tmp_path, monkeypatch):
    """A temp repo holding one selectable loop-memory record."""
    return make_selectable(tmp_path, monkeypatch)


def make_selectable(root, monkeypatch):
    """Give `root` one selectable loop-memory record and stub the campaign matching.

    The repo is a real git checkout at a real commit, so the selector's HEAD binding is
    exercised rather than skipped; head_of(root) reports that sha (from the git dir, not
    a file in the tree, since the selector reads the tree) and a fixture note names it as
    the state it proposes at.
    """
    env = {**os.environ, "GIT_AUTHOR_NAME": "f", "GIT_AUTHOR_EMAIL": "f@e",
           "GIT_AUTHOR_DATE": "2026-09-23T00:00:00+00:00",
           "GIT_COMMITTER_NAME": "f", "GIT_COMMITTER_EMAIL": "f@e",
           "GIT_COMMITTER_DATE": "2026-09-23T00:00:00+00:00"}
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True, env=env)
    (root / "keep.txt").write_text("fixture\n")
    for cmd in (["add", "-A"], ["-c", "user.name=f", "-c", "user.email=f@e", "commit", "-q", "-m", "fixture"]):
        subprocess.run(["git", *cmd], cwd=root, check=True, env=env)
    (root / "GIT_HEAD_SHA").write_text(subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True,
        check=True).stdout.strip())
    (root / "memory").mkdir()
    row = {
        "iteration_id": "iter-2026-09-15-007",
        "campaign": {"campaign_id": "seed-campaign", "campaign_manifest_sha256": "a" * 64},
        "hypothesis": {"text": "Payoff error is dominated by horizon, not arithmetic."},
        "retrieval": {"relevance": {"low_confidence": False}},
        "novelty": {"class": "novel"},
        "critique": {"verdict": "survives"},
    }
    (root / "memory/loop_memory.jsonl").write_text(json.dumps(row) + "\n")
    monkeypatch.setattr(research_campaign, "load_campaign",
                        lambda name, **kw: {"campaign_id": name, "_manifest_sha256": "a" * 64})
    monkeypatch.setattr(research_campaign, "record_matches",
                        lambda row, campaign: (row.get("campaign", {})
                                               .get("campaign_manifest_sha256") == "a" * 64))
    return root


def post(root, actor, kind, body, in_reply_to=None, head_sha=None):
    """One mailbox row in the repo the selection runs against; returns its msg_id.

    head_sha goes into body.ref, the shape Oracle's READY/PROPOSED notes use on the
    live mailbox; the selector binds a selection note to the repo state it names.
    """
    path = root / "run_state/oracle_nara_mailbox.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    if head_sha is not None:
        body = {**body, "ref": {"repo": "a_bgt_rsi", "head_sha": head_sha}}
    return mailbox.post(actor, kind, body, to="oracle", in_reply_to=in_reply_to, path=path)["msg_id"]


def review(root, *, kind="review", verdict="accept", actor="claude", head_sha=None,
           focus_id=SELECTED_FOCUS, iteration_id=SELECTED_ITERATION, reply_text=None):
    """A meta-oracle accept of an Oracle 'FOCUS SELECTION PROPOSED' note - the shape
    the selector binds to: the review replies to an oracle note naming this focus_id,
    this iteration_id and this head_sha (review claude-b10f196463dc87ad, amendment 1).
    head_sha defaults to the repo's current HEAD, i.e. a proposal at the present state.
    """
    if head_sha is None:
        head_sha = head_of(root)
    proposal = post(root, "oracle", "note", {
        "title": f"FOCUS SELECTION PROPOSED: {focus_id}", "text": "Propose the successor focus.",
        "selection": {"focus_id": focus_id, "iteration_id": iteration_id}},
        in_reply_to=None, head_sha=head_sha)
    if kind != "review":  # a non-review row cannot carry a verdict, so it replies to the note
        return post(root, actor, kind, {"text": "ok"}, in_reply_to=proposal)
    return post(root, actor, kind, {"verdict": verdict, "text": reply_text or "ok"}, in_reply_to=proposal)


def select(root, *, expected="EMPTY", authority=None, selected_by="oracle", omit=(), extra=()):
    """Parse and run the `select` subparser against `root`.

    `expected="EMPTY"` stands for a first selection after a kill, which has no
    previous receipt to compare against and must be declared with
    --allow-empty-previous; pass a sha for a compare-and-swap selection.
    """
    argv = ["select", "--iteration-id", SELECTED_ITERATION, "--focus-id", SELECTED_FOCUS,
            "--title", "Payoff error decomposition", "--reason", "Continue the historical seed.",
            "--next-action", "Freeze the paired study.", "--next-gate-json",
            json.dumps({"from": "research_seed", "to": "study_ready", "artifact": "protocol",
                        "status": "pending", "owner": "Oracle + review"}),
            "--blocker", "Needs clean refinement."]
    if expected is not None and "expected" not in omit:
        argv += (["--allow-empty-previous"] if expected == "EMPTY" else ["--expected-receipt", expected])
    if selected_by is not None and "selected_by" not in omit:
        argv += ["--selected-by", selected_by]
    if authority is not None and "authority" not in omit:
        argv += ["--authority", authority]
    args = focus.build_parser().parse_args(argv + list(extra))
    return focus.run(args, root)


def test_select_cli_writes_the_receipt_and_the_pointer(source):
    root = source
    result = select(root, authority=review(root))
    assert result["status"] == "selected" and result["focus_id"] == "focus-payoff-horizon"
    assert result["intake_policy"] == "focus_before_new_topics" and result["selected_by"] == "oracle"
    receipt = root / focus.DIRECTORY / (result["receipt_sha256"] + ".json")
    assert receipt.is_file() and (root / focus.POINTER).is_file()
    assert focus.project_focus(root)["receipt_sha256"] == result["receipt_sha256"]
    assert json.loads(receipt.read_bytes())["execution_authorized"] is False  # selection is not credit


def test_select_cli_refuses_a_stale_expected_receipt_and_writes_nothing(source):
    root = source
    authority = review(root)
    with pytest.raises(focus.FocusError, match="changed since the reviewed digest"):
        select(root, expected="0" * 64, authority=authority)
    assert focus.project_focus(root)["status"] == "none"
    assert not (root / focus.POINTER).exists()
    assert not list((root / focus.DIRECTORY).glob("*.json")) if (root / focus.DIRECTORY).exists() else True


def test_select_cli_refuses_to_switch_a_live_focus(source):
    """Switching needs close first, and there is no override: --force is not even a
    defined flag on `select`, so an overwrite attempt dies at the parser."""
    root = source
    authority = review(root)
    selected = select(root, authority=authority)
    with pytest.raises(focus.FocusError, match="already selected"):
        select(root, expected=selected["receipt_sha256"], authority=authority)
    with pytest.raises(SystemExit):  # argparse: unrecognized arguments: --force
        select(root, expected=selected["receipt_sha256"], authority=authority, extra=["--force"])
    assert focus.project_focus(root)["focus_id"] == "focus-payoff-horizon"


def test_select_cli_refuses_when_any_of_the_three_flags_is_missing(source):
    """--selected-by, --authority and the receipt expectation (a sha, or an explicit
    --allow-empty-previous) are all refused when absent."""
    root = source
    authority = review(root)
    with pytest.raises(SystemExit):
        select(root, authority=authority, selected_by=None)
    with pytest.raises(SystemExit):
        select(root, selected_by="oracle", authority=None)
    with pytest.raises(SystemExit):
        select(root, authority=authority, expected=None)  # a first selection must declare itself
    with pytest.raises(SystemExit):
        select(root, authority=authority, omit=("expected",), extra=["--allow-empty-previous",
                                                                     "--expected-receipt", "0" * 64])
    assert focus.project_focus(root)["status"] == "none"


def test_authority_is_resolved_against_the_mailbox_and_not_merely_required(source):
    """Per review claude-bfc06cece11638c0: the row must exist in that repo's mailbox
    with actor in the reviewer set, kind=review, and body.verdict=accept."""
    root = source
    accepted = review(root)
    with pytest.raises(focus.FocusError, match="unknown mailbox msg_id"):
        select(root, authority="claude-does-not-exist-000000")
    with pytest.raises(focus.FocusError, match="verdict"):
        select(root, authority=review(root, verdict="amend"))
    with pytest.raises(focus.FocusError, match="verdict"):
        select(root, authority=review(root, verdict="reject"))
    with pytest.raises(focus.FocusError, match="kind"):
        select(root, authority=review(root, kind="note"))
    with pytest.raises(focus.FocusError, match="kind"):
        select(root, authority=review(root, kind="answer"))
    assert focus.project_focus(root)["status"] == "none"
    assert select(root, authority=accepted)["status"] == "selected"  # the good id works


def test_authority_must_carry_a_reviewers_actor(source):
    """The mailbox will not let a non-reviewer post a review (KINDS), so the only way to
    get such a row is to write the chain by hand; the selector must still refuse it."""
    import hashlib

    root = source
    accepted = review(root)  # a real review first, so the hand-written row chains off a valid head
    path = root / "run_state/oracle_nara_mailbox.jsonl"
    rows = mailbox.read(path)
    row = {"schema": mailbox.SCHEMA, "seq": len(rows) + 1, "ts": "2026-09-23T00:00:00+00:00", "actor": "nara",
           "to": "oracle", "kind": "review", "in_reply_to": rows[-1]["msg_id"],
           "body": {"verdict": "accept", "text": "hand-written: nara cannot post reviews"},
           "expires_at": None, "prev_sha256": rows[-1]["row_sha256"]}
    row["msg_id"] = "nara-" + hashlib.sha256(mailbox._canonical(row)).hexdigest()[:16]
    row["row_sha256"] = hashlib.sha256(mailbox._canonical(row)).hexdigest()
    with path.open("a") as handle:
        handle.write(json.dumps(row) + "\n")
    assert mailbox.read(path)[-1]["msg_id"] == row["msg_id"]  # a valid chain, wrong actor
    with pytest.raises(focus.FocusError, match="reviewer"):
        select(root, authority=row["msg_id"])
    assert focus.project_focus(root)["status"] == "none"
    assert select(root, authority=accepted)["status"] == "selected"  # the real review still works


# --- (b2) the authority must be about THIS selection (review claude-b10f196463dc87ad, amendment 1)


def test_an_accept_of_an_unrelated_item_does_not_authorize_a_selection(source):
    """Before this change the selector checked actor, kind and verdict only, so any
    accepting review in the mailbox - e.g. of a branch - authorized any focus."""
    root = source
    unrelated = post(root, "oracle", "plan_item", {
        "title": "Build a tool", "objective": "Unrelated work.", "task_class": "tooling",
        "allowed_write_paths": ["tools/x.py"],
        "acceptance": {"test_path": "tests/test_x.py", "test_content": "def test_x():\n    assert True\n",
                       "test_argv": ["python", "-m", "pytest", "-q", "tests/test_x.py"]}},
        in_reply_to=None)
    accept = post(root, "claude", "review", {"verdict": "accept", "text": "ship it"}, in_reply_to=unrelated)
    with pytest.raises(focus.FocusError, match="must reply to an oracle note or question"):
        select(root, authority=accept)
    assert focus.project_focus(root)["status"] == "none"


def test_an_accept_of_a_note_about_a_different_focus_or_iteration_is_refused(source):
    root = source
    with pytest.raises(focus.FocusError, match="does not name this selection"):
        select(root, authority=review(root, focus_id="focus-some-other-line"))
    assert focus.project_focus(root)["status"] == "none"
    with pytest.raises(focus.FocusError, match="does not name this selection"):
        select(root, authority=review(root, iteration_id="iter-2026-01-01-001"))
    assert focus.project_focus(root)["status"] == "none"


def test_a_selection_note_at_another_repo_head_is_refused(tmp_path, monkeypatch):
    """One review authorizes a selection at the state it was proposed on: the note
    carries ref.head_sha and it must equal the repo's HEAD, else re-propose. The
    owner's 2026-09-22 'kill and propose next' was a fresh note for this reason."""
    root = tmp_path / "repo"
    root.mkdir()
    root = make_selectable(root, monkeypatch)
    stale = review(root, head_sha="e" * 40)
    with pytest.raises(focus.FocusError, match="re-propose at the current HEAD"):
        select(root, authority=stale)
    assert focus.project_focus(root)["status"] == "none"
    assert select(root, authority=review(root))["status"] == "selected"


def test_a_reused_authority_is_refused(tmp_path, monkeypatch):
    """The receipt records selection_authority, so a second select under the same
    review is refused even after closing: one review, one selection."""
    root = tmp_path / "repo"
    root.mkdir()
    root = make_selectable(root, monkeypatch)
    authority = review(root)
    first = select(root, authority=authority)
    assert first["status"] == "selected"
    focus.close_focus(root, disposition="killed", reason="Probing reuse.",
                      reopening_conditions=["A named blocker."],
                      evidence_refs=["run_state/proposal.md"], closed_by="oracle",
                      authority="D-084 + test", expected_receipt_sha256=first["receipt_sha256"])
    assert focus.project_focus(root)["status"] == "none"
    with pytest.raises(focus.FocusError, match="one review, one selection"):
        select(root, authority=authority)
    assert focus.project_focus(root)["status"] == "none"


# --- (b1) the authority is persisted, not just echoed (review claude-b10f196463dc87ad, amendment 2)


def test_the_receipt_on_disk_records_the_authorizing_review(tmp_path, monkeypatch):
    """close_focus has persisted its authority since G0.1; a selection used to carry it
    only in the CLI's returned dict, so the audit trail was not on disk."""
    root = tmp_path / "repo"
    root.mkdir()
    root = make_selectable(root, monkeypatch)
    authority = review(root)
    result = select(root, authority=authority)
    on_disk = json.loads((root / focus.DIRECTORY / (result["receipt_sha256"] + ".json")).read_bytes())
    assert on_disk["selection_authority"] == authority
    assert focus.project_focus(root)["selection_authority"] == authority
    assert result["selection_authority"] == authority


def test_the_selected_focus_engages_the_hold_the_consumers_actually_report(tmp_path, monkeypatch):
    """The machine piece, read through its two consumers instead of asserted in prose: a
    newly selected focus uses intake_policy=focus_before_new_topics, which
    coordinator.py:1474-1475 holds as focus_pending with gate_reason=research_focus and
    research_ops_status.py:566-567 reports as research_focus_next_gate. Asserting a release
    would be wrong - only status=none releases intake, which is what close_focus returns."""
    import datetime

    from orchestrator import coordinator, research_ops_status

    root = tmp_path / "repo"          # a real path: select/close resolve their root
    root.mkdir()
    root = make_selectable(root, monkeypatch)
    campaign = {"campaign_id": "daily", "_manifest_sha256": "a" * 64,
                "topic_policy": {"mode": "registered_exploratory"}, "_repo_root": root,
                "campaign_actions": {"admitted": ["noop"], "deferred": []}}

    def cycle(run_id):
        return coordinator._coordinator_cycle(
            run_id=run_id, budget=6, dry_run=True, execute_handlers=None, backend=None, model=None,
            loop_memory_path=root / "loop.jsonl", surfaced_path=root / "surfaced.jsonl",
            feedback_path=root / "feedback.jsonl", active_run_path=root / "active.json", campaign=campaign)

    view = select(root, authority=review(root))
    # assess_state needs a campaign's public context (research_question and friends) that this
    # minimal manifest does not carry; tests/test_coordinator_research_focus.py stubs it the
    # same way. The focus branch itself, which is what is under test, runs unstubbed.
    monkeypatch.setattr(coordinator, "assess_state", lambda **_kw: {
        "topic_suggestions": [{"topic_id": "unused", "topic": "unused"}], "gaps": [],
        "vote_ready_iteration_ids": []})
    monkeypatch.setattr(coordinator.coordinator_cycle_log, "write_coordinator_cycle", lambda *_a: None)
    monkeypatch.setattr(coordinator.coordinator_cycle_log, "emit_health_signals", lambda *_a: None)
    monkeypatch.setattr(daily_research, "replenish",
                        lambda *_a: pytest.fail("intake must not run while a focus holds it"))
    report = cycle("focus-held")
    assert report["status"] == "focus_pending" and report["gate_reason"] == "research_focus"
    assert report["plan"] == report["executed"] == []
    assert report["state"]["research_focus"]["focus_id"] == "focus-payoff-horizon"
    assert report["state"]["research_focus"]["intake_policy"] == "focus_before_new_topics"
    status = research_ops_status.project_research_ops_status(
        repo_root=root, observed_at=datetime.datetime(2026, 9, 23, tzinfo=datetime.timezone.utc))
    assert status["research_focus"]["focus_id"] == "focus-payoff-horizon"
    assert status["next_work"]["code"] == "research_focus_next_gate"
    # Closing is the only way to release it: status=none, pointer gone, receipt retained.
    closed = focus.close_focus(root, disposition="killed", reason="Superseded by the closeout.",
                               reopening_conditions=["A market with observable payoff assistance."],
                               evidence_refs=["the payoff closeout"], closed_by="oracle",
                               authority="D-084 + meta review",
                               expected_receipt_sha256=view["receipt_sha256"])
    assert closed["status"] == "none" and not (root / focus.POINTER).exists()
    monkeypatch.setattr(daily_research, "read_loop_rows", lambda *_a: [])
    monkeypatch.setattr(daily_research, "replenish", lambda *_a: {"status": "ok", "reason": "replenished"})
    monkeypatch.setattr(coordinator, "plan", lambda state, **_kw: [])
    released = cycle("intake-released")
    # A cycle with nothing to do ends no_valid_plan; what matters is that it is no longer
    # the focus gate holding it, and that intake ran (the replenish stub above).
    assert released["status"] not in {"focus_pending", "focus_invalid"}
    assert released.get("gate_reason") != "research_focus"
    # assess_state's snapshot carries the focus only on the held path; here the proof that
    # the pointer is gone is closed["status"] == "none" plus the missing pointer above.
    assert "research_focus" not in released["state"]


def test_select_focus_docstring_cites_d084_instead_of_the_operator_only_rule():
    """D-084 section 4.1 replaced the operator-only rule; a docstring still saying
    'never called by a model' would make the next reader refuse a permitted selection."""
    doc = focus.select_focus.__doc__ or ""
    assert "never called by a model" not in doc
    assert "D-084" in doc


def test_the_existing_subcommands_still_parse():
    """main() gained a subcommand; `status` and `close` keep their flags."""
    parser = focus.build_parser()
    assert parser.parse_args(["status"]).command == "status"
    close = parser.parse_args(["close", "--disposition", "killed", "--reason", "r", "--reopen", "c",
                               "--closed-by", "oracle", "--authority", "D-084 + claude-x",
                               "--expected-receipt", "0" * 64])
    assert close.command == "close" and close.reopen == ["c"] and close.expected_receipt == "0" * 64
    with pytest.raises(SystemExit):
        parser.parse_args(["select", "--focus-id", "x"])  # a bare select is still refused
