// RungGlyph — THE rung representation (R0 design system). A 16px six-segment
// progress ring, one segment per evidence level L0..L5 (D-059): for rung Lk,
// segments 0..k are lit (so L0 = 1/6 — a claim exists — and L5 = the full
// ring). Color encodes the D-059 bar: L4/L5 (clears the bar) lights emerald
// (--status-ok); L0-L3 lights sky (--status-info); killed renders whatever
// rung was reached in gray (--status-idle). A missing/malformed level lights
// nothing — an unknown rung reads as "no evidence level", never as a fake L0+.
//
// Level normalization mirrors src/ladderBar.ts evidenceLevelOf: the field is
// producer-owned, so anything that is not an L0..L5 string (case/space
// tolerant) is "no level". No dependency on ladderBar — that module is typed
// to HumanTodoItem; this one takes the raw scalar so every surface can use it.
import { CSSProperties } from "react";

const LEVELS = 6; // L0..L5
const SEGMENT_GAP_DEG = 24; // visual gap between segments
// Rung names verbatim from D-059 (short forms). L4+ clears the surfacing bar.
const LABELS: Record<number, string> = {
  0: "L0 · asserted",
  1: "L1 · literature-consistent",
  2: "L2 · synthetic experiment",
  3: "L3 · robustness/replication",
  4: "L4 · adversarial-survived",
  5: "L5 · human-validated",
};

export function rungIndex(level: unknown): number | null {
  if (typeof level !== "string") return null;
  const norm = level.trim().toUpperCase();
  const m = /^L([0-5])$/.exec(norm);
  return m ? Number(m[1]) : null;
}

function segmentPath(i: number, r: number, c: number): string {
  // Segment i spans 60° starting at 12 o'clock, minus a gap on each side.
  const start = -90 + i * 60 + SEGMENT_GAP_DEG / 2;
  const end = -90 + (i + 1) * 60 - SEGMENT_GAP_DEG / 2;
  const a0 = (start * Math.PI) / 180;
  const a1 = (end * Math.PI) / 180;
  const x0 = c + r * Math.cos(a0);
  const y0 = c + r * Math.sin(a0);
  const x1 = c + r * Math.cos(a1);
  const y1 = c + r * Math.sin(a1);
  return `M ${x0.toFixed(3)} ${y0.toFixed(3)} A ${r} ${r} 0 0 1 ${x1.toFixed(3)} ${y1.toFixed(3)}`;
}

export default function RungGlyph({
  level,
  killed = false,
  size = 16,
  title,
  className,
  style,
}: {
  level: unknown;
  killed?: boolean;
  size?: number;
  title?: string;
  className?: string;
  style?: CSSProperties;
}) {
  const idx = rungIndex(level);
  const lit = idx === null ? 0 : idx + 1;
  const fill =
    killed || idx === null
      ? "var(--status-idle)"
      : idx >= 4
        ? "var(--status-ok)"
        : "var(--status-info)";
  const base =
    idx === null ? "no evidence level" : LABELS[idx] ?? `L${idx}`;
  const label = title ?? (killed ? `killed · ${base}` : base);
  const c = 8;
  const r = 6.25;

  return (
    <svg
      role="img"
      aria-label={label}
      data-testid="rung-glyph"
      data-rung={idx === null ? "none" : `L${idx}`}
      data-killed={killed || undefined}
      width={size}
      height={size}
      viewBox="0 0 16 16"
      className={className}
      style={style}
    >
      <title>{label}</title>
      {Array.from({ length: LEVELS }, (_, i) => (
        <path
          key={i}
          d={segmentPath(i, r, c)}
          fill="none"
          stroke={i < lit ? fill : "var(--border-2)"}
          strokeWidth={2.25}
          strokeLinecap="round"
          data-segment={i}
          data-lit={i < lit || undefined}
        />
      ))}
    </svg>
  );
}
