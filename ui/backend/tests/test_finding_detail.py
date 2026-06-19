"""Finding-detail endpoint tests — the read-only /todo tutor data layer (U1).

Side-effect-free: every path points at tmp_path, no real run_state/memory
writes. Mirrors test_coordinator.py / test_robust_findings.py (TestClient
against the coordinator_memory create_app param, which is the memory dir the
finding-detail router reads). ``raise_server_exceptions=False`` so a regressed
endpoint surfaces as an observed 500 (the thing we guard) instead of bubbling
the exception out of the test client.

Covers: the happy-path surfaced_findings × loop_memory JOIN; the
surfaced_findings.status.jsonl EFFECTIVE-status overlay (last-row-wins) and its
absence (base status used); unknown finding_id => 200 found:false; absent files
=> 200 found:false (never 500); malformed/non-dict rows dropped; a non-dict
``evidence`` coerced to null; a finding present but its source iteration absent
=> source_iteration:null but found:true; and a WRITES-NOTHING snapshot delta of
the tmp memory dir across a GET (the tutor fence at the data layer, D-054).
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.finding_detail import register as register_finding_detail


def _client(tmp_path) -> TestClient:
    """TestClient with every path pinned at tmp_path (the test_coordinator idiom).

    The finding-detail router reads from the coordinator_memory dir
    (``coord_memory``), wired by the integrator as
    ``register(app, memory_dir=Path(coordinator_memory))``. The dir is
    intentionally NOT pre-created — the absent-file case relies on it being
    missing, and _read_jsonl tolerates that. Tests that need a file mkdir its
    parent themselves. ``raise_server_exceptions=False`` lets a regression be
    asserted as a 500 response rather than raised out of the client.
    """
    (tmp_path / "logs").mkdir(exist_ok=True)
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"current_day": "finding_detail"}), encoding="utf-8")
    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text("", encoding="utf-8")
    bench = tmp_path / "day1.csv"
    bench.write_text(
        "prompt_idx,completion_tokens,elapsed_s,decode_tok_per_s\n0,256,8.0,32.0\n",
        encoding="utf-8",
    )
    mtp = tmp_path / "mtp.csv"

    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    loop_run_state = tmp_path / "loop_run_state"
    loop_run_state.mkdir(exist_ok=True)
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir(exist_ok=True)
    loop_memory = tmp_path / "loop_memory.jsonl"

    coord_run_state = tmp_path / "coord_run_state"
    coord_memory = tmp_path / "coord_memory"

    app = create_app(
        logs_dir=tmp_path / "logs",
        telemetry_file=telemetry,
        state_file=state,
        bench_csv=bench,
        mtp_csv=mtp,
        loop_v0_repo=repo,
        loop_v0_run_state=loop_run_state,
        loop_v0_journal=journal_dir,
        loop_v0_memory=loop_memory,
        coordinator_run_state=coord_run_state,
        coordinator_memory=coord_memory,
    )
    # Wire the finding-detail router onto the test app exactly as the
    # integrator wires it in app.py: register(app, memory_dir=Path(
    # coordinator_memory)). This keeps the test self-contained (and green
    # pre-integration) without the build agent touching app.py.
    register_finding_detail(app, memory_dir=coord_memory)
    return TestClient(app, raise_server_exceptions=False)


def _memory_dir(tmp_path) -> Path:
    return tmp_path / "coord_memory"


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _snapshot(root: Path) -> dict[str, tuple]:
    """A (path -> (size, mtime_ns, bytes)) snapshot of every file under root —
    enough to detect ANY write (new file, truncate, rewrite, touch)."""
    snap: dict[str, tuple] = {}
    if not root.exists():
        return snap
    for p in sorted(root.rglob("*")):
        if p.is_file():
            st = p.stat()
            snap[str(p)] = (st.st_size, st.st_mtime_ns, p.read_bytes())
    return snap


# ─── happy path: the surfaced_findings × loop_memory JOIN ────────────────


def _finding_row() -> dict:
    return {
        "finding_id": "sf-iter-2026-06-09-003",
        "source_iteration_id": "iter-2026-06-09-003",
        "title": "Level-k convergence rate refinement worth a real run",
        "claim": "Under the measured setting, level-k beliefs converge a step "
        "faster than the analytic bound predicts.",
        "why_it_matters": "If it holds at scale it tightens the equilibrium "
        "selection argument for the auction design.",
        "what_would_change_it": "A run where the convergence step matches the "
        "analytic bound would falsify the refinement.",
        "evidence": {
            "journal_entry_path": "journal/iterations/003.md",
            "results_path": "run_state/exp/level_k_003.json",
            "experiment_outcome": {"metric": "steps_to_converge", "value": 4},
            "critic_rationale": "survives — retrieval grounded the claim.",
        },
        "novelty_class": "novel",
        "critic_verdict": "survives",
        "status": "surfaced",
        "promoted_at": "2026-06-09T13:20:00Z",
    }


def _iteration_row() -> dict:
    return {
        "iteration_id": "iter-2026-06-09-003",
        "seed": {"topic": "Level-k convergence in repeated auctions",
                 "source": "coordinator"},
        "hypothesis": {"text": "Level-k beliefs converge faster than the bound."},
        "nara_summary": "Hypothesized a faster convergence; critic let it stand.",
        "gate_status": "pending",
        "journal_entry_path": "journal/iterations/003.md",
        "started_at": "2026-06-09T13:00:00Z",
        "ended_at": "2026-06-09T13:18:00Z",
    }


def test_happy_path_join_surfaces_finding_and_source_iteration(tmp_path):
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    _write_jsonl(mem / "surfaced_findings.jsonl", [_finding_row()])
    _write_jsonl(mem / "loop_memory.jsonl", [_iteration_row()])

    resp = client.get("/api/finding/sf-iter-2026-06-09-003")
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["finding_id"] == "sf-iter-2026-06-09-003"
    assert body["claim"].startswith("Under the measured setting")
    assert body["what_would_change_it"].startswith("A run where")
    assert body["novelty_class"] == "novel"
    assert body["critic_verdict"] == "survives"
    # evidence is a DICT (surfaced_findings.jsonl shape), surfaced intact.
    assert isinstance(body["evidence"], dict)
    assert body["evidence"]["journal_entry_path"] == "journal/iterations/003.md"
    assert body["evidence"]["experiment_outcome"] == {
        "metric": "steps_to_converge", "value": 4,
    }
    # the compact source-iteration projection from loop_memory.jsonl.
    si = body["source_iteration"]
    assert si is not None
    assert si["iteration_id"] == "iter-2026-06-09-003"
    assert si["topic"] == "Level-k convergence in repeated auctions"  # seed.topic
    assert si["gate_status"] == "pending"
    assert si["nara_summary"].startswith("Hypothesized")
    assert si["journal_entry_path"] == "journal/iterations/003.md"


# ─── status overlay: last audit row wins ─────────────────────────────────


def test_status_overlay_applied_last_row_wins(tmp_path):
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    _write_jsonl(mem / "surfaced_findings.jsonl", [_finding_row()])  # base: surfaced
    # Two audit rows; the LAST one for this finding_id is the effective status.
    _write_jsonl(mem / "surfaced_findings.status.jsonl", [
        {"finding_id": "sf-iter-2026-06-09-003", "status": "in_review"},
        {"finding_id": "sf-other", "status": "validated"},  # different finding
        {"finding_id": "sf-iter-2026-06-09-003", "status": "validated"},
    ])
    resp = client.get("/api/finding/sf-iter-2026-06-09-003")
    assert resp.status_code == 200
    # base "surfaced" overridden by the LAST matching audit row, "validated".
    assert resp.json()["status"] == "validated"


def test_status_overlay_absent_uses_base_status(tmp_path):
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    _write_jsonl(mem / "surfaced_findings.jsonl", [_finding_row()])  # base: surfaced
    # No surfaced_findings.status.jsonl written at all.
    assert not (mem / "surfaced_findings.status.jsonl").exists()
    resp = client.get("/api/finding/sf-iter-2026-06-09-003")
    assert resp.status_code == 200
    assert resp.json()["status"] == "surfaced"  # base row status, un-coerced


# ─── unknown finding_id => 200 found:false (NOT 404) ─────────────────────


def test_unknown_finding_id_returns_200_found_false(tmp_path):
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    _write_jsonl(mem / "surfaced_findings.jsonl", [_finding_row()])
    resp = client.get("/api/finding/does-not-exist")
    assert resp.status_code == 200  # the tutor degrades in place, never 404
    body = resp.json()
    assert body == {"found": False, "finding_id": "does-not-exist"}


def test_pathological_finding_id_just_matches_nothing(tmp_path):
    """A weird single-segment id string is not an error — it simply joins to
    no row (found:false). A bare ``%2F`` would be a routing artifact, not an
    endpoint behavior, so the pathological id stays within one path segment."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    _write_jsonl(mem / "surfaced_findings.jsonl", [_finding_row()])
    weird = "..wat'; DROP TABLE findings;--%E2%9C%93"
    resp = client.get(f"/api/finding/{weird}")
    assert resp.status_code == 200
    assert resp.json()["found"] is False


# ─── absent files => 200 found:false, never 500 ──────────────────────────


def test_absent_files_return_200_found_false_not_500(tmp_path):
    client = _client(tmp_path)
    # No coord_memory dir / files created at all.
    assert not _memory_dir(tmp_path).exists()
    resp = client.get("/api/finding/sf-iter-2026-06-09-003")
    assert resp.status_code == 200
    assert resp.json() == {"found": False,
                           "finding_id": "sf-iter-2026-06-09-003"}


# ─── malformed / non-dict rows dropped, no 500 ───────────────────────────


def test_malformed_and_non_dict_rows_dropped(tmp_path):
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    path = mem / "surfaced_findings.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    # Garbage + non-dict JSON bracketing the one real dict row.
    path.write_text(
        "THIS IS NOT JSON {{{\n"
        "42\n"
        '"a bare string"\n'
        "[1, 2, 3]\n"
        "null\n"
        + json.dumps(_finding_row()) + "\n",
        encoding="utf-8",
    )
    _write_jsonl(mem / "loop_memory.jsonl", [_iteration_row()])
    resp = client.get("/api/finding/sf-iter-2026-06-09-003")
    assert resp.status_code == 200  # never 500 from a stray line
    body = resp.json()
    assert body["found"] is True
    assert body["source_iteration"]["iteration_id"] == "iter-2026-06-09-003"


def test_malformed_status_and_loop_memory_rows_dropped(tmp_path):
    """Garbled lines in the OVERLAY and JOIN sources are dropped too, not 500."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    _write_jsonl(mem / "surfaced_findings.jsonl", [_finding_row()])
    (mem / "surfaced_findings.status.jsonl").write_text(
        "broken{{\n"
        "99\n"
        '{"finding_id":"sf-iter-2026-06-09-003","status":"in_review"}\n',
        encoding="utf-8",
    )
    (mem / "loop_memory.jsonl").write_text(
        "]not-json[\n"
        "true\n"
        + json.dumps(_iteration_row()) + "\n",
        encoding="utf-8",
    )
    resp = client.get("/api/finding/sf-iter-2026-06-09-003")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "in_review"  # overlay applied past the garbage
    assert body["source_iteration"]["topic"] == \
        "Level-k convergence in repeated auctions"


# ─── non-dict evidence => null, no 500 ───────────────────────────────────


def test_non_dict_evidence_coerced_to_null(tmp_path):
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    row = _finding_row()
    row["evidence"] = "evidence should be a dict but isn't"  # producer drift
    _write_jsonl(mem / "surfaced_findings.jsonl", [row])
    resp = client.get("/api/finding/sf-iter-2026-06-09-003")
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["evidence"] is None  # contract: non-dict evidence => null


def test_list_evidence_coerced_to_null(tmp_path):
    """surfaced_findings.jsonl evidence is a DICT; a LIST is the classic
    producer-drift shape and must coerce to null, not leak a list."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    row = _finding_row()
    row["evidence"] = [{"journal_entry_path": "x"}]  # list, not dict
    _write_jsonl(mem / "surfaced_findings.jsonl", [row])
    resp = client.get("/api/finding/sf-iter-2026-06-09-003")
    assert resp.status_code == 200
    assert resp.json()["evidence"] is None


# ─── finding present, source iteration absent => source_iteration null ───


def test_finding_present_source_iteration_absent(tmp_path):
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    _write_jsonl(mem / "surfaced_findings.jsonl", [_finding_row()])
    # loop_memory.jsonl has NO matching iteration_id (different iteration).
    _write_jsonl(mem / "loop_memory.jsonl", [
        {"iteration_id": "iter-2026-06-09-999", "seed": {"topic": "other"}},
    ])
    resp = client.get("/api/finding/sf-iter-2026-06-09-003")
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True  # the finding itself is real
    assert body["source_iteration"] is None  # but its iteration is unreadable
    assert body["source_iteration_id"] == "iter-2026-06-09-003"


def test_finding_with_no_source_iteration_id(tmp_path):
    """A finding row missing source_iteration_id still resolves: found:true,
    source_iteration:null (no id => nothing to join)."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    row = _finding_row()
    del row["source_iteration_id"]
    _write_jsonl(mem / "surfaced_findings.jsonl", [row])
    _write_jsonl(mem / "loop_memory.jsonl", [_iteration_row()])
    resp = client.get("/api/finding/sf-iter-2026-06-09-003")
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["source_iteration"] is None
    assert body["source_iteration_id"] is None


# ─── WRITES-NOTHING: the tutor fence at the data layer (D-054) ───────────


def test_get_writes_nothing_zero_delta(tmp_path):
    """Snapshot the tmp memory dir (file set + sizes + mtimes + bytes) before
    and after a GET; assert ZERO delta. The read-only endpoint opens no file
    for writing — never fakes a write or a verdict (inviolate rule 4)."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    _write_jsonl(mem / "surfaced_findings.jsonl", [_finding_row()])
    _write_jsonl(mem / "loop_memory.jsonl", [_iteration_row()])
    _write_jsonl(mem / "surfaced_findings.status.jsonl", [
        {"finding_id": "sf-iter-2026-06-09-003", "status": "in_review"},
    ])

    before = _snapshot(mem)
    # Hit both the found and the not-found path — neither may write.
    assert client.get("/api/finding/sf-iter-2026-06-09-003").status_code == 200
    assert client.get("/api/finding/nope").status_code == 200
    after = _snapshot(mem)

    assert after == before  # byte-for-byte, mtime-for-mtime: zero writes


# ═════════════════════════════════════════════════════════════════════════
# ADVERSARIAL HARDENING (independent verifier, 2026-06-17)
#
# A previous build agent claimed this surface robust; these break it.
# The headline class (confirmed REAL bugs, all formerly 500): a surfaced
# field that is a deeply-NESTED value, a >digit-limit bigint, or a
# non-finite float is valid JSON, survives the read, but 500s FastAPI's
# JSONResponse encoder AFTER the read's try/except — exactly the case
# todo_cockpit.py guards with _within_depth. The fix degrades the one
# pathological field to null (or drops the un-parseable row), never 500.
# ═════════════════════════════════════════════════════════════════════════


def _nest(depth: int, leaf="x"):
    """A value nested `depth` dicts deep: {"a": {"a": {"a": ... leaf}}}. Thousands
    of levels is valid JSON but recursion-overflows the response encoder."""
    value = leaf
    for _ in range(depth):
        value = {"a": value}
    return value


# Deep enough to overflow the encoder's recursion on this call stack, and well
# past the endpoint's _MAX_FIELD_DEPTH cap — but cheap to build/parse.
_OVERFLOW_DEPTH = 5000


# ─── TARGET 1: response-encoder overflow — deep nesting ──────────────────


def test_deeply_nested_evidence_degrades_not_500(tmp_path):
    """evidence is surfaced intact (it is a dict), so a thousands-deep evidence
    reaches the encoder and formerly RecursionError-500'd. It must degrade to
    null (drop the one pathological field), the finding still found:true."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    row = _finding_row()
    row["evidence"] = _nest(_OVERFLOW_DEPTH)
    _write_jsonl(mem / "surfaced_findings.jsonl", [row])
    resp = client.get("/api/finding/sf-iter-2026-06-09-003")
    assert resp.status_code == 200  # NOT 500
    body = resp.json()
    assert body["found"] is True
    assert body["evidence"] is None  # pathological field dropped, never 500


def test_lone_surrogate_string_degrades_not_500(tmp_path):
    """A producer ``"\\udXXX"`` escape decodes into a LONE surrogate str: valid
    to parse, but not UTF-8-encodable, so the JSONResponse encoder formerly
    500'd AFTER the read (the same class as NaN/Infinity, on a string). The
    pathological field drops to null; the finding stays found:true."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    row = _finding_row()
    row["claim"] = "ok\ud834bad"  # a lone (unpaired) surrogate in a string value
    _write_jsonl(mem / "surfaced_findings.jsonl", [row])
    resp = client.get("/api/finding/sf-iter-2026-06-09-003")
    assert resp.status_code == 200  # NOT 500
    body = resp.json()
    assert body["found"] is True
    assert body["claim"] is None  # the unencodable field dropped, never 500


def test_deeply_nested_source_iteration_member_degrades_not_500(tmp_path):
    """A thousands-deep value in a JOINED loop_memory field (nara_summary) is
    surfaced in the source_iteration projection and formerly 500'd. Only that
    member drops; the rest of the iteration (topic, iteration_id) stays."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    _write_jsonl(mem / "surfaced_findings.jsonl", [_finding_row()])
    it = _iteration_row()
    it["nara_summary"] = _nest(_OVERFLOW_DEPTH)
    _write_jsonl(mem / "loop_memory.jsonl", [it])
    resp = client.get("/api/finding/sf-iter-2026-06-09-003")
    assert resp.status_code == 200
    si = resp.json()["source_iteration"]
    assert si is not None
    assert si["iteration_id"] == "iter-2026-06-09-003"  # join intact
    assert si["topic"] == "Level-k convergence in repeated auctions"  # intact
    assert si["nara_summary"] is None  # only the pathological member dropped


def test_deeply_nested_topic_degrades_not_500(tmp_path):
    """seed.topic is surfaced; a thousands-deep topic formerly 500'd the encoder.
    Drop topic to null, keep the rest of the iteration projection."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    _write_jsonl(mem / "surfaced_findings.jsonl", [_finding_row()])
    _write_jsonl(mem / "loop_memory.jsonl", [
        {"iteration_id": "iter-2026-06-09-003", "seed": {"topic": _nest(_OVERFLOW_DEPTH)},
         "nara_summary": "ok"},
    ])
    resp = client.get("/api/finding/sf-iter-2026-06-09-003")
    assert resp.status_code == 200
    si = resp.json()["source_iteration"]
    assert si["topic"] is None  # pathological topic dropped
    assert si["nara_summary"] == "ok"  # sibling intact


def test_deeply_nested_status_overlay_degrades_not_500(tmp_path):
    """The status-overlay value is surfaced un-coerced; a thousands-deep status
    audit value formerly 500'd. Drop the overlaid status to null (degrade), not
    500 — and do NOT silently fall back to a different status (rule 4)."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    _write_jsonl(mem / "surfaced_findings.jsonl", [_finding_row()])
    # raw write: a nested status value is not expressible via _write_jsonl helper
    (mem / "surfaced_findings.status.jsonl").write_text(
        json.dumps({"finding_id": "sf-iter-2026-06-09-003",
                    "status": _nest(_OVERFLOW_DEPTH)}) + "\n",
        encoding="utf-8",
    )
    resp = client.get("/api/finding/sf-iter-2026-06-09-003")
    assert resp.status_code == 200
    assert resp.json()["status"] is None  # pathological overlay dropped


def test_shallow_nested_evidence_still_surfaces_intact(tmp_path):
    """The depth guard must not over-fire: a normal small nested evidence dict
    surfaces BYTE-INTACT (the guard drops only the pathological, never coerces a
    valid value)."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    row = _finding_row()
    row["evidence"] = {"a": {"b": {"c": {"d": 1}}}, "metric": "steps", "value": 4}
    _write_jsonl(mem / "surfaced_findings.jsonl", [row])
    resp = client.get("/api/finding/sf-iter-2026-06-09-003")
    assert resp.status_code == 200
    assert resp.json()["evidence"] == {
        "a": {"b": {"c": {"d": 1}}}, "metric": "steps", "value": 4,
    }


# ─── TARGET 1: response-encoder overflow — non-finite floats ─────────────


def test_nan_float_in_evidence_degrades_not_500(tmp_path):
    """A NaN literal is valid to Python's json parser but the encoder emits the
    non-compliant token `NaN` and 500s. Drop evidence to null, never 500."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    path = mem / "surfaced_findings.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"finding_id":"sf-iter-2026-06-09-003","evidence":{"x":NaN}}\n',
        encoding="utf-8",
    )
    resp = client.get("/api/finding/sf-iter-2026-06-09-003")
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["evidence"] is None


def test_infinity_float_in_evidence_degrades_not_500(tmp_path):
    """Infinity / -Infinity literals likewise 500 the encoder — degrade."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    path = mem / "surfaced_findings.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"finding_id":"sf-iter-2026-06-09-003","evidence":{"a":Infinity,"b":-Infinity}}\n',
        encoding="utf-8",
    )
    resp = client.get("/api/finding/sf-iter-2026-06-09-003")
    assert resp.status_code == 200
    assert resp.json()["evidence"] is None


def test_nan_in_status_overlay_degrades_not_500(tmp_path):
    """A non-finite status-overlay value 500'd the encoder; drop to null."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    _write_jsonl(mem / "surfaced_findings.jsonl", [_finding_row()])
    (mem / "surfaced_findings.status.jsonl").write_text(
        '{"finding_id":"sf-iter-2026-06-09-003","status":NaN}\n',
        encoding="utf-8",
    )
    resp = client.get("/api/finding/sf-iter-2026-06-09-003")
    assert resp.status_code == 200
    assert resp.json()["status"] is None


# ─── TARGET 1: response-encoder overflow — huge bigints (two layers) ─────


def test_bigint_over_str_limit_row_dropped_not_500(tmp_path):
    """A numeric literal over CPython's int<->str digit limit (>4300 digits)
    makes json.loads ITSELF raise a bare ValueError (NOT a JSONDecodeError) —
    formerly an uncaught 500 at the READ layer, before the encoder is reached.
    The row is dropped as malformed (like any un-parseable line) => found:false."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    path = mem / "surfaced_findings.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    big = "1" + "0" * 6000  # 6001-digit integer literal
    path.write_text(
        '{"finding_id":"sf-iter-2026-06-09-003","title":' + big + ',"evidence":{}}\n',
        encoding="utf-8",
    )
    resp = client.get("/api/finding/sf-iter-2026-06-09-003")
    assert resp.status_code == 200  # NOT 500 from the read-layer ValueError
    assert resp.json()["found"] is False  # un-parseable row dropped


def test_bigint_over_str_limit_does_not_poison_later_rows(tmp_path):
    """The dropped >limit-bigint row must not stop a later CLEAN row for the
    same finding_id from resolving (the malformed line is skipped, not fatal)."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    path = mem / "surfaced_findings.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    big = "1" + "0" * 6000
    path.write_text(
        '{"finding_id":"sf-iter-2026-06-09-003","title":' + big + ',"evidence":{}}\n'
        + json.dumps({"finding_id": "sf-iter-2026-06-09-003", "title": "CLEAN",
                      "evidence": {"ok": 1}}) + "\n",
        encoding="utf-8",
    )
    resp = client.get("/api/finding/sf-iter-2026-06-09-003")
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["title"] == "CLEAN"  # the clean row past the dropped one


def test_bigint_under_str_limit_field_degrades_not_500(tmp_path):
    """A bigint that PARSES (<=4300 digits) but is still huge surfaces to the
    encoder whose str() of it 500s. This is the ENCODE-layer guard (distinct
    from the read-layer drop above): degrade the one field to null, found:true."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    path = mem / "surfaced_findings.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    mid = "1" + "0" * 1000  # 1001 digits: parses, but encoder-pathological
    path.write_text(
        '{"finding_id":"sf-iter-2026-06-09-003","evidence":{"n":' + mid + '}}\n',
        encoding="utf-8",
    )
    resp = client.get("/api/finding/sf-iter-2026-06-09-003")
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["evidence"] is None  # encode-layer guard dropped the field


def test_normal_small_int_evidence_preserved(tmp_path):
    """The int magnitude guard must not over-fire on real values: ordinary ints
    (counts, metrics) surface intact."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    row = _finding_row()
    row["evidence"] = {"value": 4, "count": 1234567890, "neg": -42}
    _write_jsonl(mem / "surfaced_findings.jsonl", [row])
    resp = client.get("/api/finding/sf-iter-2026-06-09-003")
    assert resp.status_code == 200
    assert resp.json()["evidence"] == {"value": 4, "count": 1234567890, "neg": -42}


# ─── TARGET 2: malformed sources beyond the existing coverage ────────────


def test_finding_id_non_string_in_row_does_not_misjoin(tmp_path):
    """A row whose finding_id is an int/null/list must not equal the string path
    arg (123 != "123"); it simply never matches. A real string row past it still
    resolves — the non-dict-fid rows do not 500 or short-circuit the scan."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    _write_jsonl(mem / "surfaced_findings.jsonl", [
        {"finding_id": 123, "evidence": {"a": 1}},
        {"finding_id": None, "evidence": {"a": 1}},
        {"finding_id": ["sf-iter-2026-06-09-003"], "evidence": {"a": 1}},
        _finding_row(),  # the real string-keyed row
    ])
    # asking for the int row by its stringified value must NOT match
    assert client.get("/api/finding/123").json()["found"] is False
    # the real row still resolves past the non-string-fid rows
    resp = client.get("/api/finding/sf-iter-2026-06-09-003")
    assert resp.status_code == 200
    assert resp.json()["found"] is True


def test_duplicate_finding_ids_last_row_wins_deterministically(tmp_path):
    """Documented winner on a duplicated finding_id: the LAST row in file order
    (the code's ``row = candidate`` with no break). Deterministic, not arbitrary."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    a = _finding_row(); a["title"] = "FIRST"
    b = _finding_row(); b["title"] = "LAST"
    _write_jsonl(mem / "surfaced_findings.jsonl", [a, b])
    resp = client.get("/api/finding/sf-iter-2026-06-09-003")
    assert resp.status_code == 200
    assert resp.json()["title"] == "LAST"  # last-row-wins, documented & stable


def test_source_iteration_id_non_string_yields_null_join(tmp_path):
    """A non-string source_iteration_id is no usable join key => source_iteration
    null, found:true, and the raw non-string id is dropped from the surfaced
    field by the encoder guard path (here it is a small int, surfaced as-is)."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    row = _finding_row()
    row["source_iteration_id"] = 999  # not a string
    _write_jsonl(mem / "surfaced_findings.jsonl", [row])
    _write_jsonl(mem / "loop_memory.jsonl", [_iteration_row()])
    resp = client.get("/api/finding/sf-iter-2026-06-09-003")
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["source_iteration"] is None  # no usable id => no join


def test_seed_non_dict_topic_extraction_does_not_crash(tmp_path):
    """A loop_memory row whose seed is a bare scalar/string (not a dict) must not
    crash topic extraction (no .get on a str) — topic just resolves to null."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    _write_jsonl(mem / "surfaced_findings.jsonl", [_finding_row()])
    _write_jsonl(mem / "loop_memory.jsonl", [
        {"iteration_id": "iter-2026-06-09-003", "seed": "not-a-dict",
         "nara_summary": "still resolves"},
    ])
    resp = client.get("/api/finding/sf-iter-2026-06-09-003")
    assert resp.status_code == 200
    si = resp.json()["source_iteration"]
    assert si is not None
    assert si["topic"] is None  # seed non-dict => no topic, not a 500
    assert si["nara_summary"] == "still resolves"


def test_status_row_non_string_status_not_500(tmp_path):
    """A status-audit row whose ``status`` is a (shallow) non-string is surfaced
    un-coerced per the documented contract (status is NEVER coerced), and does
    not 500. (A pathologically-deep one is covered by the overlay-depth test.)"""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    _write_jsonl(mem / "surfaced_findings.jsonl", [_finding_row()])  # base: surfaced
    _write_jsonl(mem / "surfaced_findings.status.jsonl", [
        {"finding_id": "sf-iter-2026-06-09-003", "status": {"code": "in_review"}},
    ])
    resp = client.get("/api/finding/sf-iter-2026-06-09-003")
    assert resp.status_code == 200
    assert resp.json()["status"] == {"code": "in_review"}  # un-coerced, no 500


def test_status_row_finding_id_non_string_ignored(tmp_path):
    """A status-audit row whose finding_id is non-string must not match (the
    overlay's ``isinstance(fid, str)`` guard) — base status stands, no 500."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    _write_jsonl(mem / "surfaced_findings.jsonl", [_finding_row()])  # base: surfaced
    _write_jsonl(mem / "surfaced_findings.status.jsonl", [
        {"finding_id": 123, "status": "should_not_apply"},
        {"finding_id": None, "status": "should_not_apply"},
    ])
    resp = client.get("/api/finding/sf-iter-2026-06-09-003")
    assert resp.status_code == 200
    assert resp.json()["status"] == "surfaced"  # base status, overlay ignored


def test_truncated_last_line_dropped_not_500(tmp_path):
    """A truncated final JSON line (interrupted append) is un-parseable; drop it,
    do not 500, and still resolve a complete earlier row."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    path = mem / "surfaced_findings.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_finding_row()) + "\n"
        + '{"finding_id":"sf-trunc","ev',  # truncated, no closing/newline
        encoding="utf-8",
    )
    resp = client.get("/api/finding/sf-iter-2026-06-09-003")
    assert resp.status_code == 200
    assert resp.json()["found"] is True


def test_empty_file_returns_found_false_not_500(tmp_path):
    """A present-but-empty surfaced_findings.jsonl (zero rows) => found:false."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    path = mem / "surfaced_findings.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    resp = client.get("/api/finding/sf-iter-2026-06-09-003")
    assert resp.status_code == 200
    assert resp.json() == {"found": False, "finding_id": "sf-iter-2026-06-09-003"}


# ─── TARGET 3: pathological finding_id path arg ──────────────────────────


def test_long_and_unicode_finding_id_matches_nothing_not_500(tmp_path):
    """A long (within URL limits) unicode/control-ish id is not an error — it
    joins to no row (found:false), never 500, never traverses to another file.
    (Path-separator ``%2F`` is a routing artifact, excluded per the existing
    pathological-id test's rationale.)"""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    _write_jsonl(mem / "surfaced_findings.jsonl", [_finding_row()])
    weird = "-leading-dash_" + "λ" * 2000 + "_いろは_..%2e%2e_end"
    resp = client.get(f"/api/finding/{weird}")
    assert resp.status_code == 200
    assert resp.json()["found"] is False


def test_finding_id_dotdot_does_not_traverse(tmp_path):
    """A ``..``-laden id WITHIN ONE path segment is just a string compared against
    finding_id values; it cannot escape the join to read another path (the id is
    never used as a filesystem path in this endpoint — only string-equality).
    Matches nothing => found:false. (An encoded ``%2F`` would split the path into
    extra segments and 404 at the ROUTER before the endpoint — a routing
    artifact, not an endpoint behavior, so it is deliberately not asserted here;
    see test_pathological_finding_id_just_matches_nothing.)"""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    _write_jsonl(mem / "surfaced_findings.jsonl", [_finding_row()])
    # ``..`` chars EMBEDDED in a segment survive URL normalization and reach the
    # endpoint as an ordinary string (a bare ``..`` segment is collapsed by the
    # URL layer to the parent path and 404s at the router — a normalization
    # artifact, excluded). None of these escapes the join to read another path.
    for weird in ("%2e%2e", "..etc..passwd..", "....__..__", "..lead", "trail.."):
        resp = client.get(f"/api/finding/{weird}")
        assert resp.status_code == 200, f"{weird!r} -> {resp.status_code}"
        assert resp.json()["found"] is False


# ─── TARGET 4: file deleted between exists() and read (race) ─────────────


def test_file_deleted_mid_read_degrades_not_500(tmp_path, monkeypatch):
    """The real TOCTOU: the producer atomically unlinks/replaces these JSONL
    logs at cycle end, so a file can vanish AFTER _read_jsonl's exists() returns
    True but BEFORE/DURING open() -> FileNotFoundError. That must degrade to "no
    rows" (found:false at 200), NOT 500 (the coordinator.active idiom). Before
    the fix this 500'd ("unreadable: [Errno 2]"); this pins the degrade.

    Simulated faithfully: patch Path.exists to claim the file is present, but
    never create it, so the subsequent open() raises FileNotFoundError exactly
    as a delete-race would."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    target = mem / "surfaced_findings.jsonl"
    mem.mkdir(parents=True, exist_ok=True)
    # Deliberately do NOT create `target`; force exists() True for it only.
    real_exists = Path.exists

    def racing_exists(self):
        if str(self) == str(target):
            return True  # "present" at check time...
        return real_exists(self)

    monkeypatch.setattr(Path, "exists", racing_exists)
    resp = client.get("/api/finding/sf-iter-2026-06-09-003")
    assert resp.status_code == 200  # the delete-race degrades, never 500
    assert resp.json() == {"found": False,
                           "finding_id": "sf-iter-2026-06-09-003"}


def test_genuinely_unreadable_file_still_500s(tmp_path, monkeypatch):
    """The delete-race fix must NOT swallow a REAL unreadable-file fault: a
    non-FileNotFound OSError (e.g. a permission/I-O error) on a file that DOES
    exist still surfaces as the documented 500 — we degrade the benign race
    only, never mask a genuine server fault (no over-broad except)."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    _write_jsonl(mem / "surfaced_findings.jsonl", [_finding_row()])
    target = mem / "surfaced_findings.jsonl"
    import builtins
    real_open = builtins.open

    def denying_open(path, *args, **kwargs):
        if str(path) == str(target):
            raise PermissionError(13, "Permission denied", str(target))
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", denying_open)
    resp = client.get("/api/finding/sf-iter-2026-06-09-003")
    assert resp.status_code == 500  # a genuine fault is NOT degraded away
    assert "unreadable" in resp.json()["detail"]


# ─── TARGET 5: WRITES-NOTHING under EVERY adversarial input ──────────────


def test_writes_nothing_under_all_adversarial_inputs(tmp_path):
    """Snapshot (size+mtime_ns+bytes) the tmp memory dir before/after a battery
    of adversarial GETs; assert ZERO delta. Read-only is structural: the module
    opens no file for writing under ANY of these inputs (the tutor fence, rule
    4 / D-054)."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    path = mem / "surfaced_findings.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    big = "1" + "0" * 6000
    # one file carrying every pathology + a clean row, raw (literals needed)
    path.write_text(
        "GARBAGE {{{\n"
        "42\n"
        '"bare"\n'
        "[1,2,3]\n"
        "null\n"
        '{"finding_id":"nan","evidence":{"x":NaN}}\n'
        '{"finding_id":"inf","evidence":{"x":Infinity}}\n'
        '{"finding_id":"big","title":' + big + ',"evidence":{}}\n'
        + json.dumps({"finding_id": "deep", "evidence": _nest(_OVERFLOW_DEPTH)}) + "\n"
        + json.dumps(_finding_row()) + "\n",
        encoding="utf-8",
    )
    (mem / "loop_memory.jsonl").write_text(
        '{"iteration_id":"i","seed":NaN}\n'
        + json.dumps(_iteration_row()) + "\n",
        encoding="utf-8",
    )
    (mem / "surfaced_findings.status.jsonl").write_text(
        '{"finding_id":"nan","status":NaN}\n'
        + json.dumps({"finding_id": "sf-iter-2026-06-09-003", "status": "validated"}) + "\n",
        encoding="utf-8",
    )

    before = _snapshot(mem)
    # Single-segment ids only (an encoded %2F is a router-level 404, unrelated to
    # whether the endpoint writes); every one of these reaches the endpoint.
    for fid in ("nan", "inf", "big", "deep", "sf-iter-2026-06-09-003",
                "does-not-exist", "123", "..dotdot..", "-dash", "%2e%2e"):
        assert client.get(f"/api/finding/{fid}").status_code == 200
    after = _snapshot(mem)
    assert after == before  # byte-for-byte, mtime-for-mtime: zero writes


def test_module_has_no_write_primitives():
    """Structural proof of read-only: the module's source contains no write-mode
    open / write_* / json.dump-to-file / rename / mkdir / replace. The single
    open() is read-mode (no mode arg). Guards against a future edit silently
    adding a write to a read-only endpoint (rule 4 / D-054)."""
    import re
    src = Path(__file__).resolve().parent.parent.joinpath("finding_detail.py").read_text(
        encoding="utf-8")
    # Strip comments and string/docstring literals so a benign mention of the
    # word "open()" in prose (e.g. the delete-race comment) is not mistaken for a
    # call; what remains is code only. Crude but sufficient: drop ``# ...`` tails
    # and triple-quoted blocks.
    code = re.sub(r"\"\"\".*?\"\"\"", "", src, flags=re.DOTALL)
    code = re.sub(r"#.*", "", code)
    # No write-mode open(): open(..., 'w'|'a'|'x'|'+', ...)
    assert not re.search(r"open\([^)]*['\"][rwxab+]*[wax+][rwxab+]*['\"]", code), \
        "write-mode open() found in a read-only endpoint"
    # No Path.write_*/write to file, json.dump (to file), os.replace/rename, mkdir, touch.
    for forbidden in (".write_text", ".write_bytes", "json.dump(", "os.replace",
                      "os.rename", ".rename(", ".mkdir(", ".touch(", "shutil."):
        assert forbidden not in code, f"write primitive {forbidden!r} found in read-only module"
    # The actual open() CALL in code is read-mode (no write-flag mode arg). There
    # is exactly one open( call site, and it carries no mode argument at all.
    open_calls = re.findall(r"open\([^)]*\)", code)
    assert len(open_calls) == 1, f"expected one open() call site, found {open_calls!r}"
    assert "encoding=" in open_calls[0] and not re.search(
        r"['\"][rwxab+]*[wax+]", open_calls[0]), \
        f"the open() call must be read-mode, got {open_calls[0]!r}"
