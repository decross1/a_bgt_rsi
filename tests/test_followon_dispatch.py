"""CPU-only fake-runner checks for the proposed dispatcher, not live calls.

These test sources are intentionally not executed during the first paired
measurement. The real sweep modules have their own source/grader tests.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from bench.flash_next_ab import followon_dispatch as group

WINDOW_ID = "qfn-followon-mia-pilot"
MIA = "flash_next_mia"


def write(path: Path, value: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, sort_keys=True).encode() + b"\n"
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def fixture(tmp_path: Path, monkeypatch):
    root = tmp_path / "research"
    root.mkdir()
    code_root = tmp_path / "followon_code"
    module_root = code_root / "bench/flash_next_ab"
    module_root.mkdir(parents=True)
    for name in group.FOLLOWON_SOURCE_MODULES:
        (module_root / name).write_text(f"# frozen fake {name}\n")
    monkeypatch.setattr(group, "FOLLOWON_CODE_ROOT", code_root)
    source_bundle = group.frozen_followon_source_bundle()
    output = group._output_path(WINDOW_ID, "flash", root)
    output.mkdir(parents=True)
    route = {
        "served_model": "qwen3.8-flash-next-mia",
        "artifact_sha256": "a" * 64,
        "runtime_sha256": "b" * 64,
        "qualification_receipt_sha256": "c" * 64,
        "max_model_len": 32768,
    }
    block_forms = [("thinking", 71, None, 2700),
                   ("context", None, 2048, 1440),
                   ("context", None, 8192, 2160),
                   ("context", None, 16384, 2880)]
    blocks = []
    plan_paths = []
    for ordinal, (kind, seed, target, ceiling) in enumerate(block_forms):
        block_id = f"followon-mia-pilot-{ordinal}"
        path = root / "evaluation/followon-block-plans" / f"{block_id}.json"
        plan = (
            {"routes": {MIA: {key: value for key, value in route.items()
                              if key != "max_model_len"}},
             "plan_sha256": "d" * 64,
             "declared_cells": [
                 {"cell_id": f"pilot-{index}", "seed": 71,
                  "task_id": f"task-{index // 5}", "role": "critic",
                  "condition": "off", "input_sha256": "e" * 64,
                  "grader_sha256": "f" * 64}
                 for index in range(30)
            ]}
            if kind == "thinking" else
            {"endpoint_name": MIA, "route": route,
             "declared_cells": [
                 {"cell_id": f"context-{target}-{index}",
                  "target_input_tokens": target}
                 for index in range(12)
             ]}
        )
        digest = write(path, plan)
        plan_paths.append(path)
        blocks.append({
            "ordinal": ordinal, "block_id": block_id, "kind": kind,
            "plan_path": str(path), "plan_raw_sha256": digest,
            "endpoint_name": MIA, "seed_block": seed, "target_block": target,
            "wall_ceiling_seconds": ceiling,
            "output_relative": f"blocks/{ordinal:02d}-{block_id}",
        })
    window = {
        "schema_version": group.WINDOW_SCHEMA, "window_id": WINDOW_ID,
        "study_id": "thinking-context-pilot-v1", "cohort": "flash",
        "output_dir": str(output),
        "candidate_variant_id": "mia-925d7be6-c0-s1",
        "route_bindings": {MIA: route}, "blocks": blocks,
        "qualified_parent_window": {},
        "registered_code_root": str(code_root),
        "followon_source_bundle": source_bundle,
        "followon_source_bundle_sha256": group._canonical_sha(source_bundle),
        "deadline_seconds": 14400, "restoration_reserve_seconds": 600,
        "block_budget_total_seconds": 9180,
        "promotion_authorized": False,
    }
    parent = root / "evaluation/window-plans/qfn-ab-parent.flash.window.json"
    parent_sha = write(parent, {
        "schema_version": "flash-next-evaluation-window/v1",
        "cohort": "flash", "promotion_authorized": False,
    })
    window["qualified_parent_window"] = {
        "path": str(parent), "sha256": parent_sha,
    }
    window_path = group._plan_path(WINDOW_ID, "flash", root)
    write(window_path, window)
    completed = []
    canceled = SimpleNamespace(value=False)

    def fake_run(plan, **kwargs):
        child = Path(kwargs["output_dir"])
        child.mkdir(parents=True)
        is_thinking = "routes" in plan
        result = (
            {"schema_version": "flash-thinking-role-effort-run/v1",
             "status": "complete", "endpoint_name": MIA,
             "seed_block": 71, "plan": plan,
             "plan_sha256": plan["plan_sha256"],
             "qualification_receipt_sha256": route["qualification_receipt_sha256"],
             "declared_cells": 30,
             "outcomes": [
                 {**item, "cell_id": item["cell_id"], "status": "returned",
                  "passed": False, "execution_error_type": None,
                  "returned_usage_valid": True,
                  "endpoint_name": MIA,
                  "served_model": route["served_model"],
                  "artifact_sha256": route["artifact_sha256"],
                  "runtime_sha256": route["runtime_sha256"],
                  "calls": [{}], "private_call_evidence": [{}]}
                 for item in plan["declared_cells"]
             ],
             "promotion_authorized": False}
            if is_thinking else
            {"schema_version": "flash-context-placement-run/v1",
             "status": "block_complete",
             "summary": {"attempted": 12, "passed": 3, "timeout": 1},
             "promotion_authorized": False}
        )
        write(child / "run.json", result)
        completed.append(kwargs)
        return result

    fake_module = SimpleNamespace(
        run_model=fake_run, validate_plan=lambda _: None,
        validate_run=lambda _: None,
        _retokenize=lambda plan, _checked: [
            SimpleNamespace(cell_id=item["cell_id"], supported=True)
            for item in plan["declared_cells"]
        ],
    )
    monkeypatch.setattr(group.importlib, "import_module", lambda _: fake_module)
    # This fixture isolates serial controller dispatch. The real frozen-call
    # predicate is exercised with producer-shaped plans in the separate
    # test_followon_call_bindings module.
    monkeypatch.setattr(
        group, "_thinking_block_complete",
        lambda run, plan, endpoint, seed: (
            run.get("status") == "complete"
            and run.get("endpoint_name") == endpoint
            and run.get("seed_block") == seed
            and len(run.get("outcomes", [])) == 30
            and [row.get("cell_id") for row in run["outcomes"]]
                == [cell["cell_id"] for cell in plan["declared_cells"]]
        ),
    )
    callbacks = SimpleNamespace(
        admit_thinking=lambda *_: None, admit_context=lambda *_: {},
        check_thinking=lambda *_: None, check_context=lambda *_: {},
    )
    cancel_event = SimpleNamespace(is_set=lambda: canceled.value)
    return root, output, window_path, plan_paths, completed, canceled, callbacks, cancel_event


def test_four_blocks_share_one_window_but_remain_pending_restoration(
    tmp_path, monkeypatch,
):
    root, output, *_middle, callbacks, cancel_event = fixture(tmp_path, monkeypatch)
    frozen = group.load_window(WINDOW_ID, "flash", root=root)
    result = group.run_group(
        frozen, controller_callbacks=callbacks,
        work_cutoff_s=time.monotonic() + 10000,
        cancel_event=cancel_event,
    )
    assert result["status"] == "blocks_complete_pending_restoration"
    assert result["comparison_eligible"] is False
    assert [item["attempted"] for item in result["blocks"]] == [30, 12, 12, 12]
    assert all(item["status"] == "complete_pending_restoration"
               for item in result["blocks"])
    assert (output / "group-attempt.json").exists()


def test_whole_group_needs_all_block_time_plus_restore_cutoff(
    tmp_path, monkeypatch,
):
    root, _output, *_middle, callbacks, cancel_event = fixture(tmp_path, monkeypatch)
    frozen = group.load_window(WINDOW_ID, "flash", root=root)
    with pytest.raises(group.FollowonError, match="whole group no longer fits"):
        group.run_group(
            frozen, controller_callbacks=callbacks,
            work_cutoff_s=time.monotonic() + 9000,
            cancel_event=cancel_event,
        )


def test_resident_pilot_binds_only_qwen_and_gemma(tmp_path, monkeypatch):
    root, _flash_output, flash_window_path, *_ = fixture(tmp_path, monkeypatch)
    window = json.loads(flash_window_path.read_text())
    qwen = {"served_model": "qwen3.8-27b-nvfp4-mtp",
            "artifact_sha256": "1" * 64, "runtime_sha256": "2" * 64,
            "qualification_receipt_sha256": "3" * 64,
            "max_model_len": 16384}
    gemma = {"served_model": "gemma-4-26b-a4b",
             "artifact_sha256": "4" * 64, "runtime_sha256": "5" * 64,
             "qualification_receipt_sha256": "6" * 64,
             "max_model_len": 32768}
    window["cohort"] = "resident"
    window["candidate_variant_id"] = None
    window["route_bindings"] = {"resident_qwen": qwen, "resident_gemma": gemma}
    window["output_dir"] = str(group._output_path(WINDOW_ID, "resident", root))
    parent = root / "evaluation/window-plans/qfn-ab-parent.resident.window.json"
    parent_sha = write(parent, {
        "schema_version": "flash-next-evaluation-window/v1",
        "cohort": "resident", "promotion_authorized": False,
    })
    window["qualified_parent_window"] = {"path": str(parent),
                                           "sha256": parent_sha}
    for block in window["blocks"]:
        endpoint = "resident_gemma" if block["target_block"] == 16384 else "resident_qwen"
        block["endpoint_name"] = endpoint
        source = Path(block["plan_path"])
        plan = json.loads(source.read_text())
        if block["kind"] == "thinking":
            plan["routes"] = {"resident_qwen": {
                key: value for key, value in qwen.items() if key != "max_model_len"
            }, MIA: plan["routes"][MIA]}
        else:
            plan["endpoint_name"] = endpoint
            plan["route"] = gemma if endpoint == "resident_gemma" else qwen
        block["plan_raw_sha256"] = write(source, plan)
    write(group._plan_path(WINDOW_ID, "resident", root), window)
    frozen = group.load_window(WINDOW_ID, "resident", root=root)
    assert [item["endpoint_name"] for item in frozen.document["blocks"]] == [
        "resident_qwen", "resident_qwen", "resident_qwen", "resident_gemma",
    ]
    window["blocks"][2]["endpoint_name"] = MIA
    write(group._plan_path(WINDOW_ID, "resident", root), window)
    with pytest.raises(group.FollowonError):
        group.load_window(WINDOW_ID, "resident", root=root)


def test_complete_label_with_omitted_cell_does_not_complete_group(
    tmp_path, monkeypatch,
):
    root, _output, _window, _plans, completed, _cancel, callbacks, cancel_event = (
        fixture(tmp_path, monkeypatch)
    )
    original_import = group.importlib.import_module

    def shortened_module(name):
        module = original_import(name)

        def shorten_first(plan, **kwargs):
            result = module.run_model(plan, **kwargs)
            if len(completed) == 1:
                result["outcomes"].pop()
                write(Path(kwargs["output_dir"]) / "run.json", result)
            return result

        return SimpleNamespace(run_model=shorten_first,
                               validate_plan=module.validate_plan,
                               validate_run=module.validate_run,
                               _retokenize=module._retokenize)

    monkeypatch.setattr(group.importlib, "import_module", shortened_module)
    frozen = group.load_window(WINDOW_ID, "flash", root=root)
    result = group.run_group(
        frozen, controller_callbacks=callbacks,
        work_cutoff_s=time.monotonic() + 10000,
        cancel_event=cancel_event,
    )
    assert result["status"] == "blocks_incomplete_pending_restoration"
    assert result["blocks"][0]["status"] == "incomplete_pending_restoration"
    assert all(item["status"] == "not_run" for item in result["blocks"][1:])


def test_durable_run_file_cannot_differ_from_returned_result(
    tmp_path, monkeypatch,
):
    root, _output, _window, _plans, completed, _cancel, callbacks, cancel_event = (
        fixture(tmp_path, monkeypatch)
    )
    original_import = group.importlib.import_module

    def replaced_file_module(name):
        module = original_import(name)

        def replace_first(plan, **kwargs):
            result = module.run_model(plan, **kwargs)
            if len(completed) == 1:
                changed = {**result, "outcomes": result["outcomes"][:-1]}
                write(Path(kwargs["output_dir"]) / "run.json", changed)
            return result

        return SimpleNamespace(run_model=replace_first,
                               validate_plan=module.validate_plan,
                               validate_run=module.validate_run,
                               _retokenize=module._retokenize)

    monkeypatch.setattr(group.importlib, "import_module", replaced_file_module)
    frozen = group.load_window(WINDOW_ID, "flash", root=root)
    result = group.run_group(
        frozen, controller_callbacks=callbacks,
        work_cutoff_s=time.monotonic() + 10000,
        cancel_event=cancel_event,
    )
    assert result["status"] == "blocks_incomplete_pending_restoration"
    assert result["blocks"][0]["status"] == "incomplete"
    assert all(item["status"] == "not_run" for item in result["blocks"][1:])


def test_plan_byte_drift_is_rejected_before_mutation(tmp_path, monkeypatch):
    root, *_ = fixture(tmp_path, monkeypatch)
    block = root / "evaluation/followon-block-plans/followon-mia-pilot-1.json"
    block.write_text('{"tampered":true}\n')
    with pytest.raises(group.FollowonError, match="block bytes changed"):
        group.load_window(WINDOW_ID, "flash", root=root)


def test_followon_checkout_byte_drift_is_rejected_before_mutation(
    tmp_path, monkeypatch,
):
    root, *_ = fixture(tmp_path, monkeypatch)
    code = group.FOLLOWON_CODE_ROOT / "bench/flash_next_ab/followon_context.py"
    code.write_text("# later implementation drift\n")
    with pytest.raises(group.FollowonError, match="source root or bytes"):
        group.load_window(WINDOW_ID, "flash", root=root)


def test_original_pair_checkout_cannot_be_followon_code_root(
    tmp_path, monkeypatch,
):
    fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(group, "FOLLOWON_CODE_ROOT", group.REGISTERED_CODE_ROOT)
    with pytest.raises(group.FollowonError, match="code root is unavailable"):
        group.frozen_followon_source_bundle()


def test_one_window_cannot_mix_flash_variants(tmp_path, monkeypatch):
    root, _output, window_path, *_ = fixture(tmp_path, monkeypatch)
    window = json.loads(window_path.read_text())
    window["blocks"][2]["endpoint_name"] = "flash_next"
    write(window_path, window)
    with pytest.raises(group.FollowonError):
        group.load_window(WINDOW_ID, "flash", root=root)


def test_unsupported_context_capacity_is_rejected_before_start(tmp_path, monkeypatch):
    root, _output, window_path, *_ = fixture(tmp_path, monkeypatch)
    window = json.loads(window_path.read_text())
    window["route_bindings"][MIA]["max_model_len"] = 16384
    for block in window["blocks"]:
        if block["kind"] == "context":
            source = Path(block["plan_path"])
            plan = json.loads(source.read_text())
            plan["route"]["max_model_len"] = 16384
            block["plan_raw_sha256"] = write(source, plan)
    write(window_path, window)
    with pytest.raises(group.FollowonError, match="context band"):
        group.load_window(WINDOW_ID, "flash", root=root)


def test_incomplete_tokenization_support_is_rejected_before_start(
    tmp_path, monkeypatch,
):
    root, *_ = fixture(tmp_path, monkeypatch)
    actual_import = group.importlib.import_module

    def eleven_supported(name):
        module = actual_import(name)

        def tokenized(plan, checked):
            rows = module._retokenize(plan, checked)
            if plan.get("declared_cells", [{}])[0].get("target_input_tokens") == 16384:
                rows[-1].supported = False
            return rows

        return SimpleNamespace(run_model=module.run_model,
                               validate_plan=module.validate_plan,
                               validate_run=module.validate_run,
                               _retokenize=tokenized)

    monkeypatch.setattr(group.importlib, "import_module", eleven_supported)
    with pytest.raises(group.FollowonError, match="twelve supported packets"):
        group.load_window(WINDOW_ID, "flash", root=root)


def test_later_block_drift_preserves_first_and_marks_unissued_not_run(
    tmp_path, monkeypatch,
):
    root, _output, _window, plan_paths, completed, _canceled, callbacks, cancel_event = (
        fixture(tmp_path, monkeypatch)
    )
    original_import = group.importlib.import_module

    def mutating_module(name):
        module = original_import(name)

        def first_then_mutate(plan, **kwargs):
            result = module.run_model(plan, **kwargs)
            if len(completed) == 1:
                plan_paths[1].write_text('{"changed":true}\n')
            return result

        return SimpleNamespace(run_model=first_then_mutate,
                               validate_plan=module.validate_plan,
                               validate_run=module.validate_run,
                               _retokenize=module._retokenize)

    monkeypatch.setattr(group.importlib, "import_module", mutating_module)
    frozen = group.load_window(WINDOW_ID, "flash", root=root)
    result = group.run_group(
        frozen, controller_callbacks=callbacks,
        work_cutoff_s=time.monotonic() + 10000,
        cancel_event=cancel_event,
    )
    assert result["status"] == "blocks_incomplete_pending_restoration"
    assert result["blocks"][0]["status"] == "complete_pending_restoration"
    assert result["blocks"][0]["run_sha256"] is not None
    assert all(item["status"] == "not_run" and item["attempted"] == 0
               for item in result["blocks"][1:])


def test_cancel_after_one_block_cuts_off_remaining_descriptors(
    tmp_path, monkeypatch,
):
    root, _output, _window, _paths, completed, canceled, callbacks, cancel_event = (
        fixture(tmp_path, monkeypatch)
    )
    original_import = group.importlib.import_module

    def canceling_module(name):
        module = original_import(name)

        def first_then_cancel(plan, **kwargs):
            result = module.run_model(plan, **kwargs)
            if len(completed) == 1:
                canceled.value = True
            return result

        return SimpleNamespace(run_model=first_then_cancel,
                               validate_plan=module.validate_plan,
                               validate_run=module.validate_run,
                               _retokenize=module._retokenize)

    monkeypatch.setattr(group.importlib, "import_module", canceling_module)
    frozen = group.load_window(WINDOW_ID, "flash", root=root)
    result = group.run_group(
        frozen, controller_callbacks=callbacks,
        work_cutoff_s=time.monotonic() + 10000,
        cancel_event=cancel_event,
    )
    assert result["blocks"][0]["status"] == "complete_pending_restoration"
    assert all(item["attempted"] == 0 for item in result["blocks"][1:])
    assert result["comparison_eligible"] is False
