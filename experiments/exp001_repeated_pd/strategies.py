"""Fixed reference strategies for the iterated Prisoner's Dilemma.

Used by exp001_repeated_pd as deterministic baselines and as fixed
opponents for the LLM player.

Action encoding follows OpenSpiel's matrix Prisoner's Dilemma:
    0 -> "C"  (cooperate)
    1 -> "D"  (defect)

Strategy core is a pure function ``History -> {"C", "D"}`` where
``History`` is a list of ``(own_action, opp_action)`` tuples in
played order. The GRA agent wrappers below adapt the cores to the
``BaseAgent.compute_action`` interface and maintain the history
across rounds via ``observe(own, opp)``.

The strategy *labels* used in the academic literature are
deliberately not spelled out in any module/class/function docstring
or human-readable string in this file — those names are part of the
experiment design and must not appear in any text that could be fed
to an LLM player. See ``notes/track-c-day4-pd.md`` for the mapping.
"""

from typing import Any, Dict, List, Tuple

try:
    from game_reasoning_arena.arena.agents.base_agent import BaseAgent
except ImportError:
    class BaseAgent:  # minimal stub so tests run without the GRA package
        def __init__(self, agent_type: str = "generic"):
            self.agent_type = agent_type
            self.action_count = 0

        def __call__(self, observation):
            action = self.compute_action(observation)
            self.action_count += 1
            return action

        def compute_action(self, observation):  # overridden by subclasses
            raise NotImplementedError


History = List[Tuple[str, str]]

C, D = "C", "D"
ACTION_INT: Dict[str, int] = {C: 0, D: 1}


def decide_mirror(history: History) -> str:
    if not history:
        return C
    return history[-1][1]


def decide_latch(history: History) -> str:
    if any(opp == D for _, opp in history):
        return D
    return C


def decide_constant_c(history: History) -> str:
    return C


def decide_constant_d(history: History) -> str:
    return D


STRATEGY_FNS = {
    "mirror": decide_mirror,
    "latch": decide_latch,
    "constant_c": decide_constant_c,
    "constant_d": decide_constant_d,
}


class _FixedStrategyAgent(BaseAgent):
    """Wraps a pure ``History -> {'C','D'}`` function as a GRA agent."""

    _strategy_key: str = ""

    def __init__(self, **_: Any) -> None:
        super().__init__(agent_type=f"fixed_{self._strategy_key}")
        self._decide = STRATEGY_FNS[self._strategy_key]
        self.history: History = []

    def observe(self, own_action: str, opp_action: str) -> None:
        self.history.append((own_action, opp_action))

    def compute_action(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        choice = self._decide(self.history)
        return {"action": ACTION_INT[choice], "reasoning": ""}


class MirrorAgent(_FixedStrategyAgent):
    _strategy_key = "mirror"


class LatchAgent(_FixedStrategyAgent):
    _strategy_key = "latch"


class ConstantCAgent(_FixedStrategyAgent):
    _strategy_key = "constant_c"


class ConstantDAgent(_FixedStrategyAgent):
    _strategy_key = "constant_d"


AGENT_CLASSES = {
    "mirror": MirrorAgent,
    "latch": LatchAgent,
    "constant_c": ConstantCAgent,
    "constant_d": ConstantDAgent,
}
