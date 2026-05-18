"""With sources absent, the sampler still emits valid lines with read_errors.

ui_plan.md section 5.1: a failed read is recorded, never silently skipped.
"""
import json
from pathlib import Path

import jsonschema

from sampler.sampler import DEFAULT_SCHEMA, Sampler
from sampler.sources import nvidia_smi


def test_missing_nvidia_smi_and_vllm(tmp_path, monkeypatch):
    # Simulate nvidia-smi not installed and vLLM not reachable.
    monkeypatch.setattr(nvidia_smi.shutil, "which", lambda _name: None)
    out = tmp_path / "telemetry.jsonl"
    sampler = Sampler(output_path=out, vllm_url="http://127.0.0.1:9/metrics",
                      interval=0.25)
    sampler.run(max_samples=5)

    validator = jsonschema.Draft202012Validator(
        json.loads(Path(DEFAULT_SCHEMA).read_text(encoding="utf-8")))
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines, "sampler produced no output"
    for line in lines:
        record = json.loads(line)
        assert not list(validator.iter_errors(record)), "line failed schema"
        assert record["gpu"] is None
        assert record["vllm"] is None
        assert record["read_errors"] is not None
        # read_errors stays populated on every line a source is failing.
        assert "nvidia-smi" in record["read_errors"]
        assert "vllm-metrics" in record["read_errors"]
