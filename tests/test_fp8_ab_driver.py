"""Contract tests for bench/fp8_ab — the D-072 window battery driver and
the 10-turn tool probe (docs/qwen_fp8_windows_plan.md "Build gaps").

Hermetic: the HTTP layer and retrieval are injected fakes — no server, no
chroma, no model calls (suite norm MOCK_LLM=1). What is pinned here:

  - sentinel order is the plan's, and sentinel-id resolution FAILS LOUDLY
    listing candidates when cases.jsonl drifts (never guesses);
  - every STOP condition aborts with the right stop_reason and a partial
    artifact;
  - frozen provenance: block completeness, prompt sha256 stability (a
    pinned hex over a fixed fixture), per-doc sha256;
  - cross-arm determinism: identical case order / seeds / prompt hashes
    and request payloads by construction;
  - absent spec-decode counters record as null, never a fabricated zero;
  - tool-probe classification of structured / XML-in-content / absent
    response shapes, script determinism, and the isolated JSON-string
    argument-replay trap turn.
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

from bench.fp8_ab import driver, tool_probe

CASES, CASES_SHA = driver.load_cases()

FIXTURE_CASE = {
    "case_id": "fixture_case",
    "hypothesis": "Tit-for-tat sustains cooperation in finitely repeated PD.",
}
FIXTURE_NEIGHBORS = [
    {"doc_id": "doc_alpha", "score": 0.91, "title": "Alpha",
     "source_layer": "curated", "chunk_text": "TFT reciprocity chunk."},
    {"doc_id": "doc_beta", "score": 0.55, "title": "Beta",
     "source_layer": "papers", "chunk_text": "Second chunk."},
]
# sha256 of prompt_messages(FIXTURE_CASE, FIXTURE_NEIGHBORS) — pinned so a
# silent change to persona bytes / neighbor formatting / canonicalization
# breaks THIS test instead of the cross-arm comparison.
FIXTURE_PROMPT_SHA = (
    "b3418d56d8af2c06207297973acfe498302249a17866a5b733ee367b1c3c3828")

METRICS_NO_SPEC = ("vllm:num_requests_running 0.0\n"
                   "vllm:generation_tokens_total 10.0\n")
METRICS_WITH_SPEC = ("vllm:num_requests_running 0.0\n"
                     "vllm:spec_decode_num_accepted_tokens_total 123.0\n"
                     "vllm:spec_decode_num_draft_tokens_total 456.0\n")


def chat_ok(payload):
    content = json.dumps({"attack_verdict": "survives_attack",
                          "rationale": "no contradiction in the set",
                          "contradicting_doc_id": None})
    return 200, {"choices": [{"message": {"content": content}}],
                 "usage": {"completion_tokens": 96}}


class FakeHTTP:
    """The injected HTTP seam: GET -> /metrics, POST -> chat responder."""

    def __init__(self, chat=chat_ok, metrics_text=METRICS_NO_SPEC,
                 metrics_raise=None):
        self.chat = chat
        self.metrics_text = metrics_text
        self.metrics_raise = metrics_raise
        self.posts = []

    def __call__(self, method, url, payload=None, timeout=None):
        if method == "GET":
            if self.metrics_raise is not None:
                raise self.metrics_raise
            return 200, self.metrics_text
        self.posts.append(payload)
        return self.chat(payload)


def fake_retrieve(_text):
    return [dict(n) for n in FIXTURE_NEIGHBORS]


def make_cfg(**kw):
    base = dict(arm_label="armA", model="qwen-fp8-test",
                endpoint="http://127.0.0.1:8002/v1", cap=12288, full=False,
                seed_base=driver.DEFAULT_SEED_BASE,
                image_digest="sha256:deadbeef", model_revision="rev123",
                cases_path="fixture", cases_sha256="fixturesha")
    base.update(kw)
    return driver.RunConfig(**base)


def make_clock(step):
    state = {"t": 0.0}

    def clock():
        state["t"] += step
        return state["t"]
    return clock


# --- sentinel order + resolution -----------------------------------------

def test_sentinel_order_is_the_plans_order():
    order = driver.build_run_order(CASES, full=False)
    assert [c["case_id"] for _, c in order] == list(driver.SENTINEL_IDS)
    # seeds come from the file index, not the run position
    for idx, case in order:
        assert CASES[idx]["case_id"] == case["case_id"]


def test_full_order_appends_remaining_cases_in_file_order():
    order = driver.build_run_order(CASES, full=True)
    ids = [c["case_id"] for _, c in order]
    assert len(ids) == 22 and len(set(ids)) == 22
    assert ids[:6] == list(driver.SENTINEL_IDS)
    rest = [c["case_id"] for c in CASES
            if c["case_id"] not in driver.SENTINEL_IDS]
    assert ids[6:] == rest


def test_sentinel_resolution_fails_loudly_listing_candidates():
    doctored = [dict(c) for c in CASES]
    for c in doctored:
        if c["case_id"] == "falsifiable_01_finite_pd_cooperate":
            c["case_id"] = "falsifiable_01_finite_pd_coop"  # near-miss
    with pytest.raises(driver.SentinelResolutionError) as ei:
        driver.build_run_order(doctored, full=False)
    msg = str(ei.value)
    assert "falsifiable_01_finite_pd_cooperate" in msg   # the missing pin
    assert "falsifiable_01_finite_pd_coop" in msg        # listed candidate
    assert "guess" in msg


# --- STOP conditions ------------------------------------------------------

def _run_sentinels(chat=chat_ok, clock=None, **fake_kw):
    fake = FakeHTTP(chat=chat, **fake_kw)
    art = driver.run_arm(CASES, make_cfg(), http=fake,
                         retrieve=fake_retrieve,
                         clock=clock or make_clock(1.0))
    return art, fake


def test_stop_empty_completion():
    def chat_empty(_payload):
        return 200, {"choices": [{"message": {"content": "   "}}],
                     "usage": {"completion_tokens": 0}}
    art, _ = _run_sentinels(chat=chat_empty)
    assert art["stop_reason"]["reason"] == "empty_completion"
    assert art["stop_reason"]["case_id"] == driver.SENTINEL_IDS[0]
    assert art["completed"] is False
    assert len(art["cases"]) == 1          # aborted on the first call
    assert "metrics_after" in art          # partial artifact still closes


def test_stop_wall_exceeded():
    art, _ = _run_sentinels(clock=make_clock(601.0))
    assert art["stop_reason"]["reason"] == "wall_exceeded"
    assert art["completed"] is False
    # the completion arrived and was parsed before the wall verdict
    assert art["cases"][0]["attack_verdict"] == "survives_attack"


def test_stop_http_error_on_transport_exception():
    def chat_boom(_payload):
        raise ConnectionError("connection refused")
    art, _ = _run_sentinels(chat=chat_boom)
    assert art["stop_reason"]["reason"] == "http_error"
    assert "ConnectionError" in art["stop_reason"]["detail"]
    assert len(art["cases"]) == 1


def test_stop_cuda_error_on_500_with_cuda_body():
    def chat_cuda(_payload):
        return 500, "CUDA error: an illegal memory access was encountered"
    art, _ = _run_sentinels(chat=chat_cuda)
    assert art["stop_reason"]["reason"] == "cuda_error"
    assert art["cases"][0]["http_status"] == 500


def test_stop_missing_call_record(tmp_path):
    def chat_hollow(_payload):
        return 200, {"id": "cmpl-x"}       # no choices[0].message
    art, _ = _run_sentinels(chat=chat_hollow)
    assert art["stop_reason"]["reason"] == "missing_call_record"
    # partial artifact round-trips with the stop recorded
    out = driver.write_artifact(art, tmp_path / "partial.json")
    reloaded = json.loads(out.read_text())
    assert reloaded["stop_reason"]["reason"] == "missing_call_record"
    assert reloaded["completed"] is False


def test_stop_retrieval_error_fail_closed():
    def broken_retrieve(_text):
        raise RuntimeError("chroma down")
    fake = FakeHTTP()
    art = driver.run_arm(CASES, make_cfg(), http=fake,
                         retrieve=broken_retrieve, clock=make_clock(1.0))
    assert art["stop_reason"]["reason"] == "retrieval_error"
    assert fake.posts == []                # no ungrounded prompt was sent


# --- frozen provenance ----------------------------------------------------

def test_prompt_sha256_is_stable_on_the_pinned_fixture():
    messages = driver.prompt_messages(FIXTURE_CASE, FIXTURE_NEIGHBORS)
    got = driver.prompt_sha256(messages)
    assert got == FIXTURE_PROMPT_SHA
    # independent recompute of the canonicalization recipe
    canon = json.dumps(messages, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False)
    assert got == hashlib.sha256(canon.encode("utf-8")).hexdigest()


def test_provenance_block_completeness_and_doc_hashes():
    art, _ = _run_sentinels()
    prov = art["provenance"]
    for key in ("image_digest", "model_revision", "endpoint", "served_model",
                "cases_path", "cases_sha256", "sentinel_ids", "seed_base",
                "sampling", "wall_cap_s", "effective_config"):
        assert key in prov, f"provenance missing {key}"
    assert prov["image_digest"] == "sha256:deadbeef"
    assert prov["model_revision"] == "rev123"
    assert prov["sampling"] == {"temperature": 0.2, "top_p": 0.95,
                                "max_tokens": 12288}
    assert prov["effective_config"]["arm_label"] == "armA"
    rec = art["cases"][0]
    assert rec["prompt_sha256"] == driver.prompt_sha256(
        driver.prompt_messages(
            next(c for c in CASES
                 if c["case_id"] == driver.SENTINEL_IDS[0]),
            FIXTURE_NEIGHBORS))
    assert rec["retrieved_doc_ids"] == ["doc_alpha", "doc_beta"]
    assert rec["retrieved_docs"][0]["sha256"] == hashlib.sha256(
        b"TFT reciprocity chunk.").hexdigest()


def test_cross_arm_determinism_same_seed_same_order_same_bytes():
    fake_a, fake_b = FakeHTTP(), FakeHTTP()
    art_a = driver.run_arm(CASES, make_cfg(arm_label="arm_36", full=True),
                           http=fake_a, retrieve=fake_retrieve,
                           clock=make_clock(1.0))
    art_b = driver.run_arm(CASES, make_cfg(arm_label="arm_38", full=True),
                           http=fake_b, retrieve=fake_retrieve,
                           clock=make_clock(1.0))
    proj_a = [(r["case_id"], r["seed"], r["prompt_sha256"])
              for r in art_a["cases"]]
    proj_b = [(r["case_id"], r["seed"], r["prompt_sha256"])
              for r in art_b["cases"]]
    assert json.dumps(proj_a) == json.dumps(proj_b)     # byte-identical
    # the actual request payloads (model held constant) are byte-identical
    assert json.dumps(fake_a.posts, sort_keys=True) == \
        json.dumps(fake_b.posts, sort_keys=True)
    seeds = [p["seed"] for p in fake_a.posts]
    assert len(seeds) == 22 and len(set(seeds)) == 22
    assert all(s >= driver.DEFAULT_SEED_BASE for s in seeds)


# --- acceptance counters --------------------------------------------------

def test_absent_spec_counters_record_null_never_invented():
    art, _ = _run_sentinels(metrics_text=METRICS_NO_SPEC)
    for block in (art["metrics_before"], art["metrics_after"]):
        assert block["spec_decode_num_accepted_tokens_total"] is None
        assert block["spec_decode_num_draft_tokens_total"] is None
        assert block["scrape_error"] is None


def test_present_spec_counters_are_read():
    art, _ = _run_sentinels(metrics_text=METRICS_WITH_SPEC)
    assert art["metrics_before"][
        "spec_decode_num_accepted_tokens_total"] == 123.0
    assert art["metrics_before"][
        "spec_decode_num_draft_tokens_total"] == 456.0


def test_scrape_failure_recorded_not_fatal():
    art, _ = _run_sentinels(metrics_raise=ConnectionError("metrics down"))
    assert art["completed"] is True        # scrape failure never aborts
    assert art["metrics_before"]["spec_decode_num_accepted_tokens_total"] is None
    assert "ConnectionError" in art["metrics_before"]["scrape_error"]


# --- artifact schema round-trip --------------------------------------------

def test_full_run_artifact_schema_roundtrip(tmp_path):
    fake = FakeHTTP(metrics_text=METRICS_WITH_SPEC)
    art = driver.run_arm(CASES, make_cfg(full=True), http=fake,
                         retrieve=fake_retrieve, clock=make_clock(1.0))
    assert art["completed"] is True and art["stop_reason"] is None
    assert art["mode"] == "full" and len(art["cases"]) == 22
    out = driver.write_artifact(art, tmp_path / "arm.json")
    assert json.loads(out.read_text()) == art
    required = {"case_id", "case_index", "sentinel", "expected_critic",
                "seed", "sampling", "retrieved_docs", "retrieved_doc_ids",
                "prompt_sha256", "wall_s", "http_status", "output_tokens",
                "tok_s", "parse_status", "attack_verdict",
                "contradicting_doc_id", "rationale_head"}
    for rec in art["cases"]:
        assert required <= set(rec), f"{rec['case_id']}: {required - set(rec)}"
    assert art["summary"]["cases_run"] == 22
    assert art["summary"]["parse_ok"] == 22
    assert art["cases"][0]["tok_s"] == 96.0   # 96 tokens / 1.0s fake wall


# --- tool probe -------------------------------------------------------------

def test_classify_structured_xml_and_absent_shapes():
    structured = {"tool_calls": [{"id": "1", "type": "function",
                                  "function": {"name": "echo",
                                               "arguments": '{"text": "hi"}'}}]}
    got = tool_probe.classify_response(structured)
    assert got["shape"] == "structured" and got["arguments_parseable"] is True

    bad_args = {"tool_calls": [{"id": "1", "type": "function",
                                "function": {"name": "echo",
                                             "arguments": "{oops"}}]}
    got = tool_probe.classify_response(bad_args)
    assert got["shape"] == "structured" and got["arguments_parseable"] is False

    xml = {"content": '<tool_call>\n{"name": "echo", "arguments": '
                      '{"text": "hi"}}\n</tool_call>'}
    got = tool_probe.classify_response(xml)
    assert got["shape"] == "xml_in_content"
    assert got["arguments_parseable"] is True

    got = tool_probe.classify_response({"content": "I cannot call tools."})
    assert got["shape"] == "absent" and got["arguments_parseable"] is None
    assert tool_probe.classify_response(None)["shape"] == "absent"


def test_probe_script_is_deterministic_and_trap_is_isolated():
    assert len(tool_probe.TURNS) == 10
    assert tool_probe.script_sha256() == tool_probe.script_sha256()
    for i in range(10):
        assert tool_probe.build_messages(i) == tool_probe.build_messages(i)

    def dict_args(messages):
        # Polarity fixed 2026-08-17: normal replays are spec-correct JSON
        # STRINGS (dicts get HTTP-400d before reaching the model, proven on
        # the first live run); the trap turn is the lone spec-VIOLATING dict.
        return [tc for m in messages if m.get("role") == "assistant"
                for tc in (m.get("tool_calls") or [])
                if isinstance(tc["function"]["arguments"], dict)]

    # exactly one dict-typed replay, only in the trap request (turn t06)
    trap_msgs = tool_probe.build_messages(tool_probe.TRAP_REQUEST_TURN)
    trapped = dict_args(trap_msgs)
    assert len(trapped) == 1
    assert trapped[0]["function"]["arguments"] == {
        "text": "καλημέρα κόσμε ✓"}
    for i in range(10):
        if i == tool_probe.TRAP_REQUEST_TURN:
            continue
        assert dict_args(tool_probe.build_messages(i)) == []
        for m in tool_probe.build_messages(i):
            for tc in (m.get("tool_calls") or []):
                assert isinstance(tc["function"]["arguments"], str)
    # the multi-tool turn replays as TWO calls in later histories
    multi = [m for m in tool_probe.build_messages(8)
             if m.get("role") == "assistant" and len(m.get("tool_calls") or []) == 2]
    assert len(multi) == 1


def test_probe_run_records_all_turns_and_roundtrips(tmp_path):
    class FakeProbeHTTP:
        def __init__(self):
            self.posts = []

        def __call__(self, method, url, payload=None, timeout=None):
            self.posts.append(payload)
            i = payload["seed"] - tool_probe.DEFAULT_SEED_BASE
            if i == tool_probe.TRAP_REQUEST_TURN:   # template TypeError
                return 400, ("TypeError: 'str' object has no attribute "
                             "'items' (chat template)")
            return 200, {"choices": [{"message": {"tool_calls": [
                {"id": "x", "type": "function",
                 "function": {"name": "echo", "arguments": "{}"}}]}}]}

    fake = FakeProbeHTTP()
    art = tool_probe.run_probe("arm_38", "qwen-fp8-test",
                               "http://127.0.0.1:8002/v1",
                               image_digest="sha256:deadbeef",
                               model_revision="rev123", http=fake,
                               clock=make_clock(0.5))
    assert len(art["turns"]) == 10          # a failed turn never aborts
    trap = art["turns"][tool_probe.TRAP_REQUEST_TURN]
    assert trap["string_args_trap"] is True
    assert trap["http_status"] == 400 and trap["shape"] == "absent"
    assert "TypeError" in trap["error"]
    assert art["summary"] == {"structured": 9, "xml_in_content": 0,
                              "absent": 1, "http_errors": 1,
                              "arguments_parseable": 9}
    assert art["provenance"]["script_sha256"] == tool_probe.script_sha256()
    out = driver.write_artifact(art, tmp_path / "probe.json")
    assert json.loads(out.read_text()) == art
    # every request pinned the frozen sampling + a per-turn seed
    assert all(p["temperature"] == 0.2 and p["top_p"] == 0.95
               for p in fake.posts)
    # every turn FORCES tool use: a named function or "required", never auto
    for p in fake.posts:
        tc = p["tool_choice"]
        assert tc == "required" or (isinstance(tc, dict)
                                    and tc["type"] == "function")


# --- MOCK_LLM refusal (rule 10) --------------------------------------------

def test_cli_refuses_under_mock_llm(monkeypatch, capsys):
    monkeypatch.setenv("MOCK_LLM", "1")
    rc = driver.main(["--model", "m", "--arm-label", "a",
                      "--image-digest", "d", "--model-revision", "r",
                      "--sentinels-only"])
    assert rc == 2
    assert "MOCK_LLM" in capsys.readouterr().out
    rc = tool_probe.main(["--model", "m", "--arm-label", "a",
                          "--image-digest", "d", "--model-revision", "r"])
    assert rc == 2
