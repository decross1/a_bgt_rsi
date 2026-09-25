from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_thesis_brief_assigns_selection_to_oracle_not_the_owner():
    brief = " ".join((ROOT / "docs/v2/THESIS_BRIEF_2026-09-23.md").read_text().split())

    assert "Oracle selects one after independent meta-oracle review" in brief
    assert "Owner approval is required only for any later live-trading action" in brief
    for stale_authority in ("owner picks one", "owner selects one", "owner chooses one"):
        assert stale_authority not in brief.lower()
