"""LLM topicality check: is a hypothesis in-domain for this apparatus?

Added 2026-06-09 (battery revision cycle, rule 7) after BOTH corpus-derived
embedding anchors were falsified as off-domain separators (calibration gaps
-0.079 / -0.075): distance-to-known-content cannot distinguish "genuinely
novel on-domain" from "vocabulary-camouflaged off-domain" — both sit far
from the corpus by construction. Asking the model the domain question
DIRECTLY is a different signal: the camouflaged cases (DB tuning, React
adoption, Raft consensus) are obviously off-domain when the question is
"what is this claim primarily about?" rather than "is it near the corpus?".

check() returns "on" | "off" | "unsure" | None:
  - None  under MOCK_LLM, or on any wrapper/parse failure (fail-OPEN: the
    relevance gate treats None exactly like the legacy no-signal path;
    each None is logged with a distinct reason, rule 7).
  - "unsure" when the model is unparseable-but-responsive or declares
    uncertainty. "unsure" never condemns (over-gating guard).
Only the literal "off" fires the gate's R0 rule.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from agent_wrapper.wrapper import call_sync

logger = logging.getLogger("topicality")

CALLS_LOG_PATH = os.environ.get("LOOP_V0_CALLS_LOG", "logs/calls.jsonl")

_SYSTEM = (
    "You judge whether a research hypothesis is IN-DOMAIN for a game-theory "
    "research apparatus. In-domain means the claim is PRIMARILY a question of "
    "game theory, behavioral game theory, or learning in games — including "
    "LLM agents playing games (Prisoner's Dilemma, auctions, beauty contests, "
    "coordination, bargaining, mechanism design, equilibrium concepts).\n"
    "OFF-domain means the claim is primarily about something else — software "
    "engineering, databases, distributed systems, ML infrastructure, code "
    "quality, web frameworks — EVEN IF it is phrased with game-theoretic "
    "vocabulary (payoffs, equilibria, strategies, cooperation). Strip the "
    "vocabulary; ask what the claim is actually about and what evidence "
    "would test it.\n"
    'Answer with ONLY a JSON object: {"domain": "on" | "off", '
    '"reason": "<one sentence>"}. If you are genuinely torn, use '
    '{"domain": "unsure", "reason": "..."}.'
)


def check(hypothesis_text: str) -> str | None:
    """One cheap LLM call -> "on" | "off" | "unsure" | None (see module doc)."""
    if os.environ.get("MOCK_LLM"):
        logger.info("topicality: MOCK_LLM set -> None (signal unavailable)")
        return None
    if not isinstance(hypothesis_text, str) or not hypothesis_text.strip():
        logger.warning("topicality: empty hypothesis_text -> None")
        return None

    try:
        record = call_sync(
            [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": hypothesis_text.strip()},
            ],
            temperature=0.0,
            max_tokens=256,
            caller_tag="topicality_check",
            log_path=CALLS_LOG_PATH,
        )
    except Exception as exc:
        logger.warning("topicality: call_sync failed (%r) -> None", exc)
        return None

    # Wrapper records carry `completion` as a plain STRING
    # (agent_wrapper/wrapper.py builds it from message.content directly —
    # the 2026-06-09 review caught a dict-shaped misread here that made R0
    # silently dead via the fail-open path).
    content = record.get("completion") if isinstance(record, dict) else None
    if not isinstance(content, str) or not content.strip():
        logger.warning("topicality: empty completion -> None")
        return None

    m = re.search(r"\{.*\}", content, re.DOTALL)
    if not m:
        logger.warning("topicality: no JSON in completion -> unsure")
        return "unsure"
    try:
        payload: Any = json.loads(m.group(0))
    except json.JSONDecodeError:
        logger.warning("topicality: unparseable JSON -> unsure")
        return "unsure"
    domain = payload.get("domain") if isinstance(payload, dict) else None
    if domain not in ("on", "off", "unsure"):
        logger.warning("topicality: off-enum domain %r -> unsure", domain)
        return "unsure"
    return domain
