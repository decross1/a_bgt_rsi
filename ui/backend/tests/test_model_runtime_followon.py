"""Source-selection checks for the supervised follow-on model viewport.

These are deliberately off-tree until the first paired measurement closes.
The producer-shaped state/memory integration test is added at installation.
"""
from datetime import datetime, timezone

from backend import model_runtime as mr
from backend import model_runtime_extended as old
from backend import model_runtime_followon as followon

NOW = datetime(2026, 9, 15, 10, 0, tzinfo=timezone.utc)


def test_newer_invalid_followon_blocks_old_runtime_fallback(monkeypatch, tmp_path):
    roots = [tmp_path / name for name in ("qualification", "evaluation", "followon")]
    monkeypatch.setattr(old, "_latest_slot_mtime", lambda root, *, extended: 10)
    monkeypatch.setattr(followon, "_latest_slot_mtime", lambda root: 11)
    monkeypatch.setattr(
        followon, "project_followon_runtime",
        lambda *args, **kwargs: mr._unknown(NOW.isoformat(), "untrusted"),
    )
    projected = followon.maybe_project_followon(
        *roots, proc_root=tmp_path / "proc", boot_id_path=tmp_path / "boot",
        observed=NOW,
    )
    assert projected is not None
    assert projected["mode"] == "unknown"
    assert projected["source_error"] == "untrusted"


def test_newer_v5_qualification_keeps_followon_from_masking_it(monkeypatch, tmp_path):
    roots = [tmp_path / name for name in ("qualification", "evaluation", "followon")]
    monkeypatch.setattr(
        old, "_latest_slot_mtime",
        lambda root, *, extended: 21 if not extended else 10,
    )
    monkeypatch.setattr(followon, "_latest_slot_mtime", lambda root: 20)
    monkeypatch.setattr(
        followon, "project_followon_runtime",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("stale follow-on read")),
    )
    assert followon.maybe_project_followon(
        *roots, proc_root=tmp_path / "proc", boot_id_path=tmp_path / "boot",
        observed=NOW,
    ) is None


def test_equal_runtime_state_order_is_unknown(monkeypatch, tmp_path):
    roots = [tmp_path / name for name in ("qualification", "evaluation", "followon")]
    monkeypatch.setattr(old, "_latest_slot_mtime", lambda root, *, extended: 10)
    monkeypatch.setattr(followon, "_latest_slot_mtime", lambda root: 10)
    projected = followon.maybe_project_followon(
        *roots, proc_root=tmp_path / "proc", boot_id_path=tmp_path / "boot",
        observed=NOW,
    )
    assert projected is not None
    assert projected["mode"] == "unknown"


def test_candidate_cgroup_identity_requires_exact_docker_path():
    candidate_id = "a" * 64
    state = {
        "candidate_id": candidate_id,
        "candidate_cgroup_path": f"/system.slice/docker-{candidate_id}.scope",
        "candidate_cgroup_pid": 400,
        "candidate_cgroup_start_ticks": 500,
    }
    assert followon._candidate_identity(state) == (
        candidate_id, state["candidate_cgroup_path"], 400, 500,
    )
    state["candidate_cgroup_path"] = "/system.slice/docker-other.scope"
    try:
        followon._candidate_identity(state)
    except mr.RuntimeSourceError:
        pass
    else:
        raise AssertionError("wrong candidate cgroup path was admitted")


def test_profile_namespace_selects_only_code_owned_mia_specs():
    from bench.flash_next_ab.followon_profiles import MIA_CTX69632, MIA_MTP1

    assert mr._mia_spec_for_run("qfn-mia-mtp1-20260915-smoke") is MIA_MTP1
    assert mr._mia_spec_for_run("qfn-mia-ctx69632-20260915-smoke") is MIA_CTX69632
    assert mr._mia_spec_for_run("qfn-mia-c0-20260915-smoke") is not None
    try:
        mr._mia_spec_for_run("qfn-mia-mtp9-20260915-smoke")
    except mr.RuntimeSourceError:
        pass
    else:
        # Returning None is also fail-closed: a made-up profile is never Mia.
        assert mr._mia_spec_for_run("qfn-mia-mtp9-20260915-smoke") is None
