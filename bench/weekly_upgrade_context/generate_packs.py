#!/usr/bin/env python3
"""Render the frozen public-synthetic long-context packs and eval manifest.

The generator is stdlib-only and does not tokenize text or contact a model.
It makes the large fixtures reviewable: a small set of planted records is
placed deterministically among clearly labelled synthetic distractors.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKS_PATH = Path(__file__).with_name("packs.json")
MANIFEST_PATH = (
    REPO_ROOT / "experiments" / "weekly_context_capability_v1_2026-09-14.json"
)
GENERATOR_PATH = Path(__file__).resolve()
GENERATOR_REPO_PATH = "bench/weekly_upgrade_context/generate_packs.py"
SCHEMA_VERSION = "weekly-context-packs/v1"
SUITE_ID = "weekly-context-capability-public-synthetic-v1-2026-09-14"

SYSTEM = (
    "Use only the public synthetic evidence packet. Distinguish direct evidence, "
    "contradictions, and irrelevant archive records. Return exactly one JSON "
    "object with keys answer_code and citations; citations must be the exact "
    "source IDs needed for the answer. The question enumerates required evidence "
    "roles: cite exactly one focal GT source for every named role and no other "
    "source. Return no prose or markdown."
)

_MECHANISMS = (
    "sealed-bid auction",
    "roommate matching",
    "network formation",
    "cost sharing",
    "committee voting",
    "bargaining",
)
_MEASURES = (
    "parser checksum",
    "queue depth",
    "serialization latency",
    "fixture row count",
    "schema version",
    "archive byte count",
)
_LABELS = (
    "calibration-only",
    "superseded logistics",
    "unrelated pilot",
    "format validation",
)


@dataclass(frozen=True)
class PackSpec:
    pack_id: str
    task_id: str
    band: str
    record_count: int
    planted: dict[int, str]
    answer_code: str
    citations: tuple[str, ...]
    citation_roles: tuple[str, ...]
    alternatives: tuple[str, ...]
    question: str


PACK_SPECS = (
    PackSpec(
        pack_id="8A",
        task_id="long_context_8k_grim_threshold",
        band="around_8k",
        record_count=145,
        planted={
            17: (
                "[GT8A-CLAIM-0017] Public synthetic draft: with Prisoner's "
                "Dilemma payoffs T=5, R=3, P=1, S=0, grim trigger sustains "
                "cooperation for every continuation probability delta at least 0.40."
            ),
            73: (
                "[GT8A-PAYOFF-0073] Public synthetic payoff note: cooperation "
                "under grim trigger gives R/(1-delta); a one-shot defection "
                "followed by permanent punishment gives T plus "
                "delta*P/(1-delta)."
            ),
            132: (
                "[GT8A-THRESHOLD-0132] Public synthetic audit: applying the "
                "incentive constraint to T=5, R=3, P=1 yields delta at least "
                "(T-R)/(T-P)=2/4=0.50. Delta 0.40 fails the constraint."
            ),
        },
        answer_code="claim_contradicted_threshold_0_5",
        citations=(
            "GT8A-CLAIM-0017",
            "GT8A-PAYOFF-0073",
            "GT8A-THRESHOLD-0132",
        ),
        citation_roles=(
            "the draft claim being assessed",
            "the primitive payoff/incentive relation",
            "the independently computed threshold audit",
        ),
        alternatives=(
            "claim_supported",
            "claim_contradicted_threshold_0_5",
            "insufficient_evidence",
        ),
        question=(
            "Is the draft's delta>=0.40 claim consistent with the packet?"
        ),
    ),
    PackSpec(
        pack_id="8B",
        task_id="long_context_8k_attrition",
        band="around_8k",
        record_count=150,
        planted={
            21: (
                "[GT8B-PROTOCOL-0021] Public synthetic protocol: forty-eight "
                "public-goods groups were randomized equally between baseline "
                "and peer punishment; final-round mean contribution was the "
                "preregistered primary outcome."
            ),
            69: (
                "[GT8B-PRELIM-0069] Public synthetic complete-case table: among "
                "groups observed in the final round, mean contribution was 4.1 "
                "at baseline and 6.8 under peer punishment."
            ),
            111: (
                "[GT8B-ATTRITION-0111] Public synthetic attrition audit: four "
                "low-contribution punishment groups withdrew before the final "
                "round; no baseline group withdrew, and the missing punishment "
                "outcomes are unknown."
            ),
            143: (
                "[GT8B-ANALYSIS-0143] Public synthetic analysis note: because "
                "final outcomes for the four withdrawn punishment groups are "
                "absent, the packet cannot compute the preregistered "
                "all-randomized-groups contrast."
            ),
        },
        answer_code="causal_increase_not_identified_differential_attrition",
        citations=(
            "GT8B-PROTOCOL-0021",
            "GT8B-PRELIM-0069",
            "GT8B-ATTRITION-0111",
            "GT8B-ANALYSIS-0143",
        ),
        citation_roles=(
            "the randomized protocol and preregistered endpoint",
            "the complete-case estimate",
            "the differential-attrition audit",
            "the analysis consequence for the all-randomized contrast",
        ),
        alternatives=(
            "causal_increase_identified",
            "causal_increase_not_identified_differential_attrition",
            "insufficient_evidence",
        ),
        question=(
            "Does the packet identify a causal increase in the preregistered "
            "final-round outcome?"
        ),
    ),
    PackSpec(
        pack_id="14A",
        task_id="long_context_14k_social_choice",
        band="around_14k",
        record_count=255,
        planted={
            29: (
                "[GT14A-CLAIM-0029] Public synthetic manuscript claim: in the "
                "reported nine-voter election, candidate A is both the plurality "
                "winner and the Condorcet winner."
            ),
            126: (
                "[GT14A-BALLOTS-0126] Public synthetic ballot profile: four "
                "voters rank A>B>C, three rank B>C>A, and two rank C>B>A."
            ),
            239: (
                "[GT14A-TALLY-0239] Public synthetic independent tally: plurality "
                "first choices are A=4, B=3, C=2; pairwise B defeats A by 5 to 4 "
                "and B defeats C by 7 to 2."
            ),
        },
        answer_code="plurality_a_condorcet_b_claim_contradicted",
        citations=(
            "GT14A-CLAIM-0029",
            "GT14A-BALLOTS-0126",
            "GT14A-TALLY-0239",
        ),
        citation_roles=(
            "the manuscript claim being assessed",
            "the primitive ballot profile",
            "the independent plurality and pairwise tally",
        ),
        alternatives=(
            "plurality_a_condorcet_a_claim_supported",
            "plurality_a_condorcet_b_claim_contradicted",
            "insufficient_evidence",
        ),
        question="Is the manuscript's joint winner claim correct?",
    ),
    PackSpec(
        pack_id="14B",
        task_id="long_context_14k_primary_endpoint",
        band="around_14k",
        record_count=260,
        planted={
            25: (
                "[GT14B-PLAN-0025] Public synthetic preregistration: 240 "
                "participants, randomized institution assignment, and round-10 "
                "contribution as the sole primary endpoint; rounds 1-9 are exploratory."
            ),
            117: (
                "[GT14B-RESULT-0117] Public synthetic results: the treatment "
                "difference over exploratory rounds 1-9 has p=0.03, while the "
                "preregistered round-10 treatment difference has p=0.41 and its "
                "interval includes zero."
            ),
            213: (
                "[GT14B-ABSTRACT-0213] Public synthetic original abstract: "
                "punishment institutions causally increase contribution, without "
                "limiting the statement to exploratory rounds."
            ),
            251: (
                "[GT14B-CORRECTION-0251] Public synthetic correction: the abstract "
                "claim was withdrawn because the primary endpoint was null; the "
                "rounds 1-9 pattern remains exploratory only."
            ),
        },
        answer_code="primary_endpoint_null_abstract_claim_contradicted",
        citations=(
            "GT14B-PLAN-0025",
            "GT14B-RESULT-0117",
            "GT14B-ABSTRACT-0213",
            "GT14B-CORRECTION-0251",
        ),
        citation_roles=(
            "the preregistered endpoint definition",
            "the primary and exploratory numeric result",
            "the abstract claim being assessed",
            "the published correction",
        ),
        alternatives=(
            "primary_endpoint_supports_claim",
            "primary_endpoint_null_abstract_claim_contradicted",
            "insufficient_evidence",
        ),
        question=(
            "Does the packet support the abstract's unqualified causal increase "
            "claim on the preregistered primary endpoint?"
        ),
    ),
)


def canonical_bytes(value: Any) -> bytes:
    """Stable pretty JSON used for the reviewable frozen artifacts."""
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _distractor(pack_id: str, index: int) -> str:
    return (
        f"[SYN-{pack_id}-D{index:04d}] Public synthetic archive distractor "
        f"{index:04d}: the {_MECHANISMS[index % len(_MECHANISMS)]} fixture "
        f"recorded {_MEASURES[(index * 3) % len(_MEASURES)]} under batch label "
        f"{_LABELS[(index * 5) % len(_LABELS)]}. This metadata record contains "
        "no result about the focal claim and must not be cited."
    )


def _question(spec: PackSpec) -> str:
    allowed = json.dumps(list(spec.alternatives), separators=(",", ":"))
    required_roles = "; ".join(
        f"({index}) {role}" for index, role in enumerate(spec.citation_roles, 1)
    )
    return (
        f"Question: {spec.question} Required evidence roles: {required_roles}. "
        "The citations array must contain exactly one focal GT source ID for each "
        "required role, in the role order above, and no other IDs. "
        f"answer_code must be exactly one of {allowed}. "
        "Return exactly {\"answer_code\":\"<one allowed code>\","
        "\"citations\":[\"source IDs needed for the answer\"]}."
    )


def _prompt(spec: PackSpec) -> str:
    lines = [
        (
            "PUBLIC SYNTHETIC LONG-CONTEXT EVIDENCE PACK. Every record is "
            "hand-authored for evaluation; none is an empirical result. Most "
            "SYN-* records are deliberate distractors. Use the few focal GT* "
            "sources needed by the question and do not cite distractors."
        )
    ]
    for index in range(1, spec.record_count + 1):
        lines.append(spec.planted.get(index, _distractor(spec.pack_id, index)))
    lines.append(_question(spec))
    return "\n".join(lines)


def build_packs() -> dict[str, Any]:
    generator_sha = sha256_bytes(GENERATOR_PATH.read_bytes())
    packs = []
    for spec in PACK_SPECS:
        prompt = _prompt(spec)
        packs.append({
            "id": spec.pack_id,
            "task_id": spec.task_id,
            "target_band": spec.band,
            "record_count": spec.record_count,
            "origin": "public_synthetic_hand_authored",
            "prompt": prompt,
            "prompt_sha256": sha256_bytes(prompt.encode("utf-8")),
            "planted_positions": sorted(spec.planted),
            "expected": {
                "answer_code": spec.answer_code,
                "citations": list(spec.citations),
                "citation_roles": list(spec.citation_roles),
            },
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "suite_id": SUITE_ID,
        "publication_class": "public_synthetic_development",
        "generator": {
            "path": GENERATOR_REPO_PATH,
            "sha256": generator_sha,
        },
        "claim_limits": [
            "This panel measures resident-model long-context capability; it is not a causal inference-policy comparison.",
            "All evidence and answers are public synthetic development fixtures, not empirical research or a hidden benchmark.",
            "No result authorizes a model, runtime, policy, context, or production cutover.",
            "The resident-default arms share temperature=0/top_p=1/seed=0, but Gemma is non-thinking while Qwen uses its template-default xhigh thinking mode.",
        ],
        "packs": packs,
    }


def build_manifest(packs_doc: dict[str, Any]) -> dict[str, Any]:
    by_id = {pack["id"]: pack for pack in packs_doc["packs"]}
    tasks = []
    for spec in PACK_SPECS:
        pack = by_id[spec.pack_id]
        tasks.append({
            "id": spec.task_id,
            "family": "evidence",
            "mode": "chat",
            "system": SYSTEM,
            "prompt": pack["prompt"],
            "grader": {
                "kind": "evidence_attribution",
                "expected": {
                    "answer_code": pack["expected"]["answer_code"],
                    "citations": pack["expected"]["citations"],
                },
            },
        })
    return {
        "schema_version": "weekly-upgrade-eval-manifest/v1",
        "suite_id": SUITE_ID,
        "description": (
            "Four public-synthetic evidence packs compare resident Gemma and "
            "Qwen long-context capability at approximately 8K and 14K input. "
            "Both resident-default arms use temperature=0, top_p=1, seed=0, "
            "the same evidence and answer schema, a 1024-token output cap, and "
            "the same request timeout. Gemma is non-thinking; Qwen retains its "
            "template-default xhigh thinking mode. "
            "This descriptive model/context capability check is not a causal "
            "inference-policy comparison and grants no production authority."
        ),
        "bootstrap_seed": 20260914,
        "bootstrap_samples": 4000,
        "ordering": "alternating_ab_ba",
        "source_snapshot": packs_doc["generator"],
        "arms": [
            {
                "id": "A",
                "label": "Gemma resident deterministic non-thinking 32K capability lane",
                "backend": "vllm-gemma",
                "profile": "deterministic",
                "model": "gemma-4-26b-a4b",
                "max_tokens": 1024,
                "request_timeout_s": 120,
                "seed": 0,
            },
            {
                "id": "B",
                "label": "Qwen resident deterministic template-default xhigh 16K capability lane",
                "backend": "vllm-qwen",
                "profile": "deterministic",
                "model": "qwen3.8-27b-nvfp4-mtp",
                "max_tokens": 1024,
                "request_timeout_s": 120,
                "seed": 0,
            },
        ],
        "tasks": tasks,
    }


def rendered_outputs() -> dict[Path, bytes]:
    packs = build_packs()
    return {
        PACKS_PATH: canonical_bytes(packs),
        MANIFEST_PATH: canonical_bytes(build_manifest(packs)),
    }


def write_outputs(*, check: bool) -> None:
    mismatches = []
    for path, expected in rendered_outputs().items():
        if check:
            if not path.is_file() or path.read_bytes() != expected:
                mismatches.append(str(path.relative_to(REPO_ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(expected)
    if mismatches:
        raise SystemExit("frozen context artifact drift: " + ", ".join(mismatches))


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    write_outputs(check=args.check)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
