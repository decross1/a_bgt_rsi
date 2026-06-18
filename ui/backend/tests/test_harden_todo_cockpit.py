"""Hardening regression tests for the `/todo` cockpit backend.

House robustness doctrine (this repo's settled stance): producer-owned JSON
(active_run.json) is UNVALIDATED and forwarded raw; a single malformed/legacy/
partial value must DEGRADE to a legible fallback, NEVER 500 the cockpit. Every
POST payload that is missing/empty/wrong-type/oversize/unicode/leading-dash must
422 (never 500, never a silent default — inviolate rule 4). These tests PIN the
degrade for each realistic malformed/edge input; the existing
``test_todo_cockpit.py`` covers the happy + basic-422 paths and stays green.

The one-shot seams (authorize_fix / directive_signoff / calibration) exec a
blessed CLI; an injected STUB runner stands in for ``subprocess.run`` so a happy
path never spawns a real process. The session-exits (spawn_topic / abstain) exec
nothing. NO test here execs a real CLI or a real model.

The load-bearing fix this file pins: a malformed ``active_run.json`` whose
surfaced field holds a non-finite float (Python's ``json.loads`` ACCEPTS the
``NaN``/``Infinity``/``-Infinity`` literals) previously reached the JSONResponse
encoder and 500'd ``GET /api/todo/concurrency``. It now fails safe to
``{active: False}``.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import todo_cockpit
from backend.todo_cockpit import register


class _StubRunner:
    """Stand-in for ``subprocess.run`` — records argv, returns a canned zero-exit
    result with VALID JSON stdout. NEVER spawns a process (no real CLI/model)."""

    def __init__(self):
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))

        class _Proc:
            returncode = 0
            stdout = '{"ok": true}'
            stderr = ""
        return _Proc()


# All POST seams + a known-good payload, so a fuzz can keep the *other* fields
# valid while corrupting one. directive_signoff / spawn_topic / abstain key on
# finding_id now (the U4 corrections).
_VALID = {
    "authorize_fix": {"ref_id": "sf-001", "task": "re-run novelty",
                      "note": "looks promising"},
    "directive_signoff": {"finding_id": "sf-1", "note": "checked",
                          "directive": "proceed"},
    "spawn_topic": {"finding_id": "sf-002", "topic": "holds?"},
    "abstain": {"finding_id": "sf-003", "note": "re-look later"},
    "calibration": {"ref_id": "sf-001", "prediction": "valid",
                    "confidence": 0.7},
}
_ENDPOINTS = sorted(_VALID)


@pytest.fixture()
def repo(tmp_path) -> Path:
    """tmp 'primary repo root' — interpreter + the CORRECTED seam modules exist
    for the /available existence checks; nothing is ever executed for real (the
    one-shot seams exec through the injected stub runner)."""
    for rel in (".venv-chroma/bin/python",
                "orchestrator/authorize_fix.py",
                "orchestrator/calibration_cli.py",
                "orchestrator/finding_session.py"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("", encoding="utf-8")
    return tmp_path


def _client(repo_root: Path, runner=None) -> TestClient:
    app = FastAPI()
    register(app, repo_root=repo_root, runner=runner or _StubRunner())
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
        if field == "confidence":
            continue  # numeric field has its own range/type tests below
        payload = dict(_VALID[endpoint])
        payload[field] = bad
        r = _client(repo).post(f"/api/todo/{endpoint}", json=payload)
        assert r.status_code == 422, f"{endpoint}.{field}={bad!r} should 422"


# ─── id guards: oversize / unicode / leading-dash / whitespace => 422 ───


# Every endpoint that takes an id field, and the field's name (corrected: the
# directive_signoff / spawn_topic / abstain id field is finding_id now).
_ID_FIELDS = {
    "authorize_fix": "ref_id",
    "directive_signoff": "finding_id",
    "spawn_topic": "finding_id",
    "abstain": "finding_id",
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
    # Free text (--task/--note/--directive/--prediction) is NOT charset
    # restricted (never a positional argv flag) — unicode must pass unchanged
    # into the blessed exec argv (asserted via the injected stub runner).
    stub = _StubRunner()
    payload = dict(_VALID["authorize_fix"])
    payload["task"] = "café ☕ re-run \U0001f9ea"
    r = _client(repo, runner=stub).post("/api/todo/authorize_fix", json=payload)
    assert r.status_code == 200
    assert payload["task"] in stub.calls[-1]          # forwarded to the CLI argv


@pytest.mark.parametrize("blank", ["", "   ", "\t\n", " "])
def test_free_text_blank_is_422(repo, blank):
    payload = dict(_VALID["authorize_fix"])
    payload["note"] = blank
    r = _client(repo).post("/api/todo/authorize_fix", json=payload)
    # NB:   (NBSP) is not stripped by str.strip in older runtimes; assert
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


# ─── GET /api/todo/available — stable shape under any state ─────────────


def test_available_stable_shape_when_interpreter_absent(tmp_path):
    # No interpreter, no seam modules — /available must still return the full
    # stable shape (all actions False, interpreter_present False), never 500.
    body = _client(tmp_path).get("/api/todo/available").json()
    assert body["available"] is False
    assert body["interpreter_present"] is False
    assert set(body["actions"]) == {
        "authorize_fix", "directive_signoff", "spawn_topic",
        "abstain", "calibration", "two_voice_chat"}
    assert all(v is False for v in body["actions"].values())
    # The allowed_actions -> endpoint map is present regardless of disk state.
    assert "allowed_action_endpoints" in body


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


# ─── production import form: stays RELATIVE so uvicorn never regresses ──────


def test_import_of_exec_blessed_is_relative_not_absolute_backend():
    # REGRESSION (integrator U4 fix): the helper import MUST be the package-relative
    # `from .attest import _exec_blessed`. The absolute `from backend.attest import`
    # form breaks the served app (uvicorn loads the module as `backend.todo_cockpit`
    # — a SUBMODULE of the `backend` package — where an absolute sibling import is
    # the fragile, refactor-unsafe form the integrator just removed). Pin the source
    # text so the relative form can never silently regress back: the test harness
    # itself imports `backend.*` from sys.path, so a bad import would NOT red any of
    # the other tests — only this static-source pin catches it.
    src = Path(todo_cockpit.__file__).read_text(encoding="utf-8")
    assert "from .attest import _exec_blessed" in src, (
        "todo_cockpit must import _exec_blessed via the package-relative "
        "`from .attest import _exec_blessed` (the integrator's uvicorn fix)")
    assert "from backend.attest import" not in src, (
        "the absolute `from backend.attest import` form regressed — it breaks "
        "the served uvicorn app; use the relative `from .attest import` form")


# ─── /available: per-module flip isolation + interpreter gates everything ───


@pytest.mark.parametrize("present,expect_true", [
    ("orchestrator/authorize_fix.py", "authorize_fix"),
    ("orchestrator/calibration_cli.py", "calibration"),
    ("orchestrator/finding_session.py", "directive_signoff"),
])
def test_available_each_oneshot_seam_flips_independently(tmp_path, present, expect_true):
    # REGRESSION: each one-shot seam must light up ONLY when ITS OWN corrected
    # module is on disk — a single missing module must not drag the others down,
    # nor a single present one falsely light the rest. (The existing tests only
    # cover all-present / all-absent; this pins the per-module isolation so a
    # future _SEAM_MODULES edit that cross-wires the existence checks reds here.)
    (tmp_path / ".venv-chroma" / "bin").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".venv-chroma" / "bin" / "python").write_text("", encoding="utf-8")
    p = tmp_path / present
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("", encoding="utf-8")
    actions = _client(tmp_path).get("/api/todo/available").json()["actions"]
    # The one seam whose module exists is True; the OTHER two one-shots are False.
    for name in ("authorize_fix", "calibration", "directive_signoff"):
        assert actions[name] is (name == expect_true), (
            f"{name} should be {name == expect_true} with only {present} present")
    # finding_session.py drives directive_signoff AND two_voice_chat together.
    assert actions["two_voice_chat"] is (present.endswith("finding_session.py"))
    # session-exits never flip True on a module's presence.
    assert actions["spawn_topic"] is False
    assert actions["abstain"] is False
    # Partial presence => the overall `available` is never True.
    assert _client(tmp_path).get("/api/todo/available").json()["available"] is False


def test_available_interpreter_absent_gates_every_action_false(tmp_path):
    # REGRESSION: with EVERY corrected module on disk but the interpreter ABSENT,
    # all actions stay False and `available` is False (python_ok gates the whole
    # handshake — a missing .venv-chroma must never let a seam claim availability).
    for rel in ("orchestrator/authorize_fix.py",
                "orchestrator/calibration_cli.py",
                "orchestrator/finding_session.py"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("", encoding="utf-8")
    body = _client(tmp_path).get("/api/todo/available").json()
    assert body["interpreter_present"] is False
    assert body["available"] is False
    assert all(v is False for v in body["actions"].values())


# ─── one-shot exec failure modes propagate through the cockpit (502) ────────


def test_oneshot_seam_spawn_oserror_is_502(repo):
    # REGRESSION: a spawn-level failure (e.g. a missing interpreter raising
    # OSError) must surface as a 502 through the cockpit — NOT a 500, NOT a faked
    # success shape. (_exec_blessed catches OSError/SubprocessError; pin that the
    # cockpit endpoints inherit that surface.)
    def raising(argv, **kw):
        raise OSError("no such interpreter")
    r = _client(repo, runner=raising).post(
        "/api/todo/authorize_fix", json=_VALID["authorize_fix"])
    assert r.status_code == 502
    body = r.json()
    assert body["rc"] is None
    assert "exec failed before the CLI completed" in body["stderr"]


def test_oneshot_seam_spawn_timeout_is_502(repo):
    # REGRESSION: a wedged CLI hitting the exec timeout (TimeoutExpired, a
    # subprocess.SubprocessError) must 502 through the cockpit, never 500.
    def timing_out(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 120)
    r = _client(repo, runner=timing_out).post(
        "/api/todo/calibration", json=_VALID["calibration"])
    assert r.status_code == 502


def test_oneshot_seam_rc0_nonjson_stdout_is_502(repo):
    # REGRESSION: a CLI that exits 0 but prints NON-JSON broke the D-046 contract
    # (the stdout is the writer's receipt). The cockpit must surface 502 with the
    # explanatory error, never fabricate a success shape from un-parseable output.
    class _BadProc:
        def __call__(self, argv, **kw):
            class P:
                returncode = 0
                stdout = "not json at all"
                stderr = ""
            return P()
    r = _client(repo, runner=_BadProc()).post(
        "/api/todo/directive_signoff", json=_VALID["directive_signoff"])
    assert r.status_code == 502
    assert "not parseable JSON" in r.json()["error"]


# ─── directive_signoff keys on finding_id, ignores a stray iteration_id ─────


def test_directive_signoff_ignores_stray_iteration_id(repo):
    # REGRESSION: the U4 fix re-keyed directive_signoff onto finding_id (the old
    # stub keyed on iteration_id with verdict-style argv). A caller that sends a
    # bogus iteration_id ALONGSIDE a valid finding_id must key on the finding_id
    # and NEVER leak iteration_id into the blessed argv (no flag/identity confusion).
    stub = _StubRunner()
    r = _client(repo, runner=stub).post("/api/todo/directive_signoff", json={
        "iteration_id": "iter-2026-06-09-001", "finding_id": "sf-9",
        "note": "n", "directive": "d"})
    assert r.status_code == 200
    tokens = stub.calls[-1][3:]
    assert tokens == [
        "--set-status", "sf-9", "validated",
        "--note", "n", "--directive", "d", "--by", "human:ui"]
    assert "iter-2026-06-09-001" not in tokens   # the stray id never reaches argv
    assert "--iteration-id" not in tokens         # no verdict-style flag


# ─── session-exits write NOTHING to a tmp repo tree (snapshot proof) ────────


def test_session_exits_create_no_file_under_tmp_repo(repo):
    # REGRESSION (target 3, tmp-snapshot form): spawn_topic / abstain must exec
    # nothing AND create no file anywhere under the (tmp) repo root — they are
    # pure session-exit indicators. Snapshot the whole tmp tree before/after so a
    # future edit that sneaks in a faked write reds here, independently of the
    # live-ledger snapshot in test_todo_cockpit.py.
    def listing() -> set[str]:
        return {str(p) for p in repo.rglob("*") if p.is_file()}
    stub = _StubRunner()
    cl = _client(repo, runner=stub)
    before = listing()
    assert cl.post("/api/todo/spawn_topic",
                   json=_VALID["spawn_topic"]).status_code == 200
    assert cl.post("/api/todo/abstain",
                   json=_VALID["abstain"]).status_code == 200
    after = listing()
    assert after == before, f"session-exit created/removed files: {after ^ before}"
    assert stub.calls == [], "session-exits must exec nothing"
