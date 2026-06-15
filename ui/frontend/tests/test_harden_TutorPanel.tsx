// Adversarial hardening — TutorPanel against malformed / producer-owned
// findingId + title, AND a structural pin of the VERDICT FENCE.
//
// TutorPanel is rendered in Todo.tsx as
//   <TutorPanel findingId={selected?.id ?? ""} title={selected?.title ?? undefined} />
// where `selected` is a finding pulled from producer-owned state (loop_memory.jsonl
// via /api/*). The `string` / `string?` prop types are a compile-time fiction:
// a legacy / partial / buggy row can hand `id` or `title` a null, number, object,
// array, NaN, or Infinity. Before the asText guard:
//   - `title.length` threw `TypeError: Cannot read properties of null` for a null
//     title (the `title !== undefined && title.length` check only excluded
//     undefined, not null), blanking the whole /todo cockpit on one bad row.
//   - an object / array `title` or `findingId` reached React as a child and threw
//     "Objects are not valid as a React child", same blank-page failure.
//   - a non-string number/object stringified to "[object Object]" / "NaN" in the
//     human-facing text.
//
// THE LOAD-BEARING INVARIANT (2026-06-14 session note PART 2): the tutor is
// STRICTLY FENCED from the verdict path — no model both teaches and validates the
// same finding (D-044 independence). The fence is structural: TutorPanel takes NO
// verdict props and exposes NO verdict affordance. These tests pin that the fence
// holds even under odd title/findingId values: no verdict button, no resolve/
// abstain/confirm/refute control, no calibration input, no onResolved callback is
// ever reachable through this surface.
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import TutorPanel from "../src/components/todo/TutorPanel";

afterEach(() => {
  vi.restoreAllMocks();
});

// Cast helper — these values are illegal per the prop type but legal in the
// JSONL the producer actually writes; the runtime must survive them.
const bad = (v: unknown) => v as unknown as string;

describe("TutorPanel hardening — malformed findingId / title never crash or blank", () => {
  it("renders valid-input identically (behavior-preserving)", () => {
    render(<TutorPanel findingId="f-123" title="Markets misprice tail risk" />);
    const panel = screen.getByTestId("tutor-panel");
    expect(panel).toBeInTheDocument();
    expect(panel).toHaveTextContent("Asked to explain:");
    expect(panel).toHaveTextContent("Markets misprice tail risk");
    expect(panel).toHaveTextContent("(f-123)");
  });

  it("falls back to the prompt copy when title is absent (undefined)", () => {
    render(<TutorPanel findingId="f-1" />);
    const panel = screen.getByTestId("tutor-panel");
    expect(panel).toHaveTextContent("Ask the tutor to explain this finding.");
    expect(panel).toHaveTextContent("(f-1)");
  });

  it("a null title degrades to the prompt copy, does NOT throw (the headline crash)", () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() =>
      render(<TutorPanel findingId="f-2" title={bad(null)} />),
    ).not.toThrow();
    const panel = screen.getByTestId("tutor-panel");
    expect(panel).toHaveTextContent("Ask the tutor to explain this finding.");
    expect(errSpy).not.toHaveBeenCalled();
  });

  it("an empty-string title degrades to the prompt copy (empty vs absent collapse cleanly)", () => {
    render(<TutorPanel findingId="f-3" title="" />);
    expect(screen.getByTestId("tutor-panel")).toHaveTextContent(
      "Ask the tutor to explain this finding.",
    );
  });

  it("a whitespace-only title is treated as empty (asText trims), prompt copy shown", () => {
    render(<TutorPanel findingId="f-4" title={"   \n\t  "} />);
    expect(screen.getByTestId("tutor-panel")).toHaveTextContent(
      "Ask the tutor to explain this finding.",
    );
  });

  it("an object / array title is DROPPED — no [object Object], no React-child throw", () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    const { rerender } = render(
      <TutorPanel findingId="f-5" title={bad({ claim: "x" })} />,
    );
    let panel = screen.getByTestId("tutor-panel");
    expect(panel).toHaveTextContent("Ask the tutor to explain this finding.");
    expect(document.body.textContent ?? "").not.toContain("[object Object]");

    rerender(<TutorPanel findingId="f-5" title={bad(["a", "b"])} />);
    panel = screen.getByTestId("tutor-panel");
    expect(panel).toHaveTextContent("Ask the tutor to explain this finding.");
    expect(document.body.textContent ?? "").not.toContain("[object Object]");

    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("a finite-number title stringifies raw; NaN / Infinity are dropped (no NaN leak)", () => {
    const { rerender } = render(
      <TutorPanel findingId="f-6" title={bad(42)} />,
    );
    expect(screen.getByTestId("tutor-panel")).toHaveTextContent("42");

    rerender(<TutorPanel findingId="f-6" title={bad(Number.NaN)} />);
    let panel = screen.getByTestId("tutor-panel");
    expect(panel).toHaveTextContent("Ask the tutor to explain this finding.");
    expect(panel.textContent ?? "").not.toMatch(/NaN/);

    rerender(<TutorPanel findingId="f-6" title={bad(Infinity)} />);
    panel = screen.getByTestId("tutor-panel");
    expect(panel).toHaveTextContent("Ask the tutor to explain this finding.");
    expect(panel.textContent ?? "").not.toMatch(/Infinity/);
  });

  it("a null / object / array findingId is dropped (no parens-garbage), panel still renders", () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    for (const v of [null, undefined, { id: 1 }, ["x"], Number.NaN, Infinity]) {
      const { unmount } = render(<TutorPanel findingId={bad(v)} title="t" />);
      const panel = screen.getByTestId("tutor-panel");
      // The panel survives and the title still renders.
      expect(panel).toHaveTextContent("Asked to explain:");
      // No garbage id leaks.
      expect(panel.textContent ?? "").not.toContain("[object Object]");
      expect(panel.textContent ?? "").not.toMatch(/NaN|Infinity/);
      unmount();
    }
    expect(errSpy).not.toHaveBeenCalled();
  });

  it("a finite-number findingId stringifies raw inside the parens", () => {
    render(<TutorPanel findingId={bad(7)} title="t" />);
    expect(screen.getByTestId("tutor-panel")).toHaveTextContent("(7)");
  });

  it("NONE of the malformed prop combinations throw", () => {
    const vals = [null, undefined, 0, 42, -1, Number.NaN, Infinity, true, false, {}, [], { a: 1 }, [1, 2]];
    for (const id of vals) {
      for (const t of vals) {
        expect(() =>
          render(<TutorPanel findingId={bad(id)} title={bad(t)} />),
        ).not.toThrow();
      }
    }
  });

  it("unicode / emoji / RTL / HTML-looking title renders as inert text (no injection)", () => {
    const samples = [
      "<script>alert(1)</script>",
      "<img src=x onerror=alert(1)>",
      "نص عربي مع اتجاه RTL",
      "emoji 🤖🔥🧪",
      "{}}{<>&\"'`",
    ];
    for (const s of samples) {
      const { unmount } = render(<TutorPanel findingId="f" title={s} />);
      expect(screen.getByTestId("tutor-panel")).toHaveTextContent(s, {
        normalizeWhitespace: false,
      });
      expect(document.querySelector("script")).toBeNull();
      expect(document.querySelector("img")).toBeNull();
      unmount();
    }
  });

  it("a very long unbroken title (5k chars) renders without throwing", () => {
    const big = "x".repeat(5000);
    expect(() => render(<TutorPanel findingId="f" title={big} />)).not.toThrow();
    expect(screen.getByTestId("tutor-panel").textContent ?? "").toContain(big);
  });

  // ADVERSARIAL DEEP-DEREF PIN (skeptic pass): asText must DROP exotic values by
  // typeof alone and NEVER touch a property on them. A producer reviver / legacy
  // path can hand a title/findingId a bigint, Symbol, function, boxed String/
  // Number, a null-prototype object, or — the nasty one — an object whose
  // toString()/getter THROWS, or a Proxy whose traps throw. A shallow guard that
  // "stringifies anything" (e.g. a future refactor to `String(value)`) would
  // detonate on the throwing-toString / throwing-Proxy cases and blank /todo on
  // one bad row. This pins that asText degrades by type, with zero deref.
  it("exotic / throwing-on-deref title & findingId are DROPPED with no property access (deep-deref safe)", () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const throwingToString = {
      toString() {
        throw new Error("toString must never be called by asText");
      },
      valueOf() {
        throw new Error("valueOf must never be called by asText");
      },
    };
    const throwingProxy = new Proxy(
      {},
      {
        get() {
          throw new Error("proxy get trap must never fire");
        },
        has() {
          throw new Error("proxy has trap must never fire");
        },
      },
    );

    const exotics: unknown[] = [
      10n, // bigint — JSON-reviver legal, typeof "bigint", unhandled => dropped
      Symbol("verdict"), // typeof "symbol" => dropped
      () => "resolve YES", // function => dropped, never invoked
      new String("boxed"), // typeof "object" (NOT "string") => dropped
      new Number(5), // typeof "object" => dropped
      Object.create(null), // null-prototype, no toString on chain => dropped
      throwingToString, // would throw IF asText ever stringified it
      throwingProxy, // would throw IF asText ever read a property
    ];

    for (const v of exotics) {
      const { unmount } = render(
        <TutorPanel findingId={bad(v)} title={bad(v)} />,
      );
      const panel = screen.getByTestId("tutor-panel");
      // Degrades to the prompt copy + dropped id — never a crash, never garbage.
      expect(panel).toHaveTextContent("Ask the tutor to explain this finding.");
      const text = panel.textContent ?? "";
      expect(text).not.toContain("[object Object]");
      expect(text).not.toMatch(/NaN|Infinity|Symbol|boxed|resolve YES/);
      unmount();
    }
    // React never logged a "not a valid child" error and no trap/toString fired
    // (a thrown trap would have propagated out of render and failed the .toThrow
    // boundary above; this asserts the quieter path too).
    expect(errSpy).not.toHaveBeenCalled();
  });
});

describe("TutorPanel — THE VERDICT FENCE (load-bearing invariant) holds under odd inputs", () => {
  // The fence is structural: TutorPanel takes NO verdict props and exposes NO
  // verdict affordance. We assert the surface NEVER renders an actionable verdict
  // control, even when title / findingId carry verdict-shaped or hostile values.
  const oddInputs: Array<[unknown, unknown]> = [
    ["resolve YES — confidence 0.9", "f-yes"],
    ["REFUTE this finding", { verdict: "no" }],
    [bad(null), bad(null)],
    [bad({ onResolved: () => "yes" }), bad(["confirm"])],
    ["Set verdict to TRUE", "calibration=0.8"],
  ];

  it("renders the visible fence note and the read-only stub, always", () => {
    for (const [t, id] of oddInputs) {
      const { unmount } = render(
        <TutorPanel findingId={bad(id)} title={bad(t)} />,
      );
      // The human-visible separation is always present.
      const fence = screen.getByTestId("tutor-fence-note");
      expect(fence).toHaveTextContent(/does not affect your verdict/i);
      expect(fence).toHaveTextContent(/independence/i);
      // The stub banner (read-only, would-run-only per D-046) is present.
      expect(screen.getByTestId("tutor-stub-banner")).toHaveTextContent(/stub/i);
      unmount();
    }
  });

  it("exposes NO actionable verdict affordance — no button, no input, no form, no link", () => {
    for (const [t, id] of oddInputs) {
      const { unmount } = render(
        <TutorPanel findingId={bad(id)} title={bad(t)} />,
      );
      // Zero interactive controls of any verdict-capable kind.
      expect(screen.queryByRole("button")).toBeNull();
      expect(screen.queryByRole("textbox")).toBeNull();
      expect(screen.queryByRole("checkbox")).toBeNull();
      expect(screen.queryByRole("radio")).toBeNull();
      expect(screen.queryByRole("slider")).toBeNull();
      expect(screen.queryByRole("combobox")).toBeNull();
      expect(screen.queryByRole("spinbutton")).toBeNull();
      expect(screen.queryByRole("link")).toBeNull();
      // No raw <input>/<select>/<textarea>/<form> nodes either.
      const panel = screen.getByTestId("tutor-panel");
      expect(panel.querySelector("button")).toBeNull();
      expect(panel.querySelector("input")).toBeNull();
      expect(panel.querySelector("select")).toBeNull();
      expect(panel.querySelector("textarea")).toBeNull();
      expect(panel.querySelector("form")).toBeNull();
      unmount();
    }
  });

  it("never surfaces verdict-affordance vocabulary as a clickable/actionable control", () => {
    // Even if a malformed title CONTAINS verdict words, they only appear as inert
    // explanation text — never as a resolve/abstain/confirm/refute control. We
    // assert no element with a verdict-action testid exists (the verdict path uses
    // FindingReviewForm / AbstainForm, which are separate components).
    render(
      <TutorPanel findingId="f" title="resolve YES confirm refute abstain" />,
    );
    const panel = screen.getByTestId("tutor-panel");
    // None of the verdict-form testids leak into this surface.
    for (const tid of [
      "finding-review-form",
      "abstain-form",
      "verdict-yes",
      "verdict-no",
      "resolve-button",
      "calibration-input",
    ]) {
      expect(panel.querySelector(`[data-testid="${tid}"]`)).toBeNull();
    }
    // The verdict words are present only as text inside the explanation span.
    expect(panel).toHaveTextContent(/resolve YES confirm refute abstain/i);
  });

  it("the component's own type accepts no verdict-shaped prop (props are minimal)", () => {
    // A compile-time / runtime smoke: passing verdict-shaped extras must not
    // produce any new affordance (extra props are ignored, not wired).
    const extras = {
      verdict: "yes",
      setVerdict: () => {},
      onResolved: () => {},
      calibration: 0.9,
    } as unknown as Record<string, unknown>;
    render(<TutorPanel findingId="f" title="t" {...extras} />);
    const panel = screen.getByTestId("tutor-panel");
    expect(screen.queryByRole("button")).toBeNull();
    expect(panel.querySelector("input")).toBeNull();
    // Still renders only the explanation + fence note + stub.
    expect(panel).toHaveTextContent("Asked to explain:");
    expect(screen.getByTestId("tutor-fence-note")).toBeInTheDocument();
  });
});
