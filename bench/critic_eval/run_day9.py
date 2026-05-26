"""Day 9 critic-eval driver. Runs workers.critic.critique against the 20
critic_hypotheses fixtures (19 flawed + 1 sound baseline) via the
Track-B-locked scorer in tests/test_critic_eval_scoring.py
(``score_critic_run`` + ``score_critic_eval``). The pass bar
(``PASS_RATE_BAR = 0.80``) lives in that scoring module and may not drift
without a D-NNN decision entry.

Tier: soft_gate (4h SLA) per the Week-2 unlock tier-shift inventory —
sensitivity (=label_correct + ≥1 target hit on flawed fixtures) ≥ 0.80 over
the 20-fixture set is the documented bar. Refuses to run under MOCK_LLM=1
because the stub critic clears the bar trivially.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.fixtures.loader import load_critic_fixtures, validate_fixture
from tests.test_critic_eval_scoring import (
    PASS_RATE_BAR,
    score_critic_eval,
    score_one,
)
from workers.critic import critique


def run(fixtures_dir: Path, out_path: Path, log_path: Path) -> Dict[str, Any]:
    fixtures = load_critic_fixtures()
    if not fixtures:
        raise SystemExit(
            f"no fixtures loaded from {fixtures_dir} — check repo layout"
        )
    for fx in fixtures:
        errs = validate_fixture(fx)
        if errs:
            raise SystemExit(f"fixture {fx.get('id')!r} invalid: {errs}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    scored = []

    with out_path.open("w") as out_fh:
        for fx in fixtures:
            t0 = time.perf_counter()
            result = critique(
                fx["hypothesis_text"],
                fx.get("context"),
                log_path=str(log_path),
            )
            duration_ms = (time.perf_counter() - t0) * 1000.0
            score = score_one(fx, result)
            scored.append(score)
            verdict = {
                "fixture_id": score.fixture_id,
                "ground_truth_label": score.ground_truth_label,
                "predicted_label": score.predicted_label,
                "label_correct": score.label_correct,
                "target_hits": score.target_hits,
                "n_targets_expected": len(fx.get("expected_critique_targets", [])),
                "passed": score.passed,
                "injected_flaw_type": fx["injected_flaw_type"],
                "severity": fx["severity"],
                "domain": fx["domain"],
                "critique_excerpt": result.get("critique_text", "")[:400],
                "reasoning_chain": result.get("reasoning_chain", []),
                "duration_ms": round(duration_ms, 1),
            }
            out_fh.write(json.dumps(verdict) + "\n")
            print(
                f"  {score.fixture_id:<45} "
                f"truth={score.ground_truth_label:<6} "
                f"pred={score.predicted_label:<6} "
                f"hits={len(score.target_hits)}/{verdict['n_targets_expected']} "
                f"pass={score.passed}",
                file=sys.stderr,
            )

    summary = score_critic_eval(scored)
    out = {
        "fixtures_scored": summary.fixtures_scored,
        "label_correct": summary.label_correct,
        "target_hits_at_least_one": summary.target_hits_at_least_one,
        "passed": summary.passed,
        "pass_rate": summary.pass_rate,
        "bar": summary.bar,
        "meets_bar": summary.meets_bar,
    }
    print(json.dumps(out, indent=2))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixtures",
        default="experiments/fixtures/critic_hypotheses",
        help="fixture directory (default: experiments/fixtures/critic_hypotheses)",
    )
    parser.add_argument(
        "--out",
        default="bench/critic_eval/day9_run.jsonl",
        help="per-fixture verdicts output (JSONL)",
    )
    parser.add_argument(
        "--log",
        default="logs/day9_critic.jsonl",
        help="wrapper call log (JSONL)",
    )
    args = parser.parse_args()

    if os.environ.get("MOCK_LLM"):
        print(
            "ERROR: MOCK_LLM is set; this eval requires the real vLLM "
            "endpoint. Relaunch with `env -u MOCK_LLM`.",
            file=sys.stderr,
        )
        return 2

    summary = run(Path(args.fixtures), Path(args.out), Path(args.log))
    return 0 if summary["meets_bar"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
