"""Prospective native-tool payoff arithmetic diagnostic for resident Gemma."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import time
from fractions import Fraction
from pathlib import Path
from typing import Any

from bench.agentic_game_theory.calibration import payoffs
from bench.flash_next_ab import harness, private_evidence, transport
from bench.flash_next_ab.adapters import CallSpec

ROOT = Path(__file__).resolve().parents[2]
PLAN_SCHEMA = "payoff-tool-study-plan/v1"
RUN_SCHEMA = "payoff-tool-study-run/v1"
POLICY = {"temperature": 0, "top_p": 1, "top_k": 64, "enable_thinking": False}
MAX_TOKENS = 256
CALL_TIMEOUT_S = 25.0
EVALUATOR_BUDGET_S = 600.0
SOURCE_PATHS = (
    "bench/payoff_tool_study/runner.py",
    "bench/agentic_game_theory/calibration.py",
    "bench/flash_next_ab/adapters.py",
    "bench/flash_next_ab/harness.py",
    "bench/flash_next_ab/transport.py",
    "bench/flash_next_ab/private_evidence.py",
    "bench/flash_next_ab/manifest.py",
    "bench/flash_next_ab/qualification.py",
    "experiments/payoff_tool_arithmetic/PREREGISTRATION.md",
)
GAMES = (
    ("G1", 3, 3, 2, (0, 1, 0, 0)),
    ("G2", 7, 5, 2, (1, 0, 0, 1)),
    ("G3", 11, 7, 3, (1, 0, 1, 1)),
)
TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "shared_return",
        "description": "Compute only the shared public-goods return for four actions.",
        "parameters": {
            "type": "object",
            "properties": {
                "actions": {"type": "array", "items": {"type": "integer", "enum": [0, 1]}, "minItems": 4, "maxItems": 4},
                "E": {"type": "integer"},
                "m_num": {"type": "integer"},
                "m_den": {"type": "integer", "minimum": 1},
            },
            "required": ["actions", "E", "m_num", "m_den"],
            "additionalProperties": False,
        },
    },
}


class ToolStudyError(ValueError):
    pass


def _require(ok: bool, reason: str) -> None:
    if not ok:
        raise ToolStudyError(reason)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sources() -> dict[str, str]:
    return {rel: _sha((ROOT / rel).read_bytes()) for rel in SOURCE_PATHS}


def _rational(value: Fraction) -> str:
    return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"


def _parse_rational(value: Any) -> Fraction | None:
    if not isinstance(value, str) or not re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*)?", value):
        return None
    try:
        parsed = Fraction(value)
    except (ValueError, ZeroDivisionError):
        return None
    return parsed if _rational(parsed) == value else None


def _fixtures() -> list[dict[str, Any]]:
    rows = []
    for game_id, E, m_num, m_den, actions in GAMES:
        for seat in (0, 1):
            values = payoffs(tuple(actions), endowment=E, multiplier=Fraction(m_num, m_den))
            shared = values[0] - Fraction(E * (1 - actions[0]))
            focal = values[seat]
            total = sum(values, Fraction())
            rows.append({
                "pair_id": f"{game_id}-seat{seat}", "game_id": game_id,
                "seat": seat, "E": E, "m_num": m_num, "m_den": m_den,
                "actions": list(actions), "shared_return": _rational(shared),
                "focal": _rational(focal), "total": _rational(total),
                "seed": 701 + len(rows) * 17,
                "arm_order": ["direct", "tool"] if len(rows) % 2 == 0 else ["tool", "direct"],
            })
    return rows


def _slots(fixtures: list[dict[str, Any]]) -> list[str]:
    return [f"{f['pair_id']}/{kind}" for f in fixtures for kind in ("direct", "tool_first", "tool_final")]


def make_plan(runtime_certificate: dict[str, Any], plan_path: str | Path) -> dict[str, Any]:
    path = Path(plan_path)
    _require(isinstance(runtime_certificate, dict), "runtime certificate missing")
    _require(runtime_certificate.get("endpoint_name") == "resident_gemma", "only registered Gemma endpoint allowed")
    _require(runtime_certificate.get("served_model") == "gemma-4-26b-a4b", "Gemma served model mismatch")
    for key in ("artifact_sha256", "runtime_sha256"):
        value = runtime_certificate.get(key)
        _require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None, f"{key} missing")
    fixtures = _fixtures()
    plan = {
        "schema_version": PLAN_SCHEMA, "code_root": str(ROOT),
        "runtime_certificate": copy.deepcopy(runtime_certificate),
        "source_sha256": _sources(), "fixtures": fixtures,
        "declared_pairs": [f["pair_id"] for f in fixtures],
        "declared_slots": _slots(fixtures), "policy": POLICY,
        "tool_spec": TOOL_SPEC, "call_timeout_s": CALL_TIMEOUT_S,
        "max_tokens": MAX_TOKENS, "evaluator_budget_s": EVALUATOR_BUDGET_S,
        "claim_limit": "native calculator invocation and arithmetic only; no strategy, theory promotion, or model promotion",
    }
    raw = json.dumps(plan, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as f:
        f.write(raw)
    return plan


def load_plan(plan_path: str | Path) -> tuple[dict[str, Any], str]:
    raw, _ = harness._read_regular_file(Path(plan_path), label="payoff tool plan", max_bytes=1_000_000)
    plan = harness._strict_object(raw, "payoff tool plan")
    _require(plan.get("schema_version") == PLAN_SCHEMA and plan.get("code_root") == str(ROOT), "plan identity mismatch")
    _require(plan.get("fixtures") == _fixtures() and plan.get("declared_pairs") == [f["pair_id"] for f in _fixtures()], "fixture drift")
    _require(plan.get("declared_slots") == _slots(_fixtures()), "declared slot drift")
    _require(plan.get("policy") == POLICY and plan.get("tool_spec") == TOOL_SPEC, "policy or tool drift")
    _require(plan.get("call_timeout_s") == CALL_TIMEOUT_S and plan.get("max_tokens") == MAX_TOKENS
             and plan.get("evaluator_budget_s") == EVALUATOR_BUDGET_S, "budget drift")
    _require(plan.get("source_sha256") == _sources(), "evaluator source drift")
    cert = plan.get("runtime_certificate")
    _require(isinstance(cert, dict) and cert.get("endpoint_name") == "resident_gemma"
             and cert.get("served_model") == "gemma-4-26b-a4b", "resident certificate drift")
    for key in ("artifact_sha256", "runtime_sha256"):
        _require(isinstance(cert.get(key), str) and re.fullmatch(r"[0-9a-f]{64}", cert[key]) is not None,
                 f"resident {key} malformed")
    return plan, _sha(raw)


def _messages(f: dict[str, Any], *, tool_first: bool) -> list[dict[str, Any]]:
    system = (
        "Compute the focal seat payoff and total payoff for a four-player public-goods round. "
        "Each player keeps E if action is 0 and contributes E if action is 1. "
        "The group shared return is m*E*k/4 and each player receives the same shared return. "
        "Final answer must be bare JSON exactly with string keys focal and total and canonical reduced rational string values."
    )
    user = (
        f"E={f['E']}; m={f['m_num']}/{f['m_den']}; actions in seat order 0..3={f['actions']}; "
        f"focal seat={f['seat']}. Calculate the focal payoff and total payoff."
    )
    if tool_first:
        user += " First call the provided shared_return function exactly once with actions, E, m_num, m_den. Do not answer before its tool result."
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _execute_tool(call: dict[str, Any]) -> str:
    args = transport._strict_json(call["function"]["arguments"])
    values = payoffs(tuple(args["actions"]), endowment=args["E"],
                     multiplier=Fraction(args["m_num"], args["m_den"]))
    return _rational(values[0] - Fraction(args["E"] * (1 - args["actions"][0])))


def _tool_result_message(call: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": "tool", "tool_call_id": call["id"], "name": "shared_return",
        "content": json.dumps({"shared_return": _execute_tool(call)}, sort_keys=True, separators=(",", ":")),
    }


def _final_messages(f: dict[str, Any], call: dict[str, Any], first_content: str) -> list[dict[str, Any]]:
    return [
        *_messages(f, tool_first=True),
        {"role": "assistant", "content": first_content, "tool_calls": [copy.deepcopy(call)]},
        _tool_result_message(call),
        {"role": "user", "content": "Using only the shared_return tool value and the disclosed actions, derive focal and total. Return the required bare JSON."},
    ]


def _grade_tool(status: str, receipt: dict[str, Any] | None, tool_calls: Any, content: str | None, f: dict[str, Any]) -> dict[str, Any]:
    grade = {"parsed_tool_call": False, "args_shape_valid": False, "args_correct": False, "tool_executed": False, "failure_code": None}
    if status != "returned":
        grade["failure_code"] = status
        return grade
    if not isinstance(tool_calls, (tuple, list)) or len(tool_calls) != 1:
        grade["failure_code"] = (
            "parser_miss" if isinstance(content, str) and "<|tool_call" in content
            else "bypass_no_tool" if _grade_final(content, "returned", f)["strict_shape"]
            else "no_tool"
        )
        return grade
    call = tool_calls[0]
    if not isinstance(call, dict) or set(call) != {"id", "type", "function"} or call.get("type") != "function" or not isinstance(call.get("id"), str) or not call["id"]:
        grade["failure_code"] = "tool_shape"
        return grade
    fun = call.get("function")
    if not isinstance(fun, dict) or set(fun) != {"name", "arguments"} or fun.get("name") != "shared_return" or not isinstance(fun.get("arguments"), str):
        grade["failure_code"] = "tool_name_or_shape"
        return grade
    grade["parsed_tool_call"] = True
    if receipt is None or receipt.get("finish_reason") != "tool_calls":
        grade["failure_code"] = "tool_incomplete"
        return grade
    if _grade_final(content, "returned", f)["strict_shape"]:
        grade["failure_code"] = "bypass_with_tool"
        return grade
    try:
        args = transport._strict_json(fun["arguments"])
    except (ValueError, TypeError):
        grade["failure_code"] = "args_json"
        return grade
    if (not isinstance(args, dict) or set(args) != {"actions", "E", "m_num", "m_den"}
            or type(args["actions"]) is not list or len(args["actions"]) != 4
            or any(type(x) is not int or x not in (0, 1) for x in args["actions"])
            or any(type(args[k]) is not int for k in ("E", "m_num", "m_den"))
            or args["m_den"] <= 0):
        grade["failure_code"] = "args_shape"
        return grade
    grade["args_shape_valid"] = True
    expected = {k: f[k] for k in ("actions", "E", "m_num", "m_den")}
    if args != expected:
        grade["failure_code"] = "wrong_args"
        return grade
    grade["args_correct"] = True
    grade["tool_executed"] = True
    return grade


def _grade_final(content: str | None, status: str, f: dict[str, Any], *,
                 finish_reason: str | None = None, tool_calls: Any = ()) -> dict[str, Any]:
    grade = {"strict_shape": False, "focal_correct": False, "total_correct": False, "both_correct": False, "failure_code": None}
    if status != "returned" or not isinstance(content, str):
        grade["failure_code"] = status
        return grade
    if finish_reason is not None and finish_reason != "stop":
        grade["failure_code"] = "final_incomplete_or_tool"
        return grade
    if tool_calls:
        grade["failure_code"] = "unexpected_final_tool"
        return grade
    try:
        obj = transport._strict_json(content)
    except (TypeError, ValueError):
        grade["failure_code"] = "final_json"
        return grade
    if not isinstance(obj, dict) or set(obj) != {"focal", "total"}:
        grade["failure_code"] = "final_shape"
        return grade
    focal, total = _parse_rational(obj["focal"]), _parse_rational(obj["total"])
    if focal is None or total is None:
        grade["failure_code"] = "final_rational_shape"
        return grade
    grade["strict_shape"] = True
    grade["focal_correct"] = focal == Fraction(f["focal"])
    grade["total_correct"] = total == Fraction(f["total"])
    grade["both_correct"] = grade["focal_correct"] and grade["total_correct"]
    grade["failure_code"] = None if grade["both_correct"] else "arithmetic_wrong"
    return grade


def _gate(plan: dict[str, Any], gate: dict[str, Any]) -> None:
    _require(isinstance(gate, dict) and gate.get("admitted") is True, "controller admission missing")
    _require(gate.get("runtime_certificate") == plan["runtime_certificate"], "runtime certificate admission mismatch")
    for key in ("window_id", "window_sha256", "ready_proof_sha256", "monitor_arm_sha256"):
        value = gate.get(key)
        _require(isinstance(value, str) and bool(value), f"{key} admission missing")
    for key in ("window_sha256", "ready_proof_sha256", "monitor_arm_sha256"):
        _require(re.fullmatch(r"[0-9a-f]{64}", gate[key]) is not None, f"{key} admission digest invalid")


def run(
    *, plan_path: str | Path, output_dir: str | Path, admission_gate: dict[str, Any],
    cancel_event: Any, absolute_cutoff_monotonic: float,
    invoke_fn=transport.complete, monotonic=time.monotonic,
) -> dict[str, Any]:
    plan, plan_raw_sha = load_plan(plan_path)
    _gate(plan, admission_gate)
    _require(callable(getattr(cancel_event, "is_set", None)), "cancel event missing")
    _require(isinstance(absolute_cutoff_monotonic, (int, float)), "absolute cutoff missing")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    _require(not (output / "run.json").exists() and not (output / "private").exists(), "run output already exists")
    arm = {"routes": [{
        "role": "arithmetic", "endpoint_name": "resident_gemma",
        "served_model": plan["runtime_certificate"]["served_model"],
        "artifact_sha256": plan["runtime_certificate"]["artifact_sha256"],
        "policies": {"payoff_off": copy.deepcopy(POLICY)},
    }]}
    start = monotonic()
    deadline = min(float(absolute_cutoff_monotonic), start + EVALUATOR_BUDGET_S)
    outcomes: list[dict[str, Any]] = []
    slots: dict[str, dict[str, Any]] = {}
    ordinal = 0
    aborted = False

    def invoke(slot_id: str, messages: list[dict[str, Any]], f: dict[str, Any], with_tool: bool) -> tuple[Any, dict[str, Any]]:
        nonlocal ordinal, aborted
        if cancel_event.is_set() or deadline - monotonic() < CALL_TIMEOUT_S + 0.05:
            aborted = True
            return None, {"slot_id": slot_id, "status": "not_run", "failure_code": "cutoff_or_cancel"}
        private: list[dict[str, Any]] = []
        spec = CallSpec(
            call_index=ordinal, call_id=f"{admission_gate['window_id']}/{slot_id}",
            role="arithmetic", policy_id="payoff_off", seed=f["seed"],
            max_tokens=MAX_TOKENS, timeout_s=CALL_TIMEOUT_S, required=True,
            messages=tuple(messages), tools=(copy.deepcopy(TOOL_SPEC),) if with_tool else (),
        )
        call = harness._invoke_call(spec, arm=arm, deadline=deadline, invoke_fn=invoke_fn,
                                    cancel_event=cancel_event, monotonic=monotonic, evidence_sink=private.append)
        _require(len(private) == 1, "private call missing")
        descriptor = harness._persist_private_call(output, ordinal=ordinal, evidence=private[0])
        ordinal += 1
        slot = {"slot_id": slot_id, "status": call.status, "failure_code": call.receipt.get("failure_code"),
                "call": call.receipt, "private_descriptor": descriptor}
        if call.receipt["timeout_s"] != CALL_TIMEOUT_S:
            aborted = True
            slot["failure_code"] = "shortened_timeout"
        return call, slot

    for f in plan["fixtures"]:
        for arm_name in f["arm_order"]:
            if aborted:
                break
            pair_id = f["pair_id"]
            calls, descriptors = [], []
            if arm_name == "direct":
                sid = f"{pair_id}/direct"
                call, slot = invoke(sid, _messages(f, tool_first=False), f, False)
                slots[sid] = slot
                if call is None:
                    grade = _grade_final(None, "not_run", f)
                else:
                    calls.append(call.receipt); descriptors.append(slot["private_descriptor"])
                    meta_content = call.content
                    grade = _grade_final(meta_content, call.status, f,
                                         finish_reason=call.receipt.get("finish_reason"), tool_calls=call.tool_calls)
                outcomes.append({"pair_id": pair_id, "arm": "direct", "calls": calls,
                                 "grade": {"details": {**grade, "_private_call_evidence": {
                                     "schema_version": harness.PRIVATE_INDEX_SCHEMA, "artifacts": descriptors}}}})
            else:
                first_id, final_id = f"{pair_id}/tool_first", f"{pair_id}/tool_final"
                first, first_slot = invoke(first_id, _messages(f, tool_first=True), f, True)
                slots[first_id] = first_slot
                if first is None:
                    tool_grade = _grade_tool("not_run", None, (), None, f)
                else:
                    calls.append(first.receipt); descriptors.append(first_slot["private_descriptor"])
                    tool_grade = _grade_tool(first.status, first.receipt, first.tool_calls, first.content, f)
                final_grade = _grade_final(None, "skipped", f)
                if first is not None and tool_grade["tool_executed"] and not aborted:
                    final, final_slot = invoke(final_id, _final_messages(f, first.tool_calls[0], first.content or ""), f, False)
                    slots[final_id] = final_slot
                    if final is not None:
                        calls.append(final.receipt); descriptors.append(final_slot["private_descriptor"])
                        final_grade = _grade_final(final.content, final.status, f,
                                                   finish_reason=final.receipt.get("finish_reason"), tool_calls=final.tool_calls)
                    else:
                        final_grade = _grade_final(None, "not_run", f)
                else:
                    slots[final_id] = {"slot_id": final_id, "status": "skipped" if not aborted else "not_run",
                                       "failure_code": tool_grade["failure_code"] if not aborted else "cutoff_or_cancel"}
                outcomes.append({"pair_id": pair_id, "arm": "tool", "calls": calls,
                                 "grade": {"details": {**final_grade, "tool": tool_grade,
                                     "_private_call_evidence": {
                                         "schema_version": harness.PRIVATE_INDEX_SCHEMA, "artifacts": descriptors}}}})
        if aborted:
            break
    for sid in plan["declared_slots"]:
        slots.setdefault(sid, {"slot_id": sid, "status": "not_run", "failure_code": "unissued_after_abort"})
    ordered_slots = [slots[sid] for sid in plan["declared_slots"]]
    status = "aborted" if aborted or cancel_event.is_set() or any(s["status"] == "not_run" for s in ordered_slots) else "complete"
    result = {
        "schema_version": RUN_SCHEMA, "status": status, "window_id": admission_gate["window_id"],
        "plan_raw_sha256": plan_raw_sha, "runtime_certificate": plan["runtime_certificate"],
        "controller_admission": copy.deepcopy(admission_gate), "declared_pairs": plan["declared_pairs"],
        "declared_slots": plan["declared_slots"], "slots": ordered_slots, "outcomes": outcomes,
        "issued_calls": ordinal, "elapsed_s": max(0.0, monotonic() - start),
        "promotion_authorized": False, "claim_limit": plan["claim_limit"],
    }
    with (output / "run.json").open("xb") as fh:
        fh.write(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n")
    return result


def replay_run(plan_path: str | Path, output_dir: str | Path) -> dict[str, Any]:
    plan, plan_raw_sha = load_plan(plan_path)
    output = Path(output_dir)
    raw, _ = harness._read_regular_file(output / "run.json", label="tool study run", max_bytes=3_000_000)
    run_record = harness._strict_object(raw, "tool study run")
    _require(run_record.get("schema_version") == RUN_SCHEMA and run_record.get("status") == "complete", "tool run not complete")
    _require(run_record.get("plan_raw_sha256") == plan_raw_sha, "tool plan hash mismatch")
    _require(run_record.get("runtime_certificate") == plan["runtime_certificate"], "tool runtime mismatch")
    _gate(plan, run_record.get("controller_admission"))
    _require(run_record.get("window_id") == run_record["controller_admission"]["window_id"]
             and run_record.get("promotion_authorized") is False
             and run_record.get("claim_limit") == plan["claim_limit"],
             "window or claim authority drift")
    _require(run_record.get("declared_pairs") == plan["declared_pairs"]
             and run_record.get("declared_slots") == plan["declared_slots"], "declared denominator mismatch")
    slots = run_record.get("slots")
    _require(isinstance(slots, list) and [s.get("slot_id") for s in slots if isinstance(s, dict)] == plan["declared_slots"], "slot accounting mismatch")
    _require(all(s.get("status") not in (None, "not_run") for s in slots), "unissued slot in complete run")
    outcomes = run_record.get("outcomes")
    _require(isinstance(outcomes, list) and len(outcomes) == 12, "condition denominator mismatch")
    expected_order = [(f["pair_id"], arm) for f in plan["fixtures"] for arm in f["arm_order"]]
    _require([(o.get("pair_id"), o.get("arm")) for o in outcomes if isinstance(o, dict)] == expected_order,
             "preregistered pair/arm order drift")
    verified = private_evidence.validate_private_evidence(run_record, output)
    issued = sum(len(o["calls"]) for o in outcomes)
    _require(run_record.get("issued_calls") == issued and issued <= 18, "issued call denominator mismatch")
    _require([c.get("call_index") for o in outcomes for c in o["calls"]] == list(range(issued)),
             "issued call chronology drift")
    by_slot = {s["slot_id"]: s for s in slots}
    by_outcome = {(o["pair_id"], o["arm"]): o for o in outcomes}
    _require(len(by_outcome) == 12, "duplicate condition")
    for f in plan["fixtures"]:
        for arm_name in ("direct", "tool"):
            o = by_outcome.get((f["pair_id"], arm_name))
            _require(isinstance(o, dict) and isinstance(o.get("grade"), dict), "condition missing")
            calls = o["calls"]
            descriptors = o["grade"]["details"]["_private_call_evidence"]["artifacts"]
            metadata = []
            for call, desc in zip(calls, descriptors, strict=True):
                path = output / desc["metadata_path"]
                meta_raw, _ = harness._read_regular_file(path, label="private tool call", max_bytes=200_000)
                _require(_sha(meta_raw) == desc["metadata_sha256"], "private metadata digest mismatch")
                metadata.append(harness._strict_object(meta_raw, "private tool call"))
                _require(metadata[-1]["call_id"] == call["call_id"], "private call id mismatch")
                request = metadata[-1]["request"]
                _require(request.get("endpoint_name") == "resident_gemma"
                         and request.get("served_model") == plan["runtime_certificate"]["served_model"]
                         and request.get("artifact_sha256") == plan["runtime_certificate"]["artifact_sha256"]
                         and request.get("resolved_policy") == POLICY
                         and request.get("seed") == f["seed"]
                         and request.get("max_tokens") == MAX_TOKENS
                         and request.get("timeout_s") == CALL_TIMEOUT_S,
                         "fixture route, policy, seed, output or timeout drift")
                slot_id = call["call_id"].split("/", 1)[-1]
                slot = by_slot.get(slot_id)
                _require(isinstance(slot, dict) and slot.get("call") == call
                         and call.get("call_id") == f"{run_record['window_id']}/{slot_id}"
                         and call.get("role") == "arithmetic"
                         and slot.get("private_descriptor") == desc
                         and slot.get("status") == call.get("status")
                         and slot.get("failure_code") == call.get("failure_code"),
                         "issued slot/receipt binding drift")
            if arm_name == "direct":
                _require(len(calls) == 1 and len(metadata) == 1, "direct call count mismatch")
                _require(metadata[0]["request"]["messages"] == _messages(f, tool_first=False)
                         and metadata[0]["request"]["tools"] == [], "direct request drift")
                grade = _grade_final(metadata[0]["response"]["content"], calls[0]["status"], f,
                                     finish_reason=calls[0].get("finish_reason"),
                                     tool_calls=metadata[0]["response"]["tool_calls"])
                stored = {k: v for k, v in o["grade"]["details"].items() if k != "_private_call_evidence"}
                _require(grade == stored, "direct grade replay mismatch")
                _require(by_slot[f"{f['pair_id']}/direct"]["status"] == calls[0]["status"], "direct slot status mismatch")
            else:
                _require(len(calls) in (1, 2) and metadata[0]["request"]["messages"] == _messages(f, tool_first=True)
                         and metadata[0]["request"]["tools"] == [TOOL_SPEC], "tool-first request drift")
                tool_grade = _grade_tool(calls[0]["status"], calls[0], metadata[0]["response"]["tool_calls"],
                                         metadata[0]["response"]["content"], f)
                _require(tool_grade == o["grade"]["details"]["tool"], "tool args grade replay mismatch")
                _require(by_slot[f"{f['pair_id']}/tool_first"]["status"] == calls[0]["status"], "tool-first slot mismatch")
                final_slot = by_slot[f"{f['pair_id']}/tool_final"]
                if tool_grade["tool_executed"]:
                    _require(len(calls) == 2 and final_slot["status"] == calls[1]["status"], "executed tool missing final call")
                    _require(metadata[1]["request"]["messages"] == _final_messages(
                                 f, metadata[0]["response"]["tool_calls"][0], metadata[0]["response"]["content"])
                             and metadata[1]["request"]["tools"] == [], "tool result/final request drift")
                    grade = _grade_final(metadata[1]["response"]["content"], calls[1]["status"], f,
                                         finish_reason=calls[1].get("finish_reason"),
                                         tool_calls=metadata[1]["response"]["tool_calls"])
                else:
                    _require(len(calls) == 1 and final_slot["status"] == "skipped"
                             and final_slot["failure_code"] == tool_grade["failure_code"], "invalid tool final not causally skipped")
                    grade = _grade_final(None, "skipped", f)
                stored = {k: v for k, v in o["grade"]["details"].items() if k not in ("tool", "_private_call_evidence")}
                _require(grade == stored, "tool final grade replay mismatch")
    return {
        "admitted": True, "status": "passed", "run_raw_sha256": _sha(raw),
        "plan_raw_sha256": plan_raw_sha, "raw_sse_replay_passed": True,
        "grade_replay_passed": True, "declared_pairs": 6,
        "declared_conditions": 12, "declared_slots": 18,
        "issued_calls": issued, "private_calls_verified": verified,
        "promotion_authorized": False,
    }
