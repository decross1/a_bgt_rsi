import { afterEach, describe, expect, it, vi } from "vitest";
import { getDailyOpsMessages, getDailyOpsV3Summary, postDailyOpsDecision, postDailyOpsMessage } from "../src/api/dailyOps";

afterEach(() => vi.unstubAllGlobals());

describe("daily operations owner authentication", () => {
  it("reads the additive v3 view with an owner credential and no write contract", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      schema_version: "daily-ops-summary/v3", generated_at: "2026-09-25T08:00:00Z",
    }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    await getDailyOpsV3Summary("owner key with spaces");

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/daily-ops/v3/summary");
    expect(init).toEqual({ headers: { Authorization: "Bearer owner key with spaces" } });
  });

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

  it("sends a decision as an authenticated revision-bound advisory request", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      request_id: "22222222-2222-4222-8222-222222222222", status: "queued",
      accepted_at: "2026-09-20T08:00:00Z", duplicate: false,
      target_kind: "work_card", target_id: "runner", action: "reprioritize",
      expected_plan_revision: "agenda-r4", execution_available: false,
    }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    await postDailyOpsDecision({
      accessKey: "owner-key",
      requestId: "22222222-2222-4222-8222-222222222222",
      targetKind: "work_card",
      targetId: "runner",
      action: "reprioritize",
      expectedPlanRevision: "agenda-r4",
      note: "Move behind the replay check.",
      priority: "next",
    });

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/daily-ops/decisions");
    expect(String(url)).not.toContain("owner-key");
    expect(init.headers).toEqual({ "Content-Type": "application/json", Authorization: "Bearer owner-key" });
    expect(JSON.parse(init.body)).toEqual({
      request_id: "22222222-2222-4222-8222-222222222222",
      target_kind: "work_card",
      target_id: "runner",
      action: "reprioritize",
      expected_plan_revision: "agenda-r4",
      note: "Move behind the replay check.",
      priority: "next",
    });
  });
});
