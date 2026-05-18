"""Synthetic JSONL fixtures for the backend chain walker.

The apparatus's real call log (day 2) and orchestrator log (day 6) do not
exist yet. These fixtures mirror the *structural* fields ui_plan.md
section 4.2 pins as stable -- request_id, parent_request_id, caller_tag,
task_id, status, timestamps -- and carry plausible opaque payload fields
(model, prompt_messages, completion, usage, host_metadata) so the chain
walker and inspector can be developed before the day-2 schema lands.

Run as a CLI to produce a log directory the backend can be pointed at:

  cd ui && python3 -m backend.tests.fixtures.gen /tmp/fixture_logs
  UI_LOGS_DIR=/tmp/fixture_logs ui/backend/run.sh
"""
import json
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

_BASE_TS = datetime(2026, 5, 18, 10, 0, 0, tzinfo=timezone.utc)


class Call:
    """One synthetic wrapper/tool call node in a chain."""

    def __init__(self, caller_tag, latency_ms, children=None, parse_error=False):
        self.caller_tag = caller_tag
        self.latency_ms = latency_ms
        self.children = children or []
        self.parse_error = parse_error


def call(caller_tag, latency_ms, children=None, parse_error=False):
    return Call(caller_tag, latency_ms, children, parse_error)


# Hand-defined chains with known shapes so tests can assert exact
# reconstruction. Coverage: a passed task with a tool call, a failed task
# with a parse-error node, a still-running task, and an experiment task
# with two tool calls. Each task's `tree` is the single top "worker" call;
# the orchestrator dispatch node is its parent.
TASKS = [
    dict(task_id="day6_task_01", task_type="repeated_pd_dryrun",
         status="passed", worker_pid=20111, log_file="day6_5seq.jsonl",
         tree=call("worker", 1850, [
             call("wrapper", 420),
             call("wrapper", 700, [call("tool", 95)]),
             call("wrapper", 510),
         ])),
    dict(task_id="day6_task_02", task_type="repeated_pd_dryrun",
         status="failed", worker_pid=20140, log_file="day6_5seq.jsonl",
         tree=call("worker", 980, [
             call("wrapper", 380),
             call("wrapper", 120, parse_error=True),
         ])),
    dict(task_id="day6_task_03", task_type="needle_probe",
         status="started", worker_pid=20177, log_file="day6_5seq.jsonl",
         tree=call("worker", 250, [call("wrapper", 250)])),
    dict(task_id="exp001_round_07", task_type="exp001_repeated_pd",
         status="passed", worker_pid=21003, log_file="exp001.jsonl",
         tree=call("worker", 3200, [
             call("wrapper", 600, [call("tool", 110), call("tool", 130)]),
             call("wrapper", 720),
         ])),
]


def _count(node):
    return 1 + sum(_count(child) for child in node.children)


def _latency_sum(node):
    return node.latency_ms + sum(_latency_sum(child) for child in node.children)


def expected_manifest():
    """{task_id: {node_count, total_latency_ms, status}} computed from TASKS.

    node_count includes the orchestrator dispatch node (the tree root).
    """
    return {
        task["task_id"]: {
            "node_count": 1 + _count(task["tree"]),
            "total_latency_ms": _latency_sum(task["tree"]),
            "status": task["status"],
        }
        for task in TASKS
    }


def _uuid(rng):
    return str(uuid.UUID(int=rng.getrandbits(128)))


def _call_record(node, request_id, parent_request_id, ts, rng):
    record = {
        "request_id": request_id,
        "parent_request_id": parent_request_id,
        "caller_tag": node.caller_tag,
        "timestamp": ts.isoformat(timespec="milliseconds"),
        "latency_ms": node.latency_ms,
        "model": "gemma-4-26b-a4b-nvfp4",
        "model_version": "sha256:" + "".join(
            rng.choice("0123456789abcdef") for _ in range(12)),
        "temperature": 0.7,
        "top_p": 0.95,
        "seed": rng.randint(1, 2 ** 31 - 1),
        "prompt_messages": [
            {"role": "system", "content": "You are playing a repeated game."},
            {"role": "user", "content": f"[{node.caller_tag}] round prompt"},
        ],
        "completion": f"[{node.caller_tag}] response {rng.randint(0, 9999)}",
        "usage": {"input_tokens": rng.randint(80, 600),
                  "output_tokens": rng.randint(20, 240)},
        "host_metadata": {"cuda_driver": "13.0",
                          "vllm_image_tag": "vllm/vllm-openai:gemma4-cu130"},
    }
    if node.parse_error:
        record["parse_error"] = True
    return record


def _emit_tree(node, parent_request_id, ts, rng, out):
    request_id = _uuid(rng)
    out.append(_call_record(node, request_id, parent_request_id, ts, rng))
    child_ts = ts
    step = node.latency_ms // max(1, len(node.children))
    for child in node.children:
        child_ts = child_ts + timedelta(milliseconds=step)
        _emit_tree(child, request_id, child_ts, rng, out)
    return request_id


def write_fixtures(out_dir, seed=20260518):
    """Write orchestrator.jsonl + call logs into out_dir. Returns expected_manifest()."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)

    orchestrator_lines = []
    call_files = {}                              # filename -> [call records]

    for index, task in enumerate(TASKS):
        dispatch_ts = _BASE_TS + timedelta(minutes=index * 3)
        root_request_id = _uuid(rng)
        calls = []
        _emit_tree(task["tree"], root_request_id,
                   dispatch_ts + timedelta(milliseconds=5), rng, calls)
        call_files.setdefault(task["log_file"], []).extend(calls)

        receipt_ts = None
        if task["status"] != "started":
            receipt_ts = (dispatch_ts
                          + timedelta(milliseconds=_latency_sum(task["tree"])))
        orchestrator_lines.append({
            "task_id": task["task_id"],
            "task_type": task["task_type"],
            "status": task["status"],
            "worker_pid": task["worker_pid"],
            "parent_request_id": root_request_id,
            "dispatch_ts": dispatch_ts.isoformat(timespec="milliseconds"),
            "receipt_ts": (receipt_ts.isoformat(timespec="milliseconds")
                           if receipt_ts else None),
        })

    _write_jsonl(out_dir / "orchestrator.jsonl", orchestrator_lines)
    for filename, records in call_files.items():
        _write_jsonl(out_dir / filename, records)
    return expected_manifest()


def _write_jsonl(path, records):
    with open(path, "w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    out_dir = argv[0] if argv else "./fixture_logs"
    manifest = write_fixtures(out_dir)
    print(f"wrote fixtures to {out_dir}/")
    for task_id, info in manifest.items():
        print(f"  {task_id}: {info['node_count']} nodes, "
              f"{info['total_latency_ms']} ms total, {info['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
