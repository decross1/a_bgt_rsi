"""A selected profile parent cannot be reused or published before admission."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bench.flash_next_ab import followon_v5_parent as parent


def test_v5_parent_refuses_unadmitted_profile_without_creating_a_source(
    tmp_path: Path, monkeypatch,
):
    root = tmp_path / "evaluation" / "followon-qualified-parents"
    root.parent.mkdir()
    monkeypatch.setattr(parent, "ROOT", root)
    monkeypatch.setattr(
        parent, "build_parent_document",
        lambda *_: (_ for _ in ()).throw(parent.V5ParentError("not admitted")),
    )
    with pytest.raises(parent.V5ParentError, match="not admitted"):
        parent.publish_parent("qfn-mia-mtp3-selected")
    assert not root.exists()


def test_v5_parent_publication_never_replaces_an_existing_descriptor(
    tmp_path: Path, monkeypatch,
):
    root = tmp_path / "evaluation" / "followon-qualified-parents"
    root.parent.mkdir()
    monkeypatch.setattr(parent, "ROOT", root)
    first = {"schema_version": parent.SCHEMA, "admission_eligible": True}
    monkeypatch.setattr(parent, "build_parent_document", lambda *_: first)
    monkeypatch.setattr(
        parent, "load_parent",
        lambda path: SimpleNamespace(document=json.loads(path.read_text())),
    )
    source = parent.publish_parent("qfn-mia-mtp3-selected")
    raw = source.read_bytes()
    monkeypatch.setattr(parent, "build_parent_document", lambda *_: {"drift": True})
    with pytest.raises(FileExistsError):
        parent.publish_parent("qfn-mia-mtp3-selected")
    assert source.read_bytes() == raw
