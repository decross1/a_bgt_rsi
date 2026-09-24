#!/usr/bin/env python3
"""Two-request concurrency smoke for the resident Flash server (stdlib only).

Sends two small streamed chat requests to the loopback SGLang endpoint at the
same instant and reports each request's start, first-token and end times
(seconds from a shared zero) plus whether their generation windows overlapped.
It also reports ``max_running_requests`` from ``/get_server_info``.

This makes two real inference calls. Run it only in the C2 cutover window
(docs/FLASH_C2_CUTOVER.md), after ``flash_resident check-ready`` passes.
``--dry-run`` prints the plan and touches no network.

Exit status: 0 = server reports 2 running requests and both requests decoded
concurrently; 1 = they ran but did not overlap or the server is not C2;
2 = a request or the server-info read failed.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.parse
import urllib.request

MODEL = "nvidia/Qwen3.8-Flash-Next-NVFP4"
DEFAULT_BASE = "http://127.0.0.1:30080"
PROMPTS = (
    "Count from 1 to 40, separated by spaces.",
    "List the letters of the English alphabet, separated by spaces.",
)


def _opener():
    # Loopback only: never route through an environment proxy.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def server_info(base: str, timeout: float) -> dict:
    with _opener().open(base + "/get_server_info", timeout=timeout) as response:
        return json.loads(response.read(16 * 1024 * 1024))


def request_body(prompt: str, max_tokens: int) -> dict:
    return {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }


def run_one(base, body, barrier, t0, timeout, out):
    """Stream one completion; times are seconds after the shared t0."""
    row = {"prompt": body["messages"][0]["content"], "start_s": None,
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


def overlap(rows: list[dict]) -> dict:
    """Both decoded at once if each produced a token before the other ended."""
    a, b = rows
    if any(r["error"] or r["first_token_s"] is None or r["end_s"] is None for r in rows):
        return {"overlapped": False, "overlap_s": 0.0}
    window = min(a["end_s"], b["end_s"]) - max(a["first_token_s"], b["first_token_s"])
    return {"overlapped": window > 0, "overlap_s": round(max(window, 0.0), 3)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    parsed = urllib.parse.urlsplit(args.base)
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost"):
        parser.error("--base must be a loopback http URL")
    base = args.base.rstrip("/")
    bodies = [request_body(p, args.max_tokens) for p in PROMPTS]
    if args.dry_run:
        print(json.dumps({
            "dry_run": True,
            "server_info": f"GET {base}/get_server_info (read max_running_requests)",
            "requests": [{"POST": f"{base}/v1/chat/completions", "body": b} for b in bodies],
            "release": "both threads released by one barrier; times from a shared monotonic zero",
            "pass_rule": "max_running_requests == 2 and each request streamed a token before the other ended",
        }, indent=2))
        return 0
    try:
        info = server_info(base, timeout=15)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": f"server_info: {type(exc).__name__}: {exc}"}))
        return 2
    rows: list[dict] = []
    barrier = threading.Barrier(2)
    t0 = time.monotonic()
    threads = [threading.Thread(target=run_one, args=(base, b, barrier, t0, args.timeout, rows))
               for b in bodies]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    rows.sort(key=lambda r: r["prompt"])
    report = {
        "max_running_requests": info.get("max_running_requests"),
        "max_total_num_tokens": info.get("max_total_num_tokens"),
        "cuda_graph_bs_decode": info.get("cuda_graph_bs_decode"),
        "requests": rows,
        **overlap(rows),
    }
    print(json.dumps(report, indent=2))
    if any(r["error"] for r in rows):
        return 2
    return 0 if report["overlapped"] and report["max_running_requests"] == 2 else 1


if __name__ == "__main__":
    sys.exit(main())
