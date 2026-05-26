"""HTTP endpoint tests via FastAPI's TestClient."""
import json

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.tests.fixtures.gen import expected_manifest, write_fixtures


def _client(tmp_path):
    logs = tmp_path / "logs"
    write_fixtures(logs)
    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text(json.dumps({
        "timestamp": "2026-05-18T10:00:00.000+00:00",
        "gpu": None, "host": None, "vllm": None,
        "processes": [], "read_errors": None,
    }) + "\n")
    state = tmp_path / "state.json"
    state.write_text(json.dumps({
        "plan_id": "test", "current_day": "day_1",
        "human_gates_pending": ["day7_publication_review_gate"],
        "metric_log": {"day1_tokens_per_sec": 32.03},
        "fallbacks_taken": {"day5_ml_intern": "direct_api"},
    }))
    bench = tmp_path / "day1.csv"
    bench.write_text("prompt_idx,completion_tokens,elapsed_s,decode_tok_per_s\n"
                     "0,256,8.0,32.0\n", encoding="utf-8")
    # mtp.csv is left to individual tests to create — points at tmp_path so
    # the repo's real bench/mtp.csv never leaks into a test.
    mtp = tmp_path / "mtp.csv"
    # run.jsonl + attestations.jsonl point at tmp_path too, so /api/unlock_status
    # never reads the real run_state/* while Track A may be mid-write.
    run_log = tmp_path / "week1.run.jsonl"
    run_log.write_text(json.dumps({
        "timestamp": "2026-05-22T00:00:00Z", "day_id": "day_6",
        "task_id": "x", "status": "passed",
        "observable_actual": "ok", "observable_expected": "ok",
        "duration_ms": 0,
    }) + "\n", encoding="utf-8")
    attestations = tmp_path / "attestations.jsonl"
    attestations.write_text("", encoding="utf-8")
    # Day-9: critic-eval log + fixtures point into tmp_path so the
    # endpoint never accidentally reads the real on-disk critic log
    # while Track A may be mid-write. Tests that exercise critic
    # specifically populate these files directly via _seed_critic
    # — do not clobber if seeded before _client.
    critic_log = tmp_path / "critic_eval.jsonl"
    if not critic_log.exists():
        critic_log.write_text("", encoding="utf-8")
    critic_fixtures = tmp_path / "critic_hypotheses"
    critic_fixtures.mkdir(exist_ok=True)
    # Day-9 stretch: meta-review log path defaults to a tmp_path file
    # that doesn't exist — the stub returns available=false.
    meta_review = tmp_path / "meta_review.jsonl"
    return TestClient(create_app(
        logs_dir=logs, telemetry_file=telemetry, state_file=state,
        bench_csv=bench, mtp_csv=mtp, run_log_file=run_log,
        attestations_file=attestations,
        critic_log_file=critic_log, critic_fixtures_dir=critic_fixtures,
        meta_review_log_file=meta_review))


def _seed_critic(tmp_path, fixtures, records):
    """Write critic fixtures + log inside tmp_path so the next
    `_client(tmp_path)` picks them up via the configured paths."""
    fdir = tmp_path / "critic_hypotheses"
    fdir.mkdir(exist_ok=True)
    for fx in fixtures:
        (fdir / f"{fx['id']}.json").write_text(json.dumps(fx),
                                               encoding="utf-8")
    log = tmp_path / "critic_eval.jsonl"
    log.write_text("".join(json.dumps(r) + "\n" for r in records),
                   encoding="utf-8")


def test_health(tmp_path):
    body = _client(tmp_path).get("/api/health").json()
    assert body["ok"] is True
    assert body["telemetry_last_seen"] == "2026-05-18T10:00:00.000+00:00"


def test_recent_tasks(tmp_path):
    body = _client(tmp_path).get("/api/recent_tasks").json()
    ids = [t["task_id"] for t in body["tasks"]]
    assert "day6_task_01" in ids
    assert ids[0] == "exp001_round_07"               # latest first


def test_chain_found(tmp_path):
    expected = expected_manifest()["day6_task_01"]
    body = _client(tmp_path).get("/api/chain/day6_task_01").json()
    assert body["found"] is True
    assert body["node_count"] == expected["node_count"]
    assert body["total_latency_ms"] == expected["total_latency_ms"]


def test_chain_not_found(tmp_path):
    assert _client(tmp_path).get("/api/chain/missing").status_code == 404


def test_state_passthrough(tmp_path):
    body = _client(tmp_path).get("/api/state").json()
    assert body["current_day"] == "day_1"


def test_baseline_endpoint(tmp_path):
    # No mtp.csv created — decode row falls back to the pre-MTP day-1 bench.
    body = _client(tmp_path).get("/api/baseline").json()
    rows = {r["key"]: r for r in body["rows"]}
    # decode tok/s is measured from the bench csv written by _client
    assert rows["decode_tok_per_s"]["source"] == "measured"
    assert "32.0 tok/s" in rows["decode_tok_per_s"]["value"]
    assert "MTP-engaged" not in rows["decode_tok_per_s"]["value"]
    # rows with no committed measurement source stay documented
    assert rows["stack"]["source"] == "documented"


def test_baseline_endpoint_uses_mtp_csv(tmp_path):
    # bench/mtp.csv present — the MTP-enabled sweep drives the decode row.
    (tmp_path / "mtp.csv").write_text(
        "prompt_idx,prompt_tokens,completion_tokens,ttft_s,"
        "decode_tok_per_s,e2e_tok_per_s\n"
        "0,23,256,0.13,74.51,72.0\n1,24,256,0.12,89.81,86.4\n",
        encoding="utf-8")
    body = _client(tmp_path).get("/api/baseline").json()
    row = {r["key"]: r for r in body["rows"]}["decode_tok_per_s"]
    assert row["source"] == "measured"
    assert "MTP-engaged" in row["value"]
    assert "mtp.csv" in row["value"]
    assert "pre-MTP day-1" in row["value"]          # day-1 bench rides alongside


def test_unlock_status_endpoint(tmp_path):
    body = _client(tmp_path).get("/api/unlock_status").json()
    assert body["milestone"] == "ui_v1_week2_unlock"
    assert body["current_day"] == "day_1"
    assert body["run_log_integrity"]["ok"] is True
    assert body["run_log_integrity"]["total_lines"] == 1
    assert body["hard_gates_pending"]["pending"][0]["task_id"] \
        == "day7_publication_review_gate"
    assert body["hard_gates_pending"]["pending"][0]["attest_command"].endswith(
        "--task-id day7_publication_review_gate")
    assert body["metric_log"]["day1_tokens_per_sec"] == 32.03
    assert body["fallbacks_taken"]["day5_ml_intern"] == "direct_api"


def test_telemetry_recent(tmp_path):
    body = _client(tmp_path).get("/api/telemetry/recent?limit=10").json()
    assert len(body["samples"]) == 1
    assert body["samples"][0]["timestamp"] == "2026-05-18T10:00:00.000+00:00"


def test_critic_summary_endpoint(tmp_path):
    _seed_critic(tmp_path,
        fixtures=[
            {"id": "003_misspecified_payoff", "hypothesis_text": "h",
             "domain": "game_theory", "injected_flaw_type": "misspecified_payoff",
             "flaw_description": "internal",
             "expected_critique_targets": ["rationality requires the agent know the objective"],
             "ground_truth_label": "flawed", "severity": "moderate",
             "schema_version": "1.0"},
        ],
        records=[
            {"timestamp": "2026-05-25T10:00:00Z",
             "hypothesis_id": "003_misspecified_payoff",
             "flag_decision": "flawed",
             "critique": "Note that rationality requires the agent know the objective; this is missing here."},
        ])
    body = _client(tmp_path).get("/api/critic_summary").json()
    assert body["milestone"] == "critic_invocations"
    assert body["fixtures"]["total"] == 1
    assert body["recent_runs"]["total_runs"] == 1
    assert body["recent_runs"]["rows"][0]["target_hits"] == [
        "rationality requires the agent know the objective"]
    assert body["fixture_matchup"]["counts"]["TP"] == 1
    assert body["flag_rate"]["flawed_count"] == 1


def test_critic_summary_empty_state_endpoint(tmp_path):
    # No critic log lines, no fixtures — endpoint returns a usable shape.
    body = _client(tmp_path).get("/api/critic_summary").json()
    assert body["recent_runs"]["rows"] == []
    assert body["flag_rate"]["total"] == 0
    assert body["fixture_matchup"]["counts"]["TP"] == 0


def test_meta_review_summary_empty_state(tmp_path):
    # logs/meta_review.jsonl absent → stub returns available=false.
    body = _client(tmp_path).get("/api/meta_review_summary").json()
    assert body["available"] is False
    assert body["total_runs"] == 0
    assert "awaiting Day-40" in body["note"]


def test_meta_review_summary_with_log_present(tmp_path):
    log = tmp_path / "meta_review.jsonl"
    log.write_text(json.dumps({"row": 1}) + "\n" + json.dumps({"row": 2}) + "\n",
                   encoding="utf-8")
    body = _client(tmp_path).get("/api/meta_review_summary").json()
    assert body["available"] is True
    assert body["total_runs"] == 2
