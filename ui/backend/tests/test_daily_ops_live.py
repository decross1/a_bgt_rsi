"""Live derivations for the Now panel, over a temp repo with a real hash-chained mailbox.

Mailbox rows are written through ``orchestrator.oracle_mailbox.post`` so they carry
the real row shape: plan items have ``in_reply_to: null``; receipts, reviews,
withdrawals and answers reply by ``in_reply_to``; ``fold()`` keys by the plan
item's ``msg_id``.
"""
import hashlib
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from backend import daily_ops_live as live
from backend.daily_ops import _agents, _validate_summary

live._orchestrator()  # puts the checkout's orchestrator on sys.path
from orchestrator import oracle_mailbox  # noqa: E402

NOW = datetime(2026, 9, 23, 18, 0, tzinfo=timezone.utc)  # 11:00 in the lab's day
PLAN_ITEM = {"objective": "Build it.", "task_class": "tooling", "allowed_write_paths": ["tools/x.py"],
             "acceptance": {"test_path": "tests/test_x.py", "test_content": "def test(): pass",
                            "test_argv": ["pytest"]}}


def _plan(repo, name, items, **extra):
    plans = repo / "run_state" / "daily_plans"
    plans.mkdir(parents=True, exist_ok=True)
    body = {"date": name[:10], "week_alignment": "G0 first.",
            "bottlenecks": [{"what": f"bottleneck {i}", "evidence": "e", "cost_of_leaving_it": "c"}
                            for i in range(7)],
            "items": items, **extra}
    path = plans / name
    path.write_text(json.dumps(body))
    return path


def _item(ident, lane, title=None, **extra):
    return {"id": ident, "owner": "x", "lane": lane, "goal": "G7.1", "repo": "a_bgt_rsi",
            "title": title or f"Item {ident}", "why_today": "Because.", "acceptance": "Tests pass.",
            "depends_on": [], **extra}


class Box:
    def __init__(self, repo):
        self.path = repo / "run_state" / "oracle_nara_mailbox.jsonl"

    def post(self, actor, kind, body, *, to="all", reply=None):
        return oracle_mailbox.post(actor, kind, body, to=to, in_reply_to=reply, path=self.path)


def _git(repo, *args, at=None):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    if at is not None:
        env.update({"GIT_AUTHOR_DATE": at, "GIT_COMMITTER_DATE": at})
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                   env=env)


def _head(repo, ref="HEAD"):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", ref], check=True,
                          capture_output=True, text=True).stdout.strip()


def _summary(repo, now=NOW):
    value = live.build(repo, now)
    value["agents"] = {k: {"label": f"{k} client", "status": "idle", "detail": "d",
                           "observed_at": "2026-09-23T18:00:00Z", "source": "s"}
                       for k in ("oracle", "pi_client", "nara")}
    _validate_summary(value)
    return value


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "_project_focus", lambda root: {"status": "none"})
    return tmp_path


def test_newest_plan_is_highest_date_then_revision_and_ignores_other_files(repo):
    _plan(repo, "2026-09-22-r3.json", [_item("d1", "oracle_dev")])
    _plan(repo, "2026-09-23.json", [_item("d1", "oracle_dev")])
    _plan(repo, "2026-09-23-r2.json", [_item("d1", "oracle_dev"), _item("d2", "nara_dev")])
    (repo / "run_state" / "daily_plans" / "2026-09-23-close-body.json").write_text("{}")
    (repo / "run_state" / "daily_plans" / "2026-09-24-close-body.json").write_text("{}")

    value = _summary(repo)

    plan = value["daily_plan"]
    assert (plan["id"], plan["date"], plan["revision"]) == ("2026-09-23-r2", "2026-09-23", "r2")
    assert value["current_plan_revision"] == "2026-09-23-r2"
    assert plan["is_current"] is True and plan["review"] is None
    assert plan["bottlenecks"] == [f"bottleneck {i}" for i in range(5)]
    assert [i["id"] for i in value["work_items"]] == ["d1", "d2"]
    assert value["sources"]["plan"] == plan["written_at"]
    assert live.build(repo, NOW + timedelta(days=2))["daily_plan"]["is_current"] is False


def test_no_plan_and_no_mailbox_is_an_honest_empty_state(repo):
    value = _summary(repo)
    assert value["daily_plan"] is None and value["current_plan_revision"] is None
    assert value["work_items"] == [] and value["waiting_on_you"] == []
    assert value["sources"]["mailbox"] is None
    assert any("git" in warning for warning in value["warnings"])


def test_unreadable_newest_plan_is_a_warning_not_old_content(repo):
    _plan(repo, "2026-09-22.json", [_item("d1", "oracle_dev")])
    (repo / "run_state" / "daily_plans" / "2026-09-23.json").write_text('{"date": "2026-09-23"}')
    value = _summary(repo)
    assert value["daily_plan"] is None
    assert any("2026-09-23.json is unreadable" in w for w in value["warnings"])


def test_plan_review_is_the_review_replying_to_the_plan_ready_note_for_that_file(repo):
    path = _plan(repo, "2026-09-23-r2.json", [_item("d1", "oracle_dev")])
    box = Box(repo)
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    old = box.post("oracle", "note", {"title": "PLAN READY: 2026-09-23", "text": "x",
                                      "ref": {"path": "run_state/daily_plans/2026-09-23.json", "sha256": "0"}})
    box.post("claude", "review", {"verdict": "reject", "summary": "old"}, reply=old["msg_id"])
    note = box.post("oracle", "note", {"title": "PLAN READY: 2026-09-23 (r2)", "text": "x",
                                       "ref": {"path": "run_state/daily_plans/2026-09-23-r2.json",
                                               "sha256": sha}})
    assert _summary(repo)["daily_plan"]["review"]["verdict"] is None
    forged = {**note, "seq": note["seq"] + 1, "msg_id": "oracle-forged-review",
              "actor": "oracle", "kind": "review", "in_reply_to": note["msg_id"],
              "body": {"verdict": "accept", "summary": "Self-review."}}
    assert live.plan_review(oracle_mailbox.read(box.path) + [forged], path.name, sha)["verdict"] is None
    review = box.post("claude", "review", {"verdict": "amend", "summary": "Accept d1.",
                                           "accepted_items": ["d1"]}, reply=note["msg_id"])
    duplicate = box.post("oracle", "note", {"title": "PLAN READY: 2026-09-23 duplicate",
                                              "ref": {"path": path.relative_to(repo).as_posix(),
                                                      "sha256": sha}})
    box.post("codex", "review", {"verdict": "reject", "summary": "Wrong duplicate."},
             reply=duplicate["msg_id"])

    got = _summary(repo)["daily_plan"]["review"]
    assert got["note_msg_id"] == note["msg_id"] and got["review_msg_id"] == review["msg_id"]
    assert (got["verdict"], got["sha_matches"], got["accepted_items"]) == ("amend", True, ["d1"])


def test_same_day_revision_uses_exact_plan_ready_window_not_reused_item_ids(repo):
    """R10 must not inherit R9's dN evidence merely because the ids repeat."""
    old = _plan(repo, "2026-09-23-r9.json", [
        _item("d1", "nara_dev", "Prior-art search"),
        _item("d3", "oracle_dev"),
        _item("d4", "oracle_dev"),
        _item("d5", "owner_decision"),
    ])
    box = Box(repo)
    old_ready = box.post("oracle", "note", {
        "title": "PLAN READY: 2026-09-23-r9",
        "ref": {"path": "run_state/daily_plans/2026-09-23-r9.json",
                "sha256": hashlib.sha256(old.read_bytes()).hexdigest()},
    })
    old_item = box.post("oracle", "plan_item", {**PLAN_ITEM, "title": "Prior-art search (d1)"}, to="nara")
    box.post("nara", "receipt", {"state": "validated", "head_sha": "a" * 40},
             to="oracle", reply=old_item["msg_id"])
    old_d3 = box.post("oracle", "note", {
        "title": "READY FOR REVIEW: oracle/2026-09-23-d3",
        "ref": {"branch": "oracle/2026-09-23-d3", "item": "d3"},
    })
    box.post("claude", "review", {"verdict": "reject", "summary": "Old revision."}, reply=old_d3["msg_id"])
    old_d4 = box.post("oracle", "note", {
        "title": "READY FOR REVIEW: oracle/2026-09-23-d4",
        "ref": {"branch": "oracle/2026-09-23-d4", "item": "d4"},
    })
    box.post("claude", "review", {"verdict": "amend", "summary": "Old revision."}, reply=old_d4["msg_id"])
    box.post("claude", "question", {"question": "Old d5?", "ref": {"item": "d5"}}, to="owner")
    # The old d3 branch is also already on main.  A new revision must not turn
    # that durable historical fact into a current-R9 completion.
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "oracle/2026-09-23-d3")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "old d3")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--ff-only", "oracle/2026-09-23-d3")

    current = _plan(repo, "2026-09-23-r10.json", [
        _item("d1", "nara_dev", "Prior-art search"),
        _item("d3", "oracle_dev"),
        _item("d4", "oracle_dev"),
        _item("d5", "owner_decision"),
    ])
    # It names R10's branch but predates the exact R10 publication, so it is not
    # admissible evidence for the revision.
    box.post("oracle", "note", {
        "title": "READY FOR REVIEW: oracle/2026-09-23-d3-r10",
        "ref": {"branch": "oracle/2026-09-23-d3-r10", "item": "d3"},
    })
    current_ready = box.post("oracle", "note", {
        "title": "PLAN READY: 2026-09-23-r10",
        "ref": {"path": "run_state/daily_plans/2026-09-23-r10.json",
                "sha256": hashlib.sha256(current.read_bytes()).hexdigest()},
    })
    box.post("claude", "review", {"verdict": "amend", "summary": "R10 needs revision.",
                                           "accepted_items": ["d2", "d4"]},
             reply=current_ready["msg_id"])

    value = _summary(repo)
    assert value["daily_plan"]["review"]["verdict"] == "amend"
    assert value["daily_plan"]["review"]["accepted_items"] == ["d2", "d4"]
    assert {row["id"]: row["status"] for row in value["work_items"]} == {
        "d1": "not_started", "d3": "not_started", "d4": "not_started", "d5": "not_started",
    }
    # The completed R9 plan remains an accomplishment, but not a current R10 badge.
    assert any(row["kind"] == "validated" and row["id"] == "2026-09-23:2026-09-23-r9:d1"
               for row in value["accomplishments"])
    assert old_ready["msg_id"] != current_ready["msg_id"]


def test_plan_window_ignores_foreign_and_bad_hash_anchors_and_first_duplicate_wins(repo):
    items = [_item("d1", "nara_dev", "Same item"), _item("d3", "oracle_dev"),
             _item("d4", "oracle_dev")]
    old = _plan(repo, "2026-09-23-r10.json", items)
    current = _plan(repo, "2026-09-23-r11.json", items)
    old_sha = hashlib.sha256(old.read_bytes()).hexdigest()
    current_sha = hashlib.sha256(current.read_bytes()).hexdigest()
    box = Box(repo)
    first = box.post("oracle", "note", {
        "title": "PLAN READY: 2026-09-23-r10",
        "ref": {"path": old.relative_to(repo).as_posix(), "sha256": old_sha},
    })
    # Neither a different actor nor Oracle naming the wrong content may start
    # R11 or terminate R10's evidence interval.
    box.post("claude", "note", {
        "title": "PLAN READY: 2026-09-23-r11",
        "ref": {"path": current.relative_to(repo).as_posix(), "sha256": current_sha},
    })
    box.post("oracle", "note", {
        "title": "PLAN READY: 2026-09-23-r11",
        "ref": {"path": current.relative_to(repo).as_posix(), "sha256": "f" * 64},
    })
    box.post("oracle", "note", {
        "title": "PLAN READY: 2026-09-22-r11",
        "ref": {"path": current.relative_to(repo).as_posix(), "sha256": current_sha},
    })
    posted = box.post("oracle", "plan_item", {**PLAN_ITEM, "title": "Same item (d1)"}, to="nara")
    box.post("nara", "receipt", {"state": "validated", "head_sha": "a" * 40},
             to="oracle", reply=posted["msg_id"])
    old_d3 = box.post("oracle", "note", {
        "title": "READY FOR REVIEW: oracle/2026-09-23-d3",
        "ref": {"branch": "oracle/2026-09-23-d3", "item": "d3"},
    })
    box.post("claude", "review", {"verdict": "reject", "summary": "R10 only."},
             reply=old_d3["msg_id"])
    old_d4 = box.post("oracle", "note", {
        "title": "READY FOR REVIEW: oracle/2026-09-23-d4",
        "ref": {"branch": "oracle/2026-09-23-d4", "item": "d4"},
    })
    box.post("codex", "review", {"verdict": "amend", "summary": "R10 only."},
             reply=old_d4["msg_id"])
    duplicate = box.post("oracle", "note", {
        "title": "PLAN READY: 2026-09-23-r10 duplicate",
        "ref": {"path": old.relative_to(repo).as_posix(), "sha256": old_sha},
    })

    value = _summary(repo)
    assert value["daily_plan"]["id"] == "2026-09-23-r11"
    assert value["daily_plan"]["review"] is None
    assert {row["id"]: row["status"] for row in value["work_items"]} == {
        "d1": "not_started", "d3": "not_started", "d4": "not_started"}
    assert [(row["id"], row["kind"]) for row in value["accomplishments"]] == [
        ("2026-09-23:2026-09-23-r10:d1", "validated")]
    assert first["msg_id"] != duplicate["msg_id"]


def test_ambiguous_legacy_receipt_cannot_duplicate_accomplishments_across_revisions(repo):
    _plan(repo, "2026-09-23-r8.json", [_item("d1", "nara_dev", "Same item")])
    _plan(repo, "2026-09-23-r9.json", [_item("d1", "nara_dev", "Same item")])
    box = Box(repo)
    box.post("oracle", "note", {"title": "PLAN READY: 2026-09-23"})
    posted = box.post("oracle", "plan_item", {**PLAN_ITEM, "title": "Same item (d1)"}, to="nara")
    box.post("nara", "receipt", {"state": "validated", "head_sha": "a" * 40},
             to="oracle", reply=posted["msg_id"])

    value = _summary(repo)
    assert value["work_items"][0]["status"] == "not_started"
    assert value["accomplishments"] == []


@pytest.mark.parametrize("mismatch", ["hash", "date"])
def test_structured_plan_ready_mismatch_disables_legacy_fallback(repo, mismatch):
    path = _plan(repo, "2026-09-23-r9.json", [_item("d1", "nara_dev", "Same item")])
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    box = Box(repo)
    box.post("oracle", "note", {
        "title": f"PLAN READY: {'2026-09-22' if mismatch == 'date' else '2026-09-23'}-r9",
        "ref": {"path": path.relative_to(repo).as_posix(),
                "sha256": "f" * 64 if mismatch == "hash" else sha},
    })
    box.post("oracle", "note", {"title": "PLAN READY: 2026-09-23"})
    posted = box.post("oracle", "plan_item", {**PLAN_ITEM, "title": "Same item (d1)"}, to="nara")
    box.post("nara", "receipt", {"state": "validated", "head_sha": "a" * 40},
             to="oracle", reply=posted["msg_id"])

    value = _summary(repo)
    assert value["work_items"][0]["status"] == "not_started"
    assert value["accomplishments"] == []


def test_latest_ready_ignores_late_review_of_older_ready_and_foreign_ready(repo):
    path = _plan(repo, "2026-09-23-r9.json", [_item("d1", "oracle_dev")])
    box = Box(repo)
    box.post("oracle", "note", {
        "title": "PLAN READY: 2026-09-23-r9",
        "ref": {"path": path.relative_to(repo).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
    })
    old = box.post("oracle", "note", {
        "title": "READY FOR REVIEW: oracle/2026-09-23-d1",
        "ref": {"branch": "oracle/2026-09-23-d1", "item": "d1"},
    })
    latest = box.post("oracle", "note", {
        "title": "READY FOR REVIEW: oracle/2026-09-23-d1-r2",
        "ref": {"branch": "oracle/2026-09-23-d1-r2", "item": "d1"},
    })
    box.post("claude", "note", {
        "title": "READY FOR REVIEW: oracle/2026-09-23-d1-r3",
        "ref": {"branch": "oracle/2026-09-23-d1-r3", "item": "d1", "head_sha": "a" * 40},
    })
    box.post("codex", "review", {"verdict": "accept", "summary": "Old head only."},
             reply=old["msg_id"])
    assert _summary(repo)["work_items"][0]["status"] == "awaiting_review"
    review = box.post("claude", "review", {"verdict": "amend", "summary": "Newest head."},
                      reply=latest["msg_id"])
    item = _summary(repo)["work_items"][0]
    assert (item["status"], item["evidence_msg_id"]) == ("amend_requested", review["msg_id"])


def test_git_merge_without_trusted_receipt_cannot_complete_new_ready_head(repo):
    path = _plan(repo, "2026-09-23-r9.json", [_item("d3", "oracle_dev")])
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "oracle/2026-09-23-d3")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "old d3")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "main diverged")
    _git(repo, "merge", "-q", "--no-ff", "oracle/2026-09-23-d3", "-m",
         "Merge oracle/2026-09-23-d3: old revision")
    box = Box(repo)
    box.post("oracle", "note", {
        "title": "PLAN READY: 2026-09-23-r9",
        "ref": {"path": path.relative_to(repo).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
    })
    _git(repo, "checkout", "-q", "-b", "oracle/2026-09-23-d3-r9")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "new d3")
    head = _head(repo)
    _git(repo, "checkout", "-q", "main")
    main_before = _head(repo, "main")
    ready = box.post("oracle", "note", {
        "title": "READY FOR REVIEW: oracle/2026-09-23-d3-r9",
        "ref": {"branch": "oracle/2026-09-23-d3-r9", "item": "d3", "head_sha": head,
                "main_before": main_before},
    })

    assert _summary(repo)["work_items"][0]["status"] == "awaiting_review"
    landed_at = (datetime.fromisoformat(ready["ts"]) + timedelta(seconds=2)).isoformat()
    _git(repo, "merge", "-q", "--no-ff", "oracle/2026-09-23-d3-r9", "-m", "land r9 d3",
         at=landed_at)
    item = _summary(repo)["work_items"][0]
    assert (item["status"], item["evidence_msg_id"]) == ("awaiting_review", ready["msg_id"])
    assert item["evidence_sha"] is None


def test_future_dated_merge_before_plan_anchor_is_not_current_merge(repo):
    path = _plan(repo, "2026-09-23-r10.json", [_item("d3", "oracle_dev")])
    before = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    forged_future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "base", at=before)
    _git(repo, "checkout", "-q", "-b", "oracle/2026-09-23-d3-r10")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "old r10 d3", at=before)
    head = _head(repo)
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "oracle/2026-09-23-d3-r10", "-m", "land too early",
         at=forged_future)
    main_before = _head(repo, "main")
    box = Box(repo)
    box.post("oracle", "note", {
        "title": "PLAN READY: 2026-09-23-r10",
        "ref": {"path": path.relative_to(repo).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
    })
    box.post("oracle", "note", {
        "title": "READY FOR REVIEW: oracle/2026-09-23-d3-r10",
        "ref": {"branch": "oracle/2026-09-23-d3-r10", "item": "d3", "head_sha": head,
                "main_before": main_before},
    })

    assert _summary(repo)["work_items"][0]["status"] == "awaiting_review"


def test_model_authored_stale_main_before_cannot_prove_post_ready_merge(repo):
    path = _plan(repo, "2026-09-23-r10.json", [_item("d3", "oracle_dev")])
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "base")
    stale_main = _head(repo, "main")
    _git(repo, "checkout", "-q", "-b", "oracle/2026-09-23-d3-r10")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "work merged before READY")
    head = _head(repo)
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "oracle/2026-09-23-d3-r10", "-m", "land before READY")
    box = Box(repo)
    box.post("oracle", "note", {
        "title": "PLAN READY: 2026-09-23-r10",
        "ref": {"path": path.relative_to(repo).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
    })
    box.post("oracle", "note", {
        "title": "READY FOR REVIEW: oracle/2026-09-23-d3-r10",
        "ref": {"branch": "oracle/2026-09-23-d3-r10", "item": "d3", "head_sha": head,
                "main_before": stale_main},
    })

    assert _summary(repo)["work_items"][0]["status"] == "awaiting_review"


def test_ready_claim_with_missing_named_branch_cannot_merge_an_unrelated_head(repo):
    path = _plan(repo, "2026-09-23-r10.json", [_item("d3", "oracle_dev")])
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "base")
    main_before = _head(repo, "main")
    _git(repo, "checkout", "-q", "-b", "unrelated")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "unrelated claimed head")
    claimed = _head(repo)
    _git(repo, "checkout", "-q", "main")
    box = Box(repo)
    box.post("oracle", "note", {
        "title": "PLAN READY: 2026-09-23-r10",
        "ref": {"path": path.relative_to(repo).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
    })
    box.post("oracle", "note", {
        "title": "READY FOR REVIEW: oracle/2026-09-23-d3-r10",
        "ref": {"branch": "oracle/2026-09-23-d3-r10", "item": "d3", "head_sha": claimed,
                "main_before": main_before},
    })
    _git(repo, "merge", "-q", "--no-ff", "unrelated", "-m", "land unrelated")

    assert _summary(repo)["work_items"][0]["status"] == "awaiting_review"


def test_ready_claimed_head_must_equal_the_named_branch_head(repo):
    path = _plan(repo, "2026-09-23-r10.json", [_item("d3", "oracle_dev")])
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "base")
    main_before = _head(repo, "main")
    box = Box(repo)
    box.post("oracle", "note", {
        "title": "PLAN READY: 2026-09-23-r10",
        "ref": {"path": path.relative_to(repo).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
    })
    _git(repo, "checkout", "-q", "-b", "oracle/2026-09-23-d3-r10")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "actual branch head")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "checkout", "-q", "-b", "unrelated")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "unrelated claimed head")
    claimed = _head(repo)
    _git(repo, "checkout", "-q", "main")
    ready = box.post("oracle", "note", {
        "title": "READY FOR REVIEW: oracle/2026-09-23-d3-r10",
        "ref": {"branch": "oracle/2026-09-23-d3-r10", "item": "d3", "head_sha": claimed,
                "main_before": main_before},
    })
    landed_at = (datetime.fromisoformat(ready["ts"]) + timedelta(seconds=2)).isoformat()
    _git(repo, "merge", "-q", "--no-ff", "unrelated", "-m", "land unrelated", at=landed_at)

    assert _summary(repo)["work_items"][0]["status"] == "awaiting_review"


def test_nara_dev_item_matches_by_id_inside_the_plan_window_and_folds_state(repo):
    _plan(repo, "2026-09-23.json", [_item("d2", "nara_dev", "Re-post the packet"),
                                    _item("d4", "nara_dev", "Closeout document"),
                                    _item("d5", "nara_dev", "Exact title")])
    box = Box(repo)
    box.post("oracle", "note", {"title": "PLAN READY: 2026-09-22", "text": "x"})
    # Yesterday's window: an item naming d2 must not count for today's d2.
    box.post("oracle", "plan_item", {**PLAN_ITEM, "title": "Packet (d2, yesterday)"}, to="nara")
    box.post("oracle", "note", {"title": "PLAN READY: 2026-09-23", "text": "x"})
    first = box.post("oracle", "plan_item", {**PLAN_ITEM, "title": "Packet (d2, 1st posting)"}, to="nara")
    box.post("oracle", "withdraw", {"title": "WITHDRAWN"}, to="nara", reply=first["msg_id"])
    ambiguous = box.post("oracle", "plan_item", {**PLAN_ITEM, "title": "d4 and d2 together"}, to="nara")
    second = box.post("oracle", "plan_item", {**PLAN_ITEM, "title": "Packet (d2, 2nd posting)"}, to="nara")
    box.post("oracle", "plan_item", {**PLAN_ITEM, "title": "Exact title"}, to="nara")
    items = {i["id"]: i for i in _summary(repo)["work_items"]}
    assert items["d2"]["status"] == "awaiting_review" and second["msg_id"] in items["d2"]["detail"]
    assert items["d4"]["status"] == "not_started"  # the ambiguous title names two ids
    assert items["d5"]["status"] == "awaiting_review"  # exact title match
    assert ambiguous["msg_id"] not in json.dumps(items)

    held = box.post("nara", "receipt", {"state": "held", "reasons": ["needs review"]},
                    to="oracle", reply=second["msg_id"])
    items = {i["id"]: i for i in _summary(repo)["work_items"]}
    assert (items["d2"]["status"], items["d2"]["evidence_msg_id"]) == ("held", held["msg_id"])
    assert "needs review" in items["d2"]["detail"]
    box.post("nara", "receipt", {"state": "claimed"}, to="oracle", reply=second["msg_id"])
    assert _summary(repo)["work_items"][0]["status"] == "building"
    box.post("nara", "receipt", {"state": "validated", "head_sha": "abcdef1234567890"},
             to="oracle", reply=second["msg_id"])
    value = _summary(repo)
    assert (value["work_items"][0]["status"], value["work_items"][0]["evidence_sha"]) == (
        "validated", "abcdef123456")
    assert [a["kind"] for a in value["accomplishments"]] == ["validated"]


def test_oracle_dev_item_follows_exact_ready_review_and_never_infers_merge(repo):
    path = _plan(repo, "2026-09-23.json", [_item("d1", "oracle_dev"), _item("d3", "oracle_dev"),
                                             _item("d10", "oracle_dev")])
    box = Box(repo)
    box.post("oracle", "note", {"title": "PLAN READY: 2026-09-23",
                                  "ref": {"path": path.relative_to(repo).as_posix(),
                                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}})
    items = {i["id"]: i for i in _summary(repo)["work_items"]}
    assert items["d1"]["status"] == "not_started"
    ready = box.post("oracle", "note", {"title": "READY FOR REVIEW: oracle/2026-09-23-d1", "text": "x",
                                        "ref": {"branch": "oracle/2026-09-23-d1", "item": "d1"}})
    items = {i["id"]: i for i in _summary(repo)["work_items"]}
    assert items["d1"]["status"] == "awaiting_review" and items["d10"]["status"] == "not_started"
    box.post("claude", "review", {"verdict": "amend", "summary": "Fix it."}, reply=ready["msg_id"])
    assert _summary(repo)["work_items"][0]["status"] == "amend_requested"
    again = box.post("oracle", "note", {"title": "READY FOR REVIEW: oracle/2026-09-23-d1-r2 @abc"})
    assert _summary(repo)["work_items"][0]["status"] == "awaiting_review"
    box.post("claude", "review", {"verdict": "accept", "summary": "Good."}, reply=again["msg_id"])
    assert _summary(repo)["work_items"][0]["status"] == "accepted"

    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "oracle/2026-09-23-d3")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "d3 work")
    d3_head = _head(repo)
    _git(repo, "checkout", "-q", "main")
    d3_main_before = _head(repo, "main")
    now = datetime.now(timezone.utc)
    items = {i["id"]: i for i in live.build(repo, now)["work_items"]}
    assert items["d3"]["status"] == "not_started"  # a branch alone is not revision evidence
    d3_ready = box.post("oracle", "note", {"title": "READY FOR REVIEW: oracle/2026-09-23-d3",
                                             "ref": {"branch": "oracle/2026-09-23-d3", "item": "d3",
                                                     "head_sha": d3_head,
                                                     "main_before": d3_main_before}})
    d3_review = box.post("claude", "review", {"verdict": "accept", "summary": "Exact d3 head."},
                         reply=d3_ready["msg_id"])
    d3_landed_at = (datetime.fromisoformat(d3_ready["ts"]) + timedelta(seconds=2)).isoformat()
    _git(repo, "merge", "-q", "--no-ff", "oracle/2026-09-23-d3", "-m", "land d3",
         at=d3_landed_at)
    _git(repo, "checkout", "-q", "-b", "oracle/2026-09-23-d1-r3")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "d1 amended")
    d1_head = _head(repo)
    d1_main_before = _head(repo, "main")
    d1_ready = box.post("oracle", "note", {"title": "READY FOR REVIEW: oracle/2026-09-23-d1-r3",
                                             "ref": {"branch": "oracle/2026-09-23-d1-r3", "item": "d1",
                                                     "head_sha": d1_head,
                                                     "main_before": d1_main_before}})
    d1_review = box.post("claude", "review", {"verdict": "accept", "summary": "Exact d1 head."},
                         reply=d1_ready["msg_id"])
    _git(repo, "checkout", "-q", "main")
    d1_landed_at = (datetime.fromisoformat(d1_ready["ts"]) + timedelta(seconds=4)).isoformat()
    _git(repo, "merge", "-q", "--no-ff", "oracle/2026-09-23-d1-r3", "-m",
         "Merge oracle/2026-09-23-d1-r3 at 1234567: gate (G7.1)", at=d1_landed_at)
    value = live.build(repo, now)
    items = {i["id"]: i for i in value["work_items"]}
    assert (items["d3"]["status"], items["d3"]["evidence_msg_id"]) == (
        "accepted", d3_review["msg_id"])
    assert (items["d1"]["status"], items["d1"]["evidence_msg_id"]) == (
        "accepted", d1_review["msg_id"])
    assert items["d10"]["status"] == "not_started"
    merges = [row for row in value["improvements"] if row["goals"] == ["G7.1"]]
    assert merges and merges[0]["subject"].startswith("Merge oracle/2026-09-23-d1")
    assert value["accomplishments"] == []


def test_owner_cards_require_a_real_question_and_direct_human_answer_or_explicit_resolution(repo):
    _plan(repo, "2026-09-23.json", [_item("d5", "owner_decision"), _item("d6", "owner_decision")])
    box = Box(repo)
    box.post("oracle", "note", {"title": "PLAN READY: 2026-09-23", "text": "x"})
    asked = box.post("claude", "question", {
        "question": "Use the reviewed worktree or main?", "why": "The runner needs one stable base.",
        "options": ["A — reviewed worktree", "B — current main"], "recommendation": "A",
        "if_deferred": "The runner remains unpinned for the next test window.",
        "ref": {"item": "d5"},
    }, to="owner")
    other = box.post("oracle", "question", {"title": "An unrelated ruling", "text": "?"}, to="owner")
    box.post("oracle", "question", {"title": "Not for the owner", "text": "?"}, to="claude")

    value = _summary(repo)
    items = {i["id"]: i for i in value["work_items"]}
    assert items["d5"]["status"] == "waiting_on_you"
    assert items["d6"]["status"] == "not_started"  # a plan field is not an actual question
    waiting = {w["id"]: w for w in value["waiting_on_you"]}
    assert set(waiting) == {"2026-09-23:d5", other["msg_id"]}
    assert waiting["2026-09-23:d5"]["msg_id"] == asked["msg_id"]
    assert f"--to claude --in-reply-to {asked['msg_id']}" in waiting["2026-09-23:d5"]["cli"]
    assert waiting["2026-09-23:d5"]["question"] == "Use the reviewed worktree or main?"
    assert waiting["2026-09-23:d5"]["context"] == "The runner needs one stable base."
    assert waiting["2026-09-23:d5"]["choices"] == ["A — reviewed worktree", "B — current main"]
    assert waiting["2026-09-23:d5"]["recommendation"] == "A"
    assert waiting["2026-09-23:d5"]["consequence"] == "The runner remains unpinned for the next test window."
    assert f"--kind answer --to oracle --in-reply-to {other['msg_id']}" in waiting[other["msg_id"]]["cli"]
    assert waiting[other["msg_id"]]["cli"].startswith(
        ".venv-chroma/bin/python -m orchestrator.oracle_mailbox post --as human:derrick")

    # A relay is context only; it must not mark the owner's question answered.
    box.post("claude", "answer", {"text": "relayed"}, to="oracle", reply=other["msg_id"])
    value = _summary(repo)
    assert value["work_items"][0]["status"] == "waiting_on_you"
    assert {w["id"] for w in value["waiting_on_you"]} == {"2026-09-23:d5", other["msg_id"]}

    box.post("human:derrick", "answer", {"text": "Use the reviewed worktree."}, to="claude", reply=asked["msg_id"])
    box.post("oracle", "question_resolution", {
        "disposition": "superseded", "summary": "The standalone ruling is superseded by the reviewed plan.",
        "reason": "It duplicates the direct owner decision.", "evidence_msg_ids": [asked["msg_id"]],
    }, to="owner", reply=other["msg_id"])
    value = _summary(repo)
    assert value["work_items"][0]["status"] == "answered"
    assert value["waiting_on_you"] == []
    assert value["question_updates"] == [{
        "id": value["question_updates"][0]["id"], "question_id": other["msg_id"],
        "title": "An unrelated ruling", "question": "An unrelated ruling", "disposition": "superseded",
        "summary": "The standalone ruling is superseded by the reviewed plan.",
        "reason": "It duplicates the direct owner decision.", "blocking_artifact": None,
        "resolved_by": "oracle", "resolved_at": value["question_updates"][0]["resolved_at"],
        "evidence_msg_ids": [asked["msg_id"]],
    }]


def test_projection_rejects_resolution_evidence_from_a_later_or_self_row_or_reviewer():
    question = {"seq": 1, "msg_id": "oracle-q", "actor": "oracle", "to": "owner", "kind": "question",
                "body": {"question": "Run it?"}, "ts": "2026-09-23T18:00:00+00:00"}
    resolution = {"seq": 2, "msg_id": "oracle-r", "actor": "oracle", "to": "owner",
                  "kind": "question_resolution", "in_reply_to": "oracle-q",
                  "body": {"disposition": "withdrawn", "summary": "No action.", "reason": "review",
                           "evidence_msg_ids": ["future-note"]}, "ts": "2026-09-23T18:01:00+00:00"}
    future = {"seq": 3, "msg_id": "future-note", "actor": "claude", "to": "owner", "kind": "note",
              "body": {"text": "later"}, "ts": "2026-09-23T18:02:00+00:00"}
    assert live.question_updates([question, resolution, future]) == []
    resolution["body"]["evidence_msg_ids"] = ["oracle-r"]
    assert live.question_updates([question, resolution, future]) == []
    resolution["body"]["evidence_msg_ids"] = ["oracle-q"]
    resolution["actor"] = "codex"
    assert live.question_updates([question, resolution, future]) == []


@pytest.mark.parametrize(("projection", "expected"), [
    ({"status": "selected", "focus_id": "f", "title": "T", "stage": "needs_clean_refinement",
      "next_action": "Do X.", "intake_policy": "focus_before_new_topics",
      "selected_at": "2026-09-23T01:00:00+00:00", "receipt_sha256": "a" * 64},
     {"status": "selected", "title": "T", "next_action": "Do X.",
      "intake_policy": "focus_before_new_topics", "selected_at": "2026-09-23T01:00:00Z"}),
    ({"status": "none", "execution_authorized": False, "last_closure": {
        "focus_id": "payoff", "title": "Payoff", "disposition": "killed",
        "closed_at": "2026-09-22T23:39:12+00:00", "reason": "Opportunity cost.",
        "closure_sha256": "b" * 64}},
     {"status": "none", "last_closure": {"focus_id": "payoff", "title": "Payoff", "disposition": "killed",
                                         "closed_at": "2026-09-22T23:39:12Z", "reason": "Opportunity cost.",
                                         "closure_sha256": "b" * 64}}),
    ({"status": "source_invalid", "reason": "FocusError"},
     {"status": "source_invalid", "reason": "FocusError"}),
])
def test_research_focus_statuses(repo, monkeypatch, projection, expected):
    monkeypatch.setattr(live, "_project_focus", lambda root: projection)
    focus = _summary(repo)["research_focus"]
    assert {k: focus[k] for k in expected} == expected
    assert "next_gate" not in focus


def test_focus_closures_and_day_closed_notes_are_accomplishments_within_seven_days(repo):
    import hashlib
    closures = repo / "run_state" / "research_focus" / "closures"
    closures.mkdir(parents=True)
    for day in (22, 10):
        raw = json.dumps({"schema_version": "research-focus-closure/v1", "disposition": "killed",
                          "title": f"Focus {day}", "closed_at": f"2026-09-{day}T01:00:00+00:00"}).encode()
        (closures / (hashlib.sha256(raw).hexdigest() + ".json")).write_bytes(raw)
    (closures / ("0" * 64 + ".json")).write_text("{}")  # content does not match its address
    box = Box(repo)
    closed = box.post("oracle", "note", {"title": "DAY CLOSED: 2026-09-22", "text": {"items": []}})
    box.post("claude", "note", {"title": "DAY CLOSED: impostor", "text": "x"})
    now = datetime.fromisoformat(closed["ts"]) + timedelta(days=1)
    rows = live.build(repo, now)["accomplishments"]
    assert [(r["kind"], r["title"], r["evidence"]) for r in rows] == [
        ("day_closed", "DAY CLOSED: 2026-09-22", closed["msg_id"]),
        ("focus_closed", "Focus killed: Focus 22", rows[1]["evidence"])]
    assert len(rows[1]["evidence"]) == 12


def test_broken_mailbox_chain_is_a_warning_and_statuses_are_not_derived(repo):
    _plan(repo, "2026-09-23.json", [_item("d1", "oracle_dev")])
    box = Box(repo)
    box.post("oracle", "note", {"title": "x", "text": "y"})
    box.path.write_text(box.path.read_text().replace('"y"', '"z"'))
    value = _summary(repo)
    assert value["work_items"] == []
    assert any("mailbox is unreadable" in w for w in value["warnings"])


def test_live_summary_with_agents_validates(repo, monkeypatch):
    from backend import daily_ops_agents
    monkeypatch.setattr(daily_ops_agents, "list_processes", lambda: [])
    value = live.live_summary(repo, NOW)
    assert _agents(value["agents"])
    _validate_summary(value)
