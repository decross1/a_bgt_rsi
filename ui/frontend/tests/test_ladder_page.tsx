// /ladder — the evidence-ladder page over GET /api/ladder. Pins: counts
// header + rung histogram labeled with the next test owed; status/rung
// filter chips; killed rows expand to their kill code + evidence-keyed
// reopening condition; agenda section; the 204 no-ledger state and the
// version-skew 404 BOTH fall back to the ideas.md render (the folded-in
// /ideas body) — honest notes, never red for a merely-missing artifact.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { LadderResponse } from "../src/types/schemas";

// Module-mock api/http so the SKEW case can reject with a status-carrying
// error through the production isVersionSkew404 path. Individual tests that
// use `initial` never fetch.
const mocks = vi.hoisted(() => ({
  getLadder: vi.fn(),
  getIdeas: vi.fn(),
  getHealth: vi.fn().mockResolvedValue({
    ok: true,
    hostname: "spark",
    telemetry_last_seen: null,
    version: "testsha",
  }),
}));
vi.mock("../src/api/http", () => ({
  getLadder: mocks.getLadder,
  getIdeas: mocks.getIdeas,
  getHealth: mocks.getHealth,
}));

import Ladder from "../src/routes/Ladder";

const FIXTURE: LadderResponse = {
  clusters: [
    {
      cluster_id: "cl-a",
      stem: "KV-cache eviction bias",
      status: "surfaced",
      evidence_level: "L4",
      origin: "consolidation",
      member_count: 2,
      last_event_ts: "2026-08-14T00:00:00Z",
      kill_reason: null,
      reopening_condition: null,
      open_agenda_count: 0,
    },
    {
      cluster_id: "cl-b",
      stem: "a killed idea",
      status: "killed",
      evidence_level: "L0",
      origin: "consolidation",
      member_count: 1,
      last_event_ts: "2026-08-13T00:00:00Z",
      kill_reason: {
        code: "redteam_fatal_flaw",
        evidence_key: "iteration:iter-002:redteam",
        detail: "redteam verdict fatal_flaw on iteration iter-002",
      },
      reopening_condition: {
        requires: "new_evidence",
        evidence_kind: "counterexample_run",
      },
      open_agenda_count: 0,
    },
    {
      cluster_id: "cl-c",
      stem: "an open idea",
      status: "open",
      evidence_level: "L1",
      origin: "consolidation",
      member_count: 1,
      last_event_ts: "2026-08-12T00:00:00Z",
      kill_reason: null,
      reopening_condition: null,
      open_agenda_count: 1,
    },
  ],
  histogram: { L0: 0, L1: 1, L2: 0, L3: 0, L4: 1, L5: 0 },
  counts: { open: 1, surfaced: 1, killed: 1 },
  agenda: [
    { topic: "probe the eviction schedule", source: "paper_gap", cluster_id: "cl-c" },
  ],
  next_owed: {
    L0: "literature screen",
    L1: "experiment_outcome with trials >= 30",
    L2: "replication evidence",
    L3: "adversarial vote survived",
    L4: "human validity verdict",
    L5: "none — ladder complete",
  },
};

describe("/ladder page", () => {
  it("renders counts header, labeled histogram, clusters and agenda", () => {
    render(<Ladder initial={FIXTURE} />);
    const header = screen.getByTestId("ladder-counts-header");
    expect(header).toHaveTextContent("1 open");
    expect(header).toHaveTextContent("1 surfaced");
    expect(header).toHaveTextContent("1 killed");

    // Histogram: every rung renders, labeled with its next-owed test.
    const l4 = screen.getByTestId("ladder-rung-L4");
    expect(l4).toHaveTextContent("L4");
    expect(l4).toHaveTextContent("1");
    expect(l4).toHaveTextContent("next: human validity verdict");
    expect(screen.getByTestId("ladder-rung-L0")).toHaveTextContent(
      "next: literature screen",
    );

    // Cluster rows.
    expect(screen.getByTestId("ladder-cluster-cl-a")).toHaveTextContent(
      "KV-cache eviction bias",
    );
    expect(screen.getByTestId("ladder-cluster-cl-c")).toHaveTextContent(
      "1 agenda",
    );

    // Agenda with provenance.
    const agenda = screen.getByTestId("ladder-agenda");
    expect(agenda).toHaveTextContent("probe the eviction schedule");
    expect(agenda).toHaveTextContent("source: paper_gap");
  });

  it("killed rows expand to the kill code + evidence-keyed reopen condition", () => {
    render(<Ladder initial={FIXTURE} />);
    const row = screen.getByTestId("ladder-cluster-cl-b");
    // <details> renders children regardless of open state — assert the
    // detail CONTENT lives inside the killed row.
    const detail = screen.getByTestId("ladder-kill-detail");
    expect(row.contains(detail)).toBe(true);
    expect(detail).toHaveTextContent("redteam_fatal_flaw");
    expect(detail).toHaveTextContent("reopen when:");
    expect(detail).toHaveTextContent("counterexample_run");
    // Live rows carry no kill detail.
    expect(
      screen.getByTestId("ladder-cluster-cl-a").querySelector(
        '[data-testid="ladder-kill-detail"]',
      ),
    ).toBeNull();
  });

  it("status chips filter the table (toggle back to all)", () => {
    render(<Ladder initial={FIXTURE} />);
    fireEvent.click(screen.getByTestId("ladder-filter-killed"));
    expect(screen.queryByTestId("ladder-cluster-cl-a")).toBeNull();
    expect(screen.getByTestId("ladder-cluster-cl-b")).toBeInTheDocument();
    // Toggle off restores everything.
    fireEvent.click(screen.getByTestId("ladder-filter-killed"));
    expect(screen.getByTestId("ladder-cluster-cl-a")).toBeInTheDocument();
  });

  it("rung chips filter the table and compose the honest no-match state", () => {
    render(<Ladder initial={FIXTURE} />);
    fireEvent.click(screen.getByTestId("ladder-filter-L4"));
    expect(screen.getByTestId("ladder-cluster-cl-a")).toBeInTheDocument();
    expect(screen.queryByTestId("ladder-cluster-cl-c")).toBeNull();
    // L4 + killed matches nothing — say so.
    fireEvent.click(screen.getByTestId("ladder-filter-killed"));
    expect(screen.getByTestId("ladder-no-match")).toBeInTheDocument();
  });

  it("204 (no ledger yet) renders the honest empty note + the ideas.md fallback", () => {
    render(
      <Ladder initial={null} initialIdeas={"# Ideas\n\n## Live work\n\n- x"} />,
    );
    expect(screen.getByTestId("ladder-empty")).toHaveTextContent(
      "no idea ledger yet",
    );
    expect(screen.getByTestId("ladder-ideas-fallback")).toHaveTextContent(
      "Live work",
    );
  });

  it("version-skew 404 renders EndpointMissingNote + the ideas.md fallback", async () => {
    mocks.getLadder.mockRejectedValue(
      Object.assign(new Error("404 Not Found"), { status: 404 }),
    );
    mocks.getIdeas.mockResolvedValue({ markdown: "# Ideas\n\nfallback body" });
    render(<Ladder />);
    await waitFor(() =>
      expect(screen.getByTestId("endpoint-missing-note")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("endpoint-missing-note")).toHaveTextContent(
      "/api/ladder",
    );
    await waitFor(() =>
      expect(screen.getByTestId("ladder-ideas-fallback")).toHaveTextContent(
        "fallback body",
      ),
    );
    // Skew is quiet degradation, never red.
    expect(screen.queryByTestId("ladder-error")).toBeNull();
  });

  it("a non-404 failure renders the honest red error", async () => {
    mocks.getLadder.mockRejectedValue(
      Object.assign(new Error("500 idea_ledger unreadable: boom"), {
        status: 500,
      }),
    );
    render(<Ladder />);
    await waitFor(() =>
      expect(screen.getByTestId("ladder-error")).toHaveTextContent(
        "idea_ledger unreadable",
      ),
    );
  });
});
