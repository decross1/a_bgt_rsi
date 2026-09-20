import { afterEach, describe, expect, it, vi } from "vitest";
import { getDailyOpsMessages, postDailyOpsMessage } from "../src/api/dailyOps";

afterEach(() => vi.unstubAllGlobals());

describe("daily operations owner authentication", () => {
  it("keeps the owner key out of the message URL and sends it as a bearer header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      schema_version: "daily-ops-messages/v1", available: true, writable: true, rows: [],
    }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    await getDailyOpsMessages("owner key with spaces");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/daily-ops/messages?limit=40");
    expect(String(url)).not.toContain("owner");
    expect(init).toEqual({ headers: { Authorization: "Bearer owner key with spaces" } });
  });

  it("sends only the exact revision-bound request contract", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      request_id: "11111111-1111-4111-8111-111111111111", status: "queued",
      accepted_at: "2026-09-20T08:00:00Z", duplicate: false,
      expected_plan_revision: "agenda-r3",
    }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    await postDailyOpsMessage({
      accessKey: "owner-key",
      requestId: "11111111-1111-4111-8111-111111111111",
      intent: "change_request",
      text: "Review the revised gate order.",
      expectedPlanRevision: "agenda-r3",
    });

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/daily-ops/messages");
    expect(String(url)).not.toContain("owner-key");
    expect(init.headers).toEqual({ "Content-Type": "application/json", Authorization: "Bearer owner-key" });
    expect(JSON.parse(init.body)).toEqual({
      request_id: "11111111-1111-4111-8111-111111111111",
      target: "oracle",
      intent: "change_request",
      text: "Review the revised gate order.",
      expected_plan_revision: "agenda-r3",
    });
  });
});
