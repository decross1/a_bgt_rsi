"""Bridge only an independently admitted known-opponent pilot into LOOP_V0.

Dry-run reads public/private hashes and produces a content-free evidence
payload. Live mode remains an explicit operator action under the active exact
campaign and its ordinary novelty/criticism/human gates; no pilot result is
promoted by this adapter.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from experiments.known_opponent_utility.admission import validate_pilot
from orchestrator.research_campaign import (
    KNOWN_OPPONENT_CAMPAIGN_ID,
    CampaignError,
    available_topics,
    load_active_campaign,
    load_campaign,
)
from orchestrator.research_ops_status import MAX_LOOP_BYTES, _read_source

STUDY_ID = "known-opponent-utility-response-pilot-v1"
METRIC = "disclosed_utility_action_validity_and_full_horizon_regret"
REPO_ROOT = Path(__file__).resolve().parents[2]


def build_bridge_payload(
    pilot_output: Path, *, topic_id: str,
    repo_root: Path = REPO_ROOT,
) -> dict:
    """Build a source-bound empirical result without model calls."""
    gate = validate_pilot(pilot_output)
    if not gate["admission_eligible"]:
        raise ValueError("partial pilot cannot make a full-schedule empirical bridge")
    campaign = load_campaign(KNOWN_OPPONENT_CAMPAIGN_ID, repo_root=repo_root)
    topic = next((row for row in campaign["topic_policy"]["topics"]
                  if row["topic_id"] == topic_id), None)
    if topic is None:
        raise CampaignError("bridge topic is not preregistered in the new campaign")
    if gate["campaign_id"] != campaign["campaign_id"] or gate["study_id"] != STUDY_ID:
        raise ValueError("admitted pilot study/campaign differs from bridge declaration")
    value = {
        "scheduled_action_calls": gate["scheduled_action_calls"],
        "valid_action_calls": gate["valid_action_calls"],
        "scheduled_episodes": gate["scheduled_episodes"],
        "complete_episodes": gate["complete_episodes"],
        "zero_regret_complete_episodes": gate["zero_regret_complete_episodes"],
        "comprehension_passed": gate["comprehension_passed"],
        "attempted_calls": gate["attempted_calls"],
        "run_sha256": gate["run_sha256"],
        "manifest_sha256": gate["manifest_sha256"],
    }
    outcome = {
        "experiment_id": STUDY_ID,
        "metric": METRIC,
        "value": value,
        "trials": gate["recorded_episodes"],
        "summary": (
            "Prospective one-episode-per-condition utility-response pilot: "
            f"{gate['valid_action_calls']}/{gate['scheduled_action_calls']} valid actions, "
            f"{gate['complete_episodes']}/{gate['scheduled_episodes']} complete episodes, "
            f"{gate['zero_regret_complete_episodes']} zero-regret complete episodes. "
            "Descriptive local model behavior; no theoretical novelty or trading claim."
        ),
    }
    return {
        "schema": "known-opponent-utility-response-loop-bridge/v1",
        "campaign_id": campaign["campaign_id"],
        "campaign_manifest_sha256": campaign["_manifest_sha256"],
        "topic_id": topic_id, "topic_sha256": topic["text_sha256"],
        "topic_text": topic["text"],
        "pilot_admission": gate,
        "experiment_outcome": outcome,
        "scientific_novelty_claimed": False,
        "human_gate_bypassed": False,
    }


def _assert_live_eligibility(plan: dict, repo_root: Path) -> None:
    active = load_active_campaign(repo_root=repo_root, env_campaign_id="")
    if (active is None or active["campaign_id"] != plan["campaign_id"]
            or active["_manifest_sha256"] != plan["campaign_manifest_sha256"]):
        raise CampaignError("bridged study's campaign is not the active exact version")
    rows, proof = _read_source(repo_root, "memory/loop_memory.jsonl", MAX_LOOP_BYTES)
    if not proof["available"]:
        raise CampaignError("complete loop-memory proof is required before bridge iteration")
    eligible = available_topics(active, [row for row, _sha in rows])
    if plan["topic_id"] not in {row["topic_id"] for row in eligible}:
        raise CampaignError("bridge topic already consumed or no longer eligible")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot-output", type=Path, required=True)
    parser.add_argument("--topic-id", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--live", action="store_true")
    args = parser.parse_args(argv)
    plan = build_bridge_payload(args.pilot_output, topic_id=args.topic_id)
    if args.dry_run:
        public = {key: value for key, value in plan.items() if key != "topic_text"}
        print(json.dumps(public, sort_keys=True))
        return 0
    _assert_live_eligibility(plan, REPO_ROOT)
    from orchestrator.nara import run_iteration  # imported only after all pure gates

    record = run_iteration(
        topic=plan["topic_text"], source="known_opponent_utility_bridge",
        experiment_outcome=plan["experiment_outcome"],
        campaign_id=plan["campaign_id"],
        campaign_manifest_sha256=plan["campaign_manifest_sha256"],
    )
    print(json.dumps({
        "schema": plan["schema"], "iteration_id": record.get("iteration_id"),
        "campaign_id": plan["campaign_id"],
        "pilot_run_sha256": plan["pilot_admission"]["run_sha256"],
        "novelty_class": (record.get("novelty") or {}).get("class"),
        "critic_verdict": (record.get("critique") or {}).get("verdict"),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
