// "undecidable" verdict tone + skeptic-override tooltip (close-out 2026-06-09,
// docs/ui_validation_handoff.md "evening additions"; EMIT:
// workers/critic_loop_v0.py `_maybe_run_skeptic`).
//
// What this pins, beyond the WF-A forward-compat probes
// (test_forwardcompat_iterations_list / test_forwardcompat_findings_panel,
// which pinned crash-safety + the quiet bg-zinc-800/text-zinc-400 family):
//
//   1. "undecidable" is now a DELIBERATE VERDICT_TONE map entry in both
//      surfaces — the intentional quiet-grey `bg-zinc-800/40 text-zinc-400`,
//      observably distinct (the /40 translucency) from the unknown-enum
//      fallback `bg-zinc-800 text-zinc-400`, while staying inside the quiet
//      family the forward-compat pins require. Fail-closed ("could not be
//      judged on this retrieval") must read quiet, never alarm (no
//      emerald/red/amber).
//   2. When the confirmed override fields are present
//      (verdict_overridden_from / skeptic_verdict — plain strings, may appear
//      on BOTH the novelty and critique blocks; flat on a finding row), the
//      block's badge carries a title tooltip "overridden from <x>; skeptic
//      said <y>" — tooltip only, no new chip. Absent/null fields → no title
//      attribute at all; garbled (object/array) fields degrade to no tooltip
//      and never leak "[object Object]" into the DOM.
//
// Idiom mirrors the forward-compat probes: `initial` prop bypasses polling
// (synchronous render), console.error/warn spied and asserted not-called.
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ResolvedIterationsList from "../src/components/ResolvedIterationsList";
import SurfacedFindingsPanel from "../src/components/SurfacedFindingsPanel";
import type { IterationRecord, SurfacedFinding } from "../src/types/schemas";

function spyConsole() {
  const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  return { errSpy, warnSpy };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const UNDECIDABLE_TONE = "bg-zinc-800/40";
const FALLBACK_BG = "bg-zinc-800";

function iter(overrides: Partial<IterationRecord>): IterationRecord {
  return {
    iteration_id: "iter-x",
    started_at: "2026-06-09T17:00:00Z",
    ended_at: "2026-06-09T17:05:00Z",
    seed: { topic: "tone/tooltip probe", source: "coordinator" },
    journal_entry_path: "journal/iterations/x.md",
    ...overrides,
  };
}

describe("ResolvedIterationsList — undecidable verdict tone + override tooltip", () => {
  it("renders 'undecidable' with the deliberate quiet tone, distinct from the unknown-enum fallback", () => {
    const { errSpy, warnSpy } = spyConsole();
    render(
      <ResolvedIterationsList
        initial={[
          iter({
            iteration_id: "iter-undec",
            novelty: { class: "unclear" },
            critique: { verdict: "undecidable" },
          }),
          // A never-seen FUTURE verdict takes the unknown-enum fallback — the
          // contrast row proving the undecidable entry is intentional.
          iter({
            iteration_id: "iter-future",
            novelty: { class: "novel" },
            critique: { verdict: "future_verdict" },
          }),
        ]}
      />,
    );

    const undecRow = screen.getByLabelText(/load journal iter-undec/);
    const undecBadge = within(undecRow).getByText("undecidable");
    expect(undecBadge.className).toContain(UNDECIDABLE_TONE);
    expect(undecBadge.className).toContain("text-zinc-400");
    // Fail-closed reads quiet, never alarm.
    expect(undecBadge.className).not.toMatch(/emerald|amber|red-950/);

    const futureRow = screen.getByLabelText(/load journal iter-future/);
    const fallbackBadge = within(futureRow).getByText("future_verdict");
    expect(fallbackBadge.className).toContain(FALLBACK_BG);
    // The fallback is the plain zinc — NOT the deliberate /40 entry.
    expect(fallbackBadge.className).not.toContain(UNDECIDABLE_TONE);

    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("title tooltip on the block's badge when override fields are present — both critique and novelty blocks", () => {
    const { errSpy, warnSpy } = spyConsole();
    render(
      <ResolvedIterationsList
        initial={[
          // Critique-side override (the skeptic-gate downgrade): both fields.
          iter({
            iteration_id: "iter-skeptic",
            novelty: { class: "novel" },
            critique: {
              verdict: "undecidable",
              verdict_overridden_from: "survives",
              override_reason: "skeptic attack_verdict='refuted'",
              skeptic_verdict: "refuted",
            },
          }),
          // Novelty-side override (low-confidence downgrade): only
          // verdict_overridden_from — the tooltip carries just that part.
          iter({
            iteration_id: "iter-nov-override",
            novelty: {
              class: "unclear",
              verdict_overridden_from: "novel",
              override_reason: "low-confidence retrieval",
            },
            critique: { verdict: "survives" },
          }),
        ]}
      />,
    );

    const skepticRow = screen.getByLabelText(/load journal iter-skeptic/);
    expect(
      within(skepticRow).getByText("undecidable").getAttribute("title"),
    ).toBe("overridden from survives; skeptic said refuted");
    // The sibling novelty badge on that row carries no override → no tooltip.
    expect(
      within(skepticRow).getByText("novel").getAttribute("title"),
    ).toBeNull();

    const novRow = screen.getByLabelText(/load journal iter-nov-override/);
    expect(within(novRow).getByText("unclear").getAttribute("title")).toBe(
      "overridden from novel",
    );
    expect(
      within(novRow).getByText("survives").getAttribute("title"),
    ).toBeNull();

    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("absent or null override fields → no title attribute (legacy + fail-closed-without-skeptic rows)", () => {
    const { errSpy, warnSpy } = spyConsole();
    render(
      <ResolvedIterationsList
        initial={[
          // Legacy row: no new fields at all.
          iter({
            iteration_id: "iter-legacy",
            novelty: { class: "rediscovery" },
            critique: { verdict: "restated" },
          }),
          // Announced shape with explicit nulls (the producer's no-override
          // emission) — null is "absent", not a tooltip.
          iter({
            iteration_id: "iter-nulls",
            novelty: { class: "unclear" },
            critique: {
              verdict: "undecidable",
              skeptic_verdict: null,
            },
          }),
        ]}
      />,
    );

    const legacyRow = screen.getByLabelText(/load journal iter-legacy/);
    expect(
      within(legacyRow).getByText("restated").getAttribute("title"),
    ).toBeNull();
    expect(
      within(legacyRow).getByText("rediscovery").getAttribute("title"),
    ).toBeNull();

    const nullsRow = screen.getByLabelText(/load journal iter-nulls/);
    expect(
      within(nullsRow).getByText("undecidable").getAttribute("title"),
    ).toBeNull();

    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("garbled (object/array) override fields degrade to no tooltip — no [object Object] in the DOM", () => {
    const { errSpy, warnSpy } = spyConsole();
    const garbled = {
      iteration_id: "iter-garbled-tooltip",
      started_at: "2026-06-09T17:10:00Z",
      ended_at: "2026-06-09T17:15:00Z",
      seed: { topic: "garbled override fields", source: "coordinator" },
      novelty: { class: "novel", verdict_overridden_from: { from: "novel" } },
      critique: {
        verdict: "undecidable",
        verdict_overridden_from: { from: "survives" },
        skeptic_verdict: ["refuted"],
      },
      journal_entry_path: "journal/iterations/garbled-tooltip.md",
    } as unknown as IterationRecord;

    const { container } = render(<ResolvedIterationsList initial={[garbled]} />);

    const row = screen.getByLabelText(/load journal iter-garbled-tooltip/);
    expect(within(row).getByText("undecidable").getAttribute("title")).toBeNull();
    expect(within(row).getByText("novel").getAttribute("title")).toBeNull();
    expect(container.innerHTML).not.toMatch(/object Object/);

    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });
});

describe("SurfacedFindingsPanel — undecidable verdict tone + override tooltip", () => {
  it("renders critic_verdict 'undecidable' with the deliberate quiet tone, distinct from the unknown-enum fallback", () => {
    const { errSpy, warnSpy } = spyConsole();
    const findings: SurfacedFinding[] = [
      {
        finding_id: "f-undec",
        title: "fail-closed finding",
        critic_verdict: "undecidable",
        promoted_at: "2026-06-09T17:00:00Z",
      },
      {
        finding_id: "f-future",
        title: "future-verdict finding",
        critic_verdict: "future_verdict",
        promoted_at: "2026-06-09T16:50:00Z",
      },
    ];
    render(<SurfacedFindingsPanel initial={findings} />);

    const undecBadge = within(screen.getByTestId("finding-f-undec")).getByText(
      "undecidable",
    );
    expect(undecBadge.className).toContain(UNDECIDABLE_TONE);
    expect(undecBadge.className).toContain("text-zinc-400");
    expect(undecBadge.className).not.toMatch(/emerald|amber|red-950/);

    const fallbackBadge = within(
      screen.getByTestId("finding-f-future"),
    ).getByText("future_verdict");
    expect(fallbackBadge.className).toContain(FALLBACK_BG);
    expect(fallbackBadge.className).not.toContain(UNDECIDABLE_TONE);

    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("title tooltip on the verdict badge when the flat override fields are present; absent/null → none", () => {
    const { errSpy, warnSpy } = spyConsole();
    const findings: SurfacedFinding[] = [
      // Override-shaped row (the promotion EMIT copying the critique
      // siblings flat onto the finding, per the forward-compat probe).
      {
        finding_id: "f-override",
        title: "override-shaped finding",
        critic_verdict: "undecidable",
        verdict_overridden_from: "survives",
        override_reason: "skeptic gate fired",
        skeptic_verdict: "falsified",
        promoted_at: "2026-06-09T17:00:00Z",
      },
      // Explicit nulls — no tooltip.
      {
        finding_id: "f-nulls",
        title: "null override fields",
        critic_verdict: "undecidable",
        verdict_overridden_from: null,
        skeptic_verdict: null,
        promoted_at: "2026-06-09T16:50:00Z",
      },
      // Legacy row — fields absent entirely.
      {
        finding_id: "f-legacy",
        title: "legacy finding",
        critic_verdict: "survives",
        promoted_at: "2026-06-09T16:40:00Z",
      },
    ];
    const { container } = render(<SurfacedFindingsPanel initial={findings} />);

    expect(
      within(screen.getByTestId("finding-f-override"))
        .getByText("undecidable")
        .getAttribute("title"),
    ).toBe("overridden from survives; skeptic said falsified");
    // Tooltip only — the sibling values still never surface as text/badges
    // (the forward-compat probe's contract holds).
    const txt = screen.getByTestId("surfaced-findings-panel").textContent ?? "";
    expect(txt).not.toMatch(/skeptic gate fired/);
    expect(screen.queryByText("falsified")).toBeNull();

    expect(
      within(screen.getByTestId("finding-f-nulls"))
        .getByText("undecidable")
        .getAttribute("title"),
    ).toBeNull();
    expect(
      within(screen.getByTestId("finding-f-legacy"))
        .getByText("survives")
        .getAttribute("title"),
    ).toBeNull();
    expect(container.innerHTML).not.toMatch(/object Object/);

    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });
});
