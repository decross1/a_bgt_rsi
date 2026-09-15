"""Public A/B/C guarded history stays distinct from productive campaign records."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from backend import guarded_research_attempts as attempts

SHA = "a" * 64
CAMPAIGN = attempts.CAMPAIGN_ID
PILOT_SHA = "b" * 64
EXPERIMENT = {
    "experiment_id": "known-opponent-utility-response-pilot-v1",
    "metric": "disclosed_utility_action_validity_and_full_horizon_regret",
    "value": {"run_sha256": PILOT_SHA, "complete_episodes": 12},
    "trials": 12,
}
NOW = datetime(2026, 9, 15, 21, 0, tzinfo=timezone.utc)


def _write(path: Path, value: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _view() -> dict:
    return {
        "schema": "research-ops-status/v1",
        "active_campaign": {"campaign_id": CAMPAIGN, "manifest_sha256": SHA},
        "empirical_pilot": {
            "status": "recorded_admitted", "pilot_run_sha256": PILOT_SHA,
        },
    }


def _receipt(root: Path, arm: str, *, status: str, started: str,
             finished: str) -> tuple[Path, str, str, str]:
    window_id = attempts.IDS["cba".index(arm)]
    child = root / window_id
    plan = {
        "schema": "guarded-empirical-research-bridge/v1",
        "window_id": window_id, "campaign_id": CAMPAIGN,
        "campaign_manifest_sha256": SHA, "pilot_run_sha256": PILOT_SHA,
        "topic_id": "topic-known-retain-utility-001",
        "experiment_outcome": EXPERIMENT,
        "guard_source_sha256": SHA,
        "scientific_admission_by_this_guard": False,
        "recorded_at": started,
    }
    plan_sha = _write(child / "plan.json", plan)
    restoration = {"status": "verified", "errors": [], "sentinel_retained": False}
    state = {
        "schema": "guarded-empirical-research-bridge-state/v1",
        "phase": "incomplete" if status == "incomplete" else "recorded_restored",
        "started_at": started, "restoration": restoration,
        "private_prompt_text": "must not leave the API",
    }
    state_sha = _write(child / "state.json", state)
    result = {
        "schema": "guarded-empirical-research-bridge-result/v1",
        "status": status, "finished_at": finished, "elapsed_s": 90.0,
        "restoration": restoration, "human_gate_bypassed": False,
        "scientific_admission_by_this_guard": False,
        "child_returncode": 1 if status == "incomplete" else 0,
        "iteration": None if status == "incomplete" else {
            "iteration_id": "iter-2026-09-15-005", "campaign_id": CAMPAIGN,
            "pilot_run_sha256": PILOT_SHA, "critic_verdict": "refuted",
            "novelty_class": "empirical",
        },
        "error": "child exited 1" if status == "incomplete" else None,
    }
    result_sha = _write(child / "result.json", result)
    if status == "incomplete":
        parent = {
            "schema": "guarded-empirical-research-bridge-emergency/v1",
            "window_id": window_id, "scientific_admission_by_parent": False,
            "research_outcome": "unknown_partial_or_incomplete",
            "guard_returncode": 1,
            "recovery": {
                "status": "recovery_unknown" if arm == "a" else "restoration_verified",
                "errors": ["parent could not verify old Nara PID"] if arm == "a" else [],
                "restoration": None if arm == "a" else restoration,
                "source_refs": {
                    "plan_raw_sha256": plan_sha, "state_raw_sha256": state_sha,
                },
            },
        }
        _write(root / f"{window_id}.emergency-recovery.json", parent)
    return child, plan_sha, state_sha, result_sha


def _b_audit(root: Path, *, plan_sha: str, state_sha: str, result_sha: str) -> None:
    expected = {
        "nara": 12, "critic": 1, "debate_challenger": 1,
        "debate_defender": 1, "restate_judge": 0, "skeptic": 0,
    }
    audit = {
        "schema": "bridge-b-empirical-prompt-chronology/v1",
        "window_id": attempts.IDS[1],
        "evidence_status": "partial_restored_unadmitted",
        "scientific_result": "not_recorded_or_admitted",
        "private_content_exported": False,
        "plan_sha256": plan_sha, "state_sha256": state_sha,
        "result_sha256": result_sha,
        "roles": {
            name: {
                "observed": count, "with_exact_hash": count,
                "status": "all_prompts_bound" if count else "not_run",
            }
            for name, count in expected.items()
        },
        "raw_private_prompt": "must not leave the API",
    }
    _write(root / f"{attempts.IDS[1]}.partial-prompt-audit.json", audit)


def _root(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "research-bridge"
    repo = tmp_path / "repo"
    root.mkdir()
    (repo / "memory").mkdir(parents=True)
    (repo / "memory/loop_memory.jsonl").write_bytes(b"")
    _, a_plan, a_state, a_result = _receipt(
        root, "a", status="incomplete",
        started="2026-09-15T19:30:50+00:00",
        finished="2026-09-15T19:30:53+00:00",
    )
    _ = a_plan, a_state, a_result
    _, b_plan, b_state, b_result = _receipt(
        root, "b", status="incomplete",
        started="2026-09-15T19:36:17+00:00",
        finished="2026-09-15T19:39:29+00:00",
    )
    _b_audit(root, plan_sha=b_plan, state_sha=b_state, result_sha=b_result)
    return root, repo


def test_fixed_a_b_history_preserves_parent_restoration_disagreement(tmp_path):
    root, repo = _root(tmp_path)
    view = attempts.project_attempts(
        producer_view=_view(), root=root, repo_root=repo, now=NOW,
    )
    assert view["latest_terminal_window_id"] == attempts.IDS[1]
    c, b, a = view["attempts"]
    assert c["terminal_status"] == "no_terminal_receipt"
    assert b["terminal_status"] == a["terminal_status"] == "incomplete"
    assert b["restoration_status"] == "guard_and_parent_verified"
    assert a["restoration_status"] == "guard_verified_parent_unverified"
    assert b["partial_prompt_receipts"] == 15
    assert a["partial_prompt_receipts"] is None
    assert b["final_record_status"] == a["final_record_status"] == "absent"
    assert "raw_private_prompt" not in str(view)
    assert "private_prompt_text" not in str(view)
    assert view["scientific_admission_claimed"] is False


def test_tampered_terminal_source_withholds_the_attempt_without_hiding_others(tmp_path):
    root, repo = _root(tmp_path)
    b = root / attempts.IDS[1] / "state.json"
    state = json.loads(b.read_text())
    state["restoration"]["sentinel_retained"] = True
    _write(b, state)
    view = attempts.project_attempts(
        producer_view=_view(), root=root, repo_root=repo, now=NOW,
    )
    assert view["attempts"][1]["terminal_status"] == "source_unavailable"
    assert view["attempts"][2]["terminal_status"] == "incomplete"
    assert view["latest_terminal_window_id"] == attempts.IDS[2]


def test_registered_b_partial_count_requires_immutable_archived_audit_hash(
        tmp_path, monkeypatch):
    root, repo = _root(tmp_path)
    monkeypatch.setattr(attempts, "ROOT", root)
    monkeypatch.setattr(attempts, "ARCHIVED_SHA256", {})
    monkeypatch.setattr(attempts, "CAMPAIGN_MANIFEST_SHA256", SHA)
    monkeypatch.setattr(attempts, "PILOT_RUN_SHA256", PILOT_SHA)
    view = attempts.project_attempts(
        producer_view=_view(), root=root, repo_root=repo, now=NOW,
    )
    assert view["attempts"][1]["terminal_status"] == "incomplete"
    assert view["attempts"][1]["partial_prompt_receipts"] is None
    assert view["attempts"][1]["partial_audit_raw_sha256"] is None


def test_archived_bridge_history_survives_later_campaign_activation(
        tmp_path, monkeypatch):
    root, repo = _root(tmp_path)
    monkeypatch.setattr(attempts, "ROOT", root)
    monkeypatch.setattr(attempts, "ARCHIVED_SHA256", {})
    monkeypatch.setattr(attempts, "CAMPAIGN_MANIFEST_SHA256", SHA)
    monkeypatch.setattr(attempts, "PILOT_RUN_SHA256", PILOT_SHA)
    changed = {"schema": "research-ops-status/v1",
               "active_campaign": {"campaign_id": "successor",
                                   "manifest_sha256": "c" * 64},
               "empirical_pilot": None}
    view = attempts.project_attempts(
        producer_view=changed, root=root, repo_root=repo, now=NOW,
    )
    assert view["attempts"][1]["terminal_status"] == "incomplete"
    assert view["attempts"][2]["terminal_status"] == "incomplete"
    assert view["latest_terminal_window_id"] == attempts.IDS[1]


def test_registered_terminal_receipt_rejects_resealed_harmless_field(
        tmp_path, monkeypatch):
    root, repo = _root(tmp_path)
    b_id = attempts.IDS[1]
    child = root / b_id
    registered = {
        key: hashlib.sha256(path.read_bytes()).hexdigest()
        for key, path in {
            "plan": child / "plan.json", "state": child / "state.json",
            "result": child / "result.json",
            "parent": root / f"{b_id}.emergency-recovery.json",
        }.items()
    }
    monkeypatch.setattr(attempts, "ROOT", root)
    monkeypatch.setattr(attempts, "ARCHIVED_SHA256", {b_id: registered})
    monkeypatch.setattr(attempts, "CAMPAIGN_MANIFEST_SHA256", SHA)
    monkeypatch.setattr(attempts, "PILOT_RUN_SHA256", PILOT_SHA)
    valid = attempts.project_attempts(
        producer_view=_view(), root=root, repo_root=repo, now=NOW,
    )
    assert valid["attempts"][1]["terminal_status"] == "incomplete"
    result = json.loads((child / "result.json").read_text())
    result["harmless_public_note"] = "resealed"
    _write(child / "result.json", result)
    rejected = attempts.project_attempts(
        producer_view=_view(), root=root, repo_root=repo, now=NOW,
    )
    assert rejected["attempts"][1]["terminal_status"] == "source_unavailable"


def test_c_guard_record_does_not_claim_final_record_until_loop_and_journal_bind(tmp_path):
    root, repo = _root(tmp_path)
    _receipt(
        root, "c", status="recorded_restored",
        started="2026-09-15T20:10:00+00:00",
        finished="2026-09-15T20:13:00+00:00",
    )
    pending = attempts.project_attempts(
        producer_view=_view(), root=root, repo_root=repo, now=NOW,
    )
    assert pending["attempts"][0]["terminal_status"] == "guard_recorded_final_unverified"
    assert pending["attempts"][0]["final_record_status"] == "unverified"
    journal = "journal/iterations/397.md"
    (repo / journal).parent.mkdir(parents=True)
    (repo / journal).write_text("# Recorded iteration\n", encoding="utf-8")
    memory = {
        "iteration_id": "iter-2026-09-15-005",
        "started_at": "2026-09-15T20:11:00+00:00",
        "ended_at": "2026-09-15T20:12:00+00:00",
        "campaign": {
            "campaign_id": CAMPAIGN, "campaign_manifest_sha256": SHA,
            "topic_id": "topic-known-retain-utility-001",
        },
        "critique": {"verdict": "refuted"},
        "novelty": {"class": "empirical"},
        "journal_entry_path": journal,
        "experiment_outcome": EXPERIMENT,
    }
    _write(repo / "memory/loop_memory.jsonl", memory)
    admitted = attempts.project_attempts(
        producer_view=_view(), root=root, repo_root=repo, now=NOW,
    )
    assert admitted["attempts"][0]["terminal_status"] == "guard_recorded_final_bound"
    assert admitted["attempts"][0]["final_record_status"] == "bound"
    assert admitted["attempts"][0]["loop_memory_raw_sha256"]
    assert admitted["attempts"][0]["journal_raw_sha256"]
    assert admitted["scientific_admission_claimed"] is False
    emergency = root / f"{attempts.IDS[0]}.emergency-recovery.json"
    _write(emergency, {"schema": "unexpected-parent-emergency"})
    unresolved_parent = attempts.project_attempts(
        producer_view=_view(), root=root, repo_root=repo, now=NOW,
    )
    assert unresolved_parent["attempts"][0]["terminal_status"] == "source_unavailable"
    emergency.unlink()
    memory["experiment_outcome"] = {"experiment_id": "different-evidence"}
    _write(repo / "memory/loop_memory.jsonl", memory)
    drifted = attempts.project_attempts(
        producer_view=_view(), root=root, repo_root=repo, now=NOW,
    )
    assert drifted["attempts"][0]["terminal_status"] == "guard_recorded_final_unverified"
    _write(repo / "memory/loop_memory.jsonl", {
        **memory, "experiment_outcome": EXPERIMENT,
    })
    (repo / journal).unlink()
    no_journal = attempts.project_attempts(
        producer_view=_view(), root=root, repo_root=repo, now=NOW,
    )
    assert no_journal["attempts"][0]["terminal_status"] == "guard_recorded_final_unverified"


def test_missing_registered_source_does_not_become_no_attempt_claim(tmp_path):
    view = attempts.project_attempts(
        producer_view=_view(), root=tmp_path / "missing",
        repo_root=tmp_path, now=NOW,
    )
    assert view["source_status"] == "source_unknown"
    assert view["latest_terminal_window_id"] is None
