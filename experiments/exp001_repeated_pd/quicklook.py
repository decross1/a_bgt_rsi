#!/usr/bin/env python3
"""Quicklook analysis for exp001_repeated_pd.

Reads per-opponent CSV results from ``--input`` and emits:
  * one cumulative-payoff PNG per opponent in ``--output-dir``;
  * a markdown summary table at ``--analysis-md`` with columns
    ``opponent | cooperation rate | mean payoff | switch points``.

Each CSV is one match: rows are rounds in play order, columns are
``own_action, opp_action, own_payoff, opp_payoff``. Actions may be
encoded as the strings ``"C"`` / ``"D"`` or the OpenSpiel ints
``0`` / ``1`` (0 = cooperate). The opponent label is the CSV's file
stem (e.g. ``tft.csv`` -> ``tft``).

CLI:
    python3 experiments/exp001_repeated_pd/quicklook.py \\
        --input experiments/exp001_repeated_pd/results \\
        --output-dir experiments/exp001_repeated_pd/plots \\
        --analysis-md experiments/exp001_repeated_pd/analysis/summary.md

The script is offline: no network, no LLM, no ChromaDB.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

import matplotlib

matplotlib.use("Agg")  # headless; safe inside CI / Track A runs
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

REQUIRED_COLUMNS = ["own_action", "opp_action", "own_payoff", "opp_payoff"]
COOPERATE_TOKENS = {"C", "c", 0, "0"}


def _is_cooperate(value) -> bool:
    """True iff ``value`` denotes cooperation under either encoding."""
    if isinstance(value, str):
        return value.strip() in {"C", "c", "0"}
    return value == 0


def _load_match(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"{csv_path.name}: missing required columns {missing}; "
            f"got {list(df.columns)}"
        )
    return df


def _summarize(opponent: str, df: pd.DataFrame) -> dict:
    own_actions = df["own_action"].tolist()
    coop_flags = [_is_cooperate(a) for a in own_actions]
    coop_rate = sum(coop_flags) / len(coop_flags) if coop_flags else 0.0
    mean_payoff = float(df["own_payoff"].mean()) if len(df) else 0.0
    # Switch points: number of round-to-round changes in own_action.
    switch_points = sum(
        1 for prev, curr in zip(own_actions[:-1], own_actions[1:]) if prev != curr
    )
    return {
        "opponent": opponent,
        "cooperation_rate": coop_rate,
        "mean_payoff": mean_payoff,
        "switch_points": switch_points,
    }


def _plot_cumulative_payoff(
    opponent: str, df: pd.DataFrame, output_dir: Path
) -> Path:
    cum_own = df["own_payoff"].cumsum()
    cum_opp = df["opp_payoff"].cumsum()
    rounds = range(1, len(df) + 1)

    fig, ax = plt.subplots(figsize=(6, 4))
    ax.plot(rounds, cum_own, label="own", linewidth=2)
    ax.plot(rounds, cum_opp, label="opponent", linewidth=2, linestyle="--")
    ax.set_xlabel("round")
    ax.set_ylabel("cumulative payoff")
    ax.set_title(f"cumulative payoff vs {opponent}")
    ax.legend()
    ax.grid(True, alpha=0.3)

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{opponent}_cumulative_payoff.png"
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path


def _render_markdown(rows: List[dict]) -> str:
    lines = [
        "# exp001_repeated_pd quicklook",
        "",
        "| opponent | cooperation rate | mean payoff | switch points |",
        "| --- | --- | --- | --- |",
    ]
    for r in rows:
        lines.append(
            f"| {r['opponent']} "
            f"| {r['cooperation_rate']:.3f} "
            f"| {r['mean_payoff']:.3f} "
            f"| {r['switch_points']} |"
        )
    lines.append("")
    return "\n".join(lines)


def run(input_dir: Path, output_dir: Path, analysis_md: Path) -> List[dict]:
    csv_paths = sorted(input_dir.glob("*.csv"))
    if not csv_paths:
        raise FileNotFoundError(f"no CSV files found in {input_dir}")

    rows: List[dict] = []
    for csv_path in csv_paths:
        opponent = csv_path.stem
        df = _load_match(csv_path)
        _plot_cumulative_payoff(opponent, df, output_dir)
        rows.append(_summarize(opponent, df))

    analysis_md.parent.mkdir(parents=True, exist_ok=True)
    analysis_md.write_text(_render_markdown(rows))
    return rows


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", required=True, type=Path,
        help="directory of per-opponent CSV files",
    )
    parser.add_argument(
        "--output-dir", required=True, type=Path,
        help="directory to write cumulative-payoff PNG plots",
    )
    parser.add_argument(
        "--analysis-md", required=True, type=Path,
        help="markdown summary output path",
    )
    args = parser.parse_args(argv)
    rows = run(args.input, args.output_dir, args.analysis_md)
    print(f"wrote {len(rows)} plots to {args.output_dir}")
    print(f"wrote summary to {args.analysis_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
