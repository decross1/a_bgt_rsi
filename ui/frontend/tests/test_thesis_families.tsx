import { StrictMode } from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import Ladder from "../src/routes/Ladder";
import { getIterations, getLadder } from "../src/api/http";
import { refreshPoll } from "../src/api/pollhub";
import { TOPIC_FIELDS } from "../src/api/ladder";
import type { LadderCluster, LadderResponse } from "../src/types/schemas";
import ThesisFamilies from "../src/components/ladder/ThesisFamilies";

vi.mock("../src/api/http", () => ({
  getLadder: vi.fn(), getIterations: vi.fn(), getIdeas: vi.fn(),
}));

const topics = [
  "Representation in Peer Selection: A Liquid Democracy Perspective",
  "Power in Liquid Democracy: A Network Centrality Approach",
];
const rows = [
  { iteration_id: "iter-2026-01-01-001", seed: { topic: topics[0] }, hypothesis: { text: "Distinct recorded spectral-gap question" } },
  { iteration_id: "iter-2026-01-01-002", seed: { topic: topics[0] }, hypothesis: { text: "Distinct recorded clustering question" } },
  { iteration_id: "iter-2026-01-01-003", seed: { topic: topics[1] }, hypothesis: { text: "Distinct recorded centrality question" } },
];
const fixture: LadderResponse & { clusters: LadderCluster[]; histogram: Record<string, number> } = {
  clusters: rows.map((r, i) => ({
    cluster_id: `cl-${r.iteration_id}`, stem: `cl-${r.iteration_id}`, status: "open",
    evidence_level: "L1", members: [r.iteration_id], member_count: 1,
    origin: "consolidation", last_event_ts: `2026-01-0${i + 1}T00:00:00Z`,
    kill_reason: null, reopening_condition: null, open_agenda_count: 0,
  })),
  counts: { open: 3, surfaced: 0, killed: 0 },
  histogram: { L0: 0, L1: 3, L2: 0, L3: 0, L4: 0, L5: 0 },
  agenda: [], next_owed: { L1: "A discriminating experiment" },
};

function page(data = fixture, iterations: unknown[] = rows) {
  return <MemoryRouter><Ladder initial={data} initialIterations={iterations} /></MemoryRouter>;
}

describe("collection classification bars", () => {
  it("keeps all-record denominators while status and search filters change matches", () => {
    const data = structuredClone(fixture);
    data.clusters[0].evidence_level = "L0";
    data.clusters[2].evidence_level = "L2";
    data.clusters[2].status = "killed";
    const before = JSON.stringify(data);
    render(page(data));
    const family = screen.getByTestId("thesis-family-collection:liquid-democracy");
    const stages = within(family).getByRole("img", { name: /^Recorded stages for all 3 records:/ });
    const statuses = within(family).getByRole("img", { name: /^Recorded statuses for all 3 records:/ });
    expect(stages).toHaveAccessibleName(/L0 1 of 3; L1 1 of 3; L2 1 of 3/);
    expect(statuses).toHaveAccessibleName(/open 2 of 3; surfaced 0 of 3; killed 1 of 3/);
    expect(stages.closest("button")).toBeNull();
    expect(within(family).getByRole("button", { name: "Expand curated association: Liquid democracy" }))
      .toHaveAccessibleDescription(/All 3 records.*Recorded stages for all 3 records:.*Recorded statuses for all 3 records:/);
    expect(within(family).queryByRole("progressbar")).not.toBeInTheDocument();
    expect(within(family).getByText("All 3 records")).toBeVisible();
    expect(within(family).getByText("2 of 3 records")).toBeVisible();
    const originalLabels = [stages.getAttribute("aria-label"), statuses.getAttribute("aria-label")];
    const widths = Array.from(stages.querySelectorAll<HTMLElement>("[data-classification]"))
      .map((segment) => Number.parseFloat(segment.style.width));
    expect(widths).toHaveLength(3);
    expect(widths.reduce((a, b) => a + b, 0)).toBeCloseTo(100);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "clustering question" } });
    expect(within(family).getByText("1 of 3 records")).toBeVisible();
    expect([stages.getAttribute("aria-label"), statuses.getAttribute("aria-label")]).toEqual(originalLabels);
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(within(family).getByText("3 records")).toBeVisible();
    expect([stages.getAttribute("aria-label"), statuses.getAttribute("aria-label")]).toEqual(originalLabels);
    expect(JSON.stringify(data)).toBe(before);
  });

  it("keeps missing and unrecognized classifications visible with exact non-color counts", () => {
    const data = structuredClone(fixture);
    data.clusters[0].evidence_level = null as unknown as string;
    data.clusters[1].evidence_level = "L7";
    data.clusters[1].status = "paused";
    data.clusters[2].status = null as unknown as string;
    render(page(data));
    const family = screen.getByTestId("thesis-family-collection:liquid-democracy");
    const stages = within(family).getByRole("img", { name: /^Recorded stages for all 3 records:/ });
    const statuses = within(family).getByRole("img", { name: /^Recorded statuses for all 3 records:/ });
    expect(stages).toHaveAccessibleName(/unknown 2 of 3/);
    expect(statuses).toHaveAccessibleName(/paused \(unrecognized\) 1 of 3/);
    expect(statuses).toHaveAccessibleName(/unknown 1 of 3/);
    expect(within(stages).getByText("unknown 2")).toBeVisible();
    expect(within(statuses).getByText("paused (unrecognized) 1")).toBeVisible();
    expect(within(statuses).getByText("unknown 1")).toBeVisible();
    expect(within(stages).getByText("L1 1")).toBeVisible();
  });

  it("reports zero categories explicitly without drawing positive-width zero segments", () => {
    render(page());
    const family = screen.getByTestId("thesis-family-collection:liquid-democracy");
    const stages = within(family).getByRole("img", { name: /^Recorded stages for all 3 records:/ });
    expect(stages).toHaveAccessibleName(/L0 0 of 3; L1 3 of 3; L2 0 of 3; L3 0 of 3; L4 0 of 3; L5 0 of 3; unknown 0 of 3/);
    const segments = stages.querySelectorAll<HTMLElement>("[data-classification]");
    expect(segments).toHaveLength(1);
    expect(segments[0]).toHaveAttribute("data-classification", "L1");
    expect(segments[0]).toHaveStyle({ width: "100%" });
    expect(within(stages).getByText("L1 3")).toBeVisible();
  });

  it("shows an empty-record state instead of a fabricated zero-denominator distribution", () => {
    render(<MemoryRouter><ThesisFamilies model={{ records: [], families: [], issues: [] }} nextOwed={{}} onPick={vi.fn()} nowMs={0} /></MemoryRouter>);
    expect(screen.getByRole("status")).toHaveTextContent("No records match the current filters.");
    expect(screen.getByText(/0 of 0 records/)).toBeVisible();
    expect(screen.queryByRole("img", { name: /^Recorded (stages|statuses) for all/ })).not.toBeInTheDocument();
    expect(document.body.innerHTML).not.toMatch(/NaN|Infinity/);
  });

  it("retains an exact rare-class count without rounding it to zero or changing its denominator", () => {
    const clusters = Array.from({ length: 101 }, (_, i) => ({ ...fixture.clusters[0],
      cluster_id: `cl-rare-${i}`, evidence_level: i === 100 ? "L2" : "L0",
    }));
    render(page({ ...fixture, clusters }));
    const family = screen.getByTestId("thesis-family-collection:liquid-democracy");
    const stages = within(family).getByRole("img", { name: /^Recorded stages for all 101 records:/ });
    expect(stages).toHaveAccessibleName(/L0 100 of 101; L1 0 of 101; L2 1 of 101/);
    expect(within(stages).getByText("L2 1")).toBeVisible();
    const rare = stages.querySelector<HTMLElement>('[data-classification="L2"]');
    expect(rare).not.toBeNull();
    expect(Number.parseFloat(rare!.style.width)).toBeCloseTo(100 / 101);
    expect(rare!.style.minWidth).toBe("");
  });

  it("retains a killed record's recorded L4 stage on a separate axis with a singular denominator", () => {
    render(page({ ...fixture, clusters: [{ ...fixture.clusters[0], status: "killed", evidence_level: "L4" }] }));
    fireEvent.change(screen.getByLabelText("Record status"), { target: { value: "all" } });
    const family = screen.getByTestId("thesis-family-collection:liquid-democracy");
    expect(within(family).getByText("All 1 record")).toBeVisible();
    expect(within(family).getByRole("img", { name: /^Recorded stages for all 1 record:/ })).toHaveAccessibleName(/L4 1 of 1/);
    expect(within(family).getByRole("img", { name: /^Recorded statuses for all 1 record:/ })).toHaveAccessibleName(/killed 1 of 1/);
  });

  it("keeps exact-topic headings once while preserving expansion and distinct claims", () => {
    const sameTopicRows = rows.map((row) => ({ ...row, seed: { topic: "One exact topic" } }));
    render(page(fixture, sameTopicRows));
    const control = screen.getByRole("button", { name: "Expand exact topic collection: One exact topic" });
    fireEvent.click(control);
    expect(screen.getAllByText("One exact topic")).toHaveLength(1);
    for (const row of rows) expect(screen.getByText(row.hypothesis.text)).toBeVisible();
    expect(control).toHaveAttribute("aria-expanded", "true");
  });
});

describe("Ladder topic collections", () => {
  it("starts with one labeled collection, two recorded topics and three distinct L1 records", () => {
    render(page());
    const expand = screen.getByRole("button", { name: "Expand curated association: Liquid democracy" });
    fireEvent.click(expand);
    const family = screen.getByTestId("thesis-family-collection:liquid-democracy");
    expect(within(family).getByText(/association only/i)).toBeVisible();
    for (const topic of topics) expect(within(family).getByText(topic)).toBeVisible();
    for (const row of rows) {
      expect(within(family).getByText(row.hypothesis.text)).toBeVisible();
      expect(within(family).getByRole("link", { name: `Open evidence for ${row.iteration_id}` }))
        .toHaveAttribute("href", `/dossier/${row.iteration_id}`);
    }
    expect(within(family).getAllByTestId(/^thesis-record-/)).toHaveLength(3);
  });

  it("searches member hypotheses while retaining the collection and matching denominator", () => {
    render(page());
    fireEvent.change(screen.getByRole("searchbox", { name: /search topics, claims or record ids/i }), { target: { value: "clustering question" } });
    fireEvent.click(screen.getByRole("button", { name: "Expand curated association: Liquid democracy" }));
    const family = screen.getByTestId("thesis-family-collection:liquid-democracy");
    expect(within(family).getByText(/1 of 3 records/i)).toBeVisible();
    expect(within(family).getByText(rows[1].hypothesis.text)).toBeVisible();
    expect(within(family).queryByText(rows[0].hypothesis.text)).not.toBeInTheDocument();
  });

  it("retains expanded identity after a reordered source refresh", () => {
    const { rerender } = render(page());
    fireEvent.click(screen.getByRole("button", { name: "Expand curated association: Liquid democracy" }));
    rerender(page({ ...fixture, clusters: [...fixture.clusters].reverse() }, [...rows].reverse()));
    expect(screen.getByRole("button", { name: "Collapse curated association: Liquid democracy" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(rows[2].hypothesis.text)).toBeVisible();
  });

  it("preserves a killed record and its own stage without assigning a family maximum", () => {
    const data = structuredClone(fixture);
    data.clusters[2].status = "killed";
    data.clusters[2].evidence_level = "L2";
    data.clusters[2].kill_reason = { code: "redteam_fatal_flaw", detail: "Original negative evidence" };
    data.counts = { open: 2, surfaced: 0, killed: 1 };
    data.histogram.L1 = 2;
    render(page(data));
    fireEvent.change(screen.getByLabelText("Record status"), { target: { value: "all" } });
    fireEvent.click(screen.getByRole("button", { name: "Expand curated association: Liquid democracy" }));
    const killed = screen.getByTestId(`thesis-record-cl-${rows[2].iteration_id}`);
    expect(within(killed).getByText("L2")).toBeVisible();
    expect(within(killed).getByText(/killed/i)).toBeVisible();
    expect(within(killed).getByText("Original negative evidence")).toBeVisible();
    expect(within(screen.getByTestId(`thesis-record-cl-${rows[0].iteration_id}`)).getByText("L1")).toBeVisible();
  });

  it("keeps records inspectable when topic provenance is unavailable", () => {
    render(<StrictMode>{page(fixture, [])}</StrictMode>);
    expect(screen.queryByRole("button", { name: "Expand curated association: Liquid democracy" })).not.toBeInTheDocument();
    expect(screen.getAllByTestId(/^thesis-family-/)).toHaveLength(3);
    expect(screen.getByText(/source relationships are not verified/i)).toBeVisible();
  });
});


describe("Ladder collection flow and source lifecycle", () => {
  it("keeps expansion and filters while inspecting the board, then shows the current picked record", () => {
    const { rerender } = render(page());
    fireEvent.click(screen.getByRole("button", { name: "Expand curated association: Liquid democracy" }));
    fireEvent.change(screen.getByLabelText("Recorded stage"), { target: { value: "L1" } });
    fireEvent.click(screen.getByTestId("ladder-view-board"));
    expect(screen.getByTestId("ladder-board")).toBeVisible();
    fireEvent.click(screen.getByTestId("ladder-view-collections"));
    expect(screen.getByRole("button", { name: "Collapse curated association: Liquid democracy" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByLabelText("Recorded stage")).toHaveValue("L1");
    const record = screen.getByTestId(`thesis-record-cl-${rows[0].iteration_id}`);
    fireEvent.click(within(record).getByRole("button"));
    expect(screen.getByTestId("ladder-peek-body")).toHaveTextContent(rows[0].hypothesis.text);
    const updated = structuredClone(fixture);
    updated.clusters[0].status = "killed";
    updated.clusters[0].kill_reason = { code: "new_negative", detail: "A newer recorded negative" };
    rerender(page(updated));
    expect(screen.getByTestId("ladder-peek-body")).toHaveTextContent("A newer recorded negative");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByTestId("ladder-peek-body")).not.toBeInTheDocument();
  });

  it("connects a focusable native disclosure to its content and does not lose duplicate membership records", () => {
    const duplicate = structuredClone(fixture.clusters[0]);
    duplicate.cluster_id = "cl-distinct-negative-copy";
    duplicate.status = "killed";
    duplicate.kill_reason = { code: "duplicate_of_existing", detail: `Recorded duplicate of ${fixture.clusters[0].cluster_id}` };
    render(page({ ...fixture, clusters: [...fixture.clusters, duplicate] }));
    fireEvent.change(screen.getByLabelText("Record status"), { target: { value: "all" } });
    const button = screen.getByRole("button", { name: "Expand curated association: Liquid democracy" });
    button.focus();
    expect(button).toHaveFocus();
    expect(button.tagName).toBe("BUTTON");
    const controls = button.getAttribute("aria-controls");
    expect(controls).toBeTruthy();
    fireEvent.click(button);
    expect(document.getElementById(controls!)).toBeVisible();
    expect(screen.getAllByTestId(/^thesis-record-/)).toHaveLength(4);
    expect(screen.getAllByRole("link", { name: `Open evidence for ${rows[0].iteration_id}` })).toHaveLength(2);
    // Keyboard activation is also checked in the real browser; jsdom does
    // not emulate the browser's native Enter-to-click default behavior.
  });

  it("deduplicates actual StrictMode source subscriptions and manual refresh, retaining stale data on failure", async () => {
    vi.mocked(getLadder).mockResolvedValue(fixture);
    vi.mocked(getIterations).mockResolvedValue({ iterations: rows.map((row) => ({ ...row, started_at: "2026-01-01T00:00:00Z", ended_at: "2026-01-01T00:01:00Z", journal_entry_path: "" })) });
    const { unmount } = render(<StrictMode><MemoryRouter><Ladder /></MemoryRouter></StrictMode>);
    const expand = await screen.findByRole("button", { name: "Expand curated association: Liquid democracy" });
    expect(getLadder).toHaveBeenCalledTimes(1);
    expect(getIterations).toHaveBeenCalledTimes(1);
    expect(getIterations).toHaveBeenCalledWith({ fields: TOPIC_FIELDS });
    fireEvent.click(expand);
    let rejectTopics: (reason: Error) => void = () => {};
    vi.mocked(getIterations).mockImplementationOnce(() => new Promise((_, reject) => { rejectTopics = reject; }));
    vi.mocked(getLadder).mockRejectedValueOnce(new Error("offline records"));
    fireEvent.click(screen.getByRole("button", { name: "Refresh sources" }));
    expect(await screen.findByRole("button", { name: "Refreshing sources…" })).toBeDisabled();
    await act(async () => { rejectTopics(new Error("offline topics")); });
    expect(await screen.findByText(/Topic refresh failed: Error: offline topics/)).toBeVisible();
    expect(screen.getByTestId("ladder-error")).toHaveTextContent("Showing last received records");
    expect(screen.getByText(rows[0].hypothesis.text)).toBeVisible();
    expect(screen.getByRole("button", { name: "Collapse curated association: Liquid democracy" })).toBeVisible();
    expect(screen.getByTestId("ladder-source-times")).toHaveTextContent("2026-01-03T00:00:00Z");
    expect(screen.getByTestId("ladder-source-times")).not.toHaveTextContent("not fetched in this view");
    expect(getLadder).toHaveBeenCalledTimes(2);
    expect(getIterations).toHaveBeenCalledTimes(2);
    unmount();
    await act(async () => {});
    expect(getLadder).toHaveBeenCalledTimes(2);
    expect(getIterations).toHaveBeenCalledTimes(2);
  });

  it("does not turn a malformed topic response into verified collection membership", async () => {
    vi.mocked(getLadder).mockResolvedValue(fixture);
    vi.mocked(getIterations).mockResolvedValue({ iterations: null } as never);
    render(<MemoryRouter><Ladder /></MemoryRouter>);
    await waitFor(() => expect(screen.getAllByTestId(/^thesis-family-/)).toHaveLength(3));
    expect(await screen.findByText(/Topic refresh failed: Error: Iteration topic source is missing or malformed/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Expand curated association: Liquid democracy" })).not.toBeInTheDocument();
    expect(screen.getByText(/source relationships are not verified/i)).toBeVisible();
  });
});


describe("review counterexamples", () => {
  it("does not leak a killed duplicate ID into the open filter or select another row's details", () => {
    const open = { ...fixture.clusters[0], cluster_id: "cl-duplicate", stem: "Open snapshot" };
    const killed = { ...fixture.clusters[1], cluster_id: "cl-duplicate", stem: "Killed snapshot", status: "killed", kill_reason: { code: "recorded_negative", detail: "This negative belongs only to killed snapshot" } };
    render(page({ ...fixture, clusters: [open, killed] }));
    for (const button of screen.getAllByRole("button", { name: /^Expand / })) fireEvent.click(button);
    expect(screen.getAllByTestId(/^thesis-record-/)).toHaveLength(1);
    expect(screen.queryByText("This negative belongs only to killed snapshot")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Record status"), { target: { value: "all" } });
    for (const button of screen.queryAllByRole("button", { name: /^Expand / })) fireEvent.click(button);
    expect(screen.getAllByTestId(/^thesis-record-/)).toHaveLength(2);
    for (const card of screen.getAllByTestId(/^thesis-record-/)) {
      const isKilled = within(card).queryByText("This negative belongs only to killed snapshot") !== null;
      fireEvent.click(within(card).getByRole("button"));
      const peek = screen.getByTestId("ladder-peek-body");
      if (isKilled) expect(peek).toHaveTextContent("This negative belongs only to killed snapshot");
      else expect(peek).not.toHaveTextContent("This negative belongs only to killed snapshot");
      fireEvent.keyDown(document, { key: "Escape" });
    }
  });

  it("keeps raw member chronology when source findings sit between old and new iterations", () => {
    const members = [rows[0].iteration_id, `sf-${rows[0].iteration_id}`, rows[1].iteration_id];
    render(page({ ...fixture, clusters: [{ ...fixture.clusters[0], members }] }));
    fireEvent.click(screen.getByRole("button", { name: /^Expand / }));
    const card = screen.getByTestId(`thesis-record-cl-${rows[0].iteration_id}`);
    expect(within(card).getAllByRole("link").map((link) => link.textContent)).toEqual(members);
  });
});

// The source ID scopes agenda, while an internal key scopes a rendered snapshot.
// Faulty source IDs must not be certified by a readable topic or a click.
describe("whole-route ambiguous snapshot boundaries", () => {
  it("withholds duplicate-ID agenda attribution and distinguishes Inspect names", () => {
    const clusters = fixture.clusters.slice(0, 2).map((c, i) => ({ ...c, cluster_id: "cl-shared", stem: `Snapshot ${i}` }));
    render(page({ ...fixture, clusters, agenda: [{ cluster_id: "cl-shared", topic: "Ambiguous next-work marker", source: "human" }] }));
    for (const button of screen.getAllByRole("button", { name: /^Expand / })) fireEvent.click(button);
    const cards = screen.getAllByTestId(/^thesis-record-/);
    const names = cards.map((card) => within(card).getByRole("button").getAttribute("aria-label"));
    expect(new Set(names).size).toBe(2);
    for (const card of cards) {
      expect(card).toHaveTextContent("cl-shared");
      fireEvent.click(within(card).getByRole("button"));
      const peek = screen.getByTestId("ladder-peek-body");
      expect(peek).not.toHaveTextContent("Ambiguous next-work marker");
      expect(peek).toHaveTextContent(/agenda attribution withheld/i);
      expect(peek).not.toHaveTextContent("no open agenda items");
      fireEvent.keyDown(document, { key: "Escape" });
    }
  });

  it("preserves unique-ID agenda even if the topic source is unsupported", () => {
    const cluster = { ...fixture.clusters[0], members: ["paper-unresolved"] };
    render(page({ ...fixture, clusters: [cluster], agenda: [{ cluster_id: cluster.cluster_id, topic: "Unique source agenda", source: "human" }] }));
    fireEvent.click(screen.getByRole("button", { name: /^Expand / }));
    fireEvent.click(within(screen.getByTestId(/^thesis-record-/)).getByRole("button"));
    expect(screen.getByTestId("ladder-peek-agenda")).toHaveTextContent("Unique source agenda");
  });

  for (const view of ["board", "table"]) for (const identity of ["duplicate", "missing"]) {
    it(`preserves ${identity} snapshot DOM and focus when ${view} rows reorder`, () => {
      const errors = vi.spyOn(console, "error").mockImplementation(() => {});
      const clusters = fixture.clusters.slice(0, 2).map((c, i) => ({ ...c,
        cluster_id: identity === "duplicate" ? "cl-shared" : undefined, stem: `Snapshot ${i}`,
      })) as LadderCluster[];
      const { rerender } = render(page({ ...fixture, clusters }));
      fireEvent.click(screen.getByTestId(`ladder-view-${view}`));
      const prefix = view === "board" ? "ladder-card-" : "ladder-row-";
      const rowFor = (stem: string) => screen.getAllByTestId(new RegExp(`^${prefix}`)).find((row) => row.textContent?.includes(stem))!;
      const first = rowFor("Snapshot 0");
      first.focus();
      expect(first).toHaveFocus();
      rerender(page({ ...fixture, clusters: structuredClone([...clusters].reverse()) }));
      expect(rowFor("Snapshot 0")).toBe(first);
      expect(first).toHaveFocus();
      fireEvent.click(first);
      expect(screen.getByTestId("ladder-peek-body")).toHaveTextContent(rows[0].hypothesis.text);
      expect(errors.mock.calls.filter((args) => args.some((value) => String(value).includes("same key")))).toEqual([]);
      errors.mockRestore();
    });
  }
});

describe("final review disclosure and last-good empty boundaries", () => {
  for (const identity of ["duplicate", "missing"]) {
    it(`distinguishes collapsed ${identity}-ID snapshots with the same title`, () => {
      const clusters = fixture.clusters.slice(0, 2).map((c) => ({ ...c,
        cluster_id: identity === "duplicate" ? "cl-shared" : undefined, stem: "Same displayed title",
      })) as LadderCluster[];
      render(page({ ...fixture, clusters }));
      const controls = screen.getAllByRole("button", { name: /^Expand record: Same displayed title/ });
      expect(controls).toHaveLength(2);
      expect(new Set(controls.map((control) => control.getAttribute("aria-label"))).size).toBe(2);
      for (const control of controls) {
        expect(control).toHaveAccessibleName(/unverified snapshot \d+/);
        fireEvent.click(control);
      }
      expect(screen.getAllByTestId(/^thesis-record-/)).toHaveLength(2);
    });
  }
  for (const status of [500, 404]) {
    it(`retains a confirmed 204 empty source and fallback after a later ${status}`, async () => {
      vi.mocked(getLadder).mockResolvedValueOnce(null);
      vi.mocked(getIterations).mockResolvedValue({ iterations: [] });
      render(<MemoryRouter><Ladder initialIdeas="# Last received ideas" /></MemoryRouter>);
      expect(await screen.findByTestId("ladder-empty")).toBeVisible();
      vi.mocked(getLadder).mockRejectedValueOnce(Object.assign(new Error(`${status} refresh failed`), { status }));
      await act(async () => { refreshPoll("ladder:records"); });
      expect(await screen.findByTestId("ladder-error")).toHaveTextContent(`${status} refresh failed`);
      expect(screen.getByTestId("ladder-empty")).toBeVisible();
      expect(screen.getAllByTestId("ladder-ideas-fallback")).toHaveLength(1);
      expect(screen.getByTestId("ladder-ideas-fallback")).toHaveTextContent("Last received ideas");
    });
  }
  it("does not hide a later 404 behind a last-good populated source", async () => {
    vi.mocked(getLadder).mockResolvedValueOnce(fixture);
    vi.mocked(getIterations).mockResolvedValue({ iterations: [] });
    render(<MemoryRouter><Ladder /></MemoryRouter>);
    expect(await screen.findByTestId("ladder-counts-header")).toHaveTextContent("3 recorded clusters");
    vi.mocked(getLadder).mockRejectedValueOnce(Object.assign(new Error("404 refresh failed"), { status: 404 }));
    await act(async () => { refreshPoll("ladder:records"); });
    expect(await screen.findByTestId("ladder-error")).toHaveTextContent("Showing last received records");
    expect(screen.getByTestId("ladder-counts-header")).toHaveTextContent("3 recorded clusters");
    expect(screen.queryByTestId("ladder-empty")).not.toBeInTheDocument();
  });
});

describe("explicit disclosure presentation kind", () => {
  it("distinguishes the original same-title record and exact collection, plus curated association", () => {
    const data = { ...fixture, clusters: [
      { ...fixture.clusters[0], cluster_id: "Shared title", stem: "Shared title", members: ["paper-unsupported"] },
      { ...fixture.clusters[1], cluster_id: "cl-grouped", stem: "Grouped record", members: ["iter-grouped"] },
      fixture.clusters[2],
    ] };
    const before = JSON.stringify(data);
    render(page(data, [...rows, {
      iteration_id: "iter-grouped", seed: { topic: "Shared title" },
      hypothesis: { text: "A separate grouped claim" },
    }]));
    const record = screen.getByRole("button", { name: "Expand record: Shared title — source ID Shared title" });
    const exact = screen.getByRole("button", { name: "Expand exact topic collection: Shared title" });
    const curated = screen.getByRole("button", { name: "Expand curated association: Liquid democracy" });
    expect(new Set([record, exact, curated].map((control) => control.getAttribute("aria-label"))).size).toBe(3);
    expect(new Set([record, exact, curated].map((control) => control.getAttribute("aria-controls"))).size).toBe(3);
    record.focus(); expect(record).toHaveFocus();
    fireEvent.click(record);
    expect(record).toHaveAccessibleName("Collapse record: Shared title — source ID Shared title");
    expect(exact).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByTestId("thesis-record-Shared title")).toHaveTextContent("Shared title");
    fireEvent.click(exact);
    expect(exact).toHaveAccessibleName("Collapse exact topic collection: Shared title");
    expect(screen.getByTestId("thesis-record-cl-grouped")).toHaveTextContent("A separate grouped claim");
    fireEvent.click(curated);
    expect(curated).toHaveAccessibleName("Collapse curated association: Liquid democracy");
    expect(screen.getAllByTestId(/^thesis-record-/)).toHaveLength(3);
    expect(JSON.stringify(data)).toBe(before);
  });

  it("retains source-ID context for same-title unique sibling records", () => {
    const clusters = fixture.clusters.slice(0, 2).map((c, i) => ({ ...c,
      cluster_id: `cl-unique-${i}`, stem: "Shared title", members: ["paper-unsupported"],
    }));
    render(page({ ...fixture, clusters }));
    for (const [i, cluster] of clusters.entries()) {
      const button = screen.getByRole("button", { name: `Expand record: Shared title — source ID cl-unique-${i}` });
      fireEvent.click(button);
      expect(screen.getByTestId(`thesis-record-${cluster.cluster_id}`)).toHaveTextContent(cluster.cluster_id);
    }
    expect(screen.getAllByTestId(/^thesis-record-/)).toHaveLength(2);
  });
});
