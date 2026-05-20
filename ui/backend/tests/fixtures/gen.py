"""Synthetic JSONL fixtures for the backend chain walker.

The apparatus's real call log (day 2) and orchestrator log (day 6) do not
exist yet. These fixtures mirror the *structural* fields ui_plan.md
section 4.2 pins as stable -- request_id, parent_request_id, caller_tag,
task_id, status, timestamps -- and carry plausible opaque payload fields
(model, prompt_messages, completion, usage, host_metadata) so the chain
walker and inspector can be developed before the day-2 schema lands.

`write_day4_fixtures` adds the day-4 surfaces (Track D day-4 sync):
- `day4_e2e.jsonl`: two-link tool-call chains rooted at a wrapper request
  (no orchestrator dispatch — chains land before day 6's orchestrator).
  One chain carries a malformed-JSON `tool_calls` string so the inspector
  can render the red banner without silent format-fixing.
- `day4_robust.jsonl`: per-trial invocation outcomes with latencies, so
  the robustness panel has invocation rate + median latency to compute.
- `events.jsonl`: forward-compatible day-3.5 stub — one
  `human_intervention` and one `calibration_entry` event. The schema for
  events.jsonl has not been committed yet, so the inspector reads it
  generically; this fixture documents the shapes the UI expects.

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
    """One synthetic wrapper/tool call node in a chain.

    `embedded_tools` carries the second tool-call shape (ui_plan.md section 9):
    a list of dicts written into the wrapper record's `tool_calls` field rather
    than emitted as their own call-log lines. The chain walker synthesizes them
    into child nodes that count toward node_count and total_latency_ms, exactly
    as separate-line tool calls do.
    """

    def __init__(self, caller_tag, latency_ms, children=None, parse_error=False,
                 embedded_tools=None):
        self.caller_tag = caller_tag
        self.latency_ms = latency_ms
        self.children = children or []
        self.parse_error = parse_error
        self.embedded_tools = embedded_tools or []


def call(caller_tag, latency_ms, children=None, parse_error=False,
         embedded_tools=None):
    return Call(caller_tag, latency_ms, children, parse_error, embedded_tools)


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
    dict(task_id="day6_task_04", task_type="needle_probe",
         status="passed", worker_pid=20210, log_file="day6_5seq.jsonl",
         tree=call("worker", 1400, [
             call("wrapper", 900, embedded_tools=[
                 {"name": "semantic_scholar_search", "latency_ms": 88,
                  "arguments": {"query": "repeated prisoner's dilemma"},
                  "result": "3 papers"},
                 {"name": "chroma_query", "latency_ms": 42,
                  "arguments": {"k": 5}, "result": "5 hits"},
             ]),
             call("wrapper", 360),
         ])),
    dict(task_id="exp001_round_07", task_type="exp001_repeated_pd",
         status="passed", worker_pid=21003, log_file="exp001.jsonl",
         tree=call("worker", 3200, [
             call("wrapper", 600, [call("tool", 110), call("tool", 130)]),
             call("wrapper", 720),
         ])),
]


def _count(node):
    # Embedded tools become tree nodes (counted), separate-line children recurse.
    return (1
            + sum(_count(child) for child in node.children)
            + len(node.embedded_tools))


def _latency_sum(node):
    # Mirrors build_chain.tally: every node contributes, embedded tools too.
    return (node.latency_ms
            + sum(_latency_sum(child) for child in node.children)
            + sum(tool.get("latency_ms", 0) for tool in node.embedded_tools))


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
                          "vllm_image_tag": "vllm/vllm-openai:v0.21.0"},
    }
    if node.parse_error:
        record["parse_error"] = True
    if node.embedded_tools:
        # Second tool-call shape: tools embedded in the wrapper record rather
        # than emitted as their own call-log lines (ui_plan.md section 9).
        record["tool_calls"] = [dict(tool) for tool in node.embedded_tools]
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


# --- day-4 surfaces (Track D day-4 sync) ---
#
# Day-4 chains begin before day 6's orchestrator runs, so they are rooted at a
# wrapper request_id (no orchestrator.jsonl dispatch). The chain-by-request_id
# walker is the read path; tests assert it against this manifest.

# Two two-link chains and one chain with a malformed-JSON tool_calls payload
# (deliberately a string rather than a list — the kind of corrupted record an
# upstream serializer bug could produce). The malformed_tool_calls count is
# what the inspector surfaces as a red banner.
DAY4_E2E_CHAINS = [
    {
        "name": "day4_chain_search",
        "root": call("wrapper", 540, [
            call("tool", 88, embedded_tools=None),
            call("tool", 72),
        ]),
    },
    {
        "name": "day4_chain_retrieve",
        "root": call("wrapper", 410, [
            call("tool", 65),
        ]),
    },
    {
        "name": "day4_chain_malformed",
        "root": call("wrapper", 320, [
            # parse_error on the wrapper itself surfaces the red banner;
            # see _emit_day4 below for the malformed tool_calls payload.
            call("tool", 95, parse_error=True),
        ]),
    },
]


def _day4_record(node, request_id, parent_request_id, ts, rng,
                 malformed_tool_calls=False):
    record = _call_record(node, request_id, parent_request_id, ts, rng)
    if malformed_tool_calls:
        # Deliberately wrong shape: an upstream serializer wrote the tool_calls
        # array as a JSON string rather than a list. The inspector must surface
        # this as a parse error, not silently format-fix it.
        record["tool_calls"] = '[{"name": "broken", "arguments": "{not json'
        record["parse_error"] = True
    return record


def _emit_day4_chain(chain, ts, rng, out):
    """Emit a day-4 tool-call chain rooted at a wrapper request. Returns the root request_id."""
    root_id = _uuid(rng)
    is_malformed = chain["name"].endswith("_malformed")
    out.append(_day4_record(chain["root"], root_id, None, ts, rng,
                            malformed_tool_calls=is_malformed))
    child_ts = ts
    step = chain["root"].latency_ms // max(1, len(chain["root"].children))
    for child in chain["root"].children:
        child_ts = child_ts + timedelta(milliseconds=step)
        cid = _uuid(rng)
        out.append(_call_record(child, cid, root_id, child_ts, rng))
    return root_id


DAY4_ROBUST_TRIALS = [
    # 10 trials: 8 invocations succeeded with various latencies, 2 missed
    # (the agent did not emit a tool call). Median latency over successes is
    # 145 ms. invocation_rate = 8/10 = 0.8.
    {"trial_id": 1,  "invoked": True,  "outcome": "ok",      "latency_ms": 92},
    {"trial_id": 2,  "invoked": True,  "outcome": "ok",      "latency_ms": 110},
    {"trial_id": 3,  "invoked": False, "outcome": "missed",  "latency_ms": None},
    {"trial_id": 4,  "invoked": True,  "outcome": "ok",      "latency_ms": 140},
    {"trial_id": 5,  "invoked": True,  "outcome": "ok",      "latency_ms": 150},
    {"trial_id": 6,  "invoked": True,  "outcome": "ok",      "latency_ms": 165},
    {"trial_id": 7,  "invoked": False, "outcome": "missed",  "latency_ms": None},
    {"trial_id": 8,  "invoked": True,  "outcome": "ok",      "latency_ms": 175},
    {"trial_id": 9,  "invoked": True,  "outcome": "timeout", "latency_ms": 3000},
    {"trial_id": 10, "invoked": True,  "outcome": "ok",      "latency_ms": 130},
]


def day4_robust_expected():
    """{trials, invocations, invocation_rate, median_latency_ms} for tests.

    Mirrors statistics.median (the reader's definition): for an even-length
    list the median averages the two middle values, so for 8 latencies the
    result is (latencies[3] + latencies[4]) / 2, not latencies[4].
    """
    import statistics as _stats
    invocations = [t for t in DAY4_ROBUST_TRIALS if t["invoked"]]
    latencies = [t["latency_ms"] for t in invocations
                 if isinstance(t["latency_ms"], (int, float))]
    median = _stats.median(latencies) if latencies else None
    return {
        "trials": len(DAY4_ROBUST_TRIALS),
        "invocations": len(invocations),
        "invocation_rate": round(len(invocations) / len(DAY4_ROBUST_TRIALS), 3),
        "median_latency_ms": median,
    }


EVENTS_FIXTURES = [
    # human_intervention: human pauses or unblocks the apparatus mid-run.
    {"timestamp": "2026-05-19T11:15:42.000+00:00",
     "event_type": "human_intervention",
     "actor": "operator",
     "subject": "day3_5_gate",
     "note": "approved schema additions; resuming run"},
    # calibration_entry: tally for a per-output calibration sweep.
    {"timestamp": "2026-05-19T11:32:08.000+00:00",
     "event_type": "calibration_entry",
     "metric": "decode_tok_per_s",
     "observed": 69.4,
     "expected_band": [80, 130],
     "verdict": "below_band"},
]


def write_day4_fixtures(out_dir, seed=20260520):
    """Write day-4 e2e, robust, and events fixtures into out_dir.

    Returns a manifest with:
      - chains: {chain_name: root_request_id} for chain-by-request_id tests
      - robust: day4_robust_expected()
      - events: list of expected event records
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)

    base_ts = datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc)
    e2e_records = []
    chain_roots = {}
    for i, chain in enumerate(DAY4_E2E_CHAINS):
        ts = base_ts + timedelta(seconds=i * 2)
        chain_roots[chain["name"]] = _emit_day4_chain(chain, ts, rng, e2e_records)

    _write_jsonl(out_dir / "day4_e2e.jsonl", e2e_records)
    _write_jsonl(out_dir / "day4_robust.jsonl", DAY4_ROBUST_TRIALS)
    _write_jsonl(out_dir / "events.jsonl", EVENTS_FIXTURES)

    return {
        "chains": chain_roots,
        "robust": day4_robust_expected(),
        "events": EVENTS_FIXTURES,
    }


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    out_dir = argv[0] if argv else "./fixture_logs"
    manifest = write_fixtures(out_dir)
    print(f"wrote fixtures to {out_dir}/")
    for task_id, info in manifest.items():
        print(f"  {task_id}: {info['node_count']} nodes, "
              f"{info['total_latency_ms']} ms total, {info['status']}")
    day4 = write_day4_fixtures(out_dir)
    print(f"day-4 chains: {list(day4['chains'].keys())}")
    print(f"day-4 robust: {day4['robust']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
