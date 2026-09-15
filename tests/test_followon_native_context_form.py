"""Frozen 32K/64K task capacity under the separate native 69K parent."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from bench.flash_next_ab import followon_context as context
from bench.flash_next_ab import followon_dispatch as grouped
from bench.flash_next_ab import followon_prepare as first
from bench.flash_next_ab.followon_profiles import MIA_CTX69632


def _blocks():
    return [
        {"kind": "context", "endpoint_name": "flash_next_mia",
         "seed_block": None, "target_block": band}
        for band in (32768, 65536)
    ]


def test_native_form_requires_both_ordered_packet_bands():
    assert grouped._shape("selected-native-context-stress-v1",
                          "flash", _blocks())
    assert not grouped._shape("selected-native-context-stress-v1",
                              "flash", _blocks()[::-1])
    assert not grouped._shape("selected-native-context-stress-v1",
                              "resident", _blocks())
    assert sum(grouped.CONTEXT_CEILINGS[band]
               for band in (32768, 65536)) == 10_080
    assert 10_080 + grouped.RESTORE_RESERVE < grouped.OUTER_DEADLINE


def test_actual_frozen_public_packets_require_qualified_69k_capacity():
    route = first._routes(first._parents(first.PARENT_ID))["flash_next_mia"]
    route["max_model_len"] = MIA_CTX69632.max_model_len
    plan = context.freeze_plan("flash_next_mia", route)
    tokenized = context._retokenize(plan, context.validate_plan(plan))
    by_id = {row.cell_id: row for row in tokenized}
    for band in (32768, 65536):
        selected = [cell for cell in plan["declared_cells"]
                    if cell["target_input_tokens"] == band]
        assert len(selected) == 12
        assert all(by_id[cell["cell_id"]].supported for cell in selected)
    route["max_model_len"] = 32768
    c0 = context.freeze_plan("flash_next_mia", route)
    unsupported = context._retokenize(c0, context.validate_plan(c0))
    c0_by_id = {row.cell_id: row for row in unsupported}
    assert all(not c0_by_id[cell["cell_id"]].supported
               for cell in plan["declared_cells"]
               if cell["target_input_tokens"] == 65536)


def test_native_builder_rejects_c0_parent_before_publishing(
    tmp_path, monkeypatch,
):
    from bench.flash_next_ab import followon_repair_prepare as builder
    from bench.flash_next_ab.followon_profiles import MIA

    monkeypatch.setattr(builder, "load_parent",
                        lambda *_: SimpleNamespace(
                            spec=MIA,
                            qualification_summary={"max_model_len": 32768},
                        ))
    source = tmp_path / "qualified-c0.json"
    with pytest.raises(ValueError, match="native profile"):
        builder.prepare_native_context(
            "qfn-followon-native-unsupported", v5_parent_path=source
        )
    assert not source.exists()
