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


def test_qwen_endpoint_unreachable_is_graceful(tmp_path):
    # Qwen endpoint pointed at a closed port: the second reader must fail
    # softly. Records keep a populated vllm_qwen field (null) so the key
    # set stays stable, surface a distinct vllm-qwen-metrics error key,
    # and validate against the schema. The primary vllm read (also
    # pointed at a closed port for determinism) must report its own error
    # under the existing vllm-metrics key — not get conflated with Qwen.
    out = tmp_path / "telemetry.jsonl"
    sampler = Sampler(
        output_path=out,
        vllm_url="http://127.0.0.1:9/metrics",
        interval=0.25,
        vllm_qwen_url="http://127.0.0.1:9/metrics",
    )
    sampler.run(max_samples=4)

    validator = jsonschema.Draft202012Validator(
        json.loads(Path(DEFAULT_SCHEMA).read_text(encoding="utf-8")))
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines, "sampler produced no output"
    for line in lines:
        record = json.loads(line)
        assert not list(validator.iter_errors(record)), "line failed schema"
        # Field is present and explicitly null (graceful degradation,
        # never silently omitted).
        assert "vllm_qwen" in record
        assert record["vllm_qwen"] is None
        # Two distinct error keys — never conflated.
        assert record["read_errors"] is not None
        assert "vllm-metrics" in record["read_errors"]
        assert "vllm-qwen-metrics" in record["read_errors"]


def test_qwen_reader_disabled_omits_error_key(tmp_path):
    # Empty vllm_qwen_url disables the second reader entirely. Lines
    # carry vllm_qwen: null but NO vllm-qwen-metrics error key — that's
    # the expected state on a Gemma-only host, and a spurious error key
    # would be noise.
    out = tmp_path / "telemetry.jsonl"
    sampler = Sampler(
        output_path=out,
        vllm_url="http://127.0.0.1:9/metrics",
        interval=0.25,
        vllm_qwen_url="",
    )
    sampler.run(max_samples=3)

    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines, "sampler produced no output"
    for line in lines:
        record = json.loads(line)
        assert record["vllm_qwen"] is None
        # No noise about the disabled reader.
        if record["read_errors"] is not None:
            assert "vllm-qwen-metrics" not in record["read_errors"]
