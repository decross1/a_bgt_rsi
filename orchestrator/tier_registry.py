"""Canonical sandbox-tier to experiment map.

The research program's sandbox spectrum has three tiers. This module is
the single place that says which built experiment lives in which tier,
and reports each experiment's apparatus capabilities (run / analyze /
loop_bridge / results summary) by *filesystem inspection only* — it does
NOT import the experiment modules.

Tiers (in spectrum order, `list_tiers()` order):

- `synthetic`      — exp001_repeated_pd, exp003_vickrey_rediscovery,
                     exp004_combinatorial_auction, exp005_mechanism_aware
- `semi_synthetic` — exp006_mechanism_design
- `applied`        — exp007_polymarket (the first applied-tier entry).
                     Applied = design-only / CFTC-gated PAPER FORECASTING:
                     read-only public market data + an LLM probability
                     forecast scored OFFLINE (Brier / Brier Skill Score
                     vs the market price). No live trading, no orders, no
                     wallet — Polymarket stays design-only until CFTC
                     compliance work is done (CLAUDE.md guardrail).

The apparatus is honestly heterogeneous, and the registry surfaces that
rather than papering over it:

- exp001_repeated_pd has neither `analyze.py` nor `loop_bridge.py` (it
  predates that convention; analysis lives under its own `analysis/`).
- exp005_mechanism_aware has `analyze.py` but no `loop_bridge.py`.
- exp003 / exp004 / exp006 carry the full run + analyze + loop_bridge set.
- `results_summary` resolution differs per experiment: exp001/exp004 ship
  `results/summary.json`; exp003 ships `results/summary.md`; the rest have
  no committed summary (None).

Each entry is a plain dict:

    {
        "experiment_id":   str,
        "tier":            str,
        "dir":             str,   # repo-relative
        "has_run":         bool,
        "has_analyze":     bool,
        "has_loop_bridge": bool,
        "results_summary": str | None,  # repo-relative path to
                                        # results/summary.{json,md} or None
    }
"""
from __future__ import annotations

import os

# repo root = parent of this file's directory (orchestrator/)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EXPERIMENTS_DIR = "experiments"

# Tier ordering is the sandbox spectrum: synthetic -> semi -> applied.
_TIER_MAP: dict[str, list[str]] = {
    "synthetic": [
        "exp001_repeated_pd",
        "exp003_vickrey_rediscovery",
        "exp004_combinatorial_auction",
        "exp005_mechanism_aware",
    ],
    "semi_synthetic": [
        "exp006_mechanism_design",
    ],
    # applied = design-only / CFTC-gated paper forecasting (read-only data
    # + LLM probability forecast scored offline). NO live trading.
    "applied": [
        "exp007_polymarket",
    ],
}


def _abs(*parts: str) -> str:
    return os.path.join(_REPO_ROOT, *parts)


def _resolve_summary(rel_dir: str) -> str | None:
    """Return repo-relative path to results/summary.{json,md}, else None.

    json is preferred over md when both exist.
    """
    for name in ("summary.json", "summary.md"):
        rel = os.path.join(rel_dir, "results", name)
        if os.path.isfile(_abs(rel)):
            return rel
    return None


def _build_entry(experiment_id: str, tier: str) -> dict:
    rel_dir = os.path.join(_EXPERIMENTS_DIR, experiment_id)
    return {
        "experiment_id": experiment_id,
        "tier": tier,
        "dir": rel_dir,
        "has_run": os.path.isfile(_abs(rel_dir, "run.py")),
        "has_analyze": os.path.isfile(_abs(rel_dir, "analyze.py")),
        "has_loop_bridge": os.path.isfile(_abs(rel_dir, "loop_bridge.py")),
        "results_summary": _resolve_summary(rel_dir),
    }


# Built once at import from the live filesystem. Keys are experiment_ids.
_REGISTRY: dict[str, dict] = {
    eid: _build_entry(eid, tier)
    for tier, eids in _TIER_MAP.items()
    for eid in eids
}


def list_tiers() -> list[str]:
    """Tier names in sandbox-spectrum order."""
    return list(_TIER_MAP.keys())


def experiments_in_tier(tier: str) -> list[dict]:
    """Entries for a tier, in declared order. Unknown tier -> KeyError."""
    if tier not in _TIER_MAP:
        raise KeyError(tier)
    return [_REGISTRY[eid] for eid in _TIER_MAP[tier]]


def get_experiment(experiment_id: str) -> dict:
    """Entry for one experiment. Unknown id -> KeyError."""
    return _REGISTRY[experiment_id]


def tiers_status() -> dict[str, int]:
    """Map each tier to its built-experiment count."""
    return {tier: len(eids) for tier, eids in _TIER_MAP.items()}
