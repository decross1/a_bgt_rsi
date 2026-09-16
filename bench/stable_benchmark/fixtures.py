"""Fresh public synthetic fixtures for stable benchmark release 1.0.0.

These fixtures deliberately have no predecessor score.  They may be rendered
into a draft definition without side effects; publication is a separate,
witnessed operation in :mod:`bench.stable_benchmark.manifest`.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


RELEASE = "1.0.0"
SUITE_ID = "a-bgt-rsi-stable-1.0.0"
REVIEW_AT = "2026-10-14T00:00:00Z"

SYSTEM = (
    "Follow the response contract exactly. Return one JSON object without "
    "Markdown fences, commentary, or hidden-reasoning tags."
)


def _task(
    task_id: str,
    domain: str,
    construct: str,
    mode: str,
    prompt: str,
    grader: dict[str, Any],
    *,
    max_tokens: int,
    timeout_s: int,
    max_model_calls: int = 1,
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": task_id,
        "panel": "model_capability",
        "domain": domain,
        "construct": construct,
        "mode": mode,
        "system": SYSTEM,
        "prompt": prompt,
        "grader": grader,
        "tools": tools or [],
        "resource": {
            "max_tokens_per_call": max_tokens,
            "episode_timeout_s": timeout_s,
            "max_model_calls": max_model_calls,
        },
        "provenance": {
            "origin": "new_public_synthetic_2026-09-16",
            "predecessor_task_ids": [],
            "contamination_resistant": False,
            "claim_scope": "fixed_public_small_panel",
            "uncertainty_cluster": task_id,
        },
    }


def _science_tasks() -> list[dict[str, Any]]:
    return [
        _task(
            "SCI-MARKOV-001",
            "science_evidence",
            "quantitative_inference",
            "chat",
            (
                "A two-state Markov chain has P(A→B)=1/4 and P(B→A)=1/2. "
                "The reward is 3 in A and 9 in B. Compute the stationary probabilities "
                "and stationary long-run reward. Response fields: stationary_a, "
                "stationary_b, long_run_reward. Use JSON decimal numbers. Answers are "
                "graded at absolute error <=1e-9; give at least 10 digits after the "
                "decimal point for repeating values."
            ),
            {
                "kind": "markov_stationary",
                "inputs": {
                    "a_to_b_num": 1,
                    "a_to_b_den": 4,
                    "b_to_a_num": 1,
                    "b_to_a_den": 2,
                    "reward_a": 3,
                    "reward_b": 9,
                },
            },
            max_tokens=512,
            timeout_s=60,
        ),
        _task(
            "SCI-RCT-001",
            "science_evidence",
            "quantitative_inference",
            "chat",
            (
                "A preregistered randomized experiment observed 39 successes among 60 "
                "treated units and 24 successes among 48 control units. Report the two "
                "rates and treatment minus control risk difference. Response fields: "
                "treatment_rate, control_rate, risk_difference. Use JSON decimal numbers; "
                "answers are graded at absolute error <=1e-9."
            ),
            {
                "kind": "randomized_effect",
                "inputs": {
                    "treatment_success": 39,
                    "treatment_total": 60,
                    "control_success": 24,
                    "control_total": 48,
                },
            },
            max_tokens=512,
            timeout_s=60,
        ),
        _task(
            "EVID-SUPPORT-001",
            "science_evidence",
            "evidence_attribution",
            "chat",
            (
                "Evidence packet:\n"
                "[DOC-A] The trial assigned subjects by a recorded random-number draw.\n"
                "[DOC-B] Follow-up was 30 days for both arms; attrition was 2/60 and 1/48.\n"
                "[DOC-C] The treated success rate exceeded the control success rate.\n"
                "Decide whether the narrow claim 'the observed 30-day success rate was "
                "higher in the randomized treatment arm' is supported. Cite the minimal "
                "sufficient source set and omit sources that are merely contextual. Return "
                "exactly decision ('supported' or 'abstain'), reason_code (one of "
                "'randomized_observed_rate_higher', 'not_randomized', or "
                "'observed_rate_not_higher'), and citations."
            ),
            {
                "kind": "evidence_attribution",
                "expected": {
                    "decision": "supported",
                    "reason_code": "randomized_observed_rate_higher",
                    "citations": ["DOC-A", "DOC-C"],
                },
            },
            max_tokens=512,
            timeout_s=60,
        ),
        _task(
            "EVID-ABSTAIN-001",
            "science_evidence",
            "evidence_abstention",
            "chat",
            (
                "Evidence packet:\n"
                "[DOC-D] Twelve of the observed participants reported the outcome.\n"
                "[DOC-E] The archive does not state how many participants were observed "
                "or assigned.\n"
                "Decide whether the claim 'the outcome rate was 60%' can be established. "
                "Cite the minimal sufficient source set. Return exactly decision "
                "('supported' or 'abstain'), reason_code (one of 'missing_denominator', "
                "'complete_rate_evidence', or 'numerator_missing'), and citations."
            ),
            {
                "kind": "evidence_abstention",
                "expected": {
                    "decision": "abstain",
                    "reason_code": "missing_denominator",
                    "citations": ["DOC-D", "DOC-E"],
                },
            },
            max_tokens=512,
            timeout_s=60,
        ),
    ]


def _code_task(
    task_id: str,
    function: str,
    specification: str,
    starter: str,
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    return _task(
        task_id,
        "functional_code_repair",
        "isolated_python_function",
        "code",
        (
            f"Repair the function below. {specification}\n\n{starter}\n\n"
            "Return exactly {\"source\": \"<complete Python function source>\"}. "
            "The source must define only the requested function and must not import modules."
        ),
        {"kind": "code_function", "function": function, "cases": cases},
        max_tokens=1536,
        timeout_s=90,
    )


def _code_tasks() -> list[dict[str, Any]]:
    return [
        _code_task(
            "CODE-MERGE-001",
            "merge_windows",
            (
                "Accept a list of [start,end] integer windows. Reject start>end with "
                "ValueError. Return sorted non-overlapping lists, merging overlaps and "
                "touching endpoints. Do not mutate the input."
            ),
            "def merge_windows(windows):\n    return windows",
            [
                {"id": "overlap", "arguments": [[[5, 8], [1, 3], [3, 6], [11, 12]]], "expected_return": [[1, 8], [11, 12]]},
                {"id": "empty", "arguments": [[]], "expected_return": []},
                {"id": "invalid", "arguments": [[[4, 2]]], "expected_exception": "ValueError"},
            ],
        ),
        _code_task(
            "CODE-WEIGHTED-MEDIAN-001",
            "weighted_median",
            (
                "Accept equal-length value and nonnegative integer weight lists with "
                "positive total weight. Return the smallest value whose cumulative weight "
                "in ascending-value order is at least half the total weight. Reject invalid "
                "lengths or weights with ValueError. Do not mutate inputs."
            ),
            "def weighted_median(values, weights):\n    return values[0]",
            [
                {"id": "odd_weight", "arguments": [[9, 2, 5], [1, 4, 2]], "expected_return": 2},
                {"id": "half_boundary", "arguments": [[1, 4, 10], [2, 2, 4]], "expected_return": 4},
                {"id": "bad_weight", "arguments": [[1, 2], [1, -1]], "expected_exception": "ValueError"},
            ],
        ),
        _code_task(
            "CODE-DRAWDOWN-001",
            "max_drawdown",
            (
                "Accept a nonempty list of nonnegative integer portfolio values. Return a "
                "dictionary with exactly drop, peak_index, and trough_index for the largest "
                "earlier-peak minus later-value drop. On ties choose the earliest trough, "
                "then earliest peak. A nondecreasing series has drop 0 and both indices 0. "
                "Reject invalid input with ValueError."
            ),
            "def max_drawdown(values):\n    return {\"drop\": 0, \"peak_index\": 0, \"trough_index\": 0}",
            [
                {"id": "two_drawdowns", "arguments": [[8, 11, 7, 10, 3, 4]], "expected_return": {"drop": 8, "peak_index": 1, "trough_index": 4}},
                {"id": "flat", "arguments": [[3, 3, 4]], "expected_return": {"drop": 0, "peak_index": 0, "trough_index": 0}},
                {"id": "empty", "arguments": [[]], "expected_exception": "ValueError"},
            ],
        ),
        _code_task(
            "CODE-WATERFALL-001",
            "waterfall_payments",
            (
                "Accept nonnegative integer claims in priority order and nonnegative integer "
                "cash. Return one payment per claim, paying each up to its claim before the "
                "next, plus any remaining cash as residual: exactly {payments,residual}. "
                "Reject negative input with ValueError and do not mutate inputs."
            ),
            "def waterfall_payments(claims, cash):\n    return {\"payments\": claims, \"residual\": cash}",
            [
                {"id": "partial", "arguments": [[4, 7, 3], 9], "expected_return": {"payments": [4, 5, 0], "residual": 0}},
                {"id": "surplus", "arguments": [[2, 1], 6], "expected_return": {"payments": [2, 1], "residual": 3}},
                {"id": "negative", "arguments": [[2, -1], 3], "expected_exception": "ValueError"},
            ],
        ),
    ]


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str], results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
        "fixtures": results,
    }


def _tool_tasks() -> list[dict[str, Any]]:
    payoff_result = {"row_payoff": 5, "column_payoff": 2}
    evidence_a = {"doc_id": "E-17", "text": "The reserve price was fixed before bids."}
    evidence_b = {"doc_id": "E-22", "text": "Bidder values were not disclosed to the seller."}
    market_result = {"market_id": "M-4", "forecast_percent": 70, "outcome": 1}
    brier_result = {"score_num": 91, "score_den": 100}
    return [
        _task(
            "TOOL-SINGLE-001",
            "deterministic_tool_use",
            "single_call",
            "tools",
            (
                "Use payoff_lookup for game G-7 and profile [cooperate, defect]. Then return "
                "exactly the fields row_payoff and column_payoff from the tool result."
            ),
            {
                "kind": "tool_trace",
                "expected_trace": [{"name": "payoff_lookup", "arguments": {"game_id": "G-7", "profile": ["cooperate", "defect"]}, "result": payoff_result}],
                "expected_final": payoff_result,
                "trace_order": "exact",
            },
            tools=[_tool(
                "payoff_lookup",
                "Return payoffs for one registered game profile.",
                {"game_id": {"type": "string"}, "profile": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 2}},
                ["game_id", "profile"],
                [{"arguments": {"game_id": "G-7", "profile": ["cooperate", "defect"]}, "result": payoff_result}],
            )],
            max_tokens=512,
            timeout_s=90,
            max_model_calls=2,
        ),
        _task(
            "TOOL-PARALLEL-001",
            "deterministic_tool_use",
            "parallel_calls",
            "tools",
            (
                "Retrieve evidence E-17 and E-22 with lookup_evidence. Return exactly "
                "{\"decision\":\"proceed\",\"citations\":[\"E-17\",\"E-22\"]}."
            ),
            {
                "kind": "tool_trace",
                "expected_trace": [
                    {"name": "lookup_evidence", "arguments": {"doc_id": "E-17"}, "result": evidence_a},
                    {"name": "lookup_evidence", "arguments": {"doc_id": "E-22"}, "result": evidence_b},
                ],
                "expected_final": {"decision": "proceed", "citations": ["E-17", "E-22"]},
                "trace_order": "any",
            },
            tools=[_tool(
                "lookup_evidence",
                "Retrieve one evidence document by exact ID.",
                {"doc_id": {"type": "string"}},
                ["doc_id"],
                [
                    {"arguments": {"doc_id": "E-17"}, "result": evidence_a},
                    {"arguments": {"doc_id": "E-22"}, "result": evidence_b},
                ],
            )],
            max_tokens=512,
            timeout_s=90,
            max_model_calls=2,
        ),
        _task(
            "TOOL-NOCALL-001",
            "deterministic_tool_use",
            "relevance_no_call",
            "tools",
            (
                "The packet itself states: settlement status is final and code is S-204. "
                "Do not call a tool because no currency conversion is requested. Return "
                "exactly {\"status\":\"final\",\"code\":\"S-204\"}."
            ),
            {
                "kind": "tool_trace",
                "expected_trace": [],
                "expected_final": {"status": "final", "code": "S-204"},
                "trace_order": "exact",
            },
            tools=[_tool(
                "currency_rate",
                "Look up a currency conversion rate when conversion is requested.",
                {"base": {"type": "string"}, "quote": {"type": "string"}},
                ["base", "quote"],
                [{"arguments": {"base": "USD", "quote": "EUR"}, "result": {"rate": 0.84}}],
            )],
            max_tokens=512,
            timeout_s=45,
            # The real tool API is present.  A correct model returns directly
            # in one call, while an incorrect tool call may consume the one
            # permitted follow-up before the episode is failed.
            max_model_calls=2,
        ),
        _task(
            "TOOL-DEPENDENT-001",
            "deterministic_tool_use",
            "dependent_calls",
            "tools",
            (
                "First call lookup_market for M-4. Then pass its forecast_percent and outcome "
                "to brier_score. Return exactly the score_num and score_den from brier_score."
            ),
            {
                "kind": "tool_trace",
                "expected_trace": [
                    {"name": "lookup_market", "arguments": {"market_id": "M-4"}, "result": market_result},
                    {"name": "brier_score", "arguments": {"forecast_percent": 70, "outcome": 1}, "result": brier_result},
                ],
                "expected_final": brier_result,
                "trace_order": "exact",
            },
            tools=[
                _tool(
                    "lookup_market",
                    "Retrieve the registered forecast and resolved binary outcome.",
                    {"market_id": {"type": "string"}},
                    ["market_id"],
                    [{"arguments": {"market_id": "M-4"}, "result": market_result}],
                ),
                _tool(
                    "brier_score",
                    "Compute one minus squared error for an integer-percent binary forecast.",
                    {"forecast_percent": {"type": "integer", "minimum": 0, "maximum": 100}, "outcome": {"type": "integer", "enum": [0, 1]}},
                    ["forecast_percent", "outcome"],
                    [{"arguments": {"forecast_percent": 70, "outcome": 1}, "result": brier_result}],
                ),
            ],
            max_tokens=512,
            timeout_s=120,
            max_model_calls=3,
        ),
    ]


def _strategic_task(task_id: str, construct: str, prompt: str, inputs: dict[str, Any]) -> dict[str, Any]:
    task = _task(
        task_id,
        "strategic_behavior",
        construct,
        "strategic",
        prompt + " Return exactly one integer field: {\"action\": <integer>}.",
        {"kind": "strategic_action", "inputs": inputs},
        max_tokens=512,
        timeout_s=45,
    )
    # The two public-goods and two Vickrey parameterizations are repeated
    # instances of their mechanism, not four independent constructs.
    task["provenance"]["uncertainty_cluster"] = construct
    return task


def _strategic_tasks() -> list[dict[str, Any]]:
    return [
        _strategic_task(
            "GAME-PUBLIC-GOODS-101",
            "public_goods",
            "Maximize your own payoff. You have endowment 10. Choose an integer contribution 0..10. Three known players contribute 0, 3, and 8. Total contributions are multiplied by 8/5 and divided equally among four players; you retain un-contributed tokens.",
            {"allowed_actions": list(range(11)), "endowment": 10, "other_contributions": [0, 3, 8], "multiplier_num": 8, "multiplier_den": 5},
        ),
        _strategic_task(
            "GAME-PUBLIC-GOODS-211",
            "public_goods",
            "Maximize your own payoff. You have endowment 12. Choose an integer contribution 0..12. Three known players contribute 2, 6, and 9. Total contributions are multiplied by 12/5 and divided equally among four players; you retain un-contributed tokens.",
            {"allowed_actions": list(range(13)), "endowment": 12, "other_contributions": [2, 6, 9], "multiplier_num": 12, "multiplier_den": 5},
        ),
        _strategic_task(
            "GAME-VICKREY-101",
            "vickrey_auction",
            "Maximize your own payoff. In a sealed second-price auction your value is 8. Known other bids are [3,7,5] and their values are [3,7,5]. Choose an integer bid 0..12. Highest bid wins and pays the second-highest bid; ties go to the lowest player index, and you are index 0.",
            {"allowed_actions": list(range(13)), "value": 8, "other_bids": [3, 7, 5], "other_values": [3, 7, 5]},
        ),
        _strategic_task(
            "GAME-VICKREY-211",
            "vickrey_auction",
            "Maximize your own payoff. In a sealed second-price auction your value is 5. Known other bids are [7,4,2] and their values are [7,4,2]. Choose an integer bid 0..12. Highest bid wins and pays the second-highest bid; ties go to the lowest player index, and you are index 0.",
            {"allowed_actions": list(range(13)), "value": 5, "other_bids": [7, 4, 2], "other_values": [7, 4, 2]},
        ),
        _strategic_task(
            "GAME-COURNOT-307",
            "cournot",
            "Maximize your own payoff. Choose an integer quantity 0..12. The known other producer chooses 5. Price is max(0,20-total quantity), marginal cost is 2 for both firms, and profit is (price-cost)*own quantity.",
            {"allowed_actions": list(range(13)), "other_quantity": 5, "demand_intercept": 20, "marginal_cost": 2},
        ),
        _strategic_task(
            "GAME-BRIER-401",
            "proper_scoring_reporting",
            "Maximize your own expected Brier utility. Your private Bernoulli belief is P(Y=1)=0.65. Report an integer probability percent 0..100 before the outcome; a known comparison forecaster reports 70. Utility after resolution is 1-(q-Y)^2.",
            {"allowed_actions": list(range(101)), "belief_percent": 65, "opponent_report": 70},
        ),
    ]


def _mission(
    mission_id: str,
    construct: str,
    prompt: str,
    tool: dict[str, Any],
    expected_args: dict[str, Any],
    result: dict[str, Any],
    expected_final: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": mission_id,
        "panel": "system_micro_workflow",
        "domain": "system_harness",
        "construct": construct,
        "mode": "system_mission",
        "system": SYSTEM,
        "prompt": prompt,
        "tools": [
            tool,
            _tool(
                "format_note",
                "Format a supplied note; this tool cannot calculate or verify the mission.",
                {"note": {"type": "string"}},
                ["note"],
                [{"arguments": {"note": "noop"}, "result": {"formatted": "noop"}}],
            ),
        ],
        "grader": {
            "kind": "system_mission",
            "expected_trace": [{"name": tool["name"], "arguments": expected_args, "result": result}],
            "expected_final": expected_final,
        },
        # The production Qwen critic route uses ``critic_current`` (xhigh).
        # A 768-token shared actor/critic cap would turn visible-final
        # truncation into a model score.  The 1,536 ceiling matches the
        # already-registered Flash cap diagnostic's larger arm and remains
        # small enough for the one-Spark weekly envelope.
        "resource": {"max_tokens_per_call": 1536, "episode_timeout_s": 120, "max_model_calls": 2},
        "provenance": {
            "origin": "new_public_synthetic_2026-09-16",
            "predecessor_task_ids": [],
            "contamination_resistant": False,
            "claim_scope": "actor_tool_critic_micro_workflow_only",
            "uncertainty_cluster": construct,
        },
    }


def _system_missions() -> list[dict[str, Any]]:
    payoff_args = {"endowment": 10, "contributions": [0, 3, 8, 4], "multiplier_num": 8, "multiplier_den": 5, "focal_index": 3}
    payoff_result = {"focal_num": 12, "focal_den": 1, "joint_num": 49, "joint_den": 1}
    auction_args = {"value": 8, "other_bids": [3, 7, 5], "candidate_bid": 8}
    auction_result = {"own_utility": 1, "efficient_winner": True, "regret": 0}
    evidence_args = {"claim": "rate_is_60_percent", "count": 12, "denominator": None}
    evidence_result = {"supported": False, "reason_code": "missing_denominator"}
    return [
        _mission(
            "SYSTEM-PAYOFF-001",
            "payoff_tool_artifact_critique",
            (
                "Analyze a four-player public-goods outcome with endowment 10 each, "
                "contributions [0,3,8,4], multiplier 8/5, and focal player index 3. Select "
                "the relevant available tool and propose a draft. Then, as critic, revise "
                "the artifact from the trusted transcript to report reduced focal and joint "
                "payoffs. The final artifact must have exactly focal_num, focal_den, "
                "joint_num, joint_den, and decision; decision must be 'retain' or 'revise' "
                "and should be 'retain' when the trusted receipt is internally consistent."
            ),
            _tool(
                "compute_public_goods",
                "Compute focal and joint public-goods utility.",
                {
                    "endowment": {"type": "integer"}, "contributions": {"type": "array", "items": {"type": "integer"}},
                    "multiplier_num": {"type": "integer"}, "multiplier_den": {"type": "integer"}, "focal_index": {"type": "integer"},
                },
                ["endowment", "contributions", "multiplier_num", "multiplier_den", "focal_index"],
                [{"arguments": payoff_args, "result": payoff_result}],
            ),
            payoff_args,
            payoff_result,
            {"focal_num": 12, "focal_den": 1, "joint_num": 49, "joint_den": 1, "decision": "retain"},
        ),
        _mission(
            "SYSTEM-AUCTION-001",
            "mechanism_tool_recommendation_critique",
            (
                "Assess candidate bid 8 for a bidder valued at 8 against other bids [3,7,5] "
                "in a second-price auction. Select the relevant available tool and propose a "
                "draft. Then, as critic, return exactly mechanism, recommended_bid, "
                "own_utility, regret, and verdict. mechanism must be 'vickrey' or "
                "'first_price'; verdict must be 'proceed' or 'revise'. Use 'proceed' when "
                "the trusted receipt shows zero regret for the candidate bid."
            ),
            _tool(
                "evaluate_vickrey",
                "Evaluate a known-opponent second-price bid.",
                {"value": {"type": "integer"}, "other_bids": {"type": "array", "items": {"type": "integer"}}, "candidate_bid": {"type": "integer"}},
                ["value", "other_bids", "candidate_bid"],
                [{"arguments": auction_args, "result": auction_result}],
            ),
            auction_args,
            auction_result,
            {"mechanism": "vickrey", "recommended_bid": 8, "own_utility": 1, "regret": 0, "verdict": "proceed"},
        ),
        _mission(
            "SYSTEM-EVIDENCE-001",
            "evidence_tool_revision_critique",
            (
                "The archive gives count 12 for claim rate_is_60_percent but no denominator. "
                "Select the relevant available tool and propose a draft. Then, as critic, "
                "return exactly decision, reason_code, and requested_next_field. decision "
                "must be 'supported' or 'abstain'; reason_code must be "
                "'missing_denominator', 'complete_rate_evidence', or 'numerator_missing'; "
                "requested_next_field must be 'denominator', 'count', or 'claim'."
            ),
            _tool(
                "check_evidence_support",
                "Check whether a count supports a rate claim.",
                {"claim": {"type": "string"}, "count": {"type": "integer"}, "denominator": {"type": ["integer", "null"]}},
                ["claim", "count", "denominator"],
                [{"arguments": evidence_args, "result": evidence_result}],
            ),
            evidence_args,
            evidence_result,
            {"decision": "abstain", "reason_code": "missing_denominator", "requested_next_field": "denominator"},
        ),
    ]


def draft_definition() -> dict[str, Any]:
    """Return a fresh draft.  A runner must reject it until witnessed."""
    capability = _science_tasks() + _code_tasks() + _tool_tasks() + _strategic_tasks()
    missions = _system_missions()
    assert len(capability) == 18
    assert sum(task["resource"]["max_model_calls"] for task in capability) == 23
    assert len(missions) == 3
    assert sum(task["resource"]["max_model_calls"] for task in missions) == 6
    return deepcopy({
        "schema_version": "stable-benchmark-definition/v1",
        "suite_id": SUITE_ID,
        "release": RELEASE,
        "description": "Small fixed public regression canary for model, system, and runtime progress on one Spark.",
        "baseline_status": "not_started",
        "historical_comparability": {
            "comparable": False,
            "reason": "fresh fixtures and contracts; historical development runs are archival predecessors only",
        },
        "freeze": {
            "status": "draft",
            "published_at": None,
            "review_at": REVIEW_AT,
            "expiry_action": "review_required",
            "witness": None,
        },
        "panels": [
            {
                "id": "model-capability-v1",
                "role": "stable_core",
                "layer": "model",
                "independent_units": 18,
                "max_model_calls_per_arm": 23,
                "task_ids": [task["id"] for task in capability],
            },
            {
                "id": "actor-tool-critic-micro-v1",
                "role": "stable_core",
                "layer": "system_harness",
                "independent_units": 3,
                "max_model_calls_per_arm": 6,
                "task_ids": [task["id"] for task in missions],
            },
        ],
        "tasks": capability + missions,
        "resource_envelope": {
            "max_model_calls_per_arm": 29,
            "max_model_calls_paired": 58,
            "max_output_tokens_per_arm": 25088,
            "max_episode_runtime_s_per_arm": 1575,
            "max_supervised_window_s": 7200,
            "paid_api_cost_usd": 0,
            "execution": "serial_one_spark",
        },
        "reporting": {
            "no_omnibus_score": True,
            "descriptive_family_counts": {
                "science_evidence": 4,
                "functional_code_repair": 4,
                "deterministic_tool_use": 4,
                "system_harness": 3,
            },
            "strategic_mechanism_counts": {
                "public_goods": 2,
                "vickrey_auction": 2,
                "cournot": 1,
                "proper_scoring_reporting": 1,
            },
            "family_count_interpretation": "binary_objective_completion_descriptive_canary_only",
            "strategic_metrics": ["valid_action", "own_utility", "joint_utility", "own_utility_regret"],
            "strategic_grouping": "mechanism",
            "strategic_regret_aggregation": "within_mechanism_only",
            "system_claim_scope": "actor-tool-critic micro-workflows; not whole-orchestrator or production-funnel success",
            "independent_unit": "task_or_episode",
            "uncertainty": "paired_cluster_bootstrap_and_discordant_counts_descriptive_small_n",
            "promotion_from_small_n": "never_automatic",
        },
        "external_rotations": {
            "included_in_release": False,
            "required_before_adoption": ["license_check", "version_pin", "oracle_replay", "arm64_resource_pilot"],
        },
    })


__all__ = ["RELEASE", "REVIEW_AT", "SUITE_ID", "draft_definition"]
