"""Off-tree UI-only isolated source-plan reconstruction for follow-on windows.

The frozen runner source records an absolute registered worktree path. A
canonical UI import gives its manifest a different REPO_ROOT even with equal
bytes. This worker validates in the fixed registered checkout without changing
the threaded backend's sys.path or module globals. It launches no model and
reads no private response. Apply only after the live GPU window restores.
"""
from __future__ import annotations

import copy
import functools
import os
import selectors
import signal
import subprocess
import threading
import time
from pathlib import Path

from . import model_runtime as mr

CODE_ROOT = Path(
    "/home/decross1/projects/a_bgt_rsi_worktrees/flash-followon-20260915"
)
PYTHON = CODE_ROOT / ".venv-chroma/bin/python"
MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_BOUND_BYTES = 8 * 1024 * 1024
MAX_WORKER_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_WORKER_SECONDS = 30
_WORKER_LOCK = threading.Lock()

_WORKER = """
import json, sys
from pathlib import Path
from bench.flash_next_ab import followon_plans as plans
source, cohort, output = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
window = plans.load_execution(source, cohort=cohort)
plan = (plans.flash_plan(window, output) if cohort == 'flash'
        else plans.resident_plan(window, output))
value = {
  'source_sha256': window.source_sha256,
  'document': window.document,
  'qualification_plan': window.qualification_plan,
  'plan': plan,
  'v5_parent': window.v5_parent is not None,
}
sys.stdout.write(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False))
"""


def _bound_ref(value: object, root: Path, *, label: str,
               maximum: int = MAX_BOUND_BYTES) -> str:
    """Refresh a SHA-bound public source before consulting the plan cache."""
    _require(isinstance(value, dict) and isinstance(value.get("path"), str)
             and isinstance(value.get("sha256"), str),
             f"{label} reference is malformed")
    path = Path(value["path"])
    _require(path.is_absolute() and path.is_relative_to(root)
             and not any(part in {".", ".."} for part in path.parts),
             f"{label} path is outside registration")
    digest = mr._sha256(mr._read_path(path, maximum=maximum, label=label))
    _require(digest == value["sha256"], f"{label} bytes changed")
    return digest


def _raw_fingerprint(source: Path, cohort: str) -> tuple[str, ...]:
    from bench.flash_next_ab import evaluation_window as ew
    from bench.flash_next_ab import followon_dispatch as grouped

    _source = mr._read_path(source, maximum=MAX_SOURCE_BYTES,
                            label="frozen follow-on window")
    window = mr._strict_object(_source, "frozen follow-on window")
    _require(source.parent == grouped.RESEARCH_ROOT /
             "evaluation/followon-window-plans"
             and source.name.endswith(f".{cohort}.json")
             and window.get("cohort") == cohort
             and window.get("window_id")
                == source.name.removesuffix(f".{cohort}.json"),
             "follow-on window source is outside registration")
    bundle = grouped.frozen_followon_source_bundle()
    _require(bundle == window.get("followon_source_bundle")
             and grouped._canonical_sha(bundle)
                == window.get("followon_source_bundle_sha256"),
             "registered follow-on source bytes differ")
    blocks = window.get("blocks")
    _require(isinstance(blocks, list) and 1 <= len(blocks) <= 7,
             "registered follow-on blocks are malformed")
    fingerprints = [mr._sha256(_source), grouped._canonical_sha(bundle)]
    for block in blocks:
        _require(isinstance(block, dict)
                 and isinstance(block.get("block_id"), str)
                 and block.get("plan_path") == str(
                     grouped.RESEARCH_ROOT / "evaluation/followon-block-plans" /
                     f"{block['block_id']}.json"
                 ), "follow-on block source path differs")
        raw = mr._read_path(Path(block["plan_path"]),
                            maximum=MAX_SOURCE_BYTES,
                            label="registered follow-on block source")
        digest = mr._sha256(raw)
        _require(digest == block.get("plan_raw_sha256"),
                 "follow-on block source bytes changed")
        fingerprints.append(digest)
        block_document = mr._strict_object(raw,
                                            "registered follow-on block source")
        evidence = block_document.get("source")
        _require(evidence is None or isinstance(evidence, dict),
                 "registered block source evidence is malformed")
        evidence = evidence or {}
        for path_key, sha_key in (
            ("manifest_path", "manifest_sha256"),
            ("pack_path", "pack_sha256"),
            ("tokenization_path", "tokenization_sha256"),
            ("tokenization_execution_path", "tokenization_execution_sha256"),
        ):
            if path_key in evidence:
                text = evidence[path_key]
                _require(isinstance(text, str),
                         "registered block external path is malformed")
                path = Path(text)
                registered_root = (
                    CODE_ROOT if path.is_relative_to(CODE_ROOT)
                    else grouped.RESEARCH_ROOT
                )
                fingerprints.append(_bound_ref(
                    {"path": text, "sha256": evidence.get(sha_key)},
                    registered_root, label=f"block {path_key}",
                ))
        files = evidence.get("source_files")
        if files is not None:
            _require(isinstance(files, dict) and 1 <= len(files) <= 12,
                     "registered block source-file refs are malformed")
            for name in sorted(files):
                _require(isinstance(name, str) and len(name) <= 256,
                         "registered block source-file name is malformed")
                if name == "context_sweep.py":
                    path = CODE_ROOT / "bench/flash_next_ab/followon_context.py"
                else:
                    path = Path(name)
                    if not path.is_absolute():
                        path = CODE_ROOT / path
                registered_root = (
                    CODE_ROOT if path.is_relative_to(CODE_ROOT)
                    else grouped.RESEARCH_ROOT
                )
                fingerprints.append(_bound_ref(
                    {"path": str(path), "sha256": files[name]},
                    registered_root, label=f"block source file {name}",
                ))
    parent = window.get("qualified_parent_window")
    _require(isinstance(parent, dict) and isinstance(parent.get("path"), str)
             and Path(parent["path"]).parent
                == grouped.RESEARCH_ROOT / "evaluation/window-plans",
             "qualified parent source path differs")
    parent_raw = mr._read_path(Path(parent["path"]),
                                maximum=MAX_SOURCE_BYTES,
                                label="qualified parent source")
    parent_sha = mr._sha256(parent_raw)
    _require(parent_sha == parent.get("sha256"),
             "qualified parent source bytes changed")
    fingerprints.append(parent_sha)
    parent_document = mr._strict_object(parent_raw, "qualified parent source")
    qualification = parent_document.get("qualification")
    benchmark = parent_document.get("benchmark")
    _require(isinstance(qualification, dict) and isinstance(benchmark, dict),
             "qualified parent bindings are malformed")
    for name in ("receipt", "qualification_plan", "contract_snapshot",
                 "contract_raw", "resident_artifacts"):
        ref = qualification.get(name)
        if ref is not None:
            fingerprints.append(_bound_ref(
                ref, grouped.RESEARCH_ROOT, label=f"qualified {name}",
            ))
    fingerprints.append(_bound_ref(
        {"path": benchmark.get("plan_path"),
         "sha256": benchmark.get("plan_file_sha256")},
        grouped.RESEARCH_ROOT / "evaluation/window-plans",
        label="qualified benchmark plan",
    ))
    # The old paired parent is a separate immutable checkout. A cached
    # expected plan must not outlive any bytes its live producer would replay.
    old_bundle = ew.frozen_controller_source_bundle()
    fingerprints.append(grouped._canonical_sha(old_bundle))
    v5_ref = window.get("v5_qualified_parent")
    if v5_ref is not None:
        v5_sha = _bound_ref(
            v5_ref, grouped.RESEARCH_ROOT /
            "evaluation/followon-qualified-parents",
            label="selected v5 parent", maximum=MAX_SOURCE_BYTES,
        )
        fingerprints.append(v5_sha)
        v5_document = mr._strict_object(
            mr._read_path(Path(v5_ref["path"]), maximum=MAX_SOURCE_BYTES,
                          label="selected v5 parent"),
            "selected v5 parent",
        )
        refs = v5_document.get("source_refs")
        _require(isinstance(refs, dict) and 1 <= len(refs) <= 8,
                 "selected v5 qualification refs are malformed")
        for name in sorted(refs):
            fingerprints.append(_bound_ref(
                refs[name], grouped.RESEARCH_ROOT / "qualification-runs",
                label=f"selected v5 {name}",
            ))
    return tuple(fingerprints)


def _require(ok: bool, reason: str) -> None:
    if not ok:
        raise mr.RuntimeSourceError(reason)


def _stop(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass


@functools.lru_cache(maxsize=16)
def _registered(source: str, cohort: str, output: str,
                fingerprints: tuple[str, ...]) -> dict:
    """Run a bounded CPU-only validator only when its registered raw inputs change."""
    _require(CODE_ROOT.is_dir() and CODE_ROOT.resolve() == CODE_ROOT
             and PYTHON.is_file() and not PYTHON.is_dir(),
             "registered follow-on interpreter is unavailable")
    env = dict(os.environ)
    for key in ("PYTHONPATH", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
                "VLLM_API_KEY", "MOCK_LLM"):
        env.pop(key, None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    command = [str(PYTHON), "-B", "-c", _WORKER,
               source, cohort, output]
    try:
        proc = subprocess.Popen(
            command, cwd=CODE_ROOT, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
    except OSError as exc:
        raise mr.RuntimeSourceError("registered follow-on validator could not start") from exc
    chunks: list[bytes] = []
    total = 0
    deadline = time.monotonic() + MAX_WORKER_SECONDS
    try:
        _require(proc.stdout is not None, "registered validator has no output pipe")
        os.set_blocking(proc.stdout.fileno(), False)
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                _require(remaining > 0, "registered validator exceeded its time bound")
                ready = selector.select(min(remaining, .2))
                if not ready and proc.poll() is not None:
                    # Allow the pipe's final bytes one more read event.
                    ready = selector.select(0)
                if not ready:
                    continue
                chunk = os.read(proc.stdout.fileno(), 64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                _require(total <= MAX_WORKER_OUTPUT_BYTES,
                         "registered validator exceeded its output bound")
                chunks.append(chunk)
        _require(proc.wait(timeout=max(.1, deadline - time.monotonic())) == 0,
                 "registered follow-on source validation failed")
        value = mr._strict_object(b"".join(chunks),
                                  "registered follow-on plan")
        _require(value.get("source_sha256") == fingerprints[0]
                 and isinstance(value.get("document"), dict)
                 and isinstance(value.get("qualification_plan"), dict)
                 and isinstance(value.get("plan"), dict)
                 and isinstance(value.get("v5_parent"), bool),
                 "registered validator output did not bind frozen source")
        return value
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise mr.RuntimeSourceError("registered validator failed within its bound") from exc
    finally:
        _stop(proc)


def registered_expected(source: Path, output: Path,
                        *, cohort: str) -> dict:
    """Return a copy of the worktree-validated plan for a live UI-only reader."""
    _require(cohort in {"flash", "resident"},
             "registered validator cohort is invalid")
    source, output = Path(source).absolute(), Path(output).absolute()
    fingerprints = _raw_fingerprint(source, cohort)
    # lru_cache alone allows duplicate concurrent misses; serialize the cold
    # CPU validator so several dashboard viewers cannot multiply setup work.
    with _WORKER_LOCK:
        result = _registered(str(source), cohort, str(output), fingerprints)
    _require(result["document"].get("followon_source_bundle_sha256")
             == fingerprints[1],
             "registered validator source bundle changed")
    return copy.deepcopy(result)
