// Healthy-baseline reference card (ui_plan.md sections 5.3, 9). Data-driven:
// rows come from GET /api/baseline, which sources decode tok/s from
// bench/day1.csv + run_state metric_log when those exist and falls back to
// documented constants otherwise. Each row is annotated measured vs
// documented so the operator can see which numbers are real.
import { useEffect, useState } from "react";
import { getBaseline } from "../api/http";
import type { BaselineRow } from "../types/schemas";

// Shown only if the backend is unreachable — the same documented constants
// the backend would return when no measurement exists.
const FALLBACK_ROWS: BaselineRow[] = [
  {
    key: "decode_tok_per_s",
    label: "Decode tok/s",
    value: "NVFP4 baseline ≈52; MTP (≈96) deferred; hard floor 40; expected band [80,130]",
    source: "documented",
  },
  {
    key: "idle_power_w",
    label: "GPU idle power",
    value: "≈5 W measured day 1 (apparatus passes ≤35 W)",
    source: "documented",
  },
  {
    key: "gpu_temp",
    label: "GPU temp",
    value: "green ≤70 °C · amber 70-80 · red >80",
    source: "documented",
  },
  {
    key: "cpu_temp",
    label: "CPU temp",
    value: "green ≤75 °C · amber 75-85 · red >85",
    source: "documented",
  },
  {
    key: "gpu_power",
    label: "GPU power",
    value: "green ≤90 W · amber 90-110 · red >110",
    source: "documented",
  },
  {
    key: "stack",
    label: "Stack",
    value: "CUDA 13.0 · MARLIN NVFP4 MoE · vLLM v0.20.0",
    source: "documented",
  },
];

function SourceBadge({ source }: { source: BaselineRow["source"] }) {
  const measured = source === "measured";
  return (
    <span
      className={
        "rounded px-1 py-0.5 text-[10px] uppercase tracking-wide " +
        (measured ? "bg-emerald-950 text-emerald-400" : "bg-zinc-800 text-zinc-500")
      }
      title={
        measured
          ? "sourced from bench/day1.csv or run_state metric_log"
          : "documented constant from ui_plan.md section 5.3 — no measurement yet"
      }
    >
      {source}
    </span>
  );
}

export default function BaselineCard() {
  const [rows, setRows] = useState<BaselineRow[]>(FALLBACK_ROWS);

  useEffect(() => {
    let cancelled = false;
    getBaseline()
      .then((d) => {
        if (!cancelled && d.rows.length) setRows(d.rows);
      })
      .catch(() => {
        /* backend unreachable — keep the documented fallback rows */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/40 p-4">
      <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
        Healthy baseline (day 1)
      </h2>
      <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
        {rows.map((row) => (
          <div key={row.key} className="flex flex-col gap-0.5">
            <div className="flex items-center gap-2">
              <dt className="text-zinc-500">{row.label}:</dt>
              <SourceBadge source={row.source} />
            </div>
            <dd className="text-zinc-300">{row.value}</dd>
            {row.source === "measured" && row.documented && (
              <dd className="text-xs text-zinc-600">expected: {row.documented}</dd>
            )}
          </div>
        ))}
      </dl>
    </div>
  );
}
