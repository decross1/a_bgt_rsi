// Adversarial hardening for AbstainForm (outcome 6 — the honest no-verdict exit).
//
// AbstainForm consumes producer-owned values that the HOUSE ROBUSTNESS DOCTRINE
// treats as UNVALIDATED:
//   - props `findingId` (string) and `available` (boolean) thread up from
//     /api/todo/available + loop_memory rows — their compile-time types are a
//     fiction; a legacy/partial row can put a number/object/array/null there.
//   - `result`, the POST body, is forwarded RAW by postTodo (`await resp.json()`
//     cast to a Record). A malformed 200 body can be a bare null/number/string/
//     array, NOT the documented {stub, would_run} object.
//
// Each malformed input must DEGRADE legibly (the form still renders, the would-run
// preview still shows, submit stays correctly gated), NEVER blank the surface,
// throw, or — critically (inviolate rule 4) — fabricate an "abstention recorded"
// verdict from a body that carries no such semantics.
//
// The happy-path contract lives in test_cockpit_resolution_forms.tsx; this file is
// the malformed-input regression only. Each `it` pins one guard added to the
// component.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import AbstainForm from "../src/components/todo/AbstainForm";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

// Cast helper — these values are illegal per the prop types but legal in the
// producer-owned JSON the runtime actually sees.
const bad = (v: unknown) => v as never;

// A fetch stub routing by URL suffix, recording bodies. Mirrors the existing
// cockpit form tests' idiom.
function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: String(status),
    json: async () => body,
  } as unknown as Response;
}

interface RecordedCall {
  url: string;
  body: Record<string, unknown> | null;
}

function stubFetch(resp: (url: string) => Response): RecordedCall[] {
  const calls: RecordedCall[] = [];
  vi.stubGlobal("fetch", async (url: unknown, init?: RequestInit) => {
    const u = String(url);
    calls.push({
      url: u,
      body:
        typeof init?.body === "string"
          ? (JSON.parse(init.body) as Record<string, unknown>)
          : null,
    });
    return resp(u);
  });
  return calls;
}

describe("AbstainForm hardening — malformed props never crash or blank the surface", () => {
  it("renders clean with a NON-STRING findingId (number / object / array / null), no React error", () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    for (const v of [42, 0, Number.NaN, Infinity, { id: "x" }, ["finding-1"], null, undefined, true]) {
      const { unmount } = render(<AbstainForm findingId={bad(v)} available={true} />);
      // The form still mounts and the semantics copy is intact.
      expect(screen.getByTestId("abstain-form")).toBeInTheDocument();
      expect(screen.getByTestId("abstain-semantics")).toHaveTextContent(/No verdict is recorded/i);
      // No garbage stringification leaked into the would-run preview.
      const argv = screen.getByTestId("abstain-argv");
      expect(argv.textContent ?? "").not.toContain("[object Object]");
      expect(argv.textContent ?? "").not.toMatch(/NaN|Infinity/);
      unmount();
    }
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("a non-string findingId degrades the argv preview to the <finding_id> placeholder", () => {
    // The crash/garbage repro: before asFindingId, `findingId || "<finding_id>"`
    // let an object through and interpolated "[object Object]"; a number that was
    // truthy interpolated a raw number. Now any non-string falls to the placeholder.
    for (const v of [{ id: "x" }, ["a"], 7, true]) {
      const { unmount } = render(<AbstainForm findingId={bad(v)} available={true} />);
      expect(screen.getByTestId("abstain-argv")).toHaveTextContent("--ref-id <finding_id>");
      unmount();
    }
  });

  it("a valid string findingId is preserved verbatim in the argv preview (behavior unchanged)", () => {
    render(<AbstainForm findingId="finding-042" available={true} />);
    expect(screen.getByTestId("abstain-argv")).toHaveTextContent("--ref-id finding-042");
  });

  it("coerces `available` STRICTLY (=== true): a truthy non-true value stays in the stub state", () => {
    // A legacy availability value like the STRING "true" or the number 1 is truthy
    // but is NOT the boolean true. Strict coercion keeps submit disabled + the stub
    // notice visible, mirroring asAvailability in api/todo.ts.
    for (const v of ["true", 1, {}, ["abstain"]]) {
      const { unmount } = render(<AbstainForm findingId="finding-1" available={bad(v)} />);
      // Stub notice shows (means !isAvailable held).
      expect(screen.getByTestId("abstain-stub")).toBeInTheDocument();
      // Submit stays disabled even with a note present.
      fireEvent.change(screen.getByLabelText(/abstain note/i), { target: { value: "revisit" } });
      expect(screen.getByRole("button", { name: /^abstain$/i })).toBeDisabled();
      unmount();
    }
  });

  it("available={false} keeps stub + disabled; available={true} + note enables (valid behavior unchanged)", () => {
    const { rerender } = render(<AbstainForm findingId="finding-1" available={false} />);
    expect(screen.getByTestId("abstain-stub")).toBeInTheDocument();
    rerender(<AbstainForm findingId="finding-1" available={true} />);
    expect(screen.queryByTestId("abstain-stub")).toBeNull();
    expect(screen.getByRole("button", { name: /^abstain$/i })).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/abstain note/i), { target: { value: "revisit after R0 fix" } });
    expect(screen.getByRole("button", { name: /^abstain$/i })).not.toBeDisabled();
  });
});

describe("AbstainForm hardening — malformed POST result body degrades honestly", () => {
  const postAndRead = async (body: unknown) => {
    stubFetch(() => jsonResponse(200, body));
    render(<AbstainForm findingId="finding-1" available={true} />);
    fireEvent.change(screen.getByLabelText(/abstain note/i), { target: { value: "revisit" } });
    fireEvent.click(screen.getByRole("button", { name: /^abstain$/i }));
    await waitFor(() => expect(screen.getByTestId("abstain-result")).toBeInTheDocument());
    return screen.getByTestId("abstain-result");
  };

  it("a NON-OBJECT 200 body (number / string / array / bool) degrades WITHOUT crashing or leaking garbage", async () => {
    // Defense-in-depth: the api/todo.ts postTodo guard already coerces a
    // non-object 200 body to an empty `{}`, so through the real path the
    // component receives `{}` (no stub markers, no would_run). The component's
    // OWN resultObj guard additionally survives a raw non-object value if one
    // ever reaches it directly. Either way: no throw, no React error, and no
    // `[object Object]` / `NaN` leaking into the surface.
    for (const body of [5, "ok", ["argv"], true]) {
      const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
      const node = await postAndRead(body);
      expect(node).toBeInTheDocument();
      // No would-run preview is fabricated from a body that carries none.
      expect(screen.queryByTestId("abstain-wouldrun")).toBeNull();
      expect(document.body.textContent ?? "").not.toContain("[object Object]");
      expect(node.textContent ?? "").not.toMatch(/NaN|Infinity/);
      expect(errSpy).not.toHaveBeenCalled();
      cleanup();
      vi.unstubAllGlobals();
      vi.restoreAllMocks();
    }
  });

  it("an empty `{}` body (the api layer's coerced-malformed default) renders the result line clean, no would-run, no crash", async () => {
    // postTodo coerces any non-object 200 body to `{}`; the component must render
    // that empty object without a fabricated would-run preview and without a
    // React error. `{}` has no stub marker, so it reads as the (honest) recorded
    // line — but critically with NO would-run and NO garbage.
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const node = await postAndRead({});
    expect(node).toBeInTheDocument();
    expect(screen.queryByTestId("abstain-wouldrun")).toBeNull();
    expect(node.textContent ?? "").not.toContain("[object Object]");
    expect(errSpy).not.toHaveBeenCalled();
  });

  it("a documented stub envelope still renders the would-run preview (valid behavior unchanged)", async () => {
    const node = await postAndRead({ stub: true, status: "stub", would_run: ["python", "-m", "x"] });
    expect(node).toHaveTextContent(/stub response/i);
    expect(screen.getByTestId("abstain-wouldrun")).toHaveTextContent("python -m x");
  });

  it("a real (non-stub) object body reads as 'abstention recorded' (valid behavior unchanged)", async () => {
    const node = await postAndRead({ status: "ok", recorded: true });
    expect(node).toHaveTextContent(/abstention recorded/i);
  });

  it("would_run with mixed / nested members stringifies each without throwing", async () => {
    // Array.isArray gates entry; member render must survive object/number members.
    const node = await postAndRead({ stub: true, would_run: ["a", 7, { x: 1 }, null] });
    expect(node).toBeInTheDocument();
    expect(screen.getByTestId("abstain-wouldrun")).toBeInTheDocument();
  });

  it("would_run with STRUCTURED (object/array) members renders LEGIBLY, never leaks [object Object]", async () => {
    // ADVERSARIAL repro (JSON-reachable): a legacy/version-skewed stub body where an
    // argv member is emitted as a {flag,value} object or a nested grouping array.
    // Before the fix, `.map(String)` rendered the object as the forbidden
    // `[object Object]` (and an array as a comma-mash), hiding what the CLI would
    // run — exactly the degrade the house doctrine forbids. Now each non-string
    // member is JSON.stringify'd (argvPreview's own legible idiom): an object reads
    // as `{"x":1}`, an array as `[1,2]`, never `[object Object]`. String members
    // pass verbatim (behavior unchanged for the documented string[] shape).
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const node = await postAndRead({
      stub: true,
      would_run: ["python", "-m", "x", { flag: "--ref-id", value: "f-1" }, [1, 2], 7, null],
    });
    expect(node).toBeInTheDocument();
    const wouldRun = screen.getByTestId("abstain-wouldrun");
    const txt = wouldRun.textContent ?? "";
    // The forbidden garbage is gone.
    expect(txt).not.toContain("[object Object]");
    // String members survive verbatim; structured members are legible JSON.
    expect(txt).toContain("python -m x");
    expect(txt).toContain('{"flag":"--ref-id","value":"f-1"}');
    expect(txt).toContain("[1,2]");
    expect(txt).toContain("7");
    expect(txt).toContain("null");
    expect(errSpy).not.toHaveBeenCalled();
  });

  it("would_run of plain strings is rendered space-joined VERBATIM (documented shape unchanged)", async () => {
    const node = await postAndRead({ stub: true, would_run: ["python", "-m", "orchestrator.x", "--ref-id", "f-1"] });
    expect(node).toBeInTheDocument();
    // No JSON quoting of plain string members — they must pass through untouched.
    expect(screen.getByTestId("abstain-wouldrun")).toHaveTextContent("python -m orchestrator.x --ref-id f-1");
  });

  it("would_run that is NOT an array is simply dropped (no preview), result line still shows", async () => {
    const node = await postAndRead({ stub: true, would_run: "not-an-array" });
    expect(node).toHaveTextContent(/stub response/i);
    expect(screen.queryByTestId("abstain-wouldrun")).toBeNull();
  });
});

describe("AbstainForm hardening — error envelope + version-skew", () => {
  it("a 404 (version skew) surfaces a legible error, not a blank page or crash", async () => {
    stubFetch(() => jsonResponse(404, { detail: "Not Found" }));
    render(<AbstainForm findingId="finding-1" available={true} />);
    fireEvent.change(screen.getByLabelText(/abstain note/i), { target: { value: "revisit" } });
    fireEvent.click(screen.getByRole("button", { name: /^abstain$/i }));
    await waitFor(() => expect(screen.getByTestId("abstain-error")).toBeInTheDocument());
    // The form survived; the error message is legible (the TodoError detail).
    expect(screen.getByTestId("abstain-form")).toBeInTheDocument();
    expect(screen.queryByTestId("abstain-result")).toBeNull();
  });

  it("a 502 {rc, stderr} renders stderr VERBATIM (valid behavior unchanged)", async () => {
    stubFetch(() => jsonResponse(502, { rc: 2, stderr: "traceback: boom\n  at line 3" }));
    render(<AbstainForm findingId="finding-1" available={true} />);
    fireEvent.change(screen.getByLabelText(/abstain note/i), { target: { value: "revisit" } });
    fireEvent.click(screen.getByRole("button", { name: /^abstain$/i }));
    await waitFor(() => expect(screen.getByTestId("abstain-stderr")).toBeInTheDocument());
    expect(screen.getByTestId("abstain-stderr")).toHaveTextContent("traceback: boom");
    expect(screen.getByTestId("abstain-stderr")).toHaveTextContent("at line 3");
  });

  it("an error 200-shaped body that fails to parse still surfaces a non-blank error", async () => {
    vi.stubGlobal("fetch", async () =>
      ({
        ok: false,
        status: 500,
        statusText: "Internal Server Error",
        json: async () => {
          throw new Error("no json body");
        },
      }) as unknown as Response,
    );
    render(<AbstainForm findingId="finding-1" available={true} />);
    fireEvent.change(screen.getByLabelText(/abstain note/i), { target: { value: "revisit" } });
    fireEvent.click(screen.getByRole("button", { name: /^abstain$/i }));
    await waitFor(() => expect(screen.getByTestId("abstain-error")).toBeInTheDocument());
    expect(screen.getByTestId("abstain-form")).toBeInTheDocument();
  });
});

describe("AbstainForm hardening — unicode / oversize / leading-dash note content", () => {
  it("oversize + unicode + leading-dash note renders inert in the argv preview, no throw/injection", () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const samples = [
      "x".repeat(5000),
      "نص عربي مع اتجاه RTL",
      "emoji 🤖🔥 mix",
      "--by attacker --note pwned", // leading-dash / argv-injection-looking
      "<script>alert(1)</script>",
      "line1\nline2",
    ];
    for (const s of samples) {
      const { unmount } = render(<AbstainForm findingId="finding-1" available={true} />);
      fireEvent.change(screen.getByLabelText(/abstain note/i), { target: { value: s } });
      const argv = screen.getByTestId("abstain-argv");
      expect(argv).toBeInTheDocument();
      // React escapes — no HTML element injected by the script sample.
      expect(document.querySelector("script")).toBeNull();
      unmount();
    }
    expect(errSpy).not.toHaveBeenCalled();
  });
});
