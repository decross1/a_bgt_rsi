// LadderMiniFunnel — Pulse's compact L0->L5 read (revamp R3). The load-bearing
// pins are the ABSENCE cases: 204 (ledger never written) and a version-skew 404
// HIDE the panel entirely, while a 500 — which ladder.py raises deliberately on
// an unreadable ledger — must NOT vanish, because silence there would misreport
// a broken ledger as "no ladder yet".
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import LadderMiniFunnel from "../src/components/LadderMiniFunnel";
import type { LadderResponse } from "../src/types/schemas";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const LADDER: LadderResponse = {
  clusters: [],
  histogram: { L0: 12, L1: 6, L2: 3, L3: 2, L4: 1, L5: 0 },
  counts: { open: 20, surfaced: 3, killed: 4 },
  agenda: [],
  next_owed: {},
};

function renderFunnel(initial?: LadderResponse | null) {
  return render(
    <MemoryRouter>
      <LadderMiniFunnel initial={initial} />
    </MemoryRouter>,
  );
}

function stubFetch(status: number, body?: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: status >= 200 && status < 300,
      status,
      statusText: String(status),
      json: async () => body ?? { detail: "boom" },
    } as Response),
  );
}

describe("LadderMiniFunnel", () => {
  it("renders all six rungs with their counts", () => {
    renderFunnel(LADDER);
    expect(screen.getByTestId("ladder-funnel-L0")).toHaveAttribute("data-count", "12");
    expect(screen.getByTestId("ladder-funnel-L4")).toHaveAttribute("data-count", "1");
    // A zero rung still renders — the funnel's shape is the information.
    expect(screen.getByTestId("ladder-funnel-L5")).toHaveAttribute("data-count", "0");
    expect(screen.getByTestId("ladder-funnel-tally")).toHaveTextContent(
      "open 20 · surfaced 3 · killed 4",
    );
    expect(screen.getByRole("link", { name: /ladder/ })).toHaveAttribute(
      "href",
      "/ladder",
    );
  });

  it("counts parked on an unknown rung are summed, not silently dropped", () => {
    renderFunnel({ ...LADDER, histogram: { ...LADDER.histogram, L7: 2, L9: 1 } });
    expect(screen.getByTestId("ladder-funnel-beyond")).toHaveTextContent(
      "+3 beyond L5",
    );
  });

  it("a malformed histogram degrades to zeros, never a crash", () => {
    renderFunnel({
      ...LADDER,
      histogram: { L0: "many", L1: null, L2: NaN, L3: -4 } as unknown as Record<
        string,
        number
      >,
    });
    expect(screen.getByTestId("ladder-funnel-L0")).toHaveAttribute("data-count", "0");
    expect(screen.getByTestId("ladder-funnel-L3")).toHaveAttribute("data-count", "0");
  });

  it("a histogram that is not an object at all degrades to zeros", () => {
    renderFunnel({ ...LADDER, histogram: ["L0", 3] as unknown as Record<string, number> });
    expect(screen.getByTestId("ladder-funnel-L0")).toHaveAttribute("data-count", "0");
  });

  it("204 (ledger never written) HIDES the panel — no zero-row noise", async () => {
    stubFetch(204);
    const { container } = render(
      <MemoryRouter>
        <LadderMiniFunnel />
      </MemoryRouter>,
    );
    await waitFor(() => expect(container.firstChild).toBeNull());
    expect(screen.queryByTestId("ladder-funnel")).toBeNull();
  });

  it("a version-skew 404 HIDES the panel — the frontend simply runs ahead", async () => {
    stubFetch(404, { detail: "Not Found" });
    const { container } = render(
      <MemoryRouter>
        <LadderMiniFunnel />
      </MemoryRouter>,
    );
    await waitFor(() => expect(container.firstChild).toBeNull());
    expect(screen.queryByTestId("ladder-funnel-unavailable")).toBeNull();
  });

  it("a 500 does NOT hide — a broken ledger is reported, not disguised as absence", async () => {
    stubFetch(500, { detail: "idea_ledger unreadable: bad json" });
    render(
      <MemoryRouter>
        <LadderMiniFunnel />
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("ladder-funnel-unavailable")).toHaveTextContent(
        "ladder unreadable",
      ),
    );
  });

  it("initial={null} is the hidden state (fixture render, no fetch)", () => {
    const spy = vi.fn();
    vi.stubGlobal("fetch", spy);
    const { container } = renderFunnel(null);
    expect(container.firstChild).toBeNull();
    expect(spy).not.toHaveBeenCalled();
  });
});
