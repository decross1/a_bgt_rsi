"""Offline response-validation tests; never invokes a model or Git."""
import copy
import json

import pytest

from tools.qwen_packet_agent import MODEL, WORKER, candidate_bytes


def response():
    return {"model": MODEL, "usage": {"prompt_tokens": 200, "completion_tokens": 20},
            "choices": [{"finish_reason": "stop", "message": {
                "content": json.dumps({"path": WORKER, "content": "def summarize_progress(rows):\n    return {}\n"})}}]}


def test_valid_source_is_data_only():
    value = response()
    value["choices"][0]["message"]["content"] = json.dumps({"path": WORKER, "content": "raise RuntimeError('must never execute in parser')\n"})
    assert candidate_bytes(value).startswith(b"raise RuntimeError")


@pytest.mark.parametrize("field,value", [("model", "wrong"), ("choices", []),
    ("usage", {"prompt_tokens": 0, "completion_tokens": 4097}),
    ("usage", {"prompt_tokens": 0, "completion_tokens": True}),
    ("usage", {"prompt_tokens": 16384, "completion_tokens": 1})])
def test_wrong_identity_or_accounting_fails(field, value):
    raw = response()
    raw[field] = value
    with pytest.raises(ValueError):
        candidate_bytes(raw)


@pytest.mark.parametrize("content", [
    '{"path":"workers/research_progress.py","path":"workers/other.py","content":"x=1"}',
    '{"path":"../outside.py","content":"x=1"}',
    '{"path":"workers/research_progress.py","content":""}',
    '{"path":"workers/research_progress.py","content":"x=1","shell":"echo bad"}',
    '[]', '```json\n{}\n```',
])
def test_invalid_file_envelope_fails(content):
    raw = response()
    raw["choices"][0]["message"]["content"] = content
    with pytest.raises(ValueError):
        candidate_bytes(raw)


def test_incomplete_completion_fails():
    raw = copy.deepcopy(response())
    raw["choices"][0]["finish_reason"] = "length"
    with pytest.raises(ValueError):
        candidate_bytes(raw)



def test_exact_correction_and_stale_baseline(tmp_path):
    import hashlib
    from tools.qwen_packet_agent import write_candidate
    target = tmp_path / "worker.py"
    old = b"original bytes preserved on refusal"
    target.write_bytes(old)
    with pytest.raises(ValueError, match="frozen correction base"):
        write_candidate(target, b"new", "0" * 64)
    assert target.read_bytes() == old
    write_candidate(target, b"exact Qwen bytes", hashlib.sha256(old).hexdigest())
    assert target.read_bytes() == b"exact Qwen bytes"


def test_new_file_and_symlink_refusal(tmp_path):
    import hashlib
    from tools.qwen_packet_agent import write_candidate
    target = tmp_path / "worker.py"
    write_candidate(target, b"new")
    with pytest.raises(FileExistsError):
        write_candidate(target, b"replacement")
    link = tmp_path / "link.py"
    link.symlink_to(target)
    with pytest.raises(OSError):
        write_candidate(link, b"replacement", hashlib.sha256(b"new").hexdigest())
    assert target.read_bytes() == b"new"
