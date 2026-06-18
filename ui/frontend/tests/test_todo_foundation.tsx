// Role B foundation: assert the /todo cockpit fixtures match the types and the
// api/todo.ts helpers build the right URLs + bodies, and degrade on a 404
// version-skew the way attest.ts does. No network — fetch is stubbed via
// vi.stubGlobal only for the url-shape assertions. Kept light.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  COCKPIT_UNAVAILABLE,
  getCockpitAvailability,
  getConcurrency,
  postAbstain,
  postAuthorizeFix,
  postCalibration,
  postDirectiveSignoff,
  postSpawnTopic,
  TodoError,
} from "../src/api/todo";
import {
  AVAILABILITY_LIVE,
  AVAILABILITY_STUB,
  CALIBRATION_DRAFT,
  CHAT_TURNS_STUB,
  CONCURRENCY_IDLE,
  CONCURRENCY_MIDFLIGHT,
  TODO_ITEMS,
} from "../src/fixtures/todo";
import { RESOLUTION_OUTCOMES } from "../src/types/todo";
import type {
  CockpitAvailability,
  ConcurrencyStatus,
  ResolutionOutcome,
} from "../src/types/todo";

type Call = { url: string; method?: string; body: unknown };
let calls: Call[];

function stubFetch(handler: (url: string) => Partial<Response> & { json?: () => Promise<unknown> }) {
  vi.stubGlobal("fetch", (url: string, init?: RequestInit) => {
    calls.push({
      url,
      method: init?.method,
      body: init?.body ? JSON.parse(String(init.body)) : null,
    });
    return Promise.resolve(handler(url) as Response);
  });
}

beforeEach(() => {
  calls = [];
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("todo fixtures match the types", () => {
  it("the six resolution outcomes are exactly the taxonomy", () => {
    const expected: ResolutionOutcome[] = [
      "sign_off",
      "reject",
      "refine_defer",
      "authorize_fix",
      "spawn_topic",
      "abstain",
    ];
    expect([...RESOLUTION_OUTCOMES]).toEqual(expected);
  });

  it("the stub availability has every NEW seam OFF (honest stub state)", () => {
    const a: CockpitAvailability = AVAILABILITY_STUB;
    expect(a.available).toBe(false);
    expect(Object.values(a.actions).every((v) => v === false)).toBe(true);
    // the forward-looking 'lit up' fixture is the inverse.
    expect(AVAILABILITY_LIVE.available).toBe(true);
    expect(Object.values(AVAILABILITY_LIVE.actions).every((v) => v === true)).toBe(true);
  });

  it("the todo items are taxonomy A+B kinds the idle-hero N counts", () => {
    const kinds = TODO_ITEMS.map((i) => i.kind);
    expect(kinds).toContain("gate_verdict"); // A — judgment
    expect(kinds).toContain("state_file_gate"); // B — blocking halt
    for (const item of TODO_ITEMS) expect(typeof item.id).toBe("string");
  });

  it("calibration draft carries a prediction + 0–1 confidence", () => {
    expect(typeof CALIBRATION_DRAFT.prediction).toBe("string");
    expect(CALIBRATION_DRAFT.confidence).toBeGreaterThanOrEqual(0);
    expect(CALIBRATION_DRAFT.confidence).toBeLessThanOrEqual(1);
  });

  it("concurrency fixtures: idle is contention-free, mid-flight names the run", () => {
    const idle: ConcurrencyStatus = CONCURRENCY_IDLE;
    expect(idle.active).toBe(false);
    // the backend's idle body is EXACTLY {active:false} — no run fields.
    expect(idle.kind).toBeUndefined();
    expect(CONCURRENCY_MIDFLIGHT.active).toBe(true);
    expect(CONCURRENCY_MIDFLIGHT.label).toBeTruthy();
    expect(CONCURRENCY_MIDFLIGHT.kind).toBe("loop_v0");
    expect(CONCURRENCY_MIDFLIGHT.narration).toBeTruthy();
  });

  it("two chat-turn stubs: Gemma DEFENDS, Qwen ATTACKS (D-044)", () => {
    expect(CHAT_TURNS_STUB).toHaveLength(2);
    expect(CHAT_TURNS_STUB.map((t) => t.stance)).toEqual(["defender", "attacker"]);
  });
});

describe("todo api helpers build the right URLs + bodies", () => {
  const ok = (payload: unknown) => () => ({
    ok: true,
    status: 200,
    statusText: "OK",
    json: () => Promise.resolve(payload),
  });

  it("getCockpitAvailability hits /api/todo/available and coerces strictly", async () => {
    stubFetch(ok({ available: true, actions: { authorize_fix: true, bogus: true } }));
    const cap = await getCockpitAvailability();
    expect(calls[0].url).toContain("/api/todo/available");
    expect(cap.available).toBe(true);
    expect(cap.actions.authorize_fix).toBe(true);
    // unknown key dropped; absent seams coerce to false (not truthy).
    expect(cap.actions.abstain).toBe(false);
  });

  it("getCockpitAvailability degrades to unavailable+skew on a 404", async () => {
    stubFetch(() => ({ ok: false, status: 404, statusText: "Not Found" }));
    const cap = await getCockpitAvailability();
    expect(cap.available).toBe(false);
    expect(cap.skew).toBe(true);
    expect(cap.actions).toEqual(COCKPIT_UNAVAILABLE.actions);
  });

  it("getConcurrency hits /api/todo/concurrency and falls back to inactive on 404", async () => {
    stubFetch(ok({ active: true, kind: "loop_v0", label: "loop_v0-x", narration: "embedding" }));
    const live = await getConcurrency();
    expect(calls[0].url).toContain("/api/todo/concurrency");
    expect(live.active).toBe(true);
    expect(live.kind).toBe("loop_v0");
    expect(live.label).toBe("loop_v0-x");
    expect(live.narration).toBe("embedding");

    calls = [];
    stubFetch(() => ({ ok: false, status: 404, statusText: "Not Found" }));
    const fallback = await getConcurrency();
    expect(fallback.active).toBe(false);
    expect(fallback.kind).toBeUndefined();
  });

  it("the NEW-outcome POSTs hit their stub paths with the BACKEND-shaped bodies", async () => {
    stubFetch(ok({ stub: true }));
    // bodies reconciled TO ui/backend/todo_cockpit.py: authorize_fix carries
    // the required `task`; spawn_topic is {ref_id, kind, topic}; abstain is
    // {ref_id, note}; calibration is FLAT {ref_id, prediction, confidence}.
    await postAuthorizeFix({ ref_id: "sf-001", task: "re-run novelty on 02", note: "fix the citation wiring" });
    await postDirectiveSignoff({
      finding_id: "sf-001",
      note: "looks right",
      directive: "proceed to experiment",
    });
    await postSpawnTopic({ ref_id: "sf-001", kind: "finding", topic: "shading under VCG" });
    await postAbstain({ ref_id: "sf-001", note: "re-look later" });
    await postCalibration({ ref_id: "sf-001", prediction: "survives", confidence: 0.7 });

    expect(calls.map((c) => c.url.replace(/^https?:\/\/[^/]+/, ""))).toEqual([
      "/api/todo/authorize_fix",
      "/api/todo/directive_signoff",
      "/api/todo/spawn_topic",
      "/api/todo/abstain",
      "/api/todo/calibration",
    ]);
    expect(calls.every((c) => c.method === "POST")).toBe(true);
    expect(calls[0].body).toEqual({
      ref_id: "sf-001",
      task: "re-run novelty on 02",
      note: "fix the citation wiring",
    });
    expect(calls[1].body).toEqual({
      finding_id: "sf-001",
      note: "looks right",
      directive: "proceed to experiment",
    });
    expect(calls[2].body).toEqual({ ref_id: "sf-001", kind: "finding", topic: "shading under VCG" });
    expect(calls[3].body).toEqual({ ref_id: "sf-001", note: "re-look later" });
    // calibration is FLAT — confidence is a top-level number, not nested.
    expect(calls[4].body).toEqual({ ref_id: "sf-001", prediction: "survives", confidence: 0.7 });
  });

  it("a 502 {rc, stderr} surfaces as a TodoError with stderr verbatim", async () => {
    stubFetch(() => ({
      ok: false,
      status: 502,
      statusText: "Bad Gateway",
      json: () => Promise.resolve({ rc: 2, stderr: "argparse: invalid choice" }),
    }));
    await expect(postAbstain({ ref_id: "sf-001", note: "x" })).rejects.toMatchObject({
      name: "TodoError",
      status: 502,
      rc: 2,
      stderr: "argparse: invalid choice",
    });
    // duck-typed interop: it IS a TodoError instance.
    await stubFetch(() => ({
      ok: false,
      status: 502,
      statusText: "Bad Gateway",
      json: () => Promise.resolve({ rc: 2, stderr: "argparse: invalid choice" }),
    }));
    const err = await postAbstain({ ref_id: "sf-001", note: "x" }).catch((e) => e);
    expect(err).toBeInstanceOf(TodoError);
  });
});
