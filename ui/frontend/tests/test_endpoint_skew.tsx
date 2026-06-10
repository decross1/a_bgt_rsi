// Graceful version skew (handoff Task 2): HttpError carries the status as
// data; a 404 from a KNOWN list/capability endpoint renders as the quiet
// EndpointMissingNote (never red), while a 500 stays an error and a
// resource-404 keeps its existing semantics. All fetches stubbed — no live
// backend, no writes.
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getActiveIteration,
  getActiveRuns,
  getHumanTodo,
  HttpError,
} from "../src/api/http";
import EndpointMissingNote, {
  isVersionSkew404,
} from "../src/components/EndpointMissingNote";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function stubFetchOnce(status: number, body: unknown, statusText = "") {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: status >= 200 && status < 300,
      status,
      statusText,
      json: async () => body,
    } as Response),
  );
}

describe("HttpError (api/http)", () => {
  it("getJSON throws HttpError carrying status + detail on 404", async () => {
    stubFetchOnce(404, { detail: "Not Found" }, "Not Found");
    const err = await getActiveRuns().then(
      () => null,
      (e: unknown) => e,
    );
    expect(err).toBeInstanceOf(HttpError);
    expect((err as HttpError).status).toBe(404);
    expect((err as HttpError).detail).toBe("Not Found");
    // Message keeps the legacy "<status> <detail>" shape so existing
    // string-matching consumers (/500/-style assertions) still hold.
    expect((err as HttpError).message).toBe("404 Not Found");
  });

  it("getJSON throws HttpError with status 500 (stays an error, not skew)", async () => {
    stubFetchOnce(500, { detail: "active_run unreadable: boom" });
    const err = await getHumanTodo().then(
      () => null,
      (e: unknown) => e,
    );
    expect(err).toBeInstanceOf(HttpError);
    expect((err as HttpError).status).toBe(500);
    expect((err as HttpError).detail).toBe("active_run unreadable: boom");
  });

  it("bespoke fetcher (getActiveIteration) throws HttpError too", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        statusText: "Internal Server Error",
        json: async () => {
          throw new Error("no body");
        },
      } as unknown as Response),
    );
    const err = await getActiveIteration().then(
      () => null,
      (e: unknown) => e,
    );
    expect(err).toBeInstanceOf(HttpError);
    expect((err as HttpError).status).toBe(500);
    // statusText fallback when the body had no JSON detail.
    expect((err as HttpError).detail).toBe("Internal Server Error");
  });

  it("getActiveIteration still resolves null on 204 (no iteration)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ status: 204, ok: false } as Response),
    );
    await expect(getActiveIteration()).resolves.toBeNull();
  });
});

describe("isVersionSkew404", () => {
  const skewErr = new HttpError(404, "Not Found");

  it("true for a 404 from each known list/capability endpoint", () => {
    for (const endpoint of [
      "/api/activity/active_runs",
      "/api/attest/available",
      "/api/human_todo",
      "/api/attest/gate_verdict",
      "/api/attest/finding_review",
      "/api/attest/bubble_ack",
      "/api/attest/defer",
    ]) {
      expect(isVersionSkew404(skewErr, endpoint)).toBe(true);
    }
  });

  it("false for a 500 from a known endpoint (a 500 stays red)", () => {
    expect(
      isVersionSkew404(new HttpError(500, "boom"), "/api/activity/active_runs"),
    ).toBe(false);
  });

  it("false for a resource-404 (journal-by-id keeps its existing semantics)", () => {
    expect(
      isVersionSkew404(skewErr, "/api/loop_v0/journal/iter-2026-06-09-001"),
    ).toBe(false);
    expect(isVersionSkew404(skewErr, "/api/chain_by_request/req-1")).toBe(false);
  });

  it("false for a bare Error / non-object (no status to read)", () => {
    expect(
      isVersionSkew404(new Error("404 Not Found"), "/api/human_todo"),
    ).toBe(false);
    expect(isVersionSkew404(null, "/api/human_todo")).toBe(false);
    expect(isVersionSkew404("404", "/api/human_todo")).toBe(false);
  });

  it("duck-types .status — a foreign-bundle error object still matches", () => {
    // Several suites module-mock ../api/http (class binding gone), and a
    // cross-bundle HttpError fails instanceof — the carried status is the
    // contract, not the class identity.
    expect(
      isVersionSkew404({ status: 404 }, "/api/attest/available"),
    ).toBe(true);
    expect(
      isVersionSkew404({ status: "404" }, "/api/attest/available"),
    ).toBe(false);
  });
});

describe("EndpointMissingNote", () => {
  it("renders the quiet zinc note with the given version — never red", () => {
    render(
      <EndpointMissingNote
        endpoint="/api/activity/active_runs"
        version="73b431b"
      />,
    );
    const note = screen.getByTestId("endpoint-missing-note");
    expect(note).toHaveTextContent("/api/activity/active_runs");
    expect(note).toHaveTextContent(
      "endpoint not in this backend build (sha 73b431b)",
    );
    expect(note.className).toContain("zinc");
    expect(note.className).not.toContain("red");
  });

  it("fetches the running binary's sha from /api/health when not given", async () => {
    stubFetchOnce(200, {
      ok: true,
      hostname: "spark",
      telemetry_last_seen: null,
      version: "abc1234",
    });
    render(<EndpointMissingNote endpoint="/api/attest/available" />);
    await waitFor(() =>
      expect(screen.getByTestId("endpoint-missing-note")).toHaveTextContent(
        "sha abc1234",
      ),
    );
  });

  it("reads 'sha unknown' when health is unreachable (quiet failure)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("ECONNREFUSED")),
    );
    render(<EndpointMissingNote endpoint="/api/human_todo" />);
    // The catch path leaves the version null; the note stays legible.
    await waitFor(() =>
      expect(screen.getByTestId("endpoint-missing-note")).toHaveTextContent(
        "sha unknown",
      ),
    );
  });

  it("version={null} renders 'sha unknown' without fetching", () => {
    const spy = vi.fn();
    vi.stubGlobal("fetch", spy);
    render(<EndpointMissingNote endpoint="/api/human_todo" version={null} />);
    expect(screen.getByTestId("endpoint-missing-note")).toHaveTextContent(
      "sha unknown",
    );
    expect(spy).not.toHaveBeenCalled();
  });
});
