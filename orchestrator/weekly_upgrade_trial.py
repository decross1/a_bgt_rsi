"""Execute a checked-in weekly experiment under a shared Spark reservation.

Frontier prose is never a command or a grader. A review may select one of the
registered manifests; its hash, complete fixture set and seeds must agree.
The canonical checkout owns accounting and the same lock used by cron/daemon.
GNU timeout independently bounds the child even if this controller is killed.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import ValidationError

from orchestrator import weekly_upgrade as review
from orchestrator.weekly_upgrade_budget import BudgetError, BudgetLedger

ROOT = Path(__file__).resolve().parents[1]
# Each registration is a code-reviewed execution type, never a model-supplied
# module, script, command, backend URL or Python expression.
TRIALS = {
    "bench/weekly_upgrade_eval/fixtures.json": ("objective", 1800),
    **{f"experiments/weekly_qwen_effort_pilot_2026-09-14/seed_{seed}.json":
       ("objective", 2250) for seed in (17, 29, 43)},
    "experiments/topic_scope_repair_2026-09-14.json": ("topic_scope", 2400),
    "experiments/topic_scope_repair_v2_2026-09-14.json": ("topic_scope", 2400),
    "experiments/weekly_upgrade_game_science_dev_v0_2026-09-14.json": ("portfolio", 2310),
    "experiments/weekly_context_capability_v1_2026-09-14.json": ("objective", 1230),
    "experiments/diversity_selection_dev_v0_2026-09-14.json": ("diversity", 880),
    "experiments/diversity_selection_v1_2026-09-14.json": ("diversity", 880),
    "experiments/weekly_role_effort_v1_2026-09-14.json": ("role_effort", 1660),
    "experiments/weekly_historical_coding_panel_v2_2026-09-14.json": ("historical_repair", 1050),
    "experiments/weekly_historical_coding_patch_wire_v1_2026-09-14.json": ("historical_repair", 1050),
}
CONTEXT_MANIFEST = "experiments/weekly_context_capability_v1_2026-09-14.json"
TRIAL_MODULES = {
    "objective": "bench.weekly_upgrade_eval.runner",
    "topic_scope": "bench.weekly_upgrade_eval.topic_scope",
    "portfolio": "bench.weekly_upgrade_portfolio.runner",
    "diversity": "bench.weekly_upgrade_diversity.runner",
    "role_effort": "bench.weekly_upgrade_effort.runner",
    "historical_repair": "bench.weekly_upgrade_historical.runner",
}
ENDPOINTS = ("http://127.0.0.1:8000", "http://127.0.0.1:8001")
RESIDENT_CONTAINERS = ("vllm-gemma4", "vllm-qwen")
MIN_MEMORY_GIB = 30  # Existing production preflight floor, not a relaxed gate.
KILL_GRACE_S = 5
SUPERVISION_MARGIN_S = 10
DEPENDENCY_PATHS = (
    "agent_wrapper", "bench/weekly_upgrade_eval", "bench/weekly_upgrade_portfolio",
    "bench/weekly_upgrade_context", "bench/weekly_upgrade_diversity",
    "bench/weekly_upgrade_effort", "bench/weekly_upgrade_historical",
    "orchestrator/coordinator_actions.py", "orchestrator/weekly_upgrade_portfolio_receipt.py",
    "orchestrator/weekly_upgrade_trial.py", "orchestrator/weekly_upgrade_budget.py",
    "orchestrator/weekly_upgrade.py", "orchestrator/weekly_upgrade_cycle.py",
    "cron/weekly-frontier-agenda.sh", "schema/calls.jsonl.schema.json",
    "schema/weekly_upgrade.schema.json",
)


class TrialError(RuntimeError):
    pass


class UnconfirmedStop(TrialError):
    """A child may still be alive; its entire reservation remains charged."""


def _sha(value: Any) -> str:
    data = value if isinstance(value, bytes) else json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode()
    return hashlib.sha256(data).hexdigest()


def _read(path: Path) -> dict:
    raw = path.read_bytes()
    if len(raw) > 8_000_000:
        raise TrialError(f"oversized artifact: {path.name}")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise TrialError(f"duplicate key: {key}")
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=unique, parse_constant=lambda x:
                      (_ for _ in ()).throw(TrialError(f"non-finite JSON: {x}")))
    if not isinstance(value, dict):
        raise TrialError("expected an artifact object")
    return value


def _write(path: Path, value: dict) -> None:
    raw = json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    import uuid
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def canonical_root(worktree: Path) -> Path:
    common = subprocess.check_output(
        ["git", "-C", str(worktree), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        text=True, timeout=5,
    ).strip()
    root = Path(common).resolve().parent
    if not (root / "run_state").is_dir():
        raise TrialError("canonical checkout has no run_state directory")
    return root


def assert_budget_journal_consistent(root: Path, week_id: str) -> None:
    """A missing budget journal cannot erase canonical same-week trial use."""
    budget = root / "run_state" / "weekly_upgrade_budget.jsonl"
    if budget.exists():
        if budget.is_symlink() or not budget.is_file():
            raise TrialError("weekly budget journal is redirected")
        return
    directory = root / "run_state" / "weekly_upgrade" / "trials"
    if not directory.exists():
        return
    if directory.is_symlink() or not directory.is_dir():
        raise TrialError("weekly trial journal directory is redirected")
    paths = list(directory.glob("*.json"))
    if len(paths) > 512:
        raise TrialError("weekly trial journal directory is unbounded")
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise TrialError("weekly trial journal is redirected")
        try:
            value = _read(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise TrialError("weekly trial journal is unreadable") from exc
        plan = value.get("plan")
        if isinstance(plan, dict) and plan.get("week_id") == week_id:
            raise TrialError(
                "same-week trial evidence exists without the canonical budget journal"
            )


def execution_fingerprint(worktree: Path) -> dict:
    try:
        names = subprocess.check_output(
            ["git", "ls-files", "-z", "--", *DEPENDENCY_PATHS], cwd=worktree,
            timeout=5, stderr=subprocess.DEVNULL,
        ).decode().split("\0")
    except subprocess.SubprocessError as exc:
        raise TrialError("execution dependencies require a Git checkout") from exc
    return {name: _sha((worktree / name).read_bytes()) for name in names if name}


def admitted_review(review_dir: Path) -> dict:
    """Revalidate both reports and their frozen snapshot, not just the card."""
    manifest = _read(review_dir / "run_manifest.json")
    report = _read(review_dir / "weekly_report.json")
    review._validate_manifest(manifest)
    review._validate("report", report)
    if (report["status"] != "CONTINUE_TRIAL" or report["independence_loss"]
            or report["frontier_calls_used"] != 2
            or report["run_manifest_sha256"] != review._manifest_hash(manifest)):
        raise TrialError("review has no fully bound two-provider admitted trial")
    proposal, adversary = report["proposal"], report["adversary"]
    if review._calls_used(review_dir) != 2:
        raise TrialError("review must contain exactly two provider receipts")
    for ordinal, vendor, role, name, value in (
        (1, "codex", "upgrade_proposer", "proposal", proposal),
        (2, "claude", "upgrade_adversary", "adversary", adversary),
    ):
        receipt = _read(review._receipt_path(review_dir, ordinal, role))
        raw = _read(review_dir / "unvalidated" / f"{ordinal:02d}-{role}.json")
        transport = receipt.get("transport", {})
        prompt = (review._proposal_prompt(manifest["snapshot"], manifest["budget"]["max_gpu_minutes"])
                  if ordinal == 1 else review._adversary_prompt(manifest["snapshot"], proposal))
        if (receipt.get("status") != "completed" or receipt.get("vendor") != vendor
                or receipt.get("ordinal") != ordinal or receipt.get("phase") != role
                or receipt.get("prompt_sha256") != _sha(prompt.encode())
                or transport.get("vendor") != vendor or transport.get("exit_code") != 0
                or transport.get("error") or transport.get("mock")
                or transport.get("auth_mode") != "subscription"
                or raw.get("truncated") is not False or raw.get("vendor") != vendor
                or raw.get("ordinal") != ordinal or raw.get("role") != role
                or not isinstance(raw.get("text"), str)
                or _sha(raw["text"].encode()) != receipt.get("response_sha256")
                or raw.get("content_sha256") != receipt.get("response_sha256")
                or review._parse_strict_object(raw["text"]) != value
                or _read(review_dir / f"{name}.json") != value):
            raise TrialError(f"unbound or non-subscription provider receipt: {vendor}")
    review.validate_proposal(proposal, manifest["snapshot"],
                             max_gpu_minutes=manifest["budget"]["max_gpu_minutes"])
    review.validate_adversary(adversary, manifest["snapshot"], proposal)
    if adversary["verdict"] != "survives_to_evaluation":
        raise TrialError("adversary did not admit evaluation")
    expected = review._make_report(manifest, status="CONTINUE_TRIAL", reason=report["reason"],
                                   proposal=proposal, adversary=adversary)
    for key in ("run_id", "week_id", "snapshot_sha256", "proposal_sha256", "experiment_card"):
        if report[key] != expected[key]:
            raise TrialError(f"review artifact mismatch: {key}")
    return report


def plan_trial(manifest_path: str, *, worktree: Path = ROOT,
               review_dir: Path | None = None, now: datetime | None = None) -> dict:
    """No calls, locks, writes or endpoint probes."""
    if manifest_path not in TRIALS:
        raise TrialError("manifest is not in the fixed trial registry")
    worktree = worktree.resolve()
    path = worktree / manifest_path
    if path.is_symlink() or path.resolve() != path.absolute():
        raise TrialError("trial manifest cannot redirect outside the worktree")
    kind, cap = TRIALS[manifest_path]
    raw_sha = _sha(path.read_bytes())
    if kind == "objective":
        from bench.weekly_upgrade_eval.manifest import load_manifest
        manifest = load_manifest(path)
        fixture_ids = [task.id for task in manifest.tasks]
        if any(type(arm.seed) is not int for arm in manifest.arms):
            raise TrialError("registered execution requires explicit integer seeds")
        seeds = sorted({arm.seed for arm in manifest.arms})
        arm_ids = [arm.id for arm in manifest.arms]
        configuration_sha = manifest.configuration_sha256
        attempts = [f"{task}:{arm}" for task in fixture_ids for arm in arm_ids]
        inputs = {task.id: task.input_sha256 for task in manifest.tasks}
        graders = {task.id: task.grader_sha256 for task in manifest.tasks}
        if any(arm.backend not in {"vllm-gemma", "vllm-qwen"} for arm in manifest.arms):
            raise TrialError("only resident local backends are admitted")
    elif kind == "portfolio":
        from bench.weekly_upgrade_portfolio.manifest import (
            load_manifest,
            plan_dict,
            sha256_json,
        )
        manifest = load_manifest(path)
        fixtures = plan_dict(manifest)
        fixture_ids = [task["id"] for task in manifest["tasks"]]
        seeds = sorted({arm["seed"] for arm in manifest["arms"]})
        arm_ids = [arm["id"] for arm in manifest["arms"]]
        configuration_sha = manifest["_configuration_sha256"]
        attempts = [row["attempt_id"] for row in fixtures["order"]]
        inputs = manifest["frozen_hashes"]["tasks"]
        graders = {task["id"]: sha256_json(task["grader"]) for task in manifest["tasks"]}
    elif kind == "diversity":
        from bench.weekly_upgrade_diversity.manifest import (
            load_manifest,
            plan_dict,
            sha256_json,
        )

        manifest = load_manifest(path)
        frozen = plan_dict(manifest)
        fixture_ids = [task["id"] for task in manifest["tasks"]]
        seeds = sorted({call["seed"] for call in frozen["calls"]})
        arm_ids = [condition["id"] for condition in manifest["conditions"]]
        configuration_sha = manifest["_configuration_sha256"]
        attempts = [call["attempt_id"] for call in frozen["calls"]]
        inputs = manifest["frozen_hashes"]["tasks"]
        graders = {
            task["id"]: sha256_json(task["grader"])
            for task in manifest["tasks"]
        }
    elif kind in {"role_effort", "historical_repair"}:
        if kind == "role_effort":
            from bench.weekly_upgrade_effort.manifest import load_manifest, plan_dict
        else:
            from bench.weekly_upgrade_historical.manifest import (
                load_manifest,
                plan_dict,
            )
        manifest = load_manifest(path)
        frozen = plan_dict(manifest)
        fixture_ids, arm_ids, seeds = frozen["fixture_ids"], frozen["arm_ids"], frozen["seeds"]
        configuration_sha = manifest["_configuration_sha256"]
        attempts = [row["attempt_id"] for row in frozen["order"]]
        inputs = frozen["input_sha256"] if kind == "role_effort" else frozen["expected_input_sha256"]
        graders = frozen["grader_sha256"] if kind == "role_effort" else frozen["expected_grader_sha256"]
    elif kind == "topic_scope":
        from bench.weekly_upgrade_eval.topic_scope import build_attempts, load_manifest
        manifest = load_manifest(path)
        fixture_ids = [row["id"] for row in manifest["topics"] + manifest["planner_cases"]]
        seeds = manifest["seeds"]
        arm_ids = [arm["id"] for arm in manifest["arms"]]
        configuration_sha = manifest["_configuration_sha256"]
        base = build_attempts(manifest)
        attempts = [row["attempt_id"] for row in base]
        attempts += [row["attempt_id"].replace("hypothesis:", "primary_r0:", 1)
                     for row in base if row["stage"] == "hypothesis"]
        inputs, graders = {}, {}
    else:  # Registry entries and dispatcher implementations must stay closed.
        raise TrialError("registered evaluation kind is unsupported")
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise TrialError("planning time must include a timezone")
    moment = moment.astimezone(timezone.utc)
    week = moment.strftime("%G-W%V")
    fingerprint = execution_fingerprint(worktree)
    report_sha = None
    if review_dir is not None:
        report = admitted_review(review_dir)
        frozen = _read(review_dir / "run_manifest.json")["snapshot"]
        if frozen.get("execution_dependencies") != fingerprint:
            raise TrialError("reviewed execution dependencies are absent or have changed")
        card = report["experiment_card"]
        if report["week_id"] != week:
            raise TrialError("review belongs to a different UTC ISO week")
        if (card["fixture_manifest_path"] != manifest_path
                or card["fixture_manifest_sha256"] != raw_sha
                or set(card["fixture_ids"]) != set(fixture_ids)
                or set(card["seeds"]) != set(seeds)):
            raise TrialError("card must match the complete registered manifest and seeds")
        if (card["caps"]["gpu_minutes"] * 60 < cap
                or card["caps"]["wall_minutes"] * 60 < cap):
            raise TrialError("card cap cannot fund the registered trial reservation")
        report_sha = _sha(report)
    plan = {
        "schema_version": "weekly-upgrade-trial-plan/v1", "week_id": week,
        "trial_id": f"{week}-{raw_sha[:24]}", "kind": kind,
        "manifest_path": manifest_path, "manifest_sha256": raw_sha,
        "fixture_ids": fixture_ids, "seeds": seeds, "reservation_s": cap,
        "payload_budget_s": cap - 30,
        "arm_ids": arm_ids, "manifest_configuration_sha256": configuration_sha,
        "expected_attempt_ids": attempts,
        "expected_input_sha256": inputs, "expected_grader_sha256": graders,
        "review_sha256": report_sha, "production_change_authorized": False,
        "execution_dependencies": fingerprint,
        "include_primary_r0": kind == "topic_scope",
        "declared_attempts": len(attempts),
    }
    if kind == "diversity":
        plan["condition_ids"] = arm_ids
    return plan


@contextmanager
def resource_lease(root: Path):
    """Cooperate with both production launchers; never change pause files."""
    handles = []
    try:
        for name in (".weekly-upgrade-execution.lock", ".coordinator-cron.lock", ".weekly-upgrade-gpu.lock"):
            stream = (root / "run_state" / name).open("a+")
            handles.append(stream)
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise TrialError(f"resource is occupied: {name}") from exc
        yield tuple(stream.fileno() for stream in handles)
    finally:
        # Do NOT explicitly LOCK_UN: inherited descriptors must keep the lease
        # if this controller exits before its separately supervised child.
        for stream in reversed(handles):
            stream.close()


def _queue_counts(text: str) -> dict:
    values = {"running": [], "waiting": []}
    pattern = r'^vllm:num_requests_(running|waiting)(?:\{[^\n]*\})?\s+([^\s]+)'
    for match in re.finditer(pattern, text, re.MULTILINE):
        value = float(match[2])
        if not math.isfinite(value) or value < 0:
            raise TrialError("invalid queue metric")
        values[match[1]].append(value)
    if not all(values.values()):
        raise TrialError("resident queue metrics unavailable")
    return {key: sum(rows) for key, rows in values.items()}


def resource_probe(root: Path, *, idle: bool) -> dict:
    for name in ("pause_coordinator", "pause_frontier", "pause_weekly_upgrade"):
        if (root / "run_state" / name).exists():
            raise TrialError(f"pause control present: {name}")
    if (root / "run_state" / "active_run.json").exists() or any(
        (root / "run_state" / "active_runs").glob("*.json")
    ):
        raise TrialError("production active-run receipt exists; inspect its live handle before proceeding")
    memory = re.search(r'^MemAvailable:\s+(\d+) kB$', Path("/proc/meminfo").read_text(), re.MULTILINE)
    available = int(memory[1]) / 1024**2 if memory else 0
    if available < MIN_MEMORY_GIB:
        raise TrialError("production memory margin is unavailable")
    queues = []
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for endpoint in ENDPOINTS:
        with opener.open(endpoint + "/metrics", timeout=2) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise TrialError("oversized resident metrics")
        queues.append(_queue_counts(raw.decode("utf-8")))
    occupancy = sum(item["running"] + item["waiting"] for item in queues)
    if occupancy > (0 if idle else 1):
        raise TrialError("resident endpoints have competing requests")
    # Read narrowly selected container fields, never Config.Env/authentication.
    # Backend labels alone cannot detect a restarted or replaced serving image.
    fields = ('{"id":{{json .Id}},"image":{{json .Image}},'
              '"running":{{json .State.Running}},"pid":{{json .State.Pid}},'
              '"started_at":{{json .State.StartedAt}},"restarts":{{json .RestartCount}},'
              '"command":{{json .Config.Cmd}}}')
    raw_identity = subprocess.check_output(
        ["docker", "inspect", "--format", fields, *RESIDENT_CONTAINERS],
        timeout=3, stderr=subprocess.DEVNULL, text=True,
    )
    identities = []
    for line in raw_identity.splitlines():
        row = json.loads(line)
        if not row.get("running") or not row.get("pid") or not row.get("image"):
            raise TrialError("a resident serving container is not running")
        # Keep only a hash of launch arguments; flags can contain private paths.
        identities.append({**{k: v for k, v in row.items() if k != "command"},
                           "command_sha256": _sha(row.get("command"))})
    if len(identities) != len(RESIDENT_CONTAINERS):
        raise TrialError("resident container identity unavailable")
    return {"mem_available_gib": available, "queues": queues, "runtime_identity": identities}


def trial_command(plan: dict, output_dir: Path, remaining_s: float,
                  *, worktree: Path = ROOT) -> list[str]:
    timeout = shutil.which("timeout")
    payload_s = plan["payload_budget_s"]
    if not timeout or remaining_s < payload_s + KILL_GRACE_S + SUPERVISION_MARGIN_S + 1:
        raise TrialError("independent deadline supervisor unavailable or reservation exhausted")
    module = TRIAL_MODULES[plan["kind"]]
    command = [timeout, "--signal=TERM", f"--kill-after={KILL_GRACE_S}s", f"{payload_s + 1:.3f}s",
               sys.executable, "-m", module, "--run", "--manifest",
               str(worktree / plan["manifest_path"]), "--output-dir", str(output_dir),
               "--runtime-budget-s", str(payload_s)]
    if plan["kind"] == "topic_scope":
        command.append("--include-r0")
    return command


def _stop(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=KILL_GRACE_S)
    except subprocess.TimeoutExpired:
        pass
    # The supervisor can exit before a descendant that ignored TERM. Always
    # kill the owned group, not just the Popen leader, before releasing leases.
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError as exc:
        raise UnconfirmedStop("could not stop experiment process group") from exc
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired as exc:
        raise UnconfirmedStop("could not confirm experiment process termination") from exc


def supervise(command: list[str], *, worktree: Path, output: Path, pass_fds: tuple,
              root: Path, probe: Callable = resource_probe) -> dict:
    env = dict(os.environ)
    for name in ("MOCK_LLM", "WRAPPER_PROFILE_OVERRIDES", "NARA_TOPICALITY_SKEPTIC"):
        env.pop(name, None)
    env.update(VLLM_BASE_URL=ENDPOINTS[0] + "/v1", VLLM_QWEN_BASE_URL=ENDPOINTS[1] + "/v1",
               WEEKLY_UPGRADE_GPU_LEASE_FD=str(pass_fds[-1]))
    before = _read(output / "preflight.json") if (output / "preflight.json").exists() else {}
    with (output / "subprocess.log").open("xb") as stream:
        proc = subprocess.Popen(command, cwd=worktree, env=env, stdout=stream,
                                stderr=subprocess.STDOUT, start_new_session=True, pass_fds=pass_fds)
        try:
            stat = Path(f"/proc/{proc.pid}/stat").read_text().rsplit(")", 1)[1].split()
            _write(output / "process.json", {"pid": proc.pid, "pgid": os.getpgid(proc.pid),
                    "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                    "start_ticks": stat[19], "command": command, "argv_sha256": _sha(command),
                    "started_at": datetime.now(timezone.utc).isoformat()})
            while proc.poll() is None:
                observed = probe(root, idle=False)
                if observed.get("runtime_identity") != before.get("runtime_identity"):
                    raise TrialError("resident serving runtime changed during the trial")
                time.sleep(1)
        except BaseException:
            _stop(proc)
            raise
    return {"returncode": proc.returncode}


def live_trial_processes(output: Path) -> list[int]:
    """Inspect actual /proc handles, including a supervisor orphaned by death.

    Match an exact controlled module/output argument pair, not a stale PID or
    elapsed heartbeat. Only public command arguments are inspected.
    """
    target = os.fsencode(str(output / "evaluation"))
    modules = {os.fsencode(module) for module in TRIAL_MODULES.values()}
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            args = (entry / "cmdline").read_bytes().split(b"\0")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if (any(module in args for module in modules)
                and any(a == b"--output-dir" and args[i + 1] == target
                        for i, a in enumerate(args[:-1]))):
            found.append(int(entry.name))
    return found


def evaluation_receipt(plan: dict, output: Path) -> dict:
    """Validate a complete, hash-bound artifact graph before crediting work.

    A self-declared status is insufficient.  The receipt binds the registered
    manifest, exact arm/cell matrix, per-cell provenance and the durable logs.
    Topic-scope runs additionally bind raw -> parsed -> blind/private views;
    their transport completion still is not a semantic result.
    """
    evaluation = output / "evaluation"
    if evaluation.is_symlink() or not evaluation.is_dir():
        raise TrialError("evaluation artifact directory is absent or redirected")

    def regular(name: str, *, required: bool = True) -> Path | None:
        candidate = evaluation / name
        if not candidate.exists():
            if required:
                raise TrialError(f"required evaluation artifact is absent: {name}")
            return None
        if candidate.is_symlink() or not candidate.is_file() or candidate.resolve().parent != evaluation.resolve():
            raise TrialError(f"evaluation artifact is not a local regular file: {name}")
        return candidate

    def json_lines(name: str, *, required: bool = True) -> list[dict]:
        candidate = regular(name, required=required)
        if candidate is None:
            return []
        raw = candidate.read_bytes()
        if len(raw) > 16_000_000 or (raw and not raw.endswith(b"\n")):
            raise TrialError(f"invalid bounded JSONL artifact: {name}")
        rows = []
        for number, line in enumerate(raw.splitlines(), 1):
            if not line:
                raise TrialError(f"blank JSONL row in {name}:{number}")
            try:
                row = json.loads(
                    line,
                    object_pairs_hook=lambda pairs, number=number: (
                        (_ for _ in ()).throw(TrialError(
                            f"duplicate JSON key in {name}:{number}"
                        )) if len({key for key, _ in pairs}) != len(pairs)
                        else dict(pairs)
                    ),
                    parse_constant=lambda value, number=number: (_ for _ in ()).throw(
                        TrialError(f"non-finite JSON in {name}:{number}: {value}")
                    ),
                )
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise TrialError(f"invalid JSON in {name}:{number}") from exc
            if not isinstance(row, dict):
                raise TrialError(f"non-object JSONL row in {name}:{number}")
            rows.append(row)
        return rows

    def finite_nonnegative(value: Any, where: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TrialError(f"{where} must be a nonnegative finite number")
        number = float(value)
        if not math.isfinite(number) or number < 0:
            raise TrialError(f"{where} must be a nonnegative finite number")
        return number

    run_path = regular("run.json")
    snapshot_path = regular("manifest.snapshot.json")
    assert run_path is not None and snapshot_path is not None
    if _sha(snapshot_path.read_bytes()) != plan.get("manifest_sha256"):
        raise TrialError("manifest snapshot differs from the registered manifest")
    artifact = _read(run_path)
    if artifact.get("promotion_authorized") is True:
        raise TrialError("evaluation artifact cannot authorize promotion")
    if plan.get("production_change_authorized") is not False:
        raise TrialError("execution plan unexpectedly authorizes production change")
    expected_attempt_ids = plan.get("expected_attempt_ids")
    if (
        not isinstance(expected_attempt_ids, list)
        or len(expected_attempt_ids) != plan.get("declared_attempts")
        or len(expected_attempt_ids) != len(set(expected_attempt_ids))
    ):
        raise TrialError("plan has no unique declared attempt matrix")

    call_schema = _read(ROOT / "schema" / "calls.jsonl.schema.json")
    from jsonschema import Draft202012Validator
    call_validator = Draft202012Validator(call_schema)

    def validate_calls(rows: list[dict], *, run_id: str) -> None:
        request_ids = []
        for index, row in enumerate(rows):
            errors = sorted(call_validator.iter_errors(row), key=lambda error: list(error.path))
            if errors:
                raise TrialError(f"call record {index} fails schema: {errors[0].message}")
            if row.get("run_id") != run_id:
                raise TrialError("call record is not bound to the evaluation run_id")
            request_ids.append(row.get("request_id"))
        if len(request_ids) != len(set(request_ids)):
            raise TrialError("evaluation call request_ids are not unique")

    def validate_activity(rows: list[dict], calls: list[dict], *, run_id: str) -> None:
        if len(rows) != len(calls):
            raise TrialError("worker activity count differs from raw call count")
        expected_keys = {
            "timestamp", "run_id", "task_id", "tokens_generated", "tokens_target",
            "tok_per_s", "eta_s", "synthetic", "backend", "model",
        }
        for activity, call in zip(rows, calls, strict=True):
            if not isinstance(activity, dict) or set(activity) != expected_keys:
                raise TrialError("worker activity row has an unexpected schema")
            output_tokens = call["usage"]["output_tokens"]
            latency_s = call["latency_ms"] / 1000.0
            rate = output_tokens / latency_s if latency_s > 0 else 0.0
            eta = None if rate == 0 else max(0, call["max_tokens"] - output_tokens) / rate
            expected = {
                "timestamp": call["timestamp"], "run_id": run_id,
                "task_id": call["caller_tag"], "tokens_generated": output_tokens,
                "tokens_target": call["max_tokens"], "tok_per_s": rate,
                "eta_s": eta, "synthetic": False, "backend": call["backend"],
                "model": call["model"],
            }
            if activity != expected:
                raise TrialError("worker activity is not the exact view of its raw call")

    artifact_hashes = {
        "run.json": _sha(run_path.read_bytes()),
        "manifest.snapshot.json": _sha(snapshot_path.read_bytes()),
    }
    if plan.get("manifest_path") == CONTEXT_MANIFEST:
        from bench.weekly_upgrade_context.preflight import validate_preflight_receipt

        context_path = output / "context_preflight.json"
        if context_path.is_symlink() or not context_path.is_file():
            raise TrialError("context evaluation lacks a local tokenizer preflight receipt")
        validate_preflight_receipt(
            _read(context_path), plan["manifest_sha256"], plan["execution_dependencies"],
        )
        artifact_hashes["../context_preflight.json"] = _sha(context_path.read_bytes())

    if plan.get("kind") == "diversity":
        from bench.weekly_upgrade_diversity.receipt import (
            validate_diversity_receipt,
        )

        complete = validate_diversity_receipt(
            plan, artifact, snapshot_path, regular=regular, json_lines=json_lines,
            validate_calls=validate_calls, validate_activity=validate_activity,
            finite_nonnegative=finite_nonnegative,
        )
        for name in (
            "raw_calls.jsonl", "outcomes.jsonl", "calls.jsonl", "worker_activity.jsonl",
        ):
            candidate = regular(
                name,
                required=complete or name in {"raw_calls.jsonl", "outcomes.jsonl"},
            )
            if candidate is not None:
                artifact_hashes[name] = _sha(candidate.read_bytes())
    elif plan.get("kind") in {"role_effort", "historical_repair"}:
        if plan["kind"] == "role_effort":
            from bench.weekly_upgrade_effort.receipt import (
                validate_effort_receipt as validate_receipt,
            )
        else:
            from bench.weekly_upgrade_historical.receipt import (
                validate_historical_receipt as validate_receipt,
            )
        complete = validate_receipt(
            plan, artifact, snapshot_path, regular=regular, json_lines=json_lines,
            validate_calls=validate_calls, validate_activity=validate_activity,
            finite_nonnegative=finite_nonnegative,
        )
        for name in ("raw_attempts.jsonl", "outcomes.jsonl", "calls.jsonl", "worker_activity.jsonl"):
            candidate = regular(name, required=complete or name in {"raw_attempts.jsonl", "outcomes.jsonl"})
            if candidate is not None:
                artifact_hashes[name] = _sha(candidate.read_bytes())
    elif plan.get("kind") == "portfolio":
        from orchestrator.weekly_upgrade_portfolio_receipt import (
            validate_portfolio_receipt,
        )
        complete = validate_portfolio_receipt(
            plan, artifact, snapshot_path, regular=regular, json_lines=json_lines,
            validate_calls=validate_calls, validate_activity=validate_activity,
            finite_nonnegative=finite_nonnegative,
        )
        for name in ("raw_attempts.jsonl", "outcomes.jsonl", "calls.jsonl", "worker_activity.jsonl"):
            candidate = regular(name, required=complete or name in {"raw_attempts.jsonl", "outcomes.jsonl"})
            if candidate is not None:
                artifact_hashes[name] = _sha(candidate.read_bytes())
    elif plan.get("kind") == "objective":
        from bench.weekly_upgrade_eval.manifest import load_manifest, sha256_json
        from bench.weekly_upgrade_eval.runner import (
            InvocationRequest,
            InvocationResult,
            _decode_tool_calls,
            _result_outcome,
            _runtime_provenance,
        )
        from bench.weekly_upgrade_eval.stats import summarize_outcomes

        manifest = load_manifest(snapshot_path)
        derived_arms = [arm.id for arm in manifest.arms]
        derived_attempts = [
            f"{task.id}:{arm.id}" for task in manifest.tasks for arm in manifest.arms
        ]
        derived_inputs = {task.id: task.input_sha256 for task in manifest.tasks}
        derived_graders = {task.id: task.grader_sha256 for task in manifest.tasks}
        if (
            manifest.raw_sha256 != plan["manifest_sha256"]
            or manifest.configuration_sha256 != plan.get("manifest_configuration_sha256")
            or derived_arms != plan.get("arm_ids")
            or derived_attempts != expected_attempt_ids
            or derived_inputs != plan.get("expected_input_sha256")
            or derived_graders != plan.get("expected_grader_sha256")
        ):
            raise TrialError("objective plan disagrees with its frozen manifest")
        if artifact.get("schema_version") != "weekly-upgrade-eval-run/v1":
            raise TrialError("objective run schema_version is invalid")
        if set(artifact) != {
            "schema_version", "run_id", "status", "started_at", "finished_at",
            "elapsed_wall_s", "provenance", "execution_order", "outcomes",
            "summary", "promotion",
        }:
            raise TrialError("objective run artifact has unexpected fields")
        provenance = artifact.get("provenance")
        expected_harness_hashes = {
            name: plan.get("execution_dependencies", {}).get(name)
            for name in (
                "bench/weekly_upgrade_eval/manifest.py",
                "bench/weekly_upgrade_eval/runner.py",
                "bench/weekly_upgrade_eval/stats.py",
            )
        }
        if not isinstance(provenance, dict) or (
            set(provenance) != {
                "manifest_path", "manifest_sha256", "manifest_configuration_sha256",
                "run_configuration_sha256", "run_configuration", "task_input_sha256",
                "task_grader_sha256", "harness_file_sha256",
                "source_snapshot_declared", "arms",
            }
            or provenance.get("manifest_sha256") != plan["manifest_sha256"]
            or provenance.get("manifest_configuration_sha256") != manifest.configuration_sha256
            or provenance.get("arms") != [arm.as_dict() for arm in manifest.arms]
            or provenance.get("task_input_sha256") != derived_inputs
            or provenance.get("task_grader_sha256") != derived_graders
            or provenance.get("source_snapshot_declared") != manifest.source_snapshot
            or any(value is None for value in expected_harness_hashes.values())
            or provenance.get("harness_file_sha256") != expected_harness_hashes
        ):
            raise TrialError("objective provenance does not match the frozen configuration")
        promotion = artifact.get("promotion")
        if (
            not isinstance(promotion, dict)
            or set(promotion) != {"authorized", "decision", "reason"}
            or promotion.get("authorized") is not False
            or promotion.get("decision") is not None
        ):
            raise TrialError("objective harness promotion guard is absent")
        run_configuration = provenance.get("run_configuration")
        if not isinstance(run_configuration, dict) or (
            set(run_configuration) != {"manifest_configuration_sha256", "runtime_budget_s", "transport"}
            or run_configuration.get("manifest_configuration_sha256") != manifest.configuration_sha256
            or finite_nonnegative(run_configuration.get("runtime_budget_s"), "runtime budget")
            != plan.get("payload_budget_s")
            or provenance.get("run_configuration_sha256") != sha256_json(run_configuration)
        ):
            raise TrialError("objective run configuration is not reservation-bound")
        outcomes = artifact.get("outcomes")
        if not isinstance(outcomes, list):
            raise TrialError("objective outcomes must be an array")
        cells = [f"{row.get('task_id')}:{row.get('arm_id')}" for row in outcomes if isinstance(row, dict)]
        if cells != derived_attempts:
            raise TrialError("objective outcomes have missing, duplicated, or reordered cells")
        arm_by_id = {arm.id: arm for arm in manifest.arms}
        task_by_id = {task.id: task for task in manifest.tasks}
        execution_indexes = []
        complete_statuses = {"passed", "failed"}
        for row in outcomes:
            task, arm = task_by_id[row["task_id"]], arm_by_id[row["arm_id"]]
            if row.get("input_sha256") != task.input_sha256 or row.get("grader_sha256") != task.grader_sha256:
                raise TrialError("objective outcome input/grader hash drifted")
            if row.get("status") not in {"passed", "failed", "timeout", "error", "not_run_budget"}:
                raise TrialError("objective outcome has an invalid status")
            finite_nonnegative(row.get("duration_s"), "objective outcome duration")
            grade = row.get("grade")
            if not isinstance(grade, dict) or grade.get("passed") is not (row.get("status") == "passed"):
                raise TrialError("objective status and grade disagree")
            if row.get("status") in complete_statuses:
                timeout_s = finite_nonnegative(row.get("request_timeout_s"), "request timeout")
                if timeout_s <= 0 or timeout_s > arm.request_timeout_s:
                    raise TrialError("objective request timeout exceeds its frozen arm")
                index = row.get("execution_index")
                if isinstance(index, bool) or not isinstance(index, int) or index < 1:
                    raise TrialError("completed objective cell lacks execution index")
                execution_indexes.append(index)
                runtime = row.get("runtime_provenance")
                if not isinstance(runtime, dict) or any(
                    runtime.get(key) != expected for key, expected in {
                        "backend": arm.backend, "model": arm.model, "profile": arm.profile,
                        "max_tokens": arm.max_tokens, "seed": arm.seed,
                    }.items()
                ):
                    raise TrialError("objective runtime provenance differs from its arm")
                if not isinstance(runtime.get("model_version"), str) or not isinstance(runtime.get("host_metadata"), dict):
                    raise TrialError("objective runtime identity is incomplete")
                if row.get("runtime_provenance_sha256") != sha256_json(runtime):
                    raise TrialError("objective runtime provenance hash is invalid")
        complete = artifact.get("status") == "complete"
        if artifact.get("status") not in {"complete", "incomplete_budget", "incomplete_transport"}:
            raise TrialError("objective run has an invalid terminal status")
        attempted = sorted(
            (row for row in outcomes if isinstance(row.get("execution_index"), int)),
            key=lambda row: row["execution_index"],
        )
        expected_pair_order = []
        for task_index, task in enumerate(manifest.tasks):
            arm_order = manifest.arms if task_index % 2 == 0 else tuple(reversed(manifest.arms))
            expected_pair_order.extend((task.id, arm.id) for arm in arm_order)
        execution_order = artifact.get("execution_order")
        reconstructed_order = [
            {
                "execution_index": row["execution_index"],
                "task_id": row["task_id"],
                "arm_id": row["arm_id"],
                "request_timeout_s": row["request_timeout_s"],
            }
            for row in attempted
        ]
        if not isinstance(execution_order, list) or execution_order != reconstructed_order:
            raise TrialError("objective execution-order receipt disagrees with its outcomes")
        if complete and [
            (row["task_id"], row["arm_id"]) for row in attempted
        ] != expected_pair_order:
            raise TrialError("objective did not execute the frozen AB/BA order")
        if complete and (
            any(row["status"] not in complete_statuses for row in outcomes)
            or sorted(execution_indexes) != list(range(1, len(outcomes) + 1))
        ):
            raise TrialError("objective completion contradicts its cell outcomes")
        expected_summary = summarize_outcomes(
            outcomes,
            task_ids=[task.id for task in manifest.tasks],
            task_families={task.id: task.family for task in manifest.tasks},
            arm_ids=manifest.arm_ids,
            elapsed_s=finite_nonnegative(artifact.get("elapsed_wall_s"), "objective elapsed wall time"),
            bootstrap_samples=manifest.bootstrap_samples,
            bootstrap_seed=manifest.bootstrap_seed,
        )
        if artifact.get("summary") != expected_summary:
            raise TrialError("objective summary is not reproducible from its outcomes")
        from agent_wrapper.generation_policy import resolve_generation_policy

        all_calls = []
        calls_by_cell = {}
        for arm in manifest.arms:
            rows = json_lines(f"calls.{arm.id}.jsonl", required=complete)
            validate_calls(rows, run_id=artifact.get("run_id"))
            first_seen_tags = []
            for row in rows:
                if row.get("backend") != arm.backend or row.get("model") != arm.model or row.get("seed") != arm.seed:
                    raise TrialError("objective call log differs from its frozen arm")
                if row.get("profile") != arm.profile or row.get("max_tokens") != arm.max_tokens:
                    raise TrialError("objective call policy differs from its frozen arm")
                tag = row.get("caller_tag")
                expected_tags = {f"weekly_upgrade_eval:{task.id}" for task in manifest.tasks}
                if tag not in expected_tags:
                    raise TrialError("objective call log has an unregistered caller tag")
                cell = (tag.removeprefix("weekly_upgrade_eval:"), arm.id)
                if cell not in calls_by_cell:
                    calls_by_cell[cell] = []
                    first_seen_tags.append(tag)
                calls_by_cell[cell].append(row)
            if complete and first_seen_tags != [
                f"weekly_upgrade_eval:{task.id}" for task in manifest.tasks
            ]:
                raise TrialError("objective call log does not cover tasks in frozen order")
            all_calls.extend(rows)
            candidate = regular(f"calls.{arm.id}.jsonl", required=complete)
            if candidate is not None:
                artifact_hashes[candidate.name] = _sha(candidate.read_bytes())
        if complete:
            protocol_failures = {"tool_unknown", "tool_json", "tool_schema", "tool_depth"}
            runtime_identities = {arm.id: set() for arm in manifest.arms}
            for outcome in outcomes:
                task = task_by_id[outcome["task_id"]]
                arm = arm_by_id[outcome["arm_id"]]
                records = tuple(calls_by_cell.get((task.id, arm.id), ()))
                if not records:
                    raise TrialError("objective cell has no durable call record")
                initial_messages = [
                    {"role": "system", "content": task.system},
                    {"role": "user", "content": task.prompt},
                ]
                resolved = resolve_generation_policy(
                    profile=arm.profile,
                    backend_name=arm.backend,
                    model_name=arm.model or records[0].get("model"),
                    seed=arm.seed,
                    caller_tag=f"weekly_upgrade_eval:{task.id}",
                )
                expected_policy = {
                    **dict(resolved.logged_params),
                    "profile": arm.profile,
                    "reasoning_effort": resolved.reasoning_effort,
                    "sampling_extra": dict(resolved.sampling_extra),
                    "max_tokens": arm.max_tokens,
                }
                for record_index, record in enumerate(records):
                    expected_parent = artifact["run_id"] if record_index == 0 else records[record_index - 1]["request_id"]
                    if record.get("parent_request_id") != expected_parent:
                        raise TrialError("objective tool-call parent chain is invalid")
                    if record.get("prompt_messages", [])[:2] != initial_messages:
                        raise TrialError("objective call prompt differs from its frozen task")
                    if any(record.get(key) != value for key, value in expected_policy.items()):
                        raise TrialError("objective effective policy differs from its frozen profile")
                runtime = _runtime_provenance(records)
                tool_calls = _decode_tool_calls(records)
                failure_code = outcome.get("failure_code")
                result = InvocationResult(
                    completion=records[-1]["completion"],
                    records=records,
                    tool_calls=tool_calls,
                    runtime_provenance=runtime,
                    failure_code=failure_code if failure_code in protocol_failures else None,
                )
                request = InvocationRequest(
                    run_id=artifact["run_id"], task=task, arm=arm,
                    request_timeout_s=outcome["request_timeout_s"],
                    calls_log_path=evaluation / f"calls.{arm.id}.jsonl",
                    worker_activity_path=evaluation / "worker_activity.jsonl",
                )
                reproduced = _result_outcome(
                    request=request,
                    execution_index=outcome["execution_index"],
                    result=result,
                    duration_s=outcome["duration_s"],
                )
                if reproduced != outcome:
                    raise TrialError("objective outcome cannot be reproduced from its raw calls")
                runtime_identities[arm.id].add(_sha({
                    "model": runtime.get("model"),
                    "model_version": runtime.get("model_version"),
                    "backend": runtime.get("backend"),
                    "host_metadata": runtime.get("host_metadata"),
                }))
            if any(len(identities) != 1 for identities in runtime_identities.values()):
                raise TrialError("objective runtime identity changed within an arm")
        activity = json_lines("worker_activity.jsonl", required=complete)
        if complete:
            ordered_calls = [
                call
                for execution in execution_order
                for call in calls_by_cell[(execution["task_id"], execution["arm_id"])]
            ]
            validate_activity(activity, ordered_calls, run_id=artifact.get("run_id"))
        activity_path = regular("worker_activity.jsonl", required=complete)
        if activity_path is not None:
            artifact_hashes[activity_path.name] = _sha(activity_path.read_bytes())

    elif plan.get("kind") == "topic_scope":
        from bench.weekly_upgrade_eval.topic_scope import (
            _messages,
            _parse_hypothesis,
            _parse_planner,
            _parse_r0,
            _runtime_identity,
            build_attempts,
            load_manifest,
        )

        manifest = load_manifest(snapshot_path)
        base_attempts = build_attempts(manifest)
        derived_arms = [arm["id"] for arm in manifest["arms"]]
        derived_attempts = [row["attempt_id"] for row in base_attempts]
        if plan.get("include_primary_r0"):
            derived_attempts += [
                row["attempt_id"].replace("hypothesis:", "primary_r0:", 1)
                for row in base_attempts if row["stage"] == "hypothesis"
            ]
        if (
            manifest["_raw_sha256"] != plan["manifest_sha256"]
            or manifest["_configuration_sha256"] != plan.get("manifest_configuration_sha256")
            or derived_arms != plan.get("arm_ids")
            or derived_attempts != expected_attempt_ids
            or plan.get("expected_input_sha256") != {}
            or plan.get("expected_grader_sha256") != {}
        ):
            raise TrialError("topic-scope plan disagrees with its frozen manifest")
        topic_source_paths = (
            "bench/weekly_upgrade_eval/topic_scope.py",
            "orchestrator/coordinator_actions.py",
        )
        expected_topic_sources = {
            name: plan.get("execution_dependencies", {}).get(name)
            for name in topic_source_paths
        }
        if artifact.get("schema_version") != "topic-scope-run/v1" or (
            set(artifact) != {
                "schema_version", "run_id", "status", "manifest_sha256",
                "configuration_sha256", "execution_source_sha256",
                "runtime_budget_s", "include_primary_r0",
                "declared_base_attempts", "declared_primary_r0_attempts",
                "attempts_recorded", "elapsed_s", "outcomes", "promotion_authorized",
            }
            or artifact.get("manifest_sha256") != plan["manifest_sha256"]
            or artifact.get("configuration_sha256") != manifest["_configuration_sha256"]
            or any(value is None for value in expected_topic_sources.values())
            or artifact.get("execution_source_sha256") != expected_topic_sources
            or artifact.get("include_primary_r0") is not plan.get("include_primary_r0")
            or artifact.get("declared_base_attempts") != len(base_attempts)
            or artifact.get("declared_primary_r0_attempts") != len(derived_attempts) - len(base_attempts)
            or artifact.get("attempts_recorded") != len(derived_attempts)
            or artifact.get("promotion_authorized") is not False
        ):
            raise TrialError("topic-scope run header does not match its plan")
        runtime_budget = finite_nonnegative(artifact.get("runtime_budget_s"), "topic runtime budget")
        if runtime_budget != plan.get("payload_budget_s"):
            raise TrialError("topic runtime budget differs from its fixed payload budget")
        if artifact.get("status") not in {"awaiting_annotation", "incomplete_transport", "invalid_runtime_drift"}:
            raise TrialError("topic run has an invalid terminal status")
        finite_nonnegative(artifact.get("elapsed_s"), "topic elapsed wall time")
        outcomes = artifact.get("outcomes")
        if not isinstance(outcomes, list) or [row.get("attempt_id") for row in outcomes if isinstance(row, dict)] != derived_attempts:
            raise TrialError("topic outcomes have missing, duplicated, or reordered attempts")
        raw_rows = json_lines("raw_attempts.jsonl")
        parsed_rows = json_lines("parsed_attempts.jsonl")
        if parsed_rows != outcomes or len(raw_rows) != len(outcomes):
            raise TrialError("topic raw/parsed/run outcome counts or contents disagree")
        call_rows = json_lines("calls.jsonl", required=artifact.get("status") == "awaiting_annotation")
        validate_calls(call_rows, run_id=artifact.get("run_id"))
        returned_records = []
        base_by_id = {row["attempt_id"]: row for row in base_attempts}
        for position, (expected_id, raw_row, parsed_row) in enumerate(
            zip(derived_attempts, raw_rows, parsed_rows, strict=True)
        ):
            if set(raw_row) != {
                "attempt_id", "stage", "case_id", "seed", "arm", "execution_index",
                "request_timeout_s", "status", "completion", "record", "error",
            }:
                raise TrialError("topic raw attempt has an unexpected schema")
            for field in (
                "attempt_id", "stage", "case_id", "seed", "arm", "status",
                "execution_index", "request_timeout_s",
            ):
                if raw_row.get(field) != parsed_row.get(field):
                    raise TrialError(f"topic raw/parsed metadata disagree for {expected_id}")
            if (
                raw_row.get("attempt_id") != expected_id
                or raw_row.get("arm") not in derived_arms
                or raw_row.get("execution_index") != position
            ):
                raise TrialError("topic attempt does not belong to the frozen matrix")
            record = raw_row.get("record")
            if raw_row.get("status") == "returned":
                if not isinstance(record, dict) or raw_row.get("completion") != record.get("completion"):
                    raise TrialError("returned topic attempt lacks its exact raw wrapper record")
                timeout_s = finite_nonnegative(raw_row.get("request_timeout_s"), "topic request timeout")
                if raw_row["stage"] == "primary_r0":
                    config = manifest["primary_r0"]
                    source_id = expected_id.replace("primary_r0:", "hypothesis:", 1)
                    source = next(row for row in outcomes if row["attempt_id"] == source_id)
                    messages = [
                        {"role": "system", "content": config["system"]},
                        {"role": "user", "content": source.get("chosen")},
                    ]
                    caller_tag = "weekly_upgrade.topic_scope.primary_r0"
                    parsed_payload = _parse_r0(record["completion"])
                else:
                    config = manifest["settings"][raw_row["stage"]]
                    messages, case = _messages(manifest, base_by_id[expected_id])
                    caller_tag = f"weekly_upgrade.topic_scope.{raw_row['stage']}"
                    parsed_payload = (
                        _parse_hypothesis(record["completion"])
                        if raw_row["stage"] == "hypothesis"
                        else _parse_planner(record["completion"], case, manifest)
                    )
                if timeout_s <= 0 or timeout_s > float(config["request_timeout_s"]):
                    raise TrialError("topic request timeout exceeds its frozen setting")
                expected_record_fields = {
                    "model": manifest["settings"]["model"],
                    "backend": manifest["settings"]["backend"],
                    "temperature": config["temperature"], "top_p": config["top_p"],
                    "seed": raw_row["seed"], "max_tokens": config["max_tokens"],
                    "caller_tag": caller_tag, "parent_request_id": None,
                    "prompt_messages": messages,
                }
                if any(record.get(key) != value for key, value in expected_record_fields.items()):
                    raise TrialError("topic raw call differs from its frozen prompt/policy")
                if any(key in record for key in ("profile", "reasoning_effort", "sampling_extra")):
                    raise TrialError("topic diagnostic unexpectedly used a named inference profile")
                identity = {
                    "model": record.get("model"), "model_version": record.get("model_version"),
                    "backend": record.get("backend"), "host_metadata": record.get("host_metadata"),
                }
                if parsed_row.get("runtime_identity") != identity:
                    raise TrialError("topic parsed runtime identity differs from raw record")
                checked_identity, drift = _runtime_identity(record, manifest)
                if drift:
                    parsed_payload["protocol_valid"] = False
                    parsed_payload["protocol_error"] = "; ".join(
                        part for part in (parsed_payload.get("protocol_error"), drift) if part
                    )
                reproduced = {
                    **{key: raw_row[key] for key in (
                        "attempt_id", "stage", "case_id", "seed", "arm",
                        "execution_index", "request_timeout_s",
                    )},
                    "status": "returned", "runtime_identity": checked_identity,
                    "runtime_identity_valid": drift is None, **parsed_payload,
                    "duration_s": parsed_row.get("duration_s"),
                }
                if parsed_row != reproduced:
                    raise TrialError("topic parsed result cannot be reproduced from its raw response")
                returned_records.append(record)
            elif record is not None or raw_row.get("completion") is not None:
                raise TrialError("non-returned topic attempt contains a fabricated response")
        if call_rows != returned_records:
            raise TrialError("topic call log is not the exact durable raw-record sequence")
        complete = artifact.get("status") == "awaiting_annotation"
        if complete and any(
            row.get("status") != "returned"
            or row.get("runtime_identity_valid") is not True
            for row in outcomes
        ):
            raise TrialError("topic completion contradicts transport/runtime outcomes")
        identities = {_sha(row.get("runtime_identity")) for row in outcomes if row.get("status") == "returned"}
        if complete and len(identities) != 1:
            raise TrialError("topic run changed runtime identity between attempts")
        activity = json_lines("worker_activity.jsonl", required=complete)
        if complete:
            validate_activity(activity, call_rows, run_id=artifact.get("run_id"))

        blind_path = regular("annotation_blind.json")
        private_path = regular("arm_map_private.json")
        assert blind_path is not None and private_path is not None
        blind = _read(blind_path)
        private = _read(private_path)
        base_ids = [row["attempt_id"] for row in base_attempts]
        blind_items = blind.get("items")
        private_items = private.get("items")
        expected_instructions = {
            "annotation_schema_version": manifest["annotation_contract"]["schema_version"],
            "required_candidate_fields": manifest["annotation_contract"]["required_fields"],
            "domain_enum": manifest["annotation_contract"]["domain"],
            "fidelity_enum": manifest["annotation_contract"]["fidelity"],
            "note": "Annotate semantic content only. Arm identity is intentionally withheld.",
        }
        if (
            set(blind) != {"schema_version", "suite_id", "instructions", "items"}
            or set(private) != {"schema_version", "run_id", "arm_labels", "items"}
            or blind.get("schema_version") != "topic-scope-blind-export/v1"
            or blind.get("suite_id") != manifest["suite_id"]
            or blind.get("instructions") != expected_instructions
            or private.get("schema_version") != "topic-scope-private-map/v1"
            or private.get("run_id") != artifact.get("run_id")
            or not isinstance(blind_items, list) or len(blind_items) != len(base_ids)
            or not isinstance(private_items, list) or len(private_items) != len(base_ids)
        ):
            raise TrialError("topic blind/private artifact headers are invalid")
        labels = private.get("arm_labels")
        if (
            not isinstance(labels, dict) or set(labels) != set(derived_arms)
            or len(set(labels.values())) != len(derived_arms)
            or any(not isinstance(value, str) or not value or value in derived_arms for value in labels.values())
        ):
            raise TrialError("topic private arm labels are invalid")
        private_by_blind = {}
        for row in private_items:
            if not isinstance(row, dict) or set(row) != {"blind_id", "attempt_id", "arm", "blind_arm"}:
                raise TrialError("topic private map row schema is invalid")
            if row["blind_id"] in private_by_blind or row["arm"] not in derived_arms or row["blind_arm"] != labels[row["arm"]]:
                raise TrialError("topic private map has duplicate or inconsistent labels")
            private_by_blind[row["blind_id"]] = row
        if [row["attempt_id"] for row in private_items] != base_ids:
            raise TrialError("topic private map does not cover the exact base attempts")
        outcome_by_id = {row["attempt_id"]: row for row in outcomes}
        seen_blind = set()
        forbidden = {"arm", "attempt_id", "source_commit", "hypothesis_system", "planner_system"}
        stack = [blind]
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                if forbidden.intersection(value):
                    raise TrialError("topic blind export leaks private arm/source fields")
                stack.extend(value.values())
            elif isinstance(value, list):
                stack.extend(value)
        for row in blind_items:
            if not isinstance(row, dict) or row.get("blind_id") in seen_blind:
                raise TrialError("topic blind export has malformed/duplicate rows")
            expected_keys = {
                "blind_id", "blind_arm", "stage", "case_id", "seed", "status",
                "protocol_valid", "protocol_error",
                *(('input_topic', 'scope_anchor', 'candidates') if row.get("stage") == "hypothesis"
                  else ('plan', 'selected_topics')),
            }
            if set(row) != expected_keys:
                raise TrialError("topic blind row has an unexpected schema")
            seen_blind.add(row["blind_id"])
            mapping = private_by_blind.get(row["blind_id"])
            if mapping is None or row.get("blind_arm") != mapping["blind_arm"]:
                raise TrialError("topic blind row is not bound to its private mapping")
            source = outcome_by_id[mapping["attempt_id"]]
            for field in ("stage", "case_id", "seed", "status", "protocol_valid", "protocol_error"):
                if row.get(field) != source.get(field):
                    raise TrialError("topic blind row differs from its parsed source")
            if row["stage"] == "hypothesis":
                candidates = row.get("candidates")
                expected_candidates = [
                    {"candidate_index": index, "text": text, "chosen": index == source.get("chosen_index")}
                    for index, text in enumerate(source.get("candidates") or [])
                ]
                topic = next(item for item in manifest["topics"] if item["id"] == row["case_id"])
                if candidates != expected_candidates or row.get("input_topic") != topic["text"] or row.get("scope_anchor") != topic["scope_anchor"]:
                    raise TrialError("topic blind hypothesis content differs from frozen/parsed inputs")
            elif row["stage"] == "planner":
                if row.get("plan") != (source.get("plan") or []) or row.get("selected_topics") != (source.get("selected_topics") or []):
                    raise TrialError("topic blind planner content differs from parsed output")
            else:
                raise TrialError("topic blind export contains an unexpected stage")
        if seen_blind != set(private_by_blind):
            raise TrialError("topic blind/private mappings do not cover the same rows")
        for candidate in (regular("raw_attempts.jsonl"), regular("parsed_attempts.jsonl"),
                          regular("calls.jsonl", required=complete), regular("worker_activity.jsonl", required=complete),
                          blind_path, private_path):
            if candidate is not None:
                artifact_hashes[candidate.name] = _sha(candidate.read_bytes())
    else:
        raise TrialError("unknown evaluation kind")

    return {
        "path": str(run_path), "sha256": artifact_hashes["run.json"],
        "artifact_sha256": artifact_hashes,
        "status": artifact.get("status"), "execution_complete": complete,
        "semantic_benefit_measured": False,
    }


def _recover(plan: dict, output: Path, state_path: Path, ledger: BudgetLedger,
             root: Path, probe: Callable) -> dict:
    """The caller owns both resource locks; no child can be silently replayed."""
    state = _read(state_path)
    binding = _sha({"plan": plan, "output": str(output)})
    if state.get("binding_sha256") != binding or state.get("plan") != plan:
        raise TrialError("execution journal binds a different plan or artifact directory")
    live = live_trial_processes(output)
    if live:
        raise TrialError(f"trial still has live process handles: {live}")
    prior = ledger.existing(plan["trial_id"])
    if prior is None:
        # Preparation occurs before reservation and process launch. A clean
        # prepared directory can resume that not-yet-started transaction.
        if state.get("phase") != "prepared" or (output / "evaluation").exists():
            raise TrialError("execution state has no matching budget receipt")
        return {}
    if prior["manifest_sha256"] != binding:
        raise TrialError("budget receipt binds a different artifact root")
    if state.get("phase") == "finished":
        result = state["result"]
        if (result.get("plan_sha256") != _sha(plan)
                or result.get("trial_id") != plan["trial_id"]
                or prior["state"] != "finished"
                or result.get("status") != prior["status"]
                or result.get("budget_receipt") != prior):
            raise TrialError("terminal execution journal/ledger mismatch")
        # Canonical receipt wins if a caller's output copy was absent/tampered.
        _write(output / "trial_result.json", result)
        return result
    # Locks are free and process handles are absent. Verify resident cancellation
    # before terminalizing; a disconnected HTTP request may still be decoding.
    probe(root, idle=True)
    measured = None
    try:
        measured = evaluation_receipt(plan, output)
    except (OSError, ValueError, TrialError):
        pass
    prepared = state.get("result") if state.get("phase") == "finishing" else None
    if prepared is not None:
        if (prepared.get("plan_sha256") != _sha(plan)
                or prepared.get("trial_id") != plan["trial_id"]
                or prepared.get("status") not in {"completed", "failed", "cancelled", "interrupted"}
                or not isinstance(prepared.get("elapsed_s"), (int, float))
                or not math.isfinite(prepared["elapsed_s"]) or prepared["elapsed_s"] < 0):
            raise TrialError("invalid prepared terminal receipt")
        if prepared["status"] == "completed" and not (measured and measured["execution_complete"]):
            raise TrialError("prepared completion no longer has its exact evaluation artifacts")
    receipt = prior
    if prior["state"] == "reserved":
        receipt = ledger.finish(
            plan["trial_id"], prepared["elapsed_s"] if prepared else plan["reservation_s"],
            prepared["status"] if prepared else "interrupted",
        )
    if receipt["status"] == "completed" and not (measured and measured["execution_complete"]):
        raise TrialError("completed budget receipt has no valid completion artifacts")
    if prepared is not None and (prepared["status"] != receipt["status"]
                                 or prepared["elapsed_s"] != receipt["elapsed_s"]):
        raise TrialError("prepared terminal receipt disagrees with budget ledger")
    result = prepared or {
        "schema_version": "weekly-upgrade-trial-result/v1", "trial_id": plan["trial_id"],
        "plan_sha256": _sha(plan), "process": None,
        "evaluation_dir": str(output / "evaluation"),
        "error": ("recovered without replay; uncertain time fully charged"
                  if receipt["status"] == "interrupted" else "recovered from terminal budget receipt"),
        "semantic_benefit_measured": False, "production_change_authorized": False,
    }
    result = {**result, "status": receipt["status"], "elapsed_s": receipt["elapsed_s"],
              "budget_receipt": receipt, "evaluation": measured}
    _write(state_path, {**state, "phase": "finished", "result": result})
    _write(output / "trial_result.json", result)
    return result


def execute_trial(plan: dict, output_dir: Path, *, worktree: Path = ROOT,
                  review_dir: Path | None = None, manual: bool = False,
                  probe: Callable = resource_probe, runner: Callable = supervise) -> dict:
    """One execution per week/manifest. Resume reads evidence, never replays."""
    from bench.weekly_upgrade_eval.runner import validate_output_dir
    worktree = worktree.resolve()
    if not manual and review_dir is None:
        raise TrialError("execution requires a validated review or explicit manual invocation")
    if manual and review_dir is not None:
        raise TrialError("manual and reviewed execution are separate explicit modes")
    expected = plan_trial(plan["manifest_path"], worktree=worktree, review_dir=review_dir)
    if plan != expected:
        raise TrialError("execution plan differs from the current registered/reviewed plan")
    root = canonical_root(worktree)
    output = Path(output_dir).resolve()
    if any(output == repo or repo in output.parents for repo in (root, worktree)):
        raise TrialError("evaluation artifacts must be outside both canonical and execution checkouts")
    if _sha((worktree / plan["manifest_path"]).read_bytes()) != plan["manifest_sha256"]:
        raise TrialError("manifest changed after planning")
    current_week = datetime.now(timezone.utc).strftime("%G-W%V")
    if plan["week_id"] != current_week:
        raise TrialError("trial plan has crossed a week boundary")
    assert_budget_journal_consistent(root, current_week)
    ledger = BudgetLedger(root / "run_state" / "weekly_upgrade_budget.jsonl")
    with resource_lease(root) as descriptors:
        state_dir = root / "run_state" / "weekly_upgrade" / "trials"
        state_dir.mkdir(parents=True, exist_ok=True)
        state_path = state_dir / f"{plan['trial_id']}.json"
        binding = _sha({"plan": plan, "output": str(output)})
        if state_path.exists():
            recovered = _recover(plan, output, state_path, ledger, root, probe)
            if recovered:
                return recovered
        else:
            if ledger.existing(plan["trial_id"]) is not None:
                raise TrialError("existing budget reservation has no execution journal; investigate")
            validate_output_dir(output)
            _write(state_path, {"phase": "prepared", "plan": plan, "output": str(output),
                                "binding_sha256": binding})
        if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all", "--",
                                    plan["manifest_path"], *DEPENDENCY_PATHS],
                                   cwd=worktree, text=True).strip():
            raise TrialError("freeze the registered manifest and execution dependencies in Git before calls")
        context_preflight = None
        if plan["manifest_path"] == CONTEXT_MANIFEST:
            from bench.weekly_upgrade_context.preflight import (
                validate_context_preflight,
            )

            # Offline CPU tokenization; reject drift before reserving GPU work.
            # This includes the pinned default reasoning template and output
            # reserve, not just an approximate count of the evidence text.
            context_preflight = validate_context_preflight(worktree / plan["manifest_path"])
        output.mkdir(parents=True, exist_ok=True)
        _write(output / "trial_plan.json", plan)
        if context_preflight is not None:
            _write(output / "context_preflight.json", context_preflight)
        start = time.monotonic()
        ledger.reserve(plan["trial_id"], plan["reservation_s"], binding)
        _write(state_path, {"phase": "reserved", "plan": plan, "output": str(output),
                            "binding_sha256": binding})
        terminal, error, process_result, measured, before = "failed", None, None, None, None
        try:
            before = probe(root, idle=True)
            _write(output / "preflight.json", before)
            command = trial_command(plan, output / "evaluation", plan["reservation_s"] - (time.monotonic() - start),
                                    worktree=worktree)
            process_result = runner(command, worktree=worktree, output=output,
                                    pass_fds=descriptors, root=root, probe=probe)
            measured = evaluation_receipt(plan, output)
            terminal = ("completed" if process_result["returncode"] == 0
                        and measured["execution_complete"] else "failed")
        except (Exception, KeyboardInterrupt) as exc:  # noqa: BLE001 -- durable dispatch boundary
            error = f"{type(exc).__name__}: {exc}"
            terminal = ("interrupted" if isinstance(exc, UnconfirmedStop)
                        else "cancelled" if isinstance(exc, KeyboardInterrupt) else "failed")
        # A disconnected HTTP client need not imply a stopped server request.
        # Only confirmed idle endpoints can release unused reserved time.
        try:
            after = probe(root, idle=True)
            _write(output / "postflight.json", after)
            if before is not None and after.get("runtime_identity") != before.get("runtime_identity"):
                terminal, error = "interrupted", "resident serving runtime changed during execution"
            if execution_fingerprint(worktree) != plan["execution_dependencies"]:
                terminal, error = "interrupted", "execution dependencies changed during execution"
        except Exception as exc:  # noqa: BLE001 -- uncertain cleanup retains full reservation
            terminal = "interrupted"
            error = f"{error or ''}; postflight cancellation unconfirmed: {type(exc).__name__}: {exc}"
        elapsed = time.monotonic() - start
        result = {
            "schema_version": "weekly-upgrade-trial-result/v1", "trial_id": plan["trial_id"],
            "status": terminal, "plan_sha256": _sha(plan), "elapsed_s": elapsed,
            "process": process_result, "error": error,
            "evaluation": measured,
            "evaluation_dir": str(output / "evaluation"), "semantic_benefit_measured": False,
            "production_change_authorized": False,
        }
        # Write the measured terminal transition before budget release. Recovery
        # can then finish either side of this two-file transaction idempotently.
        _write(state_path, {"phase": "finishing", "plan": plan, "output": str(output),
                            "binding_sha256": binding, "result": result})
        receipt = ledger.finish(plan["trial_id"], elapsed, terminal)
        result["budget_receipt"] = receipt
        _write(state_path, {"phase": "finished", "plan": plan, "output": str(output),
                            "binding_sha256": binding, "result": result})
        _write(output / "trial_result.json", result)
        return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--manifest", required=True, choices=sorted(TRIALS))
    admission = parser.add_mutually_exclusive_group()
    admission.add_argument("--review-dir", type=Path)
    admission.add_argument("--manual", action="store_true", help="explicit supervised preregistered experiment")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        plan = plan_trial(args.manifest, review_dir=args.review_dir)
        if args.plan:
            print(json.dumps(plan, indent=2))
            return 0
        if args.output_dir is None:
            parser.error("--run requires --output-dir")
        result = execute_trial(plan, args.output_dir, review_dir=args.review_dir, manual=args.manual)
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "completed" else 1
    except (ValueError, OSError, TrialError, BudgetError, ValidationError,
            subprocess.SubprocessError, review.WeeklyUpgradeError) as exc:
        print(f"weekly trial refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
