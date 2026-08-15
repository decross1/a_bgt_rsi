// test_design_rung_glyph — RungGlyph, THE rung representation (R0 design
// system). Pins:
//   - level normalization mirrors ladderBar semantics: producer-owned scalar,
//     case/space tolerant, anything not L0..L5 = "no level" (0 segments lit,
//     never a fake L0+);
//   - lit segments = rung + 1 (L0 = 1/6, L5 = full ring);
//   - color encodes the D-059 bar: L4/L5 emerald (--status-ok), L0-L3 sky
//     (--status-info), killed = gray (--status-idle) regardless of rung;
//   - accessible: role=img + a label naming the rung; killed prefixes it.
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import RungGlyph, { rungIndex } from "../src/design/RungGlyph";

afterEach(() => {
  cleanup();
});

function litSegments(): number {
  return screen
    .getByTestId("rung-glyph")
    .querySelectorAll("path[data-lit]").length;
}

describe("rungIndex — producer-owned level normalization", () => {
  it("accepts L0..L5, tolerant of case and padding", () => {
    expect(rungIndex("L0")).toBe(0);
    expect(rungIndex("l3")).toBe(3);
    expect(rungIndex(" L5 ")).toBe(5);
  });

  it("rejects anything else — no fake rungs", () => {
    expect(rungIndex(null)).toBeNull();
    expect(rungIndex(undefined)).toBeNull();
    expect(rungIndex("")).toBeNull();
    expect(rungIndex("L6")).toBeNull(); // above the ladder — malformed, not clamped
    expect(rungIndex("L10")).toBeNull();
    expect(rungIndex(4)).toBeNull(); // number, not the "L4" string
    expect(rungIndex({ level: "L4" })).toBeNull();
    expect(rungIndex("high")).toBeNull();
  });
});

describe("RungGlyph — segments", () => {
  it("always renders 6 segments", () => {
    render(<RungGlyph level="L2" />);
    expect(
      screen.getByTestId("rung-glyph").querySelectorAll("path").length,
    ).toBe(6);
  });

  it("lights rung+1 segments: L0 = 1, L3 = 4, L5 = full ring", () => {
    render(<RungGlyph level="L0" />);
    expect(litSegments()).toBe(1);
    cleanup();
    render(<RungGlyph level="L3" />);
    expect(litSegments()).toBe(4);
    cleanup();
    render(<RungGlyph level="L5" />);
    expect(litSegments()).toBe(6);
  });

  it("no/malformed level lights nothing", () => {
    render(<RungGlyph level={null} />);
    expect(litSegments()).toBe(0);
    expect(screen.getByTestId("rung-glyph")).toHaveAttribute(
      "data-rung",
      "none",
    );
    cleanup();
    render(<RungGlyph level="L9" />);
    expect(litSegments()).toBe(0);
  });
});

describe("RungGlyph — the D-059 bar in color", () => {
  const strokeOfLit = () =>
    screen
      .getByTestId("rung-glyph")
      .querySelector("path[data-lit]")!
      .getAttribute("stroke");

  it("L4/L5 (clears bar) light emerald", () => {
    render(<RungGlyph level="L4" />);
    expect(strokeOfLit()).toBe("var(--status-ok)");
    cleanup();
    render(<RungGlyph level="L5" />);
    expect(strokeOfLit()).toBe("var(--status-ok)");
  });

  it("L0-L3 (below bar) light sky", () => {
    render(<RungGlyph level="L1" />);
    expect(strokeOfLit()).toBe("var(--status-info)");
  });

  it("killed renders the reached rung in gray, whatever the rung", () => {
    render(<RungGlyph level="L4" killed />);
    expect(litSegments()).toBe(5); // rung preserved…
    expect(strokeOfLit()).toBe("var(--status-idle)"); // …color killed
    expect(screen.getByTestId("rung-glyph")).toHaveAttribute("data-killed");
  });
});

describe("RungGlyph — accessibility + labeling", () => {
  it("names the rung (D-059 short form) via role=img", () => {
    render(<RungGlyph level="L4" />);
    expect(
      screen.getByRole("img", { name: "L4 · adversarial-survived" }),
    ).toBeInTheDocument();
  });

  it("killed prefixes the label; no level says so", () => {
    render(<RungGlyph level="L2" killed />);
    expect(
      screen.getByRole("img", { name: /^killed · L2/ }),
    ).toBeInTheDocument();
    cleanup();
    render(<RungGlyph level={undefined} />);
    expect(
      screen.getByRole("img", { name: "no evidence level" }),
    ).toBeInTheDocument();
  });

  it("an explicit title overrides the derived label", () => {
    render(<RungGlyph level="L3" title="finding f-12 · L3" />);
    expect(
      screen.getByRole("img", { name: "finding f-12 · L3" }),
    ).toBeInTheDocument();
  });

  it("size prop scales the box (default 16)", () => {
    render(<RungGlyph level="L1" size={20} />);
    const svg = screen.getByTestId("rung-glyph");
    expect(svg).toHaveAttribute("width", "20");
    expect(svg).toHaveAttribute("viewBox", "0 0 16 16"); // geometry unchanged
  });
});
