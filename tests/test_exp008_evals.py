"""Offline tests for exp008 quality evals (novelty agreement + tool-call
adherence). MOCK_LLM-safe: no live model call, no production endpoint, no
writes to run_state/ or the production calls log.

The novelty eval is driven with a STUBBED classifier (same signature as the
real worker) so we exercise the eval's staging / scoring / aggregation
without a model. The tool-call eval is driven with a STUBBED caller returning
canned completions so we exercise the real bridging parser's accept/reject
counting.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

eval_novelty = importlib.import_module("experiments.exp008_qat_eval.eval_novelty")
eval_toolcall = importlib.import_module("experiments.exp008_qat_eval.eval_toolcall")


@pytest.fixture
def scratch_cache(tmp_path, monkeypatch):
    """Redirect the iteration cache to a tmp dir so the eval never writes
    under run_state/."""
    from orchestrator import iteration_cache

    monkeypatch.setattr(iteration_cache, "CACHE_ROOT", tmp_path / "iter_cache")
    return tmp_path


def _fixed_class_classifier(predicted_class):
    """Return a stub with novelty_classify's signature that always predicts
    `predicted_class`, regardless of hypothesis."""

    def _stub(hypothesis_text, iteration_id, **kwargs):
        return {
            "status": "passed",
            "result": {
                "class": predicted_class,
                "rationale": "stub",
                "top_neighbor_id": None,
            },
            "errors": [],
            "wrapper_request_id": "stub-rid",
            "parent_request_id": kwargs.get("parent_request_id"),
        }

    return _stub


def test_novelty_eval_over_real_fixtures_shape(scratch_cache, tmp_path):
    """eval_novelty over ALL real fixtures with a stubbed classifier returns
    an agreement rate in [0,1] and a confusion matrix of the right shape."""
    fixtures = eval_novelty.load_fixtures(eval_novelty.FIXTURES_DIR)
    assert len(fixtures) == 10  # the calibration set

    runs_dir = tmp_path / "runs"
    metrics = eval_novelty.run_eval(
        arm="stub-novel",
        classifier=_fixed_class_classifier("novel"),
        fixtures=fixtures,
        model=None,
        runs_dir=runs_dir,
    )

    # Agreement rate is a probability.
    assert 0.0 <= metrics["agreement_rate"] <= 1.0
    assert metrics["n"] == 10

    # Confusion matrix spans the full 4-class output space on both axes.
    conf = metrics["confusion"]
    assert set(conf) == set(eval_novelty.CLASSES)
    for gt in eval_novelty.CLASSES:
        assert set(conf[gt]) == set(eval_novelty.CLASSES)

    # Row sums of the confusion matrix account for every fixture.
    total = sum(conf[gt][pred] for gt in conf for pred in conf[gt])
    assert total == 10

    # Calibration error is a non-negative mean absolute error.
    assert metrics["calibration_error_mae"] >= 0.0

    # One JSONL row per (arm, fixture) was written.
    out = runs_dir / "novelty_stub-novel.jsonl"
    lines = [json.loads(ln) for ln in out.read_text().splitlines() if ln.strip()]
    assert len(lines) == 10
    assert {ln["fixture_id"] for ln in lines} == {f["id"] for f in fixtures}


def test_novelty_eval_agreement_is_correct_for_known_stub(scratch_cache, tmp_path):
    """An all-'rediscovery' stub agrees exactly on the well_known fixtures.
    The fixture set has 2 well_known entries (-> rediscovery), so agreement
    must be 2/10."""
    fixtures = eval_novelty.load_fixtures(eval_novelty.FIXTURES_DIR)
    n_wellknown = sum(1 for f in fixtures if f["ground_truth_tier"] == "well_known")
    assert n_wellknown == 2

    metrics = eval_novelty.run_eval(
        arm="stub-redisc",
        classifier=_fixed_class_classifier("rediscovery"),
        fixtures=fixtures,
        model=None,
        runs_dir=tmp_path / "runs",
    )
    assert metrics["agreement_rate"] == pytest.approx(n_wellknown / 10)
    # All predictions landed in the 'rediscovery' column.
    conf = metrics["confusion"]
    pred_total_redisc = sum(conf[gt]["rediscovery"] for gt in conf)
    assert pred_total_redisc == 10


def test_novelty_eval_one_fixture_smoke(scratch_cache, tmp_path):
    """A 1-fixture smoke runs clean and writes a single row."""
    fixtures = eval_novelty.load_fixtures(eval_novelty.FIXTURES_DIR, limit=1)
    assert len(fixtures) == 1

    runs_dir = tmp_path / "runs"
    metrics = eval_novelty.run_eval(
        arm="smoke",
        classifier=_fixed_class_classifier("novel"),
        fixtures=fixtures,
        model=None,
        runs_dir=runs_dir,
    )
    assert metrics["n"] == 1
    out = runs_dir / "novelty_smoke.jsonl"
    lines = [ln for ln in out.read_text().splitlines() if ln.strip()]
    assert len(lines) == 1


def test_toolcall_eval_counts_parseable_vs_not(tmp_path):
    """eval_toolcall counts parseable vs not correctly on canned completions:
    half the prompts get a valid inline tool_call, half get plain narration."""
    # Map prompt_id -> canned completion.
    inline = (
        'I will call the tool now.\n'
        '<|tool_call>call:retrieve_literature{hypothesis_text:<|"|>'
        'tft<|"|>,k:5}'
    )
    plain = "I think the answer is tit-for-tat, but I won't call any tool."
    canned = {
        "retrieve_literature": inline,
        "novelty_classify": inline,
        "hypothesize": plain,
        "critique": plain,
    }

    # Explicit 4-prompt subset (the default PROMPT_SET is now >=10) so this test
    # exercises the counting logic independent of the prompt-set size.
    prompts = [{"id": pid, "user": f"... {pid} ... Call the {pid} tool."}
               for pid in canned]

    def _stub_caller(messages, **kwargs):
        # Recover which prompt this is from the user message content.
        user = messages[-1]["content"]
        for pid in canned:
            if pid in user:
                return {"completion": canned[pid], "request_id": f"rid-{pid}"}
        return {"completion": plain, "request_id": "rid-default"}

    runs_dir = tmp_path / "runs"
    metrics = eval_toolcall.run_eval(
        arm="stub",
        caller=_stub_caller,
        prompts=prompts,
        backend=None,
        model=None,
        runs_dir=runs_dir,
    )
    assert metrics["n"] == 4
    assert metrics["adherent"] == 2
    assert metrics["adherence_rate"] == pytest.approx(0.5)

    out = runs_dir / "toolcall_stub.jsonl"
    rows = [json.loads(ln) for ln in out.read_text().splitlines() if ln.strip()]
    by_id = {r["prompt_id"]: r for r in rows}
    assert by_id["retrieve_literature"]["adherent"] is True
    assert by_id["retrieve_literature"]["n_tool_calls"] == 1
    assert by_id["hypothesize"]["adherent"] is False
    assert by_id["hypothesize"]["n_tool_calls"] == 0


def test_toolcall_is_parseable_accepts_native_serialized():
    """is_parseable_toolcall also accepts a natively-serialized OpenAI
    tool_calls array (the shape call_with_tools logs into completion)."""
    native = json.dumps(
        [
            {
                "id": "abc",
                "type": "function",
                "function": {"name": "retrieve_literature", "arguments": "{}"},
            }
        ]
    )
    adherent, n = eval_toolcall.is_parseable_toolcall({"completion": native})
    assert adherent is True
    assert n == 1

    adherent2, n2 = eval_toolcall.is_parseable_toolcall(
        {"completion": "just prose, no call"}
    )
    assert adherent2 is False
    assert n2 == 0


# ── analyze.py plumbing: drivers must emit {arm,metric,value} rows ──────────

analyze_mod = importlib.import_module("experiments.exp008_qat_eval.analyze")


def _read_metric_rows(runs_dir: Path) -> list[dict]:
    """Read every metrics_*.jsonl row the drivers wrote (the analyze-shaped
    rows), mirroring what analyze._load_rows globs at run time."""
    rows: list[dict] = []
    for p in sorted(runs_dir.glob("metrics_*.jsonl")):
        for ln in p.read_text().splitlines():
            if ln.strip():
                rows.append(json.loads(ln))
    return rows


def test_novelty_emits_analyze_metric_rows(scratch_cache, tmp_path):
    """run_eval writes a metrics_novelty_<arm>.jsonl that analyze.py can read:
    novelty_agreement (mean == agreement_rate) + calibration_error (mean ==
    calibration_error_mae), n == fixture count."""
    fixtures = eval_novelty.load_fixtures(eval_novelty.FIXTURES_DIR)
    runs_dir = tmp_path / "runs"
    metrics = eval_novelty.run_eval(
        arm="qat", classifier=_fixed_class_classifier("novel"),
        fixtures=fixtures, model=None, runs_dir=runs_dir,
    )
    rows = _read_metric_rows(runs_dir)
    agr = [r["value"] for r in rows if r["metric"] == "novelty_agreement"]
    cal = [r["value"] for r in rows if r["metric"] == "calibration_error"]
    assert len(agr) == 10 and len(cal) == 10
    assert sum(agr) / len(agr) == pytest.approx(metrics["agreement_rate"])
    assert sum(cal) / len(cal) == pytest.approx(metrics["calibration_error_mae"])
    # the rich audit file is unchanged (still exactly one row per fixture)
    rich = (runs_dir / "novelty_qat.jsonl").read_text().splitlines()
    assert len([ln for ln in rich if ln.strip()]) == 10


def test_toolcall_prompt_set_meets_min_sample():
    """The default prompt set must be >=10 so tool_call_adherence clears
    analyze.py's min_sample decision-eligibility gate."""
    assert len(eval_toolcall.PROMPT_SET) >= analyze_mod._DEFAULT_CONFIG["min_sample"]
    # prompt ids are unique (no accidental dup rows)
    ids = [p["id"] for p in eval_toolcall.PROMPT_SET]
    assert len(ids) == len(set(ids))


def test_toolcall_emits_analyze_metric_rows(tmp_path):
    """run_eval over the full prompt set writes >=10 tool_call_adherence rows
    whose mean equals the reported adherence_rate."""
    def _adherent_caller(messages, **kwargs):
        inline = ('<|tool_call>call:novelty_classify{hypothesis_text:<|"|>'
                  'x<|"|>}')
        return {"completion": inline, "request_id": "rid"}

    runs_dir = tmp_path / "runs"
    metrics = eval_toolcall.run_eval(
        arm="qat", caller=_adherent_caller, backend=None, model=None,
        runs_dir=runs_dir,
    )
    rows = [r for r in _read_metric_rows(runs_dir)
            if r["metric"] == "tool_call_adherence"]
    assert len(rows) >= 10
    vals = [r["value"] for r in rows]
    assert sum(vals) / len(vals) == pytest.approx(metrics["adherence_rate"])


def test_register_arm_backend_refuses_8000_unless_reference_pin():
    """:8000 is refused by default; the reference path permits it ONLY for the
    pin arm. A candidate arm under --reference is still refused (so a mistyped
    --arm can't route candidate traffic at production)."""
    for mod in (eval_novelty, eval_toolcall):
        # default: production endpoint refused
        with pytest.raises(ValueError):
            mod._register_arm_backend("http://localhost:8000/v1", "m")
        # --reference but a CANDIDATE arm label: still refused (must be pin)
        with pytest.raises(ValueError):
            mod._register_arm_backend(
                "http://localhost:8000/v1", "m",
                allow_production=True, arm="qat",
            )
        # --reference + arm pin: permitted (registers a read-only backend)
        mod._register_arm_backend(
            "http://localhost:8000/v1", "m", allow_production=True, arm="pin"
        )


def test_drivers_to_analyze_yields_a_decision_not_insufficient(scratch_cache, tmp_path):
    """End-to-end: the metric rows both drivers write, for a pin and a qat arm,
    feed analyze.py to a real verdict (not INSUFFICIENT) with non-empty
    per-metric deltas — i.e. the plumbing gap is closed."""
    fixtures = eval_novelty.load_fixtures(eval_novelty.FIXTURES_DIR)
    runs_dir = tmp_path / "runs"

    def _adherent_caller(messages, **kwargs):
        inline = ('<|tool_call>call:novelty_classify{hypothesis_text:<|"|>'
                  'x<|"|>}')
        return {"completion": inline, "request_id": "rid"}

    for arm in ("pin", "qat"):
        eval_novelty.run_eval(
            arm=arm, classifier=_fixed_class_classifier("novel"),
            fixtures=fixtures, model=None, runs_dir=runs_dir,
        )
        eval_toolcall.run_eval(
            arm=arm, caller=_adherent_caller, backend=None, model=None,
            runs_dir=runs_dir,
        )

    rows = _read_metric_rows(runs_dir)
    out = analyze_mod.analyze(
        rows, analyze_mod._DEFAULT_CONFIG, config_source="default"
    )
    assert out["verdict"] in ("H0", "H1")  # decided, not INSUFFICIENT
    for m in analyze_mod.DECISION_METRICS:
        assert m in out["per_metric"]
