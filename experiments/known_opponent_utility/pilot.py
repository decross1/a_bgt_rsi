"""Registered utility-response pilot for the calibrated known-opponent game.

The registered local-model controller supplies a qualified endpoint and a live
safety callback. Importing this module does not call a model.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from fractions import Fraction
from pathlib import Path

import jsonschema

from bench.agentic_game_theory import calibration, optimal_control
from bench.flash_next_ab import transport

SCHEMA = "known-opponent-utility-response-pilot/v1"
RUN_SCHEMA = "known-opponent-utility-response-pilot-run/v1"
CAMPAIGN_ID = "v2-known-opponent-utility-20260915"
STUDY_ID = "known-opponent-utility-response-pilot-v1"
MIXES = ("retainers", "contributors", "grim")
OBJECTIVES = ("own_payoff", "joint_payoff")
SEATS = (0, 3)
HORIZON = 8
MAX_CALLS = 108
MAX_WINDOW_S = 900


class ProvenanceDrift(RuntimeError):
    """The live request differs from the frozen manifest or actual history."""


def _raw_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _source(path: Path) -> str:
    return _sha(path.read_bytes())


def _write_once(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _admission_source(root: Path, receipt: dict) -> Path:
    if receipt.get("schema_version") == "flash-next-qualification-validation/v3":
        return root / "bench/flash_next_ab/followon_qualification_admission.py"
    return root / "bench/flash_next_ab/harness.py"


def _admission_identity(receipt: dict, endpoint: transport.LocalEndpoint) -> None:
    receipt_sha = receipt.get("qualification_receipt_sha256") if isinstance(receipt, dict) else None
    if (not isinstance(receipt, dict)
            or receipt.get("admission_eligible") is not True
            or receipt.get("status") != "passed"
            or not isinstance(receipt_sha, str) or len(receipt_sha) != 64
            or any(c not in "0123456789abcdef" for c in receipt_sha)):
        raise ValueError("model requires a passed validated qualification receipt")
    if receipt.get("cohort") == "flash":
        if (receipt.get("endpoint_name") != endpoint.name
                or receipt.get("served_model") != endpoint.served_model
                or receipt.get("model_artifact_sha256") != endpoint.artifact_sha256):
            raise ValueError("validated Flash variant differs from pilot endpoint")
    elif receipt.get("cohort") == "resident":
        artifacts = receipt.get("artifact_sha256_by_endpoint")
        if (not isinstance(artifacts, dict)
                or artifacts.get(endpoint.name) != endpoint.artifact_sha256):
            raise ValueError("validated resident artifact differs from pilot endpoint")
    else:
        raise ValueError("unsupported pilot qualification cohort")


def _schedule() -> list[dict]:
    """A/B objective presentation and seat order are fixed before outcomes."""
    result = []
    for group_index, mix in enumerate(MIXES):
        for step in range(4):
            seat = SEATS[step % 2]
            objective = OBJECTIVES[(step % 2 + step // 2 + group_index) % 2]
            # Every seat in every mix receives both neutral labels and utilities.
            label = "A" if (group_index + step // 2) % 2 == 0 else "B"
            result.append({"ordinal": len(result), "id": f"{mix}-{objective}-seat{seat}",
                           "mix": mix, "objective": objective, "seat": seat,
                           "rule_label": label})
    if len({row["id"] for row in result}) != 12:
        raise AssertionError("counterbalance schedule does not cover the 12 cells")
    return result


def _comprehension_messages(seat: int) -> list[dict]:
    # Identical bytes across the two objective arms for the same focal seat.
    prompt = ("Arithmetic check before an eight-round game. Four seats are numbered "
              "0,1,2,3. Each seat has 5 units; a contributor gives all 5, a "
              "retainer keeps all 5. The sum contributed is doubled and divided "
              "equally among four seats. For prior actions [contribute, retain, "
              f"contribute, retain] and focal seat {seat}, give the focal material "
              "payoff and the sum of all four material payoffs. Answer exactly "
              "focal=<number>;sum=<number>. No explanation.")
    return [{"role": "user", "content": prompt}]


def _rule_formula(objective: str) -> str:
    if objective == "own_payoff":
        return "the material payoff of your focal seat"
    if objective == "joint_payoff":
        return "the sum of the four seats' material payoffs"
    raise ValueError("unknown utility")


def _action_messages(cell: dict, history: list[dict]) -> list[dict]:
    scripts = {
        "retainers": "All three bot seats retain every round.",
        "contributors": "All three bot seats contribute every round.",
        "grim": ("All three bot seats contribute initially. Starting in the next "
                 "round after any seat retained in an earlier round, they retain "
                 "forever. Bots inspect only earlier rounds, not this round's action."),
    }
    system = (
        "You control exactly one focal seat in a known-opponent, eight-round "
        "simultaneous-action public-goods game. Four seats are numbered 0,1,2,3. "
        f"Your focal seat is {cell['seat']}; the others are committed bots. "
        f"{scripts[cell['mix']]} Each round, choose 0 to retain all 5 units or "
        "1 to contribute all 5. Each seat's material payoff is 5 if it retains, "
        "0 if it contributes, plus (2 × 5 × number of contributors)/4. "
        f"Scoring Rule {cell['rule_label']} awards {_rule_formula(cell['objective'])} "
        "each round, summed across exactly eight rounds. The prior history below "
        "lists every earlier joint action, each seat's payoff, and contributors. "
        "No bot or focal action for the current round has yet occurred. "
        "Answer exactly 0 or 1; no explanation."
    )
    prior = [{"round": row["round"], "joint_actions": row["joint_actions"],
              "material_payoffs": row["material_payoffs"],
              "aggregate_contributors": row["aggregate_contributors"],
              "defection_seen_before_recorded_round": row["defection_seen_before_recorded_round"]}
             for row in history]
    current_grim_state = any(0 in row["joint_actions"] for row in history)
    user = (f"Round {len(history) + 1} of 8. Defection seen in earlier rounds: "
            f"{str(current_grim_state).lower()}. Prior history: {_raw_json(prior).decode()}. "
            "Choose 0 or 1.")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def freeze_manifest(*, source_root: Path, endpoint: transport.LocalEndpoint,
                    registered_admission: dict, policy: dict, seed: int, max_tokens: int = 64,
                    per_call_timeout_s: float = 30.0) -> dict:
    """Freeze the actual task/order/model/source tuple before any model calls."""
    endpoint.validate()
    _admission_identity(registered_admission, endpoint)
    transport.request_body(endpoint, _comprehension_messages(0), policy, max_tokens, seed)
    source_root = source_root.resolve(strict=True)
    exact = {
        "oracle": (source_root / "bench/agentic_game_theory/optimal_control.py",
                   Path(optimal_control.__file__).resolve()),
        "payoff": (source_root / "bench/agentic_game_theory/calibration.py",
                   Path(calibration.__file__).resolve()),
        "transport": (source_root / "bench/flash_next_ab/transport.py",
                      Path(transport.__file__).resolve()),
    }
    if any(expected.resolve(strict=True) != actual for expected, actual in exact.values()):
        raise ValueError("imported controls differ from the registered source root")
    if type(seed) is not int or not 1 <= seed <= 2_147_483_540:
        raise ValueError("bounded integer seed required")
    if isinstance(per_call_timeout_s, bool) or not 0 < per_call_timeout_s <= 60:
        raise ValueError("bounded per-call timeout required")
    schedule = _schedule()
    tasks = []
    for cell in schedule:
        item = {"cell": cell, "horizon": HORIZON,
                "opponent_scripts": list(optimal_control.MIXES[cell["mix"]]),
                "comprehension_messages": _comprehension_messages(cell["seat"]),
                "initial_action_messages": _action_messages(cell, []),
                "payoff_parameters": {"endowment": 5, "multiplier": "2", "players": 4}}
        tasks.append({**item, "task_sha256": _sha(_raw_json(item))})
    manifest = {
        "schema": SCHEMA, "campaign_id": CAMPAIGN_ID,
        "study_id": STUDY_ID,
        "claim_scope": "local_behavior_pilot_no_theory_novelty_equilibrium_or_trading_claim",
        "source_root": str(source_root),
        "source_sha256": {name: _source(paths[0]) for name, paths in exact.items()},
        "admission_validator_source_sha256": _source(_admission_source(source_root, registered_admission)),
        "runner_source_sha256": _source(Path(__file__)),
        "manifest_schema_source_sha256": _source(Path(__file__).with_name("manifest.schema.json")),
        "prereg_source_sha256": _source(source_root / "experiments/PREREG_known_opponent_utility_response_2026-09-15.md"),
        "endpoint": endpoint.__dict__, "policy": policy,
        "registered_admission": registered_admission,
        "registered_admission_sha256": _sha(_raw_json(registered_admission)),
        "policy_sha256": _sha(_raw_json(policy)),
        "seed_base": seed, "max_tokens": max_tokens,
        "per_call_timeout_s": per_call_timeout_s,
        "max_window_s": MAX_WINDOW_S, "max_calls": MAX_CALLS,
        "horizon": HORIZON, "schedule": schedule, "tasks": tasks,
        "comprehension_feedback": "none",
        "invalid_action_rule": "stop_episode_remaining_actions_unknown_full_horizon_regret_null",
        "current_or_future_bot_actions_in_prompt": False,
    }
    manifest["manifest_sha256"] = _sha(_raw_json(manifest))
    return manifest


def _check_manifest(value: dict) -> None:
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise ValueError("unregistered pilot manifest")
    copy = dict(value)
    digest = copy.pop("manifest_sha256", None)
    if digest != _sha(_raw_json(copy)) or value.get("schedule") != _schedule():
        raise ValueError("manifest/order raw SHA differs from frozen design")
    if value.get("max_window_s") != MAX_WINDOW_S or value.get("max_calls") != MAX_CALLS:
        raise ValueError("unbounded pilot")
    if value.get("runner_source_sha256") != _source(Path(__file__)):
        raise ValueError("runner source drift")
    if value.get("manifest_schema_source_sha256") != _source(Path(__file__).with_name("manifest.schema.json")):
        raise ValueError("manifest schema drift")
    schema = json.loads(Path(__file__).with_name("manifest.schema.json").read_bytes())
    jsonschema.Draft202012Validator(schema).validate(value)
    source_root = Path(value["source_root"])
    for name, relpath in {"oracle": "bench/agentic_game_theory/optimal_control.py",
                          "payoff": "bench/agentic_game_theory/calibration.py",
                          "transport": "bench/flash_next_ab/transport.py"}.items():
        if value["source_sha256"].get(name) != _source(source_root / relpath):
            raise ValueError("game/transport source drift")
    if value["prereg_source_sha256"] != _source(source_root / "experiments/PREREG_known_opponent_utility_response_2026-09-15.md"):
        raise ValueError("prereg source drift")
    expected = freeze_manifest(
        source_root=source_root,
        endpoint=transport.LocalEndpoint(**value["endpoint"]),
        registered_admission=value["registered_admission"],
        policy=value["policy"], seed=value["seed_base"],
        max_tokens=value["max_tokens"],
        per_call_timeout_s=value["per_call_timeout_s"],
    )
    if expected != value:
        raise ValueError("task, prompt, model or policy differs from frozen pilot")


def _parse_action(content: str) -> int | None:
    if not isinstance(content, str) or len(content) > 16:
        return None
    answer = content.strip()
    return int(answer) if answer in ("0", "1") else None


def _parse_comprehension(content: str, seat: int) -> bool | None:
    expected = Fraction(5 if seat == 0 else 10), Fraction(30)
    if not isinstance(content, str) or len(content) > 80:
        return None
    parts = content.strip().split(";")
    if len(parts) != 2 or not parts[0].startswith("focal=") or not parts[1].startswith("sum="):
        return None
    try:
        observed = Fraction(parts[0][6:]), Fraction(parts[1][4:])
    except (ValueError, ZeroDivisionError, OverflowError):
        return None
    return observed == expected


def _safe(safety_check, cancel_event) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError("pilot canceled")
    safety_check()  # Controller-owned live monitor check; no boolean approval surrogate.


def run_pilot(manifest: dict, *, output: Path, admission_gate, safety_check, cancel_event,
              invoke_fn=transport.complete, monotonic=time.monotonic) -> dict:
    """Run the frozen pilot under an already qualified controller window."""
    _check_manifest(manifest)
    observed_admission = admission_gate()  # External controller validator, not a boolean.
    if (not isinstance(observed_admission, dict)
            or observed_admission != manifest["registered_admission"]):
        raise ValueError("current model admission differs from frozen receipt")
    endpoint = transport.LocalEndpoint(**manifest["endpoint"])
    endpoint.validate()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    (output / "private").mkdir(mode=0o700)
    _write_once(output / "manifest.json", _raw_json(manifest) + b"\n")
    start, attempt, cells = monotonic(), 0, []
    deadline = start + MAX_WINDOW_S
    status = "complete"
    active = None

    def call(cell: dict, kind: str, round_number: int, messages: list[dict]) -> tuple[dict, str | None]:
        nonlocal attempt, active
        _safe(safety_check, cancel_event)
        if attempt >= MAX_CALLS or monotonic() >= deadline:
            raise TimeoutError("pilot window/call ceiling before next request")
        attempt += 1
        call_id = f"{cell['id']}-{kind}-{round_number}"
        seed = manifest["seed_base"] + attempt - 1
        timeout = min(manifest["per_call_timeout_s"], deadline - monotonic())
        body = transport.request_body(endpoint, messages, manifest["policy"],
                                      manifest["max_tokens"], seed)
        request_sha = _sha(transport.canonical(body))
        before = monotonic()
        response = None
        failure_detail = None
        provenance_drift = False
        try:
            response = invoke_fn(endpoint, messages, policy=manifest["policy"],
                                 max_tokens=manifest["max_tokens"], timeout_s=timeout,
                                 seed=seed, cancel_event=cancel_event)
            private = response["private_evidence"]
            if response["request_sha256"] != request_sha:
                provenance_drift = True
                failure_detail = "actual request differs from frozen game/history"
                completion = None
                result_status = "provenance_drift"
            else:
                completion = response["content"]
                result_status = "returned"
        except Exception as exc:  # noqa: BLE001 - retain transport failures in denominator
            failure_detail = f"{type(exc).__name__}: {exc}"
            private = getattr(exc, "private_evidence", None)
            completion = None
            result_status = "timeout" if isinstance(exc, TimeoutError) else "error"
        raw_sse = private.get("raw_response_stream", b"") if isinstance(private, dict) else b""
        if not isinstance(raw_sse, bytes):
            raise TypeError("private transport stream is not bytes")
        raw_private = dict(private or {})
        raw_private.pop("raw_response_stream", None)
        raw_private["resolved_request"] = body
        raw_private["call_id"] = call_id
        raw_private["failure_detail"] = failure_detail
        stream_path = output / "private" / f"{attempt:04d}.sse"
        metadata_path = output / "private" / f"{attempt:04d}.json"
        _write_once(stream_path, raw_sse)
        metadata_raw = _raw_json(raw_private) + b"\n"
        _write_once(metadata_path, metadata_raw)
        receipt = {"call_id": call_id, "attempt": attempt, "status": result_status,
                   "seed": seed, "messages_sha256": _sha(_raw_json(messages)),
                   "policy_sha256": manifest["policy_sha256"],
                   "endpoint": manifest["endpoint"]["name"],
                   "served_model": manifest["endpoint"]["served_model"],
                   "artifact_sha256": manifest["endpoint"]["artifact_sha256"],
                   "request_sha256": request_sha,
                   "response_stream_sha256": _sha(raw_sse),
                   "private_metadata_sha256": _sha(metadata_raw),
                   "private_stream_bytes": len(raw_sse),
                   "private_metadata_bytes": len(metadata_raw),
                   "wall_s": max(0.0, monotonic() - before),
                   "latency_s": response.get("latency_s") if response else None,
                   "ttft_s": response.get("ttft_s") if response else None,
                   "usage": response.get("usage") if response else None,
                   "failure_code": ("provenance_drift" if provenance_drift else
                                    "timeout" if result_status == "timeout" else
                                    "transport_or_runtime_error" if result_status == "error" else None)}
        if active is None:
            raise RuntimeError("attempt lacks an active scheduled cell")
        active["calls"].append(receipt)
        if provenance_drift:
            raise ProvenanceDrift("frozen request SHA differs")
        _safe(safety_check, cancel_event)
        return receipt, completion

    try:
        for item in manifest["tasks"]:
            cell = item["cell"]
            if monotonic() >= deadline:
                status = "incomplete_cutoff"
                break
            history, actions, receipts = [], [], []
            active = {"cell": cell, "task_sha256": item["task_sha256"],
                      "scheduled_actions": HORIZON, "valid_prefix_actions": 0,
                      "first_invalid_round": None, "comprehension": "unknown",
                      "full_episode": None, "calls": receipts}
            comp_messages = item["comprehension_messages"]
            _comp_receipt, comp_content = call(cell, "comprehension", 0, comp_messages)
            comprehension = _parse_comprehension(comp_content, cell["seat"])
            active["comprehension"] = ("passed" if comprehension is True else
                                       "failed" if comprehension is False else "unknown")
            invalid = None
            for round_number in range(1, HORIZON + 1):
                messages = _action_messages(cell, history)
                receipt, content = call(cell, "action", round_number, messages)
                action = _parse_action(content)
                receipt["action"] = action
                if action is None:
                    invalid = round_number
                    active["first_invalid_round"] = round_number
                    break
                joint = optimal_control.actions_for(tuple(optimal_control.MIXES[cell["mix"]]),
                                                    cell["seat"], action,
                                                    any(0 in row["joint_actions"] for row in history))
                material = [str(p) for p in calibration.payoffs(joint)]
                history.append({"round": round_number, "joint_actions": list(joint),
                                "material_payoffs": material,
                                "aggregate_contributors": sum(joint),
                                "defection_seen_before_recorded_round": any(
                                    0 in row["joint_actions"] for row in history)})
                actions.append(action)
                active["valid_prefix_actions"] = len(actions)
            _safe(safety_check, cancel_event)
            full = (optimal_control.evaluate_sequence(actions,
                     tuple(optimal_control.MIXES[cell["mix"]]), cell["objective"],
                     player=cell["seat"]) if len(actions) == HORIZON else None)
            active["first_invalid_round"] = invalid
            if full is not None:
                oracle_raw = _raw_json(full) + b"\n"
                _write_once(output / "private" / f"oracle-{cell['ordinal']:02d}.json",
                            oracle_raw)
                active["full_episode"] = {
                    "total_utility": full["total_utility"],
                    "episode_regret": full["episode_regret"],
                    "focal_cooperation_rate": full["focal_cooperation_rate"],
                    "group_cooperation_rate": full["group_cooperation_rate"],
                    "private_oracle_sha256": _sha(oracle_raw),
                }
            cells.append(active)
            active = None
            _write_once(output / f"cell-{cell['ordinal']:02d}.json",
                        _raw_json(cells[-1]) + b"\n")
        if len(cells) < 12 and status == "complete":
            status = "incomplete_cutoff"
        elif any(row["full_episode"] is None for row in cells):
            status = "completed_schedule_with_unknown_actions"
    except Exception as exc:  # noqa: BLE001 - journal safety/cutoff breaches
        status = ("ineligible_provenance_drift" if isinstance(exc, ProvenanceDrift)
                  else "incomplete_safety_or_cutoff")
        failure = ("provenance_drift" if isinstance(exc, ProvenanceDrift)
                   else "window_cutoff" if isinstance(exc, TimeoutError)
                   else "canceled_or_safety_breach" if isinstance(exc, RuntimeError)
                   else "other_runtime_failure")
        if active is not None:
            cells.append(active)  # Preserve attempted call receipts; full regret stays null.
    else:
        failure = None
    public = {"schema": RUN_SCHEMA, "manifest_sha256": manifest["manifest_sha256"],
              "status": status, "failure": failure,
              "scheduled_cells": 12, "completed_cell_records": len(cells),
              "scheduled_calls": MAX_CALLS, "attempted_calls": attempt,
              "elapsed_s": max(0.0, monotonic() - start), "cells": cells,
              "claim_scope": manifest["claim_scope"],
              "comparison_eligible": False, "promotion_authorized": False,
              "trading_claim_authorized": False}
    _write_once(output / "run.json", _raw_json(public) + b"\n")
    return public
