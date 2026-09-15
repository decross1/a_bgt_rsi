"""Bounded public history of the four fixed guarded research bridge IDs.

These attempts are operational observations. A terminal guard result is not a
productive loop iteration or an admitted empirical/scientific result.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

from . import model_runtime as mr

ROOT = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/"
    "lab-eight-hour/research-bridge"
)
SCHEMA = "guarded-research-attempts-observation/v1"
B_AUDIT_RAW_SHA256 = "8f067d6d963973ca0f4c471e53e7502be91ba26f8b7c5427d7afe813a91b4d61"
CAMPAIGN_ID = "v2-known-opponent-utility-20260915"
CAMPAIGN_MANIFEST_SHA256 = "c0b09e366bf7b8ffe7af58bf7b00e4c0fb7f33eb83a5111f2a465c12fc0be4f7"
PILOT_RUN_SHA256 = "70763bd0c9a685722a3d01a5412abfbed1bebcf2eb0c7707578709115521c4be"
IDS = tuple(
    f"qfn-followon-known-opponent-lab8h-bridge-{arm}" for arm in "dcba"
)
ARCHIVED_SHA256 = {
    IDS[3]: {
        "plan": "bfd11c6c37a48a9f5749074b8b5714208820ec8ab14ae50988ced8b49c4ab0dd",
        "state": "f72e70f0c05e9d5edf92dc37885ce7cf855fe26a691d30834e0f884a6afb1188",
        "result": "223b4f6b072e2fe7260ffd29188471c1204705ab818a82f90d221083f3736b7b",
        "parent": "145ff9d3503ac9c5f058873b03e3a0032bd1071119655f4e57cab4195eafbfd1",
    },
    IDS[2]: {
        "plan": "9ce380db7ed95eb6bf8f5708e428878d1acfe5061667e23fd604fc50c2a05fc7",
        "state": "915c96d940ef593d6cc96ebda44e120194b0a3f2fbcc12cac1803e61a9c17ea6",
        "result": "38c5556c149035a3f0d737fa83889d163b04b7524c8bfd19d8eac38a4b88006a",
        "parent": "44421db82785611b06b8610fd7cd734189ef545730a6457a8eeae5ab2357a0e0",
    },
    IDS[1]: {
        "plan": "0960ae7b4d4f4bc188491dae2f136e6a71d1fbff49c71cb495abbe93e0a6dfa7",
        "state": "55b25826e88ebc66a9bcbb786d0b03a441572896e8182f7fc9df80f71c2f365d",
        "result": "1a92fbdedcb97c3241107244e4d58fd9e4d2a2660eb1569b62fa0973f80b8668",
        "parent": "9c1a9a5b7f1d8c22f52ed2ef28ab41e1764ff9285d51326617db188a5e35a22b",
    },
}
SHA = re.compile(r"[0-9a-f]{64}\Z")
ITERATION = re.compile(r"iter-[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{3}\Z")
JOURNAL = re.compile(r"journal/iterations/[0-9]{3}\.md\Z")
ROLES = (
    "nara", "critic", "debate_challenger", "debate_defender",
    "restate_judge", "skeptic",
)


def _read(path: Path, maximum: int) -> tuple[dict, str]:
    raw = mr._read_path(path, maximum=maximum, label="guarded research public receipt")
    return mr._strict_object(raw, "guarded research public receipt"), hashlib.sha256(raw).hexdigest()


def _sha(value: object) -> bool:
    return isinstance(value, str) and SHA.fullmatch(value) is not None


def _utc(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo == timezone.utc else None


def _restored(value: object) -> bool:
    return isinstance(value, dict) and value.get("status") == "verified" and (
        value.get("errors") == [] and value.get("sentinel_retained") is False
    )


def _unknown(window_id: str) -> dict:
    return {
        "window_id": window_id, "terminal_status": "source_unavailable",
        "restoration_status": "unknown", "final_record_status": "unknown",
        "started_at": None, "finished_at": None, "result_raw_sha256": None,
        "state_raw_sha256": None, "plan_raw_sha256": None,
        "parent_emergency_raw_sha256": None, "partial_prompt_receipts": None,
        "partial_audit_raw_sha256": None, "iteration_id": None,
        "loop_memory_raw_sha256": None, "journal_raw_sha256": None,
        "scientific_admission_claimed": False,
    }


def _parent_restoration(root: Path, window_id: str, *, plan_sha: str,
                        state_sha: str, child_code: int) -> tuple[str, str | None]:
    path = root / f"{window_id}.emergency-recovery.json"
    if not path.is_file() or path.is_symlink():
        return "guard_verified_parent_unverified", None
    parent, parent_sha = _read(path, 16_384)
    archived = ARCHIVED_SHA256.get(window_id) if root == ROOT else None
    if archived is not None and parent_sha != archived["parent"]:
        raise ValueError("archived parent receipt differs")
    recovery = parent.get("recovery")
    sources = recovery.get("source_refs") if isinstance(recovery, dict) else None
    if (parent.get("schema") != "guarded-empirical-research-bridge-emergency/v1"
            or parent.get("window_id") != window_id
            or parent.get("scientific_admission_by_parent") is not False
            or parent.get("research_outcome") != "unknown_partial_or_incomplete"
            or parent.get("guard_returncode") != child_code
            or not isinstance(sources, dict)
            or sources.get("plan_raw_sha256") != plan_sha
            or sources.get("state_raw_sha256") != state_sha):
        raise ValueError("parent closure differs from the fixed guard receipt")
    if (recovery.get("status") == "restoration_verified"
            and recovery.get("errors") == []
            and _restored(recovery.get("restoration"))):
        return "guard_and_parent_verified", parent_sha
    return "guard_verified_parent_unverified", parent_sha


def _partial_audit(root: Path, window_id: str, *, plan_sha: str,
                   state_sha: str, result_sha: str) -> tuple[int | None, str | None]:
    if window_id != IDS[2]:
        return None, None
    path = root / f"{window_id}.partial-prompt-audit.json"
    if not path.is_file() or path.is_symlink():
        return None, None
    audit, audit_sha = _read(path, 4096)
    if root == ROOT and audit_sha != B_AUDIT_RAW_SHA256:
        return None, None
    roles = audit.get("roles")
    if (audit.get("schema") != "bridge-b-empirical-prompt-chronology/v1"
            or audit.get("window_id") != window_id
            or audit.get("evidence_status") != "partial_restored_unadmitted"
            or audit.get("scientific_result") != "not_recorded_or_admitted"
            or audit.get("private_content_exported") is not False
            or audit.get("plan_sha256") != plan_sha
            or audit.get("state_sha256") != state_sha
            or audit.get("result_sha256") != result_sha
            or not isinstance(roles, dict) or set(roles) != set(ROLES)):
        return None, None
    expected = {
        "nara": 12, "critic": 1, "debate_challenger": 1,
        "debate_defender": 1, "restate_judge": 0, "skeptic": 0,
    }
    if any(
        not isinstance(roles[name], dict)
        or roles[name].get("observed") != count
        or roles[name].get("with_exact_hash") != count
        or roles[name].get("status") != (
            "all_prompts_bound" if count else "not_run"
        )
        for name, count in expected.items()
    ):
        return None, None
    return 15, audit_sha


def _final_record(repo_root: Path, iteration: dict, plan: dict, *,
                  started: datetime, finished: datetime) -> tuple[str, str] | None:
    """Join a guard summary to one exact loop row and its journal file."""
    iteration_id = iteration.get("iteration_id")
    if (not isinstance(iteration_id, str) or ITERATION.fullmatch(iteration_id) is None
            or iteration.get("campaign_id") != CAMPAIGN_ID
            or iteration.get("pilot_run_sha256") != plan.get("pilot_run_sha256")
            or not _sha(iteration.get("pilot_run_sha256"))):
        return None
    raw = mr._read_path(
        repo_root / "memory/loop_memory.jsonl", maximum=16_000_000,
        label="loop memory for guarded iteration receipt",
    )
    matches = []
    for line in raw.splitlines():
        if not line:
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            return None
        if row.get("iteration_id") == iteration_id:
            matches.append(row)
    if len(matches) != 1:
        return None
    row = matches[0]
    seed = row.get("seed")
    campaign = row.get("campaign")
    critique = row.get("critique")
    novelty = row.get("novelty")
    journal = row.get("journal_entry_path")
    row_started, row_ended = _utc(row.get("started_at")), _utc(row.get("ended_at"))
    plan_recorded = _utc(plan.get("recorded_at"))
    if (not isinstance(seed, dict)
            or seed.get("source") != "known_opponent_utility_bridge"
            or not isinstance(campaign, dict)
            or campaign.get("campaign_id") != CAMPAIGN_ID
            or campaign.get("campaign_manifest_sha256") !=
            plan.get("campaign_manifest_sha256")
            or campaign.get("topic_id") != plan.get("topic_id")
            or not isinstance(plan.get("experiment_outcome"), dict)
            or row.get("experiment_outcome") != plan.get("experiment_outcome")
            or row_started is None or row_ended is None or plan_recorded is None
            or not plan_recorded <= started <= row_started <= row_ended <= finished
            or not isinstance(critique, dict)
            or critique.get("verdict") != iteration.get("critic_verdict")
            or not isinstance(novelty, dict)
            or novelty.get("class") != iteration.get("novelty_class")
            or not isinstance(journal, str) or JOURNAL.fullmatch(journal) is None):
        return None
    journal_raw = mr._read_path(
        repo_root / journal, maximum=1_000_000,
        label="guarded iteration public journal",
    )
    return hashlib.sha256(raw).hexdigest(), hashlib.sha256(journal_raw).hexdigest()


def project_attempts(*, producer_view: dict, root: Path = ROOT,
                     repo_root: Path, now: datetime | None = None) -> dict:
    observed = now or datetime.now(timezone.utc)
    if observed.tzinfo != timezone.utc:
        observed = observed.astimezone(timezone.utc)
    rows = []
    campaign = producer_view.get("active_campaign")
    pilot = producer_view.get("empirical_pilot")
    for window_id in IDS:
        result_path = root / window_id / "result.json"
        state_path = root / window_id / "state.json"
        row = _unknown(window_id)
        if not result_path.exists() and not result_path.is_symlink():
            row["terminal_status"] = "no_terminal_receipt"
            rows.append(row)
            continue
        try:
            plan, plan_sha = _read(root / window_id / "plan.json", 16_384)
            state, state_sha = _read(state_path, 16_384)
            result, result_sha = _read(result_path, 16_384)
            archived = ARCHIVED_SHA256.get(window_id) if root == ROOT else None
            if archived is not None and (
                plan_sha != archived["plan"] or state_sha != archived["state"]
                or result_sha != archived["result"]
            ):
                raise ValueError("archived terminal receipt differs")
            started, finished = _utc(state.get("started_at")), _utc(result.get("finished_at"))
            restore = result.get("restoration")
            elapsed = result.get("elapsed_s")
            registration_bound = (
                plan.get("campaign_manifest_sha256") == CAMPAIGN_MANIFEST_SHA256
                and plan.get("pilot_run_sha256") == PILOT_RUN_SHA256
            ) if root == ROOT else (
                isinstance(campaign, dict)
                and campaign.get("campaign_id") == CAMPAIGN_ID
                and plan.get("campaign_manifest_sha256") ==
                campaign.get("manifest_sha256")
                and isinstance(pilot, dict)
                and pilot.get("status") == "recorded_admitted"
                and plan.get("pilot_run_sha256") == pilot.get("pilot_run_sha256")
            )
            if (producer_view.get("schema") != "research-ops-status/v1"
                    or not registration_bound
                    or plan.get("schema") != "guarded-empirical-research-bridge/v1"
                    or plan.get("window_id") != window_id
                    or plan.get("campaign_id") != CAMPAIGN_ID
                    or not _sha(plan.get("guard_source_sha256"))
                    or plan.get("scientific_admission_by_this_guard") is not False
                    or state.get("schema") != "guarded-empirical-research-bridge-state/v1"
                    or result.get("schema") != "guarded-empirical-research-bridge-result/v1"
                    or result.get("scientific_admission_by_this_guard") is not False
                    or result.get("human_gate_bypassed") is not False
                    or state.get("restoration") != restore or not _restored(restore)
                    or started is None or finished is None
                    or not started <= finished <= observed
                    or type(elapsed) not in (int, float) or not math.isfinite(elapsed)
                    or not 0 <= elapsed <= 10_800):
                raise ValueError("guarded attempt identity or restoration differs")
            row.update(
                started_at=state["started_at"], finished_at=result["finished_at"],
                result_raw_sha256=result_sha, state_raw_sha256=state_sha,
                plan_raw_sha256=plan_sha,
                restoration_status="guard_verified_parent_unverified",
            )
            if result.get("status") == "incomplete":
                child_code = result.get("child_returncode")
                if (state.get("phase") != "incomplete"
                        or result.get("iteration") is not None
                        or result.get("error") is None
                        or type(child_code) is not int or child_code == 0):
                    raise ValueError("incomplete guard result differs")
                restoration_status, parent_sha = _parent_restoration(
                    root, window_id, plan_sha=plan_sha, state_sha=state_sha,
                    child_code=child_code,
                )
                prompts, audit_sha = _partial_audit(
                    root, window_id, plan_sha=plan_sha, state_sha=state_sha,
                    result_sha=result_sha,
                )
                row.update(
                    terminal_status="incomplete", final_record_status="absent",
                    restoration_status=restoration_status,
                    parent_emergency_raw_sha256=parent_sha,
                    partial_prompt_receipts=prompts,
                    partial_audit_raw_sha256=audit_sha,
                )
            elif result.get("status") == "recorded_restored":
                iteration = result.get("iteration")
                if (state.get("phase") != "recorded_restored"
                        or result.get("error") is not None
                        or result.get("child_returncode") != 0
                        or not isinstance(iteration, dict)
                        or (root / f"{window_id}.emergency-recovery.json").exists()
                        or (root / f"{window_id}.emergency-recovery.json").is_symlink()):
                    raise ValueError("recorded guard result differs")
                row.update(
                    terminal_status="guard_recorded_final_unverified",
                    final_record_status="unverified",
                    iteration_id=iteration.get("iteration_id")
                    if isinstance(iteration.get("iteration_id"), str) and
                    ITERATION.fullmatch(iteration["iteration_id"]) else None,
                )
                try:
                    final = _final_record(
                        repo_root, iteration, plan, started=started, finished=finished,
                    )
                except (OSError, RuntimeError, ValueError, TypeError, KeyError,
                        json.JSONDecodeError):
                    final = None
                if final is not None:
                    row.update(
                        terminal_status="guard_recorded_final_bound",
                        final_record_status="bound",
                        loop_memory_raw_sha256=final[0],
                        journal_raw_sha256=final[1],
                    )
            else:
                raise ValueError("guarded attempt terminal status differs")
        except (OSError, RuntimeError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            row = _unknown(window_id)
        rows.append(row)
    latest = next(
        (row["window_id"] for row in rows if row["terminal_status"] not in (
            "no_terminal_receipt", "source_unavailable")),
        None,
    )
    return {
        "schema_version": SCHEMA,
        "observed_at": observed.astimezone(timezone.utc).isoformat(),
        "source_status": "available" if root.is_dir() and not root.is_symlink()
        else "source_unknown",
        "latest_terminal_window_id": latest,
        "attempts": rows,
        "current_source_replay": "not_performed",
        "scientific_admission_claimed": False,
        "private_content_exported": False,
    }
