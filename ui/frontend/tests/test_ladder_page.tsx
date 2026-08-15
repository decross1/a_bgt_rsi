// /ladder — the revamp-R1 visual centerpiece over GET /api/ladder. Pins:
//   - the aggregate FUNNEL derives from the (live-only) histogram PLUS the
//     killed clusters' rung-at-death, so it narrows monotonically and the
//     kill-ribbons carry the honest per-rung body count;
//   - the KANBAN columns bucket live clusters by rung and route every killed
//     one to the collapsed graveyard, grouped by kill code;
//   - a card opens the PeekPanel, which is where the kill detail / reopening
//     condition / next-owed / members-with-dossier-links live;
//   - the board|table toggle is two views of ONE dataset;
//   - the kills-per-rung chart maps rung → kills;
//   - the ⌘K palette gains the page's two verbs;
//   - a cluster the producer gave no rung is REPORTED, never faked into L0;
//   - the 204 no-ledger state and the version-skew 404 BOTH fall back to the
//     ideas.md render — honest notes, never red for a merely-missing artifact.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
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

import CommandPalette from "../src/design/CommandPalette";
import Ladder from "../src/routes/Ladder";

// Six clusters exercising every bucket: one surfaced L4, one open L1 with an
// agenda item, three killed at L0/L1/L3 (two sharing a kill code), and one
// live cluster the producer gave NO evidence level.
const FIXTURE: LadderResponse = {
  clusters: [
    {
      cluster_id: "cl-a",
      stem: "KV-cache eviction bias",
      status: "surfaced",
      evidence_level: "L4",
      origin: "consolidation",
      members: ["iter-001", "paper:2508.00001"],
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
      members: ["iter-002"],
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
      members: ["iter-003"],
      member_count: 1,
      last_event_ts: "2026-08-12T00:00:00Z",
      kill_reason: null,
      reopening_condition: null,
      open_agenda_count: 1,
    },
    {
      cluster_id: "cl-d",
      stem: "killed for the same reason",
      status: "killed",
      evidence_level: "L1",
      origin: "consolidation",
      members: ["iter-004"],
      member_count: 1,
      last_event_ts: "2026-08-11T00:00:00Z",
      kill_reason: { code: "redteam_fatal_flaw", detail: "second fatal flaw" },
      reopening_condition: { requires: "new_evidence" },
      open_agenda_count: 0,
    },
    {
      cluster_id: "cl-e",
      stem: "a duplicate",
      status: "killed",
      evidence_level: "L3",
      origin: "consolidation",
      members: ["iter-005"],
      member_count: 4,
      last_event_ts: "2026-08-10T00:00:00Z",
      kill_reason: { code: "duplicate_of_existing", detail: "dupe of cl-a" },
      reopening_condition: null,
      open_agenda_count: 0,
    },
    {
      cluster_id: "cl-f",
      stem: "no rung recorded",
      status: "open",
      evidence_level: null,
      origin: "niche_seed",
      members: ["paper:2508.00002"],
      member_count: 1,
      last_event_ts: "2026-08-09T00:00:00Z",
      kill_reason: null,
      reopening_condition: null,
      open_agenda_count: 0,
    },
  ],
  // Live rungs only (the backend excludes killed clusters).
  histogram: { L0: 0, L1: 1, L2: 0, L3: 0, L4: 1, L5: 0 },
  counts: { open: 2, surfaced: 1, killed: 3 },
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

function renderLadder(props: Parameters<typeof Ladder>[0] = {}) {
  return render(
    <MemoryRouter>
      <Ladder {...props} />
    </MemoryRouter>,
  );
}

describe("/ladder funnel strip", () => {
  it("narrows monotonically from the live histogram + the killed rungs", () => {
    renderLadder({ initial: FIXTURE });
    // reached[k] = live at rungs >= k (histogram) + killed at rungs >= k.
    // L0: 0 live + 1 killed(cl-b) below, plus everything above -> 5.
    const expected = { L0: 5, L1: 4, L2: 2, L3: 2, L4: 1, L5: 0 };
    const seen: number[] = [];
    for (const [level, n] of Object.entries(expected)) {
      const g = screen.getByTestId(`funnel-rung-${level}`);
      expect(g).toHaveAttribute("data-reached", String(n));
      seen.push(Number(g.getAttribute("data-reached")));
    }
    // The shape is a funnel because the series never widens.
    for (let i = 1; i < seen.length; i += 1) {
      expect(seen[i]).toBeLessThanOrEqual(seen[i - 1]);
    }
  });

  it("drops a kill ribbon only from the rungs that actually killed something", () => {
    renderLadder({ initial: FIXTURE });
    expect(screen.getByTestId("funnel-rung-L0")).toHaveAttribute("data-killed", "1");
    expect(screen.getByTestId("funnel-rung-L1")).toHaveAttribute("data-killed", "1");
    expect(screen.getByTestId("funnel-rung-L3")).toHaveAttribute("data-killed", "1");
    expect(screen.getByTestId("funnel-rung-L2")).toHaveAttribute("data-killed", "0");
    expect(screen.getByTestId("funnel-ribbon-L0")).toBeInTheDocument();
    expect(screen.queryByTestId("funnel-ribbon-L2")).toBeNull();
    // Every ribbon lands in the one graveyard node.
    expect(screen.getByTestId("funnel-graveyard")).toHaveAttribute(
      "data-total",
      "3",
    );
  });

  it("carries the counts header beside the funnel", () => {
    renderLadder({ initial: FIXTURE });
    const header = screen.getByTestId("ladder-counts-header");
    expect(header).toHaveTextContent("2 open");
    expect(header).toHaveTextContent("1 surfaced");
    expect(header).toHaveTextContent("3 killed");
    expect(header).toHaveTextContent("1 open agenda");
  });
});

describe("/ladder kills-per-rung chart", () => {
  it("maps each rung to the clusters killed there", () => {
    renderLadder({ initial: FIXTURE });
    expect(screen.getByTestId("kills-by-rung")).toHaveAttribute("data-total", "3");
    expect(screen.getByTestId("kills-chart")).toHaveAttribute(
      "aria-label",
      "Kills per rung: L0 1, L1 1, L2 0, L3 1, L4 0, L5 0.",
    );
  });

  it("says so honestly when nothing has been killed at a known rung", () => {
    renderLadder({
      initial: {
        ...FIXTURE,
        clusters: [FIXTURE.clusters![0]],
        counts: { open: 0, surfaced: 1, killed: 0 },
      },
    });
    expect(screen.getByTestId("kills-by-rung-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("kills-chart")).toBeNull();
  });
});

describe("/ladder board", () => {
  it("buckets live clusters into their rung column", () => {
    renderLadder({ initial: FIXTURE });
    expect(
      within(screen.getByTestId("ladder-column-L1")).getByTestId("ladder-card-cl-c"),
    ).toBeInTheDocument();
    expect(
      within(screen.getByTestId("ladder-column-L4")).getByTestId("ladder-card-cl-a"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("ladder-column-L4")).toHaveAttribute("data-count", "1");
    expect(screen.getByTestId("ladder-column-L0")).toHaveAttribute("data-count", "0");
    // Every rung gets a column even when empty.
    for (const l of ["L0", "L1", "L2", "L3", "L4", "L5"]) {
      expect(screen.getByTestId(`ladder-column-${l}`)).toBeInTheDocument();
    }
  });

  it("routes killed clusters to the graveyard, never to their rung column", () => {
    renderLadder({ initial: FIXTURE });
    // cl-b died at L0 — its card is not in the L0 column.
    expect(
      within(screen.getByTestId("ladder-column-L0")).queryByTestId("ladder-card-cl-b"),
    ).toBeNull();
    expect(screen.getByTestId("ladder-column-graveyard")).toHaveAttribute(
      "data-count",
      "3",
    );
  });

  it("keeps the graveyard collapsed until asked, then groups by kill code", () => {
    renderLadder({ initial: FIXTURE });
    const toggle = screen.getByTestId("ladder-graveyard-toggle");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("ladder-card-cl-b")).toBeNull();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const group = screen.getByTestId("ladder-graveyard-group-redteam_fatal_flaw");
    // Biggest group first, and both same-code tombstones live in it.
    expect(group).toHaveTextContent("redteam_fatal_flaw · 2");
    expect(within(group).getByTestId("ladder-card-cl-b")).toBeInTheDocument();
    expect(within(group).getByTestId("ladder-card-cl-d")).toBeInTheDocument();
    expect(
      screen.getByTestId("ladder-graveyard-group-duplicate_of_existing"),
    ).toHaveTextContent("duplicate_of_existing · 1");
  });

  it("keeps the rung-at-death glyph on a tombstone", () => {
    renderLadder({ initial: FIXTURE });
    fireEvent.click(screen.getByTestId("ladder-graveyard-toggle"));
    const glyph = within(screen.getByTestId("ladder-card-cl-e")).getByTestId(
      "rung-glyph",
    );
    expect(glyph).toHaveAttribute("data-rung", "L3");
    expect(glyph).toHaveAttribute("data-killed", "true");
  });

  it("puts ONE metric on a card — agenda when open, otherwise members", () => {
    renderLadder({ initial: FIXTURE });
    expect(screen.getByTestId("ladder-card-cl-c")).toHaveTextContent("1 agenda");
    expect(screen.getByTestId("ladder-card-cl-a")).toHaveTextContent("2 members");
    // The card does NOT carry the kill code / origin / cluster id.
    expect(screen.getByTestId("ladder-card-cl-a")).not.toHaveTextContent("cl-a");
  });

  it("reports a rung-less cluster instead of faking it into L0", () => {
    renderLadder({ initial: FIXTURE });
    expect(screen.getByTestId("ladder-unrung-note")).toHaveTextContent(
      "1 cluster carry no evidence level",
    );
    expect(
      within(screen.getByTestId("ladder-column-L0")).queryByTestId("ladder-card-cl-f"),
    ).toBeNull();
  });
});

describe("/ladder peek panel", () => {
  it("opens from a tombstone with the kill code + reopening condition", () => {
    renderLadder({ initial: FIXTURE });
    fireEvent.click(screen.getByTestId("ladder-graveyard-toggle"));
    fireEvent.click(screen.getByTestId("ladder-card-cl-b"));

    const peek = screen.getByTestId("peek-panel");
    expect(peek).toHaveTextContent("a killed idea");
    const kill = screen.getByTestId("ladder-peek-kill");
    expect(kill).toHaveTextContent("redteam_fatal_flaw");
    expect(kill).toHaveTextContent("iteration:iter-002:redteam");
    expect(screen.getByTestId("ladder-peek-reopen")).toHaveTextContent(
      "counterexample_run",
    );
    // A dead cluster owes no next test.
    expect(screen.queryByTestId("ladder-peek-owed")).toBeNull();
  });

  it("opens from a live card with the next test owed, its agenda and members", () => {
    renderLadder({ initial: FIXTURE });
    fireEvent.click(screen.getByTestId("ladder-card-cl-c"));
    expect(screen.getByTestId("ladder-peek-owed")).toHaveTextContent(
      "experiment_outcome with trials >= 30",
    );
    expect(screen.getByTestId("ladder-peek-agenda")).toHaveTextContent(
      "probe the eviction schedule",
    );
    expect(screen.getByTestId("ladder-peek-agenda")).toHaveTextContent("paper_gap");
    expect(screen.queryByTestId("ladder-peek-kill")).toBeNull();
  });

  it("links iteration-shaped members onward to their dossier, others as text", () => {
    renderLadder({ initial: FIXTURE });
    fireEvent.click(screen.getByTestId("ladder-card-cl-a"));
    const members = screen.getByTestId("ladder-peek-members");
    expect(within(members).getByText("iter-001")).toHaveAttribute(
      "href",
      "/dossier/iter-001",
    );
    // A paper member is not a dossier — it renders unlinked.
    expect(within(members).getByText("paper:2508.00001").tagName).not.toBe("A");
  });

  it("closes on Escape", () => {
    renderLadder({ initial: FIXTURE });
    fireEvent.click(screen.getByTestId("ladder-card-cl-a"));
    expect(screen.getByTestId("peek-panel")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByTestId("peek-panel")).toBeNull();
  });
});

describe("/ladder header", () => {
  it("points at the lab's QUEUE, which lives in Pulse's secondary zone", () => {
    // This board is the ladder's STATE; what those clusters owe next (plus
    // the agenda and the refine candidates) is the LabTodo panel on Pulse.
    renderLadder({ initial: FIXTURE });
    expect(screen.getByTestId("ladder-lab-queue-link")).toHaveAttribute(
      "href",
      "/#lab-queue",
    );
  });
});

describe("/ladder view toggle", () => {
  it("switches between the board and the table over the same dataset", () => {
    renderLadder({ initial: FIXTURE });
    expect(screen.getByTestId("ladder-board")).toBeInTheDocument();
    expect(screen.queryByTestId("ladder-table")).toBeNull();

    fireEvent.click(screen.getByTestId("ladder-view-table"));
    expect(screen.queryByTestId("ladder-board")).toBeNull();
    const table = screen.getByTestId("ladder-table");
    // The table view holds EVERY cluster — killed and rung-less included.
    for (const id of ["cl-a", "cl-b", "cl-c", "cl-d", "cl-e", "cl-f"]) {
      expect(within(table).getByTestId(`ladder-row-${id}`)).toBeInTheDocument();
    }
    // The strip stays put; only the body swaps.
    expect(screen.getByTestId("ladder-funnel")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("ladder-view-board"));
    expect(screen.getByTestId("ladder-board")).toBeInTheDocument();
  });

  it("sorts the table by a clicked column and opens the same peek", () => {
    renderLadder({ initial: FIXTURE });
    fireEvent.click(screen.getByTestId("ladder-view-table"));
    const rowIds = () =>
      Array.from(
        screen.getByTestId("ladder-table").querySelectorAll('[data-testid^="ladder-row-"]'),
      ).map((el) => el.getAttribute("data-testid"));

    // Default: rung, descending — the L4 cluster leads.
    expect(rowIds()[0]).toBe("ladder-row-cl-a");
    // By members descending, cl-e (4) leads.
    fireEvent.click(screen.getByTestId("ladder-sort-members"));
    expect(rowIds()[0]).toBe("ladder-row-cl-e");
    // Clicking again flips the direction.
    fireEvent.click(screen.getByTestId("ladder-sort-members"));
    expect(rowIds()[0]).not.toBe("ladder-row-cl-e");

    fireEvent.click(screen.getByTestId("ladder-row-cl-b"));
    expect(screen.getByTestId("ladder-peek-kill")).toHaveTextContent(
      "redteam_fatal_flaw",
    );
  });
});

describe("/ladder command palette verbs", () => {
  it("registers the page's verbs and they drive the page", () => {
    render(
      <MemoryRouter>
        <CommandPalette />
        <Ladder initial={FIXTURE} />
      </MemoryRouter>,
    );
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    const palette = screen.getByTestId("command-palette");
    expect(within(palette).getByText("toggle graveyard")).toBeInTheDocument();

    fireEvent.click(within(palette).getByText("switch ladder view"));
    expect(screen.getByTestId("ladder-table")).toBeInTheDocument();
  });
});

describe("/ladder honest degraded states", () => {
  it("204 (no ledger yet) renders the honest empty note + the ideas.md fallback", () => {
    renderLadder({
      initial: null,
      initialIdeas: "# Ideas\n\n## Live work\n\n- x",
    });
    expect(screen.getByTestId("ladder-empty")).toHaveTextContent(
      "no idea ledger yet",
    );
    expect(screen.getByTestId("ladder-ideas-fallback")).toHaveTextContent(
      "Live work",
    );
    // No funnel, no board — there is nothing to draw.
    expect(screen.queryByTestId("ladder-funnel")).toBeNull();
    expect(screen.queryByTestId("ladder-board")).toBeNull();
  });

  it("version-skew 404 renders EndpointMissingNote + the ideas.md fallback", async () => {
    mocks.getLadder.mockRejectedValue(
      Object.assign(new Error("404 Not Found"), { status: 404 }),
    );
    mocks.getIdeas.mockResolvedValue({ markdown: "# Ideas\n\nfallback body" });
    renderLadder();
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
    renderLadder();
    await waitFor(() =>
      expect(screen.getByTestId("ladder-error")).toHaveTextContent(
        "idea_ledger unreadable",
      ),
    );
    expect(screen.queryByTestId("ladder-funnel")).toBeNull();
  });

  it("an empty ledger still draws the funnel — at zero, with no fake bars", () => {
    renderLadder({
      initial: {
        clusters: [],
        histogram: { L0: 0, L1: 0, L2: 0, L3: 0, L4: 0, L5: 0 },
        counts: { open: 0, surfaced: 0, killed: 0 },
        agenda: [],
        next_owed: {},
      },
    });
    expect(screen.getByTestId("funnel-rung-L0")).toHaveAttribute("data-reached", "0");
    expect(screen.getByTestId("funnel-graveyard")).toHaveAttribute("data-total", "0");
    expect(screen.getByTestId("kills-by-rung-empty")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("ladder-view-table"));
    expect(screen.getByTestId("ladder-table-empty")).toBeInTheDocument();
  });
});
