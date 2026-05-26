"""Day 9 worker: red-team critic agent (W2-01).

Public interface (locked by tests/test_critic_contract.py):

    critique(hypothesis_text: str, context: Optional[str|dict] = None)
        -> {"critique_text": str,
            "flag_decision": "flawed"|"sound",
            "reasoning_chain": List[str]}

The critic is NOT told which hypotheses are flawed. It receives the hypothesis
text (and optional experimental context) and is asked to enumerate substantive
methodological / causal flaws — or to state plainly that the hypothesis is
sound, with no fabricated objections.

Under ``MOCK_LLM=1`` the critic short-circuits to a deterministic stub that
NEVER touches the network. The stub keys ``flag_decision`` on a ``__SOUND__``
marker substring in the hypothesis so the Day-9 eval-scoring test in
``tests/test_critic_eval_scoring.py`` can drive it predictably.

Code budget ~150 lines. The orchestrator-dispatch worker_contract wrapper is
deferred until Day 43 (PD re-run with critic in loop), at which point the
``workers.critic`` module will gain a ``dispatch(payload, log_path,
parent_request_id)`` adapter without changing this public API.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


CRITIC_SYSTEM_PROMPT = (
    "You are a methodological critic for an LLM-driven research apparatus. "
    "You receive a research hypothesis (and optionally the experimental "
    "context that produced it). Identify substantive flaws rigorously: "
    "causal (confounds, reverse causation, ecological fallacy), measurement "
    "(operationalization, construct validity), scope (overgeneralization, "
    "selection), sampling (sample size, regression to mean), methodology "
    "(missing baseline, post-hoc rationalization, circularity), or process "
    "(prompt leakage, temperature/quantization artifact, anthropomorphic "
    "attribution, publication threshold). Be specific about WHY each flaw "
    "matters from the evidence shown. If the hypothesis is sound — its "
    "claims are scoped, controls exist, disclaimers pre-empt obvious "
    "objections — say so plainly; do not invent flaws to appear thorough. "
    "Pre-check the hypothesis for its own scope and quantization disclaimers "
    "before assuming a flaw exists; restate the disclaimer in the no-flag "
    "case.\n\n"
    "Format your response in three sections exactly:\n"
    "  REASONING:\n"
    "  1. <first analytical step>\n"
    "  2. <second analytical step>\n"
    "  3. <third analytical step (optional)>\n"
    "  CRITIQUE:\n"
    "  <one-paragraph critique, or a plain statement of soundness>\n"
    "  FLAG: flawed | sound\n"
    "\n"
    "FLAG must appear on its own line, exactly one of the two values. The "
    "REASONING list must have at least one numbered step."
)


_FLAG_LINE_RE = re.compile(r"^FLAG:\s*(flawed|sound)\b", re.IGNORECASE | re.MULTILINE)
_REASONING_HEADER_RE = re.compile(r"REASONING:\s*\n", re.IGNORECASE)
_CRITIQUE_HEADER_RE = re.compile(r"\n\s*CRITIQUE:\s*\n", re.IGNORECASE)
_NUMBERED_STEP_RE = re.compile(r"^\s*\d+\.\s*(.+?)\s*$", re.MULTILINE)


def _parse_completion(completion: str) -> Dict[str, Any]:
    """Pull out the three required fields. Defensively handles missing
    sections so the contract test's shape guarantee holds even if the model
    returns malformed structure."""
    flag_match = _FLAG_LINE_RE.search(completion)
    flag = flag_match.group(1).lower() if flag_match else "flawed"

    reasoning_block = ""
    rmatch = _REASONING_HEADER_RE.search(completion)
    cmatch = _CRITIQUE_HEADER_RE.search(completion)
    if rmatch:
        end = cmatch.start() if cmatch else len(completion)
        reasoning_block = completion[rmatch.end(): end]
    steps = [m.group(1).strip() for m in _NUMBERED_STEP_RE.finditer(reasoning_block)]
    if not steps:
        # Best-effort fallback: split critique on sentence boundaries and
        # take up to three as reasoning steps so reasoning_chain is non-empty.
        critique_for_split = completion
        if cmatch:
            critique_for_split = completion[cmatch.end():]
        sentence_split = re.split(r"(?<=[.!?])\s+", critique_for_split.strip())
        steps = [s for s in sentence_split if s][:3]
        if not steps:
            steps = ["(model did not emit a structured reasoning chain)"]

    critique_text = completion
    if cmatch:
        critique_section = completion[cmatch.end():]
        if flag_match:
            critique_text = critique_section[: flag_match.start() - cmatch.end()].strip()
        else:
            critique_text = critique_section.strip()
    return {
        "critique_text": critique_text or completion.strip(),
        "flag_decision": flag,
        "reasoning_chain": steps,
    }


def _mock_critique(hypothesis_text: str, context: Any) -> Dict[str, Any]:
    """Deterministic stub used under MOCK_LLM=1. Matches the contract-test
    stub semantics: ``__SOUND__`` substring → sound; otherwise flawed."""
    sound = "__SOUND__" in (hypothesis_text or "")
    flag = "sound" if sound else "flawed"
    reasoning = [
        "step 1: identify the claim and its scope",
        "step 2: enumerate the assumptions and disclaimers",
        "step 3: stress-test the strongest assumption",
    ]
    critique_text = (
        f"(mock) hypothesis flagged {flag}; "
        f"context-kind={type(context).__name__}; "
        "the critic would here enumerate specific objections "
        "or state soundness with controls."
    )
    return {
        "critique_text": critique_text,
        "flag_decision": flag,
        "reasoning_chain": reasoning,
    }


class _Critique:
    """``critique`` is exposed as a callable instance (not a bare function) so
    that ``cls.critique = mod.critique`` in test setUpClass does NOT make it
    a bound method (which would inject the TestCase as ``hypothesis_text``).
    The test contract calls it as ``self.critique(SAMPLE_HYPOTHESIS,
    context=ctx)``; binding to a TestCase instance would shadow the
    positional argument and trigger a "multiple values for argument
    'context'" TypeError. By using a callable instance, Python's descriptor
    protocol does not rebind on attribute access; the instance's ``self`` is
    the ``_Critique`` instance, and external positional args start from
    ``hypothesis_text`` as designed."""

    def __call__(
        self,
        hypothesis_text: str,
        context: Optional[Union[str, Dict[str, Any]]] = None,
        *,
        log_path: Optional[str] = None,
        parent_request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not isinstance(hypothesis_text, str) or not hypothesis_text.strip():
            return {
                "critique_text": "(empty input)",
                "flag_decision": "sound",
                "reasoning_chain": [
                    "empty hypothesis_text — no analysis possible"
                ],
            }

        if os.environ.get("MOCK_LLM"):
            return _mock_critique(hypothesis_text, context)

        if isinstance(context, dict):
            ctx_str: Optional[str] = json.dumps(context, sort_keys=True)
        else:
            ctx_str = context

        user_parts = [f"Hypothesis:\n{hypothesis_text}"]
        if ctx_str:
            user_parts.append(f"\nExperimental context:\n{ctx_str}")
        user_parts.append(
            "\nCritique this hypothesis per the system instructions. Emit "
            "the REASONING / CRITIQUE / FLAG sections exactly as specified."
        )

        try:
            from agent_wrapper.wrapper import call_sync
            record = call_sync(
                [
                    {"role": "system", "content": CRITIC_SYSTEM_PROMPT},
                    {"role": "user", "content": "\n".join(user_parts)},
                ],
                temperature=0.0,
                seed=0,
                max_tokens=600,
                caller_tag="day9_critic",
                parent_request_id=parent_request_id,
                log_path=log_path,
            )
        except Exception as exc:
            return {
                "critique_text": (
                    f"(critic call failed: {type(exc).__name__}: {exc})"
                ),
                "flag_decision": "sound",
                "reasoning_chain": [f"call_sync raised: {type(exc).__name__}"],
            }

        return _parse_completion(record["completion"])


critique = _Critique()
