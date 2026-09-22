"""Context-capacity eval driver and probes; no model, container or service use."""
import json
import threading
from types import SimpleNamespace

import pytest

from bench.flash_context_eval import driver, probes


def test_prompts_are_deterministic_and_scorable():
    a, expected = probes.needle_prompt(3000, seed=11)
    b, again = probes.needle_prompt(3000, seed=11)
    assert a == b and expected == again and len(expected) == 4
    answer = json.dumps(expected)
    assert probes.score_needles(answer, expected) == 1.0
    wrong = dict(expected, **{next(iter(expected)): "0000000"})
    assert probes.score_needles(json.dumps(wrong), expected) == 0.75
    prompt, chain = probes.vartrack_prompt(3000, seed=5)
    assert len(chain) == 5 and all(name in prompt for name in chain)
    assert probes.score_vartrack(json.dumps(chain), chain)["exact"]
    assert probes.score_vartrack(json.dumps(chain[:2]), chain)["recall"] == 0.4


def test_stream_chat_measures_first_token_and_usage(monkeypatch):
    lines = [b'data: {"choices":[{"delta":{"content":"hel"}}]}\n',
             b'data: {"choices":[{"delta":{"content":"lo"},"finish_reason":"stop"}]}\n',
             b'data: {"choices":[],"usage":{"prompt_tokens":12,"completion_tokens":3}}\n',
             b"data: [DONE]\n"]

    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def __iter__(self): return iter(lines)

    monkeypatch.setattr(probes.urllib.request, "build_opener",
                        lambda *_: SimpleNamespace(open=lambda request, timeout: Response()))
    result = probes.stream_chat("hi", 4)
    assert result["text"] == "hello" and result["prompt_tokens"] == 12
    assert result["completion_tokens"] == 3 and result["finish_reason"] == "stop"
    assert result["ttft_s"] is not None and result["status"] == 200


def _helper(tmp_path, events, *, fail_ready=False):
    class Monitor:
        failure = None
        def __init__(self, *args): events.append("monitor_init")
        def start(self): events.append("monitor_start")
        def arm_passive_models(self): pass
        def check(self): pass
        def quiesce(self): events.append("quiesce")
        def summary(self): return {"minimum_mem_available_gib": 21.0}

    class Stopper:
        def __init__(self, *args): pass
        def stop(self, reason): events.append("container_stop")

    def ready(*args):
        if fail_ready:
            raise RuntimeError("KernelDriverFault: kernel_driver_or_allocation_failure")

    return SimpleNamespace(
        configure_profile=lambda name: {"profile": name},
        verify_control_sources=lambda: None, inspect_image=lambda ops: None,
        verify_checkpoint_receipt=lambda *a: None, assert_no_fallback_or_transition=lambda ops: None,
        assert_port_free=lambda: None, q=SimpleNamespace(HostOps=lambda: object()),
        MODEL_ROOT=tmp_path / "model", CACHE=tmp_path / "cache", STARTUP_DEADLINE_S=10,
        launch_guard=lambda *a: (SimpleNamespace(pid=1, poll=lambda: None), SimpleNamespace(close=lambda: None), 2),
        wait_launch_record=lambda *a: {"cid": "c"}, capture_candidate_allocator_environment=lambda *a: None,
        GuardStopper=Stopper, RuntimeMonitor=Monitor, wait_ready=ready,
        model_identity_projection=lambda value: value, exact_models=lambda timeout: {"max_model_len": 65536},
        terminate_guard_process=lambda *a: events.append("guard_terminated"),
        finalize_owned_fallback=lambda *a: events.append("finalized") or {"status": "removed"},
    )


def _resident(monkeypatch, tmp_path, free_gib=110):
    monkeypatch.setattr(driver.resident, "PREP", tmp_path)
    (tmp_path / "runtime").mkdir(exist_ok=True)
    monkeypatch.setattr(driver.resident, "evict_model_page_cache", lambda roots: 3)
    monkeypatch.setattr(driver.resident, "host_memory_kib",
                        lambda: {"MemFree": free_gib * 1024**2, "MemAvailable": 118 * 1024**2, "Cached": 1})


def test_failed_tier_still_removes_its_container(tmp_path, monkeypatch):
    _resident(monkeypatch, tmp_path)
    events = []
    result = driver.run_tier(_helper(tmp_path, events, fail_ready=True), 65536, threading.Event())
    assert not result["passed"] and "KernelDriverFault" in result["error"]
    assert events[-4:] == ["quiesce", "container_stop", "guard_terminated", "finalized"]
    assert result["prelaunch"]["evicted_files"] == 3


def test_prelaunch_floor_refuses_before_launch(tmp_path, monkeypatch):
    _resident(monkeypatch, tmp_path, free_gib=70)
    events = []
    result = driver.run_tier(_helper(tmp_path, events), 131072, threading.Event())
    assert result["error"] == "prelaunch MemFree below floor" and events == []


def test_escalation_stops_at_first_failure_and_resident_is_restored(tmp_path, monkeypatch):
    calls, tiers = [], []
    monkeypatch.setattr(driver, "load_helper", lambda: SimpleNamespace(resource_lease=lambda root: _Lease()))
    ready = iter([True, True])
    monkeypatch.setattr(driver.resident, "check_ready", lambda root=None: next(ready))
    monkeypatch.setattr(driver, "systemctl", lambda *args, timeout=60: calls.append(args) or "")
    monkeypatch.setattr(driver.resident, "STATE", tmp_path / "state.json")
    (tmp_path / "state.json").write_text(json.dumps({"phase": "stopped"}))
    monkeypatch.setattr(driver, "RUN_LOG", tmp_path / "run.jsonl")
    monkeypatch.setattr(driver, "run_tier", lambda helper, context, stop: tiers.append(context) or
                        {"context": context, "passed": context == 65536})
    assert driver.main(["--out", str(tmp_path / "out"), "--take-resident-offline"]) == 0
    assert tiers == [65536, 131072]  # 262144 is not attempted after a failure
    assert ("stop", "flash-resident.service") in calls and ("start", "flash-resident.service") in calls
    report = json.loads((tmp_path / "out/report.json").read_text())
    assert report["largest_passing_context"] == 65536 and report["resident_restored"]


def test_refuses_without_explicit_downtime_flag_or_pinned_helper(tmp_path):
    with pytest.raises(SystemExit, match="take-resident-offline"):
        driver.main(["--out", str(tmp_path / "x")])
    missing = tmp_path / "absent_helper.py"
    missing.write_text("tampered")
    driver_helper, driver.EVAL_HELPER = driver.EVAL_HELPER, missing
    try:
        with pytest.raises(RuntimeError, match="bytes changed"):
            driver.load_helper()
    finally:
        driver.EVAL_HELPER = driver_helper


class _Lease:
    def __enter__(self): return self
    def __exit__(self, *_): return False
