"""Read-only status for the registered 126-cell lab model comparison."""
from __future__ import annotations

import hashlib
import math
import re
import stat
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter

from . import model_runtime_lab as runtime

ROOT = runtime.ARTIFACT_ROOT
WINDOW_ROOT = ROOT / "model-windows"
PUBLICATION_ROOT = ROOT / "evaluation-pairs"
PAIR_RE = re.compile(r"qfn-ab-lab-primary-20260915-[a-z]\Z")
MAX_CHILDREN = 64
SCHEMA = "lab-model-eval-progress/v1"
FAMILIES = frozenset({"objective", "topic", "portfolio", "diversity",
                      "role_effort", "historical", "context"})


def _read_object(path: Path, *, limit: int = 4_000_000) -> tuple[dict, str]:
    from bench.flash_next_ab import harness

    raw, actual = harness._read_regular_file(path, label="lab model evaluation source",
                                             max_bytes=limit)
    if actual != path.absolute():
        raise ValueError("lab source path redirected")
    return harness._strict_object(raw, "lab model evaluation source"), hashlib.sha256(raw).hexdigest()


def _select_pair() -> tuple[str, dict[str, Path], list[str]]:
    if WINDOW_ROOT.is_symlink():
        raise ValueError("lab window root redirected")
    pairs: dict[str, dict[str, Path]] = {}
    for n, child in enumerate(WINDOW_ROOT.iterdir()):
        if n >= MAX_CHILDREN:
            raise ValueError("lab window inventory exceeds bound")
        if child.is_symlink() or not stat.S_ISDIR(child.lstat().st_mode):
            continue
        pair, dot, cohort = child.name.rpartition(".")
        if dot and PAIR_RE.fullmatch(pair) and cohort in ("resident", "flash"):
            path = child / "window.json"
            if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
                continue
            pairs.setdefault(pair, {})[cohort] = path
    complete = [(max(path.lstat().st_mtime_ns for path in rows.values()), pair, rows)
                for pair, rows in pairs.items() if set(rows) == {"resident", "flash"}]
    if not complete:
        raise ValueError("registered paired windows absent")
    complete.sort(reverse=True)
    return complete[0][1], complete[0][2], [row[1] for row in complete]


def _prepared(pair_id: str, windows: dict[str, Path]) -> tuple[str, Path]:
    from bench.flash_next_ab.lab_eval_plan import load_plan

    resident, _ = _read_object(windows["resident"])
    plan_ref = resident.get("evaluation_plan")
    if not isinstance(plan_ref, dict) or not isinstance(plan_ref.get("path"), str):
        raise TypeError("registered lab plan reference absent")
    plan_path = Path(plan_ref["path"])
    if (plan_path.parent != ROOT or not plan_path.name.startswith("primary-model-comparison")
            or not plan_path.name.endswith(".plan.json") or plan_path.is_symlink()):
        raise ValueError("registered lab plan path differs")
    plan, _, plan_sha = load_plan(plan_path)
    if plan.get("schema_version") != "lab-model-eval-plan/v1" or len(plan.get("declared_cells", [])) != 126:
        raise ValueError("registered lab plan differs")
    for cohort, path in windows.items():
        window, _ = _read_object(path)
        if (window.get("schema") != "lab-model-window/v1"
                or window.get("cohort") != cohort
                or window.get("window_id") != pair_id
                or window.get("evaluation_kind") != "primary"
                or window.get("output_dir") != str(path.parent)
                or window.get("code_root") != str(runtime.CODE_ROOT)
                or window.get("candidate_spec_id") != runtime.SPEC_ID
                or window.get("candidate_spec_sha256") != runtime.SPEC_SHA
                or window.get("evaluation_plan") != {"path": str(plan_path), "sha256": plan_sha}
                or window.get("runtime_certificate", {}).get("path") != str(runtime.PARENT_PATH)):
            raise ValueError("registered lab window differs")
        _, certificate_sha = _read_object(runtime.PARENT_PATH, limit=8192)
        if window["runtime_certificate"].get("sha256") != certificate_sha:
            raise ValueError("registered lab certificate differs")
        runtime._sources(window)
    runtime._evaluator_sources(plan, "primary")
    return plan_sha, plan_path


def _count(value: object, *, ceiling: int = 126) -> int:
    if type(value) is not int or not 0 <= value <= ceiling:
        raise ValueError("lab count outside registered bounds")
    return value


def _seconds(value: object) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100_000:
        raise ValueError("lab elapsed time outside registered bounds")
    return float(value)


def _tokens(value: object, *, measured: bool = False) -> dict[str, int | None]:
    if not isinstance(value, dict) or not 1 <= len(value) <= 3:
        raise ValueError("lab endpoint token inventory differs")
    allowed = {"resident_qwen", "resident_gemma", "flash_next_mia"}
    if not set(value) <= allowed:
        raise ValueError("lab endpoint token route differs")
    return {key: None if measured and tokens is None else _count(tokens, ceiling=131_072)
            for key, tokens in value.items()}


def _project_report(report: dict, pair_id: str) -> dict:
    if (report.get("schema_version") != "lab-model-eval-paired-report/v1"
            or report.get("pair_id") != pair_id
            or report.get("status") != "complete_admitted_pair"
            or report.get("denominator") != 126
            or report.get("promotion_authorized") is not False
            or report.get("private_content_exported") is not False
            or report.get("heldout_claim") is not False
            or report.get("original_scores_rebased") is not False):
        raise ValueError("lab report claim boundary differs")
    cohorts = report.get("cohorts")
    if not isinstance(cohorts, dict) or set(cohorts) != {"resident", "flash"}:
        raise ValueError("lab report cohorts differ")
    shown = {}
    family_names = None
    for cohort, row in cohorts.items():
        expected_variant = "resident-role-bundle" if cohort == "resident" else runtime.SPEC_ID
        if (not isinstance(row, dict) or row.get("variant_id") != expected_variant
                or row.get("status") != "complete"
                or row.get("raw_response_replay_passed") is not True):
            raise ValueError("lab admitted cohort differs")
        family_rows = row.get("families")
        if not isinstance(family_rows, dict) or set(family_rows) != FAMILIES:
            raise ValueError("lab family inventory differs")
        if family_names is None:
            family_names = set(family_rows)
        elif set(family_rows) != family_names:
            raise ValueError("lab cohort family sets differ")
        families = {}
        for name, family in family_rows.items():
            if not isinstance(family, dict):
                raise TypeError("lab family row differs")
            shown_family = {key: _count(family.get(key)) for key in
                            ("declared", "attempted", "returned", "timeout", "error", "cancelled", "passed")}
            if (shown_family["passed"] > shown_family["attempted"]
                    or shown_family["attempted"] > shown_family["declared"]):
                raise ValueError("lab family denominator differs")
            shown_family["wall_s_including_failures"] = _seconds(family.get("wall_s_including_failures"))
            families[name] = shown_family
        summary = {key: _count(row.get(key)) for key in ("declared", "attempted", "passed", "timeout")}
        if (summary["declared"] != 126 or summary["attempted"] > 126
                or summary["passed"] > summary["attempted"]
                or sum(item["declared"] for item in families.values()) != 126
                or sum(item["attempted"] for item in families.values()) != summary["attempted"]
                or sum(item["passed"] for item in families.values()) != summary["passed"]):
            raise ValueError("lab report totals differ")
        shown[cohort] = {
            "variant_id": expected_variant, **summary,
            "elapsed_s": _seconds(row.get("elapsed_s")),
            "configured_context_tokens_by_endpoint": _tokens(row.get("configured_context_tokens_by_endpoint")),
            "measured_prompt_tokens_max_by_endpoint": _tokens(
                row.get("measured_prompt_tokens_max_by_endpoint"), measured=True),
            "families": families,
        }
        if (set(shown[cohort]["configured_context_tokens_by_endpoint"]) !=
                set(shown[cohort]["measured_prompt_tokens_max_by_endpoint"])):
            raise ValueError("lab observed endpoint inventory differs")
    return shown


def project_progress(*, publication_reader: Callable[[Path], dict] | None = None) -> dict:
    base = {"schema_version": SCHEMA, "pair_id": None, "status": "source_unavailable",
            "denominator": 126, "plan_raw_sha256": None, "cohorts": None,
            "grade_replay": "not_available", "source_status": "unverified",
            "promotion_authorized": False, "registered_pair_ids": []}
    try:
        pair_id, windows, history = _select_pair()
        base["pair_id"] = pair_id
        base["registered_pair_ids"] = history
        base["plan_raw_sha256"], _ = _prepared(pair_id, windows)
        base["status"] = "pending_admission"
        base["source_status"] = "prepared_sources_verified"
        publication = PUBLICATION_ROOT / pair_id / "index.json"
        if not publication.exists():
            return base
        if publication_reader is None:
            from bench.flash_next_ab.lab_eval_report import read_publication
            publication_reader = read_publication
        report = publication_reader(publication)
        base["cohorts"] = _project_report(report, pair_id)
        base["status"] = "complete_admitted_pair"
        base["source_status"] = "current_source_replay_verified"
        base["grade_replay"] = "raw_sse_and_all_126_primary_grades_per_cohort"
    except (ImportError, OSError, RuntimeError, TypeError, ValueError, KeyError):
        # An absent or drifting publication cannot become a score card.
        base["status"] = "source_unavailable"
        base["cohorts"] = None
        base["source_status"] = "unverified"
        base["grade_replay"] = "not_available"
    return base


def register(app, *, projector: Callable[[], dict] = project_progress) -> None:
    router = APIRouter()

    @router.get("/api/lab_model_eval_progress")
    def lab_model_eval_progress():
        return projector()

    app.include_router(router)
