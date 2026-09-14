from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from bench.weekly_upgrade_historical.manifest import (
    DEFAULT_MANIFEST,
    EXPECTED_TASK_IDS,
    PATCH_WIRE_SCHEMA_VERSION,
    REPO_ROOT,
    ManifestError,
    git_blob,
    load_manifest,
    messages_for,
    plan_dict,
)
from bench.weekly_upgrade_historical.receipt import validate_historical_receipt
from bench.weekly_upgrade_historical.runner import (
    EXECUTION_SOURCE_FILES,
    _strict_patch_object,
    _strict_raw_patch,
    run_experiment,
)
from bench.weekly_upgrade_historical.sandbox import (
    GraderResult,
    apply_candidate_patch,
    grader_receipt_sha256,
    install_grader,
    materialize_workspace,
    run_grader,
)

PATCH_WIRE_MANIFEST = (
    REPO_ROOT
    / "experiments"
    / "weekly_historical_coding_patch_wire_v1_2026-09-14.json"
)


def _known_fix_patch(task: dict) -> str:
    return subprocess.check_output(
        [
            "git", "diff", "--no-ext-diff", task["base"]["commit"],
            task["grader"]["fix_commit"], "--", task["base"]["repair_path"],
        ],
        cwd=REPO_ROOT,
        text=True,
    )


def _materialize(task: dict, root: Path, manifest: dict) -> Path:
    workspace = root / "workspace"
    limits = manifest["resource_limits"]
    materialize_workspace(
        task, workspace,
        max_archive_bytes=limits["max_workspace_archive_bytes"],
        max_files=limits["max_workspace_files"],
    )
    return workspace


def test_manifest_freezes_six_single_arm_public_history_tasks():
    manifest = load_manifest()
    plan = plan_dict(manifest)
    assert tuple(plan["fixture_ids"]) == EXPECTED_TASK_IDS
    assert plan["arm_ids"] == ["gemma_coding_precise"]
    assert plan["declared_attempts"] == 6
    assert plan["publication_class"] == "public_historical"
    assert plan["contamination_resistant"] is False
    assert plan["runtime_ceiling_s"] == 1020
    assert len(plan["expected_input_sha256"]) == 6
    assert len(plan["expected_grader_sha256"]) == 6


def test_model_packet_excludes_proof_fix_and_grader_material():
    manifest = load_manifest()
    for task in manifest["tasks"]:
        base = git_blob(task["base"]["commit"], task["base"]["repair_path"]).decode()
        messages = messages_for(task, base)
        packet = json.dumps(messages, ensure_ascii=False)
        assert task["grader"]["fix_commit"] not in packet
        assert task["grader"]["source_path"] not in packet
        assert task["grader"]["proof_grader_sha256"] not in packet
        assert task["proof_task_sha256"] not in packet
        assert "expected_base_failure" not in packet
        assert messages[1]["content"].endswith(base)


def test_patch_wire_manifest_changes_only_scaffold_and_arm_contract():
    baseline = load_manifest()
    native = load_manifest(PATCH_WIRE_MANIFEST)
    assert native["schema_version"] == PATCH_WIRE_SCHEMA_VERSION
    assert plan_dict(native)["arm_ids"] == ["gemma_patch_native"]
    assert native["tasks"] == baseline["tasks"]
    assert native["resource_limits"] == baseline["resource_limits"]
    assert native["sandbox_runtime"] == baseline["sandbox_runtime"]
    assert native["source_proof"] == baseline["source_proof"]
    assert native["frozen_hashes"]["tasks"] == baseline["frozen_hashes"]["tasks"]
    assert native["frozen_hashes"]["graders"] == baseline["frozen_hashes"]["graders"]
    assert native["frozen_hashes"]["inputs"] != baseline["frozen_hashes"]["inputs"]
    assert native["frozen_hashes"]["arm"] != baseline["frozen_hashes"]["arm"]

    task = native["tasks"][0]
    base = git_blob(task["base"]["commit"], task["base"]["repair_path"]).decode()
    packet = messages_for(task, base, schema_version=native["schema_version"])
    assert "Return exactly one raw unified diff" in packet[0]["content"]
    assert "Do not return JSON" in packet[0]["content"]
    assert packet[1]["content"].endswith(base)
    assert task["grader"]["source_path"] not in json.dumps(packet)


def test_manifest_rejects_unknown_fields_and_tampered_inputs(tmp_path):
    raw = json.loads(DEFAULT_MANIFEST.read_text())
    raw["unauthorized"] = True
    path = tmp_path / "unknown.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(ManifestError, match="fields differ"):
        load_manifest(path)

    raw.pop("unauthorized")
    raw["tasks"][0]["defect_contract"] += " tampered"
    path.write_text(json.dumps(raw))
    with pytest.raises(ManifestError, match="proof binding|frozen_hashes"):
        load_manifest(path)


def test_strict_patch_schema_and_path_boundary():
    allowed = "agent_wrapper/wrapper.py"
    assert _strict_patch_object("not-json", allowed)[1] == "completion_not_strict_json"
    assert _strict_patch_object('{"path":"../escape","patch":"x"}', allowed)[1] == "completion_path"
    assert _strict_patch_object('{"path":"agent_wrapper/wrapper.py","patch":"x","extra":1}', allowed)[1] == "completion_schema"


def test_strict_raw_patch_accepts_only_an_unwrapped_exact_first_header():
    allowed = "agent_wrapper/wrapper.py"
    patch = (
        "diff --git a/agent_wrapper/wrapper.py b/agent_wrapper/wrapper.py\n"
        "--- a/agent_wrapper/wrapper.py\n"
        "+++ b/agent_wrapper/wrapper.py\n"
        "@@ -1 +1 @@\n-old\n+new\n"
    )
    assert _strict_raw_patch(patch, allowed) == (
        {"path": allowed, "patch": patch},
        None,
    )
    assert _strict_raw_patch(f"```diff\n{patch}```", allowed)[1] == (
        "completion_not_raw_diff"
    )
    assert _strict_raw_patch("Here is the fix:\n" + patch, allowed)[1] == (
        "completion_not_raw_diff"
    )
    assert _strict_raw_patch(json.dumps({"path": allowed, "patch": patch}), allowed)[1] == (
        "completion_not_raw_diff"
    )
    assert _strict_raw_patch(patch + "Thanks\n", allowed)[1] == (
        "completion_not_raw_diff"
    )
    assert _strict_raw_patch(patch + "```\n", allowed)[1] == (
        "completion_not_raw_diff"
    )
    assert _strict_raw_patch(patch.rstrip("\n"), allowed)[1] == (
        "completion_not_raw_diff"
    )


def test_patch_application_allows_only_the_registered_file(tmp_path):
    manifest = load_manifest()
    task = manifest["tasks"][0]
    workspace = _materialize(task, tmp_path, manifest)
    malicious = (
        "diff --git a/agent_wrapper/wrapper.py b/../escape.py\n"
        "--- a/agent_wrapper/wrapper.py\n+++ b/../escape.py\n@@ -1 +1 @@\n-x\n+y\n"
    )
    result = apply_candidate_patch(
        workspace, allowed_path=task["base"]["repair_path"], patch=malicious,
        max_patch_bytes=manifest["resource_limits"]["max_patch_bytes"],
    )
    assert result.valid is False
    assert result.code == "patch_path_or_header"
    assert not (tmp_path / "escape.py").exists()

    known = _known_fix_patch(task)
    result = apply_candidate_patch(
        workspace, allowed_path=task["base"]["repair_path"], patch=known,
        max_patch_bytes=manifest["resource_limits"]["max_patch_bytes"],
    )
    assert result.valid is True
    assert result.repaired_file_sha256 != task["base"]["repair_sha256"]


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap unavailable")
def test_all_six_graders_fail_on_base_and_pass_on_exact_fix():
    manifest = load_manifest()
    limits = manifest["resource_limits"]
    runtime = manifest["sandbox_runtime"]
    for task in manifest["tasks"]:
        with tempfile.TemporaryDirectory() as directory:
            workspace = _materialize(task, Path(directory), manifest)
            install_grader(task, workspace)
            base = run_grader(
                task, workspace, bwrap_path=runtime["bubblewrap_path"],
                python_path=runtime["python_path"], timeout_s=task["grader_timeout_s"],
                max_output_bytes=limits["max_grader_output_bytes"],
            )
        assert base.passed is False, task["id"]
        assert base.counts["failed"] >= 1, task["id"]

        with tempfile.TemporaryDirectory() as directory:
            workspace = _materialize(task, Path(directory), manifest)
            patch = apply_candidate_patch(
                workspace, allowed_path=task["base"]["repair_path"],
                patch=_known_fix_patch(task), max_patch_bytes=limits["max_patch_bytes"],
            )
            assert patch.valid is True, task["id"]
            install_grader(task, workspace)
            fixed = run_grader(
                task, workspace, bwrap_path=runtime["bubblewrap_path"],
                python_path=runtime["python_path"], timeout_s=task["grader_timeout_s"],
                max_output_bytes=limits["max_grader_output_bytes"],
            )
        assert fixed.passed is True, task["id"]
        assert fixed.counts == {
            "passed": task["grader"]["expected_cases"],
            "failed": 0, "errors": 0, "skipped": 0,
        }


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap unavailable")
def test_sandbox_denies_network_from_candidate_file(tmp_path):
    manifest = load_manifest()
    task = manifest["tasks"][0]
    workspace = _materialize(task, tmp_path, manifest)
    target = workspace / task["base"]["repair_path"]
    target.write_text(target.read_text() + "\nimport socket\nsocket.getaddrinfo('example.com', 443)\n")
    install_grader(task, workspace)
    grade = run_grader(
        task, workspace, bwrap_path=manifest["sandbox_runtime"]["bubblewrap_path"],
        python_path=manifest["sandbox_runtime"]["python_path"], timeout_s=15,
        max_output_bytes=manifest["resource_limits"]["max_grader_output_bytes"],
    )
    assert grade.status == "guard_denial"
    assert grade.passed is False
    assert grade.guard_event_count >= 1


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap unavailable")
def test_candidate_stdout_and_early_exit_cannot_forge_a_pass(tmp_path):
    manifest = load_manifest()
    task = manifest["tasks"][0]
    workspace = _materialize(task, tmp_path, manifest)
    target = workspace / task["base"]["repair_path"]
    target.write_text(
        target.read_text()
        + "\nprint('999 passed in 0.01s', flush=True)\n"
        + "import os\nos._exit(0)\n"
    )
    install_grader(task, workspace)
    grade = run_grader(
        task, workspace, bwrap_path=manifest["sandbox_runtime"]["bubblewrap_path"],
        python_path=manifest["sandbox_runtime"]["python_path"], timeout_s=15,
        max_output_bytes=manifest["resource_limits"]["max_grader_output_bytes"],
    )
    assert grade.passed is False
    assert grade.status == "error"
    assert grade.counts["passed"] == 0


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap unavailable")
def test_candidate_pytest_main_monkeypatch_cannot_forge_a_pass(tmp_path):
    manifest = load_manifest()
    task = manifest["tasks"][0]
    workspace = _materialize(task, tmp_path, manifest)
    target = workspace / task["base"]["repair_path"]
    target.write_text(
        target.read_text()
        + "\nimport pytest\npytest.main = lambda *args, **kwargs: 0\n"
        + "print('999 passed in 0.01s', flush=True)\n"
    )
    install_grader(task, workspace)
    grade = run_grader(
        task, workspace, bwrap_path=manifest["sandbox_runtime"]["bubblewrap_path"],
        python_path=manifest["sandbox_runtime"]["python_path"], timeout_s=15,
        max_output_bytes=manifest["resource_limits"]["max_grader_output_bytes"],
    )
    assert grade.passed is False
    assert grade.status == "failed"
    assert grade.counts == {"passed": 0, "failed": 1, "errors": 0, "skipped": 0}


class _FakeInvoke:
    def __init__(self, manifest: dict):
        self.tasks = iter(manifest["tasks"])
        self.arm = manifest["arm"]

    def __call__(self, messages, **kwargs):
        task = next(self.tasks)
        patch = _known_fix_patch(task)
        completion = (
            patch
            if self.arm["id"] == "gemma_patch_native"
            else json.dumps({
                "path": task["base"]["repair_path"],
                "patch": patch,
            })
        )
        request_id = f"request-{task['id']}"
        record = {
            "request_id": request_id, "prompt_messages": messages,
            "caller_tag": kwargs["caller_tag"], "parent_request_id": kwargs["parent_request_id"],
            "model": self.arm["model"], "model_version": "test-resident-digest",
            "backend": self.arm["backend"], "host_metadata": {"test": True},
            "profile": self.arm["profile"],
            "temperature": self.arm["expected_policy"]["temperature"],
            "top_p": self.arm["expected_policy"]["top_p"], "seed": self.arm["seed"],
            "reasoning_effort": self.arm["expected_policy"]["reasoning_effort"],
            "sampling_extra": {}, "max_tokens": task["max_tokens"],
            "completion": completion, "usage": {"input_tokens": 1, "output_tokens": 1},
            "finish_reason": "stop", "reasoning_chars": 0, "latency_ms": 0.0,
        }
        calls_path = Path(kwargs["log_path"])
        with calls_path.open("a") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        with calls_path.with_name("worker_activity.jsonl").open("a") as handle:
            handle.write("{}\n")
        return record


def _fake_grade(task, _workspace, **_kwargs):
    return GraderResult(
        status="passed", passed=True, returncode=0, timed_out=False,
        counts={"passed": task["grader"]["expected_cases"], "failed": 0, "errors": 0, "skipped": 0},
        duration_s=0.0, output_sha256="a" * 64, output_bytes=10,
        output_truncated=False, guard_event_count=0,
    )


def _json_lines(root: Path):
    def read(name: str, *, required: bool = True):
        path = root / name
        if not path.exists():
            if required:
                raise AssertionError(name)
            return []
        return [json.loads(line) for line in path.read_text().splitlines()]
    return read


def _regular(root: Path):
    def read(name: str, *, required: bool = True):
        path = root / name
        if not path.exists():
            if required:
                raise AssertionError(name)
            return None
        return path
    return read


def _finite(value, _where):
    assert not isinstance(value, bool) and isinstance(value, (int, float))
    assert math.isfinite(value) and value >= 0
    return float(value)


def _controller_plan(manifest: dict) -> dict:
    result = dict(plan_dict(manifest))
    result.update({
        "manifest_configuration_sha256": manifest["_configuration_sha256"],
        "payload_budget_s": 1020,
        "execution_dependencies": {
            str(path.relative_to(REPO_ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in EXECUTION_SOURCE_FILES
        },
    })
    return result


def test_runner_and_receipt_bind_scores_to_patch_and_grader_hashes(tmp_path):
    manifest = load_manifest()
    output = tmp_path / "evaluation"
    artifact = run_experiment(
        manifest, output_dir=output, runtime_budget_s=1020,
        invoke=_FakeInvoke(manifest), grader_fn=_fake_grade,
    )
    assert artifact["status"] == "complete"
    assert artifact["summary"]["successful_repairs"] == 6
    assert artifact["summary"]["objective_cases_total"] == 6
    assert artifact["summary"]["comparison_eligible"] is False

    plan = _controller_plan(manifest)
    assert validate_historical_receipt(
        plan, artifact, output / "manifest.snapshot.json",
        regular=_regular(output), json_lines=_json_lines(output),
        validate_calls=lambda rows, run_id: None,
        validate_activity=lambda rows, calls, run_id: None,
        finite_nonnegative=_finite,
    ) is True

    outcomes = _json_lines(output)("outcomes.jsonl")
    outcomes[0]["creditable_success"] = False
    (output / "outcomes.jsonl").write_text("".join(json.dumps(row) + "\n" for row in outcomes))
    artifact["outcomes"] = outcomes
    artifact["summary"] = {
        **artifact["summary"], "successful_repairs": 5, "success_rate": 5 / 6,
    }
    with pytest.raises(Exception, match="grader receipt or task credit"):
        validate_historical_receipt(
            plan, artifact, output / "manifest.snapshot.json",
            regular=_regular(output), json_lines=_json_lines(output),
            validate_calls=lambda rows, run_id: None,
            validate_activity=lambda rows, calls, run_id: None,
            finite_nonnegative=_finite,
        )


def test_patch_wire_runner_reuses_tasks_sandbox_and_receipt_without_json(
    tmp_path,
):
    manifest = load_manifest(PATCH_WIRE_MANIFEST)
    output = tmp_path / "patch-wire-evaluation"
    artifact = run_experiment(
        manifest,
        output_dir=output,
        runtime_budget_s=1020,
        invoke=_FakeInvoke(manifest),
        grader_fn=_fake_grade,
    )

    assert artifact["status"] == "complete"
    assert artifact["summary"]["successful_repairs"] == 6
    assert all(row["patch_status"] == "valid" for row in artifact["outcomes"])
    raw = _json_lines(output)("raw_attempts.jsonl")
    assert all(row["completion"].startswith("diff --git ") for row in raw)
    assert all(not row["completion"].startswith("{") for row in raw)
    assert validate_historical_receipt(
        _controller_plan(manifest),
        artifact,
        output / "manifest.snapshot.json",
        regular=_regular(output),
        json_lines=_json_lines(output),
        validate_calls=lambda rows, run_id: None,
        validate_activity=lambda rows, calls, run_id: None,
        finite_nonnegative=_finite,
    ) is True


def test_patch_wire_manifest_rejects_json_arm_identity(tmp_path):
    raw = json.loads(PATCH_WIRE_MANIFEST.read_text())
    raw["arm"] = json.loads(DEFAULT_MANIFEST.read_text())["arm"]
    path = tmp_path / "wrong-arm.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(ManifestError, match="response-contract treatment"):
        load_manifest(path)


def test_runner_counts_invalid_output_as_failure_without_invoking_grader(tmp_path):
    manifest = load_manifest()
    calls = {"count": 0}

    def invalid(messages, **kwargs):
        task = manifest["tasks"][calls["count"]]
        calls["count"] += 1
        return {
            "request_id": f"bad-{task['id']}", "completion": '{"path":"../escape","patch":"x"}',
            "model": manifest["arm"]["model"], "model_version": "test",
            "backend": manifest["arm"]["backend"], "host_metadata": {},
            "profile": manifest["arm"]["profile"], "temperature": 0.2, "top_p": 0.9,
            "seed": manifest["arm"]["seed"], "reasoning_effort": None,
            "sampling_extra": {}, "max_tokens": task["max_tokens"],
            "usage": {}, "finish_reason": "stop", "reasoning_chars": 0,
        }

    def forbidden_grader(*args, **kwargs):
        raise AssertionError("invalid patches must never reach the grader")

    artifact = run_experiment(
        manifest, output_dir=tmp_path / "bad", runtime_budget_s=1020,
        invoke=invalid, grader_fn=forbidden_grader,
    )
    assert artifact["status"] == "complete"
    assert artifact["summary"]["successful_repairs"] == 0
    assert all(row["patch_error"] == "completion_path" for row in artifact["outcomes"])
    assert all(row["grader"] is None for row in artifact["outcomes"])


def test_receipt_rejects_recomputed_but_contradictory_grader_result(tmp_path):
    manifest = load_manifest()
    output = tmp_path / "contradictory-grade"
    artifact = run_experiment(
        manifest, output_dir=output, runtime_budget_s=1020,
        invoke=_FakeInvoke(manifest), grader_fn=_fake_grade,
    )
    outcomes = _json_lines(output)("outcomes.jsonl")
    first = outcomes[0]
    first["grader"]["status"] = "output_limit"
    first["grader"]["passed"] = False
    first["creditable_success"] = False
    # Recompute the public consistency checksum. The receipt still has to reject
    # the internally impossible status rather than treating the hash as a MAC.
    first["grader_receipt_sha256"] = grader_receipt_sha256(
        attempt_id=first["attempt_id"], input_sha256=first["input_sha256"],
        patch_sha256=first["patch_sha256"], grader_sha256=first["grader_sha256"],
        sandbox_identity=manifest["sandbox_runtime"],
        result=GraderResult(**first["grader"]),
    )
    (output / "outcomes.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in outcomes), encoding="utf-8",
    )
    artifact["outcomes"] = outcomes
    artifact["summary"] = {
        **artifact["summary"], "successful_repairs": 5, "success_rate": 5 / 6,
    }
    with pytest.raises(Exception, match="status contradicts"):
        validate_historical_receipt(
            _controller_plan(manifest), artifact, output / "manifest.snapshot.json",
            regular=_regular(output), json_lines=_json_lines(output),
            validate_calls=lambda rows, run_id: None,
            validate_activity=lambda rows, calls, run_id: None,
            finite_nonnegative=_finite,
        )


def test_receipt_rejects_failed_branch_residual_evidence(tmp_path):
    manifest = load_manifest()

    def timeout(*_args, **_kwargs):
        raise TimeoutError

    output = tmp_path / "failed-branch"
    artifact = run_experiment(
        manifest, output_dir=output, runtime_budget_s=1020,
        invoke=timeout, grader_fn=_fake_grade,
    )
    assert artifact["status"] == "incomplete_transport"
    assert validate_historical_receipt(
        _controller_plan(manifest), artifact, output / "manifest.snapshot.json",
        regular=_regular(output), json_lines=_json_lines(output),
        validate_calls=lambda rows, run_id: None,
        validate_activity=lambda rows, calls, run_id: None,
        finite_nonnegative=_finite,
    ) is False

    raw = _json_lines(output)("raw_attempts.jsonl")
    raw[0]["usage"] = {"input_tokens": 0, "output_tokens": 0}
    (output / "raw_attempts.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in raw), encoding="utf-8",
    )
    with pytest.raises(Exception, match="non-returned attempt"):
        validate_historical_receipt(
            _controller_plan(manifest), artifact, output / "manifest.snapshot.json",
            regular=_regular(output), json_lines=_json_lines(output),
            validate_calls=lambda rows, run_id: None,
            validate_activity=lambda rows, calls, run_id: None,
            finite_nonnegative=_finite,
        )


def test_receipt_rejects_sampling_and_output_token_drift(tmp_path):
    manifest = load_manifest()
    output = tmp_path / "call-drift"
    artifact = run_experiment(
        manifest, output_dir=output, runtime_budget_s=1020,
        invoke=_FakeInvoke(manifest), grader_fn=_fake_grade,
    )
    calls = _json_lines(output)("calls.jsonl")
    calls[0]["sampling_extra"] = {"top_k": 1}
    (output / "calls.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in calls), encoding="utf-8",
    )
    with pytest.raises(Exception, match="runtime identity"):
        validate_historical_receipt(
            _controller_plan(manifest), artifact, output / "manifest.snapshot.json",
            regular=_regular(output), json_lines=_json_lines(output),
            validate_calls=lambda rows, run_id: None,
            validate_activity=lambda rows, calls, run_id: None,
            finite_nonnegative=_finite,
        )

    calls[0]["sampling_extra"] = {}
    calls[0]["usage"]["output_tokens"] = manifest["tasks"][0]["max_tokens"] + 1
    raw = _json_lines(output)("raw_attempts.jsonl")
    raw[0]["usage"] = calls[0]["usage"]
    (output / "calls.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in calls), encoding="utf-8",
    )
    (output / "raw_attempts.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in raw), encoding="utf-8",
    )
    with pytest.raises(Exception, match="output-token cap"):
        validate_historical_receipt(
            _controller_plan(manifest), artifact, output / "manifest.snapshot.json",
            regular=_regular(output), json_lines=_json_lines(output),
            validate_calls=lambda rows, run_id: None,
            validate_activity=lambda rows, calls, run_id: None,
            finite_nonnegative=_finite,
        )
