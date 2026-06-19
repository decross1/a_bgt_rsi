"""Iteration-journey endpoint tests — the read-only S2 cockpit data layer (BE2).

Side-effect-free: every path points at tmp_path, no real run_state/memory
writes. Mirrors test_finding_detail.py / test_coordinator.py (TestClient against
the coordinator_memory create_app param, which is the memory dir the
iteration-journey router reads). ``raise_server_exceptions=False`` so a regressed
endpoint surfaces as an observed 500 (the thing we guard) instead of bubbling the
exception out of the test client.

Covers: the happy-path full-row return (every journey field surfaced intact);
unknown iteration_id => 200 found:false; absent file => 200 found:false (never
500); malformed/non-dict rows dropped; a pathological / over-long / traversal-ish
iteration_id => 200 found:false (never traverses); deeply-nested / non-finite /
bigint fields degrade (found:false at 200, never 500); and a WRITES-NOTHING
snapshot delta of the tmp memory dir across a GET (the read-only fence at the
data layer).
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.iteration_journey import register as register_iteration_journey


def _client(tmp_path) -> TestClient:
    """TestClient with every path pinned at tmp_path (the test_finding_detail
    idiom). The journey router reads from the coordinator_memory dir
    (``coord_memory``), wired by the integrator as
    ``register(app, memory_dir=Path(coordinator_memory))``. The dir is
    intentionally NOT pre-created — the absent-file case relies on it being
    missing, and _read_jsonl tolerates that. Tests that need a file mkdir its
    parent themselves. ``raise_server_exceptions=False`` lets a regression be
    asserted as a 500 response rather than raised out of the client.
    """
    (tmp_path / "logs").mkdir(exist_ok=True)
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"current_day": "iteration_journey"}), encoding="utf-8")
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
    # Wire the journey router onto the test app exactly as the integrator wires
    # it in app.py: register(app, memory_dir=Path(coordinator_memory)). This
    # keeps the test self-contained (and green pre-integration) without the build
    # agent touching app.py.
    register_iteration_journey(app, memory_dir=coord_memory)
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


_IID = "iter-2026-06-09-003"


def _journey_row() -> dict:
    """A FULL loop_memory row exercising every journey block the IterationRecord
    contract models (schemas.ts ~250-395): hypothesis, retrieval.relevance,
    novelty, critique.contradicting_paper_id, redteam, meta_review, gate_status,
    experiment_outcome."""
    return {
        "iteration_id": _IID,
        "started_at": "2026-06-09T13:00:00Z",
        "ended_at": "2026-06-09T13:18:00Z",
        "seed": {"topic": "Level-k convergence in repeated auctions",
                 "source": "coordinator"},
        "hypothesis": {"text": "Level-k beliefs converge faster than the bound.",
                       "candidates_considered": 3},
        "retrieval": {
            "k": 8,
            "neighbors": [{"paper_id": "p1"}, {"paper_id": "p2"}],
            "relevance": {
                "relevance": 0.72,
                "low_confidence": False,
                "reason": "two sharp on-domain neighbors",
                "anchor_cosine": 0.51,
                "topicality": "on",
                "category": "ok",
                "rule_fired": None,
            },
        },
        "novelty": {
            "class": "novel",
            "rationale": "no prior paper states the faster-convergence step",
            "top_neighbor_id": "p1",
            "low_confidence": False,
        },
        "critique": {
            "verdict": "survives",
            "rationale": "retrieval grounded the claim",
            "contradicting_paper_id": "p7",
            "low_confidence": False,
        },
        "redteam": {"verdict": "proceed", "critique": "no fatal flaw",
                    "retries_used": 1},
        "meta_review": {"conditioning_bullets": ["prior iter saw a slower step"],
                        "rows_considered": 5},
        "gate_status": "pending",
        "experiment_outcome": {
            "experiment_id": "exp-level-k-003",
            "metric": "steps_to_converge",
            "value": 4,
            "trials": 20,
            "summary": "Verdict=YES. Converges a step early.",
            "results_path": "run_state/exp/level_k_003.json",
        },
        "journal_entry_path": "journal/iterations/003.md",
        "nara_summary": "Hypothesized a faster convergence; critic let it stand.",
        "model_version": "gemma-4-26b-a4b-nvfp4",
    }


# ─── happy path: the full journey row is returned ────────────────────────


def test_happy_path_returns_full_journey_row(tmp_path):
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    _write_jsonl(mem / "loop_memory.jsonl", [_journey_row()])

    resp = client.get(f"/api/iteration/{_IID}/journey")
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["iteration_id"] == _IID
    it = body["iteration"]
    assert it is not None
    # the WHOLE row is returned, byte-intact (never coerced) — every journey block.
    assert it == _journey_row()
    # spot-check the contract fields the journey view reads:
    assert it["hypothesis"]["text"].startswith("Level-k beliefs")
    assert it["retrieval"]["relevance"]["topicality"] == "on"
    assert it["novelty"]["class"] == "novel"
    assert it["critique"]["contradicting_paper_id"] == "p7"
    assert it["redteam"]["verdict"] == "proceed"
    assert it["meta_review"]["rows_considered"] == 5
    assert it["gate_status"] == "pending"
    assert it["experiment_outcome"]["metric"] == "steps_to_converge"


def test_target_row_selected_among_many(tmp_path):
    """The endpoint returns the row whose iteration_id matches the path arg, not
    just the first/last row of the file."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    other = _journey_row()
    other["iteration_id"] = "iter-2026-06-09-001"
    other["nara_summary"] = "a different iteration"
    _write_jsonl(mem / "loop_memory.jsonl", [other, _journey_row()])
    resp = client.get(f"/api/iteration/{_IID}/journey")
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["iteration"]["iteration_id"] == _IID
    assert body["iteration"]["nara_summary"].startswith("Hypothesized")


def test_duplicate_iteration_ids_last_row_wins(tmp_path):
    """Documented winner on a duplicated iteration_id: the LAST row in file order
    (``row = candidate`` with no break). Deterministic, not arbitrary."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    a = _journey_row(); a["nara_summary"] = "FIRST"
    b = _journey_row(); b["nara_summary"] = "LAST"
    _write_jsonl(mem / "loop_memory.jsonl", [a, b])
    resp = client.get(f"/api/iteration/{_IID}/journey")
    assert resp.status_code == 200
    assert resp.json()["iteration"]["nara_summary"] == "LAST"


# ─── unknown id => 200 found:false (NOT 404) ─────────────────────────────


def test_unknown_iteration_id_returns_200_found_false(tmp_path):
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    _write_jsonl(mem / "loop_memory.jsonl", [_journey_row()])
    resp = client.get("/api/iteration/iter-2026-01-01-999/journey")
    assert resp.status_code == 200  # the journey view degrades in place, never 404
    body = resp.json()
    assert body == {"found": False, "iteration_id": "iter-2026-01-01-999"}


def test_empty_file_returns_found_false_not_500(tmp_path):
    """A present-but-empty loop_memory.jsonl (zero rows) => found:false."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    path = mem / "loop_memory.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    resp = client.get(f"/api/iteration/{_IID}/journey")
    assert resp.status_code == 200
    assert resp.json() == {"found": False, "iteration_id": _IID}


# ─── absent file => 200 found:false, never 500 ───────────────────────────


def test_absent_file_returns_200_found_false_not_500(tmp_path):
    client = _client(tmp_path)
    # No coord_memory dir / files created at all.
    assert not _memory_dir(tmp_path).exists()
    resp = client.get(f"/api/iteration/{_IID}/journey")
    assert resp.status_code == 200
    assert resp.json() == {"found": False, "iteration_id": _IID}


# ─── malformed / non-dict rows dropped, no 500 ───────────────────────────


def test_malformed_and_non_dict_rows_dropped(tmp_path):
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    path = mem / "loop_memory.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    # Garbage + non-dict JSON bracketing the one real dict row.
    path.write_text(
        "THIS IS NOT JSON {{{\n"
        "42\n"
        '"a bare string"\n'
        "[1, 2, 3]\n"
        "null\n"
        + json.dumps(_journey_row()) + "\n",
        encoding="utf-8",
    )
    resp = client.get(f"/api/iteration/{_IID}/journey")
    assert resp.status_code == 200  # never 500 from a stray line
    body = resp.json()
    assert body["found"] is True
    assert body["iteration"]["iteration_id"] == _IID


def test_truncated_last_line_dropped_not_500(tmp_path):
    """A truncated final JSON line (interrupted append) is un-parseable; drop it,
    do not 500, and still resolve a complete earlier row."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    path = mem / "loop_memory.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_journey_row()) + "\n"
        + '{"iteration_id":"iter-2026-06-09-004","nara_su',  # truncated
        encoding="utf-8",
    )
    resp = client.get(f"/api/iteration/{_IID}/journey")
    assert resp.status_code == 200
    assert resp.json()["found"] is True


def test_iteration_id_non_string_in_row_does_not_misjoin(tmp_path):
    """A row whose iteration_id is an int/null/list must not equal the string path
    arg; it simply never matches. A real string row past it still resolves."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    _write_jsonl(mem / "loop_memory.jsonl", [
        {"iteration_id": 123, "nara_summary": "x"},
        {"iteration_id": None, "nara_summary": "x"},
        {"iteration_id": [_IID], "nara_summary": "x"},
        _journey_row(),
    ])
    resp = client.get(f"/api/iteration/{_IID}/journey")
    assert resp.status_code == 200
    assert resp.json()["found"] is True


# ─── pathological / over-long / traversal-ish id => found:false, no traverse ─


def test_unknown_id_with_valid_shape_matches_nothing(tmp_path):
    """A well-formed id that simply names no row => found:false (not 404)."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    _write_jsonl(mem / "loop_memory.jsonl", [_journey_row()])
    resp = client.get("/api/iteration/iter-2026-06-09-999/journey")
    assert resp.status_code == 200
    assert resp.json()["found"] is False


def test_over_long_id_returns_found_false_not_500(tmp_path):
    """An id longer than the 64-char guard bound is refused by the shape guard =>
    found:false, never 500, never used as a path."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    _write_jsonl(mem / "loop_memory.jsonl", [_journey_row()])
    long_id = "iter-2026-06-09-" + "9" * 200
    resp = client.get(f"/api/iteration/{long_id}/journey")
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False
    assert body["iteration_id"] == long_id


def test_traversal_ish_id_does_not_traverse(tmp_path):
    """A ``..``/separator-ish id WITHIN ONE path segment is refused by the shape
    guard (those chars are outside the allow-set) => found:false. The id is never
    used as a filesystem path here (only string-equality against iteration_id),
    so it cannot escape the join to read another file. (An encoded ``%2F`` would
    split the path into extra segments and 404 at the ROUTER before the endpoint
    — a routing artifact, not an endpoint behavior, so it is not asserted here.)
    """
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    _write_jsonl(mem / "loop_memory.jsonl", [_journey_row()])
    # Each carries a char outside the [A-Za-z0-9-_] allow-set => refused. All
    # stay WITHIN ONE path segment — a literal ``/`` (or encoded ``%2F``) would
    # split the route into extra segments and 404 at the ROUTER before the
    # endpoint (a routing artifact, not endpoint behavior), so it is excluded.
    for weird in ("..etc..passwd..", "iter-..-..-001", "iter 2026 06 09",
                  "..%2e%2e", "'; DROP TABLE--", "iter.2026.06.09"):
        resp = client.get(f"/api/iteration/{weird}/journey")
        assert resp.status_code == 200, f"{weird!r} -> {resp.status_code}"
        assert resp.json()["found"] is False


def test_unicode_id_matches_nothing_not_500(tmp_path):
    """A unicode id is outside the ASCII allow-set => refused, found:false, no 500."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    _write_jsonl(mem / "loop_memory.jsonl", [_journey_row()])
    weird = "iter-λ-いろは-001"
    resp = client.get(f"/api/iteration/{weird}/journey")
    assert resp.status_code == 200
    assert resp.json()["found"] is False


# ═════════════════════════════════════════════════════════════════════════
# RESPONSE-ENCODER OVERFLOW: deep nesting / non-finite floats / huge bigints.
# A surfaced row member that is deeply-NESTED, a >digit-limit bigint, or a
# non-finite float is valid JSON, survives the read, but 500s FastAPI's
# JSONResponse encoder AFTER the read's try/except — exactly the class
# finding_detail.py / todo_cockpit.py guard with the depth/int/finite guard.
# The whole row is surfaced as the IterationRecord, so a single pathological
# member would 500 the WHOLE response; the fix degrades the whole row to
# found:false (or drops the un-parseable line), never 500.
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


def test_deeply_nested_member_degrades_not_500(tmp_path):
    """A thousands-deep value in a surfaced member (here nara_summary) reaches the
    encoder and formerly RecursionError-500'd. The whole row degrades to
    found:false at 200, never 500."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    row = _journey_row()
    row["nara_summary"] = _nest(_OVERFLOW_DEPTH)
    _write_jsonl(mem / "loop_memory.jsonl", [row])
    resp = client.get(f"/api/iteration/{_IID}/journey")
    assert resp.status_code == 200  # NOT 500
    assert resp.json() == {"found": False, "iteration_id": _IID}


def test_nan_float_member_degrades_not_500(tmp_path):
    """A NaN literal is valid to Python's json parser but the encoder emits the
    non-compliant token `NaN` and 500s. Degrade the row to found:false."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    path = mem / "loop_memory.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"iteration_id":"' + _IID + '","hypothesis":{"confidence":NaN}}\n',
        encoding="utf-8",
    )
    resp = client.get(f"/api/iteration/{_IID}/journey")
    assert resp.status_code == 200
    assert resp.json() == {"found": False, "iteration_id": _IID}


def test_infinity_float_member_degrades_not_500(tmp_path):
    """Infinity / -Infinity literals likewise 500 the encoder — degrade."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    path = mem / "loop_memory.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"iteration_id":"' + _IID + '","retrieval":{"relevance":{"relevance":Infinity}}}\n',
        encoding="utf-8",
    )
    resp = client.get(f"/api/iteration/{_IID}/journey")
    assert resp.status_code == 200
    assert resp.json()["found"] is False


def test_bigint_over_str_limit_row_dropped_not_500(tmp_path):
    """A numeric literal over CPython's int<->str digit limit (>4300 digits) makes
    json.loads ITSELF raise a bare ValueError (NOT a JSONDecodeError) — formerly
    an uncaught 500 at the READ layer. The row is dropped as malformed =>
    found:false."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    path = mem / "loop_memory.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    big = "1" + "0" * 6000  # 6001-digit integer literal
    path.write_text(
        '{"iteration_id":"' + _IID + '","seed_value":' + big + '}\n',
        encoding="utf-8",
    )
    resp = client.get(f"/api/iteration/{_IID}/journey")
    assert resp.status_code == 200  # NOT 500 from the read-layer ValueError
    assert resp.json()["found"] is False  # un-parseable row dropped


def test_bigint_over_str_limit_does_not_poison_later_rows(tmp_path):
    """The dropped >limit-bigint row must not stop a later CLEAN row for the same
    iteration_id from resolving (the malformed line is skipped, not fatal)."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    path = mem / "loop_memory.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    big = "1" + "0" * 6000
    path.write_text(
        '{"iteration_id":"' + _IID + '","seed_value":' + big + '}\n'
        + json.dumps(_journey_row()) + "\n",
        encoding="utf-8",
    )
    resp = client.get(f"/api/iteration/{_IID}/journey")
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True  # the clean row past the dropped one
    assert body["iteration"]["nara_summary"].startswith("Hypothesized")


def test_bigint_under_str_limit_member_degrades_not_500(tmp_path):
    """A bigint that PARSES (<=4300 digits) but is still huge surfaces to the
    encoder whose str() of it 500s. This is the ENCODE-layer guard (distinct from
    the read-layer drop above): degrade the row to found:false at 200."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    path = mem / "loop_memory.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    mid = "1" + "0" * 1000  # 1001 digits: parses, but encoder-pathological
    path.write_text(
        '{"iteration_id":"' + _IID + '","seed_value":' + mid + '}\n',
        encoding="utf-8",
    )
    resp = client.get(f"/api/iteration/{_IID}/journey")
    assert resp.status_code == 200
    assert resp.json() == {"found": False, "iteration_id": _IID}


def test_lone_surrogate_string_member_degrades_not_500(tmp_path):
    """A producer-written ``"\\udXXX"`` escape decodes through json.loads into a
    LONE (unpaired) surrogate str — valid to PARSE, but FastAPI's JSONResponse
    emits UTF-8 and a lone surrogate is NOT encodable, so the encoder raises
    UnicodeEncodeError AFTER the read's try/except (the same valid-to-parse /
    fatal-to-encode class as NaN/Infinity, but on a STRING the depth/int/float
    guard never inspected). The whole row must degrade to found:false at 200, NOT
    500. The line is written as raw bytes because the 6-char ASCII escape is how a
    producer's file actually carries it (a real lone surrogate cannot itself be
    UTF-8-written)."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    path = mem / "loop_memory.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b'{"iteration_id":"' + _IID.encode() + b'","nara_summary":"\\ud800"}\n'
    )
    resp = client.get(f"/api/iteration/{_IID}/journey")
    assert resp.status_code == 200  # NOT 500 from the encoder's UTF-8 emit
    assert resp.json() == {"found": False, "iteration_id": _IID}


def test_embedded_and_nested_surrogate_members_degrade_not_500(tmp_path):
    """A surrogate need not be a whole field: one EMBEDDED amid valid text, and
    one buried in a NESTED block (the iterative walk must reach it), each 500 the
    encoder the same way. Both degrade to found:false."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    path = mem / "loop_memory.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)

    # embedded: "ok<surrogate>bad" — valid text bracketing the bad code point
    path.write_bytes(
        b'{"iteration_id":"' + _IID.encode() + b'","nara_summary":"ok\\ud834bad"}\n'
    )
    resp = client.get(f"/api/iteration/{_IID}/journey")
    assert resp.status_code == 200
    assert resp.json()["found"] is False

    # nested two blocks + a list deep — the encoder still walks to it, so the
    # guard must too (proves the walk is not shallow).
    path.write_bytes(
        b'{"iteration_id":"' + _IID.encode()
        + b'","retrieval":{"neighbors":[{"note":"\\udc00"}]}}\n'
    )
    resp = client.get(f"/api/iteration/{_IID}/journey")
    assert resp.status_code == 200
    assert resp.json()["found"] is False


def test_surrogate_in_dict_key_degrades_not_500(tmp_path):
    """The surrogate rides a dict KEY, not a value. json.loads keys are always
    str; the encoder UTF-8-emits the key and 500s the same way. The guard must
    inspect keys (not just values) — degrade to found:false, never 500."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    path = mem / "loop_memory.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b'{"iteration_id":"' + _IID.encode() + b'","meta_review":{"\\ud800":"v"}}\n'
    )
    resp = client.get(f"/api/iteration/{_IID}/journey")
    assert resp.status_code == 200
    assert resp.json() == {"found": False, "iteration_id": _IID}


def test_legitimate_unicode_preserved_not_over_dropped(tmp_path):
    """The surrogate guard must NOT over-fire: legitimate non-ASCII — CJK, Greek,
    and an ASTRAL-plane emoji (a single code point that is UTF-16 surrogate-PAIRED
    but UTF-8-encodable) — surfaces BYTE-INTACT, in both a value AND a dict key
    (the guard rejects ONLY un-encodable lone surrogates, never coerces valid
    unicode)."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    row = _journey_row()
    row["nara_summary"] = "λ いろは 😀 convergence"
    row["meta_review"] = {"いろは😀": "ok", "rows_considered": 5}
    _write_jsonl(mem / "loop_memory.jsonl", [row])
    resp = client.get(f"/api/iteration/{_IID}/journey")
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["iteration"]["nara_summary"] == "λ いろは 😀 convergence"
    assert body["iteration"]["meta_review"]["いろは😀"] == "ok"


def test_normal_small_int_and_shallow_nest_preserved(tmp_path):
    """The encoder guard must not over-fire: ordinary ints/counts and a normal
    small nested block surface BYTE-INTACT (the guard drops only the pathological,
    never coerces a valid value)."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    row = _journey_row()
    row["seed_value"] = 1234567890
    row["meta_review"] = {"conditioning_bullets": ["a", "b"], "rows_considered": 42,
                          "nested": {"a": {"b": {"c": 1}}}}
    _write_jsonl(mem / "loop_memory.jsonl", [row])
    resp = client.get(f"/api/iteration/{_IID}/journey")
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["iteration"]["seed_value"] == 1234567890
    assert body["iteration"]["meta_review"]["nested"] == {"a": {"b": {"c": 1}}}


# ─── file deleted between exists() and read (race) ───────────────────────


def test_file_deleted_mid_read_degrades_not_500(tmp_path, monkeypatch):
    """The real TOCTOU: the producer atomically unlinks/replaces these JSONL logs
    at cycle end, so a file can vanish AFTER _read_jsonl's exists() returns True
    but BEFORE/DURING open() -> FileNotFoundError. That must degrade to "no rows"
    (found:false at 200), NOT 500."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    target = mem / "loop_memory.jsonl"
    mem.mkdir(parents=True, exist_ok=True)
    # Deliberately do NOT create `target`; force exists() True for it only.
    real_exists = Path.exists

    def racing_exists(self):
        if str(self) == str(target):
            return True  # "present" at check time...
        return real_exists(self)

    monkeypatch.setattr(Path, "exists", racing_exists)
    resp = client.get(f"/api/iteration/{_IID}/journey")
    assert resp.status_code == 200  # the delete-race degrades, never 500
    assert resp.json() == {"found": False, "iteration_id": _IID}


def test_genuinely_unreadable_file_still_500s(tmp_path, monkeypatch):
    """The delete-race fix must NOT swallow a REAL unreadable-file fault: a
    non-FileNotFound OSError (e.g. a permission/I-O error) on a file that DOES
    exist still surfaces as the documented 500 — we degrade the benign race only,
    never mask a genuine server fault (no over-broad except)."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    _write_jsonl(mem / "loop_memory.jsonl", [_journey_row()])
    target = mem / "loop_memory.jsonl"
    import builtins
    real_open = builtins.open

    def denying_open(path, *args, **kwargs):
        if str(path) == str(target):
            raise PermissionError(13, "Permission denied", str(target))
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", denying_open)
    resp = client.get(f"/api/iteration/{_IID}/journey")
    assert resp.status_code == 500  # a genuine fault is NOT degraded away
    assert "unreadable" in resp.json()["detail"]


# ─── WRITES-NOTHING: the read-only fence at the data layer ───────────────


def test_get_writes_nothing_zero_delta(tmp_path):
    """Snapshot the tmp memory dir (file set + sizes + mtimes + bytes) before and
    after a battery of GETs; assert ZERO delta. The read-only endpoint opens no
    file for writing — never fakes a write (inviolate rule 4)."""
    client = _client(tmp_path)
    mem = _memory_dir(tmp_path)
    path = mem / "loop_memory.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    big = "1" + "0" * 6000
    # one file carrying every pathology + a clean row, raw bytes (literals needed,
    # plus the lone-surrogate escape ``\ud800`` which is not UTF-8-writable text).
    path.write_bytes(
        b"GARBAGE {{{\n"
        b"42\n"
        b'"bare"\n'
        b"[1,2,3]\n"
        b"null\n"
        b'{"iteration_id":"iter-2026-06-09-007","hypothesis":{"confidence":NaN}}\n'
        + b'{"iteration_id":"iter-2026-06-09-008","seed_value":' + big.encode() + b'}\n'
        + b'{"iteration_id":"iter-2026-06-09-010","nara_summary":"\\ud800"}\n'
        + json.dumps({"iteration_id": "iter-2026-06-09-009",
                      "nara_summary": _nest(_OVERFLOW_DEPTH)}).encode() + b"\n"
        + json.dumps(_journey_row()).encode() + b"\n"
    )

    before = _snapshot(mem)
    # Found, not-found, refused-shape, and pathological ids — none may write.
    # Single-segment ids only (a literal/encoded ``/`` is a router-level 404,
    # unrelated to whether the endpoint writes); every one of these reaches it.
    for iid in (_IID, "iter-2026-06-09-007", "iter-2026-06-09-008",
                "iter-2026-06-09-009", "iter-2026-06-09-010", "iter-2026-06-09-999",
                "iter-2026-06-09-" + "9" * 200, "..etc..", "iter.2026.06.09"):
        assert client.get(f"/api/iteration/{iid}/journey").status_code == 200
    after = _snapshot(mem)

    assert after == before  # byte-for-byte, mtime-for-mtime: zero writes


def test_module_has_no_write_primitives():
    """Structural proof of read-only: the module's source contains no write-mode
    open / write_* / json.dump-to-file / rename / mkdir / replace. The single
    open() is read-mode (no mode arg). Guards against a future edit silently
    adding a write to a read-only endpoint (rule 4)."""
    import re
    src = Path(__file__).resolve().parent.parent.joinpath(
        "iteration_journey.py").read_text(encoding="utf-8")
    # Strip triple-quoted blocks and ``# ...`` tails so a benign mention of the
    # word "open()" in prose is not mistaken for a call; what remains is code.
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
