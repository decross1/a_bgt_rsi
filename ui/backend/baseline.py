"""Healthy-baseline reference card data (ui_plan.md sections 5.3, 9).

The dashboard's day-1 baseline card is data-driven: each row is sourced
from the apparatus's own measurements when those exist, and falls back to
the documented constants from ui_plan.md section 5.3 until they do. Every
returned row is annotated source="measured" or source="documented" so the
card can show the operator which is which.

Measurement sources, when present:
  - bench/mtp.csv                 MTP-enabled sweep (decode_tok_per_s) — the
                                  current measurement after D-022 turned on
                                  speculative decoding (vLLM v0.21.0)
  - bench/day1.csv                pre-MTP day-1 sweep (decode_tok_per_s)
  - run_state/week1.state.json    metric_log.day1_tokens_per_sec (pre-MTP)

Track A may still be on day 1 with none committed; the functions here
degrade to the documented constants rather than failing.
"""
import csv
import json
import statistics
from pathlib import Path


# Documented constants — from ui_plan.md section 5.3 (r2) and CLAUDE.md.
# Used verbatim until the apparatus commits a measured equivalent.
DOCUMENTED = {
    "decode_tok_per_s": "MTP-engaged expected band [80,130], single-stream ≈96; "
                        "NVFP4-only ≈52; hard floor 40; MTP-engaged signal ≥50",
    "idle_power_w": "≈5 W measured day 1 (apparatus passes ≤35 W)",
    "gpu_temp": "green ≤70 °C · amber 70-80 · red >80",
    "cpu_temp": "green ≤75 °C · amber 75-85 · red >85",
    "gpu_power": "green ≤90 W · amber 90-110 · red >110",
    "stack": "CUDA 13.0 · MARLIN NVFP4 MoE · vLLM v0.21.0 · "
             "MTP enabled (Gemma 4 drafter, num_speculative_tokens=4)",
}


def _read_bench_decode(bench_csv):
    """Median/count/range of decode_tok_per_s from a bench CSV, or None.

    Works on any sweep CSV carrying a `decode_tok_per_s` column —
    bench/day1.csv (pre-MTP) and bench/mtp.csv (MTP-enabled) both qualify.

    None covers every degraded case the same way: file absent, unreadable,
    no decode_tok_per_s column, or no parseable values.
    """
    path = Path(bench_csv)
    if not path.exists():
        return None
    values = []
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                raw = (row.get("decode_tok_per_s") or "").strip()
                if not raw:
                    continue
                try:
                    values.append(float(raw))
                except ValueError:
                    continue
    except OSError:
        return None
    if not values:
        return None
    return {"median": round(statistics.median(values), 1),
            "count": len(values),
            "min": round(min(values), 1),
            "max": round(max(values), 1)}


def _read_state_tok_s(state_file):
    """metric_log.day1_tokens_per_sec, or None if missing/unpopulated."""
    path = Path(state_file)
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = (state.get("metric_log") or {}).get("day1_tokens_per_sec")
    return value if isinstance(value, (int, float)) else None


def compute_baseline(bench_csv, state_file, mtp_csv=None):
    """Return {rows: [{key, label, value, source, documented?}]}.

    `source` is "measured" when the value came from bench/state, else
    "documented". A measured row also carries `documented` so the card can
    show the expected figure beside the observed one — the two have drifted
    before (idle power 25 W estimate vs ~5 W measured; ui_plan.md section 9).

    `mtp_csv` (bench/mtp.csv) is the current decode measurement after D-022
    enabled MTP speculative decoding. When it exists it drives the decode
    row; bench/day1.csv + metric_log are kept alongside as the pre-MTP
    figures so the speed-up is visible.
    """
    day1 = _read_bench_decode(bench_csv)
    mtp = _read_bench_decode(mtp_csv) if mtp_csv else None
    state_tok_s = _read_state_tok_s(state_file)

    rows = []

    # Decode tok/s — data-driven. bench/mtp.csv is the current (MTP-enabled)
    # measurement; the pre-MTP day-1 figures ride alongside for contrast.
    if mtp:
        parts = [f"MTP-engaged: bench/mtp.csv median {mtp['median']} tok/s "
                 f"({mtp['count']} prompts, {mtp['min']}-{mtp['max']})"]
        if day1:
            parts.append(f"pre-MTP day-1 bench median {day1['median']} tok/s")
        elif state_tok_s is not None:
            parts.append(f"pre-MTP state metric_log {state_tok_s} tok/s")
        rows.append({"key": "decode_tok_per_s", "label": "Decode tok/s",
                     "value": "; ".join(parts), "source": "measured",
                     "documented": DOCUMENTED["decode_tok_per_s"]})
    elif day1 or state_tok_s is not None:
        parts = []
        if day1:
            parts.append(
                f"day-1 bench median {day1['median']} tok/s "
                f"({day1['count']} prompts, {day1['min']}-{day1['max']})")
        if state_tok_s is not None:
            parts.append(f"state metric_log {state_tok_s} tok/s")
        rows.append({"key": "decode_tok_per_s", "label": "Decode tok/s",
                     "value": "; ".join(parts), "source": "measured",
                     "documented": DOCUMENTED["decode_tok_per_s"]})
    else:
        rows.append({"key": "decode_tok_per_s", "label": "Decode tok/s",
                     "value": DOCUMENTED["decode_tok_per_s"],
                     "source": "documented"})

    # The remaining rows have no committed measurement source yet — the
    # idle-power and threshold figures are not in bench/day1.csv or the
    # state metric_log. They stay documented; revisit if a source lands.
    for key, label in (("idle_power_w", "GPU idle power"),
                        ("gpu_temp", "GPU temp"),
                        ("cpu_temp", "CPU temp"),
                        ("gpu_power", "GPU power"),
                        ("stack", "Stack")):
        rows.append({"key": key, "label": label,
                     "value": DOCUMENTED[key], "source": "documented"})

    return {"rows": rows}
