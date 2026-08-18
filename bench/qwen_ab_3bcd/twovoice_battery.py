"""Stage-3c two-voice attacker spot-run (Qwen A/B battery, prereg-locked).

Spec: experiments/PREREG_qwen_ab_3bcd_2026-08-18.md §3c (v2, LOCKED).
Per pinned finding: start_two_voice_session(...) with the REAL surfaced/
loop_memory files but sessions redirected to bench/qwen_ab_3bcd/runs/
sessions/ (never memory/finding_sessions/), then ONE two_voice_turn
addressed at the ATTACKER only, with the single pinned verbatim opening
message below (same bytes for all fixtures and both arms).

LOCKED criteria per arm (evaluated independently — a fail-open reply can
satisfy (i) while failing (ii); ALL gates must pass):
  (i)   attacker reply has non-empty visible content after
        strip_channel_markup on 3/3;
  (ii)  zero replies equal to the '[attacker unavailable: ...]' fail-open
        string;
  (iii) empty-at-cap == 0 in the arm's calls log for
        caller_tag=finding_session_attacker (max_tokens=4096).
Empty-at-cap (prereg Common): a row with empty completion AND
usage.output_tokens == max_tokens. Whitespace-only counts as empty (the
strict direction; never lenient). Time cap 15 min/arm (rule 7): on cap,
completed fixtures are the arm's result, the partial is stated.

Ordering discipline (the 2026-08-15 false-FAIL killer + calls-log
isolation): main() sets LOOP_V0_CALLS_LOG from --arm BEFORE any
orchestrator import (finding_session binds CALLS_LOG_PATH at import
time), then re-registers backend vllm-qwen with the served-model label
(stage3a pattern, bench/critic_eval/stage3a_driver.py:33-41) before any
site call. Module top has NO site imports. A model-name mismatch against
GET /v1/models REFUSES up front (exit 3) — a 400 is a driver bug, never
a 3.8 finding. Known transient (stated in the prereg): two_voice_turn
writes run_state/active_run.json and clears it in `finally`.

Run: env -u MOCK_LLM .venv-chroma/bin/python -m \
  bench.qwen_ab_3bcd.twovoice_battery --arm <served_model_label> \
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

STAGE = "3c"
RUNS_DIR = Path(__file__).resolve().parent / "runs"
SESSIONS_ROOT = RUNS_DIR / "sessions"
SURFACED_PATH = REPO_ROOT / "memory" / "surfaced_findings.jsonl"
LOOP_MEMORY_PATH = REPO_ROOT / "memory" / "loop_memory.jsonl"
DEFAULT_ENDPOINT = "http://127.0.0.1:8001/v1"

# The SAME 3 pinned surfaced findings as stage 3b (prereg §3b fixtures,
# resolved independently at build time 2026-08-18 against
# sha256(memory/surfaced_findings.jsonl) =
# 1353ae575043e44897e358d2de876e6ea1cbcbc230768b6188b651c5440395d8).
FINDING_IDS = (
    "sf-iter-2026-07-15-001",
    "sf-iter-2026-07-30-001",
    "sf-iter-2026-08-04-001",
)

# PINNED verbatim opening user_msg (prereg §3c) — one fixed attack-opening
# prompt for ALL fixtures and BOTH arms. Its sha256 rides in provenance.
OPENING_USER_MSG = (
    "Open this interrogation with your single strongest objection to the "
    "finding as stated. Ground it in the record above: name the specific "
    "metric, value, trial count, or retrieved-evidence gap you are "
    "contesting, and say exactly what evidence would change your mind. "
    "If the record does not let you decide a point, state that plainly "
    "rather than conceding it."
)

TIME_CAP_S = 15 * 60.0                       # prereg §3c: 15 min per arm
ATTACKER_TAG = "finding_session_attacker"    # _stance_turn's caller_tag
ATTACKER_MAX_TOKENS = 4096                   # stated in the prereg gate (iii)
FAIL_OPEN_PREFIX = "[attacker unavailable"   # _stance_turn's fail-open string


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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


def snapshot_surfaced(surfaced_path: Path | str = SURFACED_PATH) -> dict:
    """Fixture snapshot: sha256 of the surfaced file + the 3 pinned rows'
    finding_id/source_iteration_id. FAIL-CLOSED when any pinned id is
    absent — never substitutes (the fp8 resolve_sentinels discipline)."""
    p = Path(surfaced_path)
    raw = p.read_bytes()
    rows = [json.loads(l) for l in raw.decode("utf-8").splitlines() if l.strip()]
    by_id = {}
    for r in rows:                      # append-only file: last write wins
        if r.get("finding_id"):
            by_id[r["finding_id"]] = r
    missing = [fid for fid in FINDING_IDS if fid not in by_id]
    if missing:
        raise RuntimeError(
            f"pinned finding_id(s) {missing} not in {p} — refusing to guess "
            "(prereg §3b/§3c fixture pin; fix is a human re-pin)")
    return {
        "path": str(p),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "findings": [
            {"finding_id": fid,
             "source_iteration_id": (by_id[fid].get("source_iteration_id")
                                     or by_id[fid].get("iteration_id"))}
            for fid in FINDING_IDS],
    }


def empty_at_cap(rows: list[dict], caller_tag: str | None = None) -> list[dict]:
    """Offending rows per the prereg Common definition: empty completion AND
    usage.output_tokens == max_tokens (row's own recorded cap). Optionally
    filtered to one caller_tag. Whitespace-only completion counts as empty
    (strict direction)."""
    out = []
    for i, r in enumerate(rows):
        if caller_tag is not None and r.get("caller_tag") != caller_tag:
            continue
        completion = r.get("completion") or ""
        usage = r.get("usage") or {}
        mt = r.get("max_tokens")
        if (not completion.strip() and mt is not None
                and usage.get("output_tokens") == mt):
            out.append({"row_index": i, "caller_tag": r.get("caller_tag"),
                        "request_id": r.get("request_id"),
                        "output_tokens": usage.get("output_tokens"),
                        "max_tokens": mt})
    return out


def run_fixture(finding_id: str, start_fn, turn_fn, strip_fn, *,
                sessions_root, surfaced_path, loop_memory_path,
                clock=time.monotonic) -> dict:
    """One fixture: open the two-voice session (state-redirected), run ONE
    attacker-addressed turn with the pinned opening message. Exceptions are
    recorded (status='error'), never masked — the criteria then fail
    honestly over the recorded fixtures."""
    rec: dict = {"finding_id": finding_id, "status": "ok", "error": None,
                 "session_id": None, "request_id": None, "reply_head": None,
                 "non_empty_visible": False, "fail_open": False,
                 "capped": False, "warning": None, "wall_s": None}
    t0 = clock()
    try:
        opened = start_fn(
            finding_id,
            surfaced_path=surfaced_path,
            loop_memory_path=loop_memory_path,
            sessions_root=sessions_root,
        )
        rec["session_id"] = opened["session_id"]
        res = turn_fn(
            finding_id,
            opened["session_id"],
            OPENING_USER_MSG,
            addressee="attacker",
            sessions_root=sessions_root,
        )
        rec["capped"] = bool(res.get("capped"))
        rec["warning"] = res.get("warning")
        replies = res.get("replies") or []
        attacker = next((r for r in replies if r.get("stance") == "attacker"),
                        None)
        if attacker is None:
            rec["status"] = "error"
            rec["error"] = (f"no attacker-stance reply in turn envelope "
                            f"(stances: {[r.get('stance') for r in replies]})")
        else:
            reply = attacker.get("reply") or ""
            rec["request_id"] = attacker.get("request_id")
            rec["reply_head"] = reply[:200]
            rec["non_empty_visible"] = bool(strip_fn(reply).strip())
            rec["fail_open"] = reply.startswith(FAIL_OPEN_PREFIX)
    except Exception as exc:  # noqa: BLE001 — recorded, never masked
        rec["status"] = "error"
        rec["error"] = f"{type(exc).__name__}: {exc}"
    rec["wall_s"] = round(clock() - t0, 3)
    return rec


def evaluate_criteria(fixtures: list[dict], calls_rows: list[dict]) -> dict:
    """The three LOCKED §3c gates, each an independent pass/fail (rule 4 —
    never coerced; a partial run fails gate (i) because 3/3 requires 3)."""
    non_empty = sum(1 for f in fixtures if f.get("non_empty_visible"))
    fail_open = sum(1 for f in fixtures if f.get("fail_open"))
    offenders = empty_at_cap(calls_rows, ATTACKER_TAG)
    attacker_rows = sum(1 for r in calls_rows
                        if r.get("caller_tag") == ATTACKER_TAG)
    gates = {
        "non_empty_visible_3of3": {
            "pass": non_empty == len(FINDING_IDS),
            "observed": f"{non_empty}/{len(FINDING_IDS)}",
            "criterion": ("attacker reply has non-empty visible content "
                          "after strip_channel_markup on 3/3"),
        },
        "zero_fail_open": {
            "pass": fail_open == 0,
            "observed": fail_open,
            "criterion": ("zero replies equal to the "
                          "'[attacker unavailable: ...]' fail-open string"),
        },
        "empty_at_cap_zero": {
            "pass": len(offenders) == 0,
            "observed": len(offenders),
            "offenders": offenders,
            "attacker_rows_in_log": attacker_rows,
            "criterion": ("empty-at-cap == 0 in the arm's calls log for "
                          f"caller_tag={ATTACKER_TAG} "
                          f"(max_tokens={ATTACKER_MAX_TOKENS})"),
        },
    }
    return {"gates": gates,
            "all_pass": all(g["pass"] for g in gates.values())}


def run_arm(*, arm: str, image: str, endpoint: str, start_fn, turn_fn,
            strip_fn, calls_log_path: str, served_models: dict,
            sessions_root=SESSIONS_ROOT, surfaced_path=SURFACED_PATH,
            loop_memory_path=LOOP_MEMORY_PATH, clock=time.monotonic,
            time_cap_s: float = TIME_CAP_S) -> dict:
    """Run the 3-fixture battery for one arm; returns the artifact dict
    (partial when the 15-min cap fires — rule 7, partial stated)."""
    snapshot = snapshot_surfaced(surfaced_path)   # fail-closed, before calls
    artifact = {
        "schema": "qwen_ab_3bcd.twovoice.v1",
        "stage": STAGE,
        "generated_at": _utc_now(),
        "arm": arm,
        "provenance": {
            "prereg": "experiments/PREREG_qwen_ab_3bcd_2026-08-18.md#3c",
            "image": image,
            "endpoint": endpoint,
            "served_models": served_models,       # live GET /v1/models ids
            "arm_label": arm,
            "calls_log_path": str(calls_log_path),
            "sessions_root": str(sessions_root),
            "surfaced_findings": snapshot,
            "loop_memory_path": str(loop_memory_path),
            "finding_ids": list(FINDING_IDS),
            "opening_user_msg": OPENING_USER_MSG,
            "opening_user_msg_sha256": _sha256_text(OPENING_USER_MSG),
            "attacker_max_tokens": ATTACKER_MAX_TOKENS,
            "time_cap_s": time_cap_s,
            "entry_points": {
                "start": "orchestrator.finding_session.start_two_voice_session",
                "turn": ("orchestrator.finding_session.two_voice_turn"
                         "(addressee='attacker')"),
            },
        },
        "fixtures": [],
        "skipped": [],
    }
    t0 = clock()
    for fid in FINDING_IDS:
        if clock() - t0 >= time_cap_s:
            artifact["skipped"].append({"finding_id": fid,
                                        "reason": "time_cap"})
            continue
        artifact["fixtures"].append(run_fixture(
            fid, start_fn, turn_fn, strip_fn, sessions_root=sessions_root,
            surfaced_path=surfaced_path, loop_memory_path=loop_memory_path,
            clock=clock))
    artifact["total_wall_s"] = round(clock() - t0, 1)
    artifact["time_cap"] = {"cap_s": time_cap_s,
                            "hit": bool(artifact["skipped"]),
                            "fixtures_run": len(artifact["fixtures"]),
                            "fixtures_planned": len(FINDING_IDS)}
    artifact["completed"] = not artifact["skipped"]
    calls_rows = read_jsonl(calls_log_path)
    artifact["criteria"] = evaluate_criteria(artifact["fixtures"], calls_rows)
    # Voice distinctness is a reported human spot-check, not a gate (prereg).
    artifact["human_spot_check"] = {
        "voice_distinctness": "pending human read of the session transcripts",
        "sessions_root": str(sessions_root),
    }
    return artifact


def fetch_served_model_ids(endpoint: str, http_get_json=None) -> dict:
    """GET <endpoint>/models -> {'ids': [...], 'error': None|str}. The id
    list is required provenance (prereg Common); errors are recorded, never
    invented away."""
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
    # MOCK refusal FIRST — before argparse, before any env/site work.
    if os.environ.get("MOCK_LLM"):
        print("REFUSE: MOCK_LLM is set — stubbed backends would fake the "
              "attacker liveness this battery measures. Re-run with "
              "`env -u MOCK_LLM` (CLAUDE.md rule 10).")
        return 2

    ap = argparse.ArgumentParser(
        description="Stage-3c two-voice attacker spot-run "
                    "(PREREG_qwen_ab_3bcd_2026-08-18 §3c)")
    ap.add_argument("--arm", required=True,
                    help="served-model label; also the arm label + the "
                         "vllm-qwen re-register target")
    ap.add_argument("--image", required=True,
                    help="serving image tag/digest (frozen provenance)")
    ap.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    ap.add_argument("--out", default=None,
                    help="artifact path (default runs/3c_<arm>_<utc>.json)")
    args = ap.parse_args(argv)

    arm_safe = args.arm.replace("/", "_")
    # Calls-log isolation: set BEFORE any orchestrator import —
    # finding_session binds CALLS_LOG_PATH at import time (prereg Common).
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
    from orchestrator.finding_session import (start_two_voice_session,
                                              two_voice_turn)

    artifact = run_arm(
        arm=args.arm, image=args.image, endpoint=args.endpoint,
        start_fn=start_two_voice_session, turn_fn=two_voice_turn,
        strip_fn=strip_channel_markup, calls_log_path=calls_log_path,
        served_models=served)
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
