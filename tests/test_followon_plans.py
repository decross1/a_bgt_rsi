"""Frozen configured-context binding; run after the live pair closes."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from bench.flash_next_ab import followon_plans as plans


def _flash(tmp_path: Path, monkeypatch, cap: int):
    root = tmp_path / "research"
    source = root / "evaluation/followon-window-plans/qfn-followon-cap.flash.json"
    source.parent.mkdir(parents=True)
    route = {"served_model": "qwen3.8-flash-next-mia",
             "artifact_sha256": "a" * 64, "runtime_sha256": "b" * 64,
             "qualification_receipt_sha256": "c" * 64,
             "max_model_len": cap}
    frozen = SimpleNamespace(path=source, raw_sha256="d" * 64,
                             document={"schema_version": plans.grouped.WINDOW_SCHEMA,
                                       "cohort": "flash",
                                       "qualified_parent_window":
                                       {"path": str(root / "evaluation/window-plans/parent.flash.window.json"),
                                        "sha256": "e" * 64},
                                       "candidate_variant_id": "mia-925d7be6-c0-s1",
                                       "route_bindings": {"flash_next_mia": route}})
    parent = SimpleNamespace(
        source_sha256="e" * 64,
        qualification_plan={"docker_create_argv":
                            ["docker", "create", "--max-model-len", "32768"]},
        qualification_summary={"admission_eligible": True,
                               "variant_id": "mia-925d7be6-c0-s1",
                               "served_model": route["served_model"],
                               "model_artifact_sha256": route["artifact_sha256"],
                               "runtime_sha256": route["runtime_sha256"],
                               "qualification_receipt_sha256": route[
                                   "qualification_receipt_sha256"]},
    )
    monkeypatch.setattr(plans.grouped, "RESEARCH_ROOT", root)
    monkeypatch.setattr(plans.grouped, "load_window", lambda *_: frozen)
    monkeypatch.setattr(plans.ew, "load_evaluation_window",
                        lambda *_args, **_kwargs: parent)
    return source


def test_flash_context_route_must_equal_qualified_launch(tmp_path, monkeypatch):
    source = _flash(tmp_path, monkeypatch, 32768)
    assert plans.load_execution(source, cohort="flash").document[
        "route_bindings"]["flash_next_mia"]["max_model_len"] == 32768
    frozen = plans.grouped.load_window("unused", "flash")
    frozen.document["route_bindings"]["flash_next_mia"]["max_model_len"] = 69632
    with pytest.raises(plans.FollowonPlanError, match="context"):
        plans.load_execution(source, cohort="flash")


def test_resident_context_routes_use_registered_incumbent_lanes(
    tmp_path, monkeypatch,
):
    root = tmp_path / "research"
    source = root / "evaluation/followon-window-plans/qfn-followon-cap.resident.json"
    source.parent.mkdir(parents=True)
    routes = {
        endpoint: {"served_model": endpoint, "artifact_sha256": "a" * 64,
                   "runtime_sha256": "b" * 64,
                   "qualification_receipt_sha256": "c" * 64,
                   "max_model_len": cap}
        for endpoint, cap in plans.REGISTERED_CONTEXT_CAPS.items()
    }
    frozen = SimpleNamespace(path=source, raw_sha256="d" * 64,
                             document={"schema_version": plans.grouped.WINDOW_SCHEMA,
                                       "cohort": "resident",
                                       "qualified_parent_window":
                                       {"path": str(root / "evaluation/window-plans/parent.resident.window.json"),
                                        "sha256": "e" * 64},
                                       "route_bindings": routes})
    parent = SimpleNamespace(
        source_sha256="e" * 64,
        qualification_summary={"admission_eligible": True,
                               "artifact_sha256_by_endpoint":
                                   {key: value["artifact_sha256"] for key, value in routes.items()},
                               "runtime_sha256_by_endpoint":
                                   {key: value["runtime_sha256"] for key, value in routes.items()},
                               "qualification_receipt_sha256": "c" * 64},
    )
    monkeypatch.setattr(plans.grouped, "RESEARCH_ROOT", root)
    monkeypatch.setattr(plans.grouped, "load_window", lambda *_: frozen)
    monkeypatch.setattr(plans.ew, "load_evaluation_window",
                        lambda *_args, **_kwargs: parent)
    assert plans.load_execution(source, cohort="resident").cohort == "resident"
    routes["resident_qwen"]["max_model_len"] = 32768
    with pytest.raises(plans.FollowonPlanError):
        plans.load_execution(source, cohort="resident")
