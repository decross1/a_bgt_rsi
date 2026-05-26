"""Critic-invocation surface (ui_plan.md §11.3 Phase-2 prerequisite).

See backend/critic.py. Mirrors test_unlock.py shape: each section
exercised independently, then the consolidated compute_critic_summary
covers the cross-section interactions.
"""
import json

from backend.critic import (
    compute_critic_summary,
    compute_fixture_matchup,
    compute_flag_rate,
    compute_recent_runs,
    load_critic_fixtures,
    parse_critic_log,
)


def _write_jsonl(path, records):
    path.write_text("".join(json.dumps(r) + "\n" for r in records),
                    encoding="utf-8")


def _critic_record(hid="001_flaw_a", decision="flawed", critique="A solid critique.",
                   ts="2026-05-25T10:00:00Z", **extra):
    return {"timestamp": ts, "hypothesis_id": hid,
            "flag_decision": decision, "critique": critique, **extra}


def _fixture(fid, label="flawed", flaw="spurious_causation",
             targets=("rationality requires the agent know the objective",
                      "rerun with payoff shown in prompt is needed"),
             severity="moderate", domain="game_theory"):
    return {"id": fid, "hypothesis_text": "h",
            "domain": domain, "injected_flaw_type": flaw,
            "flaw_description": "internal", "expected_critique_targets": list(targets),
            "ground_truth_label": label, "severity": severity,
            "schema_version": "1.0"}


def _write_fixtures(fixtures_dir, fixtures):
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    for fx in fixtures:
        (fixtures_dir / f"{fx['id']}.json").write_text(
            json.dumps(fx), encoding="utf-8")


# ── parse_critic_log ─────────────────────────────────────────────────

def test_parse_critic_log_clean_file(tmp_path):
    path = tmp_path / "critic_eval.jsonl"
    _write_jsonl(path, [_critic_record(hid="a"), _critic_record(hid="b")])
    result = parse_critic_log(path)
    assert result["available"] is True
    assert result["malformed_lines"] == []
    assert len(result["records"]) == 2


def test_parse_critic_log_flags_missing_required_field(tmp_path):
    path = tmp_path / "critic_eval.jsonl"
    bad = _critic_record(hid="b")
    bad.pop("flag_decision")
    _write_jsonl(path, [_critic_record(hid="a"), bad, _critic_record(hid="c")])
    result = parse_critic_log(path)
    assert result["malformed_lines"] == [2]
    assert len(result["records"]) == 2  # the well-formed pair


def test_parse_critic_log_flags_unparseable_line(tmp_path):
    path = tmp_path / "critic_eval.jsonl"
    path.write_text(
        json.dumps(_critic_record(hid="a")) + "\n"
        + "{not json\n"
        + json.dumps(_critic_record(hid="c")) + "\n",
        encoding="utf-8")
    result = parse_critic_log(path)
    assert result["malformed_lines"] == [2]


def test_parse_critic_log_absent_file(tmp_path):
    result = parse_critic_log(tmp_path / "absent.jsonl")
    assert result == {"available": False, "records": [], "malformed_lines": [],
                      "total_lines": 0}


# ── load_critic_fixtures ─────────────────────────────────────────────

def test_load_fixtures_keyed_by_id(tmp_path):
    fdir = tmp_path / "critic_hypotheses"
    _write_fixtures(fdir, [_fixture("001_a"), _fixture("002_b", label="sound",
                                                       flaw="none")])
    fixtures = load_critic_fixtures(fdir)
    assert set(fixtures) == {"001_a", "002_b"}
    assert fixtures["002_b"]["ground_truth_label"] == "sound"


def test_load_fixtures_absent_dir(tmp_path):
    assert load_critic_fixtures(tmp_path / "missing") == {}


# ── compute_recent_runs ──────────────────────────────────────────────

def test_recent_runs_carry_excerpt_and_target_hits():
    records = [_critic_record(
        hid="003_misspecified_payoff",
        critique="The claim that rationality requires the agent know the "
                 "objective is the core problem; rerun with payoff shown "
                 "in prompt is needed to verify.")]
    fixtures = {"003_misspecified_payoff": _fixture("003_misspecified_payoff")}
    rows = compute_recent_runs(records, fixtures, limit=50)
    assert rows[0]["hypothesis_id"] == "003_misspecified_payoff"
    assert rows[0]["flag_decision"] == "flawed"
    assert rows[0]["ground_truth_label"] == "flawed"
    assert set(rows[0]["target_hits"]) == {
        "rationality requires the agent know the objective",
        "rerun with payoff shown in prompt is needed",
    }
    assert rows[0]["target_count"] == 2
    assert rows[0]["critique_excerpt"].startswith("The claim that rationality")


def test_recent_runs_caps_at_limit():
    records = [_critic_record(hid=f"h{i}", ts=f"2026-05-25T10:00:{i:02d}Z")
               for i in range(60)]
    rows = compute_recent_runs(records, {}, limit=50)
    assert len(rows) == 50
    # Newest-last preserved: last record in tail = h59.
    assert rows[-1]["hypothesis_id"] == "h59"


def test_recent_runs_unknown_flag_decision_normalised_to_none():
    records = [_critic_record(decision="maybe")]
    rows = compute_recent_runs(records, {}, limit=50)
    assert rows[0]["flag_decision"] is None


# ── compute_flag_rate ────────────────────────────────────────────────

def test_flag_rate_mixed():
    records = [
        _critic_record(decision="flawed", ts="2026-05-25T10:00:00Z"),
        _critic_record(decision="flawed", ts="2026-05-25T10:01:00Z"),
        _critic_record(decision="sound", ts="2026-05-25T10:02:00Z"),
    ]
    out = compute_flag_rate(records, rolling_window_days=7,
                            now_iso="2026-05-25T20:00:00Z")
    assert out["total"] == 3
    assert out["flawed_count"] == 2
    assert out["sound_count"] == 1
    assert abs(out["flag_rate"] - 2 / 3) < 1e-9


def test_flag_rate_excludes_outside_window():
    records = [
        _critic_record(decision="flawed", ts="2026-04-01T00:00:00Z"),  # stale
        _critic_record(decision="sound", ts="2026-05-25T10:00:00Z"),
    ]
    out = compute_flag_rate(records, rolling_window_days=7,
                            now_iso="2026-05-25T20:00:00Z")
    assert out["total"] == 1
    assert out["flawed_count"] == 0


def test_flag_rate_empty_yields_none():
    out = compute_flag_rate([], rolling_window_days=7,
                            now_iso="2026-05-25T20:00:00Z")
    assert out["total"] == 0
    assert out["flag_rate"] is None


# ── compute_fixture_matchup ──────────────────────────────────────────

def test_matchup_classifies_TP_FP_TN_FN_and_unrun():
    fixtures = {
        "f_flawed": _fixture("f_flawed", label="flawed"),
        "f_sound": _fixture("f_sound", label="sound", flaw="none"),
        "f_flawed_missed": _fixture("f_flawed_missed", label="flawed"),
        "f_sound_falsealarm": _fixture("f_sound_falsealarm", label="sound",
                                       flaw="none"),
        "f_never_run": _fixture("f_never_run", label="flawed"),
    }
    records = [
        _critic_record(hid="f_flawed", decision="flawed",
                       ts="2026-05-25T10:00:00Z"),                # TP
        _critic_record(hid="f_sound", decision="sound",
                       ts="2026-05-25T10:01:00Z"),                # TN
        _critic_record(hid="f_flawed_missed", decision="sound",
                       ts="2026-05-25T10:02:00Z"),                # FN
        _critic_record(hid="f_sound_falsealarm", decision="flawed",
                       ts="2026-05-25T10:03:00Z"),                # FP
    ]
    out = compute_fixture_matchup(records, fixtures)
    counts = out["counts"]
    assert (counts["TP"], counts["FP"], counts["TN"], counts["FN"]) == (1, 1, 1, 1)
    assert counts["unrun"] == 1
    assert counts["unknown_fixture"] == 0
    assert out["accuracy"] == 0.5  # 2 / 4 scored
    # Per-fixture outcomes surface in `rows`.
    by_id = {r["fixture_id"]: r["outcome"] for r in out["rows"]}
    assert by_id["f_flawed"] == "TP"
    assert by_id["f_sound_falsealarm"] == "FP"
    assert by_id["f_never_run"] == "unrun"


def test_matchup_uses_latest_decision_per_fixture():
    fixtures = {"f": _fixture("f", label="flawed")}
    records = [
        _critic_record(hid="f", decision="sound",
                       ts="2026-05-25T09:00:00Z"),                 # earlier
        _critic_record(hid="f", decision="flawed",
                       ts="2026-05-25T10:00:00Z"),                 # latest
    ]
    out = compute_fixture_matchup(records, fixtures)
    assert out["counts"]["TP"] == 1
    assert out["counts"]["FN"] == 0
    assert out["rows"][0]["latest_run_ts"] == "2026-05-25T10:00:00Z"


def test_matchup_surfaces_unknown_fixture_ids():
    records = [_critic_record(hid="ad_hoc_id", decision="flawed",
                              ts="2026-05-25T10:00:00Z")]
    out = compute_fixture_matchup(records, {})
    assert out["counts"]["unknown_fixture"] == 1
    assert out["rows"][0]["fixture_id"] == "ad_hoc_id"
    assert out["rows"][0]["outcome"] == "unknown_fixture"


# ── compute_critic_summary ───────────────────────────────────────────

def test_compute_critic_summary_consolidates_all_sections(tmp_path):
    log_path = tmp_path / "critic_eval.jsonl"
    fixtures_dir = tmp_path / "critic_hypotheses"
    _write_fixtures(fixtures_dir, [
        _fixture("003_misspecified_payoff", label="flawed"),
        _fixture("020_sound_baseline", label="sound", flaw="none",
                 targets=["no substantive flaw should be identified"]),
    ])
    _write_jsonl(log_path, [
        _critic_record(hid="003_misspecified_payoff", decision="flawed",
                       critique="The claim that rationality requires the agent "
                                "know the objective is the core problem; rerun "
                                "with payoff shown in prompt is needed.",
                       ts="2026-05-25T10:00:00Z"),
        _critic_record(hid="020_sound_baseline", decision="sound",
                       critique="No substantive flaw to flag.",
                       ts="2026-05-25T10:01:00Z"),
    ])

    out = compute_critic_summary(log_path, fixtures_dir,
                                 now_iso="2026-05-25T20:00:00Z")
    assert out["milestone"] == "critic_invocations"
    assert out["fixtures"]["total"] == 2
    assert out["recent_runs"]["available"] is True
    assert out["recent_runs"]["total_runs"] == 2
    assert out["flag_rate"]["available"] is True
    assert out["flag_rate"]["flawed_count"] == 1
    assert out["flag_rate"]["sound_count"] == 1
    # 2/2 correct: TP + TN.
    assert out["fixture_matchup"]["accuracy"] == 1.0
    assert out["fixture_matchup"]["counts"]["TP"] == 1
    assert out["fixture_matchup"]["counts"]["TN"] == 1


def test_compute_critic_summary_degrades_when_files_absent(tmp_path):
    out = compute_critic_summary(tmp_path / "missing.jsonl",
                                 tmp_path / "missing_dir",
                                 now_iso="2026-05-25T20:00:00Z")
    assert out["recent_runs"]["available"] is False
    assert out["recent_runs"]["rows"] == []
    assert out["flag_rate"]["available"] is False
    assert out["flag_rate"]["total"] == 0
    assert out["fixture_matchup"]["available"] is False
    assert out["fixture_matchup"]["counts"]["TP"] == 0
    assert out["fixtures"]["available"] is False
    assert out["fixtures"]["total"] == 0
