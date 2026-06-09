// FORWARD-COMPAT probe for SurfacedFindingsPanel — the ANNOUNCED additive-only
// data-contract changes (primary session's advance notice, 2026-06-09; the join
// contract from 0fdb671 is FROZEN, these are new optional fields/enum values):
//
//   - critique.verdict gains "undecidable" (fail-closed; never promotes). A
//     promoted finding row could still plausibly carry it as critic_verdict
//     (e.g. a replayed/override row), so the panel must render it as a quiet
//     zinc badge via the own-key toneFor fallback — NOT crash, NOT garbage CSS.
//   - critique gains optional siblings verdict_overridden_from / override_reason
//     / skeptic_verdict. If the promotion EMIT ever copies these onto the
//     finding row, they ride in via SurfacedFinding's index signature and must
//     be IGNORED (not rendered raw) — the panel renders only its known scalars.
//   - novelty gains optional novelty_axes = {phenomenon, substrate,
//     predicted_direction} — an OBJECT. A row carrying it as an extra key must
//     be inert (an object rendered as a React child throws and blanks the
//     Dashboard; the panel must simply never touch it).
//   - novelty.class may grow future values — an unknown novelty_class string
//     renders as its own quiet-toned badge label.
//
// These rows are INLINE literals by design (the handoff: do NOT touch
// types/schemas.ts or src/fixtures/ until the primary's close-out confirms the
// shapes) — `as unknown as SurfacedFinding[]` because the TS type predates the
// announcement; the disk contract is ahead of the type, which is the point.
//
// No-headless-browser stand-in for "renders without console errors" (the
// test_harden_SurfacedFindingsPanel idiom): jsdom render + console.error/warn
// spies asserted not-called — a render-time throw, a duplicate-key warning, or
// an act() warning all land on console.error in jsdom. The `initial` prop
// bypasses polling so rows render synchronously from the constructed inputs.
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import SurfacedFindingsPanel from "../src/components/SurfacedFindingsPanel";
import type { SurfacedFinding } from "../src/types/schemas";

function spyConsole() {
  const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  return { errSpy, warnSpy };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// row 0: the headline announced enum — critic_verdict "undecidable" (fail-
//        closed) plus the three new critique observability siblings riding as
//        extra row keys (string-valued, the announced types);
// row 1: an OVERRIDE-shaped row — verdict_overridden_from carries a real prior
//        verdict, override_reason free text, skeptic_verdict disagrees; the
//        panel must show only critic_verdict's badge, none of the siblings;
// row 2: the announced novelty_axes OBJECT as an extra key (the fatal-if-
//        rendered shape) alongside a known novelty_class — must be inert;
// row 3: a FUTURE novelty_class value (unknown enum) + "undecidable" together,
//        with novelty_axes carrying every announced axis enum + the new
//        retrieval-relevance fields riding along as extra keys too (a producer
//        that flattens the whole record onto the row) — all ignored.
const ANNOUNCED_CONTRACT_ROWS = [
  {
    finding_id: "fc0",
    title: "fail-closed undecidable finding",
    claim: "verdict could not be decided; never promotes",
    novelty_class: "novel",
    critic_verdict: "undecidable",
    verdict_overridden_from: null,
    override_reason: null,
    skeptic_verdict: null,
    source_iteration_id: "iter-fc-0",
    promoted_at: "2026-06-09T15:00:00Z",
  },
  {
    finding_id: "fc1",
    title: "override-shaped row",
    critic_verdict: "undecidable",
    verdict_overridden_from: "survives",
    override_reason: "skeptic gate fired: evidence below beta threshold",
    skeptic_verdict: "falsified",
    promoted_at: "2026-06-09T14:50:00Z",
  },
  {
    finding_id: "fc2",
    title: "novelty_axes object rides along",
    novelty_class: "rediscovery",
    critic_verdict: "survives",
    novelty_axes: {
      phenomenon: "known",
      substrate: "studied_llm",
      predicted_direction: "matches",
    },
    promoted_at: "2026-06-09T14:40:00Z",
  },
  {
    finding_id: "fc3",
    title: "future novelty class + flattened record",
    // An unknown FUTURE derived class (deliberately shares no substring with
    // the novelty_axes vocabulary so the leak regex below stays sharp).
    novelty_class: "breakthrough_candidate",
    critic_verdict: "undecidable",
    novelty_axes: {
      phenomenon: "novel",
      substrate: "unstudied_llm",
      predicted_direction: "deviates",
    },
    // Announced retrieval.relevance additions, flattened onto the row by a
    // hypothetical future producer — must ride the index signature inertly.
    anchor_cosine: 0.42,
    curated_overlap: null,
    neighbor_spread: 0.13,
    category: "no_sharp_match",
    rule_fired: "r2-thin-corpus",
    promoted_at: "2026-06-09T14:30:00Z",
  },
] as unknown as SurfacedFinding[];

describe("SurfacedFindingsPanel — forward-compat (announced 2026-06-09 contract)", () => {
  it("renders critic_verdict 'undecidable' as a quiet badge, no crash, no console error", () => {
    const { errSpy, warnSpy } = spyConsole();

    expect(() =>
      render(<SurfacedFindingsPanel initial={ANNOUNCED_CONTRACT_ROWS} />),
    ).not.toThrow();

    const panel = within(screen.getByTestId("surfaced-findings-panel"));
    // Every announced-shape row is counted — none dropped.
    expect(
      screen.getByText(String(ANNOUNCED_CONTRACT_ROWS.length)),
    ).toBeInTheDocument();

    // "undecidable" renders as its own badge label (rows fc0/fc1/fc3)...
    const undecidableBadges = panel.getAllByText("undecidable");
    expect(undecidableBadges).toHaveLength(3);
    // ...with the quiet zinc fallback tone (own-key toneFor — not an emerald
    // "promotes" tone, not garbage CSS): undecidable is fail-closed and must
    // read as quiet/unresolved, never as a survives-green.
    for (const badge of undecidableBadges) {
      const cls = badge.getAttribute("class") ?? "";
      expect(cls).toContain("bg-zinc-800");
      expect(cls).not.toMatch(/emerald|function|native code/);
    }

    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("ignores the new critique observability siblings (not rendered raw)", () => {
    const { errSpy, warnSpy } = spyConsole();
    render(<SurfacedFindingsPanel initial={ANNOUNCED_CONTRACT_ROWS} />);

    const txt = screen.getByTestId("surfaced-findings-panel").textContent ?? "";
    // The override row's sibling VALUES must not leak into the panel: there is
    // no render for them yet (that is a later, gated task) — until then they
    // ride the index signature unrendered.
    expect(txt).not.toMatch(/skeptic gate fired/);
    expect(txt).not.toMatch(/verdict_overridden_from|override_reason|skeptic_verdict/);
    // skeptic_verdict:"falsified" on fc1 must NOT surface as a badge — the only
    // verdict badge the panel owns is critic_verdict.
    expect(screen.queryByText("falsified")).toBeNull();
    // The prior verdict "survives" appears ONLY where critic_verdict says so
    // (fc2), never duplicated from fc1's verdict_overridden_from.
    expect(screen.getAllByText("survives")).toHaveLength(1);

    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("treats the novelty_axes OBJECT and flattened relevance extras as inert", () => {
    const { errSpy, warnSpy } = spyConsole();
    render(<SurfacedFindingsPanel initial={ANNOUNCED_CONTRACT_ROWS} />);

    const txt = screen.getByTestId("surfaced-findings-panel").textContent ?? "";
    // The object did not render raw (the React-child crash already failed the
    // not-called error spy if it threw; this pins the stringify leak too).
    expect(txt).not.toMatch(/\[object Object\]/);
    expect(txt).not.toMatch(/phenomenon|studied_llm|predicted_direction/);
    // The flattened retrieval extras likewise never surface.
    expect(txt).not.toMatch(/no_sharp_match|r2-thin-corpus|0\.42/);

    // The FUTURE novelty_class still renders as its own quiet-toned badge —
    // unknown enum shown degraded, never dropped or crashed.
    const futureBadge = screen.getByText("breakthrough_candidate");
    const cls = futureBadge.getAttribute("class") ?? "";
    expect(cls).toContain("bg-zinc-800");

    // The rows' legible fields all still render around the ignored extras.
    expect(screen.getByText("novelty_axes object rides along")).toBeInTheDocument();
    expect(screen.getByText("future novelty class + flattened record")).toBeInTheDocument();

    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });
});
