"""exp004 combinatorial-auction summary reader.

Read-only over experiments/exp004_combinatorial_auction/results/summary.json.
The UI never writes there; the experiment driver (primary session) does.

The summary's shape (per the experiment's own writer):

    {
      "per_mechanism": [
        {"mechanism", "truthful_fraction", "mean_efficiency",
         "mean_revenue", "parse_failure_rate", "verdict"},
        ...
      ],
      "n_trials": <int>
    }

`compute_exp004_summary` degrades the same way for every missing case
(file absent, unreadable, malformed JSON, no per_mechanism array): it
returns ``{"available": False, "per_mechanism": [], "n_trials": None}``
so the panel renders an explicit empty-state rather than an error.
"""
import json
from pathlib import Path

# Numeric fields we forward as floats; non-numeric values become None so
# the frontend renders "n/a" rather than crashing on a stray string.
_NUMERIC_FIELDS = ("truthful_fraction", "mean_efficiency", "mean_revenue",
                   "parse_failure_rate")


def _as_float(value):
    return value if isinstance(value, (int, float)) else None


def compute_exp004_summary(results_path):
    """Return ``{available, per_mechanism, n_trials}``.

    `available` is True only when the file parses to a dict with a list
    `per_mechanism`. Each mechanism row is projected onto the fields the
    panel reads; unknown extra fields are dropped, missing fields are None.
    """
    empty = {"available": False, "per_mechanism": [], "n_trials": None}
    path = Path(results_path)
    if not path.exists():
        return empty
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty
    if not isinstance(data, dict):
        return empty
    raw = data.get("per_mechanism")
    if not isinstance(raw, list):
        return empty

    rows = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        row = {
            "mechanism": entry.get("mechanism")
            if isinstance(entry.get("mechanism"), str) else None,
            "verdict": entry.get("verdict")
            if isinstance(entry.get("verdict"), str) else None,
        }
        for field in _NUMERIC_FIELDS:
            row[field] = _as_float(entry.get(field))
        rows.append(row)

    n_trials = data.get("n_trials")
    return {
        "available": True,
        "per_mechanism": rows,
        "n_trials": n_trials if isinstance(n_trials, int) else None,
    }
