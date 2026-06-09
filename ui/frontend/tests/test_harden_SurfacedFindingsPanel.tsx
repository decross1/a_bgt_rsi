// Consolidated edge-case + property-fuzz hardening for SurfacedFindingsPanel (merged from per-round files).
//
// This file merges the per-round hardening suites (r1 missing/null/absent
// fields, r2 malformed value TYPES + poll-path number-typed sort, r4 unknown /
// forward-compatible enums, r5 empty-vs-absent collections + boundary numbers)
// and the property-fuzz sweep (combined malformed shapes) into one file. Each
// source file's body is wrapped in its OWN top-level describe so describe/it
// names never collide, and EVERY it()/test() case and assertion is preserved
// verbatim from its origin.
//
// memory/surfaced_findings.jsonl is producer-owned and unvalidated. The
// no-headless-browser stand-in for "renders without console errors" across all
// rounds is the same idiom: a jsdom render + a console.error/warn spy asserted
// not-called (a render-time throw, a "two children with the same key" warning,
// or an act() warning all land on console.error in jsdom). The `initial` prop
// bypasses polling so rows render synchronously from constructed inputs; the
// poll-path case mocks the http layer to drive the live POLL path (the sort).
//
// NOTE ON THE HOISTED vi.mock: `vi.mock("../src/api/http", ...)` is hoisted to
// the top of the module by Vitest, so it applies file-wide. Every test except
// the r2 poll-path case passes an `initial` prop, and the component returns
// early from its polling effect when `initial !== undefined` (it never calls
// getSurfacedFindings), so the global http mock is inert for the synchronous
// `initial`-prop renders and only feeds the one poll-path test.
import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import SurfacedFindingsPanel from "../src/components/SurfacedFindingsPanel";
import type { SurfacedFinding } from "../src/types/schemas";

// Shared across every round/fuzz suite below (identical body in each source
// file): spy on console.error/warn for one render; a React act() warning, a
// duplicate-key warning, or a render-time throw lands on console.error in
// jsdom, so "not called" is the no-headless-browser clean-render stand-in.
function spyConsole() {
  const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  return { errSpy, warnSpy };
}

// Hoisted vi.mock from the r2 poll-path suite: with no `initial` prop the panel
// polls getSurfacedFindings and runs the promoted_at sort, which pre-fix threw
// `localeCompare is not a function` on a number-typed timestamp (inside .then →
// swallowed into the error banner, blanking the live list).
vi.mock("../src/api/http", () => ({
  getSurfacedFindings: vi.fn().mockResolvedValue({
    findings: [
      { finding_id: "p1", title: "number ts A", promoted_at: 1718000000000 },
      { finding_id: "p2", title: "number ts B", promoted_at: 1718000999999 },
    ],
  }),
}));

// Combined module-level teardown (merged from the r2 and fuzz suites, which
// each registered a file-wide afterEach): clean up the DOM and restore spies
// after every test. vi.restoreAllMocks restores vi.spyOn spies; it does not
// undo the hoisted vi.mock module factory, so the http mock stays in place.
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// HARDENING r1 (edge-case category: missing/null/undefined optional fields +
// entirely-absent nested objects) for SurfacedFindingsPanel.
//
// memory/surfaced_findings.jsonl is producer-owned and unvalidated — a legacy
// or partially-written row may arrive with fields null/undefined or simply
// absent. The panel must never crash the page or emit a React console.error/
// warn on such a row. The no-headless-browser stand-in for "renders without
// console errors" is the test_validate_panels_empty / test_source_badge idiom:
// jsdom render + a console.error/warn spy asserted not-called. The `initial`
// prop bypasses polling so these render synchronously from constructed inputs.
//
// The constructed rows are what a real JSONL producer could plausibly emit:
//   - a fully-empty {} row (no finding_id/title/promoted_at — pre-EMIT legacy);
//   - a row with every optional field explicitly null;
//   - a row whose only content is a title (finding_id/badges/iteration absent);
// MULTIPLE finding_id-less rows specifically probe the React key path: a row
// without finding_id must still get a stable, unique key (else "two children
// with the same key" lands on console.error — a real crash-the-render warning).
// ---------------------------------------------------------------------------

// Two finding_id-less, title-less rows + one null-everywhere row + one
// title-only row. `as SurfacedFinding[]` because a real producer is not bound
// by the TS optionality — the point is to hand the panel under-specified data.
const PARTIAL_ROWS = [
  {}, // fully empty — pre-EMIT/legacy line with nothing the panel keys on
  {}, // a SECOND empty row — exercises the duplicate-key path on missing id
  {
    finding_id: null,
    source_iteration_id: null,
    title: null,
    claim: null,
    novelty_class: null,
    critic_verdict: null,
    why_it_matters: null,
    status: null,
    promoted_at: null,
  },
  { title: "A title with no id, no badges, no iteration, no timestamp" },
] as unknown as SurfacedFinding[];

describe("SurfacedFindingsPanel hardening — r1 (missing/null/absent fields)", () => {
  describe("SurfacedFindingsPanel — hardening r1 (missing/null/absent fields)", () => {
    it("renders partial/legacy rows without crashing or a console error/warn", () => {
      const { errSpy, warnSpy } = spyConsole();

      // Must not throw while rendering the under-specified rows.
      expect(() =>
        render(<SurfacedFindingsPanel initial={PARTIAL_ROWS} />),
      ).not.toThrow();

      // The panel itself still mounts (not a blanked surface).
      const panel = within(screen.getByTestId("surfaced-findings-panel"));
      // The row count header reflects the rows it was given.
      expect(screen.getByText(String(PARTIAL_ROWS.length))).toBeInTheDocument();
      // The one legible field still renders (a partial row is shown, not dropped).
      expect(
        panel.getByText("A title with no id, no badges, no iteration, no timestamp"),
      ).toBeInTheDocument();

      // No NaN/undefined leaked into the rendered text.
      expect(panel.queryByText(/NaN/)).toBeNull();

      // The crux of this category: missing finding_id must not produce a React
      // duplicate-key (or any) console.error/warn.
      expect(errSpy).not.toHaveBeenCalled();
      expect(warnSpy).not.toHaveBeenCalled();
    });

    it("renders a single fully-empty row cleanly (no badges, no link, no timestamp crash)", () => {
      const { errSpy, warnSpy } = spyConsole();
      render(<SurfacedFindingsPanel initial={[{} as unknown as SurfacedFinding]} />);

      expect(screen.getByTestId("surfaced-findings-panel")).toBeInTheDocument();
      // The em-dash timestamp fallback, not a NaN/Invalid-Date.
      expect(screen.queryByText(/Invalid Date|NaN/)).toBeNull();
      expect(errSpy).not.toHaveBeenCalled();
      expect(warnSpy).not.toHaveBeenCalled();
    });
  });
});

// ---------------------------------------------------------------------------
// HARDENING r2 (edge-case category: malformed value TYPES) for
// SurfacedFindingsPanel.
//
// memory/surfaced_findings.jsonl is producer-owned and unvalidated. Round 1
// covered missing/null/absent fields; this round covers fields that are PRESENT
// but the WRONG TYPE — what a legacy/partial/buggy producer plausibly emits:
//   - promoted_at as an EPOCH NUMBER (or NaN/Infinity) instead of an ISO string
//     — `shortTimestamp` called `.replace` on it (TypeError: not a function),
//     and the poll-path sort called `.localeCompare` on it (same crash);
//   - title / claim / source_iteration_id / novelty_class / critic_verdict as an
//     OBJECT or ARRAY — rendering an object as a React child throws "Objects are
//     not valid as a React child", which blanks the WHOLE Dashboard, not the row.
// Pre-fix, the first two threw at render; this test pins the defensive coercion
// (asText + String()-guarded sort) so one bad-typed field can never crash the
// page or leak NaN/[object Object] into the text.
//
// No-headless-browser stand-in for "renders without console errors": jsdom
// render + a console.error/warn spy asserted not-called (the r1 / test_source_
// badge idiom). `initial` bypasses polling for the synchronous cases; the final
// case mocks the http layer to drive the live POLL path (the sort) like
// test_validate_panels_empty does.
// ---------------------------------------------------------------------------

// `as unknown as SurfacedFinding[]` — a real producer is not bound by the TS
// optionality; the point is to hand the panel wrong-typed data it must survive.
//   row 0: epoch-number promoted_at (the shortTimestamp .replace crash);
//   row 1: object-valued title (the React-child crash) + object claim/verdict;
//   row 2: array-valued title + array source_iteration_id + numeric badges;
//   row 3: NaN / Infinity / garbage-string timestamps + object finding_id;
//   row 4: EVERY rendered field an object (worst case — must still mount a row).
const MALFORMED_TYPE_ROWS = [
  { finding_id: "f0", title: "epoch ts row", promoted_at: 1718000000000 },
  {
    finding_id: "f1",
    title: { text: "title-as-object" },
    claim: { text: "claim-as-object" },
    novelty_class: { class: "novel" },
    critic_verdict: { verdict: "survives" },
    promoted_at: "2026-06-09T13:20:00Z",
  },
  {
    finding_id: "f2",
    title: ["array", "title"],
    source_iteration_id: ["iter", "as", "array"],
    novelty_class: 7,
    critic_verdict: true,
    promoted_at: "2026-06-09T12:00:00Z",
  },
  {
    finding_id: { id: "object-finding-id" },
    title: "non-finite ts row",
    promoted_at: NaN,
  },
  {
    finding_id: { a: 1 },
    title: { b: 2 },
    claim: { c: 3 },
    source_iteration_id: { d: 4 },
    novelty_class: { e: 5 },
    critic_verdict: { f: 6 },
    promoted_at: { g: 7 },
  },
] as unknown as SurfacedFinding[];

describe("SurfacedFindingsPanel hardening — r2 (malformed value TYPES)", () => {
  describe("SurfacedFindingsPanel — hardening r2 (malformed value TYPES)", () => {
    it("renders wrong-typed rows without throwing or a console error/warn", () => {
      const { errSpy, warnSpy } = spyConsole();

      // Pre-fix this threw (TypeError on epoch .replace; React-child on object
      // title). The whole panel — every row — must survive one bad-typed field.
      expect(() =>
        render(<SurfacedFindingsPanel initial={MALFORMED_TYPE_ROWS} />),
      ).not.toThrow();

      // The panel mounted (not a blanked surface) and counts every row it was
      // handed — a malformed row is shown degraded, not silently dropped.
      const panel = within(screen.getByTestId("surfaced-findings-panel"));
      expect(
        screen.getByText(String(MALFORMED_TYPE_ROWS.length)),
      ).toBeInTheDocument();

      // The one cleanly-typed scalar row still renders its title.
      expect(panel.getByText("epoch ts row")).toBeInTheDocument();

      // No coercion artifact leaked into the rendered text: an object field is
      // dropped (not "[object Object]"), a non-finite/garbage timestamp falls back
      // to the em-dash (not NaN / Invalid Date).
      const txt = screen.getByTestId("surfaced-findings-panel").textContent ?? "";
      expect(txt).not.toMatch(/\[object Object\]/);
      expect(txt).not.toMatch(/NaN/);
      expect(txt).not.toMatch(/Invalid Date/);

      // The crux: no render-time throw, duplicate-key, or act() warning.
      expect(errSpy).not.toHaveBeenCalled();
      expect(warnSpy).not.toHaveBeenCalled();
    });

    it("renders a lone epoch-number timestamp row without an Invalid-Date/NaN crash", () => {
      const { errSpy, warnSpy } = spyConsole();
      render(
        <SurfacedFindingsPanel
          initial={
            [
              { finding_id: "solo", title: "t", promoted_at: 1718000000000 },
            ] as unknown as SurfacedFinding[]
          }
        />,
      );
      expect(screen.getByTestId("surfaced-findings-panel")).toBeInTheDocument();
      expect(screen.queryByText(/Invalid Date|NaN/)).toBeNull();
      expect(errSpy).not.toHaveBeenCalled();
      expect(warnSpy).not.toHaveBeenCalled();
    });
  });

  // Separate describe so vi.mock isolates the POLL path: with no `initial` prop
  // the panel polls getSurfacedFindings and runs the promoted_at sort, which
  // pre-fix threw `localeCompare is not a function` on a number-typed timestamp
  // (inside .then → swallowed into the error banner, blanking the live list).
  // [The hoisted vi.mock + module-level afterEach that originally lived here are
  // consolidated at the top of this merged file.]
  describe("SurfacedFindingsPanel — hardening r2 (poll-path number-typed sort)", () => {
    it("sorts number-typed promoted_at without crashing the live list", async () => {
      const { errSpy, warnSpy } = spyConsole();
      render(<SurfacedFindingsPanel pollMs={100000} />);

      // The rows render (the sort did not throw into the catch → no error banner).
      await waitFor(() =>
        expect(screen.getByText("number ts A")).toBeInTheDocument(),
      );
      const panel = within(screen.getByTestId("surfaced-findings-panel"));
      expect(panel.getByText("number ts B")).toBeInTheDocument();
      expect(panel.queryByText(/Error|TypeError|localeCompare/)).toBeNull();
      expect(errSpy).not.toHaveBeenCalled();
      expect(warnSpy).not.toHaveBeenCalled();
    });
  });
});

// ---------------------------------------------------------------------------
// HARDENING r4 (edge-case category: UNKNOWN / forward-compatible enum values)
// for SurfacedFindingsPanel.
//
// memory/surfaced_findings.jsonl is producer-owned and unvalidated. Rounds 1/2
// covered missing/null fields and wrong value TYPES; this round covers a value
// that is a well-typed string but an UNKNOWN enum — a novel novelty_class /
// critic_verdict a future EMIT (e.g. a "nemoclaw_agent" producer) could write.
//
// The generic case (a never-seen string like "wildly_novel") was already safe:
// the tone palette's `?? generic` fallback renders the badge with the quiet
// zinc tone and the enum string as its label. The SHARP case this round pins:
// an unknown enum whose string value COLLIDES with an inherited
// Object.prototype member name ("toString"/"constructor"/"valueOf"/
// "hasOwnProperty"/"__proto__"). A bare `NOVELTY_TONE[value]` resolves to a
// FUNCTION via the prototype chain instead of undefined, so the `?? generic`
// fallback is bypassed and that function interpolates into className as
// "function toString() { [native code] }" — the badge loses its quiet fallback
// and lands garbage CSS tokens in the DOM. The fix (own-key-only lookup via
// Object.prototype.hasOwnProperty.call, mirroring SourceBadge.sourceTone /
// CoordinatorCycleCard.statusTone) degrades any prototype collision to the
// quiet zinc tone. This test pins both the generic and the prototype-key path.
//
// No-headless-browser stand-in for "renders without console errors": jsdom
// render + a console.error/warn spy asserted not-called (the r1/r2 idiom).
// `initial` bypasses polling so these render synchronously from constructed
// rows; `as unknown as SurfacedFinding[]` because a real producer is not bound
// by the TS enum unions — the point is to hand the panel a never-seen value.
// ---------------------------------------------------------------------------

// row 0: an ordinary never-seen enum (the generic-fallback path);
// row 1: novelty_class === "toString" — the inherited-fn prototype collision;
// row 2: critic_verdict === "constructor" + novelty_class === "hasOwnProperty"
//        — two more Object.prototype keys, the worst of the collision set;
// row 3: status === a never-seen value (not rendered, but must not perturb).
const UNKNOWN_ENUM_ROWS = [
  {
    finding_id: "u0",
    title: "nemoclaw-emitted finding",
    novelty_class: "wildly_novel",
    critic_verdict: "deferred",
    status: "quarantined",
    source_iteration_id: "iter-nemoclaw-0",
    promoted_at: "2026-06-09T13:20:00Z",
  },
  {
    finding_id: "u1",
    title: "toString-as-novelty-class",
    novelty_class: "toString",
    critic_verdict: "valueOf",
    promoted_at: "2026-06-09T12:10:00Z",
  },
  {
    finding_id: "u2",
    title: "prototype-key verdict",
    novelty_class: "hasOwnProperty",
    critic_verdict: "constructor",
    promoted_at: "2026-06-09T12:00:00Z",
  },
] as unknown as SurfacedFinding[];

describe("SurfacedFindingsPanel hardening — r4 (unknown / forward-compat enums)", () => {
  describe("SurfacedFindingsPanel — hardening r4 (unknown / forward-compat enums)", () => {
    it("renders an unrecognized novelty_class/critic_verdict generically, no console error", () => {
      const { errSpy, warnSpy } = spyConsole();

      expect(() =>
        render(<SurfacedFindingsPanel initial={UNKNOWN_ENUM_ROWS} />),
      ).not.toThrow();

      const panel = within(screen.getByTestId("surfaced-findings-panel"));
      // Every row mounted (a novel enum is shown, never dropped) and the unknown
      // enum strings render as their own badge labels.
      expect(screen.getByText(String(UNKNOWN_ENUM_ROWS.length))).toBeInTheDocument();
      expect(panel.getByText("wildly_novel")).toBeInTheDocument();
      expect(panel.getByText("deferred")).toBeInTheDocument();
      expect(panel.getByText("nemoclaw-emitted finding")).toBeInTheDocument();

      // No coercion/lookup artifact leaked into the rendered text.
      const txt = screen.getByTestId("surfaced-findings-panel").textContent ?? "";
      expect(txt).not.toMatch(/\[object Object\]/);
      expect(txt).not.toMatch(/NaN/);

      // The crux: no render-time throw, duplicate-key, or act() warning.
      expect(errSpy).not.toHaveBeenCalled();
      expect(warnSpy).not.toHaveBeenCalled();
    });

    it("renders an enum value that collides with an Object.prototype key as the quiet tone, not a function-in-className", () => {
      const { errSpy, warnSpy } = spyConsole();
      render(<SurfacedFindingsPanel initial={UNKNOWN_ENUM_ROWS} />);

      const panel = within(screen.getByTestId("surfaced-findings-panel"));
      // The "toString" novelty_class still renders as a badge label...
      const protoBadge = panel.getByText("toString");
      // ...and the CRUX: its className is a clean string of class tokens (the
      // quiet zinc fallback), NOT a stringified function from the prototype chain.
      const cls = protoBadge.getAttribute("class") ?? "";
      expect(cls).not.toMatch(/function|native code|=>|\{|\}/);
      expect(cls).toContain("bg-zinc-800"); // degraded to the quiet generic tone

      // No prototype-fn source leaked anywhere into the panel's class attributes
      // or text (e.g. "function toString() { [native code] }").
      const html = screen.getByTestId("surfaced-findings-panel").outerHTML;
      expect(html).not.toMatch(/native code/);
      expect(html).not.toMatch(/function (toString|valueOf|constructor|hasOwnProperty)/);

      expect(errSpy).not.toHaveBeenCalled();
      expect(warnSpy).not.toHaveBeenCalled();
    });
  });
});

// ---------------------------------------------------------------------------
// HARDENING r5 (edge-case category: empty-vs-absent collections + boundary
// numbers) for SurfacedFindingsPanel.
//
// memory/surfaced_findings.jsonl is producer-owned and unvalidated. Rounds 1/2/4
// covered missing/null fields, wrong value TYPES, and unknown enums. This round
// covers the empty-vs-ABSENT distinction and boundary list sizes — a producer
// writing `title:""` (an EMPTY STRING, deliberately distinct from absent/null),
// an all-falsy row, a single-element list, and a large list.
//
// The sharp bug this round pinned: `asText("")` keeps "" (a string is a
// string), and the old primary-line fallback used `??`, which coalesces only on
// null — so `asText(title:"") ?? asText(claim)` kept the "" and SUPPRESSED a
// real claim. A finding with an empty title but a real claim rendered an EMPTY
// content div: the row's only legible field vanished (absence-illegible — the
// exact failure the autonomy-observability work exists to prevent). The fix
// (`firstText`, coalescing on truthiness like the Badge `if (!label)` idiom)
// falls an empty/whitespace string through to the next legible field.
//
// No-headless-browser stand-in for "renders without console errors": jsdom
// render + a console.error/warn spy asserted not-called (the r1/r2/r4 idiom).
// `initial` bypasses polling so these render synchronously from constructed
// rows; `as unknown as SurfacedFinding[]` because a real producer is not bound
// by the TS optionality — the point is to hand the panel boundary data.
// ---------------------------------------------------------------------------

// row 0: empty-string title + a REAL claim — the headline empty-vs-absent bug
//        (the "" must fall through to the claim, not blank the row);
// row 1: empty title + empty claim + only a finding_id — all-falsy-but-id, the
//        id is the last-resort primary line (not a blank row);
// row 2: whitespace-only title + a real claim — a "   " is not legible content,
//        falls through like an empty string;
// row 3: empty-string EVERYTHING (incl. finding_id) — the fully-falsy row; it
//        must still mount (counted) without a blank-but-present artifact crash;
// row 4: empty-string badges + empty source_iteration_id — empty enum strings
//        drop their badges/link (the `if (!label)` / `&&` paths), no blank chip.
const EMPTY_VS_ABSENT_ROWS = [
  {
    finding_id: "e0",
    title: "",
    claim: "Level-k convergence refines Nagel — the real claim text",
    promoted_at: "2026-06-09T13:00:00Z",
  },
  {
    finding_id: "iter-only-id-e1",
    title: "",
    claim: "",
    promoted_at: "2026-06-09T12:50:00Z",
  },
  {
    finding_id: "e2",
    title: "   ",
    claim: "Whitespace title must not hide this claim",
    promoted_at: "2026-06-09T12:40:00Z",
  },
  {
    finding_id: "",
    title: "",
    claim: "",
    source_iteration_id: "",
    novelty_class: "",
    critic_verdict: "",
    promoted_at: "",
  },
  {
    finding_id: "e4",
    title: "row with empty badges + empty iteration link",
    novelty_class: "",
    critic_verdict: "",
    source_iteration_id: "",
    promoted_at: "2026-06-09T12:20:00Z",
  },
] as unknown as SurfacedFinding[];

describe("SurfacedFindingsPanel hardening — r5 (empty-vs-absent + boundary lists)", () => {
  describe("SurfacedFindingsPanel — hardening r5 (empty-vs-absent + boundary lists)", () => {
    it("an empty-string title falls through to the real claim (not a blank row)", () => {
      const { errSpy, warnSpy } = spyConsole();

      expect(() =>
        render(<SurfacedFindingsPanel initial={EMPTY_VS_ABSENT_ROWS} />),
      ).not.toThrow();

      const panel = within(screen.getByTestId("surfaced-findings-panel"));
      // The crux: title:"" did NOT blank the row — the real claim is on screen.
      expect(
        panel.getByText("Level-k convergence refines Nagel — the real claim text"),
      ).toBeInTheDocument();
      // A whitespace-only title likewise falls through to its claim.
      expect(
        panel.getByText("Whitespace title must not hide this claim"),
      ).toBeInTheDocument();

      // Every row is counted — a fully-falsy row is shown (degraded), not dropped.
      expect(
        screen.getByText(String(EMPTY_VS_ABSENT_ROWS.length)),
      ).toBeInTheDocument();

      // No coercion/empty-string artifact leaked into the text.
      const txt = screen.getByTestId("surfaced-findings-panel").textContent ?? "";
      expect(txt).not.toMatch(/\[object Object\]/);
      expect(txt).not.toMatch(/NaN/);
      expect(txt).not.toMatch(/undefined/);

      // The crux: no render-time throw, duplicate-key, or act() warning.
      expect(errSpy).not.toHaveBeenCalled();
      expect(warnSpy).not.toHaveBeenCalled();
    });

    it("an all-empty row (incl. empty finding_id) mounts cleanly, no duplicate-key warn", () => {
      const { errSpy, warnSpy } = spyConsole();
      // Two all-empty-finding_id rows specifically probe the React key path: an
      // empty-string finding_id must still yield a stable, unique key (the index
      // suffix), not a "two children with the same key" console.error.
      const allEmpty = [
        { finding_id: "", title: "", claim: "", promoted_at: "" },
        { finding_id: "", title: "", claim: "", promoted_at: "" },
      ] as unknown as SurfacedFinding[];
      render(<SurfacedFindingsPanel initial={allEmpty} />);

      expect(screen.getByTestId("surfaced-findings-panel")).toBeInTheDocument();
      // The em-dash timestamp fallback, never a NaN / Invalid Date / blank chip.
      expect(screen.queryByText(/Invalid Date|NaN/)).toBeNull();
      // Both rows are counted (not collapsed away by an empty key).
      expect(screen.getByText("2")).toBeInTheDocument();
      expect(errSpy).not.toHaveBeenCalled();
      expect(warnSpy).not.toHaveBeenCalled();
    });

    it("an empty findings list shows the clean empty state, not a blank gap", () => {
      const { errSpy, warnSpy } = spyConsole();
      render(<SurfacedFindingsPanel initial={[]} />);
      expect(screen.getByTestId("findings-empty")).toBeInTheDocument();
      expect(screen.getByText("0")).toBeInTheDocument(); // count tile reads zero
      expect(errSpy).not.toHaveBeenCalled();
      expect(warnSpy).not.toHaveBeenCalled();
    });

    it("a large list (boundary count) renders every row with no key/count drift", () => {
      const { errSpy, warnSpy } = spyConsole();
      // A producer that has surfaced many findings: confirm the count tile and the
      // index-suffixed keys hold at size, with no divide/NaN (there is no
      // arithmetic in render, but the count must equal the list length exactly).
      const N = 250;
      const big = Array.from({ length: N }, (_, i) => ({
        finding_id: `bulk-${i}`,
        title: `finding ${i}`,
        promoted_at: `2026-06-09T10:${String(i % 60).padStart(2, "0")}:00Z`,
      })) as unknown as SurfacedFinding[];
      render(<SurfacedFindingsPanel initial={big} />);

      expect(screen.getByText(String(N))).toBeInTheDocument();
      // First and last rows both present (the list rendered end-to-end).
      const panel = within(screen.getByTestId("surfaced-findings-panel"));
      expect(panel.getByText("finding 0")).toBeInTheDocument();
      expect(panel.getByText(`finding ${N - 1}`)).toBeInTheDocument();
      expect(errSpy).not.toHaveBeenCalled();
      expect(warnSpy).not.toHaveBeenCalled();
    });
  });
});

// ---------------------------------------------------------------------------
// PROPERTY-FUZZ for SurfacedFindingsPanel.
//
// memory/surfaced_findings.jsonl is producer-owned and unvalidated
// (orchestrator/finding_promotion.py appends it; only finding_promotion writes
// it, but the panel must survive legacy/partial/buggy lines too). The hand-
// written hardening rounds enumerate edge categories ONE AT A TIME — r1
// missing/null, r2 wrong-typed, r4 unknown/prototype-collision enums, r5
// empty-vs-absent + boundary lists. This fuzz pass instead SWEEPS ~50 rows that
// COMBINE those dimensions simultaneously, in permutations the enumerated cases
// don't reach, and — the genuinely new coverage — feeds the NESTED object shape
// the real producer actually writes (`evidence`, `adversarial` with a
// `refutation_summaries` array, `tier:null`) alongside the scalar fields the
// panel renders. The SurfacedFinding type declares only the rendered scalars, so
// those nested objects ride in via the index signature; rendering must ignore
// them, never throw on them.
//
// DETERMINISM: every row is a pure function of its loop index `i` — no RNG
// source is called (no Math.random / crypto / Date.now). A small integer hash of
// `i` picks each field's variant, so a failure reproduces exactly from the index
// printed in the assertion. Each row varies presence/absence, type, and length
// of every optional field independently.
//
// No-headless-browser stand-in for "renders without console errors" (the
// r1/r2/r4/r5 idiom): jsdom render + a console.error/warn spy asserted
// not-called — a render-time throw, a "two children with the same key" warning,
// or an act() warning all land on console.error in jsdom. The `initial` prop
// bypasses polling so each row renders synchronously. `as unknown as
// SurfacedFinding[]` because a real producer is not bound by the TS optionality
// — the point is to hand the panel data the types forbid but the disk allows.
// [The cleanup/restoreAllMocks afterEach that originally lived here is
// consolidated at the top of this merged file.]
// ---------------------------------------------------------------------------

const ROW_COUNT = 50;

// Deterministic non-negative integer "hash" of (i, salt) — a cheap LCG-style
// mix so different fields of the same row pick independent variants while every
// value stays a pure function of the loop index (NO RNG source is touched).
function pick(i: number, salt: number, mod: number): number {
  const h = ((i + 1) * 2654435761 + salt * 40503 + 0x9e3779b9) >>> 0;
  return h % mod;
}

// A grab-bag of values that span the kinds a malformed/forward-compat producer
// could emit for any field: well-typed strings (incl. empty/whitespace, an
// Object.prototype-key collision, a never-seen enum, a very long string, unicode),
// scalars (number/finite-edge/boolean), and the FATAL-IF-RENDERED shapes
// (object, array, nested) the panel must DROP rather than render as a child.
const STRING_VARIANTS: unknown[] = [
  "novel",
  "rediscovery",
  "survives",
  "falsified",
  "wildly_novel_2027", // forward-compat unknown enum (the nemoclaw case)
  "toString", // collides with Object.prototype — must degrade to quiet tone
  "constructor",
  "", // empty string — must not blank a row that has another legible field
  "   ", // whitespace-only — same fall-through requirement
  "a".repeat(4000), // pathological length — must not break layout/crash
  "πβ-truthfulness ≈ Nagel(1995) ✦ — résumé", // unicode / combining marks
];

const SCALAR_VARIANTS: unknown[] = [
  0,
  -1,
  42,
  3.14159,
  Number.NaN, // non-finite — asText must drop, never leak "NaN"
  Number.POSITIVE_INFINITY,
  Number.NEGATIVE_INFINITY,
  true,
  false,
];

// The shapes that THROW if handed to React as a child — the panel must drop
// them. Includes the real producer's nested blocks (`evidence`, `adversarial`).
const OBJECT_VARIANTS: unknown[] = [
  {},
  { text: "object-with-a-text-field" },
  ["array", "of", "strings"],
  [1, 2, 3],
  [],
  { nested: { deeply: { value: "x" } } },
  // The real surfaced-finding nested blocks (schema/surfaced_finding.schema.json):
  // a producer that wrote the WHOLE row into one field, or a panel that wrongly
  // tried to render `evidence`/`adversarial`, would hit these — drop, don't throw.
  {
    journal_entry_path: "journal/iterations/007.md",
    results_path: null,
    experiment_outcome: null,
    critic_rationale: "survives independent attack",
    novelty_rationale: "no close neighbor",
    human_verdict: null,
  },
  {
    model: "qwen3.6-27b",
    backend: "vllm-qwen",
    n_skeptics: 3,
    n_voting: 3,
    n_refuted: 0,
    adversarial_margin: 3,
    survived: true,
    qwen_failures: 0,
    refutation_summaries: ["weak attack A", "weak attack B"],
  },
  null,
  undefined,
];

// For each field, choose: ABSENT (key omitted), or a value drawn from one of the
// variant pools. `salt` keeps a field's choice independent of its siblings, and
// `absentMod` tunes how often the key is omitted entirely (a real legacy row).
function fieldValue(
  row: Record<string, unknown>,
  key: string,
  i: number,
  salt: number,
  pools: unknown[][],
  absentMod: number,
): void {
  if (pick(i, salt, absentMod) === 0) return; // omit the key entirely
  const pool = pools[pick(i, salt + 1, pools.length)];
  row[key] = pool[pick(i, salt + 2, pool.length)];
}

// Build one deterministic, plausibly-shaped-but-adversarial row from its index.
function fuzzRow(i: number): Record<string, unknown> {
  const row: Record<string, unknown> = {};

  // finding_id drives the React key. Vary it across present-string / absent /
  // wrong-typed / EMPTY / DUPLICATE-with-a-neighbor so the index-suffixed key
  // path (`${finding_id ?? "finding"}-${i}`) is exercised against collisions.
  const idKind = pick(i, 1, 6);
  if (idKind === 0) row.finding_id = `sf-iter-${i}`;
  else if (idKind === 1) {
    /* absent — exercises the "finding" key fallback + index suffix */
  } else if (idKind === 2) row.finding_id = ""; // empty string id
  else if (idKind === 3) row.finding_id = "dup-id"; // deliberate duplicate across rows
  else if (idKind === 4) row.finding_id = 12345; // wrong-typed id
  else row.finding_id = null;

  // Each rendered field independently: present (any variant) / absent / wrong-
  // typed / object. Different salts = independent choices per field.
  fieldValue(row, "title", i, 10, [STRING_VARIANTS, SCALAR_VARIANTS, OBJECT_VARIANTS], 5);
  fieldValue(row, "claim", i, 20, [STRING_VARIANTS, SCALAR_VARIANTS, OBJECT_VARIANTS], 4);
  fieldValue(row, "source_iteration_id", i, 30, [STRING_VARIANTS, SCALAR_VARIANTS, OBJECT_VARIANTS], 3);
  fieldValue(row, "novelty_class", i, 40, [STRING_VARIANTS, SCALAR_VARIANTS, OBJECT_VARIANTS], 3);
  fieldValue(row, "critic_verdict", i, 50, [STRING_VARIANTS, SCALAR_VARIANTS, OBJECT_VARIANTS], 3);
  fieldValue(row, "why_it_matters", i, 60, [STRING_VARIANTS, OBJECT_VARIANTS], 3);
  fieldValue(row, "status", i, 70, [STRING_VARIANTS, SCALAR_VARIANTS], 3);

  // promoted_at drives shortTimestamp (.replace) AND the poll-path sort
  // (.localeCompare); vary ISO string / epoch number / non-finite / object /
  // absent so both code paths see every shape.
  const tsKind = pick(i, 80, 6);
  if (tsKind === 0) row.promoted_at = `2026-06-09T1${i % 10}:${String(i % 60).padStart(2, "0")}:00Z`;
  else if (tsKind === 1) row.promoted_at = 1718000000000 + i * 1000; // epoch number
  else if (tsKind === 2) row.promoted_at = Number.NaN;
  else if (tsKind === 3) row.promoted_at = { when: "2026-06-09" }; // object ts
  else if (tsKind === 4) row.promoted_at = ""; // empty string ts
  /* tsKind === 5: absent */

  // Ride-along nested producer blocks the panel does NOT render but that exist
  // on every real row — confirm their mere presence is inert (index signature).
  if (pick(i, 90, 2) === 0) row.tier = null;
  if (pick(i, 91, 3) === 0) {
    row.evidence = OBJECT_VARIANTS[6]; // the real evidence block
    row.adversarial = OBJECT_VARIANTS[7]; // the real adversarial block
  }

  return row;
}

const FUZZ_ROWS = Array.from({ length: ROW_COUNT }, (_, i) =>
  fuzzRow(i),
) as unknown as SurfacedFinding[];

// Compact, throw-safe one-line shape of a fuzz row for failure messages (a row
// may carry circular-free but non-serializable values; guard JSON.stringify).
function safeShape(row: unknown): string {
  try {
    return JSON.stringify(row, (_k, v) =>
      typeof v === "number" && !Number.isFinite(v) ? `<${String(v)}>` : v,
    ).slice(0, 300);
  } catch {
    return "<unserializable row>";
  }
}

describe("SurfacedFindingsPanel hardening — fuzz (combined malformed shapes)", () => {
  describe("SurfacedFindingsPanel — property fuzz (combined malformed shapes)", () => {
    // Each row in isolation: a single bad row must never crash the panel, and the
    // failing index is reported so a crasher reproduces deterministically.
    it("renders each of ~50 fuzzed rows alone without throwing or a console error", () => {
      for (let i = 0; i < ROW_COUNT; i++) {
        const { errSpy, warnSpy } = spyConsole();
        const row = FUZZ_ROWS[i];

        expect(
          () => render(<SurfacedFindingsPanel initial={[row]} />),
          `row ${i} threw on render: ${safeShape(row)}`,
        ).not.toThrow();

        // The panel mounted (a malformed row is shown degraded, never a blank gap).
        expect(
          screen.queryByTestId("surfaced-findings-panel"),
          `row ${i} did not mount the panel`,
        ).not.toBeNull();

        // No coercion artifact leaked into the rendered text — an object/array
        // field is DROPPED (not "[object Object]"), a non-finite ts falls back to
        // the em-dash (not NaN / Invalid Date), and nothing renders "undefined".
        const txt = screen.getByTestId("surfaced-findings-panel").textContent ?? "";
        expect(txt, `row ${i} leaked [object Object]: ${safeShape(row)}`).not.toMatch(
          /\[object Object\]/,
        );
        expect(txt, `row ${i} leaked NaN`).not.toMatch(/NaN/);
        expect(txt, `row ${i} leaked Invalid Date`).not.toMatch(/Invalid Date/);
        expect(txt, `row ${i} leaked literal undefined`).not.toMatch(/undefined/);

        // The crux: no render-time throw, duplicate-key, or act() warning for
        // THIS row (the no-headless-browser clean-render stand-in).
        expect(errSpy, `row ${i} hit console.error: ${safeShape(row)}`).not.toHaveBeenCalled();
        expect(warnSpy, `row ${i} hit console.warn: ${safeShape(row)}`).not.toHaveBeenCalled();

        cleanup();
        vi.restoreAllMocks();
      }
    });

    // All ~50 rows together: stresses the React key path (duplicate/empty/absent
    // finding_ids in one list must each get a unique index-suffixed key — no
    // "two children with the same key" console.error) and the count tile.
    it("renders all ~50 fuzzed rows together with unique keys and an exact count", () => {
      const { errSpy, warnSpy } = spyConsole();

      expect(() =>
        render(<SurfacedFindingsPanel initial={FUZZ_ROWS} />),
      ).not.toThrow();

      // Every row is counted — none silently dropped or key-collapsed.
      expect(screen.getByText(String(ROW_COUNT))).toBeInTheDocument();

      const txt = screen.getByTestId("surfaced-findings-panel").textContent ?? "";
      expect(txt).not.toMatch(/\[object Object\]/);
      expect(txt).not.toMatch(/NaN/);
      expect(txt).not.toMatch(/Invalid Date/);

      // The duplicate "dup-id" finding_ids across rows must NOT trip React's
      // same-key warning (the index suffix disambiguates them).
      expect(errSpy).not.toHaveBeenCalled();
      expect(warnSpy).not.toHaveBeenCalled();
    });
  });
});
