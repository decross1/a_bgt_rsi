// App-level wiring for the HUMAN TODO surface: the "/todo" route renders a
// page-width HumanTodoPanel and the nav carries a "todo" tab — the human's
// queue is one click / one bookmark away from every page (reconciliation
// plan B3 + B5). Rendered through the real <App/> (BrowserRouter), navigated
// via history.pushState, so the route table itself is under test.
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Replace ONLY getHumanTodo; every other export stays real (none of them is
// invoked on /todo — no other route mounts there).
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

import App from "../src/App";

describe("/todo route wiring", () => {
  it("renders the page-width HumanTodoPanel at /todo and a 'todo' nav tab", async () => {
    window.history.pushState({}, "", "/todo");
    render(<App />);

    // Nav tab present on every page.
    expect(screen.getByRole("link", { name: "todo" })).toBeInTheDocument();

    // The route mounts the page wrapper + the self-polling panel, which
    // renders the queue item once getHumanTodo resolves.
    expect(screen.getByTestId("human-todo-page")).toBeInTheDocument();
    expect(screen.getByTestId("human-todo-panel")).toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.getByText("iter-2026-06-05-001 awaiting verdict"),
      ).toBeInTheDocument(),
    );
    // The resolve command renders verbatim (the backend owns its exact text).
    expect(
      screen.getByText(/orchestrator\.gate_cli --iteration-id iter-2026-06-05-001/),
    ).toBeInTheDocument();
  });
});
