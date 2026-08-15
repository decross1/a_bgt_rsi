// LadderFunnel — the aggregate funnel strip: the one-glance "screenshot of
// the lab". Hand-rolled SVG, no chart library.
//
// Six centered bars, L0 at the top down to L5, each as wide as the number of
// clusters that REACHED that rung (ladderModel.reached — monotone, so the
// shape genuinely narrows; it is not cosmetic tapering). Out of each rung a
// gray ribbon drops to a single graveyard node, its thickness set by how many
// clusters were killed AT that rung. Wide at L0, thin at L5, honest about the
// bodies — that is the whole point of the strip.
//
// Encoding follows the R0 status set, same mapping as RungGlyph so a reader
// learns it once: L4/L5 (clears the D-059 surfacing bar) emerald, L0-L3 sky,
// kills zinc. Every number is DIRECT-LABELED — nothing is tooltip-only.
//
// Motion: bars animate over --motion-enter via `transform: scaleX()` (the
// design system's transform/opacity-only rule; CSS transitions on SVG `width`
// are not portable). The horizontal corner radius is pre-divided by the scale
// so the rounded ends stay 4px at every width instead of stretching.
import { LEVELS } from "./ladderModel";

// --- canvas geometry (user units; the svg scales to its container) ---------
const VB_W = 720;
const VB_H = 244;
const ROW_Y0 = 24; // centerline of the L0 bar
const ROW_STEP = 32;
const BAR_H = 14;
const GUTTER_R = 66; // right edge of the "L0  12" gutter
const MAX_W = 440; // full-width bar (the L0 bar when it is the max)
const CX = 300; // funnel centerline
const GRAVE_X = 586;
const GRAVE_Y = 188;
const GRAVE_W = 128;
const GRAVE_H = 44;
// The D-059 surfacing bar sits between L3 and L4.
const BAR_LINE_Y = ROW_Y0 + 3 * ROW_STEP + ROW_STEP / 2;

function rungFill(k: number): string {
  return k >= 4 ? "var(--status-ok)" : "var(--status-info)";
}

export default function LadderFunnel({
  reached,
  killsByRung,
  killedTotal,
}: {
  /** Clusters that reached at least Lk; index k == Lk. */
  reached: number[];
  /** Killed clusters by rung-at-death; index k == Lk. */
  killsByRung: number[];
  /** Every killed cluster, including ones with no rung-at-death. */
  killedTotal: number;
}) {
  const widest = Math.max(1, ...reached);
  const heaviest = Math.max(1, ...killsByRung);

  return (
    <div data-testid="ladder-funnel">
      <svg
        viewBox={`0 0 ${VB_W} ${VB_H}`}
        style={{ width: "100%", height: "auto" }}
        role="img"
        aria-label={`Evidence funnel: ${reached[0]} clusters reached L0, ${reached[5]} reached L5; ${killedTotal} killed.`}
      >
        {/* The D-059 surfacing bar — a threshold, hence the dash. Labeled at
            the LEFT end: the right end is where the kill ribbons sweep past,
            and a label under a ribbon is an unreadable label. */}
        <line
          x1={GUTTER_R}
          y1={BAR_LINE_Y}
          x2={CX + MAX_W / 2}
          y2={BAR_LINE_Y}
          stroke="var(--border-2)"
          strokeWidth={1}
          strokeDasharray="3 4"
        />
        <text
          x={GUTTER_R + 2}
          y={BAR_LINE_Y - 4}
          fontSize={10}
          fill="var(--fg-muted)"
        >
          surfacing bar (D-059)
        </text>

        {LEVELS.map((level, k) => {
          const n = reached[k];
          const kills = killsByRung[k];
          const cy = ROW_Y0 + k * ROW_STEP;
          // A rung that nothing reached shows a hairline stub, not a bar —
          // "zero" must not read as "a little".
          const f = n > 0 ? Math.max(n / widest, 0.012) : 0;
          const halfW = (MAX_W / 2) * f;
          return (
            <g
              key={level}
              data-testid={`funnel-rung-${level}`}
              data-reached={n}
              data-killed={kills}
            >
              <title>
                {`${level}: ${n} reached · ${kills} killed here`}
              </title>
              <text
                x={6}
                y={cy + 4}
                fontSize={11}
                fill="var(--fg-muted)"
                fontFamily="var(--font-mono)"
              >
                {level}
              </text>
              <text
                x={GUTTER_R - 8}
                y={cy + 4}
                textAnchor="end"
                fontSize={12}
                fill="var(--fg)"
                className="tnum"
              >
                {n}
              </text>
              {f > 0 ? (
                <rect
                  x={CX - MAX_W / 2}
                  y={cy - BAR_H / 2}
                  width={MAX_W}
                  height={BAR_H}
                  rx={Math.min(4 / f, MAX_W / 2)}
                  ry={4}
                  fill={rungFill(k)}
                  // A full-strength fill on a bar this wide reads as a slab;
                  // the status hues stay saturated on the small marks.
                  fillOpacity={0.82}
                  style={{
                    transform: `scaleX(${f})`,
                    transformBox: "view-box",
                    transformOrigin: `${CX}px ${cy}px`,
                    transition:
                      "transform var(--motion-enter) var(--ease-out)",
                  }}
                />
              ) : (
                <rect
                  x={CX - 6}
                  y={cy - 1}
                  width={12}
                  height={2}
                  fill="var(--border-2)"
                />
              )}
              {kills > 0 && (
                <>
                  {/* Ribbon: out of the bar's right end, down to the node. */}
                  <path
                    d={`M ${CX + halfW} ${cy} C ${CX + halfW + 60} ${cy}, ${GRAVE_X - 70} ${GRAVE_Y + GRAVE_H / 2}, ${GRAVE_X} ${GRAVE_Y + GRAVE_H / 2}`}
                    fill="none"
                    stroke="var(--status-idle)"
                    strokeOpacity={0.55}
                    strokeWidth={2 + 8 * (kills / heaviest)}
                    strokeLinecap="round"
                    data-testid={`funnel-ribbon-${level}`}
                  />
                  <text
                    x={CX + halfW + 8}
                    y={cy - 6}
                    fontSize={10}
                    fill="var(--fg-muted)"
                    className="tnum"
                  >
                    −{kills}
                  </text>
                </>
              )}
            </g>
          );
        })}

        {/* The graveyard node every ribbon drops into. */}
        <g data-testid="funnel-graveyard" data-total={killedTotal}>
          <rect
            x={GRAVE_X}
            y={GRAVE_Y}
            width={GRAVE_W}
            height={GRAVE_H}
            rx={10}
            fill="var(--status-idle-bg)"
            stroke="var(--border-2)"
          />
          <text
            x={GRAVE_X + GRAVE_W / 2}
            y={GRAVE_Y + 20}
            textAnchor="middle"
            fontSize={16}
            fill="var(--fg)"
            className="tnum"
          >
            {killedTotal}
          </text>
          <text
            x={GRAVE_X + GRAVE_W / 2}
            y={GRAVE_Y + 34}
            textAnchor="middle"
            fontSize={10}
            fill="var(--fg-muted)"
          >
            killed
          </text>
        </g>
      </svg>
      <p
        style={{
          margin: 0,
          fontSize: "var(--text-meta)",
          color: "var(--fg-muted)",
        }}
      >
        bar = clusters that reached the rung · ribbon = killed at that rung ·
        the rest are still sitting there
      </p>
    </div>
  );
}
