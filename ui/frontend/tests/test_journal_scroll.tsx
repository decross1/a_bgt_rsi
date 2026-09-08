// JournalScroll renders a journal markdown response. Verifies the
// no-selection prompt, the markdown rendering for headings/lists/bold/code,
// and the error path.
import { render, screen, waitFor } from "@testing-library/react";
import JournalScroll from "../src/components/JournalScroll";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const SAMPLE_MD = `# Iteration iter-2026-05-26-001

- **Topic**: Tit-for-Tat dominance
- **Novelty**: rediscovery

## Hypothesis

TfT remains the most robust strategy in noisy repeated PD.

\`\`\`
summarize_paper(arxiv_id="2025.foo")
\`\`\`
`;

beforeEach(() => {
  vi.stubGlobal("fetch", (url: string) => {
    if (url.includes("/api/loop_v0/journal/iter-known")) {
      return Promise.resolve({
        ok: true,
        status: 200,
        statusText: "OK",
        json: () =>
          Promise.resolve({
            iteration_id: "iter-known",
            path: "journal/iterations/001.md",
            content: SAMPLE_MD,
          }),
      } as Response);
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
});

describe("JournalScroll", () => {
  it("shows a no-selection prompt when no iteration id is provided", () => {
    render(<JournalScroll iterationId={null} />);
    expect(
      screen.getByText(/Select an iteration from the list/),
    ).toBeInTheDocument();
  });

  it("renders the markdown returned from the backend", async () => {
    render(<JournalScroll iterationId="iter-known" />);
    await waitFor(() =>
      expect(
        screen.getByText(/Iteration iter-2026-05-26-001/),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText("Topic")).toBeInTheDocument(); // bold
    expect(screen.getByText("Hypothesis")).toBeInTheDocument(); // ## heading
    expect(
      screen.getByText(/summarize_paper\(arxiv_id="2025.foo"\)/),
    ).toBeInTheDocument();
    expect(screen.getByText("journal/iterations/001.md")).toBeInTheDocument();
  });

  it("surfaces a backend 404 inline rather than rendering empty", async () => {
    render(<JournalScroll iterationId="iter-missing" />);
    await waitFor(() =>
      expect(screen.getByText(/404/)).toBeInTheDocument(),
    );
  });
});
