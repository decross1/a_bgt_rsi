// FORWARD-COMPAT probe — ResolvedIterationsList vs the 2026-06-09 announced
// ADDITIVE data-contract changes (primary session advance notice; join contract
// from 0fdb671 is FROZEN — no renames). The announced shapes, pinned here as
// INLINE literals (types/schemas.ts and src/fixtures/ are deliberately NOT
// extended until the primary's close-out confirms the shapes):
//
//   - critique.verdict gains "undecidable" (fail-closed; never promotes), plus
//     optional siblings verdict_overridden_from / override_reason /
//     skeptic_verdict (string|null each).
//   - novelty gains OPTIONAL novelty_axes = { phenomenon, substrate,
//     predicted_direction } — an OBJECT inside novelty. Legacy novelty.class
//     remains (derived).
//   - retrieval.relevance keeps {relevance, low_confidence, reason} and gains
//     OPTIONAL anchor_cosine / curated_overlap / neighbor_spread (float|null),
//     category ("off_domain"|"thin"|"no_sharp_match"|"empty"|"ok"), rule_fired
//     (string|null).
//
// The list consumes novelty.class, critique.verdict, novelty.novelty_axes
// (via NoveltyAxesChip — wired by WF-B 2026-06-09 evening; renders the three
// axes as plain strings, never the object), and (via LowEvidenceBadge)
// relevance.low_confidence + relevance.reason; the prior hardening (toneFor
// own-key lookup, badgeText scalar coercion) absorbs the new enum value and
// the new siblings. These tests are the announced-contract regression PIN:
// new rows render, "undecidable" gets the quiet fallback badge, the
// novelty_axes OBJECT never reaches a React child, LowEvidenceBadge stays
// driven by low_confidence (not the new category field), and garbled variants
// of every new field degrade silently. Idiom mirrors
// test_harden_ResolvedIterationsList (initial= prop short-circuits the fetch
// effect; console.error/warn spied and asserted empty).
import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ResolvedIterationsList from "../src/components/ResolvedIterationsList";
import type { IterationRecord } from "../src/types/schemas";

// A fully-populated, healthy PRE-CHANGE control row so every case proves the
// known-shape rows still render alongside an announced-shape sibling.
const HEALTHY: IterationRecord = {
  iteration_id: "iter-healthy",
  started_at: "2026-06-09T10:00:00Z",
  ended_at: "2026-06-09T10:05:00Z",
  seed: { topic: "healthy control row", source: "human" },
  novelty: { class: "novel" },
  critique: { verdict: "survives" },
  journal_entry_path: "journal/iterations/healthy.md",
};

afterEach(() => {
  vi.restoreAllMocks();
});

// Render [row, HEALTHY]; assert no throw, both rows present, and no
// console.error/warn (a thrown React render surfaces as a console.error).
function expectSurvives(row: unknown, rowId: string) {
  const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

  let container!: HTMLElement;
  expect(() => {
    container = render(
      <ResolvedIterationsList initial={[row as IterationRecord, HEALTHY]} />,
    ).container;
  }).not.toThrow();

  expect(
    screen.getByLabelText(new RegExp(`load journal ${rowId}`)),
  ).toBeInTheDocument();
  expect(screen.getByLabelText(/load journal iter-healthy/)).toBeInTheDocument();
  expect(
    errorSpy,
    `console.error: ${JSON.stringify(errorSpy.mock.calls)}`,
  ).not.toHaveBeenCalled();
  expect(
    warnSpy,
    `console.warn: ${JSON.stringify(warnSpy.mock.calls)}`,
  ).not.toHaveBeenCalled();
  return { container, errorSpy, warnSpy };
}

describe("ResolvedIterationsList forward-compat — announced 2026-06-09 additive contract", () => {
  it("(a) critique.verdict='undecidable' + the three override siblings: quiet fallback badge, no crash", () => {
    const undecidable = {
      iteration_id: "iter-undecidable",
      started_at: "2026-06-09T11:00:00Z",
      ended_at: "2026-06-09T11:05:00Z",
      seed: { topic: "undecidable verdict row", source: "coordinator" },
      novelty: { class: "unclear" },
      critique: {
        verdict: "undecidable",
        verdict_overridden_from: "survives",
        override_reason: "skeptic gate fired: claim not falsifiable as stated",
        skeptic_verdict: "undecidable",
      },
      journal_entry_path: "journal/iterations/undecidable.md",
    } as unknown as IterationRecord;

    expectSurvives(undecidable, "iter-undecidable");

    // The new enum value renders as a visible badge (generic, not vanished)…
    const row = screen.getByLabelText(/load journal iter-undecidable/);
    const badge = within(row).getByText("undecidable");
    expect(badge).toBeInTheDocument();
    // …with the QUIET fallback tone — undecidable is fail-closed/never
    // promotes, so it must not borrow the green "survives" tone (nor red).
    expect(badge.className).toContain("bg-zinc-800");
    expect(badge.className).toContain("text-zinc-400");
    expect(badge.className).not.toContain("emerald");
    expect(badge.className).not.toContain("red-950");
  });

  it("(b) novelty carrying the novelty_axes OBJECT alongside class: class badge + NoveltyAxesChip strings; the OBJECT never reaches a React child", () => {
    const withAxes = {
      iteration_id: "iter-axes",
      started_at: "2026-06-09T11:10:00Z",
      ended_at: "2026-06-09T11:15:00Z",
      seed: { topic: "novelty axes row", source: "coordinator" },
      novelty: {
        class: "novel",
        novelty_axes: {
          phenomenon: "novel",
          substrate: "unstudied_llm",
          predicted_direction: "deviates",
        },
      },
      critique: { verdict: "survives" },
      journal_entry_path: "journal/iterations/axes.md",
    } as unknown as IterationRecord;

    const { container } = expectSurvives(withAxes, "iter-axes");

    // The legacy derived class still drives the badge…
    const row = screen.getByLabelText(/load journal iter-axes/);
    expect(within(row).getByText("novel")).toBeInTheDocument();
    // …and the axes now render THROUGH NoveltyAxesChip as plain strings (the
    // gated render task landed 2026-06-09 evening, WF-B; original pin said
    // "later, gated task" — coordinated relax by the serial integrator). The
    // raw OBJECT must still never reach React's child renderer.
    const chip = within(row).getByTestId("novelty-axes-chip");
    expect(chip).toHaveTextContent("axes: novel/unstudied_llm/deviates");
    expect(container.innerHTML).not.toMatch(/object Object/);
  });

  it("(c) retrieval.relevance with ALL five new siblings: row renders; LowEvidenceBadge stays driven by low_confidence", () => {
    // low_confidence=true + the full announced sibling set → badge fires as before.
    const flagged = {
      iteration_id: "iter-rel-flagged",
      started_at: "2026-06-09T11:20:00Z",
      ended_at: "2026-06-09T11:25:00Z",
      seed: { topic: "enriched relevance flagged row", source: "coordinator" },
      novelty: { class: "novel" },
      critique: { verdict: "survives" },
      retrieval: {
        relevance: {
          relevance: 0.12,
          low_confidence: true,
          reason: "anchor cosine below band",
          anchor_cosine: 0.11,
          curated_overlap: 0.0,
          neighbor_spread: 0.42,
          category: "off_domain",
          rule_fired: "anchor_cosine_lt_0.25",
        },
      },
      journal_entry_path: "journal/iterations/rel-flagged.md",
    } as unknown as IterationRecord;

    expectSurvives(flagged, "iter-rel-flagged");
    const flaggedRow = screen.getByLabelText(/load journal iter-rel-flagged/);
    const badge = within(flaggedRow).getByTestId("low-evidence-badge");
    expect(badge).toBeInTheDocument();
    // the string reason still folds into the tooltip; the new floats don't.
    expect(badge.getAttribute("title") ?? "").toMatch(/anchor cosine below band/);

    // low_confidence=false with category="thin" + rule_fired set → NO badge.
    // Pins "behavior unchanged": the badge keys on the authoritative boolean,
    // not on the new category/rule fields.
    const unflagged = {
      iteration_id: "iter-rel-ok",
      started_at: "2026-06-09T11:30:00Z",
      ended_at: "2026-06-09T11:35:00Z",
      seed: { topic: "enriched relevance unflagged row", source: "coordinator" },
      novelty: { class: "rediscovery" },
      critique: { verdict: "restated" },
      retrieval: {
        neighbors: [{ doc_id: "d1" }],
        relevance: {
          relevance: 0.61,
          low_confidence: false,
          reason: null,
          anchor_cosine: 0.58,
          curated_overlap: 0.4,
          neighbor_spread: 0.2,
          category: "thin",
          rule_fired: "none",
        },
      },
      journal_entry_path: "journal/iterations/rel-ok.md",
    } as unknown as IterationRecord;

    render(<ResolvedIterationsList initial={[unflagged]} />);
    const okRow = screen.getByLabelText(/load journal iter-rel-ok/);
    expect(within(okRow).queryByTestId("low-evidence-badge")).toBeNull();
  });

  it("(d) one row combining all three announced shapes at once renders cleanly", () => {
    const combined = {
      iteration_id: "iter-combined",
      started_at: "2026-06-09T11:40:00Z",
      ended_at: "2026-06-09T11:45:00Z",
      seed: { topic: "all three announced shapes", source: "nemoclaw_agent" },
      novelty: {
        class: "unclear",
        novelty_axes: {
          phenomenon: "known",
          substrate: "studied_llm",
          predicted_direction: "silent",
        },
      },
      critique: {
        verdict: "undecidable",
        verdict_overridden_from: null,
        override_reason: null,
        skeptic_verdict: "undecidable",
      },
      retrieval: {
        relevance: {
          relevance: 0.3,
          low_confidence: true,
          reason: "no sharp match in corpus",
          anchor_cosine: null,
          curated_overlap: null,
          neighbor_spread: null,
          category: "no_sharp_match",
          rule_fired: "spread_band",
        },
      },
      journal_entry_path: "journal/iterations/combined.md",
    } as unknown as IterationRecord;

    const { container } = expectSurvives(combined, "iter-combined");
    const row = screen.getByLabelText(/load journal iter-combined/);
    expect(within(row).getByText("undecidable")).toBeInTheDocument();
    expect(within(row).getByText("unclear")).toBeInTheDocument();
    expect(within(row).getByTestId("low-evidence-badge")).toBeInTheDocument();
    expect(container.innerHTML).not.toMatch(/object Object/);
  });

  it("(e) garbled variants of the new fields (novelty_axes a string, category a number, override fields objects) degrade silently", () => {
    const garbled = {
      iteration_id: "iter-garbled",
      started_at: "2026-06-09T11:50:00Z",
      ended_at: "2026-06-09T11:55:00Z",
      seed: { topic: "garbled announced-shape row", source: "coordinator" },
      novelty: { class: "novel", novelty_axes: "phenomenon=novel" },
      critique: {
        verdict: "undecidable",
        verdict_overridden_from: { from: "survives" },
        override_reason: { code: 7 },
        skeptic_verdict: ["undecidable"],
      },
      retrieval: {
        relevance: {
          relevance: 0.2,
          low_confidence: true,
          reason: "thin",
          anchor_cosine: "0.11",
          curated_overlap: NaN,
          neighbor_spread: Infinity,
          category: 3,
          rule_fired: { rule: "x" },
        },
      },
      journal_entry_path: "journal/iterations/garbled.md",
    } as unknown as IterationRecord;

    const { container } = expectSurvives(garbled, "iter-garbled");
    const row = screen.getByLabelText(/load journal iter-garbled/);
    // verdict badge still renders; none of the garbled siblings leak.
    expect(within(row).getByText("undecidable")).toBeInTheDocument();
    // a string-valued novelty_axes is not an object → NoveltyAxesChip renders
    // nothing (no chip faking "axes: ?/?/?" off garbage).
    expect(within(row).queryByTestId("novelty-axes-chip")).toBeNull();
    expect(container.innerHTML).not.toMatch(/object Object/);
    expect(container.innerHTML).not.toMatch(/NaN/);
    // the low-evidence badge still fires off the (valid) boolean and its
    // tooltip stays clean despite the garbled siblings.
    const badge = within(row).getByTestId("low-evidence-badge");
    expect(badge.getAttribute("title") ?? "").not.toMatch(/object Object/);
  });
});
