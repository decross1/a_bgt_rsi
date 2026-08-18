// VerdictCard — retrieval-station verdict payloads rendered as verdicts
// (owner feedback 2026-08-18: retrieval tool results come out as raw JSON,
// "a little hard to read"). Two shape families, detected by KEY SIGNATURE
// (>= 3 distinctive keys present) and NEVER by caller name:
//   escalation  {should_escalate, max_score, distinct_books, books,
//                score_threshold, min_distinct_books, reason}
//   topicality  {relevance, low_confidence, anchor_cosine, curated_overlap,
//                neighbor_spread, topicality, category, rule_fired, reason}
// "reason" appears in BOTH payloads, so it is not a signature key. A payload
// matching neither family (or confusingly both) falls through to the
// generic envelope grid; malformed content stays on MessageBody's raw
// fail-safe path. Every value renders AS LOGGED — no verdict is re-derived
// or re-judged client-side; the score meter is pure display geometry over
// the logged numbers.
import { CHIP_CLS, JsonDetails, scalarText } from "./bits";

export type VerdictFamily = "escalation" | "topicality";

const hasOwn = (obj: object, key: string): boolean =>
  Object.prototype.hasOwnProperty.call(obj, key);

const ESCALATION_SIG = [
  "should_escalate",
  "max_score",
  "distinct_books",
  "books",
  "score_threshold",
  "min_distinct_books",
];
const TOPICALITY_SIG = [
  "relevance",
  "low_confidence",
  "anchor_cosine",
  "curated_overlap",
  "neighbor_spread",
  "topicality",
  "category",
  "rule_fired",
];

/** The verdict family of a parsed payload, or null when it is not
 * CONFIDENTLY one family (>= 3 signature keys; both-match is ambiguous). */
export function detectVerdictFamily(v: unknown): VerdictFamily | null {
  if (v == null || typeof v !== "object" || Array.isArray(v)) return null;
  const rec = v as Record<string, unknown>;
  const esc = ESCALATION_SIG.filter((k) => hasOwn(rec, k)).length;
  const top = TOPICALITY_SIG.filter((k) => hasOwn(rec, k)).length;
  if (esc >= 3 && top >= 3) return null; // ambiguous → generic grid
  if (esc >= 3) return "escalation";
  if (top >= 3) return "topicality";
  return null;
}

/** A verdict payload logged BARE as tool content (no wrapper envelope), or
 * null. MessageBody's second entry point into the verdict rendering. */
export function parseBareVerdict(
  content: unknown,
): { family: VerdictFamily; data: Record<string, unknown> } | null {
  if (typeof content !== "string" || !content.trimStart().startsWith("{")) {
    return null;
  }
  try {
    const obj: unknown = JSON.parse(content);
    const family = detectVerdictFamily(obj);
    return family == null
      ? null
      : { family, data: obj as Record<string, unknown> };
  } catch {
    return null;
  }
}

const finiteOrNull = (v: unknown): number | null =>
  typeof v === "number" && Number.isFinite(v) ? v : null;

// Value-or-dash for chips/metrics: null/absent/non-scalar all display as the
// honest dash. (scalarText(null) is the literal "null"; in a metric row the
// dash reads as "not logged", which is what null means here.)
const dash = (v: unknown): string => (v == null ? "—" : (scalarText(v) ?? "—"));

// Badge tones mirror ToolResultCard's statusTone families: positive verdict
// = emerald, attention verdict = amber.
const BADGE_BASE = "rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide";
const BADGE_ON = `${BADGE_BASE} bg-emerald-950 text-emerald-400`;
const BADGE_WARN = `${BADGE_BASE} bg-amber-950 text-amber-300`;
const WARN_CHIP_CLS =
  "rounded bg-amber-950 px-1.5 py-0.5 font-mono text-[10px] text-amber-300";

/** Thin score bar: fill = max_score, tick = score_threshold, on a shared
 * 0..max(1, score, threshold) domain. Red below the tick, green at/above —
 * display geometry only; the escalation verdict itself is never recomputed
 * here (should_escalate renders as logged). */
function ScoreMeter({ score, threshold }: { score: number; threshold: number }) {
  const domain = Math.max(1, score, threshold);
  const pct = (v: number) => `${((Math.max(0, v) / domain) * 100).toFixed(1)}%`;
  const above = score >= threshold;
  return (
    <div
      data-testid="score-meter"
      className="flex items-center gap-2"
      title={`max_score ${score} vs score_threshold ${threshold}`}
    >
      <div className="relative h-1.5 w-40 max-w-full rounded bg-zinc-800">
        <div
          data-testid="score-meter-fill"
          className={`absolute inset-y-0 left-0 rounded ${
            above ? "bg-emerald-500/80" : "bg-rose-500/80"
          }`}
          style={{ width: pct(score) }}
        />
        <div
          data-testid="score-meter-tick"
          className="absolute -bottom-0.5 -top-0.5 w-px bg-zinc-300"
          style={{ left: pct(threshold) }}
        />
      </div>
      <span className="font-mono text-[10px] text-zinc-500">
        {score} / {threshold}
      </span>
    </div>
  );
}

/** The reason as ONE dim prose line (full text in the title attr; the raw
 * toggle keeps the whole payload reachable). */
function ReasonLine({ reason }: { reason: unknown }) {
  if (typeof reason !== "string" || reason.trim() === "") return null;
  return (
    <div
      data-testid="verdict-reason"
      className="truncate text-xs text-zinc-500"
      title={reason}
    >
      {reason}
    </div>
  );
}

function EscalationBody({ data }: { data: Record<string, unknown> }) {
  const should = data.should_escalate;
  const score = finiteOrNull(data.max_score);
  const threshold = finiteOrNull(data.score_threshold);
  const books = data.books;
  return (
    <div data-testid="verdict-escalation" className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center gap-1.5">
        {typeof should === "boolean" ? (
          <span
            data-testid="escalate-badge"
            className={should ? BADGE_WARN : BADGE_ON}
          >
            {should ? "escalate" : "no-escalate"}
          </span>
        ) : (
          <span className={CHIP_CLS}>should_escalate: {dash(should)}</span>
        )}
        <span data-testid="books-chip" className={CHIP_CLS}>
          books {dash(data.distinct_books)}/{dash(data.min_distinct_books)}
        </span>
      </div>
      {score != null && threshold != null ? (
        <ScoreMeter score={score} threshold={threshold} />
      ) : (
        // Either number missing/non-numeric → no meter geometry to draw;
        // the values still show, null-safe, as logged.
        <span className={`self-start ${CHIP_CLS}`}>
          max_score {dash(data.max_score)} · threshold{" "}
          {dash(data.score_threshold)}
        </span>
      )}
      {Array.isArray(books) && books.length > 0 && (
        <JsonDetails
          label={`${books.length} books ▸`}
          value={books}
          testId="verdict-books"
        />
      )}
      <ReasonLine reason={data.reason} />
    </div>
  );
}

const METRIC_KEYS = ["anchor_cosine", "curated_overlap", "neighbor_spread"];

function TopicalityBody({ data }: { data: Record<string, unknown> }) {
  const top = data.topicality;
  return (
    <div data-testid="verdict-topicality" className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center gap-1.5">
        {typeof top === "boolean" ? (
          <span
            data-testid="topicality-badge"
            className={top ? BADGE_ON : BADGE_WARN}
          >
            {top ? "topical" : "off-topic"}
          </span>
        ) : (
          <span className={CHIP_CLS}>topicality: {dash(top)}</span>
        )}
        {data.category != null && (
          <span data-testid="category-chip" className={CHIP_CLS}>
            {dash(data.category)}
          </span>
        )}
        {data.rule_fired != null && (
          <span data-testid="rule-chip" className={CHIP_CLS}>
            rule {dash(data.rule_fired)}
          </span>
        )}
        <span className={CHIP_CLS}>relevance: {dash(data.relevance)}</span>
        <span
          data-testid="low-confidence-chip"
          className={data.low_confidence === true ? WARN_CHIP_CLS : CHIP_CLS}
        >
          low_confidence: {dash(data.low_confidence)}
        </span>
      </div>
      <div
        data-testid="metric-row"
        className="flex flex-wrap gap-x-3 font-mono text-[10px] text-zinc-500"
      >
        {METRIC_KEYS.map((k) => (
          <span key={k}>
            {k} {dash(data[k])}
          </span>
        ))}
      </div>
      <ReasonLine reason={data.reason} />
    </div>
  );
}

export default function VerdictCard({
  family,
  data,
}: {
  family: VerdictFamily;
  data: Record<string, unknown>;
}) {
  return family === "escalation" ? (
    <EscalationBody data={data} />
  ) : (
    <TopicalityBody data={data} />
  );
}
