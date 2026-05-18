// Live telemetry buffer: seeds from /api/telemetry/recent, then appends
// from the /api/live WebSocket. Keeps a rolling 5-minute window (300
// samples at 1 Hz) for the dashboard's sparklines.
import { useEffect, useState } from "react";
import { getRecentTelemetry } from "../api/http";
import { connectLive } from "../api/ws";
import type { TelemetrySample } from "../types/schemas";

const MAX_SAMPLES = 300;

export interface TelemetryStream {
  samples: TelemetrySample[];
  latest: TelemetrySample | null;
  connected: boolean;
}

export function useTelemetryStream(): TelemetryStream {
  const [samples, setSamples] = useState<TelemetrySample[]>([]);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    let active = true;

    getRecentTelemetry(MAX_SAMPLES)
      .then((data) => {
        if (active) setSamples(data.samples.slice(-MAX_SAMPLES));
      })
      .catch(() => {
        /* seed is best-effort; the live stream still fills the buffer */
      });

    const close = connectLive((msg) => {
      if (msg.source !== "telemetry") return;
      setSamples((prev) => {
        const next = [...prev, msg.line as unknown as TelemetrySample];
        return next.length > MAX_SAMPLES ? next.slice(-MAX_SAMPLES) : next;
      });
    }, setConnected);

    return () => {
      active = false;
      close();
    };
  }, []);

  return { samples, latest: samples[samples.length - 1] ?? null, connected };
}
