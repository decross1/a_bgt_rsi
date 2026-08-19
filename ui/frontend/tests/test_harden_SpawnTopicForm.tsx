// Hardening for SpawnTopicForm (outcome 5 — spawn a follow-up topic).
//
// HOUSE ROBUSTNESS DOCTRINE: this form's inputs are producer-owned and
// UNVALIDATED — `findingId` rides in from selected.id of a todo row read off
// disk (a legacy/partial row could carry a non-string, null, or absent id),
// `available` comes from GET /api/todo/available (already coerced upstream, but
// the component must defend its own boundary), and the POST RESPONSE BODY is a
// raw stub envelope the running backend produces (it could be null, a bare
// array, a primitive, or carry a malformed `would_run`). A single malformed
// value must DEGRADE to a legible fallback (the "<finding_id>" placeholder, a
// dropped token, the honest stub line) and NEVER blank the page or throw.
//
// VALID-input behavior is unchanged — those paths are already covered by
// tests/test_cockpit_resolution_forms.tsx (kept green); this file pins ONLY the
// defensive guards added for INVALID/edge inputs:
//   - findingId: non-string (object/number/array) / null / NaN-source → "" so
//     the argv shows the "<finding_id>" placeholder and the POST ref_id is "",
//     never "[object Object]" / "undefined" in the preview or the body;
//   - available: coerced `=== true` — a non-boolean truthy value ("false"
//     string, 1, {}) does NOT lift the stub state or enable submit;
//   - onSubmitted: a non-function prop does not throw "not a function" on post;
//   - response body: null / bare-array / primitive / wrong-typed would_run →
//     the result block renders honestly with no [object Object]/NaN/undefined
//     leak and no crash;
//   - 404 version-skew and 502 {rc,stderr} surface legibly (no blank/throw).
//
// No-headless-browser stand-in for "renders without console errors" (the
// test_harden_* idiom): jsdom render + a console.error/warn spy asserted
// not-called — a render-time throw or an act() warning lands on console.error.
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import SpawnTopicForm from "../src/components/todo/SpawnTopicForm";

// --- fetch stub (mirrors test_cockpit_resolution_forms.tsx) -----------------

interface RecordedCall {
  url: string;
  method: string;
  body: Record<string, unknown> | null;
}

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: String(status),
    json: async () => body,
  } as unknown as Response;
}

type Route = (url: string, init?: RequestInit) => Response | undefined;

function stubFetch(route: Route): RecordedCall[] {
  const calls: RecordedCall[] = [];
  vi.stubGlobal("fetch", async (url: unknown, init?: RequestInit) => {
    const u = String(url);
    calls.push({
      url: u,
      method: init?.method ?? "GET",
      body:
        typeof init?.body === "string"
          ? (JSON.parse(init.body) as Record<string, unknown>)
          : null,
    });
    const resp = route(u, init);
    if (resp !== undefined) return resp;
    throw new Error(`unstubbed fetch in test: ${u}`);
  });
  return calls;
}

function spyConsole() {
  const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  return { errSpy, warnSpy };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

// `as unknown as` everywhere a prop/body is deliberately the WRONG type — a real
// producer is not bound by the TS signatures; the point is to hand the form data
// the types forbid but disk/HTTP allow. Exported signatures stay identical.

// ===========================================================================
// findingId — non-string / null / absent (the argv + POST-body leak path)
// ===========================================================================
describe("SpawnTopicForm hardening — malformed findingId", () => {
  const BAD_IDS: { label: string; value: unknown }[] = [
    { label: "null", value: null },
    { label: "undefined", value: undefined },
    { label: "object", value: { id: "nested-finding-id" } },
    { label: "array", value: ["a", "b"] },
    { label: "number", value: 12345 },
    { label: "NaN", value: Number.NaN },
    { label: "boolean", value: true },
    { label: "empty string", value: "" },
  ];

  for (const { label, value } of BAD_IDS) {
    it(`renders the "<finding_id>" placeholder (no [object Object]/NaN/undefined) for a ${label} findingId`, () => {
      const { errSpy, warnSpy } = spyConsole();
      stubFetch(() => undefined);

      expect(() =>
        render(
          <SpawnTopicForm
            findingId={value as unknown as string}
            available={true}
          />,
        ),
      ).not.toThrow();

      const argv = screen.getByTestId("spawn-topic-argv");
      // The crux: a non-string id degrades to the placeholder, never a coercion
      // artifact in the read-only preview.
      expect(argv).toHaveTextContent(/--ref-id <finding_id>/);
      const txt = argv.textContent ?? "";
      expect(txt).not.toMatch(/\[object Object\]/);
      expect(txt).not.toMatch(/NaN/);
      expect(txt).not.toMatch(/undefined/);
      expect(txt).not.toMatch(/12345/);
      expect(txt).not.toMatch(/nested-finding-id/);

      expect(errSpy).not.toHaveBeenCalled();
      expect(warnSpy).not.toHaveBeenCalled();
    });
  }

  it("a valid string findingId still renders verbatim in the argv (behavior preserved)", () => {
    stubFetch(() => undefined);
    render(<SpawnTopicForm findingId="finding-001" available={true} />);
    expect(screen.getByTestId("spawn-topic-argv")).toHaveTextContent(
      /--ref-id finding-001/,
    );
  });

  // `finding_id` is the key the backend reads (this pin said `ref_id` until
  // 2026-08-19, faithfully asserting the body against the wrong contract).
  it("POSTs finding_id as a clean string (\"\"), never [object Object], for an object findingId", async () => {
    const calls = stubFetch((u) =>
      u.endsWith("/api/todo/spawn_topic")
        ? jsonResponse(200, { stub: true, status: "stub", would_run: ["argv"] })
        : undefined,
    );
    render(
      <SpawnTopicForm
        findingId={{ id: "obj-id" } as unknown as string}
        available={true}
      />,
    );
    fireEvent.change(screen.getByLabelText(/new topic/i), {
      target: { value: "anchor coverage" },
    });
    fireEvent.click(screen.getByRole("button", { name: /spawn topic/i }));
    await waitFor(() =>
      expect(screen.getByTestId("spawn-topic-result")).toBeInTheDocument(),
    );
    const post = calls.find((c) => c.url.endsWith("/api/todo/spawn_topic"));
    expect(post?.body).toMatchObject({ finding_id: "", kind: "finding", topic: "anchor coverage" });
    expect(post?.body?.finding_id).toBe(""); // not "[object Object]", not the object
    expect(Object.keys(post?.body ?? {})).not.toContain("ref_id");
  });
});

// ===========================================================================
// available — strict boolean coercion (=== true)
// ===========================================================================
describe("SpawnTopicForm hardening — non-boolean available", () => {
  it("a truthy non-boolean available (\"false\" string) stays in the stub state, submit disabled", () => {
    const { errSpy, warnSpy } = spyConsole();
    stubFetch(() => undefined);
    // A stringy "false" is truthy in JS — a bare `!available` would WRONGLY lift
    // the stub; `available === true` keeps it honest.
    render(
      <SpawnTopicForm
        findingId="finding-001"
        available={"false" as unknown as boolean}
      />,
    );
    expect(screen.getByTestId("spawn-topic-stub")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/new topic/i), {
      target: { value: "anchor coverage" },
    });
    // Even with a non-empty topic, a non-true `available` keeps submit disabled.
    expect(screen.getByRole("button", { name: /spawn topic/i })).toBeDisabled();
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  const TRUTHY_NON_TRUE: { label: string; value: unknown }[] = [
    { label: "number 1", value: 1 },
    { label: "object {}", value: {} },
    { label: "non-empty string", value: "yes" },
    { label: "null", value: null },
    { label: "undefined", value: undefined },
  ];
  for (const { label, value } of TRUTHY_NON_TRUE) {
    it(`treats available=${label} as unavailable (stub shown, submit disabled)`, () => {
      stubFetch(() => undefined);
      render(
        <SpawnTopicForm
          findingId="finding-001"
          available={value as unknown as boolean}
        />,
      );
      expect(screen.getByTestId("spawn-topic-stub")).toBeInTheDocument();
      fireEvent.change(screen.getByLabelText(/new topic/i), {
        target: { value: "x" },
      });
      expect(
        screen.getByRole("button", { name: /spawn topic/i }),
      ).toBeDisabled();
    });
  }

  it("available={true} still enables submit once a topic is typed (behavior preserved)", () => {
    stubFetch(() => undefined);
    render(<SpawnTopicForm findingId="finding-001" available={true} />);
    expect(screen.queryByTestId("spawn-topic-stub")).toBeNull();
    fireEvent.change(screen.getByLabelText(/new topic/i), {
      target: { value: "anchor coverage" },
    });
    expect(
      screen.getByRole("button", { name: /spawn topic/i }),
    ).not.toBeDisabled();
  });
});

// ===========================================================================
// onSubmitted — non-function prop must not throw on post
// ===========================================================================
describe("SpawnTopicForm hardening — non-function onSubmitted", () => {
  it("a truthy non-function onSubmitted does not throw \"not a function\" after a successful post", async () => {
    const { errSpy } = spyConsole();
    stubFetch((u) =>
      u.endsWith("/api/todo/spawn_topic")
        ? jsonResponse(200, { stub: true, status: "stub", would_run: ["argv"] })
        : undefined,
    );
    render(
      <SpawnTopicForm
        findingId="finding-001"
        available={true}
        onSubmitted={"not-a-callback" as unknown as () => void}
      />,
    );
    fireEvent.change(screen.getByLabelText(/new topic/i), {
      target: { value: "anchor coverage" },
    });
    fireEvent.click(screen.getByRole("button", { name: /spawn topic/i }));
    // The result lands (post succeeded) and no console.error from a thrown
    // "onSubmitted is not a function" inside the async submit.
    await waitFor(() =>
      expect(screen.getByTestId("spawn-topic-result")).toBeInTheDocument(),
    );
    expect(errSpy).not.toHaveBeenCalled();
  });

  it("a real onSubmitted is still called once on a successful post (behavior preserved)", async () => {
    const onSubmitted = vi.fn();
    stubFetch((u) =>
      u.endsWith("/api/todo/spawn_topic")
        ? jsonResponse(200, { stub: true, status: "stub", would_run: ["argv"] })
        : undefined,
    );
    render(
      <SpawnTopicForm
        findingId="finding-001"
        available={true}
        onSubmitted={onSubmitted}
      />,
    );
    fireEvent.change(screen.getByLabelText(/new topic/i), {
      target: { value: "anchor coverage" },
    });
    fireEvent.click(screen.getByRole("button", { name: /spawn topic/i }));
    await waitFor(() => expect(onSubmitted).toHaveBeenCalledTimes(1));
  });
});

// ===========================================================================
// response body — null / primitive / bare-array / malformed would_run
// ===========================================================================
describe("SpawnTopicForm hardening — malformed response body", () => {
  async function postWith(): Promise<void> {
    render(<SpawnTopicForm findingId="finding-001" available={true} />);
    fireEvent.change(screen.getByLabelText(/new topic/i), {
      target: { value: "anchor coverage" },
    });
    fireEvent.click(screen.getByRole("button", { name: /spawn topic/i }));
    await waitFor(() =>
      expect(
        screen.queryByTestId("spawn-topic-result") ??
          screen.queryByTestId("spawn-topic-error"),
      ).not.toBeNull(),
    );
  }

  it("a null body degrades to the enqueued line with no would-run pre, no leak, no crash", async () => {
    const { errSpy, warnSpy } = spyConsole();
    stubFetch((u) =>
      u.endsWith("/api/todo/spawn_topic") ? jsonResponse(200, null) : undefined,
    );
    await postWith();
    // The crux: a null success body never throws and never leaks. The optional-
    // chained property reads (result?.stub / result?.status / would_run) on a
    // null body all short-circuit, so the would-run pre is absent and the honest
    // enqueued line is shown — a legible degrade, not a blank page or a crash.
    expect(screen.queryByTestId("spawn-topic-error")).toBeNull();
    expect(screen.queryByTestId("spawn-topic-wouldrun")).toBeNull();
    const result = screen.queryByTestId("spawn-topic-result");
    if (result !== null) {
      expect(result.textContent ?? "").not.toMatch(/\[object Object\]|NaN|undefined/);
    }
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("a primitive (string) body does not crash and shows no would-run pre", async () => {
    const { errSpy, warnSpy } = spyConsole();
    stubFetch((u) =>
      u.endsWith("/api/todo/spawn_topic")
        ? jsonResponse(200, "ok" as unknown)
        : undefined,
    );
    render(<SpawnTopicForm findingId="finding-001" available={true} />);
    fireEvent.change(screen.getByLabelText(/new topic/i), {
      target: { value: "anchor coverage" },
    });
    fireEvent.click(screen.getByRole("button", { name: /spawn topic/i }));
    await waitFor(() =>
      expect(screen.getByTestId("spawn-topic-result")).toBeInTheDocument(),
    );
    // A primitive has no .stub/.status/.would_run → enqueued line, no pre, no leak.
    const result = screen.getByTestId("spawn-topic-result");
    expect(screen.queryByTestId("spawn-topic-wouldrun")).toBeNull();
    expect(result.textContent ?? "").not.toMatch(/\[object Object\]|NaN|undefined/);
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("a bare-array body renders the enqueued branch with no would-run pre and no crash", async () => {
    const { errSpy, warnSpy } = spyConsole();
    stubFetch((u) =>
      u.endsWith("/api/todo/spawn_topic")
        ? jsonResponse(200, ["loose", "array"] as unknown)
        : undefined,
    );
    render(<SpawnTopicForm findingId="finding-001" available={true} />);
    fireEvent.change(screen.getByLabelText(/new topic/i), {
      target: { value: "anchor coverage" },
    });
    fireEvent.click(screen.getByRole("button", { name: /spawn topic/i }));
    await waitFor(() =>
      expect(screen.getByTestId("spawn-topic-result")).toBeInTheDocument(),
    );
    // result is an array → result.would_run is undefined → no pre; the enqueued
    // label (array is not stub) renders, no [object Object] leak.
    expect(screen.queryByTestId("spawn-topic-wouldrun")).toBeNull();
    expect(
      (screen.getByTestId("spawn-topic-result").textContent ?? ""),
    ).not.toMatch(/\[object Object\]/);
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("a malformed would_run (objects/null/NaN among strings) drops the non-scalar tokens, no [object Object]/NaN", async () => {
    const { errSpy, warnSpy } = spyConsole();
    stubFetch((u) =>
      u.endsWith("/api/todo/spawn_topic")
        ? jsonResponse(200, {
            stub: true,
            status: "stub",
            would_run: [
              "--ref-id",
              "finding-001",
              { malformed: "object-token" },
              null,
              Number.NaN,
              Number.POSITIVE_INFINITY,
              42,
              ["nested", "array"],
              "--kind",
              "finding",
            ],
          })
        : undefined,
    );
    render(<SpawnTopicForm findingId="finding-001" available={true} />);
    fireEvent.change(screen.getByLabelText(/new topic/i), {
      target: { value: "anchor coverage" },
    });
    fireEvent.click(screen.getByRole("button", { name: /spawn topic/i }));
    await waitFor(() =>
      expect(screen.getByTestId("spawn-topic-wouldrun")).toBeInTheDocument(),
    );
    const pre = screen.getByTestId("spawn-topic-wouldrun");
    const txt = pre.textContent ?? "";
    // Scalar tokens survive; object/array/null/non-finite are dropped.
    expect(txt).toContain("--ref-id");
    expect(txt).toContain("finding-001");
    expect(txt).toContain("42");
    expect(txt).not.toMatch(/\[object Object\]/);
    expect(txt).not.toMatch(/NaN/);
    expect(txt).not.toMatch(/Infinity/);
    expect(txt).not.toMatch(/null/);
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("a would_run that is the WRONG type (string, not array) shows no pre and does not crash", async () => {
    const { errSpy, warnSpy } = spyConsole();
    stubFetch((u) =>
      u.endsWith("/api/todo/spawn_topic")
        ? jsonResponse(200, {
            stub: true,
            status: "stub",
            would_run: "not-an-array",
          })
        : undefined,
    );
    render(<SpawnTopicForm findingId="finding-001" available={true} />);
    fireEvent.change(screen.getByLabelText(/new topic/i), {
      target: { value: "anchor coverage" },
    });
    fireEvent.click(screen.getByRole("button", { name: /spawn topic/i }));
    await waitFor(() =>
      expect(screen.getByTestId("spawn-topic-result")).toBeInTheDocument(),
    );
    // Array.isArray guard → no pre; the stub line still renders.
    expect(screen.queryByTestId("spawn-topic-wouldrun")).toBeNull();
    expect(screen.getByTestId("spawn-topic-result")).toHaveTextContent(/stub response/i);
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });
});

// ===========================================================================
// adversarial-verify — deeper would_run / findingId derefs (skeptic pass)
// ===========================================================================
// These push PAST the shallow guards: an element whose String() conversion
// would THROW (a throwing toString getter), an array where EVERY element is
// non-scalar (the filter returns ""), and a boxed `new String(...)` id (typeof
// "object", not the primitive). A producer can't literally emit a throwing
// getter from disk JSON, but the test proves the filter's design — it only
// `typeof`-checks and NEVER String()-converts a token it is about to drop, so a
// hostile element is shed before any deref can run.
describe("SpawnTopicForm adversarial — deeper would_run / id derefs", () => {
  it("a would_run element whose toString getter THROWS is dropped before String() — no crash", async () => {
    const { errSpy, warnSpy } = spyConsole();
    // typeof evil === "object" → the type-guard rejects it → .map(String) never
    // touches it → the throwing getter is never invoked. If the filter had
    // String()-mapped unconditionally (the pre-harden `.map(String)`), this would
    // throw "boom getter" inside render and blank the result block.
    const evil: Record<string, unknown> = {};
    Object.defineProperty(evil, "toString", {
      get() {
        throw new Error("boom getter");
      },
    });
    stubFetch((u) =>
      u.endsWith("/api/todo/spawn_topic")
        ? jsonResponse(200, {
            stub: true,
            would_run: ["--ref-id", evil, "finding-001"],
          })
        : undefined,
    );
    render(<SpawnTopicForm findingId="finding-001" available={true} />);
    fireEvent.change(screen.getByLabelText(/new topic/i), {
      target: { value: "anchor coverage" },
    });
    fireEvent.click(screen.getByRole("button", { name: /spawn topic/i }));
    await waitFor(() =>
      expect(screen.getByTestId("spawn-topic-wouldrun")).toBeInTheDocument(),
    );
    const txt = screen.getByTestId("spawn-topic-wouldrun").textContent ?? "";
    expect(txt).toContain("--ref-id");
    expect(txt).toContain("finding-001");
    expect(txt).not.toMatch(/\[object Object\]|boom/);
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("a would_run where EVERY element is non-scalar degrades to an empty preview (no crash, no leak)", async () => {
    const { errSpy, warnSpy } = spyConsole();
    stubFetch((u) =>
      u.endsWith("/api/todo/spawn_topic")
        ? jsonResponse(200, {
            stub: true,
            status: "stub",
            would_run: [{}, null, ["nested"], Number.NaN, Number.POSITIVE_INFINITY],
          })
        : undefined,
    );
    render(<SpawnTopicForm findingId="finding-001" available={true} />);
    fireEvent.change(screen.getByLabelText(/new topic/i), {
      target: { value: "anchor coverage" },
    });
    fireEvent.click(screen.getByRole("button", { name: /spawn topic/i }));
    await waitFor(() =>
      expect(screen.getByTestId("spawn-topic-wouldrun")).toBeInTheDocument(),
    );
    // Every token is dropped → empty string, not "[object Object] null NaN ...".
    // The honest-stub line still reads, so the box is empty-but-legible.
    expect(screen.getByTestId("spawn-topic-wouldrun").textContent ?? "").toBe("");
    expect(screen.getByTestId("spawn-topic-result")).toHaveTextContent(/stub response/i);
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("a boxed `new String(id)` findingId (typeof object) degrades to the placeholder, never leaks the wrapper", () => {
    const { errSpy, warnSpy } = spyConsole();
    stubFetch(() => undefined);
    // `new String("real-id")` is typeof "object" — a primitive-string check
    // (=== the house idiom) sheds it to "" rather than rendering the boxed value.
    render(
      <SpawnTopicForm
        findingId={new String("real-id") as unknown as string}
        available={true}
      />,
    );
    const argv = screen.getByTestId("spawn-topic-argv").textContent ?? "";
    expect(argv).toMatch(/--ref-id <finding_id>/);
    expect(argv).not.toMatch(/real-id|\[object/);
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });
});

// ===========================================================================
// transport edges — 404 version-skew + 502 {rc,stderr}
// ===========================================================================
describe("SpawnTopicForm hardening — transport edges", () => {
  it("a 404 (version-skew: backend predates /api/todo/spawn_topic) shows a legible error, not a blank/throw", async () => {
    const { errSpy, warnSpy } = spyConsole();
    stubFetch((u) =>
      u.endsWith("/api/todo/spawn_topic")
        ? jsonResponse(404, { detail: "Not Found" })
        : undefined,
    );
    render(<SpawnTopicForm findingId="finding-001" available={true} />);
    fireEvent.change(screen.getByLabelText(/new topic/i), {
      target: { value: "anchor coverage" },
    });
    fireEvent.click(screen.getByRole("button", { name: /spawn topic/i }));
    await waitFor(() =>
      expect(screen.getByTestId("spawn-topic-error")).toBeInTheDocument(),
    );
    // The form is still mounted (not blanked) and shows the error legibly.
    expect(screen.getByTestId("spawn-topic-form")).toBeInTheDocument();
    expect(screen.getByTestId("spawn-topic-error").textContent ?? "").toMatch(
      /404|Not Found/,
    );
    // jsdom console.error spy: a thrown render or unhandled rejection would trip
    // it; the handled error path must not.
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("a 404 with NO JSON body still degrades to a legible error (no crash)", async () => {
    stubFetch((u) =>
      u.endsWith("/api/todo/spawn_topic")
        ? ({
            ok: false,
            status: 404,
            statusText: "Not Found",
            json: async () => {
              throw new Error("no body");
            },
          } as unknown as Response)
        : undefined,
    );
    render(<SpawnTopicForm findingId="finding-001" available={true} />);
    fireEvent.change(screen.getByLabelText(/new topic/i), {
      target: { value: "anchor coverage" },
    });
    fireEvent.click(screen.getByRole("button", { name: /spawn topic/i }));
    await waitFor(() =>
      expect(screen.getByTestId("spawn-topic-error")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("spawn-topic-error").textContent ?? "").toMatch(
      /404/,
    );
  });

  it("a 502 {rc, stderr} renders the CLI stderr VERBATIM (no summarization, no crash)", async () => {
    stubFetch((u) =>
      u.endsWith("/api/todo/spawn_topic")
        ? jsonResponse(502, {
            rc: 2,
            stderr: "error: finding_followups seam not yet blessed",
          })
        : undefined,
    );
    render(<SpawnTopicForm findingId="finding-001" available={true} />);
    fireEvent.change(screen.getByLabelText(/new topic/i), {
      target: { value: "anchor coverage" },
    });
    fireEvent.click(screen.getByRole("button", { name: /spawn topic/i }));
    await waitFor(() =>
      expect(screen.getByTestId("spawn-topic-stderr")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("spawn-topic-stderr")).toHaveTextContent(
      "error: finding_followups seam not yet blessed",
    );
  });

  it("a 502 with a non-string stderr does not crash and falls back to the plain error banner", async () => {
    const { errSpy } = spyConsole();
    stubFetch((u) =>
      u.endsWith("/api/todo/spawn_topic")
        ? jsonResponse(502, { rc: "two", stderr: { nested: "obj" } })
        : undefined,
    );
    render(<SpawnTopicForm findingId="finding-001" available={true} />);
    fireEvent.change(screen.getByLabelText(/new topic/i), {
      target: { value: "anchor coverage" },
    });
    fireEvent.click(screen.getByRole("button", { name: /spawn topic/i }));
    // stderr is not a string → TodoError.stderr is null → plain error banner, not
    // the verbatim-stderr pre; no [object Object] from a coerced object stderr.
    await waitFor(() =>
      expect(screen.getByTestId("spawn-topic-error")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("spawn-topic-stderr")).toBeNull();
    expect(
      (screen.getByTestId("spawn-topic-error").textContent ?? ""),
    ).not.toMatch(/\[object Object\]/);
    expect(errSpy).not.toHaveBeenCalled();
  });
});

// ===========================================================================
// oversize / unicode / leading-dash topic (the argv preview robustness)
// ===========================================================================
describe("SpawnTopicForm hardening — oversize / unicode / leading-dash topic", () => {
  it("a leading-dash topic is JSON-quoted in the argv (not mistaken for a flag), no crash", () => {
    const { errSpy, warnSpy } = spyConsole();
    stubFetch(() => undefined);
    render(<SpawnTopicForm findingId="finding-001" available={true} />);
    fireEvent.change(screen.getByLabelText(/new topic/i), {
      target: { value: "--rm -rf inject" },
    });
    const argv = screen.getByTestId("spawn-topic-argv");
    // JSON.stringify quotes it, so it cannot read as an argv flag in the preview.
    expect(argv).toHaveTextContent(/--topic "--rm -rf inject"/);
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("an oversize unicode topic renders without breaking layout or a console error", () => {
    const { errSpy, warnSpy } = spyConsole();
    stubFetch(() => undefined);
    const big = "πβ-truthfulness ≈ Nagel(1995) ✦ ".repeat(400);
    render(<SpawnTopicForm findingId="finding-001" available={true} />);
    expect(() =>
      fireEvent.change(screen.getByLabelText(/new topic/i), {
        target: { value: big },
      }),
    ).not.toThrow();
    expect(screen.getByTestId("spawn-topic-form")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /spawn topic/i })).not.toBeDisabled();
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("a whitespace-only topic keeps submit disabled (trim guard, behavior preserved)", () => {
    stubFetch(() => undefined);
    render(<SpawnTopicForm findingId="finding-001" available={true} />);
    fireEvent.change(screen.getByLabelText(/new topic/i), {
      target: { value: "    " },
    });
    expect(screen.getByRole("button", { name: /spawn topic/i })).toBeDisabled();
    // and the argv shows the "<new_topic>" placeholder, not blank quotes.
    expect(screen.getByTestId("spawn-topic-argv")).toHaveTextContent(/--topic <new_topic>/);
  });
});
