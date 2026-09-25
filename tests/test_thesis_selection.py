"""Adversarial tests for the real-Nara-receipt thesis-selection path."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from orchestrator import nara_lane as lane
from orchestrator import oracle_mailbox as mailbox
from orchestrator import research_focus
from orchestrator import thesis_selection as thesis


def _git_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "tools").mkdir()
    (root / "tools/__init__.py").write_text("")
    (root / "README").write_text("test\n")
    (root / "docs/v2").mkdir(parents=True)
    (root / "docs/v2/THESIS_BRIEF_2026-09-23.md").write_text("ratified thesis brief\n")
    (root / "DECISIONS.md").write_text("D-087 conviction forecasts\n")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=root, check=True)
    (root / "config/nara_lane.json").write_text(json.dumps({"require_meta_review": True}))
    return root


def _primary(candidate_id: str, nonce: str = "") -> tuple[str, bytes]:
    locator = f"doi:10.1000/{candidate_id}"
    return (f"notes/primary/{candidate_id}.txt",
            f"Primary study {candidate_id} {nonce}; locator {locator}; observed result.\n".encode())


def _conviction(seed: float = 0.4) -> dict:
    return {"p_pass_t": seed, "p_pass_s": seed, "p_pass_a": seed,
            "p_dead_end": 1 - seed, "interest_0_10": 7,
            "reasons": {"p_pass_t": "A solvable benchmark is specified.",
                        "p_pass_s": "The local-agent design is bounded.",
                        "p_pass_a": "The applied route remains a proposal.",
                        "p_dead_end": "Primary evidence may falsify the mechanism.",
                        "interest_0_10": "The information-and-beliefs question is useful."}}


def _card(candidate_id: str, prior: str = "verified", nonce: str = "") -> dict:
    path, raw = _primary(candidate_id, nonce)
    sources = [] if prior == "unknown" else [{"locator": f"doi:10.1000/{candidate_id}", "claim": "Relevant primary result.", "source_path": path, "source_sha256": hashlib.sha256(raw).hexdigest()}]
    return {"candidate_id": candidate_id, "title": f"Candidate {candidate_id}",
      "lenses": ["behavioral_economics"], "mechanism": "Provenance changes belief updating under uncertainty.",
      "theory": {"game": "finite disclosure game", "players": "sender and receiver", "actions": "disclose or withhold", "information_structure": "sender observes type", "solution_concept": "Bayesian Nash equilibrium", "benchmark": "equilibrium posterior", "prediction": "disclosure changes action", "falsifier": "no treatment difference", "predeclared_decision_rule": "Reject when the preregistered contrast is zero."},
      "experiment": {"benchmark": "frozen prompt suite", "arms": [{"arm_id": "control", "treatment": "no disclosure"}, {"arm_id": "treat", "treatment": "timestamp disclosure"}], "sample_plan": {"unit": "independent episode", "target_n": 40, "missingness": "record all parse failures"}, "outcome": "receiver action rate", "falsifier": "predefined zero effect interval"},
      "applied": {"venue": "archived prediction venue", "data": "public historical disclosures", "as_of": "2026-09-01", "measurement": "timestamp-conditioned action", "limitation": "not causal without experiment"},
      "prior_work": {"status": prior, "summary": "Screened without claiming completeness.", "sources": sources},
      "anomaly_branches": [{"outcome": "reversal", "next_hypothesis": "pre-register adversarial credibility mechanism"}, {"outcome": "null", "next_hypothesis": "test a boundary condition"}], "estimated_flash_hours": 2, "conviction": _conviction()}


def _sandbox(worktree: Path, argv: list[str], timeout: float = 0) -> tuple[int, str]:
    done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *argv[4:]], cwd=worktree,
                          capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(worktree), "PYTHONDONTWRITEBYTECODE": "1"})
    return done.returncode, done.stdout + done.stderr


def _focus() -> dict:
    return {"focus_id": "thesis-c-alpha", "title": "Candidate c-alpha", "selection_reason": "Reviewed canonical selection.", "next_action": "Write the preregistered protocol.", "next_gate": {"from": "thesis_selected", "to": "study_ready", "artifact": "protocol", "status": "pending", "owner": "Oracle"}, "blockers": ["Execution remains separately gated."], "stage": "needs_clean_refinement", "intake_policy": "focus_before_new_topics", "initial_convictions": {"nara": _card("c-alpha")["conviction"], "oracle": _conviction(0.5), "claude": _conviction(0.45)}}


def _produce(root: Path, monkeypatch, *, nonce: str = "") -> tuple[dict, dict, dict]:
    """Run the actual Nara plan -> implementation -> terminal receipt route."""
    candidates = [_card("c-zeta", nonce=nonce), _card("c-alpha", nonce=nonce), _card("c-mid", "unknown", nonce)]
    declaration = {"schema_version": "nara-thesis-candidate-source/v1", "set_id": "g11-candidates", "path": "notes/nara_candidates.json", "base_sha": subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True).stdout.strip()}
    content = thesis._canonical({"schema_version": declaration["schema_version"], "set_id": declaration["set_id"], "candidates": candidates}).decode()
    primary_files = {path: raw.decode() for candidate in candidates for path, raw in [_primary(candidate["candidate_id"], nonce)] if candidate["prior_work"]["status"] == "verified"}
    acceptance = "import json\nfrom pathlib import Path\ndef test_candidate_source():\n payload=json.loads(Path('notes/nara_candidates.json').read_text())\n assert payload['schema_version']=='nara-thesis-candidate-source/v1'\n assert payload['set_id']=='g11-candidates'\n assert len(payload['candidates']) == 3\n"
    mailbox_path = root / "run_state/oracle_nara_mailbox.jsonl"
    plan = mailbox.post("oracle", "plan_item", {"title": "Nara candidate source", "objective": "Commit the declared candidate source.", "task_class": "documentation", "allowed_write_paths": [declaration["path"], *sorted(primary_files)], "acceptance": {"test_path": "tests/test_candidate_source.py", "test_content": acceptance, "test_argv": ["python", "-m", "pytest", "-q", "tests/test_candidate_source.py"]}, "budget": {"attempts": 1, "wall_clock_minutes": 5}, "thesis_candidate_source": declaration}, to="nara", path=mailbox_path)
    mailbox.post("claude", "review", {"verdict": "accept"}, to="oracle", in_reply_to=plan["msg_id"], path=mailbox_path)
    monkeypatch.setattr(lane, "ROOT", root); monkeypatch.setattr(lane, "WORKTREES", root.parent / "nara-worktrees")
    monkeypatch.setattr(lane, "RUN_LOG", root.parent / "nara-run.jsonl"); monkeypatch.setattr(lane, "_prechecked", lambda _item, **_kwargs: True)
    posted = lane.run_queue(
        mailbox_path,
        build=lambda *_args, **_kwargs: {declaration["path"]: content, **primary_files},
        sandbox=_sandbox,
        ready=lambda: True,
    )
    assert any(row["body"]["state"] == "validated" for row in posted), repr(posted)
    terminal = next(row for row in posted if row["body"]["state"] == "validated")
    source_path, head = declaration["path"], terminal["body"]["head_sha"]
    blob = subprocess.run(["git", "ls-tree", head, "--", source_path], cwd=root, check=True, text=True, capture_output=True).stdout.split()[2]
    raw = subprocess.run(["git", "show", f"{head}:{source_path}"], cwd=root, check=True, capture_output=True).stdout
    def object_sha(path: str) -> str:
        return hashlib.sha256(subprocess.run(["git", "show", f"{head}:{path}"], cwd=root, check=True, capture_output=True).stdout).hexdigest()
    source = {"receipt_msg_id": terminal["msg_id"], "receipt_row_sha256": terminal["row_sha256"], "branch": terminal["body"]["branch"], "base_sha": terminal["body"]["base_sha"], "head_sha": head, "path": source_path, "blob_sha256": hashlib.sha256(raw).hexdigest(), "git_blob_oid": blob, "thesis_brief_path": "docs/v2/THESIS_BRIEF_2026-09-23.md", "thesis_brief_sha256": object_sha("docs/v2/THESIS_BRIEF_2026-09-23.md"), "decision_path": "DECISIONS.md", "decision_sha256": object_sha("DECISIONS.md")}
    proposal = {"schema_version": thesis.SCHEMA_SET, "set_id": declaration["set_id"], "proposed_at": "2026-09-01T00:00:00+00:00", "proposed_by": "nara", "source": source, "candidates": candidates, "execution_authorized": False, "scientific_credit": "none_proposal_only"}
    return proposal, terminal, plan


def _screen(set_sha: str, stamp: str = "2026-09-01T00:01:00+00:00") -> dict:
    fields = ("theory", "experiment", "applied", "prior_work")
    def evaluation(candidate_id: str, score: int = 2) -> dict:
        return {"candidate_id": candidate_id, "verdicts": {key: "pass" for key in fields}, "dimension_scores": {key: score for key in fields}, "evidence": {key: [{"locator": f"receipt:{candidate_id}:{key}", "note": "Bounded reviewer finding."}] for key in fields}, "reason": "Evidence covers every eligibility gate."}
    return {"schema_version": thesis.SCHEMA_SCREEN, "candidate_set_sha256": set_sha, "screened_at": stamp, "screened_by": "oracle", "evaluations": [evaluation("c-zeta"), evaluation("c-alpha"), evaluation("c-mid", 3)], "execution_authorized": False, "scientific_credit": "none_screen_only"}


def _staged(root: Path, monkeypatch, *, nonce: str = "") -> tuple[dict, dict]:
    source_set, _terminal, _plan = _produce(root, monkeypatch, nonce=nonce)
    mailbox_path = root / "run_state/oracle_nara_mailbox.jsonl"
    terminal_stamp = next(row["ts"] for row in mailbox.read(mailbox_path) if row["msg_id"] == source_set["source"]["receipt_msg_id"])
    source_set["proposed_at"] = terminal_stamp
    proposed = thesis.create_candidate_set(root, source_set)
    screened = thesis.create_screen(root, proposed["candidate_set_sha256"], _screen(proposed["candidate_set_sha256"], terminal_stamp))
    binding = {"candidate_set_sha256": proposed["candidate_set_sha256"], "screen_sha256": screened["screen_sha256"], "chosen_candidate_id": "c-alpha", "reviewed_head": thesis._head(root), "focus_generation": research_focus.selection_generation(root)}
    proposal_row = mailbox.post("oracle", "note", {"thesis_selection": binding, "thesis_focus": _focus()}, to="all", path=mailbox_path)
    review = mailbox.post("claude", "review", {"verdict": "accept", "thesis_selection": binding, "thesis_focus": _focus()}, to="all", in_reply_to=proposal_row["msg_id"], path=mailbox_path)
    return {"schema_version": thesis.SCHEMA_ACCEPT, **binding, "accepted_at": review["ts"], "review_msg_id": review["msg_id"], "review_row_sha256": review["row_sha256"], "proposal_msg_id": proposal_row["msg_id"], "proposal_row_sha256": proposal_row["row_sha256"], "execution_authorized": False, "scientific_credit": "none_accept_only"}, source_set


def _append_review(root: Path, accept: dict, verdict: str) -> dict:
    return mailbox.post("claude", "review", {"verdict": verdict, "thesis_selection": {key: accept[key] for key in ("candidate_set_sha256", "screen_sha256", "chosen_candidate_id", "reviewed_head", "focus_generation")}, "thesis_focus": _focus()}, to="all", in_reply_to=accept["proposal_msg_id"], path=root / "run_state/oracle_nara_mailbox.jsonl")


def _primary_source_ref(source_set: dict) -> str:
    source = next(card for card in source_set["candidates"] if card["candidate_id"] == "c-alpha")["prior_work"]["sources"][0]
    return f"{source['source_path']}@sha256:{source['source_sha256']}"


def _rehash(root: Path, mutate) -> None:
    path = root / "run_state/oracle_nara_mailbox.jsonl"; rows = [json.loads(line) for line in path.read_text().splitlines()]
    mutate(rows); previous = None
    for index, row in enumerate(rows, 1):
        row["seq"], row["prev_sha256"] = index, previous; row.pop("row_sha256", None)
        row["row_sha256"] = hashlib.sha256(thesis._canonical(row)).hexdigest(); previous = row["row_sha256"]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def test_real_nara_terminal_receipt_feeds_cli_selection(tmp_path, monkeypatch, capsys):
    root = _git_root(tmp_path); accept, source_set = _staged(root, monkeypatch)
    created = thesis.create_meta_accept(root, accept)
    assert thesis.main(["select", "--meta-accept", created["meta_accept_sha256"], "--reason", "Reviewed canonical selection."], repo_root=root) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "selected"
    focus = research_focus.project_focus(root)
    assert focus["status"] == "selected" and focus["source_quality"] == "thesis_candidate_screen"
    assert focus["candidate_set_sha256"] == accept["candidate_set_sha256"]
    conviction_rows = (root / research_focus.CONVICTION_LEDGER).read_bytes().splitlines()
    assert len(conviction_rows) == 3
    assert {json.loads(row)["forecaster"] for row in conviction_rows} == {"nara", "oracle", "claude"}
    assert all(set(json.loads(row)) == {"thesis", "forecaster", "at", "p_pass_T", "p_pass_S", "p_pass_A", "p_dead_end", "interest_0_10", "reasons", "trigger"} for row in conviction_rows)
    assert {hashlib.sha256(row).hexdigest() for row in conviction_rows} == {
        item["row_sha256"] for item in focus["initial_conviction_rows"]
    }
    assert source_set["source"]["branch"].startswith("nara/") and not (root / "memory/loop_memory.jsonl").exists()


def test_live_question_resolution_rows_do_not_invalidate_selection_snapshot(tmp_path, monkeypatch):
    root = _git_root(tmp_path)
    accept, _source = _staged(root, monkeypatch)
    mailbox_path = root / "run_state/oracle_nara_mailbox.jsonl"
    question = mailbox.post("oracle", "question", {"prompt": "Is a separate card needed?"}, to="owner", path=mailbox_path)
    mailbox.post("oracle", "question_resolution", {
        "disposition": "informational", "summary": "The selection is a note, not a card.",
        "reason": "Selection never requests an owner vote.",
    }, to="owner", in_reply_to=question["msg_id"], path=mailbox_path)
    assert thesis.create_meta_accept(root, accept)["chosen_candidate_id"] == "c-alpha"


def test_old_empty_generation_review_cannot_win_after_select_then_kill_aba(tmp_path, monkeypatch):
    root = _git_root(tmp_path)
    old_accept, _source = _staged(root, monkeypatch)
    old = thesis.create_meta_accept(root, old_accept)
    newer_accept, _source = _staged(root, monkeypatch, nonce="newer")
    newer = thesis.create_meta_accept(root, newer_accept)
    selected = thesis.select_thesis_focus(root, meta_accept_sha256=newer["meta_accept_sha256"], reason="Reviewed canonical selection.")
    research_focus.close_focus(root, disposition="killed", reason="Bounded negative result.",
                                reopening_conditions=["Fresh primary evidence."], evidence_refs=["receipt"],
                                closed_by="oracle", authority="review", expected_receipt_sha256=selected["receipt_sha256"])
    assert research_focus.project_focus(root)["status"] == "none"
    with pytest.raises(thesis.ThesisSelectionError, match="focus generation"):
        thesis.select_thesis_focus(root, meta_accept_sha256=old["meta_accept_sha256"], reason="Reviewed canonical selection.")


@pytest.mark.parametrize("state", ["failed", "held"])
def test_nonvalidated_nara_terminal_receipts_are_refused(tmp_path, monkeypatch, state):
    root = _git_root(tmp_path); accept, source_set = _staged(root, monkeypatch)
    plan_id = source_set["source"]["branch"].removeprefix("nara/")
    failed = mailbox.post("nara", "receipt", {"state": state, "branch": source_set["source"]["branch"], "head_sha": source_set["source"]["head_sha"]}, to="oracle", in_reply_to=plan_id, path=root / "run_state/oracle_nara_mailbox.jsonl")
    bad = copy.deepcopy(source_set); bad["source"]["receipt_msg_id"], bad["source"]["receipt_row_sha256"] = failed["msg_id"], failed["row_sha256"]
    proposed = thesis.create_candidate_set(root, bad); screened = thesis.create_screen(root, proposed["candidate_set_sha256"], _screen(proposed["candidate_set_sha256"]))
    accept["candidate_set_sha256"], accept["screen_sha256"] = proposed["candidate_set_sha256"], screened["screen_sha256"]
    with pytest.raises(thesis.ThesisSelectionError, match="validated terminal"):
        thesis.create_meta_accept(root, accept)


@pytest.mark.parametrize("key,value,reason", [("branch", "nara/not-the-plan", "branch"), ("head_sha", "0" * 40, "head"), ("path", "other.json", "declaration"), ("blob_sha256", "0" * 64, "blob hash")])
def test_receipt_branch_head_and_declared_path_must_match(tmp_path, monkeypatch, key, value, reason):
    root = _git_root(tmp_path); accept, source_set = _staged(root, monkeypatch)
    bad = copy.deepcopy(source_set); bad["source"][key] = value
    proposed = thesis.create_candidate_set(root, bad); screened = thesis.create_screen(root, proposed["candidate_set_sha256"], _screen(proposed["candidate_set_sha256"]))
    accept["candidate_set_sha256"], accept["screen_sha256"] = proposed["candidate_set_sha256"], screened["screen_sha256"]
    with pytest.raises(thesis.ThesisSelectionError, match=reason):
        thesis.create_meta_accept(root, accept)


def test_candidate_head_must_descend_from_the_plan_pinned_base(tmp_path, monkeypatch):
    root = _git_root(tmp_path)
    _accept, source_set = _staged(root, monkeypatch)
    original_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True).stdout.strip()
    source_head = source_set["source"]["head_sha"]
    # Same tree and blobs on an unrelated root used to pass a base..head diff.
    # A plan base is causal provenance, not merely a convenient diff endpoint.
    subprocess.run(["git", "checkout", "--orphan", "unrelated"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "read-tree", source_head], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "same tree, unrelated root"], cwd=root, check=True)
    unrelated_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True).stdout.strip()
    subprocess.run(["git", "checkout", "-q", original_head], cwd=root, check=True)
    bad = copy.deepcopy(source_set)
    bad["source"]["head_sha"] = unrelated_head
    source_id = bad["source"]["receipt_msg_id"]
    _rehash(root, lambda rows: [row["body"].update({"head_sha": unrelated_head}) for row in rows if row["msg_id"] == source_id])
    bad["source"]["receipt_row_sha256"] = next(
        row["row_sha256"] for row in mailbox.read(root / "run_state/oracle_nara_mailbox.jsonl") if row["msg_id"] == source_id
    )
    with pytest.raises(thesis.ThesisSelectionError, match="does not descend from the plan base"):
        thesis._verify_candidate_provenance(root, bad, "0" * 64, admission=False)


def test_git_evidence_rejects_a_symlink_blob(tmp_path):
    root = _git_root(tmp_path)
    (root / "evidence-link").symlink_to("README")
    subprocess.run(["git", "add", "evidence-link"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "add evidence symlink"], cwd=root, check=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True).stdout.strip()
    with pytest.raises(thesis.ThesisSelectionError, match="not a regular Git file"):
        thesis._git_regular_blob(root, head, "evidence-link")


def test_empty_screen_leaves_no_focus_and_needs_no_owner_decision(tmp_path):
    """A truthful empty screen is terminal for this pass, not a vote prompt."""
    root = _git_root(tmp_path)
    candidates = [_card("c-zeta"), _card("c-alpha"), _card("c-mid")]
    proposed = thesis.create_candidate_set(root, {
        "schema_version": thesis.SCHEMA_SET,
        "set_id": "empty-screen",
        "proposed_at": "2026-09-01T00:00:00+00:00",
        "proposed_by": "nara",
        "source": {
                "receipt_msg_id": "nara-receipt",
                "receipt_row_sha256": "1" * 64,
                "branch": "nara/plan-empty",
                "base_sha": "5" * 40,
                "head_sha": "2" * 40,
                "path": "notes/nara_candidates.json",
                "blob_sha256": "3" * 64,
                "git_blob_oid": "4" * 40,
                "thesis_brief_path": "docs/v2/THESIS_BRIEF_2026-09-23.md",
                "thesis_brief_sha256": "6" * 64,
                "decision_path": "DECISIONS.md",
                "decision_sha256": "7" * 64,
        },
        "candidates": candidates,
        "execution_authorized": False,
        "scientific_credit": "none_proposal_only",
    })
    screen = _screen(proposed["candidate_set_sha256"])
    for evaluation in screen["evaluations"]:
        evaluation["verdicts"]["prior_work"] = "fail"
    screened = thesis.create_screen(root, proposed["candidate_set_sha256"], screen)
    assert screened["eligible_ids"] == []
    assert research_focus.project_focus(root)["status"] == "none"
    assert not (root / "run_state/oracle_nara_mailbox.jsonl").exists()


def test_stale_reviewed_head_is_refused_before_focus_install(tmp_path, monkeypatch):
    root = _git_root(tmp_path)
    accept, _source = _staged(root, monkeypatch)
    (root / "README").write_text("later state\\n")
    subprocess.run(["git", "add", "README"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "later state"], cwd=root, check=True)
    with pytest.raises(thesis.ThesisSelectionError, match="reviewed head is stale"):
        thesis.create_meta_accept(root, accept)


def test_duplicate_cas_selection_cannot_replace_an_active_focus(tmp_path, monkeypatch):
    root = _git_root(tmp_path)
    accept, _source = _staged(root, monkeypatch)
    created = thesis.create_meta_accept(root, accept)
    first = thesis.select_thesis_focus(
        root,
        meta_accept_sha256=created["meta_accept_sha256"],
        reason="Reviewed canonical selection.",
    )
    with pytest.raises(research_focus.FocusError, match="active focus"):
        thesis.select_thesis_focus(
            root,
            meta_accept_sha256=created["meta_accept_sha256"],
            reason="Reviewed canonical selection.",
            expected_previous_sha256=first["receipt_sha256"],
        )
    assert research_focus.project_focus(root)["receipt_sha256"] == first["receipt_sha256"]


def test_pointer_publish_crash_recovers_exact_receipt_without_duplicate_convictions(tmp_path, monkeypatch):
    root = _git_root(tmp_path)
    accept, _source = _staged(root, monkeypatch)
    created = thesis.create_meta_accept(root, accept)
    original_link = research_focus.os.link
    crashed = {"once": False}

    def crash_pointer(source, destination, **kwargs):
        if not crashed["once"] and Path(destination) == root / research_focus.POINTER:
            crashed["once"] = True
            raise OSError("simulated pointer publish crash")
        return original_link(source, destination, **kwargs)

    monkeypatch.setattr(research_focus.os, "link", crash_pointer)
    with pytest.raises(OSError, match="pointer publish crash"):
        thesis.select_thesis_focus(root, meta_accept_sha256=created["meta_accept_sha256"], reason="Reviewed canonical selection.")
    assert not (root / research_focus.POINTER).exists()
    assert len((root / research_focus.CONVICTION_LEDGER).read_text().splitlines()) == 3
    selected = thesis.select_thesis_focus(root, meta_accept_sha256=created["meta_accept_sha256"], reason="Reviewed canonical selection.")
    assert selected["status"] == "selected"
    assert len((root / research_focus.CONVICTION_LEDGER).read_text().splitlines()) == 3


def test_prepared_recovery_ignores_a_later_meta_reject(tmp_path, monkeypatch):
    root = _git_root(tmp_path)
    accept, _source = _staged(root, monkeypatch)
    created = thesis.create_meta_accept(root, accept)
    original_link = research_focus.os.link
    crashed = {"once": False}

    def crash_pointer(source, destination, **kwargs):
        if not crashed["once"] and Path(destination) == root / research_focus.POINTER:
            crashed["once"] = True
            raise OSError("simulated pointer crash")
        return original_link(source, destination, **kwargs)

    monkeypatch.setattr(research_focus.os, "link", crash_pointer)
    with pytest.raises(OSError, match="pointer crash"):
        thesis.select_thesis_focus(root, meta_accept_sha256=created["meta_accept_sha256"], reason="Reviewed canonical selection.")
    _append_review(root, accept, "reject")
    selected = thesis.select_thesis_focus(root, meta_accept_sha256=created["meta_accept_sha256"], reason="Reviewed canonical selection.")
    assert selected["status"] == "selected"
    assert len((root / research_focus.CONVICTION_LEDGER).read_text().splitlines()) == 3


def test_ledger_append_crash_recovers_without_duplicate_convictions(tmp_path, monkeypatch):
    root = _git_root(tmp_path)
    accept, _source = _staged(root, monkeypatch)
    created = thesis.create_meta_accept(root, accept)
    original_write = research_focus.os.write
    calls = {"count": 0}

    def write_then_crash(fd, payload):
        calls["count"] += 1
        written = original_write(fd, payload)
        if calls["count"] == 2:  # prepared receipt first; ledger append second
            raise OSError("simulated ledger append crash")
        return written

    monkeypatch.setattr(research_focus.os, "write", write_then_crash)
    with pytest.raises(OSError, match="ledger append crash"):
        thesis.select_thesis_focus(root, meta_accept_sha256=created["meta_accept_sha256"], reason="Reviewed canonical selection.")
    assert not (root / research_focus.POINTER).exists()
    assert len((root / research_focus.CONVICTION_LEDGER).read_text().splitlines()) == 3
    original_fsync = research_focus.os.fsync
    fsynced = []

    def record_fsync(fd):
        fsynced.append(os.readlink(f"/proc/self/fd/{fd}"))
        return original_fsync(fd)

    monkeypatch.setattr(research_focus.os, "fsync", record_fsync)
    selected = thesis.select_thesis_focus(root, meta_accept_sha256=created["meta_accept_sha256"], reason="Reviewed canonical selection.")
    assert selected["status"] == "selected"
    assert str(root / research_focus.CONVICTION_LEDGER) in fsynced
    assert len((root / research_focus.CONVICTION_LEDGER).read_text().splitlines()) == 3


def test_short_ledger_write_resumes_the_exact_prepared_payload(tmp_path, monkeypatch):
    root = _git_root(tmp_path)
    accept, _source = _staged(root, monkeypatch)
    created = thesis.create_meta_accept(root, accept)
    original_write = research_focus.os.write
    calls = {"count": 0}

    def short_then_crash(fd, payload):
        calls["count"] += 1
        if calls["count"] == 2:  # prepared receipt first; ledger append second
            original_write(fd, payload[:17])
            raise OSError("simulated crash after short ledger write")
        return original_write(fd, payload)

    monkeypatch.setattr(research_focus.os, "write", short_then_crash)
    with pytest.raises(OSError, match="short ledger write"):
        thesis.select_thesis_focus(root, meta_accept_sha256=created["meta_accept_sha256"], reason="Reviewed canonical selection.")
    assert (root / research_focus.CONVICTION_LEDGER).read_bytes().endswith(b"\n") is False
    selected = thesis.select_thesis_focus(root, meta_accept_sha256=created["meta_accept_sha256"], reason="Reviewed canonical selection.")
    assert selected["status"] == "selected"
    assert len((root / research_focus.CONVICTION_LEDGER).read_text().splitlines()) == 3


def test_short_prepared_receipt_write_leaves_no_final_name_and_retries(tmp_path, monkeypatch):
    root = _git_root(tmp_path)
    accept, _source = _staged(root, monkeypatch)
    created = thesis.create_meta_accept(root, accept)
    original_write = research_focus.os.write
    crashed = {"once": False}

    def short_then_crash(fd, payload):
        if not crashed["once"]:
            crashed["once"] = True
            original_write(fd, payload[:17])
            raise OSError("simulated short prepared receipt write")
        return original_write(fd, payload)

    monkeypatch.setattr(research_focus.os, "write", short_then_crash)
    with pytest.raises(OSError, match="short prepared receipt"):
        thesis.select_thesis_focus(root, meta_accept_sha256=created["meta_accept_sha256"], reason="Reviewed canonical selection.")
    monkeypatch.setattr(research_focus.os, "write", original_write)
    assert not list((root / research_focus.PREPARED).glob("*.json"))
    assert not (root / research_focus.CONVICTION_LEDGER).exists()
    assert thesis.select_thesis_focus(root, meta_accept_sha256=created["meta_accept_sha256"], reason="Reviewed canonical selection.")["status"] == "selected"


def test_short_final_receipt_write_leaves_no_collision_and_recovers(tmp_path, monkeypatch):
    root = _git_root(tmp_path)
    accept, _source = _staged(root, monkeypatch)
    created = thesis.create_meta_accept(root, accept)
    original_write = research_focus.os.write
    calls = {"count": 0}

    def crash_on_final_receipt(fd, payload):
        calls["count"] += 1
        # prepared receipt, conviction append, then immutable final receipt
        if calls["count"] == 3:
            original_write(fd, payload[:17])
            raise OSError("simulated short final receipt write")
        return original_write(fd, payload)

    monkeypatch.setattr(research_focus.os, "write", crash_on_final_receipt)
    with pytest.raises(OSError, match="short final receipt"):
        thesis.select_thesis_focus(root, meta_accept_sha256=created["meta_accept_sha256"], reason="Reviewed canonical selection.")
    monkeypatch.setattr(research_focus.os, "write", original_write)
    assert not list((root / research_focus.DIRECTORY).glob("[0-9a-f]*.json"))
    assert len((root / research_focus.CONVICTION_LEDGER).read_text().splitlines()) == 3
    assert thesis.select_thesis_focus(root, meta_accept_sha256=created["meta_accept_sha256"], reason="Reviewed canonical selection.")["status"] == "selected"


def test_interrupted_immutable_thesis_artifact_never_claims_its_digest(tmp_path, monkeypatch):
    directory = tmp_path / "artifacts"
    directory.mkdir()
    raw = b'{"schema_version":"test"}\n'
    target = directory / (hashlib.sha256(raw).hexdigest() + ".json")
    original_write = thesis.os.write

    def short_then_crash(fd, payload):
        original_write(fd, payload[:1])
        raise OSError("simulated short thesis artifact write")

    monkeypatch.setattr(thesis.os, "write", short_then_crash)
    with pytest.raises(OSError, match="short thesis artifact"):
        thesis._write_immutable(directory, target, raw)
    monkeypatch.setattr(thesis.os, "write", original_write)
    assert not target.exists()
    thesis._write_immutable(directory, target, raw)
    assert target.read_bytes() == raw


def test_new_nested_thesis_artifact_directory_fsyncs_its_ancestors(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    original_fsync = thesis._fsync_directory
    fsynced = []

    def record_directory(path):
        fsynced.append(Path(path))
        return original_fsync(path)

    monkeypatch.setattr(thesis, "_fsync_directory", record_directory)
    directory = thesis._safe_directory(root, "run_state/thesis_selection/screens")
    assert directory in fsynced
    assert root / "run_state" in fsynced
    assert root / "run_state" / "thesis_selection" in fsynced


def test_commit_refuses_a_fabricated_prepared_object_without_touching_ledger(tmp_path, monkeypatch):
    root = _git_root(tmp_path)
    accept, _source = _staged(root, monkeypatch)
    created = thesis.create_meta_accept(root, accept)
    captured = {}
    original_commit = research_focus.commit_prepared_thesis_focus

    def capture_prepared(_root, prepared):
        captured["prepared"] = copy.deepcopy(prepared)
        raise OSError("stop after durable preparation")

    monkeypatch.setattr(research_focus, "commit_prepared_thesis_focus", capture_prepared)
    with pytest.raises(OSError, match="durable preparation"):
        thesis.select_thesis_focus(root, meta_accept_sha256=created["meta_accept_sha256"], reason="Reviewed canonical selection.")
    monkeypatch.setattr(research_focus, "commit_prepared_thesis_focus", original_commit)
    forged = captured["prepared"]
    forged["ledger_prefix_sha256"] = "0" * 64  # structurally valid, but not the journal bytes
    with pytest.raises(research_focus.FocusError, match="differs from durable journal"):
        research_focus.commit_prepared_thesis_focus(root, forged)
    assert not (root / research_focus.CONVICTION_LEDGER).exists()
    assert thesis.select_thesis_focus(root, meta_accept_sha256=created["meta_accept_sha256"], reason="Reviewed canonical selection.")["status"] == "selected"


def test_new_prepared_journal_ancestry_is_fsynced_before_ledger_append(tmp_path, monkeypatch):
    root = _git_root(tmp_path)
    accept, _source = _staged(root, monkeypatch)
    created = thesis.create_meta_accept(root, accept)
    original_fsync = research_focus._fsync_directory
    original_write = research_focus.os.write
    durable_directories = []
    writes = {"count": 0}

    def record_directory(path):
        durable_directories.append(Path(path))
        return original_fsync(path)

    def assert_ledger_after_journal(fd, payload):
        writes["count"] += 1
        if writes["count"] == 2:  # staging prepared receipt is written first
            assert root / research_focus.DIRECTORY in durable_directories
            assert root / "run_state" in durable_directories
        return original_write(fd, payload)

    monkeypatch.setattr(research_focus, "_fsync_directory", record_directory)
    monkeypatch.setattr(research_focus.os, "write", assert_ledger_after_journal)
    assert thesis.select_thesis_focus(root, meta_accept_sha256=created["meta_accept_sha256"], reason="Reviewed canonical selection.")["status"] == "selected"


def test_closure_journal_ancestry_is_fsynced_before_pointer_removal(tmp_path, monkeypatch):
    root = _git_root(tmp_path)
    accept, _source = _staged(root, monkeypatch)
    created = thesis.create_meta_accept(root, accept)
    selected = thesis.select_thesis_focus(root, meta_accept_sha256=created["meta_accept_sha256"], reason="Reviewed canonical selection.")
    original_fsync = research_focus._fsync_directory
    original_unlink = research_focus.os.unlink
    durable_directories = []

    def record_directory(path):
        durable_directories.append(Path(path))
        return original_fsync(path)

    def assert_before_unlink(path, *args, **kwargs):
        if Path(path) == root / research_focus.POINTER:
            assert root / research_focus.DIRECTORY in durable_directories
            assert root / research_focus.CLOSURES in durable_directories
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(research_focus, "_fsync_directory", record_directory)
    monkeypatch.setattr(research_focus.os, "unlink", assert_before_unlink)
    closed = research_focus.close_focus(
        root, disposition="killed", reason="Bounded negative result.",
        reopening_conditions=["Fresh evidence."], evidence_refs=["receipt"],
        closed_by="oracle", authority="review", expected_receipt_sha256=selected["receipt_sha256"],
    )
    assert closed["status"] == "none"


def test_skeletal_content_addressed_closure_is_refused(tmp_path):
    root = _git_root(tmp_path)
    directory = root / research_focus.CLOSURES
    directory.mkdir(parents=True)
    raw = research_focus.canonical({"schema_version": research_focus.LEGACY_CLOSURE_SCHEMA}) + b"\n"
    (directory / f"{hashlib.sha256(raw).hexdigest()}.json").write_bytes(raw)
    with pytest.raises(research_focus.FocusError, match="unsupported focus closure"):
        research_focus._closures(root)


def test_retry_after_pointer_publish_returns_the_exact_active_receipt(tmp_path, monkeypatch):
    root = _git_root(tmp_path)
    accept, _source = _staged(root, monkeypatch)
    created = thesis.create_meta_accept(root, accept)
    original_link = research_focus.os.link
    crashed = {"once": False}

    def link_then_crash(source, destination, **kwargs):
        result = original_link(source, destination, **kwargs)
        if not crashed["once"] and Path(destination) == root / research_focus.POINTER:
            crashed["once"] = True
            raise OSError("simulated crash after pointer publish")
        return result

    monkeypatch.setattr(research_focus.os, "link", link_then_crash)
    with pytest.raises(OSError, match="after pointer publish"):
        thesis.select_thesis_focus(root, meta_accept_sha256=created["meta_accept_sha256"], reason="Reviewed canonical selection.")
    original_fsync = research_focus.os.fsync
    fsynced = []

    def record_fsync(fd):
        fsynced.append(os.readlink(f"/proc/self/fd/{fd}"))
        return original_fsync(fd)

    monkeypatch.setattr(research_focus.os, "fsync", record_fsync)
    selected = thesis.select_thesis_focus(root, meta_accept_sha256=created["meta_accept_sha256"], reason="Reviewed canonical selection.")
    assert selected["receipt_sha256"] == research_focus.project_focus(root)["receipt_sha256"]
    assert str(root / research_focus.CONVICTION_LEDGER) in fsynced
    assert str(root / research_focus.DIRECTORY) in fsynced
    assert str(root / "run_state") in fsynced


def test_pending_prepared_selection_blocks_a_competing_empty_generation(tmp_path, monkeypatch):
    """A second review cannot strand the first transaction's conviction rows."""
    root = _git_root(tmp_path)
    accept_a, _source = _staged(root, monkeypatch)
    created_a = thesis.create_meta_accept(root, accept_a)
    original_link = research_focus.os.link

    def crash_pointer(source, destination, **kwargs):
        if Path(destination) == root / research_focus.POINTER:
            raise OSError("simulate crash before pointer publication")
        return original_link(source, destination, **kwargs)

    monkeypatch.setattr(research_focus.os, "link", crash_pointer)
    with pytest.raises(OSError, match="before pointer"):
        thesis.select_thesis_focus(root, meta_accept_sha256=created_a["meta_accept_sha256"], reason="Reviewed canonical selection.")
    monkeypatch.setattr(research_focus.os, "link", original_link)
    accept_b, _source = _staged(root, monkeypatch, nonce="second-review")
    created_b = thesis.create_meta_accept(root, accept_b)
    with pytest.raises(research_focus.FocusError, match="pending prepared"):
        thesis.select_thesis_focus(root, meta_accept_sha256=created_b["meta_accept_sha256"], reason="Reviewed canonical selection.")
    assert not (root / research_focus.POINTER).exists()
    assert len((root / research_focus.CONVICTION_LEDGER).read_text().splitlines()) == 3
    assert len(list((root / research_focus.PREPARED).glob("*.json"))) == 1
    assert thesis.select_thesis_focus(root, meta_accept_sha256=created_a["meta_accept_sha256"], reason="Reviewed canonical selection.")["status"] == "selected"


def test_self_hashed_non_d087_prepared_append_refuses_before_pointer(tmp_path, monkeypatch):
    root = _git_root(tmp_path)
    accept, _source = _staged(root, monkeypatch)
    created = thesis.create_meta_accept(root, accept)
    original_link = research_focus.os.link

    def crash_pointer(source, destination, **kwargs):
        if Path(destination) == root / research_focus.POINTER:
            raise OSError("simulate crash before pointer publication")
        return original_link(source, destination, **kwargs)

    monkeypatch.setattr(research_focus.os, "link", crash_pointer)
    with pytest.raises(OSError, match="before pointer"):
        thesis.select_thesis_focus(root, meta_accept_sha256=created["meta_accept_sha256"], reason="Reviewed canonical selection.")
    prepared_path = next((root / research_focus.PREPARED).glob("*.json"))
    prepared = json.loads(prepared_path.read_bytes())
    poison = b"not-a-json-ledger-row\n"
    prepared["ledger_append_b64"] = base64.b64encode(poison).decode("ascii")
    prepared["ledger_append_sha256"] = hashlib.sha256(poison).hexdigest()
    prepared_path.write_bytes(research_focus.canonical(prepared) + b"\n")
    monkeypatch.setattr(research_focus.os, "link", original_link)
    with pytest.raises(research_focus.FocusError, match="prepared ledger append"):
        thesis.select_thesis_focus(root, meta_accept_sha256=created["meta_accept_sha256"], reason="Reviewed canonical selection.")
    assert not (root / research_focus.POINTER).exists()


def test_pointer_publication_never_clobbers_a_racing_pointer(tmp_path, monkeypatch):
    root = _git_root(tmp_path)
    accept, _source = _staged(root, monkeypatch)
    created = thesis.create_meta_accept(root, accept)
    original_link = research_focus.os.link
    foreign = b'{"receipt_sha256":"' + b"f" * 64 + b'","schema_version":"research-focus/v2"}\n'

    def publish_foreign_then_link(source, destination, **kwargs):
        if Path(destination) == root / research_focus.POINTER and not Path(destination).exists():
            Path(destination).write_bytes(foreign)
        return original_link(source, destination, **kwargs)

    monkeypatch.setattr(research_focus.os, "link", publish_foreign_then_link)
    with pytest.raises(research_focus.FocusError, match="refuse to overwrite"):
        thesis.select_thesis_focus(root, meta_accept_sha256=created["meta_accept_sha256"], reason="Reviewed canonical selection.")
    assert (root / research_focus.POINTER).read_bytes() == foreign


def test_thesis_receipt_rejects_valid_multibyte_content_above_projection_bound(tmp_path, monkeypatch):
    root = _git_root(tmp_path)
    accept, _source = _staged(root, monkeypatch)
    created = thesis.create_meta_accept(root, accept)
    selected = thesis.select_thesis_focus(root, meta_accept_sha256=created["meta_accept_sha256"], reason="Reviewed canonical selection.")
    receipt = {key: selected[key] for key in research_focus.THESIS_FIELDS}
    receipt["blockers"] = ["💣" * 600 for _ in range(12)]
    with pytest.raises(research_focus.FocusError, match="projection bound"):
        research_focus._validate_thesis(receipt)


def test_causal_closure_tip_ignores_equal_rollback_and_offset_timestamps():
    first = {"schema_version": research_focus.CLOSURE_SCHEMA, "closure_sha256": "1" * 64, "closed_at": "2030-01-01T00:00:00+00:00", "prior_closure_sha256": None}
    second = {"schema_version": research_focus.CLOSURE_SCHEMA, "closure_sha256": "2" * 64, "closed_at": "1999-01-01T00:00:00+00:00", "prior_closure_sha256": "1" * 64}
    third = {"schema_version": research_focus.CLOSURE_SCHEMA, "closure_sha256": "3" * 64, "closed_at": "2030-01-01T00:00:00-12:00", "prior_closure_sha256": "2" * 64}
    assert research_focus._closure_tip([first, third, second])["closure_sha256"] == "3" * 64


def test_receipt_expiry_uses_aware_receipt_order_not_wall_clock(tmp_path, monkeypatch):
    root = _git_root(tmp_path); accept, source_set = _staged(root, monkeypatch); source_id = source_set["source"]["receipt_msg_id"]
    plan_id = source_set["source"]["branch"].removeprefix("nara/")
    _rehash(root, lambda rows: [row.update({"ts": "2026-08-31T19:00:00-05:00"}) for row in rows if row["msg_id"] == source_id] + [row.update({"ts": "2026-08-31T18:00:00-05:00", "expires_at": "2026-09-01T01:00:00+01:00"}) for row in rows if row["msg_id"] == plan_id])
    receipt = next(row for row in mailbox.read(root / "run_state/oracle_nara_mailbox.jsonl") if row["msg_id"] == source_id)
    source_set["source"]["receipt_row_sha256"] = receipt["row_sha256"]
    proposed = thesis.create_candidate_set(root, source_set); screened = thesis.create_screen(root, proposed["candidate_set_sha256"], _screen(proposed["candidate_set_sha256"], source_set["proposed_at"]))
    accept["candidate_set_sha256"], accept["screen_sha256"] = proposed["candidate_set_sha256"], screened["screen_sha256"]
    _rehash(root, lambda rows: [row["body"]["thesis_selection"].update({"candidate_set_sha256": accept["candidate_set_sha256"], "screen_sha256": accept["screen_sha256"]}) for row in rows if row["msg_id"] in {accept["proposal_msg_id"], accept["review_msg_id"]}])
    hashes = {row["msg_id"]: row["row_sha256"] for row in mailbox.read(root / "run_state/oracle_nara_mailbox.jsonl")}
    accept["proposal_row_sha256"], accept["review_row_sha256"] = hashes[accept["proposal_msg_id"]], hashes[accept["review_msg_id"]]
    assert thesis.create_meta_accept(root, accept)["chosen_candidate_id"] == "c-alpha"


def test_later_meta_reject_blocks_accept_then_select_but_not_frozen_projection(tmp_path, monkeypatch):
    root = _git_root(tmp_path); accept, _source = _staged(root, monkeypatch); _append_review(root, accept, "reject")
    with pytest.raises(thesis.ThesisSelectionError, match="latest meta verdict"): thesis.create_meta_accept(root, accept)
    root = _git_root(tmp_path / "second"); accept, _source = _staged(root, monkeypatch); created = thesis.create_meta_accept(root, accept); _append_review(root, accept, "reject")
    with pytest.raises(thesis.ThesisSelectionError, match="latest meta verdict"): thesis.select_thesis_focus(root, meta_accept_sha256=created["meta_accept_sha256"], reason="Reviewed canonical selection.")
    root = _git_root(tmp_path / "third"); accept, _source = _staged(root, monkeypatch); created = thesis.create_meta_accept(root, accept)
    thesis.select_thesis_focus(root, meta_accept_sha256=created["meta_accept_sha256"], reason="Reviewed canonical selection."); _append_review(root, accept, "reject")
    assert research_focus.project_focus(root)["status"] == "selected"


def test_killed_focus_refuses_exact_replay_but_allows_fresh_review_and_graduation_is_terminal(tmp_path, monkeypatch):
    root = _git_root(tmp_path); accept, _source = _staged(root, monkeypatch); first = thesis.create_meta_accept(root, accept)
    selected = thesis.select_thesis_focus(root, meta_accept_sha256=first["meta_accept_sha256"], reason="Reviewed canonical selection.")
    research_focus.close_focus(root, disposition="killed", reason="Bounded negative result.", reopening_conditions=["A fresh Oracle proposal and independent meta review."], evidence_refs=["receipt"], closed_by="oracle", authority="review", expected_receipt_sha256=selected["receipt_sha256"])
    with pytest.raises(thesis.ThesisSelectionError, match="focus generation"):
        thesis.select_thesis_focus(root, meta_accept_sha256=first["meta_accept_sha256"], reason="Reviewed canonical selection.")
    fresh, _source = _staged(root, monkeypatch, nonce="fresh"); second = thesis.create_meta_accept(root, fresh)
    closure = research_focus.project_focus(root)["last_closure"]
    new_ref = _primary_source_ref(_source)
    _rehash(root, lambda rows: [row["body"].update({"reopening": {"closure_sha256": closure["closure_sha256"], "condition": "A fresh Oracle proposal and independent meta review.", "evidence_refs": [new_ref]}}) for row in rows if row["msg_id"] == fresh["review_msg_id"]])
    row = next(row for row in mailbox.read(root / "run_state/oracle_nara_mailbox.jsonl") if row["msg_id"] == fresh["review_msg_id"])
    fresh["review_row_sha256"] = row["row_sha256"]
    second = thesis.create_meta_accept(root, fresh)
    selected = thesis.select_thesis_focus(root, meta_accept_sha256=second["meta_accept_sha256"], reason="Reviewed canonical selection.")
    research_focus.close_focus(root, disposition="graduated", reason="The focus graduated.", reopening_conditions=[], evidence_refs=["receipt"], closed_by="oracle", authority="review", expected_receipt_sha256=selected["receipt_sha256"])
    newest, _source = _staged(root, monkeypatch); third = thesis.create_meta_accept(root, newest)
    with pytest.raises(thesis.ThesisSelectionError, match="graduated thesis"):
        thesis.select_thesis_focus(root, meta_accept_sha256=third["meta_accept_sha256"], reason="Reviewed canonical selection.")


def test_killed_focus_refuses_new_review_of_same_stale_candidate_and_screen(tmp_path, monkeypatch):
    root = _git_root(tmp_path); accept, _source = _staged(root, monkeypatch)
    first = thesis.create_meta_accept(root, accept)
    selected = thesis.select_thesis_focus(root, meta_accept_sha256=first["meta_accept_sha256"], reason="Reviewed canonical selection.")
    research_focus.close_focus(root, disposition="killed", reason="Bounded negative result.",
                                reopening_conditions=["Fresh evidence is required."], evidence_refs=["receipt"],
                                closed_by="oracle", authority="review", expected_receipt_sha256=selected["receipt_sha256"])
    closure = research_focus.project_focus(root)["last_closure"]
    binding = {key: accept[key] for key in ("candidate_set_sha256", "screen_sha256", "chosen_candidate_id", "reviewed_head")}
    binding["focus_generation"] = research_focus.selection_generation(root)
    proposal = mailbox.post("oracle", "note", {"thesis_selection": binding, "thesis_focus": _focus()}, to="all",
                            path=root / "run_state/oracle_nara_mailbox.jsonl")
    review = mailbox.post("claude", "review", {"verdict": "accept", "thesis_selection": binding, "thesis_focus": _focus(),
                                                   "reopening": {"closure_sha256": closure["closure_sha256"], "condition": "Fresh evidence is required.", "evidence_refs": ["notes/primary/c-alpha.txt@sha256:" + _card("c-alpha")["prior_work"]["sources"][0]["source_sha256"]]}},
                          to="all", in_reply_to=proposal["msg_id"], path=root / "run_state/oracle_nara_mailbox.jsonl")
    stale = {"schema_version": thesis.SCHEMA_ACCEPT, **binding, "accepted_at": review["ts"],
             "review_msg_id": review["msg_id"], "review_row_sha256": review["row_sha256"],
             "proposal_msg_id": proposal["msg_id"], "proposal_row_sha256": proposal["row_sha256"],
             "execution_authorized": False, "scientific_credit": "none_accept_only"}
    reopened = thesis.create_meta_accept(root, stale)
    with pytest.raises(thesis.ThesisSelectionError, match="genuinely new primary evidence"):
        thesis.select_thesis_focus(root, meta_accept_sha256=reopened["meta_accept_sha256"], reason="Reviewed canonical selection.")


def test_untrusted_evidence_reader_refuses_symlink_oversize_and_toctou(tmp_path, monkeypatch):
    evidence = tmp_path / "evidence.json"; evidence.write_bytes(b'{"x":1}\n')
    link = tmp_path / "link.json"; link.symlink_to(evidence)
    with pytest.raises(OSError):
        thesis._read_regular(link, thesis.MAX_ARTIFACT_BYTES)
    oversized = tmp_path / "oversized.json"; oversized.write_bytes(b"x" * (thesis.MAX_ARTIFACT_BYTES + 1))
    with pytest.raises(thesis.ThesisSelectionError, match="bounded regular"):
        thesis._read_regular(oversized, thesis.MAX_ARTIFACT_BYTES)
    original_read = thesis.os.read
    raced = {"done": False}

    def replace_after_read(fd, count):
        raw = original_read(fd, count)
        if not raced["done"]:
            raced["done"] = True
            evidence.write_bytes(b'{"y":1}\n')
        return raw

    monkeypatch.setattr(thesis.os, "read", replace_after_read)
    with pytest.raises(thesis.ThesisSelectionError, match="changed during read"):
        thesis._read_regular(evidence, thesis.MAX_ARTIFACT_BYTES)


def test_prior_focus_scan_has_a_total_bounded_budget(tmp_path):
    root = _git_root(tmp_path)
    directory = root / research_focus.DIRECTORY; directory.mkdir(parents=True)
    for number in range((thesis.MAX_SCAN_BYTES // thesis.MAX_ARTIFACT_BYTES) + 1):
        (directory / f"{number:064x}.json").write_bytes(b" " * thesis.MAX_ARTIFACT_BYTES)
    with pytest.raises(thesis.ThesisSelectionError, match="scan exceeds bound"):
        thesis._review_used(root, "unseen-review")


def test_select_uses_one_mailbox_snapshot_through_pointer_fsync(tmp_path, monkeypatch):
    root = _git_root(tmp_path); accept, _source = _staged(root, monkeypatch)
    created = thesis.create_meta_accept(root, accept)
    original_rows, calls = thesis._mailbox_rows, []

    def captured(path):
        calls.append(path)
        return original_rows(path)

    monkeypatch.setattr(thesis, "_mailbox_rows", captured)
    selected = thesis.select_thesis_focus(root, meta_accept_sha256=created["meta_accept_sha256"], reason="Reviewed canonical selection.")
    assert selected["status"] == "selected"
    assert len(calls) == 1


@pytest.mark.parametrize("timestamp", ["2026-09-01T00:00:00", "2999-01-01T00:00:00+00:00"])
def test_malformed_naive_or_future_receipt_time_refuses_selection(tmp_path, monkeypatch, timestamp):
    root = _git_root(tmp_path); accept, source_set = _staged(root, monkeypatch); source_id = source_set["source"]["receipt_msg_id"]
    _rehash(root, lambda rows: [row.update({"ts": timestamp}) for row in rows if row["msg_id"] == source_id])
    receipt = next(row for row in mailbox.read(root / "run_state/oracle_nara_mailbox.jsonl") if row["msg_id"] == source_id)
    source_set["source"]["receipt_row_sha256"] = receipt["row_sha256"]
    proposed = thesis.create_candidate_set(root, source_set); screened = thesis.create_screen(root, proposed["candidate_set_sha256"], _screen(proposed["candidate_set_sha256"]))
    accept["candidate_set_sha256"], accept["screen_sha256"] = proposed["candidate_set_sha256"], screened["screen_sha256"]
    with pytest.raises(thesis.ThesisSelectionError, match="mailbox ts"): thesis.create_meta_accept(root, accept)


def test_invalid_mailbox_recipient_refuses_provenance(tmp_path, monkeypatch):
    root = _git_root(tmp_path); accept, source_set = _staged(root, monkeypatch); source_id = source_set["source"]["receipt_msg_id"]
    _rehash(root, lambda rows: [row.update({"to": "untrusted-recipient"}) for row in rows if row["msg_id"] == source_id])
    receipt = next(row for row in mailbox.read(root / "run_state/oracle_nara_mailbox.jsonl") if row["msg_id"] == source_id)
    source_set["source"]["receipt_row_sha256"] = receipt["row_sha256"]
    proposed = thesis.create_candidate_set(root, source_set); screened = thesis.create_screen(root, proposed["candidate_set_sha256"], _screen(proposed["candidate_set_sha256"]))
    accept["candidate_set_sha256"], accept["screen_sha256"] = proposed["candidate_set_sha256"], screened["screen_sha256"]
    with pytest.raises(thesis.ThesisSelectionError, match="recipient"):
        thesis.create_meta_accept(root, accept)
