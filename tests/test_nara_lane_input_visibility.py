"""Input visibility: a plan item may not name an input file its builder cannot read.

Meta-oracle finding, review claude-e347ce59ca643116 (seq 165), severity material.
Plan 2026-09-24 d1 was posted with `notes/research/2026-09-24-g11-candidates/
READING_LIST.md` in `allowed_write_paths` and an objective telling the builder to
copy 19 paper titles from that file. The file exists nowhere: `implement()` creates
the worktree as checkout HEAD plus the acceptance test, and `builder()` reports
`current_contents` only for writable paths. So the builder was instructed to copy
titles from a path it saw as `None` - the invented-citation failure mode dressed up
as an instruction, and the item was posted knowing it (my seq 163 raised the objection).

Two rules close it:

1. `admission()` refuses an item that declares `input_paths` - paths it names as
   inputs to read - unless each one is readable by the builder: present at the
   checkout HEAD, or writable and present in the worktree. The lane holds the item
   before it draws a worktree, so no attempt is burned and no receipt is mislabelled.
2. `builder()` states the verdict in the prompt. A declared input that is absent is
   reported as `NOT PRESENT ... do not copy, quote or invent content for it`, and the
   system prompt carries the rule. Absent today: the builder just gets `None`, which
   a model reads as an empty file.

An item that declares no `input_paths` is admitted and prompted exactly as before.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from orchestrator import nara_lane as lane

WRITABLE = "notes/research/2026-09-24-g11-candidates/CANDIDATES.md"
ABSENT_INPUT = "notes/research/2026-09-24-g11-candidates/READING_LIST.md"
TRACKED_INPUT = "notes/existing_inputs.md"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout


@pytest.fixture
def repo(tmp_path):
    """A checkout whose HEAD tracks one readable input file."""
    root = tmp_path / "checkout"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "Test")
    tracked = root / TRACKED_INPUT
    tracked.parent.mkdir(parents=True, exist_ok=True)
    tracked.write_text("iter-2026-09-23-035 - a stored claim\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    return root

def _item(**body_over) -> dict:
    body = {
        "title": "d1: draft thesis candidates",
        "objective": "Write CANDIDATES.md; copy the 19 titles from the reading list verbatim.",
        "task_class": "documentation",
        "allowed_write_paths": [WRITABLE],
        "acceptance": {
            "test_path": "tests/test_g11_candidates_shape.py",
            "test_content": "def test_shape():\n    assert False\n",
            "test_argv": ["python", "-m", "pytest", "-q", "tests/test_g11_candidates_shape.py"]},
        "budget": {"attempts": 3, "wall_clock_minutes": 30},
    }
    body.update(body_over)
    return {"msg_id": "oracle-d1-test", "actor": "oracle", "body": body}


# --- rule 1: admission() refuses an item whose declared input is unreadable ----------


def test_item_declaring_no_inputs_is_admitted_as_before(repo, monkeypatch, tmp_path) -> None:
    """No regression: today's posting style (readable content inline in the objective)
    still passes admission, so the new rule only bites items that name a file."""
    monkeypatch.setattr(lane, "ROOT", tmp_path)  # non-repo test root: isolate input behavior from precheck
    monkeypatch.setattr(lane, "_prechecked", lambda _item, **_kw: True)
    assert lane.admission(_item()) == []


def test_admission_refuses_an_input_path_that_is_not_at_head(repo) -> None:
    """The seq-165 shape: input_paths names a file that is not committed at HEAD and is
    not writable. `notes/...` is inside the lane fence, so the path fence cannot catch
    this; only a visibility check can."""
    item = _item(input_paths=[ABSENT_INPUT])
    reasons = lane.admission(item, repo_root=repo)
    assert any(ABSENT_INPUT in r and "read" in r.lower() for r in reasons), reasons


def test_admission_accepts_an_input_path_tracked_at_head(repo) -> None:
    reasons = lane.admission(_item(input_paths=[TRACKED_INPUT]), repo_root=repo)
    assert not any("input" in r and TRACKED_INPUT in r for r in reasons), reasons


def test_admission_accepts_a_writable_input_path_that_exists(repo) -> None:
    """An input the builder may also write is visible when it is at HEAD: builder()
    shows current contents for writable paths."""
    (repo / "notes/writable_note.md").write_text("ok\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "note")
    item = _item(allowed_write_paths=[WRITABLE, "notes/writable_note.md"],
                 input_paths=["notes/writable_note.md"])
    reasons = lane.admission(item, repo_root=repo)
    assert not any("input" in r and "writable_note" in r for r in reasons), reasons


def test_admission_refuses_an_input_path_outside_the_fence(repo) -> None:
    """A path the lane fence denies is never readable by the sandboxed builder."""
    reasons = lane.admission(_item(input_paths=["run_state/secrets.json"]), repo_root=repo)
    assert any("run_state/secrets.json" in r for r in reasons), reasons


def test_admission_still_refuses_a_non_regular_input(repo) -> None:
    """A declared input that is not a regular file at HEAD (here, a directory) is not
    something builder() can hand over."""
    (repo / "notes/dir_input").mkdir(parents=True, exist_ok=True)
    (repo / "notes/dir_input/inner.md").write_text("inner\n", encoding="utf-8")
    _git(repo, "add", "notes/dir_input/inner.md")
    _git(repo, "commit", "-q", "-m", "directory input")
    reasons = lane.admission(_item(input_paths=["notes/dir_input"]), repo_root=repo)
    assert any("notes/dir_input" in r for r in reasons), reasons


def test_admission_holds_tracked_directory_inputs_with_trailing_slashes(repo) -> None:
    for directory in ("docs", "notes"):
        (repo / directory).mkdir(exist_ok=True)
        (repo / directory / "child.md").write_text("tracked child\n", encoding="utf-8")
    (repo / "notes/link_target.md").write_text("tracked target\n", encoding="utf-8")
    os.symlink("link_target.md", repo / "notes/linked_input.md")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "tracked directory and symlink inputs")

    for path in ("docs/", "notes/"):
        reasons = lane.admission(_item(input_paths=[path]), repo_root=repo)
        assert any(path in reason and "not readable by the builder" in reason
                   for reason in reasons), (path, reasons)

    for path in ("docs", "notes"):
        reasons = lane.admission(_item(input_paths=[path]), repo_root=repo)
        assert any(path in reason and "not readable by the builder" in reason
                   for reason in reasons), (path, reasons)

    path = "notes/linked_input.md"
    reasons = lane.admission(_item(input_paths=[path]), repo_root=repo)
    assert any(path in reason and "not readable by the builder" in reason
               for reason in reasons), (path, reasons)


# --- rule 2: builder() tells the model which declared inputs it cannot read ---------


def _call_builder(monkeypatch, body, worktree):
    captured: dict = {}

    def fake_call_sync(messages, **kw):
        captured["messages"] = messages
        return {"completion": json.dumps({"files": {WRITABLE: "# candidates\n"}})}

    import agent_wrapper.wrapper as wrapper

    monkeypatch.setattr(wrapper, "call_sync", fake_call_sync)
    files = lane.builder(body, worktree, "test output", timeout=5)
    return captured, files


def _body(**over) -> dict:
    body = {
        "title": "d1", "objective": "copy the titles from the reading list verbatim",
        "allowed_write_paths": [WRITABLE], "input_paths": [ABSENT_INPUT],
        "acceptance": {"test_path": "tests/test_g11_candidates_shape.py",
                       "test_content": "def test_shape():\n    assert False\n"},
    }
    body.update(over)
    return body


def test_builder_prompt_reports_a_missing_input_as_missing(monkeypatch, tmp_path) -> None:
    captured, files = _call_builder(monkeypatch, _body(), tmp_path)
    assert files == {WRITABLE: "# candidates\n"}
    user = json.loads(captured["messages"][1]["content"])
    verdict = user["input_visibility"][ABSENT_INPUT]
    assert verdict.startswith("NOT PRESENT")
    assert "invent" in verdict, "the verdict must forbid inventing content for a missing input"
    assert "NOT PRESENT" in captured["messages"][0]["content"], (
        "the builder system prompt never states the input-visibility rule")


def test_builder_prompt_marks_a_readable_input_and_shows_it(monkeypatch, tmp_path) -> None:
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "reading.md").write_text("2609.16270 - a stored title\n", encoding="utf-8")
    body = _body(input_paths=["notes/reading.md"], allowed_write_paths=[WRITABLE, "notes/reading.md"])
    captured, _ = _call_builder(monkeypatch, body, tmp_path)
    user = json.loads(captured["messages"][1]["content"])
    assert user["input_visibility"]["notes/reading.md"] == "PRESENT"
    assert user["current_contents"]["notes/reading.md"] == "2609.16270 - a stored title\n"


def test_builder_prompt_unchanged_when_no_inputs_declared(monkeypatch, tmp_path) -> None:
    """Backward compatibility: existing items carry no input_paths, and their prompt,
    including the system message, is byte-for-byte what it is today."""
    captured, files = _call_builder(monkeypatch, _body(input_paths=[]), tmp_path)
    assert files == {WRITABLE: "# candidates\n"}
    assert "input_visibility" not in json.loads(captured["messages"][1]["content"])
    assert captured["messages"][0]["content"] == (
        "You are Nara's builder for the lab. Make the acceptance test pass by writing complete file "
        "contents. Reply with ONLY a JSON object {\"files\": {\"<path>\": \"<full content>\"}} using only "
        "the writable_paths. Never modify the acceptance test. Standard library only unless the file "
        "already imports something else.")


def test_builder_prompt_reports_a_missing_input_that_is_also_writable(monkeypatch, tmp_path) -> None:
    """A writable path the builder must not write blind: a declared input that is absent
    is reported missing even when it is in allowed_write_paths - the seq-165 posting
    asked for exactly this combination."""
    body = _body(allowed_write_paths=[WRITABLE, ABSENT_INPUT])
    captured, _ = _call_builder(monkeypatch, body, tmp_path)
    user = json.loads(captured["messages"][1]["content"])
    assert user["current_contents"][ABSENT_INPUT] is None
    assert user["input_visibility"][ABSENT_INPUT].startswith("NOT PRESENT")


# --- review claude-80ce66157b935e62 (seq 188): a PRESENT verdict that never ships bytes
#
# Amendment 1: builder() judged a tracked-but-not-writable input PRESENT and then sent no
# content for it, because current_contents covers writable paths only. The lane told the
# model "PRESENT" about a file whose bytes it never received - the same class of defect
# this branch exists to close. Chosen fix: send the bytes. The alternative (admission
# refusing any input_paths entry that is not also writable) would forbid a genuinely
# readable, genuinely safe case: an input tracked at HEAD that the item must not rewrite.
#
# Amendment 3: an input denied by the path fence must be reported as outside the lane
# fence, not as "not a file tracked at the checkout HEAD", which is false - run_state/
# secrets.json can well be tracked.


def test_builder_sends_the_bytes_of_a_tracked_input_that_is_not_writable(monkeypatch, tmp_path) -> None:
    """The defect review seq 188 names: PRESENT, and no content.

    builder() is driven through its real seams: visibility is judged against a checkout
    whose HEAD tracks the input (the lane runs it with cwd=ROOT, whose HEAD the worktree
    is), and the bytes come from the worktree. tmp_path's git init prints a
    symlinks-resolved path on some platforms, so the HEAD is named by commit sha, which is
    identical however git spells the directory."""
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    _git(checkout, "init", "-q")
    _git(checkout, "config", "user.email", "t@example.invalid")
    _git(checkout, "config", "user.name", "Test")
    (checkout / TRACKED_INPUT).parent.mkdir(parents=True, exist_ok=True)
    (checkout / TRACKED_INPUT).write_text("iter-2026-09-23-035 - a stored claim\n", encoding="utf-8")
    _git(checkout, "add", "-A")
    _git(checkout, "commit", "-q", "-m", "base")
    head = _git(checkout, "rev-parse", "HEAD").strip()

    worktree = tmp_path / "worktree"
    subprocess.run(["git", "-c", "core.fsmonitor=false", "worktree", "add", "--detach",
                    str(worktree), head], cwd=checkout, check=True, capture_output=True, text=True)
    visibility = lane._input_visibility([TRACKED_INPUT], [], cwd=checkout, worktree=worktree)
    assert visibility[TRACKED_INPUT] == "PRESENT", visibility
    body = _body(input_paths=[TRACKED_INPUT])   # NOT in allowed_write_paths
    captured, _ = _call_builder(monkeypatch, body, worktree)
    user = json.loads(captured["messages"][1]["content"])
    assert user["input_visibility"][TRACKED_INPUT] == "PRESENT", user["input_visibility"]
    sent = user.get("input_contents", {})
    assert sent.get(TRACKED_INPUT) == "iter-2026-09-23-035 - a stored claim\n", (
        f"a PRESENT input reached the prompt with no bytes: keys={sorted(sent)}")


def test_a_present_input_that_is_absent_from_the_worktree_is_not_claimed(monkeypatch, tmp_path) -> None:
    """No invented content: PRESENT is computed from HEAD, so if the file is somehow not in
    the worktree the prompt must say so instead of shipping a PRESENT verdict with nothing."""
    body = _body(input_paths=[TRACKED_INPUT])
    captured, _ = _call_builder(monkeypatch, body, tmp_path)  # tmp_path holds no such file
    user = json.loads(captured["messages"][1]["content"])
    assert user["input_visibility"][TRACKED_INPUT].startswith("NOT PRESENT")
    assert TRACKED_INPUT not in user.get("input_contents", {})


def test_admission_says_outside_the_lane_fence_for_a_denied_input(repo) -> None:
    """Amendment 3: the reason must name the real cause."""
    reasons = lane.admission(_item(input_paths=["run_state/secrets.json"]), repo_root=repo)
    assert any("run_state/secrets.json" in r and "fence" in r.lower() for r in reasons), reasons
