#!/usr/bin/env python3
"""
Day 9 task -- input/output contract test for workers/critic.py (W2-01,
Day 39 deliverable). Drafted ahead of Track A's implementation; runs
TODAY under MOCK_LLM=1 against a deterministic stub, and against the
real critic once workers/critic.py lands.

What this test pins down:

  * The critic's PUBLIC SIGNATURE is `workers.critic.critique(
        hypothesis_text: str, context: str | dict | None = None
    ) -> dict`.

  * The returned dict MUST carry exactly three required keys:
        critique_text     -- str, non-empty
        flag_decision     -- one of {"flawed", "sound"}
        reasoning_chain   -- list[str], non-empty (the step-by-step
                             argument the critic walked)

  * Optional keys are allowed but not required (e.g. retrieval_context,
    used_tools). Unknown keys must NOT fail the contract -- the test
    only locks the required shape.

  * Behind MOCK_LLM=1, the critic MUST NOT call LOCAL_LLM_BASE_URL /
    localhost:8000 / any HTTP endpoint backed by vLLM. We assert this
    by patching agent_wrapper.wrapper's HTTP clients to raise; if the
    real critic ever leaks past the mock branch the test surfaces it.

  * The critic MUST tolerate context being None / a string / a dict;
    each branch returns a well-formed result.

Run standalone:
    MOCK_LLM=1 python3 tests/test_critic_contract.py
or under pytest:
    MOCK_LLM=1 pytest tests/test_critic_contract.py

If workers/critic.py is absent (pre-Day-39) the tests run against
``_MockCritic`` defined below -- a deterministic stand-in honouring the
same contract. This is the same "scaffold the contract before the real
module exists" pattern used by tests/_orchestrator_contract.py
(Day-3-drafted, exercised on Day 6 when openclaw_runner.py landed).
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


# DAY39-CONTRACT: the critic's signature. Update this comment alongside
# workers/critic.py once the real implementation lands.
CRITIQUE_REQUIRED_KEYS = {"critique_text", "flag_decision", "reasoning_chain"}
FLAG_DECISION_VALUES = {"flawed", "sound"}


def _load_critic():
    """Return (critique_callable, source_tag).

    source_tag ∈ {"real", "mock"}:
      - "real" — workers/critic.py exists and exposes `critique`.
      - "mock" — workers/critic.py is absent; we hand back _MockCritic.

    If workers/critic.py EXISTS but cannot be imported, raise — a broken
    real critic must not silently fall through to the mock (the same rule
    tests/_orchestrator_contract.py applies to OrchestratorClient).
    """
    path = REPO_ROOT / "workers" / "critic.py"
    if not path.exists():
        return _MockCritic().critique, "mock"
    spec = importlib.util.spec_from_file_location("workers.critic", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # let import errors propagate
    if not hasattr(mod, "critique"):
        raise AttributeError(
            "workers/critic.py exists but does not expose a `critique` "
            "callable; the Day-9 contract test cannot proceed."
        )
    return mod.critique, "real"


class _MockCritic:
    """Deterministic stand-in for workers.critic.critique().

    Returns a well-formed CritiqueResult that satisfies the contract.
    The flag_decision is keyed on a marker string in the hypothesis
    (`__SOUND__` ⇒ sound; otherwise flawed) so the eval-scoring test
    in tests/test_critic_eval_scoring.py can drive it deterministically.
    The mock NEVER touches the network.
    """

    def critique(self, hypothesis_text, context=None):
        sound = "__SOUND__" in (hypothesis_text or "")
        flag = "sound" if sound else "flawed"
        reasoning = [
            "step 1: identify the claim",
            "step 2: enumerate the assumptions",
            "step 3: stress-test the strongest assumption",
        ]
        critique_text = (
            f"(mock) hypothesis flagged {flag}; "
            f"context-kind={type(context).__name__}; "
            "the critic would here enumerate specific objections."
        )
        return {
            "critique_text": critique_text,
            "flag_decision": flag,
            "reasoning_chain": reasoning,
        }


# Sample hypothesis that mirrors the fixture shape from
# experiments/fixtures/critic_hypotheses/. Used by the happy-path tests
# below. Not a fixture file -- inline so the contract test is hermetic.
SAMPLE_HYPOTHESIS = (
    "Across our five-opponent iterated Prisoner's Dilemma sweep, runs "
    "that lasted more rounds had higher cooperation rates. We conclude "
    "that longer interaction horizons cause LLM players to cooperate "
    "more, consistent with the folk-theorem prediction."
)


# ──────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────
class CriticContractTest(unittest.TestCase):
    """The contract every workers.critic.critique() must satisfy."""

    @classmethod
    def setUpClass(cls):
        # MOCK_LLM=1 is the canonical Track B environment. Tests that
        # would otherwise hit the real vLLM endpoint short-circuit to
        # the mock branch under this flag.
        os.environ.setdefault("MOCK_LLM", "1")
        cls.critique, cls.source = _load_critic()

    def test_required_keys_present(self):
        result = self.critique(SAMPLE_HYPOTHESIS)
        self.assertIsInstance(result, dict, f"{self.source} critic must return a dict")
        missing = CRITIQUE_REQUIRED_KEYS - result.keys()
        self.assertFalse(
            missing,
            f"{self.source} critic result missing required keys: {sorted(missing)}",
        )

    def test_critique_text_is_non_empty_string(self):
        result = self.critique(SAMPLE_HYPOTHESIS)
        self.assertIsInstance(result["critique_text"], str)
        self.assertTrue(
            result["critique_text"].strip(),
            "critique_text must be a non-empty string",
        )

    def test_flag_decision_is_enum(self):
        result = self.critique(SAMPLE_HYPOTHESIS)
        self.assertIn(
            result["flag_decision"],
            FLAG_DECISION_VALUES,
            f"flag_decision must be one of {sorted(FLAG_DECISION_VALUES)}; "
            f"got {result['flag_decision']!r}",
        )

    def test_reasoning_chain_is_nonempty_list_of_strings(self):
        result = self.critique(SAMPLE_HYPOTHESIS)
        chain = result["reasoning_chain"]
        self.assertIsInstance(chain, list)
        self.assertGreaterEqual(
            len(chain), 1,
            "reasoning_chain must have at least one step",
        )
        for step in chain:
            self.assertIsInstance(step, str)
            self.assertTrue(step.strip(), "reasoning_chain steps must be non-empty")

    def test_context_kinds_tolerated(self):
        """The critic accepts None / str / dict for `context` and still
        returns a well-formed result. This pins the type union the
        Day-39 implementation must support."""
        for kind, ctx in [
            ("none", None),
            ("str", "Day-7 PD: tft=1.00, grim=1.00, all_c=1.00, all_d=0.12."),
            ("dict", {"experiment_id": "exp001_repeated_pd", "round_count": 100}),
        ]:
            with self.subTest(context_kind=kind):
                result = self.critique(SAMPLE_HYPOTHESIS, context=ctx)
                missing = CRITIQUE_REQUIRED_KEYS - result.keys()
                self.assertFalse(
                    missing,
                    f"context-kind {kind!r}: missing required keys {sorted(missing)}",
                )

    def test_short_hypothesis_does_not_crash(self):
        """An unusually short hypothesis must not raise; the critic may
        return a flag_decision of either value but the shape contract
        still holds. The bar here is `clean rejection, not crash` —
        same rule as the worker_contract on unknown task_type."""
        result = self.critique("Short claim about cooperation.")
        self.assertIn(result["flag_decision"], FLAG_DECISION_VALUES)
        self.assertIsInstance(result["critique_text"], str)


class CriticDoesNotCallVllmUnderMockTest(unittest.TestCase):
    """Behind MOCK_LLM=1 the critic must not punch through to the real
    vLLM HTTP endpoint. Two complementary guards:

      1. Patch `agent_wrapper.wrapper.call_sync` / `call_with_tools` to
         raise (the boundary the critic is *expected* to use).
      2. Patch `socket.socket.connect` to raise on ANY TCP connect (the
         catch-all, in case the critic ships its own HTTP client and
         bypasses the wrapper).

    Either guard alone is incomplete; together they nail the no-network
    invariant the Track-B charter demands.
    """

    @classmethod
    def setUpClass(cls):
        os.environ["MOCK_LLM"] = "1"
        cls.critique, cls.source = _load_critic()

    @staticmethod
    def _no_http(*_args, **_kwargs):
        raise AssertionError(
            "critic attempted to call the wrapper under MOCK_LLM=1; "
            "the mock branch is leaking past the guard"
        )

    @staticmethod
    def _no_connect(_self, address, *_a, **_kw):
        raise AssertionError(
            f"critic attempted TCP connect to {address!r} under "
            "MOCK_LLM=1; the mock branch is leaking past the guard"
        )

    def test_no_wrapper_call_under_mock(self):
        # If agent_wrapper.wrapper isn't importable in this environment
        # (e.g. openai missing), the wrapper-level guard is skipped --
        # the socket-level guard in test_no_tcp_connect_under_mock
        # still catches an actual network attempt.
        try:
            wrapper = importlib.import_module("agent_wrapper.wrapper")
        except Exception as exc:
            self.skipTest(f"agent_wrapper.wrapper not importable: {exc!r}")
        with patch.object(wrapper, "call_sync", side_effect=self._no_http), \
             patch.object(wrapper, "call_with_tools", side_effect=self._no_http):
            result = self.critique(SAMPLE_HYPOTHESIS)
            self.assertIn("critique_text", result)

    def test_no_tcp_connect_under_mock(self):
        import socket
        with patch.object(socket.socket, "connect", new=self._no_connect):
            result = self.critique(SAMPLE_HYPOTHESIS)
            self.assertIn("critique_text", result)


class CriticReturnsConsistentShapeAcrossCallsTest(unittest.TestCase):
    """Repeated calls return the same keys. Locks 'no random shape drift'
    -- the contract is a property of the function, not of a single call."""

    @classmethod
    def setUpClass(cls):
        os.environ["MOCK_LLM"] = "1"
        cls.critique, cls.source = _load_critic()

    def test_keys_stable_across_three_calls(self):
        results = [
            self.critique(SAMPLE_HYPOTHESIS),
            self.critique(SAMPLE_HYPOTHESIS, context=None),
            self.critique("__SOUND__ a known-sound hypothesis baseline."),
        ]
        keysets = [set(r.keys()) for r in results]
        # Every call carries at least the required keys; optional keys
        # may legitimately differ run-to-run (e.g. retrieval_context).
        for ks in keysets:
            self.assertTrue(CRITIQUE_REQUIRED_KEYS.issubset(ks))


if __name__ == "__main__":
    unittest.main(verbosity=2)
