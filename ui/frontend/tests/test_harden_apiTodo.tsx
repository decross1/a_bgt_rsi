// HARDEN — api/todo.ts (the cockpit STUB fetch client). House robustness
// doctrine: producer-owned bodies (the /api/todo/* stub payloads, the {rc,
// stderr} error envelope) are UNVALIDATED. A malformed/legacy/partial value —
// a bare null, a non-object, a wrong field type, NaN/Infinity, a missing key,
// an empty-vs-absent collection, a version-skew 404, a non-JSON body — must
// DEGRADE to a legible fallback (COCKPIT_UNAVAILABLE / {active:false} / {} /
// dropped field), NEVER throw past the client or fabricate a result.
//
// These tests pin the defensive guards added to asAvailability/asConcurrency,
// the parseJsonSafe wrapper, and the postTodo success/error envelope. Valid-
// input behavior is asserted unchanged (the foundation test owns the happy
// path; these cover the malformed edges only). Network is stubbed via
// vi.stubGlobal("fetch", …) — no real backend.
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  COCKPIT_UNAVAILABLE,
  getCockpitAvailability,
  getConcurrency,
  postAbstain,
  TodoError,
} from "../src/api/todo";

// A minimal Response-shaped stub. `json` may reject (non-JSON body) or resolve
// to any producer payload. Status drives the ok/skew branches.
type RespStub = {
  ok?: boolean;
  status?: number;
  statusText?: string;
  json?: () => Promise<unknown>;
};

function stubFetch(handler: () => RespStub) {
  vi.stubGlobal("fetch", () => Promise.resolve(handler() as unknown as Response));
}

const ok200 = (json: () => Promise<unknown>): RespStub => ({
  ok: true,
  status: 200,
  statusText: "OK",
  json,
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("getCockpitAvailability — malformed body degrades, never crashes", () => {
  it("a non-JSON (rejecting json()) 200 body degrades to COCKPIT_UNAVAILABLE", async () => {
    stubFetch(() => ok200(() => Promise.reject(new SyntaxError("Unexpected token <"))));
    const cap = await getCockpitAvailability();
    expect(cap.available).toBe(false);
    expect(cap.actions).toEqual(COCKPIT_UNAVAILABLE.actions);
    // a non-JSON 200 is NOT a 404 — no skew flag fabricated.
    expect(cap.skew).toBeUndefined();
  });

  it("a bare null 200 body degrades to unavailable", async () => {
    stubFetch(() => ok200(() => Promise.resolve(null)));
    const cap = await getCockpitAvailability();
    expect(cap.available).toBe(false);
    expect(cap.actions).toEqual(COCKPIT_UNAVAILABLE.actions);
  });

  it("a non-object body (array / bare number / string) degrades to unavailable", async () => {
    for (const bad of [[1, 2, 3], 42, "available"]) {
      stubFetch(() => ok200(() => Promise.resolve(bad)));
      const cap = await getCockpitAvailability();
      expect(cap.available).toBe(false);
      expect(cap.actions.authorize_fix).toBe(false);
    }
  });

  it("wrong field types coerce strictly: available:'yes' / actions:[] => all false", async () => {
    // `available` truthy-string and `actions` as an ARRAY (legacy skew) must
    // not slip through === true coercion; actions falls back to {} => all false.
    stubFetch(() => ok200(() => Promise.resolve({ available: "yes", actions: ["authorize_fix"] })));
    const cap = await getCockpitAvailability();
    expect(cap.available).toBe(false);
    expect(Object.values(cap.actions).every((v) => v === false)).toBe(true);
  });

  it("actions:null and a numeric '1' seam value coerce to false (never truthy)", async () => {
    stubFetch(() =>
      ok200(() => Promise.resolve({ available: 1, actions: null })),
    );
    const cap = await getCockpitAvailability();
    expect(cap.available).toBe(false);
    expect(cap.actions).toEqual(COCKPIT_UNAVAILABLE.actions);
  });

  it("a partial actions object keeps present-true seams and defaults absent ones to false", async () => {
    // missing-vs-present: only authorize_fix is true; every other seam absent
    // => false, and an unknown key is dropped (not leaked onto the type).
    stubFetch(() =>
      ok200(() =>
        Promise.resolve({ available: true, actions: { authorize_fix: true, bogus_seam: true } }),
      ),
    );
    const cap = await getCockpitAvailability();
    expect(cap.available).toBe(true);
    expect(cap.actions.authorize_fix).toBe(true);
    expect(cap.actions.abstain).toBe(false);
    expect(cap.actions.calibration).toBe(false);
    expect(cap.actions).not.toHaveProperty("bogus_seam");
  });

  it("a 404 version-skew degrades to unavailable + skew:true (regression on the known path)", async () => {
    stubFetch(() => ({ ok: false, status: 404, statusText: "Not Found" }));
    const cap = await getCockpitAvailability();
    expect(cap.available).toBe(false);
    expect(cap.skew).toBe(true);
    expect(cap.actions).toEqual(COCKPIT_UNAVAILABLE.actions);
  });

  it("a 500 (non-404, non-ok) throws — that is a real error, not skew", async () => {
    stubFetch(() => ({ ok: false, status: 500, statusText: "Internal Server Error" }));
    await expect(getCockpitAvailability()).rejects.toThrow(/500/);
  });
});

describe("getConcurrency — malformed body degrades to inactive", () => {
  it("a non-JSON 200 body degrades to {active:false}", async () => {
    stubFetch(() => ok200(() => Promise.reject(new SyntaxError("bad json"))));
    const c = await getConcurrency();
    expect(c.active).toBe(false);
    expect(c.kind).toBeUndefined();
  });

  it("null / non-object bodies degrade to {active:false}", async () => {
    for (const bad of [null, ["active"], 7, "active"]) {
      stubFetch(() => ok200(() => Promise.resolve(bad)));
      const c = await getConcurrency();
      expect(c.active).toBe(false);
      expect(c.kind).toBeUndefined();
    }
  });

  it("active:'true' truthy-string coerces strictly to false (never truthy)", async () => {
    stubFetch(() => ok200(() => Promise.resolve({ active: "true", kind: "loop_v0" })));
    const c = await getConcurrency();
    expect(c.active).toBe(false);
    // run-describing fields still attach when well-typed.
    expect(c.kind).toBe("loop_v0");
  });

  it("wrong-typed run fields are dropped (absent stays absent, not forced to null)", async () => {
    // kind/label/narration as numbers/objects must NOT surface — they are
    // OMITTED, preserving the absent-vs-null contract the type documents.
    stubFetch(() =>
      ok200(() => Promise.resolve({ active: true, kind: 42, label: { x: 1 }, narration: null })),
    );
    const c = await getConcurrency();
    expect(c.active).toBe(true);
    expect(c.kind).toBeUndefined();
    expect(c.label).toBeUndefined();
    expect(c.narration).toBeUndefined();
  });

  it("the exact idle body {active:false} carries no run fields (empty-vs-absent)", async () => {
    stubFetch(() => ok200(() => Promise.resolve({ active: false })));
    const c = await getConcurrency();
    expect(c).toEqual({ active: false });
  });

  it("a 404 skew falls back to inactive quietly (no fabricated warning)", async () => {
    stubFetch(() => ({ ok: false, status: 404, statusText: "Not Found" }));
    const c = await getConcurrency();
    expect(c.active).toBe(false);
    expect(c.kind).toBeUndefined();
  });
});

describe("postTodo error envelope + success body harden", () => {
  it("a 502 {rc, stderr} surfaces stderr verbatim on a TodoError (regression)", async () => {
    stubFetch(() => ({
      ok: false,
      status: 502,
      statusText: "Bad Gateway",
      json: () => Promise.resolve({ rc: 2, stderr: "argparse: invalid choice 'abstain'" }),
    }));
    const err = await postAbstain({ finding_id: "sf-001", note: "x" }).catch((e) => e);
    expect(err).toBeInstanceOf(TodoError);
    expect(err).toMatchObject({
      status: 502,
      rc: 2,
      stderr: "argparse: invalid choice 'abstain'",
    });
  });

  it("a non-ok body that is NOT valid JSON still throws a clean TodoError (rc/stderr null)", async () => {
    stubFetch(() => ({
      ok: false,
      status: 502,
      statusText: "Bad Gateway",
      json: () => Promise.reject(new SyntaxError("no body")),
    }));
    const err = await postAbstain({ finding_id: "sf-001", note: "x" }).catch((e) => e);
    expect(err).toBeInstanceOf(TodoError);
    expect(err.rc).toBeNull();
    expect(err.stderr).toBeNull();
    expect(err.detail).toMatch(/502/);
  });

  it("a non-object error body (bare array) does not leak rc/stderr from a non-map", async () => {
    stubFetch(() => ({
      ok: false,
      status: 422,
      statusText: "Unprocessable Entity",
      json: () => Promise.resolve(["task is required"]),
    }));
    const err = await postAbstain({ finding_id: "sf-001", note: "x" }).catch((e) => e);
    expect(err).toBeInstanceOf(TodoError);
    expect(err.rc).toBeNull();
    expect(err.stderr).toBeNull();
    expect(err.status).toBe(422);
  });

  it("wrong-typed rc (string) / stderr (number) coerce to null, never surfaced raw", async () => {
    stubFetch(() => ({
      ok: false,
      status: 502,
      statusText: "Bad Gateway",
      json: () => Promise.resolve({ rc: "2", stderr: 500, detail: "boom" }),
    }));
    const err = await postAbstain({ finding_id: "sf-001", note: "x" }).catch((e) => e);
    expect(err.rc).toBeNull();
    expect(err.stderr).toBeNull();
    expect(err.detail).toBe("boom");
  });

  it("a non-JSON SUCCESS (200) body degrades to an empty stub {} — never throws", async () => {
    stubFetch(() => ok200(() => Promise.reject(new SyntaxError("empty body"))));
    const res = await postAbstain({ finding_id: "sf-001", note: "x" });
    expect(res).toEqual({});
  });

  it("a non-object SUCCESS body (bare array / scalar / null) degrades to {} (no fake row)", async () => {
    for (const bad of [["would", "run"], 0, null, "ok"]) {
      stubFetch(() => ok200(() => Promise.resolve(bad)));
      const res = await postAbstain({ finding_id: "sf-001", note: "x" });
      expect(res).toEqual({});
    }
  });

  it("a well-formed stub SUCCESS body is forwarded raw (valid behavior unchanged)", async () => {
    const stub = { stub: true, lights_up_when: "seam lands", would_run: ["todo_cli", "abstain"] };
    stubFetch(() => ok200(() => Promise.resolve(stub)));
    const res = await postAbstain({ finding_id: "sf-001", note: "x" });
    expect(res).toEqual(stub);
  });

  // ADVERSARIAL: a present-but-EMPTY `detail` ("") is the nastiest envelope
  // edge — it slips PAST the `typeof === "string"` guard (an empty string IS a
  // string) yet is illegible. A naive guard would set err.detail = "" and the
  // message to "502 ", burying the only legible signal (the status). The fix
  // mirrors http.ts errorFromResponse's `if (body.detail)` truthiness: an empty
  // detail is treated as ABSENT and falls through to stderr / statusText.
  it("an EMPTY-string detail ('') degrades to stderr, never an illegible empty error", async () => {
    stubFetch(() => ({
      ok: false,
      status: 502,
      statusText: "Bad Gateway",
      json: () => Promise.resolve({ detail: "", rc: 2, stderr: "argparse: invalid choice" }),
    }));
    const err = await postAbstain({ finding_id: "sf-001", note: "x" }).catch((e) => e);
    expect(err).toBeInstanceOf(TodoError);
    // falls through to the verbatim stderr, NOT the empty detail.
    expect(err.detail).toBe("argparse: invalid choice");
    expect(err.message).not.toBe("502 ");
  });

  it("an EMPTY-string detail with NO stderr falls through to '<status> <statusText>'", async () => {
    stubFetch(() => ({
      ok: false,
      status: 502,
      statusText: "Bad Gateway",
      json: () => Promise.resolve({ detail: "" }),
    }));
    const err = await postAbstain({ finding_id: "sf-001", note: "x" }).catch((e) => e);
    expect(err).toBeInstanceOf(TodoError);
    expect(err.detail).toBe("502 Bad Gateway");
    expect(err.stderr).toBeNull();
  });

  // ADVERSARIAL: FastAPI's 422 `detail` is frequently a NESTED ARRAY of
  // validation-error objects ([{loc, msg, type}]) — a deep wrong shape, not a
  // string. It must filter to null (no deref crash) and fall back to statusText.
  it("a FastAPI-style nested-array detail filters out and degrades to statusText", async () => {
    stubFetch(() => ({
      ok: false,
      status: 422,
      statusText: "Unprocessable Entity",
      json: () =>
        Promise.resolve({
          detail: [{ loc: ["body", "task"], msg: "field required", type: "value_error.missing" }],
        }),
    }));
    const err = await postAbstain({ finding_id: "sf-001", note: "x" }).catch((e) => e);
    expect(err).toBeInstanceOf(TodoError);
    expect(err.detail).toBe("422 Unprocessable Entity");
    expect(err.rc).toBeNull();
  });

  // ADVERSARIAL: a Response-shaped body with NO json method at all (a truncated
  // proxy stub / odd polyfill) on the ERROR branch — resp.json() throws
  // synchronously ("resp.json is not a function"); the inline try must catch it
  // and still yield a clean TodoError rather than crashing the caller.
  it("an error response missing json() entirely still yields a clean TodoError", async () => {
    stubFetch(() => ({ ok: false, status: 502, statusText: "Bad Gateway" }));
    const err = await postAbstain({ finding_id: "sf-001", note: "x" }).catch((e) => e);
    expect(err).toBeInstanceOf(TodoError);
    expect(err.status).toBe(502);
    expect(err.rc).toBeNull();
    expect(err.stderr).toBeNull();
  });

  // ADVERSARIAL: json() resolving to `undefined` (not null) on a SUCCESS body —
  // distinct from null; must still hit the non-object branch and degrade to {}.
  it("a SUCCESS body resolving to undefined (not null) degrades to {}", async () => {
    stubFetch(() => ok200(() => Promise.resolve(undefined)));
    const res = await postAbstain({ finding_id: "sf-001", note: "x" });
    expect(res).toEqual({});
  });
});
