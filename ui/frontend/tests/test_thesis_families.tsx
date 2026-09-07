import { StrictMode } from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import Ladder from "../src/routes/Ladder";
import { getIterations, getLadder } from "../src/api/http";
import { TOPIC_FIELDS } from "../src/api/ladder";
import type { LadderCluster, LadderResponse } from "../src/types/schemas";

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

describe("Ladder topic collections", () => {
  it("starts with one labeled collection, two recorded topics and three distinct L1 records", () => {
    render(page());
    const expand = screen.getByRole("button", { name: "Expand Liquid democracy" });
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
    fireEvent.click(screen.getByRole("button", { name: "Expand Liquid democracy" }));
    const family = screen.getByTestId("thesis-family-collection:liquid-democracy");
    expect(within(family).getByText(/1 of 3 records/i)).toBeVisible();
    expect(within(family).getByText(rows[1].hypothesis.text)).toBeVisible();
    expect(within(family).queryByText(rows[0].hypothesis.text)).not.toBeInTheDocument();
  });

  it("retains expanded identity after a reordered source refresh", () => {
    const { rerender } = render(page());
    fireEvent.click(screen.getByRole("button", { name: "Expand Liquid democracy" }));
    rerender(page({ ...fixture, clusters: [...fixture.clusters].reverse() }, [...rows].reverse()));
    expect(screen.getByRole("button", { name: "Collapse Liquid democracy" })).toHaveAttribute("aria-expanded", "true");
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
    fireEvent.click(screen.getByRole("button", { name: "Expand Liquid democracy" }));
    const killed = screen.getByTestId(`thesis-record-cl-${rows[2].iteration_id}`);
    expect(within(killed).getByText("L2")).toBeVisible();
    expect(within(killed).getByText(/killed/i)).toBeVisible();
    expect(within(killed).getByText("Original negative evidence")).toBeVisible();
    expect(within(screen.getByTestId(`thesis-record-cl-${rows[0].iteration_id}`)).getByText("L1")).toBeVisible();
  });

  it("keeps records inspectable when topic provenance is unavailable", () => {
    render(<StrictMode>{page(fixture, [])}</StrictMode>);
    expect(screen.queryByRole("button", { name: "Expand Liquid democracy" })).not.toBeInTheDocument();
    expect(screen.getAllByTestId(/^thesis-family-/)).toHaveLength(3);
    expect(screen.getByText(/source relationships are not verified/i)).toBeVisible();
  });
});


describe("Ladder collection flow and source lifecycle", () => {
  it("keeps expansion and filters while inspecting the board, then shows the current picked record", () => {
    const { rerender } = render(page());
    fireEvent.click(screen.getByRole("button", { name: "Expand Liquid democracy" }));
    fireEvent.change(screen.getByLabelText("Recorded stage"), { target: { value: "L1" } });
    fireEvent.click(screen.getByTestId("ladder-view-board"));
    expect(screen.getByTestId("ladder-board")).toBeVisible();
    fireEvent.click(screen.getByTestId("ladder-view-collections"));
    expect(screen.getByRole("button", { name: "Collapse Liquid democracy" })).toHaveAttribute("aria-expanded", "true");
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
    const button = screen.getByRole("button", { name: "Expand Liquid democracy" });
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
    const expand = await screen.findByRole("button", { name: "Expand Liquid democracy" });
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
    expect(screen.getByRole("button", { name: "Collapse Liquid democracy" })).toBeVisible();
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
    expect(screen.queryByRole("button", { name: "Expand Liquid democracy" })).not.toBeInTheDocument();
    expect(screen.getByText(/source relationships are not verified/i)).toBeVisible();
  });
});
