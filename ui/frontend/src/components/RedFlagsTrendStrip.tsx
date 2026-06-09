// RedFlagsTrendStrip — the research program's own standing self-checks, as a
// compact strip of percentage tiles over the given iterations. Per
// ui_autonomy_observability_plan.md design principle #7 ("standing red-flags"):
// surface, at a glance, whether the loop is surfacing things genuinely new or
// fooling itself. Three rates:
//   - novel-rate              : fraction with novelty.class === "novel".
//   - suspected-false-novel   : fraction that are novel/survives AND
//                               isLowEvidence(row) — THE key trust metric (the
//                               2026-06-09 false `novel/survives` on off-domain
//                               retrieval is exactly this). Amber/red emphasis
//                               when non-trivial, because a verdict that says
//                               "new" on thin air is the thing a human must catch.
//   - off-domain / thin       : fraction with retrieval.relevance.low_confidence
//                               true — the retrieval that can't be trusted.
// Matches the dark tile idiom (MetricTile: rounded zinc tile, uppercase label,
// large tabular value). Empty/zero state safe: 0 iterations renders "—" tiles.
import { isLowEvidence } from "./LowEvidenceBadge";
import type { IterationRecord } from "../types/schemas";

// Above this, the suspected-false-novel tile escalates from quiet to emphasis:
// any non-trivial share of "new on thin air" verdicts wants a human's eye.
const SUSPECT_WARN = 0.0001; // strictly > 0 → emphasis (any false-novel is notable)
const SUSPECT_BAD = 0.25; // a quarter or more is a red-tier trust problem

// novel/survives: the trust-critical verdict shorthand used across the codebase
// (LowEvidenceBadge, AgentBadge). Either a "novel" class OR a "survives"
// verdict — the union is the broad net the low-evidence flag guards.
function isNovelOrSurvives(row: IterationRecord): boolean {
  return row.novelty?.class === "novel" || row.critique?.verdict === "survives";
}

function isOffDomain(row: IterationRecord): boolean {
  // The retrieval-relevance worker's authoritative thin/off-domain signal.
  return row.retrieval?.relevance?.low_confidence === true;
}

// Format a fraction as a whole-percent string; "—" when there is no denominator.
function pct(numerator: number, denominator: number): string {
  if (denominator === 0) return "—";
  return `${Math.round((numerator / denominator) * 100)}%`;
}

// A single percentage tile. Tone drives the value color (emerald/amber/red),
// matching the MetricTile palette without pulling in its sparkline.
const TONE_TEXT: Record<string, string> = {
  ok: "text-emerald-400",
  warn: "text-amber-400",
  bad: "text-red-400",
  idle: "text-zinc-200",
};

function Tile({
  label,
  value,
  count,
  tone,
  testid,
}: {
  label: string;
  value: string;
  count: string;
  tone: keyof typeof TONE_TEXT;
  testid: string;
}) {
  return (
    <div
      className="rounded border border-zinc-800 bg-zinc-900/40 p-3"
      data-testid={testid}
    >
      <div className="text-xs uppercase tracking-wide text-zinc-500">{label}</div>
      <div className={`mt-1 text-xl font-semibold tabular-nums ${TONE_TEXT[tone]}`}>
        {value}
      </div>
      <div className="mt-0.5 text-[10px] text-zinc-600">{count}</div>
    </div>
  );
}

export default function RedFlagsTrendStrip({
  iterations,
}: {
  iterations: IterationRecord[];
}) {
  const total = iterations.length;

  const novelCount = iterations.filter(
    (r) => r.novelty?.class === "novel",
  ).length;
  const suspectCount = iterations.filter(
    (r) => isNovelOrSurvives(r) && isLowEvidence(r),
  ).length;
  const offDomainCount = iterations.filter(isOffDomain).length;

  const suspectRate = total === 0 ? 0 : suspectCount / total;
  // Suspect tile escalates: any non-trivial false-novel share is amber, a
  // quarter-plus is red. Zero (or no data) stays quiet zinc — don't over-alarm.
  const suspectTone: keyof typeof TONE_TEXT =
    suspectRate >= SUSPECT_BAD
      ? "bad"
      : suspectRate > SUSPECT_WARN
        ? "warn"
        : "idle";
  // Off-domain retrieval is degraded, not broken → amber when present.
  const offDomainTone: keyof typeof TONE_TEXT =
    offDomainCount > 0 ? "warn" : "idle";

  return (
    <div
      className="rounded border border-zinc-800 bg-zinc-900/40 p-4"
      data-testid="red-flags-trend-strip"
    >
      <div className="flex items-baseline gap-2">
        <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          Red flags
        </h2>
        <span className="text-[10px] text-zinc-600">
          self-checks over {total} iteration{total === 1 ? "" : "s"}
        </span>
      </div>

      <div className="mt-2 grid grid-cols-3 gap-3">
        <Tile
          testid="red-flag-novel-rate"
          label="Novel rate"
          value={pct(novelCount, total)}
          count={`${novelCount} of ${total}`}
          tone="idle"
        />
        <Tile
          testid="red-flag-suspected-false-novel"
          label="Suspected false-novel"
          value={pct(suspectCount, total)}
          count={`${suspectCount} of ${total}`}
          tone={suspectTone}
        />
        <Tile
          testid="red-flag-off-domain"
          label="Off-domain retrieval"
          value={pct(offDomainCount, total)}
          count={`${offDomainCount} of ${total}`}
          tone={offDomainTone}
        />
      </div>
    </div>
  );
}
