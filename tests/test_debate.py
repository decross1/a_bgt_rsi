"""Tests for workers.debate (D-065 bounded adversarial debate).

The protocol paths are driven through injected `challenger_fn` /
`defender_fn`, so every stop criterion is exercised without a model. The
default (real-backend) turn builders are covered separately with
`run_subagent` stubbed — including the MOCK_LLM refusal, which is the
pin that a mocked run never spawns a subagent.
"""
import itertools
import json
import sys
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from workers import debate as dbt


QWEN = ("vllm-qwen", "qwen3.6-27b-nvfp4-mtp")
GEMMA = ("vllm-gemma", "gemma-4-26b-a4b-nvfp4")

EVIDENCE = [
    {"doc_id": "doc-a", "chunk_text": "text about conditional cooperation",
     "title": "A", "score": 0.7, "source_layer": "foundational"},
]


def _t(text, tag=QWEN, wall=0.4, **extra):
    return {"text": text, "backend": tag[0], "model": tag[1],
            "wall_seconds": wall, **extra}


def _scripted(*turns):
    """A turn fn that replays `turns` in order; over-calling is a failure."""
    it = iter(turns)
    def fn(claim, evidence_text, transcript):
        try:
            return next(it)
        except StopIteration:  # pragma: no cover - guard, not a path
            raise AssertionError("turn fn called more times than scripted")
    return fn


def _endless_challenger():
    """A challenger that never concedes and never repeats itself."""
    counter = itertools.count(1)
    def fn(claim, evidence_text, transcript):
        i = next(counter)
        body = " ".join(f"alpha{i}beta{j}" for j in range(6))
        return _t(f"OBJECT: fresh grievance {body}")
    return fn


def _endless_defender():
    counter = itertools.count(1)
    def fn(claim, evidence_text, transcript):
        i = next(counter)
        return _t(f"REBUT: counter {i} citing doc-a", tag=GEMMA)
    return fn


def _run(challenger, defender, **kw):
    return dbt.debate(
        "Contribution decay is driven by conditional cooperators.",
        EVIDENCE,
        challenger_fn=challenger,
        defender_fn=defender,
        **kw,
    )


# ── the round cap is a bound, not a suggestion ───────────────────────


@pytest.mark.parametrize("bad", [5, 0, -1, 99, 2.5, "3", True])
def test_max_rounds_out_of_band_raises(bad):
    with pytest.raises(ValueError):
        _run(_endless_challenger(), _endless_defender(), max_rounds=bad)


def test_five_rounds_are_impossible():
    assert dbt.MAX_DEBATE_ROUNDS == 4
    out = _run(_endless_challenger(), _endless_defender())
    assert out["rounds"] == 4
    assert len([t for t in out["transcript"] if t["role"] == "challenger"]) == 4


def test_round_cap_is_inconclusive_never_survives():
    out = _run(_endless_challenger(), _endless_defender())
    assert out["stop_reason"] == "round_cap"
    assert out["verdict"] == "inconclusive"


# ── stop criteria ────────────────────────────────────────────────────


def test_defender_concession_refutes():
    out = _run(
        _scripted(_t("OBJECT: doc-a already states this claim verbatim")),
        _scripted(_t("CONCEDE: doc-a does state it; the claim is prior art",
                     tag=GEMMA)),
    )
    assert out["verdict"] == "refuted"
    assert out["stop_reason"] == "defender_conceded"
    assert out["rounds"] == 1


def test_challenger_concession_survives_debate():
    out = _run(
        _scripted(
            _t("OBJECT: doc-a covers the same mechanism"),
            _t("CONCEDE: the rebuttal answers it; no further objection"),
        ),
        _scripted(_t("REBUT: doc-a studies one-shot play, not repeated",
                     tag=GEMMA)),
    )
    assert out["verdict"] == "survives_debate"
    assert out["stop_reason"] == "challenger_conceded"
    assert out["rounds"] == 2


def test_repeated_objection_converges_neutral():
    repeat = "OBJECT: doc-a already states the identical mechanism claim"
    out = _run(
        _scripted(_t(repeat), _t(repeat)),
        _scripted(_t("REBUT: doc-a measures a different direction", tag=GEMMA)),
    )
    assert out["stop_reason"] == "converged"
    # Owner ratification 2026-08-15 (D065_debate_params_ratified): a
    # stalled exchange is NEUTRAL. A rebutted objection is not a survival.
    assert out["verdict"] == "inconclusive"
    assert out["rounds"] == 2
    # The defender is not asked to rebut a repeat.
    assert [t["role"] for t in out["transcript"]] == [
        "challenger", "defender", "challenger"]


def test_near_identical_objection_converges_above_threshold():
    a = "OBJECT: doc-a already states the identical mechanism claim clearly"
    b = "OBJECT: doc-a already states the identical mechanism claim"
    assert dbt._jaccard(dbt._objection_tokens(a),
                        dbt._objection_tokens(b)) >= dbt.REPEAT_SIMILARITY_THRESHOLD
    out = _run(
        _scripted(_t(a), _t(b)),
        _scripted(_t("REBUT: not the same direction", tag=GEMMA)),
    )
    assert out["stop_reason"] == "converged"
    assert out["verdict"] == "inconclusive"


def test_only_an_explicit_challenger_concession_yields_survives_debate():
    """Owner ratification 2026-08-15: survives_debate has exactly ONE
    route in. Every other stop path is refuted or inconclusive."""
    repeat = "OBJECT: doc-a already states the identical mechanism claim"
    outs = [
        _run(_endless_challenger(), _endless_defender()),                 # cap
        _run(_scripted(_t(repeat), _t(repeat)),
             _scripted(_t("REBUT: different direction", tag=GEMMA))),     # converged
        _run(_scripted(_t("OBJECT: doc-a states it")),
             _scripted(_t("CONCEDE: it does", tag=GEMMA))),               # refuted
        _run(_scripted(_t("", error="boom")), _scripted()),               # error
    ]
    assert all(o["verdict"] != "survives_debate" for o in outs)
    conceded = _run(_scripted(_t("CONCEDE: nothing further")), _scripted())
    assert conceded["verdict"] == "survives_debate"
    assert conceded["stop_reason"] == "challenger_conceded"


def test_substantively_different_objection_does_not_converge():
    out = _run(
        _scripted(
            _t("OBJECT: doc-a already states this mechanism"),
            _t("OBJECT: separate problem, the population sampling is biased"),
        ),
        _scripted(
            _t("REBUT: doc-a is one-shot", tag=GEMMA),
            _t("CONCEDE: the sampling objection stands", tag=GEMMA),
        ),
    )
    assert out["stop_reason"] == "defender_conceded"
    assert out["verdict"] == "refuted"
    assert out["rounds"] == 2


# ── fail-closed ──────────────────────────────────────────────────────


def test_challenger_error_is_inconclusive():
    out = _run(
        _scripted(_t("", error="challenger turn timeout: budget exceeded")),
        _scripted(_t("REBUT: unreached", tag=GEMMA)),
    )
    assert out["verdict"] == "inconclusive"
    assert out["stop_reason"] == "challenger_error"
    assert out["transcript"][-1]["error"].startswith("challenger turn timeout")


def test_defender_error_is_inconclusive():
    out = _run(
        _scripted(_t("OBJECT: doc-a contradicts the claim")),
        _scripted(_t("", error="defender turn schema_mismatch: no JSON")),
    )
    assert out["verdict"] == "inconclusive"
    assert out["stop_reason"] == "defender_error"


def test_raising_turn_fn_is_caught_and_recorded():
    def boom(claim, evidence_text, transcript):
        raise RuntimeError("backend exploded")
    out = _run(boom, _scripted(_t("REBUT: unreached", tag=GEMMA)))
    assert out["verdict"] == "inconclusive"
    assert out["stop_reason"] == "challenger_error"
    assert "backend exploded" in out["transcript"][-1]["error"]


def test_empty_text_turn_is_inconclusive():
    out = _run(_scripted(_t("")), _scripted(_t("REBUT: x", tag=GEMMA)))
    assert out["verdict"] == "inconclusive"


def test_empty_claim_is_inconclusive():
    out = dbt.debate("", EVIDENCE,
                     challenger_fn=_scripted(), defender_fn=_scripted())
    assert out["verdict"] == "inconclusive"
    assert out["rounds"] == 0
    assert out["transcript"][0]["role"] == "system"


def test_unusable_evidence_is_inconclusive():
    out = dbt.debate("a claim", 17,
                     challenger_fn=_scripted(), defender_fn=_scripted())
    assert out["verdict"] == "inconclusive"
    assert "unusable evidence" in out["transcript"][0]["error"]


def test_verdicts_stay_inside_the_enum():
    for out in (
        _run(_endless_challenger(), _endless_defender()),
        _run(_scripted(_t("OBJECT: x y z")),
             _scripted(_t("CONCEDE: yes", tag=GEMMA))),
        _run(_scripted(_t("CONCEDE: nothing further")), _scripted()),
    ):
        assert out["verdict"] in dbt.ALLOWED_DEBATE_VERDICTS


# ── the whole point: every turn is model-tagged ──────────────────────


def test_every_model_turn_carries_backend_and_model():
    out = _run(_endless_challenger(), _endless_defender())
    model_turns = [t for t in out["transcript"] if t["role"] != "system"]
    assert len(model_turns) == 8
    for t in model_turns:
        assert t["backend"] and t["model"]
        assert set(t) >= {"round", "role", "backend", "model", "text",
                          "wall_seconds"}


def test_challenger_and_defender_tags_are_distinguishable():
    out = _run(
        _scripted(_t("OBJECT: doc-a states it")),
        _scripted(_t("CONCEDE: agreed", tag=GEMMA)),
    )
    by_role = {t["role"]: t for t in out["transcript"]}
    assert (by_role["challenger"]["backend"], by_role["challenger"]["model"]) == QWEN
    assert (by_role["defender"]["backend"], by_role["defender"]["model"]) == GEMMA


def test_round_numbers_increment_per_round():
    out = _run(_endless_challenger(), _endless_defender())
    assert [t["round"] for t in out["transcript"]] == [1, 1, 2, 2, 3, 3, 4, 4]


# ── MOCK_LLM: never spawn a real subagent ────────────────────────────


def test_mock_llm_default_turn_refuses_to_spawn(monkeypatch):
    monkeypatch.setenv("MOCK_LLM", "1")
    def explode(**kwargs):  # pragma: no cover - must never be reached
        raise AssertionError("run_subagent called under MOCK_LLM")
    monkeypatch.setattr(dbt, "run_subagent", explode)
    turn = dbt._default_challenger("claim", "evidence", [], None)
    assert turn["error"].startswith("MOCK_LLM")
    assert turn["text"] == ""


def test_mock_llm_debate_without_injected_fns_is_inconclusive(monkeypatch):
    monkeypatch.setenv("MOCK_LLM", "1")
    def explode(**kwargs):  # pragma: no cover - must never be reached
        raise AssertionError("run_subagent called under MOCK_LLM")
    monkeypatch.setattr(dbt, "run_subagent", explode)
    out = dbt.debate("a claim about cooperation", EVIDENCE)
    assert out["verdict"] == "inconclusive"
    assert out["stop_reason"] == "challenger_error"


def test_mock_llm_refuses_the_debates_own_retrieval(monkeypatch):
    monkeypatch.setenv("MOCK_LLM", "1")
    def explode(*a, **k):  # pragma: no cover - must never be reached
        raise AssertionError("query_top_k called under MOCK_LLM")
    monkeypatch.setattr(dbt, "query_top_k", explode)
    out = dbt.debate("a claim", None)
    assert out["verdict"] == "inconclusive"
    assert "MOCK_LLM" in out["transcript"][0]["error"]


def test_evidence_none_triggers_the_debates_own_retrieval(monkeypatch):
    monkeypatch.delenv("MOCK_LLM", raising=False)
    seen = {}
    def fake_query(text, k=10, parent_request_id=None):
        seen["text"], seen["k"] = text, k
        return {"status": "passed",
                "result": {"neighbors": [{"doc_id": "own-1",
                                          "chunk_text": "fresh", "title": "T"}]}}
    monkeypatch.setattr(dbt, "query_top_k", fake_query)
    captured = {}
    def challenger(claim, evidence_text, transcript):
        captured["evidence"] = evidence_text
        return _t("CONCEDE: nothing further")
    dbt.debate("independent claim", None, challenger_fn=challenger,
               defender_fn=_scripted())
    assert seen["text"] == "independent claim"
    assert seen["k"] == dbt.DEBATE_EVIDENCE_K
    assert "own-1" in captured["evidence"]


def test_retrieval_failure_is_inconclusive(monkeypatch):
    monkeypatch.delenv("MOCK_LLM", raising=False)
    monkeypatch.setattr(dbt, "query_top_k",
                        lambda *a, **k: {"status": "error", "result": {}})
    out = dbt.debate("a claim", None)
    assert out["verdict"] == "inconclusive"
    assert out["stop_reason"] == "error"


# ── the additive record block validates against the real schema ──────


def test_debate_block_validates_against_iteration_record_schema():
    out = _run(_endless_challenger(), _endless_defender())
    schema = json.loads(
        (REPO_ROOT / "schema" / "iteration_record.schema.json").read_text())
    critique = {
        "verdict": "undecidable",
        "rationale": "r",
        "skeptic_verdict": out["verdict"],
        "skeptic_backend": "vllm-qwen",
        "skeptic_model": "qwen3.6-27b-nvfp4-mtp",
        "debate": {
            "verdict":     out["verdict"],
            "rounds":      out["rounds"],
            "stop_reason": out["stop_reason"],
            "transcript":  out["transcript"][:6],
        },
    }
    jsonschema.Draft7Validator(
        schema["properties"]["critique"]).validate(critique)


# ── the real-backend turn builder (run_subagent stubbed, MOCK off) ────


class _FakeSA:
    def __init__(self, status, result, errors=None, wall=2.5):
        self.status, self.result = status, result
        self.errors = errors or []
        self.wall_seconds = wall


@pytest.fixture
def live(monkeypatch):
    """MOCK_LLM off so the default turn fns take their real path; every
    test using this fixture stubs run_subagent, so nothing is spawned."""
    monkeypatch.delenv("MOCK_LLM", raising=False)


def test_default_challenger_builds_a_tagged_canonical_turn(live, monkeypatch):
    seen = {}
    def fake(**kwargs):
        seen.update(kwargs)
        return _FakeSA("passed", {"stance": "object", "argument": "doc-a says it",
                                  "cited_doc_id": "doc-a"})
    monkeypatch.setattr(dbt, "run_subagent", fake)
    turn = dbt._default_challenger("claim", "EVIDENCE BLOCK", [], "iter-1")
    assert turn["text"] == "OBJECT: doc-a says it [cites doc-a]"
    assert turn["backend"] == "vllm-qwen"
    assert turn["model"]
    assert turn["wall_seconds"] == 2.5
    assert "error" not in turn
    assert seen["name"] == "debate_challenger"
    assert seen["backend"] == "vllm-qwen"
    assert seen["parent_request_id"] == "iter-1"
    assert seen["budget"].max_tokens_per_turn == dbt.DEBATE_MAX_TOKENS_PER_TURN
    assert "EVIDENCE BLOCK" in seen["user_prompt"]


def test_default_defender_runs_on_the_apparatus_backend(live, monkeypatch):
    seen = {}
    def fake(**kwargs):
        seen.update(kwargs)
        return _FakeSA("passed", {"stance": "concede", "argument": "it stands",
                                  "cited_doc_id": None})
    monkeypatch.setattr(dbt, "run_subagent", fake)
    turn = dbt._default_defender("claim", "ev", [], None)
    assert turn["text"] == "CONCEDE: it stands"
    assert dbt._concedes(turn["text"])
    assert seen["backend"] == dbt.DEFENDER_BACKEND == "vllm-gemma"


def test_default_challenger_honors_the_skeptic_backend_env(live, monkeypatch):
    monkeypatch.setenv("NARA_SKEPTIC_BACKEND", "vllm-gemma")
    seen = {}
    def fake(**kwargs):
        seen.update(kwargs)
        return _FakeSA("passed", {"stance": "object", "argument": "a"})
    monkeypatch.setattr(dbt, "run_subagent", fake)
    turn = dbt._default_challenger("claim", "ev", [], None)
    # The tag must be the backend that ACTUALLY ran, not the ladder default.
    assert seen["backend"] == "vllm-gemma"
    assert turn["backend"] == "vllm-gemma"


@pytest.mark.parametrize("status,result", [
    ("schema_mismatch", {"junk": 1}),
    ("timeout", None),
    ("error", None),
])
def test_failed_subagent_turn_is_an_error_turn(live, monkeypatch, status, result):
    monkeypatch.setattr(dbt, "run_subagent",
                        lambda **kw: _FakeSA(status, result, errors=["why"]))
    turn = dbt._default_challenger("claim", "ev", [], None)
    assert turn["text"] == ""
    assert status in turn["error"]
    assert turn["backend"] and turn["model"]  # tagged even on failure


def test_off_protocol_stance_is_an_error_turn(live, monkeypatch):
    monkeypatch.setattr(dbt, "run_subagent", lambda **kw: _FakeSA(
        "passed", {"stance": "agree", "argument": "hm"}))
    turn = dbt._default_defender("claim", "ev", [], None)
    assert "off-protocol" in turn["error"]


def test_empty_argument_is_an_error_turn(live, monkeypatch):
    monkeypatch.setattr(dbt, "run_subagent", lambda **kw: _FakeSA(
        "passed", {"stance": "rebut", "argument": "   "}))
    turn = dbt._default_defender("claim", "ev", [], None)
    assert "off-protocol" in turn["error"]


def test_unknown_backend_is_an_error_turn(live, monkeypatch):
    monkeypatch.setenv("NARA_SKEPTIC_BACKEND", "no-such-backend")
    def explode(**kw):  # pragma: no cover - must never be reached
        raise AssertionError("run_subagent called with an unknown backend")
    monkeypatch.setattr(dbt, "run_subagent", explode)
    turn = dbt._default_challenger("claim", "ev", [], None)
    assert "unknown debate backend" in turn["error"]


def test_run_subagent_raising_is_an_error_turn(live, monkeypatch):
    def boom(**kw):
        raise RuntimeError("vllm connection refused")
    monkeypatch.setattr(dbt, "run_subagent", boom)
    turn = dbt._default_challenger("claim", "ev", [], None)
    assert "vllm connection refused" in turn["error"]
    assert turn["text"] == ""


def test_end_to_end_with_stubbed_subagent_stays_bounded(live, monkeypatch):
    """The default fns wired to a stubbed backend that never concedes:
    the debate still stops at the cap and every turn is tagged."""
    counter = itertools.count(1)
    def fake(**kwargs):
        i = next(counter)
        return _FakeSA("passed", {
            "stance": "object" if "challenger" in kwargs["name"] else "rebut",
            "argument": f"grievance {' '.join(f'zeta{i}eta{j}' for j in range(6))}",
        })
    monkeypatch.setattr(dbt, "run_subagent", fake)
    out = dbt.debate("a claim", EVIDENCE)
    assert out["verdict"] == "inconclusive"
    assert out["stop_reason"] == "round_cap"
    assert out["rounds"] == dbt.MAX_DEBATE_ROUNDS
    assert len(out["transcript"]) == 8
    assert all(t["backend"] and t["model"] for t in out["transcript"])
    assert {t["backend"] for t in out["transcript"]} == {"vllm-qwen", "vllm-gemma"}
