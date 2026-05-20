#!/usr/bin/env python3
"""Unit tests for experiments/exp001_repeated_pd/strategies.py.

For each fixed strategy, runs the first 5 rounds against a fixed
opponent sequence and asserts the produced own-action sequence. Tests
both the pure ``History -> {'C','D'}`` decision function and the
GRA-style agent wrapper (which maintains internal history via
``observe(own, opp)``).

Run standalone:
    python3 tests/test_strategies.py
or under pytest:
    pytest tests/test_strategies.py
"""
import sys
import unittest
from pathlib import Path
from typing import Callable, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from experiments.exp001_repeated_pd import strategies  # noqa: E402
from experiments.exp001_repeated_pd.strategies import (  # noqa: E402
    C,
    D,
    ConstantCAgent,
    ConstantDAgent,
    LatchAgent,
    MirrorAgent,
    decide_constant_c,
    decide_constant_d,
    decide_latch,
    decide_mirror,
)

DecideFn = Callable[[List], str]


def _simulate_pure(decide: DecideFn, opp_seq: List[str]) -> List[str]:
    """Run ``decide`` for ``len(opp_seq)`` rounds; return the own-actions."""
    history: List = []
    own_seq: List[str] = []
    for opp in opp_seq:
        own = decide(history)
        own_seq.append(own)
        history.append((own, opp))
    return own_seq


def _simulate_agent(agent, opp_seq: List[str]) -> List[str]:
    """Drive a GRA agent through ``opp_seq``; return the own-actions."""
    int_to_str = {v: k for k, v in strategies.ACTION_INT.items()}
    obs = {"legal_actions": [0, 1], "state_string": "test", "prompt": ""}
    own_seq: List[str] = []
    for opp in opp_seq:
        result = agent.compute_action(obs)
        own_action_str = int_to_str[result["action"]]
        own_seq.append(own_action_str)
        agent.observe(own_action_str, opp)
    return own_seq


class TestMirror(unittest.TestCase):
    """Round 1 cooperates; round n>1 echoes opponent's previous move."""

    OPP = [C, D, C, D, C]
    EXPECTED = [C, C, D, C, D]

    def test_pure(self):
        self.assertEqual(_simulate_pure(decide_mirror, self.OPP), self.EXPECTED)

    def test_agent(self):
        self.assertEqual(_simulate_agent(MirrorAgent(), self.OPP), self.EXPECTED)


class TestLatch(unittest.TestCase):
    """Cooperates until opponent first defects; then defects forever."""

    OPP = [C, C, D, C, C]
    EXPECTED = [C, C, C, D, D]

    def test_pure(self):
        self.assertEqual(_simulate_pure(decide_latch, self.OPP), self.EXPECTED)

    def test_agent(self):
        self.assertEqual(_simulate_agent(LatchAgent(), self.OPP), self.EXPECTED)

    def test_latch_persists_after_opp_returns_to_c(self):
        # Even a long tail of opp-C must not unlatch the defection.
        own = _simulate_pure(decide_latch, [C, D, C, C, C, C, C])
        self.assertEqual(own, [C, C, D, D, D, D, D])


class TestConstantC(unittest.TestCase):
    """Always cooperates, including when opponent defects every round."""

    OPP = [D, D, D, D, D]
    EXPECTED = [C, C, C, C, C]

    def test_pure(self):
        self.assertEqual(_simulate_pure(decide_constant_c, self.OPP), self.EXPECTED)

    def test_agent(self):
        self.assertEqual(_simulate_agent(ConstantCAgent(), self.OPP), self.EXPECTED)


class TestConstantD(unittest.TestCase):
    """Always defects, including when opponent cooperates every round."""

    OPP = [C, C, C, C, C]
    EXPECTED = [D, D, D, D, D]

    def test_pure(self):
        self.assertEqual(_simulate_pure(decide_constant_d, self.OPP), self.EXPECTED)

    def test_agent(self):
        self.assertEqual(_simulate_agent(ConstantDAgent(), self.OPP), self.EXPECTED)


class TestFirstMove(unittest.TestCase):
    """All cooperative strategies open with C; the defector opens with D."""

    def test_first_moves(self):
        self.assertEqual(decide_mirror([]), C)
        self.assertEqual(decide_latch([]), C)
        self.assertEqual(decide_constant_c([]), C)
        self.assertEqual(decide_constant_d([]), D)


class TestActionEncoding(unittest.TestCase):
    """OpenSpiel PD convention: 0 == cooperate, 1 == defect."""

    def test_action_int_mapping(self):
        self.assertEqual(strategies.ACTION_INT[C], 0)
        self.assertEqual(strategies.ACTION_INT[D], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
