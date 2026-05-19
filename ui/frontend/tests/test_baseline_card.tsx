// BaselineCard is data-driven: measured rows from /api/baseline show a
// measured badge; an unreachable backend falls back to documented constants.
// ui_plan.md sections 5.3, 9.
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import BaselineCard from "../src/components/BaselineCard";

describe("BaselineCard", () => {
  afterEach(() => vi.restoreAllMocks());

  it("renders a measured row with a measured badge and the expected figure", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        rows: [
          {
            key: "decode_tok_per_s",
            label: "Decode tok/s",
            value: "day-1 bench median 32.0 tok/s",
            source: "measured",
            documented: "NVFP4 baseline ~52",
          },
        ],
      }),
    } as Response);

    render(<BaselineCard />);
    await waitFor(() =>
      expect(screen.getByText("day-1 bench median 32.0 tok/s")).toBeInTheDocument(),
    );
    expect(screen.getByText("measured")).toBeInTheDocument();
    expect(screen.getByText(/expected: NVFP4 baseline/)).toBeInTheDocument();
  });

  it("falls back to documented constants when the backend is unreachable", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("network down"));
    render(<BaselineCard />);
    // The card seeds with documented fallback rows and keeps them on failure.
    await waitFor(() =>
      expect(screen.getByText("GPU idle power:")).toBeInTheDocument(),
    );
    expect(screen.getAllByText("documented").length).toBeGreaterThan(0);
  });
});
