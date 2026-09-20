"""Bounded duplicate suppression for the opt-in frontier veto screen."""
from __future__ import annotations

import json
import hashlib
import inspect
from types import SimpleNamespace

from agent_wrapper import frontier_cli
from orchestrator import finding_promotion as fp
from workers import frontier_screen_cache as cache


CANDIDATE = {
    "iteration_id": "iter-001",
    "claim": "The intervention improves calibration.",
    "novelty": {"class": "novel", "rationale": "no match found"},
    "critique": {"verdict": "survives", "rationale": "controls passed"},
    "experiment_outcome": {"trials": 40, "value": 0.8},
}
CONFIG = {
    "role_vendors": {
        "methods_reviewer": "claude",
        "novelty_reviewer": "codex",
    },
    "providers": {
        "claude": {
            "model": "cli-default",
            "declared_cache_epoch_sha256": "c" * 64,
            "implementation": {"sha256": "a" * 64},
        },
        "codex": {
            "model": "gpt-test", "reasoning_effort": "max",
            "declared_cache_epoch_sha256": "d" * 64,
            "implementation": {"sha256": "b" * 64},
        },
    },
    "transport_source_sha256": "e" * 64,
    "cache_epochs_declared": True,
}


def _record(verdict: str, *, error: str | None = None) -> dict:
    return {
        "text": json.dumps({
            "verdict": verdict,
            "reasoning": f"{verdict} because the evidence says so",
            "closest_prior_work": None,
        }),
        "exit_code": 0,
        "error": error,
    }


def _invoke_counter(verdict: str = "veto", *, error: str | None = None):
    calls: list[tuple[str, str]] = []

    def invoke(vendor, prompt, *, timeout_s, role, ledger_path=None):
        calls.append((vendor, role))
        return _record(verdict, error=error)

    return calls, invoke


def test_exact_completed_veto_is_reused_without_new_calls(tmp_path):
    calls, invoke = _invoke_counter()
    first = cache.screen_candidate_cached(
        CANDIDATE, invoke, cache_dir=tmp_path,
        requested_config=CONFIG, now_s=100.0,
    )
    second = cache.screen_candidate_cached(
        CANDIDATE, invoke, cache_dir=tmp_path,
        requested_config=CONFIG, now_s=3700.0,
    )

    assert first["verdict"] == second["verdict"] == "veto"
    assert first["cache"]["stored"] is True
    assert second["cache"]["hit"] is True
    assert len(calls) == 2  # methods + novelty only on the first screen
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_evidence_or_requested_model_change_invalidates(tmp_path):
    calls, invoke = _invoke_counter()
    cache.screen_candidate_cached(
        CANDIDATE, invoke, cache_dir=tmp_path,
        requested_config=CONFIG, now_s=100.0,
    )

    changed = dict(CANDIDATE)
    changed["experiment_outcome"] = {"trials": 80, "value": 0.9}
    cache.screen_candidate_cached(
        changed, invoke, cache_dir=tmp_path,
        requested_config=CONFIG, now_s=101.0,
    )

    changed_config = json.loads(json.dumps(CONFIG))
    changed_config["providers"]["codex"]["model"] = "gpt-test-next"
    cache.screen_candidate_cached(
        CANDIDATE, invoke, cache_dir=tmp_path,
        requested_config=changed_config, now_s=102.0,
    )

    assert len(calls) == 6
    assert len(list(tmp_path.glob("*.json"))) == 3


def test_transport_source_change_invalidates(tmp_path):
    calls, invoke = _invoke_counter()
    cache.screen_candidate_cached(
        CANDIDATE, invoke, cache_dir=tmp_path,
        requested_config=CONFIG, now_s=100.0,
    )
    changed_config = json.loads(json.dumps(CONFIG))
    changed_config["transport_source_sha256"] = "f" * 64
    second = cache.screen_candidate_cached(
        CANDIDATE, invoke, cache_dir=tmp_path,
        requested_config=changed_config, now_s=101.0,
    )

    assert second["cache"]["hit"] is False
    assert len(calls) == 4


def test_prompt_change_invalidates(tmp_path, monkeypatch):
    calls, invoke = _invoke_counter()
    cache.screen_candidate_cached(
        CANDIDATE, invoke, cache_dir=tmp_path,
        requested_config=CONFIG, now_s=100.0,
    )
    monkeypatch.setitem(
        cache.frontier_review.ROLE_PROMPTS,
        "methods_reviewer",
        cache.frontier_review.ROLE_PROMPTS["methods_reviewer"] + "\nNEW RULE",
    )
    second = cache.screen_candidate_cached(
        CANDIDATE, invoke, cache_dir=tmp_path,
        requested_config=CONFIG, now_s=101.0,
    )

    assert second["cache"]["hit"] is False
    assert len(calls) == 4


def test_expiry_forces_fresh_screen(tmp_path):
    calls, invoke = _invoke_counter()
    cache.screen_candidate_cached(
        CANDIDATE, invoke, cache_dir=tmp_path,
        requested_config=CONFIG, ttl_s=60, now_s=100.0,
    )
    hit = cache.screen_candidate_cached(
        CANDIDATE, invoke, cache_dir=tmp_path,
        requested_config=CONFIG, ttl_s=60, now_s=159.0,
    )
    expired = cache.screen_candidate_cached(
        CANDIDATE, invoke, cache_dir=tmp_path,
        requested_config=CONFIG, ttl_s=60, now_s=161.0,
    )

    assert hit["cache"]["hit"] is True
    assert expired["cache"]["hit"] is False
    assert len(calls) == 4


def test_outage_and_inconclusive_results_are_never_cached(tmp_path):
    calls, invoke = _invoke_counter(error="provider unavailable")
    first = cache.screen_candidate_cached(
        CANDIDATE, invoke, cache_dir=tmp_path,
        requested_config=CONFIG, now_s=100.0,
    )
    second = cache.screen_candidate_cached(
        CANDIDATE, invoke, cache_dir=tmp_path,
        requested_config=CONFIG, now_s=101.0,
    )

    assert first["verdict"] == second["verdict"] == "inconclusive"
    assert first["cache"]["stored"] is False
    assert second["cache"]["hit"] is False
    assert len(calls) == 4
    assert list(tmp_path.glob("*.json")) == []


def test_pass_result_is_never_cached(tmp_path):
    calls, invoke = _invoke_counter("pass")
    first = cache.screen_candidate_cached(
        CANDIDATE, invoke, cache_dir=tmp_path,
        requested_config=CONFIG, now_s=100.0,
    )
    second = cache.screen_candidate_cached(
        CANDIDATE, invoke, cache_dir=tmp_path,
        requested_config=CONFIG, now_s=101.0,
    )

    assert first["verdict"] == second["verdict"] == "pass"
    assert first["cache"]["stored"] is False
    assert second["cache"]["hit"] is False
    assert len(calls) == 4


def test_veto_with_inconclusive_role_is_not_cached(tmp_path):
    calls: list[str] = []

    def invoke(vendor, prompt, *, timeout_s, role, ledger_path=None):
        calls.append(role)
        if role == "novelty_reviewer":
            return _record("inconclusive", error="timeout")
        return _record("veto")

    first = cache.screen_candidate_cached(
        CANDIDATE, invoke, cache_dir=tmp_path,
        requested_config=CONFIG, now_s=100.0,
    )
    cache.screen_candidate_cached(
        CANDIDATE, invoke, cache_dir=tmp_path,
        requested_config=CONFIG, now_s=101.0,
    )

    assert first["verdict"] == "veto"  # existing fail-open combination
    assert first["cache"]["stored"] is False
    assert len(calls) == 4


def test_invalid_ttl_bypasses_cache_without_blocking_screen(tmp_path):
    calls, invoke = _invoke_counter()
    out = cache.screen_candidate_cached(
        CANDIDATE, invoke, cache_dir=tmp_path,
        requested_config=CONFIG, ttl_s=cache.MAX_TTL_S + 1, now_s=100.0,
    )

    assert out["verdict"] == "veto"
    assert out["cache"]["hit"] is False
    assert out["cache"]["stored"] is False
    assert out["cache"]["reason"] == "invalid_ttl"
    assert len(calls) == 2


def test_ttl_policy_change_invalidates_existing_entry(tmp_path):
    calls, invoke = _invoke_counter()
    cache.screen_candidate_cached(
        CANDIDATE, invoke, cache_dir=tmp_path,
        requested_config=CONFIG, ttl_s=60, now_s=100.0,
    )
    changed = cache.screen_candidate_cached(
        CANDIDATE, invoke, cache_dir=tmp_path,
        requested_config=CONFIG, ttl_s=120, now_s=101.0,
    )

    assert changed["cache"]["hit"] is False
    assert len(calls) == 4


def test_cache_entry_count_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "MAX_CACHE_ENTRIES", 2)
    calls, invoke = _invoke_counter()
    for i in range(3):
        candidate = dict(CANDIDATE, iteration_id=f"iter-{i}")
        cache.screen_candidate_cached(
            candidate, invoke, cache_dir=tmp_path,
            requested_config=CONFIG, now_s=100.0 + i,
        )

    assert len(calls) == 6
    assert len(list(tmp_path.glob("*.json"))) == 2


def test_malformed_record_fails_open_to_fresh_screen(tmp_path):
    calls, invoke = _invoke_counter()
    first = cache.screen_candidate_cached(
        CANDIDATE, invoke, cache_dir=tmp_path,
        requested_config=CONFIG, now_s=100.0,
    )
    record = next(tmp_path.glob("*.json"))
    record.write_text("not-json")
    second = cache.screen_candidate_cached(
        CANDIDATE, invoke, cache_dir=tmp_path,
        requested_config=CONFIG, now_s=101.0,
    )

    assert first["verdict"] == second["verdict"] == "veto"
    assert second["cache"]["hit"] is False
    assert len(calls) == 4


def test_nonfinite_future_or_extended_timestamps_never_hit(tmp_path):
    calls, invoke = _invoke_counter()
    corruptions = (
        ("nan", float("nan"), 200.0),
        ("inf", 100.0, float("inf")),
        ("future", 102.0, 102.0 + cache.DEFAULT_TTL_S),
        ("extended", 100.0, 100.0 + cache.DEFAULT_TTL_S + 1),
    )
    for name, created, expires in corruptions:
        root = tmp_path / name
        cache.screen_candidate_cached(
            CANDIDATE, invoke, cache_dir=root,
            requested_config=CONFIG, now_s=100.0,
        )
        path = next(root.glob("*.json"))
        record = json.loads(path.read_text())
        record["created_at_s"] = created
        record["expires_at_s"] = expires
        path.write_text(json.dumps(record))
        out = cache.screen_candidate_cached(
            CANDIDATE, invoke, cache_dir=root,
            requested_config=CONFIG, now_s=101.0,
        )
        assert out["cache"]["hit"] is False, name

    assert len(calls) == 16


def test_tampered_outer_veto_cannot_override_two_base_passes(tmp_path):
    calls, invoke = _invoke_counter()
    cache.screen_candidate_cached(
        CANDIDATE, invoke, cache_dir=tmp_path,
        requested_config=CONFIG, now_s=100.0,
    )
    path = next(tmp_path.glob("*.json"))
    record = json.loads(path.read_text())
    record["screen"]["methods"]["verdict"] = "pass"
    record["screen"]["novelty"]["verdict"] = "pass"
    path.write_text(json.dumps(record))

    out = cache.screen_candidate_cached(
        CANDIDATE, invoke, cache_dir=tmp_path,
        requested_config=CONFIG, now_s=101.0,
    )
    assert out["cache"]["hit"] is False
    assert len(calls) == 4


def test_misrouted_review_is_not_cached(tmp_path):
    calls, invoke = _invoke_counter()
    cache.screen_candidate_cached(
        CANDIDATE, invoke, cache_dir=tmp_path,
        requested_config=CONFIG, now_s=100.0,
    )
    path = next(tmp_path.glob("*.json"))
    record = json.loads(path.read_text())
    record["screen"]["methods"]["vendor"] = "codex"
    path.write_text(json.dumps(record))

    out = cache.screen_candidate_cached(
        CANDIDATE, invoke, cache_dir=tmp_path,
        requested_config=CONFIG, now_s=101.0,
    )
    assert out["cache"]["hit"] is False
    assert len(calls) == 4


def test_split_verdict_same_provider_confirmation_is_not_cached(
    tmp_path, monkeypatch
):
    # Exercise the real screen's same-provider cross-run behavior, then prove
    # that the cache refuses to call it vendor-independent confirmation.
    monkeypatch.setenv("FRONTIER_NOVELTY_VENDOR", "claude")
    same_provider = json.loads(json.dumps(CONFIG))
    same_provider["role_vendors"] = {
        "methods_reviewer": "claude", "novelty_reviewer": "claude",
    }
    same_provider["providers"].pop("codex")
    calls: list[tuple[str, str]] = []

    def invoke(vendor, prompt, *, timeout_s, role, ledger_path=None):
        calls.append((vendor, role))
        return _record("veto" if role == "methods_reviewer" else "pass")

    first = cache.screen_candidate_cached(
        CANDIDATE, invoke, cache_dir=tmp_path,
        requested_config=same_provider, now_s=100.0,
    )
    cache.screen_candidate_cached(
        CANDIDATE, invoke, cache_dir=tmp_path,
        requested_config=same_provider, now_s=101.0,
    )

    assert first["verdict"] == "veto"
    assert first["cache"]["stored"] is False
    assert len(calls) == 6  # methods + novelty + same-provider cross, twice


def test_cache_write_failure_is_observable_and_does_not_change_veto(tmp_path):
    calls, invoke = _invoke_counter()
    not_a_dir = tmp_path / "cache"
    not_a_dir.write_text("occupied")
    out = cache.screen_candidate_cached(
        CANDIDATE, invoke, cache_dir=not_a_dir,
        requested_config=CONFIG, now_s=100.0,
    )

    assert out["verdict"] == "veto"
    assert out["cache"]["stored"] is False
    assert out["cache"]["write_reason"] == "write_error"
    assert len(calls) == 2


def test_requested_config_binds_role_model_and_implementation(monkeypatch):
    monkeypatch.setenv("FRONTIER_METHODS_VENDOR", "codex")
    monkeypatch.setenv("FRONTIER_CLAUDE_CACHE_EPOCH", "claude-review-20260914")
    monkeypatch.setenv("FRONTIER_CODEX_CACHE_EPOCH", "codex-review-20260914")
    monkeypatch.setattr(
        cache, "_implementation_identity",
        lambda module, vendor: {"resolved_path": f"/bin/{vendor}",
                                "sha256": ("a" if vendor == "claude" else "b") * 64},
    )
    fake_cli = SimpleNamespace(
        CODEX_MODEL="gpt-bound",
        CODEX_REASONING_EFFORT="high",
    )
    config = cache.requested_provider_config(fake_cli)

    assert config["role_vendors"]["methods_reviewer"] == "codex"
    assert config["providers"]["codex"]["model"] == "gpt-bound"
    assert config["providers"]["codex"]["reasoning_effort"] == "high"
    assert config["providers"]["codex"]["implementation"]["resolved_path"] == "/bin/codex"
    # A synthetic object has no inspectable transport source, so it remains
    # conservatively uncacheable even though the provider epochs are declared.
    assert config["cache_epochs_declared"] is False


def test_requested_config_binds_frontier_transport_source(monkeypatch):
    monkeypatch.delenv("FRONTIER_CLAUDE_CACHE_EPOCH", raising=False)
    monkeypatch.delenv("FRONTIER_CODEX_CACHE_EPOCH", raising=False)
    config = cache.requested_provider_config(frontier_cli)
    expected = hashlib.sha256(inspect.getsource(frontier_cli).encode()).hexdigest()
    assert config["transport_source_sha256"] == expected
    assert config["cache_epochs_declared"] is False


def test_undeclared_provider_epoch_bypasses_cache(tmp_path):
    calls, invoke = _invoke_counter()
    config = json.loads(json.dumps(CONFIG))
    config["cache_epochs_declared"] = False
    config["providers"]["claude"]["declared_cache_epoch_sha256"] = None
    first = cache.screen_candidate_cached(
        CANDIDATE, invoke, cache_dir=tmp_path,
        requested_config=config, now_s=100.0,
    )
    second = cache.screen_candidate_cached(
        CANDIDATE, invoke, cache_dir=tmp_path,
        requested_config=config, now_s=101.0,
    )

    assert first["cache"]["reason"] == "undeclared_provider_cache_epoch"
    assert second["cache"]["hit"] is False
    assert len(calls) == 4
    assert list(tmp_path.glob("*.json")) == []


def test_promotion_integration_reports_exact_veto_cache_hit(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("NARA_FRONTIER_SCREEN", "1")
    monkeypatch.setenv("NARA_FRONTIER_SCREEN_CACHE", "1")
    monkeypatch.setenv("FRONTIER_CLAUDE_CACHE_EPOCH", "claude-review-20260914")
    monkeypatch.setenv("FRONTIER_CODEX_CACHE_EPOCH", "codex-review-20260914")
    monkeypatch.setattr(
        cache, "_implementation_identity",
        lambda module, vendor: {"resolved_path": f"/bin/{vendor}",
                                "sha256": ("a" if vendor == "claude" else "b") * 64},
    )
    monkeypatch.setattr(
        fp, "resolve_backend_route",
        lambda name: SimpleNamespace(
            backend=SimpleNamespace(name=name, default_model="qwen-test")
        ),
    )
    calls, invoke = _invoke_counter()
    monkeypatch.setattr(frontier_cli, "invoke_frontier", invoke)

    row = {
        "iteration_id": "iter-001",
        "seed": {"topic": "calibration"},
        "hypothesis": {"text": CANDIDATE["claim"]},
        "novelty": CANDIDATE["novelty"],
        "critique": CANDIDATE["critique"],
        "retrieval": {
            "relevance": {
                "relevance": 0.9, "low_confidence": False,
                "reason": "fixture evidence",
            }
        },
        "experiment_outcome": {
            "experiment_id": "exp-1", "metric": "score", "value": 0.8,
            "trials": 40, "summary": "Verdict=YES.",
        },
    }
    loop_memory = tmp_path / "loop_memory.jsonl"
    loop_memory.write_text(json.dumps(row) + "\n")
    kwargs = {
        "loop_memory_path": loop_memory,
        "feedback_path": tmp_path / "feedback.jsonl",
        "surfaced_path": tmp_path / "surfaced.jsonl",
        "dry_run": True,
    }

    first = fp.promote_findings(**kwargs)
    second = fp.promote_findings(**kwargs)

    assert first["frontier_cache_hits"] == 0
    assert second["frontier_cache_hits"] == 1
    assert second["near_misses"][0]["frontier_screen"]["cache"]["hit"] is True
    assert len(calls) == 2


def test_runtime_cache_directory_is_gitignored():
    repo = fp.REPO_ROOT
    assert "run_state/frontier_screen_cache/" in (repo / ".gitignore").read_text()
