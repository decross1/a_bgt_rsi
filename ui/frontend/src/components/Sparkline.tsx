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
  if (points.length === 0) {
    return <svg width={width} height={height} aria-hidden="true" />;
  }

  let min = Math.min(...points);
  let max = Math.max(...points);
  if (reference != null) {
    min = Math.min(min, reference);
    max = Math.max(max, reference);
  }
  const span = max - min || 1;
  const dx = values.length > 1 ? width / (values.length - 1) : 0;
  const y = (v: number) => height - 1 - ((v - min) / span) * (height - 2);
  const segments: string[][] = [];
  let segment: string[] = [];
  values.forEach((value, index) => {
    if (typeof value === "number" && Number.isFinite(value)) {
      segment.push(`${(index * dx).toFixed(1)},${y(value).toFixed(1)}`);
      return;
    }
    if (segment.length > 0) segments.push(segment);
    segment = [];
  });
  if (segment.length > 0) segments.push(segment);

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
      {segments.map((line, index) =>
        line.length === 1 ? (
          <circle
            key={`${line[0]}-${index}`}
            cx={line[0].split(",")[0]}
            cy={line[0].split(",")[1]}
            r={2}
            fill={color}
          />
        ) : (
          <polyline
            key={`${line[0]}-${index}`}
            points={line.join(" ")}
            fill="none"
            stroke={color}
            strokeWidth={1.5}
            strokeLinejoin="round"
          />
        ),
      )}
    </svg>
  );
}
