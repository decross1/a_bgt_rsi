// App-level wiring for the /todo COCKPIT: the "/todo" route now renders the
// uncertainty-resolution cockpit (routes/Todo.tsx) — ConcurrencyWarning + the
// HumanTodoPanel inbox + pre-verdict calibration + the six resolution forms —
// and the nav carries a "todo" tab. Rendered through the real <App/>
// (BrowserRouter), navigated via history.pushState, so the route table itself
// is under test (2026-06-14 work order PART 2).
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
  it("renders the /todo cockpit (inbox + resolution area) and a 'todo' nav tab", async () => {
    window.history.pushState({}, "", "/todo");
    render(<App />);

    // Nav tab present on every page.
    expect(screen.getByRole("link", { name: "todo" })).toBeInTheDocument();

    // The route mounts the cockpit shell, with the HumanTodoPanel inbox inside.
    expect(screen.getByTestId("todo-cockpit")).toBeInTheDocument();
    expect(screen.getByTestId("human-todo-panel")).toBeInTheDocument();
    // The queue item surfaces once getHumanTodo resolves. The title legitimately
    // appears more than once (the inbox row + the tutor panel header, which is
    // handed the selected item's title), so assert at-least-one, not exactly-one.
    await waitFor(() =>
      expect(
        screen.getAllByText("iter-2026-06-05-001 awaiting verdict").length,
      ).toBeGreaterThanOrEqual(1),
    );
    // The resolve command renders verbatim in the inbox (the backend owns its
    // exact text); the resolution forms are calibration-locked, so it is unique.
    expect(
      screen.getByText(/orchestrator\.gate_cli --iteration-id iter-2026-06-05-001/),
    ).toBeInTheDocument();
  });
});
