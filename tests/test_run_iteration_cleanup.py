"""Regression: run_iteration cleanup runs on EVERY exit path (2026-06-10).

The set_run_id contextvar + live state files (active_iteration.json,
active_run.json) used to be cleaned only by finalize's narrow `finally`,
so any exception in the ~550-line chain body leaked them. In the
long-lived tool-plane process that stamped STALE iteration ids onto later
wrapper calls — the 2026-06-09 attribution bug. run_iteration is now a
registration wrapper with a try/finally around _run_iteration_impl.
"""
import json

import pytest

from agent_wrapper.wrapper import get_run_id
from orchestrator import active_run, nara


class _Recorder:
    """Minimal in-memory Runtime stub (state + events, no tools needed —
    the backend raises before any tool dispatch)."""

    def __init__(self):
        self.state: dict = {}
        self.events: list = []

    def dispatch_tool(self, name, args, *, parent_request_id):
        return {"status": "passed", "result": {}}

    def log_event(self, event, *, agent=None):
        self.events.append(event)

    def read_state(self, path):
        return self.state.get(path)

    def write_state(self, path, value):
        self.state[path] = json.loads(json.dumps(value))

    def delete_state(self, path):
        self.state.pop(path, None)


class _BoomBackend:
    """Raises on the first LLM turn — a mid-chain failure AFTER
    registration (set_run_id + active files) has happened."""

    name = "fake-backend"
    default_model = "fake-model"
    model_version = "fake/0"
    host_metadata: dict = {}

    def __init__(self, seen_run_ids):
        self._seen = seen_run_ids

    def create_chat(self, **kwargs):
        self._seen.append(get_run_id())
        raise RuntimeError("mid-chain boom")


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    """Keep the live run_state/ out of reach: active_run writes to tmp."""
    monkeypatch.setattr(
        active_run, "ACTIVE_RUN_PATH", tmp_path / "active_run.json"
    )
    ids = iter(f"iter-2099-01-01-{n:03d}" for n in (1, 2, 3))
    monkeypatch.setattr(nara, "_next_iteration_id", lambda *a, **k: next(ids))
    monkeypatch.setattr(
        nara, "_meta_review",
        lambda **k: {"status": "passed",
                     "result": {"conditioning_bullets": []}},
    )
    return tmp_path


def test_midchain_exception_clears_run_id_and_state(monkeypatch, isolated_state):
    seen: list = []
    rt = _Recorder()
    monkeypatch.setattr(nara, "get_backend", lambda *a, **k: _BoomBackend(seen))

    with pytest.raises(RuntimeError, match="mid-chain boom"):
        nara.run_iteration("leak topic", runtime=rt, log_path=None)

    # The turn DID run inside a registered context...
    assert seen == ["iter-2099-01-01-001"]
    # ...and every registration artifact is gone on the exception path.
    assert get_run_id() is None
    assert rt.read_state(nara.ACTIVE_PATH) is None
    assert not (isolated_state / "active_run.json").exists()


def test_consecutive_iterations_never_share_run_id(monkeypatch, isolated_state):
    seen: list = []
    rt = _Recorder()
    monkeypatch.setattr(nara, "get_backend", lambda *a, **k: _BoomBackend(seen))

    for _ in range(2):
        with pytest.raises(RuntimeError, match="mid-chain boom"):
            nara.run_iteration("leak topic", runtime=rt, log_path=None)
        # The leak bug's signature: the NEXT call inherits the prior id.
        assert get_run_id() is None

    assert seen == ["iter-2099-01-01-001", "iter-2099-01-01-002"]
    assert seen[0] != seen[1]


def test_steps_board_initialized_and_marked(monkeypatch, isolated_state):
    """The planned-chain board exists from the first write and meta_review
    is marked on it (the chips contract the UI renders from)."""
    rt = _Recorder()
    seen: list = []
    monkeypatch.setattr(nara, "get_backend", lambda *a, **k: _BoomBackend(seen))

    with pytest.raises(RuntimeError):
        nara.run_iteration("leak topic", runtime=rt, log_path=None)

    step_events = [e for e in rt.events
                   if e.get("event_type") == "loop_v0_active_step"]
    assert {"step": "meta_review", "status": "running"}.items() <= {
        k: step_events[0][k] for k in ("step", "status")
    }.items()
    assert any(e["step"] == "meta_review" and e["status"] == "passed"
               for e in step_events)
