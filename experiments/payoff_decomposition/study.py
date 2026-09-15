"""Freeze fresh public-goods payoff questions before any local-model request.

The two views present the same four actions. They differ only in presentation;
this is an arithmetic instrument diagnostic, not a strategy intervention.
"""
from __future__ import annotations

import hashlib
import json
from fractions import Fraction
from pathlib import Path

from bench.agentic_game_theory import calibration
from bench.flash_next_ab import transport

SCHEMA = "known-opponent-payoff-decomposition-manifest/v1"
RUN_SCHEMA = "known-opponent-payoff-decomposition-run/v1"
STUDY_ID = "known-opponent-payoff-representation-v1"
POLICY = {"temperature": 0.0, "top_p": 1.0, "top_k": 64, "enable_thinking": False}
MAX_CALLS = 12
MAX_WINDOW_S = 900
MAX_TOKENS = 64
PER_CALL_TIMEOUT_S = 30.0
SEATS = (0, 3)
VIEWS = ("word_list", "seat_table")
# Panel B is an independently registered fresh-input follow-up, not an A reseed.
PANELS = {
    "payoff-representation-a": ((1, 0, 0, 0), (0, 1, 0, 1), (0, 1, 1, 1)),
    "payoff-representation-b": ((0, 0, 0, 1), (1, 1, 0, 0), (1, 1, 1, 0)),
}
SOURCE_FILES = (
    "experiments/payoff_decomposition/study.py",
    "experiments/payoff_decomposition/runner.py",
    "experiments/payoff_decomposition/admission.py",
    "experiments/payoff_decomposition/controller.py",
    "experiments/payoff_decomposition/queue.py",
    "experiments/payoff_decomposition/PREREGISTRATION.md",
    "experiments/payoff_decomposition/OPERATIONS.md",
    "bench/agentic_game_theory/calibration.py",
    "bench/flash_next_ab/transport.py",
    "bench/flash_next_ab/resident_evaluation_window.py",
    "bench/flash_next_ab/resident_admission.py",
    "experiments/known_opponent_utility/resident_controller.py",
    "experiments/known_opponent_utility/admission.py",
    "experiments/known_opponent_utility/pilot.py",
    "bench/flash_next_ab/harness.py",
    "bench/flash_next_ab/qualification.py",
    "orchestrator/weekly_upgrade_trial.py",
    "experiments/payoff_decomposition/systemd/payoff-representation@.service",
    "experiments/payoff_decomposition/systemd/payoff-representation-b.timer",
)


def raw_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def source_bundle(root: Path) -> dict[str, str]:
    root = root.resolve(strict=True)
    return {name: sha((root / name).read_bytes()) for name in SOURCE_FILES}


def oracle(actions: tuple[int, ...], seat: int) -> tuple[Fraction, Fraction]:
    values = calibration.payoffs(actions)
    return values[seat], sum(values, Fraction())


def _messages(actions: tuple[int, ...], seat: int, view: str) -> list[dict]:
    words = tuple("contribute" if action else "retain" for action in actions)
    if view == "word_list":
        presentation = "Joint actions: [" + ", ".join(words) + "]."
    elif view == "seat_table":
        presentation = ("Joint actions: " + "; ".join(
            f"seat {index}={action}" for index, action in enumerate(actions))
            + " (1=contribute, 0=retain).")
    else:
        raise ValueError("unregistered action presentation")
    before = ("Arithmetic check for one four-seat public-goods round. Seats are "
              "numbered 0,1,2,3, and the four actions are in that seat order. "
              "Each seat has 5 units; a contributor gives all "
              "5 and a retainer keeps all 5. The contributed sum is doubled and "
              "divided equally among all four seats. ")
    after = (f" For focal seat {seat}, give its material payoff and the sum of "
             "all four material payoffs. Answer exactly focal=<number>;sum=<number>. "
             "No explanation or example.")
    return [{"role": "user", "content": before + presentation + after}]


def tasks(panel_id: str) -> list[dict]:
    if panel_id not in PANELS:
        raise ValueError("unregistered fresh-input panel")
    out = []
    for index, actions in enumerate(PANELS[panel_id]):
        for seat in SEATS:
            # Reverse view order on alternating paired inputs before outcomes.
            views = VIEWS if (index + seat // 3) % 2 == 0 else tuple(reversed(VIEWS))
            pair_id = f"tuple{index + 1}-seat{seat}"
            for view in views:
                focal, total = oracle(actions, seat)
                item = {"ordinal": len(out), "pair_id": pair_id,
                        "actions": list(actions), "seat": seat, "view": view,
                        "messages": _messages(actions, seat, view),
                        "expected_focal": str(focal), "expected_total": str(total)}
                out.append({**item, "task_sha256": sha(raw_json(item))})
    if len(out) != MAX_CALLS:
        raise AssertionError("paired panel is incomplete")
    return out


def freeze_manifest(*, source_root: Path, endpoint: transport.LocalEndpoint,
                    registered_admission: dict, panel_id: str, seed_base: int) -> dict:
    endpoint.validate()
    source_root = source_root.resolve(strict=True)
    if Path(__file__).resolve() != source_root / SOURCE_FILES[0]:
        raise ValueError("study import differs from registered source root")
    if Path(calibration.__file__).resolve() != source_root / "bench/agentic_game_theory/calibration.py":
        raise ValueError("payoff control differs from registered source root")
    if Path(transport.__file__).resolve() != source_root / "bench/flash_next_ab/transport.py":
        raise ValueError("transport differs from registered source root")
    if type(seed_base) is not int or not 1 <= seed_base <= 2_147_483_642:
        raise ValueError("bounded seed required")
    if (not isinstance(registered_admission, dict)
            or registered_admission.get("status") != "passed"
            or registered_admission.get("admission_eligible") is not True
            or registered_admission.get("cohort") != "resident"
            or registered_admission.get("artifact_sha256_by_endpoint", {}).get(endpoint.name)
            != endpoint.artifact_sha256):
        raise ValueError("passed resident model qualification required")
    all_tasks = tasks(panel_id)
    # Resolve the exact local request shape and seed before a live call.
    for item in all_tasks:
        transport.request_body(endpoint, item["messages"], POLICY, MAX_TOKENS, seed_base)
    value = {"schema": SCHEMA, "study_id": STUDY_ID,
             "claim_scope": "payoff_representation_instrument_only_no_strategy_repair_or_novelty_claim",
             "panel_id": panel_id, "source_root": str(source_root),
             "source_sha256": source_bundle(source_root),
             "endpoint": endpoint.__dict__, "policy": POLICY,
             "registered_admission": registered_admission,
             "registered_admission_sha256": sha(raw_json(registered_admission)),
             "seed_base": seed_base, "max_tokens": MAX_TOKENS,
             "per_call_timeout_s": PER_CALL_TIMEOUT_S,
             "max_window_s": MAX_WINDOW_S, "max_calls": MAX_CALLS,
             "scheduled_pairs": 6, "tasks": all_tasks,
             "comparison_eligible": False, "scientific_novelty_claimed": False}
    value["manifest_sha256"] = sha(raw_json(value))
    return value


def validate_manifest(value: dict) -> None:
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise ValueError("unregistered payoff manifest")
    source_root = Path(value["source_root"])
    endpoint = transport.LocalEndpoint(**value["endpoint"])
    expected = freeze_manifest(source_root=source_root, endpoint=endpoint,
                               registered_admission=value["registered_admission"],
                               panel_id=value["panel_id"], seed_base=value["seed_base"])
    if value != expected:
        raise ValueError("payoff tasks/model/source/policy differ from frozen manifest")
