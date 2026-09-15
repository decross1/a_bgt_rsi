from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.lab_model_eval_progress as progress

SHA = "a" * 64
FAMILY_COUNTS = {"objective": 24, "topic": 48, "portfolio": 16,
                 "diversity": 10, "role_effort": 18, "historical": 6, "context": 4}
PAIR = "qfn-ab-lab-primary-20260915-b"


def report() -> dict:
    families = {name: {"declared": count, "attempted": count, "returned": count,
                       "timeout": 0, "error": 0, "cancelled": 0, "passed": count,
                       "wall_s_including_failures": 10.0}
                for name, count in FAMILY_COUNTS.items()}
    def cohort(name: str) -> dict:
        return {"variant_id": "resident-role-bundle" if name == "resident" else progress.runtime.SPEC_ID,
                "status": "complete", "declared": 126, "attempted": 126, "passed": 126,
                "timeout": 0, "elapsed_s": 120.0, "families": families,
                "raw_response_replay_passed": True,
                "configured_context_tokens_by_endpoint": {
                    "resident_qwen": 16384, "resident_gemma": 32768} if name == "resident"
                    else {"flash_next_mia": 32768},
                "measured_prompt_tokens_max_by_endpoint": {
                    "resident_qwen": 1000, "resident_gemma": 14000} if name == "resident"
                    else {"flash_next_mia": 14000}}
    return {"schema_version": "lab-model-eval-paired-report/v1", "pair_id": PAIR,
            "status": "complete_admitted_pair", "denominator": 126,
            "promotion_authorized": False, "private_content_exported": False,
            "heldout_claim": False, "original_scores_rebased": False,
            "cohorts": {"resident": cohort("resident"), "flash": cohort("flash")}}


def setup(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(progress, "_select_pair", lambda: (PAIR, {"resident": tmp_path / "resident.json",
                                                             "flash": tmp_path / "flash.json"},
                                                       [PAIR, "qfn-ab-lab-primary-20260915-a"]))
    monkeypatch.setattr(progress, "_prepared", lambda pair, windows: (SHA, tmp_path / "plan.json",
                                                                      ["cell-0", "cell-1"]))
    monkeypatch.setattr(progress, "PUBLICATION_ROOT", tmp_path)


def test_prepared_pair_withholds_scores_and_keeps_prior_attempt(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    monkeypatch.setattr(progress, "_provisional", lambda *_: {
        "resident": {"schema_version": progress.EXECUTION_SCHEMA,
                     "cohort": "resident", "plan_raw_sha256": SHA,
                     "status": "recorded_prefix", "recorded_cells": 1,
                     "checkpoint_raw_sha256": SHA, "run_raw_sha256": None},
        "flash": {"schema_version": progress.EXECUTION_SCHEMA,
                  "cohort": "flash", "plan_raw_sha256": SHA,
                  "status": "prepared", "recorded_cells": None,
                  "checkpoint_raw_sha256": None, "run_raw_sha256": None}})
    row = progress.project_progress()
    assert row["status"] == "pending_admission"
    assert row["pair_id"] == PAIR
    assert row["registered_pair_ids"][-1].endswith("-a")
    assert row["cohorts"] is None
    assert row["grade_replay"] == "not_available"
    assert row["provisional_execution"]["resident"]["recorded_cells"] == 1
    assert row["provisional_execution"]["flash"]["status"] == "prepared"


def test_admitted_report_projects_only_numeric_allowlist(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    (tmp_path / PAIR).mkdir()
    (tmp_path / PAIR / "index.json").write_text("registered index exists", encoding="utf-8")
    source = report()
    source["private_response"] = "must not leave backend"
    row = progress.project_progress(publication_reader=lambda path: source)
    assert row["status"] == "complete_admitted_pair"
    assert row["cohorts"]["flash"]["passed"] == 126
    assert "private_response" not in str(row)


def test_tampered_publication_or_numeric_claim_withholds_scores(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    (tmp_path / PAIR).mkdir()
    (tmp_path / PAIR / "index.json").write_text("registered index exists", encoding="utf-8")
    for reader in (lambda path: (_ for _ in ()).throw(ValueError("source drift")),
                   lambda path: {**report(), "promotion_authorized": True},
                   lambda path: {**report(), "cohorts": {**report()["cohorts"],
                       "flash": {**report()["cohorts"]["flash"], "passed": 127}}}):
        row = progress.project_progress(publication_reader=reader)
        assert row["status"] == "source_unavailable"
        assert row["cohorts"] is None


def test_route_exposes_projection_without_running_model():
    app = FastAPI()
    progress.register(app, projector=lambda: {"schema_version": progress.SCHEMA,
                                              "status": "pending_admission", "cohorts": None})
    row = TestClient(app).get("/api/lab_model_eval_progress")
    assert row.status_code == 200
    assert row.json()["cohorts"] is None


def test_newest_exact_registered_pair_wins_and_old_attempt_is_retained(monkeypatch, tmp_path):
    root = tmp_path / "model-windows"
    root.mkdir()
    monkeypatch.setattr(progress, "WINDOW_ROOT", root)
    for pair in ("qfn-ab-lab-primary-20260915-a", PAIR):
        for cohort in ("resident", "flash"):
            child = root / f"{pair}.{cohort}"
            child.mkdir()
            (child / "window.json").write_text("{}", encoding="utf-8")
    selected, paths, history = progress._select_pair()
    assert selected == PAIR
    assert set(paths) == {"resident", "flash"}
    assert history == [PAIR, "qfn-ab-lab-primary-20260915-a"]
    (root / "qfn-ab-lab-primary-20260915-c.resident").symlink_to(root / f"{PAIR}.resident")
    selected, _, _ = progress._select_pair()
    assert selected == PAIR


def _execution_fixture(monkeypatch, tmp_path):
    output = tmp_path / "resident"
    evaluation = output / "evaluation"
    evaluation.mkdir(parents=True)
    window_path = output / "window.json"
    state_path, start_path = output / "state.json", output / "supervision-start.json"
    checkpoint_path = evaluation / "checkpoint.json"
    for path in (window_path, state_path, start_path, checkpoint_path):
        path.write_text("{}", encoding="utf-8")
    observed = datetime.now(timezone.utc)
    started = observed - timedelta(seconds=30)
    supervised = started - timedelta(seconds=1)
    argv = ["/registered/python", "-m", "bench.flash_next_ab.lab_window",
            "--worker", "--window", str(window_path)]
    rows = {
        window_path: {"wall_s": 6000, "window_id": PAIR},
        state_path: {"phase": "evaluation", "window_sha256": SHA,
                     "boot_id": "registered-boot", "worker_pid": 42,
                     "worker_start_ticks": 99, "started_at": started.isoformat()},
        start_path: {"window_sha256": SHA, "boot_id": "registered-boot",
                     "worker_pid": 42, "worker_start_ticks": 99, "pid": 42,
                     "started_at": supervised.isoformat(), "argv": argv},
        checkpoint_path: {"schema_version": progress.CHECKPOINT_SCHEMA,
                          "run_id": "lab-eval-resident-0123456789abcdef",
                          "cohort": "resident", "plan_raw_sha256": SHA,
                          "recorded_cells": ["cell-0", "cell-1"],
                          "elapsed_s": 10.0,
                          "promotion_authorized": False},
    }
    monkeypatch.setattr(progress, "_read_object", lambda path, **kwargs: (rows[path], SHA))
    monkeypatch.setattr(progress.runtime, "_worker", lambda *_: None)
    return window_path, checkpoint_path, state_path, start_path, rows, observed


def test_current_checkpoint_projects_only_frozen_ordered_prefix(monkeypatch, tmp_path):
    window, checkpoint, _, _, rows, observed = _execution_fixture(monkeypatch, tmp_path)
    os.utime(checkpoint, None)
    row = progress._provisional_cohort("resident", window, SHA,
                                       ["cell-0", "cell-1", "cell-2"], observed)
    assert row == {"schema_version": progress.EXECUTION_SCHEMA,
                   "cohort": "resident", "plan_raw_sha256": SHA,
                   "status": "recorded_prefix", "recorded_cells": 2,
                   "checkpoint_raw_sha256": SHA, "run_raw_sha256": None}
    for tamper in ({"recorded_cells": ["cell-1", "cell-0"]},
                   {"recorded_cells": ["cell-0", "cell-0"]},
                   {"plan_raw_sha256": "b" * 64},
                   {"cohort": "flash"},
                   {"elapsed_s": float("inf")},
                   {"schema_version": "other-checkpoint/v1"}):
        rows[checkpoint].update(tamper)
        assert progress._provisional_cohort("resident", window, SHA,
                                             ["cell-0", "cell-1", "cell-2"],
                                             observed)["status"] == "unverified"
        rows[checkpoint].update({"schema_version": progress.CHECKPOINT_SCHEMA,
                                 "cohort": "resident", "plan_raw_sha256": SHA,
                                 "recorded_cells": ["cell-0", "cell-1"],
                                 "elapsed_s": 10.0})
    rows[window.parent / "state.json"]["phase"] = "restoration"
    assert progress._provisional_cohort("resident", window, SHA,
                                         ["cell-0", "cell-1", "cell-2"],
                                         observed)["status"] == "unverified"


def test_stale_checkpoint_or_preflight_refusal_has_no_execution_count(monkeypatch, tmp_path):
    window, checkpoint, state, start, _, observed = _execution_fixture(monkeypatch, tmp_path)
    old = (observed - timedelta(seconds=60)).timestamp()
    os.utime(checkpoint, (old, old))
    assert progress._provisional_cohort("resident", window, SHA,
                                         ["cell-0", "cell-1"], observed)["status"] == "unverified"
    state.unlink()
    assert progress._provisional_cohort("resident", window, SHA,
                                         ["cell-0", "cell-1"], observed)["status"] == "unverified"
    start.unlink()
    assert progress._provisional_cohort("resident", window, SHA,
                                         ["cell-0", "cell-1"], observed)["status"] == "prepared"
    (window.parent / "supervision-reservation.json").write_text("{}", encoding="utf-8")
    assert progress._provisional_cohort("resident", window, SHA,
                                         ["cell-0", "cell-1"], observed)["status"] == "unverified"
    (window.parent / "supervision-reservation.json").unlink()
    state.symlink_to(window.parent / "missing-state.json")
    assert progress._provisional_cohort("resident", window, SHA,
                                         ["cell-0", "cell-1"], observed)["status"] == "unverified"


def test_bound_terminal_run_without_checkpoint_only_awaits_admission(monkeypatch, tmp_path):
    window, checkpoint, state, _, rows, observed = _execution_fixture(monkeypatch, tmp_path)
    checkpoint.unlink()
    run_path = window.parent / "evaluation/run.json"
    run_path.write_text("{}", encoding="utf-8")
    declared = ["cell-" + str(index) for index in range(126)]
    rows[run_path] = {"schema_version": progress.RUN_SCHEMA, "run_id":
                      "lab-eval-resident-0123456789abcdef", "cohort": "resident",
                      "status": "complete", "plan_raw_sha256": SHA,
                      "declared_cells": declared,
                      "outcomes": [{"cell_id": cell} for cell in declared],
                      "promotion_authorized": False, "private_response": "never exported"}
    row = progress._provisional_cohort("resident", window, SHA, declared, observed)
    assert row == {"schema_version": progress.EXECUTION_SCHEMA,
                   "cohort": "resident", "plan_raw_sha256": SHA,
                   "status": "awaiting_verification", "recorded_cells": None,
                   "checkpoint_raw_sha256": None, "run_raw_sha256": SHA}
    assert "private_response" not in str(row)
    rows[run_path]["declared_cells"] = list(reversed(declared))
    assert progress._provisional_cohort("resident", window, SHA,
                                        declared, observed)["status"] == "unverified"
    rows[run_path]["declared_cells"] = declared
    rows[state]["phase"] = "complete"
    rows[state]["restoration"] = {"status": "verified", "errors": [],
                                  "sentinel_retained": False}
    result_path, supervision_path = (window.parent / "result.json",
                                     window.parent / "supervision.json")
    result_path.write_text("{}", encoding="utf-8")
    supervision_path.write_text("{}", encoding="utf-8")
    rows[result_path] = {"schema": "lab-model-window-result/v1",
                         "status": "complete", "window_id": PAIR, "cohort": "resident",
                         "window_sha256": SHA, "evaluation_run_sha256": SHA,
                         "restoration": {"status": "verified", "errors": [],
                                         "sentinel_retained": False}}
    rows[supervision_path] = {"schema": "lab-model-supervision/v1",
                              "window_sha256": SHA, "returncode": 0,
                              "interrupted": None, "emergency_restoration": None,
                              "terminated_at_cutoff": False}
    assert progress._provisional_cohort("resident", window, SHA,
                                        declared, observed)["status"] == "awaiting_verification"
    rows[supervision_path]["terminated_at_cutoff"] = True
    assert progress._provisional_cohort("resident", window, SHA,
                                        declared, observed)["status"] == "unverified"
    rows[supervision_path]["terminated_at_cutoff"] = False
    rows[result_path]["restoration"]["sentinel_retained"] = True
    rows[state]["restoration"]["sentinel_retained"] = True
    assert progress._provisional_cohort("resident", window, SHA,
                                        declared, observed)["status"] == "unverified"
