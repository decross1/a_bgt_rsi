#!/usr/bin/env python3
"""N-request concurrency smoke for the resident Flash server (stdlib only).

N is the ``max_running_requests`` declared in ``config/model_deployment.json``
(validated by ``agent_wrapper.deployment``; 1, 2 or 4). The tool sends N small
streamed chat requests to the loopback SGLang endpoint at the same instant and
reports each stream's start, first-token and end times (seconds from a shared
zero), its time to first token, decode time and chunk rate, plus whether all
N generation windows overlapped at one instant and how many pairs overlapped.

It also reads ``/get_server_info`` and checks that the server serves the
configured count: the requested ``max_running_requests``, the scheduler's
``internal_states[0].effective_max_running_requests_per_dp`` (SGLang caps the
requested value at ``max_mamba_cache_size // 5`` on this hybrid model without
failing the launch) and ``max_total_num_tokens`` equal to the configured
context length.

This makes N real inference calls. Run it only in a cutover window
(docs/FLASH_C4_CUTOVER.md), after ``flash_resident check-ready`` passes.
``--dry-run`` prints the plan and touches no network.

Exit status: 0 = the server reports the configured count (requested and
effective) and the full token pool, and, for N > 1, all N requests decoded
concurrently; 1 = they ran but did not all overlap, or the server does not
match the configuration; 2 = the configuration, a request or the server-info
read failed.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_wrapper.deployment import DEPLOYMENT_PATH, load_model_deployment  # noqa: E402

MODEL = "nvidia/Qwen3.8-Flash-Next-NVFP4"
DEFAULT_BASE = "http://127.0.0.1:30080"
PROMPTS = (
    "Count from 1 to 40, separated by spaces.",
    "List the letters of the English alphabet, separated by spaces.",
    "Name the days of the week, then the months of the year, separated by commas.",
    "Count down from 40 to 1, separated by spaces.",
)


def _opener():
    # Loopback only: never route through an environment proxy.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def server_info(base: str, timeout: float) -> dict:
    with _opener().open(base + "/get_server_info", timeout=timeout) as response:
        return json.loads(response.read(16 * 1024 * 1024))


def effective_running_requests(info: dict):
    """The scheduler's capped running-request count, or None if unreported."""
    states = info.get("internal_states")
    if isinstance(states, list) and states and isinstance(states[0], dict):
        return states[0].get("effective_max_running_requests_per_dp")
    return None


def request_body(prompt: str, max_tokens: int) -> dict:
    return {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }


def run_one(base, index, body, barrier, t0, timeout, out):
    """Stream one completion; times are seconds after the shared t0."""
    row = {"stream": index, "prompt": body["messages"][0]["content"], "start_s": None,
           "first_token_s": None, "end_s": None, "chunks": 0, "usage": None, "error": None}
    request = urllib.request.Request(
        base + "/v1/chat/completions", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        barrier.wait(timeout=30)
        row["start_s"] = time.monotonic() - t0
        with _opener().open(request, timeout=timeout) as response:
            for raw in response:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                event = json.loads(payload)
                if event.get("usage"):
                    row["usage"] = event["usage"]
                for choice in event.get("choices") or []:
                    delta = choice.get("delta") or {}
                    # A reasoning delta is a generated token too.
                    if delta.get("content") or delta.get("reasoning_content"):
                        row["chunks"] += 1
                        if row["first_token_s"] is None:
                            row["first_token_s"] = time.monotonic() - t0
        row["end_s"] = time.monotonic() - t0
    except Exception as exc:  # noqa: BLE001 - reported, and the exit status is 2
        row["error"] = f"{type(exc).__name__}: {exc}"
    out.append(row)


def timing(row: dict) -> dict:
    """Per-stream timing derived from the shared-zero timestamps."""
    if row["error"] or row["first_token_s"] is None or row["end_s"] is None:
        return {"ttft_s": None, "decode_s": None, "chunks_per_s": None,
                "completion_tokens": None, "completion_tokens_per_s": None}
    decode = row["end_s"] - row["first_token_s"]
    tokens = (row.get("usage") or {}).get("completion_tokens")
    elapsed = row["end_s"] - row["start_s"]
    return {
        "ttft_s": round(row["first_token_s"] - row["start_s"], 3),
        "decode_s": round(decode, 3),
        "chunks_per_s": round(row["chunks"] / decode, 2) if decode > 0 else None,
        "completion_tokens": tokens,
        "completion_tokens_per_s": (
            round(tokens / elapsed, 2) if isinstance(tokens, int) and elapsed > 0 else None
        ),
    }


def overlap(rows: list[dict]) -> dict:
    """All N decoded at once if every stream produced a token before any ended.

    ``overlap_s`` is the length of the window in which all N were decoding.
    ``overlapping_pairs`` counts pairs whose decode windows intersected. A
    single stream has nothing to overlap with, so ``overlapped`` is None.
    """
    n = len(rows)
    pairs = n * (n - 1) // 2
    if n < 2:
        return {"overlapped": None, "overlap_s": 0.0, "overlapping_pairs": 0, "pairs": 0}
    if any(r["error"] or r["first_token_s"] is None or r["end_s"] is None for r in rows):
        return {"overlapped": False, "overlap_s": 0.0, "overlapping_pairs": 0, "pairs": pairs}
    window = min(r["end_s"] for r in rows) - max(r["first_token_s"] for r in rows)
    overlapping = sum(
        1
        for i in range(n)
        for j in range(i + 1, n)
        if min(rows[i]["end_s"], rows[j]["end_s"])
        > max(rows[i]["first_token_s"], rows[j]["first_token_s"])
    )
    return {"overlapped": window > 0, "overlap_s": round(max(window, 0.0), 3),
            "overlapping_pairs": overlapping, "pairs": pairs}


def server_checks(info: dict, expected_running: int, expected_tokens: int) -> dict:
    observed = {
        "max_running_requests": info.get("max_running_requests"),
        "effective_max_running_requests_per_dp": effective_running_requests(info),
        "max_total_num_tokens": info.get("max_total_num_tokens"),
    }
    expected = {
        "max_running_requests": expected_running,
        "effective_max_running_requests_per_dp": expected_running,
        "max_total_num_tokens": expected_tokens,
    }
    return {
        key: {"expected": expected[key], "observed": observed[key],
              "ok": type(observed[key]) is int and observed[key] == expected[key]}
        for key in expected
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--deployment", default=str(DEPLOYMENT_PATH),
                        help="deployment document that declares max_running_requests")
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    parsed = urllib.parse.urlsplit(args.base)
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost"):
        parser.error("--base must be a loopback http URL")
    base = args.base.rstrip("/")
    try:
        deployment = load_model_deployment(args.deployment)
    except Exception as exc:  # noqa: BLE001 - reported, and the exit status is 2
        print(json.dumps({"error": f"deployment: {type(exc).__name__}: {exc}"}))
        return 2
    running = deployment.max_running_requests
    if running > len(PROMPTS):
        print(json.dumps({"error": f"no smoke prompts for {running} streams"}))
        return 2
    bodies = [request_body(p, args.max_tokens) for p in PROMPTS[:running]]
    pass_rule = (
        "max_running_requests == internal_states[0].effective_max_running_requests_per_dp "
        f"== {running}, max_total_num_tokens == {deployment.context_length}"
        + (f", and all {running} streams produced a token before any stream ended"
           if running > 1 else ", and the single request streamed without error")
    )
    if args.dry_run:
        print(json.dumps({
            "dry_run": True,
            "configured_max_running_requests": running,
            "server_info": f"GET {base}/get_server_info (read max_running_requests, "
                           "internal_states[0].effective_max_running_requests_per_dp, "
                           "max_total_num_tokens)",
            "requests": [{"POST": f"{base}/v1/chat/completions", "body": b} for b in bodies],
            "release": f"all {running} threads released by one barrier; "
                       "times from a shared monotonic zero",
            "pass_rule": pass_rule,
        }, indent=2))
        return 0
    try:
        info = server_info(base, timeout=15)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": f"server_info: {type(exc).__name__}: {exc}"}))
        return 2
    rows: list[dict] = []
    barrier = threading.Barrier(running)
    t0 = time.monotonic()
    threads = [threading.Thread(target=run_one,
                                args=(base, i, b, barrier, t0, args.timeout, rows))
               for i, b in enumerate(bodies)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    rows.sort(key=lambda r: r["stream"])
    for row in rows:
        row.update(timing(row))
    checks = server_checks(info, running, deployment.context_length)
    report = {
        "configured_max_running_requests": running,
        "max_running_requests": info.get("max_running_requests"),
        "effective_max_running_requests_per_dp": effective_running_requests(info),
        "max_total_num_tokens": info.get("max_total_num_tokens"),
        "cuda_graph_bs_decode": info.get("cuda_graph_bs_decode"),
        "server_checks": checks,
        "requests": rows,
        **overlap(rows),
        "pass_rule": pass_rule,
    }
    print(json.dumps(report, indent=2))
    if any(r["error"] for r in rows):
        return 2
    server_ok = all(check["ok"] for check in checks.values())
    concurrent_ok = running == 1 or report["overlapped"] is True
    return 0 if server_ok and concurrent_ok else 1


if __name__ == "__main__":
    sys.exit(main())
