"""Stage-3d restate-hook battery (Qwen A/B battery, prereg-locked).

Spec: experiments/PREREG_qwen_ab_3bcd_2026-08-18.md §3d (v2, LOCKED).
Runs orchestrator.restate_skeptic.restate_attack(hypothesis_text=<case
hypothesis>, iteration_id=None, backend="vllm-qwen",
novelty_top_neighbor_id=None) over the 4 pinned lit-falsification cases.
No production writes — calls log only (the driver sets set_run_id for
call-log attribution but does NOT write run_state/active_run.json).

LOCKED criteria per arm (operationalized so they CAN fail — the return
value fail-opens everything to in-enum 'inconclusive', so it cannot gate):
  (i)  canonicalize leg parses iff returned `canonical_statement` is
       non-null, 4/4;
  (ii) judge leg parses iff the arm's calls-log row for
       caller_tag=restate_judge contains a JSON object with
       `restate_verdict` in the enum, 4/4 — measured from the CALLS LOG,
       never from the fail-open return.
Reported non-gating: agreement with historical verdicts (the returned
verdict + each case's expected_* fields ride in the artifact for the
memo's comparison); output-token utilization vs the RESTATE_MAX_TOKENS
=3072 cap (first 3.8 data on the D-070 residual). Time cap 30 min/arm
(rule 7): on cap, completed cases are the arm's result, partial stated.

Ordering discipline: main() sets LOOP_V0_CALLS_LOG from --arm BEFORE any
orchestrator/workers import (restate_skeptic AND workers.novelty_skeptic
bind CALLS_LOG_PATH at import time), then re-registers backend vllm-qwen
with the served-model label (stage3a pattern) before any site call.
Module top has NO site imports. A served-model mismatch REFUSES up front
(exit 3) — a model-name 400 is a driver bug, never a 3.8 finding.
Per-case judge rows are located by calls-log growth across the
restate_attack call (arms run serially under the pause file; no
concurrent writer shares the per-arm log).

Run: env -u MOCK_LLM .venv-chroma/bin/python -m \
  bench.qwen_ab_3bcd.restate_battery --arm <served_model_label> \
  --image <tag-or-digest>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

STAGE = "3d"
RUNS_DIR = Path(__file__).resolve().parent / "runs"
CASES_PATH = REPO_ROOT / "experiments/lit_falsification_battery/cases.jsonl"
DEFAULT_ENDPOINT = "http://127.0.0.1:8001/v1"

# The 4 pinned case ids, VERBATIM from the prereg §3d (the checklist §3d
# residual-2 set). Hypothesis fields come from cases.jsonl.
CASE_IDS = (
    "redisc_on_01_tft_reciprocity",
    "redisc_on_03_quantal_response",
    "canary_on_01_ultimatum_plain",
    "canary_on_02_hawkdove_ess",
)

TIME_CAP_S = 30 * 60.0                  # prereg §3d: 30 min per arm
CANON_TAG = "restate_canonicalize"      # restate_skeptic caller_tags
JUDGE_TAG = "restate_judge"
RESTATE_MAX_TOKENS = 3072               # prereg-stated cap (module value
                                        # re-verified + recorded in main)
ALLOWED_RESTATE_VERDICTS = ("restated", "not_restated", "inconclusive")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_jsonl(path: Path | str) -> list[dict]:
    """Tolerant JSONL read: missing file -> [], malformed/blank lines
    skipped (partial-write tolerance, finding_session._read_jsonl norm)."""
    p = Path(path)
    if not p.exists():
        return []
    rows = []
    for line in p.read_text().splitlines():
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


def load_cases(path: Path | str = CASES_PATH) -> tuple[list[dict], str]:
    """(cases, sha256-of-file-bytes) — the sha goes into provenance
    (bench/fp8_ab/driver.py pattern)."""
    raw = Path(path).read_bytes()
    cases = [json.loads(line) for line in raw.decode("utf-8").splitlines()
             if line.strip()]
    return cases, hashlib.sha256(raw).hexdigest()


def resolve_cases(cases: list[dict]) -> list[dict]:
    """The 4 pinned cases in CASE_IDS order. FAIL-CLOSED on any missing id —
    never substitutes (the fp8 resolve_sentinels discipline)."""
    by_id = {c.get("case_id"): c for c in cases}
    missing = [cid for cid in CASE_IDS if cid not in by_id]
    if missing:
        raise RuntimeError(
            f"pinned case id(s) {missing} have no exact match in cases.jsonl "
            "— refusing to guess (prereg §3d fixture pin)")
    return [by_id[cid] for cid in CASE_IDS]


def judge_parse(completion: str, extract_fn, strip_fn) -> str | None:
    """The gate-(ii) parse, applied to a calls-log row's completion: the
    site's own extractor first on the raw text, then on the
    channel-markup-stripped text (restate_skeptic's exact fallback order).
    Returns the in-enum restate_verdict, or None (off-enum/no JSON)."""
    completion = completion or ""
    payload = extract_fn(completion)
    if payload is None:
        payload = extract_fn(strip_fn(completion))
    if (isinstance(payload, dict)
            and payload.get("restate_verdict") in ALLOWED_RESTATE_VERDICTS):
        return payload["restate_verdict"]
    return None


def _utilization(rows: list[dict]) -> list[dict]:
    """Per-row output-token utilization vs the row's own recorded cap
    (reported non-gating — the D-070 residual's first 3.8 data)."""
    out = []
    for r in rows:
        usage = r.get("usage") or {}
        ot, mt = usage.get("output_tokens"), r.get("max_tokens")
        out.append({
            "caller_tag": r.get("caller_tag"),
            "request_id": r.get("request_id"),
            "output_tokens": ot,
            "max_tokens": mt,
            "utilization": (round(ot / mt, 4)
                            if isinstance(ot, (int, float))
                            and isinstance(mt, (int, float)) and mt else None),
        })
    return out


def run_fixture(case: dict, attack_fn, calls_log_path: str, extract_fn,
                strip_fn, clock=time.monotonic) -> dict:
    """One case: snapshot the calls-log length, run restate_attack, then
    evaluate both legs — (i) from the RETURN's canonical_statement, (ii)
    from the NEW judge-tagged calls-log rows (never the fail-open return).
    Exceptions are recorded (status='error'), never masked."""
    rec: dict = {"case_id": case["case_id"], "status": "ok", "error": None,
                 "restate_verdict": None, "canonical_statement_head": None,
                 "restating_doc_id": None, "rationale_head": None,
                 "model": None, "backend": None,
                 "canonicalize_parsed": False, "judge_parsed": False,
                 "judge_verdict_from_log": None, "judge_rows_in_log": 0,
                 "expected_novelty": case.get("expected_novelty"),
                 "expected_critic": case.get("expected_critic"),
                 "token_utilization": [], "wall_s": None}
    before = len(read_jsonl(calls_log_path))
    t0 = clock()
    try:
        result = attack_fn(
            hypothesis_text=case["hypothesis"],
            iteration_id=None,
            backend="vllm-qwen",
            novelty_top_neighbor_id=None,
        )
        rec["restate_verdict"] = result.get("restate_verdict")
        canon = result.get("canonical_statement")
        rec["canonical_statement_head"] = (canon or "")[:200] or None
        rec["restating_doc_id"] = result.get("restating_doc_id")
        rec["rationale_head"] = (result.get("rationale") or "")[:200]
        rec["model"] = result.get("model")
        rec["backend"] = result.get("backend")
        rec["canonicalize_parsed"] = canon is not None      # gate (i)
    except Exception as exc:  # noqa: BLE001 — recorded, never masked
        rec["status"] = "error"
        rec["error"] = f"{type(exc).__name__}: {exc}"
    rec["wall_s"] = round(clock() - t0, 3)

    # Gate (ii) + utilization: measured from the LOG rows this call added.
    new_rows = read_jsonl(calls_log_path)[before:]
    judge_rows = [r for r in new_rows if r.get("caller_tag") == JUDGE_TAG]
    rec["judge_rows_in_log"] = len(judge_rows)
    for r in judge_rows:
        verdict = judge_parse(r.get("completion") or "", extract_fn, strip_fn)
        if verdict is not None:
            rec["judge_parsed"] = True
            rec["judge_verdict_from_log"] = verdict
            break
    rec["token_utilization"] = _utilization(
        [r for r in new_rows if r.get("caller_tag") in (CANON_TAG, JUDGE_TAG)])
    return rec


def evaluate_criteria(fixtures: list[dict]) -> dict:
    """The two LOCKED §3d gates, each an independent pass/fail (rule 4 —
    a partial run fails because 4/4 requires 4)."""
    n = len(CASE_IDS)
    canon = sum(1 for f in fixtures if f.get("canonicalize_parsed"))
    judge = sum(1 for f in fixtures if f.get("judge_parsed"))
    gates = {
        "canonicalize_nonnull_4of4": {
            "pass": canon == n,
            "observed": f"{canon}/{n}",
            "criterion": ("canonicalize leg parses iff returned "
                          "canonical_statement is non-null, 4/4"),
        },
        "judge_log_parse_4of4": {
            "pass": judge == n,
            "observed": f"{judge}/{n}",
            "criterion": (f"calls-log row for caller_tag={JUDGE_TAG} contains "
                          "a JSON object with restate_verdict in the enum, "
                          "4/4 — measured from the log, never the fail-open "
                          "return"),
        },
    }
    utils = [u for f in fixtures for u in f.get("token_utilization", [])
             if u.get("utilization") is not None]
    by_tag: dict = {}
    for u in utils:
        by_tag.setdefault(u["caller_tag"], []).append(u["utilization"])
    return {
        "gates": gates,
        "all_pass": all(g["pass"] for g in gates.values()),
        "reported_non_gating": {
            "token_utilization_vs_cap": {
                tag: {"n": len(vals),
                      "max": round(max(vals), 4),
                      "mean": round(sum(vals) / len(vals), 4)}
                for tag, vals in sorted(by_tag.items())},
            "verdict_vs_expected": [
                {"case_id": f["case_id"],
                 "restate_verdict": f.get("restate_verdict"),
                 "judge_verdict_from_log": f.get("judge_verdict_from_log"),
                 "expected_novelty": f.get("expected_novelty"),
                 "expected_critic": f.get("expected_critic")}
                for f in fixtures],
        },
    }


def run_arm(*, arm: str, image: str, endpoint: str, attack_fn, extract_fn,
            strip_fn, calls_log_path: str, served_models: dict,
            cases_path=CASES_PATH, clock=time.monotonic,
            time_cap_s: float = TIME_CAP_S,
            restate_max_tokens_module: int | None = None) -> dict:
    """Run the 4-case battery for one arm; returns the artifact dict
    (partial when the 30-min cap fires — rule 7, partial stated)."""
    cases, cases_sha = load_cases(cases_path)
    pinned = resolve_cases(cases)                 # fail-closed, before calls
    artifact = {
        "schema": "qwen_ab_3bcd.restate.v1",
        "stage": STAGE,
        "generated_at": _utc_now(),
        "arm": arm,
        "provenance": {
            "prereg": "experiments/PREREG_qwen_ab_3bcd_2026-08-18.md#3d",
            "image": image,
            "endpoint": endpoint,
            "served_models": served_models,       # live GET /v1/models ids
            "arm_label": arm,
            "calls_log_path": str(calls_log_path),
            "cases_path": str(cases_path),
            "cases_sha256": cases_sha,
            "case_ids": list(CASE_IDS),
            "restate_max_tokens_prereg": RESTATE_MAX_TOKENS,
            "restate_max_tokens_module": restate_max_tokens_module,
            "time_cap_s": time_cap_s,
            "entry_points": {
                "attack": ("orchestrator.restate_skeptic.restate_attack("
                           "hypothesis_text=..., iteration_id=None, "
                           "backend='vllm-qwen', "
                           "novelty_top_neighbor_id=None)"),
            },
        },
        "fixtures": [],
        "skipped": [],
    }
    t0 = clock()
    for case in pinned:
        if clock() - t0 >= time_cap_s:
            artifact["skipped"].append({"case_id": case["case_id"],
                                        "reason": "time_cap"})
            continue
        artifact["fixtures"].append(run_fixture(
            case, attack_fn, calls_log_path, extract_fn, strip_fn,
            clock=clock))
    artifact["total_wall_s"] = round(clock() - t0, 1)
    artifact["time_cap"] = {"cap_s": time_cap_s,
                            "hit": bool(artifact["skipped"]),
                            "cases_run": len(artifact["fixtures"]),
                            "cases_planned": len(CASE_IDS)}
    artifact["completed"] = not artifact["skipped"]
    artifact["criteria"] = evaluate_criteria(artifact["fixtures"])
    return artifact


def fetch_served_model_ids(endpoint: str, http_get_json=None) -> dict:
    """GET <endpoint>/models -> {'ids': [...], 'error': None|str}. Required
    provenance (prereg Common); errors recorded, never invented away."""
    url = endpoint.rstrip("/") + "/models"
    if http_get_json is None:
        def http_get_json(u):
            import requests  # lazy: hermetic tests never import it
            resp = requests.get(u, timeout=10.0)
            resp.raise_for_status()
            return resp.json()
    try:
        body = http_get_json(url)
        ids = [m.get("id") for m in (body.get("data") or [])
               if isinstance(m, dict)]
        return {"ids": ids, "error": None, "url": url}
    except Exception as exc:  # noqa: BLE001 — recorded
        return {"ids": [], "error": f"{type(exc).__name__}: {exc}", "url": url}


def main(argv: list[str] | None = None) -> int:
    # MOCK refusal FIRST — restate_attack itself short-circuits to a stub
    # under MOCK_LLM, which would fake every leg of this battery.
    if os.environ.get("MOCK_LLM"):
        print("REFUSE: MOCK_LLM is set — restate_attack returns a stub under "
              "MOCK_LLM, faking both legs. Re-run with `env -u MOCK_LLM` "
              "(CLAUDE.md rule 10).")
        return 2

    ap = argparse.ArgumentParser(
        description="Stage-3d restate-hook battery "
                    "(PREREG_qwen_ab_3bcd_2026-08-18 §3d)")
    ap.add_argument("--arm", required=True,
                    help="served-model label; also the arm label + the "
                         "vllm-qwen re-register target")
    ap.add_argument("--image", required=True,
                    help="serving image tag/digest (frozen provenance)")
    ap.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    ap.add_argument("--out", default=None,
                    help="artifact path (default runs/3d_<arm>_<utc>.json)")
    args = ap.parse_args(argv)

    arm_safe = args.arm.replace("/", "_")
    # Calls-log isolation: set BEFORE any orchestrator/workers import —
    # restate_skeptic and workers.novelty_skeptic bind CALLS_LOG_PATH at
    # import time (prereg Common). Shared per-arm log with 3b/3c by design.
    calls_log_path = str(RUNS_DIR / f"{arm_safe}.calls.jsonl")
    os.environ["LOOP_V0_CALLS_LOG"] = calls_log_path
    RUNS_DIR.mkdir(parents=True, exist_ok=True)

    # Backend re-register seam (stage3a pattern): point vllm-qwen at the
    # actually-served label BEFORE any site call.
    from agent_wrapper.backends import register_backend
    from agent_wrapper.backends.ollama_openai import OllamaBackend
    import agent_wrapper.wrapper  # noqa: F401  (ensures base registrations ran)
    register_backend(OllamaBackend(
        name="vllm-qwen", base_url=args.endpoint, model=args.arm))

    served = fetch_served_model_ids(args.endpoint)
    if served["error"] or args.arm not in served["ids"]:
        # Preflight refusal: a model-name 400 is a DRIVER bug, never a 3.8
        # finding (prereg Common) — refuse rather than burn the battery.
        print(f"REFUSE: served-model preflight failed for arm {args.arm!r}: "
              f"ids={served['ids']} error={served['error']} "
              f"({served['url']}). Fix the serving slot or the --arm label.")
        return 3

    from agent_wrapper.cleanup import strip_channel_markup
    from agent_wrapper.wrapper import set_run_id
    from orchestrator import restate_skeptic
    from workers.novelty_skeptic import _extract_json_object

    if restate_skeptic.RESTATE_MAX_TOKENS != RESTATE_MAX_TOKENS:
        # Report, never coerce (rule 4): the prereg names 3072; a drifted
        # module value is recorded in provenance and stated here.
        print(f"WARN: orchestrator.restate_skeptic.RESTATE_MAX_TOKENS="
              f"{restate_skeptic.RESTATE_MAX_TOKENS} != prereg "
              f"{RESTATE_MAX_TOKENS}; recorded in provenance, cap NOT "
              "silently rewritten.")

    # Call-log attribution only (contextvar) — NO active_run.json write:
    # prereg §3d pins "no production writes (calls log only)".
    set_run_id(f"bench_3d_{arm_safe}")
    try:
        artifact = run_arm(
            arm=args.arm, image=args.image, endpoint=args.endpoint,
            attack_fn=restate_skeptic.restate_attack,
            extract_fn=_extract_json_object, strip_fn=strip_channel_markup,
            calls_log_path=calls_log_path, served_models=served,
            restate_max_tokens_module=restate_skeptic.RESTATE_MAX_TOKENS)
    finally:
        set_run_id(None)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = (Path(args.out) if args.out
           else RUNS_DIR / f"{STAGE}_{arm_safe}_{stamp}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, indent=2, ensure_ascii=False))
    print(json.dumps(artifact["criteria"], indent=1))
    print("time_cap:", artifact["time_cap"])
    print("wrote", out)
    return 0 if artifact["completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
