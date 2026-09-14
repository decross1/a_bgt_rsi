import json
import subprocess

import pytest

from tools.research_archive import create, verify


def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=T", "-c", "user.email=t@example.invalid", "commit", "--allow-empty", "-qm", "base"], check=True)
    (root / "memory").mkdir()
    (root / "memory/evidence.jsonl").write_text('{"prior":true}\n')
    return root


def test_archive_preserves_bytes_excludes_named_credentials_and_does_not_follow_links(tmp_path):
    root = repo(tmp_path)
    (root / "memory/.env").write_text("SECRET=yes")
    (root / "memory/link").symlink_to(root / "memory/.env")
    archive = tmp_path / "archive"
    result = create(root, archive)
    assert result["file_count"] == 1
    assert verify(archive)["status"] == "verified"
    assert (root / "memory/evidence.jsonl").read_text() == '{"prior":true}\n'
    assert (archive / "files/repository/memory/evidence.jsonl").read_bytes() == (root / "memory/evidence.jsonl").read_bytes()
    assert not (archive / "files/repository/memory/.env").exists()
    assert len(json.loads((archive / "manifest.json").read_text())["excluded"]) == 2


def test_archive_refuses_overwrite_and_detects_tampering(tmp_path):
    root = repo(tmp_path)
    archive = tmp_path / "archive"
    create(root, archive)
    with pytest.raises(ValueError, match="fresh"):
        create(root, archive)
    (archive / "files/repository/memory/evidence.jsonl").write_text("changed")
    with pytest.raises(ValueError, match="checksum"):
        verify(archive)


def test_archive_cannot_live_inside_source_or_redirect(tmp_path):
    root = repo(tmp_path)
    with pytest.raises(ValueError, match="external"):
        create(root, root / "snapshot")
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError, match="unredirected"):
        create(alias, tmp_path / "archive")


def test_verify_rejects_unlisted_files_and_symlinks(tmp_path):
    root = repo(tmp_path)
    archive = tmp_path / "archive"
    create(root, archive)
    unexpected = archive / "files/unlisted.txt"
    unexpected.write_text("unexpected")
    with pytest.raises(ValueError, match="unlisted"):
        verify(archive)
    unexpected.unlink()
    unexpected.symlink_to(root / "memory/evidence.jsonl")
    with pytest.raises(ValueError, match="redirected"):
        verify(archive)
