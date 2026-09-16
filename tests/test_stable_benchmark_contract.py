from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from bench.stable_benchmark.fixtures import CODE_SANDBOX_CONTRACT
from bench.stable_benchmark.graders import grade_task
from bench.stable_benchmark.manifest import (
    ManifestError,
    load_definition,
    make_draft,
    validate_definition,
)

REPO = Path(__file__).resolve().parents[1]


CODE_GOLD = {
    "CODE-MERGE-001": """def merge_windows(windows):
    rows = []
    for window in windows:
        if len(window) != 2 or window[0] > window[1]:
            raise ValueError("invalid window")
        rows.append([window[0], window[1]])
    rows = sorted(rows)
    merged = []
    for row in rows:
        if not merged or row[0] > merged[-1][1]:
            merged.append([row[0], row[1]])
        elif row[1] > merged[-1][1]:
            merged[-1][1] = row[1]
    return merged""",
    "CODE-WEIGHTED-MEDIAN-001": """def weighted_median(values, weights):
    if len(values) == 0 or len(values) != len(weights):
        raise ValueError("invalid lengths")
    for weight in weights:
        if weight < 0:
            raise ValueError("negative weight")
    total = sum(weights)
    if total <= 0:
        raise ValueError("zero weight")
    cumulative = 0
    for pair in sorted(zip(values, weights)):
        cumulative += pair[1]
        if cumulative * 2 >= total:
            return pair[0]
    raise ValueError("unreachable")""",
    "CODE-DRAWDOWN-001": """def max_drawdown(values):
    if not values:
        raise ValueError("empty")
    for value in values:
        if value < 0:
            raise ValueError("negative")
    peak_value = values[0]
    peak_index = 0
    best_drop = 0
    best_peak = 0
    best_trough = 0
    for index in range(1, len(values)):
        drop = peak_value - values[index]
        if drop > best_drop:
            best_drop = drop
            best_peak = peak_index
            best_trough = index
        if values[index] > peak_value:
            peak_value = values[index]
            peak_index = index
    return {"drop": best_drop, "peak_index": best_peak, "trough_index": best_trough}""",
    "CODE-WATERFALL-001": """def waterfall_payments(claims, cash):
    if cash < 0:
        raise ValueError("negative cash")
    for claim in claims:
        if claim < 0:
            raise ValueError("negative claim")
    remaining = cash
    payments = []
    for claim in claims:
        payment = min(claim, remaining)
        payments.append(payment)
        remaining -= payment
    return {"payments": payments, "residual": remaining}""",
}


# These seven contracts are written independently from ``task["grader"]``.
# They are the prompt-and-tool-derived gold artifacts used to catch a mistaken
# oracle in the source fixture itself, rather than merely proving that a grader
# accepts the expectation it supplied.
TOOL_SYSTEM_GOLD = {
    "TOOL-SINGLE-001": (
        {"row_payoff": 5, "column_payoff": 2},
        [
            {
                "name": "payoff_lookup",
                "arguments": {
                    "game_id": "G-7",
                    "profile": ["cooperate", "defect"],
                },
                "result": {"row_payoff": 5, "column_payoff": 2},
            }
        ],
    ),
    "TOOL-PARALLEL-001": (
        {"decision": "proceed", "citations": ["E-17", "E-22"]},
        [
            {
                "name": "lookup_evidence",
                "arguments": {"doc_id": "E-17"},
                "result": {
                    "doc_id": "E-17",
                    "text": "The reserve price was fixed before bids.",
                },
            },
            {
                "name": "lookup_evidence",
                "arguments": {"doc_id": "E-22"},
                "result": {
                    "doc_id": "E-22",
                    "text": "Bidder values were not disclosed to the seller.",
                },
            },
        ],
    ),
    "TOOL-NOCALL-001": (
        {"status": "final", "code": "S-204"},
        [],
    ),
    "TOOL-DEPENDENT-001": (
        {"score_num": 91, "score_den": 100},
        [
            {
                "name": "lookup_market",
                "arguments": {"market_id": "M-4"},
                "result": {
                    "market_id": "M-4",
                    "forecast_percent": 70,
                    "outcome": 1,
                },
            },
            {
                "name": "brier_score",
                "arguments": {"forecast_percent": 70, "outcome": 1},
                "result": {"score_num": 91, "score_den": 100},
            },
        ],
    ),
    "SYSTEM-PAYOFF-001": (
        {
            "focal_num": 12,
            "focal_den": 1,
            "joint_num": 49,
            "joint_den": 1,
            "decision": "retain",
        },
        [
            {
                "name": "compute_public_goods",
                "arguments": {
                    "endowment": 10,
                    "contributions": [0, 3, 8, 4],
                    "multiplier_num": 8,
                    "multiplier_den": 5,
                    "focal_index": 3,
                },
                "result": {
                    "focal_num": 12,
                    "focal_den": 1,
                    "joint_num": 49,
                    "joint_den": 1,
                },
            }
        ],
    ),
    "SYSTEM-AUCTION-001": (
        {
            "mechanism": "vickrey",
            "recommended_bid": 8,
            "own_utility": 1,
            "regret": 0,
            "verdict": "proceed",
        },
        [
            {
                "name": "evaluate_vickrey",
                "arguments": {
                    "value": 8,
                    "other_bids": [3, 7, 5],
                    "candidate_bid": 8,
                },
                "result": {
                    "own_utility": 1,
                    "efficient_winner": True,
                    "regret": 0,
                },
            }
        ],
    ),
    "SYSTEM-EVIDENCE-001": (
        {
            "decision": "abstain",
            "reason_code": "missing_denominator",
            "requested_next_field": "denominator",
        },
        [
            {
                "name": "check_evidence_support",
                "arguments": {
                    "claim": "rate_is_60_percent",
                    "count": 12,
                    "denominator": None,
                },
                "result": {
                    "supported": False,
                    "reason_code": "missing_denominator",
                },
            }
        ],
    ),
}


def _gold_contracts(tasks: dict[str, dict]) -> dict[str, tuple[dict, list[dict]]]:
    contracts: dict[str, tuple[dict, list[dict]]] = {
        "SCI-MARKOV-001": (
            {
                "stationary_a": 0.6666666666666666,
                "stationary_b": 0.3333333333333333,
                "long_run_reward": 5.0,
            },
            [],
        ),
        "SCI-RCT-001": (
            {"treatment_rate": 0.65, "control_rate": 0.5, "risk_difference": 0.15},
            [],
        ),
        "EVID-SUPPORT-001": (
            {
                "decision": "supported",
                "reason_code": "randomized_observed_rate_higher",
                "citations": ["DOC-A", "DOC-B", "DOC-C"],
            },
            [],
        ),
        "EVID-ABSTAIN-001": (
            {
                "decision": "abstain",
                "reason_code": "missing_denominator",
                "citations": ["DOC-E"],
            },
            [],
        ),
        "GAME-PUBLIC-GOODS-101": ({"action": 0}, []),
        "GAME-PUBLIC-GOODS-211": ({"action": 0}, []),
        "GAME-VICKREY-101": ({"action": 8}, []),
        "GAME-VICKREY-211": ({"action": 5}, []),
        "GAME-COURNOT-307": ({"action": 7}, []),
        "GAME-BRIER-401": ({"action": 65}, []),
    }
    for task_id, source in CODE_GOLD.items():
        contracts[task_id] = ({"source": source}, [])
    contracts.update(deepcopy(TOOL_SYSTEM_GOLD))
    return contracts


def test_release_1_1_full_21_task_gold_contract_preflight():
    draft = make_draft()
    assert draft["release"] == "1.1.0"
    assert draft["suite_id"] == "a-bgt-rsi-stable-1.1.0"
    tasks = {task["id"]: task for task in draft["tasks"]}
    for task_id, task in tasks.items():
        assert (
            task["provenance"]["origin"] == "prospective_contract_correction_2026-09-16"
        )
        assert task["provenance"]["predecessor_task_ids"] == [task_id]
        assert task["provenance"]["predecessor_suite_id"] == "a-bgt-rsi-stable-1.0.0"
        assert task["provenance"]["predecessor_release"] == "1.0.0"
    contracts = _gold_contracts(tasks)
    assert set(contracts) == set(tasks)
    assert len(contracts) == 21
    for task_id, (payload, trace) in contracts.items():
        grade = grade_task(tasks[task_id], payload, tool_trace=trace)
        assert grade.passed, f"{task_id}: {grade.failure_code}: {grade.reason}"


def test_tool_and_system_gold_is_grounded_in_the_public_prompt_and_tools():
    tasks = {task["id"]: task for task in make_draft()["tasks"]}
    prompt_literals = {
        "TOOL-SINGLE-001": (
            "payoff_lookup",
            "G-7",
            "[cooperate, defect]",
            "row_payoff",
            "column_payoff",
        ),
        "TOOL-PARALLEL-001": (
            "lookup_evidence",
            "E-17",
            "E-22",
            '"decision":"proceed"',
        ),
        "TOOL-NOCALL-001": ("Do not call a tool", "status is final", "S-204"),
        "TOOL-DEPENDENT-001": (
            "First call lookup_market for M-4",
            "Then pass its forecast_percent and outcome",
            "brier_score",
        ),
        "SYSTEM-PAYOFF-001": (
            "endowment 10",
            "contributions [0,3,8,4]",
            "multiplier 8/5",
            "focal player index 3",
            "focal_num",
            "joint_num",
        ),
        "SYSTEM-AUCTION-001": (
            "candidate bid 8",
            "valued at 8",
            "other bids [3,7,5]",
            "second-price auction",
            "regret",
            "proceed",
        ),
        "SYSTEM-EVIDENCE-001": (
            "count 12",
            "rate_is_60_percent",
            "no denominator",
            "missing_denominator",
            "requested_next_field",
        ),
    }
    for task_id, literals in prompt_literals.items():
        task = tasks[task_id]
        assert all(literal in task["prompt"] for literal in literals), task_id
        tools = {tool["name"]: tool for tool in task["tools"]}
        _payload, trace = TOOL_SYSTEM_GOLD[task_id]
        for call in trace:
            assert call["name"] in tools
            fixture = {
                json.dumps(row["arguments"], sort_keys=True): row["result"]
                for row in tools[call["name"]]["fixtures"]
            }
            assert (
                fixture[json.dumps(call["arguments"], sort_keys=True)] == call["result"]
            )

    # Independent arithmetic behind the dependent and system receipts.
    assert 100 - (70 - 100) ** 2 // 100 == 91
    contributions = [0, 3, 8, 4]
    public_return = sum(contributions) * 8 // 5
    assert public_return % 4 == 0
    assert 10 - contributions[3] + public_return // 4 == 12
    assert 4 * 10 - sum(contributions) + public_return == 49
    other_bids = [3, 7, 5]
    candidate_utility = 8 - max(other_bids)
    best_utility = max(
        8 - max(other_bids) if bid >= max(other_bids) else 0 for bid in range(13)
    )
    assert candidate_utility == best_utility == 1
    assert best_utility - candidate_utility == 0


def test_release_1_1_valid_alternative_answers_remain_valid():
    tasks = {task["id"]: task for task in make_draft()["tasks"]}
    alternatives = {
        "SCI-MARKOV-001": [
            {
                "stationary_a": 0.6666666667,
                "stationary_b": 0.3333333333,
                "long_run_reward": 5,
            }
        ],
        "SCI-RCT-001": [
            {
                "treatment_rate": 0.6500000001,
                "control_rate": 0.5,
                "risk_difference": 0.15,
            }
        ],
        "EVID-SUPPORT-001": [
            {
                "decision": "supported",
                "reason_code": "randomized_observed_rate_higher",
                "citations": ["DOC-C", "DOC-A", "DOC-B"],
            }
        ],
        "CODE-MERGE-001": [
            {
                "source": """def merge_windows(windows):
    rows = []
    for window in windows:
        if len(window) != 2 or window[0] > window[1]:
            raise ValueError("invalid window")
        rows.append([window[0], window[1]])
    used = set()
    ordered = []
    for count in range(len(rows)):
        best = None
        for index in range(len(rows)):
            if index not in used and (best is None or rows[index] < rows[best]):
                best = index
        used.add(best)
        ordered.append(rows[best])
    merged = []
    for row in ordered:
        if not merged or row[0] > merged[-1][1]:
            merged.append([row[0], row[1]])
        elif row[1] > merged[-1][1]:
            merged[-1][1] = row[1]
    return merged"""
            }
        ],
        "CODE-WEIGHTED-MEDIAN-001": [
            {
                "source": """def weighted_median(values, weights):
    if not values or len(values) != len(weights):
        raise ValueError("invalid lengths")
    for weight in weights:
        if weight < 0:
            raise ValueError("negative weight")
    total = sum(weights)
    if total <= 0:
        raise ValueError("zero weight")
    cumulative = 0
    for value in sorted(set(values)):
        for index in range(len(values)):
            if values[index] == value:
                cumulative += weights[index]
        if cumulative * 2 >= total:
            return value
    raise ValueError("unreachable")"""
            }
        ],
        "CODE-DRAWDOWN-001": [
            {
                "source": """def max_drawdown(values):
    if not isinstance(values, list) or len(values) == 0:
        raise ValueError("invalid values")
    for value in values:
        if not isinstance(value, int) or value < 0:
            raise ValueError("invalid value")
    best_drop = 0
    best_peak = 0
    best_trough = 0
    for peak in range(len(values)):
        for trough in range(peak + 1, len(values)):
            drop = values[peak] - values[trough]
            if drop > best_drop:
                best_drop = drop
                best_peak = peak
                best_trough = trough
    return {"drop": best_drop, "peak_index": best_peak, "trough_index": best_trough}"""
            }
        ],
        "CODE-WATERFALL-001": [
            {
                "source": """def waterfall_payments(claims, cash):
    if any(not isinstance(claim, int) or claim < 0 for claim in claims):
        raise ValueError("invalid claim")
    if not isinstance(cash, int) or cash < 0:
        raise ValueError("invalid cash")
    payments = []
    remaining = cash
    for claim in claims:
        payment = min(claim, remaining)
        payments.append(payment)
        remaining -= payment
    return {"payments": payments, "residual": remaining}"""
            }
        ],
        "GAME-VICKREY-101": [{"action": 7}, {"action": 12}],
        "GAME-VICKREY-211": [{"action": 0}, {"action": 6}],
        "GAME-COURNOT-307": [{"action": 6}],
    }
    for task_id, payloads in alternatives.items():
        for payload in payloads:
            grade = grade_task(tasks[task_id], payload)
            assert grade.passed, f"{task_id}: {payload}: {grade.reason}"

    parallel = tasks["TOOL-PARALLEL-001"]
    reversed_trace = list(reversed(parallel["grader"]["expected_trace"]))
    grade = grade_task(
        parallel,
        deepcopy(parallel["grader"]["expected_final"]),
        tool_trace=reversed_trace,
    )
    assert grade.passed


def test_corrected_evidence_contracts_are_minimal_and_use_bare_ids():
    tasks = {task["id"]: task for task in make_draft()["tasks"]}
    support = tasks["EVID-SUPPORT-001"]
    abstain = tasks["EVID-ABSTAIN-001"]
    assert support["grader"]["expected"]["citations"] == ["DOC-A", "DOC-B", "DOC-C"]
    assert abstain["grader"]["expected"]["citations"] == ["DOC-E"]
    assert "every factual qualifier" in support["prompt"]
    assert "bare document IDs" in support["prompt"]
    assert "bare document IDs" in abstain["prompt"]
    assert "citations (a JSON array of bare document ID strings)" in support["prompt"]
    assert "citations (a JSON array of bare document ID strings)" in abstain["prompt"]

    redundant = grade_task(
        abstain,
        {
            "decision": "abstain",
            "reason_code": "missing_denominator",
            "citations": ["DOC-D", "DOC-E"],
        },
    )
    bracketed = grade_task(
        abstain,
        {
            "decision": "abstain",
            "reason_code": "missing_denominator",
            "citations": ["[DOC-E]"],
        },
    )
    scalar_citation = grade_task(
        abstain,
        {
            "decision": "abstain",
            "reason_code": "missing_denominator",
            "citations": "DOC-E",
        },
    )
    assert not redundant.passed
    assert not bracketed.passed
    assert not scalar_citation.passed


def test_code_tasks_disclose_the_exact_unchanged_sandbox_contract():
    tasks = [task for task in make_draft()["tasks"] if task["mode"] == "code"]
    assert len(tasks) == 4
    for task in tasks:
        assert CODE_SANDBOX_CONTRACT in task["prompt"]
        for literal in (
            "65536 bytes",
            "imports, lambda",
            "ValueError, NotImplementedError",
            "sorted",
            "All attribute access, including method calls",
            "add, append, get, items, keys, startswith, and values",
            "256 MiB",
            "2-second",
            "CPU and wall-clock limits",
            "Encoded arguments",
            "each captured output stream",
            "131072 bytes",
        ):
            assert literal in task["prompt"]

    hidden_sort_style = {
        "source": """def merge_windows(windows):
    rows = []
    for row in windows:
        rows.append([row[0], row[1]])
    rows.sort()
    return rows"""
    }
    hidden_lambda_style = {
        "source": """def weighted_median(values, weights):
    pairs = sorted(zip(values, weights), key=lambda pair: pair[0])
    return pairs[0][0]"""
    }
    hidden_attribute_read_style = {
        "source": '''def merge_windows(windows):
    value = windows.real
    return []'''
    }
    sort_grade = grade_task(
        next(task for task in tasks if task["id"] == "CODE-MERGE-001"),
        hidden_sort_style,
    )
    lambda_grade = grade_task(
        next(task for task in tasks if task["id"] == "CODE-WEIGHTED-MEDIAN-001"),
        hidden_lambda_style,
    )
    attribute_grade = grade_task(
        next(task for task in tasks if task["id"] == "CODE-MERGE-001"),
        hidden_attribute_read_style,
    )
    assert not sort_grade.passed and sort_grade.failure_code == "invalid_output"
    assert not lambda_grade.passed and lambda_grade.failure_code == "invalid_output"
    assert not attribute_grade.passed and attribute_grade.failure_code == "invalid_output"
    assert "safe builtins" in sort_grade.reason
    assert "Lambda" in lambda_grade.reason
    assert "candidate method is forbidden" in attribute_grade.reason


def test_manifest_and_schemas_accept_historical_1_0_and_corrected_1_1():
    historical_path = (
        REPO / "docs/benchmarks/releases/stable-lab-v1/definition.published.json"
    )
    historical = load_definition(historical_path, require_published=True)
    assert (
        historical.raw_sha256
        == "75de9dc0dc324a4559332f88ae6e5ae861ba0d6f683334d85395d082bbaf04df"
    )
    assert historical.document["release"] == "1.0.0"
    assert historical.document["suite_id"] == "a-bgt-rsi-stable-1.0.0"
    corrected = make_draft()
    validate_definition(corrected)

    schema = json.loads(
        (REPO / "bench/stable_benchmark/schemas/definition.schema.json").read_text()
    )
    validator = Draft202012Validator(schema)
    validator.validate(historical.document)
    validator.validate(corrected)
    mismatched = deepcopy(corrected)
    mismatched["suite_id"] = "a-bgt-rsi-stable-1.0.0"
    assert list(validator.iter_errors(mismatched))
    with pytest.raises(ManifestError, match="release, suite"):
        validate_definition(mismatched)
