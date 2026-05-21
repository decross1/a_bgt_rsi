// EventsViewer renders each known event type with a per-type renderer
// driven by schema/events.jsonl.schema.json, flags incomplete records, and
// filters by type.
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

const HUMAN_INTERVENTION = {
  event_type: "human_intervention",
  timestamp: "2026-05-19T11:15:42Z",
  task_id: "day3_5_block2_schema_amend",
  subtype: "manual_decision",
  reason: "approved the retrieval_context schema addition",
  context_hash: "sha256:9f2c1a7d",
};

const CALIBRATION_ENTRY = {
  event_type: "calibration_entry",
  timestamp: "2026-05-19T11:32:08Z",
  experiment_id: "exp001_repeated_pd",
  metric_name: "decode_tok_per_s",
  pre_experiment_expected_range: [80, 130],
  post_experiment_observed: 69.4,
  within_range: false,
  human_attestation: "range set before MTP tuning landed",
};

describe("EventsViewer", () => {
  it("renders a human_intervention event from its per-type fields", async () => {
    responses["/api/events?limit=200"] = {
      available: true,
      events: [HUMAN_INTERVENTION],
    };
    render(<EventsViewer />);
    await waitFor(() =>
      expect(screen.getByText("human_intervention")).toBeInTheDocument(),
    );
    expect(screen.getByText("manual_decision")).toBeInTheDocument();
    expect(
      screen.getByText("day3_5_block2_schema_amend"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/approved the retrieval_context schema addition/),
    ).toBeInTheDocument();
    expect(screen.getByText(/context_hash:/)).toBeInTheDocument();
  });

  it("renders a calibration_entry with observed vs expected range", async () => {
    responses["/api/events?limit=200"] = {
      available: true,
      events: [CALIBRATION_ENTRY],
    };
    render(<EventsViewer />);
    await waitFor(() =>
      expect(screen.getByText("calibration_entry")).toBeInTheDocument(),
    );
    expect(screen.getByText("exp001_repeated_pd")).toBeInTheDocument();
    expect(screen.getByText("69.4")).toBeInTheDocument();
    expect(screen.getByText("[80, 130]")).toBeInTheDocument();
    // within_range: false → an explicit "out of range" badge, not silent.
    expect(screen.getByText("out of range")).toBeInTheDocument();
  });

  it("flags an incomplete record missing a schema-required field", async () => {
    const { reason, ...withoutReason } = HUMAN_INTERVENTION;
    void reason;
    responses["/api/events?limit=200"] = {
      available: true,
      events: [withoutReason],
    };
    render(<EventsViewer />);
    await waitFor(() =>
      expect(screen.getByText(/incomplete record/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/missing reason/)).toBeInTheDocument();
  });

  it("falls back to a generic dump for an unknown event_type", async () => {
    responses["/api/events?limit=200"] = {
      available: true,
      events: [{ event_type: "future_event", note: "schema not seen yet" }],
    };
    render(<EventsViewer />);
    await waitFor(() =>
      expect(screen.getByText("future_event")).toBeInTheDocument(),
    );
    expect(screen.getByText("schema not seen yet")).toBeInTheDocument();
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
      events: [HUMAN_INTERVENTION, CALIBRATION_ENTRY],
    };
    render(<EventsViewer />);
    await waitFor(() =>
      expect(screen.getByText("calibration_entry")).toBeInTheDocument(),
    );
    expect(screen.getByText("human_intervention")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: /^calibration_entry/ }),
    );
    expect(screen.queryByText("human_intervention")).toBeNull();
    expect(screen.getByText("calibration_entry")).toBeInTheDocument();
  });
});
