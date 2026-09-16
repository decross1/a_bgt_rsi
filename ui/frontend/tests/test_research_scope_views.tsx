import { cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { getResearch } from "../src/api/experiments";
import {
  getHumanTodo,
  getIterationJourney,
  getIterations,
  getLabTodo,
  getLadder,
} from "../src/api/http";
import {
  admitResearchScopeMetadata,
  getResearchScope,
} from "../src/api/researchScope";
import ResearchScopeBar from "../src/components/ResearchScopeBar";
import DossierIndex from "../src/routes/DossierIndex";
import Experiments from "../src/routes/Experiments";
import {
  explicitResearchScopedHref,
  researchScopedHref,
  researchScopeFromSearch,
  scopedResearchApiPath,
  type ResearchScopeMetadata,
} from "../src/researchScope";
import type { ResearchResponse } from "../src/types/experiments";
import type { HumanTodoItem } from "../src/types/schemas";

const CAMPAIGN = {
  campaign_id: "v2-campaign-test",
  title: "V2 behavior campaign",
  research_question: "Which objective changes cooperation?",
  manifest_sha256: "a".repeat(64),
  activated_at: "2026-09-15T00:00:00Z",
};

const ACTIVE_SCOPE: ResearchScopeMetadata = {
  mode: "active",
  status: "active",
  campaign: CAMPAIGN,
  history_preserved: true,
};

const ALL_SCOPE: ResearchScopeMetadata = {
  mode: "all",
  status: "all_research",
  campaign: null,
  history_preserved: true,
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("research scope URL and identity boundary", () => {
  it("defaults absent and unknown query values to current campaign", () => {
    expect(researchScopeFromSearch("")).toBe("active");
    expect(researchScopeFromSearch("?research_scope=typo")).toBe("active");
    expect(researchScopeFromSearch("?research_scope=all")).toBe("all");
  });

  it("always sends an explicit API scope and preserves unrelated URL state", () => {
    expect(scopedResearchApiPath("/api/ladder?limit=4", "active")).toBe(
      "/api/ladder?limit=4&research_scope=active",
    );
    expect(researchScopedHref("/dossier/iter-1?tab=trace#source", "all")).toBe(
      "/dossier/iter-1?tab=trace&research_scope=all#source",
    );
    expect(
      researchScopedHref(
        "/dossier/iter-1?tab=trace&research_scope=all#source",
        "active",
      ),
    ).toBe("/dossier/iter-1?tab=trace#source");
    expect(explicitResearchScopedHref("/dossier/iter-1#source", "active")).toBe(
      "/dossier/iter-1?research_scope=active#source",
    );
  });

  it("admits only the requested, internally coherent metadata", () => {
    expect(admitResearchScopeMetadata(ACTIVE_SCOPE, "active")).toEqual(ACTIVE_SCOPE);
    expect(admitResearchScopeMetadata(ALL_SCOPE, "all")).toEqual(ALL_SCOPE);
    expect(() => admitResearchScopeMetadata(ALL_SCOPE, "active")).toThrow(
      "Research scope integrity error",
    );
    expect(() =>
      admitResearchScopeMetadata(
        { ...ACTIVE_SCOPE, history_preserved: false },
        "active",
      ),
    ).toThrow("Research scope integrity error");
  });

  it("renders document-reload selectors with preserved current/history URLs", () => {
    render(
      <MemoryRouter initialEntries={["/ladder?panel=board"]}>
        <ResearchScopeBar fetchMetadata={false} initialMetadata={ACTIVE_SCOPE} />
      </MemoryRouter>,
    );
    const selector = screen.getByRole("navigation", { name: "Choose research view" });
    expect(within(selector).getByRole("link", { name: "Current campaign" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(selector).getByRole("link", { name: "All research history" })).toHaveAttribute(
      "href",
      "/ladder?panel=board&research_scope=all",
    );
    expect(screen.getByTestId("research-scope-campaign")).toHaveTextContent(
      "V2 behavior campaign",
    );
    expect(screen.getByTestId("research-scope-campaign")).toHaveTextContent(
      "does not establish queued or running work",
    );
  });

  it("keeps campaign identity compact when a detail page owns the source overview", () => {
    render(
      <MemoryRouter initialEntries={["/dossier/iter-current?research_scope=active"]}>
        <ResearchScopeBar fetchMetadata={false} initialMetadata={ACTIVE_SCOPE} compact />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("research-scope-campaign")).toHaveTextContent(
      "V2 behavior campaign",
    );
    expect(screen.getByTestId("research-scope-campaign")).toHaveTextContent(
      /Campaign context for the exact record below/i,
    );
    expect(screen.queryByText(CAMPAIGN.research_question)).toBeNull();
  });

  it("fetches the scope identity explicitly and fails closed on malformed identity", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(ACTIVE_SCOPE))
      .mockResolvedValueOnce(jsonResponse({ ...ACTIVE_SCOPE, campaign: null }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getResearchScope("active")).resolves.toEqual(ACTIVE_SCOPE);
    expect(String(fetchMock.mock.calls[0][0])).toContain(
      "/api/research_scope?research_scope=active",
    );
    await expect(getResearchScope("active")).rejects.toThrow(
      "Research scope integrity error",
    );
  });

  it("requires scope metadata for explicit journey reads while preserving the legacy unscoped call", async () => {
    const journey = {
      found: true,
      iteration_id: "iter-current",
      iteration: { iteration_id: "iter-current" },
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ ...journey, research_scope: ACTIVE_SCOPE }))
      .mockResolvedValueOnce(jsonResponse(journey))
      .mockResolvedValueOnce(jsonResponse(journey));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getIterationJourney("iter-current", "active")).resolves.toMatchObject(journey);
    expect(new URL(String(fetchMock.mock.calls[0][0]), "http://research.test").searchParams.get("research_scope")).toBe("active");

    await expect(getIterationJourney("iter-current", "active")).rejects.toThrow(
      "Research scope integrity error",
    );

    await expect(getIterationJourney("iter-current")).resolves.toMatchObject(journey);
    expect(new URL(String(fetchMock.mock.calls[2][0]), "http://research.test").searchParams.has("research_scope")).toBe(false);
  });
});

describe("research list clients", () => {
  const activeBodies: Record<string, unknown> = {
    "/api/loop_v0/iterations": { iterations: [], research_scope: ACTIVE_SCOPE },
    "/api/human_todo": { items: [], counts: {}, research_scope: ACTIVE_SCOPE },
    "/api/lab_todo": { agent_gaps: [], human_gaps: [], research_scope: ACTIVE_SCOPE },
    "/api/ladder": {
      clusters: [],
      agenda: [],
      histogram: { L0: 0, L1: 0, L2: 0, L3: 0, L4: 0, L5: 0 },
      counts: { open: 0, surfaced: 0, killed: 0 },
      next_owed: {},
      research_scope: ACTIVE_SCOPE,
    },
    "/api/research": {
      available: true,
      tiers: [],
      untiered: [],
      research_scope: ACTIVE_SCOPE,
    },
  };

  it("sends active explicitly on every current-view source", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: unknown) => {
      const url = new URL(String(input));
      urls.push(url.toString());
      return jsonResponse(activeBodies[url.pathname]);
    }));

    await Promise.all([
      getIterations(undefined, "active"),
      getHumanTodo("active"),
      getLabTodo("active"),
      getLadder("active"),
      getResearch("active"),
    ]);

    expect(urls).toHaveLength(5);
    for (const raw of urls) {
      expect(new URL(raw).searchParams.get("research_scope")).toBe("active");
    }
  });

  it.each([
    ["iterations", () => getIterations(undefined, "active"), { iterations: [] }],
    ["human queue", () => getHumanTodo("active"), { items: [], counts: {} }],
    ["lab queue", () => getLabTodo("active"), { agent_gaps: [], human_gaps: [] }],
    [
      "ladder",
      () => getLadder("active"),
      {
        clusters: [],
        agenda: [],
        histogram: { L0: 0, L1: 0, L2: 0, L3: 0, L4: 0, L5: 0 },
        counts: { open: 0, surfaced: 0, killed: 0 },
        next_owed: {},
      },
    ],
    ["experiments", () => getResearch("active"), { available: true, tiers: [], untiered: [] }],
  ])("rejects an old-backend unscoped 200 from %s", async (_label, call, body) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(body)));
    await expect(call()).rejects.toThrow("Research scope integrity error");
  });
});

describe("current and history route presentation", () => {
  const ITEM: HumanTodoItem = {
    kind: "gate_verdict",
    id: "iter-synthetic",
    title: "Synthetic current decision",
  };

  const EMPTY_TIERS: ResearchResponse = {
    available: true,
    tiers: [
      {
        tier: "applied",
        label: "Applied",
        description: "Legacy applied program description",
        experiments: [],
      },
    ],
    untiered: [],
  };

  it("keeps direct dossier links inside the selected view", () => {
    const { unmount } = render(
      <MemoryRouter initialEntries={["/dossier"]}>
        <DossierIndex items={[ITEM]} iterations={[]} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: /Synthetic current decision/ })).toHaveAttribute(
      "href",
      "/dossier/iter-synthetic?research_scope=all",
    );
    unmount();

    render(
      <MemoryRouter initialEntries={["/dossier?research_scope=all"]}>
        <DossierIndex items={[ITEM]} iterations={[]} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: /Synthetic current decision/ })).toHaveAttribute(
      "href",
      "/dossier/iter-synthetic?research_scope=all",
    );
  });

  it("does not inherit empty legacy tier descriptions into a current campaign", () => {
    const { unmount } = render(
      <MemoryRouter initialEntries={["/experiments"]}>
        <Experiments initial={EMPTY_TIERS} />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("experiments-campaign-empty")).toBeInTheDocument();
    expect(screen.queryByText("Legacy applied program description")).not.toBeInTheDocument();
    unmount();

    render(
      <MemoryRouter initialEntries={["/experiments?research_scope=all"]}>
        <Experiments initial={EMPTY_TIERS} />
      </MemoryRouter>,
    );
    expect(screen.getByText("Legacy applied program description")).toBeInTheDocument();
  });
});
