from __future__ import annotations

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
    monkeypatch.setattr(progress, "_prepared", lambda pair, windows: (SHA, tmp_path / "plan.json"))
    monkeypatch.setattr(progress, "PUBLICATION_ROOT", tmp_path)


def test_prepared_pair_withholds_scores_and_keeps_prior_attempt(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    row = progress.project_progress()
    assert row["status"] == "pending_admission"
    assert row["pair_id"] == PAIR
    assert row["registered_pair_ids"][-1].endswith("-a")
    assert row["cohorts"] is None
    assert row["grade_replay"] == "not_available"


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
