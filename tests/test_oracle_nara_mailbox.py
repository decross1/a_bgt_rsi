"""Oracle <-> Nara mailbox and Nara's implementor lane (D-082); no model calls."""
import hashlib
import json
import multiprocessing
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from orchestrator import nara_lane as lane
from orchestrator import oracle_mailbox as mailbox


def _append_unchecked_mailbox_row(path, row, *, generate_msg_id=True):
    """Append hash-valid evidence without invoking the current writer schema."""
    existing = mailbox.read(path)
    unchecked = dict(row)
    unchecked["prev_sha256"] = existing[-1]["row_sha256"] if existing else None
    if generate_msg_id:
        actor = unchecked["actor"]
        unchecked["msg_id"] = (
            f"{actor.split(':')[0]}-{hashlib.sha256(mailbox._canonical(unchecked)).hexdigest()[:16]}"
        )
    unchecked["row_sha256"] = hashlib.sha256(mailbox._canonical(unchecked)).hexdigest()
    with path.open("a") as handle:
        handle.write(json.dumps(unchecked) + "\n")
    return unchecked


def _post_once_process(path_text, question_id, request_id, decision, gate, results):
    """Independent writer process used to exercise the real fcntl boundary."""
    try:
        if not gate.wait(10):
            results.put(("error", "Timeout", "start gate did not open"))
            return
        row, duplicate = mailbox.post_once(
            "human:derrick", "answer",
            {"text": decision, "decision": decision, "request_id": request_id},
            to="oracle", in_reply_to=question_id, idempotency_key=request_id,
            require_open_question=True, path=Path(path_text),
        )
        results.put(("ok", duplicate, row["msg_id"]))
    except Exception as exc:  # result is asserted in the parent process
        results.put(("error", type(exc).__name__, str(exc)))


def _race_post_once(path, question_id, requests):
    context = multiprocessing.get_context("spawn")
    gate, results = context.Event(), context.Queue()
    processes = [context.Process(
        target=_post_once_process,
        args=(str(path), question_id, request_id, decision, gate, results),
    ) for request_id, decision in requests]
    for process in processes:
        process.start()
    gate.set()
    for process in processes:
        process.join(15)
        assert not process.is_alive(), "concurrent mailbox writer did not finish"
        assert process.exitcode == 0
    return [results.get(timeout=5) for _ in processes]


def _terminal_process(path_text, question_id, terminal, gate, results):
    """Race an owner answer against the asker's non-answer resolution."""
    try:
        if not gate.wait(10):
            results.put(("error", "Timeout", "start gate did not open"))
            return
        if terminal == "answer":
            row, _duplicate = mailbox.post_once(
                "human:derrick", "answer",
                {"text": "approve", "decision": "approve", "request_id": "race-answer"},
                to="oracle", in_reply_to=question_id, idempotency_key="race-answer",
                require_open_question=True, path=Path(path_text),
            )
        else:
            row = mailbox.post(
                "oracle", "question_resolution",
                {"disposition": "withdrawn", "summary": "No action remains.",
                 "reason": "The premise was superseded."},
                to="owner", in_reply_to=question_id, path=Path(path_text),
            )
        results.put(("ok", terminal, row["msg_id"]))
    except Exception as exc:  # result is asserted in the parent process
        results.put(("error", type(exc).__name__, str(exc)))


def _race_terminals(path, question_id):
    context = multiprocessing.get_context("spawn")
    gate, results = context.Event(), context.Queue()
    processes = [context.Process(
        target=_terminal_process, args=(str(path), question_id, terminal, gate, results),
    ) for terminal in ("answer", "resolution")]
    for process in processes:
        process.start()
    gate.set()
    for process in processes:
        process.join(15)
        assert not process.is_alive(), "concurrent terminal writer did not finish"
        assert process.exitcode == 0
    return [results.get(timeout=5) for _ in processes]


def _plan_ready_repo(tmp_path, *, revision="r1"):
    """A real committed repo: publisher tests must distinguish Git objects from files."""
    repo = tmp_path / "plan-repo"
    repo.mkdir()

    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True, text=True,
                              stdout=subprocess.PIPE).stdout.strip()

    git("init", "-b", "main")
    git("config", "user.name", "Mailbox test")
    git("config", "user.email", "mailbox@example.test")
    packet_path = "notes/ops/2026-09-25/STATE_PACKET.md"
    plan_path = f"run_state/daily_plans/2026-09-25-{revision}.json"
    packet = b"committed packet v1\n"
    packet_file = repo / packet_path
    packet_file.parent.mkdir(parents=True)
    packet_file.write_bytes(packet)
    plan_file = repo / plan_path
    plan_file.parent.mkdir(parents=True)
    plan = {
        "date": "2026-09-25", "revision": revision,
        "state_packet_sha256": hashlib.sha256(packet).hexdigest(),
    }
    plan_file.write_text(json.dumps(plan, sort_keys=True) + "\n")
    git("add", ".")
    git("commit", "-m", "committed plan")
    return repo, git("rev-parse", "HEAD"), plan_path, packet_path, plan_file, packet_file, git


def _publish(repo, head, plan_path, packet_path, *, mailbox_path):
    plan_bytes = subprocess.run(["git", "-C", str(repo), "show", f"{head}:{plan_path}"], check=True,
                                stdout=subprocess.PIPE).stdout
    packet_bytes = subprocess.run(["git", "-C", str(repo), "show", f"{head}:{packet_path}"], check=True,
                                  stdout=subprocess.PIPE).stdout
    return mailbox.publish_plan_ready(
        branch="main", head_sha=head, plan_path=plan_path,
        plan_sha256=hashlib.sha256(plan_bytes).hexdigest(),
        state_packet_path=packet_path, state_packet_sha256=hashlib.sha256(packet_bytes).hexdigest(),
        repo_root=repo, path=mailbox_path,
    )


def _publish_args(repo, head, plan_path, packet_path, *, mailbox_path):
    plan_bytes = subprocess.run(["git", "-C", str(repo), "show", f"{head}:{plan_path}"], check=True,
                                stdout=subprocess.PIPE).stdout
    packet_bytes = subprocess.run(["git", "-C", str(repo), "show", f"{head}:{packet_path}"], check=True,
                                  stdout=subprocess.PIPE).stdout
    return {
        "branch": "main", "head_sha": head, "plan_path": plan_path,
        "plan_sha256": hashlib.sha256(plan_bytes).hexdigest(),
        "state_packet_path": packet_path, "state_packet_sha256": hashlib.sha256(packet_bytes).hexdigest(),
        "repo_root": repo, "path": mailbox_path,
    }


def _plan(**over):
    body = {
        "title": "Add a slugify helper", "objective": "Create tools/slug.py with slugify(text).",
        "task_class": "tooling", "allowed_write_paths": ["tools/slug.py"],
        "acceptance": {"test_path": "tests/test_slug.py",
                       "test_content": "from tools.slug import slugify\n\ndef test_slug():\n    assert slugify('A b') == 'a-b'\n",
                       "test_argv": ["python", "-m", "pytest", "-q", "tests/test_slug.py"]},
        "budget": {"attempts": 2, "wall_clock_minutes": 5},
    }
    body.update(over)
    return body


def test_post_read_fold_and_chain(tmp_path):
    path = tmp_path / "mb.jsonl"
    item = mailbox.post("oracle", "plan_item", _plan(), to="nara", path=path)
    mailbox.post("nara", "receipt", {"state": "claimed"}, to="oracle", in_reply_to=item["msg_id"], path=path)
    mailbox.post("nara", "receipt", {"state": "validated", "branch": "nara/x"}, to="oracle",
                 in_reply_to=item["msg_id"], path=path)
    mailbox.post("nara", "receipt", {"state": "failed"}, to="oracle", in_reply_to=item["msg_id"], path=path)
    view = mailbox.fold(mailbox.read(path))
    assert view[item["msg_id"]]["state"] == "validated"  # terminal states stick
    lines = path.read_text().splitlines()
    tampered = json.loads(lines[1])
    tampered["body"]["state"] = "validated"
    path.write_text("\n".join([lines[0], json.dumps(tampered), *lines[2:]]) + "\n")
    with pytest.raises(mailbox.MailboxError, match="chain broken"):
        mailbox.read(path)


def test_post_if_reads_and_appends_under_one_mailbox_lock(tmp_path):
    path = tmp_path / "mb.jsonl"
    seen = []

    row = mailbox.post_if(
        "oracle", "note", {"text": "conditional"}, to="all", path=path,
        condition=lambda rows: (seen.append(list(rows)) or True),
    )
    assert row is not None and seen == [[]]
    skipped = mailbox.post_if(
        "oracle", "note", {"text": "must not appear"}, to="all", path=path,
        condition=lambda rows: len(rows) > 1,
    )
    assert skipped is None and mailbox.read(path) == [row]


def test_post_if_predicate_cannot_mutate_the_verified_prefix_used_for_append(tmp_path):
    path = tmp_path / "mb.jsonl"
    first = mailbox.post("oracle", "note", {"text": "first"}, to="all", path=path)

    def mutate_prefix(rows):
        rows[-1]["row_sha256"] = "0" * 64
        rows[-1]["body"]["text"] = "rewritten in callback"
        return True

    second = mailbox.post_if("oracle", "note", {"text": "second"}, to="all", path=path,
                             condition=mutate_prefix)

    assert second is not None and second["prev_sha256"] == first["row_sha256"]
    assert mailbox.read(path) == [first, second]


@pytest.mark.parametrize(("body", "expected"), [
    ({"title": "Title", "question": "Question", "summary": "Summary", "state": "held", "verdict": "amend", "text": "Text"}, "Title"),
    ({"title": 7, "question": "Question", "summary": "Summary", "state": "held", "verdict": "amend", "text": "Text"}, "Question"),
    ({"summary": "Summary", "state": "held", "verdict": "amend", "text": "Text"}, "Summary"),
    ({"state": "held", "verdict": "amend", "text": "Text"}, "held"),
    ({"verdict": "amend", "text": "Text"}, "amend"),
    ({"text": "x" * 81}, "x" * 80),
])
def test_list_summary_fallback_order(monkeypatch, capsys, body, expected):
    """Question-only and summary-only mailbox rows remain legible in ``list``."""
    row = {
        "seq": 1, "msg_id": "oracle-list-summary", "actor": "oracle", "to": "owner",
        "kind": "question", "in_reply_to": None, "body": body,
    }
    monkeypatch.setattr(mailbox, "read", lambda: [row])

    assert mailbox.main(["list"]) == 0
    assert json.loads(capsys.readouterr().out)["summary"] == expected


def test_actor_and_shape_rules(tmp_path):
    path = tmp_path / "mb.jsonl"
    with pytest.raises(mailbox.MailboxError, match="may not post"):
        mailbox.post("nara", "plan_item", _plan(), to="nara", path=path)
    with pytest.raises(mailbox.MailboxError, match="may not post"):
        mailbox.post("oracle", "receipt", {"state": "validated"}, to="nara", in_reply_to="x", path=path)
    with pytest.raises(mailbox.MailboxError, match="task_class"):
        mailbox.post("oracle", "plan_item", _plan(task_class="registration"), to="nara", path=path)
    with pytest.raises(mailbox.MailboxError, match="must reply"):
        mailbox.post("nara", "receipt", {"state": "claimed"}, to="oracle", path=path)
    with pytest.raises(mailbox.MailboxError, match="exceeds"):
        mailbox.post("oracle", "note", {"text": "x" * 20000}, to="nara", path=path)
    for actor in ("claude", "codex", "human:derrick"):
        with pytest.raises(mailbox.MailboxError, match="may not post"):
            mailbox.post(actor, "plan_item", _plan(), to="nara", path=path)  # Oracle plans
    with pytest.raises(mailbox.MailboxError, match="may not post"):
        mailbox.post("claude", "receipt", {"state": "validated"}, to="all", in_reply_to="x", path=path)
    with pytest.raises(mailbox.MailboxError, match="to must be"):
        mailbox.post("claude", "note", {"text": "hi"}, to="everyone", path=path)
    mailbox.post("claude", "note", {"text": "shared state"}, to="all", path=path)
    mailbox.post("human:derrick", "question", {"text": "status?"}, to="all", path=path)
    question = mailbox.post("nara", "question", {"text": "Which schema?"}, to="oracle", path=path)
    mailbox.post("oracle", "answer", {"text": "v2"}, to="nara", in_reply_to=question["msg_id"], path=path)


def test_question_resolution_is_explicit_and_preserves_question_provenance(tmp_path):
    path = tmp_path / "mb.jsonl"
    question = mailbox.post("oracle", "question", {"question": "Install the timer?"},
                            to="owner", path=path)
    withdrawn = mailbox.post("oracle", "question_resolution", {
        "disposition": "withdrawn", "summary": "No action is needed.",
        "reason": "The timer question was based on a mistaken premise.",
    }, to="owner", in_reply_to=question["msg_id"], path=path)
    assert withdrawn["in_reply_to"] == question["msg_id"]

    # A reviewer may annotate with a normal note, but cannot hide a question.
    with pytest.raises(mailbox.MailboxError, match="question asker or a human"):
        mailbox.post("claude", "question_resolution", {
            "disposition": "withdrawn", "summary": "No action.", "reason": "review",
            "evidence_msg_ids": [question["msg_id"]],
        }, to="owner", in_reply_to=question["msg_id"], path=path)
    with pytest.raises(mailbox.MailboxError, match="preceding mailbox rows"):
        mailbox.post("oracle", "question_resolution", {
            "disposition": "withdrawn", "summary": "No action.", "reason": "review",
            "evidence_msg_ids": ["oracle-not-yet-posted"],
        }, to="owner", in_reply_to=question["msg_id"], path=path)
    with pytest.raises(mailbox.MailboxError, match="question asker or a human"):
        mailbox.post("nara", "question_resolution", {
            "disposition": "withdrawn", "summary": "No action.", "reason": "not my question",
        }, to="owner", in_reply_to=question["msg_id"], path=path)
    with pytest.raises(mailbox.MailboxError, match="must reply to a question"):
        mailbox.post("oracle", "question_resolution", {
            "disposition": "withdrawn", "summary": "No action.", "reason": "wrong parent",
        }, to="owner", in_reply_to=withdrawn["msg_id"], path=path)


def test_question_dispositions_are_single_winner_and_contest_reopens(tmp_path):
    path = tmp_path / "mb.jsonl"
    answered = mailbox.post("oracle", "question", {"question": "Proceed?"}, to="owner", path=path)
    mailbox.post("human:derrick", "answer", {"text": "yes"}, to="oracle",
                 in_reply_to=answered["msg_id"], path=path)
    # A `human:*` label is unauthenticated evidence, not a terminal owner
    # ruling.  The original asker may still publish a non-owner disposition.
    mailbox.post("oracle", "question_resolution", {
        "disposition": "withdrawn", "summary": "No action.", "reason": "Too late.",
    }, to="owner", in_reply_to=answered["msg_id"], path=path)

    resolved = mailbox.post("oracle", "question", {"question": "Still proceed?"}, to="owner", path=path)
    resolution = mailbox.post("oracle", "question_resolution", {
        "disposition": "withdrawn", "summary": "No action.", "reason": "Superseded.",
    }, to="owner", in_reply_to=resolved["msg_id"], path=path)
    with pytest.raises(mailbox.MailboxError, match="no longer open"):
        mailbox.post("oracle", "question_resolution", {
            "disposition": "informational", "summary": "A second terminal.", "reason": "Too late.",
        }, to="owner", in_reply_to=resolved["msg_id"], path=path)
    with pytest.raises(mailbox.MailboxError, match="no longer open"):
        mailbox.post("human:derrick", "answer", {"text": "yes"}, to="oracle",
                     in_reply_to=resolved["msg_id"], path=path)

    first = mailbox.post("nara", "note", {
        "title": "Self-report", "text": "Wrong actor label.",
        "ref": {"posted_row": f"{resolution['msg_id']} (seq {resolution['seq']})",
                "command": "oracle_mailbox post --as oracle"},
    }, to="all", path=path)
    second = mailbox.post("nara", "note", {
        "title": "Second self-report", "text": "The row was mine.",
        "ref": {"self_reported_fault":
                f"seq {resolution['seq']} posted with --as oracle by this session"},
    }, to="all", path=path)
    mailbox.post("codex", "note", {
        "title": "Contest attribution", "text": "Preserve the row but reopen the question.",
        "provenance_contestation": {
            "contested_msg_id": resolution["msg_id"], "claimed_actor": "oracle",
            "reported_actual_actor": "nara", "basis_msg_ids": [first["msg_id"], second["msg_id"]],
            "effect": "invalidate_for_projection",
        },
    }, to="all", in_reply_to=resolution["msg_id"], path=path)
    # A contest is conservative invalidation, never actor authentication: once
    # the old disposition is distrusted, a fresh answer claim may be appended.
    mailbox.post("human:derrick", "answer", {"text": "yes"}, to="oracle",
                 in_reply_to=resolved["msg_id"], path=path)
    assert mailbox.read(path)[-1]["kind"] == "answer"


def test_answer_claim_and_resolution_race_keeps_only_the_disposition_terminal(tmp_path):
    path = tmp_path / "mb.jsonl"
    question = mailbox.post("oracle", "question", {"question": "Proceed?"}, to="owner", path=path)
    outcomes = _race_terminals(path, question["msg_id"])

    # If the disposition wins the lock first, it closes before the answer
    # claim can be recorded; if the answer arrives first it remains
    # non-terminal and the disposition still succeeds.
    assert len([result for result in outcomes if result[0] == "ok" and result[1] == "resolution"]) == 1
    rows = mailbox.read(path)
    assert rows[-1]["kind"] == "question_resolution"
    assert len(rows) in {2, 3}


def test_post_once_is_idempotent_and_owner_answer_claims_do_not_close_a_question(tmp_path):
    path = tmp_path / "mb.jsonl"
    question = mailbox.post("oracle", "question", {"question": "Proceed?"}, to="owner", path=path)
    mailbox.post("claude", "answer", {"text": "relayed"}, to="oracle",
                 in_reply_to=question["msg_id"], path=path)
    body = {"text": "approve", "decision": "approve", "request_id": "req-1"}
    answer, duplicate = mailbox.post_once(
        "human:derrick", "answer", body, to="oracle", in_reply_to=question["msg_id"],
        idempotency_key="req-1", require_open_question=True, path=path)
    assert duplicate is False and answer["kind"] == "answer"
    retry, duplicate = mailbox.post_once(
        "human:derrick", "answer", body, to="oracle", in_reply_to=question["msg_id"],
        idempotency_key="req-1", require_open_question=True, path=path)
    assert duplicate is True and retry == answer
    with pytest.raises(mailbox.MailboxError, match="different request"):
        mailbox.post_once(
            "human:derrick", "answer", {**body, "text": "decline"}, to="oracle",
            in_reply_to=question["msg_id"], idempotency_key="req-1",
            require_open_question=True, path=path)
    later, duplicate = mailbox.post_once(
        "human:not_the_owner", "answer", {"text": "again", "request_id": "req-2"}, to="oracle",
        in_reply_to=question["msg_id"], idempotency_key="req-2",
        require_open_question=True, path=path)
    assert duplicate is False and later["actor"] == "human:not_the_owner"
    assert mailbox.is_question_closed(question, mailbox.read(path)) is False


def test_post_once_requires_body_request_id_to_match_idempotency_key(tmp_path):
    path = tmp_path / "mb.jsonl"
    question = mailbox.post("oracle", "question", {"question": "Proceed?"}, to="owner", path=path)
    with pytest.raises(mailbox.MailboxError, match="body.request_id"):
        mailbox.post_once(
            "human:derrick", "answer", {"text": "approve", "request_id": "different"},
            to="oracle", in_reply_to=question["msg_id"], idempotency_key="expected",
            require_open_question=True, path=path)
    assert mailbox.read(path) == [question]


def test_forged_human_actor_claim_never_closes_an_owner_question(tmp_path):
    """The public writer can self-assert any human label; projection fails closed."""
    path = tmp_path / "mb.jsonl"
    question = mailbox.post("oracle", "question", {"question": "Proceed?"}, to="owner", path=path)
    forged = mailbox.post("human:not_the_owner", "answer", {"text": "approve"}, to="oracle",
                          in_reply_to=question["msg_id"], path=path)
    asserted_resolution = mailbox.post("human:not_the_owner", "question_resolution", {
        "disposition": "superseded", "summary": "Claimed complete.", "reason": "Untrusted claim.",
    }, to="owner", in_reply_to=question["msg_id"], path=path)

    rows = mailbox.read(path)
    assert forged in mailbox.live_rows(rows) and asserted_resolution in mailbox.live_rows(rows)
    assert mailbox.is_question_closed(question, rows) is False


def test_post_once_never_returns_a_receipt_before_file_and_directory_sync(tmp_path, monkeypatch):
    """Short writes and sync failures are uncertainty, not durable acceptance."""
    path = tmp_path / "mb.jsonl"
    question = mailbox.post("oracle", "question", {"question": "Proceed?"}, to="owner", path=path)
    complete_prefix = path.read_bytes()
    body = {"text": "context", "request_id": "sync-request"}
    real_open = Path.open

    class ShortWrite:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def __enter__(self):
            self.wrapped.__enter__()
            return self

        def __exit__(self, *args):
            return self.wrapped.__exit__(*args)

        def write(self, payload):
            written = len(payload) // 2
            assert self.wrapped.write(payload[:written]) == written
            return written

        def fileno(self):
            return self.wrapped.fileno()

        def tell(self):
            return self.wrapped.tell()

        def truncate(self, offset):
            return self.wrapped.truncate(offset)

    def short_open(self, mode="r", *args, **kwargs):
        if self == path and mode == "ab":
            return ShortWrite(real_open(self, mode, *args, **kwargs))
        return real_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", short_open)
    with pytest.raises(mailbox.MailboxError, match="short and rolled back"):
        mailbox.post_once("human:derrick", "answer", body, to="oracle", in_reply_to=question["msg_id"],
                          idempotency_key="sync-request", require_open_question=True, path=path)
    assert path.read_bytes() == complete_prefix
    monkeypatch.setattr(Path, "open", real_open)
    retry, duplicate = mailbox.post_once("human:derrick", "answer", body, to="oracle",
                                         in_reply_to=question["msg_id"], idempotency_key="sync-request",
                                         require_open_question=True, path=path)
    assert duplicate is False and retry["body"] == body

    real_fsync = mailbox.os.fsync
    fsync_body = {"text": "context", "request_id": "fsync-request"}
    monkeypatch.setattr(mailbox.os, "fsync", lambda _fd: (_ for _ in ()).throw(OSError("sync fault")))
    with pytest.raises(mailbox.MailboxError, match="durability is unconfirmed"):
        mailbox.post_once("human:derrick", "answer", fsync_body, to="oracle", in_reply_to=question["msg_id"],
                          idempotency_key="fsync-request", require_open_question=True, path=path)
    # A row may be visible after an interrupted durability boundary, but it is
    # not a success receipt until a retry synchronizes both file and directory.
    monkeypatch.setattr(mailbox.os, "fsync", real_fsync)
    row, duplicate = mailbox.post_once("human:derrick", "answer", fsync_body, to="oracle",
                                       in_reply_to=question["msg_id"], idempotency_key="fsync-request",
                                       require_open_question=True, path=path)
    assert duplicate is True and row["body"] == fsync_body


def test_retry_repairs_only_a_verified_unterminated_torn_tail(tmp_path):
    path = tmp_path / "mb.jsonl"
    question = mailbox.post("oracle", "question", {"question": "Proceed?"}, to="owner", path=path)
    prefix = path.read_bytes()
    with path.open("ab", buffering=0) as handle:
        handle.write(b'{"schema":"oracle-nara-mailbox/v1"')

    # Public reads remain honest about the broken tail; the next writer holds
    # the lock, verifies the completed prefix, repairs only the unterminated
    # fragment, and makes the repair durable before it appends.
    with pytest.raises(mailbox.MailboxError, match="not JSON"):
        mailbox.read(path)
    note = mailbox.post("oracle", "note", {"text": "after recovery"}, to="owner", path=path)
    rows = mailbox.read(path)
    assert rows == [question, note]
    assert path.read_bytes().startswith(prefix)


def test_retry_preserves_a_complete_valid_final_row_when_only_newline_is_lost(tmp_path):
    path = tmp_path / "mb.jsonl"
    first = mailbox.post("oracle", "note", {"text": "first"}, to="owner", path=path)
    second = mailbox.post("oracle", "note", {"text": "second"}, to="owner", path=path)
    path.write_bytes(path.read_bytes()[:-1])  # crash after the row, before its newline

    # Read semantics already admit the complete chain. The next locked writer
    # must preserve that row, restore its delimiter durably, and link after it.
    assert mailbox.read(path) == [first, second]
    third = mailbox.post("oracle", "note", {"text": "third"}, to="owner", path=path)
    assert mailbox.read(path) == [first, second, third]
    assert third["prev_sha256"] == second["row_sha256"]
    assert path.read_bytes().endswith(b"\n")


def test_cross_process_same_request_appends_once_and_returns_one_duplicate(tmp_path):
    path = tmp_path / "mb.jsonl"
    question = mailbox.post("oracle", "question", {"question": "Proceed?"}, to="owner", path=path)
    outcomes = _race_post_once(path, question["msg_id"], [
        ("same-request", "approve"), ("same-request", "approve"),
    ])

    assert sorted((result[0], result[1]) for result in outcomes) == [("ok", False), ("ok", True)]
    assert len({result[2] for result in outcomes}) == 1
    rows = mailbox.read(path)  # also verifies the complete hash chain
    assert len(rows) == 2 and rows[-1]["body"]["request_id"] == "same-request"


def test_cross_process_distinct_answer_claims_remain_nonterminal_and_keep_chain_valid(tmp_path):
    path = tmp_path / "mb.jsonl"
    question = mailbox.post("oracle", "question", {"question": "Proceed?"}, to="owner", path=path)
    outcomes = _race_post_once(path, question["msg_id"], [
        ("request-approve", "approve"), ("request-decline", "decline"),
    ])

    assert len([result for result in outcomes if result[:2] == ("ok", False)]) == 2
    rows = mailbox.read(path)
    assert len(rows) == 3
    assert {row["body"]["request_id"] for row in rows[1:]} == {"request-approve", "request-decline"}
    assert mailbox.is_question_closed(question, rows) is False


def test_post_once_does_not_close_on_a_forged_question_resolution(tmp_path):
    """The write-side open check shares projection's resolution predicate."""
    path = tmp_path / "mb.jsonl"
    question = mailbox.post("oracle", "question", {"question": "Proceed?"}, to="owner", path=path)
    _append_unchecked_mailbox_row(path, {
        "schema": mailbox.SCHEMA, "seq": 2, "ts": "2026-09-25T00:00:01+00:00",
        "actor": "claude", "to": "owner", "kind": "question_resolution",
        "in_reply_to": question["msg_id"],
        "body": {"disposition": "withdrawn", "summary": "No action.", "reason": "review"},
        "expires_at": None,
    })
    row, duplicate = mailbox.post_once(
        "human:derrick", "answer", {"text": "Proceed", "request_id": "req-1"}, to="oracle",
        in_reply_to=question["msg_id"], idempotency_key="req-1", require_open_question=True, path=path)
    assert row["kind"] == "answer"
    assert duplicate is False


@pytest.mark.parametrize(("poison_schema", "forced_msg_id", "reason"), [
    ("oracle-nara-mailbox/v999", None, "schema"),
    (mailbox.SCHEMA, "human-not-writer-derived", "msg_id"),
])
def test_malformed_owner_answer_is_quarantined_from_retry_and_closed_state(
        tmp_path, poison_schema, forced_msg_id, reason):
    """Hash validity alone cannot consume an owner request id or close its card."""
    path = tmp_path / "mb.jsonl"
    question = mailbox.post("oracle", "question", {"question": "Proceed?"}, to="owner", path=path)
    body = {
        "text": "Proceed", "via": "owner-ui", "authority": "owner, D-084",
        "request_id": "11111111-1111-1111-1111-111111111111", "target_kind": "question",
        "expected_plan_revision": "2026-09-25",
    }
    poison = {
        "schema": poison_schema, "seq": 2, "ts": "2026-09-25T00:00:01+00:00",
        "actor": "human:derrick", "to": "oracle", "kind": "answer",
        "in_reply_to": question["msg_id"], "body": body, "expires_at": None,
    }
    if forced_msg_id is not None:
        poison["msg_id"] = forced_msg_id
    malformed = _append_unchecked_mailbox_row(
        path, poison, generate_msg_id=forced_msg_id is None,
    )

    rows = mailbox.read(path)
    assert mailbox.quarantine(rows) == [{
        "position": 2, "seq": 2, "msg_id": malformed["msg_id"], "reason": reason,
    }]
    assert malformed not in mailbox.live_rows(rows)
    assert mailbox.find_idempotency_key(body["request_id"], path=path) is None
    assert mailbox.is_question_closed(question, rows) is False

    answer, duplicate = mailbox.post_once(
        "human:derrick", "answer", body, to="oracle", in_reply_to=question["msg_id"],
        idempotency_key=body["request_id"], require_open_question=True, path=path,
    )
    assert duplicate is False and answer["schema"] == mailbox.SCHEMA
    assert mailbox.find_idempotency_key(body["request_id"], path=path) == answer
    assert mailbox.is_question_closed(question, mailbox.read(path)) is False


@pytest.mark.parametrize(("poison_schema", "forced_msg_id"), [
    ("oracle-nara-mailbox/v999", None),
    (mailbox.SCHEMA, "human-not-writer-derived"),
])
def test_malformed_owner_answer_does_not_block_a_fresh_request(tmp_path, poison_schema, forced_msg_id):
    path = tmp_path / "mb.jsonl"
    question = mailbox.post("oracle", "question", {"question": "Proceed?"}, to="owner", path=path)
    poison = {
        "schema": poison_schema, "seq": 2, "ts": "2026-09-25T00:00:01+00:00",
        "actor": "human:derrick", "to": "oracle", "kind": "answer",
        "in_reply_to": question["msg_id"],
        "body": {
            "text": "forged", "via": "owner-ui", "authority": "owner, D-084",
            "request_id": "22222222-2222-2222-2222-222222222222", "target_kind": "question",
            "expected_plan_revision": "2026-09-25",
        },
        "expires_at": None,
    }
    if forced_msg_id is not None:
        poison["msg_id"] = forced_msg_id
    _append_unchecked_mailbox_row(path, poison, generate_msg_id=forced_msg_id is None)
    body = {"text": "Proceed", "request_id": "fresh-request"}
    answer, duplicate = mailbox.post_once(
        "human:derrick", "answer", body, to="oracle", in_reply_to=question["msg_id"],
        idempotency_key="fresh-request", require_open_question=True, path=path,
    )
    assert duplicate is False and answer["body"] == body


def test_admission_fence(monkeypatch):
    _stub_the_precheck_gate(monkeypatch)
    assert lane.admission({"actor": "oracle", "body": _plan()}) == []
    bad = _plan(allowed_write_paths=["orchestrator/nara_lane.py", "tests/conftest.py", "docs/../CLAUDE.md",
                                     "experiments/x/PREREGISTRATION.md", "tools/*.py", "bench/flash_x.py"])
    reasons = lane.admission({"actor": "oracle", "body": bad})
    assert len([r for r in reasons if r.startswith("path outside")]) == 6
    shell = _plan(acceptance={**_plan()["acceptance"], "test_argv": ["bash", "-c", "rm -rf /"]})
    assert any("test_argv" in r for r in lane.admission({"actor": "oracle", "body": shell}))
    assert any("oracle" in r for r in lane.admission({"actor": "human:x", "body": _plan()}))
    extra = _plan(acceptance={**_plan()["acceptance"],  # the JUnit verdict must name Oracle's own module
                              "test_argv": ["python", "-m", "pytest", "-q", "tests/test_other.py", "tests/test_slug.py"]})
    assert any("no other test file" in r for r in lane.admission({"actor": "oracle", "body": extra}))


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "tools").mkdir(parents=True)
    (root / "tools/__init__.py").write_text("")
    (root / "run_state").mkdir()
    (root / "config").mkdir()
    (root / "config/nara_lane.json").write_text('{"require_meta_review": false}')  # gate tested separately
    for cmd in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"]):
        subprocess.run(["git", *cmd], cwd=root, check=True)
    monkeypatch.setattr(lane, "ROOT", root)
    monkeypatch.setattr(lane, "WORKTREES", tmp_path / "wt")
    monkeypatch.setattr(lane, "RUN_LOG", tmp_path / "run.jsonl")
    _stub_the_precheck_gate(monkeypatch)
    return root


def _stub_the_precheck_gate(monkeypatch) -> None:
    """Switch off the precheck-receipt gate (plan 2026-09-23 d1), which is tested
    in tests/test_nara_lane_precheck.py. These lane tests predate it and post
    plan items without receipts; every other admission rule still runs."""
    monkeypatch.setattr(lane, "_prechecked", lambda _acceptance: True)


def _fake_sandbox(worktree, argv, timeout=0):
    done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *argv[4:]],
                          cwd=worktree, capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(worktree),
                               "PYTHONDONTWRITEBYTECODE": "1"})  # as the real sandbox sets
    return done.returncode, done.stdout + done.stderr


def _good_builder(body, worktree, feedback, timeout=0):
    return {"tools/slug.py": "def slugify(text):\n    return '-'.join(text.lower().split())\n"}


def test_lane_validates_red_first_item_on_its_own_branch(repo):
    path = repo / "run_state/mb.jsonl"
    item = mailbox.post("oracle", "plan_item", _plan(), to="nara", path=path)
    posted = lane.run_queue(path, build=_good_builder, sandbox=_fake_sandbox, ready=lambda: True)
    states = [r["body"]["state"] for r in posted]
    assert states == ["claimed", "validated"]
    final = posted[-1]["body"]
    assert final["branch"] == f"nara/{item['msg_id']}" and final["changed_files"] == ["tests/test_slug.py", "tools/slug.py"]
    log = subprocess.run(["git", "log", "--format=%an", "-1", final["branch"]], cwd=repo, capture_output=True, text=True)
    assert log.stdout.strip() == "Nara (lab lane)"
    main = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo, capture_output=True, text=True)
    assert not (repo / "tools/slug.py").exists() and main.stdout.strip() in {"master", "main"}  # never merged
    assert lane.run_queue(path, build=_good_builder, sandbox=_fake_sandbox, ready=lambda: True) == []


def test_review_kind_rules(tmp_path):
    path = tmp_path / "mb.jsonl"
    item = mailbox.post("oracle", "plan_item", _plan(), to="nara", path=path)
    for actor in ("oracle", "nara", "human:derrick"):
        with pytest.raises(mailbox.MailboxError, match="may not post"):
            mailbox.post(actor, "review", {"verdict": "accept"}, to="nara", in_reply_to=item["msg_id"], path=path)
    with pytest.raises(mailbox.MailboxError, match="verdict"):
        mailbox.post("claude", "review", {"verdict": "fine"}, to="nara", in_reply_to=item["msg_id"], path=path)
    with pytest.raises(mailbox.MailboxError, match="must reply"):
        mailbox.post("claude", "review", {"verdict": "accept"}, to="nara", path=path)
    mailbox.post("claude", "review", {"verdict": "accept"}, to="nara", in_reply_to=item["msg_id"], path=path)
    assert mailbox.fold(mailbox.read(path))[item["msg_id"]]["state"] == "open"  # a review is not a receipt


def test_lane_waits_for_the_meta_oracle_and_honors_its_verdict(repo):
    path = repo / "run_state/mb.jsonl"
    policy = repo / "config/nara_lane.json"
    policy.write_text('{"require_meta_review": true}')
    run = lambda: lane.run_queue(path, build=_good_builder, sandbox=_fake_sandbox, ready=lambda: True)
    item = mailbox.post("oracle", "plan_item", _plan(), to="nara", path=path)
    assert run() == [] and mailbox.fold(mailbox.read(path))[item["msg_id"]]["state"] == "open"
    mailbox.post("oracle", "note", {"text": "reviewing myself"}, to="nara", path=path)  # only reviewers count
    assert run() == []
    mailbox.post("claude", "review", {"verdict": "accept"}, to="nara", in_reply_to=item["msg_id"], path=path)
    assert [r["body"]["state"] for r in run()] == ["claimed", "validated"]
    for verdict in ("amend", "reject"):
        other = mailbox.post("oracle", "plan_item", _plan(title=verdict), to="nara", path=path)
        mailbox.post("codex", "review", {"verdict": verdict}, to="nara", in_reply_to=other["msg_id"], path=path)
        posted = run()
        assert posted[0]["body"]["state"] == "held" and verdict in posted[0]["body"]["reasons"][0]
    for broken in ("not json", "[]", ""):  # an unreadable policy requires review
        policy.write_text(broken)
        waiting = mailbox.post("oracle", "plan_item", _plan(title=f"policy {broken!r}"), to="nara", path=path)
        assert run() == [] and mailbox.fold(mailbox.read(path))[waiting["msg_id"]]["state"] == "open"
        mailbox.post("oracle", "withdraw", {}, to="nara", in_reply_to=waiting["msg_id"], path=path)
    policy.unlink()
    assert lane.meta_verdict([], {"msg_id": "x", "body": _plan()}) == "awaiting"
    policy.write_text('{"require_meta_review": true, "review_optional_task_classes": ["tooling"]}')
    assert lane.meta_verdict([], {"msg_id": "x", "body": _plan()}) == "accept"
    assert lane.meta_verdict([], {"msg_id": "x", "body": _plan(task_class="tests")}) == "awaiting"
    policy.write_text('{"require_meta_review": "false"}')  # only a literal false disables the gate
    assert lane.meta_verdict([], {"msg_id": "x", "body": _plan()}) == "awaiting"
    forged = [{"kind": "review", "actor": "claude", "in_reply_to": "x", "body": {}},  # appended by hand, unchecked
              {"kind": "review", "actor": "claude", "in_reply_to": "x", "body": "accept"},
              {"kind": "review", "actor": "oracle", "in_reply_to": "x", "body": {"verdict": "accept"}}]
    assert lane.meta_verdict(forged, {"msg_id": "x", "body": _plan()}) == "awaiting"


def test_quarantined_accept_cannot_override_latest_live_review_at_claim_boundary(repo, monkeypatch):
    """A hash-valid row is still non-authoritative when mailbox quarantine rejects it.

    The dispatcher sees an initial valid accept.  At the locked claim boundary a
    valid amend lands, followed by a newer forged accept whose recipient is not
    in the mailbox schema.  The latest *live* review remains amend, so the atomic
    predicate must refuse ``claimed`` and the lane records only a hold.
    """
    path = repo / "run_state/mb.jsonl"
    (repo / "config/nara_lane.json").write_text('{"require_meta_review": true}')
    item = mailbox.post("oracle", "plan_item", _plan(), to="nara", path=path)
    mailbox.post("codex", "review", {"verdict": "accept"}, to="nara",
                 in_reply_to=item["msg_id"], path=path)
    real_post_if, injected = mailbox.post_if, threading.Event()

    def poison_before_claim(actor, kind, body, **kwargs):
        if body.get("state") == "claimed" and not injected.is_set():
            injected.set()
            mailbox.post("codex", "review", {"verdict": "amend"}, to="nara",
                         in_reply_to=item["msg_id"], path=path)
            rows = mailbox.read(path)
            _append_unchecked_mailbox_row(path, {
                "schema": mailbox.SCHEMA, "seq": len(rows) + 1,
                "ts": "2026-09-25T12:00:00+00:00", "actor": "codex",
                "to": "not-a-recipient", "kind": "review", "in_reply_to": item["msg_id"],
                "body": {"verdict": "accept"}, "expires_at": None,
            })
        return real_post_if(actor, kind, body, **kwargs)

    monkeypatch.setattr(mailbox, "post_if", poison_before_claim)
    posted = lane.run_queue(path, build=lambda *a, **k: pytest.fail("quarantined review authorized a build"),
                            sandbox=_fake_sandbox, ready=lambda: True)

    assert injected.is_set()
    rows = mailbox.read(path)
    assert any(entry["reason"] == "recipient" for entry in mailbox.quarantine(rows))
    assert lane.meta_verdict(rows, item) == "amend"
    assert [row["body"]["state"] for row in posted] == ["held"]
    assert not [row for row in rows if row["kind"] == "receipt" and row["body"]["state"] == "claimed"]


def test_lane_fails_scope_escape_and_test_tampering(repo):
    path = repo / "run_state/mb.jsonl"
    mailbox.post("oracle", "plan_item", _plan(), to="nara", path=path)

    def escaping(body, worktree, feedback, timeout=0):
        (worktree / "tools/extra.py").write_text("x = 1\n")  # outside allowed paths
        return _good_builder(body, worktree, feedback)

    receipt = lane.run_queue(path, build=escaping, sandbox=_fake_sandbox, ready=lambda: True)[-1]["body"]
    assert receipt["state"] == "failed" and "outside scope" in receipt["reason"]
    second = mailbox.post("oracle", "plan_item", _plan(title="again"), to="nara", path=path)

    def tamper(body, worktree, feedback, timeout=0):
        (worktree / "tests/test_slug.py").write_text("def test_slug():\n    pass\n")
        return {"tools/slug.py": "def slugify(t):\n    return t\n"}

    receipt = lane.run_queue(path, build=tamper, sandbox=_fake_sandbox, ready=lambda: True)[-1]["body"]
    assert receipt["state"] == "failed" and "modified" in receipt["reason"], second


def test_a_held_item_is_terminal_and_does_not_occupy_the_lane(repo, monkeypatch):
    """The run_queue contract the precheck gate depends on (plan 2026-09-23 d1):
    one pass handles every open item, a held item is terminal in the fold (so it
    is never re-examined), and a held sibling does not block the next item."""
    _stub_the_precheck_gate(monkeypatch)
    path = repo / "run_state/mb.jsonl"
    blocked = mailbox.post("oracle", "plan_item", _plan(allowed_write_paths=["orchestrator/secret.py"]),
                           to="nara", path=path)
    good = mailbox.post("oracle", "plan_item", _plan(), to="nara", path=path)
    states = [(r["in_reply_to"], r["body"]["state"]) for r in
              lane.run_queue(path, build=_good_builder, sandbox=_fake_sandbox, ready=lambda: True)]
    assert states == [(blocked["msg_id"], "held"), (good["msg_id"], "claimed"), (good["msg_id"], "validated")]
    assert mailbox.fold(mailbox.read(path))[blocked["msg_id"]]["state"] == "held"  # terminal: not re-examined
    assert lane.run_queue(path, build=_good_builder, sandbox=_fake_sandbox, ready=lambda: True) == []


def test_lane_holds_inadmissible_and_requires_red_first(repo):
    path = repo / "run_state/mb.jsonl"
    mailbox.post("oracle", "plan_item", _plan(allowed_write_paths=["orchestrator/x.py"]), to="nara", path=path)
    passing = _plan(acceptance={**_plan()["acceptance"], "test_content": "def test_ok():\n    assert True\n"})
    mailbox.post("oracle", "plan_item", passing, to="nara", path=path)
    posted = lane.run_queue(path, build=_good_builder, sandbox=_fake_sandbox, ready=lambda: True)
    assert posted[0]["body"]["state"] == "held"
    assert posted[-1]["body"]["state"] == "failed" and "red-first" in posted[-1]["body"]["reason"]


def test_lane_respects_pause_and_recovers_abandoned_claims(repo):
    path = repo / "run_state/mb.jsonl"
    item = mailbox.post("oracle", "plan_item", _plan(), to="nara", path=path)
    (repo / "run_state/pause_nara_lane").write_text("")
    assert lane.run_queue(path, build=_good_builder, sandbox=_fake_sandbox, ready=lambda: True) == []
    (repo / "run_state/pause_nara_lane").unlink()
    mailbox.post("nara", "receipt", {"state": "claimed"}, to="oracle", in_reply_to=item["msg_id"], path=path)
    posted = lane.run_queue(path, build=_good_builder, sandbox=_fake_sandbox, ready=lambda: True)
    assert posted[0]["body"] == {"state": "failed", "reason": "lane interrupted; item abandoned"}


def test_malformed_item_is_quarantined_instead_of_jamming_the_queue(repo, monkeypatch):
    path = repo / "run_state/mb.jsonl"
    with pytest.raises(mailbox.MailboxError, match="budget"):
        mailbox.post("oracle", "plan_item", _plan(budget={"attempts": "2"}), to="nara", path=path)
    with pytest.raises(mailbox.MailboxError, match="strings"):
        mailbox.post("oracle", "plan_item", _plan(acceptance={**_plan()["acceptance"], "test_content": 7}),
                     to="nara", path=path)
    with monkeypatch.context() as patch:  # a row written around post()
        patch.setattr(mailbox, "validate_plan_item", lambda body: None)
        mailbox.post("oracle", "plan_item", _plan(budget={"attempts": "2"}), to="nara", path=path)
    good = mailbox.post("oracle", "plan_item", _plan(), to="nara", path=path)
    posted = lane.run_queue(path, build=_good_builder, sandbox=_fake_sandbox, ready=lambda: True)
    assert [row["body"]["state"] for row in posted] == ["claimed", "validated"]
    assert posted[-1]["in_reply_to"] == good["msg_id"] and posted[-1]["body"]["base_sha"]
    rows = mailbox.read(path)
    assert any(entry["reason"] == "plan_item_body" for entry in mailbox.quarantine(rows))
    with path.open("a") as handle:
        handle.write("{torn\n")
    with pytest.raises(mailbox.MailboxError, match="not JSON"):
        mailbox.read(path)


def test_lane_never_writes_through_a_symlink(repo, tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("host file\n")
    path = repo / "run_state/mb.jsonl"
    mailbox.post("oracle", "plan_item", _plan(), to="nara", path=path)

    def planting(worktree, argv, timeout=0):  # sandboxed code swaps an allowed path for a symlink
        (worktree / "tools/slug.py").unlink(missing_ok=True)
        (worktree / "tools/slug.py").symlink_to(victim)
        return 1, "red"

    receipt = lane.run_queue(path, build=_good_builder, sandbox=planting, ready=lambda: True)[-1]["body"]
    assert receipt["state"] == "failed" and "symlink" in receipt["reason"]
    assert victim.read_text() == "host file\n"


def test_lane_refuses_a_rewritten_git_pointer(repo, tmp_path):
    marker = tmp_path / "PWNED"
    path = repo / "run_state/mb.jsonl"
    mailbox.post("oracle", "plan_item", _plan(), to="nara", path=path)

    def rewriting(worktree, argv, timeout=0):  # sandboxed code points .git at a gitdir it controls
        fake = worktree / "tools/fakegit"
        (fake / "objects").mkdir(parents=True, exist_ok=True)
        (fake / "refs").mkdir(exist_ok=True)
        (fake / "HEAD").write_text("ref: refs/heads/x\n")
        (fake / "config").write_text(f"[core]\n\tfsmonitor = touch {marker}\n")
        (worktree / ".git").write_text(f"gitdir: {fake}\n")
        return _fake_sandbox(worktree, argv, timeout)

    receipt = lane.run_queue(path, build=_good_builder, sandbox=rewriting, ready=lambda: True)[-1]["body"]
    assert receipt["state"] == "failed" and not marker.exists()


def test_real_sandbox_blocks_both_escape_routes(repo, tmp_path):
    """End to end with bubblewrap: model code tries the symlink and .git routes from inside the sandbox."""
    victim, marker = tmp_path / "victim.txt", tmp_path / "PWNED"
    victim.write_text("host file\n")
    evil = (
        "import os, pathlib\n"
        "seen = []\n"
        "here = pathlib.Path('tools')\n"
        "os.symlink(%r, 'tools/link.tmp'); os.replace('tools/link.tmp', 'tools/slug.py')\n"
        "fake = here / 'fakegit'\n"
        "(fake / 'objects').mkdir(parents=True, exist_ok=True); (fake / 'refs').mkdir(exist_ok=True)\n"
        "(fake / 'HEAD').write_text('ref: refs/heads/x\\n')\n"
        "(fake / 'config').write_text('[core]\\n\\tfsmonitor = touch %s\\n')\n"
        "for attempt in (lambda: pathlib.Path('.git').write_text('gitdir: ' + str(fake.resolve())),\n"
        "                lambda: os.replace(str(fake), '.git')):\n"
        "    try:\n        attempt(); seen.append('GIT-WRITABLE')\n"
        "    except OSError:\n        seen.append('GIT-READ-ONLY')\n"
        "def slugify(text):\n    return ' '.join(seen)\n"  # the observations land in the test output
    ) % (str(victim), str(marker))
    calls = []

    def builder(body, worktree, feedback, timeout=0):
        calls.append(feedback)
        return {"tools/slug.py": evil if len(calls) == 1 else _good_builder(body, worktree, feedback)["tools/slug.py"]}

    path = repo / "run_state/mb.jsonl"
    item = mailbox.post("oracle", "plan_item", _plan(), to="nara", path=path)
    receipt = lane.run_queue(path, build=builder, sandbox=lane.sandbox_run, ready=lambda: True)[-1]["body"]
    worktree = lane.WORKTREES / item["msg_id"]
    pointer = (worktree / ".git").read_text()
    assert "GIT-READ-ONLY GIT-READ-ONLY" in calls[1] and "GIT-WRITABLE" not in calls[1], calls[1]
    assert receipt["state"] == "failed" and "symlink" in receipt["reason"], receipt
    assert victim.read_text() == "host file\n" and not marker.exists()
    assert pointer.startswith("gitdir: ") and "fakegit" not in pointer


def test_real_sandbox_requires_a_junit_pass(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_exit.py").write_text("import os\nos._exit(0)\n")
    (tmp_path / "tests/test_ok.py").write_text("def test_ok():\n    assert True\n")
    rc, output = lane.sandbox_run(tmp_path, ["python", "-m", "pytest", "-q", "tests/test_exit.py"], timeout=120)
    assert rc != 0 and "no JUnit report" in output, output
    rc, output = lane.sandbox_run(tmp_path, ["python", "-m", "pytest", "-q", "tests/test_ok.py"], timeout=120)
    assert rc == 0 and "acceptance_passed=1" in output, output


def test_real_sandbox_isolates_network_home_and_host_writes(tmp_path):
    worktree, marker = tmp_path / "wt", tmp_path / "outside" / "sandbox-escape-marker"
    worktree.mkdir()
    code = (
        "import socket, pathlib, sys\n"
        "s = socket.socket()\n"
        "try:\n    s.connect(('127.0.0.1', 30080)); print('NET-OPEN')\n"
        "except OSError:\n    print('NET-BLOCKED')\n"
        f"print('HOME-HIDDEN' if not pathlib.Path({__file__!r}).exists() else 'HOME-VISIBLE')\n"
        "try:\n"
        f"    pathlib.Path({str(marker)!r}).parent.mkdir(parents=True, exist_ok=True)\n"
        f"    pathlib.Path({str(marker)!r}).write_text('x')\n"
        "except OSError:\n    pass\n"
        "pathlib.Path('inside.txt').write_text('ok')\n"
    )
    rc, output = lane.sandbox_run(worktree, ["python", "-c", code], timeout=60)
    assert "NET-BLOCKED" in output and "HOME-HIDDEN" in output, output
    assert not marker.exists() and (worktree / "inside.txt").read_text() == "ok"


def test_publish_plan_ready_binds_only_committed_plan_and_packet_bytes(tmp_path):
    repo, head, plan_path, packet_path, plan_file, packet_file, _git = _plan_ready_repo(tmp_path)
    mailbox_path = tmp_path / "mb.jsonl"
    # These mutable files deliberately disagree with their committed counterparts.
    plan_file.write_text('{"date":"wrong","revision":"r99","state_packet_sha256":"0"}\n')
    packet_file.write_text("mutable packet must not be read\n")

    row, duplicate = _publish(repo, head, plan_path, packet_path, mailbox_path=mailbox_path)

    assert not duplicate and row["actor"] == "oracle" and row["kind"] == "note"
    assert row["body"]["event"] == "PLAN READY"
    assert row["body"]["head_sha"] == head
    assert row["body"]["plan_path"] == plan_path
    assert row["body"]["state_packet_path"] == packet_path
    assert len(mailbox.read(mailbox_path)) == 1


def test_publish_plan_ready_rejects_hash_mismatch_and_revision_conflict(tmp_path):
    repo, head, plan_path, packet_path, _plan_file, _packet_file, git = _plan_ready_repo(tmp_path)
    mailbox_path = tmp_path / "mb.jsonl"
    with pytest.raises(mailbox.MailboxError, match="plan_sha256"):
        mailbox.publish_plan_ready(
            branch="main", head_sha=head, plan_path=plan_path, plan_sha256="0" * 64,
            state_packet_path=packet_path, state_packet_sha256="0" * 64,
            repo_root=repo, path=mailbox_path,
        )
    row, duplicate = _publish(repo, head, plan_path, packet_path, mailbox_path=mailbox_path)
    assert not duplicate
    # A later commit cannot replace a named immutable revision after it was announced.
    (repo / "README.md").write_text("later commit\n")
    git("add", "README.md")
    git("commit", "-m", "unrelated later commit")
    later_head = git("rev-parse", "HEAD")
    with pytest.raises(mailbox.MailboxError, match="different committed binding"):
        _publish(repo, later_head, plan_path, packet_path, mailbox_path=mailbox_path)
    assert mailbox.read(mailbox_path) == [row]


def test_publish_plan_ready_replay_is_idempotent_and_recovers_after_no_mail_append(tmp_path, monkeypatch):
    repo, head, plan_path, packet_path, _plan_file, _packet_file, _git = _plan_ready_repo(tmp_path)
    mailbox_path = tmp_path / "mb.jsonl"
    original_append = mailbox._append_locked

    def interrupted(*_args, **_kwargs):
        raise OSError("simulated interruption before mailbox append")

    monkeypatch.setattr(mailbox, "_append_locked", interrupted)
    with pytest.raises(OSError, match="interruption"):
        _publish(repo, head, plan_path, packet_path, mailbox_path=mailbox_path)
    assert mailbox.read(mailbox_path) == []  # files are still committed; only the mail step failed
    monkeypatch.setattr(mailbox, "_append_locked", original_append)
    first, duplicate = _publish(repo, head, plan_path, packet_path, mailbox_path=mailbox_path)
    replay, replay_duplicate = _publish(repo, head, plan_path, packet_path, mailbox_path=mailbox_path)
    assert not duplicate and replay_duplicate and replay == first
    assert mailbox.read(mailbox_path) == [first]


def test_publish_plan_ready_rejects_traversal_and_committed_symlink_packet(tmp_path):
    repo, head, plan_path, packet_path, _plan_file, _packet_file, git = _plan_ready_repo(tmp_path)
    mailbox_path = tmp_path / "mb.jsonl"
    plan_bytes = subprocess.run(["git", "-C", str(repo), "show", f"{head}:{plan_path}"], check=True,
                                stdout=subprocess.PIPE).stdout
    packet_bytes = subprocess.run(["git", "-C", str(repo), "show", f"{head}:{packet_path}"], check=True,
                                  stdout=subprocess.PIPE).stdout
    with pytest.raises(mailbox.MailboxError, match="stay inside"):
        mailbox.publish_plan_ready(
            branch="main", head_sha=head, plan_path=plan_path,
            plan_sha256=hashlib.sha256(plan_bytes).hexdigest(), state_packet_path="../outside",
            state_packet_sha256=hashlib.sha256(packet_bytes).hexdigest(), repo_root=repo, path=mailbox_path,
        )

    link_path = "notes/ops/2026-09-25/PACKET_LINK.md"
    os.symlink("STATE_PACKET.md", repo / link_path)
    git("add", link_path)
    git("commit", "-m", "add packet symlink")
    linked_head = git("rev-parse", "HEAD")
    with pytest.raises(mailbox.MailboxError, match="regular file"):
        _publish(repo, linked_head, plan_path, link_path, mailbox_path=mailbox_path)


def test_publish_plan_ready_keeps_dashboard_and_runner_title_ref_contract(tmp_path):
    repo, head, plan_path, packet_path, _plan_file, _packet_file, _git = _plan_ready_repo(tmp_path)
    mailbox_path = tmp_path / "mb.jsonl"
    row, duplicate = mailbox.publish_plan_ready(**_publish_args(repo, head, plan_path, packet_path,
                                                                mailbox_path=mailbox_path))
    assert not duplicate
    assert row["body"]["title"] == "PLAN READY: 2026-09-25 (r1)"
    assert row["body"]["ref"] == {"path": plan_path, "sha256": row["body"]["plan_sha256"]}
    assert mailbox.PLAN_READY_TITLE.fullmatch(row["body"]["title"])
    assert row["body"]["ref"]["path"] == plan_path
    # The generic list renderer selects body.title, and the meta-oracle runner
    # selects titles beginning with PLAN READY. Neither needs a special case.
    assert row["body"]["title"].startswith("PLAN READY")


def test_plan_ready_protocol_is_reserved_and_full_chain_conflicts_are_not_hidden(tmp_path):
    repo, head, plan_path, packet_path, _plan_file, _packet_file, _git = _plan_ready_repo(tmp_path)
    mailbox_path = tmp_path / "mb.jsonl"
    with pytest.raises(mailbox.MailboxError, match="reserved"):
        mailbox.post("oracle", "note", {"event": "PLAN READY"}, to="all", path=mailbox_path)
    with pytest.raises(mailbox.MailboxError, match="reserved"):
        mailbox.post("oracle", "note", {"protocol": "oracle-plan-ready/v1"}, to="all", path=mailbox_path)
    args = _publish_args(repo, head, plan_path, packet_path, mailbox_path=mailbox_path)
    first, _ = mailbox.publish_plan_ready(**args)
    # A later legacy-shaped duplicate must be found even though the first row is exact.
    with mailbox._mailbox_lock(mailbox_path):
        mailbox._append_locked("oracle", "note", {
        "title": "PLAN READY: 2026-09-25 (r1)",
        "ref": {"path": plan_path, "sha256": "f" * 64},
        }, to="all", in_reply_to=None, expires_hours=None, path=mailbox_path,
                               rows=mailbox.read(mailbox_path))
    with pytest.raises(mailbox.MailboxError, match="ambiguous"):
        mailbox.publish_plan_ready(**args)
    assert mailbox.read(mailbox_path)[0] == first


def test_plan_ready_rejects_noncanonical_typed_envelope_or_extra_fields(tmp_path):
    repo, head, plan_path, packet_path, _plan_file, _packet_file, _git = _plan_ready_repo(tmp_path)
    mailbox_path = tmp_path / "mb.jsonl"
    args = _publish_args(repo, head, plan_path, packet_path, mailbox_path=mailbox_path)
    first, _ = mailbox.publish_plan_ready(**args)
    malformed = {**first["body"], "unexpected": "not canonical"}
    with mailbox._mailbox_lock(mailbox_path):
        mailbox._append_locked("oracle", "note", malformed, to="nara", in_reply_to=None,
                               expires_hours=None, path=mailbox_path, rows=mailbox.read(mailbox_path))
    with pytest.raises(mailbox.MailboxError, match="ambiguous"):
        mailbox.publish_plan_ready(**args)


@pytest.mark.parametrize("legacy_seq,title", [
    (16, "PLAN READY: 2026-09-25 (r1, amended per review)"),
    (52, "PLAN READY: 2026-09-25 (r1, amended per review)"),
    (81, "PLAN READY: 2026-09-25 (ref, supersedes an incomplete note)"),
    (313, "PLAN READY: 2026-09-25-r1 (amended; immutable path)"),
    (351, "PLAN READY: 2026-09-25-r1 (revised after review)"),
    (394, "PLAN READY: 2026-09-25-r1 (new immutable path; prior held)"),
    (450, "PLAN READY: 2026-09-25-r1 (new immutable path; packet corrected)"),
    (730, "PLAN READY: 2026-09-25-r1"),
    (743, "PLAN READY: 2026-09-25"),
])
def test_historical_plan_ready_titles_are_read_only_conflicts_and_generic_post_reserves_them(
        tmp_path, legacy_seq, title):
    repo, head, plan_path, packet_path, _plan_file, _packet_file, _git = _plan_ready_repo(tmp_path)
    mailbox_path = tmp_path / "mb.jsonl"
    args = _publish_args(repo, head, plan_path, packet_path, mailbox_path=mailbox_path)
    # Generic posts cannot make a row that the dashboard or meta runner would consume.
    with pytest.raises(mailbox.MailboxError, match="reserved"):
        mailbox.post("oracle", "note", {"title": title, "ref": {"path": plan_path}},
                     to="all", path=mailbox_path)
    # Existing hash-chained legacy rows remain readable but block an unverified typed duplicate.
    with mailbox._mailbox_lock(mailbox_path):
        mailbox._append_locked("oracle", "note", {"title": title, "ref": {"path": plan_path}},
                               to="all", in_reply_to=None, expires_hours=None, path=mailbox_path,
                               rows=mailbox.read(mailbox_path))
    assert mailbox.read(mailbox_path)[0]["body"]["title"] == title
    with pytest.raises(mailbox.MailboxError, match="ambiguous"):
        mailbox.publish_plan_ready(**args)


def test_generic_post_freezes_body_before_lock_contention_and_reservation_check(tmp_path, monkeypatch):
    mailbox_path = tmp_path / "mb.jsonl"
    caller_body = {"text": "ordinary note"}
    validated, release = threading.Event(), threading.Event()
    original_validate = mailbox._validate_post

    def gated_validate(actor, kind, body, to, in_reply_to):
        original_validate(actor, kind, body, to, in_reply_to)
        validated.set()
        assert release.wait(2)

    monkeypatch.setattr(mailbox, "_validate_post", gated_validate)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with mailbox._mailbox_lock(mailbox_path):
            future = pool.submit(mailbox.post, "oracle", "note", caller_body, to="all", path=mailbox_path)
            assert validated.wait(2)
            # This mutation happens after validation but before the writer gets its lock.
            caller_body.update({"title": "PLAN READY: 2026-09-25-r1", "event": "PLAN READY"})
            release.set()
        row = future.result()
    assert row["body"] == {"text": "ordinary note"}
    assert mailbox.read(mailbox_path) == [row]


def test_git_verification_has_a_hard_timeout(monkeypatch, tmp_path):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout=b"ok\n", stderr=b"")

    monkeypatch.setattr(mailbox.subprocess, "run", fake_run)
    assert mailbox._git(tmp_path, "status") == b"ok\n"
    assert calls[0][1]["timeout"] == mailbox.GIT_TIMEOUT_S


def test_publish_plan_ready_exact_retry_survives_branch_move_or_deletion(tmp_path):
    repo, head, plan_path, packet_path, _plan_file, _packet_file, git = _plan_ready_repo(tmp_path)
    mailbox_path = tmp_path / "mb.jsonl"
    args = _publish_args(repo, head, plan_path, packet_path, mailbox_path=mailbox_path)
    first, duplicate = mailbox.publish_plan_ready(**args)
    assert not duplicate
    (repo / "README.md").write_text("new head\n")
    git("add", "README.md")
    git("commit", "-m", "move main")
    retry, duplicate = mailbox.publish_plan_ready(**args)
    assert duplicate and retry == first
    git("update-ref", "-d", "refs/heads/main")
    retry, duplicate = mailbox.publish_plan_ready(**args)
    assert duplicate and retry == first


def test_mailbox_rejects_symlinked_mailbox_and_lock_without_touching_target(tmp_path):
    victim = tmp_path / "victim.jsonl"
    victim.write_text("do not append\n")
    mailbox_path = tmp_path / "mb.jsonl"
    os.symlink(victim, mailbox_path)
    with pytest.raises(mailbox.MailboxError, match="symlink"):
        mailbox.post("oracle", "note", {"text": "x"}, to="all", path=mailbox_path)
    assert victim.read_text() == "do not append\n"

    mailbox_path.unlink()
    lock_path = tmp_path / ".oracle_nara_mailbox.lock"
    os.symlink(victim, lock_path)
    with pytest.raises(mailbox.MailboxError, match="symlink"):
        mailbox.post("oracle", "note", {"text": "x"}, to="all", path=mailbox_path)
    assert victim.read_text() == "do not append\n"


def test_publish_plan_ready_enforces_separate_plan_and_packet_blob_bounds(tmp_path):
    repo, _head, plan_path, packet_path, plan_file, packet_file, git = _plan_ready_repo(tmp_path)
    mailbox_path = tmp_path / "mb.jsonl"
    plan_file.write_bytes(b"x" * (mailbox.MAX_PLAN_BYTES + 1))
    git("add", plan_path)
    git("commit", "-m", "oversize plan")
    head = git("rev-parse", "HEAD")
    with pytest.raises(mailbox.MailboxError, match="byte bound"):
        _publish(repo, head, plan_path, packet_path, mailbox_path=mailbox_path)

    # A packet gets its own (larger) cap; make the committed plan bind its new digest.
    packet = b"y" * (mailbox.MAX_STATE_PACKET_BYTES + 1)
    packet_file.write_bytes(packet)
    plan_file.write_text(json.dumps({
        "date": "2026-09-25", "revision": "r1",
        "state_packet_sha256": hashlib.sha256(packet).hexdigest(),
    }) + "\n")
    git("add", plan_path, packet_path)
    git("commit", "-m", "oversize packet")
    head = git("rev-parse", "HEAD")
    with pytest.raises(mailbox.MailboxError, match="byte bound"):
        _publish(repo, head, plan_path, packet_path, mailbox_path=mailbox_path)
