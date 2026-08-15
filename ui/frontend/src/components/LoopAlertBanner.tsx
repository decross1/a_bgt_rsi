// LoopAlertBanner — the page-top alert surface over run_state/loop_alert.json
// (GET /api/loop_alert, 2026-08-14 work order A). The flag is rewritten every
// EXECUTED coordinator cycle, so it can say two distinct things:
//   - what the last cycle concluded (level red|amber|ok + reasons[]), and
//   - by its AGE, whether cycles are running at all: an updated_at older than
//     ~26h means the 2x/day cron went silent — exactly the failure this
//     surface exists to catch, so staleness renders amber EVEN over "ok".
//
// Render contract:
//   red        -> red banner "LOOP STALLED" + every reason, verbatim.
//   amber      -> amber banner "loop degraded" + reasons.
//   ok & fresh -> nothing (the calm state is invisible; no reassurance chrome).
//   stale      -> amber "no cycle telemetry since <ts>" appended (or alone,
//                 when the level itself would have hidden the banner).
//
// Degradation (house doctrine): a 204 (flag never written), a fetch failure,
// a version-skew 404, or an unknown level renders NOTHING — this banner may
// only alarm off a flag a producer actually wrote; it never invents an alert
// from the absence of one. Reasons are producer-owned: non-string entries are
// dropped, a non-array reasons renders no list. `initial` bypasses polling
// (fixture renders stay deterministic — the HumanTodoPanel idiom); `nowMs`
// pins the staleness clock for tests.
import { useEffect, useState } from "react";
import { getLoopAlert } from "../api/http";
import type { LoopAlert } from "../types/schemas";

// ~26h: one missed 2x/day cycle plus slack, per the work order.
const STALE_AFTER_MS = 26 * 60 * 60 * 1000;

function reasonsOf(alert: LoopAlert): string[] {
  if (!Array.isArray(alert.reasons)) return [];
  return alert.reasons.filter(
    (r): r is string => typeof r === "string" && r.length > 0,
  );
}

// Staleness off updated_at. A MISSING/unparseable timestamp on a present flag
// counts as stale — a flag that cannot prove freshness must not read as fresh.
function staleSince(alert: LoopAlert, nowMs: number): string | null {
  const raw = alert.updated_at;
  if (typeof raw !== "string" || raw.length === 0) return null; // no ts at all
  const t = Date.parse(raw);
  if (Number.isNaN(t)) return null;
  return nowMs - t > STALE_AFTER_MS ? raw : null;
}

function hasParseableTs(alert: LoopAlert): boolean {
  return (
    typeof alert.updated_at === "string" &&
    !Number.isNaN(Date.parse(alert.updated_at))
  );
}

interface Props {
  /** Fixture override: null = flag absent (render nothing); an object = use
   *  as-is, no polling. Absent prop = live mode (poll /api/loop_alert). */
  initial?: LoopAlert | null;
  pollMs?: number;
  /** Staleness clock override for tests; defaults to Date.now(). */
  nowMs?: number;
}

export default function LoopAlertBanner({ initial, pollMs = 60_000, nowMs }: Props) {
  const [alert, setAlert] = useState<LoopAlert | null>(initial ?? null);

  useEffect(() => {
    if (initial !== undefined) return;
    let active = true;
    const load = () =>
      getLoopAlert()
        .then((a) => {
          if (active) setAlert(a);
        })
        .catch(() => {
          // Fetch failure / skew 404: hide rather than alarm off nothing.
          if (active) setAlert(null);
        });
    load();
    const id = setInterval(load, Math.max(5_000, pollMs));
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [initial, pollMs]);

  if (alert === null || typeof alert !== "object" || Array.isArray(alert)) {
    return null;
  }

  const now = nowMs ?? Date.now();
  const level = alert.level === "red" || alert.level === "amber" || alert.level === "ok"
    ? alert.level
    : null;
  const stale = staleSince(alert, now);
  // A present flag with NO parseable timestamp cannot prove cycles are live:
  // surface that honestly (amber), same as a stale one.
  const tsUnreadable = !hasParseableTs(alert);

  const showRed = level === "red";
  const showAmber = !showRed && (level === "amber" || stale !== null || tsUnreadable);
  if (!showRed && !showAmber) return null; // ok & fresh, or unknown & fresh

  const reasons = level === "ok" ? [] : reasonsOf(alert);
  const tone = showRed
    ? "border-red-800 bg-red-950/60 text-red-200"
    : "border-amber-800 bg-amber-950/50 text-amber-200";

  return (
    <div
      data-testid="loop-alert-banner"
      data-level={showRed ? "red" : "amber"}
      role="alert"
      className={`border-b px-6 py-2 text-xs ${tone}`}
    >
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="font-semibold uppercase tracking-wide">
          {showRed ? "LOOP STALLED" : "loop degraded"}
        </span>
        <span className={showRed ? "text-red-400/70" : "text-amber-400/70"}>
          run_state/loop_alert.json
        </span>
      </div>
      {reasons.length > 0 && (
        <ul className="mt-1 list-disc space-y-0.5 pl-5" data-testid="loop-alert-reasons">
          {reasons.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      )}
      {stale !== null && (
        <div className="mt-1" data-testid="loop-alert-stale">
          no cycle telemetry since {stale} — the coordinator cron may be silent.
        </div>
      )}
      {stale === null && tsUnreadable && (
        <div className="mt-1" data-testid="loop-alert-stale">
          the alert flag carries no readable updated_at — cycle freshness is
          unknown.
        </div>
      )}
    </div>
  );
}
