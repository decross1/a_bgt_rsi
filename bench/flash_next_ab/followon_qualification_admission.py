"""Registered Mia follow-on v5 qualification admission.

Pure receipt validation; no model, Docker or service calls.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import harness as h
from .harness import HarnessError

_read_json_receipt = h._read_json_receipt
_read_regular_file = h._read_regular_file
_digest = h._digest
_qualification_sha256 = h._qualification_sha256
_qualification_runtime_sha256 = h._qualification_runtime_sha256
_utc_datetime = h._utc_datetime
_finite_number = h._finite_number
_validate_memory_log = h._validate_memory_log
_validate_flash_probes = h._validate_flash_probes
_validate_mia_probe_attempts = h._validate_mia_probe_attempts


def _validate_profile_canary(run_dir: Path, result: dict[str, Any], spec: Any) -> None:
    """Bind the selected v5 canary to each completed private SSE stream."""
    from .followon_canaries import (
        CONTEXT_PACKET_SHA256,
        CONTEXT_SELECTED_CELL_ID,
        CONTEXT_SELECTED_MESSAGES_SHA256,
        MTP_PROTOCOL_SHA256,
        _protocol,
        decoded_view,
    )
    from .followon_profiles import MIA_CTX69632
    from .private_evidence import PrivateEvidenceError, _response_matches_raw
    from .transport import LocalEndpoint, canonical, request_body

    summary, summary_sha, summary_file = _read_json_receipt(
        run_dir / "profile-canary.json", "Mia v5 profile canary"
    )
    attempts, attempts_sha, attempts_file = _read_json_receipt(
        run_dir / "profile-canary-attempts.json", "Mia v5 canary attempts"
    )
    if (summary_file != run_dir / "profile-canary.json"
        or attempts_file != run_dir / "profile-canary-attempts.json"
        or summary.get("schema") != "flash-next-mia-profile-canary/v1"
        or attempts.get("schema") != "flash-next-mia-profile-canary-attempts/v1"
        or summary.get("status") != "passed"
        or summary.get("spec_id") != spec.spec_id
        or attempts.get("spec_id") != spec.spec_id
        or summary.get("probe_set") != spec.qualification_probe_set
        or attempts.get("probe_set") != spec.qualification_probe_set
        or summary.get("lossless_claim") is not False
        or summary.get("target_token_id_parity") != "unavailable"
        or result.get("profile_canary_status") != "passed"
        or result.get("profile_canary_sha256") != summary_sha
        or result.get("profile_canary_attempts_sha256") != attempts_sha
        or result.get("profile_canary_protocol_sha256") != summary.get("protocol_sha256")
        or result.get("profile_canary_suite") != summary.get("suite")
        or result.get("profile_canary_attempt_count") != summary.get("attempt_count")
        or result.get("profile_canary_timeout_seconds")
           != spec.profile_canary_timeout_seconds
    ):
        raise HarnessError("Mia v5 canary identity or result binding differs")
    restoration = result.get("restoration")
    if (not isinstance(restoration, dict)
        or not _utc_datetime(result.get("started_at"), "Mia v5 start")
           <= _utc_datetime(summary.get("finished_at"), "Mia v5 canary finish")
           <= _utc_datetime(restoration.get("verified_at"), "Mia v5 restoration")):
        raise HarnessError("Mia v5 canary was not inside its supervised window")

    if spec.mtp_speculative_tokens:
        protocol = _protocol()  # Rechecks the byte-for-byte prospective source.
        source_requests = protocol["requests"]
        expected_ids = [(row["id"], repetition)
                        for row in source_requests for repetition in range(3)]
        protocol_sha = MTP_PROTOCOL_SHA256
        suite = ("reduced47k_v2full4_mtp_greedy_repeats"
                 if spec.draft_vocab_path is not None else
                 "fullvocab_mtp_greedy_repeats")
        if summary.get("decoded_parity_status") != "pending_repeated_mtp0_control_comparison":
            raise HarnessError("Mia MTP canary claimed parity without the separate controls")
        if summary.get("attempt_count") != 12:
            raise HarnessError("Mia MTP canary repetition count differs")
        policy = {key: protocol["request_policy"][key]
                  for key in ("temperature", "top_p", "enable_thinking")}
        seed = protocol["request_policy"]["seed"]
    elif spec is MIA_CTX69632:
        protocol_sha = CONTEXT_PACKET_SHA256
        suite = "native69632_near_ceiling"
        expected_ids = [("native69632_near_ceiling", 0)]
        if (summary.get("cell_id") != CONTEXT_SELECTED_CELL_ID
            or summary.get("source_messages_sha256") != CONTEXT_SELECTED_MESSAGES_SHA256
            or summary.get("actual_input_tokens") != 65_581
            or summary.get("reserved_output_tokens") != 2048
            or summary.get("attempt_count") != 1):
            raise HarnessError("Mia native-context frozen packet differs")
        policy = {"temperature": 0, "top_p": 1, "enable_thinking": False}
        seed = 17
        from .followon_canaries import CONTEXT_EXPECTED_TEXT, CONTEXT_PACKET_PATH
        pack_raw, pack_file = _read_regular_file(
            CONTEXT_PACKET_PATH, label="Mia native-context frozen pack",
            max_bytes=8 * 1024 * 1024,
        )
        if (pack_file != CONTEXT_PACKET_PATH
            or hashlib.sha256(pack_raw).hexdigest() != CONTEXT_PACKET_SHA256):
            raise HarnessError("Mia native-context pack bytes differ")
        try:
            pack = json.loads(pack_raw)
            selected = [row for row in pack["tasks"]
                        if row.get("id") == CONTEXT_SELECTED_CELL_ID]
        except (KeyError, TypeError, ValueError) as exc:
            raise HarnessError("Mia native-context pack is malformed") from exc
        if (len(selected) != 1
            or selected[0].get("messages_sha256") != CONTEXT_SELECTED_MESSAGES_SHA256
            or _qualification_sha256(selected[0].get("messages"))
               != CONTEXT_SELECTED_MESSAGES_SHA256
            or selected[0].get("actual_input_tokens") != 65_581
            or selected[0].get("max_output_tokens") != 2048
            or selected[0].get("grader", {}).get("expected")
               != json.loads(CONTEXT_EXPECTED_TEXT)):
            raise HarnessError("Mia native-context selected source differs")
        source_requests = [{"messages": selected[0]["messages"],
                            "max_tokens": 2048, "tools": None}]
    else:
        raise HarnessError("Mia v5 canary has no registered source")

    rows = attempts.get("results")
    if (summary.get("protocol_sha256") != protocol_sha
        or attempts.get("protocol_sha256") != protocol_sha
        or summary.get("suite") != suite
        or not isinstance(rows, list)
        or len(rows) != len(expected_ids)
        or [(row.get("request_id"), row.get("repetition"))
            for row in rows if isinstance(row, dict)] != expected_ids):
        raise HarnessError("Mia v5 canary source or attempt coverage differs")
    endpoint = LocalEndpoint(spec.endpoint_name,
                             f"http://127.0.0.1:{spec.host_port}/v1",
                             spec.served_name, spec.model_artifact_sha256())
    for index, row in enumerate(rows):
        public = row.get("public_response")
        private = row.get("private_response")
        if (row.get("status") != "passed" or not isinstance(public, dict)
            or not isinstance(private, dict)
            or row.get("decoded_view") != decoded_view(public)
            or public.get("response_model") != spec.served_name
            or public.get("endpoint") != endpoint.__dict__
            or public.get("response_stream_sha256") != private.get("response_stream_sha256")
            or row.get("request_sha256") != public.get("request_sha256")
            or _utc_datetime(row.get("started_at"), "Mia v5 canary start")
               > _utc_datetime(row.get("finished_at"), "Mia v5 canary finish")):
            raise HarnessError("Mia v5 canary public/private row differs")
        expected_relpath = f"private-probes/canary_{row['request_id']}_{row['repetition']}.sse"
        if (private.get("private_stream_relpath") != expected_relpath
            or type(private.get("response_stream_bytes")) is not int
            or not 0 < private["response_stream_bytes"] <= 8 * 1024 * 1024
            or not _digest(private.get("response_stream_sha256"))):
            raise HarnessError("Mia v5 canary private descriptor differs")
        raw, raw_file = _read_regular_file(run_dir / expected_relpath,
                                           label="Mia v5 private canary SSE",
                                           max_bytes=8 * 1024 * 1024)
        if (raw_file != run_dir / expected_relpath
            or len(raw) != private["response_stream_bytes"]
            or hashlib.sha256(raw).hexdigest() != private["response_stream_sha256"]):
            raise HarnessError("Mia v5 canary raw SSE differs")
        try:
            _response_matches_raw(raw, public, {"served_model": spec.served_name})
        except PrivateEvidenceError as exc:
            raise HarnessError("Mia v5 canary public response differs from raw SSE") from exc
        view = decoded_view(public)
        request_id = row["request_id"]
        if request_id == "structured_tool":
            tools = view["tool_calls"]
            try:
                valid_tool = (len(tools) == 1
                              and tools[0]["name"] == "record_probe"
                              and json.loads(tools[0]["arguments"])
                                  == {"label": "mtp-parity", "value": 703})
            except (TypeError, ValueError, KeyError):
                valid_tool = False
            if view["finish_reason"] != "tool_calls" or not valid_tool:
                raise HarnessError("Mia v5 MTP tool canary objective differs")
        elif view["finish_reason"] != "stop":
            raise HarnessError("Mia v5 canary did not terminate normally")
        if request_id == "literal64" and view["content"] != "ALPHA17_BETA703_GAMMA29_DELTA11":
            raise HarnessError("Mia v5 MTP literal objective differs")
        if request_id == "short_reasoned_answer" and view["content"] != "1,1,1,1":
            raise HarnessError("Mia v5 MTP arithmetic objective differs")
        if request_id == "native69632_near_ceiling":
            from .followon_canaries import CONTEXT_EXPECTED_TEXT
            try:
                native_answer = json.loads(view["content"] or "")
            except (TypeError, ValueError):
                native_answer = None
            if (native_answer != json.loads(CONTEXT_EXPECTED_TEXT)
                or view["tool_calls"]):
                raise HarnessError("Mia v5 native-context answer differs")
        if spec.mtp_speculative_tokens:
            source = source_requests[index // 3]
            expected_body = request_body(endpoint, source["messages"], policy,
                                         source["max_tokens"], seed, source.get("tools"))
            if (public.get("resolved_request") != expected_body
                or public.get("request_sha256")
                   != hashlib.sha256(canonical(expected_body)).hexdigest()):
                raise HarnessError("Mia v5 MTP canary request differs from frozen protocol")
        else:
            source = source_requests[0]
            expected_body = request_body(endpoint, source["messages"], policy,
                                         source["max_tokens"], seed, source["tools"])
            if (row.get("cell_id") != CONTEXT_SELECTED_CELL_ID
                or row.get("source_messages_sha256") != CONTEXT_SELECTED_MESSAGES_SHA256
                or row.get("actual_input_tokens") != 65_581
                or row.get("reserved_output_tokens") != 2048
                or public.get("resolved_request") is not None
                or not isinstance(public.get("usage"), dict)
                or public["usage"].get("prompt_tokens") != 65_581
                or public.get("request_sha256")
                   != hashlib.sha256(canonical(expected_body)).hexdigest()):
                raise HarnessError("Mia v5 native-context request/usage differs")

def validate_mia_v5_bundle(
    result: dict[str, Any], receipt_sha256: str, receipt_file: Path,
    qualification_plan: dict[str, Any], plan_file: Path,
    contract: dict[str, Any], contract_snapshot_sha256: str, contract_file: Path,
    *, contract_raw_path: str | Path | None, require_passed: bool,
) -> dict[str, Any]:
    """Admit one exact registered v5 Mia profile after restoration."""
    from . import qualification as registered
    from .candidate_registry import select_candidate
    from .followon_dispatch import FOLLOWON_CODE_ROOT, frozen_followon_source_bundle
    from .followon_profiles import is_registered_spec, requires_profile_canary
    from .mia_candidate_integration import (
        MiaRegistrationError,
        plan_mia_qualification,
        validate_mia_contract,
    )

    try:
        spec = select_candidate(contract)
    except (TypeError, ValueError) as exc:
        raise HarnessError("v5 candidate is not an exact code-owned profile") from exc
    if spec is None or not is_registered_spec(spec) or not requires_profile_canary(spec):
        raise HarnessError("v5 candidate is not an exact code-owned profile")
    failures: list[str] = []
    if (
        qualification_plan.get("schema") != "qwen-flash-next-qualification-plan/v5"
        or contract.get("schema") != spec.contract_schema
        or result.get("schema") != "qwen-flash-next-qualification-result/v5"
    ):
        raise HarnessError("unsupported Mia qualification schema bundle")
    if (
        receipt_file.name != "result.json"
        or plan_file != receipt_file.parent / "plan.json"
        or contract_file != receipt_file.parent / "launch-contract.snapshot.json"
        or result.get("run_id") != receipt_file.parent.name
        or not receipt_file.parent.name.startswith(spec.run_id_prefix)
    ):
        raise HarnessError("Mia qualification siblings or run ID differ")
    raw_path = Path(contract_raw_path) if contract_raw_path is not None else (
        receipt_file.parent / "launch-contract.raw.json"
    )
    raw_file = None
    try:
        raw_contract, contract_sha256, raw_file = _read_json_receipt(
            raw_path, "Mia raw qualification contract"
        )
        if raw_file != receipt_file.parent / "launch-contract.raw.json":
            raise HarnessError("Mia raw contract is not this run's fixed sibling")
        if raw_contract != contract:
            raise HarnessError("Mia raw contract content differs from snapshot")
    except HarnessError as exc:
        failures.append(str(exc))
        contract_sha256 = result.get("contract_sha256")
    if (
        not _digest(contract_sha256)
        or qualification_plan.get("contract_sha256") != contract_sha256
        or result.get("contract_sha256") != contract_sha256
    ):
        raise HarnessError("Mia result, plan and raw contract identity differ")
    try:
        validate_mia_contract(contract, registered)
    except (MiaRegistrationError, registered.QualificationError) as exc:
        failures.append(f"Mia contract is not registered: {exc}")
    try:
        expected_plan = plan_mia_qualification(
            contract, contract_sha256, receipt_file.parent, registered
        )
        if qualification_plan != expected_plan:
            raise HarnessError("v5 full plan differs from code-owned registration")
    except HarnessError as exc:
        failures.append(str(exc))
    if result.get("plan_sha256") != _qualification_sha256(qualification_plan):
        raise HarnessError("Mia result does not bind its full plan")
    if (
        qualification_plan.get("registered_code_root") != str(FOLLOWON_CODE_ROOT)
        or qualification_plan.get("followon_source_bundle")
           != frozen_followon_source_bundle()
        or qualification_plan.get("followon_source_bundle_sha256")
           != _qualification_sha256(qualification_plan.get("followon_source_bundle"))
        or result.get("followon_source_bundle_sha256")
           != qualification_plan.get("followon_source_bundle_sha256")
    ):
        raise HarnessError("Mia v5 controller source bundle or result digest differs")
    if any((result.get("candidate") != qualification_plan.get("candidate"),
            result.get("profile") != spec.profile,
            result.get("model_artifact_sha256") != spec.model_artifact_sha256(),
            result.get("proof_receipts") != qualification_plan.get("proof_receipts"),
            qualification_plan.get("image_id") != spec.image_id,
            qualification_plan.get("docker_create_argv_sha256")
            != _qualification_sha256(qualification_plan.get("docker_create_argv")),
            result.get("paging_policy") != spec.paging_policy(),
            qualification_plan.get("paging_policy") != spec.paging_policy(),
            result.get("docker_memory_limit_bytes") != spec.docker_memory_limit_bytes,
            result.get("docker_memory_swap_total_bytes") != spec.docker_memory_limit_bytes,
            qualification_plan.get("min_mem_available_gib") != spec.min_mem_available_gib,
            qualification_plan.get("served_model") != spec.served_name,
            qualification_plan.get("container_name") != spec.container_name,
            qualification_plan.get("model_path") != str(spec.model_path))):
        raise HarnessError("Mia result identity, argv or paging policy differs")

    if result.get("status") != "passed":
        failures.append(f"status={result.get('status')!r}")
    if result.get("qualification_error") is not None or result.get("failure_stage") is not None:
        failures.append("Mia qualification has an error or failure stage")
    if result.get("weekly_budget_debit") is not False or type(result.get("paid_api_calls")) is not int or result["paid_api_calls"] != 0:
        failures.append("Mia qualification debited budget or used paid API")
    if result.get("production_change_authorized") is not False:
        failures.append("Mia qualification claims production authority")
    restoration = result.get("restoration")
    if (not isinstance(restoration, dict) or restoration.get("status") != "verified"
        or restoration.get("errors") != [] or restoration.get("sentinel_retained") is not False):
        failures.append("Mia restoration is not clean and verified")
    else:
        try:
            start = _utc_datetime(result.get("started_at"), "Mia start")
            verified = _utc_datetime(restoration.get("verified_at"), "Mia restoration")
            finished = _utc_datetime(result.get("finished_at"), "Mia finish")
            if not start <= verified <= finished <= datetime.now(timezone.utc):
                raise HarnessError("Mia restoration chronology differs")
        except HarnessError as exc:
            failures.append(str(exc))
    for key in ("elapsed_seconds", "challenger_gpu_seconds",
                "all_gpu_research_seconds", "resident_downtime_seconds"):
        try:
            if _finite_number(result.get(key), f"Mia {key}") < 0:
                raise HarnessError(f"Mia {key} is negative")
        except HarnessError as exc:
            failures.append(str(exc))
    try:
        minimum_observed = _finite_number(
            result.get("min_mem_available_gib"), "Mia minimum MemAvailable"
        )
        if minimum_observed < spec.min_mem_available_gib:
            failures.append("Mia memory floor was breached")
    except HarnessError as exc:
        minimum_observed = None
        failures.append(str(exc))
    if type(result.get("probe_count")) is not int or result["probe_count"] != 3:
        failures.append("Mia three fixed probes did not return")
    try:
        worker_state, _, state_file = _read_json_receipt(
            receipt_file.parent / "state.json", "Mia terminal worker state"
        )
        supervision, _, supervision_file = _read_json_receipt(
            receipt_file.parent / "supervision.json", "Mia supervisor closure"
        )
        worker_pid = worker_state.get("worker_pid")
        argv = supervision.get("argv")
        expected_tail = [
            "-m", "bench.flash_next_ab.qualification", "--worker",
            "--contract", str(spec.contract_path),
            "--output-dir", str(receipt_file.parent),
        ]
        if (
            state_file != receipt_file.parent / "state.json"
            or supervision_file != receipt_file.parent / "supervision.json"
            or worker_state.get("schema") != "qwen-flash-next-qualification-state/v5"
            or worker_state.get("run_id") != result.get("run_id")
            or worker_state.get("plan_sha256") != result.get("plan_sha256")
            or worker_state.get("contract_sha256") != contract_sha256
            or worker_state.get("followon_source_bundle_sha256")
               != qualification_plan.get("followon_source_bundle_sha256")
            or worker_state.get("candidate") != qualification_plan.get("candidate")
            or worker_state.get("model_artifact_sha256") != spec.model_artifact_sha256()
            or worker_state.get("phase") != "complete"
            or worker_state.get("result_status") != "passed"
            or worker_state.get("restoration") != restoration
            or type(worker_pid) is not int or worker_pid <= 0
            or type(worker_state.get("worker_start_ticks")) is not int
            or worker_state["worker_start_ticks"] <= 0
            or supervision.get("schema") != "qwen-flash-next-supervision/v1"
            or type(supervision.get("pid")) is not int
            or supervision["pid"] != worker_pid
            or not isinstance(worker_state.get("boot_id"), str)
            or worker_state["boot_id"] != supervision.get("boot_id")
            or supervision.get("worker_start_ticks")
               != worker_state.get("worker_start_ticks")
            or type(supervision.get("returncode")) is not int
            or supervision["returncode"] != 0
            or supervision.get("terminated_at_work_cutoff") is not False
            or supervision.get("force_killed") is not False
            or supervision.get("emergency_recovery") is not None
            or not isinstance(argv, list) or len(argv) != 8
            or not isinstance(argv[0], str) or not Path(argv[0]).is_absolute()
            or argv[1:] != expected_tail
            or supervision.get("argv_sha256") != _qualification_sha256(argv)
            or supervision.get("hard_deadline_seconds")
               != contract["safety"]["invocation_deadline_seconds"]
            or _finite_number(supervision.get("elapsed_seconds"), "Mia supervisor elapsed") <= 0
            or _finite_number(supervision.get("elapsed_seconds"), "Mia supervisor elapsed")
               > contract["safety"]["invocation_deadline_seconds"]
            or not _utc_datetime(result.get("finished_at"), "Mia worker finish")
               <= _utc_datetime(worker_state.get("updated_at"), "Mia state update")
               <= _utc_datetime(supervision.get("finished_at"), "Mia supervisor finish")
               <= datetime.now(timezone.utc)
        ):
            raise HarnessError("Mia terminal worker or supervisor closure differs")
    except HarnessError as exc:
        failures.append(str(exc))
    try:
        _validate_memory_log(receipt_file.parent / "memory.jsonl", result, spec=spec)
    except HarnessError as exc:
        failures.append(str(exc))

    try:
        ready, _, ready_file = _read_json_receipt(
            receipt_file.parent / "readiness.json", "Mia readiness proof"
        )
        container, quiet = ready.get("container"), ready.get("stabilization")
        if ready_file != receipt_file.parent / "readiness.json" or not isinstance(container, dict) or not isinstance(quiet, dict):
            raise HarnessError("Mia readiness identity or stabilization is absent")
        quiet_keys = {
            "required_seconds": "required_seconds", "passed": "passed",
            "started_at": "started_at", "completed_at": "completed_at",
            "duration_seconds": "duration_seconds",
            "initial_pswpout_pages": "initial_pswpout_pages",
            "final_pswpout_pages": "final_pswpout_pages",
            "samples": "samples", "epoch": "epoch",
        }
        if (
            ready.get("models") != [spec.served_name]
            or not _digest(container.get("id"))
            or result.get("candidate_cgroup_path") != f"/system.slice/docker-{container.get('id')}.scope"
            or container.get("pid") != result.get("candidate_cgroup_pid")
            or container.get("image") != spec.image_id
            or container.get("name") != spec.container_name
            or container.get("running") is not True
            or container.get("oom_killed") is not False
            or container.get("memory_limit_bytes") != spec.docker_memory_limit_bytes
            or container.get("memory_swap_total_bytes") != spec.docker_memory_limit_bytes
            or type(container.get("restart_count")) is not int
            or container["restart_count"] != 0
            or any(quiet.get(key) != result.get(f"ready_quiescence_{suffix}")
                   for key, suffix in quiet_keys.items())
            or _utc_datetime(ready.get("ready_at"), "Mia readiness time")
               > _utc_datetime(result.get("ready_quiescence_started_at"),
                               "Mia ready stabilization start")
        ):
            raise HarnessError("Mia readiness and post-ready quiet proof differ")
    except HarnessError as exc:
        failures.append(str(exc))

    try:
        probes, _, probes_file = _read_json_receipt(
            receipt_file.parent / "probes.json", "Mia qualification probes"
        )
        if probes_file != receipt_file.parent / "probes.json":
            raise HarnessError("Mia probe sibling differs")
        _validate_flash_probes(
            probes, probe_set=qualification_plan["probe_set"],
            served_model=spec.served_name,
            artifact_sha256=spec.model_artifact_sha256(),
            endpoint_name=spec.endpoint_name,
        )
        _validate_mia_probe_attempts(receipt_file.parent, probes)
    except HarnessError as exc:
        failures.append(str(exc))

    try:
        _validate_profile_canary(receipt_file.parent, result, spec)
    except HarnessError as exc:
        failures.append(str(exc))

    try:
        model_receipt, _, model_file = _read_json_receipt(
            receipt_file.parent / "model-verification.json", "Mia model proof"
        )
        if model_file != receipt_file.parent / "model-verification.json":
            raise HarnessError("Mia model proof sibling differs")
        if (
            result.get("model_verification_sha256") != _qualification_sha256(model_receipt)
            or model_receipt.get("artifact_sha256") != spec.model_artifact_sha256()
            or model_receipt.get("full_sha256") is not True
            or model_receipt.get("safetensors_total_bytes") != spec.safetensors_total_bytes
            or model_receipt.get("verified_files") != spec.expected_model_files()
            or model_receipt.get("candidate") != qualification_plan["candidate"]
            or model_receipt.get("packed_ple") != qualification_plan["packed_ple"]
            or result.get("packed_ple") != qualification_plan["packed_ple"]
            or model_receipt.get("reduced_draft_vocab") != (
                {"path": str(spec.draft_vocab_path),
                 "bytes": spec.draft_vocab_bytes,
                 "sha256": spec.draft_vocab_sha256,
                 "id_count": spec.draft_vocab_id_count}
                if spec.draft_vocab_path is not None else None
            )
        ):
            raise HarnessError("Mia full model or packed PLE proof differs")
        if spec.draft_vocab_path is not None:
            vocab_raw, vocab_file = _read_regular_file(
                spec.draft_vocab_path, label="Mia reduced draft vocabulary",
                max_bytes=spec.draft_vocab_bytes,
            )
            if (vocab_file != spec.draft_vocab_path
                or len(vocab_raw) != spec.draft_vocab_bytes
                or hashlib.sha256(vocab_raw).hexdigest() != spec.draft_vocab_sha256):
                raise HarnessError("Mia reduced draft vocabulary bytes drifted")
        proofs = model_receipt.get("proof_receipts")
        expected_proofs = qualification_plan["proof_receipts"]
        if not isinstance(proofs, dict) or set(proofs) != set(expected_proofs):
            raise HarnessError("Mia source receipt set differs")
        for label, expected in expected_proofs.items():
            observed, raw_sha, proof_file = _read_json_receipt(
                expected["path"], f"Mia {label} source receipt"
            )
            if (
                proof_file != Path(expected["path"])
                or raw_sha != expected["sha256"]
                or proofs[label] != expected
            ):
                raise HarnessError(f"Mia {label} source receipt content differs")
            if label == "acquisition" and (
                observed.get("status") != "verified"
                or observed.get("model", {}).get("repo_id") != spec.repository
                or observed.get("model", {}).get("revision") != spec.revision
                or observed.get("model", {}).get("file_count") != len(spec.files)
            ):
                raise HarnessError("Mia acquisition source differs")
            if label == "image_build" and (
                observed.get("image_id") != spec.image_id
                or observed.get("image_architecture") != "arm64"
                or observed.get("recipe_commit") != spec.recipe_commit
                or observed.get("status") != "cpu_source_verified_unqualified"
            ):
                raise HarnessError("Mia image build source differs")
            if (label == "image_build" and spec.draft_vocab_path is not None
                and (observed.get("schema") != "mia-reduced-mtp3-overlay-build/v1"
                    or observed.get("parent_image_id")
                       != "sha256:da68dd27a8ef1dadd0f380178a51f0a0671dc4235933ea1ae89fdaf66295ec72"
                    or observed.get("base_mtp_sha256")
                       != "7735cee47d0d1e4776bebd30d907e4a62160409ce4ef2d65611559f8d58af431"
                    or observed.get("mtp_patch_sha256") != spec.reduced_mtp_patch_sha256
                    or observed.get("child_mtp_sha256") != spec.mtp_module_sha256
                    or observed.get("draft_vocab") != {
                        "path": str(spec.draft_vocab_path),
                        "bytes": spec.draft_vocab_bytes,
                        "sha256": spec.draft_vocab_sha256,
                        "id_count": spec.draft_vocab_id_count,
                    }
                    or observed.get("old_mia_c0_image_replaced") is not False
                    or observed.get("gpu_runtime_qualified") is not False)):
                raise HarnessError("reduced MTP3 child image/source receipt differs")
            if label == "ple_build" and (
                observed.get("status") != "verified"
                or observed.get("checkpoint_repo") != spec.repository
                or observed.get("checkpoint_revision") != spec.revision
                or observed.get("packed_size_bytes") != spec.packed_ple_bytes
                or observed.get("packed_sha256") != spec.packed_ple_sha256
            ):
                raise HarnessError("Mia packed PLE build source differs")
    except HarnessError as exc:
        failures.append(str(exc))

    summary = {
        "schema_version": "flash-next-qualification-validation/v3",
        "cohort": "flash", "variant_id": spec.spec_id,
        "profile": spec.profile,
        "mtp_speculative_tokens": spec.mtp_speculative_tokens,
        "max_model_len": spec.max_model_len,
        "kv_cache_memory_bytes": spec.kv_cache_memory_bytes,
        "run_id": result.get("run_id"), "status": result.get("status"),
        "admission_eligible": not failures, "admission_failures": failures,
        "qualification_receipt_sha256": receipt_sha256,
        "qualification_plan_sha256": result["plan_sha256"],
        "contract_sha256": contract_sha256,
        "contract_snapshot_sha256": contract_snapshot_sha256,
        "model_artifact_sha256": spec.model_artifact_sha256(),
        "runtime_sha256": _qualification_runtime_sha256(
            image_id=spec.image_id,
            command_sha256=qualification_plan["docker_create_argv_sha256"]),
        "served_model": spec.served_name,
        "endpoint_name": spec.endpoint_name,
        "min_mem_available_gib": minimum_observed,
        "probe_count": result.get("probe_count"),
        "restoration_status": restoration.get("status") if isinstance(restoration, dict) else None,
        "receipt_path": str(receipt_file), "qualification_plan_path": str(plan_file),
        "contract_snapshot_path": str(contract_file),
        "contract_raw_path": str(raw_file) if raw_file is not None else None,
    }
    if require_passed and failures:
        raise HarnessError("Mia qualification is not admissible: " + "; ".join(failures))
    return summary
