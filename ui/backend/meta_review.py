"""Day-40 meta-review surface (W2-02). Empty-state stub.

Track A's Day-40 W2-02 task lands `logs/meta_review.jsonl`. This module
ships on Day 9 as a polling-ready stub so the dashboard's
MetaReviewPanel exists before the data does — when the log is absent,
the endpoint returns `{available: false, …, note: "awaiting Day-40
meta-review outputs"}` and the panel renders that message rather than
a 404.

Once the log lands, this module is the place to add per-row parsing
(`hypothesis_id`, `meta_reviewer`, `novelty_score`, etc. — exact shape
TBD when Track A's writer ships). Until then the panel is a count +
empty-state render.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


def compute_meta_review_summary(log_path: Path) -> Dict[str, Any]:
    """Return the empty-state-aware summary the MetaReviewPanel renders.

    - File missing → `available=false`, note flags "awaiting".
    - File present but empty → `available=true`, `total_runs=0`, note
      says the log exists but no rows yet.
    - File present with rows → `available=true`, `total_runs=N`, with
      `recent_runs` left empty for now (Day-40 fills this in when the
      record shape is known).
    """
    path = Path(log_path)
    if not path.exists():
        return {
            "available": False,
            "total_runs": 0,
            "recent_runs": [],
            "note": "logs/meta_review.jsonl not present yet — awaiting "
                    "Day-40 W2-02 meta-review outputs.",
        }
    total = 0
    try:
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    json.loads(raw)
                except json.JSONDecodeError:
                    continue
                total += 1
    except OSError:
        return {
            "available": False,
            "total_runs": 0,
            "recent_runs": [],
            "note": "logs/meta_review.jsonl unreadable.",
        }
    if total == 0:
        note = ("logs/meta_review.jsonl is present but empty — Day-40 "
                "meta-review has not produced output yet.")
    else:
        note = (f"{total} meta-review row(s) present — per-row render "
                "lands when Track A finalizes the record shape (Day 40).")
    return {"available": True, "total_runs": total,
            "recent_runs": [], "note": note}
