// test_design_skeleton — the shape-matching loading shimmer (R0 design
// system). Pins: a bare Skeleton is aria-hidden decoration; SkeletonRows and
// SkeletonCard announce as role=status "loading"; rows match the ListRow
// shape (dsn-row → var(--row-h)) and honor count; the card shell carries the
// card class pair.
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { Skeleton, SkeletonCard, SkeletonRows } from "../src/design/Skeleton";

afterEach(() => {
  cleanup();
});

describe("Skeleton — single block", () => {
  it("renders an aria-hidden shimmer block with the given size", () => {
    render(<Skeleton width={120} height={16} />);
    const el = screen.getByTestId("skeleton");
    expect(el).toHaveAttribute("aria-hidden", "true");
    expect(el).toHaveClass("dsn-skeleton");
    expect(el.style.width).toBe("120px");
    expect(el.style.height).toBe("16px");
  });

  it("accepts string widths (percent shapes)", () => {
    render(<Skeleton width="55%" />);
    expect(screen.getByTestId("skeleton").style.width).toBe("55%");
  });
});

describe("SkeletonRows — list-shaped loading", () => {
  it("announces loading and renders `count` dsn-row rows", () => {
    render(<SkeletonRows count={5} />);
    const wrap = screen.getByRole("status", { name: "loading" });
    expect(wrap.querySelectorAll(".dsn-row").length).toBe(5);
  });

  it("defaults to 3 rows", () => {
    render(<SkeletonRows />);
    expect(
      screen.getByTestId("skeleton-rows").querySelectorAll(".dsn-row").length,
    ).toBe(3);
  });
});

describe("SkeletonCard — card-shaped loading", () => {
  it("announces loading, carries the card shell classes, honors lines", () => {
    render(<SkeletonCard lines={4} />);
    const card = screen.getByRole("status", { name: "loading" });
    expect(card).toHaveClass("dsn-skeleton--card");
    // title line + 4 body lines
    expect(card.querySelectorAll('[data-testid="skeleton"]').length).toBe(5);
  });
});
