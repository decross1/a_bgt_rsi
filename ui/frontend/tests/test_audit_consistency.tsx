// CROSS-CUTTING CONSISTENCY AUDIT (autonomy-observability render half).
//
// The autonomy views are a TRUST-CALIBRATION surface: a human auditor reads
// provenance (who/where-from) and status (passed/errored, novel/survives) at a
// glance, ACROSS several components, and must not be misled by the same datum
// reading two different ways in two places. This file PINS the shared visual
// conventions so a later refactor (an inlined divergent tone map, a renamed
// key, a drifted empty-state testid) is caught by a red test rather than a
// confused human.
//
// It does NOT refactor the shared files — divergences found are reported as
// followups for the serial integrator. The assertions here encode the
// conventions that ARE currently consistent, plus the load-bearing
// distinctness the spec calls out (ui_plan.md §AUTONOMY OBSERVABILITY:
// "provenance everywhere"; the nemoclaw_agent β headline must read distinct
// from a host-coordinator cycle).
//
// No headless browser exists; "renders clean" = jsdom render + a console
// spy (vi.spyOn) asserted not-called, the repo's standing stand-in.
import { render, screen, within, cleanup, fireEvent } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import * as http from "../src/api/http";

import SourceBadge, { sourceTone } from "../src/components/SourceBadge";
import AgentBadge from "../src/components/AgentBadge";
import CoordinatorCycleCard from "../src/components/CoordinatorCycleCard";
import ResolvedIterationsList from "../src/components/ResolvedIterationsList";
import SurfacedFindingsPanel from "../src/components/SurfacedFindingsPanel";
import BubblesPanel from "../src/components/BubblesPanel";
import HealthSignalsPanel from "../src/components/HealthSignalsPanel";
import {
  COORDINATOR_CYCLES_FIXTURE,
  ITERATIONS_COORD_FIXTURE,
} from "../src/fixtures/coordinator";
import type {
  CoordinatorCycle,
  IterationRecord,
} from "../src/types/schemas";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// The Tailwind hue token carried in a className, for tone comparisons. We
// compare HUE (sky/violet/indigo/emerald/red/amber/zinc), not the exact
// shade, so the audit pins "these read as distinct colors" without being
// brittle to a 950→900 shade tweak.
const HUES = [
  "violet",
  "sky",
  "indigo",
  "emerald",
  "red",
  "amber",
  "zinc",
] as const;
function hueOf(className: string): string | null {
  for (const h of HUES) {
    // match `bg-<hue>-` or `text-<hue>-` — the tone maps always pair them.
    if (new RegExp(`(?:bg|text)-${h}-`).test(className)) return h;
  }
  return null;
}

// ---------------------------------------------------------------------------
// 1. SOURCE-BADGE provenance tones — pinned + distinct, and (because both the
//    cycle card and the iterations list render the SAME <SourceBadge>) used
//    consistently across surfaces. The β headline (nemoclaw_agent) must read
//    distinct from the host coordinator and from an arxiv pick.
// ---------------------------------------------------------------------------
describe("audit: SourceBadge provenance tones are pinned and pairwise distinct", () => {
  // The provenance origins that matter for the autonomy views (the ones that
  // appear on cycle topic_source AND iteration seed.source in live data:
  // arxiv_pick, coordinator, nemoclaw_agent, plus the human/probe quiet ones).
  const EXPECTED_HUE: Record<string, string> = {
    nemoclaw_agent: "violet",
    coordinator: "sky",
    arxiv_pick: "indigo",
    loop_memory_probe: "zinc",
    human_cli: "zinc",
    human: "zinc",
  };

  it("each known provenance source maps to its pinned hue", () => {
    for (const [source, hue] of Object.entries(EXPECTED_HUE)) {
      expect(hueOf(sourceTone(source))).toBe(hue);
    }
  });

  it("the three loud origins (nemoclaw/coordinator/arxiv) are pairwise DISTINCT hues", () => {
    const loud = ["nemoclaw_agent", "coordinator", "arxiv_pick"].map((s) =>
      hueOf(sourceTone(s)),
    );
    expect(new Set(loud).size).toBe(loud.length); // all distinct
    // none of the loud origins collapses into the quiet zinc fallback.
    expect(loud).not.toContain("zinc");
  });

  it("an unknown / forward-compat source degrades to quiet zinc, never a loud hue", () => {
    // The next EMIT provenance value the spec says to build for must not
    // accidentally borrow a loud tone before it is given one.
    expect(hueOf(sourceTone("some_future_emit_source"))).toBe("zinc");
  });
});

// ---------------------------------------------------------------------------
// 2. SOURCE-BADGE is used CONSISTENTLY across the two surfaces a human reads
//    side by side: the same provenance value renders the same hue whether it
//    is a cycle's topic_source or an iteration's seed.source. This is the
//    "provenance everywhere, read it the same everywhere" invariant.
// ---------------------------------------------------------------------------
describe("audit: a provenance value reads identically on a cycle card and an iteration row", () => {
  for (const source of ["nemoclaw_agent", "coordinator", "arxiv_pick"]) {
    it(`"${source}" → same hue on CoordinatorCycleCard.topic_source and ResolvedIterationsList seed.source`, () => {
      // Cycle card: topic_source lives under the stable wrapper testid.
      const cycle: CoordinatorCycle = {
        ...COORDINATOR_CYCLES_FIXTURE[1],
        run_id: `cyc-audit-${source}`,
        topic_source: source,
      };
      render(<CoordinatorCycleCard cycle={cycle} />);
      const cardCell = screen.getByTestId("coordinator-topic-source");
      const cardBadge = within(cardCell).getByTestId("source-badge");
      const cardHue = hueOf(cardBadge.className);
      cleanup();

      // Iterations list: seed.source on a row. `initial` bypasses polling.
      const row: IterationRecord = {
        ...ITERATIONS_COORD_FIXTURE[0],
        iteration_id: `iter-audit-${source}`,
        seed: { topic: "audit row", source },
      };
      // 2026-06-10 condense: only nemoclaw_agent badges in the ROW; every
      // source badges in the IterationDetailModal — read the hue there.
      vi.spyOn(http, "getCoordinatorCycles").mockResolvedValue({ cycles: [] });
      render(
        <MemoryRouter>
          <ResolvedIterationsList initial={[row]} />
        </MemoryRouter>,
      );
      fireEvent.click(screen.getByLabelText(`load journal iter-audit-${source}`));
      const modal = within(screen.getByTestId("iteration-detail-modal"));
      const rowHue = hueOf(modal.getAllByTestId("source-badge")[0].className);

      expect(cardHue).not.toBeNull();
      expect(rowHue).toBe(cardHue);
    });
  }
});

// ---------------------------------------------------------------------------
// 3. STATUS / SEVERITY tones are a SEPARATE semantic family from provenance.
//    A reader decodes red = bad-outcome and emerald = good-outcome; those
//    semantics must not be borrowed by the provenance badges (which encode
//    WHERE-FROM, not GOOD/BAD). The spec is explicit that degraded ≠ broken
//    (amber, not red) and a failed dispatch is red — so the status palette
//    owns red/emerald/amber, and provenance must stay clear of conflating
//    "this came from the coordinator" with "this passed".
// ---------------------------------------------------------------------------
describe("audit: status/severity tones vs provenance tones stay in distinct semantic lanes", () => {
  it("provenance hues never reuse the bad/good STATUS hues (red / emerald)", () => {
    // arxiv_pick / coordinator / nemoclaw / human — none should read red or
    // emerald, which a human decodes as a falsified/survives VERDICT.
    for (const source of [
      "nemoclaw_agent",
      "coordinator",
      "arxiv_pick",
      "human_cli",
      "loop_memory_probe",
    ]) {
      const hue = hueOf(sourceTone(source));
      expect(hue).not.toBe("red");
      expect(hue).not.toBe("emerald");
    }
  });

  it("a FAILED dispatch (errored outcome) renders RED with its error string inline (status lane)", () => {
    // The headline make-absence-legible case: the errored outcome in the
    // shared fixture must read red and carry the producer's error text.
    const erroredCycle = COORDINATOR_CYCLES_FIXTURE[0]; // has the errored run_loop_iteration
    render(<CoordinatorCycleCard cycle={erroredCycle} />);
    const errCell = screen.getByTestId(
      "coordinator-action-error-run_loop_iteration",
    );
    expect(hueOf(errCell.className)).toBe("red");
    expect(errCell).toHaveTextContent(/not a valid SeedSource/i);
  });
});

// ---------------------------------------------------------------------------
// 4. EMPTY-STATE convention is UNIFORM across the three new autonomy panels.
//    Each: a `<name>-panel` root testid, a dedicated `*-empty` testid that
//    renders under initial=[], a header count of 0, and NO console noise. A
//    human seeing an absent gitignored data file must get a clean "nothing
//    here" — never a blank gap or a crash (the dark-loop failure this work
//    exists to fix).
// ---------------------------------------------------------------------------
describe("audit: the three autonomy panels share a uniform clean-empty convention", () => {
  const PANELS = [
    {
      name: "SurfacedFindingsPanel",
      el: <SurfacedFindingsPanel initial={[]} />,
      panelTestid: "surfaced-findings-panel",
      emptyTestid: "findings-empty",
    },
    {
      name: "BubblesPanel",
      el: <BubblesPanel initial={[]} />,
      panelTestid: "bubbles-panel",
      emptyTestid: "bubbles-empty",
    },
    {
      name: "HealthSignalsPanel",
      el: <HealthSignalsPanel initial={[]} />,
      panelTestid: "health-signals-panel",
      emptyTestid: "health-signals-empty",
    },
  ];

  for (const p of PANELS) {
    it(`${p.name}: initial=[] → panel root + a dedicated empty-state node, no console errors`, () => {
      const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
      const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

      render(p.el);
      const panel = screen.getByTestId(p.panelTestid);
      expect(panel).toBeInTheDocument();

      // The empty state is its own testid'd node (not a silent blank).
      const empty = within(panel).getByTestId(p.emptyTestid);
      expect(empty).toBeInTheDocument();
      expect(empty.textContent?.trim().length).toBeGreaterThan(0);

      // Header count reads 0 (the shared `ml-auto text-[11px]` count span).
      expect(panel).toHaveTextContent(/(^|\D)0(\D|$)/);

      expect(errSpy).not.toHaveBeenCalled();
      expect(warnSpy).not.toHaveBeenCalled();
    });
  }
});

// ---------------------------------------------------------------------------
// 5. The two PROVENANCE badge families (AgentBadge = who acted, SourceBadge =
//    where-from) agree where they overlap. `coordinator` is a value BOTH can
//    carry (an agent that acted, and a topic source); it must read the same
//    hue in both so a human isn't told the coordinator is "sky here, something
//    else there". This pins the one genuine cross-family overlap.
// ---------------------------------------------------------------------------
describe("audit: AgentBadge and SourceBadge agree on the shared 'coordinator' hue", () => {
  it("coordinator reads the same hue as an agent and as a source", () => {
    render(<AgentBadge agent="coordinator" />);
    const agentHue = hueOf(screen.getByTestId("agent-badge").className);
    cleanup();
    render(<SourceBadge source="coordinator" />);
    const sourceHue = hueOf(screen.getByTestId("source-badge").className);
    expect(agentHue).toBe("sky");
    expect(sourceHue).toBe("sky");
    expect(sourceHue).toBe(agentHue);
  });
});
