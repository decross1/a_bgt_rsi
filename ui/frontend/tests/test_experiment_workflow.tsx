import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import Experiments from "../src/routes/Experiments";
import ExperimentDetail from "../src/routes/ExperimentDetail";
import {
  DETAIL_JSON_FIXTURE,
  RESEARCH_FIXTURE,
} from "../src/fixtures/experiments";

function response(body: unknown) {
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    json: async () => body,
  } as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("experiment catalog to evidence workflow", () => {
  it("uses only pinned GET surfaces and preserves catalog context into detail", async () => {
    const fetchMock = vi.fn(
      async (input: string | URL | Request, _init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/research")) return response(RESEARCH_FIXTURE);
      if (url.endsWith("/api/experiments/exp001_repeated_pd")) {
        return response(DETAIL_JSON_FIXTURE);
      }
      throw new Error(`Unexpected request: ${url}`);
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter
        initialEntries={["/experiments?q=all_d&tier=synthetic"]}
      >
        <Routes>
          <Route path="/experiments" element={<Experiments />} />
          <Route
            path="/experiments/:expId"
            element={<ExperimentDetail />}
          />
        </Routes>
      </MemoryRouter>,
    );

    const source = await screen.findByTestId(
      "research-card-exp001_repeated_pd",
    );
    fireEvent.click(
      within(source).getByRole("link", { name: /exp001 repeated pd/i }),
    );

    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: /exp001 repeated pd/i,
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Experiments/i })).toHaveAttribute(
      "href",
      "/experiments?q=all_d&tier=synthetic",
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const calls = fetchMock.mock.calls.map(([input, init]) => ({
      url: String(input),
      method: (init as RequestInit | undefined)?.method ?? "GET",
    }));
    expect(calls.map(({ method }) => method)).toEqual(["GET", "GET"]);
    expect(calls[0].url).toMatch(/\/api\/research$/);
    expect(calls[1].url).toMatch(
      /\/api\/experiments\/exp001_repeated_pd$/,
    );
    expect(calls.some(({ url }) => url.includes("/api/coordinator/cycles")))
      .toBe(false);
  });

  it("URL-encodes the selected source id for the detail GET", async () => {
    const fetchMock = vi.fn(
      async (_input: string | URL | Request, _init?: RequestInit) =>
        response(DETAIL_JSON_FIXTURE),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter initialEntries={["/experiments/source"]}>
        <ExperimentDetail expIdOverride="source with/slash" />
      </MemoryRouter>,
    );

    await screen.findByTestId("opponent-diagnostic");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toMatch(
      /\/api\/experiments\/source%20with%2Fslash$/,
    );
  });
});
