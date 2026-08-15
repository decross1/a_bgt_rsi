// PipelineJourney — the dossier reader's read-only JOURNEY spine.
//
// R2 (2026-08-15, "the Dossier is WAY too much text") REBUILT the presentation
// on progressive disclosure, WITHOUT touching a single seam:
//   - a sticky SUBWAY-MAP stepper (JourneyStepper) over eight stations —
//     hypothesis · retrieval · relevance · novelty · critic · red-team ·
//     experiment · verdict — each node colored by that step's REAL outcome
//     (journeyStations.stationsFor), the in-view section marked by scrollspy,
//     a click scrolling to its section;
//   - every section COLLAPSED to one verdict line by default (status glyph +
//     label + the station summary + a chevron). Prose, quotes and raw evidence
//     appear only on expand; expansion lives in component state (per section,
//     never localStorage);
//   - the heavy RAW EVIDENCE — retrieved chunk texts, the full critic and
//     red-team prose, the experiment trial/results block — drills into the R0
//     PeekPanel instead of inlining.
// It still NEVER recommends and NEVER writes: the verdict path is the reader's
// disposition footer, untouched by this file.
//
// (Pre-R2 this surface was the same data behind a flat PipelineRibbon + eight
// always-open sections. The ribbon's `data-reached` semantics survive on the
// stepper stations; the sections kept their `journey-*` testids so every
// absorbed-modal invariant reads 1:1.)
//
// ABSORBED from IterationDetailModal (UI simplification S2 — the modal died;
// every unique section moved HERE, per the plan's absorption table):
//   - the VERDICT HEADER badge row (full chip set, always visible — chips, not
//     prose: it is the 15-second summary R2 is built around);
//   - the override provenance for novelty / critique as VISIBLE text, now
//     living in the novelty / critic sections (with the step it explains);
//   - NoveltyAxesChip + the FULL evidence grid + the low-evidence detail;
//   - the redteam adversarial detail; conditioning bullets (with hypothesis,
//     which they primed); experiment extras; hypothesis.candidates_considered;
//   - the LAZY journal disclosure + the links section.
// GateVerdictForm is NOT absorbed — the reader's disposition footer owns the
// forms (the verdict fence).
//
// TWO ITEM FAMILIES (both resolve to ONE iteration's journey):
//   - gate_verdict (ITERATION): item.id IS an iteration_id. Self-fetch
//     getIterationJourney(item.id) → render response.iteration.
//   - finding_review (FINDING): item.id is a finding_id. Self-fetch
//     getFindingDetail(item.id) → read source_iteration_id + the claim, then
//     getIterationJourney(source_iteration_id) → render that iteration's journey
//     with the finding claim surfaced at the top.
//   - any other kind → a quiet "no pipeline journey for this item kind" note.
//
// INJECTION: the `journey` / `detail` props are the test-injection overrides
// (mirrors TutorPanel's `detail` prop). When provided we render them directly
// and DO NOT fetch — these tests never touch the network.
//
// ROBUSTNESS: every field is producer-owned JSONL parsed unchecked — the TS
// types are a compile-time fiction. All scalars render through asText (string
// trims / finite number / boolean stringifies; anything else — object, array,
// NaN, null, undefined — drops by TYPEOF ALONE, no deref, so a raw object never
// reaches React as a child). A missing / null / not-found journey degrades to a
// legible "journey unavailable" state — never a throw, never a blank.
//
// The D-052 advisory (retrieval.relevance.topicality_advisory) is DARK by
// default and surfaces here only as the raw value in a quiet zinc line — NEVER
// with amber / low-evidence styling (it is non-gating; never cry wolf). It
// never colors a station either.
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import type {
  FindingDetail,
  HumanTodoItem,
  IterationJourneyResponse,
  IterationRecord,
} from "../../types/schemas";
import {
  getCoordinatorCycles,
  getFindingDetail,
  getIterationJourney,
} from "../../api/http";
import {
  Badge,
  ExperimentChip,
  GATE_TONE,
  NOVELTY_TONE,
  OverrideProvenance,
  RedteamChip,
  VERDICT_TONE,
  conditioningBullets,
  overrideTooltip,
  processLabel,
  processTone,
  seedTopic,
  shortTimestamp,
  toneFor,
} from "../chips";
import JournalScroll from "../JournalScroll";
import LowEvidenceBadge, { isLowEvidence } from "../LowEvidenceBadge";
import NoveltyAxesChip from "../NoveltyAxesChip";
import SourceBadge from "../SourceBadge";
import TopicalityAdvisoryBadge from "../TopicalityAdvisoryBadge";
import PeekPanel from "../../design/PeekPanel";
import StatusDot from "../../design/StatusDot";
import JourneyStepper from "./JourneyStepper";
import {
  STATION_KEYS,
  asRecord,
  asText,
  stationsFor,
  type Station,
  type StationKey,
} from "./journeyStations";

// One labelled "key: value" line; renders nothing when the value has no usable
// scalar form (absent fields are DROPPED, never faked).
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

// One labelled sub-block inside an expanded section (the IterationDetailModal
// Section idiom — a quiet header + body, addressable by testid).
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
      className="mt-2 border-t border-zinc-800/60 pt-2"
    >
      <h4 className="text-[10px] font-medium uppercase tracking-wide text-zinc-500">
        {title}
      </h4>
      <div className="mt-0.5 text-xs text-zinc-300">{children}</div>
    </section>
  );
}

// A quiet "key  value" grid line (the absorbed modal DetailRow idiom); renders
// nothing when the value has no usable scalar form (absent on legacy rows →
// the line is omitted, not faked).
function DetailRow({ k, v }: { k: string; v: unknown }) {
  const text = asText(v);
  if (!text) return null;
  return (
    <>
      <span className="text-zinc-500">{k}</span>
      <span className="break-words">{text}</span>
    </>
  );
}

// The R2 button that drills raw evidence into the PeekPanel. Quiet, accent-
// colored (a link-like action, never a status color).
function PeekButton({
  testid,
  label,
  onClick,
}: {
  testid: string;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      data-testid={testid}
      onClick={onClick}
      className="mt-1.5 rounded border border-zinc-800 px-1.5 py-0.5 text-[10px] text-sky-300 hover:border-zinc-600 hover:text-sky-200"
    >
      {label} →
    </button>
  );
}

// ── R2: ONE COLLAPSIBLE STATION SECTION ────────────────────────────────────
// Collapsed it is exactly one line: status glyph · label · the station's
// verdict summary · a chevron. The body (prose, grids, peek buttons) mounts
// ONLY when expanded — so the collapsed journey fits on one screen and a
// dossier the human only glances at renders almost nothing.
function JourneySection({
  station,
  testid,
  expanded,
  onToggle,
  registerRef,
  children,
}: {
  station: Station;
  testid: string;
  expanded: boolean;
  onToggle: () => void;
  registerRef: (el: HTMLElement | null) => void;
  children: React.ReactNode;
}) {
  return (
    <section
      ref={registerRef}
      data-testid={testid}
      data-station={station.key}
      data-status={station.status}
      data-reached={station.reached ? "true" : "false"}
      data-expanded={expanded ? "true" : "false"}
      className="border-t border-zinc-800/60"
    >
      <button
        type="button"
        data-testid={`journey-toggle-${station.key}`}
        aria-expanded={expanded}
        onClick={onToggle}
        className="flex w-full items-center gap-2 px-0.5 py-1.5 text-left hover:bg-zinc-900/40"
      >
        <StatusDot
          status={station.status}
          label={`${station.label} ${station.status}`}
        />
        <span className="w-[4.5rem] shrink-0 text-[10px] uppercase tracking-wide text-zinc-500">
          {station.label}
        </span>
        <span
          data-testid={`journey-summary-${station.key}`}
          className="min-w-0 flex-1 truncate text-[11px] text-zinc-300"
        >
          {station.summary}
        </span>
        {station.phase2 ? (
          <span className="shrink-0 text-[9px] uppercase tracking-wide text-zinc-700">
            Phase 2
          </span>
        ) : null}
        <span aria-hidden="true" className="shrink-0 text-[10px] text-zinc-600">
          {expanded ? "⌄" : "›"}
        </span>
      </button>
      {expanded ? (
        <div
          data-testid={`journey-body-${station.key}`}
          className="pb-2 pl-4 text-xs text-zinc-300"
        >
          {children}
        </div>
      ) : null}
    </section>
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
// composed from the same relevance fields the badge reads. (Absorbed from the
// modal verbatim.)
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
  const category = asText(relevance?.category);
  if (category) parts.push(`category: ${category}`);
  const ruleFired = asText(relevance?.rule_fired);
  if (ruleFired) parts.push(`rule: ${ruleFired}`);
  const why = parts.length ? parts.join("; ") : "thin / off-domain retrieval";
  return `Low-evidence verdict: ${why}. The verdict rests on thin or off-domain retrieval — eyeball before trusting.`;
}

// The absorbed modal VERDICT HEADER — the full badge set (novelty class + axes,
// critique verdict, redteam, gate, process, source, low-evidence, topicality
// advisory, experiment chip) + the timestamp + the topic line. R2 keeps it
// ALWAYS VISIBLE: it is a wrapped row of chips, not prose — the densest
// at-a-glance artifact in the dossier. The override provenance moved OUT of
// here into the novelty / critic sections (it is prose, and it belongs with the
// step it explains).
function VerdictHeader({ row }: { row: IterationRecord }) {
  return (
    <div data-testid="journey-verdict-header" className="mt-1.5">
      <div className="flex flex-wrap items-baseline gap-2 text-xs">
        <span className="font-mono text-zinc-100">{asText(row.iteration_id)}</span>
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
        {/* Provenance for EVERY source — the condensed list rows show only the
            nemoclaw β signal; the full origin story reads here. */}
        <SourceBadge source={row.seed?.source} />
        <LowEvidenceBadge record={row} />
        <TopicalityAdvisoryBadge record={row} />
        <ExperimentChip outcome={row.experiment_outcome} />
        <span className="ml-auto font-mono text-[10px] text-zinc-500">
          {shortTimestamp(row.ended_at)}
        </span>
      </div>
      {seedTopic(row) && (
        <div className="mt-1.5 text-sm text-zinc-200">{seedTopic(row)}</div>
      )}
    </div>
  );
}

// The absorbed modal LINKS section — the lazy journal disclosure + the deep
// links out of the dossier: the wrapper call chain, the experiment page, and
// the coordinator cycle whose dispatched_iteration_id matches. The cycle-join
// fetch is GUARDED: a 404/older backend, a missing mock, or a malformed body
// all degrade to "no cycle link" — never a red state inside the journey.
function JourneyLinks({ row }: { row: IterationRecord }) {
  const iterationId = asText(row.iteration_id);

  const [cycleRunId, setCycleRunId] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    setCycleRunId(null);
    (async () => {
      try {
        const r = await getCoordinatorCycles();
        const cycles = Array.isArray(r?.cycles) ? r.cycles : [];
        const match = cycles.find(
          (c) =>
            c != null &&
            typeof c === "object" &&
            c.dispatched_iteration_id === iterationId,
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
  }, [iterationId]);

  // Journal mounts LAZILY on first disclosure-open: avoids fetching for a
  // dossier the human only glances at (the absorbed modal contract).
  const [journalOpen, setJournalOpen] = useState(false);

  const outcome = asRecord(row.experiment_outcome);
  const expId = asText(outcome?.experiment_id);
  const chainId = firstWrapperCallId(row);

  return (
    <Section title="journal + links" testid="journey-links">
      {iterationId.length > 0 ? (
        <details
          data-testid="journey-journal"
          onToggle={(e) => setJournalOpen((e.target as HTMLDetailsElement).open)}
          className="rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1"
        >
          <summary className="cursor-pointer text-[11px] text-zinc-400">
            journal entry
          </summary>
          {journalOpen && <JournalScroll iterationId={iterationId} />}
        </details>
      ) : null}
      <div className="mt-2 flex flex-wrap gap-3 text-[11px]">
        {chainId && (
          <Link
            data-testid="journey-chain-link"
            to={`/chain/req/${encodeURIComponent(chainId)}`}
            className="text-sky-300 underline hover:text-sky-200"
          >
            call chain {chainId.slice(0, 8)}…
          </Link>
        )}
        {expId && (
          <Link
            data-testid="journey-experiment-link"
            to={`/experiments/${encodeURIComponent(expId)}`}
            className="text-sky-300 underline hover:text-sky-200"
          >
            experiment {expId}
          </Link>
        )}
        {cycleRunId !== null && (
          <Link
            data-testid="journey-cycle-link"
            to="/cycles"
            className="text-sky-300 underline hover:text-sky-200"
          >
            coordinator cycle {cycleRunId || "(unnamed run)"}
          </Link>
        )}
      </div>
    </Section>
  );
}

// ── R2 PEEK BODIES — the heavy raw evidence, drilled into the R0 PeekPanel ──
// Every value rides the same asText/asRecord guard as the inline surfaces: a
// hostile producer field DROPS rather than reaching React as a child.

type PeekKind = "chunks" | "critic" | "redteam" | "trials";

const PEEK_TITLE: Record<PeekKind, string> = {
  chunks: "retrieved chunks",
  critic: "critic — full text",
  redteam: "red-team — full text",
  trials: "experiment trials",
};

// One retrieved neighbor: an id-ish scalar plus whatever chunk text the
// producer carried. A neighbor may be a bare id string OR an object; entries
// with no usable scalar at all are dropped rather than rendered empty.
function ChunksPeek({ neighbors }: { neighbors: unknown[] }) {
  const rows = neighbors
    .map((n) => {
      const direct = asText(n);
      const obj = asRecord(n);
      const id =
        direct ||
        (obj !== null
          ? asText(obj.id) ||
            asText(obj.doc_id) ||
            asText(obj.chunk_id) ||
            asText(obj.paper_id) ||
            asText(obj.iteration_id)
          : "");
      const text =
        obj !== null
          ? asText(obj.text) ||
            asText(obj.chunk) ||
            asText(obj.content) ||
            asText(obj.snippet)
          : "";
      const score =
        obj !== null ? asText(obj.score) || asText(obj.distance) : "";
      return { id, text, score };
    })
    .filter((r) => r.id.length > 0 || r.text.length > 0);

  return (
    <div data-testid="peek-chunks">
      {rows.length === 0 ? (
        <p className="text-[11px] text-zinc-500">
          no retrieved chunk text on this row
        </p>
      ) : (
        <ol className="space-y-2">
          {rows.map((r, i) => (
            <li
              key={i}
              data-testid={`peek-chunk-${i}`}
              className="rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1.5"
            >
              <div className="flex items-baseline gap-2">
                <span className="font-mono text-[11px] text-zinc-300">
                  {r.id || "(unnamed chunk)"}
                </span>
                {r.score.length > 0 ? (
                  <span className="font-mono text-[10px] text-zinc-500">
                    {r.score}
                  </span>
                ) : null}
              </div>
              {r.text.length > 0 ? (
                <p className="mt-1 whitespace-pre-wrap text-[11px] leading-relaxed text-zinc-400">
                  {r.text}
                </p>
              ) : (
                <p className="mt-1 text-[10px] text-zinc-600">
                  id only — the producer carried no chunk text
                </p>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function CriticPeek({ row }: { row: IterationRecord }) {
  const critique = asRecord(row.critique);
  const rationale = asText(critique?.rationale);
  const skeptic = asText(critique?.skeptic_verdict);
  const contradicting = asText(critique?.contradicting_paper_id);
  return (
    <div data-testid="peek-critic" className="space-y-2 text-[11px]">
      {rationale.length > 0 ? (
        <p className="whitespace-pre-wrap leading-relaxed text-zinc-300">
          {rationale}
        </p>
      ) : (
        <p className="text-zinc-500">no critic rationale on this row</p>
      )}
      {contradicting.length > 0 ? (
        <div className="text-zinc-400">
          <span className="text-[10px] uppercase tracking-wide text-zinc-600">
            contradicting paper
          </span>{" "}
          <span className="font-mono text-zinc-300">{contradicting}</span>
        </div>
      ) : null}
      {skeptic.length > 0 ? (
        <div className="text-zinc-400">
          <span className="text-[10px] uppercase tracking-wide text-zinc-600">
            skeptic verdict
          </span>{" "}
          <span className="font-mono text-zinc-300">{skeptic}</span>
        </div>
      ) : null}
    </div>
  );
}

function RedteamPeek({ row }: { row: IterationRecord }) {
  const redteam = asRecord(row.redteam);
  const critique = asText(redteam?.critique);
  const revision = asText(redteam?.suggested_revision);
  return (
    <div data-testid="peek-redteam" className="space-y-2 text-[11px]">
      {critique.length > 0 ? (
        <div>
          <div className="text-[10px] uppercase tracking-wide text-zinc-600">
            red-team critique
          </div>
          <p className="mt-0.5 whitespace-pre-wrap leading-relaxed text-zinc-300">
            {critique}
          </p>
        </div>
      ) : null}
      {revision.length > 0 ? (
        <div>
          <div className="text-[10px] uppercase tracking-wide text-zinc-600">
            suggested revision
          </div>
          <p className="mt-0.5 whitespace-pre-wrap leading-relaxed text-zinc-300">
            {revision}
          </p>
        </div>
      ) : null}
      {critique.length === 0 && revision.length === 0 ? (
        <p className="text-zinc-500">no red-team prose on this row</p>
      ) : null}
    </div>
  );
}

function TrialsPeek({ row }: { row: IterationRecord }) {
  const outcome = asRecord(row.experiment_outcome);
  const trials = asText(outcome?.trials);
  const resultsPath = asText(outcome?.results_path);
  // A multi-metric OBJECT value renders its own scalar entries as a table —
  // never "[object Object]"; junk sub-values drop.
  const entries =
    outcome?.value != null &&
    typeof outcome.value === "object" &&
    !Array.isArray(outcome.value)
      ? Object.entries(outcome.value as Record<string, unknown>)
          .map(([k, v]) => [k, asText(v)] as const)
          .filter(([, v]) => v !== "")
      : [];
  const scalarValue = asText(outcome?.value);

  return (
    <div data-testid="peek-trials" className="space-y-2 text-[11px]">
      <div className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 font-mono">
        <DetailRow k="experiment" v={outcome?.experiment_id} />
        <DetailRow k="metric" v={outcome?.metric} />
        {scalarValue.length > 0 ? (
          <DetailRow k="value" v={outcome?.value} />
        ) : null}
        {entries.map(([k, v]) => (
          <DetailRow key={k} k={`value.${k}`} v={v} />
        ))}
        <DetailRow k="trials" v={outcome?.trials} />
        <DetailRow k="results" v={outcome?.results_path} />
      </div>
      {trials.length === 0 && resultsPath.length === 0 ? (
        <p className="text-zinc-500">
          no trial count or results path on this row
        </p>
      ) : null}
      <p className="text-[10px] text-zinc-600">
        read the results file for the per-trial rows — the loop row carries the
        summary, not the table.
      </p>
    </div>
  );
}

interface Props {
  /** The SELECTED cockpit item. `item.id` is an iteration_id for gate_verdict
   *  items, a finding_id for finding_review items. */
  item: HumanTodoItem;
  /** Injected journey — when provided, wins and SUPPRESSES the self-fetch.
   *  Test-injection / preview override (mirrors TutorPanel's `detail`). */
  journey?: IterationJourneyResponse;
  /** Injected finding detail (finding_review family) — when provided, wins and
   *  SUPPRESSES the getFindingDetail self-fetch. */
  detail?: FindingDetail;
}

// Map an item.kind to a family. gate_verdict → iteration; finding_review →
// finding; anything else → other (a quiet note).
function familyOf(kind: unknown): "iteration" | "finding" | "other" {
  if (kind === "gate_verdict") return "iteration";
  if (kind === "finding_review") return "finding";
  return "other";
}

export default function PipelineJourney({ item, journey, detail }: Props) {
  const itemObj = asRecord(item);
  const kind = itemObj?.kind;
  const family = familyOf(kind);
  const itemId = asText(itemObj?.id);

  // FINDING family: resolve the source iteration id + claim from the finding
  // detail (injected `detail` wins, else self-fetch getFindingDetail(itemId)).
  const [fetchedDetail, setFetchedDetail] = useState<FindingDetail | null>(null);
  const [detailFailed, setDetailFailed] = useState(false);
  useEffect(() => {
    // Only the finding family fetches a detail; injected detail suppresses it.
    if (family !== "finding") return;
    if (detail !== undefined) return;
    if (itemId.length === 0) return;
    let live = true;
    setFetchedDetail(null);
    setDetailFailed(false);
    getFindingDetail(itemId)
      .then((d) => {
        if (live) setFetchedDetail(d);
      })
      .catch(() => {
        if (live) setDetailFailed(true);
      });
    return () => {
      live = false;
    };
  }, [family, detail, itemId]);

  const resolvedDetail: FindingDetail | null =
    detail !== undefined ? detail : fetchedDetail;
  const detailObj = asRecord(resolvedDetail);
  const detailUsable = detailObj !== null && detailObj.found === true;
  const findingClaim = detailUsable
    ? asText(detailObj.claim) || asText(detailObj.title)
    : "";

  // The iteration id whose journey we render. For the iteration family that is
  // item.id directly; for the finding family it is the resolved finding's
  // source_iteration_id (from source_iteration_id or source_iteration.iteration_id).
  const sourceIterId =
    family === "finding"
      ? detailUsable
        ? asText(detailObj.source_iteration_id) ||
          asText(asRecord(detailObj.source_iteration)?.iteration_id)
        : ""
      : itemId;

  // Self-fetch the journey for sourceIterId (injected `journey` wins). The
  // finding family waits until its source iteration id is resolved.
  const [fetchedJourney, setFetchedJourney] =
    useState<IterationJourneyResponse | null>(null);
  const [journeyFailed, setJourneyFailed] = useState(false);
  useEffect(() => {
    if (family === "other") return;
    if (journey !== undefined) return;
    if (sourceIterId.length === 0) return;
    let live = true;
    setFetchedJourney(null);
    setJourneyFailed(false);
    getIterationJourney(sourceIterId)
      .then((j) => {
        if (live) setFetchedJourney(j);
      })
      .catch(() => {
        if (live) setJourneyFailed(true);
      });
    return () => {
      live = false;
    };
  }, [family, journey, sourceIterId]);

  const resolvedJourney: IterationJourneyResponse | null =
    journey !== undefined ? journey : fetchedJourney;
  const journeyObj = asRecord(resolvedJourney);
  // The iteration record: only when the response is found:true and carries an
  // object iteration block (a non-object iteration degrades to unavailable).
  const iterationRecord: IterationRecord | null =
    journeyObj !== null && journeyObj.found === true
      ? (asRecord(journeyObj.iteration) as IterationRecord | null)
      : null;

  // ── R2 presentation state (component state only — NEVER localStorage) ──
  // Which sections the human opened, the scrollspy's current station, and the
  // raw-evidence peek. All reset with the component, which the reader remounts
  // per dossier id.
  const [expanded, setExpanded] = useState<Set<StationKey>>(new Set());
  const [activeKey, setActiveKey] = useState<StationKey | null>(null);
  const [peek, setPeek] = useState<PeekKind | null>(null);
  const sectionEls = useRef(new Map<StationKey, HTMLElement>());

  const toggle = (key: StationKey) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const registerRef = (key: StationKey) => (el: HTMLElement | null) => {
    if (el) sectionEls.current.set(key, el);
    else sectionEls.current.delete(key);
  };

  // Clicking a station SCROLLS to its section (and marks it current). It does
  // NOT expand — the chevron owns disclosure, the map owns navigation.
  const goToStation = (key: StationKey) => {
    setActiveKey(key);
    sectionEls.current
      .get(key)
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  // SCROLLSPY — the topmost section inside the reading band becomes the current
  // station. Guarded: jsdom (and any environment without IntersectionObserver)
  // simply gets no scrollspy, and the stepper still navigates by click.
  const loadedId = iterationRecord !== null ? asText(iterationRecord.iteration_id) : "";
  useEffect(() => {
    if (typeof IntersectionObserver !== "function") return;
    const els = Array.from(sectionEls.current.values());
    if (els.length === 0) return;
    const visible = new Set<string>();
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          const key = (e.target as HTMLElement).dataset.station;
          if (key === undefined) continue;
          if (e.isIntersecting) visible.add(key);
          else visible.delete(key);
        }
        const first = STATION_KEYS.find((k) => visible.has(k));
        if (first !== undefined) setActiveKey(first);
      },
      { rootMargin: "-15% 0px -70% 0px", threshold: 0 },
    );
    for (const el of els) io.observe(el);
    return () => io.disconnect();
  }, [loadedId]);

  // Shared chrome — the header renders in EVERY state (other-kind, unavailable,
  // loaded) so the surface never blanks.
  const chrome = (body: React.ReactNode) => (
    <div
      data-testid="pipeline-journey"
      className="rounded border border-zinc-800 bg-zinc-950/40 px-2 py-1.5"
    >
      <div className="text-[10px] uppercase tracking-wide text-zinc-500">
        pipeline journey (read-only)
      </div>
      {body}
    </div>
  );

  // 1) OTHER kind — no pipeline journey for this item kind. Still shows the
  // chrome; degrades quietly.
  if (family === "other") {
    return chrome(
      <div
        data-testid="journey-no-kind"
        className="mt-1 text-[11px] text-zinc-500"
      >
        no pipeline journey for this item kind
        {asText(kind).length > 0 ? (
          <span className="text-zinc-600"> ({asText(kind)})</span>
        ) : null}
      </div>,
    );
  }

  // 2) UNAVAILABLE — the journey could not be resolved: a fetch failure, a
  // found:false response, a non-object iteration, OR (finding family) the
  // finding detail failed / had no source iteration. Degrade in place; never
  // throw, never blank. The stepper still renders (all stations un-reached).
  //
  // `detailFailed` is a FINDING-FAMILY-ONLY signal: only the finding family
  // ever fetches a detail, and its effect early-returns (without resetting the
  // flag) for the iteration family. So it is gated by `family === "finding"`
  // here — otherwise a re-render that switches a SAME-mounted component from a
  // failed finding to a healthy iteration would stay falsely stuck on
  // "journey unavailable" (the stale flag never cleared).
  const unavailable =
    journeyFailed ||
    (family === "finding" && detailFailed) ||
    iterationRecord === null ||
    (family === "finding" && !detailUsable);

  if (unavailable) {
    return chrome(
      <>
        {/* finding family still surfaces the claim if we have it */}
        {family === "finding" && findingClaim.length > 0 ? (
          <div
            data-testid="journey-finding-claim"
            className="mt-1 text-[11px] font-medium text-zinc-300"
          >
            {findingClaim}
          </div>
        ) : null}
        <JourneyStepper
          stations={stationsFor(null)}
          activeKey={null}
          onSelect={() => {}}
        />
        <div
          data-testid="journey-unavailable"
          className="mt-1 text-[11px] text-zinc-500"
        >
          journey unavailable
          {sourceIterId.length > 0 ? (
            <span className="text-zinc-600"> ({sourceIterId})</span>
          ) : itemId.length > 0 ? (
            <span className="text-zinc-600"> ({itemId})</span>
          ) : null}
        </div>
      </>,
    );
  }

  // 3) LOADED — the full journey. For the finding family, surface the claim at
  // the top so the human sees what the iteration produced.
  const row = iterationRecord;
  const stations = stationsFor(row);
  const byKey = (k: StationKey) =>
    stations.find((s) => s.key === k) ?? stations[0];

  const hypothesis = asRecord(row.hypothesis);
  const retrieval = asRecord(row.retrieval);
  const relevance = asRecord(retrieval?.relevance);
  const novelty = asRecord(row.novelty);
  const critique = asRecord(row.critique);
  const redteam = asRecord(row.redteam);
  const outcome = asRecord(row.experiment_outcome);

  // `neighbors` may be a non-array on a malformed row → no preview, no peek.
  const neighbors = Array.isArray(retrieval?.neighbors) ? retrieval!.neighbors : [];
  const neighborPreview = neighbors
    .slice(0, 2)
    .map((n) => {
      const direct = asText(n);
      if (direct.length > 0) return direct;
      const obj = asRecord(n);
      return obj !== null ? asText(obj.id) || asText(obj.iteration_id) : "";
    })
    .filter((s) => s.length > 0);

  // The contradicting-paper line: a non-null id → "contradicted by <id>"; an
  // explicit null (or absent) → "uncontradicted".
  const contradictingId = asText(critique?.contradicting_paper_id);

  // The D-052 advisory raw value — surfaced ONLY when present, quiet zinc,
  // NEVER amber. Absent on every normal row (advisory is dark by default).
  const topicalityAdvisory = asText(relevance?.topicality_advisory);

  // hypothesis.candidates_considered: a finite number only — NaN/garbage drops
  // the line rather than faking a count.
  const candidatesRaw = hypothesis?.candidates_considered;
  const candidates =
    typeof candidatesRaw === "number" && Number.isFinite(candidatesRaw)
      ? candidatesRaw
      : null;

  const bullets = conditioningBullets(row);

  // experiment_outcome.value is scalar OR object (multi-metric); only a usable
  // scalar renders as "value" — an object renders its own scalar entries.
  const scalarValue = asText(outcome?.value);
  const objectValueEntries =
    outcome?.value != null &&
    typeof outcome.value === "object" &&
    !Array.isArray(outcome.value)
      ? Object.entries(outcome.value as Record<string, unknown>)
          .map(([k, v]) => [k, asText(v)] as const)
          .filter(([, v]) => v !== "")
      : [];

  const applied = outcome !== null;

  return chrome(
    <div data-testid="journey-loaded">
      {family === "finding" && findingClaim.length > 0 ? (
        <div
          data-testid="journey-finding-claim"
          className="mt-1 rounded border border-zinc-800/60 bg-zinc-950/40 px-1.5 py-1 text-[11px] font-medium text-zinc-200"
        >
          <span className="text-[10px] uppercase tracking-wide text-zinc-600">
            finding claim{" "}
          </span>
          {findingClaim}
        </div>
      ) : null}

      {/* the absorbed modal VERDICT HEADER — the chip row stays visible; it is
          the 15-second read. */}
      <VerdictHeader row={row} />

      {/* the R2 SUBWAY MAP — sticky under the app header, scrollspy-marked. */}
      <JourneyStepper
        stations={stations}
        activeKey={activeKey}
        onSelect={goToStation}
      />

      <div data-testid="journey-sections">
        {/* ── hypothesis (+ what conditioned it) ── */}
        <JourneySection
          station={byKey("hypothesis")}
          testid="journey-hypothesis"
          expanded={expanded.has("hypothesis")}
          onToggle={() => toggle("hypothesis")}
          registerRef={registerRef("hypothesis")}
        >
          {asText(hypothesis?.text).length > 0 ? (
            <p className="leading-relaxed">{asText(hypothesis?.text)}</p>
          ) : (
            <p className="text-zinc-500">no hypothesis text on this row</p>
          )}
          {candidates !== null ? (
            <div
              data-testid="journey-candidates"
              className="mt-1 text-[11px] text-zinc-400"
            >
              candidates considered: {candidates}
            </div>
          ) : null}
          {/* conditioned by — the meta_review bullets this iteration was primed
              with (absorbed modal section 5; the inner testid keeps the modal's
              conditioning-<id> shape so the moved-scope pins read 1:1). */}
          <Section title="conditioned by" testid="journey-conditioning">
            {bullets.length > 0 ? (
              <div
                data-testid={`conditioning-${asText(row.iteration_id) || "row"}`}
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
        </JourneySection>

        {/* ── retrieval (raw chunk texts drill into the peek) ── */}
        <JourneySection
          station={byKey("retrieval")}
          testid="journey-retrieval"
          expanded={expanded.has("retrieval")}
          onToggle={() => toggle("retrieval")}
          registerRef={registerRef("retrieval")}
        >
          {retrieval !== null ? (
            <>
              <Field label="k" value={retrieval.k} />
              {neighborPreview.length > 0 ? (
                <div
                  data-testid="journey-neighbors"
                  className="mt-1 text-[11px] text-zinc-400"
                >
                  <span className="text-[10px] uppercase tracking-wide text-zinc-600">
                    top neighbors
                  </span>{" "}
                  <span className="font-mono text-zinc-300">
                    {neighborPreview.join(", ")}
                  </span>
                </div>
              ) : null}
              {neighbors.length > 0 ? (
                <PeekButton
                  testid="journey-peek-chunks"
                  label={`raw chunks (${neighbors.length})`}
                  onClick={() => setPeek("chunks")}
                />
              ) : null}
            </>
          ) : (
            <p className="text-zinc-500">no retrieval block on this row</p>
          )}
        </JourneySection>

        {/* ── relevance (the evidence grid + the low-evidence amber lane) ── */}
        <JourneySection
          station={byKey("relevance")}
          testid="journey-relevance"
          expanded={expanded.has("relevance")}
          onToggle={() => toggle("relevance")}
          registerRef={registerRef("relevance")}
        >
          {relevance !== null ? (
            <>
              <Field label="relevance" value={relevance.relevance} />
              <Field label="reason" value={relevance.reason} />
              {/* topicality only if present (the gating field) */}
              <Field label="topicality" value={relevance.topicality} />
              {/* D-052 advisory: quiet zinc, NEVER amber / low-evidence styling */}
              {topicalityAdvisory.length > 0 ? (
                <div
                  data-testid="journey-topicality-advisory"
                  className="mt-1 text-[10px] text-zinc-500"
                >
                  <span className="uppercase tracking-wide text-zinc-600">
                    topicality advisory (non-gating)
                  </span>{" "}
                  <span className="font-mono text-zinc-400">
                    {topicalityAdvisory}
                  </span>
                </div>
              ) : null}
              {/* the FULL evidence diagnostic grid (absorbed modal section 3):
                  the ladder diagnostics beyond the frozen trio. Absent fields
                  omit their line (legacy rows), never fake a value. */}
              <div
                data-testid="journey-evidence-grid"
                className="mt-1.5 grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 font-mono text-[11px]"
              >
                <DetailRow k="category" v={relevance.category} />
                <DetailRow k="rule_fired" v={relevance.rule_fired} />
                <DetailRow k="anchor_cosine" v={relevance.anchor_cosine} />
                <DetailRow k="curated_overlap" v={relevance.curated_overlap} />
                <DetailRow k="neighbor_spread" v={relevance.neighbor_spread} />
              </div>
            </>
          ) : (
            <p className="text-zinc-500">no relevance block on this row</p>
          )}
          {/* the low-evidence detail INLINE (absorbed modal amber box) — only
              when the badge itself would fire; the D-052 advisory above stays
              OUT of this amber lane (non-gating; never cry wolf). */}
          {isLowEvidence(row) && (
            <div
              data-testid="journey-low-evidence-detail"
              className="mt-2 rounded border border-amber-900/50 bg-amber-950/20 px-2 py-1.5 text-[11px] text-amber-200/90"
            >
              <LowEvidenceBadge record={row} />
              <p className="mt-1">{lowEvidenceDetail(row)}</p>
            </div>
          )}
        </JourneySection>

        {/* ── novelty (its override provenance travels with it) ── */}
        <JourneySection
          station={byKey("novelty")}
          testid="journey-novelty"
          expanded={expanded.has("novelty")}
          onToggle={() => toggle("novelty")}
          registerRef={registerRef("novelty")}
        >
          <Field label="rationale" value={novelty?.rationale} />
          {novelty === null ? (
            <p className="text-zinc-500">no novelty block on this row</p>
          ) : null}
          <OverrideProvenance
            label="novelty"
            testid="journey-override-novelty"
            block={row.novelty}
          />
        </JourneySection>

        {/* ── critic (full rationale drills into the peek) ── */}
        <JourneySection
          station={byKey("critic")}
          testid="journey-critic"
          expanded={expanded.has("critic")}
          onToggle={() => toggle("critic")}
          registerRef={registerRef("critic")}
        >
          <div
            data-testid="journey-contradicting-paper"
            className="mt-1 text-[11px] text-zinc-400"
          >
            <span className="text-[10px] uppercase tracking-wide text-zinc-600">
              contradicting paper
            </span>{" "}
            {contradictingId.length > 0 ? (
              <span className="text-zinc-300">
                contradicted by{" "}
                <span className="font-mono">{contradictingId}</span>
              </span>
            ) : (
              <span className="text-zinc-500">uncontradicted</span>
            )}
          </div>
          <Field label="skeptic verdict" value={critique?.skeptic_verdict} />
          {critique === null ? (
            <p className="text-zinc-500">no critique block on this row</p>
          ) : (
            <PeekButton
              testid="journey-peek-critic"
              label="full critic text"
              onClick={() => setPeek("critic")}
            />
          )}
          <OverrideProvenance
            label="critique"
            testid="journey-override-critique"
            block={row.critique}
          />
        </JourneySection>

        {/* ── red-team (the adversarial prose drills into the peek) ── */}
        <JourneySection
          station={byKey("redteam")}
          testid="journey-redteam"
          expanded={expanded.has("redteam")}
          onToggle={() => toggle("redteam")}
          registerRef={registerRef("redteam")}
        >
          {redteam !== null ? (
            <div data-testid="journey-redteam-detail">
              <RedteamChip redteam={row.redteam} />
              <div className="mt-1 grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 text-[11px]">
                <DetailRow k="confidence" v={redteam.confidence} />
                <DetailRow k="retries used" v={redteam.retries_used} />
              </div>
              <PeekButton
                testid="journey-peek-redteam"
                label="full red-team text"
                onClick={() => setPeek("redteam")}
              />
            </div>
          ) : (
            <p className="text-zinc-500">no red-team pass on this row</p>
          )}
        </JourneySection>

        {/* ── experiment (trials + results drill into the peek) ── */}
        <JourneySection
          station={byKey("experiment")}
          testid="journey-experiment"
          expanded={expanded.has("experiment")}
          onToggle={() => toggle("experiment")}
          registerRef={registerRef("experiment")}
        >
          {/* the honest STAGE BANNER — names the tier this iteration actually
              reached (applied vs literature), inferred from experiment_outcome.
              applied = quiet cyan; literature = quiet zinc (never amber — it is
              not a warning, just where the loop is). */}
          <div
            data-testid="journey-stage-banner"
            data-stage={applied ? "applied" : "literature"}
            className={`mt-1 rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${
              applied
                ? "border-cyan-900/60 bg-cyan-950/30 text-cyan-300"
                : "border-zinc-800 bg-zinc-950 text-zinc-500"
            }`}
          >
            {applied ? "applied-tier" : "literature-stage"}
            <span className="ml-1 normal-case tracking-normal text-zinc-600">
              {applied
                ? "— an experiment outcome was bridged in"
                : "— judged on retrieval, not experimentally tested"}
            </span>
          </div>
          {outcome !== null ? (
            <div data-testid="journey-outcome-present">
              <Field label="experiment" value={outcome.experiment_id} />
              <Field label="metric" value={outcome.metric} />
              {/* value: scalar renders as-is; a multi-metric OBJECT renders its
                  own scalar entries (absorbed modal idiom — never
                  "[object Object]", junk sub-values dropped). */}
              {scalarValue.length > 0 ? (
                <Field label="value" value={outcome.value} />
              ) : (
                objectValueEntries.map(([k, v]) => (
                  <Field key={k} label={`value.${k}`} value={v} />
                ))
              )}
              <Field label="summary" value={outcome.summary} />
              <PeekButton
                testid="journey-peek-trials"
                label="trials + results"
                onClick={() => setPeek("trials")}
              />
            </div>
          ) : (
            <p
              data-testid="journey-outcome-placeholder"
              className="text-zinc-600"
            >
              literature-stage — not experimentally tested (Phase 2)
            </p>
          )}
          {/* the HONEST STAGE LABEL — names where this iteration actually got,
              no fabrication. */}
          <div
            data-testid="journey-stage-label"
            className="mt-2 rounded border border-zinc-800/60 bg-zinc-950/40 px-1.5 py-1 text-[10px] leading-snug text-zinc-500"
          >
            <span className="uppercase tracking-wide text-zinc-600">stage</span>{" "}
            {applied
              ? "experiment-bridged — an outcome was recorded (Tier 1/2 bridge)"
              : "literature-stage — judged on retrieval, not experimentally tested (Phase 2)"}
          </div>
        </JourneySection>

        {/* ── verdict (the Step-8 human gate this dossier is about) ── */}
        <JourneySection
          station={byKey("verdict")}
          testid="journey-verdict"
          expanded={expanded.has("verdict")}
          onToggle={() => toggle("verdict")}
          registerRef={registerRef("verdict")}
        >
          <Field label="gate" value={row.gate_status} />
          <Field label="process" value={row.process_status} />
          <Field label="summary" value={row.nara_summary} />
          <p className="mt-1.5 text-[10px] text-zinc-600">
            the verdict itself is recorded in the disposition form below — this
            journey is read-only.
          </p>
        </JourneySection>
      </div>

      {/* the absorbed journal disclosure + deep links out of the dossier. */}
      <JourneyLinks row={row} />

      {/* the R2 RAW-EVIDENCE drill-in (R0 PeekPanel — pure presentation). */}
      <PeekPanel
        open={peek !== null}
        onClose={() => setPeek(null)}
        title={peek !== null ? PEEK_TITLE[peek] : undefined}
      >
        {peek === "chunks" ? <ChunksPeek neighbors={neighbors} /> : null}
        {peek === "critic" ? <CriticPeek row={row} /> : null}
        {peek === "redteam" ? <RedteamPeek row={row} /> : null}
        {peek === "trials" ? <TrialsPeek row={row} /> : null}
      </PeekPanel>
    </div>,
  );
}
