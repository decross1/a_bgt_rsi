// App-level wiring for the /todo COCKPIT: the "/todo" route now renders the
// uncertainty-resolution cockpit (routes/Todo.tsx) — ConcurrencyWarning + the
// HumanTodoPanel inbox (SELECT-ONLY) + the WORKSPACE (selected-item header +
// PipelineJourney + optional CalibrationCapture + the kind-gated resolution
// forms, which render UNCONDITIONALLY post-reframe) — and the nav carries a
// "todo" tab. Rendered through the real <App/> (BrowserRouter), navigated via
// history.pushState, so the route table itself is under test (S2 reframe,
// docs/ui_reframe_plan.md §1).
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Replace ONLY getHumanTodo (the inbox + the cockpit's selection pointer poll
// it); every other api/http export stays real.
vi.mock("../src/api/http", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../src/api/http")>();
  return {
    ...mod,
    getHumanTodo: vi.fn().mockResolvedValue({
      items: [
        {
          kind: "gate_verdict",
          id: "iter-2026-06-05-001",
          title: "iter-2026-06-05-001 awaiting verdict",
          since: "2026-06-05T19:58:00Z",
          resolve_command:
            "python -m orchestrator.gate_cli --iteration-id iter-2026-06-05-001 --verdict valid",
        },
      ],
      counts: {
        gate_verdict: 1,
        finding_review: 0,
        bubble_ack: 0,
        stale_active_run: 0,
        state_gate: 0,
      },
    }),
  };
});

// The cockpit's capability + concurrency probes hit api/todo (a different
// module). Stub them so the route renders deterministically without network —
// unavailable caps keep the NEW seams in their honest stub state; idle
// concurrency hides the warn banner.
vi.mock("../src/api/todo", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../src/api/todo")>();
  return {
    ...mod,
    getCockpitAvailability: vi.fn().mockResolvedValue(mod.COCKPIT_UNAVAILABLE),
    getConcurrency: vi.fn().mockResolvedValue({ active: false }),
  };
});

import App from "../src/App";

describe("/todo route wiring", () => {
  it("renders the /todo cockpit (inbox select-only + workspace resolution area) and a 'todo' nav tab", async () => {
    window.history.pushState({}, "", "/todo");
    render(<App />);

    // Nav tab present on every page.
    expect(screen.getByRole("link", { name: "todo" })).toBeInTheDocument();

    // The route mounts the cockpit shell, with the HumanTodoPanel inbox inside.
    expect(screen.getByTestId("todo-cockpit")).toBeInTheDocument();
    expect(screen.getByTestId("human-todo-panel")).toBeInTheDocument();

    // The WORKSPACE (resolution area) is wired in alongside the inbox — the new
    // cockpit structure: inbox (select-only) ABOVE, resolve-a-selected-item
    // workspace BELOW. This proves the route mounts the REAL cockpit, not a stub.
    expect(screen.getByTestId("todo-resolution-area")).toBeInTheDocument();

    // The queue item getHumanTodo returns flows through to the cockpit: the
    // selection defaults to the first item, so the workspace surfaces the
    // selected-item header carrying that item's real id + title. The title
    // legitimately appears more than once (the workspace header + journey, and
    // the inbox row once its list settles), so assert at-least-one.
    await waitFor(() =>
      expect(
        screen.getAllByText("iter-2026-06-05-001 awaiting verdict").length,
      ).toBeGreaterThanOrEqual(1),
    );
    const selected = screen.getByTestId("todo-selected-item");
    expect(selected).toHaveTextContent("iter-2026-06-05-001");

    // The kind-gated resolution forms render UNCONDITIONALLY for the selection
    // (the forced pre-verdict calibration gate is REMOVED — there is no
    // resolution-locked element). The default-selected gate_verdict (ITERATION)
    // item keys the iteration-only GateVerdictForm; the forced gate is gone.
    await waitFor(() =>
      expect(screen.getByTestId("resolution-forms")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("resolution-locked")).toBeNull();
    // GateVerdictForm self-gates on the attest capability (resolved async), so
    // waitFor it. The U5 kind-gate holds through the route: an ITERATION item
    // keys ONLY the iteration family — NO finding-keyed form renders.
    await waitFor(() =>
      expect(screen.getByTestId("gate-verdict-form")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("finding-review-form")).toBeNull();
    expect(screen.queryByTestId("authorize-fix-form")).toBeNull();
    expect(screen.queryByTestId("two-voice-chat-pane")).toBeNull();
  });
});
