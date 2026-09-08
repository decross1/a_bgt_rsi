// DossierReader — the /dossier/:id READER (UI simplification S2 — "the
// product"). One dossier, read top to bottom:
//
//   ConcurrencyWarning → header (id · kind · title · deferred tag) → the
//   trimmed TutorPanel overview → the PipelineJourney SPINE (which absorbed
//   the retired IterationDetailModal's unique sections) → optional blind
//   CalibrationCapture (pre-reveal) → the REVEAL FENCE → ChatPane ×2
//   (mode=tutor + mode=two_voice) → the kind-gated DISPOSITION FOOTER.
//
// KIND RESOLUTION: the item's kind comes from the live /api/human_todo queue
// (find by id); an id NOT in the queue falls back to its prefix — sf-* reads
// as a finding dossier, iter-* as an iteration dossier (the resolved-history
// rows the index links). Anything else is an "other" dossier: journey +
// defer only.
//
// THE VERDICT FENCE (inviolate rule 4 / D-053/D-054): the forms in the
// disposition footer are the ONLY dispositions. The chat panes accept no
// verdict-shaped prop (structurally fence-preserving); the tutor never
// recommends; the U5 kind-gate keeps an iteration_id out of the finding-keyed
// forms and vice versa. The footer renders UNCONDITIONALLY — calibration is
// OPT-IN and gates nothing; the reveal fence only protects "blind if used".
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import GateVerdictForm from "../components/GateVerdictForm";
import FindingReviewForm from "../components/FindingReviewForm";
import BubbleAckForm from "../components/BubbleAckForm";
import DeferForm from "../components/DeferForm";
import ConcurrencyWarning from "../components/todo/ConcurrencyWarning";
import CalibrationCapture from "../components/todo/CalibrationCapture";
import DirectiveSignOffField from "../components/todo/DirectiveSignOffField";
import AuthorizeFixForm from "../components/todo/AuthorizeFixForm";
import SpawnTopicForm from "../components/todo/SpawnTopicForm";
import AbstainForm from "../components/todo/AbstainForm";
import ChatPane from "../components/todo/ChatPane";
import TutorPanel from "../components/todo/TutorPanel";
import PipelineJourney from "../components/todo/PipelineJourney";

import RungGlyph, { rungIndex } from "../design/RungGlyph";

import { getCockpitAvailability, COCKPIT_UNAVAILABLE } from "../api/todo";
import {
  getFindingDetail,
  getHumanTodo,
  getIterationJourney,
} from "../api/http";
import type { CockpitAvailability, CockpitActions } from "../types/todo";
import type {
  FindingDetail,
  HumanTodoItem,
  IterationJourneyResponse,
} from "../types/schemas";
import "./dossiers.css";

// --- defensive guards (lifted VERBATIM from the retired routes/Todo.tsx) ----
// The `availability` + `items` PROPS bypass the fetch path's coercion
// (api/todo.ts asAvailability / resp.items ?? []), and getHumanTodo() casts
// its body without validation. So a malformed/legacy/partial value injected
// as a prop OR returned by the producer must degrade to a legible fallback
// (every gated action disabled; an empty queue) — never blank/throw.

// Coerce any value to the per-outcome action booleans, strictly (=== true).
// A null/non-object `actions` (or a missing one) leaves every gated action
// disabled, matching COCKPIT_UNAVAILABLE's honest capability-off state.
function safeActions(caps: unknown): CockpitActions {
  const raw =
    caps !== null && typeof caps === "object" && !Array.isArray(caps)
      ? (caps as Record<string, unknown>).actions
      : undefined;
  const a =
    raw !== null && typeof raw === "object" && !Array.isArray(raw)
      ? (raw as Record<string, unknown>)
      : {};
  return {
    directive_signoff: a.directive_signoff === true,
    authorize_fix: a.authorize_fix === true,
    spawn_topic: a.spawn_topic === true,
    abstain: a.abstain === true,
    calibration: a.calibration === true,
    two_voice_chat: a.two_voice_chat === true,
  };
}

// Coerce any value to a clean HumanTodoItem[] (the Todo.tsx safeItems).
function safeItems(value: unknown): HumanTodoItem[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (it): it is HumanTodoItem =>
      it !== null &&
      typeof it === "object" &&
      !Array.isArray(it) &&
      typeof (it as { id?: unknown }).id === "string" &&
      (it as { id: string }).id.length > 0,
  );
}

function queueIntegrity(value: unknown): {
  items: HumanTodoItem[];
  partial: boolean;
} {
  if (!Array.isArray(value)) return { items: [], partial: true };
  const admitted = safeItems(value);
  return { items: admitted, partial: admitted.length !== value.length };
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asText(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "";
  return "";
}

// The U5 kind-gate families (the Todo.tsx classifyKind, extended with the
// bubble family the reader also disposes): the EXACT producer enum values
// only; anything else — including hostile non-string kinds — is "other" and
// renders NEITHER keyed family, only the kind-agnostic DeferForm.
type KindClass = "iteration" | "finding" | "bubble" | "other";
function classifyKind(kind: unknown): KindClass {
  if (kind === "gate_verdict") return "iteration";
  if (kind === "finding_review") return "finding";
  if (kind === "bubble_ack" || kind === "bubble_unacked") return "bubble";
  return "other";
}

// COARSE age for the header ("how long has this been waiting?"). `since` is
// producer-owned: a non-string / unparseable value yields "" so the line is
// DROPPED rather than showing "NaNd". Deliberately coarse — time.elapsed()
// renders minutes ("4320m 0s") which is unreadable for a days-old dossier.
function ageText(since: unknown, nowMs: number): string {
  if (typeof since !== "string" || since.length === 0) return "";
  const t = Date.parse(since);
  if (Number.isNaN(t)) return "";
  const mins = Math.max(0, Math.floor((nowMs - t) / 60000));
  if (mins < 60) return `${mins}m old`;
  const hours = Math.floor(mins / 60);
  if (hours < 48) return `${hours}h old`;
  return `${Math.floor(hours / 24)}d old`;
}

// Fallback kind for an id NOT in the live queue: its prefix names the family
// (sf-* = surfaced finding, iter-* = iteration). Anything else stays unknown.
function kindFromPrefix(id: string): string | null {
  if (id.startsWith("sf-")) return "finding_review";
  if (id.startsWith("iter-")) return "gate_verdict";
  return null;
}

interface Props {
  /** Tests/preview may inject a known capability to bypass the fetch. */
  availability?: CockpitAvailability;
  /** Tests/preview may inject the queue items to bypass the fetch. */
  items?: HumanTodoItem[];
}

type RecordReadState =
  | "idle"
  | "loading"
  | "ready"
  | "missing"
  | "partial"
  | "error";

interface RecordRead {
  state: RecordReadState;
  detail: FindingDetail | null;
  journey: IterationJourneyResponse | null;
  sourceIterationId: string;
}

export default function DossierReader(props: Props) {
  const params = useParams<{ id: string }>();
  const dossierId = asText(params.id);
  return <DossierReaderRecord key={dossierId} {...props} dossierId={dossierId} />;
}

function DossierReaderRecord({
  availability,
  items,
  dossierId,
}: Props & { dossierId: string }) {

  // One capability fetch feeds every form's `available` prop (lifted VERBATIM
  // from Todo.tsx). The override wins (tests inject it); otherwise fetch once
  // and degrade to UNAVAILABLE on failure.
  const [caps, setCaps] = useState<CockpitAvailability>(
    availability ?? COCKPIT_UNAVAILABLE,
  );
  useEffect(() => {
    if (availability !== undefined) return;
    let live = true;
    getCockpitAvailability()
      .then((c) => {
        if (live) setCaps(c);
      })
      .catch(() => {
        if (live) setCaps(COCKPIT_UNAVAILABLE);
      });
    return () => {
      live = false;
    };
  }, [availability]);

  // The live queue — the reader resolves this dossier's KIND (and title /
  // deferred tag) from it. One fetch; an id not in the queue (a resolved
  // iteration, a legacy finding) falls back to its prefix.
  const [queue, setQueue] = useState<HumanTodoItem[]>(safeItems(items));
  const [queueLoaded, setQueueLoaded] = useState(items !== undefined);
  const [queueError, setQueueError] = useState(false);
  const [queuePartial, setQueuePartial] = useState(
    items !== undefined ? queueIntegrity(items).partial : false,
  );
  useEffect(() => {
    if (items !== undefined) {
      const inspected = queueIntegrity(items);
      setQueue(inspected.items);
      setQueuePartial(inspected.partial);
      setQueueLoaded(true);
      setQueueError(false);
      return;
    }
    let live = true;
    getHumanTodo()
      .then((resp) => {
        if (!live) return;
        const inspected = queueIntegrity(resp?.items);
        setQueue(inspected.items);
        setQueuePartial(inspected.partial);
        setQueueLoaded(true);
        setQueueError(false);
      })
      .catch(() => {
        // Queue unreachable → prefix fallback still names the family; the
        // reader never blanks on a dead queue endpoint.
        if (live) {
          setQueueLoaded(true);
          setQueueError(true);
        }
      });
    return () => {
      live = false;
    };
  }, [items]);

  const item = queue.find((it) => it.id === dossierId) ?? null;
  const resolvedKind: string | null =
    item !== null && typeof item.kind === "string"
      ? item.kind
      : kindFromPrefix(dossierId);
  const kindClass = classifyKind(resolvedKind);
  const interrogable = kindClass === "iteration" || kindClass === "finding";
  const title = item !== null ? asText(item.title) : "";
  // How long this has been waiting (the queue row's `since`). Coarse and
  // computed once per render — no live clock for a days-scale number.
  const age = item !== null ? ageText(item.since, Date.now()) : "";

  // The journey item PipelineJourney replays: the live queue item when
  // present, else a synthesized pointer carrying the resolved kind.
  const journeyItem: HumanTodoItem =
    item ?? ({ id: dossierId, kind: resolvedKind ?? "unknown" } as HumanTodoItem);

  // Calibration + reveal are target-local. DossierReader keys this complete
  // reader boundary by dossierId, so no reader or action state survives a
  // same-route identity transition.
  const [calibratedIds, setCalibratedIds] = useState<Set<string>>(new Set());
  const calibrated = dossierId.length > 0 && calibratedIds.has(dossierId);
  const [revealedIds, setRevealedIds] = useState<Set<string>>(new Set());
  const interrogationRevealed =
    dossierId.length > 0 && revealedIds.has(dossierId);

  const actions = safeActions(caps);

  // One reader-local read model feeds both the overview and the journey. This
  // keeps their identity bound and avoids duplicate journey/detail requests.
  const [recordRead, setRecordRead] = useState<RecordRead>({
    state: "idle",
    detail: null,
    journey: null,
    sourceIterationId: "",
  });
  useEffect(() => {
    if (!interrogable || dossierId.length === 0) {
      setRecordRead({
        state: "idle",
        detail: null,
        journey: null,
        sourceIterationId: "",
      });
      return;
    }

    let live = true;
    setRecordRead({
      state: "loading",
      detail: null,
      journey: null,
      sourceIterationId: kindClass === "iteration" ? dossierId : "",
    });

    const resolveJourney = async (
      sourceIterationId: string,
      detail: FindingDetail | null,
    ) => {
      let journey: IterationJourneyResponse;
      try {
        journey = await getIterationJourney(sourceIterationId);
      } catch {
        if (live) {
          setRecordRead({
            state: "error",
            detail,
            journey: null,
            sourceIterationId,
          });
        }
        return;
      }
      if (!live) return;
      const journeyObj = asRecord(journey);
      const iterationObj = asRecord(journeyObj?.iteration);
      if (journeyObj === null || typeof journeyObj.found !== "boolean") {
        setRecordRead({
          state: "partial",
          detail,
          journey: null,
          sourceIterationId,
        });
        return;
      }
      if (journeyObj.found !== true || iterationObj === null) {
        setRecordRead({
          state: "missing",
          detail,
          journey,
          sourceIterationId,
        });
        return;
      }
      if (asText(iterationObj.iteration_id) !== sourceIterationId) {
        setRecordRead({
          state: "partial",
          detail,
          journey: null,
          sourceIterationId,
        });
        return;
      }
      setRecordRead({
        state: "ready",
        detail,
        journey,
        sourceIterationId,
      });
    };

    (async () => {
      try {
        if (kindClass === "iteration") {
          await resolveJourney(dossierId, null);
          return;
        }
        const detail = await getFindingDetail(dossierId);
        if (!live) return;
        const detailObj = asRecord(detail);
        if (
          detailObj === null ||
          typeof detailObj.found !== "boolean" ||
          (detailObj.found === true && asText(detailObj.finding_id) !== dossierId)
        ) {
          setRecordRead({
            state: "partial",
            detail: null,
            journey: null,
            sourceIterationId: "",
          });
          return;
        }
        if (detailObj.found !== true) {
          setRecordRead({
            state: "missing",
            detail,
            journey: null,
            sourceIterationId: "",
          });
          return;
        }
        const sourceIterationId =
          asText(detailObj.source_iteration_id) ||
          asText(asRecord(detailObj.source_iteration)?.iteration_id);
        const nestedSourceIterationId = asText(
          asRecord(detailObj.source_iteration)?.iteration_id,
        );
        if (sourceIterationId.length === 0) {
          setRecordRead({
            state: "partial",
            detail,
            journey: null,
            sourceIterationId: "",
          });
          return;
        }
        if (
          nestedSourceIterationId.length > 0 &&
          nestedSourceIterationId !== sourceIterationId
        ) {
          setRecordRead({
            state: "partial",
            detail: null,
            journey: null,
            sourceIterationId: "",
          });
          return;
        }
        await resolveJourney(sourceIterationId, detail);
      } catch {
        if (live) {
          setRecordRead({
            state: "error",
            detail: null,
            journey: null,
            sourceIterationId: "",
          });
        }
      }
    })();

    return () => {
      live = false;
    };
  }, [dossierId, interrogable, kindClass]);

  const captureCalibration = () => {
    if (dossierId.length === 0) return;
    setCalibratedIds((prev) => {
      const next = new Set(prev);
      next.add(dossierId);
      return next;
    });
  };
  const revealInterrogation = () => {
    if (dossierId.length === 0) return;
    setRevealedIds((prev) => {
      const next = new Set(prev);
      next.add(dossierId);
      return next;
    });
  };

  if (dossierId.length === 0) {
    return (
      <div className="page-prose" data-testid="dossier-reader">
        <div data-testid="dossier-no-id" className="text-[11px] text-zinc-500">
          no dossier id — pick one from{" "}
          <Link to="/dossier" className="text-sky-300 underline">
            the index
          </Link>
          .
        </div>
      </div>
    );
  }

  const sourceState = queueError
    ? "error"
    : queuePartial
      ? "partial"
      : !queueLoaded
        ? "loading"
        : item !== null
          ? "ready"
          : resolvedKind !== null
            ? "unknown"
            : "error";
  const sourceStateText = queueError
    ? item !== null
      ? "Queue refresh unavailable · showing the last recorded queue record"
      : "Queue unavailable · family inferred from the ID only"
    : queuePartial
      ? item !== null
        ? "Live queue record · queue response is partial"
        : "Queue response partial · identity inferred from the ID"
      : !queueLoaded
        ? "Checking the live queue"
        : item !== null
          ? "Live queue record"
          : resolvedKind !== null
            ? "Historical record · family inferred from the ID"
            : "Record identity unresolved";
  const boundaryText = item !== null && !queueError && !queuePartial
    ? "This record is present in the live queue. The controls below still use their existing capability and confirmation checks."
    : queueError || queuePartial
      ? "Current queue eligibility cannot be established from this response. A valid-looking ID does not grant authority; every control keeps its existing gate."
      : resolvedKind !== null
        ? "This record is not present in the live queue. Historical status neither grants nor removes authority; every control keeps its existing gate."
        : "This record's source family is unknown. No family-specific decision is inferred from its ID.";
  const journeyObj = asRecord(recordRead.journey);
  const journeyRecord = asRecord(journeyObj?.iteration);
  const journeySeed = asRecord(journeyRecord?.seed);
  const detailRecord = asRecord(recordRead.detail);
  const displayTitle =
    title ||
    asText(detailRecord?.title) ||
    asText(journeySeed?.topic) ||
    dossierId;
  const evidenceStateText =
    !interrogable
      ? "No stage journey is defined for this record family"
      : recordRead.state === "ready"
        ? `Exact evidence loaded from ${recordRead.sourceIterationId}`
        : recordRead.state === "loading" || recordRead.state === "idle"
          ? "Loading exact recorded evidence"
          : recordRead.state === "missing"
            ? "No exact journey record resolved for this source"
            : recordRead.state === "partial"
              ? "Evidence response is malformed, incomplete, or bound to a different identity"
              : "Exact evidence is unavailable";

  return (
    <div className="dossier-reader-page" data-testid="dossier-reader">
      <Link
        to="/dossier"
        className="text-xs text-sky-700 underline-offset-4 hover:underline"
      >
        Back to dossiers
      </Link>

      <header className="dossier-reader-context mt-3" data-testid="dossier-header">
        <div className="dossier-context-line">
          <span className="dossier-context-id">{dossierId}</span>
          {/* THE rung representation (R0 RungGlyph, D-059) — rendered only when
              the queue row actually carries an L0..L5 level; a legacy/absent/
              malformed level shows NOTHING rather than a fake empty ring. */}
          {rungIndex(item?.evidence_level) !== null ? (
            <span data-testid="dossier-rung" className="flex items-center">
              <RungGlyph level={item?.evidence_level} />
            </span>
          ) : null}
          {resolvedKind !== null ? (
            <span
              data-testid="dossier-kind"
              className="text-[10px] uppercase tracking-wide text-zinc-500"
            >
              {resolvedKind}
            </span>
          ) : (
            <span
              data-testid="dossier-kind-unknown"
              className="text-[10px] uppercase tracking-wide text-zinc-600"
            >
              unknown kind
            </span>
          )}
          {item !== null && item.deferred === true && (
            <span
              data-testid="todo-deferred-tag"
              className="rounded bg-sky-950 px-1.5 py-0.5 text-[10px] text-sky-400"
            >
              deferred to dev session
            </span>
          )}
          {age.length > 0 && (
            <span
              data-testid="dossier-age"
              className="ml-auto text-[10px] text-zinc-600"
            >
              {age}
            </span>
          )}
          <span
            className="dossier-source-state ml-auto"
            data-state={sourceState}
            data-testid="dossier-record-source-state"
          >
            {sourceStateText}
          </span>
        </div>
        <h1 className="dossier-page-title mt-3">{displayTitle}</h1>
        <p className="dossier-boundary-note" data-testid="dossier-boundary-note">
          {boundaryText}
        </p>
      </header>

      <section className="mt-4" aria-labelledby="dossier-evidence-heading">
        <div className="dossier-section-heading">
          <h2 className="dossier-section-title" id="dossier-evidence-heading">
            Evidence
          </h2>
          <span
            className="dossier-source-state ml-auto"
            data-state={
              !interrogable
                ? "unknown"
                : recordRead.state === "ready"
                  ? "ready"
                  : recordRead.state
            }
            data-testid="dossier-evidence-state"
          >
            {evidenceStateText}
          </span>
        </div>
        <p className="dossier-section-copy">
          Read the journal, recorded links, and stage history bound to this exact
          source before using a decision control.
        </p>
        <PipelineJourney
          key={`journey-${dossierId}`}
          item={journeyItem}
          detail={kindClass === "finding" ? recordRead.detail : undefined}
          journey={interrogable ? recordRead.journey : undefined}
          loading={
            interrogable &&
            (recordRead.state === "loading" || recordRead.state === "idle")
          }
        />
      </section>

      <section
        className="dossier-decision-boundary dossier-surface"
        aria-labelledby="dossier-decision-heading"
      >
        <h2 className="dossier-section-title" id="dossier-decision-heading">
          Human decision
        </h2>
        <p className="dossier-section-copy">
          No decision is made on load. Availability, required notes, and
          confirmation remain governed by each existing control.
        </p>
        <ConcurrencyWarning />
        {/* the DISPOSITION FOOTER — kind-gated, UNCONDITIONAL (no calibration
            prerequisite). The U5 kind-gate: an ITERATION id keys ONLY
            GateVerdictForm; a FINDING id ONLY the finding-keyed set; a bubble
            ONLY its ack; every kind gets the blessed DeferForm. */}
        <div data-testid="resolution-forms" className="mt-3 space-y-2">
          {kindClass === "iteration" && (
            <>
              {/* the blessed gate-verdict form: valid = sign off, invalid =
                  reject. The ONLY iteration-keyed disposition. */}
              <GateVerdictForm iterationId={dossierId} />
              {/* the copy-paste CLI fallback (ported verbatim from the retired
                  IterationDetailModal gate panel — the Task-3 degradation
                  path). */}
              <details className="rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1">
                <summary className="cursor-pointer text-[11px] text-zinc-400">
                  CLI fallback — resolve this gate from a terminal
                </summary>
                <code
                  data-testid="dossier-gate-cli"
                  className="mt-1 block overflow-x-auto whitespace-pre rounded bg-zinc-950 px-2 py-1 font-mono text-[11px] text-zinc-300"
                >
                  {`.venv-chroma/bin/python -m orchestrator.gate_cli --iteration-id ${dossierId} --verdict <valid|invalid|needs_revision> --note '<why>'`}
                </code>
              </details>
            </>
          )}

          {kindClass === "finding" && (
            <>
              <FindingReviewForm findingId={dossierId} />
              {/* sign off the FINDING with a directive (finding_session
                  --set-status validated --directive). */}
              <DirectiveSignOffField
                findingId={dossierId}
                note="signed off via dossier reader"
                available={actions.directive_signoff}
              />
              <AuthorizeFixForm
                findingId={dossierId}
                available={actions.authorize_fix}
              />
              <SpawnTopicForm
                findingId={dossierId}
                available={actions.spawn_topic}
              />
              <AbstainForm findingId={dossierId} available={actions.abstain} />
            </>
          )}

          {kindClass === "bubble" && <BubbleAckForm bubbleRunId={dossierId} />}

          {/* refine, defer to a dev session (blessed). Kind-aware — renders
              nothing for an unknown kind; the one in-UI action even for the
              "other" kinds. */}
          <DeferForm kind={resolvedKind ?? "unknown"} refId={dossierId} />
        </div>
      </section>

      <details
        className="dossier-support dossier-surface"
        data-testid="dossier-support"
      >
        <summary>Optional calibration and decision support</summary>
        <div className="dossier-support-body space-y-3">
          <p className="dossier-section-copy">
            Calibration remains optional and does not gate the decision. Tutor
            and two-voice support explain or challenge; they never set a verdict.
          </p>
          {interrogable ? (
            <TutorPanel
              key={`tutor-${dossierId}`}
              findingId={dossierId}
              title={title.length > 0 ? title : undefined}
              kind={kindClass === "iteration" ? "iteration" : "finding"}
              detail={kindClass === "finding" ? recordRead.detail : undefined}
              journey={kindClass === "iteration" ? recordRead.journey : undefined}
              loading={
                recordRead.state === "loading" || recordRead.state === "idle"
              }
              compact
            />
          ) : null}
          <CalibrationCapture
            key={`calib-${dossierId}`}
            refId={dossierId}
            available={actions.calibration}
            captured={calibrated}
            onCaptured={captureCalibration}
          />
          {interrogable && (
            <div data-testid="dossier-interrogate">
              {!interrogationRevealed ? (
                <button
                  type="button"
                  data-testid="reveal-interrogation"
                  onClick={revealInterrogation}
                  className="rounded border border-zinc-700 bg-zinc-950 px-2 py-1 text-[11px] text-zinc-300 hover:border-zinc-600 hover:text-zinc-100"
                >
                  Reveal tutor and two-voice support
                </button>
              ) : (
                <div
                  data-testid="dossier-aux-interactive"
                  className="grid gap-3 md:grid-cols-2"
                >
                  <ChatPane
                    findingId={dossierId}
                    mode="tutor"
                    available={actions.two_voice_chat}
                  />
                  <ChatPane
                    findingId={dossierId}
                    mode="two_voice"
                    available={actions.two_voice_chat}
                  />
                </div>
              )}
            </div>
          )}
        </div>
      </details>
    </div>
  );
}
