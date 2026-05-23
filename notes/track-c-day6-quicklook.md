# Track C — Day 6 scratch: quicklook drafting

Drafted on 2026-05-23 in worktree `day6-quicklook`. Files written:

- `experiments/exp001_repeated_pd/quicklook.py`
- `tests/test_quicklook.py`

Intended for Track A to consume Day 7 morning after merge.

## CLI contract

```
python3 experiments/exp001_repeated_pd/quicklook.py \
    --input   <results-dir>      # one CSV per opponent
    --output-dir <plots-dir>     # PNGs written here
    --analysis-md <markdown-path>
```

Importable surface (used by the test): `quicklook.run(input_dir,
output_dir, analysis_md) -> List[dict]`. Each dict has keys
`opponent, cooperation_rate, mean_payoff, switch_points`.

## CSV schema (assumed)

Rows are rounds in play order. Columns:

| column      | type   | notes                                    |
| ----------- | ------ | ---------------------------------------- |
| own_action  | str/int| `"C"`/`"D"` or OpenSpiel `0`/`1` (0=C)   |
| opp_action  | str/int| same encoding                            |
| own_payoff  | int    | round payoff for the LLM player          |
| opp_payoff  | int    | round payoff for the fixed-strategy opp  |

Opponent label = CSV file stem (`tft.csv` → `tft`). Plot file naming:
`<opponent>_cumulative_payoff.png`.

## Metric definitions

- **cooperation rate**: `mean(own_action == C)` across rounds.
- **mean payoff**: `mean(own_payoff)` — own side only, so the LLM's
  per-round score. The opponent's cumulative payoff is plotted but not
  tabulated.
- **switch points**: number of round-to-round changes in `own_action`
  (e.g. C→D or D→C). 0 means a pure stationary policy across the
  match; high counts mean a thrashing policy.

These match the spec in `AGENT_PLAN.md` Day 6 prompt verbatim — no
extra metrics were added (Track A may add them on Day 7 if they want).

## Notes for the Track A reviewer

1. **Headless backend.** `matplotlib.use("Agg")` is set before
   `pyplot` import so the script runs in a Track A SSH session or CI
   without a display.
2. **No LLM, no ChromaDB, no network.** The script is pure pandas /
   matplotlib over local CSVs. Safe to run on the GPU host without
   touching `LOCAL_LLM_BASE_URL` (Track C is forbidden from doing so
   anyway).
3. **Action encoding tolerance.** `_is_cooperate` accepts both `"C"`
   and `0` (and their string forms `"c"`, `"0"`). The Day-7 runner can
   write whichever encoding is easier; the strategies file in this
   repo uses string `"C"`/`"D"` externally and `0`/`1` ints internally
   (see `experiments/exp001_repeated_pd/strategies.py` ACTION_INT).
4. **No `requirements.txt` change.** Pandas + matplotlib pins live in
   the test docstring only. Track A decides whether to promote them.
5. **Opponents.** Test fixture uses `tft, grim, all_c, all_d, random`.
   The fifth slot ("random") is a placeholder for whatever Day 7
   expands to — quicklook is opponent-name-agnostic; it just walks
   `*.csv`.
6. **Switch-point semantics.** Counted on `own_action` only, not the
   joint (own, opp) pair. If Track A wants joint-state transitions,
   that's a one-line extension.

## What I did NOT do (and why)

- Did not modify `requirements.txt`. Track A owns global deps.
- Did not write `run_state/`. Track C is read-only there.
- Did not call the vLLM endpoint or any localhost service.
- Did not exercise ChromaDB. The script does not need it.
- Did not add a plot for joint cooperation timeline / payoff
  difference / regret. Out of scope for the Day-6 spec.

## Test setup notes

- venv: `.venv-quicklook/` (gitignored via `.venv-*/` glob in
  `.gitignore`); pandas 2.2.3, matplotlib 3.9.2, pytest 8.3.3.
- The test file pins the same versions in its docstring so the
  reviewer knows what was used.
- Run with `.venv-quicklook/bin/pytest tests/test_quicklook.py -v`.
