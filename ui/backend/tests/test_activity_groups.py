"""Task 1 backend tests — live-calls ``groups[]`` + ``GET /api/activity/active_runs``.

Additive coverage for the 2026-06-10 handoff (Now board / attribution):

- ``_live_calls`` ``groups[]``: aggregation per (caller_tag, model, backend,
  run_id); count-desc sort; cap 12 with ``groups_truncated``/``other_count``;
  STRICT passthrough of ``backend``/``run_id`` (null stays null — never
  guessed from the model name); existing keys untouched.
- ``GET /api/activity/active_runs``: D-047 registry reads with
  ``heartbeat_at`` passthrough; malformed files skipped + counted (never a
  500); absent dir == ``{runs: []}``; legacy ``active_run.json`` fallback
  wrapped with ``legacy_mirror: true``; ``UI_ACTIVE_RUNS_DIR`` env override.

Every path is tmp_path-scoped — no test reads or writes the live repo's
``run_state``/``logs``/``memory``. Run-doc fixtures are explicitly-synthetic
constructions shaped like ``orchestrator/active_run.py:write_active_run``
output (run_id/kind/label/started_at/heartbeat_at[/progress]), not
presented as live rows.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.activity import (
    LIVE_CALLS_GROUPS_CAP,
    LIVE_CALLS_WINDOW_S,
    _live_calls,
    register,
)

# ─── helpers ──────────────────────────────────────────────────────────

# Fixed clock for _live_calls unit tests (the function takes `now` directly,
# so no test depends on the wall clock).
FIXED_NOW = datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _call(seconds_ago: float, **fields) -> dict:
    rec = {"timestamp": _iso(FIXED_NOW - timedelta(seconds=seconds_ago))}
    rec.update(fields)
    return rec


def _write_calls(logs_dir: Path, rows: list[dict]) -> Path:
    logs_dir.mkdir(parents=True, exist_ok=True)
    path = logs_dir / "calls.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                    encoding="utf-8")
    return path


def _group_by_tag(payload: dict, tag) -> dict:
    matches = [g for g in payload["groups"] if g["tag"] == tag]
    assert len(matches) == 1, f"expected exactly one group for tag={tag!r}"
    return matches[0]


def _runs_client(tmp_path: Path, *, runs_dir: Path | None = None,
                 legacy_path: Path | None = None) -> TestClient:
    """App with every activity path pinned under tmp_path (never the live
    repo). runs_dir/legacy_path default to tmp locations that DON'T exist —
    the endpoint's absent-state — unless a test pins its own."""
    app = FastAPI()
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(exist_ok=True)
    register(
        app,
        logs_dir=logs_dir,
        telemetry_file=tmp_path / "telemetry.jsonl",
        active_run_path=(legacy_path if legacy_path is not None
                         else tmp_path / "active_run.json"),
        worker_activity_path=tmp_path / "worker_activity.jsonl",
        active_runs_dir=(runs_dir if runs_dir is not None
                         else tmp_path / "active_runs"),
    )
    return TestClient(app)


# Explicitly-synthetic run docs, shaped like write_active_run's output.
def _run_doc(run_id: str, kind: str, **extra) -> dict:
    doc = {
        "run_id": run_id,
        "kind": kind,
        "label": f"{kind} fixture run",
        "started_at": "2026-06-10T11:58:00Z",
        "heartbeat_at": "2026-06-10T11:59:55Z",
    }
    doc.update(extra)
    return doc


def _write_run(runs_dir: Path, doc: dict) -> Path:
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = runs_dir / f"{doc['run_id']}.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


# ─── groups[]: aggregation ────────────────────────────────────────────

def test_groups_aggregate_per_tag_model_backend_run_id(tmp_path):
    # Three calls share the full (tag, model, backend, run_id) key -> ONE
    # group with count 3 and last_call_at = the newest member's timestamp;
    # a fourth call with a different key forms its own group; a stale call
    # (outside the window) contributes nothing.
    rows = [
        _call(10, caller_tag="skeptic_attack", model="qwen3.6-27b-nvfp4-mtp",
              backend="vllm-qwen", run_id="loop_v0_x1"),
        _call(8, caller_tag="skeptic_attack", model="qwen3.6-27b-nvfp4-mtp",
              backend="vllm-qwen", run_id="loop_v0_x1"),
        _call(2, caller_tag="skeptic_attack", model="qwen3.6-27b-nvfp4-mtp",
              backend="vllm-qwen", run_id="loop_v0_x1"),
        _call(5, caller_tag="hypothesize", model="gemma-4-26b-a4b",
              backend="vllm-gemma", run_id="loop_v0_x1"),
        _call(60, caller_tag="stale_tag", model="gemma-4-26b-a4b",
              backend="vllm-gemma"),  # outside the 15s window
    ]
    _write_calls(tmp_path / "logs", rows)
    payload = _live_calls(tmp_path / "logs", LIVE_CALLS_WINDOW_S, FIXED_NOW)

    assert payload["count"] == 4
    assert len(payload["groups"]) == 2
    skeptic = _group_by_tag(payload, "skeptic_attack")
    assert skeptic == {
        "tag": "skeptic_attack",
        "model": "qwen3.6-27b-nvfp4-mtp",
        "backend": "vllm-qwen",
        "run_id": "loop_v0_x1",
        "count": 3,
        "last_call_at": _iso(FIXED_NOW - timedelta(seconds=2)),
    }
    hypo = _group_by_tag(payload, "hypothesize")
    assert hypo["count"] == 1
    assert hypo["backend"] == "vllm-gemma"
    assert not any(g["tag"] == "stale_tag" for g in payload["groups"])


def test_groups_split_on_any_key_component(tmp_path):
    # Same tag+model but different backend or run_id -> DISTINCT groups
    # (the aggregation key is the full 4-tuple).
    rows = [
        _call(9, caller_tag="battery", model="m", backend="vllm-gemma",
              run_id="r1"),
        _call(8, caller_tag="battery", model="m", backend="vllm-qwen",
              run_id="r1"),
        _call(7, caller_tag="battery", model="m", backend="vllm-gemma",
              run_id="r2"),
    ]
    _write_calls(tmp_path / "logs", rows)
    payload = _live_calls(tmp_path / "logs", LIVE_CALLS_WINDOW_S, FIXED_NOW)
    assert len(payload["groups"]) == 3
    assert all(g["count"] == 1 for g in payload["groups"])


def test_groups_include_untagged_calls_so_counts_reconcile(tmp_path):
    # A record with no caller_tag still lands in a (tag=None) group, so
    # sum(group counts) + other_count == count covers EVERY windowed call —
    # while the pre-existing caller_tags key keeps ignoring untagged rows.
    rows = [
        _call(4, model="gemma-4-26b-a4b"),  # no caller_tag at all
        _call(3, caller_tag="hypothesize", model="gemma-4-26b-a4b"),
    ]
    _write_calls(tmp_path / "logs", rows)
    payload = _live_calls(tmp_path / "logs", LIVE_CALLS_WINDOW_S, FIXED_NOW)
    assert payload["count"] == 2
    untagged = _group_by_tag(payload, None)
    assert untagged["count"] == 1
    assert [t["tag"] for t in payload["caller_tags"]] == ["hypothesize"]
    total = sum(g["count"] for g in payload["groups"]) + payload["other_count"]
    assert total == payload["count"]


# ─── groups[]: sort / cap / truncation ────────────────────────────────

def test_groups_sorted_count_desc(tmp_path):
    rows = (
        [_call(9, caller_tag="one_call", model="m")]
        + [_call(8 - i / 10, caller_tag="three_calls", model="m")
           for i in range(3)]
        + [_call(7 - i / 10, caller_tag="two_calls", model="m")
           for i in range(2)]
    )
    _write_calls(tmp_path / "logs", rows)
    payload = _live_calls(tmp_path / "logs", LIVE_CALLS_WINDOW_S, FIXED_NOW)
    assert [g["tag"] for g in payload["groups"]] == [
        "three_calls", "two_calls", "one_call"]
    assert [g["count"] for g in payload["groups"]] == [3, 2, 1]
    assert payload["groups_truncated"] is False
    assert payload["other_count"] == 0


def test_groups_capped_at_12_with_truncation_and_other_count(tmp_path):
    # 14 distinct groups; tag NN gets (14 - NN) calls so the count-desc
    # order is tag00..tag13. Cap keeps the top 12; the two dropped groups
    # held 2 + 1 = 3 calls -> other_count 3, groups_truncated True.
    rows = []
    for i in range(14):
        for j in range(14 - i):
            rows.append(_call(10 - i / 100 - j / 10000,
                              caller_tag=f"tag{i:02d}", model="m"))
    _write_calls(tmp_path / "logs", rows)
    payload = _live_calls(tmp_path / "logs", LIVE_CALLS_WINDOW_S, FIXED_NOW)

    assert payload["count"] == 105  # 14+13+...+1
    assert len(payload["groups"]) == LIVE_CALLS_GROUPS_CAP == 12
    assert [g["tag"] for g in payload["groups"]] == [
        f"tag{i:02d}" for i in range(12)]
    assert payload["groups_truncated"] is True
    assert payload["other_count"] == 3
    total = sum(g["count"] for g in payload["groups"]) + payload["other_count"]
    assert total == payload["count"]


def test_groups_exactly_at_cap_not_truncated(tmp_path):
    rows = [_call(9 - i / 100, caller_tag=f"tag{i:02d}", model="m")
            for i in range(12)]
    _write_calls(tmp_path / "logs", rows)
    payload = _live_calls(tmp_path / "logs", LIVE_CALLS_WINDOW_S, FIXED_NOW)
    assert len(payload["groups"]) == 12
    assert payload["groups_truncated"] is False
    assert payload["other_count"] == 0


# ─── groups[]: passthrough honesty ────────────────────────────────────

def test_groups_null_backend_stays_null_never_guessed_from_model(tmp_path):
    # Pre-2026-06-10 rows carry NO backend. Even when the model name maps
    # 1:1 to a known backend (gemma-4-26b-a4b is served by vllm-gemma), the
    # group's backend must be None — passthrough, never fabricated.
    rows = [
        _call(6, caller_tag="battery", model="gemma-4-26b-a4b"),  # old row
        _call(4, caller_tag="skeptic_attack", model="qwen3.6-27b-nvfp4-mtp",
              backend="vllm-qwen"),  # post-EMIT row
    ]
    _write_calls(tmp_path / "logs", rows)
    payload = _live_calls(tmp_path / "logs", LIVE_CALLS_WINDOW_S, FIXED_NOW)

    old = _group_by_tag(payload, "battery")
    assert old["backend"] is None          # NOT "vllm-gemma"
    assert old["run_id"] is None           # absent on the record -> null
    new = _group_by_tag(payload, "skeptic_attack")
    assert new["backend"] == "vllm-qwen"   # exact passthrough
    assert new["run_id"] is None


def test_groups_run_id_passthrough_when_present(tmp_path):
    rows = [_call(3, caller_tag="exp009_runner", model="m",
                  backend="anthropic", run_id="exp009_ab12cd34")]
    _write_calls(tmp_path / "logs", rows)
    payload = _live_calls(tmp_path / "logs", LIVE_CALLS_WINDOW_S, FIXED_NOW)
    grp = _group_by_tag(payload, "exp009_runner")
    assert grp["run_id"] == "exp009_ab12cd34"
    assert grp["backend"] == "anthropic"


# ─── groups[] is additive: existing keys untouched ────────────────────

def test_live_calls_existing_keys_unchanged_alongside_groups(tmp_path):
    rows = [
        _call(5, caller_tag="skeptic_attack", model="qwen3.6-27b-nvfp4-mtp",
              backend="vllm-qwen"),
        _call(4, caller_tag="skeptic_attack", model="qwen3.6-27b-nvfp4-mtp",
              backend="vllm-qwen"),
        _call(3, caller_tag="hypothesize", model="gemma-4-26b-a4b",
              backend="vllm-gemma"),
    ]
    _write_calls(tmp_path / "logs", rows)
    payload = _live_calls(tmp_path / "logs", LIVE_CALLS_WINDOW_S, FIXED_NOW)

    # Pre-groups contract, unchanged (older renders/tests key off these).
    assert payload["active"] is True
    assert payload["count"] == 3
    assert payload["window_s"] == LIVE_CALLS_WINDOW_S
    assert payload["calls_per_s"] == round(3 / LIVE_CALLS_WINDOW_S, 2)
    assert payload["last_call_at"] == _iso(FIXED_NOW - timedelta(seconds=3))
    assert payload["caller_tags"] == [
        {"tag": "skeptic_attack", "count": 2},
        {"tag": "hypothesize", "count": 1},
    ]
    assert payload["model"] == "qwen3.6-27b-nvfp4-mtp"
    # The additive keys ride alongside.
    assert {"groups", "groups_truncated", "other_count"} <= payload.keys()


def test_monitor_endpoint_surfaces_groups(tmp_path):
    # End-to-end: /api/activity/monitor's live_calls block carries groups[]
    # (the endpoint uses the wall clock, so the fixture rows are stamped
    # relative to real now).
    now = datetime.now(timezone.utc)
    logs_dir = tmp_path / "logs"
    _write_calls(logs_dir, [
        {"timestamp": _iso(now - timedelta(seconds=1)),
         "caller_tag": "subagent.finding_skeptic_1",
         "model": "qwen3.6-27b-nvfp4-mtp", "backend": "vllm-qwen",
         "run_id": "loop_v0_aa11bb22"},
    ])
    client = _runs_client(tmp_path)
    live = client.get("/api/activity/monitor").json()["live_calls"]
    assert live["groups"] == [{
        "tag": "subagent.finding_skeptic_1",
        "model": "qwen3.6-27b-nvfp4-mtp",
        "backend": "vllm-qwen",
        "run_id": "loop_v0_aa11bb22",
        "count": 1,
        "last_call_at": _iso(now - timedelta(seconds=1)),
    }]
    assert live["groups_truncated"] is False
    assert live["other_count"] == 0


# ─── /api/activity/active_runs ────────────────────────────────────────

def test_active_runs_absent_dir_yields_empty_runs(tmp_path):
    # Neither the registry dir nor the legacy mirror exists -> {runs: []},
    # 200 (never a 404/500 on the pre-D-047 idle state).
    client = _runs_client(tmp_path)  # helper paths don't exist
    resp = client.get("/api/activity/active_runs")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["runs"] == []
    assert payload["skipped"] == 0


def test_active_runs_lists_registry_with_heartbeat_passthrough(tmp_path):
    runs_dir = tmp_path / "active_runs"
    coord = _run_doc("coordinator_ab12cd34", "coordinator",
                     heartbeat_at="2026-06-10T11:59:59Z",
                     current_step="plan_validation")
    loop = _run_doc("loop_v0_ee55ff66", "loop_v0",
                    progress={"done": 3, "total": 6, "unit": "steps"})
    _write_run(runs_dir, coord)
    _write_run(runs_dir, loop)
    client = _runs_client(tmp_path, runs_dir=runs_dir)

    resp = client.get("/api/activity/active_runs")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["skipped"] == 0
    by_id = {r["run_id"]: r for r in payload["runs"]}
    assert set(by_id) == {"coordinator_ab12cd34", "loop_v0_ee55ff66"}
    # Raw passthrough: heartbeat_at + every other producer key, verbatim.
    assert by_id["coordinator_ab12cd34"] == coord
    assert by_id["loop_v0_ee55ff66"] == loop
    # Registry docs are NOT tagged as the legacy mirror.
    assert all("legacy_mirror" not in r for r in payload["runs"])


def test_active_runs_unknown_kind_passes_through_raw(tmp_path):
    # The kind set is {experiment, autoresearch, loop_v0, ad_hoc,
    # coordinator} today and may grow — an unknown kind is passed through
    # raw, never filtered or normalized.
    runs_dir = tmp_path / "active_runs"
    future = _run_doc("future_run_01", "swarm_consensus")
    _write_run(runs_dir, future)
    client = _runs_client(tmp_path, runs_dir=runs_dir)
    payload = client.get("/api/activity/active_runs").json()
    assert payload["runs"] == [future]
    assert payload["runs"][0]["kind"] == "swarm_consensus"


def test_active_runs_malformed_files_skipped_and_counted(tmp_path):
    runs_dir = tmp_path / "active_runs"
    good = _run_doc("loop_v0_good1234", "loop_v0")
    _write_run(runs_dir, good)
    (runs_dir / "corrupt.json").write_text("{not json", encoding="utf-8")
    (runs_dir / "nondict.json").write_text("[1, 2]", encoding="utf-8")

    client = _runs_client(tmp_path, runs_dir=runs_dir)
    resp = client.get("/api/activity/active_runs")
    assert resp.status_code == 200  # never 500 on bad registry files
    payload = resp.json()
    assert payload["runs"] == [good]
    assert payload["skipped"] == 2


def test_active_runs_legacy_fallback_when_dir_absent(tmp_path):
    legacy_path = tmp_path / "active_run.json"
    legacy = _run_doc("exp008_legacy01", "experiment",
                      heartbeat_at="2026-06-10T11:59:40Z",
                      narration="evaluating cohort")
    legacy_path.write_text(json.dumps(legacy), encoding="utf-8")
    client = _runs_client(tmp_path, runs_dir=tmp_path / "nonexistent_dir",
                          legacy_path=legacy_path)

    payload = client.get("/api/activity/active_runs").json()
    assert payload["runs"] == [{**legacy, "legacy_mirror": True}]
    assert payload["runs"][0]["heartbeat_at"] == "2026-06-10T11:59:40Z"
    assert payload["skipped"] == 0


def test_active_runs_legacy_fallback_when_dir_empty(tmp_path):
    # Dir exists but holds no .json files -> same fallback as absent dir.
    runs_dir = tmp_path / "active_runs"
    runs_dir.mkdir()
    legacy_path = tmp_path / "active_run.json"
    legacy = _run_doc("adhoc_mirror001", "ad_hoc")
    legacy_path.write_text(json.dumps(legacy), encoding="utf-8")
    client = _runs_client(tmp_path, runs_dir=runs_dir,
                          legacy_path=legacy_path)
    payload = client.get("/api/activity/active_runs").json()
    assert payload["runs"] == [{**legacy, "legacy_mirror": True}]


def test_active_runs_registry_wins_over_legacy_mirror(tmp_path):
    # When the registry has files, the mirror is ignored (it is the most
    # recent writer, already represented by its own registry file).
    runs_dir = tmp_path / "active_runs"
    reg = _run_doc("loop_v0_reg00001", "loop_v0")
    _write_run(runs_dir, reg)
    legacy_path = tmp_path / "active_run.json"
    legacy_path.write_text(json.dumps(reg), encoding="utf-8")
    client = _runs_client(tmp_path, runs_dir=runs_dir,
                          legacy_path=legacy_path)
    payload = client.get("/api/activity/active_runs").json()
    assert payload["runs"] == [reg]
    assert "legacy_mirror" not in payload["runs"][0]


def test_active_runs_registry_all_skipped_does_not_fall_back(tmp_path):
    # A registry dir WITH .json files (all malformed) is neither absent nor
    # empty: no mirror fallback (it could resurrect a stale run); the
    # skipped count is the honest signal.
    runs_dir = tmp_path / "active_runs"
    runs_dir.mkdir()
    (runs_dir / "corrupt.json").write_text("{{{", encoding="utf-8")
    legacy_path = tmp_path / "active_run.json"
    legacy_path.write_text(json.dumps(_run_doc("stale_mirror01", "ad_hoc")),
                           encoding="utf-8")
    client = _runs_client(tmp_path, runs_dir=runs_dir,
                          legacy_path=legacy_path)
    payload = client.get("/api/activity/active_runs").json()
    assert payload["runs"] == []
    assert payload["skipped"] == 1


def test_active_runs_corrupt_legacy_never_500s(tmp_path):
    legacy_path = tmp_path / "active_run.json"
    legacy_path.write_text("{corrupt", encoding="utf-8")
    client = _runs_client(tmp_path, runs_dir=tmp_path / "nonexistent_dir",
                          legacy_path=legacy_path)
    resp = client.get("/api/activity/active_runs")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["runs"] == []
    assert payload["skipped"] == 1


def test_active_runs_env_var_overrides_default_dir(tmp_path, monkeypatch):
    # app.py's register_activity(...) call passes no active_runs_dir — the
    # live server steers the path with UI_ACTIVE_RUNS_DIR (the
    # DEFAULT_COORDINATOR_RUN_STATE idiom replicated in activity.py).
    env_dir = tmp_path / "env_runs"
    doc = _run_doc("loop_v0_envtest1", "loop_v0")
    _write_run(env_dir, doc)
    monkeypatch.setenv("UI_ACTIVE_RUNS_DIR", str(env_dir))

    app = FastAPI()
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(exist_ok=True)
    register(
        app,
        logs_dir=logs_dir,
        telemetry_file=tmp_path / "telemetry.jsonl",
        # Pin the legacy mirror path into tmp too, so this test can never
        # read the live repo even if the env dir were empty.
        active_run_path=tmp_path / "active_run.json",
        worker_activity_path=tmp_path / "worker_activity.jsonl",
        # active_runs_dir intentionally NOT passed -> env override applies.
    )
    client = TestClient(app)
    payload = client.get("/api/activity/active_runs").json()
    assert payload["runs"] == [doc]
