"""Offline contract tests for the frozen topic-scope repair diagnostic."""
from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from bench.weekly_upgrade_eval import topic_scope as ts

V2_MANIFEST = ts.REPO_ROOT / "experiments" / "topic_scope_repair_v2_2026-09-14.json"


@pytest.fixture
def manifest():
    return ts.load_manifest()


def _planner_completion(messages):
    user = messages[1]["content"]
    start = user.index("{")
    end = user.rindex("}\n\nEmit the plan") + 1
    state = json.loads(user[start:end])
    # A valid no-op is enough for transport tests; the harness must validate
    # it but must never dispatch it.
    assert state["in_flight"] == {"active": False, "run": None}
    return json.dumps([{"action": "noop", "args": {"reason": "diagnostic"}}])


def _valid_invoke(calls):
    def invoke(messages, **kwargs):
        calls.append((messages, kwargs))
        system = messages[0]["content"]
        if messages[1]["content"].startswith("Research topic: "):
            topic = messages[1]["content"].removeprefix("Research topic: ")
            completion = json.dumps({"candidates": [topic], "chosen": topic})
        elif "COORDINATOR brain" in system:
            completion = _planner_completion(messages)
        else:
            completion = json.dumps({"domain": "on", "reason": "strategic interaction"})
        return {
            "request_id": f"offline-{len(calls)}",
            "completion": completion,
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "model": "gemma-4-26b-a4b",
            "model_version": "offline/frozen",
            "backend": "vllm-gemma",
            "host_metadata": {"vllm_image_tag": "offline"},
        }
    return invoke


def _annotation_for(blind_path: Path, *, candidate_fidelity="preserved"):
    blind = json.loads(blind_path.read_text())
    items = []
    for row in blind["items"]:
        if row["stage"] != "hypothesis" or not row["protocol_valid"]:
            continue
        for candidate in row["candidates"]:
            items.append({
                "blind_id": row["blind_id"],
                "candidate_index": candidate["candidate_index"],
                "domain": "in_scope",
                "substantive_mechanism": True,
                "fidelity": candidate_fidelity,
                "unsupported_attribution": False,
                "generic_output": False,
            })
    return {
        "schema_version": ts.ANNOTATION_VERSION,
        "reviewer": "offline-independent",
        "reviewer_kind": "human",
        "independent_of_generator": True,
        "items": items,
    }


def test_manifest_freezes_exact_matrix_t6_prompts_menu_states_and_hashes(manifest):
    plan = ts.plan_dict(manifest, include_r0=True)
    assert plan["hypothesis_attempts"] == 32
    assert plan["planner_attempts"] == 16
    assert plan["optional_primary_r0_attempts"] == 32
    assert next(topic for topic in manifest["topics"] if topic["id"] == "T6")["text"] == (
        "Test-Time Collaborative Classification over Multi-Agent Networks"
    )
    assert len(manifest["planner_cases"]) == 4
    assert any(item["name"] == "run_loop_iteration" for item in manifest["planner_menu"])
    assert "already vetted\nfor scope" in manifest["arms"][0]["planner_system"]
    assert "candidates, NOT scope-vetted" in manifest["arms"][1]["planner_system"]
    assert manifest["frozen_hashes"]["settings"] == ts._sha(manifest["settings"])


def test_v2_manifest_is_one_prompt_delta_with_content_addressed_source(manifest):
    v2 = ts.load_manifest(V2_MANIFEST)
    candidate = next(arm for arm in v2["arms"] if arm["id"] == "candidate")
    assert manifest["_raw_sha256"] == ts.V1_MANIFEST_SHA256
    assert v2["suite_id"] == ts.V2_SUITE_ID
    assert candidate["source_commit"] == ts.V2_CANDIDATE_SOURCE_COMMIT
    assert ts._sha(candidate["planner_system"]) == ts.V2_CANDIDATE_PLANNER_SHA256
    assert "each menu object uses 'name'" in candidate["planner_system"]
    assert "Never emit a 'name' key in the output" in candidate["planner_system"]
    assert [row["attempt_id"] for row in ts.build_attempts(v2)] == [
        row["attempt_id"] for row in ts.build_attempts(manifest)
    ]


def test_v2_lineage_rejects_any_second_input_delta(tmp_path):
    raw = json.loads(V2_MANIFEST.read_text())
    raw["topics"][0]["scope_anchor"] += " Additional unregistered text."
    raw["frozen_hashes"]["topic_grading_anchors"]["T1"] = ts._sha(
        raw["topics"][0]["scope_anchor"]
    )
    path = tmp_path / "mutated-v2.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(ts.ManifestError, match="v2 may change only"):
        ts.load_manifest(path)


def test_v2_lineage_rejects_a_self_consistent_unregistered_prompt(tmp_path):
    raw = json.loads(V2_MANIFEST.read_text())
    candidate = next(arm for arm in raw["arms"] if arm["id"] == "candidate")
    candidate["planner_system"] += "\nUnregistered instruction."
    raw["frozen_hashes"]["arm_system_prompts"]["candidate"]["planner"] = ts._sha(
        candidate["planner_system"]
    )
    path = tmp_path / "mutated-prompt-v2.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(ts.ManifestError, match="not the preregistered repair"):
        ts.load_manifest(path)


def test_order_is_ab_ba_and_second_seed_reverses_cases(manifest):
    attempts = ts.build_attempts(manifest)
    hypothesis = [row for row in attempts if row["stage"] == "hypothesis"]
    planner = [row for row in attempts if row["stage"] == "planner"]
    assert [(row["case_id"], row["arm"]) for row in hypothesis[:4]] == [
        ("T1", "control"), ("T1", "candidate"),
        ("T2", "candidate"), ("T2", "control"),
    ]
    second_seed = [row for row in hypothesis if row["seed"] == 29]
    assert [row["case_id"] for row in second_seed[:4]] == ["T8", "T8", "T7", "T7"]
    assert [row["case_id"] for row in planner if row["seed"] == 29][:4] == ["P4", "P4", "P3", "P3"]


def test_plan_subprocess_is_read_only_and_does_not_import_model_or_historical_code(tmp_path):
    output = tmp_path / "must-not-exist"
    code = (
        "import json,sys; "
        "from bench.weekly_upgrade_eval.topic_scope import main; "
        f"rc=main(['--plan','--manifest',{str(ts.DEFAULT_MANIFEST)!r},'--output-dir',{str(output)!r}]); "
        "print(json.dumps({'rc':rc,'wrapper': 'agent_wrapper.wrapper' in sys.modules,"
        "'coordinator':'orchestrator.coordinator' in sys.modules}))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=ts.REPO_ROOT, capture_output=True,
        text=True, timeout=10, env={**os.environ, "MOCK_LLM": "1"}, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    final = json.loads(proc.stdout.splitlines()[-1])
    assert final == {"rc": 0, "wrapper": False, "coordinator": False}
    assert not output.exists()


def test_real_wrapper_signature_accepts_every_bound_argument(manifest, tmp_path):
    from agent_wrapper.wrapper import call_sync
    attempt = ts.build_attempts(manifest)[0]
    messages, _ = ts._messages(manifest, attempt)
    kwargs = ts._call_kwargs(manifest, attempt, tmp_path / "calls.jsonl", 30)
    inspect.signature(call_sync).bind(messages, **kwargs)
    assert kwargs["seed"] == 17
    assert kwargs["request_timeout_s"] == 30
    assert kwargs["log_path"] == str(tmp_path / "calls.jsonl")


def test_stub_run_preserves_all_48_cells_and_never_invokes_actions(manifest, tmp_path, monkeypatch):
    calls = []
    dispatched = []
    # If the harness ever grows a dispatch path, this catches the obvious seam.
    monkeypatch.setattr("orchestrator.coordinator_actions.ACTIONS", {}, raising=False)
    artifact = ts.run_experiment(
        manifest, output_dir=tmp_path / "run", runtime_budget_s=60,
        invoke=_valid_invoke(calls),
    )
    assert artifact["status"] == "awaiting_annotation"
    assert len(calls) == len(artifact["outcomes"]) == 48
    assert [row["stage"] for row in artifact["outcomes"]].count("hypothesis") == 32
    assert [row["stage"] for row in artifact["outcomes"]].count("planner") == 16
    assert dispatched == []
    assert sum(1 for _ in (tmp_path / "run" / "raw_attempts.jsonl").open()) == 48
    assert sum(1 for _ in (tmp_path / "run" / "parsed_attempts.jsonl").open()) == 48


def test_wrapper_calls_bind_seed_deadline_log_and_are_serial(manifest, tmp_path):
    calls = []
    ts.run_experiment(manifest, output_dir=tmp_path / "run", runtime_budget_s=60, invoke=_valid_invoke(calls))
    assert len(calls) == 48
    for _, kwargs in calls:
        assert kwargs["backend"] == "vllm-gemma"
        assert kwargs["model"] == "gemma-4-26b-a4b"
        assert kwargs["seed"] in {17, 29}
        assert 0 < kwargs["request_timeout_s"] <= 30
        assert kwargs["log_path"] == str(tmp_path / "run" / "calls.jsonl")
        assert kwargs["parent_request_id"] is None


def test_default_wrapper_adapter_isolates_activity_and_restores_context(manifest, tmp_path, monkeypatch):
    from agent_wrapper import worker_activity, wrapper

    prior_path = tmp_path / "prior-activity.jsonl"
    worker_activity.DEFAULT_LOG_PATH = prior_path
    current_id = {"value": "prior-run"}
    seen = []
    delegate = _valid_invoke(seen)

    monkeypatch.delenv("MOCK_LLM", raising=False)
    monkeypatch.setattr(wrapper, "get_run_id", lambda: current_id["value"])
    monkeypatch.setattr(wrapper, "set_run_id", lambda value: current_id.__setitem__("value", value))

    def fake(messages, **kwargs):
        assert current_id["value"].startswith("topic-scope-")
        assert worker_activity.DEFAULT_LOG_PATH == tmp_path / "run" / "worker_activity.jsonl"
        return delegate(messages, **kwargs)

    monkeypatch.setattr(wrapper, "call_sync", fake)
    artifact = ts.run_experiment(manifest, output_dir=tmp_path / "run", runtime_budget_s=60)
    assert artifact["status"] == "awaiting_annotation"
    assert current_id["value"] == "prior-run"
    assert worker_activity.DEFAULT_LOG_PATH == prior_path


def test_optional_primary_r0_is_direct_and_adds_exactly_32_calls(manifest, tmp_path):
    calls = []
    artifact = ts.run_experiment(
        manifest, output_dir=tmp_path / "run", runtime_budget_s=60,
        include_r0=True, invoke=_valid_invoke(calls),
    )
    assert len(calls) == len(artifact["outcomes"]) == 80
    r0 = [row for row in artifact["outcomes"] if row["stage"] == "primary_r0"]
    assert len(r0) == 32
    assert all(row["protocol_valid"] and row["domain"] == "on" for row in r0)
    assert all(call[1]["caller_tag"] != "topicality_check" for call in calls)


def test_attempt_errors_and_budget_exhaustion_remain_in_denominator(manifest, tmp_path):
    calls = []
    base = _valid_invoke(calls)
    count = {"n": 0}

    def flaky(messages, **kwargs):
        count["n"] += 1
        if count["n"] == 1:
            raise TimeoutError("bounded")
        return base(messages, **kwargs)

    class Clock:
        def __init__(self): self.value = -0.1
        def __call__(self): self.value += 0.1; return self.value

    artifact = ts.run_experiment(
        manifest, output_dir=tmp_path / "run", runtime_budget_s=0.8,
        invoke=flaky, monotonic=Clock(),
    )
    assert len(artifact["outcomes"]) == 48
    statuses = [row["status"] for row in artifact["outcomes"]]
    assert "timeout" in statuses
    assert "not_run_budget" in statuses
    assert artifact["status"] == "incomplete_transport"


def test_raw_response_is_durable_before_parser_failure(manifest, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(ts, "_parse_hypothesis", lambda _completion: (_ for _ in ()).throw(RuntimeError("parser broke")))
    artifact = ts.run_experiment(manifest, output_dir=tmp_path / "run", runtime_budget_s=60, invoke=_valid_invoke(calls))
    raws = [json.loads(line) for line in (tmp_path / "run" / "raw_attempts.jsonl").read_text().splitlines()]
    assert len(raws) == 48
    assert raws[0]["status"] == "returned" and raws[0]["completion"]
    assert artifact["outcomes"][0]["protocol_error"].startswith("harness parse error")


@pytest.mark.parametrize("completion", ["not json", "{}", '{"candidates": ["x"], "chosen": "y"}', '{"candidates": [], "chosen": "x"}'])
def test_hypothesis_invalid_schema_never_becomes_a_semantic_candidate(completion):
    parsed = ts._parse_hypothesis(completion)
    assert parsed["protocol_valid"] is False
    assert parsed["candidates"] == []
    assert parsed["chosen"] is None


def test_planner_validation_accepts_schema_but_never_calls_menu_action(manifest):
    case = manifest["planner_cases"][0]
    selected = case["expected"]["preferred_topic"]
    parsed = ts._parse_planner(
        json.dumps([{"action": "run_loop_iteration", "args": {"topic": selected}}]),
        case, manifest,
    )
    assert parsed["protocol_valid"]
    assert parsed["preferred_topic_selected"]
    assert parsed["exact_copy_provenance"]
    malformed = ts._parse_planner(
        json.dumps([{"action": "run_loop_iteration", "args": {"topic": selected, "explanation": "extra"}}]),
        case, manifest,
    )
    assert not malformed["protocol_valid"]


def test_blind_export_separates_private_arm_mapping(manifest, tmp_path):
    calls = []
    ts.run_experiment(manifest, output_dir=tmp_path / "run", runtime_budget_s=60, invoke=_valid_invoke(calls))
    blind_text = (tmp_path / "run" / "annotation_blind.json").read_text()
    blind = json.loads(blind_text)
    private = json.loads((tmp_path / "run" / "arm_map_private.json").read_text())
    assert '"arm":"control"' not in blind_text
    assert '"arm":"candidate"' not in blind_text
    hypothesis = next(item for item in blind["items"] if item["stage"] == "hypothesis")
    assert hypothesis["input_topic"] and hypothesis["scope_anchor"]
    assert {row["arm"] for row in private["items"]} == {"control", "candidate"}


def test_grading_package_is_standalone_and_contains_no_private_mapping(manifest, tmp_path):
    calls = []
    artifact_dir = tmp_path / "evaluation"
    ts.run_experiment(manifest, output_dir=artifact_dir, runtime_budget_s=60, invoke=_valid_invoke(calls))
    package_path = tmp_path / "grader-delivery" / "topic-scope-blind.json"
    receipt = ts.export_grading_package(
        artifact_dir, package_path,
        expected_manifest_sha256=manifest["_raw_sha256"],
    )
    package = json.loads(package_path.read_text())
    serialized = json.dumps(package, sort_keys=True)
    assert receipt["contains_private_arm_map"] is False
    assert receipt["candidate_annotation_count"] == 32
    assert "arm_map_private" not in serialized
    assert '"arm": "control"' not in serialized
    assert '"arm": "candidate"' not in serialized
    assert all(item["domain"] is None for item in package["annotation_template"]["items"])
    with pytest.raises(ValueError, match="outside the evaluation"):
        ts.export_grading_package(artifact_dir, artifact_dir / "grader.json")


def test_unrelated_redirect_cannot_count_as_grounded_repair(manifest, tmp_path):
    calls = []
    ts.run_experiment(manifest, output_dir=tmp_path / "run", runtime_budget_s=60, invoke=_valid_invoke(calls))
    annotations = _annotation_for(tmp_path / "run" / "annotation_blind.json", candidate_fidelity="unrelated_redirect")
    annotation_path = tmp_path / "annotations.json"
    annotation_path.write_text(json.dumps(annotations))
    summary = ts.summarize_annotations(tmp_path / "run", annotation_path)
    assert summary["metrics_by_arm"]["control"]["repair_grounded_useful"] == 0
    assert summary["metrics_by_arm"]["candidate"]["repair_grounded_useful"] == 0
    assert summary["decision"] == "NO-MATERIAL-SIGNAL"
    assert summary["production_change_authorized"] is False


def test_candidate_only_earns_larger_eval_from_blind_grounded_annotations(manifest, tmp_path):
    calls = []
    ts.run_experiment(manifest, output_dir=tmp_path / "run", runtime_budget_s=60, invoke=_valid_invoke(calls))
    blind = json.loads((tmp_path / "run" / "annotation_blind.json").read_text())
    private = json.loads((tmp_path / "run" / "arm_map_private.json").read_text())
    arm_for = {row["blind_id"]: row["arm"] for row in private["items"]}
    case_for = {row["blind_id"]: row["case_id"] for row in blind["items"]}
    annotations = _annotation_for(tmp_path / "run" / "annotation_blind.json")
    for item in annotations["items"]:
        repair = case_for[item["blind_id"]] in {"T5", "T6", "T7"}
        if repair:
            item["fidelity"] = (
                "grounded_transfer" if arm_for[item["blind_id"]] == "candidate"
                else "unrelated_redirect"
            )
    path = tmp_path / "annotations.json"
    path.write_text(json.dumps(annotations))
    summary = ts.summarize_annotations(tmp_path / "run", path)
    assert summary["metrics_by_arm"]["candidate"]["repair_grounded_useful"] == 6
    assert summary["metrics_by_arm"]["control"]["repair_grounded_useful"] == 0
    assert summary["decision"] == "EVALUATE-LARGER"


def test_runtime_identity_drift_invalidates_run(manifest, tmp_path):
    calls = []
    good = _valid_invoke(calls)
    count = {"n": 0}

    def drift(messages, **kwargs):
        result = good(messages, **kwargs)
        count["n"] += 1
        if count["n"] == 2:
            result["model_version"] = "offline/different"
        return result

    artifact = ts.run_experiment(manifest, output_dir=tmp_path / "run", runtime_budget_s=60, invoke=drift)
    assert artifact["status"] == "invalid_runtime_drift"


def test_annotations_must_cover_every_candidate_with_strict_schema(manifest, tmp_path):
    calls = []
    ts.run_experiment(manifest, output_dir=tmp_path / "run", runtime_budget_s=60, invoke=_valid_invoke(calls))
    annotations = _annotation_for(tmp_path / "run" / "annotation_blind.json")
    annotations["items"].pop()
    path = tmp_path / "missing.json"
    path.write_text(json.dumps(annotations))
    with pytest.raises(ValueError, match="cover every candidate"):
        ts.summarize_annotations(tmp_path / "run", path)
    annotations = _annotation_for(tmp_path / "run" / "annotation_blind.json")
    annotations["items"][0]["invented"] = True
    path = tmp_path / "extra.json"
    path.write_text(json.dumps(annotations))
    with pytest.raises(ts.ManifestError, match="unknown fields"):
        ts.summarize_annotations(tmp_path / "run", path)


def test_live_cli_refuses_mock_and_existing_or_live_output(manifest, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MOCK_LLM", "1")
    output = tmp_path / "new"
    rc = ts.main(["--run", "--manifest", manifest["_path"], "--output-dir", str(output), "--runtime-budget-s", "30"])
    assert rc == 2 and not output.exists()
    assert "REFUSE" in capsys.readouterr().err
    with pytest.raises(ValueError, match="live artifact root"):
        ts.validate_output_dir(ts.REPO_ROOT / "run_state" / "topic")
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(FileExistsError):
        ts.validate_output_dir(existing)


def test_runtime_budget_cannot_exceed_forty_minutes(manifest, tmp_path):
    with pytest.raises(ValueError, match="cannot exceed 2400"):
        ts.run_experiment(manifest, output_dir=tmp_path / "run", runtime_budget_s=2400.1, invoke=lambda *_a, **_k: {})
