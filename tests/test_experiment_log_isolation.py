"""Guards that experiment harnesses never write the production call log.

A real `--live` / `env -u MOCK_LLM` experiment run drives both Nara's own
orchestrator turns AND in-chain workers (hypothesize / novelty_classify /
meta_review). The workers read ``LOOP_V0_CALLS_LOG`` at IMPORT time and
meta_review hard-codes the module constant (no per-call log_path), so passing
``log_path=`` to ``run_iteration`` alone redirects only Nara's turns — the
worker calls still default to production ``logs/calls.jsonl``. The complete fix
is to set ``LOOP_V0_CALLS_LOG`` to an eval-local path BEFORE the orchestrator
(and thus the workers) is imported. This test pins that contract by source so a
future edit can't silently reintroduce the leak.

Source-level (not import-level) on purpose: importing these harness modules has
global side effects (they set os.environ and import the orchestrator), which
would pollute other tests. The invariant we need is precisely an ordering one.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

HARNESSES = [
    "experiments/exp002_loop_v0_robustness/runner.py",
    "experiments/exp001_repeated_pd/loop_bridge.py",
    "experiments/exp003_vickrey_rediscovery/loop_bridge.py",
    "experiments/exp009_cournot/loop_bridge.py",
    "experiments/exp004_combinatorial_auction/loop_bridge.py",
    "experiments/exp006_mechanism_design/loop_bridge.py",
    "experiments/exp007_polymarket/loop_bridge.py",
    "experiments/exp010_audit_collusion/loop_bridge.py",
    "experiments/exp011_matching_reconstruction/loop_bridge.py",
    "experiments/exp012_lqg_spectral/loop_bridge.py",
    "experiments/replication_driver.py",
]

_ENV_SET = re.compile(r"""os\.environ\[\s*["']LOOP_V0_CALLS_LOG["']\s*\]\s*=""")
_NARA_IMPORT = "from orchestrator.nara import run_iteration"


def _is_real_import(line: str) -> bool:
    """The actual import statement, not a comment/docstring mention of it."""
    return line.lstrip().startswith(_NARA_IMPORT)


@pytest.mark.parametrize("rel", HARNESSES)
def test_sets_loop_v0_calls_log_before_orchestrator_import(rel):
    lines = (REPO / rel).read_text().splitlines()
    env_idx = next((i for i, ln in enumerate(lines) if _ENV_SET.search(ln)), None)
    imp_idx = next((i for i, ln in enumerate(lines) if _is_real_import(ln)), None)
    assert env_idx is not None, f"{rel}: never sets LOOP_V0_CALLS_LOG (worker calls would leak to production)"
    assert imp_idx is not None, f"{rel}: expected a `{_NARA_IMPORT}` line"
    assert env_idx < imp_idx, (
        f"{rel}: LOOP_V0_CALLS_LOG is set at line {env_idx + 1} but the "
        f"orchestrator import is at line {imp_idx + 1}; workers read the env "
        "var at import time, so it must be set BEFORE the import or the "
        "worker calls leak to production logs/calls.jsonl"
    )


@pytest.mark.parametrize("rel", HARNESSES)
def test_redirects_nara_turns_via_log_path(rel):
    """Nara's own turns are redirected via the explicit log_path= arg (the env
    var covers the workers; run_iteration's own default is logs/calls.jsonl)."""
    src = (REPO / rel).read_text()
    assert "log_path=CALLS_LOG_PATH" in src, (
        f"{rel}: run_iteration must be passed log_path=CALLS_LOG_PATH so Nara's "
        "own orchestrator turns are redirected too"
    )
    assert 'os.environ["LOOP_V0_CALLS_LOG"] = CALLS_LOG_PATH' in src or \
        "LOOP_V0_CALLS_LOG" in src
