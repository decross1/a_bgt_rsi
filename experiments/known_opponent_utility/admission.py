"""Read-only replay of the known-opponent pilot's private call/DP evidence.

Only a completed twelve-cell schedule becomes an admitted empirical pilot.
Partial schedules remain observed but ineligible for a full-horizon claim.
This validator never calls a model or rewrites producer files.
"""

from __future__ import annotations

import json
import math
import os
import stat
from pathlib import Path

from bench.agentic_game_theory import calibration, optimal_control
from bench.flash_next_ab import transport
from experiments.known_opponent_utility import pilot

SCHEMA = "known-opponent-utility-response-validation/v1"
MAX_MANIFEST_BYTES = 1_000_000
MAX_RUN_BYTES = 1_000_000
MAX_METADATA_BYTES = 128_000
MAX_STREAM_BYTES = 2_000_000
MAX_ORACLE_BYTES = 128_000


class PilotAdmissionError(ValueError):
    pass


def _must(ok: bool, reason: str) -> None:
    if not ok:
        raise PilotAdmissionError(reason)


def _read(root: Path, relative: str, limit: int) -> bytes:
    parts = Path(relative).parts
    _must(bool(parts) and not Path(relative).is_absolute()
          and all(part not in {"", ".", ".."} for part in parts),
          "pilot evidence path is outside its output root")
    opened: list[int] = []
    try:
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        opened.append(directory)
        for part in parts[:-1]:
            directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=directory)
            opened.append(directory)
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        opened.append(fd)
        info = os.fstat(fd)
        _must(stat.S_ISREG(info.st_mode) and info.st_size <= limit,
              "pilot evidence is nonregular or oversized")
        chunks: list[bytes] = []
        remaining = limit + 1
        while remaining:
            chunk = os.read(fd, min(remaining, 1_048_576))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(fd)
        _must(len(raw) == info.st_size and len(raw) <= limit and
              (info.st_ino, info.st_size, info.st_mtime_ns)
              == (after.st_ino, after.st_size, after.st_mtime_ns),
              "pilot evidence changed during read")
        return raw
    except OSError as exc:
        raise PilotAdmissionError("pilot evidence is unavailable or redirected") from exc
    finally:
        for fd in reversed(opened):
            os.close(fd)


def _object(raw: bytes) -> dict:
    def unique(pairs):
        out = {}
        for key, value in pairs:
            _must(key not in out, "pilot evidence has duplicate JSON fields")
            out[key] = value
        return out

    try:
        value = json.loads(raw, object_pairs_hook=unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite")))
    except (ValueError, UnicodeError) as exc:
        raise PilotAdmissionError("pilot evidence is not strict JSON") from exc
    _must(isinstance(value, dict), "pilot evidence is not an object")
    return value


def _returned_sse(raw: bytes, model: str) -> dict:
    try:
        stream = transport.StreamAccumulator(model)
        for line in raw.splitlines():
            if stream.done and line.strip(b"\r"):
                raise transport.TransportError("bytes after terminal SSE marker")
            payload = transport._sse_data(line.rstrip(b"\r"))
            if payload is not None:
                stream.accept(payload)
        return stream.result()
    except (TypeError, ValueError, transport.TransportError) as exc:
        raise PilotAdmissionError("returned private SSE is malformed") from exc


def _number(value: object, maximum: float) -> bool:
    return (not isinstance(value, bool) and isinstance(value, int | float)
            and math.isfinite(value) and 0 <= value <= maximum)


def validate_pilot(output: Path) -> dict:
    """Replay raw manifest/run/calls, observed game history, and private DP."""
    manifest_raw = _read(output, "manifest.json", MAX_MANIFEST_BYTES)
    manifest = _object(manifest_raw)
    _must(manifest_raw == pilot._raw_json(manifest) + b"\n",
          "pilot manifest raw bytes are not the producer's frozen form")
    pilot._check_manifest(manifest)
    run_raw = _read(output, "run.json", MAX_RUN_BYTES)
    run = _object(run_raw)
    _must(run_raw == pilot._raw_json(run) + b"\n",
          "pilot run raw bytes are not the producer's form")
    _must(run.get("schema") == pilot.RUN_SCHEMA
          and run.get("manifest_sha256") == manifest["manifest_sha256"]
          and run.get("claim_scope") == manifest["claim_scope"]
          and run.get("comparison_eligible") is False
          and run.get("promotion_authorized") is False
          and run.get("trading_claim_authorized") is False
          and run.get("scheduled_cells") == 12
          and run.get("scheduled_calls") == pilot.MAX_CALLS
          and isinstance(run.get("cells"), list)
          and run.get("completed_cell_records") == len(run["cells"])
          and len(run["cells"]) <= 12
          and type(run.get("attempted_calls")) is int
          and 0 <= run["attempted_calls"] <= pilot.MAX_CALLS
          and _number(run.get("elapsed_s"), pilot.MAX_WINDOW_S + 60),
          "pilot public run identity/caps drifted")
    endpoint = transport.LocalEndpoint(**manifest["endpoint"])
    endpoint.validate()
    attempts = 0
    verified_streams = 0
    complete_episodes = 0
    valid_actions = 0
    comprehension_passed = 0
    zero_regret = 0
    for ordinal, row in enumerate(run["cells"]):
        task = manifest["tasks"][ordinal]
        cell = task["cell"]
        _must(isinstance(row, dict) and row.get("cell") == cell
              and row.get("task_sha256") == task["task_sha256"]
              and row.get("scheduled_actions") == pilot.HORIZON
              and isinstance(row.get("calls"), list)
              and 1 <= len(row["calls"]) <= 9,
              "pilot cell/order/task differs from frozen schedule")
        history: list[dict] = []
        actions: list[int] = []
        comp_status = "unknown"
        invalid_round = None
        for index, receipt in enumerate(row["calls"]):
            _must(isinstance(receipt, dict), "pilot call receipt is not an object")
            attempts += 1
            kind = "comprehension" if index == 0 else "action"
            round_number = 0 if index == 0 else index
            call_id = f"{cell['id']}-{kind}-{round_number}"
            seed = manifest["seed_base"] + attempts - 1
            messages = (task["comprehension_messages"] if index == 0
                        else pilot._action_messages(cell, history))
            body = transport.request_body(endpoint, messages, manifest["policy"],
                                          manifest["max_tokens"], seed)
            expected_request = pilot._sha(transport.canonical(body))
            _must(receipt.get("call_id") == call_id
                  and receipt.get("attempt") == attempts
                  and receipt.get("seed") == seed
                  and receipt.get("endpoint") == endpoint.name
                  and receipt.get("served_model") == endpoint.served_model
                  and receipt.get("artifact_sha256") == endpoint.artifact_sha256
                  and receipt.get("policy_sha256") == manifest["policy_sha256"]
                  and receipt.get("messages_sha256") == pilot._sha(pilot._raw_json(messages))
                  and receipt.get("request_sha256") == expected_request
                  and receipt.get("status") in {"returned", "timeout", "error", "provenance_drift"}
                  and _number(receipt.get("wall_s"), manifest["per_call_timeout_s"] + 10),
                  "pilot call request/identity differs from actual history")
            stream = _read(output, f"private/{attempts:04d}.sse", MAX_STREAM_BYTES)
            metadata_raw = _read(output, f"private/{attempts:04d}.json", MAX_METADATA_BYTES)
            metadata = _object(metadata_raw)
            _must(receipt.get("response_stream_sha256") == pilot._sha(stream)
                  and receipt.get("private_metadata_sha256") == pilot._sha(metadata_raw)
                  and receipt.get("private_stream_bytes") == len(stream)
                  and receipt.get("private_metadata_bytes") == len(metadata_raw)
                  and metadata.get("call_id") == call_id
                  and metadata.get("resolved_request") == body
                  and metadata.get("response_stream_sha256", pilot._sha(stream)) == pilot._sha(stream),
                  "pilot private call hashes or rendered request drifted")
            if receipt["status"] == "returned":
                replay = _returned_sse(stream, endpoint.served_model)
                for key in ("content", "reasoning_content", "tool_calls", "response_id",
                            "response_model", "finish_reason", "usage", "stream_events"):
                    _must(metadata.get(key) == replay[key],
                          f"pilot returned private {key} differs from raw SSE")
                _must(receipt.get("usage") == replay["usage"]
                      and receipt.get("failure_code") is None
                      and _number(receipt.get("latency_s"), manifest["per_call_timeout_s"] + 10)
                      and (receipt.get("ttft_s") is None
                           or (_number(receipt["ttft_s"], manifest["per_call_timeout_s"] + 10)
                               and receipt["ttft_s"] <= receipt["latency_s"])),
                      "pilot returned public usage/timing/status differs")
                verified_streams += 1
                content = replay["content"]
            else:
                _must(receipt.get("failure_code") in {
                    "timeout", "transport_or_runtime_error", "provenance_drift"},
                    "pilot failed call has no closed failure code")
                content = None
            if index == 0:
                comp = pilot._parse_comprehension(content, cell["seat"])
                comp_status = "passed" if comp is True else "failed" if comp is False else "unknown"
                comprehension_passed += comp is True
            else:
                action = pilot._parse_action(content)
                _must(receipt.get("action") == action,
                      "pilot public action differs from private SSE content")
                if action is None:
                    invalid_round = round_number
                    _must(index == len(row["calls"]) - 1,
                          "pilot issued further actions after the first invalid action")
                else:
                    _must(invalid_round is None,
                          "pilot action followed an invalid predecessor")
                    joint = optimal_control.actions_for(
                        tuple(optimal_control.MIXES[cell["mix"]]), cell["seat"], action,
                        any(0 in item["joint_actions"] for item in history))
                    history.append({
                        "round": round_number, "joint_actions": list(joint),
                        "material_payoffs": [str(payoff) for payoff in calibration.payoffs(joint)],
                        "aggregate_contributors": sum(joint),
                        "defection_seen_before_recorded_round": any(
                            0 in item["joint_actions"] for item in history),
                    })
                    actions.append(action)
                    valid_actions += 1
        _must(row.get("comprehension") == comp_status
              and row.get("valid_prefix_actions") == len(actions)
              and row.get("first_invalid_round") == invalid_round,
              "pilot cell comprehension/prefix differs from private calls")
        full = (optimal_control.evaluate_sequence(
            actions, tuple(optimal_control.MIXES[cell["mix"]]), cell["objective"],
            player=cell["seat"]) if len(actions) == pilot.HORIZON else None)
        if full is None:
            _must(row.get("full_episode") is None,
                  "incomplete pilot episode invented full-horizon score")
        else:
            complete_episodes += 1
            zero_regret += full["episode_regret"] == "0"
            oracle_raw = _read(output, f"private/oracle-{ordinal:02d}.json", MAX_ORACLE_BYTES)
            _must(oracle_raw == pilot._raw_json(full) + b"\n"
                  and row.get("full_episode") == {
                      "total_utility": full["total_utility"],
                      "episode_regret": full["episode_regret"],
                      "focal_cooperation_rate": full["focal_cooperation_rate"],
                      "group_cooperation_rate": full["group_cooperation_rate"],
                      "private_oracle_sha256": pilot._sha(oracle_raw),
                  }, "pilot full-horizon DP/private oracle differs")
        if (ordinal < len(run["cells"]) - 1
                or run["status"] in {"complete", "completed_schedule_with_unknown_actions",
                                      "incomplete_cutoff"}):
            cell_raw = _read(output, f"cell-{ordinal:02d}.json", MAX_METADATA_BYTES)
            _must(cell_raw == pilot._raw_json(row) + b"\n",
                  "pilot completed cell raw receipt differs")
    _must(attempts == run["attempted_calls"],
          "pilot attempted denominator differs from recorded private calls")
    full_schedule = len(run["cells"]) == 12
    if full_schedule:
        expected_status = ("complete" if complete_episodes == 12
                           else "completed_schedule_with_unknown_actions")
        _must(run.get("status") == expected_status and run.get("failure") is None,
              "pilot complete schedule status differs from replay")
    else:
        _must(run.get("status") in {"incomplete_cutoff", "incomplete_safety_or_cutoff",
                                        "ineligible_provenance_drift"},
              "pilot partial schedule was falsely marked complete")
    return {
        "schema": SCHEMA, "status": "admitted_empirical_pilot" if full_schedule else "partial_observed",
        "admission_eligible": full_schedule,
        "campaign_id": manifest["campaign_id"], "study_id": manifest["study_id"],
        "manifest_sha256": manifest["manifest_sha256"],
        "run_sha256": pilot._sha(run_raw),
        "scheduled_episodes": 12, "recorded_episodes": len(run["cells"]),
        "scheduled_action_calls": 96, "valid_action_calls": valid_actions,
        "complete_episodes": complete_episodes,
        "comprehension_passed": comprehension_passed,
        "zero_regret_complete_episodes": zero_regret,
        "attempted_calls": attempts, "returned_sse_verified": verified_streams,
        "comparison_eligible": False, "scientific_novelty_claimed": False,
        "private_content_exported": False,
    }


__all__ = ["PilotAdmissionError", "validate_pilot"]
