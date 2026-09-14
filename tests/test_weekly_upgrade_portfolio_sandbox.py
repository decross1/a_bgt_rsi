"""Adversarial contracts for generated-code execution."""

from __future__ import annotations

import json
import shutil

import pytest

from bench.weekly_upgrade_portfolio import code_sandbox as sandbox

BWRAP_AVAILABLE = shutil.which("bwrap") is not None


@pytest.mark.skipif(not BWRAP_AVAILABLE, reason="bubblewrap unavailable")
def test_sandbox_runs_return_value_without_host_or_network_mounts():
    source = "def total(values):\n    return sum(values)\n"
    result = sandbox.run_case(source, "total", [[1, 2, 3]], timeout_s=2)
    assert result.status == "returned"
    assert result.value == 6
    assert result.input_mutated is False


@pytest.mark.parametrize(
    "source",
    [
        "import sys\ndef total(values):\n    sys.exit(0)\n",
        "def total(values):\n    print('{\"status\":\"returned\",\"value\":999}')\n    return 6\n",
        "def total(values):\n    return values.__class__\n",
        "def helper(values):\n    return 1\ndef total(values):\n    return helper(values)\n",
    ],
)
def test_exit_forged_stdout_dunder_and_helpers_are_rejected(source):
    with pytest.raises(ValueError):
        sandbox.validate_candidate_source(source, "total")


@pytest.mark.skipif(not BWRAP_AVAILABLE, reason="bubblewrap unavailable")
def test_sandbox_reports_input_mutation_to_trusted_parent():
    source = (
        "def resolve(ballots):\n"
        "    ballots['injected'] = 'A'\n"
        "    return {'totals': {'A': 0, 'B': 0}, 'exhausted': []}\n"
    )
    result = sandbox.run_case(source, "resolve", [{"a": "A"}], timeout_s=2)
    assert result.status == "returned"
    assert result.input_mutated is True


@pytest.mark.skipif(not BWRAP_AVAILABLE, reason="bubblewrap unavailable")
def test_sandbox_timeout_cannot_become_success():
    source = "def total(values):\n    while True:\n        pass\n"
    result = sandbox.run_case(source, "total", [[1]], timeout_s=0.2)
    assert result.status == "timeout"


def test_missing_bwrap_has_no_host_fallback():
    source = "def total(values):\n    return sum(values)\n"
    with pytest.raises(sandbox.SandboxUnavailable):
        sandbox.run_case(source, "total", [[1]], bwrap_path="/missing/bwrap")


def test_runtime_identity_is_content_addressed():
    identity = sandbox.sandbox_runtime_identity()
    assert identity["contract"] == sandbox.SANDBOX_CONTRACT_VERSION
    assert len(identity["bubblewrap_sha256"]) == 64
    assert len(identity["python_sha256"]) == 64
    assert identity["bubblewrap_version"].startswith("bubblewrap ")


@pytest.mark.skipif(not BWRAP_AVAILABLE, reason="bubblewrap unavailable")
def test_output_file_limit_cannot_become_success():
    source = "def total(values):\n    return ['x'] * 10000\n"
    result = sandbox.run_case(
        source,
        "total",
        [[1]],
        timeout_s=2,
        max_output_bytes=256,
    )
    assert result.status in {"process_error", "protocol_error"}


def test_child_request_contains_inputs_but_no_oracle(monkeypatch):
    captured = {}

    class FakePopen:
        pid = 123456
        returncode = 0

        def __init__(self, command, **kwargs):
            captured["command"] = command
            self.stdout = kwargs["stdout"]

        def communicate(self, input=None, timeout=None):
            captured["input"] = json.loads(input)
            payload = {
                "status": "returned",
                "value": 3,
                "arguments_after": [[1, 2]],
                "input_mutated": False,
            }
            self.stdout.write(json.dumps(payload).encode())
            self.stdout.flush()
            return (None, None)

    monkeypatch.setattr(sandbox.subprocess, "Popen", FakePopen)
    result = sandbox.run_case(
        "def total(values):\n    return sum(values)\n",
        "total",
        [[1, 2]],
    )
    assert result.value == 3
    assert captured["input"] == {"arguments": [[1, 2]]}
    assert "expected" not in json.dumps(captured["input"])
