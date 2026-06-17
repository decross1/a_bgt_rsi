// test_todo_route — the /todo cockpit SHELL (Todo.tsx). Asserts the assembly
// contract, NOT the leaf forms' internals (those have their own suites):
//   - the INBOX renders (HumanTodoPanel is the cockpit's list of what needs
//     resolving — its home is now /todo);
//   - the ORDERING CONTRACT (ARCH §6.5.4): calibration is REQUIRED before the
//     six resolution forms appear — they are locked until onCaptured fires;
//   - the stub forms show their read-only would-run / honest stub label and no
//     execute affordance (D-046 / rule 8 / rule 4);
//   - the tutor exposes NO verdict affordance (it is FENCED from the verdict).
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

describe("Todo cockpit shell", () => {
  it("renders the inbox (HumanTodoPanel is the cockpit's list of what needs resolving)", async () => {
    renderTodo({ availability: AVAILABILITY_STUB });
    expect(screen.getByTestId("todo-cockpit")).toBeInTheDocument();
    expect(screen.getByTestId("todo-inbox")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId("human-todo-panel")).toBeInTheDocument(),
    );
  });

  it("ORDERING CONTRACT: the resolution forms are LOCKED until calibration is captured", async () => {
    renderTodo({ availability: AVAILABILITY_STUB });

    // Before calibration: the resolution forms are absent; the lock note shows.
    expect(screen.queryByTestId("resolution-forms")).toBeNull();
    expect(screen.getByTestId("resolution-locked")).toBeInTheDocument();
    // Calibration capture is present FIRST.
    expect(screen.getByTestId("calibration-capture")).toBeInTheDocument();

    // Capture calibration → the forms reveal.
    fireEvent.change(screen.getByLabelText(/calibration prediction/i), {
      target: { value: "survives the attack panel 2/3" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /capture calibration/i }),
    );

    await waitFor(() =>
      expect(screen.getByTestId("resolution-forms")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("resolution-locked")).toBeNull();
  });

  it("after calibration: the FINDING resolution surfaces are present", async () => {
    // FINDING-kind item: the finding-keyed forms render (authorize-fix,
    // spawn-topic, abstain). directive-signoff is ITERATION-keyed, asserted in
    // the kind-gating suite; here we pin the finding family.
    renderTodo({ availability: AVAILABILITY_STUB, items: FINDING_ITEMS });
    fireEvent.change(screen.getByLabelText(/calibration prediction/i), {
      target: { value: "p" },
    });
    fireEvent.click(screen.getByRole("button", { name: /capture calibration/i }));
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
    // abstain) are finding-keyed.
    renderTodo({ availability: AVAILABILITY_STUB, items: FINDING_ITEMS });
    fireEvent.change(screen.getByLabelText(/calibration prediction/i), {
      target: { value: "p" },
    });
    fireEvent.click(screen.getByRole("button", { name: /capture calibration/i }));
    await waitFor(() =>
      expect(screen.getByTestId("resolution-forms")).toBeInTheDocument(),
    );

    // honest stub labels (capability is OFF in AVAILABILITY_STUB)
    expect(screen.getByTestId("authorize-fix-stub")).toHaveTextContent(/stub — lights up/i);
    expect(screen.getByTestId("spawn-topic-stub")).toHaveTextContent(/stub — lights up/i);
    expect(screen.getByTestId("abstain-stub")).toHaveTextContent(/stub — lights up/i);

    // would-run argv is read-only (<pre>, not a button); no execute/run button.
    const argv = screen.getByTestId("authorize-fix-argv");
    expect(argv.tagName.toLowerCase()).toBe("pre");
    expect(screen.queryByRole("button", { name: /execute|run/i })).toBeNull();

    // stub submit stays disabled (the seam is not live).
    expect(screen.getByRole("button", { name: /authorize fix/i })).toBeDisabled();
  });

  it("the tutor exposes NO verdict affordance (FENCED from the verdict path)", () => {
    // The tutor is a FINDING-keyed aux pane (it explains a finding); it renders
    // only for a finding_review item.
    renderTodo({ availability: AVAILABILITY_STUB, items: FINDING_ITEMS });
    const tutor = screen.getByTestId("tutor-panel");
    expect(tutor).toBeInTheDocument();
    expect(screen.getByTestId("tutor-fence-note")).toHaveTextContent(
      /does not affect your verdict/i,
    );
    // The tutor renders no verdict buttons (valid / invalid / needs_revision).
    expect(within(tutor).queryByRole("button")).toBeNull();
  });

  it("two-voice pane is gated off availability (disabled send while the seam is dark)", () => {
    // Two-voice is a FINDING-keyed aux pane (it interrogates a finding); it
    // renders only for a finding_review item.
    renderTodo({ availability: AVAILABILITY_STUB, items: FINDING_ITEMS });
    expect(screen.getByTestId("two-voice-chat-pane")).toBeInTheDocument();
    expect(screen.getByTestId("two-voice-send")).toBeDisabled();
  });

  it("when the cockpit seams are LIVE, the stub submit enables (capability flows through)", async () => {
    // AbstainForm is FINDING-keyed; drive with a finding_review item.
    renderTodo({ availability: AVAILABILITY_LIVE, items: FINDING_ITEMS });
    fireEvent.change(screen.getByLabelText(/calibration prediction/i), {
      target: { value: "p" },
    });
    fireEvent.click(screen.getByRole("button", { name: /capture calibration/i }));
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
