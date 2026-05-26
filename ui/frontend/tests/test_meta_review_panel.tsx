// MetaReviewPanel — Day-9 empty-state stub for Day-40 W2-02
// meta-review surface. Renders "awaiting day-40" when the backend
// reports the log absent; renders the row count when it lands.
import { render, screen, waitFor } from "@testing-library/react";
import MetaReviewPanel from "../src/components/MetaReviewPanel";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MetaReviewSummary } from "../src/types/schemas";

const responses: Record<string, unknown> = {};

beforeEach(() => {
  vi.stubGlobal("fetch", (url: string) => {
    for (const [key, value] of Object.entries(responses)) {
      if (url.endsWith(key) || url.includes(key)) {
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

function payload(overrides: Partial<MetaReviewSummary> = {}): MetaReviewSummary {
  return {
    available: false,
    total_runs: 0,
    note: "logs/meta_review.jsonl not present yet — awaiting Day-40 W2-02 meta-review outputs.",
    ...overrides,
  };
}

describe("MetaReviewPanel", () => {
  it("renders the awaiting-day-40 stub when the log is absent", async () => {
    responses["/api/meta_review_summary"] = payload();
    render(<MetaReviewPanel />);
    await waitFor(() =>
      expect(screen.getByText(/awaiting day-40/i)).toBeInTheDocument(),
    );
    expect(
      screen.getByText(/awaiting Day-40 W2-02 meta-review outputs/),
    ).toBeInTheDocument();
    // Read-only: no buttons.
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("renders the row count once logs/meta_review.jsonl exists", async () => {
    responses["/api/meta_review_summary"] = payload({
      available: true,
      total_runs: 7,
      note: "7 meta-review row(s) present — per-row render lands when Track A finalizes the record shape (Day 40).",
    });
    render(<MetaReviewPanel />);
    await waitFor(() =>
      expect(screen.getByText("7 runs")).toBeInTheDocument(),
    );
    expect(screen.getByText(/7 meta-review row\(s\) present/)).toBeInTheDocument();
  });
});
