// PipelineJourney — the dossier reader's read-only JOURNEY spine (S2 cockpit
// reframe slice FE2; extended in UI simplification S2 to absorb the retired
// IterationDetailModal's unique sections). It answers "what pipeline produced
// the thing I'm about to resolve?" by replaying the eight loop steps for ONE
// iteration: hypothesis → retrieval → relevance → novelty → critic →
// experiments (Phase-2, greyed) → gate → outcome. It NEVER recommends and NEVER
// writes — the verdict path is elsewhere (the reader's disposition footer);
// this surface only shows the journey, read-only.
//
// ABSORBED from IterationDetailModal (UI simplification S2 — the modal died;
// every unique section moved HERE, per the plan's absorption table):
//   - the VERDICT HEADER badge row (full chip set + override provenance as
//     VISIBLE text, both blocks);
//   - NoveltyAxesChip + the FULL evidence grid (category / rule_fired /
//     topicality_advisory / anchor_cosine / curated_overlap / neighbor_spread)
//     + the low-evidence detail inline (amber box);
//   - the redteam adversarial detail (skeptic_verdict, critique / suggested
//     revision / confidence / retries_used);
//   - conditioning bullets ("conditioned by");
//   - experiment extras (trials, results_path, object-valued value rows);
//   - hypothesis.candidates_considered;
//   - the LAZY journal disclosure (JournalScroll mounts on first open);
//   - the links section (/chain/req/<first wrapper call>, /experiments/<id>,
//     the matching coordinator cycle → /cycles [the S3 route rename — the
//     S2 deviation is resolved]).
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
// with amber / low-evidence styling (it is non-gating; never cry wolf).
import { useEffect, useState } from "react";
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

// The shared scalar guard — the TutorPanel.asText / SourceBadge.asText idiom. A
// string trims; a finite number / boolean stringifies; anything else (object,
// array, NaN, Infinity, null, undefined, bigint, Symbol, a throwing-toString)
// yields "" by TYPEOF ALONE — no property read, deep-deref safe. So a malformed
// row drops the field rather than crashing React with a raw-object child.
function asText(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "";
  if (typeof value === "boolean") return String(value);
  return "";
}

// Re-coerce a typed-but-unvalidated block to a plain record, or null when it is
// a non-object (string / array / number / null). Mirrors TutorPanel's srcObj /
// evObj guard: a non-record degrades to "no block" rather than crashing on a
// property read.
function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

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

// The eight pipeline steps in pinned order. `experiments` is Phase-2 (greyed) —
// the loop is literature-stage today (D-040 not yet at β); the slot is shown so
// the human sees what is NOT yet wired, not hidden.
const STEPS = [
  { key: "hypothesis", label: "hypothesis", phase2: false },
  { key: "retrieval", label: "retrieval", phase2: false },
  { key: "relevance", label: "relevance", phase2: false },
  { key: "novelty", label: "novelty", phase2: false },
  { key: "critic", label: "critic", phase2: false },
  { key: "experiments", label: "experiments", phase2: true },
  { key: "gate", label: "gate", phase2: false },
  { key: "outcome", label: "outcome", phase2: false },
] as const;

// Which steps did THIS iteration actually reach? Each predicate reads only the
// block's presence — a missing block means the row never got there (a pre-v1 row
// or an iteration that halted early), and the ribbon greys that step.
function reachedSteps(row: IterationRecord | null): Record<string, boolean> {
  const r = asRecord(row);
  if (r === null) {
    return Object.fromEntries(STEPS.map((s) => [s.key, false]));
  }
  const relevance = asRecord(asRecord(r.retrieval)?.relevance);
  return {
    hypothesis: asRecord(r.hypothesis) !== null,
    retrieval: asRecord(r.retrieval) !== null,
    relevance: relevance !== null,
    novelty: asRecord(r.novelty) !== null,
    critic: asRecord(r.critique) !== null,
    // experiments is Phase-2: reached only when an outcome was bridged in.
    experiments: asRecord(r.experiment_outcome) !== null,
    gate: asText(r.gate_status).length > 0,
    outcome: asRecord(r.experiment_outcome) !== null,
  };
}

// The pipeline ribbon: the eight steps, each marked reached / not-reached, with
// the experiment step GREYED and Phase-2-labelled regardless of reach.
function PipelineRibbon({ row }: { row: IterationRecord | null }) {
  const reached = reachedSteps(row);
  return (
    <ol
      data-testid="pipeline-ribbon"
      className="flex flex-wrap items-center gap-1 text-[10px]"
    >
      {STEPS.map((step) => {
        const hit = reached[step.key] === true;
        // Phase-2 steps are ALWAYS quiet zinc with the Phase-2 label — they are
        // never lit emerald, the loop hasn't run them.
        const tone = step.phase2
          ? "border-zinc-800 bg-zinc-950 text-zinc-600"
          : hit
            ? "border-emerald-900/60 bg-emerald-950/40 text-emerald-300"
            : "border-zinc-800 bg-zinc-950 text-zinc-600";
        return (
          <li
            key={step.key}
            data-testid={`ribbon-step-${step.key}`}
            data-reached={hit ? "true" : "false"}
            data-phase2={step.phase2 ? "true" : "false"}
            className={`rounded border px-1.5 py-0.5 uppercase tracking-wide ${tone}`}
          >
            {step.label}
            {step.phase2 ? (
              <span className="ml-1 text-[9px] text-zinc-700">Phase 2</span>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

// One labelled section (the IterationDetailModal Section idiom — a quiet header
// + body, addressable by testid).
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
// advisory, experiment chip) + the timestamp + the topic line + the override
// provenance AS VISIBLE TEXT for both blocks. Read-only chips; no close button
// (this is an inline spine section, not a dialog).
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
      <OverrideProvenance
        label="novelty"
        testid="journey-override-novelty"
        block={row.novelty}
      />
      <OverrideProvenance
        label="critique"
        testid="journey-override-critique"
        block={row.critique}
      />
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

// The journey blocks for ONE iteration — read-only, the absorbed modal
// rendering idioms reused (hypothesis / retrieval+relevance / novelty / critic +
// contradicting paper / experiment-outcome / honest stage label). Every value is
// asText-coerced; absent blocks render their own quiet placeholder.
function JourneyBlocks({ row }: { row: IterationRecord }) {
  const hypothesis = asRecord(row.hypothesis);
  const retrieval = asRecord(row.retrieval);
  const relevance = asRecord(retrieval?.relevance);
  const novelty = asRecord(row.novelty);
  const critique = asRecord(row.critique);
  const outcome = asRecord(row.experiment_outcome);

  // The retrieval neighbor count + a couple of top neighbors (each coerced; a
  // neighbor may be a bare id string or a {id} object — only a usable scalar
  // shows). `neighbors` may be a non-array on a malformed row → no preview.
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
  // explicit null (or absent) → "uncontradicted". critique.contradicting_paper_id
  // is producer-owned; coerce defensively.
  const contradictingId = asText(critique?.contradicting_paper_id);

  // The D-052 advisory raw value — surfaced ONLY when present, quiet zinc, NEVER
  // amber. Absent on every normal row (advisory is dark by default).
  const topicalityAdvisory = asText(relevance?.topicality_advisory);

  // hypothesis.candidates_considered (absorbed modal line): a finite number
  // only — NaN/garbage drops the line rather than faking a count.
  const candidatesRaw = hypothesis?.candidates_considered;
  const candidates =
    typeof candidatesRaw === "number" && Number.isFinite(candidatesRaw)
      ? candidatesRaw
      : null;

  // Conditioning bullets (absorbed "conditioned by" section) — the shared
  // chips.conditioningBullets guard: non-array → [], junk entries filtered.
  const bullets = conditioningBullets(row);

  // experiment_outcome.value is scalar OR object (multi-metric); only a usable
  // scalar renders as "value" — an object renders its own scalar entries
  // instead (never "[object Object]"). Absorbed modal idiom.
  const scalarValue = asText(outcome?.value);
  const objectValueEntries =
    outcome?.value != null &&
    typeof outcome.value === "object" &&
    !Array.isArray(outcome.value)
      ? Object.entries(outcome.value as Record<string, unknown>)
          .map(([k, v]) => [k, asText(v)] as const)
          .filter(([, v]) => v !== "")
      : [];

  return (
    <div data-testid="journey-blocks">
      {/* hypothesis */}
      <Section title="hypothesis" testid="journey-hypothesis">
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
      </Section>

      {/* retrieval + relevance */}
      <Section title="retrieval + relevance" testid="journey-retrieval">
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
          </>
        ) : (
          <p className="text-zinc-500">no retrieval block on this row</p>
        )}
        {relevance !== null ? (
          <div data-testid="journey-relevance" className="mt-1">
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
          </div>
        ) : null}
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
      </Section>

      {/* novelty */}
      <Section title="novelty" testid="journey-novelty">
        <Field label="class" value={novelty?.class} />
        <Field label="rationale" value={novelty?.rationale} />
        {novelty === null ? (
          <p className="text-zinc-500">no novelty block on this row</p>
        ) : null}
      </Section>

      {/* critic + contradicting paper */}
      <Section title="critic" testid="journey-critic">
        <Field label="verdict" value={critique?.verdict} />
        <Field label="rationale" value={critique?.rationale} />
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
        ) : null}
        {/* the redteam ADVERSARIAL DETAIL (absorbed modal section 4): the
            clean proceed/0 chip that never earns a row's alarm slot reads
            here, with every redteam field. Absent block → no sub-section. */}
        {row.redteam != null && typeof row.redteam === "object" && (
          <div data-testid="journey-redteam" className="mt-2">
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

      {/* experiment outcome — Phase-2 placeholder when absent */}
      <Section title="experiment outcome" testid="journey-outcome">
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
            <Field label="trials" value={outcome.trials} />
            <Field label="results" value={outcome.results_path} />
            <Field label="summary" value={outcome.summary} />
          </div>
        ) : (
          <p
            data-testid="journey-outcome-placeholder"
            className="text-zinc-600"
          >
            literature-stage — not experimentally tested (Phase 2)
          </p>
        )}
      </Section>
    </div>
  );
}

// The HONEST STAGE LABEL — names where this iteration actually got, no
// fabrication. An outcome present means it reached the experiment bridge;
// otherwise it is literature-stage (the loop's current reality).
function stageLabel(row: IterationRecord): string {
  const outcome = asRecord(row.experiment_outcome);
  if (outcome !== null) {
    return "experiment-bridged — an outcome was recorded (Tier 1/2 bridge)";
  }
  return "literature-stage — judged on retrieval, not experimentally tested (Phase 2)";
}

// The SHORT stage tag for the banner ABOVE the ribbon — literature-stage vs
// applied-tier, inferred PURELY from whether an experiment_outcome block is
// present (frontend inference; no backend stage field needed — the loop is
// literature-stage until β / D-040, so an outcome means it reached the applied
// tier). Mirrors stageLabel's predicate so the top banner and the bottom detail
// line never disagree.
function stageBanner(row: IterationRecord): { label: string; applied: boolean } {
  const applied = asRecord(row.experiment_outcome) !== null;
  return { label: applied ? "applied-tier" : "literature-stage", applied };
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

  // Shared chrome — the header + ribbon render in EVERY state (other-kind,
  // unavailable, loaded) so the surface never blanks.
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
  // throw, never blank. The ribbon still renders (all steps un-reached).
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
        <PipelineRibbon row={null} />
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

      {/* the absorbed modal VERDICT HEADER — the full badge row + override
          provenance as visible text (the row surfaces keep tooltip-only). */}
      <VerdictHeader row={iterationRecord} />

      {/* the honest STAGE BANNER above the ribbon — names the tier this
          iteration actually reached (applied vs literature), inferred from the
          experiment_outcome block. applied = quiet cyan; literature = quiet
          zinc (never amber — it is not a warning, just where the loop is). */}
      {(() => {
        const banner = stageBanner(iterationRecord);
        return (
          <div
            data-testid="journey-stage-banner"
            data-stage={banner.applied ? "applied" : "literature"}
            className={`mt-1.5 rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${
              banner.applied
                ? "border-cyan-900/60 bg-cyan-950/30 text-cyan-300"
                : "border-zinc-800 bg-zinc-950 text-zinc-500"
            }`}
          >
            {banner.label}
            <span className="ml-1 normal-case tracking-normal text-zinc-600">
              {banner.applied
                ? "— an experiment outcome was bridged in"
                : "— judged on retrieval, not experimentally tested"}
            </span>
          </div>
        );
      })()}

      <div className="mt-1.5">
        <PipelineRibbon row={iterationRecord} />
      </div>

      <Field label="iteration" value={iterationRecord.iteration_id} />

      <JourneyBlocks row={iterationRecord} />

      <div
        data-testid="journey-stage-label"
        className="mt-2 rounded border border-zinc-800/60 bg-zinc-950/40 px-1.5 py-1 text-[10px] leading-snug text-zinc-500"
      >
        <span className="uppercase tracking-wide text-zinc-600">stage</span>{" "}
        {stageLabel(iterationRecord)}
      </div>

      {/* the absorbed journal disclosure + deep links out of the dossier. */}
      <JourneyLinks row={iterationRecord} />
    </div>,
  );
}
