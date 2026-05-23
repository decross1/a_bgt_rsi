"""LLM player for exp001_repeated_pd.

Plays a repeated 2-player matrix game by feeding the rules + recent
history to Gemma 4 and parsing a single-letter reply. The prompt
intentionally never names any strategy from the academic literature —
those names would tip the model off to the experimental setup it is
being evaluated in. See notes/track-c-day4-pd.md.

Action encoding follows OpenSpiel's matrix Prisoner's Dilemma:
    0 -> "C"  (cooperate)
    1 -> "D"  (defect)

Parser policy: one retry with a tighter format instruction; on a
second failure log a ``parse_failure`` observation event to the run
log and default to action 1 (D). The default is logged, not silent.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, List, Tuple

from agent_wrapper.wrapper import call_sync

try:
    from game_reasoning_arena.arena.agents.base_agent import BaseAgent
except ImportError:
    class BaseAgent:  # minimal stub for tests without GRA installed
        def __init__(self, agent_type: str = "generic"):
            self.agent_type = agent_type
            self.action_count = 0


History = List[Tuple[str, str]]
C, D = "C", "D"
ACTION_INT: Dict[str, int] = {C: 0, D: 1}

# Payoffs match OpenSpiel matrix_pd: CC=(5,5), CD=(0,10), DC=(10,0), DD=(1,1).
_RULES = (
    "You are playing a game with another player across many rounds. "
    "In each round, you and the other player simultaneously and "
    "independently choose one of two moves, written 'C' or 'D'. "
    "After both moves are revealed you both receive points by this rule: "
    "if you both play C you each get 5 points; "
    "if you play C and they play D you get 0 and they get 10; "
    "if you play D and they play C you get 10 and they get 0; "
    "if you both play D you each get 1 point. "
    "There will be many more rounds after this one. Your goal is to "
    "maximize your own total points across the whole game."
)
_FORMAT = (
    "Reply with exactly one character: C or D. Do not include any "
    "explanation, punctuation, or extra text."
)
_RETRY = (
    "Your previous reply could not be parsed. Reply with exactly one "
    "character — either C or D — and nothing else."
)

# Named diagnostic prompt variants. The "baseline" variant is the
# original deliberately-neutral framing. Other variants are documented
# DIAGNOSTIC experiments — selecting any non-baseline variant logs as
# a research-design intervention, not the headline experiment.
RULES_VARIANTS: Dict[str, str] = {
    "baseline": "",
    "exploitation_hint": (
        " Note that defecting against a cooperator gives you the largest "
        "single-round payoff (10 points). You may choose to defect if "
        "that maximizes your total points in the long run."
    ),
}


def _format_history(history: History, last_n: int = 20) -> str:
    if not history:
        return "No rounds have been played yet."
    recent = history[-last_n:]
    lines = []
    for i, (own, opp) in enumerate(recent, start=max(1, len(history) - last_n + 1)):
        lines.append(f"  round {i}: you={own}, them={opp}")
    head = f"Last {len(recent)} round(s) of {len(history)} so far:\n"
    return head + "\n".join(lines)


def _parse(text: str) -> str | None:
    if not text:
        return None
    m = re.search(r"[CDcd]", text)
    if not m:
        return None
    return m.group(0).upper()


def _log_parse_failure(log_path: str | None, *, round_idx: int, raw: str, attempt: int) -> None:
    if not log_path:
        return
    rec = {
        "ts": time.time(),
        "event": "parse_failure",
        "round": round_idx,
        "attempt": attempt,
        "raw_excerpt": (raw or "")[:200],
        "caller": "exp001_llm_agent",
    }
    os.makedirs(os.path.dirname(os.path.abspath(log_path)) or ".", exist_ok=True)
    with open(log_path, "a") as f:
        f.write(json.dumps(rec) + "\n")


class LLMAgent(BaseAgent):
    """Gemma-4 player. Maintains ``(own, opp)`` history; one parser retry."""

    def __init__(
        self,
        *,
        log_path: str | None = None,
        model: str | None = None,
        max_tokens: int = 4,
        seed: int | None = None,
        temperature: float = 0.0,
        history_window: int = 20,
        caller_tag: str = "exp001_llm_agent",
        rules_variant: str = "baseline",
    ) -> None:
        super().__init__(agent_type="llm")
        self.history: History = []
        self.log_path = log_path
        self.model = model
        self.max_tokens = max_tokens
        self.seed = seed
        self.temperature = temperature
        self.history_window = history_window
        self.caller_tag = caller_tag
        if rules_variant not in RULES_VARIANTS:
            raise ValueError(
                f"unknown rules_variant {rules_variant!r}; known: "
                f"{sorted(RULES_VARIANTS)}"
            )
        self.rules_variant = rules_variant
        self._rules = _RULES + RULES_VARIANTS[rules_variant]
        self.parse_failures = 0
        self.default_d_plays = 0

    def observe(self, own_action: str, opp_action: str) -> None:
        self.history.append((own_action, opp_action))

    def _call(self, system: str, user: str) -> str:
        record = call_sync(
            [{"role": "system", "content": system},
             {"role": "user", "content": user}],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            seed=self.seed,
            caller_tag=self.caller_tag,
            log_path=self.log_path,
            model=self.model,
        )
        return (record.get("completion") or "").strip()

    def compute_action(self, observation: Dict[str, Any] | None = None) -> Dict[str, Any]:
        round_idx = len(self.history) + 1
        user = (
            f"{_format_history(self.history, last_n=self.history_window)}\n\n"
            f"It is now round {round_idx}. Your move?"
        )

        raw1 = self._call(self._rules + " " + _FORMAT, user)
        parsed = _parse(raw1)
        if parsed is not None:
            return {"action": ACTION_INT[parsed], "reasoning": "", "raw": raw1}

        self.parse_failures += 1
        _log_parse_failure(self.log_path, round_idx=round_idx, raw=raw1, attempt=1)

        raw2 = self._call(self._rules + " " + _RETRY, user)
        parsed = _parse(raw2)
        if parsed is not None:
            return {"action": ACTION_INT[parsed], "reasoning": "", "raw": raw2}

        self.parse_failures += 1
        self.default_d_plays += 1
        _log_parse_failure(self.log_path, round_idx=round_idx, raw=raw2, attempt=2)
        return {"action": ACTION_INT[D], "reasoning": "default_d_after_parse_failure", "raw": raw2}
