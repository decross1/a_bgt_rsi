"""Supervised Flash context-capacity eval: 64K -> 131,072 -> 262,144.

Owner request 2026-09-22: find the largest context that fits inside the
10 GiB host reserve. One pass stops the 32K resident, runs each tier once
under the same memory, swap, PSI and driver guard (monitor 10 GiB, guard
8 GiB), stops escalating at the first failed tier, and restores the resident.
It measures capacity, latency and synthetic recall only; it changes no
deployment, client limit or benchmark manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import random
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from bench.flash_context_eval import probes
from orchestrator import flash_resident as resident

EVAL_HELPER = resident.PREP / "sglang_context_eval_v1.py"
EVAL_HELPER_SHA256 = "4f3af0e760984cfcf79afb9037aa06c44be4df111b5de3b520720b9ac5efc331"  # output of make_context_eval_helper.py
TIERS = {
    65536: ("nextn-64k-c1-s3.json", (8000, 30000, 56000)),
    131072: ("nextn-128k-c1-s3.json", (8000, 56000, 100000)),
    262144: ("nextn-262k-c1-s3.json", (8000, 100000, 250000)),
}
OUTPUT_RESERVE = 512  # input + output must fit the served window
RUN_LOG = resident.ROOT / "run_state/week1.run.jsonl"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(task: str, status: str, actual: str, expected: str) -> None:
    row = dict(timestamp=now(), task_id=f"flash-context-eval:{task}", agent="claude-code-main",
               status=status, observable_actual=actual, observable_expected=expected, duration_ms=0)
    with RUN_LOG.open("a") as handle:
        handle.write(json.dumps(row) + "\n")


def load_helper():
    if EVAL_HELPER_SHA256 is None:
        raise RuntimeError("eval helper is not pinned; refusing to launch")
    if hashlib.sha256(EVAL_HELPER.read_bytes()).hexdigest() != EVAL_HELPER_SHA256:
        raise RuntimeError("eval helper bytes changed")
    spec = importlib.util.spec_from_file_location("flash_context_eval_helper", EVAL_HELPER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def words_for(tokens: int, ratio: float) -> int:
    """Filler words for a target token count, 3% under to absorb estimate error."""
    return max(200, int((tokens * 0.97 - 200) / ratio))


def run_probes(context: int, sizes: tuple[int, ...], monitor) -> dict:
    """All requests are sequential except one queued canary."""
    out = {"needles": [], "failures": []}

    def request(name, prompt, max_tokens):
        monitor.check()
        result = probes.stream_chat(prompt, max_tokens)
        monitor.check()
        if result.get("status") != 200:
            out["failures"].append({name: result})
        return result

    calibrate = request("calibrate", " ".join(probes.filler(random.Random(0), 2000)), 1)
    if not calibrate.get("prompt_tokens"):
        return out  # recorded as a failure; the tier does not pass
    ratio = out["tokens_per_word"] = calibrate["prompt_tokens"] / 2000

    for size in sizes:
        target = min(size, context - OUTPUT_RESERVE)
        prompt, expected = probes.needle_prompt(words_for(target, ratio), seed=size)
        result = request(f"needle_{size}", prompt, 256)
        result["accuracy"] = probes.score_needles(result.get("text", ""), expected)
        result["target_tokens"] = target
        out["needles"].append({k: v for k, v in result.items() if k != "text"})
    largest = min(sizes[-1], context - OUTPUT_RESERVE)
    prompt, expected = probes.needle_prompt(words_for(largest, ratio), seed=sizes[-1])
    warm = request("needle_warm", prompt, 256)
    out["needle_warm"] = {k: v for k, v in warm.items() if k != "text"}
    track_prompt, chain = probes.vartrack_prompt(words_for(largest, ratio), seed=7 + largest)
    canary = {}

    def queued_canary():
        time.sleep(3)
        canary.update(probes.stream_chat("Reply with exactly: canary", 8, timeout=900))

    thread = threading.Thread(target=queued_canary)
    thread.start()
    track = request("vartrack", track_prompt, 256)
    thread.join()
    track.update(probes.score_vartrack(track.get("text", ""), chain))
    out["vartrack"] = {k: v for k, v in track.items() if k != "text"}
    out["queued_canary"] = {k: v for k, v in canary.items() if k != "text"}
    decode = request("decode", "Write the numbers from 1 to 300 separated by spaces.", 700)
    out["decode"] = {k: v for k, v in decode.items() if k != "text"}
    return out


LoadEvictor = resident.LoadEvictor


def run_tier(helper, context: int, stop: threading.Event) -> dict:
    name, sizes = TIERS[context]
    result = {"context": context, "profile": helper.configure_profile(name), "passed": False}
    helper.verify_control_sources()
    ops = helper.q.HostOps()
    helper.inspect_image(ops)
    helper.verify_checkpoint_receipt(resident.RECEIPT, resident.RECEIPT_SHA)
    helper.assert_no_fallback_or_transition(ops)
    helper.assert_port_free()
    evicted = resident.evict_model_page_cache((helper.MODEL_ROOT, helper.CACHE))
    memory = resident.host_memory_kib()
    result["prelaunch"] = {"evicted_files": evicted, "meminfo_kib": memory,
                           "buddyinfo": Path("/proc/buddyinfo").read_text()}
    if memory["MemFree"] / 1024**2 < resident.PRELAUNCH_MIN_FREE_GIB:
        result["error"] = "prelaunch MemFree below floor"
        return result
    output = resident.PREP / "runtime" / f"context-eval-{context}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    output.mkdir(mode=0o700)
    result["artifact_dir"] = str(output)
    guard = log_file = stopper = monitor = None
    evictor = LoadEvictor(helper.MODEL_ROOT)
    state = {}
    started = time.monotonic()
    session_start = datetime.now(timezone.utc)  # kernel-fault window opens before launch
    try:
        guard, log_file, ticks = helper.launch_guard(output, resident.RECEIPT, resident.RECEIPT_SHA, ())
        state.update(guard_pid=guard.pid, guard_start_ticks=ticks)
        evictor.start()
        deadline = time.monotonic() + helper.STARTUP_DEADLINE_S
        record = helper.wait_launch_record(output, guard, resident.RECEIPT_SHA, deadline, stop)
        helper.capture_candidate_allocator_environment(output, ops, record)
        stopper = helper.GuardStopper(output)
        monitor = helper.RuntimeMonitor(output, record, stopper, session_start)
        monitor.start()
        helper.wait_ready(output, monitor, deadline, stop)
        result["load_eviction"] = evictor.stop()
        monitor.arm_passive_models()
        result["ready_s"] = round(time.monotonic() - started, 1)
        result["identity"] = helper.model_identity_projection(helper.exact_models(timeout=10))
        result["probes"] = run_probes(context, sizes, monitor)
        monitor.check()
        result["passed"] = not result["probes"]["failures"]
    except BaseException as exc:  # recorded, then the owned container is removed
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if "load_eviction" not in result:
            result["load_eviction"] = evictor.stop()
        steps = []
        if monitor is not None:
            steps.append(("monitor", monitor.quiesce))
        if stopper is not None:
            steps.append(("stop", lambda: stopper.stop("context eval tier complete")))
        if guard is not None:
            result["guard_returncode"] = guard.poll()  # 8 = guard watchdog stopped first
            steps.append(("guard", lambda: helper.terminate_guard_process(
                output, state, guard, "context eval tier complete")))
        if log_file is not None:
            steps.append(("log", log_file.close))
        steps.append(("cleanup", lambda: result.__setitem__("cleanup", helper.finalize_owned_fallback(
            output, helper.q.HostOps(), resident.RECEIPT_SHA))))
        for name, step in steps:
            try:
                step()
            except BaseException as exc:
                result.setdefault("cleanup_errors", {})[name] = f"{type(exc).__name__}: {exc}"
                result["passed"] = False
        if monitor is not None:
            result["monitor"] = monitor.summary()
            if monitor.failure:
                result["passed"] = False
    return result


class _NoMonitor:
    """The resident supervisor already guards a live baseline."""
    failure = None

    def check(self) -> None:
        if not resident.check_ready():
            raise RuntimeError("resident left readiness during the baseline")


def _served_context() -> int:
    opener = probes.urllib.request.build_opener(probes.urllib.request.ProxyHandler({}))
    with opener.open("http://127.0.0.1:30080/v1/models", timeout=5) as response:
        return int(json.loads(response.read(65536))["data"][0]["max_model_len"])


def systemctl(*args: str, timeout: float = 60) -> str:
    done = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=timeout)
    return done.stdout.strip()


def wait_resident(timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if resident.check_ready():
            return True
        if systemctl("is-active", "flash-resident.service") in {"failed", "inactive"}:
            return False
        time.sleep(15)
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--tiers", default="65536,131072,262144")
    parser.add_argument("--take-resident-offline", action="store_true",
                        help="required: the eval stops the 32K resident, then restores it")
    parser.add_argument("--baseline-live", action="store_true",
                        help="probe the served resident in place (no service changes)")
    args = parser.parse_args(argv)
    if args.baseline_live:
        if not resident.check_ready():
            raise SystemExit("refusing: the resident is not ready")
        context = _served_context()
        args.out.mkdir(parents=True, exist_ok=False)
        result = {"context": context, "baseline_live": True, "started_at": now(),
                  "probes": run_probes(context, (8000, min(24000, context - OUTPUT_RESERVE)), _NoMonitor())}
        result["finished_at"] = now()
        (args.out / "report.json").write_text(json.dumps(result, indent=2) + "\n")
        log("baseline-live", "completed" if not result["probes"]["failures"] else "failed",
            f"context {context}; failures {len(result['probes']['failures'])}", "baseline probes complete")
        return 0
    tiers = [int(t) for t in args.tiers.split(",")]
    if any(t not in TIERS for t in tiers) or tiers != sorted(tiers):
        raise SystemExit("tiers must be an ascending subset of 65536,131072,262144")
    if not args.take_resident_offline:
        raise SystemExit("refusing: pass --take-resident-offline")
    helper = load_helper()
    if not resident.check_ready():
        raise SystemExit("refusing: the 32K resident is not ready before the eval")
    args.out.mkdir(parents=True, exist_ok=False)
    stop = threading.Event()
    for number in (signal.SIGINT, signal.SIGTERM):
        signal.signal(number, lambda *_: stop.set())
    report = {"started_at": now(), "tiers": [], "host_reserve_gib": resident.HOST_RESERVE_GIB}
    log("start", "started", f"tiers {tiers}", "each tier ready, probed and removed; resident restored")
    systemctl("stop", "flash-resident.service", timeout=960)
    stopped = json.loads(resident.STATE.read_text())
    report["resident_stop"] = {k: stopped.get(k) for k in ("phase", "error", "cleanup", "stop_post_cleanup")}
    try:
        if stopped.get("phase") != "stopped":
            raise RuntimeError("resident did not stop cleanly; not running tiers")
        with helper.resource_lease(resident.ROOT):
            for context in tiers:
                if stop.is_set():
                    break
                tier = run_tier(helper, context, stop)
                report["tiers"].append(tier)
                (args.out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
                log(f"tier-{context}", "completed" if tier["passed"] else "failed",
                    json.dumps({k: tier.get(k) for k in ("passed", "error", "ready_s")}), "tier passes")
                if not tier["passed"]:
                    break
    finally:
        systemctl("start", "flash-resident.service")
        report["resident_restored"] = wait_resident(1800)
        report["finished_at"] = now()
        passed = [t["context"] for t in report["tiers"] if t["passed"]]
        report["largest_passing_context"] = max(passed) if passed else None
        (args.out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        log("finish", "completed" if report["resident_restored"] else "failed",
            f"largest passing {report['largest_passing_context']}; resident restored {report['resident_restored']}",
            "resident restored")
    return 0 if report["resident_restored"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
