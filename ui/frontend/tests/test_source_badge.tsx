// SourceBadge — the shared provenance chip for a seed.source / topic_source.
// The load-bearing case is the headline β signal: "nemoclaw_agent" (Nara
// forming + running a thesis itself inside nara-sandbox) must read VIOLET and
// distinctly from a host-coordinator cycle (sky) and an arxiv-picked topic
// (indigo), so the moment the loop drives itself is legible at a glance.
//
// Also covers the forgiving cases the autonomy views rely on: an unknown source
// renders its raw string (a new EMIT provenance value still shows), and a
// null/empty source renders nothing (no badge for an unattributed row). The
// last test renders a real CoordinatorCycleCard whose topic_source is
// "nemoclaw_agent" and asserts the violet badge surfaces end-to-end — and that
// it does so without React/console errors (no headless browser; jsdom + a
// console spy stands in for "renders clean").
import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import SourceBadge, { sourceTone } from "../src/components/SourceBadge";
import CoordinatorCycleCard from "../src/components/CoordinatorCycleCard";
import { COORDINATOR_CYCLES_FIXTURE } from "../src/fixtures/coordinator";
import type { CoordinatorCycle } from "../src/types/schemas";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SourceBadge — tones", () => {
  it("renders nemoclaw_agent VIOLET (the headline) — distinct from coordinator and arxiv_pick", () => {
    const { rerender } = render(<SourceBadge source="nemoclaw_agent" />);
    const nemo = screen.getByTestId("source-badge");
    expect(nemo.className).toContain("violet");
    // The headline tone must not collide with the host-loop or arxiv tones.
    expect(nemo.className).not.toContain("sky");
    expect(nemo.className).not.toContain("indigo");
    // A short humanized label is fine ("nemoclaw"); the full source is on title.
    expect(nemo).toHaveTextContent(/nemoclaw/i);
    expect(nemo).toHaveAttribute("title", "nemoclaw_agent");

    // coordinator -> sky, arxiv_pick -> indigo, and all three differ.
    rerender(<SourceBadge source="coordinator" />);
    const coord = screen.getByTestId("source-badge");
    expect(coord.className).toContain("sky");
    expect(coord.className).not.toContain("violet");

    rerender(<SourceBadge source="arxiv_pick" />);
    const arxiv = screen.getByTestId("source-badge");
    expect(arxiv.className).toContain("indigo");
    expect(arxiv.className).not.toContain("violet");
  });

  it("renders human/memory-probe sources as quiet zinc (not the headline)", () => {
    const { rerender } = render(<SourceBadge source="human_cli" />);
    const human = screen.getByTestId("source-badge");
    expect(human.className).toContain("zinc");
    expect(human.className).not.toContain("violet");
    expect(human).toHaveTextContent(/human/i);

    rerender(<SourceBadge source="loop_memory_probe" />);
    expect(screen.getByTestId("source-badge").className).toContain("zinc");
  });

  it("renders an UNKNOWN source as its raw string, quiet zinc, without crashing", () => {
    render(<SourceBadge source="some_new_emit_value" />);
    const badge = screen.getByTestId("source-badge");
    // Forward-compat: a value we don't know still shows (raw), so a future
    // EMIT provenance string is never silently dropped.
    expect(badge).toHaveTextContent("some_new_emit_value");
    expect(badge.className).toContain("zinc");
  });

  it("renders NOTHING for a null / empty / whitespace source", () => {
    const { rerender } = render(<SourceBadge source={null} />);
    expect(screen.queryByTestId("source-badge")).toBeNull();
    rerender(<SourceBadge source="" />);
    expect(screen.queryByTestId("source-badge")).toBeNull();
    rerender(<SourceBadge source="   " />);
    expect(screen.queryByTestId("source-badge")).toBeNull();
    rerender(<SourceBadge source={undefined} />);
    expect(screen.queryByTestId("source-badge")).toBeNull();
  });
});

describe("sourceTone helper", () => {
  it("maps known sources to their tones and falls back to quiet zinc", () => {
    expect(sourceTone("nemoclaw_agent")).toContain("violet");
    expect(sourceTone("coordinator")).toContain("sky");
    expect(sourceTone("arxiv_pick")).toContain("indigo");
    expect(sourceTone("human_cli")).toContain("zinc");
    // unknown / null / empty -> quiet zinc.
    expect(sourceTone("totally_unknown")).toContain("zinc");
    expect(sourceTone(null)).toContain("zinc");
    expect(sourceTone(undefined)).toContain("zinc");
  });
});

describe("CoordinatorCycleCard — nemoclaw_agent provenance", () => {
  // A cycle DRIVEN by the in-sandbox NemoClaw agent. Built inline (not in the
  // shared fixtures) per the task — the only delta from a normal cycle is the
  // topic_source. The card must surface it as the violet headline badge, under
  // the stable `coordinator-topic-source` testid, with no console errors.
  const nemoclawCycle: CoordinatorCycle = {
    ...COORDINATOR_CYCLES_FIXTURE[1],
    run_id: "cyc-nemoclaw-001",
    topic: "In-sandbox: NemoClaw self-forms a level-k convergence thesis",
    topic_source: "nemoclaw_agent",
  };

  it("shows the violet nemoclaw badge on the cycle card", () => {
    render(<CoordinatorCycleCard cycle={nemoclawCycle} />);

    // The stable testid the cycle/route tests rely on still resolves, and the
    // SourceBadge inside it is the violet headline.
    const sourceCell = screen.getByTestId("coordinator-topic-source");
    const badge = within(sourceCell).getByTestId("source-badge");
    expect(badge.className).toContain("violet");
    expect(badge).toHaveTextContent(/nemoclaw/i);
    // Distinct from the host-coordinator sky tone.
    expect(badge.className).not.toContain("sky");
  });

  it("renders the nemoclaw card without React/console errors (jsdom stand-in for a headless render)", () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    render(<CoordinatorCycleCard cycle={nemoclawCycle} />);
    expect(screen.getByTestId("coordinator-cycle-card")).toBeInTheDocument();
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });
});
