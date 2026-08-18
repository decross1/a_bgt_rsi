"""Tests for the stage-3c/3d Qwen A/B battery drivers (prereg §3c/§3d).

Hermetic under MOCK_LLM=1: every site seam (start_two_voice_session /
two_voice_turn / restate_attack / strip / extract) is injected as a fake;
no wrapper, backend, or network import happens. The driver modules are
loaded BY FILE PATH (not `import bench.qwen_ab_3bcd...`) so these tests
are import-guarded against the parallel 3b builder owning
bench/qwen_ab_3bcd/__init__.py — they pass whether or not it exists yet.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


twovoice = _load("qwen_ab_3bcd_twovoice_battery",
                 "bench/qwen_ab_3bcd/twovoice_battery.py")
restate = _load("qwen_ab_3bcd_restate_battery",
                "bench/qwen_ab_3bcd/restate_battery.py")

SERVED_OK = {"ids": ["m"], "error": None, "url": "http://x/v1/models"}


# --------------------------------------------------------------------------- #
# Shared helpers                                                              #
# --------------------------------------------------------------------------- #


def _extract(text):
    """Minimal balanced-brace JSON-object extractor for tests (stands in for
    workers.novelty_skeptic._extract_json_object at the injected seam)."""
    try:
        start = text.index("{")
    except (ValueError, AttributeError):
        return None
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _strip(text):
    """Fake strip_channel_markup: removes the <CH>...</CH> marker pair."""
    return text.replace("<CH>", "").replace("</CH>", "")


def _write_calls_log(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def _call_row(tag, completion, out_tokens, max_tokens, req="r"):
    return {"caller_tag": tag, "completion": completion,
            "usage": {"input_tokens": 10, "output_tokens": out_tokens},
            "max_tokens": max_tokens, "request_id": req}


def _surfaced_file(tmp_path: Path) -> Path:
    p = tmp_path / "surfaced_findings.jsonl"
    rows = [{"finding_id": fid, "source_iteration_id": f"iter-{i}"}
            for i, fid in enumerate(twovoice.FINDING_IDS)]
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return p


def _cases_file(tmp_path: Path, ids=None) -> Path:
    p = tmp_path / "cases.jsonl"
    rows = [{"case_id": cid, "hypothesis": f"hyp for {cid}",
             "expected_novelty": "rediscovery", "expected_critic": "refuted"}
            for cid in (ids if ids is not None else restate.CASE_IDS)]
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return p


class _FakeSession:
    """Injectable start/turn pair for the 3c battery."""

    def __init__(self, replies_by_finding, clock_box=None, advance=0.0):
        self.replies = replies_by_finding
        self.clock_box = clock_box
        self.advance = advance
        self.turn_calls = []

    def start(self, finding_id, **kwargs):
        return {"session_id": f"fs-{finding_id[-3:]}", "finding": {},
                "stances": ["defender", "attacker"]}

    def turn(self, finding_id, session_id, user_msg, *, addressee,
             sessions_root):
        self.turn_calls.append((finding_id, session_id, user_msg, addressee))
        if self.clock_box is not None:
            self.clock_box[0] += self.advance
        return {"turn_index": 1, "addressee": addressee, "warning": None,
                "capped": False,
                "replies": [{"stance": "attacker",
                             "reply": self.replies[finding_id],
                             "request_id": f"req-{finding_id[-3:]}"}]}


# --------------------------------------------------------------------------- #
# 3c — twovoice_battery                                                       #
# --------------------------------------------------------------------------- #


def test_3c_mock_llm_refusal(monkeypatch, capsys):
    monkeypatch.setenv("MOCK_LLM", "1")
    assert twovoice.main([]) == 2
    assert "MOCK_LLM" in capsys.readouterr().out


def test_3c_snapshot_resolves_and_hashes(tmp_path):
    p = _surfaced_file(tmp_path)
    snap = twovoice.snapshot_surfaced(p)
    assert snap["sha256"] == hashlib.sha256(p.read_bytes()).hexdigest()
    assert [f["finding_id"] for f in snap["findings"]] == list(
        twovoice.FINDING_IDS)
    assert snap["findings"][0]["source_iteration_id"] == "iter-0"


def test_3c_snapshot_fail_closed_on_missing_pin(tmp_path):
    p = tmp_path / "surfaced_findings.jsonl"
    p.write_text(json.dumps({"finding_id": twovoice.FINDING_IDS[0]}) + "\n")
    with pytest.raises(RuntimeError, match="refusing to guess"):
        twovoice.snapshot_surfaced(p)


def test_3c_empty_at_cap_definition():
    tag = twovoice.ATTACKER_TAG
    rows = [
        _call_row(tag, "", 4096, 4096),          # offender: empty AND at cap
        _call_row(tag, "   \n", 4096, 4096),     # whitespace-only == empty
        _call_row(tag, "", 1200, 4096),          # empty but BELOW cap: no
        _call_row(tag, "full answer", 4096, 4096),  # at cap but non-empty: no
        _call_row("other_tag", "", 4096, 4096),  # other tag: filtered out
    ]
    offenders = twovoice.empty_at_cap(rows, tag)
    assert [o["row_index"] for o in offenders] == [0, 1]
    # Unfiltered sees the other-tag offender too.
    assert len(twovoice.empty_at_cap(rows)) == 3


def test_3c_run_arm_all_gates_pass(tmp_path):
    surfaced = _surfaced_file(tmp_path)
    calls_log = tmp_path / "arm.calls.jsonl"
    _write_calls_log(calls_log, [
        _call_row(twovoice.ATTACKER_TAG, "objection text", 900, 4096),
        _call_row(twovoice.ATTACKER_TAG, "objection text", 1100, 4096),
        _call_row(twovoice.ATTACKER_TAG, "objection text", 800, 4096),
        # An OTHER-tag empty-at-cap row must NOT trip the 3c gate (iii).
        _call_row("finding_promotion_skeptic", "", 6144, 6144),
    ])
    fake = _FakeSession({fid: "<CH>strong, grounded objection</CH>"
                         for fid in twovoice.FINDING_IDS})
    art = twovoice.run_arm(
        arm="m", image="img@sha256:abc", endpoint="http://x/v1",
        start_fn=fake.start, turn_fn=fake.turn, strip_fn=_strip,
        calls_log_path=str(calls_log), served_models=SERVED_OK,
        sessions_root=tmp_path / "sessions", surfaced_path=surfaced,
        loop_memory_path=tmp_path / "loop_memory.jsonl")
    gates = art["criteria"]["gates"]
    assert gates["non_empty_visible_3of3"]["pass"] is True
    assert gates["zero_fail_open"]["pass"] is True
    assert gates["empty_at_cap_zero"]["pass"] is True
    assert art["criteria"]["all_pass"] is True
    assert art["completed"] is True and art["time_cap"]["hit"] is False
    # Every turn used the ONE pinned opening message, attacker-addressed.
    assert all(c[2] == twovoice.OPENING_USER_MSG and c[3] == "attacker"
               for c in fake.turn_calls)
    prov = art["provenance"]
    assert prov["opening_user_msg"] == twovoice.OPENING_USER_MSG
    assert prov["opening_user_msg_sha256"] == hashlib.sha256(
        twovoice.OPENING_USER_MSG.encode()).hexdigest()
    assert prov["surfaced_findings"]["sha256"] == hashlib.sha256(
        surfaced.read_bytes()).hexdigest()


def test_3c_run_arm_fail_paths(tmp_path):
    """Fail-open string + empty-visible reply + an empty-at-cap attacker row:
    every gate fails, and the gates stay INDEPENDENT (a fail-open reply still
    counts as visible content for gate (i))."""
    surfaced = _surfaced_file(tmp_path)
    calls_log = tmp_path / "arm.calls.jsonl"
    _write_calls_log(calls_log, [
        _call_row(twovoice.ATTACKER_TAG, "ok", 900, 4096),
        _call_row(twovoice.ATTACKER_TAG, "", 4096, 4096),  # think-block starve
    ])
    f1, f2, f3 = twovoice.FINDING_IDS
    fake = _FakeSession({
        f1: "<CH>grounded objection</CH>",
        f2: ("[attacker unavailable: RuntimeError: boom] No grounded "
             "response could be produced this turn; this is NOT a "
             "concession or an endorsement of the claim."),
        f3: "<CH></CH>",                      # strips to empty (starved)
    })
    art = twovoice.run_arm(
        arm="m", image="img", endpoint="http://x/v1",
        start_fn=fake.start, turn_fn=fake.turn, strip_fn=_strip,
        calls_log_path=str(calls_log), served_models=SERVED_OK,
        sessions_root=tmp_path / "sessions", surfaced_path=surfaced,
        loop_memory_path=tmp_path / "loop_memory.jsonl")
    fx = {f["finding_id"]: f for f in art["fixtures"]}
    assert fx[f2]["fail_open"] is True
    assert fx[f2]["non_empty_visible"] is True   # gates independent
    assert fx[f3]["non_empty_visible"] is False
    gates = art["criteria"]["gates"]
    assert gates["non_empty_visible_3of3"]["pass"] is False
    assert gates["non_empty_visible_3of3"]["observed"] == "2/3"
    assert gates["zero_fail_open"]["pass"] is False
    assert gates["zero_fail_open"]["observed"] == 1
    assert gates["empty_at_cap_zero"]["pass"] is False
    assert gates["empty_at_cap_zero"]["observed"] == 1
    assert art["criteria"]["all_pass"] is False


def test_3c_run_arm_error_recorded_not_masked(tmp_path):
    surfaced = _surfaced_file(tmp_path)

    def boom_start(finding_id, **kwargs):
        raise KeyError(f"no surfaced_finding {finding_id}")

    art = twovoice.run_arm(
        arm="m", image="img", endpoint="http://x/v1",
        start_fn=boom_start, turn_fn=None, strip_fn=_strip,
        calls_log_path=str(tmp_path / "none.jsonl"), served_models=SERVED_OK,
        sessions_root=tmp_path / "sessions", surfaced_path=surfaced,
        loop_memory_path=tmp_path / "loop_memory.jsonl")
    assert all(f["status"] == "error" for f in art["fixtures"])
    assert "KeyError" in art["fixtures"][0]["error"]
    assert art["criteria"]["all_pass"] is False


def test_3c_time_cap_partial_recorded(tmp_path):
    surfaced = _surfaced_file(tmp_path)
    clock_box = [0.0]
    fake = _FakeSession({fid: "<CH>ok</CH>" for fid in twovoice.FINDING_IDS},
                        clock_box=clock_box, advance=1000.0)  # > 900 s cap
    art = twovoice.run_arm(
        arm="m", image="img", endpoint="http://x/v1",
        start_fn=fake.start, turn_fn=fake.turn, strip_fn=_strip,
        calls_log_path=str(tmp_path / "none.jsonl"), served_models=SERVED_OK,
        sessions_root=tmp_path / "sessions", surfaced_path=surfaced,
        loop_memory_path=tmp_path / "loop_memory.jsonl",
        clock=lambda: clock_box[0])
    assert art["time_cap"]["hit"] is True
    assert art["time_cap"]["fixtures_run"] == 1
    assert [s["finding_id"] for s in art["skipped"]] == list(
        twovoice.FINDING_IDS[1:])
    assert all(s["reason"] == "time_cap" for s in art["skipped"])
    assert art["completed"] is False
    # A partial can never satisfy the 3/3 gate (rule 4 — no coercion).
    assert art["criteria"]["gates"]["non_empty_visible_3of3"]["pass"] is False


# --------------------------------------------------------------------------- #
# 3d — restate_battery                                                        #
# --------------------------------------------------------------------------- #


def _fake_attack(calls_log: Path, *, canonical, judge_completion,
                 verdict="inconclusive", clock_box=None, advance=0.0):
    """Build a restate_attack stand-in that appends site-shaped rows to the
    calls log (canonicalize always; judge only when judge_completion is not
    None) and returns the frozen result shape."""

    def attack_fn(*, hypothesis_text, iteration_id, backend,
                  novelty_top_neighbor_id):
        assert iteration_id is None and backend == "vllm-qwen"
        assert novelty_top_neighbor_id is None
        rows = [_call_row(restate.CANON_TAG,
                          '{"canonical_statement": "c", "concept_names": []}',
                          150, 3072)]
        if judge_completion is not None:
            rows.append(_call_row(restate.JUDGE_TAG, judge_completion,
                                  200, 3072))
        with open(calls_log, "a") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        if clock_box is not None:
            clock_box[0] += advance
        return {"restate_verdict": verdict, "rationale": "r",
                "restating_doc_id": None, "canonical_statement": canonical,
                "backend": "vllm-qwen", "model": "m-v1"}

    return attack_fn


def test_3d_mock_llm_refusal(monkeypatch, capsys):
    monkeypatch.setenv("MOCK_LLM", "1")
    assert restate.main([]) == 2
    assert "MOCK_LLM" in capsys.readouterr().out


def test_3d_resolve_cases_fail_closed(tmp_path):
    cases, _sha = restate.load_cases(
        _cases_file(tmp_path, ids=restate.CASE_IDS[:-1]))
    with pytest.raises(RuntimeError, match="refusing to guess"):
        restate.resolve_cases(cases)


def test_3d_judge_parse_paths():
    ok = '{"restate_verdict": "restated", "restating_doc_id": "d1"}'
    assert restate.judge_parse(ok, _extract, _strip) == "restated"
    # Markup-wrapped JSON parses via the strip fallback.
    wrapped = "<CH>" + ok + "</CH>"
    assert restate.judge_parse(
        wrapped, lambda t: None if "<CH>" in t else _extract(t),
        _strip) == "restated"
    # Off-enum verdict and JSON-free text both fail the parse.
    assert restate.judge_parse('{"restate_verdict": "maybe"}',
                               _extract, _strip) is None
    assert restate.judge_parse("no json here", _extract, _strip) is None
    assert restate.judge_parse("", _extract, _strip) is None


def test_3d_run_arm_all_gates_pass(tmp_path):
    cases_path = _cases_file(tmp_path)
    calls_log = tmp_path / "arm.calls.jsonl"
    attack_fn = _fake_attack(
        calls_log, canonical="In the ultimatum game, responders reject.",
        judge_completion=('reasoning... {"restate_verdict": "restated", '
                          '"rationale": "x", "restating_doc_id": "d1"}'),
        verdict="restated")
    art = restate.run_arm(
        arm="m", image="img@sha256:abc", endpoint="http://x/v1",
        attack_fn=attack_fn, extract_fn=_extract, strip_fn=_strip,
        calls_log_path=str(calls_log), served_models=SERVED_OK,
        cases_path=cases_path, restate_max_tokens_module=3072)
    gates = art["criteria"]["gates"]
    assert gates["canonicalize_nonnull_4of4"]["pass"] is True
    assert gates["canonicalize_nonnull_4of4"]["observed"] == "4/4"
    assert gates["judge_log_parse_4of4"]["pass"] is True
    assert art["criteria"]["all_pass"] is True
    assert art["completed"] is True
    # Reported non-gating: utilization vs the 3072 cap, per leg.
    util = art["criteria"]["reported_non_gating"]["token_utilization_vs_cap"]
    assert util[restate.JUDGE_TAG]["n"] == 4
    assert util[restate.JUDGE_TAG]["max"] == pytest.approx(200 / 3072,
                                                           abs=1e-4)
    assert util[restate.CANON_TAG]["max"] == pytest.approx(150 / 3072,
                                                           abs=1e-4)
    assert art["provenance"]["cases_sha256"] == hashlib.sha256(
        cases_path.read_bytes()).hexdigest()
    assert art["provenance"]["case_ids"] == list(restate.CASE_IDS)


def test_3d_gates_measured_from_log_not_failopen_return(tmp_path):
    """The return fail-opens to in-enum 'inconclusive' with a null
    canonical_statement — the exact shape that could never gate. Both gates
    must FAIL: (i) from the null canonical, (ii) from the LOG (garbage judge
    completion), never from the in-enum return."""
    cases_path = _cases_file(tmp_path)
    calls_log = tmp_path / "arm.calls.jsonl"
    attack_fn = _fake_attack(
        calls_log, canonical=None,
        judge_completion="the model rambled; no JSON object at all",
        verdict="inconclusive")   # in-enum! must NOT satisfy gate (ii)
    art = restate.run_arm(
        arm="m", image="img", endpoint="http://x/v1",
        attack_fn=attack_fn, extract_fn=_extract, strip_fn=_strip,
        calls_log_path=str(calls_log), served_models=SERVED_OK,
        cases_path=cases_path)
    gates = art["criteria"]["gates"]
    assert gates["canonicalize_nonnull_4of4"]["pass"] is False
    assert gates["canonicalize_nonnull_4of4"]["observed"] == "0/4"
    assert gates["judge_log_parse_4of4"]["pass"] is False
    assert gates["judge_log_parse_4of4"]["observed"] == "0/4"
    assert art["criteria"]["all_pass"] is False
    # The returns were all in-enum — proof the gate ignored them.
    assert all(f["restate_verdict"] == "inconclusive"
               for f in art["fixtures"])
    assert all(f["judge_rows_in_log"] == 1 for f in art["fixtures"])


def test_3d_missing_judge_row_fails_gate(tmp_path):
    """No judge row in the log at all (e.g. the judge call never happened)
    fails gate (ii) even when the return looks healthy."""
    cases_path = _cases_file(tmp_path)
    calls_log = tmp_path / "arm.calls.jsonl"
    attack_fn = _fake_attack(calls_log, canonical="c",
                             judge_completion=None,   # no judge row written
                             verdict="not_restated")  # in-enum return
    art = restate.run_arm(
        arm="m", image="img", endpoint="http://x/v1",
        attack_fn=attack_fn, extract_fn=_extract, strip_fn=_strip,
        calls_log_path=str(calls_log), served_models=SERVED_OK,
        cases_path=cases_path)
    assert art["criteria"]["gates"]["canonicalize_nonnull_4of4"]["pass"] is True
    assert art["criteria"]["gates"]["judge_log_parse_4of4"]["pass"] is False
    assert all(f["judge_rows_in_log"] == 0 for f in art["fixtures"])


def test_3d_attack_exception_recorded_not_masked(tmp_path):
    cases_path = _cases_file(tmp_path)

    def boom(**kwargs):
        raise RuntimeError("backend down")

    art = restate.run_arm(
        arm="m", image="img", endpoint="http://x/v1",
        attack_fn=boom, extract_fn=_extract, strip_fn=_strip,
        calls_log_path=str(tmp_path / "arm.calls.jsonl"),
        served_models=SERVED_OK, cases_path=cases_path)
    assert all(f["status"] == "error" for f in art["fixtures"])
    assert "RuntimeError" in art["fixtures"][0]["error"]
    assert art["criteria"]["all_pass"] is False


def test_3d_time_cap_partial_recorded(tmp_path):
    cases_path = _cases_file(tmp_path)
    calls_log = tmp_path / "arm.calls.jsonl"
    clock_box = [0.0]
    attack_fn = _fake_attack(
        calls_log, canonical="c",
        judge_completion='{"restate_verdict": "restated", '
                         '"restating_doc_id": "d1"}',
        verdict="restated", clock_box=clock_box, advance=1000.0)
    art = restate.run_arm(
        arm="m", image="img", endpoint="http://x/v1",
        attack_fn=attack_fn, extract_fn=_extract, strip_fn=_strip,
        calls_log_path=str(calls_log), served_models=SERVED_OK,
        cases_path=cases_path, clock=lambda: clock_box[0])
    # 30-min cap, 1000 s per case: cases 1+2 run, 3+4 skipped.
    assert art["time_cap"]["hit"] is True
    assert art["time_cap"]["cases_run"] == 2
    assert [s["case_id"] for s in art["skipped"]] == list(restate.CASE_IDS[2:])
    assert all(s["reason"] == "time_cap" for s in art["skipped"])
    assert art["completed"] is False
    # A partial can never satisfy the 4/4 gates (rule 4 — no coercion).
    assert art["criteria"]["gates"]["canonicalize_nonnull_4of4"]["pass"] is False
    assert art["criteria"]["gates"]["judge_log_parse_4of4"]["pass"] is False
