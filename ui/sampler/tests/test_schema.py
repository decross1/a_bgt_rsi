"""Sampler output validates against the telemetry schema. ui_plan.md section 5.1."""
import json
from pathlib import Path

import jsonschema

from sampler.sampler import DEFAULT_SCHEMA, Sampler


def _schema():
    return json.loads(Path(DEFAULT_SCHEMA).read_text(encoding="utf-8"))


def test_telemetry_schema_is_valid_json_schema():
    jsonschema.Draft202012Validator.check_schema(_schema())


def test_samples_validate_against_schema(tmp_path):
    out = tmp_path / "telemetry.jsonl"
    # Point vLLM at a closed port so the scrape fails fast and deterministically.
    sampler = Sampler(output_path=out, vllm_url="http://127.0.0.1:9/metrics",
                      interval=0.25)
    written = sampler.run(max_samples=8)
    assert written == 8

    validator = jsonschema.Draft202012Validator(_schema())
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 8
    for i, line in enumerate(lines):
        record = json.loads(line)
        errors = [e.message for e in validator.iter_errors(record)]
        assert not errors, f"line {i} failed schema: {errors}"
        assert isinstance(record["processes"], list)
