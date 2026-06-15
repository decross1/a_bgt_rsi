// Hardening for DirectiveSignOffField against the HOUSE ROBUSTNESS DOCTRINE.
//
// DirectiveSignOffField is a CONTROLLED field: the integrator owns `iterationId`
// and `note` and lifts them off producer-owned JSON (active_run.json / the
// /api/* envelopes). The `string` types on those props are a compile-time
// fiction over an unchecked stream — a legacy/partial body can hand the field a
// non-string (null, a number, an object) where a string is expected. A bare
// `note.trim()` / `iterationId` template-interpolation then throws "x.trim is
// not a function" and blanks the whole cockpit on one bad field. The fix coerces
// each controlled prop to a safe string (SystemActivityHero.asText idiom): a
// non-string degrades to "" — the SAME bare-placeholder path as a genuinely
// empty value — never a crash.
//
// The POST response body is ALSO producer-owned (the stub returns
// {stub, would_run:[...]} but a malformed/legacy/array/primitive body must
// degrade): `result` reaching the render as a non-object, and `would_run`
// carrying non-string elements ("[object Object]" leak), are pinned here.
//
// `available` is coerced strictly (=== true), never truthy — a stringy/numeric
// truthy must NOT light up the live submit (rule 4 / attest.ts idiom): the
// honest stub state stays the default.
//
// No headless browser in this stack, so "renders without console errors" is the
// jsdom stand-in: render and assert console.error/console.warn were not called.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import DirectiveSignOffField from "../src/components/todo/DirectiveSignOffField";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function watchConsole() {
  return {
    error: vi.spyOn(console, "error").mockImplementation(() => {}),
    warn: vi.spyOn(console, "warn").mockImplementation(() => {}),
  };
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

// Stub fetch for the directive_signoff POST; default echoes an honest stub body.
function stubSignoff(body: unknown, status = 200) {
  vi.stubGlobal("fetch", async (url: unknown) => {
    const u = String(url);
    if (u.endsWith("/api/todo/directive_signoff")) return jsonResponse(status, body);
    throw new Error(`unstubbed fetch: ${u}`);
  });
}

// Non-string values a real producer-owned body can hand a `string`-typed prop
// but the Props type forbids at compile time. Cast through unknown.
const BAD_STRINGS: Array<[string, unknown]> = [
  ["null", null],
  ["undefined", undefined],
  ["a number", 42],
  ["NaN", NaN],
  ["Infinity", Infinity],
  ["a boolean", true],
  ["an object", { x: 1 }],
  ["an array", ["a", "b"]],
];

describe("DirectiveSignOffField hardening — non-string controlled props", () => {
  it("the regression: a non-string `note` does not throw (no `.trim is not a function`)", () => {
    for (const [name, note] of BAD_STRINGS) {
      const c = watchConsole();
      const { container, unmount } = render(
        <DirectiveSignOffField
          iterationId="iter-2026-06-14-001"
          note={note as unknown as string}
          available={true}
        />,
      );
      // Field still mounts; nothing leaks into the DOM.
      expect(screen.getByTestId("directive-signoff-field"), name).toBeInTheDocument();
      expect(container.innerHTML, name).not.toContain("[object Object]");
      expect(container.innerHTML, name).not.toContain("NaN");
      expect(c.error, name).not.toHaveBeenCalled();
      expect(c.warn, name).not.toHaveBeenCalled();
      unmount();
    }
  });

  it("a non-string `iterationId` degrades to the <iter-ID> placeholder in the argv preview, never throws", () => {
    for (const [name, iterationId] of BAD_STRINGS) {
      const c = watchConsole();
      const { unmount } = render(
        <DirectiveSignOffField
          iterationId={iterationId as unknown as string}
          note="audit note"
          available={true}
        />,
      );
      // Type a directive so the would-run argv pre renders.
      fireEvent.change(screen.getByLabelText("sign-off directive (optional)"), {
        target: { value: "proceed to step 9" },
      });
      const argv = screen.getByTestId("directive-signoff-argv").textContent ?? "";
      // The malformed id degrades to the placeholder rather than leaking junk.
      expect(argv, name).toContain("<iter-ID>");
      expect(argv, name).not.toContain("[object Object]");
      expect(argv, name).not.toContain("NaN");
      expect(c.error, name).not.toHaveBeenCalled();
      unmount();
    }
  });

  it("a non-string `note` keeps the directive submit DISABLED (empty audit note) and renders no junk", () => {
    const c = watchConsole();
    render(
      <DirectiveSignOffField
        iterationId="iter-1"
        note={{ legacy: "row" } as unknown as string}
        available={true}
      />,
    );
    fireEvent.change(screen.getByLabelText("sign-off directive (optional)"), {
      target: { value: "proceed" },
    });
    // A malformed note reads as empty → the directive variant cannot submit
    // (it needs a real audit note), the same as a genuinely empty note.
    const btn = screen.getByRole("button", { name: /sign off with directive/i });
    expect(btn).toBeDisabled();
    const argv = screen.getByTestId("directive-signoff-argv").textContent ?? "";
    expect(argv).toContain("<why>");
    expect(argv).not.toContain("[object Object]");
    expect(c.error).not.toHaveBeenCalled();
  });

  it("the fix did not over-suppress: valid string props produce the real argv and an enabled submit", () => {
    watchConsole();
    render(
      <DirectiveSignOffField
        iterationId="iter-2026-06-14-007"
        note="looks sound; advancing"
        available={true}
      />,
    );
    fireEvent.change(screen.getByLabelText("sign-off directive (optional)"), {
      target: { value: "proceed to step 9" },
    });
    const argv = screen.getByTestId("directive-signoff-argv").textContent ?? "";
    expect(argv).toContain("iter-2026-06-14-007");
    expect(argv).toContain("proceed to step 9");
    expect(argv).toContain("looks sound; advancing");
    expect(
      screen.getByRole("button", { name: /sign off with directive/i }),
    ).toBeEnabled();
  });
});

describe("DirectiveSignOffField hardening — `available` coerced strictly", () => {
  it("a truthy NON-boolean `available` stays in the honest stub state (submit disabled)", () => {
    // A producer can hand a stringy/numeric truthy where a boolean is expected.
    // Strict === true means none of these light up the live submit (rule 4).
    for (const available of ["true", 1, {}, [], "yes"] as unknown[]) {
      const c = watchConsole();
      const { unmount } = render(
        <DirectiveSignOffField
          iterationId="iter-1"
          note="note"
          available={available as unknown as boolean}
        />,
      );
      // Honest stub banner still shown; submit disabled even with a directive.
      expect(screen.getByTestId("directive-signoff-stub")).toBeInTheDocument();
      fireEvent.change(screen.getByLabelText("sign-off directive (optional)"), {
        target: { value: "proceed" },
      });
      expect(
        screen.getByRole("button", { name: /sign off with directive/i }),
      ).toBeDisabled();
      expect(c.error).not.toHaveBeenCalled();
      unmount();
    }
  });

  it("available === true (only) enables the live submit", () => {
    watchConsole();
    render(
      <DirectiveSignOffField iterationId="iter-1" note="note" available={true} />,
    );
    expect(screen.queryByTestId("directive-signoff-stub")).toBeNull();
    fireEvent.change(screen.getByLabelText("sign-off directive (optional)"), {
      target: { value: "proceed" },
    });
    expect(
      screen.getByRole("button", { name: /sign off with directive/i }),
    ).toBeEnabled();
  });
});

describe("DirectiveSignOffField hardening — malformed POST response body", () => {
  async function submitDirective() {
    fireEvent.change(screen.getByLabelText("sign-off directive (optional)"), {
      target: { value: "proceed to step 9" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /sign off with directive/i }),
    );
  }

  it("a non-object body (number / string / array / null) does not throw or leak junk", async () => {
    for (const body of [42, "ok", [1, 2, 3], null] as unknown[]) {
      const c = watchConsole();
      stubSignoff(body);
      const { unmount } = render(
        <DirectiveSignOffField iterationId="iter-1" note="note" available={true} />,
      );
      await submitDirective();
      // The result region either stays silent (null/non-object) or degrades to a
      // legible line — never crashes the field, never prints "[object Object]".
      await waitFor(() => {
        const field = screen.getByTestId("directive-signoff-field");
        expect(field.innerHTML).not.toContain("[object Object]");
      });
      expect(c.error).not.toHaveBeenCalled();
      expect(c.warn).not.toHaveBeenCalled();
      unmount();
    }
  });

  it("would_run carrying NON-string elements never leaks [object Object]/NaN into the preview", async () => {
    const c = watchConsole();
    stubSignoff({
      stub: true,
      would_run: ["python", { obj: 1 }, null, 7, NaN, ["nested"], "--flag"],
    });
    render(
      <DirectiveSignOffField iterationId="iter-1" note="note" available={true} />,
    );
    await submitDirective();
    const pre = await screen.findByTestId("directive-signoff-wouldrun");
    const txt = pre.textContent ?? "";
    // Legible string/finite-number tokens survive; objects/null/NaN/arrays drop.
    expect(txt).toContain("python");
    expect(txt).toContain("--flag");
    expect(txt).toContain("7");
    expect(txt).not.toContain("[object Object]");
    expect(txt).not.toContain("NaN");
    expect(c.error).not.toHaveBeenCalled();
  });

  it("rule-4: a MISTYPED stub body (stub:'true'/stray status) carrying a would_run preview is NOT claimed as a recorded write", async () => {
    // The defining signature of a stub that wrote NOTHING is the would_run
    // preview. A producer (legacy/version-skew) can send the stub marker
    // mistyped — `stub:"true"` (string) plus a stray `status:"ok"` — alongside
    // the would_run argv. The strict `stub === true`/`status === "stub"` checks
    // both miss, and a naive default would announce "sign-off recorded with
    // directive": a FABRICATED write claim while the seam is dark (rule 4). The
    // presence of would_run must force the honest-stub line.
    const c = watchConsole();
    stubSignoff({
      stub: "true",
      status: "ok",
      would_run: ["orchestrator.gate_cli", "--verdict", "valid"],
    });
    render(
      <DirectiveSignOffField iterationId="iter-1" note="note" available={true} />,
    );
    await submitDirective();
    const result = await screen.findByTestId("directive-signoff-result");
    // MUST report nothing-written, MUST NOT claim a recorded sign-off.
    expect(result).toHaveTextContent(/nothing written/i);
    expect(result.textContent ?? "").not.toMatch(/recorded with directive/i);
    // The preview still renders verbatim (the human sees what WOULD run).
    expect(screen.getByTestId("directive-signoff-wouldrun")).toHaveTextContent(
      "orchestrator.gate_cli --verdict valid",
    );
    expect(c.error).not.toHaveBeenCalled();
  });

  it("a TRUE recorded body (no would_run, no stub marker) still reports the recorded line (no over-suppression)", async () => {
    // The fix must not blanket-suppress: a body that is genuinely a recorded
    // sign-off (the live seam, which carries NO would_run preview) still reads
    // as recorded.
    watchConsole();
    stubSignoff({ recorded: true, verdict: "valid" });
    render(
      <DirectiveSignOffField iterationId="iter-1" note="note" available={true} />,
    );
    await submitDirective();
    const result = await screen.findByTestId("directive-signoff-result");
    expect(result).toHaveTextContent(/recorded with directive/i);
    expect(screen.queryByTestId("directive-signoff-wouldrun")).toBeNull();
  });

  it("a well-formed stub body still renders the stub line + would-run preview (no over-suppression)", async () => {
    watchConsole();
    stubSignoff({ stub: true, would_run: ["orchestrator.gate_cli", "--verdict", "valid"] });
    render(
      <DirectiveSignOffField iterationId="iter-1" note="note" available={true} />,
    );
    await submitDirective();
    const result = await screen.findByTestId("directive-signoff-result");
    expect(result).toHaveTextContent(/nothing written/i);
    expect(screen.getByTestId("directive-signoff-wouldrun")).toHaveTextContent(
      "orchestrator.gate_cli --verdict valid",
    );
  });

  it("a version-skew 404 surfaces a legible error, never a blank/crash", async () => {
    const c = watchConsole();
    stubSignoff({ detail: "Not Found" }, 404);
    render(
      <DirectiveSignOffField iterationId="iter-1" note="note" available={true} />,
    );
    await submitDirective();
    // postTodo throws TodoError on !ok; the field surfaces it in the error slot.
    const err = await screen.findByTestId("directive-signoff-error");
    expect(err.textContent ?? "").toMatch(/404|not found/i);
    // The field itself stays mounted (no blank page).
    expect(screen.getByTestId("directive-signoff-field")).toBeInTheDocument();
    // console.error is expected NOT to fire — the catch handles it legibly.
    expect(c.error).not.toHaveBeenCalled();
  });

  it("a 502 {rc, stderr} body renders stderr VERBATIM in the stderr slot", async () => {
    watchConsole();
    stubSignoff({ rc: 3, stderr: "gate_cli: iteration not found\n" }, 502);
    render(
      <DirectiveSignOffField iterationId="iter-1" note="note" available={true} />,
    );
    await submitDirective();
    const stderr = await screen.findByTestId("directive-signoff-stderr");
    expect(stderr.textContent ?? "").toContain("gate_cli: iteration not found");
  });
});
