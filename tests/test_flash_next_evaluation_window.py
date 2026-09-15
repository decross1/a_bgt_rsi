"""CPU-only tests for the frozen evaluation-window hook."""
from __future__ import annotations

import ast
import hashlib
import json
import os
import threading
import time
from pathlib import Path

import pytest

from bench.flash_next_ab import evaluation_window as ew
from bench.flash_next_ab import qualification as q
from bench.flash_next_ab.qualification import PAGING_POLICY


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def _write(path: Path, value) -> str:
    raw = _raw(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _ref(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def fixture(monkeypatch, tmp_path, *, cohort="flash"):
    research = tmp_path / "research"
    plan_root = research / "evaluation" / "window-plans"
    run_root = research / "evaluation" / "runs"
    qualification_root = research / "qualification-runs"
    runtime_root = research / "runtime"
    for path in (plan_root, run_root, qualification_root, runtime_root):
        path.mkdir(parents=True, exist_ok=True)
    ledger = runtime_root / "research-usage.jsonl"
    resident_qualification = runtime_root / "resident-qualification-v2.json"
    resident_artifacts = runtime_root / "resident-model-artifacts.json"
    monkeypatch.setattr(ew, "RESEARCH_ROOT", research)
    monkeypatch.setattr(ew, "WINDOW_PLAN_ROOT", plan_root)
    monkeypatch.setattr(ew, "WINDOW_RUN_ROOT", run_root)
    monkeypatch.setattr(ew, "QUALIFICATION_ROOT", qualification_root)
    monkeypatch.setattr(ew, "RUNTIME_ROOT", runtime_root)
    monkeypatch.setattr(ew, "RESEARCH_LEDGER", ledger)
    monkeypatch.setattr(ew, "RESIDENT_QUALIFICATION", resident_qualification)
    monkeypatch.setattr(ew, "RESIDENT_ARTIFACTS", resident_artifacts)

    pair_id = "qfn-ab-unit-v1"
    benchmark_path = plan_root / f"{pair_id}.benchmark.json"
    benchmark_plan = {"schema_version": "unit-benchmark", "declared_cells": ["one"]}
    benchmark_sha = _write(benchmark_path, benchmark_plan)
    monkeypatch.setattr(ew, "validate_plan", lambda value: value)

    if cohort == "flash":
        qualification_dir = qualification_root / "qfn-c0-passed-unit"
        qualification_dir.mkdir()
        receipt = qualification_dir / "result.json"
        qualification_plan = qualification_dir / "plan.json"
        contract_snapshot = qualification_dir / "launch-contract.snapshot.json"
        contract_raw = qualification_dir / "launch-contract.raw.json"
        raw_contract_digest = _write(contract_raw, {"profile": "C0-S1", "marker": "raw"})
        _write(receipt, {
            "schema": "qwen-flash-next-qualification-result/v3",
            "profile": "C0-S1", "contract_sha256": raw_contract_digest,
            "model_artifact_sha256": q.model_artifact_sha256(),
        })
        launch = ["docker", "create", "fixed-image"]
        qualification_plan_document = {
            "schema": "qwen-flash-next-qualification-plan/v3",
            "contract_sha256": raw_contract_digest,
            "image_id": q.IMAGE_ID,
            "model_artifact_sha256": q.model_artifact_sha256(),
            "served_model": q.SERVED_MODEL,
            "docker_create_argv": launch,
            "docker_create_argv_sha256": hashlib.sha256(
                json.dumps(launch, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "probe_set": "flash-next-minimal-v1",
            "setup_quiescence_seconds": 60,
            "ready_quiescence_seconds": 60,
            "paging_policy": json.loads(json.dumps(PAGING_POLICY)),
        }
        _write(qualification_plan, qualification_plan_document)
        _write(contract_snapshot, {"marker": "snapshot"})
        qualification = {
            "receipt": _ref(receipt),
            "qualification_plan": _ref(qualification_plan),
            "contract_snapshot": _ref(contract_snapshot),
            "contract_raw": _ref(contract_raw),
            "resident_artifacts": None,
        }
        expected_receipt_sha = qualification["receipt"]["sha256"]
    else:
        _write(resident_qualification, {"marker": "resident"})
        _write(resident_artifacts, {"marker": "artifacts"})
        qualification = {
            "receipt": _ref(resident_qualification),
            "qualification_plan": None,
            "contract_snapshot": None,
            "contract_raw": None,
            "resident_artifacts": _ref(resident_artifacts),
        }
        expected_receipt_sha = qualification["receipt"]["sha256"]

    validation_calls = []

    def validate(plan, observed_cohort, **kwargs):
        validation_calls.append((plan, observed_cohort, kwargs))
        summary = {
            "qualification_receipt_sha256": expected_receipt_sha,
            "admission_eligible": True,
        }
        if observed_cohort == "flash":
            summary.update(
                {
                    "qualification_plan_sha256": hashlib.sha256(
                        json.dumps(
                            qualification_plan_document,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode()
                    ).hexdigest(),
                    "contract_sha256": raw_contract_digest,
                    "runtime_sha256": "4" * 64,
                    "model_artifact_sha256": q.model_artifact_sha256(),
                    "served_model": q.SERVED_MODEL,
                }
            )
        return summary

    monkeypatch.setattr(ew, "validate_qualification_receipt", validate)
    document = {
        "schema_version": ew.WINDOW_SCHEMA,
        "pair_id": pair_id,
        "cohort": cohort,
        "benchmark": {
            "plan_path": str(benchmark_path),
            "plan_file_sha256": benchmark_sha,
            "runtime_budget_seconds": ew.FULL_COHORT_BUDGET_SECONDS,
        },
        "qualification": qualification,
        "safety": {
            "window_deadline_seconds": ew.WINDOW_DEADLINE_SECONDS,
            "restoration_reserve_seconds": ew.RESTORATION_RESERVE_SECONDS,
            "min_mem_available_gib": ew.MIN_MEMORY_GIB,
            "memory_poll_seconds": 1,
        },
        "accounting": {
            "class": "uncapped-local-model-research",
            "weekly_budget_debit": False,
            "paid_api_allowed": False,
            "journal_path": str(ledger),
        },
        "promotion_authorized": False,
    }
    window_path = plan_root / f"{pair_id}.{cohort}.window.json"
    _write(window_path, document)
    return {
        "document": document,
        "window_path": window_path,
        "benchmark_path": benchmark_path,
        "benchmark_plan": benchmark_plan,
        "qualification_root": qualification_root,
        "run_root": run_root,
        "ledger": ledger,
        "validation_calls": validation_calls,
    }


def test_flash_window_loads_and_cross_binds_every_evidence_file(monkeypatch, tmp_path):
    values = fixture(monkeypatch, tmp_path)
    window = ew.load_evaluation_window(values["window_path"], expected_cohort="flash")

    assert window.cohort == "flash"
    assert window.runtime_budget_seconds == ew.MAX_RUNTIME_BUDGET_S == 10_430
    assert window.benchmark_plan == values["benchmark_plan"]
    assert len(values["validation_calls"]) == 1
    _, cohort, kwargs = values["validation_calls"][0]
    assert cohort == "flash"
    assert Path(kwargs["contract_raw_path"]).name == "launch-contract.raw.json"
    assert kwargs["resident_artifacts_path"] is None
    output = values["run_root"] / f"{window.pair_id}.flash"
    extended = ew.build_extended_evaluation_plan(
        window, output, must_be_absent=True
    )
    assert extended["schema_version"] == ew.EXTENDED_PLAN_SCHEMA
    assert extended["effective_invocation_deadline_seconds"] == 14_400
    assert extended["work_cutoff_seconds"] == 13_800
    assert extended["ready_quiescence_seconds"] == 60
    assert extended["paging_policy"] == PAGING_POLICY
    assert extended["benchmark_runtime_budget_seconds"] == 10_430
    assert extended["prior_qualification_receipt_sha256"] == (
        window.qualification_summary["qualification_receipt_sha256"]
    )
    assert len(ew.extended_plan_sha256(extended)) == 64


def test_resident_window_uses_only_registered_resident_evidence(monkeypatch, tmp_path):
    values = fixture(monkeypatch, tmp_path, cohort="resident")
    window = ew.load_evaluation_window(values["window_path"])

    assert window.cohort == "resident"
    _, _, kwargs = values["validation_calls"][0]
    assert kwargs["qualification_plan_path"] is None
    assert kwargs["contract_snapshot_path"] is None
    assert kwargs["contract_raw_path"] is None
    assert kwargs["resident_artifacts_path"] == ew.RESIDENT_ARTIFACTS


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda value: value["benchmark"].update(runtime_budget_seconds=10_429), "full frozen"),
        (lambda value: value["safety"].update(min_mem_available_gib=19), "safety envelope"),
        (lambda value: value["accounting"].update(weekly_budget_debit=True), "accounting"),
        (lambda value: value.update(promotion_authorized=True), "promotion"),
        (lambda value: value.update(shell="curl example.com"), "fields differ"),
    ],
)
def test_window_contract_drift_is_rejected(monkeypatch, tmp_path, mutation, match):
    values = fixture(monkeypatch, tmp_path)
    mutation(values["document"])
    _write(values["window_path"], values["document"])

    with pytest.raises(ew.EvaluationWindowError, match=match):
        ew.load_evaluation_window(values["window_path"])


def test_hash_drift_and_symlinked_source_are_rejected(monkeypatch, tmp_path):
    values = fixture(monkeypatch, tmp_path)
    values["benchmark_path"].write_bytes(b'{}\n')
    with pytest.raises(ew.EvaluationWindowError, match="hash differs"):
        ew.load_evaluation_window(values["window_path"])

    values = fixture(monkeypatch, tmp_path / "second")
    target = values["window_path"]
    link = target.with_name("linked.window.json")
    link.symlink_to(target)
    with pytest.raises(ew.EvaluationWindowError, match="redirected"):
        ew.load_evaluation_window(link)


def test_bounded_reader_rejects_fifo_without_blocking(tmp_path):
    fifo = tmp_path / "receipt.fifo"
    fifo.parent.mkdir(exist_ok=True)
    fifo.unlink(missing_ok=True)
    os.mkfifo(fifo)
    started = time.monotonic()
    with pytest.raises(ew.EvaluationWindowError, match="regular file"):
        ew._regular_bytes(fifo, label="FIFO receipt", max_bytes=1024)
    assert time.monotonic() - started < 1


def test_bounded_reader_rejects_symlinked_parent(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()
    source = actual / "receipt.json"
    source.write_text('{"ok":true}\n', encoding="utf-8")
    redirected = tmp_path / "redirected"
    redirected.symlink_to(actual, target_is_directory=True)

    with pytest.raises(ew.EvaluationWindowError, match="parent.*redirected"):
        ew._regular_bytes(
            redirected / source.name,
            label="redirected receipt",
            max_bytes=1024,
        )


class Monitor:
    def __init__(self):
        self.cancel_event = threading.Event()
        self.checks = 0

    def check(self):
        self.checks += 1


def test_flash_hook_runs_direct_harness_and_emits_separate_usage(monkeypatch, tmp_path):
    values = fixture(monkeypatch, tmp_path)
    window = ew.load_evaluation_window(values["window_path"])
    evaluation_output = values["run_root"] / f"{window.pair_id}.flash"
    execution_plan = ew.build_extended_evaluation_plan(
        window, evaluation_output, must_be_absent=True
    )
    evaluation_output.mkdir()
    gate_calls = []

    def fake_harness(plan, **kwargs):
        kwargs["qualification_gate"](plan, kwargs["cohort"])
        gate_calls.append(kwargs)
        output = Path(kwargs["output_dir"])
        output.mkdir()
        result = {
            "status": "complete",
            "cohort": "flash",
            "declared_cells": ["one"],
        }
        _write(output / "run.json", result)
        return result

    monkeypatch.setattr(ew, "run_harness", fake_harness)
    monkeypatch.setattr(ew, "validate_run", lambda result, cohort: result)
    monitor = Monitor()
    receipt = ew.run_flash_after_probes(
        window,
        execution_plan=execution_plan,
        evaluation_output=evaluation_output,
        work_deadline=time.monotonic() + ew.FULL_COHORT_BUDGET_SECONDS + 120,
        monitor=monitor,
    )

    assert receipt["status"] == "harness_complete_pending_restoration"
    assert receipt["evaluation_complete"] is False
    assert receipt["restoration_required"] is True
    assert receipt["weekly_budget_debit"] is False
    assert receipt["paid_api_calls"] == 0
    assert len(receipt["harness_run_sha256"]) == 64
    assert gate_calls[0]["runtime_budget_s"] == 10_430
    assert gate_calls[0]["cancel_event"] is monitor.cancel_event
    assert monitor.checks == 2
    usage = [json.loads(line) for line in values["ledger"].read_text().splitlines()]
    assert [row["event"] for row in usage] == [
        "evaluation_started",
        "evaluation_finished",
    ]
    assert all(row["weekly_budget_debit"] is False for row in usage)


def test_flash_hook_refuses_short_window_before_output_or_usage(monkeypatch, tmp_path):
    values = fixture(monkeypatch, tmp_path)
    window = ew.load_evaluation_window(values["window_path"])
    evaluation_output = values["run_root"] / f"{window.pair_id}.flash"
    execution_plan = ew.build_extended_evaluation_plan(window, evaluation_output)
    evaluation_output.mkdir()

    with pytest.raises(ew.EvaluationWindowError, match="no longer fits"):
        ew.run_flash_after_probes(
            window,
            execution_plan=execution_plan,
            evaluation_output=evaluation_output,
            work_deadline=time.monotonic() + ew.FULL_COHORT_BUDGET_SECONDS,
            monitor=Monitor(),
        )
    assert not (evaluation_output / "harness").exists()
    assert not values["ledger"].exists()


def test_flash_hook_rejects_an_unregistered_effective_deadline(
    monkeypatch, tmp_path
):
    values = fixture(monkeypatch, tmp_path)
    window = ew.load_evaluation_window(values["window_path"])
    evaluation_output = values["run_root"] / f"{window.pair_id}.flash"
    execution_plan = ew.build_extended_evaluation_plan(window, evaluation_output)
    execution_plan["effective_invocation_deadline_seconds"] = 3600
    evaluation_output.mkdir()

    with pytest.raises(ew.EvaluationWindowError, match="plan changed"):
        ew.run_flash_after_probes(
            window,
            execution_plan=execution_plan,
            evaluation_output=evaluation_output,
            work_deadline=time.monotonic()
            + ew.FULL_COHORT_BUDGET_SECONDS
            + 120,
            monitor=Monitor(),
        )
    assert not (evaluation_output / "harness").exists()
    assert not values["ledger"].exists()


def test_aborted_harness_is_failure_inclusive_and_cannot_pass(monkeypatch, tmp_path):
    values = fixture(monkeypatch, tmp_path)
    window = ew.load_evaluation_window(values["window_path"])
    evaluation_output = values["run_root"] / f"{window.pair_id}.flash"
    execution_plan = ew.build_extended_evaluation_plan(window, evaluation_output)
    evaluation_output.mkdir()

    def aborted(plan, **kwargs):
        kwargs["qualification_gate"](plan, kwargs["cohort"])
        output = Path(kwargs["output_dir"])
        output.mkdir()
        result = {"status": "aborted", "cohort": "flash"}
        _write(output / "run.json", result)
        return result

    monkeypatch.setattr(ew, "run_harness", aborted)
    monkeypatch.setattr(ew, "validate_run", lambda result, cohort: result)
    with pytest.raises(ew.EvaluationWindowError, match="did not complete"):
        ew.run_flash_after_probes(
            window,
            execution_plan=execution_plan,
            evaluation_output=evaluation_output,
            work_deadline=time.monotonic() + ew.FULL_COHORT_BUDGET_SECONDS + 120,
            monitor=Monitor(),
        )
    receipt = json.loads((evaluation_output / "harness-attempt.json").read_text())
    assert receipt["status"] == "harness_failed_pending_restoration"
    assert receipt["evaluation_complete"] is False
    assert receipt["harness_run_sha256"]


def test_module_has_no_shell_or_weekly_budget_execution_path():
    tree = ast.parse(Path(ew.__file__).read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert "subprocess" not in imports
    assert "orchestrator.weekly_upgrade_budget" not in imports
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "BudgetLedger" not in calls
