// Edge-case hardening for AuthorizeFixForm (outcome 4 — gated spawn-contract
// enqueue stub). House robustness doctrine: the props (findingId from a
// producer-owned finding row, `available` from the cockpit capability handshake)
// and the POST response body are UNVALIDATED. A malformed/legacy/partial value
// must DEGRADE to a legible fallback — never blank the page or throw, and never
// fake a write/verdict (inviolate rule 4) or light up the gated form on a
// truthy-but-not-true flag.
//
// The component pre-existing contract test (test_cockpit_resolution_forms.tsx)
// pins VALID-input behavior; this file pins the INVALID/edge degrades. The
// no-headless-browser "renders clean" stand-in is the same idiom used across the
// other test_harden_*.tsx files: a jsdom render + a console.error/warn spy
// asserted not-called (a render-time throw or an act()/key warning lands on
// console.error in jsdom).
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import AuthorizeFixForm from "../src/components/todo/AuthorizeFixForm";

function spyConsole() {
  const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  return { errSpy, warnSpy };
}

// --- fetch stub (mirrors test_cockpit_resolution_forms.tsx) ---
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

function stubFetchReturning(body: unknown, status = 200): RecordedCall[] {
  const calls: RecordedCall[] = [];
  vi.stubGlobal("fetch", async (url: unknown, init?: RequestInit) => {
    calls.push({
      url: String(url),
      method: init?.method ?? "GET",
      body:
        typeof init?.body === "string"
          ? (JSON.parse(init.body) as Record<string, unknown>)
          : null,
    });
    return jsonResponse(status, body);
  });
  return calls;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

// =========================================================================
// 1. `available` prop coercion — only `=== true` may light up the gated form
// =========================================================================
describe("AuthorizeFixForm — `available` coerced strictly (=== true)", () => {
  // A non-boolean truthy flag (string "false", 1, {}, []) must NOT be treated as
  // available: the gated form stays in its honest stub state and submit disabled.
  const truthyButNotTrue: unknown[] = ["false", "true", 1, {}, [], "yes"];

  for (const v of truthyButNotTrue) {
    it(`stays stubbed + submit disabled for available=${JSON.stringify(v)}`, () => {
      const { errSpy } = spyConsole();
      // @ts-expect-error — feeding a deliberately malformed prop
      render(<AuthorizeFixForm findingId="finding-001" available={v} />);
      // Honest stub copy shows (the !isAvailable branch).
      expect(screen.getByTestId("authorize-fix-stub")).toBeInTheDocument();
      // Even with task + note filled, the gate keeps submit disabled.
      fireEvent.change(screen.getByLabelText(/authorize-fix task/i), {
        target: { value: "do the thing" },
      });
      fireEvent.change(screen.getByLabelText(/authorize-fix note/i), {
        target: { value: "because" },
      });
      expect(screen.getByRole("button", { name: /authorize fix/i })).toBeDisabled();
      expect(errSpy).not.toHaveBeenCalled();
    });
  }

  for (const v of [null, undefined, 0, "", NaN, false]) {
    it(`stays stubbed for falsy available=${JSON.stringify(v)}`, () => {
      // @ts-expect-error — deliberately malformed prop
      render(<AuthorizeFixForm findingId="finding-001" available={v} />);
      expect(screen.getByTestId("authorize-fix-stub")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /authorize fix/i })).toBeDisabled();
    });
  }

  it("VALID available={true} still enables submit once task+note set (no regression)", () => {
    render(<AuthorizeFixForm findingId="finding-001" available={true} />);
    expect(screen.queryByTestId("authorize-fix-stub")).not.toBeInTheDocument();
    const button = screen.getByRole("button", { name: /authorize fix/i });
    expect(button).toBeDisabled(); // empty fields
    fireEvent.change(screen.getByLabelText(/authorize-fix task/i), {
      target: { value: "patch the gate" },
    });
    fireEvent.change(screen.getByLabelText(/authorize-fix note/i), {
      target: { value: "fixes the over-gate" },
    });
    expect(button).toBeEnabled();
  });
});

// =========================================================================
// 2. `findingId` coercion — a non-string id degrades to the placeholder, never
//    leaks [object Object] / a comma-joined array into the argv OR the POST body
// =========================================================================
describe("AuthorizeFixForm — non-string findingId degrades to placeholder", () => {
  const malformed: Array<[string, unknown]> = [
    ["null", null],
    ["undefined", undefined],
    ["number", 42],
    ["object", { id: "x" }],
    ["array", ["a", "b"]],
    ["NaN", NaN],
    ["boolean", true],
  ];

  for (const [label, v] of malformed) {
    it(`argv shows <finding_id> placeholder (not garbled) for findingId=${label}`, () => {
      const { errSpy } = spyConsole();
      // @ts-expect-error — deliberately malformed prop
      render(<AuthorizeFixForm findingId={v} available={true} />);
      const argv = screen.getByTestId("authorize-fix-argv");
      expect(argv).toHaveTextContent(/--ref-id <finding_id>/);
      // The garble shapes that the pre-guard code would have leaked:
      expect(argv.textContent ?? "").not.toContain("[object Object]");
      expect(argv.textContent ?? "").not.toContain("--ref-id 42");
      expect(argv.textContent ?? "").not.toContain("--ref-id a,b");
      expect(errSpy).not.toHaveBeenCalled();
    });
  }

  it("non-string findingId is sent as an empty string (not raw) in the POST body", async () => {
    const calls = stubFetchReturning({ stub: true, status: "stub", would_run: ["x"] });
    // @ts-expect-error — deliberately malformed prop
    render(<AuthorizeFixForm findingId={{ id: "leak" }} available={true} />);
    fireEvent.change(screen.getByLabelText(/authorize-fix task/i), {
      target: { value: "task" },
    });
    fireEvent.change(screen.getByLabelText(/authorize-fix note/i), {
      target: { value: "note" },
    });
    fireEvent.click(screen.getByRole("button", { name: /authorize fix/i }));
    await waitFor(() =>
      expect(screen.getByTestId("authorize-fix-result")).toBeInTheDocument(),
    );
    const post = calls.find((c) => c.url.endsWith("/api/todo/authorize_fix"));
    expect(post).toBeDefined();
    // ref_id must be a STRING, never the object — no [object Object] leaks
    // through into the (eventual) CLI argv.
    expect(typeof post?.body?.ref_id).toBe("string");
    expect(post?.body?.ref_id).toBe("");
  });

  it("VALID string findingId still flows verbatim into argv + POST (no regression)", async () => {
    const calls = stubFetchReturning({ stub: true, status: "stub", would_run: ["x"] });
    render(<AuthorizeFixForm findingId="finding-xyz" available={true} />);
    expect(screen.getByTestId("authorize-fix-argv")).toHaveTextContent(
      /--ref-id finding-xyz/,
    );
    fireEvent.change(screen.getByLabelText(/authorize-fix task/i), {
      target: { value: "t" },
    });
    fireEvent.change(screen.getByLabelText(/authorize-fix note/i), {
      target: { value: "n" },
    });
    fireEvent.click(screen.getByRole("button", { name: /authorize fix/i }));
    await waitFor(() =>
      expect(screen.getByTestId("authorize-fix-result")).toBeInTheDocument(),
    );
    const post = calls.find((c) => c.url.endsWith("/api/todo/authorize_fix"));
    expect(post?.body?.ref_id).toBe("finding-xyz");
  });

  it("unicode / leading-dash findingId is preserved verbatim (a string is a string)", () => {
    render(<AuthorizeFixForm findingId={"--rm-rf 𝔘𝔫𝔦"} available={true} />);
    expect(screen.getByTestId("authorize-fix-argv")).toHaveTextContent(
      /--ref-id --rm-rf 𝔘𝔫𝔦/,
    );
  });
});

// =========================================================================
// 3. Malformed POST response body — degrade legibly, never throw / blank
// =========================================================================
describe("AuthorizeFixForm — malformed success body degrades, never crashes", () => {
  async function submitWith(body: unknown) {
    const { errSpy } = spyConsole();
    stubFetchReturning(body);
    render(<AuthorizeFixForm findingId="f1" available={true} />);
    fireEvent.change(screen.getByLabelText(/authorize-fix task/i), {
      target: { value: "t" },
    });
    fireEvent.change(screen.getByLabelText(/authorize-fix note/i), {
      target: { value: "n" },
    });
    fireEvent.click(screen.getByRole("button", { name: /authorize fix/i }));
    return errSpy;
  }

  it("null body → degrades to enqueued copy, no would_run block, no crash", async () => {
    const errSpy = await submitWith(null);
    // A null JSON body must not throw or blank the surface. The component
    // degrades to the honest "enqueued" branch with no would_run block (a null
    // result has no `.would_run` array, so Array.isArray suppresses it).
    await waitFor(() =>
      expect(screen.getByTestId("authorize-fix-form")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("authorize-fix-wouldrun")).not.toBeInTheDocument();
    expect(errSpy).not.toHaveBeenCalled();
  });

  it("bare-string body → 'enqueued' degrade (no stub/would_run access throws)", async () => {
    const errSpy = await submitWith("just a string");
    await waitFor(() =>
      expect(screen.getByTestId("authorize-fix-result")).toBeInTheDocument(),
    );
    // No `would_run` array → no wouldrun block; component never throws on .stub.
    expect(screen.queryByTestId("authorize-fix-wouldrun")).not.toBeInTheDocument();
    expect(errSpy).not.toHaveBeenCalled();
  });

  it("array body → renders, no crash, no would_run block", async () => {
    const errSpy = await submitWith(["a", "b"]);
    await waitFor(() =>
      expect(screen.getByTestId("authorize-fix-result")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("authorize-fix-wouldrun")).not.toBeInTheDocument();
    expect(errSpy).not.toHaveBeenCalled();
  });

  it("would_run present but NOT an array → block suppressed (Array.isArray guard)", async () => {
    const errSpy = await submitWith({ status: "stub", would_run: "ls -la" });
    await waitFor(() =>
      expect(screen.getByTestId("authorize-fix-result")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("authorize-fix-wouldrun")).not.toBeInTheDocument();
    expect(errSpy).not.toHaveBeenCalled();
  });

  it("would_run array with non-string entries (object/number/null) renders legibly", async () => {
    const errSpy = await submitWith({
      status: "stub",
      would_run: ["python", 42, { a: 1 }, null, NaN],
    });
    await waitFor(() =>
      expect(screen.getByTestId("authorize-fix-wouldrun")).toBeInTheDocument(),
    );
    // map(String) coerces each entry — no throw, a legible (if ugly) line.
    expect(screen.getByTestId("authorize-fix-wouldrun").textContent ?? "").toContain(
      "python",
    );
    expect(errSpy).not.toHaveBeenCalled();
  });

  it("stub flagged via stub:true (not status) still reads as 'nothing written'", async () => {
    await submitWith({ stub: true, would_run: ["python", "-m", "x"] });
    await waitFor(() =>
      expect(screen.getByTestId("authorize-fix-result")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("authorize-fix-result")).toHaveTextContent(
      /nothing written/i,
    );
  });

  it("missing stub/status keys → honest 'enqueued' copy, never a faked stub", async () => {
    await submitWith({ would_run: ["python"] });
    await waitFor(() =>
      expect(screen.getByTestId("authorize-fix-result")).toBeInTheDocument(),
    );
    // Inviolate rule 4: a body that does NOT mark itself a stub must not be
    // re-labelled "nothing written"; it reads as the enqueued branch.
    expect(screen.getByTestId("authorize-fix-result")).toHaveTextContent(
      /spawn-contract enqueued/i,
    );
  });
});

// =========================================================================
// 4. Error paths — version-skew 404 + malformed error envelopes
// =========================================================================
describe("AuthorizeFixForm — error envelopes degrade legibly", () => {
  async function submitExpectingError() {
    render(<AuthorizeFixForm findingId="f1" available={true} />);
    fireEvent.change(screen.getByLabelText(/authorize-fix task/i), {
      target: { value: "t" },
    });
    fireEvent.change(screen.getByLabelText(/authorize-fix note/i), {
      target: { value: "n" },
    });
    fireEvent.click(screen.getByRole("button", { name: /authorize fix/i }));
  }

  it("version-skew 404 → plain error message, no stderr block, no crash", async () => {
    const { errSpy } = spyConsole();
    stubFetchReturning(null, 404);
    await submitExpectingError();
    await waitFor(() =>
      expect(screen.getByTestId("authorize-fix-error")).toBeInTheDocument(),
    );
    // 404 carries no {rc, stderr} → falls to the plain-error branch, not the
    // stderr-verbatim block.
    expect(screen.queryByTestId("authorize-fix-stderr")).not.toBeInTheDocument();
    expect(errSpy).not.toHaveBeenCalled();
  });

  it("502 {rc, stderr} → stderr rendered VERBATIM (rule 4 — un-summarized)", async () => {
    stubFetchReturning({ rc: 2, stderr: "Traceback: boom\n  line 9" }, 502);
    await submitExpectingError();
    await waitFor(() =>
      expect(screen.getByTestId("authorize-fix-stderr")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("authorize-fix-stderr")).toHaveTextContent(
      "Traceback: boom",
    );
  });

  it("502 with non-string stderr / non-number rc → plain error, no crash", async () => {
    const { errSpy } = spyConsole();
    stubFetchReturning({ rc: "two", stderr: { msg: "obj" } }, 502);
    await submitExpectingError();
    await waitFor(() =>
      expect(screen.getByTestId("authorize-fix-error")).toBeInTheDocument(),
    );
    // stderr is not a string → TodoError.stderr is null → plain error branch.
    expect(screen.queryByTestId("authorize-fix-stderr")).not.toBeInTheDocument();
    expect(errSpy).not.toHaveBeenCalled();
  });
});

// =========================================================================
// 5. ADVERSARIAL-VERIFY (skeptic pass) — the nastiest realistic edges the
//    harden pass did NOT pin. These probe values that slip past a SHALLOW
//    truthy/typeof guard or throw on a DEEPER deref. The component already
//    SURVIVES all of these (the `=== true` + `safeFindingId` + map(String)
//    idioms hold); these are durable regressions so a future "simplification"
//    back to truthy coercion is caught.
// =========================================================================
describe("AuthorizeFixForm — adversarial edges (skeptic regressions)", () => {
  // The single nastiest `available` value: `new Boolean(false)` is an OBJECT,
  // so it is TRUTHY in JS (`!!new Boolean(false) === true`) even though it
  // boxes `false`. A `!available` / truthy guard would have LIT UP the gated
  // spawn-contract enqueue form on a flag that means "not available" — the
  // exact rule-4 violation the strict `=== true` coercion exists to prevent.
  it("boxed Boolean(false) available (truthy object!) stays STUBBED, submit disabled", () => {
    const { errSpy } = spyConsole();
    // @ts-expect-error — a producer/handshake could hand back a boxed Boolean
    render(<AuthorizeFixForm findingId="finding-001" available={new Boolean(false)} />);
    expect(screen.getByTestId("authorize-fix-stub")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/authorize-fix task/i), {
      target: { value: "do the thing" },
    });
    fireEvent.change(screen.getByLabelText(/authorize-fix note/i), {
      target: { value: "because" },
    });
    expect(screen.getByRole("button", { name: /authorize fix/i })).toBeDisabled();
    expect(errSpy).not.toHaveBeenCalled();
  });

  // A `new String("x")` is `typeof === "object"`, so safeFindingId degrades it
  // to the placeholder rather than leaking the boxed wrapper's `.toString()`.
  it("boxed String findingId (typeof object) degrades to <finding_id> placeholder", () => {
    const { errSpy } = spyConsole();
    // @ts-expect-error — boxed String slips past a naive `typeof !== object` check differently
    render(<AuthorizeFixForm findingId={new String("boxed")} available={true} />);
    expect(screen.getByTestId("authorize-fix-argv")).toHaveTextContent(
      /--ref-id <finding_id>/,
    );
    expect(errSpy).not.toHaveBeenCalled();
  });

  // would_run entries that are nested arrays / nested objects / a 100k-char
  // string — the would_run render does `(...).map(String)`. map(String) on
  // JSON-sourced values can never throw (no Symbols / no throwing toString
  // survive JSON.parse), so it must produce a legible (if ugly) line.
  it("would_run with nested-array / nested-object / oversize-string entries renders, no crash", async () => {
    const { errSpy } = spyConsole();
    stubFetchReturning({
      status: "stub",
      would_run: [["nested", "deep"], { a: { b: 1 } }, "x".repeat(100000)],
    });
    render(<AuthorizeFixForm findingId="f1" available={true} />);
    fireEvent.change(screen.getByLabelText(/authorize-fix task/i), {
      target: { value: "t" },
    });
    fireEvent.change(screen.getByLabelText(/authorize-fix note/i), {
      target: { value: "n" },
    });
    fireEvent.click(screen.getByRole("button", { name: /authorize fix/i }));
    await waitFor(() =>
      expect(screen.getByTestId("authorize-fix-wouldrun")).toBeInTheDocument(),
    );
    // nested array → "nested,deep"; nested object → "[object Object]" (ugly but
    // legible); neither throws.
    expect(screen.getByTestId("authorize-fix-wouldrun").textContent ?? "").toContain(
      "nested,deep",
    );
    expect(errSpy).not.toHaveBeenCalled();
  });

  // prop↔callback race: onSubmitted throws AFTER setResult. The throw is caught
  // by submit()'s try/catch (it wraps non-Errors too), the result stays set,
  // and the surface degrades to the plain-error branch — never an unhandled
  // render-phase crash that blanks the cockpit.
  it("onSubmitted callback that throws is caught — result stays, error shown, no blank", async () => {
    stubFetchReturning({ status: "stub", would_run: ["x"] });
    render(
      <AuthorizeFixForm
        findingId="f1"
        available={true}
        onSubmitted={() => {
          throw new Error("boom-cb");
        }}
      />,
    );
    fireEvent.change(screen.getByLabelText(/authorize-fix task/i), {
      target: { value: "t" },
    });
    fireEvent.change(screen.getByLabelText(/authorize-fix note/i), {
      target: { value: "n" },
    });
    fireEvent.click(screen.getByRole("button", { name: /authorize fix/i }));
    await waitFor(() =>
      expect(screen.getByTestId("authorize-fix-error")).toBeInTheDocument(),
    );
    // The success result was committed before the callback threw, and the
    // callback's error degrades to the plain-error branch — the form is intact.
    expect(screen.getByTestId("authorize-fix-form")).toBeInTheDocument();
    expect(screen.getByTestId("authorize-fix-result")).toBeInTheDocument();
    expect(screen.getByTestId("authorize-fix-error")).toHaveTextContent(/boom-cb/);
  });

  // findingId === 0 (a number): not the falsy-string "" trap. safeFindingId
  // coerces a number to "" → placeholder, and the argv `|| "<finding_id>"`
  // path is reached via the empty string, not via a number-0 falsy slip.
  it("numeric findingId 0 degrades to placeholder (no number falsy-trap)", () => {
    // @ts-expect-error — a producer row id could arrive as a raw number
    render(<AuthorizeFixForm findingId={0} available={true} />);
    expect(screen.getByTestId("authorize-fix-argv")).toHaveTextContent(
      /--ref-id <finding_id>/,
    );
  });
});
