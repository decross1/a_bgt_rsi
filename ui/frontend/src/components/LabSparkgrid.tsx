// LabSparkgrid — the "is the lab alive?" glance (revamp R3). A
// GitHub-contribution-style heatmap over the last N weeks: columns are weeks,
// rows are UTC weekdays, one ~10px cell per day. Two event series are folded
// into one magnitude per day — LOOP_V0 iterations (`ended_at`) and coordinator
// cycles (`timestamp`) — because the question this answers is "did the
// apparatus do anything", not "which subsystem did it".
//
// Color is a SEQUENTIAL single-hue lightness ramp on the accent hue (250), per
// the design system: magnitude gets one hue light->dark, never a rainbow and
// never the status set (those are reserved for run/rung state). Five classes
// total (empty + 4), which stays under the ~7-class legibility ceiling, and a
// less->more scale legend ships with it.
//
// Everything is derived CLIENT-SIDE from the two list endpoints Pulse already
// polls — there is no server-side aggregate, and this component fetches
// nothing. Timestamps are producer-owned: a non-string or unparseable value is
// DROPPED from the bucket rather than counted as "now", so a malformed row
// undercounts honestly instead of inventing activity on today's cell.
import { useMemo } from "react";

const DAY_MS = 86_400_000;
const DEFAULT_WEEKS = 12;
const CELL_PX = 10;
const GAP_PX = 2;

// Sequential ramp: one hue (the accent's 250), lightness ascending. Index 0 is
// "no activity" and deliberately reads as surface, not as a dim data value.
const RAMP = [
  "var(--surface-2)",
  "oklch(0.34 0.05 250)",
  "oklch(0.46 0.08 250)",
  "oklch(0.58 0.11 250)",
  "oklch(0.70 0.13 250)",
];

/** UTC day key ("YYYY-MM-DD") for an epoch-ms instant. */
export function dayKeyOf(ms: number): string {
  const d = new Date(ms);
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  return `${d.getUTCFullYear()}-${m}-${day}`;
}

/** The `days` consecutive UTC day keys ending on the day containing endMs. */
export function dayKeys(endMs: number, days: number): string[] {
  const end = new Date(endMs);
  const endDay = Date.UTC(
    end.getUTCFullYear(),
    end.getUTCMonth(),
    end.getUTCDate(),
  );
  const out: string[] = [];
  for (let i = days - 1; i >= 0; i--) out.push(dayKeyOf(endDay - i * DAY_MS));
  return out;
}

/**
 * Count producer-owned ISO timestamps into UTC day buckets inside the window.
 * Non-string / unparseable / out-of-window values are dropped — an unreadable
 * timestamp is not evidence that the lab ran today.
 */
export function bucketByDay(
  timestamps: unknown[],
  endMs: number,
  days: number,
): Map<string, number> {
  const window = new Set(dayKeys(endMs, days));
  const counts = new Map<string, number>();
  for (const raw of Array.isArray(timestamps) ? timestamps : []) {
    if (typeof raw !== "string" || !raw) continue;
    const t = Date.parse(raw);
    if (Number.isNaN(t)) continue;
    const key = dayKeyOf(t);
    if (!window.has(key)) continue;
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return counts;
}

/**
 * Ramp cut points from the window's own day totals — QUARTILES over the
 * DISTINCT nonzero totals, not a fraction of the maximum.
 *
 * This is load-bearing, not a preference. Lab activity is heavy-tailed: on the
 * live apparatus a 12-week window runs 1-4 events on a typical day against a
 * single 125-event day, so scaling linearly against the max puts 64 of 65
 * active days in the dimmest class and the heatmap degenerates to "ran / did
 * not run". Quartiles over the distinct totals spread the same data across all
 * four lit classes. A window with only ONE distinct total carries no magnitude
 * information at all, so every active day takes the top class rather than
 * reading as near-noise.
 */
export function rampThresholds(dayTotals: number[]): [number, number, number] {
  const uniq = [...new Set(dayTotals.filter((n) => n > 0))].sort((a, b) => a - b);
  if (uniq.length === 0) return [1, 1, 1];
  if (uniq.length === 1) return [0, 0, 0];
  const at = (p: number) => uniq[Math.min(uniq.length - 1, Math.floor(p * uniq.length))];
  return [at(0.25), at(0.5), at(0.75)];
}

/** Ramp class 0..4 for a day's total against the window's cut points. */
export function rampLevel(
  total: number,
  thresholds: [number, number, number],
): number {
  if (total <= 0) return 0;
  if (total <= thresholds[0]) return 1;
  if (total <= thresholds[1]) return 2;
  if (total <= thresholds[2]) return 3;
  return 4;
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

export interface LabSparkgridProps {
  /** Iteration `ended_at` values (producer-owned; junk is dropped). */
  iterationTimes?: unknown[];
  /** Coordinator cycle `timestamp` values (producer-owned). */
  cycleTimes?: unknown[];
  /** Injectable clock; defaults to now. */
  nowMs?: number;
  weeks?: number;
}

export default function LabSparkgrid({
  iterationTimes,
  cycleTimes,
  nowMs,
  weeks = DEFAULT_WEEKS,
}: LabSparkgridProps) {
  const now = nowMs ?? Date.now();
  const days = weeks * 7;

  const { keys, iters, cycles, thresholds, active, totalIters, totalCycles } =
    useMemo(() => {
      const k = dayKeys(now, days);
      const i = bucketByDay(iterationTimes ?? [], now, days);
      const c = bucketByDay(cycleTimes ?? [], now, days);
      const totals: number[] = [];
      let ti = 0;
      let tc = 0;
      for (const key of k) {
        const iv = i.get(key) ?? 0;
        const cv = c.get(key) ?? 0;
        ti += iv;
        tc += cv;
        totals.push(iv + cv);
      }
      return {
        keys: k,
        iters: i,
        cycles: c,
        thresholds: rampThresholds(totals),
        active: totals.some((n) => n > 0),
        totalIters: ti,
        totalCycles: tc,
      };
    }, [iterationTimes, cycleTimes, now, days]);

  // Column-major fill (grid-auto-flow: column) lays weeks out left-to-right,
  // so the first column is padded up to the window's opening weekday — the
  // GitHub alignment, where a row is always the same weekday.
  const leadPad = new Date(`${keys[0]}T00:00:00Z`).getUTCDay();
  const summary = `${plural(totalIters, "iteration")} · ${plural(totalCycles, "coordinator cycle")} over the last ${weeks} weeks`;

  return (
    <div data-testid="lab-sparkgrid">
      <div
        role="img"
        aria-label={`Lab activity heatmap: ${summary}`}
        data-testid="lab-sparkgrid-grid"
        style={{
          display: "grid",
          gridTemplateRows: `repeat(7, ${CELL_PX}px)`,
          gridAutoFlow: "column",
          gridAutoColumns: `${CELL_PX}px`,
          gap: `${GAP_PX}px`,
          width: "max-content",
        }}
      >
        {Array.from({ length: leadPad }, (_, i) => (
          <span key={`pad-${i}`} aria-hidden="true" />
        ))}
        {keys.map((key) => {
          const iv = iters.get(key) ?? 0;
          const cv = cycles.get(key) ?? 0;
          const total = iv + cv;
          const level = rampLevel(total, thresholds);
          return (
            <span
              key={key}
              data-testid={`spark-cell-${key}`}
              data-count={total}
              data-level={level}
              title={
                total === 0
                  ? `${key} · nothing ran`
                  : `${key} · ${plural(iv, "iteration")} · ${plural(cv, "cycle")}`
              }
              style={{
                background: RAMP[level],
                borderRadius: 2,
                width: CELL_PX,
                height: CELL_PX,
              }}
            />
          );
        })}
      </div>

      {/* Values are never hover-gated: the summary carries the totals in text. */}
      <div
        data-testid="lab-sparkgrid-summary"
        style={{
          marginTop: "var(--space-3)",
          display: "flex",
          alignItems: "center",
          gap: "var(--space-2)",
          fontSize: "var(--text-meta)",
          color: "var(--fg-muted)",
        }}
      >
        <span>{active ? summary : `nothing ran in the last ${weeks} weeks`}</span>
        <span style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: GAP_PX }}>
          less
          {RAMP.map((c, i) => (
            <span
              key={i}
              aria-hidden="true"
              style={{ background: c, borderRadius: 2, width: CELL_PX, height: CELL_PX }}
            />
          ))}
          more
        </span>
      </div>
    </div>
  );
}
