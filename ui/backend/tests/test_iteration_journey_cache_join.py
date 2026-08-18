"""Iteration-cache join tests — the 2026-08-18 dossier-gap enrichment.

The journey endpoint fills TWO blocks from ``run_state/iteration_cache/<id>/``
when the loop_memory row lacks them: neighbor ``chunk_text`` (retrieval.json,
joined by doc_id) and ``critique.debate`` (critique.json). Side-effect-free:
every path points at tmp_path — no real run_state/memory reads or writes.
Mirrors test_iteration_journey.py's _client idiom, but exercises the join the
way app.py actually wires it: through ``create_app(coordinator_run_state=…)``
(create_app registers the route itself with
``iteration_cache_dir=coordinator_run_state / "iteration_cache"``; a second
test-local register would be shadowed by the first-registered route).

Covers: the happy fill-join (text per doc_id + the debate transcript intact);
fill-only semantics (rows already carrying text/debate are byte-identical, a
malformed cache cannot clobber them); no cache dir / no cache file => the row
serves un-enriched at 200 (never 500, never found:false); malformed / non-dict
/ over-cap cache files => enrichment skipped; a doc_id absent from the cache
keeps its honest no-text state; NO fabricated critique block; a pathological
(encoder-unsafe) cache value falls back to the clean un-enriched row; and the
WRITES-NOTHING snapshot across a GET (cache dir included).
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app


def _client(tmp_path) -> TestClient:
    """TestClient with every path pinned at tmp_path (the test_iteration_journey
    idiom). The journey route is the one create_app registers — with
    iteration_cache_dir = coord_run_state / "iteration_cache" — so these tests
    exercise the production wiring, not a test-local re-register."""
    (tmp_path / "logs").mkdir(exist_ok=True)
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"current_day": "cache_join"}), encoding="utf-8")
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
    return TestClient(app, raise_server_exceptions=False)


def _memory_dir(tmp_path) -> Path:
    return tmp_path / "coord_memory"


def _cache_dir(tmp_path, iteration_id: str) -> Path:
    d = tmp_path / "coord_run_state" / "iteration_cache" / iteration_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _snapshot(root: Path) -> dict[str, tuple]:
    """(path -> (size, mtime_ns, bytes)) for every file under root — detects
    ANY write (new file, truncate, rewrite, touch)."""
    snap: dict[str, tuple] = {}
    if not root.exists():
        return snap
    for p in sorted(root.rglob("*")):
        if p.is_file():
            st = p.stat()
            snap[str(p)] = (st.st_size, st.st_mtime_ns, p.read_bytes())
    return snap


_IID = "iter-2026-08-18-005"

_TEXT_A = "Cooperation among LLM agents varies with context augmentation " * 8
_TEXT_B = "A second cached chunk, short and sharp."

# The 6-turn challenger⇄defender debate the real iter-2026-08-18-005 carries
# (survives_debate / challenger_conceded) — turns keyed `text`, the producer key.
_DEBATE = {
    "verdict": "survives_debate",
    "rounds": 4,
    "stop_reason": "challenger_conceded",
    "transcript": [
        {"round": 1, "role": "challenger", "backend": "vllm-qwen",
         "model": "qwen3.6-27b-nvfp4-mtp", "text": "OBJECT: the claim overreaches.",
         "wall_seconds": 154.3},
        {"round": 1, "role": "defender", "backend": "vllm-gemma",
         "model": "gemma-4-26b-a4b", "text": "DEFEND: bounded to the cited setting.",
         "wall_seconds": 88.1},
        {"round": 2, "role": "challenger", "backend": "vllm-qwen",
         "model": "qwen3.6-27b-nvfp4-mtp", "text": "OBJECT: cite 7 contradicts.",
         "wall_seconds": 120.0},
        {"round": 2, "role": "defender", "backend": "vllm-gemma",
         "model": "gemma-4-26b-a4b", "text": "DEFEND: cite 7 is off-population.",
         "wall_seconds": 91.4},
        {"round": 3, "role": "challenger", "backend": "vllm-qwen",
         "model": "qwen3.6-27b-nvfp4-mtp", "text": "PROBE: strongest remaining doubt.",
         "wall_seconds": 60.2},
        {"round": 3, "role": "defender", "backend": "vllm-gemma",
         "model": "gemma-4-26b-a4b", "text": "DEFEND: doubt already priced in.",
         "wall_seconds": 45.9},
    ],
}


def _bare_row(iteration_id: str = _IID) -> dict:
    """A loop_memory row WITHOUT chunk_text and WITHOUT debate — the older-row
    shape the join exists for. Neighbors carry doc_id/score only."""
    return {
        "iteration_id": iteration_id,
        "started_at": "2026-08-18T09:00:00Z",
        "ended_at": "2026-08-18T09:30:00Z",
        "seed": {"topic": "context length vs cooperation", "source": "coordinator"},
        "hypothesis": {"text": "Longer context raises cooperation monotonically."},
        "retrieval": {
            "k": 2,
            "neighbors": [
                {"doc_id": "s2:aaa", "score": 0.70},
                {"doc_id": "s2:bbb", "score": 0.61},
            ],
            "relevance": {"relevance": 0.7, "low_confidence": False},
        },
        "critique": {
            "verdict": "survives",
            "rationale": "no contradiction surfaced",
            "skeptic_verdict": "survives_debate",
        },
        "gate_status": "pending",
    }


def _cache_retrieval(texts: dict[str, str]) -> dict:
    return {
        "status": "ok",
        "result": {
            "k": len(texts),
            "neighbors": [
                {"doc_id": doc, "content_hash": f"sha256:{i}", "score": 0.7,
                 "chunk_text": text}
                for i, (doc, text) in enumerate(texts.items())
            ],
            "latency_ms": 120,
            "escalation": None,
            "relevance": {"relevance": 0.7},
        },
        "errors": [],
    }


def _cache_critique(debate: dict | None = None) -> dict:
    result: dict = {
        "verdict": "survives",
        "rationale": "no contradiction surfaced",
        "skeptic_verdict": "survives_debate",
        "skeptic_backend": "vllm-qwen",
        "skeptic_model": "qwen3.6-27b-nvfp4-mtp",
        "skeptic_wall_seconds": 512.0,
    }
    if debate is not None:
        result["debate"] = debate
    return {"status": "ok", "result": result, "errors": []}


# ─── the happy fill-join ─────────────────────────────────────────────────


def test_join_fills_chunk_text_and_debate(tmp_path):
    client = _client(tmp_path)
    _write_jsonl(_memory_dir(tmp_path) / "loop_memory.jsonl", [_bare_row()])
    cache = _cache_dir(tmp_path, _IID)
    (cache / "retrieval.json").write_text(
        json.dumps(_cache_retrieval({"s2:aaa": _TEXT_A, "s2:bbb": _TEXT_B})),
        encoding="utf-8",
    )
    (cache / "critique.json").write_text(
        json.dumps(_cache_critique(_DEBATE)), encoding="utf-8"
    )

    body = client.get(f"/api/iteration/{_IID}/journey").json()
    assert body["found"] is True
    it = body["iteration"]
    ns = it["retrieval"]["neighbors"]
    # each neighbor got its OWN cached text, joined by doc_id
    assert ns[0]["chunk_text"] == _TEXT_A
    assert ns[1]["chunk_text"] == _TEXT_B
    # non-text neighbor fields untouched
    assert ns[0]["doc_id"] == "s2:aaa" and ns[0]["score"] == 0.70
    # the debate landed on the EXISTING critique block, transcript intact
    debate = it["critique"]["debate"]
    assert debate["verdict"] == "survives_debate"
    assert debate["rounds"] == 4
    assert debate["stop_reason"] == "challenger_conceded"
    assert len(debate["transcript"]) == 6
    assert debate["transcript"][0]["role"] == "challenger"
    assert debate["transcript"][0]["backend"] == "vllm-qwen"
    assert debate["transcript"][0]["text"] == "OBJECT: the claim overreaches."
    # …and the rest of the critique block survived the copy-on-write
    assert it["critique"]["verdict"] == "survives"
    assert it["critique"]["skeptic_verdict"] == "survives_debate"


def test_doc_id_absent_from_cache_stays_honestly_textless(tmp_path):
    """Only the neighbors the cache actually covers get text; the rest keep
    their honest no-text state (the frontend fallback line remains earned)."""
    client = _client(tmp_path)
    _write_jsonl(_memory_dir(tmp_path) / "loop_memory.jsonl", [_bare_row()])
    cache = _cache_dir(tmp_path, _IID)
    (cache / "retrieval.json").write_text(
        json.dumps(_cache_retrieval({"s2:aaa": _TEXT_A})), encoding="utf-8"
    )

    body = client.get(f"/api/iteration/{_IID}/journey").json()
    ns = body["iteration"]["retrieval"]["neighbors"]
    assert ns[0]["chunk_text"] == _TEXT_A
    assert "chunk_text" not in ns[1]


# ─── fill-only: never clobber, never fabricate ───────────────────────────


def test_row_already_carrying_text_and_debate_is_untouched(tmp_path):
    """A modern row (chunk_text + debate already in loop_memory) is served
    byte-identical — even when the cache files are present AND malformed, the
    fill-only join never reads past what it needs, never clobbers."""
    client = _client(tmp_path)
    row = _bare_row()
    row["retrieval"]["neighbors"] = [
        {"doc_id": "s2:aaa", "score": 0.70, "chunk_text": "the loop_memory text"},
        {"doc_id": "s2:bbb", "score": 0.61, "chunk_text": "another"},
    ]
    row["critique"]["debate"] = _DEBATE
    _write_jsonl(_memory_dir(tmp_path) / "loop_memory.jsonl", [row])
    cache = _cache_dir(tmp_path, _IID)
    (cache / "retrieval.json").write_text("{ not json", encoding="utf-8")
    (cache / "critique.json").write_text("{ not json", encoding="utf-8")

    body = client.get(f"/api/iteration/{_IID}/journey").json()
    assert body["found"] is True
    assert body["iteration"] == row


def test_no_critique_block_is_never_fabricated(tmp_path):
    """A row with NO critique block keeps none, even when critique.json carries
    a debate — attaching one would fake a 'critic reached' station."""
    client = _client(tmp_path)
    row = _bare_row()
    del row["critique"]
    _write_jsonl(_memory_dir(tmp_path) / "loop_memory.jsonl", [row])
    cache = _cache_dir(tmp_path, _IID)
    (cache / "critique.json").write_text(
        json.dumps(_cache_critique(_DEBATE)), encoding="utf-8"
    )

    body = client.get(f"/api/iteration/{_IID}/journey").json()
    assert body["found"] is True
    assert "critique" not in body["iteration"]


# ─── degraded cache: enrichment skipped, never 500, never found:false ────


def test_no_cache_dir_serves_row_unchanged(tmp_path):
    client = _client(tmp_path)
    _write_jsonl(_memory_dir(tmp_path) / "loop_memory.jsonl", [_bare_row()])
    # coord_run_state/iteration_cache never created at all

    resp = client.get(f"/api/iteration/{_IID}/journey")
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["iteration"] == _bare_row()


def test_malformed_cache_json_skips_enrichment_not_500(tmp_path):
    client = _client(tmp_path)
    _write_jsonl(_memory_dir(tmp_path) / "loop_memory.jsonl", [_bare_row()])
    cache = _cache_dir(tmp_path, _IID)
    (cache / "retrieval.json").write_text("{{{{ garbage", encoding="utf-8")
    (cache / "critique.json").write_text("\x00\x01binary-ish", encoding="utf-8")

    resp = client.get(f"/api/iteration/{_IID}/journey")
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["iteration"] == _bare_row()


def test_wrong_shape_cache_skips_enrichment(tmp_path):
    """Valid JSON, wrong shapes: a list at top level, a list `result`, a scalar
    debate, scalar neighbors — every one is skipped, never joined, never 500."""
    client = _client(tmp_path)
    _write_jsonl(_memory_dir(tmp_path) / "loop_memory.jsonl", [_bare_row()])
    cache = _cache_dir(tmp_path, _IID)
    (cache / "retrieval.json").write_text(
        json.dumps({"status": "ok", "result": {"neighbors": "not-a-list"}}),
        encoding="utf-8",
    )
    (cache / "critique.json").write_text(
        json.dumps({"status": "ok", "result": {"debate": "conceded"}}),
        encoding="utf-8",
    )

    body = client.get(f"/api/iteration/{_IID}/journey").json()
    assert body["found"] is True
    assert body["iteration"] == _bare_row()

    # and a non-dict top level on both files
    (cache / "retrieval.json").write_text(json.dumps([1, 2]), encoding="utf-8")
    (cache / "critique.json").write_text(json.dumps("nope"), encoding="utf-8")
    body = client.get(f"/api/iteration/{_IID}/journey").json()
    assert body["iteration"] == _bare_row()


def test_over_cap_cache_file_skips_enrichment(tmp_path):
    """A cache file past the bounded-read cap is producer garbage — the join
    skips it without reading it into memory."""
    client = _client(tmp_path)
    _write_jsonl(_memory_dir(tmp_path) / "loop_memory.jsonl", [_bare_row()])
    cache = _cache_dir(tmp_path, _IID)
    huge_text = "x" * 5_000_000  # > _MAX_CACHE_FILE_BYTES once serialized
    (cache / "retrieval.json").write_text(
        json.dumps(_cache_retrieval({"s2:aaa": huge_text})), encoding="utf-8"
    )

    body = client.get(f"/api/iteration/{_IID}/journey").json()
    assert body["found"] is True
    assert "chunk_text" not in body["iteration"]["retrieval"]["neighbors"][0]


def test_encoder_unsafe_cache_value_falls_back_to_clean_row(tmp_path):
    """A cache-sourced value that would 500 the response encoder (NaN wall
    seconds in the debate) must cost only the ENRICHMENT: the clean un-enriched
    row is served at found:true — never 500, never found:false."""
    client = _client(tmp_path)
    _write_jsonl(_memory_dir(tmp_path) / "loop_memory.jsonl", [_bare_row()])
    cache = _cache_dir(tmp_path, _IID)
    bad_debate = {
        "verdict": "survives_debate",
        "rounds": 4,
        "stop_reason": "challenger_conceded",
        "transcript": [{"role": "challenger", "wall_seconds": float("nan")}],
    }
    # json.dumps default rejects NaN-compliantly only with allow_nan; emit the
    # non-compliant literal the stdlib WILL parse back (the producer-bug shape).
    (cache / "critique.json").write_text(
        json.dumps({"status": "ok", "result": {"debate": bad_debate}}),
        encoding="utf-8",
    )

    resp = client.get(f"/api/iteration/{_IID}/journey")
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    # the poisoned debate was dropped; the clean row survived
    assert "debate" not in body["iteration"]["critique"]


# ─── the read-only fence ─────────────────────────────────────────────────


def test_get_writes_nothing_including_cache_dir(tmp_path):
    client = _client(tmp_path)
    _write_jsonl(_memory_dir(tmp_path) / "loop_memory.jsonl", [_bare_row()])
    cache = _cache_dir(tmp_path, _IID)
    (cache / "retrieval.json").write_text(
        json.dumps(_cache_retrieval({"s2:aaa": _TEXT_A})), encoding="utf-8"
    )
    (cache / "critique.json").write_text(
        json.dumps(_cache_critique(_DEBATE)), encoding="utf-8"
    )

    before = _snapshot(tmp_path / "coord_run_state") | _snapshot(_memory_dir(tmp_path))
    assert client.get(f"/api/iteration/{_IID}/journey").status_code == 200
    after = _snapshot(tmp_path / "coord_run_state") | _snapshot(_memory_dir(tmp_path))
    assert after == before
