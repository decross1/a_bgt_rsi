// NoveltyAxesChip — the compact chip for the decomposed novelty judgment
// `novelty.novelty_axes` (2026-06-09 evening additive contract). Pins:
//   1. full axes render as one "axes: a/b/c" token;
//   2. the transfer/replication EMPHASIS (cyan) fires exactly on
//      phenomenon="known" && substrate="unstudied_llm" and on nothing else;
//   3. partial axes render the known ones with "?" placeholders;
//   4. garbage axes (string / number / null / array / boolean) and garbage
//      axis VALUES degrade to null / "?" — never a throw, never
//      "[object Object]", never a React console.error.
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import NoveltyAxesChip from "../src/components/NoveltyAxesChip";
import { ITERATIONS_OBSERVABILITY_FIXTURE } from "../src/fixtures/coordinator";

afterEach(() => {
  vi.restoreAllMocks();
});

// Cast helper — these values are illegal per the prop type but legal in the
// producer-owned JSONL; the runtime must survive them.
const bad = (v: unknown) => v as unknown as { phenomenon?: string };

describe("NoveltyAxesChip — happy path", () => {
  it("renders the full axes of a fixture row as one compact token", () => {
    // Fixture row 0: a NEW phenomenon (novel/unstudied_llm/silent) — present,
    // but NOT the transfer bucket, so it reads quiet zinc.
    const axes = ITERATIONS_OBSERVABILITY_FIXTURE[0].novelty?.novelty_axes;
    render(<NoveltyAxesChip axes={axes} />);
    const chip = screen.getByTestId("novelty-axes-chip");
    expect(chip).toHaveTextContent("axes: novel/unstudied_llm/silent");
    expect(chip.className).toContain("zinc");
    expect(chip.className).not.toContain("cyan");
  });

  it("emphasizes the transfer/replication bucket (known phenomenon, unstudied LLM substrate)", () => {
    // Fixture row 1 is exactly the close-out's replication-transfer bucket:
    // a known phenomenon on an unstudied LLM substrate.
    const axes = ITERATIONS_OBSERVABILITY_FIXTURE[1].novelty?.novelty_axes;
    render(<NoveltyAxesChip axes={axes} />);
    const chip = screen.getByTestId("novelty-axes-chip");
    expect(chip).toHaveTextContent("axes: known/unstudied_llm/matches");
    expect(chip.className).toContain("cyan");
    // The tooltip explains WHY this one is emphasized.
    expect(chip.getAttribute("title")).toMatch(/transfer|replication/i);
  });

  it("does NOT emphasize known on a STUDIED substrate (only the exact bucket fires)", () => {
    render(
      <NoveltyAxesChip
        axes={{
          phenomenon: "known",
          substrate: "studied_llm",
          predicted_direction: "deviates",
        }}
      />,
    );
    const chip = screen.getByTestId("novelty-axes-chip");
    expect(chip).toHaveTextContent("axes: known/studied_llm/deviates");
    expect(chip.className).toContain("zinc");
    expect(chip.className).not.toContain("cyan");
  });
});

describe("NoveltyAxesChip — partial axes", () => {
  it("renders the present axis with '?' placeholders for the absent ones", () => {
    render(<NoveltyAxesChip axes={{ phenomenon: "known" }} />);
    const chip = screen.getByTestId("novelty-axes-chip");
    expect(chip).toHaveTextContent("axes: known/?/?");
    // substrate is absent, so the transfer bucket cannot fire.
    expect(chip.className).toContain("zinc");
    expect(chip.className).not.toContain("cyan");
  });

  it("coerces garbage axis VALUES to '?' without leaking [object Object]", () => {
    render(
      <NoveltyAxesChip
        axes={bad({
          phenomenon: { nested: true },
          substrate: 42,
          predicted_direction: null,
        })}
      />,
    );
    const chip = screen.getByTestId("novelty-axes-chip");
    // The object and null axes degrade to "?"; the finite number shows raw
    // (forward-compat, same stance as SourceBadge's asText).
    expect(chip).toHaveTextContent("axes: ?/42/?");
    expect(document.body.textContent ?? "").not.toContain("[object Object]");
  });
});

describe("NoveltyAxesChip — garbage / absent axes render nothing", () => {
  it("renders null for null / undefined axes (legacy + explicit-null sentinel rows)", () => {
    const { container, rerender } = render(<NoveltyAxesChip axes={null} />);
    expect(screen.queryByTestId("novelty-axes-chip")).toBeNull();
    expect(container).toBeEmptyDOMElement();

    rerender(<NoveltyAxesChip />);
    expect(screen.queryByTestId("novelty-axes-chip")).toBeNull();
  });

  it("renders null for non-object axes (string / number / boolean / array) without throwing", () => {
    for (const v of [
      "phenomenon=novel",
      42,
      Number.NaN,
      true,
      false,
      ["known", "unstudied_llm"],
    ]) {
      const { unmount } = render(<NoveltyAxesChip axes={bad(v)} />);
      expect(screen.queryByTestId("novelty-axes-chip")).toBeNull();
      unmount();
    }
  });

  it("renders null for an empty / all-garbage object (no usable axis, no 'axes: ?/?/?')", () => {
    const { rerender } = render(<NoveltyAxesChip axes={{}} />);
    expect(screen.queryByTestId("novelty-axes-chip")).toBeNull();

    rerender(
      <NoveltyAxesChip
        axes={bad({ phenomenon: {}, substrate: [], predicted_direction: Number.NaN })}
      />,
    );
    expect(screen.queryByTestId("novelty-axes-chip")).toBeNull();
  });

  it("never logs a React console.error/warn across every malformed shape", () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    for (const v of [
      null,
      undefined,
      "garbage",
      7,
      Number.NaN,
      true,
      [],
      ["a"],
      {},
      { phenomenon: { deep: 1 } },
      { phenomenon: "known", substrate: "unstudied_llm" },
      ITERATIONS_OBSERVABILITY_FIXTURE[0].novelty?.novelty_axes,
    ]) {
      const { unmount } = render(<NoveltyAxesChip axes={bad(v)} />);
      unmount();
    }
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });
});
