// LabSparkgrid — the "is the lab alive?" heatmap (revamp R3). Pins the
// BUCKETING (the part that can silently lie): UTC day keys, the window edges,
// producer-owned junk dropped rather than counted, and the two series summed
// per day. Plus the render contract: one cell per day in the window, a
// sequential ramp with an honest zero class, and totals reachable as TEXT (a
// value must never be hover-gated).
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import LabSparkgrid, {
  bucketByDay,
  dayKeyOf,
  dayKeys,
  rampLevel,
  rampThresholds,
} from "../src/components/LabSparkgrid";

// A fixed instant mid-day UTC, so "the day containing now" is unambiguous.
const NOW = Date.parse("2026-08-15T13:45:00.000Z");

describe("dayKeys / dayKeyOf", () => {
  it("keys are UTC days, oldest-first, ending on the day containing now", () => {
    const keys = dayKeys(NOW, 3);
    expect(keys).toEqual(["2026-08-13", "2026-08-14", "2026-08-15"]);
  });

  it("dayKeyOf is UTC — not the runner's local zone", () => {
    // 23:30Z is still the 15th in UTC even where local time has rolled over.
    expect(dayKeyOf(Date.parse("2026-08-15T23:30:00.000Z"))).toBe("2026-08-15");
    expect(dayKeyOf(Date.parse("2026-08-16T00:30:00.000Z"))).toBe("2026-08-16");
  });
});

describe("bucketByDay", () => {
  it("counts timestamps into their UTC day", () => {
    const counts = bucketByDay(
      [
        "2026-08-15T01:00:00.000Z",
        "2026-08-15T22:00:00.000Z",
        "2026-08-14T12:00:00.000Z",
      ],
      NOW,
      7,
    );
    expect(counts.get("2026-08-15")).toBe(2);
    expect(counts.get("2026-08-14")).toBe(1);
    expect(counts.get("2026-08-13")).toBeUndefined();
  });

  it("drops events outside the window instead of clamping them to an edge", () => {
    // A 7-day window ending 08-15 opens on 08-09; 08-08 is outside it.
    const counts = bucketByDay(
      ["2026-08-08T12:00:00.000Z", "2026-08-09T12:00:00.000Z"],
      NOW,
      7,
    );
    expect(counts.get("2026-08-09")).toBe(1);
    expect([...counts.values()].reduce((a, b) => a + b, 0)).toBe(1);
  });

  it("producer-owned junk is DROPPED, never counted as today", () => {
    const counts = bucketByDay(
      [
        null,
        undefined,
        42,
        { ended_at: "2026-08-15T00:00:00Z" },
        ["2026-08-15T00:00:00Z"],
        "",
        "not-a-timestamp",
        "2026-08-15T05:00:00.000Z",
      ] as unknown[],
      NOW,
      7,
    );
    // Exactly the ONE parseable string survived.
    expect([...counts.values()].reduce((a, b) => a + b, 0)).toBe(1);
    expect(counts.get("2026-08-15")).toBe(1);
  });

  it("a non-array series is empty, not a crash", () => {
    expect(bucketByDay(null as unknown as unknown[], NOW, 7).size).toBe(0);
  });
});

describe("rampThresholds / rampLevel", () => {
  it("zero is its own class; magnitude maps into the 4 lit classes", () => {
    const t = rampThresholds([1, 2, 3, 4, 6, 8, 9, 11, 28, 125]);
    expect(rampLevel(0, t)).toBe(0);
    expect(rampLevel(1, t)).toBe(1);
    expect(rampLevel(6, t)).toBe(2);
    expect(rampLevel(11, t)).toBe(3);
    expect(rampLevel(125, t)).toBe(4);
  });

  it("HEAVY TAIL: real lab data must not collapse into one class", () => {
    // The live 12-week window (2026-08): ~65 active days at 1-4 events against
    // a single 125-event day. Scaling against the MAX put 64 of 65 days in the
    // dimmest class — a heatmap that only says "ran / did not run". Quartiles
    // over the distinct totals must spread them across at least 3 classes.
    const totals = [
      ...Array(3).fill(1),
      ...Array(31).fill(2),
      ...Array(10).fill(3),
      ...Array(14).fill(4),
      6, 6, 8, 9, 11, 28, 125,
    ];
    const t = rampThresholds(totals);
    const used = new Set(totals.map((n) => rampLevel(n, t)));
    expect(used.size).toBeGreaterThanOrEqual(3);
    // The outlier day is unambiguously the hottest; a 1-event day is not.
    expect(rampLevel(125, t)).toBe(4);
    expect(rampLevel(1, t)).toBe(1);
  });

  it("a window with ONE distinct total carries no magnitude — all days read hot", () => {
    // Nothing to rank against, so a steady lab must not render as near-noise.
    const t = rampThresholds([1, 0, 1, 1]);
    expect(rampLevel(1, t)).toBe(4);
  });

  it("a dead window yields cut points that light nothing", () => {
    const t = rampThresholds([0, 0, 0]);
    expect(rampLevel(0, t)).toBe(0);
  });
});

describe("LabSparkgrid render", () => {
  it("renders one cell per day and sums BOTH series into the day's count", () => {
    render(
      <LabSparkgrid
        weeks={2}
        nowMs={NOW}
        iterationTimes={["2026-08-15T01:00:00Z", "2026-08-15T02:00:00Z"]}
        cycleTimes={["2026-08-15T03:00:00Z", "2026-08-14T03:00:00Z"]}
      />,
    );
    expect(document.querySelectorAll('[data-testid^="spark-cell-"]')).toHaveLength(14);
    const today = screen.getByTestId("spark-cell-2026-08-15");
    expect(today).toHaveAttribute("data-count", "3");
    expect(today).toHaveAttribute(
      "title",
      "2026-08-15 · 2 iterations · 1 cycle",
    );
    const yesterday = screen.getByTestId("spark-cell-2026-08-14");
    expect(yesterday).toHaveAttribute("data-count", "1");
    // The busier day is visibly hotter than the quieter one (the cut points
    // are window-relative, so assert the ORDER, not an absolute class).
    expect(Number(today.getAttribute("data-level"))).toBeGreaterThan(
      Number(yesterday.getAttribute("data-level")),
    );
    expect(Number(yesterday.getAttribute("data-level"))).toBeGreaterThan(0);
  });

  it("a dead day is level 0 and says so — never a dim fake value", () => {
    render(<LabSparkgrid weeks={1} nowMs={NOW} iterationTimes={["2026-08-15T01:00:00Z"]} />);
    const dead = screen.getByTestId("spark-cell-2026-08-12");
    expect(dead).toHaveAttribute("data-count", "0");
    expect(dead).toHaveAttribute("data-level", "0");
    expect(dead).toHaveAttribute("title", "2026-08-12 · nothing ran");
  });

  it("totals are readable as TEXT — values are never hover-gated", () => {
    render(
      <LabSparkgrid
        weeks={2}
        nowMs={NOW}
        iterationTimes={["2026-08-15T01:00:00Z", "2026-08-14T01:00:00Z"]}
        cycleTimes={["2026-08-13T01:00:00Z"]}
      />,
    );
    expect(screen.getByTestId("lab-sparkgrid-summary")).toHaveTextContent(
      "2 iterations · 1 coordinator cycle over the last 2 weeks",
    );
  });

  it("an empty apparatus says nothing ran — it does not draw a hopeful grid", () => {
    render(<LabSparkgrid weeks={4} nowMs={NOW} />);
    expect(screen.getByTestId("lab-sparkgrid-summary")).toHaveTextContent(
      "nothing ran in the last 4 weeks",
    );
    // The grid still renders (all-empty IS the signal), every cell at zero.
    const cells = document.querySelectorAll('[data-testid^="spark-cell-"]');
    expect(cells).toHaveLength(28);
    expect([...cells].every((c) => c.getAttribute("data-level") === "0")).toBe(true);
  });
});
