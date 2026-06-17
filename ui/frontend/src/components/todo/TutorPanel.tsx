// TutorPanel — the /todo finding OVERVIEW. It explains the finding the human is
// about to resolve (the claim, where it came from, what would change it, what it
// rests on) and it NEVER recommends. The verdict path is elsewhere
// (FindingReviewForm / AbstainForm); this surface only teaches.
//
// THE FENCE (D-054, enforced BY CONSTRUCTION):
//   - This component accepts NO verdict / confidence / onResolved / calibration /
//     setter prop. It is STRUCTURALLY unable to influence or auto-fill the
//     verdict, because it is never handed the means to.
//   - It renders NO recommendation and NO accept/deny steer. The mechanical
//     outcome-effects line states what each outcome DOES (neutrally); the
//     pros/cons enumeration lists considerations UNWEIGHTED — no "this outweighs
//     that", no "you should".
//   - The visible fence note cites the REAL source of the fence: the 2026-06-14
//     session note PART 2 + inviolate rule 4 + D-053 (NOT D-044 — D-044 is the
//     vllm-qwen novelty-skeptic independence decision, a different fence).
//
// DATA: the overview comes from GET /api/finding/{finding_id} (getFindingDetail),
// a READ-ONLY join of surfaced_findings.jsonl with its source loop_memory.jsonl
// iteration (the GET writes nothing — the tutor cannot mutate state either). The
// `detail` prop is the test-injection override (mirrors Todo.tsx's availability/
// items overrides): when provided we render it directly and DO NOT fetch. An
// empty findingId renders the idle "select a finding" state with no fetch; a
// failed/empty fetch degrades to "detail unavailable" — never a throw, never a
// blank.
import { useEffect, useState } from "react";
import type { FindingDetail } from "../../types/schemas";
import { getFindingDetail } from "../../api/http";

interface Props {
  findingId: string;
  /** A short human-readable title/claim to anchor the explanation (legacy
   *  back-compat; the fetched detail's title wins when present). */
  title?: string;
  /** Injected detail — when provided, wins and SUPPRESSES the self-fetch. The
   *  test-injection / preview override (mirrors Todo.tsx availability/items). */
  detail?: FindingDetail;
}

// Every field on FindingDetail is producer-owned and unvalidated (the backend
// casts the JSONL without a shape check, and the `detail` prop bypasses even
// that). Normalize each field to a usable scalar the SAME way SourceBadge.asText
// / LowEvidenceBadge.asText do — a string trims, a finite number / boolean
// stringifies, anything else (object / array / NaN / Infinity / null / undefined,
// and exotics like bigint / Symbol / a throwing-toString) yields "" by TYPEOF
// ALONE so the field is DROPPED, never "[object Object]" / "NaN" in the DOM and
// never a raw object reaching React as a child (which throws "Objects are not
// valid as a React child" and would blank the whole /todo cockpit on one bad
// row). asText reads NO property on the value — no deref, deep-deref safe.
function asText(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "";
  if (typeof value === "boolean") return String(value);
  return "";
}

// One labelled line: render only when the coerced value is non-empty (absent
// fields are DROPPED, never shown as an empty/garbage row).
function Field({ label, value }: { label: string; value: unknown }) {
  const text = asText(value);
  if (text.length === 0) return null;
  return (
    <div className="mt-1 text-[11px] leading-snug text-zinc-400">
      <span className="text-[10px] uppercase tracking-wide text-zinc-600">
        {label}
      </span>{" "}
      <span className="text-zinc-300">{text}</span>
    </div>
  );
}

// A quiet inline badge for the classification chips (novelty_class /
// critic_verdict / status). Dropped when the value coerces to "".
function Badge({ label, value }: { label: string; value: unknown }) {
  const text = asText(value);
  if (text.length === 0) return null;
  return (
    <span className="rounded border border-zinc-800 bg-zinc-950 px-1.5 py-0.5 font-mono text-[10px] text-zinc-400">
      <span className="text-zinc-600">{label} </span>
      {text}
    </span>
  );
}

// One evidence ref line (read-only). `detail.evidence` is a DICT (not a list);
// each ref is coerced independently and dropped when absent.
function EvidenceRef({ label, value }: { label: string; value: unknown }) {
  const text = asText(value);
  if (text.length === 0) return null;
  return (
    <li className="break-all text-[11px] text-zinc-400">
      <span className="text-[10px] uppercase tracking-wide text-zinc-600">
        {label}
      </span>{" "}
      <span className="font-mono text-zinc-300">{text}</span>
    </li>
  );
}

export default function TutorPanel({ findingId, title, detail }: Props) {
  const idText = asText(findingId);

  // Self-fetch when no detail is injected and there IS a finding to explain.
  // Mirrors ConcurrencyWarning's self-fetch idiom: a live-flag cleanup, and a
  // swallowed rejection so a failed fetch (network error, non-2xx throw, or
  // `fetch` undefined under jsdom) degrades to "detail unavailable" rather than
  // surfacing an unhandled rejection or a console error. We never fabricate a
  // detail.
  const [fetched, setFetched] = useState<FindingDetail | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    // Injected detail wins → no fetch. Empty findingId → idle, no fetch.
    if (detail !== undefined || idText.length === 0) return;
    let live = true;
    setFetched(null);
    setFailed(false);
    getFindingDetail(idText)
      .then((d) => {
        if (live) setFetched(d);
      })
      .catch(() => {
        // Cannot load the overview → mark unavailable; never throw, never blank.
        if (live) setFailed(true);
      });
    return () => {
      live = false;
    };
  }, [detail, idText]);

  const titleText = asText(title);

  // The fence note + header are ALWAYS rendered (idle, unavailable, and loaded
  // states all show the separation). Shared chrome:
  const chrome = (body: React.ReactNode) => (
    <div
      data-testid="tutor-panel"
      className="rounded border border-indigo-900/60 bg-indigo-950/20 px-2 py-1.5"
    >
      <div className="text-[10px] uppercase tracking-wide text-indigo-400">
        tutor / finding overview
      </div>
      {/* THE VISIBLE FENCE — cites the REAL source (NOT D-044). It explains; it
          never recommends. */}
      <div
        data-testid="tutor-fence-note"
        className="mt-0.5 text-[10px] text-zinc-500"
      >
        tutor — does not affect your verdict (2026-06-14 note PART 2 · inviolate
        rule 4 · D-053). It explains; it never recommends.
      </div>
      {body}
    </div>
  );

  // 1) Idle — nothing selected to explain. No fetch ran.
  if (idText.length === 0 && detail === undefined) {
    return chrome(
      <div
        data-testid="tutor-idle"
        className="mt-1 text-[11px] text-zinc-500"
      >
        Select a finding to see its overview.
      </div>,
    );
  }

  // Resolve the detail to render: the injected prop wins; else the fetched one.
  const resolved: FindingDetail | null =
    detail !== undefined ? detail : fetched;

  // 2) Unavailable — fetch failed, OR the backend returned found:false (unknown
  // id at HTTP 200), OR an injected detail is malformed/empty. The tutor
  // degrades in place; it NEVER blanks and NEVER fabricates content.
  const unavailable =
    failed ||
    resolved === null ||
    typeof resolved !== "object" ||
    Array.isArray(resolved) ||
    (resolved as FindingDetail).found !== true;

  if (unavailable) {
    return chrome(
      <div
        data-testid="tutor-unavailable"
        className="mt-1 text-[11px] text-zinc-500"
      >
        {/* still anchor the title if a legacy prop carried one */}
        {titleText.length > 0 ? (
          <>
            <span className="text-zinc-400">{titleText}</span>
            {" — "}
          </>
        ) : null}
        finding overview unavailable.
        {idText.length > 0 ? (
          <span className="text-zinc-600"> ({idText})</span>
        ) : null}
      </div>,
    );
  }

  const d = resolved as FindingDetail;
  // The fetched title wins; fall back to the legacy `title` prop.
  const claimTitle = asText(d.title) || titleText;
  // `source_iteration` / `evidence` are typed, but the producer JSONL (and the
  // injected `detail` prop) are unvalidated — re-coerce through `unknown` to a
  // plain record so a non-object (string / array / null) degrades to "no block"
  // rather than crashing on a property read. The per-field asText still guards
  // every value inside.
  const src = d.source_iteration as unknown;
  const srcObj =
    src !== null && typeof src === "object" && !Array.isArray(src)
      ? (src as Record<string, unknown>)
      : null;
  const ev = d.evidence as unknown;
  const evObj =
    ev !== null && typeof ev === "object" && !Array.isArray(ev)
      ? (ev as Record<string, unknown>)
      : null;
  const srcIterId = asText(d.source_iteration_id) || asText(srcObj?.iteration_id);

  // The NEUTRAL MECHANICAL outcome-effects line: states what each outcome DOES,
  // no recommendation. Deliberately avoids the word "verdict" so the route-level
  // single-match fence-note assertion stays exact.
  const iterRef = srcIterId.length > 0 ? srcIterId : "its source iteration";

  return chrome(
    <div data-testid="tutor-overview">
      {/* CLAIM (+ title) */}
      {claimTitle.length > 0 ? (
        <div className="mt-1 text-[11px] font-medium text-zinc-200">
          {claimTitle}
        </div>
      ) : null}
      <Field label="claim" value={d.claim} />

      {/* SOURCE ITERATION */}
      {srcObj !== null ? (
        <div
          data-testid="tutor-source-iteration"
          className="mt-1.5 rounded border border-zinc-800/60 bg-zinc-950/40 px-1.5 py-1"
        >
          <div className="text-[10px] uppercase tracking-wide text-zinc-600">
            source iteration
          </div>
          <Field label="id" value={srcObj.iteration_id} />
          <Field label="topic" value={srcObj.topic} />
          <Field label="gate" value={srcObj.gate_status} />
          <Field label="summary" value={srcObj.nara_summary} />
        </div>
      ) : null}

      {/* WHAT WOULD CHANGE IT / blocker, and WHY IT MATTERS */}
      <Field label="what would change it" value={d.what_would_change_it} />
      <Field label="why it matters" value={d.why_it_matters} />

      {/* EVIDENCE REFS (read-only) — evidence is a DICT; drop absent refs. */}
      {evObj !== null ? (
        <div data-testid="tutor-evidence" className="mt-1.5">
          <div className="text-[10px] uppercase tracking-wide text-zinc-600">
            evidence (read-only)
          </div>
          <ul className="mt-0.5 space-y-0.5">
            <EvidenceRef label="journal" value={evObj.journal_entry_path} />
            <EvidenceRef label="results" value={evObj.results_path} />
            <EvidenceRef
              label="experiment outcome"
              value={evObj.experiment_outcome}
            />
            <EvidenceRef label="critic rationale" value={evObj.critic_rationale} />
          </ul>
        </div>
      ) : null}

      {/* quiet classification badges */}
      <div className="mt-1.5 flex flex-wrap gap-1">
        <Badge label="novelty" value={d.novelty_class} />
        <Badge label="critic" value={d.critic_verdict} />
        <Badge label="status" value={d.status} />
      </div>

      {/* NEUTRAL MECHANICAL outcome-effects — what each outcome DOES, no steer. */}
      <div
        data-testid="tutor-outcome-effects"
        className="mt-2 rounded border border-zinc-800/60 bg-zinc-950/40 px-1.5 py-1 text-[10px] leading-snug text-zinc-500"
      >
        <span className="uppercase tracking-wide text-zinc-600">
          what each outcome does (mechanical)
        </span>
        <div className="mt-0.5">
          accept → writes a valid loop_feedback row against iteration{" "}
          <span className="font-mono text-zinc-400">{iterRef}</span> and clears
          this from the queue · deny → writes an invalid row and clears it ·
          in_review → leaves it queued (no row written).
        </div>
      </div>

      {/* NEUTRAL UNWEIGHTED considerations — enumerated, NOT weighted, NO steer. */}
      <div
        data-testid="tutor-considerations"
        className="mt-1.5 grid gap-1 sm:grid-cols-2"
      >
        <div className="rounded border border-zinc-800/60 bg-zinc-950/40 px-1.5 py-1">
          <div className="text-[10px] uppercase tracking-wide text-zinc-600">
            considerations for
          </div>
          <ul className="mt-0.5 list-disc pl-3 text-[10px] leading-snug text-zinc-500">
            <li>the claim survived the critic to be surfaced at all.</li>
            <li>the source iteration + evidence refs above are inspectable.</li>
            <li>accepting records it for the loop to build on.</li>
          </ul>
        </div>
        <div className="rounded border border-zinc-800/60 bg-zinc-950/40 px-1.5 py-1">
          <div className="text-[10px] uppercase tracking-wide text-zinc-600">
            considerations against
          </div>
          <ul className="mt-0.5 list-disc pl-3 text-[10px] leading-snug text-zinc-500">
            <li>
              the &ldquo;what would change it&rdquo; line names what is still
              unsettled.
            </li>
            <li>novelty / critic chips may rest on thin or off-domain retrieval.</li>
            <li>in_review keeps it open if you are not yet decided.</li>
          </ul>
        </div>
      </div>

      <div className="mt-1.5 text-[10px] text-zinc-600">
        These are unweighted considerations, not a recommendation.
      </div>
    </div>,
  );
}
