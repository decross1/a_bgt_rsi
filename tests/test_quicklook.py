#!/usr/bin/env python3
"""Unit tests for experiments/exp001_repeated_pd/quicklook.py.

Synthesizes a 5-opponent results directory under pytest's tmp_path,
runs the quicklook entrypoint, then asserts:
  * exactly 5 cumulative-payoff plot files were written;
  * the markdown summary has a table with 5 data rows.

The five opponents mirror Day 7's planned matchups (TFT, grim, all-C,
all-D, plus one extra) so the test fixture matches what Track A will
feed quicklook on Day 7.

Run:
    pytest tests/test_quicklook.py -v

Dependencies pinned here (do NOT propagate to requirements.txt --
that's Track A's call):
    pandas == 2.2.3
    matplotlib == 3.9.2
    pytest == 8.3.3
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import List, Tuple

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from experiments.exp001_repeated_pd import quicklook  # noqa: E402

# Five opponents: TFT, grim, all-C, all-D, plus a "random" fifth slot
# reserved for the Day-7 expansion. Each entry is
# (opponent_name, list_of_rounds) where each round is
# (own_action, opp_action, own_payoff, opp_payoff).
OPPONENTS: List[Tuple[str, List[Tuple[str, str, int, int]]]] = [
    (
        "tft",
        [
            ("C", "C", 3, 3),
            ("C", "C", 3, 3),
            ("D", "C", 5, 0),
            ("C", "D", 0, 5),
            ("C", "C", 3, 3),
        ],
    ),
    (
        "grim",
        [
            ("C", "C", 3, 3),
            ("C", "C", 3, 3),
            ("D", "C", 5, 0),
            ("D", "D", 1, 1),
            ("D", "D", 1, 1),
        ],
    ),
    (
        "all_c",
        [
            ("D", "C", 5, 0),
            ("D", "C", 5, 0),
            ("D", "C", 5, 0),
            ("D", "C", 5, 0),
            ("D", "C", 5, 0),
        ],
    ),
    (
        "all_d",
        [
            ("C", "D", 0, 5),
            ("C", "D", 0, 5),
            ("D", "D", 1, 1),
            ("D", "D", 1, 1),
            ("D", "D", 1, 1),
        ],
    ),
    (
        "random",
        [
            ("C", "D", 0, 5),
            ("D", "C", 5, 0),
            ("C", "C", 3, 3),
            ("D", "D", 1, 1),
            ("C", "C", 3, 3),
        ],
    ),
]


def _write_results_dir(root: Path) -> Path:
    results = root / "results"
    results.mkdir()
    for name, rounds in OPPONENTS:
        with (results / f"{name}.csv").open("w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["own_action", "opp_action", "own_payoff", "opp_payoff"])
            writer.writerows(rounds)
    return results


def test_quicklook_writes_five_plots_and_five_row_table(tmp_path: Path) -> None:
    input_dir = _write_results_dir(tmp_path)
    output_dir = tmp_path / "plots"
    analysis_md = tmp_path / "analysis" / "summary.md"

    rows = quicklook.run(input_dir, output_dir, analysis_md)

    # 5 plot files, one per opponent.
    plot_files = sorted(output_dir.glob("*.png"))
    assert len(plot_files) == 5, (
        f"expected 5 plots, got {len(plot_files)}: {[p.name for p in plot_files]}"
    )
    plot_stems = {p.stem.replace("_cumulative_payoff", "") for p in plot_files}
    assert plot_stems == {name for name, _ in OPPONENTS}

    # Markdown table has 5 data rows.
    md_text = analysis_md.read_text()
    table_data_rows = [
        line for line in md_text.splitlines()
        if line.startswith("|")
        and not line.startswith("| opponent")
        and not line.startswith("| ---")
    ]
    assert len(table_data_rows) == 5, (
        f"expected 5 data rows in markdown table, got {len(table_data_rows)}:\n"
        f"{md_text}"
    )

    # Sanity-check the in-memory rows match the table count too.
    assert len(rows) == 5


def test_quicklook_summary_values(tmp_path: Path) -> None:
    """Spot-check cooperation rate / mean payoff / switch points for one match."""
    input_dir = _write_results_dir(tmp_path)
    output_dir = tmp_path / "plots"
    analysis_md = tmp_path / "summary.md"

    rows = quicklook.run(input_dir, output_dir, analysis_md)
    by_opp = {r["opponent"]: r for r in rows}

    # all_c match: own_action is D every round -> coop rate 0, mean 5, 0 switches.
    all_c = by_opp["all_c"]
    assert all_c["cooperation_rate"] == pytest.approx(0.0)
    assert all_c["mean_payoff"] == pytest.approx(5.0)
    assert all_c["switch_points"] == 0

    # tft match: own_actions = [C,C,D,C,C] -> coop rate 4/5, 2 switches.
    tft = by_opp["tft"]
    assert tft["cooperation_rate"] == pytest.approx(0.8)
    assert tft["switch_points"] == 2


def test_quicklook_raises_on_empty_input(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError):
        quicklook.run(empty, tmp_path / "plots", tmp_path / "summary.md")


def test_quicklook_handles_int_action_encoding(tmp_path: Path) -> None:
    """OpenSpiel encodes actions as 0=C, 1=D. Quicklook must handle either."""
    results = tmp_path / "results"
    results.mkdir()
    with (results / "int_encoded.csv").open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["own_action", "opp_action", "own_payoff", "opp_payoff"])
        # 5 rounds, all cooperate (0). Coop rate should be 1.0.
        for _ in range(5):
            writer.writerow([0, 0, 3, 3])

    rows = quicklook.run(results, tmp_path / "plots", tmp_path / "summary.md")
    assert len(rows) == 1
    assert rows[0]["cooperation_rate"] == pytest.approx(1.0)
    assert rows[0]["switch_points"] == 0
