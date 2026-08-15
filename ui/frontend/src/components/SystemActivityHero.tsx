// Dashboard hero — "what is the machine doing RIGHT NOW". The headline fix
// for the 2026-06-09 screenshot complaint: GPU at 96% + gemma decoding while
// the dashboard read "ACTIVE: idle / HEALTHY all systems nominal".
//
// UI simplification S1: the pure verdict (computeActivity + its builders)
// moved VERBATIM to ./nowVerdict.ts, shared with the merged NowBoard headline
// strip — this file is now only the presentational shell (it still mounts on
// the old /dashboard and dies with it in S3). Pure / prop-driven: no fetching
// here — the Dashboard wires the feeds in.
import { Component, isValidElement, type ReactNode } from "react";
import { useNow } from "../time";
import {
  computeActivity,
  STATE_LABEL,
  STATE_TONE,
  type ActivityInput,
} from "./nowVerdict";

// The needsYou slot is typed ReactNode, but its value crosses a prop boundary
// the Dashboard owns — and a future caller (or a producer-derived count) may
// pass something React refuses to render as a child: a bare object, an array
// containing one, or a non-finite number ("Objects are not valid as a React
// child" THROWS and blanks the whole Dashboard). Pass through only what React
// renders safely — a valid element, string, finite number, or an array of
// those — and DROP anything else (null). Valid-input behavior is identical:
// the Dashboard's <Link> is a valid element and survives untouched.
function asNode(v: unknown): ReactNode {
  if (v === null || v === undefined) return null;
  if (isValidElement(v)) return v;
  if (typeof v === "string") return v;
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (Array.isArray(v)) {
    const kids = v.map(asNode).filter((k) => k !== null);
    return kids.length > 0 ? kids : null;
  }
  // boolean / object / function / symbol — not a legible child; drop it.
  return null;
}

// asNode guards the needsYou VALUE, but it can only inspect the value's own
// shape — not the interior of an opaque element it passes through. A valid
// element (isValidElement) whose own children are a producer-derived bare
// object (e.g. <Link>{escalation.summary}</Link> where `summary` arrived as an
// object/array from loop_memory) sails past the shallow isValidElement check
// and then THROWS "Objects are not valid as a React child" when React renders
// the child — blanking the whole Dashboard, since this slot sits in the
// always-rendered header. React surfaces such a deep-child fault only at
// render time, so the only honest guard is to catch the render itself and
// drop to the absent-slot fallback (the same legible degradation asNode gives
// for a value it can statically reject). Scoped to the slot only; the verdict
// header is unaffected.
class SlotBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? null : this.props.children;
  }
}

export interface SystemActivityHeroProps extends ActivityInput {
  // Injectable clock for tests; defaults to the shared 1 Hz live clock.
  nowMs?: number;
  // The dashboard's "N need you →" coupling (PART 1, 2026-06-14 work order):
  // the pending human-escalation count, rendered in EVERY state so a busy
  // machine can never hide a pending decision. Router-free by design — the
  // Dashboard (inside the Router) supplies the actual `<Link to="/todo">`
  // node; the hero just gives it a home in the header. Omitted/undefined →
  // nothing renders (the hero stays usable outside the dashboard).
  needsYou?: ReactNode;
}

export default function SystemActivityHero(props: SystemActivityHeroProps) {
  const tick = useNow();
  const now = props.nowMs ?? tick;
  const verdict = computeActivity(props, now);
  const tone = STATE_TONE[verdict.state];
  // Drop a non-renderable needsYou rather than let it throw (asNode idiom).
  const needsYou = asNode(props.needsYou);

  return (
    <div
      data-testid="system-activity-hero"
      data-state={verdict.state}
      className={`rounded border ${tone.border} bg-zinc-900/40 px-4 py-3`}
    >
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <span className="flex items-center gap-2">
          <span className={`h-2.5 w-2.5 rounded-full ${tone.dot}`} aria-hidden />
          <span className={`text-lg font-semibold tracking-wide ${tone.text}`}>
            {STATE_LABEL[verdict.state]}
          </span>
        </span>
        <span className="text-sm text-zinc-400">{verdict.headline}</span>
        {needsYou != null && (
          <SlotBoundary>
            <span className="ml-auto" data-testid="system-activity-needs-you">
              {needsYou}
            </span>
          </SlotBoundary>
        )}
      </div>
      {verdict.evidence.length > 0 && (
        <div
          className="mt-1 font-mono text-xs text-zinc-500"
          data-testid="system-activity-evidence"
        >
          {verdict.evidence.join(" · ")}
        </div>
      )}
    </div>
  );
}
