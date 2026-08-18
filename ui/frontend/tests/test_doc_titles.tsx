// Doc-id → title fill-in (owner request 2026-08-18: "2604.15267" should read
// "2604.15267 — <its title>"). Pins, in order:
//   1. useDocTitles BATCHES one GET per ≤50 ids, dedups via a module cache,
//      and FILLS IN asynchronously — bare id first, title when answered;
//   2. a failed endpoint leaves bare ids standing (nothing cached, no throw,
//      no spinner litter);
//   3. the dossier ChunksPeek shows the resolved title as the emphasized
//      line while the id stays (smaller, mono);
//   4. the model-io ToolResultCard neighbor rows do the same;
//   5. both surfaces keep the bare id when the endpoint does not answer.
import {
  cleanup,
  fireEvent,
  render as rtlRender,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import useDocTitles, {
  _resetDocTitlesForTests,
} from "../src/hooks/useDocTitles";
import PipelineJourney from "../src/components/todo/PipelineJourney";
import ToolResultCard from "../src/components/payload/ToolResultCard";
import type {
  HumanTodoItem,
  IterationJourneyResponse,
  IterationRecord,
} from "../src/types/schemas";
import * as http from "../src/api/http";

beforeEach(() => {
  _resetDocTitlesForTests();
  // PipelineJourney's absorbed links section joins coordinator cycles on
  // every loaded journey — stub it so no test reaches a live :8700.
  vi.spyOn(http, "getCoordinatorCycles").mockResolvedValue({
    cycles: [],
  } as never);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const TITLES: Record<string, { title: string; kind: string; detail: string }> =
  {
    "2404.08492": {
      title:
        "Strategic Interactions between Large Language Models-based Agents " +
        "in Beauty Contests",
      kind: "paper",
      detail: "2024",
    },
    "osborne_rubinstein-chunk-850": {
      title:
        "Osborne & Rubinstein, A Course in Game Theory — 8 Repeated Games " +
        "(pp 150-151)",
      kind: "book",
      detail: "8.2",
    },
  };

// fetch stub answering /api/doc_titles from TITLES; records every call.
function stubTitlesEndpoint() {
  const mock = vi.fn(async (url: string) => {
    const ids = (new URL(url).searchParams.get("ids") ?? "").split(",");
    const body: Record<string, unknown> = {};
    for (const id of ids) if (TITLES[id]) body[id] = TITLES[id];
    return { ok: true, status: 200, json: async () => body };
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

function stubFailingEndpoint(status = 503) {
  const mock = vi.fn(async () => ({
    ok: false,
    status,
    json: async () => ({ detail: "chroma unavailable" }),
  }));
  vi.stubGlobal("fetch", mock);
  return mock;
}

function Probe({ ids }: { ids: string[] }) {
  const titles = useDocTitles(ids);
  return (
    <div>
      {ids.map((id) => (
        <div key={id} data-testid={`probe-${id}`}>
          {titles[id] ? titles[id].title : `bare:${id}`}
        </div>
      ))}
    </div>
  );
}

// ─── 1+2. hook behavior ────────────────────────────────────────────────────

describe("useDocTitles", () => {
  it("batches ONE GET for all ids and fills titles in (bare id first)", async () => {
    const mock = stubTitlesEndpoint();
    const ids = ["2404.08492", "osborne_rubinstein-chunk-850", "s2:none"];
    rtlRender(<Probe ids={ids} />);
    // Synchronous first paint: every id bare — no blocking on the fetch.
    expect(screen.getByTestId("probe-2404.08492")).toHaveTextContent(
      "bare:2404.08492",
    );
    await waitFor(() =>
      expect(screen.getByTestId("probe-2404.08492")).toHaveTextContent(
        /Beauty Contests/,
      ),
    );
    expect(
      screen.getByTestId("probe-osborne_rubinstein-chunk-850"),
    ).toHaveTextContent(/A Course in Game Theory/);
    // Unresolved id: stays bare, no error state.
    expect(screen.getByTestId("probe-s2:none")).toHaveTextContent(
      "bare:s2:none",
    );
    // ONE batched call carrying all three ids.
    expect(mock).toHaveBeenCalledTimes(1);
    const sent = new URL(mock.mock.calls[0][0] as string).searchParams.get(
      "ids",
    );
    expect(new Set(sent?.split(","))).toEqual(new Set(ids));
  });

  it("splits over-cap requests: 51 ids → a 50-batch and a 1-batch", async () => {
    const mock = stubTitlesEndpoint();
    const many = Array.from({ length: 51 }, (_, i) => `2404.${10000 + i}`);
    rtlRender(<Probe ids={many} />);
    await waitFor(() => expect(mock).toHaveBeenCalledTimes(2));
    const sizes = mock.mock.calls.map(
      (c) =>
        (new URL(c[0] as string).searchParams.get("ids") ?? "").split(",")
          .length,
    );
    expect(sizes.sort((a, b) => b - a)).toEqual([50, 1]);
  });

  it("serves a repeat consumer from the cache — no second fetch", async () => {
    const mock = stubTitlesEndpoint();
    const first = rtlRender(<Probe ids={["2404.08492"]} />);
    await waitFor(() =>
      expect(screen.getByTestId("probe-2404.08492")).toHaveTextContent(
        /Beauty Contests/,
      ),
    );
    first.unmount();
    rtlRender(<Probe ids={["2404.08492"]} />);
    // Cached: the title is there on FIRST paint, and no new request went out.
    expect(screen.getByTestId("probe-2404.08492")).toHaveTextContent(
      /Beauty Contests/,
    );
    expect(mock).toHaveBeenCalledTimes(1);
  });

  it("a failed endpoint leaves every id bare and never throws", async () => {
    const mock = stubFailingEndpoint();
    rtlRender(<Probe ids={["2404.08492"]} />);
    await waitFor(() => expect(mock).toHaveBeenCalledTimes(1));
    expect(screen.getByTestId("probe-2404.08492")).toHaveTextContent(
      "bare:2404.08492",
    );
  });
});

// ─── 3. dossier ChunksPeek ─────────────────────────────────────────────────

const ITER: IterationRecord = {
  iteration_id: "iter-2026-08-18-005",
  started_at: "2026-08-18T09:00:00Z",
  ended_at: "2026-08-18T09:40:00Z",
  journal_entry_path: "journal/iterations/005.md",
  seed: { topic: "x", source: "t" },
  hypothesis: { text: "h" },
  retrieval: {
    k: 2,
    neighbors: [
      { doc_id: "2404.08492", chunk_text: "beauty contest chunk", score: 0.9 },
      { doc_id: "s2:none", chunk_text: "unresolvable chunk", score: 0.5 },
    ],
  },
  gate_status: "pending",
};

const journey: IterationJourneyResponse = {
  found: true,
  iteration_id: ITER.iteration_id,
  iteration: ITER,
};
const item: HumanTodoItem = { kind: "gate_verdict", id: ITER.iteration_id };

function openChunksPeek() {
  rtlRender(<PipelineJourney item={item} journey={journey} />, {
    wrapper: MemoryRouter,
  });
  fireEvent.click(screen.getByTestId("journey-toggle-retrieval"));
  fireEvent.click(screen.getByTestId("journey-peek-chunks"));
}

describe("ChunksPeek titles", () => {
  it("shows the resolved title as the emphasized line; the id stays", async () => {
    stubTitlesEndpoint();
    openChunksPeek();
    await waitFor(() =>
      expect(screen.getByTestId("chunk-title-0")).toHaveTextContent(
        /Beauty Contests/,
      ),
    );
    // The id is still on the row (smaller/mono, but present).
    expect(screen.getByTestId("peek-chunk-0")).toHaveTextContent("2404.08492");
    // The unresolved neighbor keeps its bare id and gets NO title line.
    expect(screen.queryByTestId("chunk-title-1")).toBeNull();
    expect(screen.getByTestId("peek-chunk-1")).toHaveTextContent("s2:none");
  });

  it("keeps bare ids when the endpoint does not answer", async () => {
    const mock = stubFailingEndpoint();
    openChunksPeek();
    await waitFor(() => expect(mock).toHaveBeenCalled());
    expect(screen.queryByTestId("chunk-title-0")).toBeNull();
    expect(screen.getByTestId("peek-chunk-0")).toHaveTextContent("2404.08492");
  });
});

// ─── 4. model-io tool-result neighbor rows ─────────────────────────────────

const ENV = {
  status: "passed",
  result: {
    k: 2,
    neighbors: [
      { doc_id: "2404.08492", score: 0.91, chunk_text: "beauty contests" },
      { doc_id: "s2:none", score: 0.4 },
    ],
  },
  errors: [],
  wrapperRequestId: null,
  parentRequestId: null,
};

describe("ToolResultCard neighbor titles", () => {
  it("renders doc_id + score rows and fills the title in", async () => {
    stubTitlesEndpoint();
    rtlRender(<ToolResultCard env={ENV} />);
    // Neighbor row is id+score, not a bare {…} blob.
    expect(screen.getByText("2404.08492")).toBeInTheDocument();
    expect(screen.getByText("0.91")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId("neighbor-title-0")).toHaveTextContent(
        /Beauty Contests/,
      ),
    );
    // Unresolved id: bare, no title element.
    expect(screen.queryByTestId("neighbor-title-1")).toBeNull();
    expect(screen.getByText("s2:none")).toBeInTheDocument();
  });

  it("keeps bare ids when the endpoint fails", async () => {
    const mock = stubFailingEndpoint();
    rtlRender(<ToolResultCard env={ENV} />);
    await waitFor(() => expect(mock).toHaveBeenCalled());
    expect(screen.queryByTestId("neighbor-title-0")).toBeNull();
    expect(screen.getByText("2404.08492")).toBeInTheDocument();
  });
});
