"""CPU-only adverse receipt tests; intentionally unrun during live A/B."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bench.flash_next_ab import followon_completed_window_admission as gate
from bench.flash_next_ab.qualification import sha256


def _write(path: Path, value: dict) -> str:
    raw = json.dumps(value, sort_keys=True, allow_nan=False).encode() + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def terminal(tmp_path: Path, monkeypatch):
    source = tmp_path / "evaluation/followon-window-plans/qfn-followon-fixture.flash.json"
    output = tmp_path / "evaluation/followon-runs/qfn-followon-fixture.flash"
    output.mkdir(parents=True)
    plan = {"launcher_python_path": "/usr/bin/python3.12"}
    window = SimpleNamespace(
        pair_id="qfn-followon-fixture", cohort="flash",
        source_path=source, source_sha256="a" * 64,
        document={"output_dir": str(output),
                  "followon_source_bundle_sha256": "b" * 64,
                  "blocks": [{"block_id": "followon-fixture-0", "kind": "thinking",
                              "output_relative": "blocks/00-followon-fixture-0"}]},
    )
    _write(source, {"fixture": True})
    attempt = {
        "schema_version": gate.grouped.ATTEMPT_SCHEMA,
        "status": "blocks_complete_pending_restoration",
        "window_id": window.pair_id, "cohort": "flash",
        "window_plan_sha256": window.source_sha256,
        "followon_source_bundle_sha256": "b" * 64,
        "abort_reason": None, "restoration_required": True,
        "comparison_eligible": False, "promotion_authorized": False,
        "blocks": [{"ordinal": 0, "block_id": "followon-fixture-0",
                    "kind": "thinking", "status": "complete_pending_restoration",
                    "attempted": 30, "passed": 10, "timeouts": 1}],
    }
    digest = _write(output / "group-attempt.json", attempt)
    restore = {"status": "verified", "verified_at": "2026-09-15T08:10:00+00:00",
               "errors": [], "sentinel_retained": False}
    result = {"status": "complete", "restoration": restore,
              "started_at": "2026-09-15T08:00:00+00:00",
              "finished_at": "2026-09-15T08:11:00+00:00",
              "weekly_budget_debit": False, "paid_api_calls": 0,
              "production_change_authorized": False,
              "group_attempt_status": "blocks_complete_pending_restoration",
              "group_attempt_sha256": digest}
    state = {"phase": "complete", "result_status": "complete",
             "worker_pid": 17, "worker_start_ticks": 23, "boot_id": "fixture-boot"}
    argv = [plan["launcher_python_path"], "-m",
            "bench.flash_next_ab.extended_lifecycle", "--worker",
            "--eval-plan", str(source), "--output-dir", str(output)]
    supervision = {"returncode": 0, "terminated_at_work_cutoff": False,
                   "force_killed": False, "emergency_recovery": None,
                   "pid": 17, "worker_start_ticks": 23,
                   "boot_id": "fixture-boot", "argv": argv,
                   "argv_sha256": sha256(argv), "elapsed_seconds": 660,
                   "finished_at": "2026-09-15T08:12:00+00:00"}
    for name, value in (("result.json", result), ("state.json", state),
                        ("supervision.json", supervision)):
        _write(output / name, value)
    # This fixture isolates terminal sequencing and proof drift. Separate
    # producer→gate tests must exercise real private calls and raw monitors.
    monkeypatch.setattr(gate, "_block", lambda *_: {"private_calls_verified": 30})
    return window, output, plan, attempt, result, state, supervision


def test_unrestored_or_cutoff_window_is_never_completed(tmp_path, monkeypatch):
    window, output, plan, _attempt, result, _state, supervision = terminal(
        tmp_path, monkeypatch
    )
    gate._common(window, output, plan)
    result["restoration"]["status"] = "unknown"
    _write(output / "result.json", result)
    with pytest.raises(gate.FollowonAdmissionError, match="incomplete"):
        gate._common(window, output, plan)
    result["restoration"]["status"] = "verified"
    _write(output / "result.json", result)
    supervision["terminated_at_work_cutoff"] = True
    _write(output / "supervision.json", supervision)
    with pytest.raises(gate.FollowonAdmissionError, match="supervisor"):
        gate._common(window, output, plan)


def test_group_raw_drift_or_missing_block_is_never_completed(
    tmp_path, monkeypatch,
):
    window, output, plan, attempt, _result, _state, _supervision = terminal(
        tmp_path, monkeypatch
    )
    attempt["blocks"][0]["attempted"] = 29
    _write(output / "group-attempt.json", attempt)
    with pytest.raises(gate.FollowonAdmissionError, match="unbound"):
        gate._common(window, output, plan)
    result = json.loads((output / "result.json").read_text())
    result["group_attempt_sha256"] = _write(output / "group-attempt.json",
                                             {**attempt, "blocks": []})
    _write(output / "result.json", result)
    with pytest.raises(gate.FollowonAdmissionError, match="omitted"):
        gate._common(window, output, plan)


def test_flash_supervisor_snapshots_must_exist_and_match_registered_inputs(
    tmp_path, monkeypatch,
):
    output = tmp_path / "flash"
    output.mkdir()
    bundle = {"followon_dispatch.py": {"path": "/registered/source",
                                          "sha256": "a" * 64, "bytes": 12}}
    prior = {"schema": "qualified-C0-plan", "docker_create_argv":
             ["--max-model-len", "32768"]}
    contract = {"schema": "qualified-C0-contract", "runtime":
                {"max_model_len": 32768}}
    contract_sha = _write(output / "launch-contract.raw.json", contract)
    _write(output / "launch-contract.snapshot.json", contract)
    _write(output / "prior-c0-plan.snapshot.json", prior)
    _write(output / "controller-source-bundle.snapshot.json", bundle)
    window = SimpleNamespace(document={"followon_source_bundle": bundle},
                             qualification_plan=prior, parent=object(),
                             v5_parent=None)
    plan = {"controller_source_bundle": bundle,
            "controller_source_bundle_sha256": gate.grouped._canonical_sha(bundle),
            "contract_sha256": contract_sha}
    monkeypatch.setattr(gate.grouped, "frozen_followon_source_bundle", lambda: bundle)
    calls = []
    monkeypatch.setattr(gate.flash_safety, "_supervisor_inputs",
                        lambda *args: calls.append(args))
    gate._supervisor_inputs(window, output, plan, "flash")
    assert len(calls) == 1  # The existing full image/argv validator also runs.

    (output / "launch-contract.raw.json").unlink()
    with pytest.raises(gate.FollowonAdmissionError, match="raw launch"):
        gate._supervisor_inputs(window, output, plan, "flash")
    _write(output / "launch-contract.raw.json", contract)
    _write(output / "controller-source-bundle.snapshot.json", {"drift": True})
    with pytest.raises(gate.FollowonAdmissionError, match="snapshot"):
        gate._supervisor_inputs(window, output, plan, "flash")
    _write(output / "controller-source-bundle.snapshot.json", bundle)
    _write(output / "prior-c0-plan.snapshot.json", {"different_parent": True})
    with pytest.raises(gate.FollowonAdmissionError, match="snapshot"):
        gate._supervisor_inputs(window, output, plan, "flash")


def test_v5_supervisor_replays_own_raw_contract_and_literal_image(
    tmp_path, monkeypatch,
):
    output = tmp_path / "flash"
    output.mkdir()
    registered = tmp_path / "qualified" / "launch-contract.raw.json"
    contract = {"schema": "selected-v5-contract"}
    raw_sha = _write(registered, contract)
    _write(output / "launch-contract.raw.json", contract)
    _write(output / "launch-contract.snapshot.json", contract)
    prior = {"docker_create_argv": ["literal", "--max-model-len", "32768"],
             "docker_create_argv_sha256": "f" * 64}
    _write(output / "prior-c0-plan.snapshot.json", prior)
    bundle = {"followon_dispatch.py": {"path": "/registered/source",
                                       "sha256": "a" * 64, "bytes": 12}}
    _write(output / "controller-source-bundle.snapshot.json", bundle)
    ref = {"path": "/registered/v5-parent.json", "sha256": "b" * 64}
    spec = SimpleNamespace(spec_id="literal-v5", image_id="sha256:literal",
                           identity_sha256=lambda: "c" * 64)
    parent = SimpleNamespace(spec=spec, qualification_plan=prior,
                             document={"source_refs": {
                                 "launch-contract.raw.json":
                                 {"path": str(registered), "sha256": raw_sha}}})
    window = SimpleNamespace(
        document={"followon_source_bundle": bundle,
                  "v5_qualified_parent": ref},
        qualification_plan=prior, v5_parent=parent,
    )
    plan = {"controller_source_bundle": bundle,
            "controller_source_bundle_sha256": gate.grouped._canonical_sha(bundle),
            "contract_sha256": raw_sha, "candidate_variant_id": spec.spec_id,
            "candidate_spec_sha256": spec.identity_sha256(),
            "image_id": spec.image_id,
            "docker_create_argv": prior["docker_create_argv"],
            "docker_create_argv_sha256": prior["docker_create_argv_sha256"],
            "v5_qualified_parent": ref}
    monkeypatch.setattr(gate.grouped, "frozen_followon_source_bundle",
                        lambda: bundle)
    monkeypatch.setattr(gate.q, "_verified_contract_raw",
                        lambda *_args, **_kwargs:
                        (output / "launch-contract.raw.json").read_bytes())
    monkeypatch.setattr(gate.flash_safety, "_supervisor_inputs",
                        lambda *_: pytest.fail("C0 gate may not admit a v5 image"))
    gate._supervisor_inputs(window, output, plan, "flash")
    plan["image_id"] = "sha256:different"
    with pytest.raises(gate.FollowonAdmissionError, match="snapshot"):
        gate._supervisor_inputs(window, output, plan, "flash")
    plan["image_id"] = spec.image_id
    _write(registered, {"schema": "different"})
    with pytest.raises(gate.FollowonAdmissionError, match="snapshot"):
        gate._supervisor_inputs(window, output, plan, "flash")


def test_resident_controller_source_snapshot_must_match_current_code(
    tmp_path, monkeypatch,
):
    output = tmp_path / "resident"
    output.mkdir()
    bundle = {"followon_dispatch.py": {"path": "/registered/source",
                                          "sha256": "a" * 64, "bytes": 12}}
    plan = {"controller_source_bundle": bundle,
            "controller_source_bundle_sha256": gate.grouped._canonical_sha(bundle)}
    window = SimpleNamespace(document={"followon_source_bundle": bundle})
    monkeypatch.setattr(gate.grouped, "frozen_followon_source_bundle", lambda: bundle)
    _write(output / "plan.json", plan)
    gate._supervisor_inputs(window, output, plan, "resident")
    _write(output / "plan.json", {"different_source": True})
    with pytest.raises(gate.FollowonAdmissionError, match="snapshot"):
        gate._supervisor_inputs(window, output, plan, "resident")


def test_adaptive_retry_requires_source_bound_public_trigger_and_token_charge(
    tmp_path,
):
    child = tmp_path / "thinking"
    child.mkdir()
    content = ('{"answer_code":"causal_comparison_supported",'
               '"citations":["E71"],"needs_review":true}')
    first = {"call_id": "adaptive-cell#0", "status": "returned",
             "usage": {"completion_tokens": 5}}
    row = {"cell_id": "adaptive-cell",
           "task_id": "effort_v1_evidence_random_assignment",
           "role": "evidence", "condition": "adaptive",
           "calls": [first, {"call_id": "adaptive-cell#1", "status": "returned"}],
           "escalation_public_trigger": True}

    def persist(text: str):
        private = {"call_id": first["call_id"], "status": first["status"],
                   "response": {"content": text, "reasoning_content": None,
                                "tool_calls": []}}
        raw_sha = _write(child / "private/calls/0000-adaptive.json", private)
        row["private_call_evidence"] = [{
            "metadata_path": "private/calls/0000-adaptive.json",
            "metadata_sha256": raw_sha,
            "metadata_bytes": (child / "private/calls/0000-adaptive.json").stat().st_size,
        }]

    persist(content)
    gate._thinking_triggers(child, {"outcomes": [row]})
    persist(content.replace("true", "false"))
    with pytest.raises(gate.FollowonAdmissionError, match="trigger"):
        gate._thinking_triggers(child, {"outcomes": [row]})
    persist(content)
    first["usage"]["completion_tokens"] = 0
    with pytest.raises(gate.FollowonAdmissionError, match="valid public trigger"):
        gate._thinking_triggers(child, {"outcomes": [row]})
