// Live telemetry buffer: seeds from /api/telemetry/recent, then appends
// from the /api/live WebSocket. Keeps a rolling 5-minute window (300
// samples at 1 Hz) for the dashboard's sparklines.
//
// PERF (2026-08-18): WS frames arrive at 1 Hz, and every frame used to
// setState immediately — re-rendering the whole consuming page once per
// second. Frames are now buffered and FLUSHED every 2s (first frame after an
// empty buffer flushes immediately, so initial paint is not delayed): the
// page re-renders at most ~0.5 Hz for telemetry. 2s is deliberately under
// HealthVerdict's 5s staleness threshold, so batching can never manufacture
// a false "telemetry stale" — and the samples themselves keep their real
// producer timestamps (no fake freshness).
import { useEffect, useRef, useState } from "react";
import { getRecentTelemetry } from "../api/http";
import { connectLive } from "../api/ws";
import type { TelemetrySample } from "../types/schemas";

const MAX_SAMPLES = 300;
const FLUSH_MS = 2000;

export interface TelemetryStream {
  samples: TelemetrySample[];
  latest: TelemetrySample | null;
  connected: boolean;
}

export function useTelemetryStream(): TelemetryStream {
  const [samples, setSamples] = useState<TelemetrySample[]>([]);
  const [connected, setConnected] = useState(false);
  const pending = useRef<TelemetrySample[]>([]);

  useEffect(() => {
    let active = true;

    const flush = () => {
      if (!active || pending.current.length === 0) return;
      const batch = pending.current;
      pending.current = [];
      setSamples((prev) => {
        const next = [...prev, ...batch];
        return next.length > MAX_SAMPLES ? next.slice(-MAX_SAMPLES) : next;
      });
    };

    getRecentTelemetry(MAX_SAMPLES)
      .then((data) => {
        if (active) setSamples(data.samples.slice(-MAX_SAMPLES));
      })
      .catch(() => {
        /* seed is best-effort; the live stream still fills the buffer */
      });

    let hadFirstFrame = false;
    const close = connectLive((msg) => {
      if (msg.source !== "telemetry") return;
      pending.current.push(msg.line as unknown as TelemetrySample);
      // The very first frame paints immediately; the batch timer takes over
      // from there.
      if (!hadFirstFrame) {
        hadFirstFrame = true;
        flush();
      }
    }, setConnected);
    const flushId = setInterval(flush, FLUSH_MS);

    return () => {
      active = false;
      clearInterval(flushId);
      close();
    };
  }, []);

  return { samples, latest: samples[samples.length - 1] ?? null, connected };
}
