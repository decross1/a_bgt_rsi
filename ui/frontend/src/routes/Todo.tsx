// Todo.tsx — the /todo UNCERTAINTY-RESOLUTION COCKPIT (2026-06-14 session note
// "## UI session work order" PART 2). This is the thin presentational SHELL that
// ASSEMBLES the already-built pieces; it owns no business logic of its own beyond
// (a) one capability fetch that feeds every stub form's `available` prop, (b) a
// selected-item pointer, and (c) the PRE-VERDICT ORDERING contract.
//
// The cockpit is where Nara escalates anything it is unsure about and the human
// resolves it. Top-to-bottom it composes:
//   1. ConcurrencyWarning — the shared-models warn/queue guard (self-fetches,
//      self-hides when idle).
//   2. The INBOX — the existing HumanTodoPanel (its home is now /todo; PART 1
//      removed it from the dashboard). Its own blessed forms (gate_verdict /
//      finding_review / bubble_ack / defer) live inside it.
//   3. The RESOLUTION AREA for a selected item. The ORDERING CONTRACT (ARCH
//      §6.5.4): CalibrationCapture renders FIRST; only after its onCaptured fires
//      do the six resolution forms appear. Calibration before verdict, always.
//   4. The two-voice interrogation pane (gated off actions.two_voice_chat) and
//      the tutor (FENCED from the verdict — handed NO verdict props).
//
// DISCIPLINE (inviolate rules inherit): the stub forms surface their would-run
// argv READ-ONLY and never write a ledger (D-046 / rule 8); they label themselves
// honestly and stay disabled until their named seam lands; the tutor cannot touch
// the verdict path (rule 4). No new deps.
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
import TutorPanel from "../components/todo/TutorPanel";

import { getCockpitAvailability, COCKPIT_UNAVAILABLE } from "../api/todo";
import { getHumanTodo } from "../api/http";
import type { CockpitAvailability, CockpitActions } from "../types/todo";
import type { HumanTodoItem } from "../types/schemas";

// --- defensive guards (HOUSE ROBUSTNESS DOCTRINE) -----------------------
// The `availability` + `items` PROPS bypass the fetch path's coercion
// (api/todo.ts asAvailability / resp.items ?? []), and getHumanTodo() casts
// its body without validation. So a malformed/legacy/partial value injected
// as a prop OR returned by the producer must degrade to a legible fallback
// (every NEW seam stubbed; an empty selectable list) — never blank/throw.

// Coerce any value to the per-outcome action booleans, strictly (=== true).
// A null/non-object `actions` (or a missing one) keeps every NEW seam stubbed,
// matching COCKPIT_UNAVAILABLE's honest "seam not live" state.
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
// only the kind-agnostic DeferForm + CalibrationCapture.
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

interface Props {
  /** Tests/preview may inject a known capability to bypass the fetch — mirrors
   *  HumanTodoPanel's `attest` override idiom. When provided, no fetch runs. */
  availability?: CockpitAvailability;
  /** Tests/preview may inject the selectable inbox items to bypass the fetch.
   *  The INBOX panel itself still renders from its own props (see below). */
  items?: HumanTodoItem[];
}

export default function Todo({ availability, items }: Props) {
  // One capability fetch feeds every stub form's `available` prop. The override
  // wins (tests inject it); otherwise fetch once and degrade to UNAVAILABLE on
  // failure (a missing endpoint keeps every NEW seam in its honest stub state).
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

  // The selectable item list backing the RESOLUTION AREA's chosen item. The
  // INBOX panel below self-polls its own copy; this small fetch only drives the
  // resolution pointer. Override wins for tests.
  const [todoItems, setTodoItems] = useState<HumanTodoItem[]>(safeItems(items));
  useEffect(() => {
    if (items !== undefined) return;
    let live = true;
    getHumanTodo()
      .then((resp) => {
        // resp is producer-owned + cast (getJSON does no shape check): a
        // non-array `items` (or a malformed element) is coerced/dropped, never
        // forwarded to .find/.map below.
        if (live) setTodoItems(safeItems(resp?.items));
      })
      .catch(() => {
        if (live) setTodoItems([]);
      });
    return () => {
      live = false;
    };
  }, [items]);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected =
    todoItems.find((it) => it.id === selectedId) ?? todoItems[0] ?? null;

  // The ORDERING CONTRACT, per-item: calibration must be captured BEFORE the
  // resolution forms appear. Tracked by the captured item id so switching items
  // re-gates the forms (each item's verdict is preceded by its own calibration).
  const [calibratedId, setCalibratedId] = useState<string | null>(null);
  const calibrated = selected !== null && calibratedId === selected.id;

  // `caps` may be an injected/legacy availability prop that bypassed
  // asAvailability (the fetch path's coercion) — a null/non-object or a missing
  // `actions` must keep every NEW seam stubbed, not crash on `actions.<flag>`.
  const actions = safeActions(caps);

  // U5 kind-gate: which form family `selected.id` is keyed for. ITERATION-keyed
  // forms get an iteration_id; FINDING-keyed forms + the aux panes get a
  // finding_id; an "other" kind (bubble_ack, state_file_gate, stale_active_run,
  // unknown) gets neither family — only the kind-agnostic DeferForm +
  // CalibrationCapture. This is what stops a finding_id from ever reaching
  // GateVerdictForm (or an iteration_id reaching the finding-keyed forms).
  const kindClass = selected !== null ? classifyKind(selected.kind) : "other";

  return (
    <div className="mx-auto max-w-7xl p-5" data-testid="todo-cockpit">
      <header className="mb-3">
        <h1 className="text-sm font-semibold uppercase tracking-wide text-zinc-300">
          /todo · uncertainty-resolution cockpit
        </h1>
        <p className="mt-0.5 text-[11px] text-zinc-500">
          Where Nara escalates what it is unsure about and you resolve it. The
          NEW resolution outcomes are STUBS until the cockpit seams land
          (docs/todo_cockpit_seam_plan.md) — they surface their would-run argv
          read-only and write nothing.
        </p>
      </header>

      {/* 1) shared-models warn/queue guard — self-fetches; self-hides when idle. */}
      <ConcurrencyWarning />

      {/* 2) the INBOX — HumanTodoPanel's new home. Its blessed forms live inside. */}
      <section className="mt-3" data-testid="todo-inbox">
        <div className="mb-1 text-[10px] uppercase tracking-wide text-zinc-600">
          inbox · what needs resolving
        </div>
        <HumanTodoPanel initial={items} />
      </section>

      {/* 3) the RESOLUTION AREA for a selected item. */}
      <section className="mt-4" data-testid="todo-resolution-area">
        <div className="mb-1 text-[10px] uppercase tracking-wide text-zinc-600">
          resolve a selected item
        </div>

        {selected === null ? (
          <div data-testid="todo-no-selection" className="text-[11px] text-zinc-500">
            nothing to resolve — the inbox is empty.
          </div>
        ) : (
          <div className="space-y-3">
            {/* selection pointer (the panel does not emit selection — keep a
                thin chooser here so the resolution forms know their target). */}
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[10px] uppercase tracking-wide text-zinc-600">
                resolving
              </span>
              {todoItems.map((it) => (
                <button
                  key={it.id}
                  type="button"
                  aria-pressed={it.id === selected.id}
                  onClick={() => setSelectedId(it.id)}
                  className={`rounded border px-1.5 py-0.5 text-[10px] ${
                    it.id === selected.id
                      ? "border-sky-700 bg-sky-950 text-sky-300"
                      : "border-zinc-800 bg-zinc-950 text-zinc-500 hover:text-zinc-300"
                  }`}
                >
                  {it.id}
                </button>
              ))}
            </div>

            {/* THE ORDERING CONTRACT: calibration FIRST. */}
            <CalibrationCapture
              key={`calib-${selected.id}`}
              findingId={selected.id}
              available={actions.calibration}
              onCaptured={() => setCalibratedId(selected.id)}
            />

            {!calibrated ? (
              <div
                data-testid="resolution-locked"
                className="rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1.5 text-[11px] text-zinc-500"
              >
                capture your pre-verdict calibration above to unlock the
                resolution forms (ARCH §6.5.4 — calibration before verdict).
              </div>
            ) : (
              <div data-testid="resolution-forms" className="space-y-2">
                {/* U5 KIND-GATE: an ITERATION item (gate_verdict) carries an
                    iteration_id → only the iteration-keyed forms; a FINDING item
                    (finding_review) carries a finding_id → only the finding-keyed
                    forms. selected.id is never crossed into the wrong family. */}
                {kindClass === "iteration" && (
                  <>
                    {/* outcome 1 (bare) + outcome 2 (reject) — the blessed
                        gate-verdict form: valid = sign off, invalid = reject.
                        WANTS an iteration_id. */}
                    <GateVerdictForm iterationId={selected.id} />

                    {/* outcome 1 variant — sign off WITH a directive (stub). The
                        note is the sign-off's audit note; left to the form here.
                        WANTS an iteration_id. */}
                    <DirectiveSignOffField
                      iterationId={selected.id}
                      note="signed off via /todo cockpit"
                      available={actions.directive_signoff}
                    />
                  </>
                )}

                {kindClass === "finding" && (
                  <>
                    {/* outcome 2 (finding reject path) — the blessed
                        finding-review form. WANTS a finding_id. */}
                    <FindingReviewForm findingId={selected.id} />

                    {/* outcome 4 — refine, authorize an autonomous fix (stub,
                        gated). WANTS a finding_id. */}
                    <AuthorizeFixForm
                      findingId={selected.id}
                      available={actions.authorize_fix}
                    />

                    {/* outcome 5 — spawn a follow-up topic (stub). WANTS a
                        finding_id. */}
                    <SpawnTopicForm
                      findingId={selected.id}
                      available={actions.spawn_topic}
                    />

                    {/* outcome 6 — abstain, the honest no-verdict exit (stub).
                        WANTS a finding_id. */}
                    <AbstainForm findingId={selected.id} available={actions.abstain} />
                  </>
                )}

                {/* outcome 3 — refine, defer to a dev session (blessed). Already
                    kind-aware (DeferForm renders nothing for an unknown kind), so
                    it renders for ALL kinds — the one in-UI action even for the
                    "other" kinds whose direct resolution stays primary-session. */}
                <DeferForm kind={selected.kind} refId={selected.id} />
              </div>
            )}
          </div>
        )}
      </section>

      {/* 4) two-voice interrogation (gated) + tutor (FENCED from the verdict).
          U5 KIND-GATE: aux panes are FINDING-keyed (they interrogate / explain a
          finding), so they render ONLY for a finding_review item. selected.id is
          therefore always a real finding_id here — never the empty-string id a
          non-finding selection used to feed them, and never an iteration_id. */}
      {selected !== null && kindClass === "finding" && (
        <section className="mt-4 grid gap-3 md:grid-cols-2" data-testid="todo-aux">
          <TwoVoiceChatPane
            findingId={selected.id}
            available={actions.two_voice_chat}
          />
          {/* The tutor is handed NO verdict props — it cannot influence or
              auto-fill a verdict (D-044 independence; rule 4). */}
          <TutorPanel findingId={selected.id} title={selected.title ?? undefined} />
        </section>
      )}
    </div>
  );
}
