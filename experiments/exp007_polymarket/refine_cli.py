"""Interactive applied-tier refinement CLI for exp007 (Polymarket PAPER forecasting).

DESIGN-ONLY / ZERO TRADING (D-018). This re-runs the exp007 *paper* forecast with
human-tweaked params (seed / temperature / n markets) against the offline fixture and
reports forecast quality (Brier vs resolved outcomes). There is NO wallet, NO orders,
NO live-data fetch, NO trading surface — it only re-invokes the existing paper-forecast
harness `experiments.exp007_polymarket.run` and scores the result.

Mirrors the `finding_session chat` per-turn CLI: verbs `start` | `turn` ONLY (no verdict
verb), one JSON envelope on stdout (exit 0) or a JSON error on stderr (exit != 0). The UI
drives it through a blessed `_exec_blessed` seam (argv array, no shell), exactly like the
two-voice / tutor chat seam.

  start  --session-id <id>                              open a refine session (default params)
  turn   --session-id <id> [--param k:v] [--message …]  apply the tweak, re-run, report quality

Tunable params: seed:int · temperature:float · n:int (markets). Under MOCK_LLM the harness
uses its deterministic stub forecast (tests); a real `env -u MOCK_LLM` turn re-runs the real
forecaster against the offline fixture.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SESSIONS_DIR = REPO_ROOT / "run_state" / "applied_sessions"
TUNABLE = {"seed": int, "temperature": float, "n": int}
DEFAULTS = {"seed": 20260605, "temperature": 0.2, "n": 5}


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _fail(msg: str, code: int = 2) -> int:
    sys.stderr.write(json.dumps({"ok": False, "error": msg}) + "\n")
    sys.stderr.flush()
    return code


def _session_path(sid: str) -> Path:
    return SESSIONS_DIR / f"{sid}.json"


def _brier(forecasts: list[dict]) -> float | None:
    """Honest Brier over rows that carry a numeric prob AND a 0/1 resolved outcome.
    None when nothing is scorable (never fabricate a score)."""
    scored = [
        (f["prob"], f["outcome"])
        for f in forecasts
        if isinstance(f.get("prob"), (int, float)) and f.get("outcome") in (0, 1)
    ]
    if not scored:
        return None
    return round(sum((p - o) ** 2 for p, o in scored) / len(scored), 4)


def _run_forecast(sid: str, params: dict) -> tuple[int, list[dict]]:
    """Re-run the exp007 PAPER forecast into a per-session out file. Returns
    (rc, forecast rows with a prob)."""
    from experiments.exp007_polymarket import run as exp007_run

    out = SESSIONS_DIR / f"{sid}_forecasts.jsonl"
    rc = exp007_run.main([
        "--n", str(params["n"]),
        "--seed", str(params["seed"]),
        "--temperature", str(params["temperature"]),
        "--out", str(out),
    ])
    if not out.exists():
        return rc, []
    rows = []
    for line in out.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if "prob" in row:  # drop per-market error rows
            rows.append(row)
    return rc, rows


def _refine_cli(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="exp007 refine")
    p.add_argument("action", choices=("start", "turn"))
    p.add_argument("--session-id", required=True)
    p.add_argument("--param", help="one tunable as key:value, e.g. temperature:0.4")
    p.add_argument("--message", help="free-text refinement intent (logged in the envelope)")
    args = p.parse_args(argv)

    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    sp = _session_path(args.session_id)

    if args.action == "start":
        params = dict(DEFAULTS)
        sp.write_text(json.dumps({"session_id": args.session_id, "params": params, "turns": 0}))
        _emit({
            "ok": True, "action": "start", "session_id": args.session_id,
            "params": params, "tunable": {k: t.__name__ for k, t in TUNABLE.items()},
            "note": "exp007 PAPER forecasting — design-only, zero trading (D-018)",
        })
        return 0

    # action == "turn"
    if not sp.exists():
        return _fail(f"no such session: {args.session_id} (call start first)")
    state = json.loads(sp.read_text())
    params = dict(state.get("params") or DEFAULTS)
    if args.param:
        if ":" not in args.param:
            return _fail(f"--param must be key:value, got {args.param!r}")
        key, raw = args.param.split(":", 1)
        key = key.strip()
        if key not in TUNABLE:
            return _fail(f"unknown param {key!r}; tunable: {sorted(TUNABLE)}")
        try:
            params[key] = TUNABLE[key](raw.strip())
        except ValueError:
            return _fail(f"param {key} must be {TUNABLE[key].__name__}, got {raw!r}")

    t0 = time.perf_counter()
    rc, forecasts = _run_forecast(args.session_id, params)
    if rc != 0 and not forecasts:
        return _fail(f"exp007 paper-forecast re-run failed (rc={rc})")
    state["params"] = params
    state["turns"] = int(state.get("turns", 0)) + 1
    sp.write_text(json.dumps(state))
    sample = [
        {
            "question": (f.get("question") or "")[:70],
            "prob": f.get("prob"),
            "market_prob": f.get("market_prob"),
            "outcome": f.get("outcome"),
        }
        for f in forecasts[:5]
    ]
    _emit({
        "ok": True, "action": "turn", "session_id": args.session_id,
        "params": params, "message": args.message, "turns": state["turns"],
        "n_forecast": len(forecasts), "brier": _brier(forecasts), "sample": sample,
        "elapsed_s": round(time.perf_counter() - t0, 1),
        "note": "PAPER forecast — zero trading (D-018)",
    })
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return _refine_cli(argv if argv is not None else sys.argv[1:])
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — envelope, never a bare traceback to the seam
        return _fail(f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
