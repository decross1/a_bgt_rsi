"""One-time, content-free comparison of two admitted known-opponent pilots.

Run this file as a script from its registered report worktree. It replays the
private evidence once at publication. Readers can later verify the public raw
hashes in the no-overwrite index without replaying 108 SSE streams per poll.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import stat
import sys
from fractions import Fraction
from pathlib import Path

REPORT_ROOT = Path("/home/decross1/projects/a_bgt_rsi_worktrees/lab-mia-comparison-20260915")
SOURCE_PATH = REPORT_ROOT / "bench/agentic_game_theory/known_opponent_comparison.py"
MIA_CODE_ROOT = Path("/home/decross1/projects/a_bgt_rsi_worktrees/lab-mia-known-opponent-20260915")
MIA_CONTROLLER_PATH = MIA_CODE_ROOT / "experiments/known_opponent_utility/mia_controller.py"
MIA_CONTROLLER_SHA256 = "e2b3dcaa56b856d8fe49692351005d2052a983782d4566140afb8a31e6739760"
MIA_POLICY = {"temperature": 0.0, "top_p": 1.0, "top_k": 64, "enable_thinking": False}
ARTIFACT_ROOT = Path("/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/lab-eight-hour")
MIA_ID = "qfn-followon-known-opponent-mia-lab8h-a"
MIA_OUTPUT = ARTIFACT_ROOT / "known-opponent-utility-mia" / MIA_ID
MIA_WINDOW = MIA_OUTPUT / "window.json"
REPORT_PATH = MIA_OUTPUT / "descriptive-comparison.json"
INDEX_PATH = MIA_OUTPUT / "descriptive-comparison-index.json"
ARCHIVED_SOURCE_PATH = MIA_OUTPUT / "descriptive-comparison-source.py"
GEMMA_OUTPUT = ARTIFACT_ROOT / "known-opponent-utility/qfn-followon-known-opponent-lab8h-a"
SCHEMA = "known-opponent-mia-gemma-descriptive-comparison/v1"
INDEX_SCHEMA = "known-opponent-mia-gemma-comparison-index/v1"

class ComparisonError(ValueError):
    pass


def _must(ok: bool, reason: str) -> None:
    if not ok:
        raise ComparisonError(reason)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode()


def _registered_modules():
    """Load exact Mia sources only in this standalone publication process."""
    _must(__name__ == "__main__" and Path(__file__).absolute() == SOURCE_PATH,
          "comparison replay requires the registered direct-script entrypoint")
    sys.path.insert(0, str(MIA_CODE_ROOT))
    from experiments.known_opponent_utility import admission, mia_controller
    _must(Path(mia_controller.__file__).resolve() == MIA_CONTROLLER_PATH
          and _sha(_raw(MIA_CONTROLLER_PATH)) == MIA_CONTROLLER_SHA256,
          "frozen Mia controller import or bytes differ")
    return admission, mia_controller


def _raw(path: Path, limit: int = 2_000_000) -> bytes:
    _must(path.is_absolute() and path.is_file() and not path.is_symlink()
          and path.resolve() == path, "comparison raw path is missing or redirected")
    before = path.stat()
    _must(stat.S_ISREG(before.st_mode) and before.st_size <= limit,
          "comparison raw file is nonregular or oversized")
    raw = path.read_bytes()
    after = path.stat()
    _must(len(raw) == before.st_size and
          (before.st_ino, before.st_size, before.st_mtime_ns)
          == (after.st_ino, after.st_size, after.st_mtime_ns),
          "comparison raw file changed during read")
    return raw


def _object(path: Path) -> tuple[dict, bytes]:
    raw = _raw(path)
    def unique(pairs):
        value = {}
        for key, item in pairs:
            _must(key not in value, "comparison raw JSON repeats a field")
            value[key] = item
        return value
    try:
        value = json.loads(raw, object_pairs_hook=unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
    except (UnicodeError, ValueError) as exc:
        raise ComparisonError("comparison raw JSON is malformed") from exc
    _must(isinstance(value, dict) and raw == _canonical(value) + b"\n",
          "comparison raw JSON is not its producer form")
    return value, raw


def _ref(path: Path) -> dict:
    return {"path": str(path), "sha256": _sha(_raw(path))}


def _write_once(path: Path, value: dict) -> None:
    raw = _canonical(value) + b"\n"
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _archive_source_once() -> dict:
    """Preserve the exact report producer bytes beside historical receipts."""
    raw = _raw(SOURCE_PATH)
    if ARCHIVED_SOURCE_PATH.exists():
        _must(_raw(ARCHIVED_SOURCE_PATH) == raw,
              "archived comparison source differs from current producer")
    else:
        with ARCHIVED_SOURCE_PATH.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    return _ref(ARCHIVED_SOURCE_PATH)


def project_cell(task: dict, row: dict) -> dict:
    """Project one already-replayed cell without exporting actions or prompts."""
    cell = task["cell"]
    _must(row.get("cell") == cell and row.get("task_sha256") == task["task_sha256"],
          "comparison cell does not match the registered task")
    comp = row.get("comprehension")
    prefix = row.get("valid_prefix_actions")
    calls = row.get("calls")
    full = row.get("full_episode")
    invalid = row.get("first_invalid_round")
    _must(comp in {"passed", "failed", "unknown"}
          and type(prefix) is int and 0 <= prefix <= 8
          and isinstance(calls, list) and 1 <= len(calls) <= 9
          and row.get("scheduled_actions") == 8,
          "comparison cell has invalid public denominators")
    if prefix == 8:
        _must(invalid is None and len(calls) == 9 and isinstance(full, dict),
              "comparison full episode has incomplete action evidence")
        regret = full.get("episode_regret")
        try:
            rational = Fraction(regret)
        except (TypeError, ValueError, ZeroDivisionError) as exc:
            raise ComparisonError("comparison episode regret is not rational") from exc
        _must(rational >= 0 and str(rational) == regret,
              "comparison episode regret is not canonical")
        zero_regret = rational == 0
    else:
        _must(type(invalid) is int and invalid == prefix + 1
              and len(calls) == prefix + 2 and full is None,
              "comparison incomplete episode invented a full regret")
        regret, zero_regret = None, None
    return {
        "arithmetic_status": comp, "valid_action_prefix": prefix,
        "attempted_calls": len(calls), "first_invalid_round": invalid,
        "complete_episode": prefix == 8,
        "episode_regret": regret, "zero_regret": zero_regret,
    }


def project_arm(manifest: dict, run: dict, replay: dict) -> tuple[list[dict], dict]:
    """Require all twelve public rows to agree with the independent replay."""
    tasks, rows = manifest.get("tasks"), run.get("cells")
    _must(isinstance(tasks, list) and isinstance(rows, list)
          and len(tasks) == len(rows) == 12
          and replay.get("admission_eligible") is True
          and replay.get("recorded_episodes") == 12,
          "comparison arm is not an admitted twelve-cell schedule")
    projected = [project_cell(task, row) for task, row in zip(tasks, rows, strict=True)]
    arithmetic = sum(item["arithmetic_status"] == "passed" for item in projected)
    actions = sum(item["valid_action_prefix"] for item in projected)
    complete = sum(item["complete_episode"] for item in projected)
    zero = sum(item["zero_regret"] is True for item in projected)
    attempted = sum(item["attempted_calls"] for item in projected)
    elapsed = run.get("elapsed_s")
    _must(type(elapsed) in {int, float} and math.isfinite(elapsed)
          and 0 <= elapsed <= 960, "comparison evaluator elapsed time is invalid")
    issued_wall = 0.0
    completed_tokens = 0
    usage_reported_calls = 0
    for row in rows:
        for call in row["calls"]:
            wall = call.get("wall_s")
            _must(type(wall) in {int, float} and math.isfinite(wall)
                  and 0 <= wall <= 40, "comparison call wall time is invalid")
            issued_wall += wall
            usage = call.get("usage")
            if isinstance(usage, dict):
                tokens = usage.get("completion_tokens")
                _must(type(tokens) is int and 0 <= tokens <= 1_000_000,
                      "comparison reported completion usage is invalid")
                completed_tokens += tokens
                usage_reported_calls += 1
    _must(replay.get("comprehension_passed") == arithmetic
          and replay.get("valid_action_calls") == actions
          and replay.get("complete_episodes") == complete
          and replay.get("zero_regret_complete_episodes") == zero
          and replay.get("attempted_calls") == attempted
          and replay.get("scheduled_action_calls") == 96,
          "comparison arm counts differ from replayed denominators")
    return projected, {
        "scheduled_cells": 12, "recorded_cells": 12,
        "scheduled_action_calls": 96, "attempted_calls": attempted,
        "arithmetic_passed": arithmetic, "valid_action_calls": actions,
        "complete_episodes": complete, "zero_regret_complete_episodes": zero,
        "returned_sse_verified": replay["returned_sse_verified"],
        "evaluator_elapsed_s": elapsed,
        "issued_call_wall_s_sum": round(issued_wall, 3),
        "reported_completion_tokens": completed_tokens,
        "calls_with_reported_usage": usage_reported_calls,
    }


def _matching(gemma: dict, mia: dict) -> dict:
    fields = ("schedule", "tasks", "policy", "seed_base", "max_tokens",
              "per_call_timeout_s", "max_window_s", "max_calls", "horizon")
    _must(all(gemma.get(key) == mia.get(key) for key in fields)
          and mia["policy"] == MIA_POLICY
          and mia["seed_base"] == 301 and mia["max_tokens"] == 64
          and mia["per_call_timeout_s"] == 30.0
          and mia["max_window_s"] == 900 and mia["max_calls"] == 108
          and mia["horizon"] == 8,
          "comparison task, seed or request policy differs")
    task_hashes = [task["task_sha256"] for task in mia["tasks"]]
    return {
        "ordered_task_sha256": task_hashes,
        "task_panel_sha256": _sha(_canonical(mia["tasks"])),
        "schedule_sha256": _sha(_canonical(mia["schedule"])),
        "policy_sha256": _sha(_canonical(mia["policy"])),
        "seed_base": 301, "max_tokens": 64, "per_call_timeout_s": 30.0,
        "max_window_s": 900, "max_calls": 108, "horizon": 8,
        "fixed_game_conditions_matched": True,
        "adaptive_histories_and_later_call_seeds_may_differ": True,
    }


def build_report() -> dict:
    """Admit both parents and raw game evidence before projecting public counts."""
    admission, mia_controller = _registered_modules()
    mia_gate = mia_controller.validate_completed(MIA_WINDOW)
    mia_admission, mia_admission_raw = _object(MIA_OUTPUT / "admission.json")
    _must(mia_admission == mia_gate and mia_gate["comparison_eligible"] is False,
          "recorded Mia admission differs from independent terminal replay")
    gemma_refs, gemma_manifest = mia_controller._gemma_reference()
    gemma_admission, gemma_admission_raw = _object(GEMMA_OUTPUT / "admission.json")
    _must(_sha(gemma_admission_raw) == mia_controller.GEMMA_ADMISSION_SHA256
          and gemma_admission["comparison_eligible"] is False,
          "recorded Gemma admission differs from pinned receipt")
    gemma_replay = admission.validate_pilot(GEMMA_OUTPUT / "pilot")
    _must(gemma_replay == gemma_admission["pilot_validation"]
          and gemma_replay["admission_eligible"] is True,
          "Gemma private-response replay differs from admitted result")
    mia_manifest, mia_manifest_raw = _object(MIA_OUTPUT / "manifest.snapshot.json")
    _, mia_pilot_manifest_raw = _object(MIA_OUTPUT / "evaluation/manifest.json")
    _, gemma_pilot_manifest_raw = _object(GEMMA_OUTPUT / "pilot/manifest.json")
    _must(mia_manifest_raw == mia_pilot_manifest_raw
          and gemma_pilot_manifest_raw == _raw(GEMMA_OUTPUT / "manifest.snapshot.json")
          and mia_manifest["manifest_sha256"] == mia_gate["pilot_validation"]["manifest_sha256"],
          "pilot manifests differ from frozen parent snapshots")
    mia_run, mia_run_raw = _object(MIA_OUTPUT / "evaluation/run.json")
    gemma_run, gemma_run_raw = _object(GEMMA_OUTPUT / "pilot/run.json")
    _must(_sha(mia_run_raw) == mia_gate["pilot_run_sha256"]
          and _sha(gemma_run_raw) == gemma_admission["pilot_run_sha256"],
          "pilot run bytes differ from admitted receipts")
    matching = _matching(gemma_manifest, mia_manifest)
    gemma_cells, gemma_summary = project_arm(
        gemma_manifest, gemma_run, gemma_replay)
    mia_cells, mia_summary = project_arm(
        mia_manifest, mia_run, mia_gate["pilot_validation"])
    rows = []
    for ordinal, (task, gemma, mia) in enumerate(zip(
            mia_manifest["tasks"], gemma_cells, mia_cells, strict=True)):
        cell = task["cell"]
        rows.append({
            "ordinal": ordinal, "task_sha256": task["task_sha256"],
            "mix": cell["mix"], "objective": cell["objective"],
            "seat": cell["seat"], "neutral_rule_label": cell["rule_label"],
            "gemma": gemma, "mia": mia,
        })
    source_ref = _ref(SOURCE_PATH)
    raw_refs = {
        "gemma": {
            "admission": _ref(GEMMA_OUTPUT / "admission.json"),
            "manifest": _ref(GEMMA_OUTPUT / "manifest.snapshot.json"),
            "pilot_manifest": _ref(GEMMA_OUTPUT / "pilot/manifest.json"),
            "run": _ref(GEMMA_OUTPUT / "pilot/run.json"),
            "window": _ref(GEMMA_OUTPUT / "window.json"),
            "result": _ref(GEMMA_OUTPUT / "result.json"),
            "supervision": _ref(GEMMA_OUTPUT / "supervision.json"),
        },
        "mia": {
            "admission": _ref(MIA_OUTPUT / "admission.json"),
            "manifest": _ref(MIA_OUTPUT / "manifest.snapshot.json"),
            "pilot_manifest": _ref(MIA_OUTPUT / "evaluation/manifest.json"),
            "run": _ref(MIA_OUTPUT / "evaluation/run.json"),
            "window": _ref(MIA_OUTPUT / "window.json"),
            "result": _ref(MIA_OUTPUT / "result.json"),
            "state": _ref(MIA_OUTPUT / "state.json"),
            "supervision": _ref(MIA_OUTPUT / "supervision.json"),
            "supervision_start": _ref(MIA_OUTPUT / "supervision-start.json"),
            "supervision_reservation": _ref(MIA_OUTPUT / "supervision-reservation.json"),
            "ready_proof": _ref(MIA_OUTPUT / "admission-ready-proof.json"),
            "profile_canary": _ref(MIA_OUTPUT / "profile-canary.json"),
            "profile_canary_attempts": _ref(MIA_OUTPUT / "profile-canary-attempts.json"),
        },
    }
    _must(raw_refs["gemma"]["admission"]["sha256"] == gemma_refs["admission_sha256"]
          and raw_refs["mia"]["admission"]["sha256"] == _sha(mia_admission_raw),
          "comparison admissions are not exact raw registered receipts")
    return {
        "schema": SCHEMA, "mia_window_id": MIA_ID,
        "source_ref": source_ref, "raw_refs": raw_refs,
        "matching": matching,
        "arms": {"gemma": gemma_summary, "mia": mia_summary},
        "per_cell": rows,
        "terminal_replay": {"gemma": "recorded_admission_and_raw_refs_verified",
                            "mia": "current_source_terminal_gate_verified"},
        "comparison_eligible": False, "private_content_exported": False,
        "scientific_novelty_claimed": False, "trading_claim_authorized": False,
        "interpretation": "descriptive_matched_fixture_adaptive_serial_trajectories",
    }


def publish() -> tuple[Path, Path]:
    """Write the report and SHA-bound index once after exact restored admission."""
    _must(not INDEX_PATH.exists(), "descriptive comparison index already exists")
    report = build_report()
    report["source_ref"] = _archive_source_once()
    if REPORT_PATH.exists():
        recorded, _ = _object(REPORT_PATH)
        _must(recorded == report,
              "existing descriptive report differs from independent replay")
    else:
        _write_once(REPORT_PATH, report)
    index = {
        "schema": INDEX_SCHEMA, "mia_window_id": MIA_ID,
        "report_ref": _ref(REPORT_PATH), "source_ref": report["source_ref"],
        "raw_refs": report["raw_refs"],
        "comparison_eligible": False, "private_content_exported": False,
    }
    _write_once(INDEX_PATH, index)
    return REPORT_PATH, INDEX_PATH


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publish", action="store_true", required=True)
    args = parser.parse_args(argv)
    if args.publish:
        report, index = publish()
        print(report)
        print(index)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
