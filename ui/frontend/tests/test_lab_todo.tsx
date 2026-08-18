// LabTodo — "The lab's queue" (GET /api/lab_todo). The load-bearing pins:
//
//  1. the OWNERSHIP distinction is stated, not implied — the header says this
//     is not the human's queue, and the human_gaps arrive as ONE muted line
//     pointing back at the OweStrip hero, NEVER as a second todo list;
//  2. every section has an HONEST empty state (a quiet lab is not a blank
//     panel), and a failed read says the queue is UNKNOWN, not empty;
//  3. the refine section says out loud that refine_idea is a coordinator
//     action — this surface does not trigger it;
//  4. a version-skew 404 degrades to the EndpointMissingNote.
import { act, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import LabTodo from "../src/components/LabTodo";
import type { LabTodoResponse } from "../src/types/schemas";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers(); // the frozen-age tests fake the clock
});

const PAYLOAD: LabTodoResponse = {
  gaps_source: "assess_state",
  gaps_as_of: null,
  agent_gaps: [
    "4 open cluster(s) at L1 awaiting synthetic experiment",
    "loop has not iterated in 6 days",
  ],
  human_gaps: [
    "3 recent iteration(s) await a human gate verdict",
    "2 surfaced finding(s) await human review",
  ],
  owed: [
    {
      test: "literature-consistency pass",
      rung: "L0",
      clusters: [
        { cluster_id: "cl-c", stem: "router entropy collapse", last_event_ts: "2026-08-04T00:00:00Z" },
      ],
    },
    {
      test: "synthetic experiment",
      rung: "L1",
      clusters: [
        { cluster_id: "cl-a", stem: "KV-cache eviction bias", last_event_ts: "2026-08-02T00:00:00Z" },
        { cluster_id: "cl-b", stem: "prefix reuse drift", last_event_ts: "2026-08-02T01:00:00Z" },
        { cluster_id: "cl-d", stem: "speculative decode drift", last_event_ts: "2026-08-02T02:00:00Z" },
      ],
    },
  ],
  agenda: [
    { topic: "probe the eviction schedule", source: "paper_gap", cluster_id: "cl-c" },
  ],
  refine_candidates: [
    { cluster_id: "cl-k", stem: "quantized router noise", kill_code: "redteam_fatal_flaw" },
    { cluster_id: "cl-p01", stem: "cl-p01", kill_code: "paper_prior_exists" },
  ],
  generated_at: "2026-08-15T12:00:00Z",
};

const EMPTY: LabTodoResponse = {
  gaps_source: "assess_state",
  gaps_as_of: null,
  agent_gaps: [],
  human_gaps: [],
  owed: [],
  agenda: [],
  refine_candidates: [],
  generated_at: "2026-08-15T12:00:00Z",
};

function renderPanel(initial?: LabTodoResponse) {
  return render(
    <MemoryRouter>
      <LabTodo initial={initial} />
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

describe("LabTodo", () => {
  it("names whose queue this is, and it is not the human's", () => {
    renderPanel(PAYLOAD);
    expect(screen.getByTestId("lab-todo")).toHaveTextContent("The lab's queue");
    expect(screen.getByTestId("lab-todo")).toHaveTextContent(
      "what Nara and the PI advance on their own — not your queue",
    );
  });

  it("groups owed tests by rung, with the cluster ids under each", () => {
    renderPanel(PAYLOAD);
    const l1 = screen.getByTestId("lab-todo-owed-L1");
    expect(l1).toHaveAttribute("data-count", "3");
    expect(l1).toHaveTextContent("3 clusters owe synthetic experiment");
    // The ids are there (a <details> body renders in jsdom regardless of open
    // state) and every one links into the ladder board.
    for (const cid of ["cl-a", "cl-b", "cl-d"]) {
      expect(within(l1).getByRole("link", { name: cid })).toHaveAttribute(
        "href",
        "/ladder",
      );
    }
    // Singular/plural is not faked: one cluster reads "1 cluster owes".
    expect(screen.getByTestId("lab-todo-owed-L0")).toHaveTextContent(
      "1 cluster owes literature-consistency pass",
    );
  });

  it("lists the agenda with its provenance", () => {
    renderPanel(PAYLOAD);
    const row = screen.getByTestId("lab-todo-agenda-0");
    expect(row).toHaveTextContent("probe the eviction schedule");
    expect(row).toHaveTextContent("source: paper_gap");
  });

  it("names the refine candidates AND that the UI cannot trigger them", () => {
    renderPanel(PAYLOAD);
    expect(screen.getByTestId("lab-todo-refine-count")).toHaveTextContent(
      "2 killed clusters a refine cycle could still improve",
    );
    expect(screen.getByTestId("lab-todo-refine-0")).toHaveTextContent(
      "redteam_fatal_flaw",
    );
    expect(screen.getByTestId("lab-todo-refine-note")).toHaveTextContent(
      "refine_idea is a coordinator action (cost 2)",
    );
    expect(screen.getByTestId("lab-todo-refine-note")).toHaveTextContent(
      "does not trigger it",
    );
    // No button anywhere in the panel — the read-only fence is structural.
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });

  it("shows the coordinator's own gap sentences, agent-actionable only", () => {
    renderPanel(PAYLOAD);
    const gaps = screen.getByTestId("lab-todo-gaps");
    expect(gaps).toHaveTextContent("loop has not iterated in 6 days");
    // The human-owed gaps are NEVER restated as rows here.
    expect(gaps.textContent).not.toContain("await a human gate verdict");
    expect(gaps.textContent).not.toContain("await human review");
  });

  it("renders human gaps as ONE muted line pointing at the hero, not a list", () => {
    renderPanel(PAYLOAD);
    const blocked = screen.getByTestId("lab-todo-blocked");
    expect(blocked).toHaveTextContent("2 of the loop's gaps wait on you");
    expect(within(blocked).getByRole("link", { name: /what you owe/ })).toHaveAttribute(
      "href",
      "#what-you-owe",
    );
    // The gap TEXT itself stays in the hero's territory — this is a pointer,
    // never a second todo list.
    expect(blocked.textContent).not.toContain("await a human gate verdict");
    expect(blocked.querySelectorAll("li")).toHaveLength(0);
  });

  it("drops the blocked line entirely when nothing waits on the human", () => {
    renderPanel(EMPTY);
    expect(screen.queryByTestId("lab-todo-blocked")).not.toBeInTheDocument();
  });

  it("every section has an honest empty state", () => {
    renderPanel(EMPTY);
    expect(screen.getByTestId("lab-todo-owed-empty")).toHaveTextContent(
      "no open cluster is parked on a rung",
    );
    expect(screen.getByTestId("lab-todo-agenda-empty")).toHaveTextContent(
      "nothing queued",
    );
    expect(screen.getByTestId("lab-todo-refine-empty")).toHaveTextContent(
      "no killed cluster is still improvable",
    );
    expect(screen.getByTestId("lab-todo-gaps-empty")).toHaveTextContent(
      "the loop is honestly idle",
    );
  });

  it("dates the gaps when they came from the last cycle, not a live read", () => {
    // The PRODUCTION path (ui/.venv cannot import the coordinator). The panel
    // must never let persisted gaps read as live.
    renderPanel({
      ...PAYLOAD,
      gaps_source: "last_cycle",
      gaps_as_of: new Date(Date.now() - 3 * 3_600_000).toISOString(),
    });
    expect(screen.getByTestId("lab-todo-gaps-asof")).toHaveTextContent(
      "as of the coordinator's last cycle, 3h ago — not a live read",
    );
  });

  it("a live read carries no as-of note", () => {
    renderPanel(PAYLOAD);
    expect(screen.queryByTestId("lab-todo-gaps-asof")).not.toBeInTheDocument();
  });

  it("gaps the backend could not read say UNKNOWN, never 'honestly idle'", () => {
    // The dangerous confusion this pins: "no gaps" and "could not read the
    // gaps" look identical on the wire (both empty lists). Only gaps_source
    // separates them, and calling the second one "idle" would be a lie.
    renderPanel({ ...EMPTY, gaps_source: "unavailable" });
    expect(screen.getByTestId("lab-todo-gaps-unknown")).toHaveTextContent(
      "gaps UNKNOWN",
    );
    expect(screen.queryByTestId("lab-todo-gaps-empty")).not.toBeInTheDocument();
  });

  it("a version-skew 404 degrades to the endpoint-missing note", async () => {
    stubFetch(404, { detail: "Not Found" });
    renderPanel();
    await waitFor(() =>
      expect(screen.getByTestId("endpoint-missing-note")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("endpoint-missing-note")).toHaveTextContent(
      "/api/lab_todo",
    );
    expect(screen.queryByTestId("lab-todo-owed")).not.toBeInTheDocument();
  });

  it("a 500 says the queue is UNKNOWN — never a calm empty panel", async () => {
    stubFetch(500, { detail: "idea_ledger unreadable: malformed JSON" });
    renderPanel();
    await waitFor(() =>
      expect(screen.getByTestId("lab-todo-error")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("lab-todo-error")).toHaveTextContent(
      "UNKNOWN, not empty",
    );
    expect(screen.getByTestId("lab-todo-error")).toHaveTextContent(
      "idea_ledger unreadable",
    );
    // The honest empty states must NOT render off a failed read.
    expect(screen.queryByTestId("lab-todo-owed-empty")).not.toBeInTheDocument();
  });

  it("producer-owned junk degrades instead of crashing the panel", () => {
    renderPanel({
      agent_gaps: ["real gap", 42, null, { nope: 1 }] as unknown as string[],
      human_gaps: "not a list" as unknown as string[],
      owed: [
        null,
        { test: null, rung: null, clusters: "nope" },
        { test: "synthetic experiment", rung: "L1", clusters: [null, { stem: "no id" }] },
      ] as unknown as LabTodoResponse["owed"],
      agenda: [{ topic: null, source: null, cluster_id: null }],
      refine_candidates: [{ cluster_id: null, kill_code: null }],
      generated_at: null,
    });
    // Only the one legible gap string survives.
    expect(screen.getByTestId("lab-todo-gap-0")).toHaveTextContent("real gap");
    expect(screen.queryByTestId("lab-todo-gap-1")).not.toBeInTheDocument();
    // A non-list human_gaps is "none", not a crash.
    expect(screen.queryByTestId("lab-todo-blocked")).not.toBeInTheDocument();
    // A group whose clusters are not a list counts zero rather than guessing.
    expect(screen.getByTestId("lab-todo-owed-unknown")).toHaveAttribute(
      "data-count",
      "0",
    );
    expect(screen.getByTestId("lab-todo-owed-L1")).toHaveAttribute(
      "data-count",
      "1",
    );
    expect(screen.getByTestId("lab-todo-agenda-0")).toHaveTextContent(
      "(untitled topic)",
    );
    expect(screen.getByTestId("lab-todo-refine-0")).toHaveTextContent("(no id)");
  });

  it("an off-enum rung is reported as itself, never coerced onto the ladder", () => {
    renderPanel({
      ...EMPTY,
      owed: [
        {
          test: "unknown evidence level 'L9' — ladder position cannot be assessed",
          rung: "L9",
          clusters: [{ cluster_id: "cl-x", stem: "mystery", last_event_ts: null }],
        },
      ],
    });
    const row = screen.getByTestId("lab-todo-owed-L9");
    expect(row).toHaveTextContent("L9");
    expect(row).toHaveTextContent("ladder position cannot be assessed");
    // RungGlyph is only drawn for the six real rungs.
    expect(row.querySelector('[role="img"]')).toBeNull();
  });
});

// ── The backend's OWN staleness stamps (residual fix 3, 2026-08-18) ────────
// ui/backend/lab_todo.py serves stale-while-revalidate and stamps
// cache_age_s + refresh_error on EVERY response ("stale is always legible
// as stale"). The panel must display both — and never blank the list while
// doing so.
describe("LabTodo backend cache legibility (cache_age_s / refresh_error)", () => {
  it("a cache_age_s past the 90s fresh window renders the muted 'as of Xs ago' line", () => {
    renderPanel({ ...PAYLOAD, cache_age_s: 95, refresh_error: null });
    const note = screen.getByTestId("lab-todo-cache-age");
    expect(note).toHaveTextContent("as of 95s ago");
    expect(note).toHaveTextContent("served from the backend's cache");
    // The list is NEVER blanked by staleness.
    expect(screen.getByTestId("lab-todo-owed-L1")).toHaveAttribute(
      "data-count",
      "3",
    );
  });

  it("a fresh cache_age_s (inside the window) renders NO cache-age line", () => {
    renderPanel({ ...PAYLOAD, cache_age_s: 5.0, refresh_error: null });
    expect(screen.queryByTestId("lab-todo-cache-age")).toBeNull();
  });

  it("an older backend that stamps neither field renders neither note", () => {
    renderPanel(PAYLOAD); // no cache_age_s / refresh_error keys at all
    expect(screen.queryByTestId("lab-todo-cache-age")).toBeNull();
    expect(screen.queryByTestId("lab-todo-refresh-error")).toBeNull();
  });

  it("a set refresh_error renders the amber 'refresh failing' note WITH the list", () => {
    renderPanel({
      ...PAYLOAD,
      cache_age_s: 200,
      refresh_error: "ValueError: idea ledger row 41 unparseable",
    });
    const note = screen.getByTestId("lab-todo-refresh-error");
    expect(note).toHaveTextContent("refresh failing");
    expect(note).toHaveTextContent("ValueError: idea ledger row 41 unparseable");
    // Both notes can coexist (stale AND failing to rebuild)…
    expect(screen.getByTestId("lab-todo-cache-age")).toBeInTheDocument();
    // …and the queue still renders in full: stale ≠ blank.
    expect(screen.getByTestId("lab-todo-owed-L1")).toHaveAttribute(
      "data-count",
      "3",
    );
    expect(screen.getByTestId("lab-todo-agenda-0")).toBeInTheDocument();
  });
});

// ── Frozen ages (residual fix 4, 2026-08-18) ───────────────────────────────
// Under pollhub change detection the panel re-renders only when the payload
// CHANGES, so a Date.now()-at-render age froze at the last data change. The
// age text now self-ticks (a 30s useNow scoped to the LiveAge leaf).
describe("LabTodo ages advance without a data change", () => {
  it("the gaps-as-of age ticks forward while the payload stays identical", async () => {
    vi.useFakeTimers();
    const TEN_MIN = 10 * 60_000;
    renderPanel({
      ...EMPTY,
      gaps_source: "last_cycle",
      gaps_as_of: new Date(Date.now() - TEN_MIN).toISOString(),
    });
    expect(screen.getByTestId("lab-todo-gaps-asof")).toHaveTextContent(
      "10m ago",
    );
    // Two minutes pass with NO new payload (fixture mode never refetches):
    // the age must advance anyway — this froze at "10m" before the fix.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2 * 60_000);
    });
    expect(screen.getByTestId("lab-todo-gaps-asof")).toHaveTextContent(
      "12m ago",
    );
  });
});
