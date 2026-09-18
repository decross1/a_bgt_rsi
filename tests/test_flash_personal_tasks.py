import socket

import pytest

from bench.flash_next_ab.personal_tasks import (
    CODING_TASKS,
    POLICIES,
    SCIENCE_TASKS,
    SandboxTools,
    grade_science,
    materialize_coding_task,
    run_coding_check,
    summarize_attempts,
    task_manifest,
)

REPAIRS = {
    "code-csv-paid-total": '''import csv
import io
from decimal import Decimal, InvalidOperation


def paid_total(csv_text):
    reader = csv.DictReader(io.StringIO(csv_text, newline=""))
    expected = ["order_id", "status", "amount"]
    if reader.fieldnames != expected:
        raise ValueError("invalid header")
    total = Decimal("0")
    for row in reader:
        if None in row:
            raise ValueError("invalid row")
        if row["status"] != "paid":
            continue
        try:
            amount = Decimal(row["amount"])
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("invalid paid amount") from exc
        if not amount.is_finite():
            raise ValueError("invalid paid amount")
        total += amount
    return format(total, ".2f")
''',
    "code-half-open-intervals": '''def merge_half_open(intervals):
    copied = []
    for interval in intervals:
        if not isinstance(interval, (list, tuple)) or len(interval) != 2:
            raise ValueError("invalid interval")
        start, end = interval
        if type(start) is not int or type(end) is not int or start >= end:
            raise ValueError("invalid interval")
        copied.append([start, end])
    result = []
    for start, end in sorted(copied):
        if result and start < result[-1][1]:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([start, end])
    return result
''',
    "code-injected-ttl-cache": '''import math


class TTLCache:
    def __init__(self, clock):
        self._clock = clock
        self._data = {}

    def set(self, key, value, ttl_s):
        if isinstance(ttl_s, bool) or not isinstance(ttl_s, (int, float)) or not math.isfinite(ttl_s) or ttl_s <= 0:
            raise ValueError("invalid ttl")
        self._data[key] = (value, self._clock() + ttl_s)

    def get(self, key):
        item = self._data.get(key)
        if item is None:
            return None
        value, expires = item
        if self._clock() >= expires:
            del self._data[key]
            return None
        return value
''',
    "code-jsonl-metrics": '''import json
import math


def summarize(text):
    values = []
    invalid = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            invalid += 1
            continue
        value = row.get("latency_ms") if isinstance(row, dict) else None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            invalid += 1
            continue
        values.append(value)
    mean = round(sum(values) / len(values), 3) if values else None
    return {"valid": len(values), "invalid": invalid, "mean_latency_ms": mean}
''',
    "code-mixed-payoffs": '''import math


def _number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _strategy(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2 or not all(_number(item) and 0 <= item <= 1 for item in value) or abs(sum(value) - 1) > 1e-9:
        raise ValueError("invalid strategy")


def _matrix(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2 or any(not isinstance(row, (list, tuple)) or len(row) != 2 or not all(_number(item) for item in row) for row in value):
        raise ValueError("invalid matrix")


def expected_payoffs(row_strategy, column_strategy, row_payoffs, column_payoffs):
    _strategy(row_strategy)
    _strategy(column_strategy)
    _matrix(row_payoffs)
    _matrix(column_payoffs)
    row_total = column_total = 0.0
    for i in range(2):
        for j in range(2):
            probability = row_strategy[i] * column_strategy[j]
            row_total += probability * row_payoffs[i][j]
            column_total += probability * column_payoffs[i][j]
    return row_total, column_total
''',
}


def test_manifest_is_answer_free_five_plus_five_with_explicit_policies():
    manifest = task_manifest()
    assert manifest["schema"] == "flash-personal-usability-panel/v1"
    assert len(manifest["manifest_sha256"]) == 64
    assert [row["id"] for row in manifest["policies"]] == ["off", "medium"]
    assert manifest["policies"][0] == {
        "id": "off",
        "enable_thinking": False,
        "reasoning_effort": None,
        "temperature": 0.7,
        "top_p": 0.8,
        "top_k": 20,
        "max_output_tokens": 8192,
        "request_timeout_s": 300.0,
        "task_deadline_s": 900.0,
        "max_turns": 8,
    }
    assert manifest["policies"][1]["reasoning_effort"] == "medium"
    assert manifest["policies"][1]["max_output_tokens"] == 16384
    assert manifest["policies"][1]["task_deadline_s"] == 900.0
    assert len(manifest["tasks"]) == 10
    assert [row["kind"] for row in manifest["tasks"]].count("science") == 5
    assert [row["kind"] for row in manifest["tasks"]].count("coding") == 5
    assert all("expected_json" not in row and "answer" not in row for row in manifest["tasks"])
    assert all(row["policy_ids"] == ["off", "medium"] for row in manifest["tasks"])


@pytest.mark.parametrize("task", SCIENCE_TASKS, ids=lambda task: task.id)
def test_science_graders_separate_semantics_from_representation(task):
    canonical = grade_science(task.id, f"calculation\n<final>{task.expected_json}</final>")
    assert canonical == {
        "task_id": task.id,
        "passed": True,
        "classification": "passed",
        "contract_ok": True,
        "semantic_ok": True,
    }
    presentation = grade_science(task.id, f"```json\n{task.expected_json}\n```")
    assert presentation["classification"] == "representation_only_failure"
    assert presentation["semantic_ok"] is True
    assert grade_science(task.id, "<final>{\"wrong\": 1}</final>")["classification"] == "wrong_semantics"
    assert grade_science(task.id, "   ")["classification"] == "no_final"


@pytest.mark.parametrize("task", CODING_TASKS, ids=lambda task: task.id)
def test_each_coding_task_starts_broken_and_has_a_semantic_repair(tmp_path, task):
    plan = materialize_coding_task(task.id, tmp_path / task.id)
    initial = run_coding_check(plan)
    assert initial["passed"] is False
    assert initial["classification"] == "wrong_semantics"

    tools = SandboxTools(plan)
    listing = tools("list_files", {})
    assert {row["path"] for row in listing["files"]} == set(plan.declared_paths)
    assert tools("read_file", {"path": task.editable_paths[0]})["content"]
    tools("write_file", {"path": task.editable_paths[0], "content": REPAIRS[task.id]})
    visible = tools("run_tests", {})
    assert visible["timed_out"] is False
    assert visible["return_code"] == 0, visible["stderr"]
    checked = run_coding_check(plan)
    assert checked["passed"] is True, checked["stderr"]
    assert tools.receipt()["reads"] == 1
    assert tools.receipt()["writes"] == 1
    assert tools.receipt()["test_runs"] == 1


def test_coding_tools_reject_escape_and_read_only_edits(tmp_path):
    plan = materialize_coding_task(CODING_TASKS[0].id, tmp_path / "task")
    tools = SandboxTools(plan)
    with pytest.raises(ValueError, match="escapes"):
        tools("read_file", {"path": "../outside"})
    with pytest.raises(ValueError, match="outside"):
        tools("write_file", {"path": "test_orders.py", "content": "pass\n"})
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "keep").write_text("keep")
    with pytest.raises(ValueError, match="absent or an empty"):
        materialize_coding_task(CODING_TASKS[0].id, occupied)
    assert (occupied / "keep").read_text() == "keep"


def test_generated_code_cannot_see_verifier_host_files_or_network(tmp_path):
    plan = materialize_coding_task(CODING_TASKS[0].id, tmp_path / "isolated")
    host_marker = tmp_path / "host-marker"
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    server.settimeout(0.1)
    port = server.getsockname()[1]
    probe = f'''from pathlib import Path
import socket
try:
    hidden = Path("/control/verify.py").read_text()
except OSError:
    print("CONTROL_INACCESSIBLE")
else:
    print("HIDDEN_LEAK:" + hidden)
target = Path({str(host_marker)!r})
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text("sandbox-only")
try:
    socket.create_connection(("127.0.0.1", {port}), timeout=0.05).close()
except OSError:
    pass
'''
    tools = SandboxTools(plan)
    tools("write_file", {
        "path": "orders.py", "content": probe + REPAIRS[CODING_TASKS[0].id],
    })
    visible = tools("run_tests", {})
    assert visible["return_code"] == 0, visible["stderr"]
    assert "CONTROL_INACCESSIBLE" in visible["stdout"]
    assert "HIDDEN_LEAK:" not in visible["stdout"]
    assert run_coding_check(plan)["passed"] is True
    assert not host_marker.exists()
    with pytest.raises(TimeoutError):
        server.accept()
    server.close()


def test_attempt_summary_keeps_failure_modes_and_usability_axes_separate():
    summary = summarize_attempts([
        {"classification": "passed", "interventions": 3, "elapsed_s": 2.5},
        {"classification": "representation_only_failure", "interventions": 0, "elapsed_s": 1},
        {"classification": "wrong_semantics", "interventions": 2, "elapsed_s": 4},
        {"classification": "no_final", "interventions": 1, "elapsed_s": 5},
        {"classification": "parser_error", "interventions": 0, "elapsed_s": 0.5},
        {"classification": "exhausted", "interventions": 4, "elapsed_s": 10},
        {"classification": "runner_error", "interventions": 0, "elapsed_s": 0.25},
    ])
    assert summary["attempts"] == 7
    assert summary["completed"] == 3
    assert summary["correct"] == 1
    assert summary["interventions"] == 10
    assert summary["exhausted"] == 1
    assert summary["elapsed_s"] == 23.25
    assert summary["classifications"]["representation_only_failure"] == 1
    assert summary["classifications"]["runner_error"] == 1


def test_policy_objects_match_the_two_declared_request_modes():
    off, medium = POLICIES
    assert off.inference_policy() == {
        "temperature": 0.7,
        "top_p": 0.8,
        "top_k": 20,
        "enable_thinking": False,
    }
    assert medium.inference_policy() == {
        "temperature": 1.0,
        "top_p": 0.95,
        "top_k": 20,
        "enable_thinking": True,
        "reasoning_effort": "medium",
    }
