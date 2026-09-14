"""Exact, CPU-only public-goods controls; this does not call or score an LLM.

Report stage-game utility regret separately from cooperation. In repeated games,
myopic regret is a diagnostic, not proof that a long-horizon strategy is wrong.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from fractions import Fraction
from pathlib import Path

DEFAULT_MANIFEST = Path(__file__).resolve().parents[2] / "experiments/agentic_game_theory_v2_calibration_2026-09-14.json"
OBJECTIVES = ("own_payoff", "joint_payoff")
VISIBILITY = ("public_history", "own_outcomes")
POLICIES = ("retain", "contribute", "previous_majority")


def load_manifest(path: Path) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate manifest field")
            result[key] = value
        return result
    if path.stat().st_size > 64_000:
        raise ValueError("manifest exceeds bound")
    value = json.loads(path.read_bytes(), object_pairs_hook=unique)
    expected = {"schema_version", "campaign_id", "study_id", "players", "endowment",
                "multiplier", "rounds", "objectives", "visibility", "policies",
                "model_calls_authorized", "status", "hypotheses", "future_model_trial"}
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("invalid calibration manifest fields")
    if (value["schema_version"] != "agentic-game-theory-calibration/v1"
            or value["model_calls_authorized"] is not False
            or value["status"] != "cpu_calibration_only"
            or value["players"] != 4 or type(value["players"]) is not int
            or value["endowment"] != 5 or type(value["endowment"]) is not int
            or value["multiplier"] != "2" or value["rounds"] != 8
            or type(value["rounds"]) is not int
            or tuple(value["objectives"]) != OBJECTIVES
            or tuple(value["visibility"]) != VISIBILITY
            or tuple(value["policies"]) != POLICIES):
        raise ValueError("unsupported or GPU-enabled calibration configuration")
    return value


def payoffs(actions: tuple[int, ...], *, endowment: int = 5,
            multiplier: Fraction = Fraction(2)) -> tuple[Fraction, ...]:
    """Actions are exact binary contribute-all decisions, not amounts."""
    if len(actions) != 4 or any(type(a) is not int or a not in (0, 1) for a in actions):
        raise ValueError("four binary integer actions required")
    if type(endowment) is not int or endowment <= 0 or not 1 < multiplier < len(actions):
        raise ValueError("public-goods social dilemma parameters required")
    common_return = multiplier * endowment * sum(actions) / len(actions)
    return tuple(Fraction(endowment * (1 - action)) + common_return for action in actions)


def utility(actions: tuple[int, ...], player: int, objective: str) -> Fraction:
    if type(player) is not int or not 0 <= player < 4 or objective not in OBJECTIVES:
        raise ValueError("invalid player or objective")
    values = payoffs(actions)
    return values[player] if objective == "own_payoff" else sum(values, Fraction())


def regret(actions: tuple[int, ...], player: int, objective: str) -> Fraction:
    alternatives = [actions[:player] + (a,) + actions[player + 1:] for a in (0, 1)]
    return max(utility(a, player, objective) for a in alternatives) - utility(actions, player, objective)


def observation(history: list[tuple[int, ...]], player: int, visibility: str) -> dict:
    if visibility not in VISIBILITY or type(player) is not int or not 0 <= player < 4:
        raise ValueError("invalid observation contract")
    result = {"player": player, "round": len(history) + 1,
              "own_actions": [h[player] for h in history],
              "own_payoffs": [str(payoffs(h)[player]) for h in history]}
    if visibility == "public_history":
        result["public_actions"] = [list(h) for h in history]
    return result


def act(policy: str, visible: dict) -> int:
    if policy == "retain":
        return 0
    if policy == "contribute":
        return 1
    if policy != "previous_majority":
        raise ValueError("unknown classical policy")
    # With own outcomes, a player can infer aggregate contributions from payoff
    # and own action; pretending this information is absent would be a confound.
    if not visible["own_payoffs"]:
        return 1
    if "public_actions" in visible:
        contributors = sum(visible["public_actions"][-1])
    else:
        retained = 5 * (1 - visible["own_actions"][-1])
        contributors = (Fraction(visible["own_payoffs"][-1]) - retained) / Fraction(5, 2)
    return int(contributors >= 2)


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def calibrate(manifest: dict) -> dict:
    profiles = list(itertools.product((0, 1), repeat=4))
    stage = []
    for objective in OBJECTIVES:
        equilibria = [list(a) for a in profiles if all(regret(a, i, objective) == 0 for i in range(4))]
        stage.append({"objective": objective, "pure_nash_profiles": equilibria,
                      "profiles_checked": len(profiles), "unilateral_deviations_checked": 64})
    simulations = []
    # Enumerate all 3^4 classical policy assignments; no selected seed or model
    # sampling. Hold policies fixed across objective/visibility conditions.
    for policy_assignment in itertools.product(POLICIES, repeat=4):
        for visibility in VISIBILITY:
            history = []
            for _ in range(manifest["rounds"]):
                next_actions = tuple(act(policy, observation(history, i, visibility))
                                     for i, policy in enumerate(policy_assignment))
                history.append(next_actions)
            for objective in OBJECTIVES:
                simulations.append({
                    "policies": list(policy_assignment), "visibility": visibility,
                    "objective": objective, "actions": [list(h) for h in history],
                    "cooperation_rate": sum(map(sum, history)) / (4 * len(history)),
                    "total_material_payoff": str(sum((sum(payoffs(h), Fraction()) for h in history), Fraction())),
                    "total_stage_utility_regret": str(sum((regret(h, i, objective) for h in history for i in range(4)), Fraction())),
                })
    return {
        "schema_version": "agentic-game-theory-calibration-result/v1",
        "campaign_id": manifest["campaign_id"], "study_id": manifest["study_id"],
        "manifest_sha256": _digest(manifest),
        "execution_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "status": "cpu_controls_verified", "model_calls": 0,
        "claim_scope": "classical payoff and observation controls; no LLM capability, novelty or research validation claim",
        "stage_game": stage, "classical_simulations": simulations,
        "information_warning": "Own payoff and own action identify aggregate contributions in this game; public history adds identities, not aggregate contribution information.",
        "interpretation": "Cooperation and utility consistency are distinct. Stage regret is not repeated-game equilibrium regret.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = calibrate(load_manifest(args.manifest))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"status": result["status"], "stage_game": result["stage_game"],
                      "simulations": len(result["classical_simulations"]), "model_calls": 0}))


if __name__ == "__main__":
    main()
