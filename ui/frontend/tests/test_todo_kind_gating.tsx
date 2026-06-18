// test_todo_kind_gating — the /todo cockpit's U5 KIND-GATE (src/routes/Todo.tsx).
// THE BUG this pins closed: Todo.tsx used to pass selected.id into EVERY
// resolution form unconditionally, so a finding_id reached GateVerdictForm
// (which wants an iteration_id) and an iteration_id reached the finding-keyed
// forms + the aux panes (which want a finding_id). The fix gates the forms by
// selected.kind so selected.id is never crossed into the wrong family.
//
// The contract this suite holds (work order PART U5):
//   - gate_verdict (ITERATION item, selected.id is an iteration_id) →
//       GateVerdictForm + DirectiveSignOffField render;
//       FindingReviewForm / AuthorizeFix / SpawnTopic / Abstain / TwoVoice /
//       Tutor are ABSENT.
//   - finding_review (FINDING item, selected.id is a finding_id) →
//       the finding-keyed set + TwoVoice + Tutor render;
//       GateVerdictForm + DirectiveSignOffField are ABSENT.
//   - any OTHER kind (bubble_ack / state_gate / …) → NEITHER keyed family;
//       only DeferForm + CalibrationCapture.
//   - DeferForm + CalibrationCapture render for ALL kinds. Calibration is the
//       pre-verdict ORDERING gate: it is captured FIRST and the kind-appropriate
//       forms appear only after onCaptured fires (that gate is unchanged).
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

// Drive the ORDERING gate open: calibration is captured FIRST, which reveals the
// kind-appropriate resolution forms (the gate itself is kind-agnostic).
async function captureCalibration() {
  // Calibration capture is always present once an item is selected.
  expect(screen.getByTestId("calibration-capture")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText(/calibration prediction/i), {
    target: { value: "survives the attack panel 2/3" },
  });
  fireEvent.click(screen.getByRole("button", { name: /capture calibration/i }));
  await waitFor(() =>
    expect(screen.getByTestId("resolution-forms")).toBeInTheDocument(),
  );
}

describe("Todo cockpit — U5 kind-gate", () => {
  it("a gate_verdict (ITERATION) item shows the iteration-keyed forms ONLY", async () => {
    renderTodo(GATE_VERDICT_ITEM);
    await captureCalibration();

    // ITERATION-keyed forms present (gate-verdict self-gates on the LIVE attest
    // capability — it resolves async, so waitFor its form testid).
    await waitFor(() =>
      expect(screen.getByTestId("gate-verdict-form")).toBeInTheDocument(),
    );

    // FINDING-keyed forms + aux panes ABSENT — no iteration_id reaches them.
    // directive-signoff is now FINDING-keyed (it signs off a finding via
    // finding_session --set-status validated --directive; wiring doc 1d).
    expect(screen.queryByTestId("directive-signoff-field")).toBeNull();
    expect(screen.queryByTestId("finding-review-form")).toBeNull();
    expect(screen.queryByTestId("authorize-fix-form")).toBeNull();
    expect(screen.queryByTestId("spawn-topic-form")).toBeNull();
    expect(screen.queryByTestId("abstain-form")).toBeNull();
    expect(screen.queryByTestId("two-voice-chat-pane")).toBeNull();
    expect(screen.queryByTestId("tutor-panel")).toBeNull();
    expect(screen.queryByTestId("todo-aux")).toBeNull();

    // Kind-agnostic surfaces still present.
    await waitFor(() =>
      expect(screen.getByTestId("defer-form")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("calibration-capture")).toBeInTheDocument();
  });

  it("a finding_review (FINDING) item shows the finding-keyed forms + aux ONLY", async () => {
    renderTodo(FINDING_REVIEW_ITEM);
    await captureCalibration();

    // FINDING-keyed forms present (finding-review self-gates on the LIVE attest
    // capability — resolves async, so waitFor it; the three stub forms render
    // synchronously off the cockpit `available` prop).
    await waitFor(() =>
      expect(screen.getByTestId("finding-review-form")).toBeInTheDocument(),
    );
    // directive sign-off is a FINDING op (set-status validated --directive).
    expect(screen.getByTestId("directive-signoff-field")).toBeInTheDocument();
    expect(screen.getByTestId("authorize-fix-form")).toBeInTheDocument();
    expect(screen.getByTestId("spawn-topic-form")).toBeInTheDocument();
    expect(screen.getByTestId("abstain-form")).toBeInTheDocument();

    // Aux panes present — selected.id here is a real finding_id.
    expect(screen.getByTestId("todo-aux")).toBeInTheDocument();
    expect(screen.getByTestId("two-voice-chat-pane")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId("tutor-panel")).toBeInTheDocument(),
    );

    // ITERATION-keyed forms ABSENT — no finding_id reaches GateVerdictForm.
    expect(screen.queryByTestId("gate-verdict-form")).toBeNull();

    // Kind-agnostic surfaces still present.
    await waitFor(() =>
      expect(screen.getByTestId("defer-form")).toBeInTheDocument(),
    );
  });

  it("a bubble_ack (OTHER) item shows NEITHER keyed family — only Defer + Calibration", async () => {
    renderTodo(BUBBLE_ACK_ITEM);
    await captureCalibration();

    // Neither family renders.
    expect(screen.queryByTestId("gate-verdict-form")).toBeNull();
    expect(screen.queryByTestId("directive-signoff-field")).toBeNull();
    expect(screen.queryByTestId("finding-review-form")).toBeNull();
    expect(screen.queryByTestId("authorize-fix-form")).toBeNull();
    expect(screen.queryByTestId("spawn-topic-form")).toBeNull();
    expect(screen.queryByTestId("abstain-form")).toBeNull();
    expect(screen.queryByTestId("two-voice-chat-pane")).toBeNull();
    expect(screen.queryByTestId("tutor-panel")).toBeNull();
    expect(screen.queryByTestId("todo-aux")).toBeNull();

    // Defer (kind-aware) + Calibration DO render for the OTHER kinds.
    expect(screen.getByTestId("calibration-capture")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId("defer-form")).toBeInTheDocument(),
    );
  });

  it("a state_file_gate (OTHER) item likewise shows NEITHER keyed family", async () => {
    renderTodo(STATE_GATE_ITEM);
    await captureCalibration();

    expect(screen.queryByTestId("gate-verdict-form")).toBeNull();
    expect(screen.queryByTestId("directive-signoff-field")).toBeNull();
    expect(screen.queryByTestId("finding-review-form")).toBeNull();
    expect(screen.queryByTestId("authorize-fix-form")).toBeNull();
    expect(screen.queryByTestId("spawn-topic-form")).toBeNull();
    expect(screen.queryByTestId("abstain-form")).toBeNull();
    expect(screen.queryByTestId("todo-aux")).toBeNull();

    // state_file_gate is a defer-ONLY kind — defer is its only in-UI action.
    await waitFor(() =>
      expect(screen.getByTestId("defer-form")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("defer-only-note")).toBeInTheDocument();
  });

  it("ORDERING preserved: the kind-appropriate forms are LOCKED until calibration", async () => {
    // A gate_verdict item: before calibration the iteration-keyed forms are
    // absent (locked); the lock note + calibration capture show first.
    renderTodo(GATE_VERDICT_ITEM);
    expect(screen.queryByTestId("resolution-forms")).toBeNull();
    expect(screen.queryByTestId("gate-verdict-form")).toBeNull();
    expect(screen.getByTestId("resolution-locked")).toBeInTheDocument();
    expect(screen.getByTestId("calibration-capture")).toBeInTheDocument();

    // After calibration: the iteration-keyed form reveals (attest resolves async).
    await captureCalibration();
    await waitFor(() =>
      expect(screen.getByTestId("gate-verdict-form")).toBeInTheDocument(),
    );
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

// The keyed form testids, grouped by the family their id is keyed for. The
// invariant: for an "other"-classed kind NEITHER group renders; the two groups
// are mutually exclusive for the enum kinds.
const ITERATION_KEYED = ["gate-verdict-form"] as const;
const FINDING_KEYED = [
  "finding-review-form",
  "directive-signoff-field",
  "authorize-fix-form",
  "spawn-topic-form",
  "abstain-form",
  "two-voice-chat-pane",
  "tutor-panel",
] as const;

function expectNoKeyedForms() {
  for (const id of ITERATION_KEYED) expect(screen.queryByTestId(id)).toBeNull();
  for (const id of FINDING_KEYED) expect(screen.queryByTestId(id)).toBeNull();
  // The aux SECTION wrapper is also absent (it is finding-gated as a whole).
  expect(screen.queryByTestId("todo-aux")).toBeNull();
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
  // form with a finding_id↔iteration_id crossed. We prove NEITHER family renders.
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
      // The row is selectable (id is a valid string) and the cockpit mounts.
      expect(screen.getByTestId("todo-cockpit")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "iter-hostile-0001" })).toBeInTheDocument();
      await captureCalibration();

      // THE INVARIANT: not one iteration-keyed NOR finding-keyed form rendered —
      // classifyKind sent the hostile kind to "other", so selected.id (which would
      // be neither a real iteration_id nor finding_id) is crossed into no family.
      expectNoKeyedForms();

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
  // for a real finding_review item, and the id they receive is the item's real,
  // non-empty finding_id. We prove the value by READING it out of the DOM where
  // each pane legitimately surfaces it under LIVE availability:
  //   - TwoVoiceChatPane (two_voice_chat:true) renders "directed at both · <id>".
  //   - TutorPanel surfaces "(<id>)" in its unavailable branch (found:false stub).
  it("a finding_review item feeds the REAL finding_id to both aux panes (never \"\")", async () => {
    renderTodo(FINDING_REVIEW_ITEM); // id = "sf-2026-06-14-001"
    await captureCalibration();

    // Aux section mounts (finding-keyed).
    const aux = await screen.findByTestId("todo-aux");

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
  // carries an iteration_id; it must NEVER reach the finding-keyed aux.
  it("a gate_verdict item mounts NO aux pane — the iteration_id never reaches them", async () => {
    renderTodo(GATE_VERDICT_ITEM);
    await captureCalibration();
    await waitFor(() =>
      expect(screen.getByTestId("gate-verdict-form")).toBeInTheDocument(),
    );
    // No aux section, no panes — the iteration_id "iter-2026-06-14-002" is fenced
    // out of the finding-keyed family entirely.
    expect(screen.queryByTestId("todo-aux")).toBeNull();
    expect(screen.queryByTestId("two-voice-chat-pane")).toBeNull();
    expect(screen.queryByTestId("tutor-panel")).toBeNull();
    // And the iteration_id text never appears inside a (non-existent) tutor.
    expect(screen.queryByText(/\(iter-2026-06-14-002\)/)).toBeNull();
  });
});

describe("Todo cockpit — U5 kind-gate: selection SWITCHING unmounts the wrong family", () => {
  // Render TWO items of DIFFERENT kinds and switch between them. The forms must
  // track the CURRENT selection's kind: switching finding→gate must UNMOUNT the
  // finding-keyed forms + aux and MOUNT the iteration-keyed forms (and reverse).
  // A stale wrong-keyed form lingering would cross an id into the wrong family.
  // NOTE: switching to a not-yet-calibrated sibling RE-LOCKS the forms (per-item
  // ordering gate, pinned in test_harden_TodoShell), so we re-capture after each
  // switch before asserting the revealed family.
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
    // The first item (finding_review) is default-selected. Calibrate → finding set.
    await captureCalibration();
    await waitFor(() =>
      expect(screen.getByTestId("finding-review-form")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("todo-aux")).toBeInTheDocument();

    // Switch to the gate_verdict item (its id is the chooser button label).
    fireEvent.click(screen.getByRole("button", { name: "iter-2026-06-14-002" }));
    // Per-item ordering gate re-locks; re-capture to reveal the new family.
    await waitFor(() =>
      expect(screen.getByTestId("resolution-locked")).toBeInTheDocument(),
    );
    await captureCalibration();

    // Iteration-keyed forms now mount...
    await waitFor(() =>
      expect(screen.getByTestId("gate-verdict-form")).toBeInTheDocument(),
    );
    // ...and EVERY finding-keyed surface (incl. directive-signoff now) + the aux
    // is GONE (no stale lingering).
    for (const id of FINDING_KEYED) expect(screen.queryByTestId(id)).toBeNull();
    expect(screen.queryByTestId("todo-aux")).toBeNull();
  });

  it("gate_verdict → finding_review: iteration forms UNMOUNT, finding forms + aux MOUNT", async () => {
    renderPair();
    // Switch to the gate_verdict item FIRST and calibrate it.
    fireEvent.click(screen.getByRole("button", { name: "iter-2026-06-14-002" }));
    await captureCalibration();
    await waitFor(() =>
      expect(screen.getByTestId("gate-verdict-form")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("todo-aux")).toBeNull();

    // Switch back to the finding_review item.
    fireEvent.click(screen.getByRole("button", { name: "sf-2026-06-14-001" }));
    await waitFor(() =>
      expect(screen.getByTestId("resolution-locked")).toBeInTheDocument(),
    );
    await captureCalibration();

    // Finding-keyed forms + aux now mount...
    await waitFor(() =>
      expect(screen.getByTestId("finding-review-form")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("todo-aux")).toBeInTheDocument();
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
      // Only the valid iteration row is selectable — the hostile finding was dropped.
      expect(screen.getByRole("button", { name: "iter-valid-0007" })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "bad finding" })).toBeNull();
      await captureCalibration();

      // The (default-selected) valid row is an ITERATION → finding-keyed surfaces
      // are absent, AND the dropped finding never injected one either.
      await waitFor(() =>
        expect(screen.getByTestId("gate-verdict-form")).toBeInTheDocument(),
      );
      for (const id of FINDING_KEYED) expect(screen.queryByTestId(id)).toBeNull();
      expect(screen.queryByTestId("todo-aux")).toBeNull();
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

// The kind-appropriate RESOLUTION FORMS — the verdict-bearing forms that the
// pre-verdict ordering gate (ARCH §6.5.4) locks behind calibration. This is the
// "six resolution forms" set the shell gates (Todo.tsx block 3), as DISTINCT from
// the aux panes (block 4 — two-voice + tutor), which are NOT inside that gate (see
// the documented-as-built observation below). For a finding item the verdict
// FORMS are the four finding-keyed forms; the aux is intentionally separate.
const FINDING_VERDICT_FORMS = [
  "finding-review-form",
  "authorize-fix-form",
  "spawn-topic-form",
  "abstain-form",
] as const;

describe("Todo cockpit — U5 kind-gate: calibration ORDERING holds for BOTH kinds", () => {
  // The pre-verdict ordering gate (calibration FIRST) must lock the kind-
  // APPROPRIATE RESOLUTION FORMS for EACH kind, not just gate_verdict. Before
  // calibration: resolution-locked shows, resolution-forms is absent, and no
  // verdict-bearing form of the selected kind's family is present.
  it("a finding_review item: the finding RESOLUTION FORMS are LOCKED until calibration", async () => {
    renderTodo(FINDING_REVIEW_ITEM);
    // Pre-calibration: locked; the verdict-bearing finding forms are all absent.
    expect(screen.getByTestId("resolution-locked")).toBeInTheDocument();
    expect(screen.queryByTestId("resolution-forms")).toBeNull();
    for (const id of FINDING_VERDICT_FORMS) expect(screen.queryByTestId(id)).toBeNull();
    expect(screen.getByTestId("calibration-capture")).toBeInTheDocument();

    // After calibration: the finding-keyed verdict forms reveal.
    await captureCalibration();
    await waitFor(() =>
      expect(screen.getByTestId("finding-review-form")).toBeInTheDocument(),
    );
    for (const id of FINDING_VERDICT_FORMS) expect(screen.getByTestId(id)).toBeInTheDocument();
    expect(screen.queryByTestId("resolution-locked")).toBeNull();
  });

  it("an iteration (gate_verdict) item: iteration-keyed forms are LOCKED until calibration", async () => {
    renderTodo(GATE_VERDICT_ITEM);
    expect(screen.getByTestId("resolution-locked")).toBeInTheDocument();
    expect(screen.queryByTestId("resolution-forms")).toBeNull();
    for (const id of ITERATION_KEYED) expect(screen.queryByTestId(id)).toBeNull();
    expect(screen.getByTestId("calibration-capture")).toBeInTheDocument();

    await captureCalibration();
    await waitFor(() =>
      expect(screen.getByTestId("gate-verdict-form")).toBeInTheDocument(),
    );
    // directive-signoff is finding-keyed now — absent for a gate_verdict item.
    expect(screen.queryByTestId("directive-signoff-field")).toBeNull();
    expect(screen.queryByTestId("resolution-locked")).toBeNull();
  });

  // ── DOCUMENTED AS-BUILT BEHAVIOR (flagged, not silently blessed) ───────────
  // FINDING this verifier surfaces: for a finding_review item the aux panes
  // (two-voice interrogation + tutor, Todo.tsx block 4) render BEFORE calibration
  // is captured — they are gated ONLY by `selected !== null && kindClass ===
  // "finding"`, NOT by `calibrated`. The four verdict FORMS (asserted above) ARE
  // locked; only the aux is not. The U5 kind-gate invariant is intact (the aux is
  // finding-keyed and receives a real finding_id — never an iteration_id, never
  // "").  Whether the aux SHOULD also sit behind the pre-verdict calibration gate
  // is a SEPARATE contract (ARCH §6.5.4 scopes the ordering lock to "the verdict
  // form opens"; the work-order 2026-06-14 PART 2 lists the aux as a distinct
  // affordance, and Todo.tsx's header scopes the gate to "the six resolution
  // forms"). This test PINS the current behavior so a future change to it is
  // deliberate and visible; the contamination-risk note is in the report's
  // residual_risks for the human/primary to rule on — it is NOT silently "fixed"
  // here (would invent a contract the spec does not state, inviolate rule 8) nor
  // silently accepted.
  it("RESOLVED: pre-calibration the tutor OVERVIEW renders; the INTERACTIVE aux gates on calibration (D-054)", async () => {
    // Resolution of the 2026-06-17 aux-vs-calibration flag: the static tutor
    // OVERVIEW is the BASIS for the calibration prediction, so it is visible
    // PRE-calibration; the INTERACTIVE panes (live tutor chat + two-voice
    // interrogation) are decision-support that could bias the pre-verdict
    // calibration signal §6.5.4 measures, so they unlock only AFTER calibration.
    renderTodo(FINDING_REVIEW_ITEM);
    // Pre-calibration: verdict forms locked...
    expect(screen.getByTestId("resolution-locked")).toBeInTheDocument();
    expect(screen.queryByTestId("resolution-forms")).toBeNull();
    for (const id of FINDING_VERDICT_FORMS) expect(screen.queryByTestId(id)).toBeNull();
    // ...the tutor OVERVIEW (the prediction basis) IS shown...
    expect(screen.getByTestId("todo-aux")).toBeInTheDocument();
    expect(screen.getByTestId("tutor-panel")).toBeInTheDocument();
    // ...but the INTERACTIVE interrogation panes are NOT yet rendered.
    expect(screen.queryByTestId("todo-aux-interactive")).toBeNull();
    expect(screen.queryByTestId("two-voice-chat-pane")).toBeNull();
    expect(screen.queryByTestId("tutor-chat-pane")).toBeNull();

    // After calibration, the interactive interrogation unlocks.
    await captureCalibration();
    expect(screen.getByTestId("todo-aux-interactive")).toBeInTheDocument();
    expect(screen.getByTestId("two-voice-chat-pane")).toBeInTheDocument();
    expect(screen.getByTestId("tutor-chat-pane")).toBeInTheDocument();
  });

  // The MIRROR for an iteration item: NO aux pane renders pre- OR post-calibration
  // (the aux is finding-keyed). So the iteration_id is fenced from the aux at every
  // phase — the documented aux-pre-calibration behavior cannot cross an iteration_id.
  it("an iteration item renders NO aux pane at any phase (iteration_id fenced from aux)", async () => {
    renderTodo(GATE_VERDICT_ITEM);
    expect(screen.queryByTestId("todo-aux")).toBeNull(); // pre-calibration
    await captureCalibration();
    await waitFor(() =>
      expect(screen.getByTestId("gate-verdict-form")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("todo-aux")).toBeNull(); // post-calibration
    expect(screen.queryByTestId("two-voice-chat-pane")).toBeNull();
  });
});

// ===========================================================================
// ADVERSARIAL-VERIFY additions, ROUND 2 (independent auditor, 2026-06-18).
// The D-054 aux calibration-gate (Todo.tsx block 4): for a finding_review item
// the static tutor OVERVIEW (testid tutor-panel) renders PRE-calibration, but the
// INTERACTIVE panes (todo-aux-interactive wrapper + tutor-chat-pane + two-voice-
// chat-pane) mount ONLY after calibration is captured. The existing "RESOLVED"
// test pins the single-selection phase transition; these blocks attack the gate
// where it is most likely to leak: SELECTION SWITCHING between two FINDINGS (the
// per-item ordering must RE-LOCK the interactive panes on a not-yet-calibrated
// sibling), the gate's INDEPENDENCE from the kind-gate, and the interactive panes'
// total absence (not just two-voice but the tutor-chat-pane + the wrapper) under
// HOSTILE kinds. The interactive trio is distinct from the static tutor-panel and
// must be enumerated as such — the FINDING_KEYED list above carries tutor-panel,
// NOT tutor-chat-pane, so a leak of the live chat pane would slip past it.
// ===========================================================================

// A SECOND finding_review item, distinct id, so we can switch between two findings
// and prove the calibration-gate is tracked PER ITEM (calibrating A must not leave
// B's interactive panes unlocked). Its id is a real, non-empty finding_id.
const FINDING_REVIEW_ITEM_B: HumanTodoItem = {
  kind: "finding_review",
  id: "sf-2026-06-15-009",
  title: "Finding: equilibrium shading persists under second-price tie-break",
};

// The INTERACTIVE aux trio — the panes D-054 gates behind calibration. Distinct
// from the static tutor-panel OVERVIEW (which renders pre-cal). A leak of ANY of
// these pre-calibration is the contamination D-054 forbids.
const AUX_INTERACTIVE = [
  "todo-aux-interactive",
  "tutor-chat-pane",
  "two-voice-chat-pane",
] as const;

function expectInteractiveLocked() {
  for (const id of AUX_INTERACTIVE) expect(screen.queryByTestId(id)).toBeNull();
}
function expectInteractiveUnlocked() {
  for (const id of AUX_INTERACTIVE) expect(screen.getByTestId(id)).toBeInTheDocument();
}

describe("Todo cockpit — D-054 aux calibration-gate: static overview vs interactive panes", () => {
  // The crisp single-selection contract, asserted on the FULL interactive trio
  // (the RESOLVED test omits the todo-aux-interactive wrapper from its pre-cal
  // absence check and never asserts tutor-chat-pane's presence post-cal alongside
  // the wrapper). PRE-cal: tutor-panel overview present, interactive trio absent.
  // POST-cal: the SAME tutor-panel overview still present AND the interactive trio
  // mounts. The static overview never disappears — it is the calibration BASIS.
  it("finding pre-cal: tutor OVERVIEW shows, interactive trio absent; post-cal: trio mounts, overview persists", async () => {
    renderTodo(FINDING_REVIEW_ITEM);

    // PRE-calibration: the aux SECTION + the static overview are up...
    expect(screen.getByTestId("todo-aux")).toBeInTheDocument();
    expect(screen.getByTestId("tutor-panel")).toBeInTheDocument();
    // ...but NONE of the interactive panes (nor their grid wrapper) exist yet.
    expectInteractiveLocked();
    // The verdict forms are also still locked (the ordering gate is shut).
    expect(screen.getByTestId("resolution-locked")).toBeInTheDocument();

    await captureCalibration();

    // POST-calibration: the interactive trio mounts in full...
    expectInteractiveUnlocked();
    // ...and the static overview is STILL present (it was the prediction basis,
    // not a thing that toggles off when the interactive panes arrive).
    expect(screen.getByTestId("tutor-panel")).toBeInTheDocument();
    expect(screen.getByTestId("todo-aux")).toBeInTheDocument();
  });

  // INDEPENDENCE of the calibration-gate from the kind-gate: an ITERATION item
  // has NO aux at all (kind-gate excludes it) — so the calibration-gate has nothing
  // to gate. Neither the static overview NOR the interactive trio appears at ANY
  // phase. This proves the two gates compose: kind-gate decides IF aux exists,
  // calibration-gate decides WHEN the interactive subset of it unlocks.
  it("an iteration item: NO aux overview and NO interactive trio at either phase (gates compose)", async () => {
    renderTodo(GATE_VERDICT_ITEM);
    // Pre-cal: no aux section, no overview, no interactive trio.
    expect(screen.queryByTestId("todo-aux")).toBeNull();
    expect(screen.queryByTestId("tutor-panel")).toBeNull();
    expectInteractiveLocked();

    await captureCalibration();
    await waitFor(() =>
      expect(screen.getByTestId("gate-verdict-form")).toBeInTheDocument(),
    );
    // Post-cal: STILL no aux of any kind — the interactive panes never mount for
    // an iteration item even once calibration is captured.
    expect(screen.queryByTestId("todo-aux")).toBeNull();
    expect(screen.queryByTestId("tutor-panel")).toBeNull();
    expectInteractiveLocked();
  });
});

describe("Todo cockpit — D-054 aux calibration-gate: PER-ITEM re-lock across finding↔finding switch", () => {
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

  // The sharpest D-054 attack: TWO findings. Calibrate finding A → A's interactive
  // panes unlock. Switch to finding B (not yet calibrated) → the interactive panes
  // must RE-LOCK (the per-item ordering gate tracks calibratedId === selected.id,
  // so a calibrated sibling does NOT carry its unlock across). Crucially the static
  // tutor OVERVIEW for B still shows (it is the basis for B's own calibration) and
  // carries B's REAL finding_id — never A's, never "". Then calibrate B → B unlocks.
  it("calibrate finding A, switch to finding B: interactive panes RE-LOCK until B is calibrated", async () => {
    renderTwoFindings();

    // Finding A is default-selected. Pre-cal: interactive locked, overview shows.
    expect(screen.getByTestId("tutor-panel")).toBeInTheDocument();
    expectInteractiveLocked();

    // Calibrate A → A's interactive trio unlocks, fed A's real finding_id.
    await captureCalibration();
    expectInteractiveUnlocked();
    {
      const twoVoiceA = screen.getByTestId("two-voice-chat-pane");
      expect(
        within(twoVoiceA).getByText(/directed at both · sf-2026-06-14-001/),
      ).toBeInTheDocument();
    }

    // Switch to finding B (its id is the chooser button label).
    fireEvent.click(screen.getByRole("button", { name: "sf-2026-06-15-009" }));

    // B is NOT yet calibrated → the per-item gate RE-LOCKS the interactive panes,
    // even though A was calibrated. The verdict forms re-lock too.
    await waitFor(() =>
      expect(screen.getByTestId("resolution-locked")).toBeInTheDocument(),
    );
    expectInteractiveLocked();
    // But B's static OVERVIEW is shown (the basis for B's calibration) and carries
    // B's OWN finding_id — A's unlock did not leak A's id into B's aux.
    expect(screen.getByTestId("tutor-panel")).toBeInTheDocument();

    // Calibrate B → NOW B's interactive trio unlocks, fed B's real finding_id
    // (sf-2026-06-15-009), never A's (sf-2026-06-14-001), never "".
    await captureCalibration();
    expectInteractiveUnlocked();
    const twoVoiceB = screen.getByTestId("two-voice-chat-pane");
    expect(
      within(twoVoiceB).getByText(/directed at both · sf-2026-06-15-009/),
    ).toBeInTheDocument();
    // A's id must not appear in B's interactive pane (no stale-id leak on switch).
    expect(within(twoVoiceB).queryByText(/sf-2026-06-14-001/)).toBeNull();
  });

  // The reverse direction + a calibrated→calibrated round trip: switching BACK to
  // finding A (already calibrated earlier this render) must NOT auto-unlock — the
  // gate keys on the LAST captured id, and a switch away then back lands on the
  // most-recent calibratedId. We assert the deterministic current behavior: A
  // re-locks on return because calibratedId now points at B (only one slot). This
  // pins the single-slot calibratedId semantics so a future multi-slot change is
  // a DELIBERATE, visible edit.
  it("round trip A→B→A: returning to A re-locks (single-slot calibratedId semantics)", async () => {
    renderTwoFindings();

    // Calibrate A.
    await captureCalibration();
    expectInteractiveUnlocked();

    // Switch to B, calibrate B → calibratedId now points at B.
    fireEvent.click(screen.getByRole("button", { name: "sf-2026-06-15-009" }));
    await waitFor(() =>
      expect(screen.getByTestId("resolution-locked")).toBeInTheDocument(),
    );
    await captureCalibration();
    expectInteractiveUnlocked();

    // Switch BACK to A → calibratedId (=== B's id) !== A's id, so A re-locks.
    fireEvent.click(screen.getByRole("button", { name: "sf-2026-06-14-001" }));
    await waitFor(() =>
      expect(screen.getByTestId("resolution-locked")).toBeInTheDocument(),
    );
    expectInteractiveLocked();
    // A's static overview is back (basis for re-calibrating A).
    expect(screen.getByTestId("tutor-panel")).toBeInTheDocument();
  });
});

describe("Todo cockpit — D-054 aux calibration-gate: hostile kinds NEVER mount the interactive trio", () => {
  // The kind-gate excludes the aux for any non-finding kind, so the calibration-
  // gate's interactive trio must be absent for a HOSTILE kind at BOTH phases —
  // even after calibration is captured. (The hostile-kind block above asserts the
  // keyed FORMS absent and lists tutor-panel + two-voice-chat-pane, but does NOT
  // enumerate tutor-chat-pane or the todo-aux-interactive wrapper — a live tutor
  // chat pane leaking for a hostile kind would slip past it. We close that here.)
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
      // Pre-cal: no aux section, no interactive trio.
      expect(screen.queryByTestId("todo-aux")).toBeNull();
      expectInteractiveLocked();

      // Even AFTER calibration is captured, the interactive trio must stay absent
      // (the kind-gate excludes the aux entirely; calibration cannot conjure it).
      await captureCalibration();
      expect(screen.queryByTestId("todo-aux")).toBeNull();
      expectInteractiveLocked();
      // The kind-agnostic calibration capture is still present (never stranded).
      expect(screen.getByTestId("calibration-capture")).toBeInTheDocument();
    });
  }
});
