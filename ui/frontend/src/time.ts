// Shared live-clock + elapsed-time helpers. Extracted verbatim from
// ActiveIterationPanel.tsx (which originally defined useNow / elapsed /
// toolDuration locally) so /activity's HERO worker rows, the active-iteration
// panel, and the dashboard's compact line all tick off one implementation.
// Behavior is unchanged — this is a pure dedupe.
import { useEffect, useState } from "react";
import type { LoopV0ToolCall } from "./types/schemas";

/** A 1 Hz (configurable) re-rendering clock. Returns Date.now() in ms and
 * re-renders the caller on every tick so live elapsed counters advance. */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

/** Human-readable elapsed from an ISO timestamp to nowMs. "—" when the
 * input is absent/unparseable. Sub-minute shows tenths of a second; past a
 * minute it switches to "Nm Ns". */
export function elapsed(fromIso: string | null | undefined, nowMs: number): string {
  if (!fromIso) return "—";
  const t = Date.parse(fromIso);
  if (Number.isNaN(t)) return "—";
  const s = Math.max(0, (nowMs - t) / 1000);
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${(s - m * 60).toFixed(0)}s`;
}

/** Duration of a tool call: ended_at - started_at, or started_at - now when
 * still in flight. "—" when started_at is unparseable. */
export function toolDuration(call: LoopV0ToolCall, nowMs: number): string {
  const start = Date.parse(call.started_at);
  if (Number.isNaN(start)) return "—";
  const end = call.ended_at ? Date.parse(call.ended_at) : nowMs;
  const s = Math.max(0, (end - start) / 1000);
  return `${s.toFixed(1)}s`;
}
