// Top strip: 5 GPU/host tiles, colour-coded against the day-1 baselines
// in ui_plan.md section 5.3.
import { fmt } from "../format";
import type { TelemetrySample } from "../types/schemas";
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
  const latest = samples[samples.length - 1] ?? null;
  const gpu = latest?.gpu ?? null;
  const host = latest?.host ?? null;

  const series = (pick: (s: TelemetrySample) => number | null | undefined) =>
    samples.map(pick);

  const memUsed = gpu?.mem_used_mb;
  const memTotal = gpu?.mem_total_mb;
  const memValue =
    memUsed != null && memTotal != null
      ? `${(memUsed / 1024).toFixed(1)}/${(memTotal / 1024).toFixed(1)}`
      : "n/a";

  return (
    <div className="grid grid-cols-5 gap-3">
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
        note={memUsed == null ? "GB10 unified memory — n/a" : undefined}
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
    </div>
  );
}
