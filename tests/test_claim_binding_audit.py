# Source: oracle_system/tests/test_apparatus_audit.py
# Inspected source SHA256: 45a1cbb7586926067aa0613e34728eac7dc27793c45147815b8779880bba0367
# Lab-owned candidate copy; no Oracle runtime dependency. Source behavior retained.
from __future__ import annotations

from hashlib import sha256
import json

import pytest

from tools import audit_claim_binding as cli
import tools.claim_binding_audit as apparatus_audit_module
from tools.claim_binding_audit import (
    ApparatusAuditInputError,
    DOWNSTREAM_STAGES,
    audit_claim_bindings,
)


def _write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def _completion(stage, hypothesis_text, *, arguments=None):
    if arguments is None:
        arguments = json.dumps({"hypothesis_text": hypothesis_text})
    return json.dumps(
        [
            {
                "id": f"tool-{stage}",
                "type": "function",
                "function": {"name": stage, "arguments": arguments},
            }
        ]
    )


def _call(
    request_id,
    completion,
    *,
    run_id="iter-1",
    caller_tag="nara.run_iteration",
    parent_request_id="iter-1",
):
    return {
        "request_id": request_id,
        "run_id": run_id,
        "caller_tag": caller_tag,
        "parent_request_id": parent_request_id,
        "completion": completion,
    }


def _iteration(hypothesis_text, wrapper_call_ids):
    return {
        "iteration_id": "iter-1",
        "hypothesis": {"text": hypothesis_text},
        "wrapper_call_ids": wrapper_call_ids,
    }


def test_all_three_stages_bind_and_exact_ids_exclude_same_run_lookalikes(tmp_path):
    hypothesis = "Canonical claim, byte for byte."
    loop_memory = tmp_path / "loop_memory.jsonl"
    call_log = tmp_path / "calls.jsonl"
    linked = ["linked-retrieve", "linked-novelty", "linked-critic"]
    _write_jsonl(loop_memory, [_iteration(hypothesis, linked)])
    _write_jsonl(
        call_log,
        [
            # These share the run_id and duplicate target stages, but they are
            # not named by wrapper_call_ids and therefore are not evidence.
            _call("unrelated-1", _completion("retrieve_literature", "stale")),
            _call("unrelated-2", _completion("retrieve_literature", "stale")),
            _call(linked[0], _completion("retrieve_literature", hypothesis)),
            _call(
                linked[1],
                _completion("novelty_classify", hypothesis),
                parent_request_id=linked[0],
            ),
            _call(
                linked[2],
                _completion("critic_loop_v0", hypothesis),
                parent_request_id=linked[1],
            ),
        ],
    )
    before_loop = loop_memory.read_bytes()
    before_calls = call_log.read_bytes()

    report = audit_claim_bindings(loop_memory, call_log)

    assert report["passed"] is True
    assert report["policy"]["authority_effect"] == "none"
    assert "consistency" in report["policy"]["source_authentication"]
    assert report["policy"]["dispatch_or_execution_proof"] is False
    assert report["aggregate"]["stage_status"] == {
        "bound": 3,
        "mismatch": 0,
        "unverifiable": 0,
    }
    assert report["aggregate"]["stage_status_by_name"] == {
        stage: {"bound": 1, "mismatch": 0, "unverifiable": 0}
        for stage in DOWNSTREAM_STAGES
    }
    iteration = report["iterations"][0]
    assert iteration["status"] == "bound"
    assert set(iteration["stages"]) == set(DOWNSTREAM_STAGES)
    for stage, request_id in zip(DOWNSTREAM_STAGES, linked, strict=True):
        result = iteration["stages"][stage]
        assert result["status"] == "bound"
        assert result["evidence"][0]["request_id"] == request_id
        assert result["evidence"][0]["comparison"] == "exact_match"
    assert report["sources"]["loop_memory"]["sha256"] == (
        "sha256:" + sha256(before_loop).hexdigest()
    )
    assert report["sources"]["call_log"]["sha256"] == (
        "sha256:" + sha256(before_calls).hexdigest()
    )
    assert set(report["sources"]["loop_memory"]["fingerprint"]) == {
        "device",
        "inode",
        "size",
        "mtime_ns",
        "ctime_ns",
    }
    assert loop_memory.read_bytes() == before_loop
    assert call_log.read_bytes() == before_calls


def test_multiple_attributable_calls_for_a_stage_all_must_match(tmp_path):
    hypothesis = "Canonical claim."
    loop_memory = tmp_path / "loop_memory.jsonl"
    call_log = tmp_path / "calls.jsonl"
    linked = ["retrieve-1", "retrieve-2", "novelty", "critic"]
    _write_jsonl(loop_memory, [_iteration(hypothesis, linked)])

    def write_calls(second_retrieval):
        _write_jsonl(
            call_log,
            [
                _call(linked[0], _completion("retrieve_literature", hypothesis)),
                _call(
                    linked[1],
                    _completion("retrieve_literature", second_retrieval),
                    parent_request_id=linked[0],
                ),
                _call(
                    linked[2],
                    _completion("novelty_classify", hypothesis),
                    parent_request_id=linked[1],
                ),
                _call(
                    linked[3],
                    _completion("critic_loop_v0", hypothesis),
                    parent_request_id=linked[2],
                ),
            ],
        )

    write_calls(hypothesis)
    matching = audit_claim_bindings(loop_memory, call_log)
    result = matching["iterations"][0]["stages"]["retrieve_literature"]
    assert matching["passed"] is True
    assert len(result["evidence"]) == 2
    assert {item["comparison"] for item in result["evidence"]} == {"exact_match"}

    write_calls("Stale claim.")
    mismatching = audit_claim_bindings(loop_memory, call_log)
    result = mismatching["iterations"][0]["stages"]["retrieve_literature"]
    assert mismatching["passed"] is False
    assert result["status"] == "mismatch"
    assert {item["comparison"] for item in result["evidence"]} == {
        "exact_match",
        "exact_mismatch",
    }


def test_revised_canonical_hypothesis_detects_stale_downstream_argument(tmp_path):
    canonical = "Revised canonical hypothesis."
    stale = "Earlier hypothesis that downstream evidence still discusses."
    loop_memory = tmp_path / "loop_memory.jsonl"
    call_log = tmp_path / "calls.jsonl"
    linked = ["retrieve", "novelty", "critic"]
    _write_jsonl(loop_memory, [_iteration(canonical, linked)])
    _write_jsonl(
        call_log,
        [
            _call(linked[0], _completion("retrieve_literature", stale)),
            _call(
                linked[1],
                _completion("novelty_classify", canonical),
                parent_request_id=linked[0],
            ),
            _call(
                linked[2],
                _completion("critic_loop_v0", canonical),
                parent_request_id=linked[1],
            ),
        ],
    )

    report = audit_claim_bindings(loop_memory, call_log)

    iteration = report["iterations"][0]
    assert report["passed"] is False
    assert iteration["status"] == "mismatch"
    mismatch = iteration["stages"]["retrieve_literature"]
    assert mismatch["status"] == "mismatch"
    assert mismatch["evidence"][0]["comparison"] == "exact_mismatch"
    assert mismatch["evidence"][0]["hypothesis_text_sha256"] != (
        iteration["canonical_hypothesis"]["sha256"]
    )


def test_missing_exact_call_id_makes_binding_unverifiable(tmp_path):
    hypothesis = "Claim."
    loop_memory = tmp_path / "loop_memory.jsonl"
    call_log = tmp_path / "calls.jsonl"
    linked = ["retrieve", "novelty", "critic", "missing"]
    _write_jsonl(loop_memory, [_iteration(hypothesis, linked)])
    _write_jsonl(
        call_log,
        [
            _call(linked[0], _completion("retrieve_literature", hypothesis)),
            _call(
                linked[1],
                _completion("novelty_classify", hypothesis),
                parent_request_id=linked[0],
            ),
            _call(
                linked[2],
                _completion("critic_loop_v0", hypothesis),
                parent_request_id=linked[1],
            ),
        ],
    )

    report = audit_claim_bindings(loop_memory, call_log)

    iteration = report["iterations"][0]
    assert report["passed"] is False
    assert iteration["status"] == "unverifiable"
    assert "wrapper_call_id_missing:missing" in iteration["link_issues"]
    assert {result["status"] for result in iteration["stages"].values()} == {
        "unverifiable"
    }


def test_malformed_tool_arguments_and_completions_are_unverifiable(tmp_path):
    loop_memory = tmp_path / "loop_memory.jsonl"
    call_log = tmp_path / "calls.jsonl"
    linked = ["retrieve", "novelty", "critic"]
    _write_jsonl(loop_memory, [_iteration("Claim.", linked)])
    _write_jsonl(
        call_log,
        [
            _call(
                linked[0],
                _completion("retrieve_literature", "unused", arguments="{bad-json"),
            ),
            _call(
                linked[1],
                "{not-a-json-completion",
                parent_request_id=linked[0],
            ),
            _call(
                linked[2],
                json.dumps({"not": "an array"}),
                parent_request_id=linked[1],
            ),
        ],
    )

    report = audit_claim_bindings(loop_memory, call_log)

    iteration = report["iterations"][0]
    assert iteration["stages"]["retrieve_literature"]["status"] == "unverifiable"
    assert (
        iteration["stages"]["retrieve_literature"]["evidence"][0]["extraction"]
        == "arguments_not_json"
    )
    assert iteration["stages"]["novelty_classify"]["status"] == "unverifiable"
    assert iteration["stages"]["critic_loop_v0"]["status"] == "unverifiable"
    assert [item["status"] for item in iteration["linked_call_diagnostics"]] == [
        "structured_json_array",
        "completion_not_json",
        "completion_not_json_array",
    ]


def test_duplicate_argument_key_is_ambiguous_not_last_value_wins(tmp_path):
    hypothesis = "Canonical claim."
    loop_memory = tmp_path / "loop_memory.jsonl"
    call_log = tmp_path / "calls.jsonl"
    linked = ["retrieve", "novelty", "critic"]
    _write_jsonl(loop_memory, [_iteration(hypothesis, linked)])
    ambiguous_arguments = (
        '{"hypothesis_text":"stale",'
        '"hypothesis_text":"Canonical claim."}'
    )
    _write_jsonl(
        call_log,
        [
            _call(
                linked[0],
                _completion(
                    "retrieve_literature",
                    hypothesis,
                    arguments=ambiguous_arguments,
                ),
            ),
            _call(
                linked[1],
                _completion("novelty_classify", hypothesis),
                parent_request_id=linked[0],
            ),
            _call(
                linked[2],
                _completion("critic_loop_v0", hypothesis),
                parent_request_id=linked[1],
            ),
        ],
    )

    report = audit_claim_bindings(loop_memory, call_log)

    assert report["passed"] is False
    result = report["iterations"][0]["stages"]["retrieve_literature"]
    assert result["status"] == "unverifiable"
    assert result["evidence"][0]["extraction"] == (
        "arguments_duplicate_object_key"
    )


@pytest.mark.parametrize("position", [0, 2, 3])
@pytest.mark.parametrize(
    "completion",
    [
        None,
        "",
        "The iteration is complete.",
        "{not-json",
        '{"not":"an array"}',
        '"terminal text"',
        '[{"id":"hidden","id":"duplicate"}]',
        "[NaN]",
        "[1e999]",
        '["\\ud800"]',
        "[" + "9" * 5000 + "]",
    ],
    ids=[
        "missing",
        "empty",
        "prose",
        "malformed_json",
        "object",
        "json_string",
        "duplicate_key",
        "non_json_number",
        "overflow",
        "surrogate",
        "decoder_limit",
    ],
)
def test_matching_stages_cannot_hide_an_unverifiable_linked_completion(
    tmp_path, completion, position
):
    hypothesis = "Canonical claim."
    loop_memory = tmp_path / "loop_memory.jsonl"
    call_log = tmp_path / "calls.jsonl"
    completions = [
        (stage, _completion(stage, hypothesis))
        for stage in DOWNSTREAM_STAGES
    ]
    completions.insert(position, ("invalid", completion))
    linked = [request_id for request_id, _ in completions]
    _write_jsonl(loop_memory, [_iteration(hypothesis, linked)])
    _write_jsonl(
        call_log,
        [
            _call(
                request_id,
                value,
                parent_request_id="iter-1" if index == 0 else linked[index - 1],
            )
            for index, (request_id, value) in enumerate(completions)
        ],
    )

    report = audit_claim_bindings(loop_memory, call_log)

    assert report["passed"] is False
    iteration = report["iterations"][0]
    assert iteration["status"] == "unverifiable"
    assert "wrapper_call_completion_unverifiable:invalid" in iteration["link_issues"]
    assert {stage["status"] for stage in iteration["stages"].values()} == {
        "unverifiable"
    }


@pytest.mark.parametrize("completion", ["[]", _completion("journal", "Claim.")])
def test_valid_non_target_completion_preserves_bound_evidence(tmp_path, completion):
    hypothesis = "Canonical claim."
    loop_memory = tmp_path / "loop_memory.jsonl"
    call_log = tmp_path / "calls.jsonl"
    linked = [*DOWNSTREAM_STAGES, "terminal"]
    _write_jsonl(loop_memory, [_iteration(hypothesis, linked)])
    _write_jsonl(
        call_log,
        [
            _call(
                request_id,
                _completion(request_id, hypothesis)
                if request_id in DOWNSTREAM_STAGES
                else completion,
                parent_request_id="iter-1" if index == 0 else linked[index - 1],
            )
            for index, request_id in enumerate(linked)
        ],
    )

    report = audit_claim_bindings(loop_memory, call_log)

    assert report["passed"] is True
    assert report["iterations"][0]["link_issues"] == []


def test_unverifiable_completion_preserves_positive_mismatch_evidence(tmp_path):
    loop_memory = tmp_path / "loop_memory.jsonl"
    call_log = tmp_path / "calls.jsonl"
    linked = [*DOWNSTREAM_STAGES, "invalid"]
    _write_jsonl(loop_memory, [_iteration("Canonical claim.", linked)])
    _write_jsonl(
        call_log,
        [
            _call(
                request_id,
                _completion(request_id, "Stale claim.")
                if request_id in DOWNSTREAM_STAGES
                else "[malformed",
                parent_request_id="iter-1" if index == 0 else linked[index - 1],
            )
            for index, request_id in enumerate(linked)
        ],
    )

    report = audit_claim_bindings(loop_memory, call_log)

    assert report["passed"] is False
    iteration = report["iterations"][0]
    assert iteration["status"] == "mismatch"
    assert "wrapper_call_completion_unverifiable:invalid" in iteration["link_issues"]
    assert {stage["status"] for stage in iteration["stages"].values()} == {"mismatch"}


def test_duplicate_exact_request_id_is_ambiguous_not_a_pass(tmp_path):
    loop_memory = tmp_path / "loop_memory.jsonl"
    call_log = tmp_path / "calls.jsonl"
    _write_jsonl(loop_memory, [_iteration("Claim.", ["same-id"])])
    _write_jsonl(
        call_log,
        [
            _call("same-id", _completion("retrieve_literature", "Claim.")),
            _call("same-id", _completion("retrieve_literature", "Claim.")),
        ],
    )

    report = audit_claim_bindings(loop_memory, call_log)

    iteration = report["iterations"][0]
    assert iteration["status"] == "unverifiable"
    assert iteration["linked_call_diagnostics"][0]["status"] == (
        "duplicated_in_call_log"
    )


def test_cross_run_wrapper_ids_and_malformed_tool_envelopes_do_not_bind(tmp_path):
    hypothesis = "Claim."
    loop_memory = tmp_path / "loop_memory.jsonl"
    call_log = tmp_path / "calls.jsonl"
    linked = ["wrong-run", "wrong-type", "missing-id"]
    _write_jsonl(loop_memory, [_iteration(hypothesis, linked)])
    wrong_type = json.loads(_completion("novelty_classify", hypothesis))
    wrong_type[0]["type"] = "not-a-function"
    missing_id = json.loads(_completion("critic_loop_v0", hypothesis))
    missing_id[0].pop("id")
    _write_jsonl(
        call_log,
        [
            _call(
                linked[0],
                _completion("retrieve_literature", hypothesis),
                run_id="iter-other",
            ),
            _call(
                linked[1],
                json.dumps(wrong_type),
                parent_request_id=linked[0],
            ),
            _call(
                linked[2],
                json.dumps(missing_id),
                parent_request_id=linked[1],
            ),
        ],
    )

    report = audit_claim_bindings(loop_memory, call_log)

    iteration = report["iterations"][0]
    assert report["passed"] is False
    assert iteration["status"] == "unverifiable"
    assert (
        "wrapper_call_run_id_missing_or_mismatch:wrong-run"
        in iteration["link_issues"]
    )
    assert {result["status"] for result in iteration["stages"].values()} == {
        "unverifiable"
    }
    assert iteration["linked_call_diagnostics"][1]["malformed_array_items"] == 1
    assert iteration["linked_call_diagnostics"][2]["malformed_array_items"] == 1


@pytest.mark.parametrize(
    "attack",
    [
        "malformed_member",
        "duplicate_tool_id",
        "missing_function_name",
        "nonstring_function_name",
        "missing_function_arguments",
    ],
)
def test_matching_call_cannot_hide_completion_envelope_ambiguity(tmp_path, attack):
    hypothesis = "Claim."
    loop_memory = tmp_path / "loop_memory.jsonl"
    call_log = tmp_path / "calls.jsonl"
    linked = ["retrieve", "novelty", "critic"]
    _write_jsonl(loop_memory, [_iteration(hypothesis, linked)])
    retrieve_calls = json.loads(_completion("retrieve_literature", hypothesis))
    if attack == "malformed_member":
        retrieve_calls.append({"malformed": "not-a-tool-call"})
    elif attack == "duplicate_tool_id":
        duplicate = json.loads(_completion("novelty_classify", hypothesis))[0]
        duplicate["id"] = retrieve_calls[0]["id"]
        retrieve_calls.append(duplicate)
    else:
        malformed_function = {
            "id": "extra-tool",
            "type": "function",
            "function": {"name": "unknown_tool", "arguments": "{}"},
        }
        if attack == "missing_function_name":
            malformed_function["function"].pop("name")
        elif attack == "nonstring_function_name":
            malformed_function["function"]["name"] = 7
        else:
            malformed_function["function"].pop("arguments")
        retrieve_calls.append(malformed_function)
    _write_jsonl(
        call_log,
        [
            _call(linked[0], json.dumps(retrieve_calls)),
            _call(
                linked[1],
                _completion("novelty_classify", hypothesis),
                parent_request_id=linked[0],
            ),
            _call(
                linked[2],
                _completion("critic_loop_v0", hypothesis),
                parent_request_id=linked[1],
            ),
        ],
    )

    report = audit_claim_bindings(loop_memory, call_log)

    assert report["passed"] is False
    iteration = report["iterations"][0]
    assert iteration["status"] == "unverifiable"
    assert (
        "wrapper_call_completion_ambiguous:retrieve"
        in iteration["link_issues"]
    )
    assert iteration["linked_call_diagnostics"][0]["status"] == (
        "structured_json_array_ambiguous"
    )


@pytest.mark.parametrize(
    ("field", "value", "issue"),
    [
        (
            "caller_tag",
            "different.caller",
            "wrapper_call_caller_tag_missing_or_mismatch",
        ),
        (
            "parent_request_id",
            "same-run-but-wrong-parent",
            "wrapper_call_parent_request_id_missing_or_mismatch",
        ),
    ],
)
def test_same_run_call_graft_fails_caller_and_parent_chain(
    tmp_path, field, value, issue
):
    hypothesis = "Claim."
    loop_memory = tmp_path / "loop_memory.jsonl"
    call_log = tmp_path / "calls.jsonl"
    linked = ["retrieve", "novelty", "critic"]
    _write_jsonl(loop_memory, [_iteration(hypothesis, linked)])
    graft = _call(
        linked[1],
        _completion("novelty_classify", hypothesis),
        parent_request_id=linked[0],
    )
    graft[field] = value
    _write_jsonl(
        call_log,
        [
            _call(linked[0], _completion("retrieve_literature", hypothesis)),
            graft,
            _call(
                linked[2],
                _completion("critic_loop_v0", hypothesis),
                parent_request_id=linked[1],
            ),
        ],
    )

    report = audit_claim_bindings(loop_memory, call_log)

    assert report["passed"] is False
    iteration = report["iterations"][0]
    assert iteration["status"] == "unverifiable"
    assert any(item.startswith(issue) for item in iteration["link_issues"])


def test_malformed_jsonl_fails_closed_with_line_locator(tmp_path):
    loop_memory = tmp_path / "loop_memory.jsonl"
    call_log = tmp_path / "calls.jsonl"
    loop_memory.write_text("not-json\n")
    call_log.write_text("")

    with pytest.raises(ApparatusAuditInputError, match="loop-memory row 1"):
        audit_claim_bindings(loop_memory, call_log)


def test_duplicate_key_in_jsonl_source_fails_input_integrity(tmp_path):
    loop_memory = tmp_path / "loop_memory.jsonl"
    call_log = tmp_path / "calls.jsonl"
    loop_memory.write_text(
        '{"iteration_id":"stale","iteration_id":"iter-1",'
        '"hypothesis":{"text":"Claim."},"wrapper_call_ids":[]}\n'
    )
    call_log.write_text("")

    with pytest.raises(ApparatusAuditInputError, match="duplicate object key"):
        audit_claim_bindings(loop_memory, call_log)


@pytest.mark.parametrize(
    ("raw_value", "match"),
    [
        ('{"text":"\\ud800"}', "surrogate code point"),
        ('{"text":"Claim.","not_json":NaN}', "non-JSON numeric constant"),
        ('{"text":"Claim.","overflow":1e999}', "not finite"),
        ('{"text":"Claim.","too_large":' + "9" * 5000 + "}", "decoder limit"),
    ],
)
def test_nonportable_json_values_fail_input_integrity(tmp_path, raw_value, match):
    loop_memory = tmp_path / "loop_memory.jsonl"
    call_log = tmp_path / "calls.jsonl"
    loop_memory.write_text(
        '{"iteration_id":"iter-1","hypothesis":'
        + raw_value
        + ',"wrapper_call_ids":[]}\n'
    )
    call_log.write_text("")

    with pytest.raises(ApparatusAuditInputError, match=match):
        audit_claim_bindings(loop_memory, call_log)


def test_source_append_between_reads_fails_final_fingerprint_check(
    tmp_path, monkeypatch
):
    loop_memory = tmp_path / "loop_memory.jsonl"
    call_log = tmp_path / "calls.jsonl"
    _write_jsonl(loop_memory, [_iteration("Claim.", ["retrieve"])])
    _write_jsonl(
        call_log,
        [_call("retrieve", _completion("retrieve_literature", "Claim."))],
    )
    original_read_jsonl = apparatus_audit_module._read_jsonl
    mutated = False

    def read_then_mutate(
        path,
        label,
        *,
        keep=None,
        byte_limit=None,
        expected_sha256=None,
        initial_fingerprint=None,
    ):
        nonlocal mutated
        result = original_read_jsonl(
            path,
            label,
            keep=keep,
            byte_limit=byte_limit,
            expected_sha256=expected_sha256,
            initial_fingerprint=initial_fingerprint,
        )
        if label == "loop-memory" and not mutated:
            with loop_memory.open("ab") as stream:
                stream.write(b"{}\n")
            mutated = True
        return result

    monkeypatch.setattr(apparatus_audit_module, "_read_jsonl", read_then_mutate)

    with pytest.raises(
        ApparatusAuditInputError,
        match="loop-memory .* changed during apparatus audit .*final post-read check",
    ):
        audit_claim_bindings(loop_memory, call_log)


def test_call_append_after_loop_read_violates_precaptured_snapshot(
    tmp_path, monkeypatch
):
    loop_memory = tmp_path / "loop_memory.jsonl"
    call_log = tmp_path / "calls.jsonl"
    _write_jsonl(loop_memory, [_iteration("Claim.", ["retrieve"])])
    call_log.write_text("")
    original_read_jsonl = apparatus_audit_module._read_jsonl
    mutated = False

    def read_then_graft(
        path,
        label,
        *,
        keep=None,
        byte_limit=None,
        expected_sha256=None,
        initial_fingerprint=None,
    ):
        nonlocal mutated
        result = original_read_jsonl(
            path,
            label,
            keep=keep,
            byte_limit=byte_limit,
            expected_sha256=expected_sha256,
            initial_fingerprint=initial_fingerprint,
        )
        if label == "loop-memory" and not mutated:
            _write_jsonl(
                call_log,
                [_call("retrieve", _completion("retrieve_literature", "Claim."))],
            )
            mutated = True
        return result

    monkeypatch.setattr(apparatus_audit_module, "_read_jsonl", read_then_graft)

    with pytest.raises(
        ApparatusAuditInputError,
        match="call-log .* changed during apparatus audit .*snapshot check",
    ):
        audit_claim_bindings(loop_memory, call_log)


def test_cli_defaults_to_fixed_sources_and_details_are_explicit(
    tmp_path, capsys, monkeypatch
):
    loop_memory = tmp_path / "loop_memory.jsonl"
    call_log = tmp_path / "calls.jsonl"
    _write_jsonl(loop_memory, [_iteration("Claim.", ["missing"])])
    call_log.write_text("")
    monkeypatch.setattr(cli, "LOOP_MEMORY", loop_memory)
    monkeypatch.setattr(cli, "CALL_LOG", call_log)

    assert cli.main(["apparatus-audit"]) == 1
    summary = json.loads(capsys.readouterr().out)
    assert summary["passed"] is False
    assert set(summary) == {
        "schema",
        "classification",
        "audit",
        "policy",
        "sources",
        "aggregate",
        "passed",
    }
    assert "iterations" not in summary

    assert (
        cli.main(["apparatus-audit", "--details"])
        == 1
    )
    detailed = json.loads(capsys.readouterr().out)
    assert detailed["passed"] is False
    assert detailed["iterations"][0]["iteration_id"] == "iter-1"

    loop_memory.write_text("not-json\n")
    assert (
        cli.main(["apparatus-audit"])
        == 2
    )
    assert "apparatus audit input invalid" in capsys.readouterr().err


def test_cli_requires_complete_prefix_replay_tuple(capsys):
    assert (
        cli.main(["apparatus-audit", "--loop-prefix-bytes", "10"])
        == 2
    )
    assert "requires both byte limits and both hashes" in capsys.readouterr().err


def test_library_requires_complete_prefix_replay_tuple(tmp_path):
    loop_memory = tmp_path / "loop_memory.jsonl"
    call_log = tmp_path / "calls.jsonl"
    _write_jsonl(loop_memory, [_iteration("Claim.", [])])
    call_log.write_text("")

    with pytest.raises(
        ApparatusAuditInputError,
        match="requires both byte limits and both hashes",
    ):
        audit_claim_bindings(
            loop_memory,
            call_log,
            loop_memory_bytes=len(loop_memory.read_bytes()),
        )


def test_pinned_byte_prefix_replays_after_sources_append(tmp_path):
    hypothesis = "Pinned claim."
    loop_memory = tmp_path / "loop_memory.jsonl"
    call_log = tmp_path / "calls.jsonl"
    linked = ["r1", "n1", "c1"]
    _write_jsonl(loop_memory, [_iteration(hypothesis, linked)])
    _write_jsonl(
        call_log,
        [
            _call(linked[0], _completion("retrieve_literature", hypothesis)),
            _call(
                linked[1],
                _completion("novelty_classify", hypothesis),
                parent_request_id=linked[0],
            ),
            _call(
                linked[2],
                _completion("critic_loop_v0", hypothesis),
                parent_request_id=linked[1],
            ),
        ],
    )
    loop_prefix = loop_memory.read_bytes()
    call_prefix = call_log.read_bytes()
    with loop_memory.open("ab") as stream:
        stream.write(
            (json.dumps({
                "iteration_id": "iter-2",
                "hypothesis": {"text": "Later claim."},
                "wrapper_call_ids": ["r2", "n2", "c2"],
            }) + "\n").encode()
        )
    with call_log.open("ab") as stream:
        parent_request_id = "iter-2"
        for stage, request_id in zip(DOWNSTREAM_STAGES, ["r2", "n2", "c2"]):
            stream.write(
                (json.dumps(_call(
                    request_id,
                    _completion(stage, "Later claim."),
                    run_id="iter-2",
                    parent_request_id=parent_request_id,
                )) + "\n").encode()
            )
            parent_request_id = request_id

    report = audit_claim_bindings(
        loop_memory,
        call_log,
        loop_memory_bytes=len(loop_prefix),
        call_log_bytes=len(call_prefix),
        expected_loop_memory_sha256=sha256(loop_prefix).hexdigest(),
        expected_call_log_sha256=sha256(call_prefix).hexdigest(),
    )

    assert report["passed"] is True
    assert report["aggregate"]["iterations"] == 1
    assert report["sources"]["loop_memory"]["prefix_mode"] is True
    assert report["sources"]["call_log"]["prefix_mode"] is True


def test_symlink_and_non_row_aligned_prefix_are_rejected(tmp_path):
    loop_memory = tmp_path / "loop_memory.jsonl"
    call_log = tmp_path / "calls.jsonl"
    _write_jsonl(loop_memory, [_iteration("Claim.", ["r"])])
    _write_jsonl(call_log, [_call("r", _completion("retrieve_literature", "Claim."))])
    symlink = tmp_path / "linked-loop.jsonl"
    symlink.symlink_to(loop_memory)

    with pytest.raises(ApparatusAuditInputError, match="non-symlink regular file"):
        audit_claim_bindings(symlink, call_log)
    with pytest.raises(ApparatusAuditInputError, match="row boundary"):
        loop_prefix = loop_memory.read_bytes()[:-1]
        call_prefix = call_log.read_bytes()
        audit_claim_bindings(
            loop_memory,
            call_log,
            loop_memory_bytes=len(loop_prefix),
            call_log_bytes=len(call_prefix),
            expected_loop_memory_sha256=sha256(loop_prefix).hexdigest(),
            expected_call_log_sha256=sha256(call_prefix).hexdigest(),
        )
