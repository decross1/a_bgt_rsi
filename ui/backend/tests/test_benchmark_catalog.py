import json

import pytest

from backend import benchmark_catalog as catalog


def _fixture(tmp_path, monkeypatch):
    parent = tmp_path / "artifacts"
    parent.mkdir()
    monkeypatch.setattr(catalog, "ARTIFACT_PARENT", parent)
    repo = tmp_path / "repo"
    path = repo / catalog.CATALOG_PATH
    path.parent.mkdir(parents=True)
    value = {"schema_version": "stable-benchmark-catalog/v1", "active_release": "1.1.0",
             "releases": [
                 {"version": "1.0.0", "suite_id": "a-bgt-rsi-stable-1.0.0", "root": str(parent / "stable-benchmark"),
                  "definition_sha256": "a" * 64, "label": "Commissioning archive", "measurement_review_sha256": "c" * 64},
                 {"version": "1.1.0", "suite_id": "a-bgt-rsi-stable-1.1.0", "root": str(parent / "stable-benchmark-v1_1"),
                  "definition_sha256": "b" * 64, "label": "Fixed canary", "measurement_review_sha256": None},
             ]}
    path.write_text(json.dumps(value))
    return repo, path, value


def test_current_release_and_archive_are_explicit_separate_series(tmp_path, monkeypatch):
    repo, path, value = _fixture(tmp_path, monkeypatch)
    root, selected, options = catalog.select_program(repo)
    assert root.name == "stable-benchmark-v1_1"
    assert selected["version"] == "1.1.0"
    assert [x["selected"] for x in options] == [False, True]
    root, selected, options = catalog.select_program(repo, "1.0.0")
    assert root.name == "stable-benchmark"
    assert selected["version"] == "1.0.0"
    assert [x["selected"] for x in options] == [True, False]
    assert options[0]["href"] == "/benchmarks?release=1.0.0"


def test_missing_catalog_cannot_make_archived_release_current(tmp_path, monkeypatch):
    repo, path, _ = _fixture(tmp_path, monkeypatch)
    path.unlink()
    with pytest.raises(ValueError, match="catalog is absent"):
        catalog.select_program(repo)


def test_review_binding_must_be_digest_or_explicit_null(tmp_path, monkeypatch):
    repo, path, value = _fixture(tmp_path, monkeypatch)
    value["releases"][0]["measurement_review_sha256"] = "invalid"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        catalog.select_program(repo)


@pytest.mark.parametrize("version", ["../../etc/passwd", "99.0.0", "", "/tmp/run"])
def test_query_cannot_select_unregistered_root(tmp_path, monkeypatch, version):
    repo, _, _ = _fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        catalog.select_program(repo, version)


@pytest.mark.parametrize("damage", ["root", "duplicate", "hash", "active", "redirect"])
def test_invalid_existing_catalog_cannot_fall_back_to_legacy(tmp_path, monkeypatch, damage):
    repo, path, value = _fixture(tmp_path, monkeypatch)
    if damage == "root": value["releases"][0]["root"] = str(tmp_path / "outside")
    elif damage == "duplicate": value["releases"].append(value["releases"][0])
    elif damage == "hash": value["releases"][0]["definition_sha256"] = "wrong"
    elif damage == "active": value["active_release"] = "9.0.0"
    if damage == "redirect":
        target = tmp_path / "elsewhere.json"
        target.write_text(json.dumps(value))
        path.unlink()
        path.symlink_to(target)
    else:
        path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        catalog.select_program(repo)
