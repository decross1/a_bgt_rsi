"""Offline contracts for the public synthetic portfolio manifest."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from bench.weekly_upgrade_portfolio import manifest as pm


def test_manifest_is_public_synthetic_and_freezes_eight_tasks():
    manifest = pm.load_manifest()
    assert manifest["publication_class"] == pm.PUBLICATION_CLASS
    assert tuple(task["id"] for task in manifest["tasks"]) == pm.EXPECTED_TASK_IDS
    assert [task["family"] for task in manifest["tasks"]].count("scientific") == 4
    assert [task["family"] for task in manifest["tasks"]].count("evidence") == 2
    assert [task["family"] for task in manifest["tasks"]].count("coding") == 2
    assert all(
        task["provenance"]["origin"] == "synthetic_authored_for_eval"
        for task in manifest["tasks"]
    )
    assert "historical" not in json.dumps(manifest["tasks"]).casefold()


def test_plan_is_exact_16_cell_ab_ba_order():
    plan = pm.plan_dict(pm.load_manifest())
    assert plan["planned_calls"] == 16
    assert len({row["attempt_id"] for row in plan["order"]}) == 16
    assert [row["arm"] for row in plan["order"][:8]] == [
        "A", "B", "B", "A", "A", "B", "B", "A",
    ]
    assert plan["runtime_ceiling_s"] == 2280


def test_plan_subprocess_does_not_import_wrapper_or_write(tmp_path):
    output = tmp_path / "must-not-exist"
    code = (
        "import json,sys; "
        "from bench.weekly_upgrade_portfolio.runner import main; "
        f"rc=main(['--plan','--manifest',{str(pm.DEFAULT_MANIFEST)!r}]); "
        "print(json.dumps({'rc':rc,'wrapper':'agent_wrapper.wrapper' in sys.modules}))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=pm.REPO_ROOT,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
        env={**os.environ, "MOCK_LLM": "1"},
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout.splitlines()[-1]) == {"rc": 0, "wrapper": False}
    assert not output.exists()


def test_manifest_rejects_duplicate_keys(tmp_path):
    text = pm.DEFAULT_MANIFEST.read_text()
    mutated = text.replace(
        '"schema_version": "weekly-upgrade-game-science-development/v1",',
        '"schema_version": "weekly-upgrade-game-science-development/v1",\n'
        '  "schema_version": "weekly-upgrade-game-science-development/v1",',
        1,
    )
    path = tmp_path / "duplicate.json"
    path.write_text(mutated)
    with pytest.raises(pm.ManifestError, match="duplicate JSON key"):
        pm.load_manifest(path)


def test_manifest_rejects_hash_drift_and_nonfinite_values(tmp_path):
    raw = json.loads(pm.DEFAULT_MANIFEST.read_text())
    raw["tasks"][0]["grader"]["inputs"]["baseline_weights"][0] = float("nan")
    path = tmp_path / "nan.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(pm.ManifestError, match="canonical JSON"):
        pm.load_manifest(path)

    raw = json.loads(pm.DEFAULT_MANIFEST.read_text())
    raw["tasks"][0]["prompt"] += " drift"
    path = tmp_path / "drift.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(pm.ManifestError, match="frozen_hashes"):
        pm.load_manifest(path)


def test_manifest_rejects_path_escape_even_with_claimed_hash(tmp_path):
    raw = json.loads(pm.DEFAULT_MANIFEST.read_text())
    code_task = next(task for task in raw["tasks"] if task["mode"] == "code")
    code_task["starter"]["path"] = "../outside.py"
    path = tmp_path / "escape.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(pm.ManifestError, match="repository-relative"):
        pm.load_manifest(path)
