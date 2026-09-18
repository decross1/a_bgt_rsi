"""Real file observer tests; no model calls."""

import json
import stat

from agent_wrapper.live_trace import (
    CHANNEL_BYTES,
    MAX_FILES,
    LocalModelTrace,
    start_trace,
)


def make_trace(path):
    return LocalModelTrace(path, model="local-model", backend="flash",
                           source="test", messages=[{"role": "user", "content": "Question"}])


def test_opt_in_only(monkeypatch):
    monkeypatch.delenv("LOCAL_MODEL_TRACE_DIR", raising=False)
    assert start_trace(model="m", backend="b", source="test", messages=[]) is None


def test_channels_terminal_and_private_atomic_file(tmp_path):
    trace = make_trace(tmp_path)
    path = tmp_path / f"{trace.request_id}.json"
    initial = json.loads(path.read_text())
    assert initial["status"] == "streaming"
    trace.update(reasoning_content="emitted reasoning", content="answer", status="completed",
                 usage={"completion_tokens": 10}, finish_reason="stop", force=True)
    row = json.loads(path.read_text())
    assert row["reasoning_content"] == "emitted reasoning"
    assert row["content"] == "answer" and row["status"] == "completed"
    assert row["started_at"] == initial["started_at"]
    assert row["usage"]["completion_tokens"] == 10
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert list(tmp_path.glob(".trace-*")) == []


def test_multibyte_tail_is_bounded_and_disclosed(tmp_path):
    trace = make_trace(tmp_path)
    trace.update(reasoning_content="語" * CHANNEL_BYTES + " latest", force=True)
    row = json.loads((tmp_path / f"{trace.request_id}.json").read_text())
    assert len(row["reasoning_content"].encode()) <= CHANNEL_BYTES
    assert row["reasoning_content"].endswith(" latest")
    assert row["truncated"]["reasoning_content"]


def test_disk_failure_is_nonfatal_and_no_partial_snapshot(tmp_path, monkeypatch):
    trace = make_trace(tmp_path)
    def fail(*_):
        raise OSError("disk full")
    monkeypatch.setattr("agent_wrapper.live_trace.os.replace", fail)
    trace.update(content="new", force=True)
    assert trace.disabled
    assert json.loads((tmp_path / f"{trace.request_id}.json").read_text())["content"] == ""
    assert not list(tmp_path.glob(".trace-*"))


def test_history_is_bounded_without_removing_unrelated_files(tmp_path):
    untouched = tmp_path / "owner.json"
    untouched.write_text("{}")
    for index in range(MAX_FILES + 3):
        (tmp_path / f"{index:032x}.json").write_text("{}")
    trace = make_trace(tmp_path)
    assert untouched.exists() and not trace.disabled
    assert len(list(tmp_path.glob("*.json"))) == MAX_FILES + 1


def test_symlink_directory_does_not_write(tmp_path):
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    trace = make_trace(link)
    assert trace.disabled and not list(target.iterdir())


def test_scan_limit_disables_writing_instead_of_unbounded_history(tmp_path):
    for index in range(513):
        (tmp_path / f"unrelated-{index}").touch()
    for _ in range(3):
        trace = make_trace(tmp_path)
        assert trace.disabled
        trace.update(content="ignored", force=True)
    assert not list(tmp_path.glob("*.json"))


def test_large_usage_extras_cannot_hide_terminal_status(tmp_path):
    trace = make_trace(tmp_path)
    trace.update(status="completed", content="answer", force=True,
                 usage={"prompt_tokens": 8, "completion_tokens": 2,
                        "extra": "x" * 600_000})
    row = json.loads((tmp_path / f"{trace.request_id}.json").read_text())
    assert row["status"] == "completed" and not trace.disabled
    assert row["usage"] == {"prompt_tokens": 8, "completion_tokens": 2}
    assert row["usage_truncated"]


def test_json_escape_expansion_keeps_terminal_state(tmp_path):
    trace = make_trace(tmp_path)
    trace.update(status="completed", reasoning_content="\0" * CHANNEL_BYTES,
                 content="\1" * CHANNEL_BYTES, force=True)
    path = tmp_path / f"{trace.request_id}.json"
    row = json.loads(path.read_text())
    assert row["status"] == "completed" and not trace.disabled
    assert path.stat().st_size <= 512 * 1024
    assert row["truncated"]["reasoning_content"] or row["truncated"]["content"]


def test_large_unknown_status_cannot_loop_or_remain_streaming(tmp_path):
    trace = make_trace(tmp_path)
    trace.update(status="x" * 600_000, force=True)
    row = json.loads((tmp_path / f"{trace.request_id}.json").read_text())
    assert row["status"] == "interrupted" and not trace.disabled
    assert row["error"] == "Trace observer received an unsupported status."
