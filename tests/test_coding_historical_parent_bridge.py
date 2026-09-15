"""CPU-only source/gate replay of the unchanged qualified reduced parent."""
from __future__ import annotations

import copy
import json

import pytest

from bench.flash_next_ab import historical_v5_parent_bridge as bridge
from bench.flash_next_ab import followon_v5_parent as parent_gate
from bench.flash_next_ab.followon_profiles import MIA_MTP3_REDUCED47K_OPT


def _source():
    run = (bridge.PARENT_PATH.parents[2] / "qualification-runs" /
           bridge.QUALIFICATION_RUN_ID)
    paths = {name: run / name for name in parent_gate.SOURCE_NAMES}
    raw = {name: path.read_bytes() for name, path in paths.items()}
    plan = json.loads(raw["plan.json"])
    return paths, raw, plan


def test_old_reduced_parent_gate_replays_in_old_interpreter():
    admitted = parent_gate.load_parent(bridge.PARENT_PATH)
    assert admitted.source_sha256 == bridge.PARENT_SHA256
    assert admitted.qualification_summary["admission_eligible"] is True
    assert admitted.qualification_summary["qualification_receipt_sha256"] \
        == bridge.RESULT_SHA256


def test_old_bundle_or_result_tamper_rejected_before_replay():
    paths, raw, plan = _source()
    changed = copy.deepcopy(plan)
    changed["followon_source_bundle_sha256"] = "0" * 64
    with pytest.raises(bridge.HistoricalParentError, match="parent|bundle"):
        bridge.replay_reduced_parent(raw, paths, changed,
                                     MIA_MTP3_REDUCED47K_OPT)
    changed = copy.deepcopy(raw)
    changed["result.json"] += b" "
    with pytest.raises(bridge.HistoricalParentError, match="parent|profile"):
        bridge.replay_reduced_parent(changed, paths, plan,
                                     MIA_MTP3_REDUCED47K_OPT)


def test_fake_historical_gate_output_cannot_admit(monkeypatch):
    paths, raw, plan = _source()

    class FakeProcess:
        returncode = 0
        stdout = json.dumps({"schema": bridge.REPLAY_SCHEMA,
                             "source_sha256": "0" * 64,
                             "qualification_summary": {
                                 "admission_eligible": True,
                                 "qualification_receipt_sha256":
                                     bridge.RESULT_SHA256,
                             }})

    monkeypatch.setattr(bridge.subprocess, "run", lambda *args, **kwargs:
                        FakeProcess())
    with pytest.raises(bridge.HistoricalParentError, match="identity"):
        bridge.replay_reduced_parent(raw, paths, plan,
                                     MIA_MTP3_REDUCED47K_OPT)
