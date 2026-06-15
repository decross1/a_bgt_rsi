// A single HealthStrip-style tile for HOST RAM usage. The integrator slots
// this beside the existing GPU/CPU tiles (work order PART 1, center order 3).
//
// HONEST DATA STANCE (inviolate rule 4). Host telemetry (TelemetrySample.host)
// carries `mem_used_mb` ONLY — the psutil sampler emits used MB, never a total
// (ui/sampler/sources/psutil_procs.py). So this tile shows host RAM *used*
// (GiB); it does NOT invent a total, a free figure, or a percent. When host
// telemetry is null/absent (psutil read failed) or `mem_used_mb` is missing,
// the tile renders an explicit unavailable state ("—", available:false stance)
// — never a fabricated number.
//
// POLL DISCIPLINE mirrors HumanTodoPanel/SurfacedFindingsPanel: an `initial`
// prop pins the render (fixtures/tests NEVER fetch), otherwise it polls
// /api/telemetry/recent so it stands alone without parent wiring.
import { useEffect, useState } from "react";
import { getRecentTelemetry } from "../api/http";
import { fmt } from "../format";
import type { TelemetrySample } from "../types/schemas";
import MetricTile from "./MetricTile";

// The host RAM-used series (GiB) and the latest value, or null when no host
// sample carries mem_used_mb. Pure — the test drives it through `initial`.
export function hostMemSeries(
  samples: TelemetrySample[],
): { values: (number | null)[]; latestGiB: number | null } {
  const list = Array.isArray(samples) ? samples : [];
  const values = list.map((s) => {
    const mb = s?.host?.mem_used_mb;
    return typeof mb === "number" && Number.isFinite(mb) ? mb / 1024 : null;
  });
  // Walk from the end for the most recent usable reading (a trailing null host
  // sample must not blank a tile that has fresh data just behind it).
  let latestGiB: number | null = null;
  for (let i = values.length - 1; i >= 0; i--) {
    if (values[i] != null) {
      latestGiB = values[i];
      break;
    }
  }
  return { values, latestGiB };
}

export default function HostMemoryTile({
  initial,
  pollMs = 5000,
}: {
  initial?: TelemetrySample[];
  pollMs?: number;
}) {
  const [samples, setSamples] = useState<TelemetrySample[]>(initial ?? []);

  useEffect(() => {
    if (initial !== undefined) return;
    let active = true;
    const load = () =>
      getRecentTelemetry()
        .then((r) => {
          // A version-skewed / malformed 200 body can be null or a non-object
          // (the producer JSON is forwarded raw, never validated). `r?.samples`
          // degrades that to the absent series instead of throwing on the read.
          if (active) setSamples(Array.isArray(r?.samples) ? r.samples : []);
        })
        .catch(() => {
          // Leave the last good series; an unavailable read surfaces as the
          // honest "—" via the empty/absent latest value, not a fake number.
        });
    load();
    const id = setInterval(load, pollMs);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [initial, pollMs]);

  const { values, latestGiB } = hostMemSeries(samples);
  const available = latestGiB != null;

  return (
    <MetricTile
      label="Host RAM"
      value={available ? fmt(latestGiB, 1) : "—"}
      unit={available ? "GiB" : undefined}
      tone="idle"
      values={available ? values : undefined}
      note={available ? "used" : "host telemetry unavailable"}
    />
  );
}
