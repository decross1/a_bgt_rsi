// test_todo_route — the /todo cockpit SHELL (Todo.tsx). Asserts the assembly
// contract, NOT the leaf forms' internals (those have their own suites). The S2
// reframe (docs/ui_reframe_plan.md §1) changed the flow, and these assertions
// track the NEW behavior while protecting the SAME properties:
//   - the INBOX renders (HumanTodoPanel is the cockpit's list of what needs
//     resolving — its home is now /todo) and is SELECT-ONLY (the inline verdict
//     writers are suppressed; a row is a selector for the workspace);
//   - the RESOLUTION CONTRACT (post-reframe): the kind-gated resolution forms
//     render UNCONDITIONALLY for any selection — the forced pre-verdict
//     calibration gate is REMOVED (there is no resolution-locked element).
//     Calibration is OPTIONAL; the forms do not wait on it;
//   - the stub forms show their read-only would-run / honest stub label and no
//     execute affordance (D-046 / rule 8 / rule 4);
//   - the INTERACTIVE aux panes are REVEAL-gated (finding-kind only): absent
//     until reveal-interrogation is clicked, then they mount;
//   - the tutor exposes NO verdict affordance (it is FENCED from the verdict) —
//     it now lives INSIDE the revealed interrogation trio.
//
// Network is fully stubbed: api/todo (cockpit fetches) and api/http
// (getHumanTodo) are module-mocked, and global fetch is stubbed so the blessed
// attest forms' capability probe degrades quietly. The shell is driven through
// its injected `availability` + `items` props (the override idiom), so the
// render is deterministic without timers.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import Todo from "../src/routes/Todo";
import { AVAILABILITY_STUB, AVAILABILITY_LIVE, TODO_ITEMS } from "../src/fixtures/todo";
import type { HumanTodoItem } from "../src/types/schemas";

// U5 kind-gate: the FINDING-keyed resolution surfaces (finding-review,
// authorize-fix, spawn-topic, abstain) and the aux panes (two-voice, tutor)
// now render ONLY for a finding_review item — selected.id there is a
// finding_id, never an iteration_id. TODO_ITEMS[0] is a gate_verdict
// (ITERATION) item, so the tests below that assert those FINDING surfaces are
// driven with an explicit finding_review item. This adjusts the fixture KIND
// to match the gate; the assertions' intent (those surfaces render and stub-
// gate correctly) is unchanged. The full kind-gate matrix is owned by
// tests/test_todo_kind_gating.tsx.
const FINDING_ITEMS: HumanTodoItem[] = [
  {
    kind: "finding_review",
    id: "sf-2026-06-14-001",
    title: "Finding: shading is dominated under VCG (survives 2/3)",
    since: "2026-06-14T16:00:00Z",
  },
];

// --- network stub (by URL) ----------------------------------------------
// The shell is driven through its injected `availability` + `items` props, so
// Todo.tsx's own getCockpitAvailability/getHumanTodo fetches never run. What
// DOES self-fetch through the real api helpers (→ global fetch):
//   - ConcurrencyWarning → GET /api/todo/concurrency (we answer idle);
//   - HumanTodoPanel (the inbox) → GET /api/human_todo (we answer TODO_ITEMS);
//   - the blessed attest forms → GET /api/attest/available (404 → they degrade
//     to their honest CLI-fallback note; they still render).
// The stub POST seams answer with an honest stub envelope so nothing throws.
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
    if (u.endsWith("/api/human_todo"))
      return jsonResponse(200, { items: TODO_ITEMS, counts: {} });
    if (u.includes("/api/todo/"))
      return jsonResponse(200, { status: "stub", would_run: ["<read-only>"] });
    // everything else (attest capability probe) 404s → quiet degradation.
    return jsonResponse(404, {});
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderTodo(props: Parameters<typeof Todo>[0] = {}) {
  return render(
    <MemoryRouter initialEntries={["/todo"]}>
      <Todo items={TODO_ITEMS} {...props} />
    </MemoryRouter>,
  );
}

// The interactive aux trio (tutor-panel + tutor-chat-pane + two-voice-chat-pane)
// is REVEAL-gated now (finding-kind only): pre-reveal it is absent; clicking
// reveal-interrogation mounts it. Tests asserting on a surface INSIDE the trio
// must reveal it first. This replaces the OLD calibration gate — the trio gates
// on the reveal click, never on calibration.
async function revealInterrogation() {
  fireEvent.click(screen.getByTestId("reveal-interrogation"));
  await waitFor(() =>
    expect(screen.getByTestId("todo-aux-interactive")).toBeInTheDocument(),
  );
}

describe("Todo cockpit shell", () => {
  it("renders the inbox (HumanTodoPanel is the cockpit's list of what needs resolving)", async () => {
    renderTodo({ availability: AVAILABILITY_STUB });
    expect(screen.getByTestId("todo-cockpit")).toBeInTheDocument();
    expect(screen.getByTestId("todo-inbox")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId("human-todo-panel")).toBeInTheDocument(),
    );
  });

  it("RESOLUTION CONTRACT: the resolution forms render UNCONDITIONALLY (no forced calibration gate)", async () => {
    renderTodo({ availability: AVAILABILITY_STUB });

    // The first item is default-selected (no click needed), and the resolution
    // forms are present IMMEDIATELY — the forced pre-verdict calibration gate is
    // gone. There is NO resolution-locked element anymore (the gate that used to
    // hide the forms until onCaptured fired was REMOVED in the S2 reframe).
    await waitFor(() =>
      expect(screen.getByTestId("resolution-forms")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("resolution-locked")).toBeNull();

    // The selected-item header + the journey are the prediction basis, present
    // alongside the forms. Calibration is OPTIONAL (opt-in), shown but NOT
    // gating: capturing it does NOT reveal anything that was hidden.
    expect(screen.getByTestId("todo-selected-item")).toBeInTheDocument();
    expect(screen.getByTestId("pipeline-journey")).toBeInTheDocument();
    expect(screen.getByTestId("calibration-capture")).toBeInTheDocument();

    // Recording a blind calibration leaves the forms exactly where they were —
    // present (the gate is gone, so capture is a no-op for the forms' visibility).
    fireEvent.change(screen.getByLabelText(/calibration prediction/i), {
      target: { value: "survives the attack panel 2/3" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /record blind calibration/i }),
    );
    await waitFor(() =>
      expect(screen.getByTestId("calibration-captured")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("resolution-forms")).toBeInTheDocument();
    expect(screen.queryByTestId("resolution-locked")).toBeNull();
  });

  it("the FINDING resolution surfaces are present unconditionally for a finding item", async () => {
    // FINDING-kind item: the finding-keyed forms render (authorize-fix,
    // spawn-topic, abstain, and directive-signoff — it signs off a FINDING via
    // finding_session --set-status; wiring doc 1d). The full matrix is asserted
    // in the kind-gating suite; here we pin the finding family. The forms render
    // directly (no calibration step — the forced gate is gone).
    renderTodo({ availability: AVAILABILITY_STUB, items: FINDING_ITEMS });
    await waitFor(() =>
      expect(screen.getByTestId("resolution-forms")).toBeInTheDocument(),
    );
    // the finding-keyed stub forms (authorize-fix, spawn-topic, abstain) render
    // off the cockpit `available` prop (no attest probe), so they are present
    // even while the attest handshake 404s in this stub.
    expect(screen.getByTestId("authorize-fix-form")).toBeInTheDocument();
    expect(screen.getByTestId("spawn-topic-form")).toBeInTheDocument();
    expect(screen.getByTestId("abstain-form")).toBeInTheDocument();
  });

  it("STUB forms label themselves honestly and show a read-only would-run argv (no execute)", async () => {
    // FINDING-kind item: the stub forms under test (authorize-fix/spawn-topic/
    // abstain) are finding-keyed. They render directly (no calibration step).
    renderTodo({ availability: AVAILABILITY_STUB, items: FINDING_ITEMS });
    await waitFor(() =>
      expect(screen.getByTestId("resolution-forms")).toBeInTheDocument(),
    );

    // honest capability-off labels (capability is OFF in AVAILABILITY_STUB):
    // authorize_fix is a LIVE exec gated by its capability flag; spawn_topic +
    // abstain are session-exits (preview-only by design). None claim a future
    // "seam lands" — they say capability-off / session-exit honestly.
    expect(screen.getByTestId("authorize-fix-stub")).toHaveTextContent(/not enabled in this environment/i);
    expect(screen.getByTestId("spawn-topic-stub")).toHaveTextContent(/session-exit, not an in-UI one-shot/i);
    expect(screen.getByTestId("abstain-stub")).toHaveTextContent(/session-exit, not an in-UI one-shot/i);

    // would-run argv is read-only (<pre>, not a button); no execute/run button.
    const argv = screen.getByTestId("authorize-fix-argv");
    expect(argv.tagName.toLowerCase()).toBe("pre");
    expect(screen.queryByRole("button", { name: /execute|run/i })).toBeNull();

    // submit stays disabled (the authorize_fix exec is not enabled here).
    expect(screen.getByRole("button", { name: /authorize fix/i })).toBeDisabled();
  });

  it("the tutor exposes NO verdict affordance (FENCED from the verdict path)", async () => {
    // The tutor is a FINDING-keyed aux pane (it explains a finding); it now
    // lives INSIDE the reveal-gated interrogation trio, so we reveal it first.
    // The verdict-fence is UNCHANGED: the tutor carries no verdict prop and
    // renders no verdict affordance.
    renderTodo({ availability: AVAILABILITY_STUB, items: FINDING_ITEMS });
    await revealInterrogation();
    const tutor = screen.getByTestId("tutor-panel");
    expect(tutor).toBeInTheDocument();
    expect(screen.getByTestId("tutor-fence-note")).toHaveTextContent(
      /does not affect your verdict/i,
    );
    // The tutor renders no verdict buttons (valid / invalid / needs_revision).
    expect(within(tutor).queryByRole("button")).toBeNull();
  });

  it("two-voice pane is gated off availability (disabled send while the seam is dark)", async () => {
    // Two-voice is a FINDING-keyed aux pane (it interrogates a finding); it
    // renders only for a finding_review item AND only AFTER the interrogation is
    // REVEALED (the interactive panes are reveal-gated now, not calibration-
    // gated — the OLD D-054 calibration gate on the aux is gone). Reveal first,
    // then assert its send is disabled while the seam is dark.
    renderTodo({ availability: AVAILABILITY_STUB, items: FINDING_ITEMS });
    await revealInterrogation();
    await waitFor(() =>
      expect(screen.getByTestId("two-voice-chat-pane")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("two-voice-send")).toBeDisabled();
  });

  it("when the cockpit seams are LIVE, the stub submit enables (capability flows through)", async () => {
    // AbstainForm is FINDING-keyed; drive with a finding_review item. The forms
    // render directly (no calibration step — the forced gate is gone).
    renderTodo({ availability: AVAILABILITY_LIVE, items: FINDING_ITEMS });
    await waitFor(() =>
      expect(screen.getByTestId("resolution-forms")).toBeInTheDocument(),
    );
    // Capability flows through to a stub form: AbstainForm needs only a note,
    // so a non-empty note + live capability enables its submit (proving the
    // single getCockpitAvailability fetch's actions reach the forms).
    const abstain = screen.getByTestId("abstain-form");
    fireEvent.change(within(abstain).getByLabelText(/abstain note/i), {
      target: { value: "revisit after R0 fix" },
    });
    await waitFor(() =>
      expect(
        within(screen.getByTestId("abstain-form")).getByRole("button", {
          name: /^abstain$/i,
        }),
      ).not.toBeDisabled(),
    );
  });

  it("empty inbox: honest no-selection state, no resolution forms", () => {
    renderTodo({ availability: AVAILABILITY_STUB, items: [] });
    expect(screen.getByTestId("todo-no-selection")).toBeInTheDocument();
    expect(screen.queryByTestId("resolution-forms")).toBeNull();
    expect(screen.queryByTestId("calibration-capture")).toBeNull();
  });
});
