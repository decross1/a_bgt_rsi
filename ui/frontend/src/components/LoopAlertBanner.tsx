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
//   gated      -> the flag's additive `gate` block (a cycle a coordinator gate
//                 HELD rather than ran). It never forces the banner open on its
//                 own: a FRESH gate arrives at level "ok" and stays invisible,
//                 exactly like any other calm state. The producer escalates it
//                 by AGE (loop_health.gate_continuity: ok -> amber at 3h -> red
//                 at 12h continuously held), and only then does this render —
//                 as "idle: <reason> for <age>" with the gate's own detail, and
//                 with the headline reading LOOP IDLE instead of LOOP STALLED.
//                 That distinction is the point: a red the owner cannot explain
//                 was the original complaint, and "stalled" would be a LIE for a
//                 loop that is being deliberately held.
//
// Degradation (house doctrine): a 204 (flag never written), a version-skew
// 404 before anything loaded, or an unknown level renders NOTHING — this
// banner may only alarm off a flag a producer actually wrote; it never
// invents an alert from the absence of one. But the inverse is inviolate
// too (adversarial-review residual fix 6, 2026-08-18): a FAILED poll never
// CLEARS an active alert — the old catch -> setAlert(null) made a red
// "LOOP STALLED" vanish the moment the backend hiccuped, which is exactly
// when it matters. The banner now rides the shared pollhub (usePolled —
// App-level mounting is no obstacle: the hub is module-global, same
// import + subscribe as the Pulse sources), whose SWR keeps the last-known
// alert across failures; a stale marker names the failing refresh, and only
// an EXPLICIT payload — ok & fresh, or absent (204 -> null) — clears it.
// Reasons are producer-owned: non-string entries are dropped, a non-array
// reasons renders no list. `initial` bypasses polling (fixture renders stay
// deterministic — the HumanTodoPanel idiom); `nowMs` pins the staleness
// clock for tests.
import { getLoopAlert } from "../api/http";
import { usePolled } from "../api/pollhub";
import { ageLabel } from "../ladderBar";
import { useNow } from "../time";
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

// The additive `gate` block, coerced. Producer-owned like `reasons`: a reason
// that is not a non-empty string means there is no gate to name, so we render
// none rather than an empty "idle:" line.
interface GateView {
  reason: string;
  detail: string | null;
  firstGatedAt: string | null;
}

function gateOf(alert: LoopAlert): GateView | null {
  const g = alert.gate;
  if (typeof g !== "object" || g === null || Array.isArray(g)) return null;
  const raw = g as Record<string, unknown>;
  const reason = raw.reason;
  if (typeof reason !== "string" || reason.length === 0) return null;
  return {
    reason,
    detail: typeof raw.detail === "string" && raw.detail.length > 0 ? raw.detail : null,
    firstGatedAt:
      typeof raw.first_gated_at === "string" && raw.first_gated_at.length > 0
        ? raw.first_gated_at
        : null,
  };
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
  // Shared-pollhub subscription (residual fix 6): in-flight guard, change
  // detection, SWR. `data` undefined = never loaded (render nothing — a
  // failing-from-birth source, e.g. a version-skew 404, never invents an
  // alert); null = an explicit 204 "flag absent" payload; an object = the
  // producer's flag.
  const poll = usePolled<LoopAlert | null>("loop_alert", getLoopAlert, {
    intervalMs: Math.max(5_000, pollMs),
    enabled: initial === undefined,
  });
  const alert: LoopAlert | null =
    initial !== undefined ? (initial ?? null) : (poll.data ?? null);
  // A failing refresh while a real flag is rendered: keep it, mark it.
  const refreshFailing =
    initial === undefined && poll.failing && poll.data != null;
  // 30 s live clock: under change detection the banner may not re-render
  // for hours, so a render-time Date.now() would freeze the ~26h staleness
  // verdict (and the stale-marker age) at mount. The banner is a handful of
  // DOM nodes — a whole-banner tick is cheap. `nowMs` still pins tests.
  const liveNow = useNow(30_000);

  if (alert === null || typeof alert !== "object" || Array.isArray(alert)) {
    return null;
  }

  const now = nowMs ?? liveNow;
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
  const gate = gateOf(alert);
  const tone = showRed
    ? "border-red-800 bg-red-950/60 text-red-200"
    : "border-amber-800 bg-amber-950/50 text-amber-200";
  // A held loop is IDLE, not stalled. Saying "LOOP STALLED" over a gate the
  // producer named would be the same unexplained red the owner objected to.
  const headline = gate ? `LOOP IDLE — ${gate.reason}` : showRed ? "LOOP STALLED" : "loop degraded";

  return (
    <div
      data-testid="loop-alert-banner"
      data-level={showRed ? "red" : "amber"}
      role="alert"
      className={`border-b px-6 py-2 text-xs ${tone}`}
    >
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="font-semibold uppercase tracking-wide">{headline}</span>
        <span className={showRed ? "text-red-400/70" : "text-amber-400/70"}>
          run_state/loop_alert.json
        </span>
      </div>
      {gate !== null && (
        <div className="mt-1" data-testid="loop-alert-gate">
          idle: {gate.reason}
          {gate.firstGatedAt !== null ? ` for ${ageLabel(gate.firstGatedAt, now)}` : ""}
          {gate.detail !== null ? ` — ${gate.detail}` : ""}
        </div>
      )}
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
      {refreshFailing && (
        // The failing-refresh marker (residual fix 6): the alert above is
        // the LAST-KNOWN flag, kept on purpose — it clears only on an
        // explicit ok/absent payload, never on a failed poll.
        <div className="mt-1" data-testid="loop-alert-refresh-failing">
          alert refresh failing — showing the last-known alert
          {poll.asOf != null
            ? ` (as of ${ageLabel(new Date(poll.asOf).toISOString(), now)} ago)`
            : ""}
          .
        </div>
      )}
    </div>
  );
}
