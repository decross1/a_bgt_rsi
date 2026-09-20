from __future__ import annotations

import copy

import pytest

from . import contract, design, replay, runner, wire
from .fixtures import FakeInvoke
from .test_runner import run_case


def write_run(output, value):
    (output / "run.json").write_bytes(design.canonical(value) + b"\n")


def replace_protocol(output, run, index, change):
    outcome = run["outcomes"][index]
    private = runner.read_protocol(output, outcome["protocol"])
    change(private)
    raw = design.canonical(private) + b"\n"
    (output / outcome["protocol"]["path"]).write_bytes(raw)
    outcome["protocol"]["sha256"] = design.sha(raw)
    outcome["protocol"]["bytes"] = len(raw)
    write_run(output, run)


def test_replay_is_repeatable_without_live_tools_models_or_resource_probes(
    tmp_path, monkeypatch
):
    plan, output, *_ = run_case(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("replay attempted a live action")

    monkeypatch.setattr(contract, "execute_once", forbidden)
    monkeypatch.setattr(design, "executor_for", forbidden)
    monkeypatch.setattr(wire, "invoke", forbidden)
    monkeypatch.setattr(design.resident, "_live_runtime_binding", forbidden)
    first = replay.validate(plan, output)
    assert first == replay.validate(plan, output)
    assert first["recorded_tool_attempts_verified"] == 8
    assert first["tool_calls_executed_by_replay"] == 0
    assert first["model_calls_executed_by_replay"] == 0
    assert first["primary_denominator_per_arm"] == 4
    assert first["permanently_excluded"] is True
    assert first["scientific_admission_eligible"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r.update(
            status="aborted", abort_reason="forged_abort_without_trigger"
        ),
        lambda r: r["slots"].pop(),
        lambda r: r["outcomes"].pop(),
        lambda r: r["slots"].__setitem__(1, copy.deepcopy(r["slots"][0])),
        lambda r: r["outcomes"][0].__setitem__("final_issued", 1),
        lambda r: r.__setitem__("permanently_excluded", 1),
        lambda r: r.__setitem__("scientific_admission_eligible", True),
        lambda r: r["accounting"].__setitem__("attempted_calls", 1),
        lambda r: r["outcomes"][0]["final_grade"]["contract"].__setitem__(
            "substantive_correct", "fail"
        ),
        lambda r: r["resource_observations"][0].__setitem__("memory_gib", 19),
        lambda r: r["slots"][0]["call"].__setitem__("call_index", True),
    ],
)
def test_replay_rejects_public_rewrites(tmp_path, mutation):
    plan, output, _, run, _ = run_case(tmp_path)
    mutation(run)
    write_run(output, run)
    with pytest.raises(ValueError):
        replay.validate(plan, output)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p.__setitem__("stage", "execution_attempting"),
        lambda p: p["execution_marker"].__setitem__("source_binding_sha256", "0" * 64),
        lambda p: p["execution"].__setitem__("retained_result_sha256", "0" * 64),
        lambda p: p["execution"].__setitem__("execution_attempted", 1),
        lambda p: p["continuation_request_messages"][2].__setitem__(
            "content", "leaked pretool text"
        ),
        lambda p: p["continuation_request_messages"][3].__setitem__(
            "content", '{"invented":"result"}'
        ),
        lambda p: p["wire_attempts"].pop(),
        lambda p: p["first_call"].__setitem__(
            "reasoning_content", "replaced reasoning"
        ),
    ],
)
def test_replay_rejects_rehashed_protocol_forgery(tmp_path, mutation):
    plan, output, _, run, _ = run_case(tmp_path)
    index = next(i for i, o in enumerate(run["outcomes"]) if o["arm"] == "calculator")
    replace_protocol(output, run, index, mutation)
    with pytest.raises(ValueError):
        replay.validate(plan, output)


def test_skips_and_wrong_finals_keep_fixed_denominators(tmp_path):
    plan, output, *_ = run_case(
        tmp_path, fake=FakeInvoke(malformed_tools=True, wrong_finals=True)
    )
    report = replay.validate(plan, output)
    assert report["accounting"]["attempted_calls"] == 12
    assert report["accounting"]["skipped_unissued"] == 8
    assert report["recorded_tool_attempts_verified"] == 0
    assert report["facets_by_arm"]["direct"]["substantive_correct"] == {
        "pass": 0,
        "fail": 4,
        "unassessed": 0,
    }
    assert report["facets_by_arm"]["calculator"]["substantive_correct"] == {
        "pass": 0,
        "fail": 0,
        "unassessed": 4,
    }


def test_private_protocol_parent_symlink_is_rejected(tmp_path):
    plan, output, _, _run, _ = run_case(tmp_path)
    protocol_dir = output / "private/protocols"
    relocated = output / "moved-protocols"
    protocol_dir.rename(relocated)
    protocol_dir.symlink_to(relocated, target_is_directory=True)
    with pytest.raises(ValueError):
        replay.validate(plan, output)


def test_missing_terminal_bundle_cannot_be_accepted(tmp_path):
    plan, output, *_ = run_case(tmp_path)
    (output / "run.json").unlink()
    with pytest.raises((ValueError, OSError)):
        replay.validate(plan, output)


def test_plan_source_drift_and_denominator_changes_are_rejected(tmp_path):
    plan, output, value, *_ = run_case(tmp_path)
    value["declared_units"].pop()
    plan.write_bytes(design.canonical(value))
    with pytest.raises(ValueError, match="drift"):
        replay.validate(plan, output)


def test_abort_cannot_hide_higher_priority_resource_fault(tmp_path):
    plan, output, _, run, _ = run_case(tmp_path)
    run.update(status="aborted", abort_reason="cancelled_after_last_call")
    run["resource_observations"][-1]["memory_gib"] = 19
    write_run(output, run)
    with pytest.raises(ValueError, match="precedence"):
        replay.validate(plan, output)


def test_post_preflight_cancellation_requires_preflight_record(tmp_path):
    plan, output, _, run, _ = run_case(tmp_path)
    run.update(status="aborted", abort_reason="cancelled_after_pre_call_probes")
    write_run(output, run)
    with pytest.raises(ValueError, match="boundary"):
        replay.validate(plan, output)


def test_replay_rejects_missing_single_use_claim(tmp_path):
    plan, output, _, run, _ = run_case(tmp_path)
    claim_path = output.parent / run["plan_claim"]["path"]
    claim_path.unlink()
    with pytest.raises((ValueError, OSError)):
        replay.validate(plan, output)


def test_rehashed_claim_cannot_be_bound_to_a_different_output(tmp_path):
    plan, output, _, run, _ = run_case(tmp_path)
    root = output.parent
    claim = runner.read_plan_claim(root, run["plan_claim"])
    claim["output"] = str(root / "another-run")
    raw = design.canonical(claim) + b"\n"
    (root / run["plan_claim"]["path"]).write_bytes(raw)
    run["plan_claim"]["sha256"] = design.sha(raw)
    run["plan_claim"]["bytes"] = len(raw)
    write_run(output, run)
    with pytest.raises(ValueError, match="single-use plan claim"):
        replay.validate(plan, output)
