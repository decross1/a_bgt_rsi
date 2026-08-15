// LadderMiniFunnel — Pulse's compact L0->L5 read of the evidence ladder
// (revamp R3). A six-rung funnel off GET /api/ladder's `histogram` (non-killed
// clusters per rung, D-059), sized against the busiest rung, linking into
// /ladder for the real thing.
//
// ABSENCE IS NOT AN ERROR: 204 (the ledger has never been written on this
// checkout) and a version-skew 404 (running binary predates the endpoint) both
// HIDE the panel entirely — an apparatus with no ladder shows no funnel rather
// than a row of noisy zeros. A 500 is different: ladder.py raises it
// deliberately on an unreadable/invalid ledger, so that degrades to one muted
// line instead of vanishing, which would misreport a broken ledger as "no
// ladder yet".
//
// The histogram is producer-owned. Only L0..L5 render (the D-059 rungs); any
// count parked on a rung this build does not know about is SUMMED into a muted
// "beyond L5" note rather than dropped silently.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import RungGlyph from "../design/RungGlyph";
import { getLadder } from "../api/http";
import { isVersionSkew404 } from "./EndpointMissingNote";
import type { LadderResponse } from "../types/schemas";

const LADDER_ENDPOINT = "/api/ladder";
const RUNGS = ["L0", "L1", "L2", "L3", "L4", "L5"] as const;

// Producer-owned count -> a non-negative integer, or 0. A garbage value is
// never a bar.
function asCount(v: unknown): number {
  return typeof v === "number" && Number.isFinite(v) && v > 0 ? v : 0;
}

export interface LadderMiniFunnelProps {
  /** Fixture injection: `null` = the hidden (204) state, `undefined` = fetch. */
  initial?: LadderResponse | null;
  pollMs?: number;
}

export default function LadderMiniFunnel({
  initial,
  pollMs = 60000,
}: LadderMiniFunnelProps) {
  const [data, setData] = useState<LadderResponse | null>(initial ?? null);
  const [hidden, setHidden] = useState(initial === null);
  const [broken, setBroken] = useState(false);

  useEffect(() => {
    if (initial !== undefined) return;
    let on = true;
    const load = () =>
      getLadder()
        .then((r) => {
          if (!on) return;
          // null = 204: the ledger has never been written. Nothing to show.
          setHidden(r == null);
          setData(r);
          setBroken(false);
        })
        .catch((e) => {
          if (!on) return;
          if (isVersionSkew404(e, LADDER_ENDPOINT)) {
            setHidden(true);
          } else {
            setBroken(true);
          }
        });
    load();
    const id = setInterval(load, pollMs);
    return () => {
      on = false;
      clearInterval(id);
    };
  }, [initial, pollMs]);

  if (hidden) return null;

  if (broken) {
    return (
      <div
        data-testid="ladder-funnel-unavailable"
        style={{ fontSize: "var(--text-meta)", color: "var(--fg-muted)" }}
      >
        ladder unreadable — /api/ladder is failing
      </div>
    );
  }
  if (data == null) return null;

  const histogram =
    data.histogram != null &&
    typeof data.histogram === "object" &&
    !Array.isArray(data.histogram)
      ? (data.histogram as Record<string, unknown>)
      : {};

  const rows = RUNGS.map((rung) => ({ rung, count: asCount(histogram[rung]) }));
  const max = rows.reduce((m, r) => Math.max(m, r.count), 0);
  const beyond = Object.entries(histogram)
    .filter(([k]) => !(RUNGS as readonly string[]).includes(k))
    .reduce((sum, [, v]) => sum + asCount(v), 0);

  const counts = data.counts ?? {};
  const tally = [
    ["open", asCount(counts.open)],
    ["surfaced", asCount(counts.surfaced)],
    ["killed", asCount(counts.killed)],
  ] as const;

  return (
    <div data-testid="ladder-funnel">
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
        {rows.map(({ rung, count }) => (
          <div
            key={rung}
            data-testid={`ladder-funnel-${rung}`}
            data-count={count}
            style={{ display: "flex", alignItems: "center", gap: "var(--space-2)" }}
          >
            <RungGlyph level={rung} size={14} />
            <span
              className="tnum"
              style={{
                width: 20,
                fontFamily: "var(--font-mono)",
                fontSize: "var(--text-meta)",
                color: "var(--fg-muted)",
              }}
            >
              {rung}
            </span>
            <span
              aria-hidden="true"
              style={{
                height: 6,
                borderRadius: "var(--radius-pill)",
                // Zero keeps a hairline stub so the rung reads as present-but-empty.
                width: max > 0 && count > 0 ? `${Math.max(6, (count / max) * 100)}%` : 3,
                minWidth: 3,
                background:
                  count === 0
                    ? "var(--surface-2)"
                    : rung === "L4" || rung === "L5"
                      ? "var(--status-ok)"
                      : "var(--status-info)",
              }}
            />
            <span
              className="tnum"
              style={{
                marginLeft: "auto",
                fontFamily: "var(--font-mono)",
                fontSize: "var(--text-meta)",
                color: count > 0 ? "var(--fg)" : "var(--fg-muted)",
              }}
            >
              {count}
            </span>
          </div>
        ))}
      </div>

      <div
        style={{
          marginTop: "var(--space-3)",
          display: "flex",
          alignItems: "baseline",
          gap: "var(--space-3)",
          fontSize: "var(--text-meta)",
          color: "var(--fg-muted)",
        }}
      >
        <span data-testid="ladder-funnel-tally">
          {tally.map(([k, v]) => `${k} ${v}`).join(" · ")}
        </span>
        {beyond > 0 && (
          <span data-testid="ladder-funnel-beyond">+{beyond} beyond L5</span>
        )}
        <Link to="/ladder" style={{ marginLeft: "auto", color: "var(--accent)" }}>
          ladder →
        </Link>
      </div>
    </div>
  );
}
