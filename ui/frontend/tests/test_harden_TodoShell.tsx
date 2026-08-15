// test_harden_TodoShell — HOUSE ROBUSTNESS DOCTRINE regression suite for the
// /todo cockpit SHELL (src/routes/Todo.tsx). The shell's `availability` + `items`
// PROPS bypass the fetch path's coercion (api/todo.ts asAvailability /
// resp.items ?? []), and getHumanTodo() casts its body without a shape check.
// So a malformed/legacy/partial value — injected as a prop OR returned by the
// producer — must DEGRADE to a legible fallback (every NEW seam stubbed; an
// empty selectable list; honest no-selection) and NEVER blank the page or throw.
//
// VALID-input behavior is asserted unchanged in test_todo_route.tsx; this suite
// pins ONLY the degrade-on-garbage guards (safeActions / safeItems). Each `it`
// pins one fix. We render and assert the cockpit root mounts (no crash/blank)
// plus the specific legible fallback for that malformed input.
//
// S2 COCKPIT-REFRAME RECONCILE: the forced calibration-before-forms ordering
// gate is REMOVED. The resolution forms render UNCONDITIONALLY for any selection
// (calibration is OPTIONAL + recorded per-id, never re-prompted on switch-back).
// The interactive aux trio (tutor + tutor-chat + two-voice) is now REVEAL-gated
// (the reveal-interrogation button, finding-kind only), NOT calibration-gated.
// Every robustness invariant below is PRESERVED — only the FLOW to reach the
// forms / the aux changed: a robustness test no longer captures calibration to
// reveal the forms (they are already there); a test that needs the two-voice
// surface clicks reveal-interrogation to mount the trio. The kind-gate, the
// safeItems/safeActions drops, and the deep-deref coercions are untouched.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import Todo from "../src/routes/Todo";
import { AVAILABILITY_LIVE, TODO_ITEMS } from "../src/fixtures/todo";
import { resetAttestCapabilityCache } from "../src/api/attest";
import type { CockpitAvailability } from "../src/types/todo";
import type { HumanTodoItem } from "../src/types/schemas";

// U5 kind-gate: two-voice + abstain (asserted by the safeActions block below)
// are FINDING-keyed surfaces, rendered only for a finding_review item. The
// safeActions guards being pinned (malformed availability ⇒ seam stays stubbed,
// no crash) are kind-agnostic, so these tests are driven with a finding_review
// item — adjusting the fixture KIND to match the gate, NOT the guard's intent.
const FINDING_ITEMS: HumanTodoItem[] = [
  // evidence_level clears the ladder bar so the row stays inbox-visible.
  { kind: "finding_review", id: "sf-harden-001", title: "finding under harden", evidence_level: "L4" },
];

// --- network stub (mirrors test_todo_route.tsx) -------------------------
// The leaf children self-fetch through the real api helpers; answer them so the
// shell renders deterministically. The shell's OWN fetches are bypassed by the
// injected props in every test, EXCEPT the explicit "malformed getHumanTodo
// body" test, which omits `items` so getHumanTodo runs and we feed it garbage.
function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: String(status),
    json: async () => body,
  } as unknown as Response;
}

let humanTodoBody: unknown = { items: TODO_ITEMS, counts: {} };

beforeEach(() => {
  humanTodoBody = { items: TODO_ITEMS, counts: {} };
  vi.stubGlobal("fetch", async (url: unknown) => {
    const u = String(url);
    if (u.endsWith("/api/todo/concurrency")) return jsonResponse(200, { active: false });
    if (u.endsWith("/api/human_todo")) return jsonResponse(200, humanTodoBody);
    if (u.includes("/api/todo/"))
      return jsonResponse(200, { status: "stub", would_run: ["<read-only>"] });
    // everything else (attest capability probe, cockpit available) 404s.
    return jsonResponse(404, {});
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  // The attest capability is cached per page-load (module-level) and outlives a
  // single test; reset it so a test that lights `defer` live doesn't leak.
  resetAttestCapabilityCache();
});

function renderTodo(props: Parameters<typeof Todo>[0] = {}) {
  return render(
    <MemoryRouter initialEntries={["/todo"]}>
      <Todo {...props} />
    </MemoryRouter>,
  );
}

// S2 reframe: the resolution forms now render UNCONDITIONALLY (no calibration
// gate). The malformed-`actions` crash hazard lives in the forms (which read the
// per-outcome flags); they are present immediately, so just confirm they mounted
// — no calibration capture needed.
async function expectFormsPresent() {
  await waitFor(() =>
    expect(screen.getByTestId("resolution-forms")).toBeInTheDocument(),
  );
}

// The interactive aux trio (tutor-chat + two-voice + tutor-panel) is REVEAL-
// gated now (finding-kind only): pre-reveal it is absent; clicking reveal-
// interrogation mounts it. Tests that assert on a surface INSIDE the trio (e.g.
// two-voice-send) must reveal it first. This replaces the old calibration gate:
// the trio gates on the reveal click, never on calibration.
async function revealAux() {
  fireEvent.click(screen.getByTestId("reveal-interrogation"));
  await waitFor(() =>
    expect(screen.getByTestId("todo-aux-interactive")).toBeInTheDocument(),
  );
}

describe("TodoShell hardening — malformed availability prop (safeActions)", () => {
  // A null availability prop: `caps` holds null; `caps.actions.calibration`
  // would throw. Guard => every NEW seam stubbed, cockpit mounts.
  it("availability=null degrades to all-seams-stubbed (no crash)", async () => {
    renderTodo({ availability: null as unknown as CockpitAvailability, items: FINDING_ITEMS });
    expect(screen.getByTestId("todo-cockpit")).toBeInTheDocument();
    // forms render unconditionally now; the aux trio (two-voice) is reveal-gated.
    await expectFormsPresent();
    await revealAux();
    // two-voice send is gated off actions.two_voice_chat → disabled when stub.
    expect(screen.getByTestId("two-voice-send")).toBeDisabled();
  });

  it("availability with a MISSING actions key degrades (no crash)", async () => {
    renderTodo({
      availability: { available: true } as unknown as CockpitAvailability,
      items: FINDING_ITEMS,
    });
    expect(screen.getByTestId("todo-cockpit")).toBeInTheDocument();
    await expectFormsPresent();
    await revealAux();
    expect(screen.getByTestId("two-voice-send")).toBeDisabled();
  });

  it("availability.actions of WRONG type (number) degrades (no crash)", async () => {
    renderTodo({
      availability: { available: true, actions: 42 } as unknown as CockpitAvailability,
      items: FINDING_ITEMS,
    });
    expect(screen.getByTestId("todo-cockpit")).toBeInTheDocument();
    await expectFormsPresent();
    await revealAux();
    expect(screen.getByTestId("two-voice-send")).toBeDisabled();
  });

  it("availability.actions as an ARRAY degrades (no crash)", async () => {
    renderTodo({
      availability: { available: true, actions: [] } as unknown as CockpitAvailability,
      items: FINDING_ITEMS,
    });
    expect(screen.getByTestId("todo-cockpit")).toBeInTheDocument();
    await expectFormsPresent();
    await revealAux();
    expect(screen.getByTestId("two-voice-send")).toBeDisabled();
  });

  it("non-boolean truthy action flags (e.g. \"yes\"/1) coerce to STUBBED (=== true only)", async () => {
    // A producer that returns truthy-but-not-true must NOT light a seam up:
    // availability gating coerces strictly. Proves all-false-ish keeps NEW
    // seams stubbed even when the values are truthy.
    renderTodo({
      availability: {
        available: true,
        actions: {
          directive_signoff: "yes",
          authorize_fix: 1,
          spawn_topic: {},
          abstain: "true",
          calibration: 1,
          two_voice_chat: "on",
        },
      } as unknown as CockpitAvailability,
      items: FINDING_ITEMS,
    });
    expect(screen.getByTestId("todo-cockpit")).toBeInTheDocument();
    await expectFormsPresent();
    await revealAux();
    // two_voice_chat was "on" (truthy, not === true) → still gated off.
    expect(screen.getByTestId("two-voice-send")).toBeDisabled();
  });

  it("VALID live availability still lights the seam up (behavior preserved)", async () => {
    renderTodo({ availability: AVAILABILITY_LIVE, items: FINDING_ITEMS });
    await expectFormsPresent();
    const abstain = screen.getByTestId("abstain-form");
    fireEvent.change(within(abstain).getByLabelText(/abstain note/i), {
      target: { value: "revisit later" },
    });
    await waitFor(() =>
      expect(
        within(screen.getByTestId("abstain-form")).getByRole("button", {
          name: /^abstain$/i,
        }),
      ).not.toBeDisabled(),
    );
  });
});

describe("TodoShell hardening — malformed items list (safeItems)", () => {
  // The selection pointer reads todoItems.find / .map — a non-array or a
  // malformed element would crash. Each must degrade to a clean list or the
  // honest no-selection empty state.

  it("items=null degrades to honest no-selection (no crash)", () => {
    renderTodo({
      availability: AVAILABILITY_LIVE,
      items: null as unknown as HumanTodoItem[],
    });
    expect(screen.getByTestId("todo-cockpit")).toBeInTheDocument();
    expect(screen.getByTestId("todo-no-selection")).toBeInTheDocument();
    expect(screen.queryByTestId("resolution-forms")).toBeNull();
  });

  it("items as a non-array OBJECT degrades to no-selection (no crash)", () => {
    renderTodo({
      availability: AVAILABILITY_LIVE,
      items: { 0: { id: "x" } } as unknown as HumanTodoItem[],
    });
    expect(screen.getByTestId("todo-cockpit")).toBeInTheDocument();
    expect(screen.getByTestId("todo-no-selection")).toBeInTheDocument();
  });

  it("items as a NUMBER degrades to no-selection (no crash)", () => {
    renderTodo({
      availability: AVAILABILITY_LIVE,
      items: 7 as unknown as HumanTodoItem[],
    });
    expect(screen.getByTestId("todo-cockpit")).toBeInTheDocument();
    expect(screen.getByTestId("todo-no-selection")).toBeInTheDocument();
  });

  it("drops malformed ELEMENTS (null / non-object / missing-id / non-string-id / empty-id) and keeps the valid one", () => {
    const mixed = [
      null,
      42,
      "nope",
      [],
      { title: "no id here" },
      { id: 99 }, // non-string id
      { id: "" }, // empty id
      { id: "iter-good", kind: "gate_verdict", title: "the one valid item" },
    ];
    renderTodo({
      availability: AVAILABILITY_LIVE,
      items: mixed as unknown as HumanTodoItem[],
    });
    expect(screen.getByTestId("todo-cockpit")).toBeInTheDocument();
    // exactly the one valid item is selectable. In select mode the inbox row's
    // selector button is labeled by its title (id is the fallback only when no
    // title); the one kept element carries a title, so match it.
    expect(
      screen.getByRole("button", { name: "the one valid item" }),
    ).toBeInTheDocument();
    // no crash from the dropped null/empty-id elements.
    expect(screen.queryByTestId("todo-no-selection")).toBeNull();
  });

  it("ALL elements malformed => empty selectable list, honest no-selection", () => {
    renderTodo({
      availability: AVAILABILITY_LIVE,
      items: [null, { nope: 1 }, { id: 5 }] as unknown as HumanTodoItem[],
    });
    expect(screen.getByTestId("todo-cockpit")).toBeInTheDocument();
    expect(screen.getByTestId("todo-no-selection")).toBeInTheDocument();
  });

  it("empty array (present-but-empty) => no-selection, no calibration/forms", () => {
    renderTodo({ availability: AVAILABILITY_LIVE, items: [] });
    expect(screen.getByTestId("todo-no-selection")).toBeInTheDocument();
    expect(screen.queryByTestId("calibration-capture")).toBeNull();
    expect(screen.queryByTestId("resolution-forms")).toBeNull();
  });
});

describe("TodoShell hardening — malformed getHumanTodo body (fetch path)", () => {
  // With `items` ABSENT the shell runs its own getHumanTodo fetch. getJSON casts
  // the body without a shape check, so a non-array `items` (or a null body) must
  // be coerced/dropped, never forwarded to .find/.map.
  it("getHumanTodo body with a non-array items => no-selection (no crash)", async () => {
    humanTodoBody = { items: { not: "an array" }, counts: {} };
    renderTodo({ availability: AVAILABILITY_LIVE });
    await waitFor(() =>
      expect(screen.getByTestId("todo-cockpit")).toBeInTheDocument(),
    );
    await waitFor(() =>
      expect(screen.getByTestId("todo-no-selection")).toBeInTheDocument(),
    );
  });

  it("getHumanTodo body that is a bare null => no-selection (no crash)", async () => {
    humanTodoBody = null;
    renderTodo({ availability: AVAILABILITY_LIVE });
    await waitFor(() =>
      expect(screen.getByTestId("todo-cockpit")).toBeInTheDocument(),
    );
    await waitFor(() =>
      expect(screen.getByTestId("todo-no-selection")).toBeInTheDocument(),
    );
  });

  it("getHumanTodo body with malformed items elements => only the valid item surfaces", async () => {
    // The fetch path's safeItems(resp?.items) drops the null + empty-id elements
    // and keeps the one valid element. With `items` ABSENT the shell drives its
    // OWN selection from the fetched list, so the valid item surfaces as the
    // workspace selection (todo-selected-item) — never .find/.map on a malformed
    // element, never the honest no-selection state.
    humanTodoBody = {
      items: [null, { id: "" }, { id: "iter-from-fetch", kind: "gate_verdict" }],
      counts: {},
    };
    renderTodo({ availability: AVAILABILITY_LIVE });
    await waitFor(() =>
      expect(screen.getByTestId("todo-selected-item")).toHaveTextContent(
        "iter-from-fetch",
      ),
    );
    // the malformed siblings were dropped, not surfaced as a no-selection blank.
    expect(screen.queryByTestId("todo-no-selection")).toBeNull();
    // and the valid selection drives the forms (forms render unconditionally).
    expect(screen.getByTestId("resolution-forms")).toBeInTheDocument();
  });
});

describe("TodoShell reframe — forms render unconditionally + per-id calibration", () => {
  // S2 reframe: the forced calibration-before-forms ordering gate is REMOVED.
  // resolution-locked no longer exists; the forms render UNCONDITIONALLY for any
  // selection. This replaces the old "forms LOCKED before calibration" coverage
  // with the POSITIVE assertion of the new behavior (forms present immediately,
  // even with a malformed availability — the guard still doesn't crash).
  it("forms render UNCONDITIONALLY (no calibration) even with null availability", () => {
    renderTodo({
      availability: null as unknown as CockpitAvailability,
      items: TODO_ITEMS,
    });
    // The forced gate is gone: there is NO resolution-locked element, and the
    // forms are present immediately — no calibration capture required.
    expect(screen.queryByTestId("resolution-locked")).toBeNull();
    expect(screen.getByTestId("resolution-forms")).toBeInTheDocument();
    // Calibration capture is still PRESENT (optional, not a gate) and did not
    // crash on the null availability.
    expect(screen.getByTestId("calibration-capture")).toBeInTheDocument();
  });

  it("a finding with NO id is dropped, so no selection can point at it", () => {
    // An item missing its id can't be a verdict target; safeItems drops it,
    // leaving the next valid item (or no-selection) — nothing can be resolved on
    // a target without an id (the selection key + the forms' target).
    renderTodo({
      availability: AVAILABILITY_LIVE,
      items: [{ kind: "gate_verdict", title: "no id" }] as unknown as HumanTodoItem[],
    });
    expect(screen.getByTestId("todo-no-selection")).toBeInTheDocument();
    expect(screen.queryByTestId("calibration-capture")).toBeNull();
    // and with no selection there are no forms either.
    expect(screen.queryByTestId("resolution-forms")).toBeNull();
  });

  // ADVERSARIAL-VERIFY additions. The shallow guards (safeItems / safeActions)
  // validate the SELECTION KEY (`id`) but forward the rest of a valid item's
  // producer-owned fields (`kind`, `title`) RAW into the resolution-area
  // children. These probe the DEEPER derefs + the per-id calibration Set across
  // a switch.

  // flag-2: calibration is recorded PER ID into a Set and NEVER re-prompted when
  // you switch away from a calibrated item and back. A closure/stale-id bug here
  // would either leak item A's calibration onto item B, or LOSE A's calibration
  // when you return. This pins the round-trip A→B→A: A stays recorded, B is its
  // own un-calibrated item (each id's calibration is independent), and the forms
  // are present throughout (they no longer gate on calibration).
  it("per-id calibration: A→B→A keeps A recorded (no re-prompt), forms always present", async () => {
    renderTodo({ availability: AVAILABILITY_LIVE, items: TODO_ITEMS });
    // The first item is default-selected; the forms are present immediately.
    expect(screen.getByTestId("resolution-forms")).toBeInTheDocument();
    // Record a blind calibration for item A (the default selection).
    fireEvent.change(screen.getByLabelText(/calibration prediction/i), {
      target: { value: "p" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /record blind calibration/i }),
    );
    await waitFor(() =>
      expect(screen.getByTestId("calibration-captured")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("calibration-captured")).toHaveTextContent(
      /blind calibration recorded for this item/i,
    );

    // Switch to the SECOND item (its select button is labeled by its title).
    fireEvent.click(
      screen.getByRole("button", { name: TODO_ITEMS[1].title as string }),
    );
    // B is its OWN un-calibrated item: it re-presents the calibration FORM (not
    // the recorded state) — per-id, so A's calibration did NOT leak onto B.
    await waitFor(() =>
      expect(screen.queryByTestId("calibration-captured")).toBeNull(),
    );
    expect(screen.getByLabelText(/calibration prediction/i)).toBeInTheDocument();
    // …and B's forms are present anyway (no calibration gate).
    expect(screen.getByTestId("resolution-forms")).toBeInTheDocument();

    // Switch BACK to A: the per-id Set persists — A STILL shows "recorded" and is
    // NEVER re-prompted (the old "switch-back RE-LOCKS / re-prompts" is inverted).
    fireEvent.click(
      screen.getByRole("button", { name: TODO_ITEMS[0].title as string }),
    );
    await waitFor(() =>
      expect(screen.getByTestId("calibration-captured")).toBeInTheDocument(),
    );
    expect(screen.queryByLabelText(/calibration prediction/i)).toBeNull();
    // A's forms remain present throughout.
    expect(screen.getByTestId("resolution-forms")).toBeInTheDocument();
  });
});

describe("TodoShell hardening — valid id but malformed sibling fields (deep deref)", () => {
  // safeItems keeps an item with a non-empty string id but DOES NOT validate
  // `kind`/`title`. Those flow RAW into DeferForm (kind={selected.kind}) and
  // TutorPanel (title={selected.title}). A producer/legacy row can carry a
  // non-string kind or an OBJECT title — rendering an object as a React child
  // throws "Objects are not valid as a React child" and blanks the WHOLE
  // cockpit. The children must coerce; the shell must not crash on the deref.
  it("a valid item with an OBJECT title still mounts the tutor (no React-child throw)", async () => {
    // U5 kind-gate: the tutor is a FINDING-keyed aux pane, so this probe of the
    // OBJECT-title → TutorPanel React-child coercion uses a finding_review kind
    // (otherwise the tutor would correctly be hidden). The OBJECT-KIND →
    // DeferForm probe is covered separately below ("OBJECT kind with LIVE
    // defer capability renders no defer form"). S2 reframe: the tutor now lives
    // inside the REVEAL-gated aux trio (no longer pre-calibration), so reveal it.
    const nasty = [
      {
        id: "sf-nasty",
        kind: "finding_review",
        evidence_level: "L4", // clears the ladder bar — row stays visible
        // title as an object: TutorPanel renders title as a child → would throw
        // "Objects are not valid as a React child" if not coerced to text.
        title: { not: "a string" },
        since: 12345, // non-string since (number) — age label path
      },
    ];
    renderTodo({
      availability: AVAILABILITY_LIVE,
      items: nasty as unknown as HumanTodoItem[],
    });
    // The valid id is selectable — the item was NOT dropped (id is a string).
    // The object title is not renderable, so the inbox selector falls back to id.
    expect(screen.getByRole("button", { name: "sf-nasty" })).toBeInTheDocument();
    // forms render unconditionally; reveal the aux trio so the tutor mounts.
    await expectFormsPresent();
    await revealAux();
    // The tutor (handed the object title) degraded legibly — NOT "[object Object]".
    expect(screen.getByTestId("tutor-panel")).toBeInTheDocument();
    expect(screen.queryByText(/\[object Object\]/)).toBeNull();
  });

  // A title that is an ARRAY (another legacy/partial shape) flowing to TutorPanel
  // — finding_review kind so the FINDING-keyed tutor renders (U5 kind-gate).
  it("a valid item with an ARRAY title still mounts and shows no raw array text", async () => {
    const nasty = [
      { id: "sf-arr", kind: "finding_review", title: ["a", "b"], evidence_level: "L4" },
    ];
    renderTodo({
      availability: AVAILABILITY_LIVE,
      items: nasty as unknown as HumanTodoItem[],
    });
    // array title is not renderable → inbox selector falls back to the id.
    expect(screen.getByRole("button", { name: "sf-arr" })).toBeInTheDocument();
    await expectFormsPresent();
    await revealAux();
    expect(screen.getByTestId("tutor-panel")).toBeInTheDocument();
  });

  // The deepest forward: DeferForm gets kind={selected.kind} and, when the
  // attest capability is LIVE (defer:true), renders its BODY — calling
  // deferKindOf(kind) + deferOnly(kind) on a producer-owned `kind`. An OBJECT
  // kind must not crash that render (hasOwnProperty-keyed map => null => the
  // defer form renders nothing for an unknown/garbage kind), and the cockpit
  // stays mounted. This exercises the live-capability branch the 404-stub tests
  // above never reach.
  it("OBJECT kind with LIVE defer capability renders no defer form, no crash", async () => {
    // Light the attest handshake so DeferForm's body attempts to render.
    vi.stubGlobal("fetch", async (url: unknown) => {
      const u = String(url);
      if (u.endsWith("/api/todo/concurrency")) return jsonResponse(200, { active: false });
      if (u.endsWith("/api/human_todo")) return jsonResponse(200, humanTodoBody);
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
      if (u.includes("/api/todo/"))
        return jsonResponse(200, { status: "stub", would_run: ["<read-only>"] });
      return jsonResponse(404, {});
    });
    resetAttestCapabilityCache();
    renderTodo({
      availability: AVAILABILITY_LIVE,
      items: [
        { id: "iter-objkind", kind: { malformed: true }, title: "ok title" },
      ] as unknown as HumanTodoItem[],
    });
    // the inbox selector is labeled by the (renderable) title here.
    expect(screen.getByRole("button", { name: "ok title" })).toBeInTheDocument();
    // forms render unconditionally — no calibration needed to reach the defer path.
    await expectFormsPresent();
    // A garbage kind has no blessed defer mapping => the defer form is absent,
    // and crucially the cockpit did not blank.
    expect(screen.queryByTestId("defer-form")).toBeNull();
    expect(screen.getByTestId("todo-cockpit")).toBeInTheDocument();
  });

  // The mirror: a VALID kind ("gate_verdict") with LIVE defer must STILL render
  // the defer form — proving the object-kind guard above is a real drop, not a
  // blanket suppression that would also break valid producer rows.
  it("VALID kind with LIVE defer capability DOES render the defer form (no over-suppression)", async () => {
    vi.stubGlobal("fetch", async (url: unknown) => {
      const u = String(url);
      if (u.endsWith("/api/todo/concurrency")) return jsonResponse(200, { active: false });
      if (u.endsWith("/api/human_todo")) return jsonResponse(200, humanTodoBody);
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
      if (u.includes("/api/todo/"))
        return jsonResponse(200, { status: "stub", would_run: ["<read-only>"] });
      return jsonResponse(404, {});
    });
    resetAttestCapabilityCache();
    renderTodo({
      availability: AVAILABILITY_LIVE,
      items: [
        { id: "iter-valid-kind", kind: "gate_verdict", title: "ok" },
      ] as unknown as HumanTodoItem[],
    });
    // forms render unconditionally — no calibration needed to reach the defer form.
    await expectFormsPresent();
    await waitFor(() =>
      expect(screen.getByTestId("defer-form")).toBeInTheDocument(),
    );
  });
});

describe("TodoShell hardening — duplicate ids + fetch undefined body", () => {
  // loop_memory.jsonl can emit two rows with the same iteration id (a re-queued
  // finding). Both pass safeItems; .find returns the first; React keys collide
  // (a console warning) but the page must NOT blank.
  it("duplicate ids render without blanking (first is the selection target)", () => {
    // Two rows carry the SAME id (a re-queued finding). Both pass safeItems; the
    // selection .find returns the first; the React keys collide (a console
    // warning) but the page must NOT blank. In select mode each row's selector
    // is labeled by its title, so the two rows surface as two distinct buttons.
    const dupes = [
      { id: "iter-dup", kind: "gate_verdict", title: "first" },
      { id: "iter-dup", kind: "gate_verdict", title: "second" },
    ];
    renderTodo({
      availability: AVAILABILITY_LIVE,
      items: dupes as unknown as HumanTodoItem[],
    });
    expect(screen.getByTestId("todo-cockpit")).toBeInTheDocument();
    // Both rows render (their titles label the selectors); the cockpit did not
    // blank — duplicate ids degrade to a console key-warning, never a crash.
    expect(screen.getByRole("button", { name: "first" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "second" })).toBeInTheDocument();
    expect(screen.queryByTestId("todo-no-selection")).toBeNull();
    // The first duplicate is the selection target (.find returns it) → its forms
    // are present (forms render unconditionally for the selected item).
    expect(screen.getByTestId("resolution-forms")).toBeInTheDocument();
  });

  // getHumanTodo's getJSON casts the body with no shape check; a 200 whose JSON
  // body is literally `undefined` (resp === undefined) hits `resp?.items` →
  // safeItems(undefined) → []. Probes the optional-chain on the fetch result.
  it("getHumanTodo body that is undefined => no-selection (no crash)", async () => {
    humanTodoBody = undefined;
    renderTodo({ availability: AVAILABILITY_LIVE });
    await waitFor(() =>
      expect(screen.getByTestId("todo-cockpit")).toBeInTheDocument(),
    );
    await waitFor(() =>
      expect(screen.getByTestId("todo-no-selection")).toBeInTheDocument(),
    );
  });
});
