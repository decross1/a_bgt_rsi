"""Focused durable-mailbox regressions retained by the card-only port.

These cases are intentionally independent of ``nara_lane``: the card surface
uses the same mailbox writer and projection, and must preserve its locking,
durability, quarantine, and fail-closed authority properties.
"""
import hashlib
import json
import multiprocessing
import os
from pathlib import Path

import pytest

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
    """Independent process: exercise the actual fcntl lock boundary."""
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
    except Exception as exc:  # result is asserted by parent
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


def test_post_if_reads_and_appends_under_one_mailbox_lock(tmp_path):
    path, seen = tmp_path / "mb.jsonl", []
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


def test_post_if_predicate_cannot_mutate_verified_prefix_used_for_append(tmp_path):
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


def test_post_once_is_idempotent_and_owner_claims_do_not_close_question(tmp_path):
    path = tmp_path / "mb.jsonl"
    question = mailbox.post("oracle", "question", {"question": "Proceed?"}, to="owner", path=path)
    body = {"text": "approve", "decision": "approve", "request_id": "req-1"}
    answer, duplicate = mailbox.post_once(
        "human:derrick", "answer", body, to="oracle", in_reply_to=question["msg_id"],
        idempotency_key="req-1", require_open_question=True, path=path,
    )
    retry, duplicate_retry = mailbox.post_once(
        "human:derrick", "answer", body, to="oracle", in_reply_to=question["msg_id"],
        idempotency_key="req-1", require_open_question=True, path=path,
    )
    assert duplicate is False and duplicate_retry is True and retry == answer
    with pytest.raises(mailbox.MailboxError, match="different request"):
        mailbox.post_once(
            "human:derrick", "answer", {**body, "text": "decline"}, to="oracle",
            in_reply_to=question["msg_id"], idempotency_key="req-1",
            require_open_question=True, path=path,
        )
    assert mailbox.is_question_closed(question, mailbox.read(path)) is False


def test_post_once_requires_matching_body_request_id(tmp_path):
    path = tmp_path / "mb.jsonl"
    question = mailbox.post("oracle", "question", {"question": "Proceed?"}, to="owner", path=path)
    with pytest.raises(mailbox.MailboxError, match="body.request_id"):
        mailbox.post_once(
            "human:derrick", "answer", {"text": "approve", "request_id": "different"},
            to="oracle", in_reply_to=question["msg_id"], idempotency_key="expected",
            require_open_question=True, path=path,
        )
    assert mailbox.read(path) == [question]


def test_cross_process_same_request_appends_once_and_returns_one_duplicate(tmp_path):
    path = tmp_path / "mb.jsonl"
    question = mailbox.post("oracle", "question", {"question": "Proceed?"}, to="owner", path=path)
    outcomes = _race_post_once(path, question["msg_id"], [
        ("same-request", "approve"), ("same-request", "approve"),
    ])
    assert sorted((result[0], result[1]) for result in outcomes) == [("ok", False), ("ok", True)]
    assert len({result[2] for result in outcomes}) == 1
    rows = mailbox.read(path)
    assert len(rows) == 2 and rows[-1]["body"]["request_id"] == "same-request"


def test_cross_process_distinct_claims_remain_nonterminal_and_keep_chain_valid(tmp_path):
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


def test_post_once_never_returns_before_file_and_directory_sync(tmp_path, monkeypatch):
    path = tmp_path / "mb.jsonl"
    question = mailbox.post("oracle", "question", {"question": "Proceed?"}, to="owner", path=path)
    complete_prefix, real_open = path.read_bytes(), Path.open

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

    body = {"text": "context", "request_id": "sync-request"}
    monkeypatch.setattr(Path, "open", short_open)
    with pytest.raises(mailbox.MailboxError, match="short and rolled back"):
        mailbox.post_once("human:derrick", "answer", body, to="oracle", in_reply_to=question["msg_id"],
                          idempotency_key="sync-request", require_open_question=True, path=path)
    assert path.read_bytes() == complete_prefix
    monkeypatch.setattr(Path, "open", real_open)

    real_fsync = mailbox.os.fsync
    fsync_body = {"text": "context", "request_id": "fsync-request"}
    monkeypatch.setattr(mailbox.os, "fsync", lambda _fd: (_ for _ in ()).throw(OSError("sync fault")))
    with pytest.raises(mailbox.MailboxError, match="durability is unconfirmed"):
        mailbox.post_once("human:derrick", "answer", fsync_body, to="oracle", in_reply_to=question["msg_id"],
                          idempotency_key="fsync-request", require_open_question=True, path=path)
    monkeypatch.setattr(mailbox.os, "fsync", real_fsync)
    row, duplicate = mailbox.post_once("human:derrick", "answer", fsync_body, to="oracle",
                                       in_reply_to=question["msg_id"], idempotency_key="fsync-request",
                                       require_open_question=True, path=path)
    assert duplicate is True and row["body"] == fsync_body


def test_retry_repairs_only_verified_unterminated_torn_tail(tmp_path):
    path = tmp_path / "mb.jsonl"
    question = mailbox.post("oracle", "question", {"question": "Proceed?"}, to="owner", path=path)
    prefix = path.read_bytes()
    with path.open("ab", buffering=0) as handle:
        handle.write(b'{"schema":"oracle-nara-mailbox/v1"')
    with pytest.raises(mailbox.MailboxError, match="not JSON"):
        mailbox.read(path)
    note = mailbox.post("oracle", "note", {"text": "after recovery"}, to="owner", path=path)
    assert mailbox.read(path) == [question, note]
    assert path.read_bytes().startswith(prefix)


def test_retry_preserves_complete_final_row_when_only_newline_is_lost(tmp_path):
    path = tmp_path / "mb.jsonl"
    first = mailbox.post("oracle", "note", {"text": "first"}, to="owner", path=path)
    second = mailbox.post("oracle", "note", {"text": "second"}, to="owner", path=path)
    path.write_bytes(path.read_bytes()[:-1])
    assert mailbox.read(path) == [first, second]
    third = mailbox.post("oracle", "note", {"text": "third"}, to="owner", path=path)
    assert mailbox.read(path) == [first, second, third]
    assert third["prev_sha256"] == second["row_sha256"] and path.read_bytes().endswith(b"\n")


def test_mailbox_rejects_symlinked_mailbox_and_lock_without_touching_target(tmp_path):
    victim = tmp_path / "victim.jsonl"
    victim.write_text("do not append\n")
    path = tmp_path / "mb.jsonl"
    os.symlink(victim, path)
    with pytest.raises(mailbox.MailboxError, match="symlink"):
        mailbox.post("oracle", "note", {"text": "x"}, to="all", path=path)
    assert victim.read_text() == "do not append\n"

    path.unlink()
    lock = tmp_path / ".oracle_nara_mailbox.lock"
    os.symlink(victim, lock)
    with pytest.raises(mailbox.MailboxError, match="symlink"):
        mailbox.post("oracle", "note", {"text": "x"}, to="all", path=path)
    assert victim.read_text() == "do not append\n"


@pytest.mark.parametrize(("poison_schema", "forced_msg_id", "reason"), [
    ("oracle-nara-mailbox/v999", None, "schema"),
    (mailbox.SCHEMA, "human-not-writer-derived", "msg_id"),
])
def test_structurally_invalid_owner_answer_is_quarantined_and_cannot_consume_retry(
        tmp_path, poison_schema, forced_msg_id, reason):
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
    malformed = _append_unchecked_mailbox_row(path, poison, generate_msg_id=forced_msg_id is None)
    rows = mailbox.read(path)
    assert mailbox.quarantine(rows) == [{
        "position": 2, "seq": 2, "msg_id": malformed["msg_id"], "reason": reason,
    }]
    assert mailbox.find_idempotency_key(body["request_id"], path=path) is None
    answer, duplicate = mailbox.post_once(
        "human:derrick", "answer", body, to="oracle", in_reply_to=question["msg_id"],
        idempotency_key=body["request_id"], require_open_question=True, path=path,
    )
    assert duplicate is False and answer["schema"] == mailbox.SCHEMA


def test_forged_human_actor_claim_never_closes_owner_question(tmp_path):
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
