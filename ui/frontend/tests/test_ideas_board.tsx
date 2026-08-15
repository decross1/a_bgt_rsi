// Ideas board (2026-08-14 work order C): /ideas renders memory/ideas.md —
// the deterministic idea-ledger projection — as plain markdown, read-only.
// Absent file (204 -> null) gets the honest "no ideas board yet" state, not
// a blank page. Fixture renders via `initial` (no fetch).
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Ideas from "../src/routes/Ideas";

const IDEAS_MD = `# Ideas

## Live work

- cl-iter-2026-07-13-001 · L1 · next: synthetic experiment

## Graveyard

- cl-iter-2026-05-27-003 · killed: paper_prior_exists
`;

describe("Ideas board (/ideas)", () => {
  it("renders the projection's sections as markdown", () => {
    render(<Ideas initial={IDEAS_MD} />);
    expect(screen.getByTestId("ideas-board")).toBeInTheDocument();
    expect(screen.getByTestId("mini-markdown")).toBeInTheDocument();
    expect(screen.getByText("Live work")).toBeInTheDocument();
    expect(screen.getByText("Graveyard")).toBeInTheDocument();
    expect(
      screen.getByText(/cl-iter-2026-07-13-001 · L1 · next: synthetic experiment/),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("ideas-empty")).toBeNull();
    expect(screen.queryByTestId("ideas-error")).toBeNull();
  });

  it("absent file (204 -> null) renders the honest empty state", () => {
    render(<Ideas initial={null} />);
    expect(screen.getByTestId("ideas-empty").textContent).toContain(
      "no ideas board yet",
    );
    expect(screen.queryByTestId("mini-markdown")).toBeNull();
  });

  it("is read-only — no editing affordance is rendered", () => {
    render(<Ideas initial={IDEAS_MD} />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
  });
});
