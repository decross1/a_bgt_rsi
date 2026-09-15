"""Publish source-bound, content-free fresh and context evaluation pairs.

The execution worktree performs the expensive private-stream and grader replay
once. The portable reader rechecks immutable sources, terminal restoration,
and every displayed numeric value without returning private model content.
"""
from __future__ import annotations

import hashlib
import importlib
import math
from pathlib import Path
from typing import Any

from . import lab_eval_context, lab_eval_fresh, manifest
from .lab_eval_report import _doc

ARTIFACT_ROOT = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/lab-eight-hour"
)
PUBLICATION_ROOT = ARTIFACT_ROOT / "evaluation-supplement-pairs"
WINDOW_ROOT = ARTIFACT_ROOT / "model-windows"
SCHEMA = "lab-model-supplement-paired-report/v1"
INDEX_SCHEMA = "lab-model-supplement-publication-index/v1"
KINDS = {
    "fresh": {
        "pair_id": "qfn-ab-lab-fresh-20260915-a",
        "denominator": 12,
        "module": lab_eval_fresh,
        "run_schema": lab_eval_fresh.RUN_SCHEMA,
        "replay_count_key": "primary_cells_replayed",
        "grade_replay": "raw_sse_and_all_12_fresh_primary_grades_per_cohort",
        "claim_limit": "NEW_SYNTHETIC_DEVELOPMENT_CANARIES_NOT_TRADING_EVIDENCE",
    },
    "context": {
        "pair_id": "qfn-ab-lab-context-20260915-a",
        "denominator": 36,
        "module": lab_eval_context,
        "run_schema": lab_eval_context.RUN_SCHEMA,
        "replay_count_key": "objective_cells_replayed",
        "grade_replay": "raw_sse_and_all_36_context_objective_grades_per_cohort",
        "claim_limit": "PUBLIC_DEVELOPMENT_CONTEXT_DIAGNOSTIC_NOT_HELDOUT",
    },
}


class SupplementReportError(ValueError):
    pass


def _must(ok: bool, reason: str) -> None:
    if not ok:
        raise SupplementReportError(reason)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read(path: Path, *, label: str, ceiling: int = 16_000_000) -> tuple[dict, str]:
    try:
        return _doc(path, label=label, ceiling=ceiling)
    except Exception as exc:
        raise SupplementReportError(f"{label} is absent, malformed or redirected") from exc


def _kind(kind: str) -> dict:
    _must(kind in KINDS, "supplement kind is not registered")
    return KINDS[kind]


def _numeric(run: dict, *, kind: str, plan: dict, cohort: str) -> dict:
    spec = _kind(kind)
    outcomes = run.get("outcomes")
    _must(isinstance(outcomes, list) and len(outcomes) == spec["denominator"]
          and type(run.get("elapsed_s")) in (int, float)
          and math.isfinite(run["elapsed_s"]) and run["elapsed_s"] >= 0,
          "supplement denominator differs")

    def aggregate(rows: list[dict]) -> dict:
        wall = sum(row["wall_s"] for row in rows)
        _must(math.isfinite(wall) and wall >= 0, "supplement wall time is invalid")
        return {
            "declared": len(rows),
            "attempted": sum(len(row["calls"]) == 1 for row in rows),
            "returned": sum(row["status"] == "returned" for row in rows),
            "timeout": sum(row["status"] == "timeout" for row in rows),
            "error": sum(row["status"] == "error" for row in rows),
            "cancelled": sum(row["status"] == "cancelled" for row in rows),
            "passed": sum(row["passed"] is True for row in rows),
            "wall_s_including_failures": wall,
        }

    _must([row.get("cell_id") for row in outcomes] == plan["declared_cells"],
          "supplement ordered tasks differ from source")
    for row in outcomes:
        endpoint = plan["call_routes"][cohort][row["cell_id"]][0]
        _must(isinstance(row, dict) and isinstance(row.get("calls"), list)
              and len(row["calls"]) == 1
              and row.get("status") in {"returned", "timeout", "error", "cancelled"}
              and row["calls"][0].get("status") == row["status"]
              and row["calls"][0].get("endpoint_name") == endpoint
              and type(row.get("passed")) is bool
              and type(row.get("wall_s")) in (int, float)
              and math.isfinite(row["wall_s"]) and row["wall_s"] >= 0,
              "complete supplement has an unissued or invalid cell")
        receipt = plan["cell_receipts"][row["cell_id"]]
        if kind == "fresh":
            _must(row.get("kind") == receipt["kind"]
                  and row.get("messages_sha256") == receipt["messages_sha256"]
                  and row.get("fixture_sha256") == receipt["fixture_sha256"],
                  "fresh result kind differs from frozen fixture")
        else:
            _must(row.get("server_context_tokens")
                  == receipt["server_context_tokens"]
                  and row.get("source_task_id") == receipt["source_task_id"]
                  and row.get("placement") == receipt["placement"]
                  and row.get("output_reserve_tokens") == receipt["max_output_tokens"]
                  and row.get("actual_prompt_tokens_preflight")
                  == receipt["actual_prompt_tokens_by_endpoint"][endpoint]
                  and row.get("messages_sha256") == receipt["messages_sha256"]
                  and row.get("grader_sha256") == receipt["grader_sha256"],
                  "context group or prompt evidence differs from frozen packet")
    result: dict[str, Any] = {"total": aggregate(outcomes)}
    if kind == "fresh":
        _must([row.get("kind") for row in outcomes] == ["science"] * 6 + ["coding"] * 6,
              "fresh science/coding schedule differs")
        result["by_kind"] = {
            name: aggregate([row for row in outcomes if row["kind"] == name])
            for name in ("science", "coding")
        }
    else:
        capacities = (8192, 16384, 32768)
        placements = tuple(lab_eval_context.packs.PLACEMENTS)
        _must(set(placements) == {row.get("placement") for row in outcomes}
              and {row.get("server_context_tokens") for row in outcomes} == set(capacities)
              and all(row.get("output_reserve_tokens") == 2048 for row in outcomes),
              "context capacity, placement or output reserve differs")
        result["by_capacity"] = {
            str(cap): aggregate([row for row in outcomes
                                 if row["server_context_tokens"] == cap])
            for cap in capacities
        }
        result["measured_prompt_tokens_max_by_capacity"] = {
            str(cap): max((
                call["usage"]["prompt_tokens"]
                for row in outcomes if row["server_context_tokens"] == cap
                for call in row["calls"]
                if isinstance(call.get("usage"), dict)
                and type(call["usage"].get("prompt_tokens")) is int
                and call["usage"]["prompt_tokens"] >= 0
            ), default=None)
            for cap in capacities
        }
        result["by_placement"] = {
            place: aggregate([row for row in outcomes if row["placement"] == place])
            for place in placements
        }
        result["by_capacity_placement"] = {
            str(cap): {
                place: aggregate([row for row in outcomes
                                  if row["server_context_tokens"] == cap
                                  and row["placement"] == place])
                for place in placements
            }
            for cap in capacities
        }
        _must(all(value["declared"] == 12 for value in result["by_capacity"].values())
              and all(value["declared"] == 12 for value in result["by_placement"].values())
              and all(value["declared"] == 4 for grid in
                      result["by_capacity_placement"].values() for value in grid.values()),
              "context grouped denominators differ")
    _must(result["total"]["attempted"] == spec["denominator"],
          "supplement complete score omits attempted cells")
    return result


def _prompt_identity(run: dict, *, kind: str, plan: dict, cohort: str) -> None:
    selected = {name for routes in plan["call_routes"][cohort].values()
                for name in routes}
    configured = {
        name: plan["endpoints"][name]["max_model_len"] for name in selected}
    observed = {
        name: max((
            call["usage"]["prompt_tokens"]
            for row in run["outcomes"] for call in row["calls"]
            if call.get("endpoint_name") == name
            and isinstance(call.get("usage"), dict)
            and type(call["usage"].get("prompt_tokens")) is int
            and call["usage"]["prompt_tokens"] >= 0
        ), default=None)
        for name in selected
    }
    expected_variant = (
        plan["runtime_certificates"]["flash"]["candidate_spec_id"]
        if cohort == "flash" else
        "resident-role-bundle" if kind == "fresh" else "resident-gemma"
    )
    _must(run.get("candidate_variant_id") == expected_variant
          and run.get("claim_limit") == plan["claim_limit"]
          and run.get("promotion_authorized") is False,
          "supplement variant or claim limit differs from frozen plan")
    if kind == "fresh":
        _must(run.get("configured_context_tokens_by_endpoint") == configured
              and run.get("measured_prompt_tokens_max_by_endpoint") == observed,
              "fresh configured or measured prompt capacity differs from calls")
    else:
        endpoint = plan["call_routes"][cohort][plan["declared_cells"][0]][0]
        _must(selected == {endpoint}
              and run.get("configured_context_tokens") == configured[endpoint]
              and run.get("measured_prompt_tokens_max") == observed[endpoint]
              and run.get("output_reserve_tokens") == 2048,
              "context configured or measured prompt capacity differs from calls")


def _terminal(window: dict, result: dict, state: dict, supervision: dict,
              *, kind: str, cohort: str, plan_path: Path, plan_raw_sha: str,
              window_sha: str, run_sha: str) -> None:
    restoration = result.get("restoration")
    _must(window.get("schema") == "lab-model-window/v1"
          and window.get("evaluation_kind") == kind
          and window.get("cohort") == cohort
          and window.get("window_id") == _kind(kind)["pair_id"]
          and window.get("evaluation_plan") == {
              "path": str(plan_path), "sha256": plan_raw_sha}
          and result.get("schema") == "lab-model-window-result/v1"
          and result.get("cohort") == cohort and result.get("status") == "complete"
          and result.get("window_id") == window["window_id"]
          and result.get("evaluation_run_sha256") == run_sha
          and result.get("error") is None
          and result.get("promotion_authorized") is False
          and result.get("window_sha256") == window_sha
          and state.get("phase") == "complete"
          and state.get("window_sha256") == window_sha
          and state.get("restoration") == restoration
          and isinstance(restoration, dict)
          and restoration.get("status") == "verified"
          and restoration.get("errors") == []
          and restoration.get("sentinel_retained") is False
          and isinstance(restoration.get("verified_at"), str)
          and supervision.get("schema") == "lab-model-supervision/v1"
          and supervision.get("window_sha256") == window_sha
          and supervision.get("returncode") == 0
          and supervision.get("interrupted") is None
          and supervision.get("terminated_at_cutoff") is False
          and supervision.get("emergency_restoration") is None,
          "supplement lacks a closed, exactly restored window")


def _closed_window(path: Path, *, kind: str, cohort: str,
                   plan_path: Path, plan_raw_sha: str) -> tuple[dict, dict, dict, dict]:
    controller = importlib.import_module("bench.flash_next_ab.lab_window")
    window, _ = controller.load_window(path)
    output = Path(window["output_dir"])
    result, result_sha = _read(output / "result.json", label="supplement terminal result")
    state, state_sha = _read(output / "state.json", label="supplement terminal state")
    supervision, supervision_sha = _read(
        output / "supervision.json", label="supplement supervision")
    run_path = output / "evaluation/run.json"
    run, run_sha = _read(run_path, label="supplement model run")
    window_sha = manifest.sha256_file(path)
    _terminal(window, result, state, supervision, kind=kind, cohort=cohort,
              plan_path=plan_path, plan_raw_sha=plan_raw_sha,
              window_sha=window_sha, run_sha=run_sha)
    replay = _kind(kind)["module"].replay_run(plan_path, run_path)
    _must(replay.get("primary_replay_passed") is True
          and replay.get(_kind(kind)["replay_count_key"]) == _kind(kind)["denominator"]
          and replay.get("run_raw_sha256") == run_sha
          and replay.get("cohort") == cohort,
          "supplement raw response or grade replay did not pass")
    refs = {
        "window_path": str(path), "window_raw_sha256": window_sha,
        "result_path": str(output / "result.json"), "result_raw_sha256": result_sha,
        "state_path": str(output / "state.json"), "state_raw_sha256": state_sha,
        "supervision_path": str(output / "supervision.json"),
        "supervision_raw_sha256": supervision_sha,
        "run_path": str(run_path), "run_raw_sha256": run_sha,
    }
    return window, run, replay, refs


def build_report(kind: str, plan_path: str | Path, resident_window_path: str | Path,
                 flash_window_path: str | Path) -> tuple[dict, dict, dict]:
    spec = _kind(kind)
    plan_path = Path(plan_path).absolute()
    plan, _, plan_raw_sha = spec["module"].load_plan(plan_path)
    closed = {
        cohort: _closed_window(
            Path(path).absolute(), kind=kind, cohort=cohort,
            plan_path=plan_path, plan_raw_sha=plan_raw_sha)
        for cohort, path in (
            ("resident", resident_window_path), ("flash", flash_window_path))
    }
    cohorts = {}
    refs = {"plan": {"path": str(plan_path), "raw_sha256": plan_raw_sha},
            "report_builder": {
                "source_path": "bench/flash_next_ab/lab_eval_supplement_report.py",
                "raw_sha256": manifest.sha256_file(__file__),
            },
            "resident": closed["resident"][3], "flash": closed["flash"][3]}
    for cohort in ("resident", "flash"):
        window, run, replay, _ = closed[cohort]
        _must(run.get("schema_version") == spec["run_schema"]
              and run.get("cohort") == cohort and run.get("status") == "complete"
              and run.get("declared_cells") == plan["declared_cells"]
              and [row.get("cell_id") for row in run.get("outcomes", [])]
              == plan["declared_cells"]
              and run.get("plan_raw_sha256") == plan_raw_sha
              and run.get("runtime_certificate") == plan["runtime_certificates"][cohort]
              and window["window_id"] == spec["pair_id"],
              "supplement pair does not share the frozen task/runtime plan")
        _prompt_identity(run, kind=kind, plan=plan, cohort=cohort)
        cohorts[cohort] = {
            "variant_id": run["candidate_variant_id"],
            "status": "complete",
            "elapsed_s": run["elapsed_s"],
            "scores": _numeric(run, kind=kind, plan=plan, cohort=cohort),
            "raw_response_replay_passed": replay["primary_replay_passed"],
        }
        if kind == "fresh":
            cohorts[cohort]["configured_context_tokens_by_endpoint"] = (
                run["configured_context_tokens_by_endpoint"])
            cohorts[cohort]["measured_prompt_tokens_max_by_endpoint"] = (
                run["measured_prompt_tokens_max_by_endpoint"])
            cohorts[cohort]["normalization_diagnostic"] = (
                replay["normalization_diagnostic"])
        else:
            cohorts[cohort]["configured_context_tokens"] = run["configured_context_tokens"]
            cohorts[cohort]["measured_prompt_tokens_max"] = (
                run["measured_prompt_tokens_max"])
            cohorts[cohort]["output_reserve_tokens"] = run["output_reserve_tokens"]
    report = {
        "schema_version": SCHEMA, "kind": kind, "pair_id": spec["pair_id"],
        "status": "complete_admitted_pair",
        "suite_id": plan["suite_id"], "cell_set": plan["cell_set"],
        "plan_raw_sha256": plan_raw_sha,
        "plan_sha256": manifest.sha256_json(plan),
        "denominator_per_cohort": spec["denominator"],
        "cohorts": cohorts,
        "original_scores_rebased": False, "heldout_claim": False,
        "private_content_exported": False, "promotion_authorized": False,
        "claim_limit": spec["claim_limit"],
    }
    return report, refs, {
        "resident": closed["resident"][2], "flash": closed["flash"][2]}


def publish(kind: str, plan_path: str | Path, resident_window_path: str | Path,
            flash_window_path: str | Path, *, output_dir: str | Path | None = None) -> dict:
    report, refs, replays = build_report(
        kind, plan_path, resident_window_path, flash_window_path)
    output = Path(output_dir or PUBLICATION_ROOT / report["pair_id"]).absolute()
    _must(output.parent == PUBLICATION_ROOT
          and output.name == report["pair_id"] and not output.parent.is_symlink(),
          "supplement publication is outside its registered direct child")
    PUBLICATION_ROOT.mkdir(exist_ok=True)
    output.mkdir(mode=0o700)
    replay_refs = {}
    for cohort, replay in replays.items():
        leaf = f"{cohort}-replay.json"
        raw = manifest.canonical_json(replay) + b"\n"
        with (output / leaf).open("xb") as handle:
            handle.write(raw)
        replay_refs[cohort] = {"relpath": leaf, "raw_sha256": _sha(raw)}
    report_raw = manifest.canonical_json(report) + b"\n"
    with (output / "report.json").open("xb") as handle:
        handle.write(report_raw)
    index = {
        "schema_version": INDEX_SCHEMA, "kind": kind,
        "pair_id": report["pair_id"], "status": "complete_admitted_pair",
        "report_relpath": "report.json", "report_raw_sha256": _sha(report_raw),
        "replay_refs": replay_refs, "source_refs": refs,
        "grade_replay": _kind(kind)["grade_replay"],
        "private_content_exported": False, "promotion_authorized": False,
    }
    with (output / "index.json").open("xb") as handle:
        handle.write(manifest.canonical_json(index) + b"\n")
    return index


def read_publication(index_path: str | Path) -> dict:
    """Rehash a registered pair and derive each displayed score from run bytes."""
    index_path = Path(index_path).absolute()
    _must(index_path.name == "index.json"
          and index_path.parent.parent == PUBLICATION_ROOT
          and not index_path.parent.is_symlink(),
          "supplement publication is not a registered direct child")
    index, _ = _read(index_path, label="supplement index")
    kind = index.get("kind")
    spec = _kind(kind)
    _must(index_path.parent.name == spec["pair_id"]
          and set(index) == {
              "schema_version", "kind", "pair_id", "status", "report_relpath",
              "report_raw_sha256", "replay_refs", "source_refs", "grade_replay",
              "private_content_exported", "promotion_authorized"}
          and index["schema_version"] == INDEX_SCHEMA
          and index["pair_id"] == spec["pair_id"]
          and index["status"] == "complete_admitted_pair"
          and index["report_relpath"] == "report.json"
          and index["grade_replay"] == spec["grade_replay"]
          and index["private_content_exported"] is False
          and index["promotion_authorized"] is False,
          "supplement index identity or claim fields differ")
    report, report_sha = _read(index_path.parent / "report.json", label="supplement report")
    _must(report_sha == index["report_raw_sha256"]
          and report.get("schema_version") == SCHEMA
          and report.get("kind") == kind
          and report.get("pair_id") == spec["pair_id"]
          and report.get("status") == "complete_admitted_pair"
          and report.get("denominator_per_cohort") == spec["denominator"]
          and report.get("original_scores_rebased") is False
          and report.get("heldout_claim") is False
          and report.get("private_content_exported") is False
          and report.get("promotion_authorized") is False
          and report.get("claim_limit") == spec["claim_limit"],
          "supplement report claim or digest differs")
    sources = index["source_refs"]
    _must(isinstance(sources, dict)
          and set(sources) == {"plan", "report_builder", "resident", "flash"}
          and sources["report_builder"] == {
              "source_path": "bench/flash_next_ab/lab_eval_supplement_report.py",
              "raw_sha256": manifest.sha256_file(__file__)},
          "supplement builder/source inventory differs")
    plan_path = Path(sources["plan"]["path"])
    _must(plan_path.is_relative_to(ARTIFACT_ROOT),
          "supplement plan path is outside registered artifacts")
    plan, _, plan_sha = spec["module"].load_plan(plan_path)
    _must(sources["plan"] == {"path": str(plan_path), "raw_sha256": plan_sha}
          and plan_sha == report["plan_raw_sha256"]
          and report["plan_sha256"] == manifest.sha256_json(plan)
          and report["suite_id"] == plan["suite_id"]
          and report["cell_set"] == plan["cell_set"],
          "supplement plan or runtime source differs")
    _must(isinstance(index["replay_refs"], dict)
          and set(index["replay_refs"]) == {"resident", "flash"}
          and isinstance(report.get("cohorts"), dict)
          and set(report["cohorts"]) == {"resident", "flash"},
          "supplement paired cohort inventory differs")
    delivered_root = Path(__file__).resolve().parents[2]
    for cohort in ("resident", "flash"):
        source = sources[cohort]
        _must(isinstance(source, dict)
              and set(source) == {
                  "window_path", "window_raw_sha256",
                  "result_path", "result_raw_sha256",
                  "state_path", "state_raw_sha256",
                  "supervision_path", "supervision_raw_sha256",
                  "run_path", "run_raw_sha256"},
              "supplement source receipt fields differ")
        window_path = Path(source["window_path"])
        output = WINDOW_ROOT / f"{spec['pair_id']}.{cohort}"
        _must(window_path == output / "window.json"
              and source["result_path"] == str(output / "result.json")
              and source["state_path"] == str(output / "state.json")
              and source["supervision_path"] == str(output / "supervision.json")
              and source["run_path"] == str(output / "evaluation/run.json"),
              "supplement source path differs from registered window")
        terminal = {}
        for leaf in ("window", "result", "state", "supervision", "run"):
            path = Path(source[f"{leaf}_path"])
            doc, raw_sha = _read(path, label=f"{cohort} supplement {leaf}")
            _must(raw_sha == source[f"{leaf}_raw_sha256"],
                  "supplement source bytes changed")
            terminal[leaf] = doc
        window, run = terminal["window"], terminal["run"]
        _must(window.get("output_dir") == str(output),
              "supplement window output differs from registered path")
        _terminal(window, terminal["result"], terminal["state"],
                  terminal["supervision"], kind=kind, cohort=cohort,
                  plan_path=plan_path, plan_raw_sha=plan_sha,
                  window_sha=source["window_raw_sha256"],
                  run_sha=source["run_raw_sha256"])
        _must(window.get("code_root")
              == str(Path(window.get("code_root", "")))
              and isinstance(window.get("controller_sources"), dict)
              and "bench/flash_next_ab/lab_window.py" in window["controller_sources"],
              "supplement controller source inventory is missing")
        recorded_root = Path(window["code_root"])
        for relative, identity in window["controller_sources"].items():
            registered = recorded_root / relative
            _must(identity == {
                "path": str(registered), "sha256": manifest.sha256_file(registered)}
                and manifest.sha256_file(delivered_root / relative) == identity["sha256"],
                "supplement controller source differs from delivered code")
        replay_ref = index["replay_refs"][cohort]
        _must(isinstance(replay_ref, dict)
              and set(replay_ref) == {"relpath", "raw_sha256"}
              and replay_ref["relpath"] == f"{cohort}-replay.json"
              and isinstance(replay_ref["raw_sha256"], str)
              and len(replay_ref["raw_sha256"]) == 64,
            "supplement replay receipt path differs")
        replay, replay_sha = _read(
            index_path.parent / replay_ref["relpath"], label="supplement grade replay")
        _must(replay_sha == replay_ref["raw_sha256"]
              and replay.get("cohort") == cohort
              and replay.get("run_raw_sha256") == source["run_raw_sha256"]
              and replay.get("primary_replay_passed") is True
              and replay.get(spec["replay_count_key"]) == spec["denominator"]
              and replay.get("promotion_authorized") is False
              and replay.get("private_content_exported") is False,
              "supplement private-stream/grade replay receipt differs")
        _must(run.get("schema_version") == spec["run_schema"]
              and run.get("cohort") == cohort and run.get("status") == "complete"
              and run.get("plan_raw_sha256") == plan_sha
              and run.get("plan_sha256") == manifest.sha256_json(plan)
              and run.get("runtime_certificate") == plan["runtime_certificates"][cohort]
              and run.get("declared_cells") == plan["declared_cells"]
              and [row.get("cell_id") for row in run.get("outcomes", [])]
              == plan["declared_cells"]
              and run.get("promotion_authorized") is False,
              "supplement run differs from its frozen plan/certificate")
        _prompt_identity(run, kind=kind, plan=plan, cohort=cohort)
        expected = {
            "variant_id": run["candidate_variant_id"],
            "status": "complete", "elapsed_s": run["elapsed_s"],
            "scores": _numeric(run, kind=kind, plan=plan, cohort=cohort),
            "raw_response_replay_passed": True,
        }
        if kind == "fresh":
            expected.update({
                "configured_context_tokens_by_endpoint":
                    run["configured_context_tokens_by_endpoint"],
                "measured_prompt_tokens_max_by_endpoint":
                    run["measured_prompt_tokens_max_by_endpoint"],
                "normalization_diagnostic": replay["normalization_diagnostic"],
            })
        else:
            expected.update({
                "configured_context_tokens": run["configured_context_tokens"],
                "measured_prompt_tokens_max": run["measured_prompt_tokens_max"],
                "output_reserve_tokens": run["output_reserve_tokens"],
            })
        _must(report["cohorts"][cohort] == expected,
              "supplement numeric report differs from bound run")
    return report
