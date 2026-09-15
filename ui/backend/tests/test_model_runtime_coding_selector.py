"""UI-only source-version selection tests; run after Flash44 restore."""
import hashlib
import json

import pytest

from backend import model_runtime as mr
from backend import model_runtime_followon as followon
from backend import registered_followon_coding_plan as coding
from backend import registered_followon_plan as old
from bench.flash_next_ab import followon_dispatch as grouped


def _hint(monkeypatch, value):
    raw = json.dumps(value, sort_keys=True).encode()
    monkeypatch.setattr(mr, "_read_path", lambda *_args, **_kw: raw)


def test_exact_coding_study_uses_new_root_validator(monkeypatch, tmp_path):
    _hint(monkeypatch, {
        "study_id": "coding-temp1-medium-and-decode-v1",
        "registered_code_root": str(coding.CODE_ROOT),
    })
    calls = []
    monkeypatch.setattr(coding, "registered_expected",
                        lambda *args, **kw: calls.append((args, kw)) or {"new": True})
    monkeypatch.setattr(old, "registered_expected",
                        lambda *_args, **_kw: (_ for _ in ()).throw(
                            AssertionError("old source validator was selected")))
    source, output = tmp_path / "window.json", tmp_path / "run"
    assert followon._registered_expected_for_window(source, output) == {"new": True}
    assert calls == [((source, output), {"cohort": "flash"})]


def test_coding_study_wrong_root_and_unknown_study_fail_closed(monkeypatch, tmp_path):
    source, output = tmp_path / "window.json", tmp_path / "run"
    _hint(monkeypatch, {
        "study_id": "coding-temp1-medium-and-decode-v1",
        "registered_code_root": "/tmp/unregistered",
    })
    with pytest.raises(mr.RuntimeSourceError):
        followon._registered_expected_for_window(source, output)
    _hint(monkeypatch, {
        "study_id": "unregistered-coding-study",
        "registered_code_root": str(coding.CODE_ROOT),
    })
    with pytest.raises(mr.RuntimeSourceError):
        followon._registered_expected_for_window(source, output)


def test_coding_source_drift_is_unknown_not_old_fallback(monkeypatch, tmp_path):
    _hint(monkeypatch, {
        "study_id": "coding-temp1-medium-and-decode-v1",
        "registered_code_root": str(coding.CODE_ROOT),
    })
    monkeypatch.setattr(coding, "registered_expected",
                        lambda *_args, **_kw: (_ for _ in ()).throw(
                            mr.RuntimeSourceError("coding bytes changed")))
    monkeypatch.setattr(old, "registered_expected",
                        lambda *_args, **_kw: (_ for _ in ()).throw(
                            AssertionError("old root fallback after drift")))
    with pytest.raises(mr.RuntimeSourceError):
        followon._registered_expected_for_window(
            tmp_path / "window.json", tmp_path / "run")


@pytest.mark.parametrize("study_id", [
    "thinking-market-diagnostics-v1", "selected-profile-repair-v1",
])
def test_original_followon_still_uses_old_validator(monkeypatch, tmp_path, study_id):
    _hint(monkeypatch, {
        "study_id": study_id,
        "registered_code_root": str(old.CODE_ROOT),
    })
    monkeypatch.setattr(old, "registered_expected",
                        lambda *_args, **_kw: {"old": True})
    monkeypatch.setattr(coding, "registered_expected",
                        lambda *_args, **_kw: (_ for _ in ()).throw(
                            AssertionError("new root selected for old C0")))
    assert followon._registered_expected_for_window(
        tmp_path / "window.json", tmp_path / "run") == {"old": True}


def test_new_root_code_bundle_raw_drift_rejected_before_worker(monkeypatch, tmp_path):
    code_root = tmp_path / "new-code"
    module_root = code_root / "bench/flash_next_ab"
    module_root.mkdir(parents=True)
    research = tmp_path / "research"
    source_root = research / "evaluation/followon-window-plans"
    source_root.mkdir(parents=True)
    monkeypatch.setattr(coding, "CODE_ROOT", code_root)
    monkeypatch.setattr(grouped, "RESEARCH_ROOT", research)
    names = sorted(coding.MANDATORY_NEW_SOURCE_NAMES)
    names.extend(f"filler-{index:02d}.py" for index in range(39))
    bundle = {}
    for name in names:
        path = module_root / name
        raw = f"# {name}\n".encode()
        path.write_bytes(raw)
        bundle[name] = {"path": str(path),
                        "sha256": hashlib.sha256(raw).hexdigest(),
                        "bytes": len(raw)}
    window_id = "qfn-followon-coding-temp1-test"
    source = source_root / f"{window_id}.flash.json"
    source.write_text(json.dumps({
        "window_id": window_id, "cohort": "flash",
        "study_id": coding.STUDY_ID,
        "registered_code_root": str(code_root),
        "followon_source_bundle": bundle,
        "followon_source_bundle_sha256": grouped._canonical_sha(bundle),
        "blocks": [],
    }))
    short = json.loads(source.read_text())
    short["followon_source_bundle"].pop(names[-1])
    short["followon_source_bundle_sha256"] = grouped._canonical_sha(
        short["followon_source_bundle"])
    source.write_text(json.dumps(short))
    with pytest.raises(mr.RuntimeSourceError, match="bundle shape"):
        coding._raw_fingerprint(source, "flash")
    short["followon_source_bundle"] = bundle
    short["followon_source_bundle_sha256"] = grouped._canonical_sha(bundle)
    source.write_text(json.dumps(short))
    (module_root / names[0]).write_bytes(b"# changed\n")
    with pytest.raises(mr.RuntimeSourceError, match="raw bytes changed"):
        coding._raw_fingerprint(source, "flash")
