// OweStrip — Pulse's "do I owe anything" strip. Pins: only blocking kinds
// (gate_verdict + state_gate families) and L4+-bar findings render; the
// demoted mass (legacy no-level findings) stays OFF the strip but is counted
// honestly in the ladder histogram line; rows link into the dossier reader;
// a 404 is an HONEST "queue UNKNOWN", never a calm empty state.
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import OweStrip from "../src/components/OweStrip";
import type { HumanTodoItem } from "../src/types/schemas";

function renderStrip(items?: HumanTodoItem[]) {
  return render(
    <MemoryRouter>
      <OweStrip initial={items} />
    </MemoryRouter>,
  );
}

const GATE: HumanTodoItem = {
  kind: "gate_verdict",
  id: "iter-2026-08-14-001",
  title: "iter-2026-08-14-001 awaiting verdict",
  since: "2026-08-14T10:00:00Z",
};
const STATE_GATE: HumanTodoItem = {
  kind: "state_gate",
  id: "gate-block-1",
  title: "human_gates_pending: day3_review",
  since: "2026-08-13T10:00:00Z",
};
const L4_FINDING: HumanTodoItem = {
  kind: "finding_review",
  id: "sf-ladder-001",
  title: "ladder finding that cleared the bar",
  since: "2026-08-14T12:00:00Z",
  evidence_level: "L4",
};
const LEGACY_FINDING: HumanTodoItem = {
  kind: "finding_review",
  id: "sf-legacy-001",
  title: "pre-ladder finding (no level)",
  since: "2026-06-01T00:00:00Z",
};
const BUBBLE: HumanTodoItem = {
  kind: "bubble_ack",
  id: "coordinator_abc",
  title: "bubble: needs a read receipt",
  since: "2026-08-14T09:00:00Z",
};

describe("OweStrip", () => {
  it("renders ONLY blocking kinds + L4+ findings; demoted/informational stay off", () => {
    renderStrip([GATE, STATE_GATE, L4_FINDING, LEGACY_FINDING, BUBBLE]);
    const strip = screen.getByTestId("owe-strip");
    expect(strip).toHaveTextContent("iter-2026-08-14-001 awaiting verdict");
    expect(strip).toHaveTextContent("human_gates_pending: day3_review");
    expect(strip).toHaveTextContent("ladder finding that cleared the bar");
    // Below-bar finding and the informational bubble never make the strip.
    expect(strip.textContent).not.toContain("pre-ladder finding");
    expect(strip.textContent).not.toContain("read receipt");
    expect(screen.getByTestId("owe-count")).toHaveTextContent("3");
  });

  it("rows link into the dossier reader (/dossier/:id)", () => {
    renderStrip([L4_FINDING]);
    const link = screen.getByRole("link", {
      name: /ladder finding that cleared the bar/,
    });
    expect(link).toHaveAttribute("href", "/dossier/sf-ladder-001");
  });

  it("carries the L4 chip on bar-clearing findings", () => {
    renderStrip([L4_FINDING]);
    expect(screen.getByText("L4")).toBeInTheDocument();
  });

  it("ladder histogram line counts ALL finding rows (demoted included)", () => {
    renderStrip([L4_FINDING, LEGACY_FINDING, { ...LEGACY_FINDING, id: "sf-legacy-002" }]);
    const line = screen.getByTestId("owe-ladder-counts");
    expect(line).toHaveTextContent("L4 ×1");
    expect(line).toHaveTextContent("no level ×2");
  });

  it("empty owed queue is the calm state", () => {
    renderStrip([LEGACY_FINDING, BUBBLE]);
    expect(screen.getByTestId("owe-empty")).toHaveTextContent(
      "You owe nothing",
    );
    expect(screen.getByTestId("owe-count")).toHaveTextContent("0");
  });

  it("a 404 renders the HONEST queue-UNKNOWN state, never calm-empty", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 404,
      statusText: "Not Found",
      json: async () => ({ detail: "Not Found" }),
    } as Response);
    render(
      <MemoryRouter>
        <OweStrip />
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("owe-error")).toHaveTextContent(
        "queue is UNKNOWN",
      ),
    );
    expect(screen.queryByTestId("owe-empty")).toBeNull();
    vi.restoreAllMocks();
  });

  it("malformed rows degrade (non-object entries dropped, never a crash)", () => {
    renderStrip([
      null,
      42,
      ["array-row"],
      GATE,
    ] as unknown as HumanTodoItem[]);
    expect(screen.getByTestId("owe-count")).toHaveTextContent("1");
    expect(
      screen.getByText("iter-2026-08-14-001 awaiting verdict"),
    ).toBeInTheDocument();
  });
});
