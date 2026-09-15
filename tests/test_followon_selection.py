"""Selector tests to copy into the separate checkout after the first pair.

These are pure registered-path tests and are not run during live measurement.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from bench.flash_next_ab import followon_selection as selector


def test_original_portfolio_uses_unchanged_loader_and_code_root(monkeypatch):
    source = selector.ew.WINDOW_PLAN_ROOT / "qfn-ab-original.flash.window.json"
    original = object()
    seen = []

    def old_loader(path, *, expected_cohort):
        seen.append((path, expected_cohort))
        return original

    monkeypatch.setattr(selector.ew, "load_evaluation_window", old_loader)
    picked = selector.select_window(source, cohort="flash")
    assert picked.kind == "portfolio"
    assert picked.window is original
    assert picked.registered_code_root == selector.ew.REGISTERED_CODE_ROOT
    assert seen == [(source, "flash")]


def test_followon_uses_new_registered_path_and_code_root(monkeypatch):
    source = (selector.followon.RESEARCH_ROOT / "evaluation/followon-window-plans"
              / "qfn-followon-mia-pilot.flash.json")
    frozen = SimpleNamespace(path=source)
    seen = []

    def new_loader(window_id, cohort):
        seen.append((window_id, cohort))
        return frozen

    monkeypatch.setattr(selector.followon, "load_window", new_loader)
    picked = selector.select_window(source, cohort="flash")
    assert picked.kind == "followon"
    assert picked.window is frozen
    assert picked.registered_code_root == selector.followon.FOLLOWON_CODE_ROOT
    assert seen == [("qfn-followon-mia-pilot", "flash")]


@pytest.mark.parametrize("source", [
    Path("/tmp/qfn-followon-mia-pilot.flash.json"),
    Path("/tmp/evaluation/followon-window-plans/qfn-followon-mia-pilot.flash.json"),
])
def test_outside_path_never_falls_back_to_portfolio(source):
    with pytest.raises(selector.SelectionError, match="outside both"):
        selector.select_window(source, cohort="flash")


def test_followon_file_suffix_cannot_silently_change_cohort():
    source = (selector.followon.RESEARCH_ROOT / "evaluation/followon-window-plans"
              / "qfn-followon-mia-pilot.resident.json")
    with pytest.raises(selector.SelectionError, match="source cohort differs"):
        selector.select_window(source, cohort="flash")
