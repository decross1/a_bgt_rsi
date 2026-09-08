import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import NowBoard from "../src/components/NowBoard";
import OweCard from "../src/components/OweCard";
import type { ActiveRun } from "../src/types/activity";
import type { HumanTodoItem } from "../src/types/schemas";

const NOW = Date.parse("2026-09-08T04:00:00.000Z");

function Workflow({
  items,
  runs,
}: {
  items: HumanTodoItem[];
  runs: ActiveRun[];
}) {
  return (
    <MemoryRouter>
      <main>
        <OweCard initial={items} nowMs={NOW} expanded={false} />
        <NowBoard
          initial={{ runs, skipped: 0 }}
          nowMs={NOW}
          orientation
        />
      </main>
    </MemoryRouter>
  );
}

describe("Now attention and source workflow", () => {
  it("keeps recorded requests source-qualified and behind an explicit review control", () => {
    render(
      <Workflow
        items={[
          {
            kind: "gate_verdict",
            id: "iter-recorded-001",
            title: "Recorded verdict request",
            since: "2026-06-01T00:00:00Z",
            resolve_command: "gate_cli --iteration-id iter-recorded-001",
          },
        ]}
        runs={[
          {
            run_id: "run-current-001",
            kind: "experiment",
            label: "bounded fixture run",
            started_at: "2026-09-08T03:55:00Z",
            heartbeat_at: "2026-09-08T03:59:30Z",
          },
        ]}
      />,
    );

    expect(screen.getByTestId("owe-strip")).toHaveTextContent(
      "They do not establish a current obligation, eligibility, or approval",
    );
    expect(screen.getByTestId("pulse-human-requests")).not.toHaveAttribute(
      "open",
    );
    expect(screen.getByTestId("now-board")).toHaveAttribute(
      "data-source-state",
      "current",
    );
    expect(screen.getByText("bounded fixture run")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Review recorded requests"));
    expect(screen.getByTestId("pulse-human-requests")).toHaveAttribute("open");
    expect(
      screen.getByRole("link", { name: /Recorded verdict request/i }),
    ).toHaveAttribute("href", "/dossier/iter-recorded-001");
  });

  it("never converts malformed request and run sources into cleared or idle claims", () => {
    render(
      <Workflow
        items={({ bad: "shape" } as unknown) as HumanTodoItem[]}
        runs={("bad-runs" as unknown) as ActiveRun[]}
      />,
    );

    expect(screen.getByTestId("owe-count")).toHaveTextContent("unknown");
    expect(screen.getByTestId("owe-malformed")).toBeInTheDocument();
    expect(screen.getByTestId("now-board")).toHaveAttribute(
      "data-source-state",
      "unknown",
    );
    expect(screen.queryByTestId("owe-empty")).toBeNull();
    expect(screen.queryByTestId("now-board-empty")).toBeNull();
    expect(screen.queryByTestId("now-verdict")).toBeNull();
    expect(document.body).not.toHaveTextContent(/unblocked|\bIDLE\b|\bDOWN\b/);
  });
});
