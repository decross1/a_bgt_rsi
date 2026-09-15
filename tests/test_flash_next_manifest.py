import copy
from collections import Counter

import pytest

from bench.flash_next_ab.manifest import (
    PlanError,
    build_plan,
    make_arm_receipt,
    plan_fingerprints,
    policy_set,
    sha256_json,
    validate_arms,
    validate_plan,
)


def arms():
    return [
        make_arm_receipt(
            "resident",
            qualification_receipt_sha256="1" * 64,
            artifact_sha256_by_endpoint={
                "resident_gemma": "2" * 64,
                "resident_qwen": "3" * 64,
            },
            runtime_sha256_by_endpoint={
                "resident_gemma": "4" * 64,
                "resident_qwen": "5" * 64,
            },
        ),
        make_arm_receipt(
            "flash",
            qualification_receipt_sha256="6" * 64,
            artifact_sha256_by_endpoint={"flash_next": "7" * 64},
            runtime_sha256_by_endpoint={"flash_next": "8" * 64},
        ),
    ]


def test_full_plan_covers_every_registered_family_and_frozen_cell_matrix():
    plan, definitions = build_plan(arms())
    assert len(definitions) == 126
    assert Counter(row["family"] for row in plan["cell_receipts"].values()) == {
        "objective": 24,
        "topic": 48,
        "context": 4,
        "portfolio": 16,
        "diversity": 10,
        "role_effort": 18,
        "historical": 6,
    }
    assert plan["declared_cells"] == list(plan["cell_receipts"])
    assert validate_plan(plan) is plan
    assert all(len(value) == 64 for value in plan_fingerprints(plan).values())


def test_context_endpoint_arms_are_collapsed_but_substantive_variants_remain():
    plan, _ = build_plan(arms())
    context = [
        row for row in plan["cell_receipts"].values() if row["family"] == "context"
    ]
    assert {row["condition"] for row in context} == {"matched"}
    assert len({row["task_id"] for row in context}) == 4
    assert {
        row["condition"]
        for row in plan["cell_receipts"].values()
        if row["family"] == "role_effort"
    } == {"xhigh", "medium", "adaptive"}


def test_fixed_bundle_routes_and_gemma_effort_omission_are_explicit():
    resident, flash = arms()
    resident_routes = {row["role"]: row for row in resident["routes"]}
    assert resident_routes["critic"]["endpoint_name"] == "resident_qwen"
    assert all(
        route["endpoint_name"] == "resident_gemma"
        for role, route in resident_routes.items()
        if role != "critic"
    )
    assert {route["endpoint_name"] for route in flash["routes"]} == {"flash_next"}
    assert "reasoning_effort" not in policy_set("resident_gemma")["critic_current"]
    assert policy_set("flash_next")["critic_current"]["reasoning_effort"] == "xhigh"
    for endpoint, expected_top_k in (
        ("resident_gemma", 64), ("resident_qwen", 20), ("flash_next", 20)
    ):
        assert all(
            policy["top_k"] == expected_top_k
            for policy in policy_set(endpoint).values()
        )


def test_small_plan_preserves_requested_order_and_rejects_unknown_cells():
    full, _ = build_plan(arms(), families=["objective"])
    requested = list(reversed(full["declared_cells"][:2]))
    plan, definitions = build_plan(
        arms(), families=["objective"], cell_ids=requested
    )
    assert plan["declared_cells"] == requested
    assert list(definitions) == requested
    with pytest.raises(PlanError, match="unavailable"):
        build_plan(arms(), families=["objective"], cell_ids=["missing"])


@pytest.mark.parametrize("mutation", ["call", "policy", "source", "promotion"])
def test_plan_tampering_fails_closed(mutation):
    plan, _ = build_plan(arms(), families=["context"])
    changed = copy.deepcopy(plan)
    cell = changed["cell_receipts"][changed["declared_cells"][0]]
    if mutation == "call":
        cell["call_plan"]["steps"][0]["seed"] += 1
    elif mutation == "policy":
        changed["arms"][0]["routes"][0]["policies"]["deterministic"]["top_p"] = 0.5
    elif mutation == "source":
        cell["source"]["task_sha256"] = "z" * 64
    else:
        changed["promotion_authorized"] = True
    with pytest.raises(PlanError):
        validate_plan(changed)


def test_plan_and_call_hashes_are_canonical_and_recomputable():
    plan, _ = build_plan(arms(), families=["diversity"])
    for cell in plan["cell_receipts"].values():
        assert cell["call_plan_sha256"] == sha256_json(cell["call_plan"])
    for arm in plan["arms"]:
        for route in arm["routes"]:
            assert route["policy_set_sha256"] == sha256_json(route["policies"])


def mia_arm():
    return make_arm_receipt(
        "flash",
        qualification_receipt_sha256="9" * 64,
        artifact_sha256_by_endpoint={"flash_next_mia": "a" * 64},
        runtime_sha256_by_endpoint={"flash_next_mia": "b" * 64},
        flash_endpoint_name="flash_next_mia",
    )


def test_explicit_mia_bundle_uses_same_tasks_and_policy_with_distinct_identity():
    resident, nvidia = arms()
    nvidia_plan, _ = build_plan([resident, nvidia])
    mia_plan, _ = build_plan([resident, mia_arm()])
    assert validate_plan(mia_plan) is mia_plan
    assert mia_plan["declared_cells"] == nvidia_plan["declared_cells"]
    assert mia_plan["cell_receipts"] == nvidia_plan["cell_receipts"]
    assert mia_plan["arms"][0] == nvidia_plan["arms"][0]
    assert sha256_json(mia_plan) != sha256_json(nvidia_plan)
    assert policy_set("flash_next_mia") == policy_set("flash_next")
    assert {row["endpoint_name"] for row in mia_plan["arms"][1]["routes"]} == {"flash_next_mia"}
    assert {row["served_model"] for row in mia_plan["arms"][1]["routes"]} == {"qwen3.8-flash-next-mia"}


@pytest.mark.parametrize("mutation", ["variant", "artifact", "runtime", "resident", "served_name"])
def test_flash_bundle_rejects_mixed_variants_or_identities(mutation):
    candidate = mia_arm()
    row = candidate["routes"][-1]
    if mutation == "variant":
        row.update(endpoint_name="flash_next", served_model="qwen3.8-flash-next")
    elif mutation == "artifact":
        row["artifact_sha256"] = "c" * 64
    elif mutation == "runtime":
        row["runtime_sha256"] = "d" * 64
    elif mutation == "resident":
        row.update(endpoint_name="resident_qwen", served_model="qwen3.8-27b-nvfp4-mtp")
    else:
        row["served_model"] = "qwen3.8-flash-next"
    with pytest.raises(PlanError):
        validate_arms([candidate], partial=True)


def test_unknown_flash_variant_is_not_an_endpoint_alias():
    with pytest.raises(PlanError, match="not registered"):
        make_arm_receipt(
            "flash", qualification_receipt_sha256="1" * 64,
            artifact_sha256_by_endpoint={}, runtime_sha256_by_endpoint={},
            flash_endpoint_name="http://example.invalid/model",
        )
