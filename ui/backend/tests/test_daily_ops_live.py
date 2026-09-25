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
from pathlib import Path

import pytest

from backend import daily_ops_live as live
from backend import card_presentation_policy as card_policy

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
        # The live view must continue to read historical PLAN READY notes that
        # predate the mailbox writer's newer publish-plan-ready protocol.  Keep
        # those fixtures hash-valid evidence rather than weakening that writer
        # contract merely to construct legacy read-model inputs.
        if (kind == "note" and isinstance(body, dict)
                and str(body.get("title", "")).startswith("PLAN READY:")):
            return _append_hash_valid_row(
                self, schema=oracle_mailbox.SCHEMA, actor=actor, kind=kind,
                body=body, to=to, reply=reply,
            )
        return oracle_mailbox.post(actor, kind, body, to=to, in_reply_to=reply, path=self.path)


def _append_hash_valid_row(box, *, schema, actor, kind, body, to, reply=None, msg_id=None):
    """Append malformed-but-chain-valid evidence without the validated writer."""
    rows = oracle_mailbox.read(box.path)
    row = {
        "schema": schema, "seq": len(rows) + 1, "ts": datetime.now(timezone.utc).isoformat(),
        "actor": actor, "to": to, "kind": kind, "in_reply_to": reply, "body": body,
        "expires_at": None, "prev_sha256": rows[-1]["row_sha256"] if rows else None,
    }
    row["msg_id"] = (msg_id
                     or f"{actor.split(':')[0]}-"
                     f"{hashlib.sha256(oracle_mailbox._canonical(row)).hexdigest()[:16]}")
    row["row_sha256"] = hashlib.sha256(oracle_mailbox._canonical(row)).hexdigest()
    with box.path.open("a") as handle:
        handle.write(json.dumps(row) + "\n")
    return row


def _contest(box, resolution, *, reporter="oracle"):
    """Append the two structured self-reports and conservative reviewer contest used by seq680."""
    first = box.post(reporter, "note", {
        "title": "NOT MINE", "text": "I used the wrong actor label.",
        "ref": {"posted_row": f"{resolution['msg_id']} (seq {resolution['seq']})",
                "command": f"oracle_mailbox post --as {resolution['actor']}"},
    })
    second = box.post(reporter, "note", {
        "title": "Plan note with self-report", "text": "Preserve the contaminated row.",
        "ref": {"self_reported_fault":
                f"seq {resolution['seq']} posted with --as {resolution['actor']} by this session"},
    })
    contest = box.post("codex", "note", {
        "title": "Contested attribution", "text": "Preserve the row and reopen the question.",
        "provenance_contestation": {
            "contested_msg_id": resolution["msg_id"], "claimed_actor": resolution["actor"],
            "reported_actual_actor": reporter, "basis_msg_ids": [first["msg_id"], second["msg_id"]],
            "effect": "invalidate_for_projection",
        },
    }, reply=resolution["msg_id"])
    return first, second, contest


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
    value["agents"] = {k: {"label": f"{k} client", "role": "test observer", "status": "idle", "detail": "d",
                           "observed_at": "2026-09-23T18:00:00Z", "source": "s",
                           "activity": None, "activity_at": None, "since": None}
                       for k in ("oracle", "pi_client", "nara")}
    live.validate_live(value, live.validate_agents)
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


@pytest.mark.parametrize("reverse_ready", [False, True])
def test_legacy_base_and_explicit_r1_collision_fails_closed_until_r2(repo, reverse_ready):
    base = _plan(repo, "2026-09-23.json", [_item("d1", "nara_dev", "Base task")])
    r1 = _plan(repo, "2026-09-23-r1.json", [_item("d1", "nara_dev", "R1 task")])
    box = Box(repo)

    def ready(path):
        return box.post("oracle", "note", {
            "title": f"PLAN READY: {path.name[:10]}",
            "ref": {"path": path.relative_to(repo).as_posix(),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
        })

    if reverse_ready:
        ready(r1)
    ready(base)
    first_item = box.post("oracle", "plan_item", {**PLAN_ITEM, "title": "Base task"}, to="nara")
    box.post("nara", "receipt", {"state": "validated", "head_sha": "a" * 40},
             to="oracle", reply=first_item["msg_id"])
    if not reverse_ready:
        ready(r1)
    box.post("oracle", "plan_item", {**PLAN_ITEM, "title": "Base task"}, to="nara")

    rows = oracle_mailbox.read(box.path)
    assert live.plan_files(repo) == {}
    assert live.current_plan(repo, NOW) is None
    catalog = live._plan_catalog(repo, live.plan_files(repo))
    windows = live.plan_windows(rows, max_date="2026-09-23")
    base_window = live._revision_window(
        rows, windows, "2026-09-23", base.name,
        hashlib.sha256(base.read_bytes()).hexdigest(), None, catalog)
    r1_window = live._revision_window(
        rows, windows, "2026-09-23", r1.name,
        hashlib.sha256(r1.read_bytes()).hexdigest(), None, catalog)
    assert base_window == (float("inf"), float("inf"), True)
    assert r1_window == (float("inf"), float("inf"), True)

    value = _summary(repo)
    assert value["daily_plan"] is None and value["current_plan_revision"] is None
    assert value["work_items"] == [] and value["accomplishments"] == []
    assert any("revision identity is ambiguous" in warning for warning in value["warnings"])

    r2 = _plan(repo, "2026-09-23-r2.json", [_item("d1", "nara_dev", "R2 task")])
    ready(r2)
    r2_item = box.post("oracle", "plan_item", {**PLAN_ITEM, "title": "R2 task"}, to="nara")
    value = _summary(repo)
    assert value["current_plan_revision"] == "2026-09-23-r2"
    assert value["work_items"][0]["evidence_msg_id"] == r2_item["msg_id"]
    assert value["accomplishments"] == []
    assert any("revision identity is ambiguous" in warning for warning in value["warnings"])


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
    mismatched = box.post("oracle", "note", {
        "title": "PLAN READY: 2026-09-23 (r2)",
        "ref": {"path": "run_state/daily_plans/2026-09-23-r2.json", "sha256": "f" * 64},
    })
    box.post("claude", "review", {"verdict": "amend", "summary": "Wrong content."},
             reply=mismatched["msg_id"])
    assert _summary(repo)["daily_plan"]["review"] is None
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
    box.post("claude", "review", {"verdict": "reject", "summary": "Old revision."},
             reply=old_d3["msg_id"])
    old_d4 = box.post("oracle", "note", {
        "title": "READY FOR REVIEW: oracle/2026-09-23-d4",
        "ref": {"branch": "oracle/2026-09-23-d4", "item": "d4"},
    })
    box.post("claude", "review", {"verdict": "amend", "summary": "Old revision."},
             reply=old_d4["msg_id"])
    box.post("claude", "question", {"question": "Old d5?", "ref": {"item": "d5"}}, to="owner")
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
        "d1": "not_started", "d3": "not_started", "d4": "not_started", "d5": "held",
    }
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
    now = NOW
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


def test_owner_cards_require_a_real_question_and_non_owner_explicit_resolution(repo):
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
    assert items["d6"]["status"] == "held"
    assert "Oracle or Nara must" in items["d6"]["detail"]
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

    box.post("claude", "answer", {"text": "relayed owner preference"}, to="oracle", reply=asked["msg_id"])
    value = _summary(repo)
    assert value["work_items"][0]["status"] == "waiting_on_you"
    assert value["work_items"][1]["status"] == "held"

    box.post("human:derrick", "answer", {"text": "Install on main."}, to="claude", reply=asked["msg_id"])
    box.post("claude", "answer", {"text": "relayed"}, to="oracle", reply=other["msg_id"])
    value = _summary(repo)
    assert value["work_items"][0]["status"] == "waiting_on_you"
    # Model relays and human labels are context, not authenticated closures.
    assert {w["id"] for w in value["waiting_on_you"]} == {"2026-09-23:d5", other["msg_id"]}
    assert any(row["disposition"] == "contested" for row in value["question_updates"])
    other_resolution = box.post("oracle", "question_resolution", {
        "disposition": "superseded", "summary": "The later plan replaced this ruling.",
        "reason": "No owner action remains.",
    }, to="owner", reply=other["msg_id"])
    value = _summary(repo)
    assert {row["id"] for row in value["waiting_on_you"]} == {"2026-09-23:d5", other["msg_id"]}
    assert any(row["id"] == other_resolution["msg_id"] and row["disposition"] == "contested"
               for row in value["question_updates"])

    d6_question = box.post("oracle", "question", {"title": "Item d6", "ref": {"item": "d6"}}, to="owner")
    resolution = box.post("oracle", "question_resolution", {
        "disposition": "superseded", "summary": "Oracle selected the replacement path.",
        "reason": "The owner choice is no longer needed.",
    }, to="owner", reply=d6_question["msg_id"])
    value = _summary(repo)
    assert value["work_items"][1]["status"] == "waiting_on_you"
    assert value["work_items"][1]["evidence_msg_id"] == d6_question["msg_id"]
    assert {row["id"] for row in value["waiting_on_you"]} == {
        "2026-09-23:d5", other["msg_id"], "2026-09-23:d6",
    }
    assert {other_resolution["msg_id"], resolution["msg_id"]} <= {
        row["id"] for row in value["question_updates"]
    }


@pytest.mark.parametrize("terminal", ["answer", "question_resolution"])
def test_hash_valid_wrong_schema_terminal_cannot_hide_owner_card(repo, terminal):
    path = _plan(repo, "2026-09-23-r2.json", [_item("d5", "owner_decision")])
    box = Box(repo)
    box.post("oracle", "note", {
        "title": "PLAN READY: 2026-09-23-r2",
        "ref": {"path": path.relative_to(repo).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
    })
    question = box.post("claude", "question", {
        "title": "Choose the lab profile", "ref": {"item": "d5"},
    }, to="owner")
    if terminal == "answer":
        actor, body, to = "human:derrick", {"text": "Use C4."}, "claude"
    else:
        actor, body, to = "claude", {
            "disposition": "superseded", "summary": "Claimed complete.",
            "reason": "This row has the wrong schema.",
        }, "owner"
    malformed = _append_hash_valid_row(
        box, schema="oracle-nara-mailbox/v999", actor=actor, kind=terminal,
        body=body, to=to, reply=question["msg_id"])

    # The source remains readable and append-only, but the action projection
    # does not let the malformed terminal row close a real question.
    assert oracle_mailbox.read(box.path)[-1]["msg_id"] == malformed["msg_id"]
    value = _summary(repo)
    assert value["work_items"][0]["status"] == "waiting_on_you"
    assert [card["msg_id"] for card in value["waiting_on_you"]] == [question["msg_id"]]
    assert any("structurally invalid row" in warning for warning in value["warnings"])


@pytest.mark.parametrize("terminal", ["answer", "question_resolution"])
def test_hash_valid_terminal_before_its_question_cannot_close_future_card(repo, monkeypatch, terminal):
    box = Box(repo)
    box.post("oracle", "note", {"title": "A preceding valid row"})
    future_id = "claude-future-question"
    if terminal == "answer":
        actor, body, to = "human:derrick", {
            "text": "Approve", "via": "owner-ui", "request_id": "11111111-1111-1111-1111-111111111111",
            "target_kind": "question", "expected_plan_revision": "2026-09-25-r5",
        }, "claude"
    else:
        actor, body, to = "claude", {
            "disposition": "superseded", "summary": "Claimed complete.",
            "reason": "This terminal predates the question it names.",
        }, "owner"
    terminal_row = _append_hash_valid_row(
        box, schema=oracle_mailbox.SCHEMA, actor=actor, kind=terminal,
        body=body, to=to, reply=future_id)
    question = _append_hash_valid_row(
        box, schema=oracle_mailbox.SCHEMA, actor="claude", kind="question",
        body={"title": "The real future question"}, to="owner", msg_id=future_id)
    recorded = oracle_mailbox.read(box.path)
    assert [row["seq"] for row in recorded[-2:]] == [2, 3]
    assert terminal_row["row_sha256"] == recorded[1]["row_sha256"]
    if terminal == "answer":
        assert live._human_answer(question, recorded) is None
    else:
        assert live._question_resolution(question, recorded) is None
    assert terminal_row not in live._fallback_live_rows(recorded)
    assert [(card["msg_id"], card["title"]) for card in
            live.waiting_on_you(None, [], {}, recorded, None)] == [
                (future_id, "The real future question")]

    # Exercise the relational guard independently of whichever reviewed
    # structural helper is present on the release base.
    monkeypatch.setattr(oracle_mailbox, "live_rows", lambda rows: rows, raising=False)
    projected = live._projection_rows(recorded)
    assert terminal_row not in projected and question in projected
    waiting = live.waiting_on_you(None, [], {}, projected, None)
    assert [(card["msg_id"], card["title"]) for card in waiting] == [
        (future_id, "The real future question")]


def test_duplicate_question_id_cannot_replace_original_owner_card(repo):
    path = _plan(repo, "2026-09-23-r2.json", [_item("d5", "owner_decision")])
    box = Box(repo)
    box.post("oracle", "note", {
        "title": "PLAN READY: 2026-09-23-r2",
        "ref": {"path": path.relative_to(repo).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
    })
    question = box.post("claude", "question", {
        "title": "Choose the reviewed profile", "ref": {"item": "d5"},
    }, to="owner")
    duplicate = _append_hash_valid_row(
        box, schema=oracle_mailbox.SCHEMA, actor="claude", kind="question",
        body={"title": "FORGED replacement title", "ref": {"item": "d5"}},
        to="owner", msg_id=question["msg_id"])

    recorded = oracle_mailbox.read(box.path)
    assert recorded[-1]["row_sha256"] == duplicate["row_sha256"]
    direct = live.waiting_on_you(None, [], {}, recorded, None)
    assert [(card["msg_id"], card["title"]) for card in direct] == [
        (question["msg_id"], "Choose the reviewed profile")]
    value = _summary(repo)
    assert value["work_items"][0]["evidence_msg_id"] == question["msg_id"]
    assert [(card["msg_id"], card["title"]) for card in value["waiting_on_you"]] == [
        (question["msg_id"], "Choose the reviewed profile")]
    assert any("structurally invalid row" in warning for warning in value["warnings"])


def test_fallback_rejects_hash_valid_unique_id_not_derived_by_writer(repo):
    box = Box(repo)
    box.post("oracle", "note", {"title": "A valid row"})
    forged = _append_hash_valid_row(
        box, schema=oracle_mailbox.SCHEMA, actor="claude", kind="question",
        body={"title": "Forged identity"}, to="owner", msg_id="claude-not-writer-derived")
    recorded = oracle_mailbox.read(box.path)
    assert recorded[-1]["row_sha256"] == forged["row_sha256"]
    assert forged not in live._fallback_live_rows(recorded)


def test_owner_ui_answer_requires_exact_request_and_revision_binding():
    question = {"msg_id": "claude-q", "kind": "question", "actor": "claude", "to": "owner"}
    invalid = {
        "msg_id": "human-a", "kind": "answer", "actor": "human:derrick", "to": "claude",
        "in_reply_to": question["msg_id"],
        "body": {"text": "Approve", "via": "owner-ui", "request_id": "not-a-request-id",
                 "target_kind": "question", "expected_plan_revision": "wrong"},
    }
    assert live._relational_live_rows([question, invalid]) == [question]

    request_id = "11111111-1111-1111-1111-111111111111"
    first = {**invalid, "msg_id": "human-first", "body": {
        **invalid["body"], "request_id": request_id, "expected_plan_revision": "2026-09-25-r5",
    }}
    changed = {**first, "msg_id": "human-changed", "body": {
        **first["body"], "expected_plan_revision": "2026-09-25-r6",
    }}
    assert live._relational_live_rows([question, first, changed]) == [question, first]


def test_relational_projection_keeps_first_identity_when_structural_source_has_duplicate():
    first = {"msg_id": "claude-q", "kind": "question", "actor": "claude", "to": "owner"}
    duplicate = {**first, "body": {"title": "forged"}}
    assert live._relational_live_rows([first, duplicate]) == [first]


def test_owner_question_card_keeps_structured_title_and_legacy_free_text_actionable():
    lane_context = ((
        "The main checkout is on the Flash branch while main contains the reviewed lane inputs. "
        "The lane builds from checkout HEAD but prechecks stamp main, so fresh receipts and builds disagree. "
        "Reconcile the checkout in an attended window, pin the lane base, or keep Nara items held. "
    ) * 2).strip()
    structured = {
        "msg_id": "claude-lane-base", "body": {
            "title": "Should the Nara lane build on main?",
            "question": lane_context,
            "options": ["reconcile in an attended window", "pin the lane base", "keep items held"],
            "recommendation": "Reconcile in an attended window.",
            "consequence_of_deferring": "Nara items remain held on the divergent checkout.",
        },
    }
    assert live._question_card(structured) == {
        "title": "Should the Nara lane build on main?",
        "question": "Should the Nara lane build on main?",
        "context": lane_context,
        "choices": ["reconcile in an attended window", "pin the lane base", "keep items held"],
        "recommendation": "Reconcile in an attended window.",
        "consequence": "Nara items remain held on the divergent checkout.",
    }

    legacy = {"msg_id": "claude-retro", "body": {
        "title": "Two authority rulings from the retro",
        "text": "The first ruling needs a named state-root exception; the second asks about a canary.",
    }}
    assert live._question_card(legacy) == {
        "title": "Two authority rulings from the retro",
        "question": "Two authority rulings from the retro",
        "context": "The first ruling needs a named state-root exception; the second asks about a canary.",
        "choices": [], "recommendation": None, "consequence": None,
    }

    no_title_short = {"msg_id": "oracle-short", "body": {"question": "Run the source screen?"}}
    assert live._question_card(no_title_short)["context"] is None
    no_title_long = {"msg_id": "oracle-long", "body": {"question": lane_context}}
    assert live._question_card(no_title_long) == {
        "title": lane_context[:299].rstrip() + "…", "question": lane_context[:299].rstrip() + "…",
        "context": lane_context, "choices": [], "recommendation": None, "consequence": None,
    }
    text_only_long = {"msg_id": "oracle-text", "body": {"text": lane_context}}
    assert live._question_card(text_only_long) == {
        "title": lane_context[:299].rstrip() + "…", "question": lane_context[:299].rstrip() + "…",
        "context": lane_context, "choices": [], "recommendation": None, "consequence": None,
    }
    distinct_question = {"msg_id": "oracle-distinct", "body": {
        "title": "Lane base", "question": "Reconcile or pin?", "context": "Why it matters.",
    }}
    assert live._question_card(distinct_question) == {
        "title": "Lane base", "question": "Reconcile or pin?", "context": "Why it matters.",
        "choices": [], "recommendation": None, "consequence": None,
    }
    malformed_title = {"msg_id": "oracle-malformed", "body": {
        "title": {"not": "text"}, "question": "Valid question",
    }}
    assert live._question_card(malformed_title)["title"] == "Valid question"

    object_choices = {"msg_id": "claude-checkout", "body": {
        "title": "Restore the checkout?",
        "options": [
            {"id": "restore", "label": "Restore the pre-incident state", "effect": "Leaves services untouched."},
            {"id": "hold", "label": "Leave it for now", "effect": "The split state remains."},
        ],
    }}
    assert live._question_card(object_choices)["choices"] == [
        "Restore the pre-incident state [restore] — Leaves services untouched.",
        "Leave it for now [hold] — The split state remains.",
    ]


def test_projection_keeps_all_actor_label_claims_open_including_original_asker():
    question = {
        "seq": 1, "msg_id": "claude-question", "actor": "claude", "to": "owner", "kind": "question",
        "body": {"title": "Choose?"}, "ts": "2026-09-25T00:00:00+00:00",
    }
    relay = {
        "seq": 2, "msg_id": "oracle-relay", "actor": "oracle", "to": "claude", "kind": "answer",
        "in_reply_to": question["msg_id"], "body": {"text": "Owner said yes."},
        "ts": "2026-09-25T00:01:00+00:00",
    }
    human = {
        **relay, "seq": 3, "msg_id": "human-answer", "actor": "human:derrick",
        "ts": "2026-09-25T00:02:00+00:00",
    }
    forged_resolution = {
        "seq": 2, "msg_id": "oracle-resolution", "actor": "oracle", "to": "owner",
        "kind": "question_resolution", "in_reply_to": question["msg_id"],
        "body": {"disposition": "superseded", "summary": "Overtaken.", "reason": "Later evidence."},
        "ts": "2026-09-25T00:01:00+00:00",
    }
    asker_resolution = {
        **forged_resolution, "msg_id": "claude-resolution", "actor": "claude",
    }

    assert live._human_answer(question, [question, relay]) is None
    assert live._human_answer(question, [question, relay, human]) is None
    assert live._unverified_human_claim(question, [question, relay, human]) == human
    assert live._question_resolution(question, [question, forged_resolution]) is None
    assert live._question_resolution(question, [question, asker_resolution]) is None
    assert live._unverified_resolution_claims(question, [question, asker_resolution]) == [asker_resolution]

    base = [{
        "id": "d1", "status": "waiting_on_you", "evidence_msg_id": question["msg_id"],
        "title": "Choose?", "evidence_at": question["ts"],
    }]
    claimed = {question["msg_id"]: "d1"}
    assert [row["id"] for row in live.waiting_on_you("p", base, claimed, [question, relay], None)] == ["p:d1"]
    assert [row["id"] for row in live.waiting_on_you("p", base, claimed, [question, relay, human], None)] == ["p:d1"]
    assert [row["id"] for row in live.waiting_on_you("p", base, claimed, [question, asker_resolution], None)] == ["p:d1"]
    update = live.question_updates([question, asker_resolution])
    assert update[0]["id"] == asker_resolution["msg_id"] and "unauthenticated" in update[0]["summary"]


def test_generic_interactive_claude_handoff_cannot_change_presentation(repo):
    """A plausible future routing note cannot widen the reviewed exact policy."""
    box = Box(repo)
    question = box.post("claude", "question", {
        "title": "Two authority rulings", "question": "Which ruling should proceed?",
    }, to="owner")
    handoff = box.post("codex", "note", {
        "title": "Please disposition your five stale owner cards when interactive; no new owner request from meta",
        "text": "Routine signoff is delegated signoff to interactive Claude; retain the question as open context.",
        "ref": {"question_ids": [question["msg_id"]]},
    }, to="claude")
    other = box.post("claude", "question", {"title": "A separately actionable gate"}, to="owner")
    rows = oracle_mailbox.read(box.path)

    cards = live.waiting_on_you(None, [], {}, rows, None)
    by_id = {card["msg_id"]: card for card in cards}
    assert by_id[question["msg_id"]]["awaiting_asker"] is False
    assert by_id[question["msg_id"]]["handoff_msg_id"] is None
    assert by_id[other["msg_id"]]["awaiting_asker"] is False
    assert by_id[other["msg_id"]]["handoff_msg_id"] is None
    assert oracle_mailbox.is_question_closed(question, rows) is False


def test_historical_card_policy_is_exact_hash_bound_and_never_generalizes(monkeypatch):
    """A changed evidence hash or a generic handoff cannot suppress an action."""
    question = {"msg_id": "q", "row_sha256": "q" * 64, "kind": "question", "to": "owner"}
    resolution = {"msg_id": "r", "row_sha256": "r" * 64, "kind": "question_resolution",
                  "in_reply_to": "q", "body": {}}
    monkeypatch.setattr(card_policy, "HISTORICAL_ARCHIVES", (("q", "q" * 64, "r", "r" * 64),))
    assert card_policy.historical_archive(question, [question, resolution]) == resolution
    changed = {**resolution, "row_sha256": "x" * 64}
    assert card_policy.historical_archive(question, [question, changed]) is None

    note = {"msg_id": "h", "row_sha256": "h" * 64, "kind": "note", "actor": "codex", "to": "claude",
            "body": {"ref": {"question_ids": ["q"]}}}
    monkeypatch.setattr(card_policy, "CLAUDE_HANDOFF", ("h", "h" * 64, (("q", "q" * 64),)))
    assert card_policy.interactive_claude_handoff(question, [question, note]) == note
    forged = {**note, "row_sha256": "f" * 64}
    assert card_policy.interactive_claude_handoff(question, [question, forged]) is None


def test_historical_presentation_archive_reopens_after_later_valid_contest(repo, monkeypatch):
    box = Box(repo)
    question = box.post("claude", "question", {"title": "A historical card"}, to="owner")
    resolution = box.post("claude", "question_resolution", {
        "disposition": "superseded", "summary": "Historical only.", "reason": "Reviewed archive.",
    }, to="owner", reply=question["msg_id"])
    monkeypatch.setattr(card_policy, "HISTORICAL_ARCHIVES", ((
        question["msg_id"], question["row_sha256"], resolution["msg_id"], resolution["row_sha256"],
    ),))
    rows = oracle_mailbox.read(box.path)
    assert live._historical_presentation_archive(question, rows) == resolution
    _contest(box, resolution, reporter="oracle")
    contested = oracle_mailbox.read(box.path)
    assert live._historical_presentation_archive(question, contested) is None
    assert question["msg_id"] in {card["msg_id"] for card in live.waiting_on_you(None, [], {}, contested, None)}


def test_historical_presentation_archive_reopens_for_later_owner_context(repo, monkeypatch):
    box = Box(repo)
    question = box.post("claude", "question", {"title": "An older card"}, to="owner")
    resolution = box.post("claude", "question_resolution", {
        "disposition": "superseded", "summary": "Historical only.", "reason": "Reviewed archive.",
    }, to="owner", reply=question["msg_id"])
    monkeypatch.setattr(card_policy, "HISTORICAL_ARCHIVES", ((
        question["msg_id"], question["row_sha256"], resolution["msg_id"], resolution["row_sha256"],
    ),))
    box.post("human:derrick", "answer", {"text": "Use the new evidence."}, to="claude",
             reply=question["msg_id"])
    box.post("human:derrick", "note", {
        "via": "authorized-owner-ui", "reconciliation": "genuine_owner_confirmation_required",
        "text": "Reconcile before proceeding.",
    }, to="claude", reply=question["msg_id"])
    rows = oracle_mailbox.read(box.path)
    assert live._historical_presentation_archive(question, rows) is None
    assert question["msg_id"] in {card["msg_id"] for card in live.waiting_on_you(None, [], {}, rows, None)}
    updates = live.question_updates(rows)
    assert {row["id"] for row in updates} >= {rows[-2]["msg_id"], rows[-1]["msg_id"]}


def test_primary_mailbox_replay_anchors_only_the_reviewed_cards():
    """Replay the deployed primary mailbox when this lab fixture is available.

    The checkout deliberately does not vendor a mutable operational log.  This
    test still makes the exact primary replay part of the attended release
    check, while portable tests above exercise the policy's fail-closed shape.
    """
    primary = Path("/home/decross1/projects/a_bgt_rsi/run_state/oracle_nara_mailbox.jsonl")
    if not primary.is_file():
        pytest.skip("primary lab mailbox is not available in this checkout")
    rows = oracle_mailbox.read(primary)
    # The operational mailbox is append-only: new coordination notes must not
    # invalidate the exact reviewed fixture or silently enter its assertions.
    assert len(rows) >= 857
    assert rows[856]["seq"] == 857
    assert rows[856]["row_sha256"] == (
        "9f04c90d3e9374aed7b423994a61870b2094c04ae935df1683c0dc01f0d5e5cb")
    rows = rows[:857]
    cards = live._waiting_cards(None, [], {}, rows, None)
    by_id = {card["msg_id"]: card for card in cards}
    archived = {row[0] for row in card_policy.HISTORICAL_ARCHIVES}
    assert len(cards) == 7
    assert len(card_policy.HISTORICAL_ARCHIVES) == 10
    for question_id, question_sha, evidence_id, evidence_sha in card_policy.HISTORICAL_ARCHIVES:
        question = next(row for row in rows if row["msg_id"] == question_id)
        evidence = card_policy.historical_archive(question, rows)
        assert question["row_sha256"] == question_sha
        assert evidence is not None
        assert (evidence["msg_id"], evidence["row_sha256"]) == (evidence_id, evidence_sha)
    assert archived.isdisjoint(by_id)
    # q815/819 has no independently durable corroboration; q604's purported
    # asker resolution is contested.  Both must remain owner-actionable.
    assert by_id["oracle-0065d604c31a1f22"]["awaiting_asker"] is False
    assert by_id["claude-dcc5a13d09fea05b"]["awaiting_asker"] is False
    handoff_ids = {question_id for question_id, _ in card_policy.CLAUDE_HANDOFF[2]}
    assert all(by_id[question_id]["awaiting_asker"] is True for question_id in handoff_ids)
    assert live.question_updates_overflow(rows) >= 2


def test_waiting_cards_prioritize_actions_and_report_bounded_overflow():
    rows = []
    for index in range(17):
        rows.append({"seq": index + 1, "msg_id": f"q-{index}", "actor": "oracle", "to": "owner",
                     "kind": "question", "body": {"title": f"Question {index}"},
                     "ts": "2026-09-25T00:00:00+00:00"})
    cards = live.waiting_on_you(None, [], {}, rows, None)
    assert len(cards) == live.MAX_ROWS and cards[-1]["msg_id"] == "q-15"
    assert live.waiting_overflow(None, [], {}, rows, None) == 1


def test_question_update_overflow_is_visible_to_the_summary(repo, monkeypatch):
    box = Box(repo)
    archives = []
    for index in range(11):
        question = box.post("claude", "question", {"title": f"Archived {index}"}, to="owner")
        resolution = box.post("claude", "question_resolution", {
            "disposition": "informational", "summary": "Archived.", "reason": "History.",
        }, to="owner", reply=question["msg_id"])
        archives.append((question["msg_id"], question["row_sha256"],
                         resolution["msg_id"], resolution["row_sha256"]))
    monkeypatch.setattr(card_policy, "HISTORICAL_ARCHIVES", tuple(archives))
    rows = oracle_mailbox.read(box.path)
    assert len(live.question_updates(rows)) == 10
    assert live.question_updates_overflow(rows) == 1
    value = _summary(repo)
    assert any("1 additional non-terminal or historical update" in warning for warning in value["warnings"])


def test_stale_plan_is_history_not_an_actionable_plan(repo):
    _plan(repo, "2026-09-23.json", [_item("d1", "oracle_dev")])
    assert live.current_plan(repo, NOW + timedelta(days=2)) is None
    value = _summary(repo, NOW + timedelta(days=2))
    assert value["daily_plan"]["is_current"] is False
    assert value["work_items"] == []
    assert any("controls are disabled" in warning for warning in value["warnings"])


def test_future_plan_is_not_actionable_early(repo):
    _plan(repo, "2026-09-24.json", [_item("d1", "oracle_dev")])
    assert live.current_plan(repo, NOW) is None
    value = _summary(repo)
    assert value["daily_plan"]["is_current"] is False
    assert value["work_items"] == []


def test_future_plan_does_not_shadow_today_plan(repo):
    _plan(repo, "2026-09-23.json", [_item("today", "oracle_dev")])
    _plan(repo, "2026-09-24.json", [_item("future", "oracle_dev")])
    assert live.current_plan(repo, NOW)[0] == "2026-09-23"
    value = _summary(repo)
    assert value["daily_plan"]["id"] == "2026-09-23"
    assert value["daily_plan"]["is_current"] is True
    assert value["current_plan_revision"] == "2026-09-23"


@pytest.mark.parametrize(("current_name", "intruder_name"), [
    ("2026-09-23-r10.json", "2026-09-24.json"),
    ("2026-09-23-r10.json", "2026-09-23-r9.json"),
    ("2026-09-23.json", "2026-09-22.json"),
])
def test_future_or_delayed_older_anchor_cannot_erase_current_work(repo, current_name, intruder_name):
    current = _plan(repo, current_name, [_item("d1", "nara_dev", "Current item")])
    intruder = _plan(repo, intruder_name, [_item("d1", "nara_dev", "Other item")])
    box = Box(repo)
    for path in (current, intruder):
        box.post("oracle", "note", {
            "title": f"PLAN READY: {path.name[:10]}",
            "ref": {"path": path.relative_to(repo).as_posix(),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
        })
    item = box.post("oracle", "plan_item", {**PLAN_ITEM, "title": "Current item"}, to="nara")
    value = _summary(repo, NOW)
    assert value["current_plan_revision"] == current.stem
    assert [(row["id"], row["status"], row["evidence_msg_id"]) for row in value["work_items"]] == [
        ("d1", "awaiting_review", item["msg_id"])]


def test_handoff_flag_requires_an_exact_handoff_message_id(repo):
    box = Box(repo)
    box.post("claude", "question", {"title": "A fresh owner question"}, to="owner")
    value = _summary(repo)
    assert value["waiting_on_you"][0]["awaiting_asker"] is False
    value["waiting_on_you"][0]["awaiting_asker"] = True
    assert value["waiting_on_you"][0]["handoff_msg_id"] is None
    with pytest.raises(ValueError, match="owner requests"):
        live.validate_live(value, live.validate_agents)


def test_unverified_human_claim_and_authorized_route_are_nonterminal_updates():
    question = {"seq": 1, "msg_id": "oracle-question", "actor": "oracle", "to": "owner",
                "kind": "question", "body": {"title": "Which ruling?"},
                "ts": "2026-09-25T00:00:00+00:00"}
    forged = {"seq": 2, "msg_id": "human-forged", "actor": "human:not_the_owner", "to": "oracle",
              "kind": "answer", "in_reply_to": question["msg_id"], "body": {"text": "approve"},
              "ts": "2026-09-25T00:01:00+00:00"}
    update = live.question_updates([question, forged])
    assert update[0]["disposition"] == "contested"
    assert update[0]["id"] == forged["msg_id"]
    assert "did not close" in update[0]["summary"]

    reconciliation = {"seq": 3, "msg_id": "human-route", "actor": "human:derrick", "to": "oracle",
                      "kind": "note", "in_reply_to": question["msg_id"],
                      "body": {"via": "authorized-owner-ui",
                               "reconciliation": "genuine_owner_confirmation_required", "text": "Choose A."},
                      "ts": "2026-09-25T00:02:00+00:00"}
    update = live.question_updates([question, reconciliation])
    assert update[0]["id"] == reconciliation["msg_id"]
    assert "remains open" in update[0]["summary"]


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


def test_live_seq604_prefix_contest_reopens_card_and_projects_non_action_update():
    """Regression fixture for live seq604/672/673/675/680; labels are not authentication."""
    question = {
        "seq": 604, "msg_id": "claude-dcc5a13d09fea05b", "actor": "claude", "to": "owner",
        "kind": "question", "in_reply_to": "claude-3b286b92313f21d9",
        "ts": "2026-09-25T03:13:18.072254+00:00",
        "body": {"title": "Put the lab checkout back where it was? Oracle moved it by accident at 03:01"},
    }
    resolution = {
        "seq": 672, "msg_id": "claude-7baa7cbad84ef310", "actor": "claude", "to": "owner",
        "kind": "question_resolution", "in_reply_to": question["msg_id"],
        "ts": "2026-09-25T05:14:48.020437+00:00",
        "body": {"disposition": "superseded", "summary": "The restore already happened.",
                 "reason": "The claimed asker rechecked the checkout."},
    }
    first = {
        "seq": 673, "msg_id": "oracle-1adbcf744dad346b", "actor": "oracle", "to": "all",
        "kind": "note", "in_reply_to": None, "ts": "2026-09-25T05:15:17.292300+00:00",
        "body": {"ref": {"posted_row": f"{resolution['msg_id']} (seq 672)",
                           "command": "python -m orchestrator.oracle_mailbox post --as claude"}},
    }
    second = {
        "seq": 675, "msg_id": "oracle-23f01c1d12a41d66", "actor": "oracle", "to": "all",
        "kind": "note", "in_reply_to": None, "ts": "2026-09-25T05:19:29.493710+00:00",
        "body": {"ref": {"self_reported_fault":
                           "seq 672 posted with --as claude by this session, disowned at seq 673"}},
    }
    contest = {
        "seq": 680, "msg_id": "codex-8fbb6371871c852c", "actor": "codex", "to": "all",
        "kind": "note", "in_reply_to": resolution["msg_id"],
        "ts": "2026-09-25T05:24:14.856582+00:00",
        "body": {"title": "Contested attribution for seq672; preserve and reopen seq604 in projections",
                 "text": "Pi self-reported that it posted seq672 with --as claude.",
                 "provenance_contestation": {
                     "contested_msg_id": resolution["msg_id"], "claimed_actor": "claude",
                     "reported_actual_actor": "oracle",
                     "basis_msg_ids": [first["msg_id"], second["msg_id"]],
                     "effect": "invalidate_for_projection",
                 }},
    }
    rows = [question, resolution, first, second, contest]

    assert oracle_mailbox.is_valid_question_resolution(question, resolution, rows[:-1]) is True
    assert oracle_mailbox.is_valid_question_resolution(question, resolution, rows) is False
    assert live._question_resolution(question, rows) is None
    waiting = live.waiting_on_you("2026-09-25-r4", [{
        "id": "d5", "status": "waiting_on_you", "evidence_msg_id": question["msg_id"],
        "title": "Lane base", "evidence_at": question["ts"],
    }], {question["msg_id"]: "d5"}, rows, None)
    assert [card["id"] for card in waiting] == ["2026-09-25-r4:d5"]
    updates = live.question_updates(rows)
    assert len(updates) == 1
    assert updates[0]["id"] == contest["msg_id"]
    assert updates[0]["disposition"] == "contested"
    assert updates[0]["evidence_msg_ids"] == [first["msg_id"], second["msg_id"]]


def test_contested_question_keeps_later_claim_and_authorized_context_distinct():
    question = {"seq": 604, "msg_id": "claude-q", "actor": "claude", "to": "owner",
                "kind": "question", "body": {"title": "Name the ruling"},
                "ts": "2026-09-25T03:13:18+00:00"}
    resolution = {"seq": 672, "msg_id": "claude-r", "actor": "claude", "to": "owner",
                  "kind": "question_resolution", "in_reply_to": question["msg_id"],
                  "body": {"disposition": "superseded", "summary": "Claimed done.", "reason": "Claim."},
                  "ts": "2026-09-25T05:14:48+00:00"}
    first = {"seq": 673, "msg_id": "oracle-a", "actor": "oracle", "to": "all", "kind": "note",
             "body": {"ref": {"posted_row": "claude-r", "command": "post --as claude"}},
             "ts": "2026-09-25T05:15:17+00:00"}
    second = {"seq": 675, "msg_id": "oracle-b", "actor": "oracle", "to": "all", "kind": "note",
              "body": {"ref": {"self_reported_fault": "seq 672 posted with --as claude by this session"}},
              "ts": "2026-09-25T05:19:29+00:00"}
    contest = {"seq": 680, "msg_id": "codex-c", "actor": "codex", "to": "all", "kind": "note",
               "in_reply_to": resolution["msg_id"], "ts": "2026-09-25T05:24:14+00:00",
               "body": {"provenance_contestation": {
                   "contested_msg_id": resolution["msg_id"], "claimed_actor": "claude",
                   "reported_actual_actor": "oracle", "basis_msg_ids": [first["msg_id"], second["msg_id"]],
                   "effect": "invalidate_for_projection"}}}
    claim = {"seq": 681, "msg_id": "human-later", "actor": "human:derrick", "to": "claude",
             "kind": "answer", "in_reply_to": question["msg_id"], "body": {"text": "Use the pinned base."},
             "ts": "2026-09-25T05:25:00+00:00"}
    reconciliation = {"seq": 682, "msg_id": "owner-route", "actor": "human:derrick", "to": "claude",
                      "kind": "note", "in_reply_to": question["msg_id"],
                      "body": {"via": "authorized-owner-ui",
                               "reconciliation": "genuine_owner_confirmation_required",
                               "text": "Confirm pinned base for the next run."},
                      "ts": "2026-09-25T05:26:00+00:00"}
    rows = [question, resolution, first, second, contest, claim, reconciliation]

    updates = live.question_updates(rows)
    assert {row["id"] for row in updates} == {contest["msg_id"], claim["msg_id"], reconciliation["msg_id"]}
    assert any("pinned base" in row["summary"] for row in updates if row["id"] == claim["msg_id"])
    assert any("next run" in row["summary"] for row in updates if row["id"] == reconciliation["msg_id"])
    assert live._human_answer(question, rows) is None


def test_contest_requires_structured_evidence_and_never_makes_a_claim_terminal(repo):
    path = _plan(repo, "2026-09-23.json", [_item("d5", "owner_decision")])
    box = Box(repo)
    box.post("oracle", "note", {
        "title": "PLAN READY: 2026-09-23",
        "ref": {"path": path.relative_to(repo).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
    })
    question = box.post("claude", "question", {"title": "Item d5", "ref": {"item": "d5"}}, to="owner")
    resolution = box.post("claude", "question_resolution", {
        "disposition": "superseded", "summary": "Already done.", "reason": "Rechecked.",
    }, to="owner", reply=question["msg_id"])

    fake_a = box.post("oracle", "note", {"title": "Claim", "text": "I posted it."})
    fake_b = box.post("oracle", "note", {"title": "Claim again", "text": "Trust me."})
    box.post("codex", "note", {
        "title": "Unsubstantiated contest", "text": "Actor labels remain unauthenticated.",
        "provenance_contestation": {
            "contested_msg_id": resolution["msg_id"], "claimed_actor": "claude",
            "reported_actual_actor": "oracle", "basis_msg_ids": [fake_a["msg_id"], fake_b["msg_id"]],
            "effect": "invalidate_for_projection",
        },
    }, reply=resolution["msg_id"])
    assert _summary(repo)["work_items"][0]["status"] == "waiting_on_you"

    _first, _second, contest = _contest(box, resolution)
    duplicate = box.post("codex", "note", contest["body"], reply=resolution["msg_id"])
    value = _summary(repo)
    assert value["work_items"][0]["status"] == "waiting_on_you"
    updates = [row for row in value["question_updates"] if row["question_id"] == question["msg_id"]]
    assert len(updates) == 1 and updates[0]["id"] == duplicate["msg_id"]

    fresh = box.post("claude", "question_resolution", {
        "disposition": "informational", "summary": "Fresh independent recheck.",
        "reason": "The original asker verified it after the contest.",
    }, to="owner", reply=question["msg_id"])
    value = _summary(repo)
    assert value["work_items"][0]["status"] == "waiting_on_you"
    updates = [row for row in value["question_updates"] if row["question_id"] == question["msg_id"]]
    assert {row["id"] for row in updates} == {duplicate["msg_id"], fresh["msg_id"]}

    second_question = box.post("claude", "question", {"title": "A second choice"}, to="owner")
    second_resolution = box.post("claude", "question_resolution", {
        "disposition": "superseded", "summary": "Already done.", "reason": "Rechecked.",
    }, to="owner", reply=second_question["msg_id"])
    _contest(box, second_resolution)
    later_claim = box.post("human:derrick", "answer", {"text": "Use the safe path."}, to="claude",
                           reply=second_question["msg_id"])
    value = _summary(repo)
    assert second_question["msg_id"] in {card["msg_id"] for card in value["waiting_on_you"]}
    later_updates = [row for row in value["question_updates"]
                     if row["question_id"] == second_question["msg_id"]]
    assert any(row["id"] == later_claim["msg_id"] and row["disposition"] == "contested"
               and "Use the safe path." in row["summary"] for row in later_updates)


def test_malformed_contest_schema_is_rejected(repo):
    box = Box(repo)
    question = box.post("claude", "question", {"title": "Choice"}, to="owner")
    resolution = box.post("claude", "question_resolution", {
        "disposition": "superseded", "summary": "Done.", "reason": "Checked.",
    }, to="owner", reply=question["msg_id"])
    with pytest.raises(oracle_mailbox.MailboxError, match="provenance_contestation"):
        box.post("codex", "note", {"provenance_contestation": {
            "contested_msg_id": resolution["msg_id"], "claimed_actor": "claude",
            "reported_actual_actor": "oracle", "basis_msg_ids": [],
            "effect": "invalidate_for_projection",
        }}, reply=resolution["msg_id"])


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
    assert live.validate_agents(value["agents"])
    live.validate_live(value, live.validate_agents)
