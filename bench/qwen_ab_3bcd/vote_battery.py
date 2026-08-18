"""Stage-3b finding_promotion multi-vote battery (Qwen A/B, one arm per run).

Spec: experiments/PREREG_qwen_ab_3bcd_2026-08-18.md §3b (v2, LOCKED). Per
pinned candidate the driver calls
`finding_promotion._adversarial_vote(row, _claim_text(row), n_skeptics=3,
backend="vllm-qwen", parent_request_id=<bench id>)` — NEVER
`promote_findings()` (which writes surfaced_findings.jsonl,
run_state/active_run.json, and the idea ledger; `_adversarial_vote` writes
nothing but the calls log).

Calls-log isolation (prereg Common): LOOP_V0_CALLS_LOG is set to
bench/qwen_ab_3bcd/runs/<arm>.calls.jsonl BEFORE orchestrator.finding_promotion
is imported (CALLS_LOG_PATH binds at import time there — the exp003
loop_bridge pattern: env first, lazy site import inside the run path). If the
module was already imported with a different binding this driver REFUSES
(CallsLogBindingError) rather than let calls land in the wrong log.

Backend re-register seam (the 2026-08-15 false-FAIL killer): the served-model
label from --model is re-registered onto backend "vllm-qwen" BEFORE any site
call (stage3a pattern, bench/critic_eval/stage3a_driver.py:33-41), and
GET :8001/v1/models is recorded in the artifact. A model-name 400 is a driver
bug, never a 3.8 finding.

LOCKED criteria per arm (prereg §3b): (i) liveness = parseable-verdict
fraction over skeptic slots run (qwen_failures==0 tallied per candidate);
(ii) zero empty-at-cap rows in the arm's calls log (empty completion AND
usage.output_tokens == max_tokens); (iii) reported non-gating: votes vs the
historical record, calls/vote vs the D-070 12.5 baseline, wall/vote. The A/B
gate (3.8 liveness >= 3.6 liveness AND 3.8 empty-at-cap == 0) is evaluated
cross-arm by the integrator over candidates completed in BOTH arms. Time cap
(rule 7): 60 min per arm; on cap, completed candidates are the arm's result,
partial stated.

Run (one arm):
  env -u MOCK_LLM .venv-chroma/bin/python -m bench.qwen_ab_3bcd.vote_battery \
    --arm-label qwen36 --model qwen3.6-27b-nvfp4 --image vllm/vllm-openai:v0.21.0
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

RUNS_DIR = Path(__file__).resolve().parent / "runs"
SURFACED_PATH = REPO_ROOT / "memory" / "surfaced_findings.jsonl"
LOOP_MEMORY_PATH = REPO_ROOT / "memory" / "loop_memory.jsonl"

ENDPOINT = "http://127.0.0.1:8001/v1"
MODELS_URL = ENDPOINT + "/models"

STAGE = "3b"
N_SKEPTICS = 3
TIME_CAP_S = 3600.0            # prereg §3b: 60 min per arm (rule 7)
BASELINE_CALLS_PER_VOTE = 12.5  # D-070 baseline (reported, non-gating)

# Prereg-stated production vote budgets (configured inside
# finding_promotion._adversarial_vote; recorded here as provenance).
VOTE_BUDGET = {"max_turns": 4, "max_tokens_per_turn": 6144,
               "max_tokens_total": 16000, "max_wall_seconds": 800.0}

# Build-time fixture resolution (prereg §3b): the 3 most recent rows in
# memory/surfaced_findings.jsonl with complete promotion-vote blocks resolved
# 2026-08-18 to these ids (file sha256 1353ae57...95d8). resolve_fixtures()
# re-applies the rule against the LIVE file and REFUSES on any drift — the
# fix is a human re-pin, never a guess (fp8 resolve_sentinels pattern).
EXPECTED_FINDING_IDS = (
    "sf-iter-2026-07-15-001",
    "sf-iter-2026-07-30-001",
    "sf-iter-2026-08-04-001",
)
VOTE_BLOCK_KEYS = ("n_skeptics", "n_voting", "n_refuted",
                   "adversarial_margin", "survived", "qwen_failures")
SKEPTIC_TAG_PREFIX = "subagent.finding_skeptic_"


class FixtureResolutionError(RuntimeError):
    """Live fixture resolution drifted from the prereg pins."""


class CallsLogBindingError(RuntimeError):
    """finding_promotion.CALLS_LOG_PATH is bound to the wrong log."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read_raw_lines(path: Path | str) -> list[str]:
    p = Path(path)
    if not p.exists():
        return []
    return p.read_text().splitlines()


def _parse_jsonl_lines(lines: list[str]) -> list[dict]:
    """Tolerant JSONL parse (skip blank/malformed — the site's own norm)."""
    rows: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def read_jsonl(path: Path | str) -> list[dict]:
    return _parse_jsonl_lines(_read_raw_lines(path))


# ── fixture resolution (prereg §3b rule, verified against pins) ─────────


def resolve_fixtures(
    surfaced_path: Path | str = SURFACED_PATH,
    loop_memory_path: Path | str = LOOP_MEMORY_PATH,
    expected_ids: tuple[str, ...] = EXPECTED_FINDING_IDS,
) -> tuple[list[dict], str, str]:
    """Apply the prereg rule — the 3 most recent surfaced rows with complete
    promotion-vote blocks — against the LIVE file, verify the result equals
    the pinned ids, and join each fixture's loop_memory row (the row shape
    _claim_text/_adversarial_vote expect). Returns
    (fixtures, sha256(surfaced), sha256(loop_memory)); raises
    FixtureResolutionError on any drift or missing loop row (never guesses).
    """
    surfaced_path, loop_memory_path = Path(surfaced_path), Path(loop_memory_path)
    for p in (surfaced_path, loop_memory_path):
        if not p.exists():
            raise FixtureResolutionError(f"required live file missing: {p}")
    surfaced_sha = _sha256_file(surfaced_path)
    loop_sha = _sha256_file(loop_memory_path)

    complete = [
        r for r in read_jsonl(surfaced_path)
        if isinstance(r.get("adversarial"), dict)
        and all(k in r["adversarial"] for k in VOTE_BLOCK_KEYS)
        and isinstance(r.get("finding_id"), str)
        and isinstance(r.get("source_iteration_id"), str)
    ]
    most_recent = complete[-3:]  # append-only file: tail order = recency
    resolved_ids = tuple(r["finding_id"] for r in most_recent)
    if resolved_ids != tuple(expected_ids):
        raise FixtureResolutionError(
            "the 3 most recent complete-vote rows in "
            f"{surfaced_path} resolve to {list(resolved_ids)}, but the "
            f"prereg pins {list(expected_ids)} "
            f"(sha256={surfaced_sha}) — the live file drifted since the "
            "build-time snapshot; refusing to guess (prereg §3b: fixtures "
            "are pinned as of the build-time snapshot; re-pin is a human "
            "decision).")

    loop_rows = {
        r["iteration_id"]: r
        for r in read_jsonl(loop_memory_path)
        if isinstance(r.get("iteration_id"), str)
    }
    fixtures: list[dict] = []
    for row in most_recent:
        iid = row["source_iteration_id"]
        loop_row = loop_rows.get(iid)
        if loop_row is None:
            raise FixtureResolutionError(
                f"fixture {row['finding_id']}: no loop_memory row for "
                f"source_iteration_id={iid!r} in {loop_memory_path} — "
                "_adversarial_vote needs that row; refusing to run without it.")
        fixtures.append({
            "finding_id": row["finding_id"],
            "source_iteration_id": iid,
            "promoted_at": row.get("promoted_at"),
            "historical_adversarial": {
                k: row["adversarial"].get(k) for k in VOTE_BLOCK_KEYS},
            "loop_row": loop_row,
        })
    return fixtures, surfaced_sha, loop_sha


# ── site binding + backend re-register (prereg Common) ──────────────────


def bind_promotion_site(calls_log_path: str):
    """Set LOOP_V0_CALLS_LOG, then import orchestrator.finding_promotion and
    verify its import-time CALLS_LOG_PATH binding matches. A mismatch means
    the module was imported before the env was set — skeptic calls would land
    in the WRONG log and every calls-log-based criterion would be computed
    over the wrong rows. Fail closed (rule 4), never silently rebind."""
    os.environ["LOOP_V0_CALLS_LOG"] = str(calls_log_path)
    import orchestrator.finding_promotion as fp  # lazy site import
    if str(fp.CALLS_LOG_PATH) != str(calls_log_path):
        raise CallsLogBindingError(
            f"orchestrator.finding_promotion.CALLS_LOG_PATH is bound to "
            f"{fp.CALLS_LOG_PATH!r}, expected {str(calls_log_path)!r} — the "
            "module was imported before LOOP_V0_CALLS_LOG was set (prereg "
            "Common 'Calls-log isolation'). Run this CLI in a fresh "
            "interpreter.")
    return fp


def reregister_backend(label: str, endpoint: str = ENDPOINT) -> None:
    """Re-register backend 'vllm-qwen' with the SERVED model label before any
    site call (stage3a pattern, bench/critic_eval/stage3a_driver.py:33-41):
    the registry hard-pins the 3.6 name, but the :8001 slot serves whichever
    model the window put there. A model-name 400 is a driver bug, never a
    3.8 finding."""
    from agent_wrapper.backends import register_backend
    from agent_wrapper.backends.ollama_openai import OllamaBackend
    import agent_wrapper.wrapper  # noqa: F401  (ensures base registrations ran)
    register_backend(OllamaBackend(
        name="vllm-qwen", base_url=endpoint, model=label))


def fetch_served_models(url: str = MODELS_URL, timeout: float = 10.0) -> dict:
    """GET /v1/models — the served-model id recorded in the artifact
    (prereg Common). A failed fetch is RECORDED, not fatal: a dead endpoint
    fails the liveness criterion honestly rather than aborting provenance."""
    out: dict[str, Any] = {"url": url, "ids": [], "fetched_at": _utc_now(),
                           "error": None}
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        out["ids"] = [m.get("id") for m in (body.get("data") or [])
                      if isinstance(m, dict)]
    except Exception as exc:  # noqa: BLE001 — recorded, never invented
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


# ── criteria (prereg §3b, LOCKED) ────────────────────────────────────────


def empty_at_cap_rows(rows: list[dict]) -> list[dict]:
    """Prereg Common definition, verbatim: a calls-log row with EMPTY
    completion AND usage.output_tokens == max_tokens. Rows without a
    max_tokens field cannot be at-cap. Returns compact summaries."""
    hits: list[dict] = []
    for r in rows:
        completion = r.get("completion")
        if (completion or "").strip():
            continue
        max_tokens = r.get("max_tokens")
        usage = r.get("usage") if isinstance(r.get("usage"), dict) else {}
        if max_tokens is None or usage.get("output_tokens") != max_tokens:
            continue
        hits.append({
            "timestamp": r.get("timestamp"),
            "request_id": r.get("request_id"),
            "caller_tag": r.get("caller_tag"),
            "parent_request_id": r.get("parent_request_id"),
            "output_tokens": usage.get("output_tokens"),
            "max_tokens": max_tokens,
        })
    return hits


def evaluate_criteria(candidates: list[dict], log_rows: list[dict],
                      bench_id: str, n_skeptics: int = N_SKEPTICS) -> dict:
    """Full §3b criteria evaluation with per-gate pass flags. Gates evaluate
    over candidates that COMPLETED (rule 7: on cap, completed candidates are
    the arm's result). Zero completed candidates = both gates FAIL (an arm
    that ran nothing demonstrated nothing — a vacuous pass would be a
    silently-coerced validation, rule 4)."""
    ran = [c for c in candidates if c.get("status") == "completed"
           and isinstance(c.get("tally"), dict)]
    slots_run = n_skeptics * len(ran)
    parseable = sum(int(c["tally"].get("n_voting") or 0) for c in ran)
    per_candidate = {
        c["finding_id"]: {
            "qwen_failures": c["tally"].get("qwen_failures"),
            "pass": c["tally"].get("qwen_failures") == 0,
        }
        for c in ran
    }
    liveness = {
        "fraction": (round(parseable / slots_run, 4) if slots_run else None),
        "parseable_verdicts": parseable,
        "slots_run": slots_run,
        "per_candidate": per_candidate,
        "pass": bool(slots_run) and parseable == slots_run,
        "pass_definition": (
            "all skeptic slots run returned parseable verdicts "
            "(fraction == 1.0; qwen_failures == 0 on every completed "
            "candidate); zero candidates completed = FAIL"),
    }

    whole_log_hits = empty_at_cap_rows(log_rows)
    run_hits = [h for h in whole_log_hits
                if h.get("parent_request_id") == bench_id]
    empty_at_cap = {
        "definition": ("row with empty completion AND usage.output_tokens == "
                       "max_tokens, computed from the arm's calls log "
                       "(prereg Common)"),
        "count_whole_arm_log": len(whole_log_hits),
        "count_this_run": len(run_hits),
        "rows": whole_log_hits,
        "pass": bool(slots_run) and not whole_log_hits,
    }

    votes_vs_history = []
    for c in ran:
        hist = c.get("historical_adversarial") or {}
        cur = c["tally"]
        votes_vs_history.append({
            "finding_id": c["finding_id"],
            "historical": {k: hist.get(k) for k in VOTE_BLOCK_KEYS},
            "current": {k: cur.get(k) for k in VOTE_BLOCK_KEYS
                        if k != "n_skeptics"},
            "survived_agrees": cur.get("survived") == hist.get("survived"),
        })
    calls_per_vote = {c["finding_id"]: c.get("skeptic_calls") for c in ran}
    wall_per_vote = {c["finding_id"]: c.get("wall_s") for c in ran}

    def _mean(vals):
        vals = [v for v in vals if isinstance(v, (int, float))]
        return round(sum(vals) / len(vals), 3) if vals else None

    return {
        "liveness": liveness,
        "empty_at_cap": empty_at_cap,
        "reported_non_gating": {
            "votes_vs_history": votes_vs_history,
            "calls_per_vote": {
                "per_candidate": calls_per_vote,
                "mean": _mean(calls_per_vote.values()),
                "baseline_d070": BASELINE_CALLS_PER_VOTE,
            },
            "wall_per_vote_s": {
                "per_candidate": wall_per_vote,
                "mean": _mean(wall_per_vote.values()),
            },
        },
        "ab_gate": {
            "definition": ("3.8 liveness >= 3.6 liveness AND 3.8 "
                           "empty-at-cap == 0, evaluated over candidates "
                           "completed in BOTH arms (prereg §3b) — cross-arm; "
                           "the integrator evaluates it from both artifacts"),
            "evaluable_single_arm": False,
            "this_arm": {
                "liveness_fraction": liveness["fraction"],
                "empty_at_cap_count": len(whole_log_hits),
                "candidates_completed": [c["finding_id"] for c in ran],
            },
        },
    }


# ── arm runner ───────────────────────────────────────────────────────────


@dataclass
class RunConfig:
    arm_label: str
    model_label: str
    image: str
    calls_log_path: str
    bench_id: str
    limit: int | None = None
    n_skeptics: int = N_SKEPTICS
    time_cap_s: float = TIME_CAP_S
    surfaced_path: str = str(SURFACED_PATH)
    loop_memory_path: str = str(LOOP_MEMORY_PATH)
    surfaced_sha256: str = ""
    loop_memory_sha256: str = ""
    served_models: dict = field(default_factory=dict)


def run_arm(fp, fixtures: list[dict], cfg: RunConfig,
            clock=time.monotonic) -> dict:
    """Run one 3b arm over the resolved fixtures. `fp` is the bound
    orchestrator.finding_promotion module (bind_promotion_site). Enforces the
    60-min arm cap BETWEEN candidates (a candidate's own wall is bounded by
    the site's 3 x 800 s budget); on cap, remaining candidates are recorded
    not_run_time_cap and the artifact states the partial (rule 7)."""
    planned = (fixtures[: cfg.limit] if cfg.limit is not None
               else list(fixtures))
    calls_path = Path(cfg.calls_log_path)
    artifact: dict[str, Any] = {
        "schema": "qwen_ab_3bcd.3b.v1",
        "stage": STAGE,
        "generated_at": _utc_now(),
        "arm_label": cfg.arm_label,
        "bench_id": cfg.bench_id,
        "provenance": {
            "prereg": "experiments/PREREG_qwen_ab_3bcd_2026-08-18.md#3b",
            "image": cfg.image,
            "endpoint": ENDPOINT,
            "served_model_label": cfg.model_label,
            "served_models_live": cfg.served_models,
            "backend_reregistered": "vllm-qwen",
            "calls_log_path": str(cfg.calls_log_path),
            "surfaced_path": str(cfg.surfaced_path),
            "surfaced_sha256": cfg.surfaced_sha256,
            "loop_memory_path": str(cfg.loop_memory_path),
            "loop_memory_sha256": cfg.loop_memory_sha256,
            "expected_finding_ids": list(EXPECTED_FINDING_IDS),
            "fixtures": [
                {"finding_id": f["finding_id"],
                 "source_iteration_id": f["source_iteration_id"],
                 "promoted_at": f.get("promoted_at"),
                 "historical_adversarial": f.get("historical_adversarial")}
                for f in fixtures],
            "planned_finding_ids": [f["finding_id"] for f in planned],
            "n_skeptics": cfg.n_skeptics,
            "vote_budget": dict(VOTE_BUDGET),
            "time_cap_s": cfg.time_cap_s,
            "limit": cfg.limit,
            "effective_config": {
                k: v for k, v in asdict(cfg).items() if k != "served_models"},
        },
        "candidates": [],
        "time_cap_hit": False,
        "completed": False,
    }

    t0 = clock()
    for pos, fx in enumerate(planned):
        elapsed = clock() - t0
        if elapsed >= cfg.time_cap_s:
            artifact["time_cap_hit"] = True
            for rest in planned[pos:]:
                artifact["candidates"].append({
                    "finding_id": rest["finding_id"],
                    "source_iteration_id": rest["source_iteration_id"],
                    "status": "not_run_time_cap",
                })
            print(f"TIME CAP: {elapsed:.0f}s >= {cfg.time_cap_s:.0f}s — "
                  f"{len(planned) - pos} candidate(s) not run; completed "
                  "candidates are the arm's result (rule 7)", flush=True)
            break

        loop_row = fx["loop_row"]
        claim = fp._claim_text(loop_row)
        rec: dict[str, Any] = {
            "finding_id": fx["finding_id"],
            "source_iteration_id": fx["source_iteration_id"],
            "historical_adversarial": fx.get("historical_adversarial"),
            "claim_head": claim[:200],
        }
        pre_lines = len(_read_raw_lines(calls_path))
        t_start = clock()
        try:
            tally = fp._adversarial_vote(
                loop_row, claim,
                n_skeptics=cfg.n_skeptics,
                backend="vllm-qwen",
                parent_request_id=cfg.bench_id,
            )
            rec["status"] = "completed"
            rec["tally"] = tally
        except Exception as exc:  # noqa: BLE001 — recorded, never swallowed
            rec["status"] = "error"
            rec["tally"] = None
            rec["error"] = f"{type(exc).__name__}: {exc}"
        rec["wall_s"] = round(clock() - t_start, 3)
        appended = _parse_jsonl_lines(_read_raw_lines(calls_path)[pre_lines:])
        rec["calls_appended"] = len(appended)
        rec["skeptic_calls"] = sum(
            1 for r in appended
            if str(r.get("caller_tag") or "").startswith(SKEPTIC_TAG_PREFIX))
        artifact["candidates"].append(rec)
        if rec["status"] == "completed":
            t = rec["tally"]
            print(f"[{pos + 1}/{len(planned)}] {fx['finding_id']}: "
                  f"n_voting={t.get('n_voting')} n_refuted={t.get('n_refuted')} "
                  f"survived={t.get('survived')} "
                  f"qwen_failures={t.get('qwen_failures')} "
                  f"({rec['wall_s']}s, {rec['skeptic_calls']} skeptic calls)",
                  flush=True)
        else:
            print(f"[{pos + 1}/{len(planned)}] {fx['finding_id']}: "
                  f"ERROR {rec.get('error')}", flush=True)

    all_log_rows = read_jsonl(calls_path)
    artifact["criteria"] = evaluate_criteria(
        artifact["candidates"], all_log_rows, cfg.bench_id, cfg.n_skeptics)
    artifact["errors"] = [
        f"{c['finding_id']}: {c['error']}"
        for c in artifact["candidates"] if c.get("status") == "error"]
    artifact["completed"] = (
        not artifact["time_cap_hit"]
        and all(c.get("status") == "completed"
                for c in artifact["candidates"]))
    artifact["total_wall_s"] = round(clock() - t0, 1)
    return artifact


def write_artifact(artifact: dict, out_path: Path | str) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False))
    return out_path


# ── CLI ──────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Stage-3b finding_promotion multi-vote battery "
                    "(PREREG_qwen_ab_3bcd_2026-08-18.md §3b; one arm per run)")
    ap.add_argument("--arm-label", required=True,
                    help="arm tag, e.g. qwen36 / qwen38 (names the per-arm "
                         "calls log and the artifact)")
    ap.add_argument("--model", required=True,
                    help="SERVED model label on :8001 — re-registered onto "
                         "backend vllm-qwen before any call")
    ap.add_argument("--image", required=True,
                    help="serving image tag/digest (provenance)")
    ap.add_argument("--out", default=None,
                    help="artifact path (default runs/3b_<arm>_<utc>.json)")
    ap.add_argument("--limit", type=int, default=None,
                    help="smoke: run only the first N fixtures (default all "
                         "3; 0 = resolve/bind/provenance only, zero votes)")
    args = ap.parse_args(argv)

    if os.environ.get("MOCK_LLM"):
        print("REFUSE: MOCK_LLM is set — stubbed backends would fake the "
              "skeptic panel and poison the A/B liveness evidence. Re-run "
              "with `env -u MOCK_LLM` (CLAUDE.md rule 10).")
        return 2

    # Calls-log isolation FIRST (env before the site import binds it).
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    calls_log = str(RUNS_DIR / f"{args.arm_label}.calls.jsonl")
    fp = bind_promotion_site(calls_log)

    # A/B seam: re-register vllm-qwen with the served label BEFORE any call.
    reregister_backend(args.model)
    served = fetch_served_models()
    if served["error"]:
        print(f"WARN: GET {MODELS_URL} failed ({served['error']}) — recorded; "
              "liveness will judge the endpoint honestly", flush=True)
    elif args.model not in served["ids"]:
        print(f"WARN: --model {args.model!r} not among served ids "
              f"{served['ids']} — recorded; a model-name 400 is a DRIVER bug "
              "(prereg Common)", flush=True)

    fixtures, surfaced_sha, loop_sha = resolve_fixtures()
    bench_id = f"qwen-ab-3b-{args.arm_label}-{uuid.uuid4().hex[:8]}"
    cfg = RunConfig(
        arm_label=args.arm_label, model_label=args.model, image=args.image,
        calls_log_path=calls_log, bench_id=bench_id, limit=args.limit,
        surfaced_sha256=surfaced_sha, loop_memory_sha256=loop_sha,
        served_models=served,
    )
    artifact = run_arm(fp, fixtures, cfg)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out) if args.out else (
        RUNS_DIR / f"{STAGE}_{args.arm_label}_{stamp}.json")
    write_artifact(artifact, out)

    crit = artifact["criteria"]
    print(json.dumps({
        "liveness_fraction": crit["liveness"]["fraction"],
        "liveness_pass": crit["liveness"]["pass"],
        "empty_at_cap_count": crit["empty_at_cap"]["count_whole_arm_log"],
        "empty_at_cap_pass": crit["empty_at_cap"]["pass"],
        "time_cap_hit": artifact["time_cap_hit"],
        "completed": artifact["completed"],
    }, indent=1))
    print("wrote", out)
    return 0 if artifact["completed"] and not artifact["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
