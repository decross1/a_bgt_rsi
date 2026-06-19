// Todo.tsx — the /todo UNCERTAINTY-RESOLUTION COCKPIT (S2 reframe,
// docs/ui_reframe_plan.md §1 / 2026-06-19 work order). The owner's sign-off to
// APPLIED-tier experiments: literature-stage iterations auto-advance (observable,
// not gated — the backend drops them from the gate_verdict inbox); the owner is
// reserved for the substantive end-of-pipeline decisions.
//
// This is the thin presentational SHELL that ASSEMBLES the already-built pieces.
// The intended flow (top to bottom of the workspace):
//   pick (from the inbox) -> read the JOURNEY (PipelineJourney, the prediction
//   basis) -> OPTIONAL blind calibration -> interrogate (tutor + two-voice,
//   revealed on demand so a blind calibration is not contaminated) -> DECIDE
//   (the kind-gated resolution forms — NO LONGER gated behind calibration).
//
// It owns: (a) ONE lifted /api/human_todo fetch shared with the inbox (so the
// inbox + workspace can never disagree); (b) one capability fetch feeding each
// form's `available`; (c) the selected-item pointer (selection comes FROM the
// inbox — HumanTodoPanel selectMode — there is no separate chooser); (d) a per-id
// Set of calibrated ids (flag-2: calibration is recorded once per id and never
// re-prompted on switch-away-and-back); (e) a per-id Set of items whose decision
// support has been revealed.
//
// DISCIPLINE (inviolate rules inherit): the inline writers live in the inbox only
// when NOT in select mode; in the cockpit the inbox is select-only, which closes
// the §6.5.4 calibration-bypass at the source (a verdict can no longer be written
// from the inbox with no calibration). The chat panes are capability-gated; the
// tutor is fenced from the verdict (rule 4). No new deps.
import { useEffect, useState } from "react";

import HumanTodoPanel from "../components/HumanTodoPanel";
import GateVerdictForm from "../components/GateVerdictForm";
import FindingReviewForm from "../components/FindingReviewForm";
import DeferForm from "../components/DeferForm";
import ConcurrencyWarning from "../components/todo/ConcurrencyWarning";
import CalibrationCapture from "../components/todo/CalibrationCapture";
import DirectiveSignOffField from "../components/todo/DirectiveSignOffField";
import AuthorizeFixForm from "../components/todo/AuthorizeFixForm";
import SpawnTopicForm from "../components/todo/SpawnTopicForm";
import AbstainForm from "../components/todo/AbstainForm";
import TwoVoiceChatPane from "../components/todo/TwoVoiceChatPane";
import TutorChatPane from "../components/todo/TutorChatPane";
import TutorPanel from "../components/todo/TutorPanel";
import PipelineJourney from "../components/todo/PipelineJourney";

import { getCockpitAvailability, COCKPIT_UNAVAILABLE } from "../api/todo";
import { getHumanTodo } from "../api/http";
import type { CockpitAvailability, CockpitActions } from "../types/todo";
import type { HumanTodoItem } from "../types/schemas";

// --- defensive guards (HOUSE ROBUSTNESS DOCTRINE) -----------------------
// The `availability` + `items` PROPS bypass the fetch path's coercion
// (api/todo.ts asAvailability / resp.items ?? []), and getHumanTodo() casts
// its body without validation. So a malformed/legacy/partial value injected
// as a prop OR returned by the producer must degrade to a legible fallback
// (every gated action disabled; an empty selectable list) — never blank/throw.

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

// Classify the selected item's kind into the form FAMILY it may render
// (U5 — the kind-gate). `selected.id` is an iteration_id for a gate_verdict
// item and a finding_id for a finding_review item; routing the wrong id into a
// form is the bug this gate closes (a finding_id into GateVerdictForm, or an
// iteration_id into the finding-keyed forms + the aux panes). The match is on
// the EXACT producer enum value; `kind` is producer-owned and may be a non-
// string (the harden suite injects object kinds) — anything that is not one of
// the two verdict-bearing kinds is "other": it renders NEITHER keyed family,
// only the kind-agnostic DeferForm.
type KindClass = "iteration" | "finding" | "other";
function classifyKind(kind: unknown): KindClass {
  if (kind === "gate_verdict") return "iteration";
  if (kind === "finding_review") return "finding";
  return "other";
}

// Coerce any value to a clean HumanTodoItem[]: drop non-array containers and
// any element that is not an object carrying a non-empty string `id` (the id
// is the selection key + the forms' target — an item without one cannot be
// pointed at, so it is dropped rather than crashing .find/.map/key/argv).
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

// asText for the selected-item header (producer-owned title/kind/id may be a
// non-string): a string trims, a finite number stringifies, anything else drops.
function asText(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "";
  return "";
}

interface Props {
  /** Tests/preview may inject a known capability to bypass the fetch — mirrors
   *  HumanTodoPanel's `attest` override idiom. When provided, no fetch runs. */
  availability?: CockpitAvailability;
  /** Tests/preview may inject the inbox items to bypass the fetch. This is the
   *  ONE lifted list — the inbox renders from it (no separate self-poll), so the
   *  inbox + workspace can never disagree. */
  items?: HumanTodoItem[];
  /** Poll interval for the lifted /api/human_todo fetch (live mode only). */
  pollMs?: number;
}

export default function Todo({ availability, items, pollMs = 10000 }: Props) {
  // One capability fetch feeds every form's `available` prop. The override
  // wins (tests inject it); otherwise fetch once and degrade to UNAVAILABLE on
  // failure (a missing endpoint leaves every gated action disabled).
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

  // THE ONE lifted /api/human_todo list — shared by the inbox (passed down as
  // `initial`, which suppresses the panel's own self-poll) AND the workspace
  // (the selection pointer). Override wins for tests; live mode fetches + polls.
  const [todoItems, setTodoItems] = useState<HumanTodoItem[]>(safeItems(items));
  useEffect(() => {
    if (items !== undefined) {
      setTodoItems(safeItems(items));
      return;
    }
    let live = true;
    const load = () =>
      getHumanTodo()
        .then((resp) => {
          // resp is producer-owned + cast (getJSON does no shape check): a
          // non-array `items` (or a malformed element) is coerced/dropped.
          if (live) setTodoItems(safeItems(resp?.items));
        })
        .catch(() => {
          if (live) setTodoItems([]);
        });
    load();
    const interval = setInterval(load, Math.max(1000, pollMs));
    return () => {
      live = false;
      clearInterval(interval);
    };
  }, [items, pollMs]);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected =
    todoItems.find((it) => it.id === selectedId) ?? todoItems[0] ?? null;

  // flag-2 ruling: calibration is recorded PER ID into a Set — never re-prompted
  // when you switch away from a calibrated item and back (no double
  // calibration_entry). Calibration is OPTIONAL (opt-in, blind-if-used); it no
  // longer gates the resolution forms.
  const [calibratedIds, setCalibratedIds] = useState<Set<string>>(new Set());
  const calibrated = selected !== null && calibratedIds.has(selected.id);

  // The decision support (tutor + two-voice interrogation) is hidden by default
  // so an OPTIONAL blind calibration is not contaminated by it; the human reveals
  // it explicitly. Revealing requires NO calibration (the gate is gone) — it only
  // protects "blind if used". Per-id so a reveal sticks across a switch-and-back.
  const [revealedIds, setRevealedIds] = useState<Set<string>>(new Set());
  const interrogationRevealed =
    selected !== null && revealedIds.has(selected.id);

  // `caps` may be an injected/legacy availability prop that bypassed
  // asAvailability — a null/non-object or a missing `actions` leaves every gated
  // action disabled, not crash on `actions.<flag>`.
  const actions = safeActions(caps);

  // U5 kind-gate: which form family `selected.id` is keyed for. ITERATION-keyed
  // forms get an iteration_id; FINDING-keyed forms + the interrogation panes get
  // a finding_id; an "other" kind gets neither keyed family — only DeferForm.
  const kindClass = selected !== null ? classifyKind(selected.kind) : "other";

  const captureCalibration = () => {
    if (selected === null) return;
    setCalibratedIds((prev) => {
      const next = new Set(prev);
      next.add(selected.id);
      return next;
    });
  };
  const revealInterrogation = () => {
    if (selected === null) return;
    setRevealedIds((prev) => {
      const next = new Set(prev);
      next.add(selected.id);
      return next;
    });
  };

  return (
    <div className="mx-auto max-w-7xl p-5" data-testid="todo-cockpit">
      <header className="mb-3">
        <h1 className="text-sm font-semibold uppercase tracking-wide text-zinc-300">
          /todo · uncertainty-resolution cockpit
        </h1>
        <p className="mt-0.5 text-[11px] text-zinc-500">
          Your sign-off to applied-tier experiments — the rigorous go/no-go
          before the applied world. Literature-stage iterations auto-advance
          (observable, not gated); you are reserved for the substantive
          end-of-pipeline decisions. Pick an item, read its journey, optionally
          record a blind calibration, interrogate the two voices, then decide.
        </p>
        {/* collapsible "what am I being asked?" — the two-validation model + the
            three ops/info kinds (legible, not the raw producer enum). */}
        <details
          data-testid="todo-explainer"
          className="mt-1 rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1"
        >
          <summary className="cursor-pointer text-[10px] uppercase tracking-wide text-zinc-500">
            what am I being asked?
          </summary>
          <div className="mt-1 space-y-1 text-[11px] text-zinc-400">
            <div>
              <span className="text-zinc-300">Two research validations.</span>{" "}
              <strong className="text-zinc-300">gate-verdict</strong> — sign off
              or reject a WHOLE ITERATION (the full literature pipeline for one
              hypothesis).{" "}
              <strong className="text-zinc-300">finding-review</strong> —
              validate or reject ONE CLAIM a finding surfaced.
            </div>
            <div>
              <span className="text-zinc-300">Three ops / info.</span>{" "}
              <strong className="text-zinc-300">bubble-ack</strong> — acknowledge
              a coordinator bubble.{" "}
              <strong className="text-zinc-300">stale-active-run</strong> — a
              run-state heads-up that active_run.json looks stale.{" "}
              <strong className="text-zinc-300">state-gate</strong> — a pending
              human gate in the run state.
            </div>
            <div className="text-[10px] text-zinc-600">
              Literature-stage iterations auto-advance and appear on
              Activity/Resolved, not here.
            </div>
          </div>
        </details>
      </header>

      {/* 1) shared-models warn/queue guard — self-fetches; self-hides when idle. */}
      <ConcurrencyWarning />

      {/* 2) the INBOX — select-only (the calibration-bypass is closed at the
          source: the inline verdict writers are suppressed; a row is a selector
          that drives the workspace below). Defer + bubble-ack stay inline. */}
      <section className="mt-3" data-testid="todo-inbox">
        <div className="mb-1 text-[10px] uppercase tracking-wide text-zinc-600">
          inbox · what needs resolving
        </div>
        <HumanTodoPanel
          initial={todoItems}
          selectMode
          onSelect={setSelectedId}
          selectedId={selected?.id ?? null}
        />
      </section>

      {/* 3) the WORKSPACE for the selected item: journey -> optional blind
          calibration -> reveal-gated interrogation -> decide. */}
      <section className="mt-4" data-testid="todo-resolution-area">
        <div className="mb-1 text-[10px] uppercase tracking-wide text-zinc-600">
          resolve a selected item
        </div>

        {selected === null ? (
          <div data-testid="todo-no-selection" className="text-[11px] text-zinc-500">
            nothing selected — pick an item from the inbox above.
          </div>
        ) : (
          <div className="space-y-3">
            {/* the selected item (selection now comes from the inbox, not a
                separate chip chooser). */}
            <div
              data-testid="todo-selected-item"
              className="flex flex-wrap items-center gap-2 text-[11px]"
            >
              <span className="text-[10px] uppercase tracking-wide text-zinc-600">
                resolving
              </span>
              <span className="rounded border border-sky-800 bg-sky-950 px-1.5 py-0.5 font-mono text-[10px] text-sky-300">
                {asText(selected.id) || "(no id)"}
              </span>
              {asText(selected.kind).length > 0 ? (
                <span className="text-[10px] uppercase tracking-wide text-zinc-500">
                  {asText(selected.kind)}
                </span>
              ) : null}
              {asText(selected.title).length > 0 ? (
                <span className="text-zinc-400">{asText(selected.title)}</span>
              ) : null}
            </div>

            {/* the JOURNEY — the read-only pipeline context, the prediction
                basis (read first). */}
            <PipelineJourney key={`journey-${selected.id}`} item={selected} />

            {/* OPTIONAL blind calibration — opt-in; recorded once per id and
                never re-prompted (flag-2). It no longer GATES the forms. */}
            <CalibrationCapture
              key={`calib-${selected.id}`}
              refId={selected.id}
              available={actions.calibration}
              captured={calibrated}
              onCaptured={captureCalibration}
            />

            {/* INTERROGATE (finding items only) — decision support, hidden by
                default so an optional blind calibration is not contaminated.
                Revealing requires NO calibration. */}
            {kindClass === "finding" && (
              <div data-testid="todo-interrogate">
                {!interrogationRevealed ? (
                  <button
                    type="button"
                    data-testid="reveal-interrogation"
                    onClick={revealInterrogation}
                    className="rounded border border-zinc-700 bg-zinc-950 px-2 py-1 text-[11px] text-zinc-300 hover:border-zinc-600 hover:text-zinc-100"
                  >
                    reveal decision support (tutor + two-voice) — record a blind
                    calibration first if you want one
                  </button>
                ) : (
                  <div
                    data-testid="todo-aux-interactive"
                    className="space-y-3"
                  >
                    {/* the finding overview + the live interrogation. The tutor
                        is fenced from the verdict (2026-06-14 PART 2 · rule 4 ·
                        D-053/D-054); D-044 governs the two-voice interrogator's
                        independence, cited on that pane. */}
                    <TutorPanel
                      findingId={selected.id}
                      title={selected.title ?? undefined}
                    />
                    <div className="grid gap-3 md:grid-cols-2">
                      <TutorChatPane
                        findingId={selected.id}
                        available={actions.two_voice_chat}
                      />
                      <TwoVoiceChatPane
                        findingId={selected.id}
                        available={actions.two_voice_chat}
                      />
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* DECIDE — the kind-gated resolution forms. They render
                UNCONDITIONALLY now (the forced calibration gate is removed;
                calibration is opt-in). U5 kind-gate: an ITERATION item carries
                an iteration_id -> only GateVerdictForm; a FINDING item carries a
                finding_id -> only the finding-keyed forms. */}
            <div data-testid="resolution-forms" className="space-y-2">
              {kindClass === "iteration" && (
                /* the blessed gate-verdict form: valid = sign off, invalid =
                   reject. The ONLY iteration-keyed disposition. */
                <GateVerdictForm iterationId={selected.id} />
              )}

              {kindClass === "finding" && (
                <>
                  <FindingReviewForm findingId={selected.id} />
                  {/* sign off the FINDING with a directive (finding_session
                      --set-status validated --directive). */}
                  <DirectiveSignOffField
                    findingId={selected.id}
                    note="signed off via /todo cockpit"
                    available={actions.directive_signoff}
                  />
                  <AuthorizeFixForm
                    findingId={selected.id}
                    available={actions.authorize_fix}
                  />
                  <SpawnTopicForm
                    findingId={selected.id}
                    available={actions.spawn_topic}
                  />
                  <AbstainForm
                    findingId={selected.id}
                    available={actions.abstain}
                  />
                </>
              )}

              {/* refine, defer to a dev session (blessed). Already kind-aware
                  (renders nothing for an unknown kind), so it is available for
                  ALL kinds — the one in-UI action even for the "other" kinds. */}
              <DeferForm kind={selected.kind} refId={selected.id} />
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
