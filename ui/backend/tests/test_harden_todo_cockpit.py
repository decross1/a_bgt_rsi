"""Hardening regression tests for the `/todo` cockpit backend.

House robustness doctrine (this repo's settled stance): producer-owned JSON
(active_run.json) is UNVALIDATED and forwarded raw; a single malformed/legacy/
partial value must DEGRADE to a legible fallback, NEVER 500 the cockpit. Every
POST payload that is missing/empty/wrong-type/oversize/unicode/leading-dash must
422 (never 500, never a silent default — inviolate rule 4). These tests PIN the
degrade for each realistic malformed/edge input; the existing
``test_todo_cockpit.py`` covers the happy + basic-422 paths and stays green.

The load-bearing fix this file pins: a malformed ``active_run.json`` whose
surfaced field holds a non-finite float (Python's ``json.loads`` ACCEPTS the
``NaN``/``Infinity``/``-Infinity`` literals) previously reached the JSONResponse
encoder and 500'd ``GET /api/todo/concurrency``. It now fails safe to
``{active: False}``.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.todo_cockpit import register

# All POST seams + a known-good payload, so a fuzz can keep the *other* fields
# valid while corrupting one. Mirrors test_todo_cockpit._VALID_PAYLOADS.
_VALID = {
    "authorize_fix": {"ref_id": "sf-001", "task": "re-run novelty",
                      "note": "looks promising"},
    "directive_signoff": {"iteration_id": "iter-1", "note": "checked",
                          "directive": "proceed"},
    "spawn_topic": {"ref_id": "sf-002", "kind": "finding", "topic": "holds?"},
    "abstain": {"ref_id": "sf-003", "note": "re-look later"},
    "calibration": {"ref_id": "sf-001", "prediction": "valid",
                    "confidence": 0.7},
}
_ENDPOINTS = sorted(_VALID)


@pytest.fixture()
def repo(tmp_path) -> Path:
    """tmp 'primary repo root' — interpreter + seam modules exist for the
    /available existence checks; nothing is ever executed."""
    for rel in (".venv-chroma/bin/python",
                "orchestrator/todo_cli.py",
                "orchestrator/gate_cli.py",
                "orchestrator/finding_session.py"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("", encoding="utf-8")
    return tmp_path


def _client(repo_root: Path) -> TestClient:
    app = FastAPI()
    register(app, repo_root=repo_root)
    # raise_server_exceptions=False so a 500 is OBSERVED (not re-raised) — that
    # is exactly the failure mode the doctrine forbids and we assert against.
    return TestClient(app, raise_server_exceptions=False)


def _write_active_run(repo_root: Path, raw: str) -> None:
    p = repo_root / "run_state" / "active_run.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(raw, encoding="utf-8")


# ─── POST bodies: non-object / null / wrong-type => 422, never 500 ──────


@pytest.mark.parametrize("endpoint", _ENDPOINTS)
@pytest.mark.parametrize("body", [None, [1, 2], "astring", 42, 3.14, True])
def test_post_non_object_body_is_422(repo, endpoint, body):
    # A bare null / array / scalar producer body must 422 (Body(dict)), not 500.
    r = _client(repo).post(f"/api/todo/{endpoint}", json=body)
    assert r.status_code == 422


@pytest.mark.parametrize("endpoint", _ENDPOINTS)
def test_post_empty_body_is_422(repo, endpoint):
    # No body at all (empty content) => 422, never 500.
    r = _client(repo).post(f"/api/todo/{endpoint}")
    assert r.status_code == 422


@pytest.mark.parametrize("endpoint", _ENDPOINTS)
def test_post_invalid_json_body_is_422(repo, endpoint):
    r = _client(repo).post(f"/api/todo/{endpoint}", content="{not json",
                           headers={"content-type": "application/json"})
    assert r.status_code == 422


@pytest.mark.parametrize("endpoint", _ENDPOINTS)
def test_post_empty_object_is_422(repo, endpoint):
    # Empty-vs-absent collection: an empty {} is missing every required field.
    r = _client(repo).post(f"/api/todo/{endpoint}", json={})
    assert r.status_code == 422


# Field-type fuzz: replace ONE required field with a wrong-typed value, keep the
# rest valid; an id/text field that is a number/object/array/null must 422.
_WRONG_TYPES = [123, 1.5, {"x": 1}, [1, 2], None, True]


@pytest.mark.parametrize("endpoint", _ENDPOINTS)
@pytest.mark.parametrize("bad", _WRONG_TYPES)
def test_post_wrong_field_type_is_422(repo, endpoint, bad):
    for field in _VALID[endpoint]:
        if field == "kind":
            continue  # enum field: any non-member already 422s (own test below)
        if field == "confidence":
            continue  # numeric field has its own range/type tests below
        payload = dict(_VALID[endpoint])
        payload[field] = bad
        r = _client(repo).post(f"/api/todo/{endpoint}", json=payload)
        assert r.status_code == 422, f"{endpoint}.{field}={bad!r} should 422"


# ─── id guards: oversize / unicode / leading-dash / whitespace => 422 ───


# Every endpoint that takes an id field, and the field's name.
_ID_FIELDS = {
    "authorize_fix": "ref_id",
    "directive_signoff": "iteration_id",
    "spawn_topic": "ref_id",
    "abstain": "ref_id",
    "calibration": "ref_id",
}


@pytest.mark.parametrize("endpoint,field", sorted(_ID_FIELDS.items()))
@pytest.mark.parametrize("bad_id", [
    "a" * 201,            # oversize (> _MAX_ID_LEN)
    "-sf-001",            # leading-dash argv-flag injection
    "sf-café",       # unicode outside the conservative charset
    "sf 001",             # embedded space
    "   ",                # whitespace-only
    "sf/001",             # path-ish char outside charset
])
def test_id_field_rejects_unsafe_ids(repo, endpoint, field, bad_id):
    payload = dict(_VALID[endpoint])
    payload[field] = bad_id
    r = _client(repo).post(f"/api/todo/{endpoint}", json=payload)
    assert r.status_code == 422, f"{endpoint}.{field}={bad_id!r} should 422"


def test_id_field_max_len_boundary_accepted(repo):
    # 200 chars is the cap and must still be ACCEPTED (valid-input preserved).
    payload = dict(_VALID["authorize_fix"])
    payload["ref_id"] = "a" * 200
    r = _client(repo).post("/api/todo/authorize_fix", json=payload)
    assert r.status_code == 200


# ─── free-text fields: unicode accepted, blank/whitespace rejected ──────


def test_free_text_accepts_unicode(repo):
    # Free text (--task/--note/--directive/--topic/--prediction) is NOT charset
    # restricted (never a positional argv flag) — unicode must pass unchanged.
    payload = dict(_VALID["authorize_fix"])
    payload["task"] = "café ☕ re-run \U0001f9ea"
    body = _client(repo).post("/api/todo/authorize_fix", json=payload).json()
    assert payload["task"] in body["would_run"]


@pytest.mark.parametrize("blank", ["", "   ", "\t\n", " "])
def test_free_text_blank_is_422(repo, blank):
    payload = dict(_VALID["authorize_fix"])
    payload["note"] = blank
    r = _client(repo).post("/api/todo/authorize_fix", json=payload)
    # NB:   (NBSP) is not stripped by str.strip in older runtimes; assert
    # only the clearly-blank cases hard-fail. The first three MUST 422.
    if blank.strip() == "":
        assert r.status_code == 422


# ─── calibration confidence: NaN/Infinity/out-of-range => 422 ───────────


@pytest.mark.parametrize("tok", ["NaN", "Infinity", "-Infinity"])
def test_calibration_non_finite_confidence_is_422(repo, tok):
    # NaN/Infinity arrive only as raw wire tokens (httpx won't serialize them);
    # they must 422 (out of [0,1]) — never coerced, never 500.
    raw = f'{{"ref_id":"sf-1","prediction":"p","confidence":{tok}}}'
    r = _client(repo).post("/api/todo/calibration", content=raw,
                           headers={"content-type": "application/json"})
    assert r.status_code == 422


@pytest.mark.parametrize("bad", [1.5, -0.1, "high", {"v": 1}, [1], None])
def test_calibration_bad_confidence_is_422(repo, bad):
    r = _client(repo).post("/api/todo/calibration", json={
        "ref_id": "sf-1", "prediction": "p", "confidence": bad})
    assert r.status_code == 422


# ─── spawn_topic enum: out-of-enum / missing => 422 ─────────────────────


@pytest.mark.parametrize("bad_kind", ["bogus", "", "FINDING", " finding"])
def test_spawn_topic_out_of_enum_kind_is_422(repo, bad_kind):
    r = _client(repo).post("/api/todo/spawn_topic", json={
        "ref_id": "sf-1", "kind": bad_kind, "topic": "t"})
    assert r.status_code == 422


# ─── GET /api/todo/available — stable shape under any state ─────────────


def test_available_stable_shape_when_interpreter_absent(tmp_path):
    # No interpreter, no seam modules — /available must still return the full
    # stable shape (all actions False, interpreter_present False), never 500.
    body = _client(tmp_path).get("/api/todo/available").json()
    assert body["available"] is False
    assert body["stub"] is True
    assert body["interpreter_present"] is False
    assert set(body["actions"]) == {
        "authorize_fix", "directive_signoff", "spawn_topic",
        "abstain", "calibration", "two_voice_chat"}
    assert all(v is False for v in body["actions"].values())


# ─── GET /api/todo/concurrency — malformed active_run.json => active:false ──


@pytest.mark.parametrize("raw", [
    "[1, 2, 3]",          # non-dict: bare array
    '"a string"',         # non-dict: bare string
    "42",                 # non-dict: bare number
    "null",               # non-dict: bare null
    "{not json",          # invalid JSON
    "",                   # empty file
    "   ",                # whitespace-only file
])
def test_concurrency_malformed_or_nondict_is_inactive(repo, raw):
    _write_active_run(repo, raw)
    r = _client(repo).get("/api/todo/concurrency")
    assert r.status_code == 200
    assert r.json() == {"active": False}


@pytest.mark.parametrize("raw", [
    '{"kind":NaN,"label":"x"}',       # non-finite in a surfaced field
    '{"label":Infinity}',
    '{"narration":-Infinity}',
    '{"kind":NaN}',
])
def test_concurrency_non_finite_field_fails_safe(repo, raw):
    # REGRESSION: a non-finite float (json.loads accepts NaN/Infinity literals)
    # in a surfaced field previously reached the JSONResponse encoder and 500'd
    # the cockpit. It must now degrade to {active: False}.
    _write_active_run(repo, raw)
    r = _client(repo).get("/api/todo/concurrency")
    assert r.status_code == 200
    assert r.json() == {"active": False}


def test_concurrency_valid_active_run_is_unchanged(repo):
    # Valid-input behavior is identical: active:true + surfaced fields.
    _write_active_run(
        repo, '{"kind":"loop_v0","label":"iter-1","narration":"embedding"}')
    body = _client(repo).get("/api/todo/concurrency").json()
    assert body == {"active": True, "kind": "loop_v0", "label": "iter-1",
                    "narration": "embedding"}


def test_concurrency_absent_optional_fields_omitted(repo):
    # missing optional keys: absent fields are simply omitted, not nulled.
    _write_active_run(repo, '{"kind":"ad_hoc","label":"promote"}')
    body = _client(repo).get("/api/todo/concurrency").json()
    assert body == {"active": True, "kind": "ad_hoc", "label": "promote"}


def test_concurrency_null_optional_fields_omitted(repo):
    # explicit null optional fields are dropped (not surfaced as null).
    _write_active_run(
        repo, '{"kind":"loop_v0","label":null,"narration":null}')
    body = _client(repo).get("/api/todo/concurrency").json()
    assert body == {"active": True, "kind": "loop_v0"}


@pytest.mark.parametrize("depth", [2000, 5000])
@pytest.mark.parametrize("field", ["kind", "label", "narration"])
def test_concurrency_deeply_nested_surfaced_field_fails_safe(repo, field, depth):
    # ADVERSARIAL: json.loads ACCEPTS a deeply-nested value (it parses fine), so
    # the non-finite parse_constant hook does NOT catch it. But surfacing it sent
    # a multi-thousand-level structure into FastAPI's RECURSIVE JSONResponse
    # encoder — and the request call stack is already deep, so it overflowed into
    # a RecursionError raised DURING response encoding (after the read's
    # try/except) and 500'd the cockpit. The over-deep field must now be dropped
    # and the read must NOT 500.
    raw = '{"' + field + '":' + "[" * depth + "]" * depth + ', "kind":"loop_v0"}'
    _write_active_run(repo, raw)
    r = _client(repo).get("/api/todo/concurrency")
    assert r.status_code == 200, f"{field} depth {depth} 500'd"
    body = r.json()
    assert body["active"] is True
    # the pathological field is dropped; never surfaced as an un-encodable value
    assert field not in body or not isinstance(body[field], (list, dict))


def test_concurrency_deeply_nested_object_field_fails_safe(repo):
    # Same overflow via nested OBJECTS rather than arrays.
    raw = '{"narration":' + '{"a":' * 3000 + '1' + '}' * 3000 + '}'
    _write_active_run(repo, raw)
    r = _client(repo).get("/api/todo/concurrency")
    assert r.status_code == 200
    assert r.json() == {"active": True}


def test_concurrency_shallow_nested_field_is_preserved(repo):
    # Behavior-preserving: a MODESTLY-nested value (within the depth cap) is
    # surfaced unchanged — the guard only drops the pathological case.
    _write_active_run(
        repo, '{"kind":"loop_v0","narration":{"phase":"embed","n":3}}')
    body = _client(repo).get("/api/todo/concurrency").json()
    assert body == {"active": True, "kind": "loop_v0",
                    "narration": {"phase": "embed", "n": 3}}


def test_concurrency_huge_dict_does_not_crash(repo):
    # A huge (but valid) active_run.json must not crash; it surfaces the known
    # fields and ignores the rest.
    import json as _json
    doc = {"kind": "loop_v0", "label": "iter-1",
           "extra": ["x"] * 50000, "blob": "y" * 200000}
    _write_active_run(repo, _json.dumps(doc))
    r = _client(repo).get("/api/todo/concurrency")
    assert r.status_code == 200
    body = r.json()
    assert body["active"] is True
    assert body["kind"] == "loop_v0"
    assert body["label"] == "iter-1"
    assert "extra" not in body and "blob" not in body
