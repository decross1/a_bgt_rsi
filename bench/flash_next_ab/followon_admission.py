"""Controller-owned tickets for grouped diagnostic runners.

Only the already-running q/resident workers may construct these callbacks.
Every runner call still uses the existing armed monitor and monotonic cutoff.
No browser/API observation, model text, or stored approval bit is admission.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from bench.flash_next_ab import followon_plans as plans
from bench.flash_next_ab import qualification as q
from bench.flash_next_ab import resident_evaluation_window as resident


class LeaseError(ValueError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise LeaseError(reason)


def _sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _current_worker(state: dict, cutoff: float) -> None:
    _require(state.get("boot_id")
             == Path("/proc/sys/kernel/random/boot_id").read_text().strip()
             and state.get("worker_pid") == os.getpid()
             and state.get("worker_start_ticks") == q._self_start_ticks()
             and type(cutoff) in {int, float} and math.isfinite(cutoff)
             and time.monotonic() < cutoff,
             "follow-on worker identity or cutoff is no longer current")


def _source_still_frozen(window: plans.FollowonExecution) -> None:
    current = plans.load_execution(window.source_path, cohort=window.cohort)
    _require(current == window,
             "follow-on window/parent/source changed before a block")


def _ticket(window: plans.FollowonExecution, state: dict, endpoint: str,
            cutoff: float) -> dict:
    route = window.document["route_bindings"][endpoint]
    lease = _sha({
        "window_sha256": window.source_sha256,
        "controller_source_bundle_sha256": window.document[
            "followon_source_bundle_sha256"
        ],
        "boot_id": state["boot_id"], "worker_pid": state["worker_pid"],
        "worker_start_ticks": state["worker_start_ticks"],
        "candidate_id": state.get("candidate_id"),
        "candidate_cgroup_path": state.get("candidate_cgroup_path"),
        "candidate_cgroup_pid": state.get("candidate_cgroup_pid"),
        "candidate_cgroup_start_ticks": state.get("candidate_cgroup_start_ticks"),
        "watchdog_sentinel_id": state.get("watchdog_sentinel_id"),
        "endpoint": endpoint, "route": route, "work_cutoff_s": cutoff,
    })
    return {"status": "admitted", "endpoint_name": endpoint,
            "qualification_receipt_sha256": route["qualification_receipt_sha256"],
            "served_model": route["served_model"],
            "artifact_sha256": route["artifact_sha256"],
            "runtime_sha256": route["runtime_sha256"],
            "max_model_len": route["max_model_len"],
            "lease_sha256": lease, "work_cutoff_s": cutoff}


def _plan_route(window: plans.FollowonExecution, plan: dict,
                endpoint: str) -> None:
    _require(endpoint in window.document["route_bindings"],
             "follow-on endpoint is outside this window")
    route = window.document["route_bindings"][endpoint]
    selected = (plan.get("route") if plan.get("endpoint_name") == endpoint
                else plan.get("routes", {}).get(endpoint))
    if isinstance(selected, dict) and "max_model_len" not in selected:
        route = {key: value for key, value in route.items()
                 if key != "max_model_len"}
    _require(selected == route, "follow-on runner route differs from live ticket")


def _callbacks(window: plans.FollowonExecution, state: dict, monitor: Any,
               cutoff: float, phase_guard) -> SimpleNamespace:
    _require(callable(getattr(monitor, "check", None))
             and callable(getattr(getattr(monitor, "cancel_event", None),
                                  "is_set", None)),
             "existing armed monitor is unavailable")

    def safe() -> None:
        _current_worker(state, cutoff)
        phase_guard()
        monitor.check()
        _require(not monitor.cancel_event.is_set(),
                 "existing safety monitor canceled the block")

    def admit_thinking(plan: dict, endpoint: str) -> None:
        _source_still_frozen(window)
        _plan_route(window, plan, endpoint)
        safe()

    def admit_context(plan: dict) -> dict:
        endpoint = plan.get("endpoint_name")
        _source_still_frozen(window)
        _plan_route(window, plan, endpoint)
        safe()
        return _ticket(window, state, endpoint, cutoff)

    def check_thinking() -> None:
        safe()

    def check_context(ticket: dict) -> dict:
        _require(isinstance(ticket, dict)
                 and ticket.get("endpoint_name")
                    in window.document["route_bindings"],
                 "context ticket endpoint differs")
        endpoint = ticket["endpoint_name"]
        _require(ticket == _ticket(window, state, endpoint, cutoff),
                 "context ticket lease or route changed")
        safe()
        return {"status": "safe", "lease_sha256": ticket["lease_sha256"]}

    safe()
    return SimpleNamespace(admit_thinking=admit_thinking,
                           admit_context=admit_context,
                           check_thinking=check_thinking,
                           check_context=check_context)


def flash_callbacks(window: plans.FollowonExecution, state: dict,
                    monitor: Any, candidate: dict, *, cutoff: float) -> SimpleNamespace:
    _require(window.cohort == "flash"
             and state.get("phase") == "evaluation"
             and isinstance(candidate, dict)
             and candidate.get("id") == state.get("candidate_id")
             and candidate.get("image")
                == window.qualification_plan.get("image_id")
             and candidate.get("pid") == state.get("candidate_cgroup_pid")
             and candidate.get("running") is True
             and candidate.get("oom_killed") is False
             and candidate.get("restart_count") == 0
             and state.get("candidate_cgroup_path")
                == monitor.candidate_cgroup_bound_path
             and state.get("candidate_cgroup_pid")
                == monitor.candidate_cgroup_bound_pid
             and state.get("candidate_cgroup_start_ticks")
                == monitor.candidate_cgroup_start_ticks,
             "Flash follow-on candidate has no exact live cgroup/image bind")

    def phase_guard() -> None:
        _require(state.get("phase") == "evaluation"
                 and monitor._phase == "evaluation"
                 and monitor._candidate_id == state["candidate_id"]
                 and monitor.candidate_cgroup_bound_path
                    == state["candidate_cgroup_path"]
                 and monitor.candidate_cgroup_bound_pid
                    == state["candidate_cgroup_pid"]
                 and monitor.candidate_cgroup_start_ticks
                    == state["candidate_cgroup_start_ticks"],
                 "Flash follow-on monitor left the armed serving phase")

    return _callbacks(window, state, monitor, cutoff, phase_guard)


def resident_callbacks(window: plans.FollowonExecution, state: dict,
                       monitor: Any, ops: Any, *, cutoff: float) -> SimpleNamespace:
    quiet = state.get("quiet_observation")
    _require(window.cohort == "resident" and state.get("phase") == "evaluation"
             and isinstance(quiet, dict)
             and quiet.get("nara", {}).get("ActiveState") == "inactive"
             and quiet.get("residents_by_name")
                == monitor.original.get("residents_by_name")
             and isinstance(state.get("watchdog_sentinel_id"), str),
             "resident follow-on has no exact Nara/ID isolation")

    def phase_guard() -> None:
        _require(state.get("phase") == "evaluation"
                 and monitor.phase == "evaluation"
                 and monitor.sentinel_id == state["watchdog_sentinel_id"],
                 "resident follow-on monitor left Nara isolation")
        resident._verify_sentinel(
            ops, window.pair_id, state["watchdog_sentinel_id"]
        )

    return _callbacks(window, state, monitor, cutoff, phase_guard)
