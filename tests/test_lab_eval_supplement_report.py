"""Producer-shaped numeric publications for the two closed supplement kinds."""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from bench.flash_next_ab import (
    lab_eval_context,
    lab_eval_fresh,
    manifest,
)
from bench.flash_next_ab import lab_eval_supplement_report as supplement


def _gate(plan: dict, cohort: str, pair_id: str) -> dict:
    cert = plan["runtime_certificates"][cohort]
    names = {name for routes in plan["call_routes"][cohort].values()
             for name in routes}
    return {
        "schema_version": "lab-model-eval-admission/v1",
        "admitted": True, "cohort": cohort,
        "window_id": pair_id, "plan_sha256": manifest.sha256_json(plan),
        "certificate_sha256": (
            cert["parent_sha256"] if cohort == "flash" else cert["receipt_sha256"]),
        "endpoint_identities": {
            name: {key: plan["endpoints"][name][key]
                   for key in ("served_model", "artifact_sha256", "runtime_sha256")}
            for name in names
        },
        "candidate_spec_sha256": (
            cert["candidate_spec_sha256"] if cohort == "flash" else None),
        "monitor_armed": True, "controller_source_bundle_sha256": "a" * 64,
        "ready_proof_sha256": "b" * 64,
    }


@pytest.mark.parametrize(
    ("kind", "module", "expected"),
    [("fresh", lab_eval_fresh, 12), ("context", lab_eval_context, 36)],
)
def test_complete_timeout_pair_replays_and_forged_numeric_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    kind: str, module, expected: int,
) -> None:
    pair_id = supplement.KINDS[kind]["pair_id"]
    monkeypatch.setattr(supplement, "ARTIFACT_ROOT", tmp_path)
    windows_root = tmp_path / "model-windows"
    windows_root.mkdir()
    monkeypatch.setattr(supplement, "WINDOW_ROOT", windows_root)
    publications = tmp_path / "evaluation-supplement-pairs"
    publications.mkdir()
    monkeypatch.setattr(supplement, "PUBLICATION_ROOT", publications)
    plan_path = tmp_path / f"{kind}.plan.json"
    module.freeze_plan(plan_path)
    _, _, plan_raw_sha = module.load_plan(plan_path)

    def timeout(*_args, **_kwargs):
        raise TimeoutError("synthetic local endpoint timeout")

    source_root = Path(__file__).resolve().parents[1]
    controller_file = source_root / "bench/flash_next_ab/lab_window.py"
    windows = {}
    for cohort in ("resident", "flash"):
        output = windows_root / f"{pair_id}.{cohort}"
        output.mkdir()
        run = module.run(
            plan_path, cohort=cohort, output_dir=output / "evaluation",
            runtime_budget_s=300, admission_gate=lambda p, c: _gate(p, c, pair_id),
            cancel_event=threading.Event(), invoke_fn=timeout,
        )
        assert run["status"] == "complete"
        assert len(run["outcomes"]) == expected
        window_path = output / "window.json"
        window = {
            "schema": "lab-model-window/v1", "window_id": pair_id,
            "cohort": cohort, "evaluation_kind": kind,
            "output_dir": str(output), "code_root": str(source_root),
            "evaluation_plan": {"path": str(plan_path), "sha256": plan_raw_sha},
            "controller_sources": {
                "bench/flash_next_ab/lab_window.py": {
                    "path": str(controller_file),
                    "sha256": manifest.sha256_file(controller_file),
                },
            },
        }
        window_path.write_bytes(manifest.canonical_json(window) + b"\n")
        window_sha = manifest.sha256_file(window_path)
        restoration = {
            "status": "verified", "errors": [], "sentinel_retained": False,
            "verified_at": "2026-09-15T19:00:00+00:00",
        }
        (output / "state.json").write_bytes(manifest.canonical_json({
            "phase": "complete", "window_sha256": window_sha,
            "restoration": restoration,
        }) + b"\n")
        (output / "result.json").write_bytes(manifest.canonical_json({
            "schema": "lab-model-window-result/v1",
            "window_id": pair_id, "cohort": cohort,
            "status": "complete", "error": None,
            "window_sha256": window_sha, "restoration": restoration,
            "evaluation_run_sha256": manifest.sha256_file(
                output / "evaluation/run.json"),
            "promotion_authorized": False,
        }) + b"\n")
        (output / "supervision.json").write_bytes(manifest.canonical_json({
            "schema": "lab-model-supervision/v1",
            "window_sha256": window_sha, "returncode": 0,
            "interrupted": None, "terminated_at_cutoff": False,
            "emergency_restoration": None,
        }) + b"\n")
        windows[cohort] = window_path

    class FakeController:
        def load_window(self, path):
            return json.loads(path.read_bytes()), SimpleNamespace()

    monkeypatch.setattr(
        supplement.importlib, "import_module", lambda _name: FakeController())
    output = publications / pair_id
    supplement.publish(
        kind, plan_path, windows["resident"], windows["flash"], output_dir=output)
    admitted = supplement.read_publication(output / "index.json")
    for cohort in ("resident", "flash"):
        assert admitted["cohorts"][cohort]["scores"]["total"] == {
            "declared": expected, "attempted": expected, "returned": 0,
            "timeout": expected, "error": 0, "cancelled": 0,
            "passed": 0,
            "wall_s_including_failures":
                admitted["cohorts"][cohort]["scores"]["total"]["wall_s_including_failures"],
        }
    if kind == "fresh":
        assert set(admitted["cohorts"]["flash"]["scores"]["by_kind"]) == {
            "science", "coding"}
        assert all(row["declared"] == 6 for row in
                   admitted["cohorts"]["flash"]["scores"]["by_kind"].values())
    else:
        scores = admitted["cohorts"]["flash"]["scores"]
        assert all(row["declared"] == 12 for row in scores["by_capacity"].values())
        assert set(scores["measured_prompt_tokens_max_by_capacity"]) == {
            "8192", "16384", "32768"}
        assert all(row["declared"] == 12 for row in scores["by_placement"].values())
        assert all(row["declared"] == 4 for grid in
                   scores["by_capacity_placement"].values() for row in grid.values())

    forged = dict(admitted)
    forged["cohorts"] = {**admitted["cohorts"],
                         "resident": {**admitted["cohorts"]["resident"],
                                      "scores": {**admitted["cohorts"]["resident"]["scores"],
                                                 "total": {
                                                     **admitted["cohorts"]["resident"]["scores"]["total"],
                                                     "passed": 1}}}}
    forged_raw = manifest.canonical_json(forged) + b"\n"
    (output / "report.json").write_bytes(forged_raw)
    index = json.loads((output / "index.json").read_bytes())
    index["report_raw_sha256"] = hashlib.sha256(forged_raw).hexdigest()
    (output / "index.json").write_bytes(manifest.canonical_json(index) + b"\n")
    with pytest.raises(supplement.SupplementReportError,
                       match="numeric report differs"):
        supplement.read_publication(output / "index.json")


def test_unregistered_or_incomplete_publication_is_withheld(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(supplement, "PUBLICATION_ROOT", tmp_path / "publications")
    outside = tmp_path / "index.json"
    outside.write_text("{}")
    with pytest.raises(supplement.SupplementReportError,
                       match="registered direct child"):
        supplement.read_publication(outside)
    registered = supplement.PUBLICATION_ROOT / supplement.KINDS["fresh"]["pair_id"]
    registered.mkdir(parents=True)
    (registered / "index.json").write_text("{}")
    with pytest.raises(supplement.SupplementReportError):
        supplement.read_publication(registered / "index.json")
