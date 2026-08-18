// Dossier enrichment tests (2026-08-18 gaps): the D-071 DEBATE EXCHANGE in the
// critic section + the retrieval chunk-text EXPANDABLE SNIPPET in the chunks
// peek. Rendered through PipelineJourney with an injected journey (the
// component's test-injection override — no network, mirrors
// test_PipelineJourney.tsx).
//
// Pins: (1) a critique.debate renders header (verdict badge, rounds,
// stop_reason), the transcript collapsed beyond the FIRST 2 turns with an
// expand-all, backend/model provenance per turn, and the CONCESSION as an
// explicit machine-validated terminal event (visible even while collapsed —
// it is the outcome, not a prose turn); (2) an iteration WITHOUT a debate is
// byte-for-byte the pre-debate critic section (single-shot skeptic line only,
// no debate chrome — zero regression); (3) neighbor chunk_text renders as a
// collapsed ~300-char snippet with per-neighbor show-more/show-less, and a
// neighbor genuinely lacking text keeps the honest id-only fallback line;
// (4) malformed producer shapes degrade (drop, never throw, never
// "[object Object]" / NaN).
import {
  cleanup,
  fireEvent,
  render as rtlRender,
  screen,
  within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PipelineJourney from "../src/components/todo/PipelineJourney";
import type {
  HumanTodoItem,
  IterationJourneyResponse,
  IterationRecord,
} from "../src/types/schemas";
import * as http from "../src/api/http";

const render = (ui: React.ReactElement) =>
  rtlRender(ui, { wrapper: MemoryRouter });

// The absorbed links section joins coordinator cycles on every LOADED journey;
// stub it file-wide so no test reaches a live backend (the suite's rule).
beforeEach(() => {
  vi.spyOn(http, "getCoordinatorCycles").mockResolvedValue({
    cycles: [],
  } as never);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const bad = (v: unknown) => v as unknown as never;

function watchConsole() {
  return {
    error: vi.spyOn(console, "error").mockImplementation(() => {}),
    warn: vi.spyOn(console, "warn").mockImplementation(() => {}),
  };
}

const iterItem = (id: string): HumanTodoItem => ({ kind: "gate_verdict", id });

const journeyOf = (iter: IterationRecord | null): IterationJourneyResponse => ({
  found: iter !== null,
  iteration_id: iter?.iteration_id ?? "missing",
  iteration: iter,
});

const expand = (key: string) =>
  fireEvent.click(screen.getByTestId(`journey-toggle-${key}`));

// ── fixtures ───────────────────────────────────────────────────────────────

// A >300-char chunk text with a unique tail token, so snippet truncation is
// assertable from both sides.
const LONG_TEXT =
  "Cooperation among LLM agents varies with context augmentation across game environments. ".repeat(
    5,
  ) + "TAIL_MARKER_END";

// The real iter-2026-08-18-005 shape: 6-turn qwen⇄gemma debate,
// survives_debate via challenger_conceded. Turns keyed `text` (producer key).
const DEBATE = {
  verdict: "survives_debate",
  rounds: 4,
  stop_reason: "challenger_conceded",
  transcript: [
    { round: 1, role: "challenger", backend: "vllm-qwen", model: "qwen3.6-27b-nvfp4-mtp", text: "OBJECT: the claim overreaches.", wall_seconds: 154.3 },
    { round: 1, role: "defender", backend: "vllm-gemma", model: "gemma-4-26b-a4b", text: "DEFEND: bounded to the cited setting.", wall_seconds: 88.1 },
    { round: 2, role: "challenger", backend: "vllm-qwen", model: "qwen3.6-27b-nvfp4-mtp", text: "OBJECT: cite 7 contradicts.", wall_seconds: 120.0 },
    { round: 2, role: "defender", backend: "vllm-gemma", model: "gemma-4-26b-a4b", text: "DEFEND: cite 7 is off-population.", wall_seconds: 91.4 },
    { round: 3, role: "challenger", backend: "vllm-qwen", model: "qwen3.6-27b-nvfp4-mtp", text: "PROBE: strongest remaining doubt.", wall_seconds: 60.2 },
    { round: 3, role: "defender", backend: "vllm-gemma", model: "gemma-4-26b-a4b", text: "DEFEND: doubt already priced in.", wall_seconds: 45.9 },
  ],
};

const BASE: IterationRecord = {
  iteration_id: "iter-2026-08-18-005",
  started_at: "2026-08-18T09:00:00Z",
  ended_at: "2026-08-18T09:40:00Z",
  seed: { topic: "context length vs cooperation", source: "coordinator" },
  hypothesis: { text: "Longer context raises cooperation monotonically." },
  retrieval: {
    k: 2,
    neighbors: [
      { doc_id: "s2:aaa", score: 0.7, chunk_text: LONG_TEXT },
      { doc_id: "s2:bbb", score: 0.61 }, // honestly text-less
    ],
    relevance: { relevance: 0.7, low_confidence: false },
  },
  novelty: { class: "novel", rationale: "no prior monotonicity result." },
  critique: {
    verdict: "survives",
    rationale: "no contradiction surfaced.",
    skeptic_verdict: "survives_debate",
  },
  gate_status: "pending",
  journal_entry_path: "journal/iterations/005.md",
};

const withDebate = (): IterationRecord => ({
  ...BASE,
  critique: { ...BASE.critique, debate: DEBATE },
});

// ═══════════════════════════════════════════════════════════════════════════
// the DEBATE EXCHANGE
// ═══════════════════════════════════════════════════════════════════════════

describe("DebateExchange — critique.debate renders the bounded exchange", () => {
  it("header carries the verdict badge, round count and stop_reason", () => {
    render(
      <PipelineJourney item={iterItem("x")} journey={journeyOf(withDebate())} />,
    );
    expand("critic");
    const debate = screen.getByTestId("journey-debate");
    expect(within(debate).getByTestId("debate-verdict")).toHaveTextContent(
      "survives_debate",
    );
    expect(within(debate).getByTestId("debate-rounds")).toHaveTextContent(
      "4 rounds",
    );
    expect(within(debate).getByTestId("debate-stop")).toHaveTextContent(
      "challenger_conceded",
    );
  });

  it("collapses beyond the FIRST 2 turns; expand-all reveals all 6 with role + backend/model provenance", () => {
    render(
      <PipelineJourney item={iterItem("x")} journey={journeyOf(withDebate())} />,
    );
    expand("critic");
    // collapsed: turns 0 and 1 only
    expect(screen.getByTestId("debate-turn-0")).toBeInTheDocument();
    expect(screen.getByTestId("debate-turn-1")).toBeInTheDocument();
    expect(screen.queryByTestId("debate-turn-2")).toBeNull();
    // the alternation is DATA, surfaced as data-role
    expect(screen.getByTestId("debate-turn-0")).toHaveAttribute(
      "data-role",
      "challenger",
    );
    expect(screen.getByTestId("debate-turn-1")).toHaveAttribute(
      "data-role",
      "defender",
    );
    // per-turn provenance: the roles.ts backend tones + the model in mono
    const turn0 = screen.getByTestId("debate-turn-0");
    expect(turn0).toHaveTextContent("vllm-qwen");
    expect(turn0).toHaveTextContent("qwen3.6-27b-nvfp4-mtp");
    expect(turn0).toHaveTextContent("OBJECT: the claim overreaches.");
    // backendTone(vllm-qwen) = sky family (same chip as health panels/model-io)
    expect(turn0.innerHTML).toContain("bg-sky-950");
    const turn1 = screen.getByTestId("debate-turn-1");
    expect(turn1).toHaveTextContent("vllm-gemma");
    expect(turn1.innerHTML).toContain("bg-emerald-950");

    // expand-all
    const btn = screen.getByTestId("debate-expand");
    expect(btn).toHaveTextContent("show all 6 turns");
    fireEvent.click(btn);
    for (let i = 0; i < 6; i++) {
      expect(screen.getByTestId(`debate-turn-${i}`)).toBeInTheDocument();
    }
    expect(screen.getByTestId("debate-turn-5")).toHaveTextContent(
      "DEFEND: doubt already priced in.",
    );
    // and back
    fireEvent.click(screen.getByTestId("debate-expand"));
    expect(screen.queryByTestId("debate-turn-2")).toBeNull();
  });

  it("the CONCESSION is an explicit terminal event, visible even while the transcript is collapsed", () => {
    render(
      <PipelineJourney item={iterItem("x")} journey={journeyOf(withDebate())} />,
    );
    expand("critic");
    // still collapsed (only 2 turns showing) — the terminal event shows anyway
    expect(screen.queryByTestId("debate-turn-2")).toBeNull();
    const evt = screen.getByTestId("debate-concession");
    expect(evt).toHaveTextContent("challenger CONCEDED");
    expect(evt).toHaveTextContent("machine-validated stance");
  });

  it("a non-concession stop_reason renders NO concession event", () => {
    const iter = withDebate();
    (iter.critique!.debate as Record<string, unknown>).stop_reason = "round_cap";
    render(
      <PipelineJourney item={iterItem("x")} journey={journeyOf(iter)} />,
    );
    expand("critic");
    expect(screen.getByTestId("debate-stop")).toHaveTextContent("round_cap");
    expect(screen.queryByTestId("debate-concession")).toBeNull();
  });

  it("a turn keyed `content` (defensive fallback) still renders its text", () => {
    const iter = withDebate();
    (iter.critique!.debate as Record<string, unknown>).transcript = [
      { role: "challenger", backend: "vllm-qwen", content: "via the content key" },
    ];
    render(
      <PipelineJourney item={iterItem("x")} journey={journeyOf(iter)} />,
    );
    expand("critic");
    expect(screen.getByTestId("debate-turn-0")).toHaveTextContent(
      "via the content key",
    );
  });

  it("malformed debate fields degrade — drop, never throw, never [object Object]/NaN", () => {
    const c = watchConsole();
    const iter = withDebate();
    iter.critique!.debate = bad({
      verdict: { v: 1 },
      rounds: NaN,
      stop_reason: 7, // finite number → renders as "7", legal
      transcript: [null, "a bare string", 42, { role: {}, text: [] }],
    });
    expect(() =>
      render(<PipelineJourney item={iterItem("x")} journey={journeyOf(iter)} />),
    ).not.toThrow();
    expand("critic");
    const debate = screen.getByTestId("journey-debate");
    const text = debate.textContent ?? "";
    expect(text).not.toContain("[object Object]");
    expect(text).not.toMatch(/NaN|Infinity/);
    // only the one record-shaped turn survives, honestly unattributed/text-less
    expect(screen.getByTestId("debate-turn-0")).toHaveTextContent(
      "(unattributed)",
    );
    expect(screen.getByTestId("debate-turn-0")).toHaveTextContent(
      "(no turn text on this row)",
    );
    expect(screen.queryByTestId("debate-turn-1")).toBeNull();
    expect(c.error).not.toHaveBeenCalled();
  });

  it("a non-array transcript renders header + honest no-transcript note", () => {
    const iter = withDebate();
    (iter.critique!.debate as Record<string, unknown>).transcript = "nope";
    render(
      <PipelineJourney item={iterItem("x")} journey={journeyOf(iter)} />,
    );
    expand("critic");
    expect(screen.getByTestId("journey-debate")).toHaveTextContent(
      "no debate transcript on this row",
    );
    expect(screen.queryByTestId("debate-turn-0")).toBeNull();
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// the SINGLE-SHOT fallback — zero regression for pre-debate iterations
// ═══════════════════════════════════════════════════════════════════════════

describe("critic section WITHOUT a debate — the single-shot skeptic line, unchanged", () => {
  it("no debate chrome mounts; the skeptic verdict line renders exactly as before", () => {
    const c = watchConsole();
    render(<PipelineJourney item={iterItem("x")} journey={journeyOf(BASE)} />);
    expand("critic");
    expect(screen.queryByTestId("journey-debate")).toBeNull();
    expect(screen.queryByTestId("debate-concession")).toBeNull();
    // the pre-debate single-shot line is intact
    const critic = screen.getByTestId("journey-critic");
    expect(critic).toHaveTextContent("skeptic verdict");
    expect(critic).toHaveTextContent("survives_debate");
    // …and the peek drill-in is untouched
    expect(screen.getByTestId("journey-peek-critic")).toBeInTheDocument();
    expect(c.error).not.toHaveBeenCalled();
  });

  it("a null/scalar debate value mounts nothing (asRecord guard)", () => {
    for (const junk of [null, "conceded", 4, true]) {
      const iter: IterationRecord = {
        ...BASE,
        critique: { ...BASE.critique, debate: bad(junk) },
      };
      render(<PipelineJourney item={iterItem("x")} journey={journeyOf(iter)} />);
      expand("critic");
      expect(screen.queryByTestId("journey-debate")).toBeNull();
      cleanup();
    }
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// the CHUNK-TEXT SNIPPET in the chunks peek
// ═══════════════════════════════════════════════════════════════════════════

describe("ChunksPeek — chunk_text renders as an expandable snippet", () => {
  function openChunksPeek() {
    expand("retrieval");
    fireEvent.click(screen.getByTestId("journey-peek-chunks"));
  }

  it("long text collapses to ~300 chars; show more reveals the full text; show less collapses back", () => {
    render(<PipelineJourney item={iterItem("x")} journey={journeyOf(BASE)} />);
    openChunksPeek();
    const chunk = screen.getByTestId("peek-chunk-0");
    // collapsed: leading text present, tail hidden, ellipsis shown
    expect(chunk).toHaveTextContent("Cooperation among LLM agents");
    expect(chunk.textContent).not.toContain("TAIL_MARKER_END");
    expect(chunk.textContent).toContain("…");
    // expand
    fireEvent.click(screen.getByTestId("chunk-more-0"));
    expect(screen.getByTestId("peek-chunk-0").textContent).toContain(
      "TAIL_MARKER_END",
    );
    expect(screen.getByTestId("chunk-more-0")).toHaveTextContent("show less");
    // collapse back
    fireEvent.click(screen.getByTestId("chunk-more-0"));
    expect(screen.getByTestId("peek-chunk-0").textContent).not.toContain(
      "TAIL_MARKER_END",
    );
  });

  it("short text renders in full with NO show-more button", () => {
    const iter: IterationRecord = {
      ...BASE,
      retrieval: {
        ...BASE.retrieval,
        neighbors: [{ doc_id: "s2:short", chunk_text: "short and sharp." }],
      },
    };
    render(<PipelineJourney item={iterItem("x")} journey={journeyOf(iter)} />);
    openChunksPeek();
    expect(screen.getByTestId("peek-chunk-0")).toHaveTextContent(
      "short and sharp.",
    );
    expect(screen.queryByTestId("chunk-more-0")).toBeNull();
  });

  it("a neighbor genuinely lacking text keeps the honest id-only fallback line", () => {
    render(<PipelineJourney item={iterItem("x")} journey={journeyOf(BASE)} />);
    openChunksPeek();
    // neighbor 1 (s2:bbb) carries no text in ANY key
    const chunk1 = screen.getByTestId("peek-chunk-1");
    expect(chunk1).toHaveTextContent("s2:bbb");
    expect(chunk1).toHaveTextContent(
      "id only — no cached chunk text for this neighbor",
    );
    expect(screen.queryByTestId("chunk-more-1")).toBeNull();
  });

  it("chunk_text is preferred but the legacy text keys still render (no regression)", () => {
    const iter: IterationRecord = {
      ...BASE,
      retrieval: {
        ...BASE.retrieval,
        neighbors: [{ id: "legacy-1", text: "legacy text key still works" }],
      },
    };
    render(<PipelineJourney item={iterItem("x")} journey={journeyOf(iter)} />);
    openChunksPeek();
    expect(screen.getByTestId("peek-chunk-0")).toHaveTextContent(
      "legacy text key still works",
    );
  });
});
