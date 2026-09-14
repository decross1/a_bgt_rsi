"""Hermetic checks for the default-off weekly upgrade cycle owner."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_wrapper import maintenance_frontier as maintenance
from orchestrator import weekly_upgrade_cycle as cycle
from orchestrator import weekly_upgrade_trial as trial

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)


def _repo(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.delenv("MOCK_LLM", raising=False)
    root = tmp_path / "repo"
    (root / "run_state").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.org"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
    (root / "tracked.txt").write_text("fixture\n")
    subprocess.run(["git", "-C", str(root), "add", "tracked.txt"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "fixture"], check=True)
    (root / "run_state" / "frontier_tos_ratified").write_text("ratified\n")
    monkeypatch.setattr(trial, "canonical_root", lambda worktree: root)
    return root


def _packet(tmp_path: Path, *, accessed_at: str = "2026-09-14T11:00:00Z") -> Path:
    path = tmp_path / "sources.json"
    path.write_text(json.dumps({
        "schema_version": "weekly-upgrade-source-packet-v1",
        "sources": [{
            "url": "https://developers.openai.com/release",
            "publisher": "OpenAI", "published_at": "2026-09-14",
            "accessed_at": accessed_at, "content_sha256": "a" * 64,
            "evidence": "A bounded current-week source snapshot.",
            "verification_status": "FETCHED_UNVERIFIED", "verified_claims": [],
        }],
    }))
    return path


def _subscriptions(vendor: str) -> tuple[bool, str]:
    return True, f"{vendor} subscription fixture"


def _ready(tmp_path, monkeypatch, **updates):
    root = _repo(tmp_path, monkeypatch)
    kwargs = {
        "source_packet": _packet(tmp_path), "now": NOW,
        "subscription_probe": _subscriptions,
    }
    kwargs.update(updates)
    return root, cycle.readiness_report(root, tmp_path / "output", **kwargs)


def test_readiness_is_bounded_read_only_and_subscription_only(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    packet = _packet(tmp_path)
    before = sorted(path.relative_to(root) for path in root.rglob("*"))
    report = cycle.readiness_report(
        root, tmp_path / "output", source_packet=packet, now=NOW,
        subscription_probe=_subscriptions,
    )
    after = sorted(path.relative_to(root) for path in root.rglob("*"))
    assert report["ready"] is True
    assert before == after
    assert report["production_change_authorized"] is False
    assert {item["name"] for item in report["checks"]} >= {
        "frontier_tos", "pause_controls", "subscription_codex",
        "subscription_claude", "cycle_deadline",
    }


def test_pause_blocks_before_subscription_probe(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    (root / "run_state" / "pause_weekly_upgrade").write_text("pause\n")
    probes = []

    def probe(vendor):
        probes.append(vendor)
        return True, "should not run"

    report = cycle.readiness_report(
        root, tmp_path / "output", source_packet=_packet(tmp_path), now=NOW,
        subscription_probe=probe,
    )
    assert report["ready"] is False
    assert probes == []
    assert next(item for item in report["checks"] if item["name"] == "pause_controls")["ok"] is False


def test_stale_or_redirected_source_packet_fails_closed(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    stale = _packet(tmp_path, accessed_at="2026-09-07T11:00:00Z")
    report = cycle.readiness_report(
        root, tmp_path / "output", source_packet=stale, now=NOW,
        subscription_probe=_subscriptions,
    )
    assert report["ready"] is False
    stale.unlink()
    target = _packet(tmp_path)
    link = tmp_path / "redirected.json"
    link.symlink_to(target)
    redirected = cycle.readiness_report(
        root, tmp_path / "output", source_packet=link, now=NOW,
        subscription_probe=_subscriptions,
    )
    assert redirected["ready"] is False

    future = _packet(tmp_path, accessed_at="2026-09-15T11:00:00Z")
    future_report = cycle.readiness_report(
        root, tmp_path / "output", source_packet=future, now=NOW,
        subscription_probe=_subscriptions,
    )
    assert future_report["ready"] is False


def test_output_inside_checkout_and_naive_time_are_rejected(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    report = cycle.readiness_report(
        root, root / "output", source_packet=_packet(tmp_path), now=NOW,
        subscription_probe=_subscriptions,
    )
    assert report["ready"] is False
    real_output = tmp_path / "real-output"
    real_output.mkdir()
    redirected_output = tmp_path / "redirected-output"
    redirected_output.symlink_to(real_output, target_is_directory=True)
    redirected = cycle.run_cycle(
        root, redirected_output, source_packet=_packet(tmp_path),
        now_fn=lambda: NOW, subscription_probe=_subscriptions,
        review_fn=lambda *args, **kwargs: pytest.fail("review called"),
    )
    assert redirected["status"] == "READINESS_BLOCKED"
    with pytest.raises(cycle.CycleError, match="timezone aware"):
        cycle.readiness_report(
            root, tmp_path / "output", source_packet=_packet(tmp_path),
            now=NOW.replace(tzinfo=None),
            subscription_probe=_subscriptions,
        )


def test_cycle_is_idempotent_after_terminal_review(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    packet = _packet(tmp_path)
    output = tmp_path / "output"
    provider_runs = []

    def fake_review(repo_root, review_dir, **kwargs):
        provider_runs.append(kwargs)
        review_dir.mkdir(parents=True, exist_ok=True)
        existing = review_dir / "weekly_report.json"
        if existing.exists():
            return json.loads(existing.read_text())
        for ordinal, vendor, role in (
            (1, "codex", "upgrade_proposer"),
            (2, "claude", "upgrade_adversary"),
        ):
            receipt = review_dir / "receipts" / f"{ordinal:02d}-{role}.json"
            receipt.parent.mkdir(parents=True, exist_ok=True)
            receipt.write_text(json.dumps({
                "vendor": vendor, "status": "completed",
                "transport": {
                    "model_ids": [f"{vendor}-actual"],
                    "requested_model": f"{vendor}-requested",
                },
            }))
        report = {
            "status": "NO_CHANGE", "run_id": "fixture-run",
            "snapshot_sha256": "a" * 64, "proposal_sha256": None,
            "frontier_calls_used": 2, "experiment_card": None,
        }
        existing.write_text(json.dumps(report))
        return report

    first = cycle.run_cycle(
        root, output, source_packet=packet, now_fn=lambda: NOW,
        subscription_probe=_subscriptions, review_fn=fake_review,
    )
    second = cycle.run_cycle(
        root, output, source_packet=packet, now_fn=lambda: NOW,
        subscription_probe=_subscriptions, review_fn=fake_review,
    )
    assert first["status"] == second["status"] == "REVIEW_COMPLETE"
    # The controller is re-entered, while the durable report prevents another
    # simulated provider attempt.
    assert len(provider_runs) == 2
    assert first["usage"]["frontier"]["week_subscription_attempts"]["review_reserved"] == 2
    assert first["promotion_authorized"] is False
    assert provider_runs[0]["operational_history_root"] == output.resolve()


def test_canonical_week_claim_prevents_review_replay_from_another_root(
    tmp_path, monkeypatch,
):
    root = _repo(tmp_path, monkeypatch)
    packet = _packet(tmp_path)
    calls = []

    def fake_review(repo_root, review_dir, **kwargs):
        calls.append(str(review_dir))
        review_dir.mkdir(parents=True, exist_ok=True)
        report = {
            "status": "NO_CHANGE", "run_id": "fixture-run",
            "snapshot_sha256": "a" * 64, "proposal_sha256": None,
            "frontier_calls_used": 2, "experiment_card": None,
        }
        (review_dir / "weekly_report.json").write_text(json.dumps(report))
        return report

    first = cycle.run_cycle(
        root, tmp_path / "output-a", source_packet=packet, now_fn=lambda: NOW,
        subscription_probe=_subscriptions, review_fn=fake_review,
    )
    second = cycle.run_cycle(
        root, tmp_path / "output-b", source_packet=packet, now_fn=lambda: NOW,
        subscription_probe=_subscriptions, review_fn=fake_review,
    )
    assert first["status"] == "REVIEW_COMPLETE"
    assert second["status"] == "READINESS_BLOCKED"
    assert len(calls) == 1
    owner = json.loads((
        root / "run_state" / "weekly_upgrade" / "cycles" / "2026-W38.json"
    ).read_text())
    assert owner["output_root"] == str((tmp_path / "output-a").resolve())


def test_cycle_deadline_blocks_before_source_or_review(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    called = []

    def fetch(*args, **kwargs):
        called.append("fetch")
        raise AssertionError("not reached")

    def review(*args, **kwargs):
        called.append("review")
        raise AssertionError("not reached")

    config = tmp_path / "fetch.json"
    config.write_text(json.dumps({
        "schema_version": "weekly-upgrade-fetch-v1",
        "sources": [{
            "url": "https://developers.openai.com/release",
            "publisher": "OpenAI", "published_at": None,
        }],
    }))
    result = cycle.run_cycle(
        root, tmp_path / "output", fetch_config=config,
        review_deadline_s=600, fetch_deadline_s=60, cycle_deadline_s=650,
        now_fn=lambda: NOW, subscription_probe=_subscriptions,
        fetch_fn=fetch, review_fn=review,
    )
    assert result["status"] == "READINESS_BLOCKED"
    assert called == []


def test_cycle_rejects_source_config_mutation_during_fetch(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    config = tmp_path / "fetch.json"
    original = {
        "schema_version": "weekly-upgrade-fetch-v1",
        "sources": [{
            "url": "https://developers.openai.com/release",
            "publisher": "OpenAI", "published_at": None,
        }],
    }
    config.write_text(json.dumps(original))

    def mutating_fetch(path, **kwargs):
        config.write_text(json.dumps({**original, "sources": []}))
        return {
            "schema_version": "weekly-upgrade-fetch-result-v1",
            "source_packet": json.loads(_packet(tmp_path).read_text()),
            "receipts": [],
            "bounds": {
                "request_timeout_s": 10, "total_deadline_s": 60,
                "max_bytes_per_source": 262_144, "max_total_bytes": 1_048_576,
            },
            "note": "HTTP retrieval proves access and content hash only; every fetched source remains FETCHED_UNVERIFIED.",
        }

    with pytest.raises(cycle.CycleError, match="changed during"):
        cycle.run_cycle(
            root, tmp_path / "output", fetch_config=config, now_fn=lambda: NOW,
            subscription_probe=_subscriptions, fetch_fn=mutating_fetch,
            review_fn=lambda *args, **kwargs: pytest.fail("review called"),
        )
    receipt = json.loads((
        tmp_path / "output" / "2026-W38" / "source_fetch_receipt.json"
    ).read_text())
    assert receipt["status"] == "reserved"


def test_declared_cycle_may_not_cross_utc_iso_week(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    sunday = datetime(2026, 9, 20, 23, 59, tzinfo=timezone.utc)
    report = cycle.readiness_report(
        root, tmp_path / "output", source_packet=_packet(tmp_path), now=sunday,
        subscription_probe=_subscriptions,
    )
    assert report["ready"] is False
    week = next(item for item in report["checks"] if item["name"] == "week_boundary")
    assert week["ok"] is False


def test_owner_lock_rejects_wrong_inherited_inode(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    actual = root / "run_state" / ".frontier-agenda-cron.lock"
    actual.write_text("")
    other = tmp_path / "other.lock"
    other.write_text("")
    with (
        other.open("r+") as stream,
        pytest.raises(cycle.CycleError, match="wrong inode"),
        cycle.owner_lock(root, stream.fileno()),
    ):
        pass
    actual.unlink()
    actual.symlink_to(other)
    with (
        pytest.raises(cycle.CycleError, match="redirected"),
        cycle.owner_lock(root),
    ):
        pass


def test_cron_hook_is_default_off_and_bounded_when_enabled(tmp_path):
    repo = tmp_path / "cron-repo"
    (repo / "cron").mkdir(parents=True)
    (repo / "run_state").mkdir()
    (repo / "logs").mkdir()
    (repo / ".venv-chroma" / "bin").mkdir(parents=True)
    shutil.copy(
        Path(__file__).resolve().parents[1] / "cron" / "weekly-frontier-agenda.sh",
        repo / "cron" / "weekly-frontier-agenda.sh",
    )
    (repo / "run_state" / "frontier_tos_ratified").write_text("yes\n")
    (repo / "bench" / "weekly_upgrade_eval").mkdir(parents=True)
    (repo / "bench" / "weekly_upgrade_eval" / "sources.json").write_text("{}\n")
    calls = repo / "calls.txt"
    inherited = repo / "inherited.txt"
    lock_held = repo / "lock-held.txt"
    python = repo / ".venv-chroma" / "bin" / "python"
    python.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$*\" >> {calls}\n"
        "case \"$*\" in\n"
        f"  *weekly_upgrade_cycle*) readlink /proc/$$/fd/9 > {inherited} || exit 44; "
        f"if flock -n {repo / 'run_state' / '.frontier-agenda-cron.lock'} -c true; "
        f"then exit 45; else printf held > {lock_held}; fi ;;\n"
        "esac\n"
    )
    python.chmod(0o755)
    script = repo / "cron" / "weekly-frontier-agenda.sh"

    subprocess.run([str(script)], check=True, env={**os.environ, "NARA_WEEKLY_UPGRADE": "0"})
    assert calls.read_text().splitlines() == ["-m orchestrator.frontier_agenda --once"]

    subprocess.run([
        str(script),
    ], check=True, env={
        **os.environ, "NARA_WEEKLY_UPGRADE": "1",
        "NARA_WEEKLY_UPGRADE_OUTPUT_ROOT": str(tmp_path / "outputs"),
    })
    rows = calls.read_text().splitlines()
    assert len(rows) == 2
    assert "-m orchestrator.weekly_upgrade_cycle --run" in rows[-1]
    assert "--frontier-call-budget 2" in rows[-1]
    assert "--max-gpu-minutes 120" in rows[-1]
    assert inherited.read_text().strip() == str(
        repo / "run_state" / ".frontier-agenda-cron.lock"
    )
    assert lock_held.read_text() == "held"


def test_active_subscription_transport_observes_pause_and_kills_group(tmp_path):
    pause = tmp_path / "pause_weekly_upgrade"
    pid_path = tmp_path / "pid"

    def request_stop():
        deadline = time.monotonic() + 2
        while not pid_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        pause.write_text("stop\n")

    stopper = threading.Thread(target=request_stop)
    stopper.start()
    started = time.monotonic()
    with pytest.raises(maintenance.StopRequested):
        maintenance._run(
            [sys.executable, "-c", (
                "import os,sys,time,pathlib; "
                "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(60)"
            ), str(pid_path)],
            env=dict(os.environ), cwd=tmp_path, deadline=time.monotonic() + 5,
            cancel_paths=(pause,),
        )
    stopper.join(timeout=2)
    assert time.monotonic() - started < 3
    pid = int(pid_path.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_sigterm_is_raised_for_cleanup_before_outer_kill():
    with (
        pytest.raises(cycle.CycleError, match="termination requested"),
        cycle._termination_cleanup(),
    ):
        os.kill(os.getpid(), 15)
