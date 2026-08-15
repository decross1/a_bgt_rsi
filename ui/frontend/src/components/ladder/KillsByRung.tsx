// KillsByRung — the page's ONE chart: "where do ideas die?" Six bars, one per
// rung, height = clusters killed at that rung.
//
// Deliberately plain: a single series, so one hue (--status-bad, the reserved
// killed status) for every bar and no legend — the title names the series. No
// gridlines, no y-axis; the bars are direct-labeled instead, so no value is
// reachable only through the tooltip. Explicit width/height rather than
// ResponsiveContainer: the panel is fixed-size, and it keeps the chart
// deterministic (and console-silent) under jsdom.
import {
  Bar,
  BarChart,
  LabelList,
  Tooltip,
  XAxis,
} from "recharts";

import { LEVELS } from "./ladderModel";

const CHART_W = 300;
// Plot + the x-axis band, so the labels are never clipped by the box.
const CHART_H = 168;

export default function KillsByRung({
  killsByRung,
  killsUnrung = 0,
}: {
  /** Killed clusters by rung-at-death; index k == Lk. */
  killsByRung: number[];
  /** Killed clusters with no rung-at-death — reported, never folded into L0. */
  killsUnrung?: number;
}) {
  const data = LEVELS.map((rung, k) => ({ rung, kills: killsByRung[k] ?? 0 }));
  const total = data.reduce((s, d) => s + d.kills, 0);
  // Bars are geometry no screen reader can read; the same rung→count mapping
  // in words is the chart's accessible equivalent.
  const summary = `Kills per rung: ${data
    .map((d) => `${d.rung} ${d.kills}`)
    .join(", ")}.`;

  return (
    <div data-testid="kills-by-rung" data-total={total}>
      <h2
        style={{
          margin: 0,
          marginBottom: "var(--space-2)",
          fontSize: "var(--text-ui)",
          fontWeight: "var(--weight-medium)",
        }}
      >
        Where do ideas die?
      </h2>
      {total === 0 ? (
        <p
          data-testid="kills-by-rung-empty"
          style={{
            margin: 0,
            fontSize: "var(--text-meta)",
            color: "var(--fg-muted)",
          }}
        >
          nothing killed at a known rung yet.
        </p>
      ) : (
        <div role="img" aria-label={summary} data-testid="kills-chart">
        <BarChart
          width={CHART_W}
          height={CHART_H}
          data={data}
          margin={{ top: 16, right: 8, bottom: 4, left: 8 }}
        >
          <XAxis
            dataKey="rung"
            tickLine={false}
            axisLine={{ stroke: "var(--border-1)" }}
            tick={{ fill: "var(--fg-muted)", fontSize: 11 }}
          />
          <Tooltip
            cursor={{ fill: "var(--surface-2)" }}
            contentStyle={{
              background: "var(--surface-3)",
              border: "1px solid var(--border-2)",
              borderRadius: "var(--radius-control)",
              fontSize: "var(--text-meta)",
            }}
            labelStyle={{ color: "var(--fg-muted)" }}
            itemStyle={{ color: "var(--fg)" }}
            formatter={(v: unknown) => [`${v} killed here`, ""]}
          />
          <Bar
            dataKey="kills"
            fill="var(--status-bad)"
            radius={[4, 4, 0, 0]}
            isAnimationActive={false}
          >
            <LabelList
              dataKey="kills"
              position="top"
              fill="var(--fg-muted)"
              fontSize={11}
              formatter={(v: unknown) =>
                typeof v === "number" && v > 0 ? String(v) : ""
              }
            />
          </Bar>
        </BarChart>
        </div>
      )}
      {killsUnrung > 0 && (
        <p
          data-testid="kills-by-rung-unrung"
          style={{
            margin: "var(--space-2) 0 0",
            fontSize: "var(--text-meta)",
            color: "var(--fg-muted)",
          }}
        >
          + {killsUnrung} killed with no recorded rung
        </p>
      )}
    </div>
  );
}
