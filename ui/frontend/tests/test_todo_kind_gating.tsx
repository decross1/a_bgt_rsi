// test_todo_kind_gating — the /todo cockpit's U5 KIND-GATE (src/routes/Todo.tsx).
// THE BUG this pins closed: Todo.tsx used to pass selected.id into EVERY
// resolution form unconditionally, so a finding_id reached GateVerdictForm
// (which wants an iteration_id) and an iteration_id reached the finding-keyed
// forms + the aux panes (which want a finding_id). The fix gates the forms by
// selected.kind so selected.id is never crossed into the wrong family.
//
// S2 REFRAME (cockpit model, 2026-06-19): the FORCED calibration gate is GONE.
// The kind-gated resolution forms render UNCONDITIONALLY on selection — there is
// NO resolution-locked element anymore. Calibration is OPTIONAL + PER-ID (a Set:
// once recorded for an id it is never re-prompted on switch-away-and-back). The
// interactive aux trio (tutor-panel overview + tutor-chat-pane + two-voice-chat-
// pane, wrapped in todo-aux-interactive) is REVEAL-gated, not calibration-gated:
// for a finding item a reveal-interrogation button is shown, and clicking it
// mounts the trio. The kind-gate INVARIANT is unchanged in intent.
//
// The contract this suite holds (work order PART U5, + the 2026-06-30 work order
// that makes gate-verdict ITERATIONS interrogable):
//   - gate_verdict (ITERATION item, selected.id is an iteration_id) →
//       GateVerdictForm renders and is the ONLY disposition;
//       FindingReviewForm / DirectiveSignOff / AuthorizeFix / SpawnTopic /
//       Abstain are ABSENT.
//       AUX (2026-06-30): an INTERROGATE section + reveal-interrogation button
//       ARE now present (iterations are interrogable — the backend chat seam
//       accepts an iter-* id); clicking reveal mounts the aux trio (TwoVoice +
//       TutorChat + Tutor) keyed to the iter-id. THE FENCE HOLDS: the chat is
//       decision SUPPORT only — no verdict/disposition is reachable from it; the
//       sole iteration disposition stays GateVerdictForm.
//   - finding_review (FINDING item, selected.id is a finding_id) →
//       the finding-keyed form set renders; an INTERROGATE section with a
//       reveal-interrogation button is present; clicking it mounts the aux trio
//       (TwoVoice + TutorChat + Tutor) keyed to the real finding_id;
//       GateVerdictForm is ABSENT.
//   - any OTHER kind (bubble_ack / state_gate / …) → NEITHER keyed family;
//       only DeferForm + CalibrationCapture; NO aux at any phase.
//   - DeferForm + CalibrationCapture render for ALL kinds. The resolution FORMS
//       render immediately on selection (no calibration prerequisite); the aux
//       trio renders only AFTER the reveal-interrogation click (finding OR
//       iteration kind).
//
// Network is stubbed by URL (mirrors test_todo_route.tsx). Crucially, the
// attest capability probe answers LIVE (gate_verdict + finding_review + defer
// true) so the self-gating GateVerdictForm / FindingReviewForm / DeferForm
// actually render their form testids — letting us assert their presence AND
// absence by testid rather than via the attest-unavailable fallback. The attest
// capability is cached per page-load, so we reset it between tests.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import Todo from "../src/routes/Todo";
import { AVAILABILITY_LIVE } from "../src/fixtures/todo";
import { resetAttestCapabilityCache } from "../src/api/attest";
import type { HumanTodoItem } from "../src/types/schemas";

// Items, one per kind under test. selected.id reads as an iteration_id for the
// gate_verdict item and a finding_id for the finding_review item — the very
// distinction the gate enforces.
const GATE_VERDICT_ITEM: HumanTodoItem = {
  kind: "gate_verdict",
  id: "iter-2026-06-14-002",
  title: "Verdict needed: novel_on_02 over-gated by primary R0",
};
const FINDING_REVIEW_ITEM: HumanTodoItem = {
  kind: "finding_review",
  id: "sf-2026-06-14-001",
  title: "Finding: shading is dominated under VCG (survives 2/3)",
};
const BUBBLE_ACK_ITEM: HumanTodoItem = {
  kind: "bubble_unacked",
  id: "bubble-2026-06-14-001",
  title: "Bubble: coordinator raised a degraded-signal note",
};
const STATE_GATE_ITEM: HumanTodoItem = {
  kind: "state_file_gate",
  id: "gate-d049-ratification",
  title: "State-file gate: D-049 scheduled cycles await ratification",
};

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: String(status),
    json: async () => body,
  } as unknown as Response;
}

beforeEach(() => {
  vi.stubGlobal("fetch", async (url: unknown) => {
    const u = String(url);
    if (u.endsWith("/api/todo/concurrency")) return jsonResponse(200, { active: false });
    if (u.endsWith("/api/human_todo")) return jsonResponse(200, { items: [], counts: {} });
    // LIVE attest capability so the self-gating forms (gate_verdict /
    // finding_review / defer) render their form testids rather than the
    // attest-unavailable fallback — we want to assert presence/absence by id.
    if (u.endsWith("/api/attest/available"))
      return jsonResponse(200, {
        available: true,
        actions: {
          gate_verdict: true,
          finding_review: true,
          bubble_ack: true,
          defer: true,
        },
      });
    // The tutor (finding kind) self-fetches the finding detail — answer found:false
    // so it degrades in place; it still renders the tutor-panel chrome.
    if (u.includes("/api/finding/"))
      return jsonResponse(200, { found: false, finding_id: "x" });
    if (u.includes("/api/todo/"))
      return jsonResponse(200, { status: "stub", would_run: ["<read-only>"] });
    return jsonResponse(404, {});
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  // The attest capability is cached module-level per page-load; reset it so a
  // live-capability test does not leak into the next.
  resetAttestCapabilityCache();
});

function renderTodo(item: HumanTodoItem) {
  return render(
    <MemoryRouter initialEntries={["/todo"]}>
      <Todo availability={AVAILABILITY_LIVE} items={[item]} />
    </MemoryRouter>,
  );
}

// S2 REFRAME helper — record an OPTIONAL blind calibration for the CURRENT
// selection. Calibration NO LONGER reveals the forms (they are already present);
// it only records the per-id flag and flips CalibrationCapture into its
// "recorded" state. The button label is "record blind calibration" now (was
// "capture calibration -> open verdict"); the recorded copy is "blind
// calibration recorded for this item." (was "the verdict form is now open").
async function recordCalibration() {
  // Calibration capture is always present once an item is selected.
  expect(screen.getByTestId("calibration-capture")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText(/calibration prediction/i), {
    target: { value: "survives the attack panel 2/3" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: /record blind calibration/i }),
  );
  await waitFor(() =>
    expect(screen.getByTestId("calibration-captured")).toBeInTheDocument(),
  );
  expect(
    screen.getByText(/blind calibration recorded for this item/i),
  ).toBeInTheDocument();
}

// S2 REFRAME helper — REVEAL the interactive interrogation trio for the current
// (finding) selection. The trio is reveal-gated, not calibration-gated: pre-click
// the trio is absent and the reveal-interrogation button is present; clicking it
// mounts todo-aux-interactive (tutor-panel + tutor-chat-pane + two-voice-chat-
// pane). Asserting the button presence first keeps this honest for finding kinds.
async function revealInterrogation() {
  const button = screen.getByTestId("reveal-interrogation");
  fireEvent.click(button);
  await waitFor(() =>
    expect(screen.getByTestId("todo-aux-interactive")).toBeInTheDocument(),
  );
}

// Select an inbox row by its item. The inbox selector button is labelled by the
// row's TITLE (HumanTodoPanel renders `title ?? id` in select mode), so we click
// by title and then confirm the workspace header now points at the item's id —
// the selection key the kind-gate routes on. Returns once the workspace reflects
// the new selection.
async function selectRow(item: HumanTodoItem) {
  const label = item.title ?? item.id;
  fireEvent.click(screen.getByRole("button", { name: label as string }));
  await waitFor(() =>
    expect(
      within(screen.getByTestId("todo-selected-item")).getByText(item.id as string),
    ).toBeInTheDocument(),
  );
}

describe("Todo cockpit — U5 kind-gate", () => {
  it("a gate_verdict (ITERATION) item shows the iteration-keyed forms ONLY", async () => {
    renderTodo(GATE_VERDICT_ITEM);

    // S2: the resolution forms render UNCONDITIONALLY — no calibration needed.
    await waitFor(() =>
      expect(screen.getByTestId("resolution-forms")).toBeInTheDocument(),
    );

    // ITERATION-keyed forms present (gate-verdict self-gates on the LIVE attest
    // capability — it resolves async, so waitFor its form testid).
    await waitFor(() =>
      expect(screen.getByTestId("gate-verdict-form")).toBeInTheDocument(),
    );

    // FINDING-keyed forms + aux ABSENT — no iteration_id reaches them.
    // directive-signoff is FINDING-keyed (it signs off a finding via
    // finding_session --set-status validated --directive; wiring doc 1d).
    expect(screen.queryByTestId("directive-signoff-field")).toBeNull();
    expect(screen.queryByTestId("finding-review-form")).toBeNull();
    expect(screen.queryByTestId("authorize-fix-form")).toBeNull();
    expect(screen.queryByTestId("spawn-topic-form")).toBeNull();
    expect(screen.queryByTestId("abstain-form")).toBeNull();
    // 2026-06-30: an iteration is now INTERROGABLE — the interrogate section +
    // reveal button ARE present, but the interactive trio stays hidden until the
    // reveal click. (The disposition is still GateVerdictForm only — the fence.)
    expectAuxRevealableTrioHidden();
    // Reveal → the trio mounts (keyed to the iter-id), and STILL no finding-keyed
    // disposition appears; GateVerdictForm remains the ONLY way to dispose.
    await revealInterrogation();
    expect(screen.getByTestId("two-voice-chat-pane")).toBeInTheDocument();
    expect(screen.getByTestId("tutor-panel")).toBeInTheDocument();
    expect(screen.queryByTestId("finding-review-form")).toBeNull();
    expect(screen.queryByTestId("directive-signoff-field")).toBeNull();
    expect(screen.getByTestId("gate-verdict-form")).toBeInTheDocument();

    // Kind-agnostic surfaces still present.
    await waitFor(() =>
      expect(screen.getByTestId("defer-form")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("calibration-capture")).toBeInTheDocument();
  });

  it("a finding_review (FINDING) item shows the finding-keyed forms + reveals aux", async () => {
    renderTodo(FINDING_REVIEW_ITEM);

    // S2: forms render unconditionally on selection (no calibration prereq).
    await waitFor(() =>
      expect(screen.getByTestId("finding-review-form")).toBeInTheDocument(),
    );
    // directive sign-off is a FINDING op (set-status validated --directive).
    expect(screen.getByTestId("directive-signoff-field")).toBeInTheDocument();
    expect(screen.getByTestId("authorize-fix-form")).toBeInTheDocument();
    expect(screen.getByTestId("spawn-topic-form")).toBeInTheDocument();
    expect(screen.getByTestId("abstain-form")).toBeInTheDocument();

    // The INTERROGATE section + reveal button are present (finding kind). The aux
    // trio is REVEAL-gated: absent until the reveal-interrogation click.
    expect(screen.getByTestId("todo-interrogate")).toBeInTheDocument();
    expect(screen.getByTestId("reveal-interrogation")).toBeInTheDocument();
    expect(screen.queryByTestId("todo-aux-interactive")).toBeNull();
    expect(screen.queryByTestId("two-voice-chat-pane")).toBeNull();
    expect(screen.queryByTestId("tutor-chat-pane")).toBeNull();
    expect(screen.queryByTestId("tutor-panel")).toBeNull();

    // Reveal → the trio mounts — selected.id here is a real finding_id.
    await revealInterrogation();
    expect(screen.getByTestId("two-voice-chat-pane")).toBeInTheDocument();
    expect(screen.getByTestId("tutor-chat-pane")).toBeInTheDocument();
    expect(screen.getByTestId("tutor-panel")).toBeInTheDocument();

    // ITERATION-keyed forms ABSENT — no finding_id reaches GateVerdictForm.
    expect(screen.queryByTestId("gate-verdict-form")).toBeNull();

    // Kind-agnostic surfaces still present.
    await waitFor(() =>
      expect(screen.getByTestId("defer-form")).toBeInTheDocument(),
    );
  });

  it("a bubble_ack (OTHER) item shows NEITHER keyed family — only Defer + Calibration", async () => {
    renderTodo(BUBBLE_ACK_ITEM);

    // S2: forms render unconditionally — but this is an OTHER kind, so neither
    // keyed family renders; the resolution-forms wrapper carries only Defer.
    await waitFor(() =>
      expect(screen.getByTestId("resolution-forms")).toBeInTheDocument(),
    );

    // Neither family renders.
    expect(screen.queryByTestId("gate-verdict-form")).toBeNull();
    expect(screen.queryByTestId("directive-signoff-field")).toBeNull();
    expect(screen.queryByTestId("finding-review-form")).toBeNull();
    expect(screen.queryByTestId("authorize-fix-form")).toBeNull();
    expect(screen.queryByTestId("spawn-topic-form")).toBeNull();
    expect(screen.queryByTestId("abstain-form")).toBeNull();
    // No aux of any kind for an OTHER kind — no interrogate section/button/trio.
    expect(screen.queryByTestId("todo-interrogate")).toBeNull();
    expect(screen.queryByTestId("reveal-interrogation")).toBeNull();
    expect(screen.queryByTestId("todo-aux-interactive")).toBeNull();
    expect(screen.queryByTestId("two-voice-chat-pane")).toBeNull();
    expect(screen.queryByTestId("tutor-panel")).toBeNull();

    // Defer (kind-aware) + Calibration DO render for the OTHER kinds.
    expect(screen.getByTestId("calibration-capture")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId("defer-form")).toBeInTheDocument(),
    );
  });

  it("a state_file_gate (OTHER) item likewise shows NEITHER keyed family", async () => {
    renderTodo(STATE_GATE_ITEM);

    await waitFor(() =>
      expect(screen.getByTestId("resolution-forms")).toBeInTheDocument(),
    );

    expect(screen.queryByTestId("gate-verdict-form")).toBeNull();
    expect(screen.queryByTestId("directive-signoff-field")).toBeNull();
    expect(screen.queryByTestId("finding-review-form")).toBeNull();
    expect(screen.queryByTestId("authorize-fix-form")).toBeNull();
    expect(screen.queryByTestId("spawn-topic-form")).toBeNull();
    expect(screen.queryByTestId("abstain-form")).toBeNull();
    expect(screen.queryByTestId("todo-interrogate")).toBeNull();
    expect(screen.queryByTestId("todo-aux-interactive")).toBeNull();

    // state_file_gate is a defer-ONLY kind — defer is its only in-UI action.
    await waitFor(() =>
      expect(screen.getByTestId("defer-form")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("defer-only-note")).toBeInTheDocument();
  });

  it("the kind-appropriate forms render UNCONDITIONALLY (the forced calibration gate is GONE)", async () => {
    // S2 reframe: a gate_verdict item shows the iteration-keyed form IMMEDIATELY —
    // there is NO resolution-locked element and the forms do NOT wait on
    // calibration. (This REPLACES the retired "forms are LOCKED until calibration"
    // ORDERING test: the positive assertion of the new behavior, same coverage.)
    renderTodo(GATE_VERDICT_ITEM);
    // resolution-forms is present from the start — no lock, no calibration step.
    expect(screen.getByTestId("resolution-forms")).toBeInTheDocument();
    expect(screen.queryByTestId("resolution-locked")).toBeNull();
    expect(screen.getByTestId("calibration-capture")).toBeInTheDocument();
    // The iteration-keyed form reveals once the attest capability resolves async —
    // NOT because any calibration was recorded.
    await waitFor(() =>
      expect(screen.getByTestId("gate-verdict-form")).toBeInTheDocument(),
    );

    // Recording the OPTIONAL calibration does NOT change which forms are present;
    // it only flips the capture into its recorded state. The form is still there.
    await recordCalibration();
    expect(screen.getByTestId("gate-verdict-form")).toBeInTheDocument();
    expect(screen.queryByTestId("resolution-locked")).toBeNull();
  });
});

// ===========================================================================
// ADVERSARIAL-VERIFY additions (independent auditor, 2026-06-17). The happy-path
// describe above exercises only the FOUR producer ENUM kinds. The invariant the
// gate exists to hold is sharper: "no iteration_id ever reaches a finding-keyed
// form and no finding_id ever reaches an iteration-keyed form" — and it must hold
// under HOSTILE producer-owned `kind` shapes (kind is cast unvalidated, the
// `items` prop bypasses every coercion). These blocks attack that invariant.
// ===========================================================================

// The keyed FORM testids, grouped by the family their id is keyed for. The
// invariant: for an "other"-classed kind NEITHER group renders; the two groups
// are mutually exclusive for the enum kinds. NOTE the aux PANES (tutor-panel /
// tutor-chat-pane / two-voice-chat-pane) are NOT in this list — under the reframe
// they are reveal-gated, not rendered on selection; their absence is asserted via
// the interrogate section + trio (see expectNoAux below), not as a keyed form.
const ITERATION_KEYED = ["gate-verdict-form"] as const;
const FINDING_KEYED = [
  "finding-review-form",
  "directive-signoff-field",
  "authorize-fix-form",
  "spawn-topic-form",
  "abstain-form",
] as const;

// The aux surfaces — the finding-only interrogate section, its reveal button, the
// revealed trio wrapper, and the three interactive panes. For an "other"/iteration
// kind NONE of these exist at any phase (there is no reveal button to even click).
const AUX_SURFACES = [
  "todo-interrogate",
  "reveal-interrogation",
  "todo-aux-interactive",
  "tutor-panel",
  "tutor-chat-pane",
  "two-voice-chat-pane",
] as const;

function expectNoKeyedForms() {
  for (const id of ITERATION_KEYED) expect(screen.queryByTestId(id)).toBeNull();
  for (const id of FINDING_KEYED) expect(screen.queryByTestId(id)).toBeNull();
}

function expectNoAux() {
  for (const id of AUX_SURFACES) expect(screen.queryByTestId(id)).toBeNull();
}

// The interactive trio (the panes the reveal click mounts) — distinct from the
// interrogate SECTION + reveal button, which are present for an interrogable
// (finding OR iteration) kind even pre-reveal.
const INTERACTIVE_TRIO = [
  "todo-aux-interactive",
  "tutor-panel",
  "tutor-chat-pane",
  "two-voice-chat-pane",
] as const;

// An interrogable kind (finding OR gate-verdict iteration) PRE-reveal: the
// interrogate section + reveal button are present, but the interactive trio is
// hidden until the reveal click. (For an "other"/hostile kind use expectNoAux —
// there is no interrogate section at all.)
function expectAuxRevealableTrioHidden() {
  expect(screen.getByTestId("todo-interrogate")).toBeInTheDocument();
  expect(screen.getByTestId("reveal-interrogation")).toBeInTheDocument();
  for (const id of INTERACTIVE_TRIO) expect(screen.queryByTestId(id)).toBeNull();
}

// Build a HumanTodoItem with a real string id but a hostile `kind`. The id is a
// VALID selection key (a non-empty string), so safeItems keeps the row and the
// gate is actually exercised on the kind — exactly the path we want to attack.
function itemWithKind(kind: unknown): HumanTodoItem {
  return {
    id: "iter-hostile-0001",
    kind: kind as HumanTodoItem["kind"],
    title: "hostile-kind probe row",
  } as HumanTodoItem;
}

describe("Todo cockpit — U5 kind-gate: HOSTILE kind values all route to OTHER", () => {
  // classifyKind must be a TOTAL function: only the two exact enum strings map to
  // a keyed family; EVERYTHING else (null/undefined/number/object/array/empty/
  // whitespace/wrong-case/unknown) is "other" and renders NEITHER keyed family —
  // only the kind-agnostic DeferForm + CalibrationCapture. A non-string kind that
  // slipped past would (a) crash on no comparison, or worse (b) accidentally key a
  // form with a finding_id↔iteration_id crossed. We prove NEITHER family renders,
  // AND that the finding-only aux (interrogate section/reveal/trio) never appears.
  const HOSTILE_KINDS: ReadonlyArray<readonly [string, unknown]> = [
    ["null", null],
    ["undefined", undefined],
    ["a number", 42],
    ["an object", { kind: "finding_review" }],
    ["an array", ["finding_review"]],
    ["empty string", ""],
    ["whitespace-padded finding_review", "  finding_review  "],
    ["wrong-case GATE_VERDICT", "GATE_VERDICT"],
    ["wrong-case Finding_Review", "Finding_Review"],
    ["an unknown string", "totally_made_up_kind"],
    ["a boolean", true],
  ];

  for (const [label, kind] of HOSTILE_KINDS) {
    it(`kind = ${label} → NEITHER keyed family renders, no crash`, async () => {
      renderTodo(itemWithKind(kind));
      // The row is selectable (id is a valid string) and the cockpit mounts. The
      // inbox selector button is labelled by the row's title (HumanTodoPanel
      // renders `title ?? id`); the SELECTED item's id surfaces in the workspace
      // header, proving the valid string id is the live selection key.
      expect(screen.getByTestId("todo-cockpit")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "hostile-kind probe row" })).toBeInTheDocument();
      expect(
        within(screen.getByTestId("todo-selected-item")).getByText("iter-hostile-0001"),
      ).toBeInTheDocument();

      // S2: the resolution-forms wrapper renders unconditionally — but for a
      // hostile (→"other") kind it carries NEITHER keyed family.
      await waitFor(() =>
        expect(screen.getByTestId("resolution-forms")).toBeInTheDocument(),
      );

      // THE INVARIANT: not one iteration-keyed NOR finding-keyed form rendered —
      // classifyKind sent the hostile kind to "other", so selected.id (which would
      // be neither a real iteration_id nor finding_id) is crossed into no family.
      expectNoKeyedForms();
      // And the finding-only aux never appears — there is no reveal path for it.
      expectNoAux();

      // The kind-AGNOSTIC calibration capture still renders — the human is never
      // stranded on a blank cockpit. (DeferForm is NOT asserted here: it owns its
      // OWN frozen-enum gate — deferKindOf returns null for a kind outside its
      // alias map, so for these hostile kinds DeferForm correctly renders nothing.
      // That is DeferForm's contract, separately pinned in test_human_todo_panel /
      // the harden suite; the U5 invariant under test is the keyed-family gate.)
      expect(screen.getByTestId("calibration-capture")).toBeInTheDocument();
      // No "[object Object]"/garbage leaked into the DOM from a non-string kind.
      expect(screen.queryByText(/\[object Object\]/)).toBeNull();
    });
  }
});

describe("Todo cockpit — U5 kind-gate: aux panes get a NON-EMPTY real finding_id", () => {
  // THE OLD BUG this pins gone: the aux panes used to be handed `selected?.id ?? ""`
  // — an empty-string finding_id for a non-finding selection. Now they mount ONLY
  // for a real finding_review item, ONLY after the reveal-interrogation click, and
  // the id they receive is the item's real, non-empty finding_id. We prove the
  // value by READING it out of the DOM where each pane legitimately surfaces it
  // under LIVE availability:
  //   - TwoVoiceChatPane (two_voice_chat:true) renders "directed at both · <id>".
  //   - TutorPanel surfaces "(<id>)" in its unavailable branch (found:false stub).
  it("a finding_review item feeds the REAL finding_id to both aux panes (never \"\")", async () => {
    renderTodo(FINDING_REVIEW_ITEM); // id = "sf-2026-06-14-001"
    // Reveal the interrogation (the aux is reveal-gated, not calibration-gated).
    await revealInterrogation();

    // The revealed trio wrapper mounts (finding-keyed).
    const aux = await screen.findByTestId("todo-aux-interactive");

    // TwoVoiceChatPane: LIVE availability renders the real id after "· ".
    const twoVoice = within(aux).getByTestId("two-voice-chat-pane");
    expect(
      within(twoVoice).getByText(/directed at both · sf-2026-06-14-001/),
    ).toBeInTheDocument();
    // And NOT the empty-string fallback: "directed at both · " with nothing after.
    expect(within(twoVoice).queryByText(/directed at both · $/)).toBeNull();

    // TutorPanel: the unavailable branch echoes the real id in parentheses; an
    // empty id would have rendered the IDLE "Select a finding" state with no id.
    const tutor = await within(aux).findByTestId("tutor-panel");
    expect(within(tutor).getByText(/\(sf-2026-06-14-001\)/)).toBeInTheDocument();
    expect(within(tutor).queryByTestId("tutor-idle")).toBeNull();
  });

  // The mirror that makes the proof bite: for a NON-finding selection the aux
  // panes are ABSENT entirely (so the empty-string id can never be constructed —
  // the code path that built it is gone, not merely guarded). A gate_verdict item
  // carries an iteration_id; it must NEVER reach the finding-keyed aux, and there
  // is no reveal button to even attempt it.
  it("a gate_verdict item: the aux panes are fed its real iter-id (interrogation works; GateVerdictForm still the only disposition)", async () => {
    renderTodo(GATE_VERDICT_ITEM);
    await waitFor(() =>
      expect(screen.getByTestId("gate-verdict-form")).toBeInTheDocument(),
    );
    // 2026-06-30: an iteration is interrogable. Pre-reveal the interactive trio is
    // hidden; the interrogate section + reveal button are present.
    expectAuxRevealableTrioHidden();
    // Reveal → the trio mounts, fed the REAL iter-id "iter-2026-06-14-002" (a
    // non-empty id — never the old "" fallback). The two-voice pane echoes it
    // after "· ", exactly as it echoes a finding_id for a finding item.
    await revealInterrogation();
    const aux = await screen.findByTestId("todo-aux-interactive");
    const twoVoice = within(aux).getByTestId("two-voice-chat-pane");
    expect(
      within(twoVoice).getByText(/directed at both · iter-2026-06-14-002/),
    ).toBeInTheDocument();
    expect(within(twoVoice).queryByText(/directed at both · $/)).toBeNull();
    // THE FENCE: no finding-keyed disposition is reachable for the iteration —
    // GateVerdictForm remains the SOLE way to dispose of it (the chat is support).
    for (const id of FINDING_KEYED) expect(screen.queryByTestId(id)).toBeNull();
    expect(screen.getByTestId("gate-verdict-form")).toBeInTheDocument();
  });
});

describe("Todo cockpit — U5 kind-gate: selection SWITCHING unmounts the wrong family", () => {
  // Render TWO items of DIFFERENT kinds and switch between them. The forms must
  // track the CURRENT selection's kind: switching finding→gate must UNMOUNT the
  // finding-keyed forms + aux and MOUNT the iteration-keyed forms (and reverse).
  // A stale wrong-keyed form lingering would cross an id into the wrong family.
  // S2: the forms render UNCONDITIONALLY on selection — no calibration step between
  // switches. The reveal is per-id (a Set), so an aux reveal on one item does not
  // carry to a sibling of a different kind (the kind-gate excludes it anyway).
  function renderPair() {
    return render(
      <MemoryRouter initialEntries={["/todo"]}>
        <Todo
          availability={AVAILABILITY_LIVE}
          items={[FINDING_REVIEW_ITEM, GATE_VERDICT_ITEM]}
        />
      </MemoryRouter>,
    );
  }

  it("finding_review → gate_verdict: finding forms + aux UNMOUNT, iteration forms MOUNT", async () => {
    renderPair();
    // The first item (finding_review) is default-selected — its forms are present
    // immediately, and we reveal its aux trio.
    await waitFor(() =>
      expect(screen.getByTestId("finding-review-form")).toBeInTheDocument(),
    );
    await revealInterrogation();
    expect(screen.getByTestId("todo-aux-interactive")).toBeInTheDocument();

    // Switch to the gate_verdict item (selected by its inbox row title).
    await selectRow(GATE_VERDICT_ITEM);

    // Iteration-keyed form now mounts...
    await waitFor(() =>
      expect(screen.getByTestId("gate-verdict-form")).toBeInTheDocument(),
    );
    // ...EVERY finding-keyed surface (incl. directive-signoff) is GONE (no stale
    // lingering), and the finding's REVEALED trio unmounts on the switch. The gate
    // is itself interrogable, so its OWN interrogate section + reveal button are
    // present, but the trio is HIDDEN (reveal is per-id; the gate's id was never
    // revealed). The gate's disposition stays GateVerdictForm only.
    for (const id of FINDING_KEYED) expect(screen.queryByTestId(id)).toBeNull();
    expectAuxRevealableTrioHidden();
  });

  it("gate_verdict → finding_review: iteration forms UNMOUNT, finding forms + aux MOUNT", async () => {
    renderPair();
    // Switch to the gate_verdict item FIRST. It is interrogable (its own reveal
    // button), but its interactive trio is hidden until revealed.
    await selectRow(GATE_VERDICT_ITEM);
    await waitFor(() =>
      expect(screen.getByTestId("gate-verdict-form")).toBeInTheDocument(),
    );
    expectAuxRevealableTrioHidden();

    // Switch back to the finding_review item — its forms mount immediately.
    await selectRow(FINDING_REVIEW_ITEM);
    await waitFor(() =>
      expect(screen.getByTestId("finding-review-form")).toBeInTheDocument(),
    );
    // The interrogate section + reveal button are back; reveal mounts the trio.
    expect(screen.getByTestId("todo-interrogate")).toBeInTheDocument();
    await revealInterrogation();
    expect(screen.getByTestId("todo-aux-interactive")).toBeInTheDocument();
    expect(screen.getByTestId("two-voice-chat-pane")).toBeInTheDocument();
    // ...and the iteration-keyed forms are GONE.
    for (const id of ITERATION_KEYED) expect(screen.queryByTestId(id)).toBeNull();
  });
});

describe("Todo cockpit — U5 kind-gate: safeItems drops hostile finding rows", () => {
  // A finding_review row whose ID is hostile ("" / object / missing) must be
  // DROPPED by safeItems — it can never be selected, so its (would-be) finding_id
  // never reaches a finding-keyed form or the aux. We mix one such hostile
  // finding_review row with one VALID gate_verdict row and prove only the valid
  // one is selectable and NO finding-keyed surface ever renders.
  const HOSTILE_FINDING_ROWS: ReadonlyArray<readonly [string, unknown]> = [
    ["empty-string id", { kind: "finding_review", id: "", title: "bad finding" }],
    ["object id", { kind: "finding_review", id: { v: 1 }, title: "bad finding" }],
    ["missing id", { kind: "finding_review", title: "bad finding" }],
    ["numeric id", { kind: "finding_review", id: 7, title: "bad finding" }],
  ];

  for (const [label, badRow] of HOSTILE_FINDING_ROWS) {
    it(`finding_review with ${label} is dropped; never reaches a finding form`, async () => {
      const validIter: HumanTodoItem = {
        kind: "gate_verdict",
        id: "iter-valid-0007",
        title: "the only selectable row",
      };
      render(
        <MemoryRouter initialEntries={["/todo"]}>
          <Todo
            availability={AVAILABILITY_LIVE}
            items={[badRow, validIter] as unknown as HumanTodoItem[]}
          />
        </MemoryRouter>,
      );
      // Only the valid iteration row is selectable — the hostile finding was
      // dropped. The selector button is labelled by the row's title; the valid
      // row's title button is present and the dropped finding's title button is
      // not, and the workspace header points at the valid row's id.
      expect(screen.getByRole("button", { name: "the only selectable row" })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "bad finding" })).toBeNull();
      expect(
        within(screen.getByTestId("todo-selected-item")).getByText("iter-valid-0007"),
      ).toBeInTheDocument();

      // The (default-selected) valid row is an ITERATION → finding-keyed surfaces
      // are absent, AND the dropped finding never injected one either. The
      // iteration's OWN interrogate aux is revealable (trio hidden pre-reveal) —
      // that aux belongs to the iteration, not the dropped finding (which is gone).
      await waitFor(() =>
        expect(screen.getByTestId("gate-verdict-form")).toBeInTheDocument(),
      );
      for (const id of FINDING_KEYED) expect(screen.queryByTestId(id)).toBeNull();
      expectAuxRevealableTrioHidden();
    });
  }

  it("a lone hostile finding_review row (empty id) leaves the cockpit with NO selection", () => {
    render(
      <MemoryRouter initialEntries={["/todo"]}>
        <Todo
          availability={AVAILABILITY_LIVE}
          items={[{ kind: "finding_review", id: "" }] as unknown as HumanTodoItem[]}
        />
      </MemoryRouter>,
    );
    // Dropped → empty selectable list → honest no-selection, no forms, no aux.
    expect(screen.getByTestId("todo-no-selection")).toBeInTheDocument();
    expect(screen.queryByTestId("calibration-capture")).toBeNull();
    expect(screen.queryByTestId("two-voice-chat-pane")).toBeNull();
    expect(screen.queryByTestId("tutor-panel")).toBeNull();
  });
});

// The kind-appropriate RESOLUTION FORMS — the verdict-bearing forms. S2 reframe:
// these render UNCONDITIONALLY on selection (the forced calibration gate is GONE).
// This is the "resolution forms" set the shell renders (Todo.tsx resolution-forms
// block), as DISTINCT from the aux trio (the reveal-gated interrogation panes).
const FINDING_VERDICT_FORMS = [
  "finding-review-form",
  "authorize-fix-form",
  "spawn-topic-form",
  "abstain-form",
] as const;

describe("Todo cockpit — U5 kind-gate: forms render unconditionally for BOTH kinds", () => {
  // S2 reframe: the kind-APPROPRIATE RESOLUTION FORMS render IMMEDIATELY on
  // selection for EACH kind — there is NO resolution-locked element and NO
  // calibration prerequisite. (REPLACES the retired "LOCKED until calibration"
  // ORDERING tests with the positive assertion of the new unconditional behavior;
  // the kind-gate coverage — which family renders for which kind — is preserved.)
  it("a finding_review item: the finding RESOLUTION FORMS render unconditionally", async () => {
    renderTodo(FINDING_REVIEW_ITEM);
    // Present from the start — no lock, no calibration step.
    expect(screen.getByTestId("resolution-forms")).toBeInTheDocument();
    expect(screen.queryByTestId("resolution-locked")).toBeNull();
    expect(screen.getByTestId("calibration-capture")).toBeInTheDocument();

    // The finding-keyed verdict forms are all present without any calibration.
    await waitFor(() =>
      expect(screen.getByTestId("finding-review-form")).toBeInTheDocument(),
    );
    for (const id of FINDING_VERDICT_FORMS) expect(screen.getByTestId(id)).toBeInTheDocument();

    // Recording the OPTIONAL calibration leaves the forms in place (no toggle).
    await recordCalibration();
    for (const id of FINDING_VERDICT_FORMS) expect(screen.getByTestId(id)).toBeInTheDocument();
    expect(screen.queryByTestId("resolution-locked")).toBeNull();
  });

  it("an iteration (gate_verdict) item: iteration-keyed form renders unconditionally", async () => {
    renderTodo(GATE_VERDICT_ITEM);
    expect(screen.getByTestId("resolution-forms")).toBeInTheDocument();
    expect(screen.queryByTestId("resolution-locked")).toBeNull();
    expect(screen.getByTestId("calibration-capture")).toBeInTheDocument();

    await waitFor(() =>
      expect(screen.getByTestId("gate-verdict-form")).toBeInTheDocument(),
    );
    // directive-signoff is finding-keyed — absent for a gate_verdict item.
    expect(screen.queryByTestId("directive-signoff-field")).toBeNull();

    await recordCalibration();
    expect(screen.getByTestId("gate-verdict-form")).toBeInTheDocument();
    expect(screen.queryByTestId("resolution-locked")).toBeNull();
  });

  // The interactive aux trio is REVEAL-gated (NOT calibration-gated). For a
  // finding item the static-overview tutor now lives INSIDE the revealed trio
  // (it is no longer shown pre-reveal). Pre-reveal: the reveal button is present
  // and the trio (tutor-panel overview + tutor-chat-pane + two-voice-chat-pane) is
  // absent; after the reveal click the trio mounts. (REPLACES the retired D-054
  // "pre-calibration tutor overview shows / interactive unlocks after calibration"
  // contract: the gate is now the reveal click, not calibration.)
  it("RESOLVED: the interactive aux trio is REVEAL-gated, not calibration-gated", async () => {
    renderTodo(FINDING_REVIEW_ITEM);
    // Forms render unconditionally (finding-review self-gates on the LIVE attest
    // capability, which resolves async — waitFor it; the rest are synchronous).
    expect(screen.getByTestId("resolution-forms")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId("finding-review-form")).toBeInTheDocument(),
    );
    for (const id of FINDING_VERDICT_FORMS) expect(screen.getByTestId(id)).toBeInTheDocument();
    // ...the interrogate section + reveal button are present...
    expect(screen.getByTestId("todo-interrogate")).toBeInTheDocument();
    expect(screen.getByTestId("reveal-interrogation")).toBeInTheDocument();
    // ...but NOTHING in the trio (including the static tutor overview) is mounted
    // yet — the trio is reveal-gated and the tutor now lives inside it.
    expect(screen.queryByTestId("todo-aux-interactive")).toBeNull();
    expect(screen.queryByTestId("tutor-panel")).toBeNull();
    expect(screen.queryByTestId("two-voice-chat-pane")).toBeNull();
    expect(screen.queryByTestId("tutor-chat-pane")).toBeNull();

    // After the REVEAL click (no calibration involved), the trio mounts in full.
    await revealInterrogation();
    expect(screen.getByTestId("todo-aux-interactive")).toBeInTheDocument();
    expect(screen.getByTestId("tutor-panel")).toBeInTheDocument();
    expect(screen.getByTestId("two-voice-chat-pane")).toBeInTheDocument();
    expect(screen.getByTestId("tutor-chat-pane")).toBeInTheDocument();
  });

  // The MIRROR for an iteration item: NO aux at any phase (the aux is finding-
  // keyed). So the iteration_id is fenced from the aux — no interrogate section,
  // no reveal button, and recording calibration cannot conjure one.
  it("an iteration item: aux is reveal-gated (interrogable); GateVerdictForm stays the sole disposition", async () => {
    renderTodo(GATE_VERDICT_ITEM);
    // 2026-06-30: iterations gained the interrogation aux. Pre-calibration: reveal
    // button present, interactive trio hidden.
    expectAuxRevealableTrioHidden();
    await recordCalibration();
    await waitFor(() =>
      expect(screen.getByTestId("gate-verdict-form")).toBeInTheDocument(),
    );
    // Recording calibration does NOT reveal the trio (the reveal-gate is
    // independent of calibration).
    expectAuxRevealableTrioHidden();
    // Reveal → the trio mounts; the disposition is STILL GateVerdictForm only (no
    // finding-keyed form, no verdict path from the chat — the fence holds).
    await revealInterrogation();
    expect(screen.getByTestId("todo-aux-interactive")).toBeInTheDocument();
    for (const id of FINDING_KEYED) expect(screen.queryByTestId(id)).toBeNull();
    expect(screen.getByTestId("gate-verdict-form")).toBeInTheDocument();
  });
});

// ===========================================================================
// ADVERSARIAL-VERIFY additions, ROUND 2 (independent auditor, 2026-06-18,
// REWORKED for the S2 reframe 2026-06-19). The aux REVEAL-gate (Todo.tsx
// interrogate block): for a finding_review item the interrogate section + a
// reveal-interrogation button render on selection, but the INTERACTIVE trio
// (todo-aux-interactive wrapper + tutor-panel + tutor-chat-pane + two-voice-
// chat-pane) mounts ONLY after the reveal click. The OLD D-054 calibration-gate
// is GONE — the trio gates on the REVEAL click, not on calibration. The reveal
// is tracked PER ID (a Set), so it STICKS across a switch-away-and-back (it does
// NOT re-lock). These blocks attack the reveal-gate where it is most likely to
// leak: SELECTION SWITCHING between two FINDINGS, the gate's INDEPENDENCE from the
// kind-gate, and the trio's total absence under HOSTILE kinds.
// ===========================================================================

// A SECOND finding_review item, distinct id, so we can switch between two findings
// and prove the reveal-gate is tracked PER ID. Its id is a real, non-empty
// finding_id.
const FINDING_REVIEW_ITEM_B: HumanTodoItem = {
  kind: "finding_review",
  id: "sf-2026-06-15-009",
  title: "Finding: equilibrium shading persists under second-price tie-break",
};

// The INTERACTIVE aux trio — the panes the reveal-interrogation click mounts. The
// static tutor-panel OVERVIEW now lives INSIDE the trio (it is no longer shown
// pre-reveal), so it is part of this set. A leak of ANY of these pre-reveal would
// break the "blind if used" protection the reveal-gate preserves.
const AUX_INTERACTIVE = [
  "todo-aux-interactive",
  "tutor-panel",
  "tutor-chat-pane",
  "two-voice-chat-pane",
] as const;

function expectInteractiveHidden() {
  for (const id of AUX_INTERACTIVE) expect(screen.queryByTestId(id)).toBeNull();
}
function expectInteractiveRevealed() {
  for (const id of AUX_INTERACTIVE) expect(screen.getByTestId(id)).toBeInTheDocument();
}

describe("Todo cockpit — aux REVEAL-gate: hidden trio vs revealed interactive panes", () => {
  // The crisp single-selection contract, asserted on the FULL interactive trio.
  // PRE-reveal: the interrogate section + reveal button are up, the trio absent.
  // POST-reveal: the interactive trio mounts in full. (REWORKED from the retired
  // D-054 calibration-gate: the gate is the REVEAL click now, not calibration.)
  it("finding pre-reveal: reveal button shows, trio absent; post-reveal: trio mounts", async () => {
    renderTodo(FINDING_REVIEW_ITEM);

    // PRE-reveal: the interrogate section + reveal button are up...
    expect(screen.getByTestId("todo-interrogate")).toBeInTheDocument();
    expect(screen.getByTestId("reveal-interrogation")).toBeInTheDocument();
    // ...but NONE of the interactive trio exists yet.
    expectInteractiveHidden();
    // The verdict forms render unconditionally (no lock) — the reveal-gate is
    // independent of them.
    expect(screen.getByTestId("resolution-forms")).toBeInTheDocument();
    expect(screen.queryByTestId("resolution-locked")).toBeNull();

    await revealInterrogation();

    // POST-reveal: the interactive trio mounts in full.
    expectInteractiveRevealed();
    // The reveal button is consumed (the trio replaces it).
    expect(screen.queryByTestId("reveal-interrogation")).toBeNull();
  });

  // INDEPENDENCE of the reveal-gate from the kind-gate: an ITERATION item has NO
  // aux at all (kind-gate excludes it) — so there is no interrogate section, no
  // reveal button, and the trio never appears at ANY phase, even after recording
  // calibration. This proves the two gates compose: the kind-gate decides IF aux
  // exists, the reveal-gate decides WHEN the trio mounts.
  it("an iteration item IS interrogable: interrogate section present, trio reveal-gated (gates compose)", async () => {
    renderTodo(GATE_VERDICT_ITEM);
    // Pre: the iteration is interrogable — interrogate section + reveal present,
    // trio hidden. The kind-gate now ALLOWS aux for an iteration (as for a
    // finding); the reveal-gate controls WHEN the trio mounts — the gates compose.
    expect(screen.getByTestId("todo-interrogate")).toBeInTheDocument();
    expect(screen.getByTestId("reveal-interrogation")).toBeInTheDocument();
    expectInteractiveHidden();

    await recordCalibration();
    await waitFor(() =>
      expect(screen.getByTestId("gate-verdict-form")).toBeInTheDocument(),
    );
    // Calibration does not reveal the trio (the reveal-gate is independent).
    expectInteractiveHidden();

    // Reveal → the trio mounts; GateVerdictForm stays the sole disposition (fence).
    await revealInterrogation();
    expectInteractiveRevealed();
    expect(screen.getByTestId("gate-verdict-form")).toBeInTheDocument();
    for (const id of FINDING_KEYED) expect(screen.queryByTestId(id)).toBeNull();
  });
});

describe("Todo cockpit — aux REVEAL-gate: PER-ID reveal STICKS across finding↔finding switch", () => {
  function renderTwoFindings() {
    return render(
      <MemoryRouter initialEntries={["/todo"]}>
        <Todo
          availability={AVAILABILITY_LIVE}
          items={[FINDING_REVIEW_ITEM, FINDING_REVIEW_ITEM_B]}
        />
      </MemoryRouter>,
    );
  }

  // The sharpest reveal-gate attack: TWO findings. Reveal finding A → A's trio
  // mounts, keyed to A's real finding_id. Switch to finding B (not yet revealed) →
  // B's trio is HIDDEN (the reveal is per-id, so A's reveal does NOT carry across)
  // and B shows its OWN reveal button. B's would-be trio carries B's REAL
  // finding_id — never A's, never "". Then reveal B → B's trio mounts.
  it("reveal finding A, switch to finding B: B's trio is HIDDEN until B is revealed", async () => {
    renderTwoFindings();

    // Finding A is default-selected. Pre-reveal: trio hidden, reveal button shown.
    expect(screen.getByTestId("reveal-interrogation")).toBeInTheDocument();
    expectInteractiveHidden();

    // Reveal A → A's interactive trio mounts, fed A's real finding_id.
    await revealInterrogation();
    expectInteractiveRevealed();
    {
      const twoVoiceA = screen.getByTestId("two-voice-chat-pane");
      expect(
        within(twoVoiceA).getByText(/directed at both · sf-2026-06-14-001/),
      ).toBeInTheDocument();
    }

    // Switch to finding B (selected by its inbox row title).
    await selectRow(FINDING_REVIEW_ITEM_B);

    // B is NOT yet revealed → the per-id reveal-gate keeps B's trio HIDDEN, even
    // though A was revealed. B shows its own reveal button.
    await waitFor(() =>
      expect(screen.getByTestId("reveal-interrogation")).toBeInTheDocument(),
    );
    expectInteractiveHidden();

    // Reveal B → NOW B's interactive trio mounts, fed B's real finding_id
    // (sf-2026-06-15-009), never A's (sf-2026-06-14-001), never "".
    await revealInterrogation();
    expectInteractiveRevealed();
    const twoVoiceB = screen.getByTestId("two-voice-chat-pane");
    expect(
      within(twoVoiceB).getByText(/directed at both · sf-2026-06-15-009/),
    ).toBeInTheDocument();
    // A's id must not appear in B's interactive pane (no stale-id leak on switch).
    expect(within(twoVoiceB).queryByText(/sf-2026-06-14-001/)).toBeNull();
  });

  // The round-trip that INVERTS the old single-slot semantics: the reveal is now a
  // per-id SET (flag-2), so a reveal STICKS. Reveal A, reveal B, switch BACK to A →
  // A STAYS revealed (the Set persists; no re-lock, no re-prompt). This pins the
  // per-id Set semantics so a future change is a DELIBERATE, visible edit. (This
  // INVERTS the retired "round trip A→B→A re-locks (single-slot)" test.)
  it("round trip A→B→A: A STAYS revealed (per-id Set persists, no re-lock)", async () => {
    renderTwoFindings();

    // Reveal A.
    await revealInterrogation();
    expectInteractiveRevealed();

    // Switch to B, reveal B → both ids are now in the revealed Set.
    await selectRow(FINDING_REVIEW_ITEM_B);
    await waitFor(() =>
      expect(screen.getByTestId("reveal-interrogation")).toBeInTheDocument(),
    );
    await revealInterrogation();
    expectInteractiveRevealed();

    // Switch BACK to A → A's id is STILL in the revealed Set, so A's trio is
    // immediately present again with NO re-reveal, NO reveal button.
    await selectRow(FINDING_REVIEW_ITEM);
    await waitFor(() =>
      expect(screen.getByTestId("todo-aux-interactive")).toBeInTheDocument(),
    );
    expectInteractiveRevealed();
    expect(screen.queryByTestId("reveal-interrogation")).toBeNull();
    // And it carries A's OWN id again (not B's) — no stale-id leak on return.
    const twoVoiceA = screen.getByTestId("two-voice-chat-pane");
    expect(
      within(twoVoiceA).getByText(/directed at both · sf-2026-06-14-001/),
    ).toBeInTheDocument();
    expect(within(twoVoiceA).queryByText(/sf-2026-06-15-009/)).toBeNull();
  });

  // CALIBRATION is the per-id INVERSE: the old "round-trip A→B→A re-LOCKS / re-
  // prompts calibration" assertion INVERTS — calibration is a per-id Set too, so
  // calibrating A then returning to A still shows "recorded" (NOT re-prompted).
  it("round trip A→B→A: A's calibration STAYS recorded (per-id Set, no re-prompt)", async () => {
    renderTwoFindings();

    // Record calibration for A → A shows the recorded state.
    await recordCalibration();
    expect(
      screen.getByText(/blind calibration recorded for this item/i),
    ).toBeInTheDocument();

    // Switch to B → B is NOT calibrated, so its capture form is re-presented
    // (the record button is back; no "recorded" copy for B yet).
    await selectRow(FINDING_REVIEW_ITEM_B);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /record blind calibration/i }),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText(/blind calibration recorded for this item/i)).toBeNull();
    await recordCalibration();

    // Switch BACK to A → A is STILL in the calibrated Set, so it shows "recorded"
    // and is NOT re-prompted (no record button for A).
    await selectRow(FINDING_REVIEW_ITEM);
    await waitFor(() =>
      expect(
        screen.getByText(/blind calibration recorded for this item/i),
      ).toBeInTheDocument(),
    );
    // The capture form is NOT re-presented for A (the per-id Set persists).
    expect(
      screen.queryByRole("button", { name: /record blind calibration/i }),
    ).toBeNull();
  });
});

describe("Todo cockpit — aux REVEAL-gate: hostile kinds NEVER mount the interactive trio", () => {
  // The kind-gate excludes the aux for any non-finding kind, so the reveal-gate's
  // interactive trio must be absent for a HOSTILE kind at BOTH phases — there is no
  // interrogate section and no reveal button to even click, and recording
  // calibration cannot conjure one. (The hostile-kind block above asserts the keyed
  // FORMS absent; this closes the aux-trio side, enumerating tutor-chat-pane + the
  // todo-aux-interactive wrapper a live chat-pane leak would otherwise slip past.)
  const HOSTILE_AUX_KINDS: ReadonlyArray<readonly [string, unknown]> = [
    ["null", null],
    ["an object spoofing finding_review", { kind: "finding_review" }],
    ["whitespace-padded finding_review", "  finding_review  "],
    ["wrong-case Finding_Review", "Finding_Review"],
    ["empty string", ""],
  ];

  for (const [label, kind] of HOSTILE_AUX_KINDS) {
    it(`kind = ${label} → no interactive aux trio pre- OR post-calibration`, async () => {
      renderTodo(itemWithKind(kind));
      // Pre: no interrogate section, no reveal button, no trio.
      expect(screen.queryByTestId("todo-interrogate")).toBeNull();
      expect(screen.queryByTestId("reveal-interrogation")).toBeNull();
      expectInteractiveHidden();

      // Even AFTER recording calibration, the trio must stay absent (the kind-gate
      // excludes the aux entirely; calibration cannot conjure it, nor is there a
      // reveal button to click).
      await recordCalibration();
      expect(screen.queryByTestId("todo-interrogate")).toBeNull();
      expect(screen.queryByTestId("reveal-interrogation")).toBeNull();
      expectInteractiveHidden();
      // The kind-agnostic calibration capture is still present (never stranded).
      expect(screen.getByTestId("calibration-capture")).toBeInTheDocument();
    });
  }
});
