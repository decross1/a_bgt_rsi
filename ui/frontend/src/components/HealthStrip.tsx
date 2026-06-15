// Top strip: 5 GPU/host tiles, colour-coded against the day-1 baselines
// in ui_plan.md section 5.3.
import { fmt } from "../format";
import type { TelemetrySample } from "../types/schemas";
import HostMemoryTile from "./HostMemoryTile";
import MetricTile, { type Tone } from "./MetricTile";

function gpuTempTone(t: number | null | undefined): Tone {
  if (t == null) return "idle";
  if (t > 80) return "bad";
  if (t >= 70) return "warn";
  return "ok";
}

function gpuPowerTone(w: number | null | undefined): Tone {
  if (w == null) return "idle";
  if (w > 110) return "bad";
  if (w >= 90) return "warn";
  return "ok";
}

function cpuTempTone(t: number | null | undefined): Tone {
  if (t == null) return "idle";
  if (t > 85) return "bad";
  if (t >= 75) return "warn";
  return "ok";
}

function gpuUtilTone(u: number | null | undefined): Tone {
  if (u == null) return "idle";
  return u < 1 ? "idle" : "ok"; // gray when no work is running
}

export default function HealthStrip({ samples }: { samples: TelemetrySample[] }) {
  // Producer-owned telemetry is forwarded raw (house robustness doctrine): the
  // declared TelemetrySample[] cannot enforce shape at runtime. A null/absent
  // body, a non-array, or a null/non-object trailing sample must all degrade to
  // an honest "n/a"/idle tile, never blank the strip with a .map/index throw.
  const list = Array.isArray(samples) ? samples : [];
  const rawLatest = list[list.length - 1];
  const latest =
    rawLatest != null && typeof rawLatest === "object" ? rawLatest : null;
  const gpu = latest?.gpu ?? null;
  const host = latest?.host ?? null;

  const series = (pick: (s: TelemetrySample) => number | null | undefined) =>
    list.map((s) => (s != null && typeof s === "object" ? pick(s) : null));

  const memUsed = gpu?.mem_used_mb;
  const memTotal = gpu?.mem_total_mb;
  // Both must be FINITE numbers before we divide — a string/NaN/Infinity from a
  // malformed sample would otherwise toFixed() into a literal "NaN" in the tile.
  const memValue =
    typeof memUsed === "number" &&
    Number.isFinite(memUsed) &&
    typeof memTotal === "number" &&
    Number.isFinite(memTotal)
      ? `${(memUsed / 1024).toFixed(1)}/${(memTotal / 1024).toFixed(1)}`
      : "n/a";

  return (
    <div className="grid grid-cols-6 gap-3">
      <MetricTile
        label="GPU util"
        value={fmt(gpu?.util_pct)}
        unit="%"
        tone={gpuUtilTone(gpu?.util_pct)}
        values={series((s) => s.gpu?.util_pct)}
      />
      <MetricTile
        label="GPU memory"
        value={memValue}
        unit="GiB"
        tone="idle"
        values={series((s) => s.gpu?.mem_used_mb)}
        note={memValue === "n/a" ? "GB10 unified memory — n/a" : undefined}
      />
      <MetricTile
        label="GPU temp"
        value={fmt(gpu?.temp_c, 1)}
        unit="°C"
        tone={gpuTempTone(gpu?.temp_c)}
        values={series((s) => s.gpu?.temp_c)}
      />
      <MetricTile
        label="GPU power"
        value={fmt(gpu?.power_w, 1)}
        unit="W"
        tone={gpuPowerTone(gpu?.power_w)}
        values={series((s) => s.gpu?.power_w)}
      />
      <MetricTile
        label="CPU temp"
        value={fmt(host?.cpu_temp_c, 1)}
        unit="°C"
        tone={cpuTempTone(host?.cpu_temp_c)}
        values={series((s) => s.host?.cpu_temp_c)}
      />
      {/* PART 1 (2026-06-14): host RAM-used, alongside the GPU/CPU tiles.
          Fed the strip's own samples so it shares this poll (no second
          fetch); renders an honest "—" when host telemetry lacks mem. */}
      <HostMemoryTile initial={list} />
    </div>
  );
}
