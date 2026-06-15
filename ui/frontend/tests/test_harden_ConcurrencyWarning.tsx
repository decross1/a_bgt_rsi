// Hardening for ConcurrencyWarning — the cockpit's in-place warn/queue guard.
//
// Provenance (house robustness doctrine):
//
// ConcurrencyWarning resolves its status from one of TWO producer-owned
// sources, neither of which the component owns:
//
//  1. the INJECTED `status` prop — the cockpit shell / a future caller hands a
//     ConcurrencyStatus directly. This BYPASSES api/todo.ts's asConcurrency
//     sanitizer, so a garbled value (a non-object, an array, `active` as a
//     stringy/numeric truthy, `kind`/`label`/`narration` as an object/number/
//     empty string) reaches the render path verbatim. The component used to do
//     `!resolved.active` (truthy, not strict) and `resolved.narration ?? …`
//     (null-guard only) — so `active:"true"` fabricated a warning and an object
//     narration leaked "[object Object]" into the human-facing banner.
//
//  2. the SELF-FETCH (getConcurrency, only when no prop) — already sanitized by
//     api/todo.ts. A FAILED self-fetch (network error / non-404 !ok throw) must
//     leave the guard silent — never fabricate a warning — and must not surface
//     as an unhandled-rejection console error.
//
// The fix mirrors asConcurrency: coerce the resolved status (asSafeStatus) so a
// non-object/array → null (render nothing, never throw on a primitive's
// `.active`), `active === true` strictly, and the optional run-describing fields
// survive only as a non-empty string. Valid input renders identically.
//
// No headless browser here, so "renders without console errors" is the jsdom
// stand-in: render and assert console.error / console.warn were not called.
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ConcurrencyWarning from "../src/components/todo/ConcurrencyWarning";
import type { ConcurrencyStatus } from "../src/types/todo";
import * as todoApi from "../src/api/todo";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function watchConsole() {
  return {
    error: vi.spyOn(console, "error").mockImplementation(() => {}),
    warn: vi.spyOn(console, "warn").mockImplementation(() => {}),
  };
}

// Express a garbled status the producer can hand the prop at runtime but the
// ConcurrencyStatus type forbids at compile time — cast through unknown.
function asStatus(v: unknown): ConcurrencyStatus {
  return v as ConcurrencyStatus;
}

describe("ConcurrencyWarning hardening — injected prop (bypasses api sanitizer)", () => {
  // Garbled prop SHAPES that are not a real `active:true` contention signal →
  // the guard must render nothing (and never throw on a primitive's `.active`).
  const NON_ACTIVE: Array<[string, unknown]> = [
    ["a number prop", 42],
    ["a string prop", "busy"],
    ["a boolean prop", true],
    ["NaN", NaN],
    ["Infinity", Infinity],
    ["an empty array", []],
    ["a populated array", [{ active: true }]],
    ["{} (active absent)", {}],
    ['active:"true" (stringy truthy — NOT === true)', { active: "true" }],
    ["active:1 (numeric truthy — NOT === true)", { active: 1 }],
    ["active:NaN", { active: NaN }],
    ['active:"" then truthy fields', { active: "", kind: "loop_v0" }],
  ];

  it("renders nothing (no banner, no throw, no console error) for every non-active garbled prop", () => {
    for (const [name, val] of NON_ACTIVE) {
      const c = watchConsole();
      const { container, unmount } = render(
        <ConcurrencyWarning status={asStatus(val)} />,
      );
      expect(container, name).toBeEmptyDOMElement();
      expect(container.innerHTML, name).not.toContain("[object Object]");
      expect(container.innerHTML, name).not.toContain("NaN");
      expect(c.error, name).not.toHaveBeenCalled();
      expect(c.warn, name).not.toHaveBeenCalled();
      unmount();
    }
  });

  it("the regression: active:'true' (stringy truthy) does NOT fabricate a warning", () => {
    const c = watchConsole();
    const { container } = render(
      <ConcurrencyWarning status={asStatus({ active: "true" })} />,
    );
    // Strict === true means a stringy/numeric truthy is idle → silent.
    expect(screen.queryByTestId("concurrency-warning")).toBeNull();
    expect(container).toBeEmptyDOMElement();
    expect(c.error).not.toHaveBeenCalled();
  });

  it("the regression: an object/number/array narration never leaks [object Object] (or a stray number) into the banner", () => {
    for (const narration of [
      { nested: { deep: true } } as unknown,
      ["off", "domain"],
      12345,
      NaN,
      Infinity,
    ]) {
      const c = watchConsole();
      const { container, unmount } = render(
        <ConcurrencyWarning status={asStatus({ active: true, narration })} />,
      );
      // The banner STILL fires (it IS active) …
      const banner = screen.getByTestId("concurrency-warning");
      expect(banner).toHaveTextContent(/models busy/i);
      // … but the garbled narration is dropped → falls back to the honest stub,
      // never "[object Object]" / a raw number / NaN / Infinity.
      expect(container.innerHTML).not.toContain("[object Object]");
      expect(container.innerHTML).not.toContain("12345");
      expect(container.innerHTML).not.toContain("NaN");
      expect(container.innerHTML).not.toContain("Infinity");
      expect(banner).toHaveTextContent(/iteration is mid-flight/i);
      expect(c.error).not.toHaveBeenCalled();
      expect(c.warn).not.toHaveBeenCalled();
      unmount();
    }
  });

  it("garbled kind / label (object/number/array/empty) are dropped, banner still renders cleanly", () => {
    const c = watchConsole();
    const { container } = render(
      <ConcurrencyWarning
        status={asStatus({
          active: true,
          kind: { x: 1 },
          label: [1, 2, 3],
        })}
      />,
    );
    const banner = screen.getByTestId("concurrency-warning");
    expect(banner).toHaveTextContent(/models busy/i);
    expect(container.innerHTML).not.toContain("[object Object]");
    expect(container.innerHTML).not.toContain("NaN");
    expect(c.error).not.toHaveBeenCalled();
  });

  it("empty-string kind/label/narration degrade to absent (no dangling separators, honest stub narration)", () => {
    const c = watchConsole();
    render(
      <ConcurrencyWarning
        status={asStatus({ active: true, kind: "", label: "", narration: "" })}
      />,
    );
    const banner = screen.getByTestId("concurrency-warning");
    // empty narration → honest stub, not a blank dangling "— ".
    expect(banner).toHaveTextContent(/iteration is mid-flight/i);
    expect(c.error).not.toHaveBeenCalled();
  });
});

describe("ConcurrencyWarning — VALID input unchanged (fix did not over-suppress)", () => {
  it("a well-formed active status renders the named run verbatim", () => {
    const c = watchConsole();
    render(
      <ConcurrencyWarning
        status={{
          active: true,
          kind: "loop_v0",
          label: "iter-042",
          narration: "skeptic critiquing the gate verdict",
        }}
      />,
    );
    const banner = screen.getByTestId("concurrency-warning");
    expect(banner).toHaveTextContent(/models busy/i);
    expect(banner).toHaveTextContent("skeptic critiquing the gate verdict");
    expect(banner).toHaveTextContent("loop_v0");
    expect(banner).toHaveTextContent("iter-042");
    expect(banner).toHaveTextContent(/warn\/queue, not a block/i);
    expect(c.error).not.toHaveBeenCalled();
  });

  it("an idle status (active:false) renders nothing, as before", () => {
    const { container } = render(
      <ConcurrencyWarning status={{ active: false }} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("active with only narration (kind/label absent) renders narration, no run-id span", () => {
    render(
      <ConcurrencyWarning
        status={{ active: true, narration: "loop mid-flight" }}
      />,
    );
    const banner = screen.getByTestId("concurrency-warning");
    expect(banner).toHaveTextContent("loop mid-flight");
  });

  // ADVERSARIAL-VERIFY pin: the fix drops a GARBLED (object/number/array)
  // narration so React never prints "[object Object]". But a narration that is
  // the LITERAL valid string "[object Object]" (a producer can legitimately
  // narrate that text) must still render verbatim — the drop is by TYPE
  // (non-string) + EMPTINESS, never by content. Guards against a future
  // over-eager "scrub the substring [object Object]" fix that would wrongly
  // suppress a legitimate string and blank the banner.
  it("does NOT over-suppress: a narration that is the literal string '[object Object]' renders verbatim", () => {
    const c = watchConsole();
    render(
      <ConcurrencyWarning
        status={asStatus({ active: true, narration: "[object Object]" })}
      />,
    );
    const banner = screen.getByTestId("concurrency-warning");
    // It is a real non-empty string → surfaced, NOT replaced by the stub.
    expect(banner.textContent).toContain("[object Object]");
    expect(banner).not.toHaveTextContent(/iteration is mid-flight/i);
    expect(c.error).not.toHaveBeenCalled();
  });

  // ADVERSARIAL-VERIFY pin: a null-prototype object (Object.create(null), a
  // shape a producer/proxy can hand the prop) has no Object.prototype, so any
  // guard that leaned on inherited methods would mis-handle it. asSafeStatus
  // uses only typeof / === / Array.isArray, so it coerces cleanly.
  it("a null-prototype status object coerces cleanly (no prototype-method assumption)", () => {
    const c = watchConsole();
    const o = Object.create(null) as Record<string, unknown>;
    o.active = true;
    o.narration = "null-proto narration";
    render(<ConcurrencyWarning status={asStatus(o)} />);
    expect(screen.getByTestId("concurrency-warning")).toHaveTextContent(
      "null-proto narration",
    );
    expect(c.error).not.toHaveBeenCalled();
  });
});

describe("ConcurrencyWarning — self-fetch path (no prop injected)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("a FAILED self-fetch does NOT fabricate a warning and surfaces no console error", async () => {
    const c = watchConsole();
    vi.spyOn(todoApi, "getConcurrency").mockRejectedValue(
      new Error("network down"),
    );
    const { container } = render(<ConcurrencyWarning />);
    // Give the rejected promise + its .catch a microtask to settle.
    await waitFor(() => {
      expect(container).toBeEmptyDOMElement();
    });
    expect(screen.queryByTestId("concurrency-warning")).toBeNull();
    // The .catch swallows the rejection → no unhandled-rejection console error.
    expect(c.error).not.toHaveBeenCalled();
    expect(c.warn).not.toHaveBeenCalled();
  });

  it("a self-fetch resolving idle (the skew/absent-run default) renders nothing", async () => {
    vi.spyOn(todoApi, "getConcurrency").mockResolvedValue({ active: false });
    const { container } = render(<ConcurrencyWarning />);
    await waitFor(() => {
      expect(container).toBeEmptyDOMElement();
    });
  });

  it("a self-fetch resolving active renders the warning", async () => {
    vi.spyOn(todoApi, "getConcurrency").mockResolvedValue({
      active: true,
      narration: "fetched contention",
    });
    render(<ConcurrencyWarning />);
    await waitFor(() => {
      expect(screen.getByTestId("concurrency-warning")).toHaveTextContent(
        "fetched contention",
      );
    });
  });

  // ADVERSARIAL-VERIFY pin: prop↔poll ORDERING race. A caller mounts WITH a
  // prop (suppresses the fetch), then DROPS the prop to undefined (e.g. a shell
  // that hands a snapshot then lets the component self-poll). The effect's
  // `[status]` dep re-fires and a self-fetch starts; when it resolves the
  // banner must switch to the fetched contention cleanly, with no stale-prop
  // bleed-through and no console error. Pins the prop→undefined→late-fetch
  // handoff the existing tests did not cover.
  it("prop active → dropped to undefined → late self-fetch wins cleanly (no stale bleed, no error)", async () => {
    const c = watchConsole();
    let resolveFetch: (s: ConcurrencyStatus) => void = () => {};
    vi.spyOn(todoApi, "getConcurrency").mockImplementation(
      () => new Promise<ConcurrencyStatus>((res) => (resolveFetch = res)),
    );
    const { rerender } = render(
      <ConcurrencyWarning status={{ active: true, narration: "from prop" }} />,
    );
    expect(screen.getByTestId("concurrency-warning")).toHaveTextContent(
      "from prop",
    );
    // Caller drops the prop → effect re-runs → self-fetch begins.
    rerender(<ConcurrencyWarning status={undefined} />);
    resolveFetch({ active: true, narration: "from fetch" });
    await waitFor(() => {
      expect(screen.getByTestId("concurrency-warning")).toHaveTextContent(
        "from fetch",
      );
    });
    expect(screen.getByTestId("concurrency-warning")).not.toHaveTextContent(
      "from prop",
    );
    expect(c.error).not.toHaveBeenCalled();
    expect(c.warn).not.toHaveBeenCalled();
  });

  // ADVERSARIAL-VERIFY pin: late-fetch-after-unmount stale-set race. The
  // self-fetch resolves AFTER the component unmounts; the effect's `active`
  // cleanup flag must gate the setState so React logs no
  // "setState on unmounted component" error and the rejection-free path stays
  // quiet.
  it("a self-fetch resolving AFTER unmount does not setState / log an error", async () => {
    const c = watchConsole();
    let resolveFetch: (s: ConcurrencyStatus) => void = () => {};
    vi.spyOn(todoApi, "getConcurrency").mockImplementation(
      () => new Promise<ConcurrencyStatus>((res) => (resolveFetch = res)),
    );
    const { unmount } = render(<ConcurrencyWarning />);
    unmount();
    resolveFetch({ active: true, narration: "too late" });
    await new Promise((r) => setTimeout(r, 10));
    expect(c.error).not.toHaveBeenCalled();
    expect(c.warn).not.toHaveBeenCalled();
  });
});
