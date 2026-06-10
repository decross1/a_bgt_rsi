// IterationDetailModal — the full-detail drill-in for one resolved iteration
// (handoff 2026-06-10 Task 4). The ResolvedIterationsList rows condensed to
// id + max-4 badges + topic; everything that left the row lands HERE:
// NoveltyAxesChip, conditioning bullets, the process badge, non-nemoclaw
// source badges, the second/third alarm chips, and the override provenance as
// VISIBLE text (the row keeps tooltip-only).
//
// Mechanics: a NATIVE <dialog> (no new deps) opened with showModal() on
// mount. Esc and a backdrop click close it; the OPENING CARD's focus is
// restored by the parent (ResolvedIterationsList) via the onClose callback.
// jsdom lacks showModal()/close() — tests/setup.ts carries the polyfill.
//
// This file is also the home of the chip primitives the condensed list shares
// (tone maps, Badge, RedteamChip, ExperimentChip, the scalar guards). They
// moved here VERBATIM from ResolvedIterationsList.tsx so the dependency stays
// one-directional (list → modal) without a new shared module. Tones are
// unchanged — the forward-compat pins (quiet zinc fallback, the deliberate
// undecidable /40) still bite.
//
// Every field below is producer-owned JSONL parsed unchecked — the TS types
// are a compile-time fiction. All scalars render through badgeText/asScalar
// (never "[object Object]", never NaN); absent fields omit their line rather
// than faking a value.
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { getCoordinatorCycles } from "../api/http";
import type { IterationRecord } from "../types/schemas";
import GateVerdictForm from "./GateVerdictForm";
import JournalScroll from "./JournalScroll";
import LowEvidenceBadge, { isLowEvidence } from "./LowEvidenceBadge";
import NoveltyAxesChip from "./NoveltyAxesChip";
import SourceBadge from "./SourceBadge";

// ---------------------------------------------------------------------------
// Shared chip primitives (moved verbatim from ResolvedIterationsList.tsx —
// the list imports them back from here).
// ---------------------------------------------------------------------------

export const NOVELTY_TONE: Record<string, string> = {
  novel: "bg-emerald-950 text-emerald-400",
  rediscovery: "bg-amber-950 text-amber-400",
  unclear: "bg-zinc-800 text-zinc-400",
  nonsense: "bg-red-950 text-red-400",
};

export const VERDICT_TONE: Record<string, string> = {
  survives: "bg-emerald-950 text-emerald-400",
  restated: "bg-amber-950 text-amber-400",
  falsified: "bg-red-950 text-red-400",
  malformed: "bg-red-950 text-red-400",
  // "undecidable" (close-out 2026-06-09, EMIT: workers/critic_loop_v0.py) fails
  // closed — "could not be judged on this retrieval", never promotes. A
  // DELIBERATE quiet-grey entry, not the unknown-enum fallback: same quiet lane
  // (no emerald/red/amber alarm), the /40 translucency marks it as intentional.
  // The forward-compat pins (test_forwardcompat_iterations_list) require the
  // tone to keep the bg-zinc-800 + text-zinc-400 quiet family.
  undecidable: "bg-zinc-800/40 text-zinc-400",
};

// Loop v1 Step 8 human-gate state.
export const GATE_TONE: Record<string, string> = {
  pending: "bg-sky-950 text-sky-300",
  valid: "bg-emerald-950 text-emerald-400",
  invalid: "bg-red-950 text-red-400",
  needs_revision: "bg-amber-950 text-amber-400",
};

// Tone lookup for the producer-owned enum fields (novelty.class / critique.verdict
// / gate_status). These are append-only JSONL values, so an UNKNOWN/forward-compat
// enum (a never-seen class, or a value colliding with an inherited Object.prototype
// member name — "toString", "constructor", "valueOf", "hasOwnProperty", "__proto__")
// must fall back to the quiet tone, NOT resolve a prototype function. A bare
// `MAP[value] ?? fallback` resolves "toString" to `Function.prototype.toString` (a
// function, not undefined), so `?? fallback` does NOT fire and that function
// interpolates into className as "function toString() { [native code] }". Own-key
// lookup only; any unknown value (prototype collision included) takes `fallback`.
// Mirrors SourceBadge / AgentBadge's prototype-collision guard.
export function toneFor(
  map: Record<string, string>,
  key: string | null | undefined,
  fallback: string,
): string {
  if (typeof key !== "string") return fallback;
  return Object.prototype.hasOwnProperty.call(map, key) ? map[key] : fallback;
}

// Process-status badge. `status` mirrors /api/loop_v0/processes:
// running / exited_clean / exited_error_<rc> / killed_signal_<sig>.
// `status` is producer-owned (joined from /api/loop_v0/processes); a malformed
// row can hand a number/object, and `.startsWith` then throws
// ("status.startsWith is not a function") and takes the row down. A non-string
// is treated as "no status" — the `typeof` guards stand in for the previous
// falsy check.
export function processTone(status: string | undefined): string {
  if (typeof status !== "string" || !status) return "bg-zinc-800 text-zinc-400";
  if (status === "running") return "bg-sky-950 text-sky-300";
  if (status === "exited_clean") return "bg-emerald-950 text-emerald-400";
  if (status.startsWith("exited_error_")) return "bg-red-950 text-red-400";
  if (status.startsWith("killed_signal_")) return "bg-red-950 text-red-400";
  return "bg-zinc-800 text-zinc-400";
}

export function processLabel(status: string | undefined): string | null {
  if (typeof status !== "string" || !status) return null;
  if (status === "exited_clean") return "pid clean";
  if (status === "running") return "pid running";
  if (status.startsWith("exited_error_")) return `pid err ${status.slice("exited_error_".length)}`;
  if (status.startsWith("killed_signal_")) return `pid killed ${status.slice("killed_signal_".length)}`;
  return status;
}

// `text` is fed producer-owned enum fields (novelty.class / critique.verdict /
// gate_status). The `string | null | undefined` type is a compile-time fiction
// over unchecked JSONL: a malformed/legacy row can emit an object or array, and
// React throws "Objects are not valid as a React child" the moment one reaches
// {text} — crashing the whole row. Coerce to a safe scalar string: a string /
// finite number renders as-is; anything without a usable scalar form (object,
// array, NaN, null, undefined) yields no badge rather than a throw.
export function badgeText(text: string | null | undefined): string {
  if (typeof text === "string") return text;
  if (typeof text === "number") return Number.isFinite(text) ? String(text) : "";
  return "";
}

// Wider scalar guard for the modal's detail lines: also stringifies booleans
// (relevance.low_confidence, topicality flags). Same stance as
// SourceBadge.asText — anything without a usable scalar form yields "".
function asScalar(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "";
  if (typeof value === "boolean") return String(value);
  return "";
}

// Skeptic-gate override provenance (close-out 2026-06-09):
// verdict_overridden_from / skeptic_verdict are plain strings that may appear
// on BOTH the novelty and critique blocks (absent on legacy rows). On the ROW
// they surface as a title tooltip on that block's badge; the modal's verdict
// header additionally renders all three as visible text (OverrideProvenance).
// Producer-owned: a garbled field (object/array, per the forward-compat pins)
// is dropped via badgeText so "[object Object]" can never land in the title
// attribute. Returns undefined (no tooltip) when neither field is usable.
export function overrideTooltip(
  block:
    | { verdict_overridden_from?: unknown; skeptic_verdict?: unknown }
    | null
    | undefined,
): string | undefined {
  const from = badgeText(
    block?.verdict_overridden_from as string | null | undefined,
  );
  const skeptic = badgeText(block?.skeptic_verdict as string | null | undefined);
  const parts: string[] = [];
  if (from) parts.push(`overridden from ${from}`);
  if (skeptic) parts.push(`skeptic said ${skeptic}`);
  return parts.length > 0 ? parts.join("; ") : undefined;
}

export function Badge({
  text,
  tone,
  title,
}: {
  text: string | null | undefined;
  tone: string;
  title?: string;
}) {
  const safe = badgeText(text);
  if (!safe) return null;
  return (
    <span
      title={title}
      className={`rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${tone}`}
    >
      {safe}
    </span>
  );
}

// Loop v1 Step 2.5 red-team chip. Highlighted (red) when the critic ruled
// fatal_flaw OR any revision retries were spent — those are the rows a
// human most needs to eyeball. A clean "proceed / 0 retries" pass renders
// quiet zinc. Returns null when no redteam block is present (pre-v1 rows).
export function RedteamChip({
  redteam,
}: {
  redteam: IterationRecord["redteam"];
}) {
  if (!redteam || (redteam.verdict == null && redteam.retries_used == null)) {
    return null;
  }
  const retries = redteam.retries_used ?? 0;
  const fatal = redteam.verdict === "fatal_flaw";
  const highlight = fatal || retries > 0;
  const tone = highlight
    ? "bg-red-950 text-red-400"
    : "bg-zinc-800 text-zinc-400";
  const label = `redteam ${redteam.verdict ?? "?"}${
    retries > 0 ? ` · ${retries} retr${retries === 1 ? "y" : "ies"}` : ""
  }`;
  return (
    <span
      data-testid="redteam-chip"
      className={`rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${tone}`}
    >
      {label}
    </span>
  );
}

// TRUE when the redteam record is the ALARMING kind (fatal_flaw or retries
// spent) — the state that earns the row's single alarm slot. A clean
// proceed/0 pass (and a boundary NaN/negative retries count, which `> 0`
// rejects) is quiet and lives in the modal only.
export function redteamAlarm(redteam: IterationRecord["redteam"]): boolean {
  if (!redteam || typeof redteam !== "object") return false;
  if (redteam.verdict === "fatal_flaw") return true;
  const retries = redteam.retries_used;
  return typeof retries === "number" && retries > 0;
}

// Derive the Verdict=YES|NO chip text from the producer's own summary line
// ("Verdict=YES. …" / "VCG verdict=YES. …" — the exp001/exp003/exp004 shape in
// docs/DATA_SHAPES.md). The verdict is rendered ONLY when the summary literally
// states it; an outcome without a verdict line gets the quiet "experiment"
// marker — never a fabricated verdict.
export function experimentVerdict(
  outcome: IterationRecord["experiment_outcome"],
): "YES" | "NO" | null {
  if (outcome == null || typeof outcome !== "object" || Array.isArray(outcome)) {
    return null;
  }
  const summary = (outcome as { summary?: unknown }).summary;
  if (typeof summary !== "string") return null;
  const m = summary.match(/verdict\s*=\s*(YES|NO)\b/i);
  return m ? (m[1].toUpperCase() as "YES" | "NO") : null;
}

// experiment_outcome chip (handoff Task 4 alarm slot / Task 6): emerald for a
// stated Verdict=YES, red for Verdict=NO, quiet zinc when the outcome carries
// no verdict line. Scalar-guard idiom on metric/value (value may legitimately
// be an OBJECT for multi-metric outcomes — only a usable scalar reaches the
// title; mirrors Experiments.tsx bridgeLabel).
export function ExperimentChip({
  outcome,
}: {
  outcome: IterationRecord["experiment_outcome"];
}) {
  if (outcome == null || typeof outcome !== "object" || Array.isArray(outcome)) {
    return null;
  }
  const verdict = experimentVerdict(outcome);
  const tone =
    verdict === "YES"
      ? "bg-emerald-950 text-emerald-400"
      : verdict === "NO"
        ? "bg-red-950 text-red-400"
        : "bg-zinc-800 text-zinc-400";
  const id = asScalar(outcome.experiment_id);
  const metric = asScalar(outcome.metric);
  const value = asScalar(outcome.value); // object value -> "" (multi-metric)
  const titleParts: string[] = [];
  if (id) titleParts.push(id);
  if (metric && value) titleParts.push(`${metric}=${value}`);
  else if (metric) titleParts.push(metric);
  const summary = asScalar(outcome.summary);
  if (summary) titleParts.push(summary);
  return (
    <span
      data-testid="experiment-chip"
      title={titleParts.length > 0 ? titleParts.join(" · ") : undefined}
      className={`rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${tone}`}
    >
      {verdict ? `exp verdict=${verdict}` : "experiment"}
    </span>
  );
}

// loop_memory.jsonl is producer-owned; a buggy/legacy row can emit
// meta_review.conditioning_bullets as a bare string (not a list) or with junk
// entries (null, numbers, objects). A non-array used to crash the whole list
// via `.map`, and a raw-object entry crashes React's child renderer. Return
// only the string bullets so one bad row degrades to "no bullets" instead of
// blanking the page.
export function conditioningBullets(row: IterationRecord): string[] {
  const bullets = row.meta_review?.conditioning_bullets;
  if (!Array.isArray(bullets)) return [];
  return bullets.filter((b): b is string => typeof b === "string");
}

// seed.topic is likewise producer-owned: coerce a non-string topic to a safe
// string so neither the topic filter (`.toLowerCase()`) nor the row render
// throws on a malformed row.
export function seedTopic(row: IterationRecord): string {
  const topic = row.seed?.topic;
  return typeof topic === "string" ? topic : "";
}

// ended_at is producer-owned: a legacy/buggy row can emit it as a number
// (epoch), object, or garbage rather than an ISO string. `.replace` then
// throws ("iso.replace is not a function") and crashes the whole row. Treat a
// non-string as no-timestamp ("—") rather than throwing; a string passes
// through unchanged.
export function shortTimestamp(iso: unknown): string {
  if (typeof iso !== "string" || !iso) return "—";
  return iso.replace("T", " ").replace("Z", "");
}

// ---------------------------------------------------------------------------
// Modal internals
// ---------------------------------------------------------------------------

// One labeled section in the pinned order. The testid is the section anchor
// the tests (and the integrator) address.
function Section({
  title,
  testid,
  children,
}: {
  title: string;
  testid: string;
  children: React.ReactNode;
}) {
  return (
    <section
      data-testid={testid}
      className="border-t border-zinc-800/60 px-4 py-3"
    >
      <h3 className="text-[10px] font-medium uppercase tracking-wide text-zinc-500">
        {title}
      </h3>
      <div className="mt-1.5 text-xs text-zinc-300">{children}</div>
    </section>
  );
}

// A quiet "key  value" detail line; renders nothing when the value has no
// usable scalar form (absent on legacy rows → the line is omitted, not faked).
function DetailRow({ k, v }: { k: string; v: unknown }) {
  const text = asScalar(v);
  if (!text) return null;
  return (
    <>
      <span className="text-zinc-500">{k}</span>
      <span className="break-words">{text}</span>
    </>
  );
}

// The override provenance AS VISIBLE TEXT (handoff Task 4 modal section 1 —
// the row keeps tooltip-only). Renders nothing when no usable field exists.
function OverrideProvenance({
  label,
  testid,
  block,
}: {
  label: string;
  testid: string;
  block:
    | {
        verdict_overridden_from?: unknown;
        override_reason?: unknown;
        skeptic_verdict?: unknown;
      }
    | null
    | undefined;
}) {
  if (block == null || typeof block !== "object") return null;
  const from = badgeText(
    block.verdict_overridden_from as string | null | undefined,
  );
  const reason = badgeText(block.override_reason as string | null | undefined);
  const skeptic = badgeText(block.skeptic_verdict as string | null | undefined);
  if (!from && !reason && !skeptic) return null;
  return (
    <div
      data-testid={testid}
      className="mt-1.5 rounded border border-amber-900/40 bg-amber-950/20 px-2 py-1 text-[11px] text-amber-200/90"
    >
      <div className="text-[10px] uppercase tracking-wide text-amber-500/90">
        {label} override
      </div>
      {from && (
        <div>
          overridden from <span className="font-mono">{from}</span>
        </div>
      )}
      {reason && <div>reason: {reason}</div>}
      {skeptic && (
        <div>
          skeptic said <span className="font-mono">{skeptic}</span>
        </div>
      )}
    </div>
  );
}

// First usable wrapper call id → the /chain/req/<id> inspector target.
function firstWrapperCallId(row: IterationRecord): string | null {
  const ids = row.wrapper_call_ids;
  if (!Array.isArray(ids)) return null;
  const first = ids.find((v) => typeof v === "string" && v.trim().length > 0);
  return first ?? null;
}

// The low-evidence detail INLINE (what LowEvidenceBadge's tooltip says),
// composed from the same relevance fields the badge reads.
function lowEvidenceDetail(row: IterationRecord): string {
  const relevance = row.retrieval?.relevance;
  const parts: string[] = [];
  if (relevance?.low_confidence === true) {
    const why =
      typeof relevance.reason === "string" && relevance.reason.trim()
        ? relevance.reason
        : null;
    parts.push(
      why
        ? `retrieval flagged low-confidence — ${why}`
        : "retrieval flagged low-confidence",
    );
  }
  if (
    Array.isArray(row.retrieval?.neighbors) &&
    row.retrieval!.neighbors!.length === 0
  ) {
    parts.push("0 retrieved neighbors");
  }
  const category = asScalar(relevance?.category);
  if (category) parts.push(`category: ${category}`);
  const ruleFired = asScalar(relevance?.rule_fired);
  if (ruleFired) parts.push(`rule: ${ruleFired}`);
  const why = parts.length ? parts.join("; ") : "thin / off-domain retrieval";
  return `Low-evidence verdict: ${why}. The verdict rests on thin or off-domain retrieval — eyeball before trusting.`;
}

interface Props {
  row: IterationRecord;
  onClose: () => void;
}

export default function IterationDetailModal({ row, onClose }: Props) {
  const dialogRef = useRef<HTMLDialogElement | null>(null);

  // Native modal open on mount. The parent mounts this component only while
  // open, so a single showModal() per mount is the whole lifecycle.
  useEffect(() => {
    const d = dialogRef.current;
    if (d && !d.open) d.showModal();
  }, []);

  // The coordinator cycle whose dispatched_iteration_id matches this
  // iteration (links section). GUARDED: a 404/older backend, a missing mock,
  // or a malformed body all degrade to "no cycle link" — never a red state
  // inside the modal (the Task-2 skew stance).
  const [cycleRunId, setCycleRunId] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const r = await getCoordinatorCycles();
        const cycles = Array.isArray(r?.cycles) ? r.cycles : [];
        const match = cycles.find(
          (c) =>
            c != null &&
            typeof c === "object" &&
            c.dispatched_iteration_id === row.iteration_id,
        );
        if (active && match) {
          setCycleRunId(typeof match.run_id === "string" ? match.run_id : "");
        }
      } catch {
        /* endpoint absent/unreachable — no cycle link */
      }
    })();
    return () => {
      active = false;
    };
  }, [row.iteration_id]);

  // Journal mounts LAZILY on first disclosure-open: avoids a duplicate
  // journal-scroll surface when the Dashboard's inline JournalScroll is
  // already showing this iteration, and avoids fetching for a modal the
  // human only glances at.
  const [journalOpen, setJournalOpen] = useState(false);

  const close = () => {
    const d = dialogRef.current;
    if (d?.open) d.close();
  };

  const bullets = conditioningBullets(row);
  const relevance = row.retrieval?.relevance;
  const outcome =
    row.experiment_outcome != null &&
    typeof row.experiment_outcome === "object" &&
    !Array.isArray(row.experiment_outcome)
      ? row.experiment_outcome
      : null;
  const expId = asScalar(outcome?.experiment_id);
  const chainId = firstWrapperCallId(row);
  const hypothesis =
    row.hypothesis != null && typeof row.hypothesis === "object"
      ? row.hypothesis
      : null;
  const candidates = hypothesis?.candidates_considered;
  // experiment_outcome.value is scalar OR object (multi-metric); only a
  // usable scalar renders as "value" — an object renders its own scalar
  // entries instead (never "[object Object]").
  const scalarValue = asScalar(outcome?.value);
  const objectValueEntries =
    outcome?.value != null &&
    typeof outcome.value === "object" &&
    !Array.isArray(outcome.value)
      ? Object.entries(outcome.value as Record<string, unknown>)
          .map(([k, v]) => [k, asScalar(v)] as const)
          .filter(([, v]) => v !== "")
      : [];

  return (
    <dialog
      ref={dialogRef}
      data-testid="iteration-detail-modal"
      aria-label={`iteration detail ${row.iteration_id}`}
      onClose={onClose}
      onKeyDown={(e) => {
        // Esc closes. Browsers also fire the native cancel→close pair; the
        // close() here is what makes the path testable under jsdom. The
        // open-guard inside close() keeps the two paths from double-firing.
        if (e.key === "Escape") {
          e.preventDefault();
          close();
        }
      }}
      onClick={(e) => {
        // Backdrop click: with p-0 on the dialog and all content inside the
        // padded wrapper, a click whose target is the <dialog> element itself
        // can only be the backdrop (::backdrop clicks target the dialog).
        if (e.target === dialogRef.current) close();
      }}
      className="m-auto max-h-[85vh] w-[min(64rem,92vw)] overflow-y-auto rounded border border-zinc-700 bg-zinc-950 p-0 text-zinc-200 backdrop:bg-black/60"
    >
      {/* ── 1. Verdict header — full badge set + override provenance as text */}
      <div data-testid="modal-verdict-header" className="px-4 py-3">
        <div className="flex flex-wrap items-baseline gap-2 text-xs">
          <span className="font-mono text-zinc-100">{row.iteration_id}</span>
          <Badge
            text={row.novelty?.class}
            tone={toneFor(
              NOVELTY_TONE,
              row.novelty?.class,
              "bg-zinc-800 text-zinc-400",
            )}
            title={overrideTooltip(row.novelty)}
          />
          <NoveltyAxesChip axes={row.novelty?.novelty_axes} />
          <Badge
            text={row.critique?.verdict}
            tone={toneFor(
              VERDICT_TONE,
              row.critique?.verdict,
              "bg-zinc-800 text-zinc-400",
            )}
            title={overrideTooltip(row.critique)}
          />
          <RedteamChip redteam={row.redteam} />
          <Badge
            text={row.gate_status}
            tone={toneFor(GATE_TONE, row.gate_status, "")}
          />
          <Badge
            text={processLabel(row.process_status)}
            tone={processTone(row.process_status)}
          />
          {/* Provenance for EVERY source — the row shows only the nemoclaw β
              signal; the full origin story reads here. */}
          <SourceBadge source={row.seed?.source} />
          <LowEvidenceBadge record={row} />
          <ExperimentChip outcome={row.experiment_outcome} />
          <span className="ml-auto flex items-center gap-2">
            <span className="font-mono text-[10px] text-zinc-500">
              {shortTimestamp(row.ended_at)}
            </span>
            <button
              type="button"
              aria-label="close iteration detail"
              onClick={close}
              className="rounded border border-zinc-700 bg-zinc-900 px-1.5 py-0.5 text-[11px] text-zinc-300 hover:border-zinc-500"
            >
              ✕ close
            </button>
          </span>
        </div>
        {seedTopic(row) && (
          <div className="mt-1.5 text-sm text-zinc-200">{seedTopic(row)}</div>
        )}
        <OverrideProvenance
          label="novelty"
          testid="modal-override-novelty"
          block={row.novelty}
        />
        <OverrideProvenance
          label="critique"
          testid="modal-override-critique"
          block={row.critique}
        />
      </div>

      {/* ── 2. Hypothesis */}
      <Section title="hypothesis" testid="modal-hypothesis">
        {asScalar(hypothesis?.text) ? (
          <p className="leading-relaxed">{asScalar(hypothesis?.text)}</p>
        ) : (
          <p className="text-zinc-500">no hypothesis text on this row</p>
        )}
        <div className="mt-1.5 flex flex-wrap items-baseline gap-2 text-[11px] text-zinc-400">
          {asScalar(row.seed?.source) && (
            <span className="flex items-baseline gap-1">
              source <SourceBadge source={row.seed?.source} />
            </span>
          )}
          {typeof candidates === "number" && Number.isFinite(candidates) && (
            <span data-testid="modal-candidates">
              candidates considered: {candidates}
            </span>
          )}
        </div>
      </Section>

      {/* ── 3. Evidence */}
      <Section title="evidence" testid="modal-evidence">
        {relevance != null &&
        typeof relevance === "object" &&
        !Array.isArray(relevance) ? (
          <div className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 font-mono text-[11px]">
            <DetailRow k="relevance" v={relevance.relevance} />
            <DetailRow k="category" v={relevance.category} />
            <DetailRow k="rule_fired" v={relevance.rule_fired} />
            <DetailRow k="topicality" v={relevance.topicality} />
            <DetailRow k="anchor_cosine" v={relevance.anchor_cosine} />
            <DetailRow k="curated_overlap" v={relevance.curated_overlap} />
            <DetailRow k="neighbor_spread" v={relevance.neighbor_spread} />
            <DetailRow k="reason" v={relevance.reason} />
          </div>
        ) : (
          <p className="text-zinc-500">
            no retrieval.relevance block (pre-2026-06-09 row)
          </p>
        )}
        <div className="mt-2 flex flex-wrap items-baseline gap-2">
          <NoveltyAxesChip axes={row.novelty?.novelty_axes} />
        </div>
        {asScalar(row.novelty?.rationale) && (
          <p className="mt-1.5 leading-relaxed text-zinc-400">
            {asScalar(row.novelty?.rationale)}
          </p>
        )}
        {isLowEvidence(row) && (
          <div
            data-testid="modal-low-evidence-detail"
            className="mt-2 rounded border border-amber-900/50 bg-amber-950/20 px-2 py-1.5 text-[11px] text-amber-200/90"
          >
            <LowEvidenceBadge record={row} />
            <p className="mt-1">{lowEvidenceDetail(row)}</p>
          </div>
        )}
      </Section>

      {/* ── 4. Adversarial record */}
      <Section title="adversarial record" testid="modal-adversarial">
        {row.critique != null && typeof row.critique === "object" ? (
          <div className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 text-[11px]">
            <DetailRow k="critique rationale" v={row.critique.rationale} />
            <DetailRow
              k="contradicting paper"
              v={row.critique.contradicting_paper_id}
            />
            <DetailRow k="skeptic verdict" v={row.critique.skeptic_verdict} />
          </div>
        ) : (
          <p className="text-zinc-500">no critique block on this row</p>
        )}
        {row.redteam != null && typeof row.redteam === "object" && (
          <div className="mt-2">
            <RedteamChip redteam={row.redteam} />
            <div className="mt-1 grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 text-[11px]">
              <DetailRow k="redteam critique" v={row.redteam.critique} />
              <DetailRow
                k="suggested revision"
                v={row.redteam.suggested_revision}
              />
              <DetailRow k="confidence" v={row.redteam.confidence} />
              <DetailRow k="retries used" v={row.redteam.retries_used} />
            </div>
          </div>
        )}
      </Section>

      {/* ── 5. Conditioning bullets (the meta_review block that left the row;
             same testid the row carried so the moved-scope tests read 1:1) */}
      <Section title="conditioned by" testid="modal-conditioning">
        {bullets.length > 0 ? (
          <div
            data-testid={`conditioning-${row.iteration_id}`}
            className="rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1"
          >
            <ul className="list-disc space-y-0.5 pl-4 text-[11px] text-zinc-400">
              {bullets.map((bullet, i) => (
                <li key={i}>{bullet}</li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="text-zinc-500">no conditioning bullets on this row</p>
        )}
      </Section>

      {/* ── 6. Experiment outcome (only when the bridge block exists) */}
      {outcome && (
        <Section title="experiment outcome" testid="modal-experiment-outcome">
          <div className="flex flex-wrap items-baseline gap-2">
            <ExperimentChip outcome={row.experiment_outcome} />
          </div>
          <div className="mt-1.5 grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 font-mono text-[11px]">
            <DetailRow k="experiment" v={outcome.experiment_id} />
            <DetailRow k="metric" v={outcome.metric} />
            {scalarValue && <DetailRow k="value" v={outcome.value} />}
            {!scalarValue &&
              objectValueEntries.map(([k, v]) => (
                <DetailRow key={k} k={`value.${k}`} v={v} />
              ))}
            <DetailRow k="trials" v={outcome.trials} />
            <DetailRow k="results" v={outcome.results_path} />
          </div>
          {asScalar(outcome.summary) && (
            <p className="mt-1.5 text-[11px] leading-relaxed text-zinc-400">
              {asScalar(outcome.summary)}
            </p>
          )}
        </Section>
      )}

      {/* ── 7. Gate panel — status + the integrator's attestation slot + the
             copy-paste CLI fallback (the Task-3 degradation path) */}
      <Section title="gate" testid="modal-gate-panel">
        <div className="flex flex-wrap items-baseline gap-2">
          <span className="text-zinc-500">gate_status</span>
          {badgeText(row.gate_status) ? (
            <Badge
              text={row.gate_status}
              tone={toneFor(GATE_TONE, row.gate_status, "bg-zinc-800 text-zinc-400")}
            />
          ) : (
            <span className="text-zinc-500">— (pre-v1 row, no gate)</span>
          )}
        </div>
        {/* Task-3 write-back seam: the form self-gates on the capability
            handshake and renders its own degrade note when unavailable; the
            modal supplies the copy-paste CLI fallback below. */}
        <div
          data-attest-slot="gate"
          data-iteration-id={row.iteration_id}
          className="mt-2"
        >
          <GateVerdictForm iterationId={row.iteration_id} />
        </div>
        <details className="mt-2 rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1">
          <summary className="cursor-pointer text-[11px] text-zinc-400">
            CLI fallback — resolve this gate from a terminal
          </summary>
          <code
            data-testid="modal-gate-cli"
            className="mt-1 block overflow-x-auto whitespace-pre rounded bg-zinc-950 px-2 py-1 font-mono text-[11px] text-zinc-300"
          >
            {`.venv-chroma/bin/python -m orchestrator.gate_cli --iteration-id ${row.iteration_id} --verdict <valid|invalid|needs_revision> --note '<why>'`}
          </code>
        </details>
      </Section>

      {/* ── 8. Links */}
      <Section title="links" testid="modal-links">
        <details
          data-testid="modal-journal"
          onToggle={(e) =>
            setJournalOpen((e.target as HTMLDetailsElement).open)
          }
          className="rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1"
        >
          <summary className="cursor-pointer text-[11px] text-zinc-400">
            journal entry
          </summary>
          {journalOpen && <JournalScroll iterationId={row.iteration_id} />}
        </details>
        <div className="mt-2 flex flex-wrap gap-3 text-[11px]">
          {chainId && (
            <Link
              data-testid="modal-chain-link"
              to={`/chain/req/${encodeURIComponent(chainId)}`}
              className="text-sky-300 underline hover:text-sky-200"
            >
              call chain {chainId.slice(0, 8)}…
            </Link>
          )}
          {expId && (
            <Link
              data-testid="modal-experiment-link"
              to={`/experiments/${encodeURIComponent(expId)}`}
              className="text-sky-300 underline hover:text-sky-200"
            >
              experiment {expId}
            </Link>
          )}
          {cycleRunId !== null && (
            <Link
              data-testid="modal-cycle-link"
              to="/coordinator"
              className="text-sky-300 underline hover:text-sky-200"
            >
              coordinator cycle {cycleRunId || "(unnamed run)"}
            </Link>
          )}
        </div>
      </Section>
    </dialog>
  );
}
