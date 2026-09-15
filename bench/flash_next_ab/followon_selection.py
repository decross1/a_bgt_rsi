"""Exact source selector for the existing two supervisor CLIs.

The portfolio path/loader stays bound to its original source root. A new
follow-on plan is admitted only in its separate registered namespace/root.
This module selects an input kind; it never starts or stops a service.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bench.flash_next_ab import evaluation_window as ew
from bench.flash_next_ab import followon_dispatch as followon


class SelectionError(ValueError):
    pass


@dataclass(frozen=True)
class Selection:
    kind: str
    window: Any
    registered_code_root: Path


def select_window(source_path: str | Path, *, cohort: str) -> Selection:
    """Keep the original loader byte behavior; add one disjoint follow-on path."""
    if cohort not in {"flash", "resident"}:
        raise SelectionError("cohort is outside the registered windows")
    candidate = Path(source_path)
    if not candidate.is_absolute():
        raise SelectionError("window path must be absolute")
    source = Path(os.path.abspath(candidate))
    if source.parent == ew.WINDOW_PLAN_ROOT:
        original = ew.load_evaluation_window(source, expected_cohort=cohort)
        return Selection("portfolio", original, ew.REGISTERED_CODE_ROOT)
    followon_root = followon.RESEARCH_ROOT / "evaluation/followon-window-plans"
    if source.parent != followon_root:
        raise SelectionError("window is outside both registered namespaces")
    suffix = f".{cohort}.json"
    if not source.name.endswith(suffix):
        raise SelectionError("follow-on source cohort differs")
    window_id = source.name[: -len(suffix)]
    if followon.WINDOW_ID.fullmatch(window_id) is None:
        raise SelectionError("follow-on source ID differs")
    frozen = followon.load_window(window_id, cohort)
    if frozen.path != source:
        raise SelectionError("follow-on source path changed")
    return Selection("followon", frozen, followon.FOLLOWON_CODE_ROOT)
