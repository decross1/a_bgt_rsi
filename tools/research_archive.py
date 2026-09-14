#!/usr/bin/env python3
"""Create and verify a local, non-destructive research archive.

The snapshot has per-file cutoffs, not transactional consistency across live
ledgers. It never moves source files or follows symlinks. Named credential paths
are excluded; private archive contents are not content-classified.
Archives stay outside checkouts; raw research is not a public Git artifact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

RESEARCH_DIRS = ("experiments", "bench", "docs", "notes/research", "human", "logs", "books", "archive", "tasks",
                 "journal", "memory", "findings", "README.md", "START_HERE.md",
                 "CLAUDE.md", "AGENTS.md", "ARCHITECTURE.md", "PROJECT_CONTEXT.md",
                 "LOOP_V0.md", "LOOP_V1.md", "DECISIONS.md", "chroma_db/manifest.json")
STATE_NAMES = ("loop_memory.jsonl", "coordinator_cycles.jsonl", "frontier_calls.jsonl",
               "events.jsonl", "health_signals.jsonl", "week1.run.jsonl", "week1.state.json",
               "weekly_upgrade_budget.jsonl", "weekly_upgrade", "iteration_cache",
               "surfaced_findings.jsonl", "gate_verdicts.jsonl")
EXCLUDED_NAMES = {".git", "__pycache__", ".pytest_cache", "node_modules", ".venv", "venv", "codex_home"}
MAX_FILE_BYTES = 2_000_000_000
MAX_TOTAL_BYTES = 10_000_000_000
MAX_ARCHIVE_ENTRIES = 200_000


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while data := stream.read(1024 * 1024):
            digest.update(data)
    return digest.hexdigest()


def excluded(path):
    return any(part in EXCLUDED_NAMES or part.startswith(".venv-") for part in path.parts) or path.name.startswith(".env") or path.suffix in {".pem", ".key"}


def collect(root, selected):
    """Enumerate only named research roots; no arbitrary home/config sweep."""
    found, skipped = [], []
    for relative in selected:
        origin = root / relative
        if not origin.exists() and not origin.is_symlink():
            continue
        pending = [origin]
        while pending:
            item = pending.pop()
            rel = item.relative_to(root)
            if excluded(rel):
                skipped.append({"path": str(rel), "reason": "excluded_nonresearch_or_credential_path"})
            elif item.is_symlink() or item.resolve() != item:
                skipped.append({"path": str(rel), "reason": "symlink_not_followed"})
            elif item.is_dir():
                pending.extend(sorted(item.iterdir(), reverse=True))
            elif item.is_file():
                found.append(item)
            else:
                skipped.append({"path": str(rel), "reason": "nonregular_file"})
    return sorted(set(found)), skipped


def create(root, destination, *, extra_roots=()):
    root = Path(root).absolute()
    destination = Path(destination).absolute()
    if root.is_symlink() or root.resolve() != root or not (root / ".git").exists():
        raise ValueError("source must be an unredirected Git checkout")
    sources = [("repository", root, (*RESEARCH_DIRS, *("run_state/" + n for n in STATE_NAMES)))]
    for i, extra in enumerate(extra_roots):
        extra = Path(extra).absolute()
        if not extra.is_dir() or extra.is_symlink() or extra.resolve() != extra:
            raise ValueError("extra research root must be a regular directory")
        sources.append((f"external-{i+1}", extra, (".",)))
    if destination.exists() or destination.resolve() != destination or any(destination == r or r in destination.parents for _, r, _ in sources):
        raise ValueError("archive needs a fresh external unredirected destination")
    files, skipped = [], []
    for label, source, selected in sources:
        selected_files, omissions = collect(source, selected)
        files.extend((label, source, p) for p in selected_files)
        skipped.extend({"source": label, **row} for row in omissions)
    if sum(p.stat().st_size for _, _, p in files) > MAX_TOTAL_BYTES:
        raise ValueError("research archive exceeds the declared total bound")
    destination.mkdir(parents=True, mode=0o700)
    manifest = {"schema_version": "research-archive/v1", "status": "copying",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "snapshot_consistency": "per_file_cutoffs_not_global_transaction",
                "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
                "sources": [{"id": label, "path": str(source)} for label, source, _ in sources],
                "excluded": skipped, "files": []}
    copied_bytes = 0
    for label, source, path in files:
        relative = Path(label) / path.relative_to(source)
        target = destination / "files" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as inp, target.open("xb") as out:
            before = os.fstat(inp.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE_BYTES:
                raise ValueError("source is nonregular or exceeds the file bound")
            copied_bytes += before.st_size
            if copied_bytes > MAX_TOTAL_BYTES:
                raise ValueError("research archive exceeds the declared total bound during copy")
            left, digest = before.st_size, hashlib.sha256()
            while left:
                data = inp.read(min(left, 1024 * 1024))
                if not data:
                    raise ValueError("source was truncated during snapshot")
                out.write(data)
                digest.update(data)
                left -= len(data)
            out.flush()
            os.fsync(out.fileno())
            # A live append is acceptable; an in-place rewrite of the captured
            # prefix is not. Re-read that exact prefix before crediting it.
            inp.seek(0)
            check, left = hashlib.sha256(), before.st_size
            while left:
                data = inp.read(min(left, 1024 * 1024))
                if not data:
                    raise ValueError("source prefix disappeared during verification")
                check.update(data)
                left -= len(data)
            if check.digest() != digest.digest():
                raise ValueError("source prefix changed during snapshot")
            after = os.fstat(inp.fileno())
        if before.st_size == after.st_size and before.st_mtime_ns != after.st_mtime_ns:
            raise ValueError("source was rewritten during snapshot; archive is incomplete")
        manifest["files"].append({"path": relative.as_posix(), "bytes": before.st_size,
                                  "sha256": digest.hexdigest(), "source_mtime_ns": before.st_mtime_ns,
                                  "source_grew_during_copy": after.st_size > before.st_size})
    manifest["status"] = "complete"
    manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
    manifest["file_count"] = len(manifest["files"])
    manifest["bytes"] = sum(row["bytes"] for row in manifest["files"])
    raw = canonical(manifest) + b"\n"
    (destination / "manifest.json").write_bytes(raw)
    (destination / "manifest.sha256").write_text(hashlib.sha256(raw).hexdigest() + "\n")
    verify(destination)
    return {k: manifest[k] for k in ("status", "file_count", "bytes", "created_at", "completed_at")}


def verify(destination):
    root = Path(destination).absolute()
    if root.is_symlink() or root.resolve() != root:
        raise ValueError("archive directory is redirected")
    for name in ("manifest.json", "manifest.sha256"):
        path = root / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 64_000_000:
            raise ValueError("archive manifest is missing, redirected or oversized")
    raw = (root / "manifest.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != (root / "manifest.sha256").read_text().strip():
        raise ValueError("archive manifest checksum differs")
    manifest = json.loads(raw)
    if manifest.get("schema_version") != "research-archive/v1" or manifest.get("status") != "complete":
        raise ValueError("archive is not complete")
    if len(manifest["files"]) > MAX_ARCHIVE_ENTRIES or manifest["bytes"] > MAX_TOTAL_BYTES:
        raise ValueError("archive exceeds verification bounds")
    seen = set()
    for row in manifest["files"]:
        relative = PurePosixPath(row["path"])
        if relative.is_absolute() or ".." in relative.parts or str(relative) in seen:
            raise ValueError("invalid or duplicated archive path")
        seen.add(str(relative))
        path = root / "files" / relative
        if path.is_symlink() or path.resolve() != path or not path.is_file():
            raise ValueError("archived file missing or redirected")
        if path.stat().st_size != row["bytes"] or sha_file(path) != row["sha256"]:
            raise ValueError("archived research checksum differs: " + str(relative))
    if len(seen) != manifest["file_count"] or sum(r["bytes"] for r in manifest["files"]) != manifest["bytes"]:
        raise ValueError("archive totals differ")
    actual, pending, entries = set(), [root / "files"], 0
    while pending:
        current = pending.pop()
        entries += 1
        if entries > MAX_ARCHIVE_ENTRIES:
            raise ValueError("archive exceeds verification entry bound")
        if current.is_symlink() or current.resolve() != current:
            raise ValueError("archive contains redirected entries")
        if current.is_dir():
            with os.scandir(current) as children:
                for child in children:
                    if len(pending) + entries >= MAX_ARCHIVE_ENTRIES:
                        raise ValueError("archive exceeds verification entry bound")
                    pending.append(Path(child.path))
        elif current.is_file():
            actual.add(current.relative_to(root / "files").as_posix())
        else:
            raise ValueError("archive contains a nonregular entry")
    if actual != seen:
        raise ValueError("archive contains unlisted files or missing manifest entries")
    return {"status": "verified", "file_count": len(seen), "bytes": manifest["bytes"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("create", "verify"))
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--extra-root", type=Path, action="append", default=[])
    args = parser.parse_args()
    if args.mode == "create" and args.repo is None:
        parser.error("create requires --repo")
    result = create(args.repo, args.archive, extra_roots=args.extra_root) if args.mode == "create" else verify(args.archive)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
