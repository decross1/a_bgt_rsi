"""Source-controlled benchmark release selection; query strings are not paths."""
from __future__ import annotations

import re
from pathlib import Path

CATALOG_PATH = Path("docs/benchmarks/program_catalog.json")
ARTIFACT_PARENT = Path("/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-16/ui-benchmark-eight-hour")
VERSION = re.compile(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def read_catalog(repo: Path) -> dict:
    from .benchmark_history import read_document

    path = repo / CATALOG_PATH
    if not path.exists() and not path.is_symlink():
        raise ValueError("benchmark release catalog is absent")
    catalog, _ = read_document(path, limit=16_384)
    if (set(catalog) != {"schema_version", "active_release", "releases"}
            or catalog["schema_version"] != "stable-benchmark-catalog/v1"
            or not isinstance(catalog["releases"], list)
            or not 1 <= len(catalog["releases"]) <= 8):
        raise ValueError("benchmark catalog shape differs")
    versions, roots = set(), set()
    for release in catalog["releases"]:
        if (not isinstance(release, dict)
                or set(release) != {"version", "suite_id", "root", "definition_sha256", "label", "measurement_review_sha256"}
                or not isinstance(release["version"], str)
                or VERSION.fullmatch(release["version"]) is None
                or release["suite_id"] != f"a-bgt-rsi-stable-{release['version']}"
                or not isinstance(release["definition_sha256"], str)
                or SHA256.fullmatch(release["definition_sha256"]) is None
                or (release["measurement_review_sha256"] is not None and
                    (not isinstance(release["measurement_review_sha256"], str) or
                     SHA256.fullmatch(release["measurement_review_sha256"]) is None))
                or not isinstance(release["label"], str) or not 1 <= len(release["label"]) <= 160
                or not isinstance(release["root"], str)):
            raise ValueError("benchmark catalog release differs")
        root = Path(release["root"])
        if (not root.is_absolute() or root.parent != ARTIFACT_PARENT
                or root.resolve() != root or root.is_symlink()
                or re.fullmatch(r"stable-benchmark(?:-v[0-9_]+)?", root.name) is None
                or release["version"] in versions or str(root) in roots):
            raise ValueError("benchmark catalog identity/path is invalid")
        versions.add(release["version"])
        roots.add(str(root))
    if catalog["active_release"] not in versions:
        raise ValueError("benchmark catalog active release is absent")
    return catalog


def select_program(repo: Path, version: str | None = None) -> tuple[Path, dict, list[dict]]:
    catalog = read_catalog(repo)
    selected = version if version is not None else catalog["active_release"]
    entry = next((entry for entry in catalog["releases"] if entry["version"] == selected), None)
    if entry is None:
        raise ValueError("benchmark release is not registered")
    options = [{"version": item["version"], "label": item["label"],
                "active": item["version"] == catalog["active_release"],
                "selected": item["version"] == selected,
                "href": f"/benchmarks?release={item['version']}"}
               for item in catalog["releases"]]
    return Path(entry["root"]), entry, options


def active_program_root(repo: Path) -> Path:
    return select_program(repo)[0]
