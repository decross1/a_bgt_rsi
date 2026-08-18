"""Stage-3b vote-battery driver tests (PREREG_qwen_ab_3bcd_2026-08-18.md §3b).

Hermetic under MOCK_LLM=1: the finding_promotion site is replaced by a fake
(monkeypatch-style seam — run_arm takes the bound module as an argument), so
no wrapper call, no network, no live-file write ever happens here. Covers:
fixture resolution vs the prereg pins (drift refuses), the calls-log binding
check, criteria evaluation on YES and NO fixtures, empty-at-cap detection
from the calls log, time-cap partial recording (rule 7), and the MOCK_LLM
CLI refusal (exit 2).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bench.qwen_ab_3bcd import vote_battery as vb  # noqa: E402

EXPECTED = list(vb.EXPECTED_FINDING_IDS)
SOURCE_IDS = [f[len("sf-"):] for f in EXPECTED]

HIST_BLOCK = {"n_skeptics": 3, "n_voting": 3, "n_refuted": 3,
              "adversarial_margin": -3, "survived": False, "qwen_failures": 0}


def _surfaced_row(finding_id: str, adversarial=None) -> dict:
    return {
        "finding_id": finding_id,
        "source_iteration_id": finding_id[len("sf-"):],
        "promoted_at": "2026-07-01T00:00:00Z",
        "adversarial": dict(HIST_BLOCK) if adversarial is None else adversarial,
    }


def _loop_row(iteration_id: str) -> dict:
    return {"iteration_id": iteration_id,
            "hypothesis": {"text": f"hypothesis text for {iteration_id}"},
            "seed": {"topic": f"topic {iteration_id}"}}


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


@pytest.fixture
def live_files(tmp_path):
    """tmp surfaced_findings + loop_memory that resolve to the prereg pins:
    an older complete row, the 3 pinned rows, then a NEWER row with an
    INCOMPLETE vote block (must be skipped by the completeness filter)."""
    surfaced = tmp_path / "surfaced_findings.jsonl"
    _write_jsonl(surfaced, [
        _surfaced_row("sf-iter-2026-05-26-008"),
        *[_surfaced_row(f) for f in EXPECTED],
        _surfaced_row("sf-iter-2026-08-10-001",
                      adversarial={"n_voting": 3}),  # incomplete block
    ])
    loop = tmp_path / "loop_memory.jsonl"
    _write_jsonl(loop, [_loop_row(i) for i in SOURCE_IDS])
    return surfaced, loop


# ── fixture resolution (prereg rule vs pins) ─────────────────────────────


def test_resolve_fixtures_matches_pins_and_records_sha(live_files):
    surfaced, loop = live_files
    fixtures, s_sha, l_sha = vb.resolve_fixtures(surfaced, loop)
    assert [f["finding_id"] for f in fixtures] == EXPECTED
    assert [f["source_iteration_id"] for f in fixtures] == SOURCE_IDS
    assert s_sha == hashlib.sha256(surfaced.read_bytes()).hexdigest()
    assert l_sha == hashlib.sha256(loop.read_bytes()).hexdigest()
    for f in fixtures:
        assert f["historical_adversarial"] == HIST_BLOCK
        assert f["loop_row"]["hypothesis"]["text"].startswith("hypothesis")


def test_resolve_fixtures_refuses_on_drift(live_files):
    surfaced, loop = live_files
    with open(surfaced, "a") as fh:  # a NEWER complete row shifts the tail
        fh.write(json.dumps(_surfaced_row("sf-iter-2026-08-10-001")) + "\n")
    with pytest.raises(vb.FixtureResolutionError, match="drifted"):
        vb.resolve_fixtures(surfaced, loop)


def test_resolve_fixtures_refuses_on_missing_loop_row(live_files, tmp_path):
    surfaced, _ = live_files
    loop = tmp_path / "loop_partial.jsonl"
    _write_jsonl(loop, [_loop_row(i) for i in SOURCE_IDS[:2]])  # drop last
    with pytest.raises(vb.FixtureResolutionError, match=SOURCE_IDS[2]):
        vb.resolve_fixtures(surfaced, loop)


# ── calls-log binding check (prereg Common: calls-log isolation) ─────────


def test_bind_promotion_site_refuses_wrong_binding(tmp_path, monkeypatch):
    import orchestrator.finding_promotion as fp
    monkeypatch.setenv("LOOP_V0_CALLS_LOG", "sentinel")
    monkeypatch.setattr(fp, "CALLS_LOG_PATH", "/somewhere/else.jsonl")
    with pytest.raises(vb.CallsLogBindingError, match="imported before"):
        vb.bind_promotion_site(str(tmp_path / "arm.calls.jsonl"))


def test_bind_promotion_site_accepts_matching_binding(tmp_path, monkeypatch):
    import orchestrator.finding_promotion as fp
    want = str(tmp_path / "arm.calls.jsonl")
    monkeypatch.setenv("LOOP_V0_CALLS_LOG", "sentinel")
    monkeypatch.setattr(fp, "CALLS_LOG_PATH", want)
    import os
    assert vb.bind_promotion_site(want) is fp
    assert os.environ["LOOP_V0_CALLS_LOG"] == want


# ── fake site: the ONE seam run_arm calls ────────────────────────────────


class FakeFP:
    """Stands in for the bound finding_promotion module. Each vote appends
    calls-log rows exactly in the site's record shape (completion / usage /
    max_tokens / caller_tag / parent_request_id) then returns its scripted
    tally — so the driver's calls-log-based criteria paths run for real."""

    def __init__(self, calls_log: Path, tallies: list[dict],
                 rows_per_skeptic: int = 4, empty_at_cap_for: set[str] = ()):
        self.calls_log = Path(calls_log)
        self.tallies = list(tallies)
        self.rows_per_skeptic = rows_per_skeptic
        self.empty_at_cap_for = set(empty_at_cap_for)
        self.seen_kwargs: list[dict] = []
        self._i = 0

    def _claim_text(self, row):
        return row["hypothesis"]["text"]

    def _adversarial_vote(self, row, claim, *, n_skeptics, backend,
                          parent_request_id):
        self.seen_kwargs.append({
            "iteration_id": row["iteration_id"], "claim": claim,
            "n_skeptics": n_skeptics, "backend": backend,
            "parent_request_id": parent_request_id})
        iid = row["iteration_id"]
        with open(self.calls_log, "a") as fh:
            for s in range(1, n_skeptics + 1):
                for turn in range(self.rows_per_skeptic):
                    at_cap = (iid in self.empty_at_cap_for
                              and s == 2 and turn == 0)
                    fh.write(json.dumps({
                        "timestamp": "2026-08-18T00:00:00Z",
                        "request_id": f"{iid}-s{s}-t{turn}",
                        "completion": "" if at_cap else '{"verdict":"stands"}',
                        "usage": {"input_tokens": 10,
                                  "output_tokens": 6144 if at_cap else 100},
                        "max_tokens": 6144,
                        "caller_tag": f"subagent.finding_skeptic_{s}",
                        "parent_request_id": parent_request_id,
                    }) + "\n")
        tally = self.tallies[self._i]
        self._i += 1
        if isinstance(tally, Exception):
            raise tally
        return tally


def _tally(n_voting=3, n_refuted=1, survived=True, qwen_failures=0):
    return {"n_voting": n_voting, "n_refuted": n_refuted,
            "adversarial_margin": n_voting - 2 * n_refuted,
            "survived": survived, "qwen_failures": qwen_failures,
            "refutation_summaries": [], "quorum": 2}


def _cfg(tmp_path, **kw):
    defaults = dict(
        arm_label="testarm", model_label="qwen-test", image="img:tag",
        calls_log_path=str(tmp_path / "testarm.calls.jsonl"),
        bench_id="qwen-ab-3b-testarm-deadbeef",
        surfaced_sha256="s" * 64, loop_memory_sha256="l" * 64,
        served_models={"ids": ["qwen-test"], "error": None},
    )
    defaults.update(kw)
    return vb.RunConfig(**defaults)


# ── criteria: YES fixture (everything passes) ────────────────────────────


def test_run_arm_yes_fixture_all_gates_pass(tmp_path, live_files):
    fixtures, _, _ = vb.resolve_fixtures(*live_files)
    cfg = _cfg(tmp_path)
    fp = FakeFP(cfg.calls_log_path, [_tally(), _tally(), _tally()])
    art = vb.run_arm(fp, fixtures, cfg)

    # Seam pinned by the prereg: exact kwargs, loop_memory row, claim text.
    assert [k["iteration_id"] for k in fp.seen_kwargs] == SOURCE_IDS
    for k in fp.seen_kwargs:
        assert k["backend"] == "vllm-qwen"
        assert k["n_skeptics"] == 3
        assert k["parent_request_id"] == cfg.bench_id
        assert k["claim"].startswith("hypothesis text for ")

    crit = art["criteria"]
    assert crit["liveness"]["fraction"] == 1.0
    assert crit["liveness"]["slots_run"] == 9
    assert crit["liveness"]["pass"] is True
    assert all(v["pass"] for v in crit["liveness"]["per_candidate"].values())
    assert crit["empty_at_cap"]["count_whole_arm_log"] == 0
    assert crit["empty_at_cap"]["pass"] is True
    cpv = crit["reported_non_gating"]["calls_per_vote"]
    assert cpv["per_candidate"] == {f: 12 for f in EXPECTED}
    assert cpv["baseline_d070"] == 12.5
    vh = crit["reported_non_gating"]["votes_vs_history"]
    assert all(v["survived_agrees"] is False for v in vh)  # hist False, now True
    assert crit["ab_gate"]["evaluable_single_arm"] is False
    assert crit["ab_gate"]["this_arm"]["candidates_completed"] == EXPECTED
    assert art["completed"] is True and art["time_cap_hit"] is False
    assert art["errors"] == []
    prov = art["provenance"]
    assert prov["image"] == "img:tag"
    assert prov["calls_log_path"] == cfg.calls_log_path
    assert [f["finding_id"] for f in prov["fixtures"]] == EXPECTED
    assert prov["vote_budget"] == vb.VOTE_BUDGET

    out = vb.write_artifact(art, tmp_path / "out" / "3b_testarm_x.json")
    assert json.loads(out.read_text())["stage"] == "3b"


# ── criteria: NO fixture (liveness + empty-at-cap both fail honestly) ────


def test_run_arm_no_fixture_gates_fail(tmp_path, live_files):
    fixtures, _, _ = vb.resolve_fixtures(*live_files)
    cfg = _cfg(tmp_path)
    # A stale empty-at-cap row from a PREVIOUS run in the same arm log:
    # counted in the whole-arm-log gate, excluded from the run-scoped count.
    Path(cfg.calls_log_path).write_text(json.dumps({
        "completion": "", "usage": {"output_tokens": 4096},
        "max_tokens": 4096, "caller_tag": "subagent.finding_skeptic_1",
        "parent_request_id": "some-other-run"}) + "\n")
    fp = FakeFP(
        cfg.calls_log_path,
        [_tally(), _tally(n_voting=2, qwen_failures=1, survived=False),
         _tally()],
        empty_at_cap_for={SOURCE_IDS[1]},
    )
    art = vb.run_arm(fp, fixtures, cfg)

    crit = art["criteria"]
    assert crit["liveness"]["fraction"] == round(8 / 9, 4)
    assert crit["liveness"]["pass"] is False
    flags = crit["liveness"]["per_candidate"]
    assert flags[EXPECTED[0]]["pass"] is True
    assert flags[EXPECTED[1]] == {"qwen_failures": 1, "pass": False}
    assert flags[EXPECTED[2]]["pass"] is True
    assert crit["empty_at_cap"]["count_whole_arm_log"] == 2
    assert crit["empty_at_cap"]["count_this_run"] == 1
    assert crit["empty_at_cap"]["pass"] is False
    hit_tags = {h["caller_tag"] for h in crit["empty_at_cap"]["rows"]}
    assert hit_tags == {"subagent.finding_skeptic_1",
                        "subagent.finding_skeptic_2"}
    # Reported, not gated: the arm still completed all 3 candidates.
    assert art["completed"] is True


def test_empty_at_cap_definition_edges():
    rows = [
        # hit: empty completion AND output_tokens == max_tokens
        {"completion": "", "usage": {"output_tokens": 6144},
         "max_tokens": 6144, "caller_tag": "t"},
        # whitespace-only completion is empty too
        {"completion": "  \n", "usage": {"output_tokens": 100},
         "max_tokens": 100},
        # empty but UNDER cap -> not a hit
        {"completion": "", "usage": {"output_tokens": 99}, "max_tokens": 6144},
        # at cap but non-empty -> not a hit
        {"completion": "text", "usage": {"output_tokens": 6144},
         "max_tokens": 6144},
        # no max_tokens field -> cannot be at-cap
        {"completion": "", "usage": {"output_tokens": 512}},
    ]
    hits = vb.empty_at_cap_rows(rows)
    assert len(hits) == 2
    assert hits[0]["max_tokens"] == 6144 and hits[1]["max_tokens"] == 100


def test_zero_completed_candidates_is_not_a_vacuous_pass():
    crit = vb.evaluate_criteria([], [], "bench-x")
    assert crit["liveness"]["pass"] is False
    assert crit["liveness"]["fraction"] is None
    assert crit["empty_at_cap"]["pass"] is False


def test_candidate_exception_is_recorded_not_swallowed(tmp_path, live_files):
    fixtures, _, _ = vb.resolve_fixtures(*live_files)
    cfg = _cfg(tmp_path)
    fp = FakeFP(cfg.calls_log_path,
                [_tally(), RuntimeError("backend exploded"), _tally()])
    art = vb.run_arm(fp, fixtures, cfg)
    st = {c["finding_id"]: c["status"] for c in art["candidates"]}
    assert st == {EXPECTED[0]: "completed", EXPECTED[1]: "error",
                  EXPECTED[2]: "completed"}
    assert art["errors"] == [f"{EXPECTED[1]}: RuntimeError: backend exploded"]
    assert art["completed"] is False
    # Criteria evaluate over the candidates that DID complete.
    assert art["criteria"]["liveness"]["slots_run"] == 6


# ── time cap: partials recorded (rule 7) ─────────────────────────────────


class FakeClock:
    def __init__(self, step):
        self.step, self.t = step, -step

    def __call__(self):
        self.t += self.step
        return self.t


def test_time_cap_partial_recording(tmp_path, live_files):
    fixtures, _, _ = vb.resolve_fixtures(*live_files)
    cfg = _cfg(tmp_path, time_cap_s=350.0)
    fp = FakeFP(cfg.calls_log_path, [_tally(), _tally(), _tally()])
    # clock calls: t0=0; c1 cap-check=100 (<350, runs), t_start=200, end=300;
    # c2 cap-check=400 (>=350) -> cap hit; total=500.
    art = vb.run_arm(fp, fixtures, cfg, clock=FakeClock(100.0))

    assert art["time_cap_hit"] is True
    assert art["completed"] is False
    st = [(c["finding_id"], c["status"]) for c in art["candidates"]]
    assert st == [(EXPECTED[0], "completed"),
                  (EXPECTED[1], "not_run_time_cap"),
                  (EXPECTED[2], "not_run_time_cap")]
    assert len(fp.seen_kwargs) == 1  # the vote after the cap never ran
    # Completed candidates are the arm's result: criteria cover candidate 1.
    crit = art["criteria"]
    assert crit["liveness"]["slots_run"] == 3
    assert crit["ab_gate"]["this_arm"]["candidates_completed"] == [EXPECTED[0]]
    assert art["candidates"][0]["wall_s"] == 100.0


# ── smoke --limit ────────────────────────────────────────────────────────


def test_limit_runs_first_n_fixtures_only(tmp_path, live_files):
    fixtures, _, _ = vb.resolve_fixtures(*live_files)
    cfg = _cfg(tmp_path, limit=1)
    fp = FakeFP(cfg.calls_log_path, [_tally()])
    art = vb.run_arm(fp, fixtures, cfg)
    assert [c["finding_id"] for c in art["candidates"]] == [EXPECTED[0]]
    assert art["completed"] is True
    assert art["provenance"]["limit"] == 1
    assert art["provenance"]["planned_finding_ids"] == [EXPECTED[0]]
    # The FULL resolved fixture set stays in provenance even on a smoke.
    assert [f["finding_id"] for f in art["provenance"]["fixtures"]] == EXPECTED


# ── MOCK_LLM refusal (exit 2, before any binding or write) ──────────────


def test_cli_refuses_under_mock_llm(monkeypatch, capsys):
    monkeypatch.setenv("MOCK_LLM", "1")
    monkeypatch.setenv("LOOP_V0_CALLS_LOG", "sentinel-unchanged")
    rc = vb.main(["--arm-label", "smoke", "--model", "m", "--image", "img"])
    assert rc == 2
    assert "REFUSE" in capsys.readouterr().out
    import os
    # Refusal fires before the calls-log binding touches the environment.
    assert os.environ["LOOP_V0_CALLS_LOG"] == "sentinel-unchanged"
