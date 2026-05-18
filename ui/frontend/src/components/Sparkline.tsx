// Minimal inline SVG sparkline. Matches the apparatus's text-and-numbers
// tone (ui_plan.md section 10) — no gradients, no animation.

interface SparklineProps {
  values: (number | null | undefined)[];
  width?: number;
  height?: number;
  color?: string;
  reference?: number; // optional dashed baseline (e.g. the tok/s floor)
}

export default function Sparkline({
  values,
  width = 116,
  height = 26,
  color = "#38bdf8",
  reference,
}: SparklineProps) {
  const points = values.filter(
    (v): v is number => typeof v === "number" && Number.isFinite(v),
  );
  if (points.length < 2) {
    return <svg width={width} height={height} aria-hidden="true" />;
  }

  let min = Math.min(...points);
  let max = Math.max(...points);
  if (reference != null) {
    min = Math.min(min, reference);
    max = Math.max(max, reference);
  }
  const span = max - min || 1;
  const dx = width / (points.length - 1);
  const y = (v: number) => height - 1 - ((v - min) / span) * (height - 2);
  const line = points
    .map((v, i) => `${(i * dx).toFixed(1)},${y(v).toFixed(1)}`)
    .join(" ");

  return (
    <svg width={width} height={height} aria-hidden="true">
      {reference != null && (
        <line
          x1={0}
          x2={width}
          y1={y(reference)}
          y2={y(reference)}
          stroke="#52525b"
          strokeWidth={1}
          strokeDasharray="2 2"
        />
      )}
      <polyline
        points={line}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinejoin="round"
      />
    </svg>
  );
}
