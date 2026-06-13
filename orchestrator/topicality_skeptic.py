"""Independent topicality attack — the off-domain arm of the skeptic (R0b).

Added 2026-06-10 (D-045 residual 1). The falsification-battery baseline
(runs/battery_20260609T212352Z) showed `fase_off_01_semantic_entropy`
passing BOTH the primary Gemma R0 judge (orchestrator/topicality.py) AND
the generic D-044 refute attack — the refute prompt has no off-domain
arm, so "the chunks contain no discussion of semantic entropy" reads as
absence-of-contradiction instead of as the off-domain fingerprint it is
(the iter-001 trap again). This module is the purpose-built fix: an
ADVERSARIAL second domain judgment on an independent backend (vllm-qwen
by default), framed as an attack on the primary judge's IN-DOMAIN call.

attack_topicality() returns "on" | "off" | "unsure" | None:
  - None under MOCK_LLM, on empty input, on an unknown backend, on any
    wrapper failure, or on an empty completion (fail-OPEN: the consumer —
    orchestrator/topicality.py check() — treats None as "no independent
    signal" and the primary verdict stands; each None is logged with a
    distinct reason, rule 7).
  - "unsure" when the model is responsive but unparseable / off-enum.
    "unsure" never condemns (over-gating guard — the canary cases are
    part of the battery bar).
Only the literal "off" condemns: check() maps it to "off_independent"
and the relevance ladder (workers/retrieval_relevance.py) fires R0b.
The whole seam is gated by NARA_TOPICALITY_SKEPTIC=1 at the check()
layer; unset, this module is never called and the pipe is byte-identical
to D-045 behavior.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from agent_wrapper.backends import get_backend
from agent_wrapper.wrapper import call_sync

logger = logging.getLogger("topicality_skeptic")

CALLS_LOG_PATH = os.environ.get("LOOP_V0_CALLS_LOG", "logs/calls.jsonl")

# Qwen burns tokens on a hidden reasoning channel before the visible
# answer and starves at 512/2048 (observed 2026-06-09, D-044) — 3072 is
# the working figure the other independent-skeptic calls run with.
ATTACK_MAX_TOKENS = 3072

# REFUTE-framed against the primary judge's in-domain call: the attack
# must name the claim's PRIMARY subject and the evidence that would test
# it, with the substrate-transfer boundary stated in BOTH directions
# (vocabulary camouflage condemns; LLM-agents-playing-games clears).
_SYSTEM = (
    "The apparatus's own model judged this claim IN-DOMAIN for a "
    "game-theory research apparatus. Attack that judgment — but apply the "
    "domain boundary HONESTLY in both directions; condemning a genuine "
    "game-theory claim is as much an error as clearing a camouflaged "
    "off-domain one. State the claim's PRIMARY subject and the concrete "
    "evidence that would test it, then judge:\n"
    "OFF-domain: the primary tested quantity is NOT strategic interaction "
    "— e.g. code-quality / software-engineering / database / "
    "distributed-systems / ML-infrastructure metrics, retrieval or "
    "chunk-overlap quality, or properties of ONE model's outputs in "
    "isolation (uncertainty / entropy / calibration / hallucination "
    "detection) — EVEN when dressed in payoff / equilibrium / auction / "
    "cooperation vocabulary.\n"
    "ON-domain: the claim is substantively about STRATEGIC INTERACTION "
    "among decision-makers. This INCLUDES the canonical theory of games "
    "and behavioral / evolutionary game theory stated in PLAIN LANGUAGE, "
    "with NO AI or LLM framing required, whether the agents are humans, "
    "animals, or machines — for example: equilibrium and solution "
    "concepts (Nash, quantal-response / QRE, level-k, correlated), the "
    "folk theorem and repeated-game cooperation / reciprocity (tit-for-"
    "tat, reputation), bargaining (ultimatum, Nash bargaining), and "
    "evolutionary stability (hawk-dove, ESS, replicator dynamics), plus "
    "human or agent experimental tests of any of these. Do NOT condemn a "
    "plain-language classic of game theory as off-domain merely because "
    "it omits AI, or because its evidence is human-experimental or "
    "mathematical rather than artificial-agent game-play.\n"
    "Output STRICT JSON, nothing else — no prose, no markdown fences:\n"
    '{"domain": "on" | "off" | "unsure", '
    '"primary_subject": "<one phrase>", "reason": "<one sentence>"}. '
    'If you are genuinely torn, use "unsure".'
)


def attack_topicality(
    hypothesis_text: str, backend: str | None = None,
) -> str | None:
    """One adversarial domain call -> "on" | "off" | "unsure" | None.

    backend=None resolves from NARA_SKEPTIC_BACKEND (default "vllm-qwen",
    the backend the 2026-06-09 D-044 ladder step-1 live test validated).
    An unknown backend name fails OPEN to None — never silently coerced
    to the default (rule 4 / explicit-fallback discipline, mirroring
    orchestrator/novelty_skeptic.attack()).
    """
    if backend is None:
        backend = os.environ.get("NARA_SKEPTIC_BACKEND", "vllm-qwen")
    if os.environ.get("MOCK_LLM"):
        logger.info("topicality_skeptic: MOCK_LLM set -> None (signal unavailable)")
        return None
    if not isinstance(hypothesis_text, str) or not hypothesis_text.strip():
        logger.warning("topicality_skeptic: empty hypothesis_text -> None")
        return None
    try:
        get_backend(backend)
    except KeyError as exc:
        logger.warning("topicality_skeptic: unknown backend (%s) -> None", exc)
        return None

    try:
        record = call_sync(
            [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": hypothesis_text.strip()},
            ],
            temperature=0.0,
            max_tokens=ATTACK_MAX_TOKENS,
            caller_tag="topicality_attack",
            backend=backend,
            log_path=CALLS_LOG_PATH,
        )
    except Exception as exc:
        logger.warning("topicality_skeptic: call_sync failed (%r) -> None", exc)
        return None

    # Wrapper records carry `completion` as a plain STRING (same shape
    # note as topicality.py — the 2026-06-09 review caught a dict-shaped
    # misread that made R0 silently dead via the fail-open path).
    content = record.get("completion") if isinstance(record, dict) else None
    if not isinstance(content, str) or not content.strip():
        logger.warning("topicality_skeptic: empty completion -> None")
        return None

    m = re.search(r"\{.*\}", content, re.DOTALL)
    if not m:
        logger.warning("topicality_skeptic: no JSON in completion -> unsure")
        return "unsure"
    try:
        payload: Any = json.loads(m.group(0))
    except json.JSONDecodeError:
        logger.warning("topicality_skeptic: unparseable JSON -> unsure")
        return "unsure"
    domain = payload.get("domain") if isinstance(payload, dict) else None
    if domain not in ("on", "off", "unsure"):
        logger.warning("topicality_skeptic: off-enum domain %r -> unsure", domain)
        return "unsure"
    return domain
