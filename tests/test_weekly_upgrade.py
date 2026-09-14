"""Hermetic tests for the bounded weekly operational-review controller."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from orchestrator import weekly_upgrade as wu
from orchestrator import weekly_upgrade_trial as wt
from orchestrator.weekly_upgrade_budget import BudgetLedger

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "logs").mkdir(parents=True)
    (root / "run_state").mkdir()
    (root / "cron").mkdir()
    (root / "agent_wrapper").mkdir()
    (root / "orchestrator").mkdir()
    (root / "schema").mkdir()
    (root / "docs").mkdir()
    (root / "bench" / "weekly_upgrade_eval").mkdir(parents=True)
    (root / "AGENTS.md").write_text("maintenance authority; human gate for runtime\n")
    (root / "CLAUDE.md").write_text("D-061 frontier falsifiers; runtime human gate\n")
    (root / "ARCHITECTURE.md").write_text("version pin: v0.test\n")
    (root / "DECISIONS.md").write_text("D-066 Tier P only\n")
    (root / "cron" / "serve-models.sh").write_text("IMAGE=v0.test\n")
    (root / "run_state" / "vllm_image.digest").write_text("sha256:test\n")
    (root / "bench" / "weekly_upgrade_eval" / "fixtures.json").write_text(
        json.dumps({"tasks": [{"id": "critic-01"}, {"id": "critic-02"}]})
    )
    call = {
        "timestamp": "2026-09-08T10:00:00Z",
        "caller_tag": "fixture",
        "backend": "vllm-gemma",
        "completion": "RAW-COMPLETION-MUST-NOT-LEAK",
        "prompt_messages": [{"role": "user", "content": "RAW-PROMPT-MUST-NOT-LEAK"}],
        "usage": {"input_tokens": 10, "output_tokens": 4},
        "latency_ms": 25,
        "max_tokens": 4,
    }
    (root / "logs" / "calls.jsonl").write_text(json.dumps(call) + "\n")
    frontier = {
        "timestamp": "2026-09-09T09:00:00Z", "vendor": "codex",
        "duration_ms": 50, "exit_code": 0, "model_ids": ["test-model"],
    }
    (root / "run_state" / "frontier_calls.jsonl").write_text(json.dumps(frontier) + "\n")
    return root


def _snapshot_from_prompt(prompt: str) -> dict:
    return json.loads(prompt.split("SNAPSHOT_JSON_BEGIN\n", 1)[1].split("\nSNAPSHOT_JSON_END", 1)[0])


def _proposal(snapshot: dict, **updates) -> dict:
    evidence = next(item for item in snapshot["files"] if item["path"] == "AGENTS.md")
    manifest = next(
        item for item in snapshot["evaluation_manifests"]
        if item["path"] == "bench/weekly_upgrade_eval/fixtures.json"
    )
    digest = wu._sha(snapshot)
    value = {
        "schema_version": "weekly-upgrade-v1",
        "week_id": snapshot["week_id"],
        "snapshot_sha256": digest,
        "proposal_id": f"wu-{digest[:8]}",
        "title": "Compare one bounded sampling policy",
        "claim": "The candidate changes parsed fixture success under a fixed budget.",
        "repo_references": [{
            "path": "AGENTS.md", "locator": "maintenance authority",
            "sha256": evidence["sha256"],
        }],
        "external_claims": [],
        "change_surface": ["bench/weekly_upgrade_eval/manifest.json"],
        "tier": "P",
        "baseline": {
            "status": "UNMEASURED", "artifact": None,
            "artifact_sha256": None, "measurement_locator": None,
            "metric": "parsed_success_rate", "value": None,
        },
        "candidate": {"single_delta": "temperature 0.0 to 0.2"},
        "experiment": {
            "fixture_manifest_path": manifest["path"],
            "fixture_manifest_sha256": manifest["sha256"],
            "fixture_ids": ["critic-01", "critic-02"],
            "arms": ["baseline", "candidate"], "seeds": [0, 1],
            "max_gpu_minutes": 10, "max_wall_minutes": 20,
            "max_frontier_calls": 0, "primary_metric": "parsed_success_rate",
            "guardrails": ["zero malformed tool calls"],
            "pass_rule": "candidate succeeds on both paired fixtures",
        },
        "falsifier": "Any paired fixture regresses.",
        "abort_conditions": ["memory floor is breached"],
        "execution_scope": "EVALUATION_ONLY",
        "production_change_authorized": False,
    }
    value.update(updates)
    return value


def _adversary(snapshot: dict, proposal: dict, verdict="survives_to_evaluation") -> dict:
    return {
        "schema_version": "weekly-upgrade-v1",
        "week_id": snapshot["week_id"],
        "snapshot_sha256": wu._sha(snapshot),
        "proposal_id": proposal["proposal_id"],
        "verdict": verdict,
        "violated_rules": [],
        "objections": [],
        "cheapest_decisive_test": "Run the two paired fixtures.",
        "residual_risks": ["small sample"],
        "external_claims": [],
    }


class FakeFrontier:
    def __init__(self, verdict="survives_to_evaluation", proposal_mutator=None,
                 adversary_mutator=None):
        self.calls = []
        self.verdict = verdict
        self.proposal_mutator = proposal_mutator
        self.adversary_mutator = adversary_mutator

    def __call__(self, vendor, prompt, *, timeout_s, role, ledger_path=None):
        self.calls.append({"vendor": vendor, "prompt": prompt, "role": role,
                           "timeout_s": timeout_s, "ledger_path": ledger_path})
        snapshot = _snapshot_from_prompt(prompt)
        if role == "upgrade_proposer":
            value = _proposal(snapshot)
            if self.proposal_mutator:
                value = self.proposal_mutator(value)
        else:
            proposal = json.loads(
                prompt.split("IMMUTABLE_PROPOSAL_JSON_BEGIN\n", 1)[1]
                .split("\nIMMUTABLE_PROPOSAL_JSON_END", 1)[0]
            )
            value = _adversary(snapshot, proposal, self.verdict)
            if self.adversary_mutator:
                value = self.adversary_mutator(value)
        return {
            "text": json.dumps(value), "vendor": vendor,
            "cli_version": "test-double-1", "duration_ms": 3,
            "exit_code": 0, "error": None,
            "metadata": {"model_ids": [f"{vendor}-test"], "auth_mode": "test"},
        }


def _run(repo: Path, out: Path, invoke, **overrides):
    kwargs = {
        "frontier_call_budget": 2,
        "total_deadline_s": 600,
        "max_gpu_minutes": 30,
        "call_timeout_s": 120,
        "invoke_fn": invoke,
        "now_fn": lambda: NOW,
    }
    kwargs.update(overrides)
    return wu.run_review(repo, out, **kwargs)


def test_schema_is_valid_and_closed():
    schema = json.loads(wu.SCHEMA_PATH.read_text())
    Draft202012Validator.check_schema(schema)
    assert schema["$defs"]["report"]["additionalProperties"] is False
    assert schema["$defs"]["proposal"]["additionalProperties"] is False
    assert schema["$defs"]["adversary"]["additionalProperties"] is False
    assert (
        schema["$defs"]["proposal"]["properties"]["experiment"]
        ["properties"]["max_gpu_minutes"]["maximum"]
    ) == 120
    assert (
        schema["$defs"]["experiment_card"]["properties"]["caps"]
        ["properties"]["gpu_minutes"]["maximum"]
    ) == 120
    assert (
        schema["$defs"]["run_manifest"]["properties"]["budget"]
        ["properties"]["max_gpu_minutes"]["maximum"]
    ) == 120
    assert schema["$defs"]["run_manifest"]["additionalProperties"] is False


def test_plan_is_offline_read_only_and_redacted(tmp_path):
    repo = _repo(tmp_path)
    before = sorted(p.relative_to(repo) for p in repo.rglob("*"))
    plan = wu.plan_review(repo, now=NOW)
    after = sorted(p.relative_to(repo) for p in repo.rglob("*"))
    rendered = json.dumps(plan)
    assert before == after
    assert plan["writes"] == []
    assert [c["vendor"] for c in plan["provider_calls"]] == ["codex", "claude"]
    assert "RAW-PROMPT-MUST-NOT-LEAK" not in rendered
    assert "RAW-COMPLETION-MUST-NOT-LEAK" not in rendered
    assert plan["snapshot"]["call_aggregates"][0]["at_cap"] == 1
    assert plan["snapshot"]["telemetry_window"] == {
        "start": "2026-09-07T12:00:00Z",
        "end_exclusive": "2026-09-14T12:00:00Z",
    }


def test_atomic_receipt_write_fsyncs_file_and_parent(tmp_path, monkeypatch):
    observed = []
    real_fsync = wu.os.fsync

    def record(fd):
        observed.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr(wu.os, "fsync", record)
    path = tmp_path / "receipts" / "reserved.json"
    wu._atomic_json(path, {"status": "reserved"})
    assert json.loads(path.read_text()) == {"status": "reserved"}
    assert len(observed) == 2


def test_prompt_supplies_exact_bindings_and_week_key_is_stable(tmp_path):
    repo = _repo(tmp_path)
    first = wu.build_snapshot(repo, now=NOW)
    later = wu.build_snapshot(
        repo, now=datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc),
    )
    assert first["week_key_sha256"] == later["week_key_sha256"]
    assert wu._sha(first) != wu._sha(later)
    prompt = wu._proposal_prompt(first, 30)
    assert f"week_id={first['week_id']}" in prompt
    assert f"snapshot_sha256={wu._sha(first)}" in prompt
    assert f"proposal_id=wu-{wu._sha(first)[:8]}" in prompt
    assert "CLAIM_HUMAN_VERIFIED" in prompt


def test_nonfinite_telemetry_is_dropped_before_snapshot_hashing(tmp_path):
    repo = _repo(tmp_path)
    row = json.loads((repo / "logs" / "calls.jsonl").read_text())
    row["latency_ms"] = float("nan")
    (repo / "logs" / "calls.jsonl").write_text(json.dumps(row) + "\n")
    plan = wu.plan_review(repo, now=NOW)
    assert plan["snapshot"]["call_aggregates"][0]["p50_latency_ms"] is None
    assert "NaN" not in wu._canonical(plan).decode()


def test_success_uses_exactly_two_providers_and_emits_inert_card(tmp_path):
    repo, out = _repo(tmp_path), tmp_path / "out"
    invoke = FakeFrontier()
    report = _run(repo, out, invoke)
    assert report["status"] == "CONTINUE_TRIAL"
    assert report["frontier_calls_used"] == 2
    assert [(c["vendor"], c["role"]) for c in invoke.calls] == [
        ("codex", "upgrade_proposer"), ("claude", "upgrade_adversary")]
    assert report["experiment_card"]["measurement_ref"] is None
    assert report["experiment_card"]["caps"]["frontier_calls"] == 0
    assert report["proposal_sha256"] == hashlib.sha256(
        wu._canonical(report["proposal"])
    ).hexdigest()
    card = report["experiment_card"]
    assert card["proposal_sha256"] == report["proposal_sha256"]
    assert card["fixture_ids"] == report["proposal"]["experiment"]["fixture_ids"]
    assert card["fixture_manifest_sha256"] == report["proposal"]["experiment"]["fixture_manifest_sha256"]
    assert card["seeds"] == [0, 1]
    assert card["baseline"]["status"] == "UNMEASURED"
    assert card["candidate"] == report["proposal"]["candidate"]
    assert card["pass_rule"] == report["proposal"]["experiment"]["pass_rule"]
    assert card["execution_scope"] == "EVALUATION_ONLY"
    assert card["production_change_authorized"] is False
    assert not any((out / name).exists() for name in ("packet.json", "promotion.json", "command.sh"))
    wu._validate("report", json.loads((out / "weekly_report.json").read_text()))


def test_adversary_kill_is_no_change(tmp_path):
    invoke = FakeFrontier(verdict="kill")
    report = _run(_repo(tmp_path), tmp_path / "out", invoke)
    assert report["status"] == "NO_CHANGE"
    assert report["experiment_card"] is None
    assert report["independence_loss"] is False


def test_snapshot_hash_mismatch_is_invalid_and_stops_before_claude(tmp_path):
    def corrupt(value):
        return {**value, "snapshot_sha256": "0" * 64}

    invoke = FakeFrontier(proposal_mutator=corrupt)
    report = _run(_repo(tmp_path), tmp_path / "out", invoke)
    assert report["status"] == "INVALID_REPORT"
    assert report["frontier_calls_used"] == 1
    assert [call["vendor"] for call in invoke.calls] == ["codex"]


def test_unverified_tier_or_surface_is_rejected(tmp_path):
    def corrupt(value):
        return {**value, "tier": "S", "change_surface": ["cron/serve-models.sh"]}

    report = _run(_repo(tmp_path), tmp_path / "out", FakeFrontier(proposal_mutator=corrupt))
    assert report["status"] == "INVALID_REPORT"
    assert "Tier-P" in report["reason"]


def test_provider_failure_never_becomes_one_provider_pass(tmp_path):
    calls = []

    def fail(vendor, prompt, **kwargs):
        calls.append(vendor)
        return {"text": "", "vendor": vendor, "cli_version": "x",
                "duration_ms": 1, "exit_code": 1, "error": "offline"}

    report = _run(_repo(tmp_path), tmp_path / "out", fail)
    assert report["status"] == "FRONTIER_UNAVAILABLE"
    assert report["independence_loss"] is True
    assert calls == ["codex"]


def test_transport_vendor_mismatch_is_frontier_unavailable(tmp_path):
    def mismatched(vendor, prompt, **kwargs):
        snapshot = _snapshot_from_prompt(prompt)
        return {
            "text": json.dumps(_proposal(snapshot)), "vendor": "claude",
            "cli_version": "test-double-1", "duration_ms": 1,
            "exit_code": 0, "error": None,
        }

    report = _run(_repo(tmp_path), tmp_path / "out", mismatched)
    assert report["status"] == "FRONTIER_UNAVAILABLE"
    assert report["frontier_calls_used"] == 1


def test_completed_run_is_idempotent(tmp_path):
    repo, out = _repo(tmp_path), tmp_path / "out"
    first = FakeFrontier()
    report1 = _run(repo, out, first)
    second = FakeFrontier()
    report2 = _run(repo, out, second)
    assert report2 == report1
    assert len(first.calls) == 2
    assert second.calls == []


def test_uncertain_reserved_call_is_not_repeated(tmp_path):
    repo, out = _repo(tmp_path), tmp_path / "out"

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        _run(repo, out, interrupt)
    assert json.loads(next((out / "receipts").glob("*.json")).read_text())["status"] == "reserved"
    retry = FakeFrontier()
    report = _run(repo, out, retry)
    assert report["status"] == "FRONTIER_UNAVAILABLE"
    assert "automatic retry is refused" in report["reason"]
    assert retry.calls == []


def test_resume_uses_frozen_snapshot_when_only_rolling_time_changes(
    tmp_path, monkeypatch,
):
    repo, out = _repo(tmp_path), tmp_path / "out"
    first = FakeFrontier()
    reserve = wu._reserve_call

    def interrupt_before_adversary(*args, **kwargs):
        if kwargs.get("ordinal") == 2:
            raise KeyboardInterrupt
        return reserve(*args, **kwargs)

    monkeypatch.setattr(wu, "_reserve_call", interrupt_before_adversary)
    with pytest.raises(KeyboardInterrupt):
        _run(repo, out, first)
    assert [call["vendor"] for call in first.calls] == ["codex"]
    monkeypatch.setattr(wu, "_reserve_call", reserve)

    second = FakeFrontier()
    later = NOW + timedelta(seconds=60)
    report = _run(repo, out, second, now_fn=lambda: later)
    assert report["status"] == "CONTINUE_TRIAL"
    assert [call["vendor"] for call in second.calls] == ["claude"]


def test_completed_receipt_without_validated_artifact_is_not_repeated(tmp_path):
    repo, out = _repo(tmp_path), tmp_path / "out"

    def invalid(vendor, prompt, **kwargs):
        return {"text": "not-json", "vendor": vendor,
                "cli_version": "test-double-1", "duration_ms": 1,
                "exit_code": 0, "error": None}

    first = _run(repo, out, invalid)
    assert first["status"] == "INVALID_REPORT"
    raw = json.loads(
        (out / "unvalidated" / "01-upgrade_proposer.json").read_text()
    )
    assert raw["validation_status"] == "UNVALIDATED"
    assert raw["text"] == "not-json"
    assert raw["content_sha256"] == hashlib.sha256(b"not-json").hexdigest()
    assert raw["truncated"] is False
    wu._validate("unvalidated_response", raw)
    (out / "weekly_report.json").unlink()  # simulate lost terminal write
    retry = FakeFrontier()
    report = _run(repo, out, retry)
    assert report["status"] == "FRONTIER_UNAVAILABLE"
    assert "automatic retry is refused" in report["reason"]
    assert retry.calls == []


def test_wrong_call_budget_fails_before_provider(tmp_path):
    invoke = FakeFrontier()
    report = _run(
        _repo(tmp_path), tmp_path / "out", invoke,
        frontier_call_budget=1,
    )
    assert report["status"] == "BUDGET_EXHAUSTED"
    assert report["frontier_calls_used"] == 0
    assert invoke.calls == []


def test_mock_default_transport_cannot_count_as_review(tmp_path, monkeypatch):
    monkeypatch.setenv("MOCK_LLM", "1")
    report = wu.run_review(
        _repo(tmp_path), tmp_path / "out", frontier_call_budget=2,
        total_deadline_s=600, max_gpu_minutes=0, now_fn=lambda: NOW,
    )
    assert report["status"] == "FRONTIER_UNAVAILABLE"
    assert report["frontier_calls_used"] == 0


def test_explicit_source_packet_validation_and_binding(tmp_path):
    packet_path = tmp_path / "sources.json"
    packet = {
        "schema_version": "weekly-upgrade-source-packet-v1",
        "sources": [{
            "url": "https://example.org/release",
            "publisher": "Example Project",
            "published_at": "2026-09-13",
            "accessed_at": "2026-09-14T11:00:00Z",
            "content_sha256": "a" * 64,
            "evidence": "The release changes one relevant behavior.",
            "verification_status": "HUMAN_VERIFIED",
            "verified_claims": [{
                "claim": "One behavior changed.",
                "evidence_excerpt": "changes one relevant behavior",
            }],
        }],
    }
    packet_path.write_text(json.dumps(packet))
    scanned = wu.scan_source_packet(packet_path)
    assert scanned["valid"] is True
    assert "no model or network" in scanned["note"]

    snapshot = wu.build_snapshot(_repo(tmp_path), source_packet=packet, now=NOW)
    proposal = _proposal(snapshot, external_claims=[{
        "claim": "One behavior changed.",
        "url": "https://example.org/release",
        "status": "CLAIM_HUMAN_VERIFIED",
        "content_sha256": "a" * 64,
        "evidence_excerpt": "changes one relevant behavior",
    }])
    assert wu.validate_proposal(proposal, snapshot, max_gpu_minutes=30) == proposal


def test_verified_external_claim_without_packet_is_rejected(tmp_path):
    snapshot = wu.build_snapshot(_repo(tmp_path), now=NOW)
    proposal = _proposal(snapshot, external_claims=[{
        "claim": "Unsupported release claim.",
        "url": "https://example.org/release",
        "status": "CLAIM_HUMAN_VERIFIED",
        "content_sha256": "a" * 64,
        "evidence_excerpt": "unsupported",
    }])
    with pytest.raises(Exception, match="exact reviewed source binding"):
        wu.validate_proposal(proposal, snapshot, max_gpu_minutes=30)


def test_repo_reference_locator_must_appear_in_snapshot_excerpt(tmp_path):
    snapshot = wu.build_snapshot(_repo(tmp_path), now=NOW)
    proposal = _proposal(snapshot)
    proposal["repo_references"][0]["locator"] = "invented locator"
    with pytest.raises(Exception, match="locator is not in snapshotted text"):
        wu.validate_proposal(proposal, snapshot, max_gpu_minutes=30)


def test_human_verified_claim_requires_exact_reviewed_claim_binding(tmp_path):
    packet = {
        "schema_version": "weekly-upgrade-source-packet-v1",
        "sources": [{
            "url": "https://example.org/release",
            "publisher": "Example Project",
            "published_at": "2026-09-13",
            "accessed_at": "2026-09-14T11:00:00Z",
            "content_sha256": "a" * 64,
            "evidence": "The release changes one relevant behavior.",
            "verification_status": "HUMAN_VERIFIED",
            "verified_claims": [{
                "claim": "One behavior changed.",
                "evidence_excerpt": "changes one relevant behavior",
            }],
        }],
    }
    snapshot = wu.build_snapshot(_repo(tmp_path), source_packet=packet, now=NOW)
    proposal = _proposal(snapshot, external_claims=[{
        "claim": "A different claim on the same page.",
        "url": "https://example.org/release",
        "status": "CLAIM_HUMAN_VERIFIED",
        "content_sha256": "a" * 64,
        "evidence_excerpt": "changes one relevant behavior",
    }])
    with pytest.raises(Exception, match="explicitly reviewed"):
        wu.validate_proposal(proposal, snapshot, max_gpu_minutes=30)


def test_measured_or_invented_baseline_is_rejected(tmp_path):
    snapshot = wu.build_snapshot(_repo(tmp_path), now=NOW)
    proposal = _proposal(snapshot, baseline={
        "status": "MEASURED",
        "artifact": "bench/nonexistent.json",
        "artifact_sha256": "f" * 64,
        "measurement_locator": "result.primary_metric",
        "metric": "parsed_success_rate",
        "value": 0.5,
    })
    with pytest.raises(Exception):
        wu.validate_proposal(proposal, snapshot, max_gpu_minutes=30)


def test_unknown_fixture_id_is_rejected(tmp_path):
    snapshot = wu.build_snapshot(_repo(tmp_path), now=NOW)
    proposal = _proposal(snapshot)
    proposal["experiment"]["fixture_ids"] = ["invented-fixture"]
    with pytest.raises(Exception, match="unknown fixture ids"):
        wu.validate_proposal(proposal, snapshot, max_gpu_minutes=30)


def test_adversary_revision_is_distinct_from_no_change(tmp_path):
    report = _run(_repo(tmp_path), tmp_path / "out", FakeFrontier(verdict="revise"))
    assert report["status"] == "REVISION_REQUIRED"
    assert report["experiment_card"] is None


def test_substantive_bounded_rule_explanation_is_accepted(tmp_path):
    explanation = "rule-ref: " + "substantive explanation " * 18
    assert 240 < len(explanation) < 1000

    def explain(value):
        value["verdict"] = "revise"
        value["violated_rules"] = [explanation]
        return value

    report = _run(
        _repo(tmp_path), tmp_path / "out",
        FakeFrontier(adversary_mutator=explain),
    )
    assert report["status"] == "REVISION_REQUIRED"
    assert report["adversary"]["violated_rules"] == [explanation]


@pytest.mark.parametrize("field", ["violated_rules", "objections"])
def test_survives_verdict_cannot_retain_material_findings(tmp_path, field):
    def corrupt(value):
        if field == "violated_rules":
            value[field] = ["scope violation"]
        else:
            evidence = next(
                item for item in snapshot["files"] if item["path"] == "AGENTS.md"
            )
            value[field] = [{
                "claim": "The proposal still has a material objection.",
                "repo_references": [{
                    "path": "AGENTS.md", "locator": "maintenance authority",
                    "sha256": evidence["sha256"],
                }],
                "falsifier": "Resolve the objection before evaluation.",
            }]
        return value

    repo = _repo(tmp_path)
    snapshot = wu.build_snapshot(repo, now=NOW)
    report = _run(
        repo, tmp_path / "out",
        FakeFrontier(adversary_mutator=corrupt),
    )
    assert report["status"] == "INVALID_REPORT"
    assert "cannot retain" in report["reason"]


class _Headers(dict):
    def get_content_type(self):
        return self["Content-Type"].split(";", 1)[0]


class _Response:
    def __init__(self, body: bytes, url="https://developers.openai.com/release"):
        self.body = body
        self.url = url
        self.status = 200
        self.headers = _Headers({
            "Content-Type": "text/html; charset=utf-8",
            "Content-Length": str(len(body)),
        })

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def geturl(self):
        return self.url

    def getcode(self):
        return self.status

    def read(self, limit):
        return self.body[:limit]


class _Opener:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        return self.response


def _public_dns(*args, **kwargs):
    return [(2, 1, 6, "", ("93.184.216.34", 443))]


def test_bounded_fetch_produces_unverified_source_and_receipt():
    body = b"<html><body>Official release evidence.</body></html>"
    opener = _Opener(_Response(body))
    config = {
        "schema_version": "weekly-upgrade-fetch-v1",
        "sources": [{
            "url": "https://developers.openai.com/release",
            "publisher": "OpenAI", "published_at": "2026-09-13",
        }],
    }
    result = wu.fetch_sources(
        config, resolver=_public_dns, opener_factory=lambda resolver: opener,
        now_fn=lambda: NOW,
    )
    source = result["source_packet"]["sources"][0]
    receipt = result["receipts"][0]
    assert source["verification_status"] == "FETCHED_UNVERIFIED"
    assert source["content_sha256"] == hashlib.sha256(body).hexdigest()
    assert source["evidence"] == "Official release evidence."
    assert receipt["status"] == "FETCHED_UNVERIFIED"
    assert receipt["retrieved_at"] == "2026-09-14T12:00:00Z"
    assert result["note"].endswith("FETCHED_UNVERIFIED.")
    assert len(opener.requests) == 1
    wu._validate("fetch_result", result)


def test_fetch_hard_deadline_interrupts_blocked_dns():
    config = {
        "schema_version": "weekly-upgrade-fetch-v1",
        "sources": [{
            "url": "https://developers.openai.com/release",
            "publisher": "OpenAI", "published_at": None,
        }],
    }

    def blocked_dns(*args, **kwargs):
        time.sleep(5)
        return _public_dns()

    started = time.monotonic()
    result = wu.fetch_sources(
        config, request_timeout_s=0.05, total_deadline_s=1,
        resolver=blocked_dns,
    )
    assert time.monotonic() - started < 0.5
    assert result["receipts"][0]["error_category"] == "TIMEOUT"


@pytest.mark.parametrize("url", [
    "https://127.0.0.1/release",
    "https://example.com/release",
    "https://github.com/untrusted/project",
    "https://user:secret@developers.openai.com/release",
])
def test_fetch_rejects_non_allowlisted_or_credential_urls(url):
    config = {
        "schema_version": "weekly-upgrade-fetch-v1",
        "sources": [{"url": url, "publisher": "X", "published_at": None}],
    }
    result = wu.fetch_sources(config, resolver=_public_dns)
    assert result["source_packet"]["sources"] == []
    assert result["receipts"][0]["error_category"] == "URL_REJECTED"


def test_fetch_config_requires_https_before_network():
    config = {
        "schema_version": "weekly-upgrade-fetch-v1",
        "sources": [{
            "url": "http://developers.openai.com/release",
            "publisher": "OpenAI", "published_at": None,
        }],
    }
    with pytest.raises(Exception, match="does not match"):
        wu.fetch_sources(config, resolver=_public_dns)


def test_fetched_source_does_not_validate_a_source_verified_claim(tmp_path):
    body = b"release"
    opener = _Opener(_Response(body))
    fetched = wu.fetch_sources({
        "schema_version": "weekly-upgrade-fetch-v1",
        "sources": [{
            "url": "https://developers.openai.com/release",
            "publisher": "OpenAI", "published_at": None,
        }],
    }, resolver=_public_dns, opener_factory=lambda resolver: opener, now_fn=lambda: NOW)
    snapshot = wu.build_snapshot(
        _repo(tmp_path), source_packet=fetched["source_packet"], now=NOW,
    )
    proposal = _proposal(snapshot, external_claims=[{
        "claim": "Fetched does not mean verified.",
        "url": "https://developers.openai.com/release",
        "status": "CLAIM_HUMAN_VERIFIED",
        "content_sha256": hashlib.sha256(body).hexdigest(),
        "evidence_excerpt": "release",
    }])
    with pytest.raises(Exception, match="exact reviewed source binding"):
        wu.validate_proposal(proposal, snapshot, max_gpu_minutes=30)


def test_generation_policy_path_is_allowed_for_inert_experiment(tmp_path):
    snapshot = wu.build_snapshot(_repo(tmp_path), now=NOW)
    proposal = _proposal(
        snapshot, change_surface=["agent_wrapper/generation_policy.py"],
    )
    assert wu.validate_proposal(proposal, snapshot, max_gpu_minutes=30) == proposal


def test_explicit_review_target_is_snapshot_bound_and_preserves_adversarial_rejection(tmp_path):
    repo = _repo(tmp_path)
    target = "experiments/topic_scope_repair_v2_2026-09-14.json"
    snapshot = wu.build_snapshot(repo, now=NOW, review_target_manifest=target)
    assert snapshot["review_target_manifest"] == target
    assert wu._stable_snapshot_binding(snapshot)["review_target_manifest"] == target
    assert "adversary may reject" in wu._proposal_prompt(snapshot, 120)
    with pytest.raises(Exception, match="explicit review target"):
        wu.validate_proposal(_proposal(snapshot), snapshot, max_gpu_minutes=30)
    with pytest.raises(wu.WeeklyUpgradeError, match="registered experiment"):
        wu.build_snapshot(repo, now=NOW, review_target_manifest="arbitrary-command.sh")


def test_registered_review_inputs_expose_actual_arms_and_grading_boundary():
    manifests = {row["path"]: row for row in wu._evaluation_manifests(wt.ROOT)}
    for name in ("topic_scope_repair_v2_2026-09-14.json",
                 "weekly_upgrade_game_science_dev_v0_2026-09-14.json",
                 "diversity_selection_dev_v0_2026-09-14.json"):
        path = f"experiments/{name}"
        document = json.loads((wt.ROOT / path).read_text())
        execution = manifests[path]["execution"]
        assert execution["arm_settings"] == document.get("arms", document.get("conditions"))
        assert execution["resource_limits"] == document["resource_limits"]
        assert execution["ordering"] == document["ordering"]
    topic = manifests["experiments/topic_scope_repair_v2_2026-09-14.json"]["execution"]
    assert topic["semantic_grading"] == "independent_blind_annotations_required_after_transport"
    prereg = wu._snapshot_file(wt.ROOT, "experiments/PREREG_weekly_upgrade_game_science_dev_v0_2026-09-14.md")
    assert "one seed" in prereg["evidence_excerpt"]
    assert "no result" in prereg["evidence_excerpt"].lower()


def test_review_resolves_implicit_qwen_thinking_in_deterministic_profile():
    policies = wu._resolved_review_arms({"arms": [
        {"id": "A", "backend": "vllm-gemma", "model": "gemma-4-26b-a4b",
         "profile": "deterministic", "seed": 0},
        {"id": "B", "backend": "vllm-qwen", "model": "qwen3.8-27b-nvfp4-mtp",
         "profile": "deterministic", "seed": 0},
    ]})
    assert policies[0]["effective_reasoning_effort"] is None
    assert policies[0]["gemma_thinking"] is False
    assert policies[1]["effective_reasoning_effort"] == "xhigh"
    assert policies[1]["request_kwargs"] == {"temperature": 0.0, "top_p": 1.0, "seed": 0}


def _write_canonical(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(wu._canonical(value) + b"\n")


def test_worktree_snapshot_uses_canonical_production_telemetry(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    canonical = tmp_path / "production"
    (canonical / "logs").mkdir(parents=True)
    (canonical / "logs" / "calls.jsonl").write_text(json.dumps({
        "timestamp": "2026-09-13T10:00:00Z", "caller_tag": "production_loop",
        "backend": "vllm-gemma", "usage": {"input_tokens": 100, "output_tokens": 20},
        "latency_ms": 1000, "max_tokens": 100, "completion": "private",
    }) + "\n")
    monkeypatch.setattr(wt, "canonical_root", lambda _root: canonical)
    snapshot = wu.build_snapshot(repo, now=NOW)
    assert snapshot["telemetry_source"] == "canonical_checkout"
    assert [row["caller_tag"] for row in snapshot["call_aggregates"]] == ["production_loop"]
    assert "private" not in json.dumps(snapshot["call_aggregates"])


def _receipt_observations(**updates):
    value = {
        "fixed_attempts_expected": 80,
        "fixed_attempts_returned": 79,
        "fixed_attempts_protocol_valid": 79,
        "objective_cases_passed": None,
        "objective_cases_total": None,
        "repair_cases_passed": 1,
        "repair_cases_total": 12,
        "annotation_disagreements": 3,
    }
    value.update(updates)
    return value


def test_operational_history_binds_sanitized_evaluation_receipt(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    history = tmp_path / "history"
    history.mkdir()
    monkeypatch.setattr(wt, "canonical_root", lambda root: repo)
    trial_id = "2026-W38-topic-scope-v1"
    output = tmp_path / "trial-output"
    result = {
        "trial_id": trial_id,
        "status": "failed",
        "elapsed_s": 137.0,
        "evaluation": {"sha256": "e" * 64, "execution_complete": False},
        "budget_receipt": None,
        "semantic_benefit_measured": False,
    }
    ledger = BudgetLedger(repo / "run_state" / "weekly_upgrade_budget.jsonl")
    ledger.reserve(trial_id, 2_400, "d" * 64, now=NOW)
    result["budget_receipt"] = ledger.finish(trial_id, 137, "failed", now=NOW)
    (output / "trial_result.json").parent.mkdir(parents=True)
    (output / "trial_result.json").write_bytes(
        json.dumps(result, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    )
    journal = {
        "phase": "finished",
        "plan": {
            "trial_id": trial_id, "week_id": "2026-W38",
            "manifest_path": "experiments/topic_scope_repair_2026-09-14.json",
            "kind": "topic_scope",
            "arm_ids": ["control", "candidate"], "declared_attempts": 80,
        },
        "output": str(output),
        "result": result,
    }
    journal_path = repo / "run_state" / "weekly_upgrade" / "trials" / f"{trial_id}.json"
    _write_canonical(journal_path, journal)
    receipt = {
        "schema_version": "weekly-upgrade-evaluation-summary/v1",
        "trial_id": trial_id,
        "recorded_at": "2026-09-14T11:30:00Z",
        "provenance": "operator_recorded",
        "trial_journal_sha256": wu._file_sha(journal_path),
        "trial_result_sha256": wu._file_sha(output / "trial_result.json"),
        "transport_evaluation_sha256": "e" * 64,
        "summary_artifact_sha256": "c" * 64,
        "annotation_artifacts": [{
            "provenance": "independent_subscription_annotation",
            "vendor": "claude",
            "artifact_sha256": "a" * 64,
            "transport_receipt_sha256": "b" * 64,
            "model_ids": ["claude-opus-5"],
        }],
        "observations": {
            **_receipt_observations(),
            "failure_categories": [{"code": "incomplete_transport", "count": 1}],
        },
        "arm_observations": [
            {"arm": "control", **_receipt_observations(
                fixed_attempts_expected=40, fixed_attempts_returned=40,
                fixed_attempts_protocol_valid=40, repair_cases_passed=0,
                repair_cases_total=6, annotation_disagreements=0,
            )},
            {"arm": "candidate", **_receipt_observations(
                fixed_attempts_expected=40, fixed_attempts_returned=39,
                fixed_attempts_protocol_valid=39, repair_cases_passed=1,
                repair_cases_total=6, annotation_disagreements=3,
            )},
        ],
    }
    receipt_path = (
        repo / "run_state" / "weekly_upgrade" / "evaluations" / f"{trial_id}.json"
    )
    _write_canonical(receipt_path, receipt)

    before = sorted(path.relative_to(repo) for path in repo.rglob("*"))
    snapshot = wu.build_snapshot(
        repo, operational_history_root=history, now=NOW,
    )
    after = sorted(path.relative_to(repo) for path in repo.rglob("*"))
    operational = snapshot["operational_history"]
    assert before == after
    assert operational["status"] == "validated"
    assert operational["trials"][0]["status"] == "failed"
    summary = operational["evaluation_summaries"][0]
    assert summary["evidence_class"] == "UNVERIFIED_OPERATOR_SUMMARY"
    assert summary["candidate_benefit_verified"] is False
    assert summary["arm_observations"][0]["repair_cases_passed"] == 0
    assert summary["arm_observations"][1]["repair_cases_passed"] == 1
    assert operational["invalid_artifact_counts"] == {
        "trials": 0, "evaluation_summaries": 0, "prior_reviews": 0,
    }


def test_operational_history_rejects_receipt_hash_as_untrusted(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    history = tmp_path / "history"
    history.mkdir()
    monkeypatch.setattr(wt, "canonical_root", lambda root: repo)
    evaluation = repo / "run_state" / "weekly_upgrade" / "evaluations"
    _write_canonical(evaluation / "orphan.json", {
        "schema_version": "weekly-upgrade-evaluation-summary/v1",
    })
    snapshot = wu.build_snapshot(
        repo, operational_history_root=history, now=NOW,
    )
    operational = snapshot["operational_history"]
    assert operational["evaluation_summaries"] == []
    assert operational["invalid_artifact_counts"]["evaluation_summaries"] == 1


def test_naive_snapshot_time_is_rejected(tmp_path):
    with pytest.raises(wu.WeeklyUpgradeError, match="timezone aware"):
        wu.build_snapshot(_repo(tmp_path), now=NOW.replace(tzinfo=None))


def test_openai_model_catalog_host_is_allowlisted():
    assert "learn.chatgpt.com" in wu.OFFICIAL_SOURCE_RULES


def test_github_release_api_is_bounded_to_allowed_owners_and_semantic_fields():
    accepted = wu._validate_source_url(
        "https://api.github.com/repos/vllm-project/vllm/releases/latest",
        resolver=_public_dns,
    )
    assert accepted.endswith("/repos/vllm-project/vllm/releases/latest")
    with pytest.raises(wu.WeeklyUpgradeError, match="outside the official allowlist"):
        wu._validate_source_url(
            "https://api.github.com/repos/untrusted/project/releases/latest",
            resolver=_public_dns,
        )
    raw = json.dumps({
        "assets": [{"name": "x" * 3000}],
        "tag_name": "v0.29.0", "published_at": "2026-09-13T00:00:00Z",
        "html_url": "https://github.com/vllm-project/vllm/releases/tag/v0.29.0",
        "body": "Important correctness fix after a large asset list.",
    }).encode()
    excerpt = wu._source_excerpt(raw, "application/json")
    assert "v0.29.0" in excerpt
    assert "Important correctness fix" in excerpt
    assert "assets" not in excerpt
    assert len(excerpt) <= 2000


def test_operational_object_reads_are_bounded_and_bind_exact_bytes(tmp_path, monkeypatch):
    path = tmp_path / "receipt.json"
    path.write_bytes(b'{"value":1}\n')
    monkeypatch.setattr(Path, "read_bytes", lambda self: pytest.fail("unbounded read forbidden"))
    value, digest = wu._bounded_object(path, with_hash=True)
    assert value == {"value": 1}
    assert digest == wu._sha(b'{"value":1}\n')
    with pytest.raises(wu.WeeklyUpgradeError, match="exceeds"):
        wu._bounded_object(path, maximum=4)
    redirected = tmp_path / "redirected.json"
    redirected.symlink_to(path)
    with pytest.raises(wu.WeeklyUpgradeError, match="redirected"):
        wu._bounded_object(redirected)
