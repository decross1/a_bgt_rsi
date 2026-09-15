"""Exact read-only replay of the previously qualified reduced v5 parent.

The prospective coding checkout has a different controller source bundle.
This bridge verifies the old 39-file snapshot and invokes its unchanged
parent gate in the old registered interpreter. It cannot admit a new parent.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from .harness import _read_regular_file

OLD_ROOT = Path(
    "/home/decross1/projects/a_bgt_rsi_worktrees/flash-followon-20260915"
)
OLD_MODULE_ROOT = OLD_ROOT / "bench/flash_next_ab"
QUALIFICATION_RUN_ID = "qfn-mia-mtp3-red47k-20260915-a"
RESULT_SHA256 = "d0492c9146fc352d8bf73155d132d630e0f29d9042d48314861c6fbbb19006ee"
OLD_SOURCE_BUNDLE_SHA256 = "87b1adb040a36f7700e382bef52b25cfdf00b766f808f6f46df6188bc9e42908"
PARENT_SHA256 = "338e86bd0a929dc3b9c445a5758481bc3f0d897728050eda30c852e29461f796"
PARENT_PATH = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/"
    "qwen-flash-next-research/evaluation/followon-qualified-parents/"
    f"{QUALIFICATION_RUN_ID}.json"
)
OUTPUT_LIMIT = 16_384
TIMEOUT_SECONDS = 30
REPLAY_SCHEMA = "flash-coding-temp1-historical-v5-parent-replay/v1"

_OLD_REPLAY = """\
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path[:0] = [str(root), str(root / 'ui')]
from bench.flash_next_ab.followon_v5_parent import load_parent
parent = load_parent(Path(sys.argv[2]))
print(json.dumps({'schema': 'flash-coding-temp1-historical-v5-parent-replay/v1',
                  'source_sha256': parent.source_sha256,
                  'qualification_summary': parent.qualification_summary},
                 sort_keys=True, allow_nan=False))
"""


class HistoricalParentError(ValueError):
    pass


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise HistoricalParentError(message)


def _raw(path: Path, *, maximum: int) -> bytes:
    raw, observed = _read_regular_file(
        path, label="historical v5 parent source", max_bytes=maximum,
    )
    _require(observed == path.absolute(), "historical parent path redirected")
    return raw


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_sha(value: Any) -> str:
    return _sha(json.dumps(value, sort_keys=True, separators=(",", ":"),
                           allow_nan=False).encode())


def _verify_old_sources(recorded: dict) -> None:
    _require(isinstance(recorded, dict) and len(recorded) == 39
             and _canonical_sha(recorded) == OLD_SOURCE_BUNDLE_SHA256,
             "historical controller bundle identity differs")
    _require(OLD_ROOT.is_dir() and not OLD_ROOT.is_symlink()
             and OLD_ROOT.resolve() == OLD_ROOT,
             "historical controller root redirected")
    for name, descriptor in recorded.items():
        _require(isinstance(name, str) and name == Path(name).name
                 and isinstance(descriptor, dict)
                 and set(descriptor) == {"path", "sha256", "bytes"}
                 and descriptor["path"] == str(OLD_MODULE_ROOT / name)
                 and type(descriptor["bytes"]) is int
                 and 0 < descriptor["bytes"] <= 2_000_000,
                 "historical controller path or descriptor differs")
        raw = _raw(OLD_MODULE_ROOT / name, maximum=2_000_000)
        _require(len(raw) == descriptor["bytes"]
                 and _sha(raw) == descriptor["sha256"],
                 "historical controller source bytes drifted")


def replay_reduced_parent(raw: dict[str, bytes], sources: dict[str, Path],
                          recorded_plan: dict, spec: Any) -> dict:
    """Return only the old gate's admitted content-free summary."""
    _require(sources["result.json"].parent.name == QUALIFICATION_RUN_ID
             and _sha(raw["result.json"]) == RESULT_SHA256
             and recorded_plan.get("registered_code_root") == str(OLD_ROOT)
             and recorded_plan.get("followon_source_bundle_sha256")
                == OLD_SOURCE_BUNDLE_SHA256
             and spec.run_id_prefix == "qfn-mia-mtp3-red47k-"
             and recorded_plan.get("candidate", {}).get("id") == spec.spec_id,
             "historical reduced parent run/profile differs")
    _verify_old_sources(recorded_plan.get("followon_source_bundle"))
    _require(_sha(_raw(PARENT_PATH, maximum=1_000_000)) == PARENT_SHA256,
             "historical admitted parent descriptor drifted")
    launcher = OLD_ROOT / ".venv-chroma/bin/python"
    _require(launcher.is_file() and not launcher.is_dir()
             and launcher.resolve() == Path("/usr/bin/python3.12"),
             "historical registered Python launcher changed")
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    try:
        replay = subprocess.run(
            [str(launcher), "-I", "-c", _OLD_REPLAY,
             str(OLD_ROOT), str(PARENT_PATH)],
            cwd=OLD_ROOT, env=environment, text=True,
            capture_output=True, check=False, timeout=TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HistoricalParentError("historical parent gate could not finish") from exc
    _require(replay.returncode == 0
             and 0 < len(replay.stdout.encode()) <= OUTPUT_LIMIT,
             "unchanged historical parent gate rejected this receipt")
    try:
        received = json.loads(replay.stdout)
    except (UnicodeError, ValueError, TypeError) as exc:
        raise HistoricalParentError("historical gate output malformed") from exc
    _require(isinstance(received, dict)
             and set(received) == {"schema", "source_sha256",
                                   "qualification_summary"}
             and received["schema"] == REPLAY_SCHEMA
             and received["source_sha256"] == PARENT_SHA256,
             "historical gate replay identity differs")
    summary = received["qualification_summary"]
    _require(isinstance(summary, dict)
             and summary.get("admission_eligible") is True
             and summary.get("status") == "passed"
             and summary.get("variant_id") == spec.spec_id
             and summary.get("qualification_receipt_sha256") == RESULT_SHA256
             and summary.get("qualification_plan_sha256")
                == _canonical_sha(recorded_plan),
             "historical gate summary is not the reduced passed parent")
    return summary
