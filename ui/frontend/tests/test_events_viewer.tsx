// EventsViewer renders the two known event types and filters by type.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import EventsViewer from "../src/routes/EventsViewer";

const responses: Record<string, unknown> = {};

beforeEach(() => {
  vi.stubGlobal("fetch", (url: string) => {
    for (const [key, value] of Object.entries(responses)) {
      if (url.endsWith(key)) {
        return Promise.resolve({
          ok: true,
          status: 200,
          statusText: "OK",
          json: () => Promise.resolve(value),
        } as Response);
      }
    }
    return Promise.resolve({
      ok: false,
      status: 404,
      statusText: "not found",
      json: () => Promise.resolve({ detail: "missing" }),
    } as Response);
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  for (const key of Object.keys(responses)) delete responses[key];
});

describe("EventsViewer", () => {
  it("renders human_intervention and calibration_entry events", async () => {
    responses["/api/events?limit=200"] = {
      available: true,
      events: [
        {
          event_type: "human_intervention",
          timestamp: "2026-05-19T11:15:42Z",
          actor: "operator",
          note: "approved",
        },
        {
          event_type: "calibration_entry",
          timestamp: "2026-05-19T11:32:08Z",
          metric: "decode_tok_per_s",
          observed: 69.4,
        },
      ],
    };
    render(<EventsViewer />);
    await waitFor(() =>
      expect(screen.getByText("human_intervention")).toBeInTheDocument(),
    );
    expect(screen.getByText("calibration_entry")).toBeInTheDocument();
    expect(screen.getByText("approved")).toBeInTheDocument();
  });

  it("shows the not-yet-available notice when events.jsonl is absent", async () => {
    responses["/api/events?limit=200"] = { available: false, events: [] };
    render(<EventsViewer />);
    await waitFor(() =>
      expect(
        screen.getByText(/logs\/events.jsonl is not present yet/),
      ).toBeInTheDocument(),
    );
  });

  it("filters events by event_type", async () => {
    responses["/api/events?limit=200"] = {
      available: true,
      events: [
        { event_type: "human_intervention", note: "A" },
        { event_type: "calibration_entry", metric: "x" },
        { event_type: "human_intervention", note: "B" },
      ],
    };
    render(<EventsViewer />);
    // Two event rows of type human_intervention render the bare label "human_intervention";
    // the filter button reads "human_intervention (2)" so it does not match exactly.
    await waitFor(() => expect(screen.getAllByText("human_intervention")).toHaveLength(2));
    expect(screen.getByText("A")).toBeInTheDocument();
    expect(screen.getByText("B")).toBeInTheDocument();
    expect(screen.getByText("x")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^calibration_entry/ }));
    expect(screen.queryByText("A")).toBeNull();
    expect(screen.queryByText("B")).toBeNull();
    expect(screen.getByText("x")).toBeInTheDocument();
  });
});
