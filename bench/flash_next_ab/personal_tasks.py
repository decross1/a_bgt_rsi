"""Small, practical tasks for evaluating a warm local Flash candidate.

This is a new usability panel.  It does not reinterpret any historical Flash
grade.  Five source-grounded calculations use deterministic semantic checks;
five repair tasks materialize real files and run bounded tests in a disposable
workspace.  Importing the module has no filesystem, process, or model effects.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import resource
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path, PurePosixPath
from typing import Any

from bench.weekly_upgrade_historical.sandbox import DEFAULT_BWRAP, SandboxUnavailable

PANEL_SCHEMA = "flash-personal-usability-panel/v1"
MAX_TASK_FILE_BYTES = 128 * 1024
MAX_CHECK_OUTPUT_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class RequestPolicy:
    id: str
    enable_thinking: bool
    reasoning_effort: str | None
    temperature: float
    top_p: float
    top_k: int
    max_output_tokens: int
    request_timeout_s: float
    task_deadline_s: float
    max_turns: int

    def inference_policy(self) -> dict[str, Any]:
        policy: dict[str, Any] = {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "enable_thinking": self.enable_thinking,
        }
        if self.reasoning_effort is not None:
            policy["reasoning_effort"] = self.reasoning_effort
        return policy


POLICIES = (
    RequestPolicy(
        id="off",
        enable_thinking=False,
        reasoning_effort=None,
        temperature=0.7,
        top_p=0.8,
        top_k=20,
        max_output_tokens=8_192,
        request_timeout_s=300.0,
        task_deadline_s=900.0,
        max_turns=8,
    ),
    RequestPolicy(
        id="medium",
        enable_thinking=True,
        reasoning_effort="medium",
        temperature=1.0,
        top_p=0.95,
        top_k=20,
        max_output_tokens=16_384,
        request_timeout_s=600.0,
        task_deadline_s=900.0,
        max_turns=10,
    ),
)
_POLICY_BY_ID = {policy.id: policy for policy in POLICIES}


def get_policy(policy_id: str) -> RequestPolicy:
    try:
        return _POLICY_BY_ID[policy_id]
    except KeyError as exc:
        raise ValueError(f"unknown personal-evaluation policy: {policy_id!r}") from exc


@dataclass(frozen=True, slots=True)
class SourceExcerpt:
    id: str
    title: str
    url: str
    excerpt: str


@dataclass(frozen=True, slots=True)
class ScienceTask:
    id: str
    title: str
    question: str
    final_schema: str
    sources: tuple[SourceExcerpt, ...]
    expected_json: str

    @property
    def kind(self) -> str:
        return "science"

    def messages(self) -> tuple[dict[str, str], ...]:
        sources = "\n\n".join(
            f"[{source.id}] {source.title}\nURL: {source.url}\n{source.excerpt}"
            for source in self.sources
        )
        prompt = (
            f"Problem: {self.title}\n\n{self.question}\n\n"
            f"Frozen source notes:\n{sources}\n\n"
            "Show the calculation so a reader can audit it. Use only the source "
            "notes and the numbers in the problem. End with one JSON object inside "
            "literal <final> and </final> tags. Do not put text after </final>.\n"
            f"Final object schema: {self.final_schema}"
        )
        return (
            {
                "role": "system",
                "content": (
                    "You are solving a bounded scientific calculation. Keep exact "
                    "fractions where the requested schema uses strings."
                ),
            },
            {"role": "user", "content": prompt},
        )


@dataclass(frozen=True, slots=True)
class TaskFile:
    path: str
    content: str
    editable: bool = False


@dataclass(frozen=True, slots=True)
class CodingTask:
    id: str
    title: str
    prompt: str
    files: tuple[TaskFile, ...]
    verifier_source: str

    @property
    def kind(self) -> str:
        return "coding"

    @property
    def editable_paths(self) -> tuple[str, ...]:
        return tuple(file.path for file in self.files if file.editable)

    def messages(self) -> tuple[dict[str, str], ...]:
        return (
            {
                "role": "system",
                "content": (
                    "Repair the small repository through the supplied filesystem "
                    "tools. Inspect the files, make the smallest correct edit, and "
                    "run the tests. Do not merely describe a patch."
                ),
            },
            {"role": "user", "content": self.prompt},
        )


SCIENCE_TASKS = (
    ScienceTask(
        id="science-vickrey-deviations",
        title="Second-price auction deviations",
        question=(
            "Two risk-neutral bidders have private values v_A=10 and v_B=7. "
            "The highest bid wins and pays the other bid; utility is value minus "
            "payment for the winner and zero for the loser. Calculate the truthful "
            "outcome and utilities. Then calculate A's utility at bids 6 and 12 "
            "while B bids 7, and B's utility at bid 11 while A bids 10. State "
            "whether truthful bidding is weakly dominant in this mechanism."
        ),
        final_schema=(
            '{"winner": string, "price": integer, "utilities": '
            '{"A": integer, "B": integer}, "deviation_utilities": '
            '{"A_bid_6": integer, "A_bid_12": integer, "B_bid_11": integer}, '
            '"truthful_weakly_dominant": boolean, "source_ids": [string]}'
        ),
        sources=(SourceExcerpt(
            id="vickrey-1961",
            title="Counterspeculation, Auctions, and Competitive Sealed Tenders",
            url="https://doi.org/10.1111/j.1540-6261.1961.tb02789.x",
            excerpt=(
                "In a sealed-bid second-price auction the highest bidder receives "
                "the item and pays the second-highest bid. With private values and "
                "quasilinear utility, truthful bidding is a weakly dominant strategy."
            ),
        ),),
        expected_json=(
            '{"winner":"A","price":7,"utilities":{"A":3,"B":0},'
            '"deviation_utilities":{"A_bid_6":0,"A_bid_12":3,"B_bid_11":-3},'
            '"truthful_weakly_dominant":true,"source_ids":["vickrey-1961"]}'
        ),
    ),
    ScienceTask(
        id="science-asymmetric-mixed-nash",
        title="Mixed equilibrium in an asymmetric 2x2 game",
        question=(
            "The row player's payoffs for (U,L),(U,R),(D,L),(D,R) are 4,0,1,3. "
            "The column player's corresponding payoffs are 1,3,4,0. Find the "
            "unique completely mixed Nash equilibrium. Report the probability of "
            "row choosing U, the probability of column choosing L, and both exact "
            "equilibrium expected payoffs."
        ),
        final_schema=(
            '{"row_U_probability": fraction string, "column_L_probability": '
            'fraction string, "row_expected_payoff": integer, '
            '"column_expected_payoff": integer, "source_ids": [string]}'
        ),
        sources=(SourceExcerpt(
            id="nash-1950",
            title="Equilibrium Points in N-Person Games",
            url="https://doi.org/10.1073/pnas.36.1.48",
            excerpt=(
                "At a completely mixed equilibrium, every pure strategy used with "
                "positive probability is a best response. In a two-strategy game, "
                "each player's mixing probability makes the opponent indifferent."
            ),
        ),),
        expected_json=(
            '{"row_U_probability":"2/3","column_L_probability":"1/2",'
            '"row_expected_payoff":2,"column_expected_payoff":2,'
            '"source_ids":["nash-1950"]}'
        ),
    ),
    ScienceTask(
        id="science-bayes-action",
        title="Bayesian signal update and action choice",
        question=(
            "A hidden state is H with prior 0.4 and L with prior 0.6. A positive "
            "signal has likelihood 0.75 under H and 0.25 under L; a negative signal "
            "has the complementary likelihoods. After each signal, compute P(H|s). "
            "An action pays +5 in H and -4 in L, while abstaining pays 0. Report the "
            "exact expected action payoff and optimal decision after each signal."
        ),
        final_schema=(
            '{"positive": {"posterior_H": fraction string, "action_payoff": '
            'integer, "decision": string}, "negative": {"posterior_H": '
            'fraction string, "action_payoff": fraction string, "decision": '
            'string}, "source_ids": [string]}'
        ),
        sources=(SourceExcerpt(
            id="bayes-1763",
            title="An Essay towards solving a Problem in the Doctrine of Chances",
            url="https://doi.org/10.1098/rstl.1763.0053",
            excerpt=(
                "Bayes' rule updates a prior by multiplying each state's prior "
                "probability by the likelihood of the observed evidence and then "
                "normalizing those products."
            ),
        ),),
        expected_json=(
            '{"positive":{"posterior_H":"2/3","action_payoff":2,'
            '"decision":"act"},"negative":{"posterior_H":"2/11",'
            '"action_payoff":"-26/11","decision":"abstain"},'
            '"source_ids":["bayes-1763"]}'
        ),
    ),
    ScienceTask(
        id="science-replicator-hawk-dove",
        title="Interior stability under replicator dynamics",
        question=(
            "A symmetric population game has strategies H and D and row payoff "
            "matrix [[-1,4],[0,2]], with the population opponent using the same "
            "H frequency x. Under dx/dt=x(1-x)(f_H-f_D), derive the interior fixed "
            "point, evaluate the derivative of the right-hand side there, and "
            "classify the interior point and both boundary points as stable or "
            "unstable from within [0,1]."
        ),
        final_schema=(
            '{"interior_x": fraction string, "interior_derivative": fraction '
            'string, "interior_stability": string, "x_0_stability": string, '
            '"x_1_stability": string, "source_ids": [string]}'
        ),
        sources=(SourceExcerpt(
            id="taylor-jonker-1978",
            title="Evolutionarily Stable Strategies and Game Dynamics",
            url="https://doi.org/10.1016/0025-5564(78)90077-9",
            excerpt=(
                "Replicator dynamics increase a strategy's share when its payoff "
                "exceeds the current population-average payoff. Local stability is "
                "determined by the direction of the vector field around a rest point."
            ),
        ),),
        expected_json=(
            '{"interior_x":"2/3","interior_derivative":"-2/3",'
            '"interior_stability":"stable","x_0_stability":"unstable",'
            '"x_1_stability":"unstable","source_ids":["taylor-jonker-1978"]}'
        ),
    ),
    ScienceTask(
        id="science-shapley-weighted-vote",
        title="Shapley-Shubik power in a weighted voting game",
        question=(
            "Three players A,B,C have weights 2,1,1 and a coalition wins at total "
            "weight at least 3. Enumerate the six arrival orders and use each "
            "player's probability of being pivotal to calculate the Shapley-Shubik "
            "power vector. Also report whether efficiency (the powers sum to one) "
            "and symmetry of B and C hold."
        ),
        final_schema=(
            '{"pivotal_counts": {"A": integer, "B": integer, "C": integer}, '
            '"power": {"A": fraction string, "B": fraction string, "C": '
            'fraction string}, "efficiency": boolean, "B_C_symmetric": boolean, '
            '"source_ids": [string]}'
        ),
        sources=(SourceExcerpt(
            id="shapley-1953",
            title="A Value for n-Person Games",
            url="https://doi.org/10.1515/9781400881970-018",
            excerpt=(
                "The Shapley value averages a player's marginal contribution over "
                "all player orders. In a simple voting game, that contribution is "
                "one exactly when the arriving player first makes the coalition win."
            ),
        ),),
        expected_json=(
            '{"pivotal_counts":{"A":4,"B":1,"C":1},'
            '"power":{"A":"2/3","B":"1/6","C":"1/6"},'
            '"efficiency":true,"B_C_symmetric":true,'
            '"source_ids":["shapley-1953"]}'
        ),
    ),
)


CODING_TASKS = (
    CodingTask(
        id="code-csv-paid-total",
        title="Repair quoted CSV aggregation",
        prompt=(
            "Inspect orders.py and its tests. Repair paid_total(csv_text). It must "
            "parse standard CSV (including quoted commas and CRLF), require exactly "
            "the order_id,status,amount header, sum only rows whose status is exactly "
            "paid using Decimal, return two decimal places, ignore empty physical "
            "lines, and raise ValueError for an invalid paid amount or bad header."
        ),
        files=(
            TaskFile("orders.py", '''from decimal import Decimal\n\n\ndef paid_total(csv_text):\n    total = Decimal("0")\n    for line in csv_text.strip().splitlines()[1:]:\n        order_id, status, amount = line.split(",")\n        if status == "paid":\n            total += Decimal(amount)\n    return str(total)\n''', True),
            TaskFile("test_orders.py", '''import unittest\nfrom orders import paid_total\n\n\nclass OrdersTest(unittest.TestCase):\n    def test_quotes_and_format(self):\n        text = 'order_id,status,amount\\r\\n"A,1",paid,10.20\\r\\nB,void,99\\r\\nC,paid,0.30\\r\\n'\n        self.assertEqual(paid_total(text), "10.50")\n\n    def test_bad_header(self):\n        with self.assertRaises(ValueError):\n            paid_total("id,status,amount\\n1,paid,2")\n\n\nif __name__ == "__main__":\n    unittest.main()\n'''),
        ),
        verifier_source='''import sys\nsys.path.insert(0, sys.argv[1])\nfrom orders import paid_total\nassert paid_total('order_id,status,amount\\n"x,y",paid,1.05\\n2,paid,2.10\\n') == "3.15"\nassert paid_total('order_id,status,amount\\n1,void,not-a-number\\n') == "0.00"\nfor invalid in ("nope", "NaN", "Infinity", "-Infinity"):\n    try:\n        paid_total(f'order_id,status,amount\\n1,paid,{invalid}\\n')\n    except ValueError:\n        pass\n    else:\n        raise AssertionError(f"invalid paid amount accepted: {invalid}")\nprint("verified")\n''',
    ),
    CodingTask(
        id="code-half-open-intervals",
        title="Repair half-open interval merging",
        prompt=(
            "Inspect intervals.py and its tests. merge_half_open must return sorted "
            "merged [start,end) integer pairs without mutating the input. Overlapping "
            "intervals merge, touching intervals such as [1,3) and [3,5) remain "
            "separate, and bool endpoints or intervals with start>=end raise ValueError."
        ),
        files=(
            TaskFile("intervals.py", '''def merge_half_open(intervals):\n    result = []\n    for start, end in sorted(intervals):\n        if result and start <= result[-1][1]:\n            result[-1][1] = max(result[-1][1], end)\n        else:\n            result.append([start, end])\n    return result\n''', True),
            TaskFile("test_intervals.py", '''import unittest\nfrom intervals import merge_half_open\n\n\nclass IntervalTest(unittest.TestCase):\n    def test_overlap_but_not_touch(self):\n        source = [[3, 5], [1, 3], [4, 8]]\n        self.assertEqual(merge_half_open(source), [[1, 3], [3, 8]])\n        self.assertEqual(source, [[3, 5], [1, 3], [4, 8]])\n\n    def test_invalid(self):\n        with self.assertRaises(ValueError):\n            merge_half_open([[2, 2]])\n\n\nif __name__ == "__main__":\n    unittest.main()\n'''),
        ),
        verifier_source='''import sys\nsys.path.insert(0, sys.argv[1])\nfrom intervals import merge_half_open\nassert merge_half_open([[8, 10], [1, 4], [2, 6], [6, 8]]) == [[1, 6], [6, 8], [8, 10]]\nfor bad in ([[True, 2]], [[3, 1]], [[1, 2, 3]], [[1.5, 2]], [[1, 2.5]]):\n    try:\n        merge_half_open(bad)\n    except ValueError:\n        pass\n    else:\n        raise AssertionError(f"accepted {bad!r}")\nprint("verified")\n''',
    ),
    CodingTask(
        id="code-injected-ttl-cache",
        title="Repair deterministic TTL expiry",
        prompt=(
            "Inspect ttl_cache.py and its tests. The cache must use only the injected "
            "clock. set(key,value,ttl_s) rejects bool or nonpositive/nonfinite TTLs. "
            "get returns the value strictly before expiry, returns None at or after "
            "expiry, and removes expired entries."
        ),
        files=(
            TaskFile("ttl_cache.py", '''import time\n\n\nclass TTLCache:\n    def __init__(self, clock):\n        self._clock = clock\n        self._data = {}\n\n    def set(self, key, value, ttl_s):\n        self._data[key] = (value, time.time() + ttl_s)\n\n    def get(self, key):\n        item = self._data.get(key)\n        if item is None:\n            return None\n        value, expires = item\n        if self._clock() > expires:\n            return None\n        return value\n''', True),
            TaskFile("test_ttl_cache.py", '''import unittest\nfrom ttl_cache import TTLCache\n\n\nclass Clock:\n    now = 10.0\n    def __call__(self):\n        return self.now\n\n\nclass CacheTest(unittest.TestCase):\n    def test_exact_expiry(self):\n        clock = Clock()\n        cache = TTLCache(clock)\n        cache.set("a", 7, 2.0)\n        self.assertEqual(cache.get("a"), 7)\n        clock.now = 12.0\n        self.assertIsNone(cache.get("a"))\n        self.assertNotIn("a", cache._data)\n\n\nif __name__ == "__main__":\n    unittest.main()\n'''),
        ),
        verifier_source='''import math, sys\nsys.path.insert(0, sys.argv[1])\nfrom ttl_cache import TTLCache\n+class Clock:\n    value = 0.0\n    def __call__(self): return self.value\nc = Clock(); cache = TTLCache(c); cache.set("k", "v", 0.5)\nc.value = 0.499; assert cache.get("k") == "v"\nc.value = 0.5; assert cache.get("k") is None and "k" not in cache._data\nfor bad in (True, 0, -1, float("inf"), float("nan")):\n    try: cache.set("x", 1, bad)\n    except ValueError: pass\n    else: raise AssertionError(f"accepted ttl {bad!r}")\nprint("verified")\n'''.replace("\n+", "\n"),
    ),
    CodingTask(
        id="code-jsonl-metrics",
        title="Repair robust JSONL metrics",
        prompt=(
            "Inspect jsonl_metrics.py and its tests. summarize(text) must examine each "
            "nonblank line independently. A valid row is a JSON object with a finite, "
            "nonnegative numeric latency_ms that is not bool. Return valid, invalid, "
            "and mean_latency_ms rounded to three decimals (None when no row is valid). "
            "Malformed rows count invalid and do not abort later rows."
        ),
        files=(
            TaskFile("jsonl_metrics.py", '''import json\n\n\ndef summarize(text):\n    rows = [json.loads(line) for line in text.splitlines() if line.strip()]\n    values = [row["latency_ms"] for row in rows]\n    return {"valid": len(values), "invalid": 0, "mean_latency_ms": sum(values) / len(values)}\n''', True),
            TaskFile("test_jsonl_metrics.py", '''import unittest\nfrom jsonl_metrics import summarize\n\n\nclass MetricsTest(unittest.TestCase):\n    def test_mixed_rows(self):\n        text = '{"latency_ms": 1.1114}\\nnot json\\n{"latency_ms": 2.2222}\\n{"x": 3}\\n'\n        self.assertEqual(summarize(text), {"valid": 2, "invalid": 2, "mean_latency_ms": 1.667})\n\n    def test_empty(self):\n        self.assertEqual(summarize("\\n"), {"valid": 0, "invalid": 0, "mean_latency_ms": None})\n\n\nif __name__ == "__main__":\n    unittest.main()\n'''),
        ),
        verifier_source='''import sys\nsys.path.insert(0, sys.argv[1])\nfrom jsonl_metrics import summarize\ntext = '{"latency_ms": true}\\n{"latency_ms": -1}\\n{"latency_ms": 0}\\n{"latency_ms": 2.0}\\n{bad}\\n'\nassert summarize(text) == {"valid": 2, "invalid": 3, "mean_latency_ms": 1.0}\nassert summarize('{"latency_ms": NaN}\\n') == {"valid": 0, "invalid": 1, "mean_latency_ms": None}\nprint("verified")\n''',
    ),
    CodingTask(
        id="code-mixed-payoffs",
        title="Repair asymmetric mixed-strategy payoffs",
        prompt=(
            "Inspect payoff.py and its tests. expected_payoffs(row_strategy, "
            "column_strategy, row_payoffs, column_payoffs) handles a 2x2 bimatrix. "
            "Validate that each strategy contains two finite, non-bool probabilities "
            "in [0,1] summing to one within 1e-9, and that both payoff matrices are "
            "finite numeric 2x2 matrices. Return (row_expected,column_expected) using "
            "the same row i and column j for both matrices."
        ),
        files=(
            TaskFile("payoff.py", '''def expected_payoffs(row_strategy, column_strategy, row_payoffs, column_payoffs):\n    row_total = 0.0\n    column_total = 0.0\n    for i in range(2):\n        for j in range(2):\n            probability = row_strategy[i] * column_strategy[j]\n            row_total += probability * row_payoffs[j][i]\n            column_total += probability * column_payoffs[i][j]\n    return row_total, column_total\n''', True),
            TaskFile("test_payoff.py", '''import unittest\nfrom payoff import expected_payoffs\n\n\nclass PayoffTest(unittest.TestCase):\n    def test_asymmetric_matrix(self):\n        got = expected_payoffs([0.25, 0.75], [0.6, 0.4], [[4, 0], [1, 3]], [[1, 3], [4, 0]])\n        self.assertAlmostEqual(got[0], 1.95)\n        self.assertAlmostEqual(got[1], 2.25)\n\n    def test_bad_strategy(self):\n        with self.assertRaises(ValueError):\n            expected_payoffs([0.2, 0.2], [0.5, 0.5], [[1, 2], [3, 4]], [[1, 2], [3, 4]])\n\n\nif __name__ == "__main__":\n    unittest.main()\n'''),
        ),
        verifier_source='''import sys\nsys.path.insert(0, sys.argv[1])\nfrom payoff import expected_payoffs\nr, c = expected_payoffs([1, 0], [0, 1], [[10, 20], [30, 40]], [[-1, -2], [-3, -4]])\nassert r == 20 and c == -2\nr, c = expected_payoffs([0.5, 0.5], [0.5, 0.5], [[0, 2], [4, 8]], [[1, 3], [5, 7]])\nassert r == 3.5 and c == 4.0\nvalid = [[1, 2], [3, 4]]\nfor strategy in ([True, 0], [float("nan"), 0], [0.1, 0.8]):\n    try: expected_payoffs(strategy, [0.5, 0.5], valid, valid)\n    except ValueError: pass\n    else: raise AssertionError(f"accepted {strategy!r}")\nfor row_matrix, column_matrix in (([[1, 2, 3], [4, 5, 6]], valid), ([[True, 2], [3, 4]], valid), ([[float("nan"), 2], [3, 4]], valid), (valid, [[1, 2], [3, float("inf")]])):\n    try: expected_payoffs([0.5, 0.5], [0.5, 0.5], row_matrix, column_matrix)\n    except ValueError: pass\n    else: raise AssertionError(f"accepted matrices {row_matrix!r}, {column_matrix!r}")\nprint("verified")\n''',
    ),
)

TASKS = SCIENCE_TASKS + CODING_TASKS
_TASK_BY_ID = {task.id: task for task in TASKS}
if len(_TASK_BY_ID) != 10 or len(SCIENCE_TASKS) != 5 or len(CODING_TASKS) != 5:
    raise AssertionError("personal usability panel must remain exactly five plus five")


def get_task(task_id: str) -> ScienceTask | CodingTask:
    try:
        return _TASK_BY_ID[task_id]
    except KeyError as exc:
        raise ValueError(f"unknown personal-evaluation task: {task_id!r}") from exc


def task_manifest() -> dict[str, Any]:
    """Return the public, answer-free task and request plan."""
    policies = [
        {
            "id": policy.id,
            "enable_thinking": policy.enable_thinking,
            "reasoning_effort": policy.reasoning_effort,
            "temperature": policy.temperature,
            "top_p": policy.top_p,
            "top_k": policy.top_k,
            "max_output_tokens": policy.max_output_tokens,
            "request_timeout_s": policy.request_timeout_s,
            "task_deadline_s": policy.task_deadline_s,
            "max_turns": policy.max_turns,
        }
        for policy in POLICIES
    ]
    tasks: list[dict[str, Any]] = []
    for task in TASKS:
        row: dict[str, Any] = {
            "id": task.id,
            "title": task.title,
            "kind": task.kind,
            "policy_ids": [policy.id for policy in POLICIES],
            "messages": list(task.messages()),
        }
        if isinstance(task, ScienceTask):
            row["source_ids"] = [source.id for source in task.sources]
            row["grader"] = "exact-calculation/v1"
        else:
            row["files"] = [
                {"path": file.path, "editable": file.editable}
                for file in task.files
            ]
            row["grader"] = "out-of-process-semantic-check/v1"
        tasks.append(row)
    document = {"schema": PANEL_SCHEMA, "policies": policies, "tasks": tasks}
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    document["manifest_sha256"] = hashlib.sha256(encoded).hexdigest()
    return document


def _strict_json_object(raw: str) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        obj: dict[str, Any] = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("duplicate JSON key")
            obj[key] = value
        return obj

    value = json.loads(
        raw,
        object_pairs_hook=unique,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"non-finite JSON constant: {value}")
        ),
    )
    if not isinstance(value, dict):
        raise TypeError("final value is not an object")
    return value


def _tagged_final(text: str) -> dict[str, Any] | None:
    start = text.rfind("<final>")
    end = text.rfind("</final>")
    if start < 0 or end < start or text[end + len("</final>"):].strip():
        return None
    if text.count("<final>") != 1 or text.count("</final>") != 1:
        return None
    return _strict_json_object(text[start + len("<final>"):end].strip())


def _json_objects(text: str) -> Iterable[dict[str, Any]]:
    """Yield balanced JSON objects from prose, respecting quoted braces."""
    starts: list[int] = []
    depth = 0
    in_string = False
    escaped = False
    for index, character in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            if depth == 0:
                starts.append(index)
            depth += 1
        elif character == "}" and depth:
            depth -= 1
            if depth == 0:
                start = starts.pop()
                try:
                    yield _strict_json_object(text[start:index + 1])
                except (ValueError, TypeError, json.JSONDecodeError):
                    continue


def _same_schema(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and set(actual) == set(expected)
            and all(_same_schema(actual[key], value) for key, value in expected.items())
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(_same_schema(a, e) for a, e in zip(actual, expected, strict=True))
        )
    return type(actual) is type(expected)


def _fraction(value: Any) -> Fraction | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, float) and math.isfinite(value):
        return Fraction(str(value))
    if isinstance(value, str):
        try:
            return Fraction(value.strip())
        except (ValueError, ZeroDivisionError):
            return None
    return None


def _semantically_equal(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and set(actual) == set(expected)
            and all(_semantically_equal(actual[key], value) for key, value in expected.items())
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(_semantically_equal(a, e) for a, e in zip(actual, expected, strict=True))
        )
    if isinstance(expected, bool):
        return actual is expected
    if isinstance(expected, (int, float)) or (
        isinstance(expected, str) and _fraction(expected) is not None
        and ("/" in expected or expected.lstrip("-").isdigit())
    ):
        left, right = _fraction(actual), _fraction(expected)
        return left is not None and right is not None and left == right
    return isinstance(actual, str) and actual.strip().casefold() == str(expected).casefold()


def grade_science(task_id: str, final_text: str | None) -> dict[str, Any]:
    """Grade answer semantics separately from its presentation contract."""
    task = get_task(task_id)
    if not isinstance(task, ScienceTask):
        raise TypeError("science grader received a coding task")
    if final_text is None or not final_text.strip():
        return {
            "task_id": task_id,
            "passed": False,
            "classification": "no_final",
            "contract_ok": False,
            "semantic_ok": False,
        }
    expected = _strict_json_object(task.expected_json)
    canonical: dict[str, Any] | None = None
    try:
        canonical = _tagged_final(final_text)
    except (ValueError, TypeError, json.JSONDecodeError):
        canonical = None
    if canonical is not None:
        semantic = _semantically_equal(canonical, expected)
        schema = _same_schema(canonical, expected)
        if semantic and schema:
            return {
                "task_id": task_id,
                "passed": True,
                "classification": "passed",
                "contract_ok": True,
                "semantic_ok": True,
            }
        if semantic:
            return {
                "task_id": task_id,
                "passed": False,
                "classification": "representation_only_failure",
                "contract_ok": False,
                "semantic_ok": True,
            }
        return {
            "task_id": task_id,
            "passed": False,
            "classification": "wrong_semantics",
            "contract_ok": schema,
            "semantic_ok": False,
        }
    for candidate in reversed(tuple(_json_objects(final_text))):
        if _semantically_equal(candidate, expected):
            return {
                "task_id": task_id,
                "passed": False,
                "classification": "representation_only_failure",
                "contract_ok": False,
                "semantic_ok": True,
            }
    return {
        "task_id": task_id,
        "passed": False,
        "classification": "wrong_semantics",
        "contract_ok": False,
        "semantic_ok": False,
    }


@dataclass(frozen=True, slots=True)
class SandboxPlan:
    task_id: str
    root: Path
    workspace: Path
    control: Path
    declared_paths: tuple[str, ...]
    editable_paths: tuple[str, ...]
    visible_test_argv: tuple[str, ...]
    verifier_argv: tuple[str, ...]


def _safe_relative(path: str) -> str:
    if not isinstance(path, str) or not path or "\\" in path:
        raise ValueError("task path must be a nonempty POSIX relative path")
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or any(part in ("", ".", "..") for part in parsed.parts):
        raise ValueError("task path escapes its workspace")
    return str(parsed)


def materialize_coding_task(task_id: str, root: str | Path) -> SandboxPlan:
    """Create a new task workspace without deleting or overwriting any path."""
    task = get_task(task_id)
    if not isinstance(task, CodingTask):
        raise TypeError("coding materializer received a science task")
    task_root = Path(root)
    if task_root.exists():
        if not task_root.is_dir() or any(task_root.iterdir()):
            raise ValueError("task root must be absent or an empty directory")
    else:
        task_root.mkdir(mode=0o700, parents=True)
    task_root = task_root.resolve(strict=True)
    workspace = task_root / "workspace"
    control = task_root / "control"
    # The model-facing parent remains private. Bubblewrap remaps these two
    # directories read-only under an unprivileged uid for every execution.
    workspace.mkdir(mode=0o755)
    control.mkdir(mode=0o755)
    declared: list[str] = []
    for file in task.files:
        relative = _safe_relative(file.path)
        raw = file.content.encode()
        if not raw or len(raw) > MAX_TASK_FILE_BYTES:
            raise ValueError("task file is empty or exceeds its byte ceiling")
        destination = workspace / relative
        destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        try:
            os.write(descriptor, raw)
        finally:
            os.close(descriptor)
        declared.append(relative)
    verifier = control / "verify.py"
    verifier.write_text(task.verifier_source, encoding="utf-8")
    verifier.chmod(0o444)
    return SandboxPlan(
        task_id=task.id,
        root=task_root,
        workspace=workspace,
        control=control,
        declared_paths=tuple(declared),
        editable_paths=task.editable_paths,
        visible_test_argv=(
            str(Path(sys.executable).resolve()), "-m", "unittest", "-q",
        ),
        verifier_argv=(
            str(Path(sys.executable).resolve()), "-I", "-c",
            (
                "import sys;exec(compile(sys.stdin.buffer.read(),"
                "'<hidden-verifier>','exec'),{'__name__':'__main__'})"
            ),
            "/workspace",
        ),
    )


def _limit_child(timeout_s: float) -> Callable[[], None]:
    def apply() -> None:
        cpu = max(1, math.ceil(timeout_s))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
        resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
        resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    return apply


def _bounded_process(
    argv: tuple[str, ...],
    *,
    cwd: Path,
    timeout_s: float,
    stdin_bytes: bytes | None = None,
) -> dict[str, Any]:
    if (
        isinstance(timeout_s, bool)
        or not isinstance(timeout_s, (int, float))
        or not math.isfinite(timeout_s)
        or not 0.1 <= timeout_s <= 60.0
    ):
        raise ValueError("check timeout must be finite and in 0.1..60 seconds")
    bwrap = shutil.which(DEFAULT_BWRAP)
    python = Path(sys.executable).resolve()
    if bwrap is None or not Path(bwrap).is_file():
        raise SandboxUnavailable("bubblewrap is unavailable")
    if not python.is_file() or not Path("/usr").is_dir() or not Path("/lib").is_dir():
        raise SandboxUnavailable("minimal Python sandbox runtime is unavailable")
    command = [
        bwrap,
        "--die-with-parent",
        "--unshare-all",
        "--cap-drop", "ALL",
        "--uid", "65534",
        "--gid", "65534",
        "--clearenv",
        "--ro-bind", "/usr", "/usr",
        "--ro-bind", "/lib", "/lib",
    ]
    if Path("/lib64").is_dir():
        command += ["--ro-bind", "/lib64", "/lib64"]
    command += [
        "--ro-bind", str(cwd), "/workspace",
    ]
    command += [
        "--proc", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
        "--dir", "/tmp/home",
        "--chdir", "/workspace",
        "--setenv", "HOME", "/tmp/home",
        "--setenv", "PATH", "/usr/bin",
        "--setenv", "LANG", "C.UTF-8",
        "--setenv", "PYTHONHASHSEED", "0",
        "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
        "--setenv", "PYTHONNOUSERSITE", "1",
        "--", *argv,
    ]
    started = time.monotonic()
    with tempfile.TemporaryFile(dir=cwd.parent) as stdout_file, tempfile.TemporaryFile(
        dir=cwd.parent
    ) as stderr_file:
        try:
            process = subprocess.Popen(
                command,
                cwd=cwd.parent,
                env={
                    "PATH": os.environ.get("PATH", ""),
                    "PYTHONHASHSEED": "0",
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                stdin=subprocess.PIPE if stdin_bytes is not None else subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                start_new_session=True,
                preexec_fn=_limit_child(float(timeout_s)),  # noqa: PLW1509
            )
        except OSError as exc:
            raise SandboxUnavailable("cannot start bubblewrap task sandbox") from exc
        timed_out = False
        try:
            if stdin_bytes is None:
                return_code = process.wait(timeout=float(timeout_s))
            else:
                process.communicate(input=stdin_bytes, timeout=float(timeout_s))
                return_code = process.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            if stdin_bytes is None:
                return_code = process.wait(timeout=5)
            else:
                process.communicate(timeout=5)
                return_code = process.returncode
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read(MAX_CHECK_OUTPUT_BYTES + 1)
        stderr = stderr_file.read(MAX_CHECK_OUTPUT_BYTES + 1)
    truncated = len(stdout) > MAX_CHECK_OUTPUT_BYTES or len(stderr) > MAX_CHECK_OUTPUT_BYTES
    sandbox_error = return_code != 0 and stderr.startswith(b"bwrap:")
    return {
        "return_code": return_code,
        "timed_out": timed_out,
        "sandbox_error": sandbox_error,
        "output_truncated": truncated,
        "stdout": stdout[:MAX_CHECK_OUTPUT_BYTES].decode("utf-8", errors="replace"),
        "stderr": stderr[:MAX_CHECK_OUTPUT_BYTES].decode("utf-8", errors="replace"),
        "elapsed_s": max(0.0, time.monotonic() - started),
    }


def run_coding_check(plan: SandboxPlan, *, timeout_s: float = 10.0) -> dict[str, Any]:
    """Run the hidden semantic verifier using only its fixed argv."""
    task = get_task(plan.task_id)
    if not isinstance(task, CodingTask):
        raise TypeError("coding checker received a science task")
    try:
        result = _bounded_process(
            plan.verifier_argv,
            cwd=plan.workspace,
            timeout_s=timeout_s,
            stdin_bytes=task.verifier_source.encode(),
        )
    except SandboxUnavailable as exc:
        return {
            "task_id": plan.task_id,
            "passed": False,
            "classification": "runner_error",
            "return_code": None,
            "timed_out": False,
            "sandbox_error": True,
            "output_truncated": False,
            "stdout": "",
            "stderr": str(exc),
            "elapsed_s": 0.0,
        }
    if result["sandbox_error"]:
        classification = "runner_error"
    elif result["timed_out"]:
        classification = "exhausted"
    elif result["return_code"] == 0 and not result["output_truncated"]:
        classification = "passed"
    elif result["output_truncated"]:
        classification = "runner_error"
    else:
        classification = "wrong_semantics"
    return {
        "task_id": plan.task_id,
        "passed": classification == "passed",
        "classification": classification,
        **result,
    }


FILESYSTEM_TOOLS: tuple[dict[str, Any], ...] = (
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List the files available in the bounded task workspace.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read one declared UTF-8 task file.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Replace one editable UTF-8 task file with complete content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": "Run the task's fixed visible unit-test command.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
)


class SandboxTools:
    """Exact tool surface for one materialized coding task."""

    def __init__(self, plan: SandboxPlan, *, test_timeout_s: float = 10.0):
        self.plan = plan
        self.test_timeout_s = test_timeout_s
        self.events: list[dict[str, Any]] = []

    def _record(self, name: str, path: str | None, status: str) -> None:
        self.events.append({
            "index": len(self.events), "name": name, "path": path, "status": status,
        })

    def _path(self, raw: Any, *, editable: bool = False) -> tuple[str, Path]:
        relative = _safe_relative(raw)
        allowed = self.plan.editable_paths if editable else self.plan.declared_paths
        if relative not in allowed:
            raise ValueError("file is outside the declared tool scope")
        return relative, self.plan.workspace / relative

    def _read(self, raw: Any) -> dict[str, Any]:
        relative, path = self._path(raw)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(path, flags)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_TASK_FILE_BYTES:
                raise ValueError("task file is not a bounded regular file")
            data = os.read(descriptor, MAX_TASK_FILE_BYTES + 1)
            if len(data) != info.st_size:
                raise ValueError("task file changed during read")
        finally:
            os.close(descriptor)
        return {"path": relative, "content": data.decode("utf-8", errors="strict")}

    def _write(self, raw_path: Any, content: Any) -> dict[str, Any]:
        relative, path = self._path(raw_path, editable=True)
        if not isinstance(content, str):
            raise TypeError("file content must be text")
        encoded = content.encode()
        if not encoded or len(encoded) > MAX_TASK_FILE_BYTES:
            raise ValueError("replacement file is empty or exceeds its byte ceiling")
        parent = path.parent
        with tempfile.NamedTemporaryFile(dir=parent, delete=False) as temporary:
            temporary.write(encoded)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        temporary_path.chmod(0o644)
        os.replace(temporary_path, path)
        return {"path": relative, "bytes": len(encoded), "sha256": hashlib.sha256(encoded).hexdigest()}

    def __call__(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            raise TypeError("tool arguments must be an object")
        path = arguments.get("path") if isinstance(arguments.get("path"), str) else None
        try:
            if name == "list_files" and not arguments:
                result = {
                    "files": [
                        {"path": item, "editable": item in self.plan.editable_paths}
                        for item in self.plan.declared_paths
                    ]
                }
            elif name == "read_file" and set(arguments) == {"path"}:
                result = self._read(arguments["path"])
            elif name == "write_file" and set(arguments) == {"path", "content"}:
                result = self._write(arguments["path"], arguments["content"])
            elif name == "run_tests" and not arguments:
                result = _bounded_process(
                    self.plan.visible_test_argv,
                    cwd=self.plan.workspace,
                    timeout_s=self.test_timeout_s,
                )
            else:
                raise ValueError("unknown tool or argument shape")
        except Exception:
            self._record(name, path, "error")
            raise
        self._record(name, path, "ok")
        return result

    def receipt(self) -> dict[str, Any]:
        return {
            "events": list(self.events),
            "interventions": len(self.events),
            "reads": sum(event["name"] == "read_file" for event in self.events),
            "writes": sum(event["name"] == "write_file" for event in self.events),
            "test_runs": sum(event["name"] == "run_tests" for event in self.events),
        }


def summarize_attempts(attempts: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate the panel's practical usability axes without changing old grades."""
    rows = list(attempts)
    allowed = {
        "passed", "representation_only_failure", "wrong_semantics", "no_final",
        "transport_error", "parser_error", "exhausted", "runner_error",
        "repetition_aborted",
    }
    for row in rows:
        if row.get("classification") not in allowed:
            raise ValueError("attempt has an unknown classification")
        if isinstance(row.get("elapsed_s", 0), bool) or not isinstance(
            row.get("elapsed_s", 0), (int, float)
        ) or not math.isfinite(float(row.get("elapsed_s", 0))) or row.get("elapsed_s", 0) < 0:
            raise ValueError("attempt elapsed time is invalid")
        if isinstance(row.get("interventions", 0), bool) or not isinstance(
            row.get("interventions", 0), int
        ) or row.get("interventions", 0) < 0:
            raise ValueError("attempt intervention count is invalid")
    counts = {classification: 0 for classification in sorted(allowed)}
    for row in rows:
        counts[row["classification"]] += 1
    completed = sum(
        row["classification"] not in {
            "transport_error", "parser_error", "no_final", "exhausted",
            "repetition_aborted", "runner_error",
        }
        for row in rows
    )
    return {
        "attempts": len(rows),
        "completed": completed,
        "correct": counts["passed"],
        "completion_rate": completed / len(rows) if rows else 0.0,
        "correctness_rate": counts["passed"] / len(rows) if rows else 0.0,
        "interventions": sum(row.get("interventions", 0) for row in rows),
        "exhausted": counts["exhausted"],
        "elapsed_s": sum(float(row.get("elapsed_s", 0.0)) for row in rows),
        "classifications": counts,
    }
