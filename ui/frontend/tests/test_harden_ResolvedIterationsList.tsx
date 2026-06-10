// Consolidated edge-case + property-fuzz hardening for ResolvedIterationsList (merged from per-round files).
//
// Merged from test_harden_ResolvedIterationsList_r{1,2,4,5,6}.tsx. Each source
// file's body is preserved verbatim inside its own top-level describe() block so
// describe/it names and per-file helpers never collide. Every it()/test() case
// and assertion is kept exactly as authored.
//
// NOTE ON SCOPING: each round defined module-level helpers that collide by name
// (HEALTHY ×4 with identical bodies; expectSurvives ×3 where r2's body differs
// from r4/r5's; a top-level afterEach in r1/r2/r4/r5). To keep every test's
// original setup intact, each round's helpers + its afterEach live INSIDE that
// round's describe block. The single exception is r6's `vi.mock("../src/api/http")`
// and its module-mutable RESPONSE: vitest hoists vi.mock to the top of the module,
// so it must stay at module scope. Rounds r1/r2/r4/r5 drive the synchronous
// `initial=` prop, which short-circuits the component's fetch useEffect
// (ResolvedIterationsList.tsx: `if (initial !== undefined) return;`), so the
// mocked getIterations is never invoked by them — the mock is exercised only by
// r6, which omits `initial`.

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ResolvedIterationsList from "../src/components/ResolvedIterationsList";
import type { IterationRecord } from "../src/types/schemas";

// ---------------------------------------------------------------------------
// Module-scoped mock from round 6. vi.mock is hoisted to the top of the module
// by vitest, so the api/http mock and the RESPONSE it reads cannot be nested
// inside a describe. RESPONSE is reset in r6's afterEach. Rounds r1/r2/r4/r5
// never trigger the fetch path (they pass `initial=`), so this mock is inert
// for them.
// ---------------------------------------------------------------------------
let RESPONSE: unknown = { iterations: [] };
vi.mock("../src/api/http", () => ({
  getIterations: vi.fn(() => Promise.resolve(RESPONSE)),
}));

// ===========================================================================
// Round 1 (edge-case category): missing / null / undefined optional fields +
// entirely-absent nested objects, AND nested fields present-but-malformed
// (wrong runtime type). loop_memory.jsonl is producer-owned and may carry
// partial, legacy, or malformed rows; a single bad row must NEVER crash the
// whole Resolved-iterations list, print NaN, blank the surface, or log a React
// console error/warn.
//
// The existing suite (test_resolved_iterations_list.tsx) already covers the
// sparse-but-type-conformant cases (missing ended_at / novelty / critique /
// redteam / meta_review). What was NOT covered: a nested optional that is
// PRESENT but the wrong type — the case a buggy/legacy producer actually emits.
// Headline: meta_review.conditioning_bullets emitted as a bare string (not a
// list) made the row's .map() throw and took the entire page down.
// ===========================================================================
describe("ResolvedIterationsList hardening — r1: malformed/partial rows never crash the page", () => {
  // A fully-populated, healthy control row so we can prove the GOOD rows still
  // render when a sibling row is malformed (skip-the-bad-row, never blank-all).
  const HEALTHY: IterationRecord = {
    iteration_id: "iter-healthy",
    started_at: "2026-06-09T10:00:00Z",
    ended_at: "2026-06-09T10:05:00Z",
    seed: { topic: "healthy control row", source: "human" },
    novelty: { class: "novel" },
    critique: { verdict: "survives" },
    journal_entry_path: "journal/iterations/healthy.md",
  };

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("survives an entirely-absent-nested-objects row (only the required keys)", () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    // A pre-2026-06-09 legacy row: no seed/novelty/critique/retrieval/
    // meta_review/redteam/gate_status/process_status at all. Cast through
    // unknown because a real JSONL producer is not bound by the TS type.
    const bare = {
      iteration_id: "iter-legacy-bare",
      started_at: "2026-05-01T10:00:00Z",
      ended_at: "2026-05-01T10:05:00Z",
      journal_entry_path: "journal/iterations/legacy.md",
    } as unknown as IterationRecord;

    render(<ResolvedIterationsList initial={[bare, HEALTHY]} />);

    expect(
      screen.getByLabelText(/load journal iter-legacy-bare/),
    ).toBeInTheDocument();
    // the healthy sibling still renders — the bad row didn't blank the surface.
    expect(
      screen.getByLabelText(/load journal iter-healthy/),
    ).toBeInTheDocument();
    expect(errorSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("survives conditioning_bullets emitted as a bare string instead of a list", () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    // Producer bug: meta_review.conditioning_bullets is a string. `.length`
    // is then the string length (truthy) and the component used to call
    // `.map` on it → "x.map is not a function" → the whole list crashed.
    const badBullets = {
      iteration_id: "iter-badbullets",
      started_at: "2026-06-09T11:00:00Z",
      ended_at: "2026-06-09T11:05:00Z",
      seed: { topic: "string bullets row", source: "coordinator" },
      novelty: { class: "novel" },
      critique: { verdict: "survives" },
      meta_review: { conditioning_bullets: "carried one bullet as a string" },
      journal_entry_path: "journal/iterations/badbullets.md",
    } as unknown as IterationRecord;

    render(<ResolvedIterationsList initial={[badBullets, HEALTHY]} />);

    // the row renders rather than throwing, and the healthy sibling survives.
    expect(
      screen.getByLabelText(/load journal iter-badbullets/),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText(/load journal iter-healthy/),
    ).toBeInTheDocument();
    // a non-array conditioning_bullets is treated as "no bullets": the
    // conditioning block is omitted rather than half-rendered.
    expect(screen.queryByTestId("conditioning-iter-badbullets")).toBeNull();
    expect(errorSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("survives meta_review.conditioning_bullets containing null / non-string entries", () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    // The array is the right shape but its entries are junk (null, number,
    // nested object). React can render strings/numbers but NOT a raw object —
    // an object child throws "Objects are not valid as a React child".
    const junkEntries = {
      iteration_id: "iter-junkbullets",
      started_at: "2026-06-09T11:10:00Z",
      ended_at: "2026-06-09T11:15:00Z",
      seed: { topic: "junk bullet entries", source: "coordinator" },
      meta_review: {
        conditioning_bullets: ["ok bullet", null, 42, { nested: "obj" }],
      },
      journal_entry_path: "journal/iterations/junk.md",
    } as unknown as IterationRecord;

    render(<ResolvedIterationsList initial={[junkEntries, HEALTHY]} />);

    expect(
      screen.getByLabelText(/load journal iter-junkbullets/),
    ).toBeInTheDocument();
    // the one good bullet still shows; the junk entries don't crash render.
    const block = screen.queryByTestId("conditioning-iter-junkbullets");
    if (block) {
      expect(within(block).getByText("ok bullet")).toBeInTheDocument();
    }
    expect(
      screen.getByLabelText(/load journal iter-healthy/),
    ).toBeInTheDocument();
    expect(errorSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("survives a non-string seed.topic, including while the topic filter is active", () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    // Producer bug: seed.topic is a number. The topic filter lowercases the
    // topic, so a non-string used to throw `.toLowerCase is not a function`
    // the moment a human typed in the search box.
    const numericTopic = {
      iteration_id: "iter-numtopic",
      started_at: "2026-06-09T11:20:00Z",
      ended_at: "2026-06-09T11:25:00Z",
      seed: { topic: 12345, source: "coordinator" },
      novelty: { class: "novel" },
      critique: { verdict: "survives" },
      journal_entry_path: "journal/iterations/numtopic.md",
    } as unknown as IterationRecord;

    render(<ResolvedIterationsList initial={[numericTopic, HEALTHY]} />);

    // renders cleanly with no filter…
    expect(
      screen.getByLabelText(/load journal iter-numtopic/),
    ).toBeInTheDocument();

    // …and applying a topic filter does not throw on the malformed row.
    fireEvent.change(screen.getByLabelText("search topic"), {
      target: { value: "healthy" },
    });
    expect(
      screen.getByLabelText(/load journal iter-healthy/),
    ).toBeInTheDocument();
    expect(
      screen.queryByLabelText(/load journal iter-numtopic/),
    ).not.toBeInTheDocument();

    expect(errorSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("survives null nested blocks (seed/novelty/critique/meta_review/redteam explicitly null)", () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    // Explicit JSON null (distinct from absent) on every nested block — a
    // producer that writes `"novelty": null` rather than omitting the key.
    const nulls = {
      iteration_id: "iter-nulls",
      started_at: "2026-06-09T12:00:00Z",
      ended_at: "2026-06-09T12:05:00Z",
      seed: null,
      hypothesis: null,
      retrieval: null,
      novelty: null,
      critique: null,
      meta_review: null,
      redteam: null,
      gate_status: null,
      process_status: null,
      journal_entry_path: "journal/iterations/nulls.md",
    } as unknown as IterationRecord;

    render(<ResolvedIterationsList initial={[nulls, HEALTHY]} />);

    expect(
      screen.getByLabelText(/load journal iter-nulls/),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText(/load journal iter-healthy/),
    ).toBeInTheDocument();
    expect(errorSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });
});

// ===========================================================================
// Round 2 (edge-case category): malformed value TYPES.
// loop_memory.jsonl is producer-owned and parsed unchecked — the TS types are a
// compile-time fiction. A legacy/buggy producer can emit a STRING where a number
// is expected (and vice-versa), an OBJECT/ARRAY where a scalar is expected,
// NaN/Infinity numbers, or a garbage non-ISO timestamp. A single such row must
// NEVER throw, print "NaN", blank the whole Resolved-iterations surface, or log a
// React console error/warn — it degrades to "no badge / no timestamp" and the
// healthy sibling rows still render.
//
// What round 1 (test_harden_ResolvedIterationsList_r1.tsx) covered: absent/null
// nested objects, conditioning_bullets as a string / with junk entries, a
// non-string seed.topic. What it did NOT cover, and this file adds: the
// type-confused SCALAR fields on the row's own render path —
//   - ended_at as a number / object  -> shortTimestamp's `.replace` threw
//   - process_status as a number      -> processLabel/processTone's `.startsWith` threw
//   - novelty.class / critique.verdict / gate_status as an object/array
//                                      -> reached React's child renderer and threw
//                                         "Objects are not valid as a React child".
// ===========================================================================
describe("ResolvedIterationsList hardening — r2: malformed value TYPES never crash the page", () => {
  // A fully-populated, healthy control row, so every case proves the GOOD rows
  // still render when a sibling is malformed (skip-the-bad-row, never blank-all).
  const HEALTHY: IterationRecord = {
    iteration_id: "iter-healthy",
    started_at: "2026-06-09T10:00:00Z",
    ended_at: "2026-06-09T10:05:00Z",
    seed: { topic: "healthy control row", source: "human" },
    novelty: { class: "novel" },
    critique: { verdict: "survives" },
    journal_entry_path: "journal/iterations/healthy.md",
  };

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // Render [bad, HEALTHY], assert no throw / no console.error|warn, and that both
  // the bad row and the healthy sibling rendered. Returns the spies so a caller
  // can make extra assertions.
  function expectSurvives(bad: unknown, badId: string) {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    expect(() =>
      render(<ResolvedIterationsList initial={[bad as IterationRecord, HEALTHY]} />),
    ).not.toThrow();

    expect(screen.getByLabelText(new RegExp(`load journal ${badId}`))).toBeInTheDocument();
    // the healthy sibling survives — the bad row didn't blank the surface.
    expect(screen.getByLabelText(/load journal iter-healthy/)).toBeInTheDocument();
    expect(errorSpy, "console.error").not.toHaveBeenCalled();
    expect(warnSpy, "console.warn").not.toHaveBeenCalled();
    return { errorSpy, warnSpy };
  }

  it("survives ended_at emitted as a number (epoch) — no throw, no NaN, no '[object'", () => {
    // Producer bug: ended_at is a Unix-epoch number, not an ISO string.
    // shortTimestamp called `.replace` on it → "iso.replace is not a function".
    const numericEndedAt = {
      iteration_id: "iter-epoch",
      started_at: "2026-06-09T11:00:00Z",
      ended_at: 1717934400,
      seed: { topic: "numeric ended_at", source: "coordinator" },
      novelty: { class: "novel" },
      critique: { verdict: "survives" },
      journal_entry_path: "journal/iterations/epoch.md",
    } as unknown as IterationRecord;

    const { errorSpy } = expectSurvives(numericEndedAt, "iter-epoch");
    // a non-string timestamp degrades to the em-dash placeholder, not NaN/epoch.
    const row = screen.getByLabelText(/load journal iter-epoch/);
    expect(row).toHaveTextContent("—");
    expect(row.textContent).not.toMatch(/NaN/);
    expect(row.textContent).not.toMatch(/1717934400/);
    expect(errorSpy).not.toHaveBeenCalled();
  });

  it("survives ended_at emitted as an object (garbage timestamp shape)", () => {
    const objectEndedAt = {
      iteration_id: "iter-objts",
      started_at: "2026-06-09T11:05:00Z",
      ended_at: { seconds: 1717934400 },
      seed: { topic: "object ended_at", source: "coordinator" },
      journal_entry_path: "journal/iterations/objts.md",
    } as unknown as IterationRecord;

    expectSurvives(objectEndedAt, "iter-objts");
    expect(screen.getByLabelText(/load journal iter-objts/)).toHaveTextContent("—");
  });

  it("survives process_status emitted as a number instead of a status string", () => {
    // Producer/join bug: process_status is a raw exit code (137), not the
    // "exited_error_137" string. processLabel/processTone called `.startsWith`
    // on a number → "status.startsWith is not a function".
    const numericProcStatus = {
      iteration_id: "iter-procnum",
      started_at: "2026-06-09T11:10:00Z",
      ended_at: "2026-06-09T11:15:00Z",
      seed: { topic: "numeric process_status", source: "coordinator" },
      process_status: 137,
      journal_entry_path: "journal/iterations/procnum.md",
    } as unknown as IterationRecord;

    const row = screen.getByLabelText;
    expectSurvives(numericProcStatus, "iter-procnum");
    // a non-string process_status renders no pid badge rather than crashing.
    expect(row(/load journal iter-procnum/).textContent).not.toMatch(/NaN/);
  });

  it("survives novelty.class / critique.verdict emitted as an object or array", () => {
    // A malformed row emits the verdict enums as structured values. Passed to
    // the badge they reach React's child renderer → "Objects are not valid as a
    // React child". An array verdict must likewise not render its joined members.
    const structuredEnums = {
      iteration_id: "iter-structenum",
      started_at: "2026-06-09T11:20:00Z",
      ended_at: "2026-06-09T11:25:00Z",
      seed: { topic: "structured enums", source: "coordinator" },
      novelty: { class: { weird: true } },
      critique: { verdict: ["survives", "falsified"] },
      journal_entry_path: "journal/iterations/structenum.md",
    } as unknown as IterationRecord;

    const row = screen.getByLabelText;
    expectSurvives(structuredEnums, "iter-structenum");
    // neither the object nor the array leaks into the rendered badge text.
    const text = row(/load journal iter-structenum/).textContent ?? "";
    expect(text).not.toMatch(/object Object/);
    expect(text).not.toMatch(/survives,falsified/);
  });

  it("survives gate_status emitted as an object", () => {
    // gate_status is fed straight to the Badge; an object child throws.
    const objectGate = {
      iteration_id: "iter-objgate",
      started_at: "2026-06-09T11:30:00Z",
      ended_at: "2026-06-09T11:35:00Z",
      seed: { topic: "object gate_status", source: "coordinator" },
      gate_status: { state: "pending" },
      journal_entry_path: "journal/iterations/objgate.md",
    } as unknown as IterationRecord;

    const row = screen.getByLabelText;
    expectSurvives(objectGate, "iter-objgate");
    expect(row(/load journal iter-objgate/).textContent).not.toMatch(/object Object/);
  });
});

// ===========================================================================
// Round 4 (edge-case category): UNKNOWN / forward-compat ENUM values.
// loop_memory.jsonl is producer-owned and append-only; the EMIT layer keeps
// adding enum values (the headline β value seed.source="nemoclaw_agent" is not
// in the data yet, and novelty.class / critique.verdict / gate_status are open
// strings). A never-seen enum value — including a benign new one like
// "provisional" or a value that happens to collide with an inherited
// Object.prototype member name ("toString", "constructor", "valueOf",
// "hasOwnProperty", "__proto__") — must render GENERICALLY (quiet fallback tone,
// the raw value shown), NEVER crash, blank the surface, leak a function/"[native
// code]"/"[object Object]" into the badge className, or log a React console
// error/warn.
//
// What rounds 1 and 2 covered: ABSENT/NULL nested objects, and malformed value
// TYPES (string-where-list, number-where-string, object/array-where-scalar). What
// they did NOT cover, and this round adds: a well-typed STRING enum value that is
// simply not in the known set. The headline live bug found here:
//   novelty.class / critique.verdict / gate_status are keyed straight into plain
//   tone-map objects (NOVELTY_TONE / VERDICT_TONE / GATE_TONE) with `MAP[value] ??
//   fallback`. A value of "toString" resolves to `Function.prototype.toString` (a
//   function, not undefined), so `?? fallback` does NOT fire and that function was
//   interpolated into the badge className as
//   `function toString() { [native code] }`. Own-key lookup (toneFor) now guards it,
//   mirroring SourceBadge / AgentBadge's existing prototype-collision guard.
// ===========================================================================
describe("ResolvedIterationsList hardening — r4: unknown/forward-compat enum values render generically", () => {
  // A fully-populated, healthy control row so every case proves the GOOD rows still
  // render when a sibling carries an unknown enum (render-generically, never blank-all).
  const HEALTHY: IterationRecord = {
    iteration_id: "iter-healthy",
    started_at: "2026-06-09T10:00:00Z",
    ended_at: "2026-06-09T10:05:00Z",
    seed: { topic: "healthy control row", source: "human" },
    novelty: { class: "novel" },
    critique: { verdict: "survives" },
    journal_entry_path: "journal/iterations/healthy.md",
  };

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // Render [bad, HEALTHY], assert no throw / no console.error|warn, both rows present.
  function expectSurvives(bad: unknown, badId: string) {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    let container!: HTMLElement;
    expect(() => {
      container = render(
        <ResolvedIterationsList initial={[bad as IterationRecord, HEALTHY]} />,
      ).container;
    }).not.toThrow();

    expect(
      screen.getByLabelText(new RegExp(`load journal ${badId}`)),
    ).toBeInTheDocument();
    // the healthy sibling survives — the unknown-enum row didn't blank the surface.
    expect(screen.getByLabelText(/load journal iter-healthy/)).toBeInTheDocument();
    expect(errorSpy, "console.error").not.toHaveBeenCalled();
    expect(warnSpy, "console.warn").not.toHaveBeenCalled();
    return { container, errorSpy, warnSpy };
  }

  it("renders a never-seen seed.source / novelty.class / critique.verdict / gate_status generically (badge shows the raw value, quiet tone, no crash)", () => {
    // A forward-compat row from a newer EMIT layer: the headline β provenance
    // value plus novel-but-benign enum values not in any known set. Each must
    // render its raw value with the quiet fallback tone — never vanish, never crash.
    const forwardCompat = {
      iteration_id: "iter-forward",
      started_at: "2026-06-09T11:00:00Z",
      ended_at: "2026-06-09T11:05:00Z",
      seed: { topic: "forward-compat enums", source: "nemoclaw_agent" },
      novelty: { class: "provisional" },
      critique: { verdict: "deferred" },
      gate_status: "awaiting_second_reviewer",
      journal_entry_path: "journal/iterations/forward.md",
    } as unknown as IterationRecord;

    const { container } = expectSurvives(forwardCompat, "iter-forward");

    // The unknown enum values still SHOW (render generically, don't vanish).
    const row = screen.getByLabelText(/load journal iter-forward/);
    expect(row).toHaveTextContent("provisional");
    expect(row).toHaveTextContent("deferred");
    expect(row).toHaveTextContent("awaiting_second_reviewer");

    // No className carries a leaked function / native-code / object string.
    const html = container.innerHTML;
    expect(html).not.toMatch(/native code/);
    expect(html).not.toMatch(/object Object/);
    expect(html.match(/class="[^"]*function[^"]*"/g)).toBeNull();
  });

  it("survives novelty.class / critique.verdict / gate_status colliding with Object.prototype member names (no function leaks into className)", () => {
    // The adversarial unknown-enum case: a producer emits an enum value that is a
    // string but collides with an inherited prototype member. `NOVELTY_TONE["toString"]`
    // is a function (not undefined), so a bare `?? fallback` would NOT fire and the
    // function would interpolate into className. toneFor's own-key lookup must take
    // the quiet fallback instead.
    const protoCollision = {
      iteration_id: "iter-proto",
      started_at: "2026-06-09T11:10:00Z",
      ended_at: "2026-06-09T11:15:00Z",
      seed: { topic: "prototype-collision enums", source: "human" },
      novelty: { class: "toString" },
      critique: { verdict: "hasOwnProperty" },
      gate_status: "valueOf",
      journal_entry_path: "journal/iterations/proto.md",
    } as unknown as IterationRecord;

    const { container } = expectSurvives(protoCollision, "iter-proto");

    // The crux: NO badge className may contain a stringified function / native code.
    const html = container.innerHTML;
    const offending = html.match(/class="[^"]*function[^"]*"/g);
    expect(offending, `leaked function into className: ${JSON.stringify(offending)}`).toBeNull();
    expect(html).not.toMatch(/native code/);

    // The raw collision values still render as badge text (generic fallback, not lost).
    const row = screen.getByLabelText(/load journal iter-proto/);
    expect(row).toHaveTextContent("toString");
    expect(row).toHaveTextContent("hasOwnProperty");
    expect(row).toHaveTextContent("valueOf");
  });

  it("survives a '__proto__' / 'constructor' enum value (the classic prototype-pollution-shaped keys)", () => {
    const dunder = {
      iteration_id: "iter-dunder",
      started_at: "2026-06-09T11:20:00Z",
      ended_at: "2026-06-09T11:25:00Z",
      seed: { topic: "dunder enums", source: "constructor" },
      novelty: { class: "__proto__" },
      critique: { verdict: "constructor" },
      gate_status: "__proto__",
      journal_entry_path: "journal/iterations/dunder.md",
    } as unknown as IterationRecord;

    const { container } = expectSurvives(dunder, "iter-dunder");
    const html = container.innerHTML;
    expect(html.match(/class="[^"]*function[^"]*"/g)).toBeNull();
    expect(html).not.toMatch(/native code/);
    expect(html).not.toMatch(/object Object/);
  });

  it("an unknown novelty/verdict filter value still narrows correctly (forward-compat enum is filterable)", () => {
    // Even an enum value the <select> doesn't list can arrive on a row; the filter
    // compares by equality, so it must not throw and must keep the matching row.
    const a = {
      iteration_id: "iter-fwd-a",
      started_at: "2026-06-09T11:30:00Z",
      ended_at: "2026-06-09T11:35:00Z",
      seed: { topic: "alpha", source: "nemoclaw_agent" },
      novelty: { class: "provisional" },
      critique: { verdict: "deferred" },
      journal_entry_path: "journal/iterations/fwd-a.md",
    } as unknown as IterationRecord;

    expect(() =>
      render(<ResolvedIterationsList initial={[a, HEALTHY]} />),
    ).not.toThrow();
    // both rows present; the unknown enum did not strand the row out of the list.
    expect(screen.getByLabelText(/load journal iter-fwd-a/)).toBeInTheDocument();
    expect(screen.getByLabelText(/load journal iter-healthy/)).toBeInTheDocument();
  });
});

// ===========================================================================
// Round 5 (edge-case category): empty-vs-absent COLLECTIONS + boundary NUMBERS.
// loop_memory.jsonl is producer-owned and append-only; a row's collections can
// be empty `[]` (distinct from absent) and its numeric fields can be a boundary
// value (0 / negative / huge / NaN / Infinity / a string-number). A single such
// row — or a producer that appends the SAME iteration_id twice (a
// crash-and-retry / re-dispatch on an append-only log) — must NEVER throw, print
// "NaN", blank the whole Resolved-iterations surface, or log a React console
// error/warn. It degrades cleanly and the healthy sibling rows still render.
//
// What rounds 1/2/4 covered: absent/null nested objects, malformed value TYPES
// (string-where-list, number-where-string, object-where-scalar), and unknown /
// prototype-collision ENUM strings. What they did NOT cover, and this round adds:
//   - DUPLICATE iteration_id  -> the React `key` collided ("Encountered two
//     children with the same key", a console.error; a row could be omitted). The
//     headline live bug this round found and fixed: the key now composites the
//     row index, mirroring SurfacedFindingsPanel / BubblesPanel / HealthSignalsPanel.
//   - boundary RedteamChip.retries_used (NaN / Infinity / negative / huge / a
//     string-number) -> no NaN leaks, no throw; the retry suffix only shows for a
//     real positive count.
//   - empty `[]` collections distinct from absent: empty conditioning_bullets
//     (no block) and empty retrieval.neighbors (the low-evidence trigger fires,
//     row still renders).
// ===========================================================================
describe("ResolvedIterationsList hardening — r5: empty-vs-absent collections + boundary numbers", () => {
  // A fully-populated, healthy control row so every case proves the GOOD rows
  // still render when a sibling is at a boundary (skip/degrade, never blank-all).
  const HEALTHY: IterationRecord = {
    iteration_id: "iter-healthy",
    started_at: "2026-06-09T10:00:00Z",
    ended_at: "2026-06-09T10:05:00Z",
    seed: { topic: "healthy control row", source: "human" },
    novelty: { class: "novel" },
    critique: { verdict: "survives" },
    journal_entry_path: "journal/iterations/healthy.md",
  };

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // Render [bad, HEALTHY], assert no throw / no console.error|warn, both present.
  function expectSurvives(bad: unknown, badId: string) {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    let container!: HTMLElement;
    expect(() => {
      container = render(
        <ResolvedIterationsList initial={[bad as IterationRecord, HEALTHY]} />,
      ).container;
    }).not.toThrow();

    expect(
      screen.getByLabelText(new RegExp(`load journal ${badId}`)),
    ).toBeInTheDocument();
    // the healthy sibling survives — the boundary row didn't blank the surface.
    expect(screen.getByLabelText(/load journal iter-healthy/)).toBeInTheDocument();
    expect(errorSpy, "console.error").not.toHaveBeenCalled();
    expect(warnSpy, "console.warn").not.toHaveBeenCalled();
    return { container, errorSpy, warnSpy };
  }

  it("survives a DUPLICATE iteration_id without a React key-collision console.error (and keeps BOTH rows)", () => {
    // The headline live bug. loop_memory.jsonl is append-only; a crash-and-retry
    // or a re-dispatch can append the same iteration_id twice. A bare
    // `key={row.iteration_id}` then collided → React logged "Encountered two
    // children with the same key" (a console.error) and could drop a row.
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    const dup1 = {
      iteration_id: "iter-dup",
      started_at: "2026-06-09T11:00:00Z",
      ended_at: "2026-06-09T11:05:00Z",
      seed: { topic: "duplicate id — first append" },
      novelty: { class: "novel" },
      journal_entry_path: "journal/iterations/dup1.md",
    } as unknown as IterationRecord;
    const dup2 = {
      iteration_id: "iter-dup",
      started_at: "2026-06-09T11:10:00Z",
      ended_at: "2026-06-09T11:15:00Z",
      seed: { topic: "duplicate id — retry append" },
      novelty: { class: "rediscovery" },
      journal_entry_path: "journal/iterations/dup2.md",
    } as unknown as IterationRecord;

    expect(() =>
      render(<ResolvedIterationsList initial={[dup1, dup2]} />),
    ).not.toThrow();

    // BOTH rows render — the collision did not omit one. Distinct topics prove it.
    expect(screen.getByText("duplicate id — first append")).toBeInTheDocument();
    expect(screen.getByText("duplicate id — retry append")).toBeInTheDocument();
    expect(screen.getAllByLabelText(/load journal iter-dup/)).toHaveLength(2);

    // The crux: no React duplicate-key console.error/warn.
    expect(
      errorSpy,
      `console.error calls: ${JSON.stringify(errorSpy.mock.calls)}`,
    ).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("survives boundary redteam.retries_used (NaN / Infinity / negative) — no NaN, no spurious retry suffix", () => {
    // `retries_used` is producer-owned. The retry suffix must only show for a
    // real positive count; NaN/Infinity/negative must not leak into the label.
    // Topics deliberately avoid the substrings "NaN"/"retr"/"-3"/"Infinity" so the
    // assertions catch a leak from the NUMBER, not from the topic text.
    //
    // 2026-06-10 condensed-row note: a NaN retries count reads as a CLEAN
    // pass (NaN > 0 is false, verdict "proceed"), and clean redteam chips
    // moved to the detail modal — so the NaN row now renders NO row chip at
    // all (the alarm slot rejects it), which is itself the no-leak outcome.
    const nan = {
      iteration_id: "iter-nan",
      started_at: "2026-06-09T11:20:00Z",
      ended_at: "2026-06-09T11:25:00Z",
      seed: { topic: "boundary count alpha" },
      redteam: { verdict: "proceed", retries_used: NaN },
      journal_entry_path: "journal/iterations/nan.md",
    } as unknown as IterationRecord;

    const { container } = expectSurvives(nan, "iter-nan");
    // NaN > 0 is false → clean pass → quiet chip lives in the modal, not the row.
    expect(screen.queryByTestId("redteam-chip")).toBeNull();
    expect(container.innerHTML).not.toMatch(/NaN/);

    // Negative count: likewise no suffix, no leaked number, no throw.
    const neg = {
      iteration_id: "iter-neg",
      started_at: "2026-06-09T11:30:00Z",
      ended_at: "2026-06-09T11:35:00Z",
      seed: { topic: "boundary count beta" },
      redteam: { verdict: "fatal_flaw", retries_used: -3 },
      journal_entry_path: "journal/iterations/neg.md",
    } as unknown as IterationRecord;
    render(<ResolvedIterationsList initial={[neg]} />);
    // two trees in the body now → scope to the negative row's chip explicitly.
    const negChip = within(
      screen.getByLabelText(/load journal iter-neg/),
    ).getByTestId("redteam-chip");
    expect(negChip.textContent ?? "").not.toMatch(/retr/);
    expect(negChip.textContent ?? "").not.toMatch(/-3/);

    // Infinity is a finite-vs-infinite boundary: `Infinity > 0` is true, so the
    // chip renders generically ("· Infinity retr...") — that is the documented
    // "render the raw value" stance (same as a huge 1e21 count), not a crash. The
    // bar this round defends is no THROW / no NaN / no blanked surface, which
    // holds: the chip renders and the sibling row survives.
    const inf = {
      iteration_id: "iter-inf",
      started_at: "2026-06-09T11:40:00Z",
      ended_at: "2026-06-09T11:45:00Z",
      seed: { topic: "boundary count infinite" },
      redteam: { verdict: "proceed", retries_used: Infinity },
      journal_entry_path: "journal/iterations/inf.md",
    } as unknown as IterationRecord;
    render(<ResolvedIterationsList initial={[inf]} />);
    const infRow = screen.getByLabelText(/load journal iter-inf/);
    const infChip = within(infRow).getByTestId("redteam-chip");
    expect(infChip).toBeInTheDocument();
    expect(infChip.textContent ?? "").not.toMatch(/NaN/);
  });

  it("treats an EMPTY conditioning_bullets [] as 'no bullets' (block omitted, distinct from a populated one)", () => {
    // Empty array is distinct from absent; both must omit the conditioned-by block
    // rather than render an empty bullet list.
    const emptyBullets = {
      iteration_id: "iter-emptyb",
      started_at: "2026-06-09T11:50:00Z",
      ended_at: "2026-06-09T11:55:00Z",
      seed: { topic: "empty bullets row" },
      meta_review: { conditioning_bullets: [] },
      journal_entry_path: "journal/iterations/emptyb.md",
    } as unknown as IterationRecord;

    expectSurvives(emptyBullets, "iter-emptyb");
    expect(screen.queryByTestId("conditioning-iter-emptyb")).toBeNull();
  });

  it("renders a row whose retrieval.neighbors is the EMPTY list [] (the low-evidence trigger fires; the row still renders)", () => {
    // An explicitly-present, empty neighbor list is the structural low-evidence
    // signal (0 retrieved → nothing grounded the verdict). The badge must fire AND
    // the row must render cleanly — empty-collection edge, not a crash.
    const emptyNeighbors = {
      iteration_id: "iter-emptyn",
      started_at: "2026-06-09T12:00:00Z",
      ended_at: "2026-06-09T12:05:00Z",
      seed: { topic: "empty neighbors row" },
      novelty: { class: "novel" },
      critique: { verdict: "survives" },
      retrieval: { neighbors: [] },
      journal_entry_path: "journal/iterations/emptyn.md",
    } as unknown as IterationRecord;

    expectSurvives(emptyNeighbors, "iter-emptyn");
    // the empty-neighbors low-evidence flag is present on the flagged row.
    expect(screen.getByTestId("low-evidence-badge")).toBeInTheDocument();
  });

  it("renders an empty seed.topic '' and an empty iteration_id '' with no topic block, no key warn, no crash", () => {
    // Empty strings (distinct from absent) on the two string fields that drive
    // render: an empty topic omits the topic line; an empty id is still a valid,
    // unique key (now composited with the index) and must not warn.
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    const emptyStrings = {
      iteration_id: "",
      started_at: "2026-06-09T12:10:00Z",
      ended_at: "2026-06-09T12:15:00Z",
      seed: { topic: "", source: "human" },
      novelty: { class: "novel" },
      journal_entry_path: "journal/iterations/empty.md",
    } as unknown as IterationRecord;

    expect(() =>
      render(<ResolvedIterationsList initial={[emptyStrings, HEALTHY]} />),
    ).not.toThrow();

    // The healthy row still renders alongside the all-empty-strings row.
    expect(screen.getByLabelText(/load journal iter-healthy/)).toBeInTheDocument();
    expect(errorSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("renders a single-element list and an empty list with no pager and the right count/empty-state", () => {
    // Boundary list sizes: exactly one row (no pager, count "1"); and the empty
    // list (no pager, the no-iterations empty state, count "0").
    const one = render(
      <ResolvedIterationsList initial={[HEALTHY]} />,
    );
    expect(screen.queryByTestId("resolved-pager")).toBeNull();
    expect(screen.getByTestId("resolved-count")).toHaveTextContent("1");
    one.unmount();

    render(<ResolvedIterationsList initial={[]} />);
    expect(screen.queryByTestId("resolved-pager")).toBeNull();
    expect(screen.getByTestId("resolved-count")).toHaveTextContent("0");
    // the explicit empty state, never a blank gap.
    expect(screen.getByText(/No iterations yet/)).toBeInTheDocument();
  });
});

// ===========================================================================
// ROUND 6 — components/ResolvedIterationsList.tsx, edge-case category: a
// MALFORMED RESPONSE BODY on the polling path (not a malformed ROW — every prior
// round, r1/r2/r4/r5, drove the synchronous `initial=` prop, which
// short-circuits the useEffect and never exercises the fetch-response handler at
// all). The contract is {iterations:[...]}, but getJSON forwards whatever a 200
// carries verbatim, so a legacy/mid-rotation backend, a proxy, or a
// serialization slip can hand back a bare-null body, a `{}` with no `iterations`
// key, `iterations:null`, or a non-array `iterations`.
//
// THE BUG THIS ROUND FIXED (component-owned, polling path): the newest-first
// sort did `const sorted = [...r.iterations].sort(...)` with NO guard on the
// body. `[...null]` / `[...undefined]` / `[...42]` throws
// ("Cannot read properties of null (reading 'iterations')" /
// "r.iterations is not iterable"), which rejects the load promise into `.catch`,
// painting a raw TypeError in the red banner and blanking the WHOLE resolved
// list — the blank-gap-on-bad-data failure the autonomy-observability work
// exists to eliminate. The sibling autonomy route Coordinator.tsx already guards
// the identical case (`Array.isArray(r?.cycles) ? r.cycles : []`); this brings
// ResolvedIterationsList (which the autonomy batch extended with the source /
// low-evidence badges) to parity. The fix coerces a non-array/absent body to []
// (the clean empty state), exactly like the sibling.
//
// We drive the POLLING path (api/http mocked — where the sort runs and the bug
// lived), mirroring the test_harden_Coordinator_r2 idiom: a module-mutable
// RESPONSE the hoisted vi.mock factory reads, a renderPollingQuietly() that
// flushes the async load and settles on a real steady state, and console.error /
// console.warn spied + asserted empty (a thrown React render surfaces as a
// console.error here too, so a crash is caught even when render() doesn't
// rethrow; React's act() advisory is filtered as test-harness noise).
//
// (The module-mutable RESPONSE + vi.mock("../src/api/http") this round needs are
// hoisted to module scope at the top of this consolidated file.)
// ===========================================================================
describe("ResolvedIterationsList hardening — r6: malformed RESPONSE BODY on the polling path", () => {
  // A well-formed row, so a malformed BODY is exercised against the knowledge of
  // what a good row looks like — when the body IS an array of good rows the list
  // must render them, proving the guard doesn't over-broadly blank a valid load.
  function mk(over: Partial<IterationRecord>): IterationRecord {
    return {
      iteration_id: `iter-${Math.random().toString(36).slice(2, 10)}`,
      started_at: "2026-06-09T10:00:00Z",
      ended_at: "2026-06-09T10:03:00Z",
      seed: { topic: "well-formed iteration", source: "coordinator" },
      novelty: { class: "novel" },
      critique: { verdict: "survives" },
      journal_entry_path: "journal/iterations/000.md",
      ...over,
    } as IterationRecord;
  }

  // Render the polling list, flush the async load + sort, and return the
  // console.error/warn the render path emitted (a thrown render lands here too),
  // with React's act() advisory filtered out. The list loads via a Promise, so
  // settle on a real steady state — a journal row OR the empty-state text present
  // — rather than a bare microtask flush. The panel has no page-level testid, so
  // `loaded` is observed via the panel container + its known steady-state text.
  async function renderPollingQuietly() {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    render(<ResolvedIterationsList pollMs={999_999} />);
    await waitFor(() => {
      const hasRow =
        document.querySelector('[aria-label^="load journal "]') !== null;
      const hasEmpty = /No iterations yet/.test(
        document.querySelector('[data-testid="resolved-iterations-list"]')
          ?.textContent ?? "",
      );
      expect(hasRow || hasEmpty).toBe(true);
    });
    const calls = {
      error: errSpy.mock.calls
        .map((c) => String(c[0]))
        .filter((m) => !m.includes("not wrapped in act")),
      warn: warnSpy.mock.calls
        .map((c) => String(c[0]))
        .filter((m) => !m.includes("not wrapped in act")),
    };
    errSpy.mockRestore();
    warnSpy.mockRestore();
    return calls;
  }

  // Assert the panel settled into its clean empty state (the contract for an
  // absent / malformed body) with no TypeError leaked onto the page.
  function expectCleanEmpty(error: string[]) {
    const panel = screen.getByTestId("resolved-iterations-list");
    expect(panel.textContent ?? "").toMatch(/No iterations yet/);
    expect(screen.queryByLabelText(/^load journal /)).toBeNull();
    expect(panel.textContent ?? "").not.toMatch(
      /TypeError|is not iterable|is not a function|Cannot read properties/,
    );
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
  }

  afterEach(() => {
    cleanup();
    RESPONSE = { iterations: [] };
    vi.clearAllMocks();
  });

  // The headline regression: a bare-null body. `[...null.iterations]` threw
  // "Cannot read properties of null (reading 'iterations')" pre-fix.
  it("POLLING: a bare-null body degrades to the clean empty state (no crash)", async () => {
    RESPONSE = null;
    const { error } = await renderPollingQuietly();
    expectCleanEmpty(error);
  });

  // A 200 with NO `iterations` key — `[...undefined]` threw "not iterable".
  it("POLLING: a body missing the iterations key degrades to the clean empty state", async () => {
    RESPONSE = {};
    const { error } = await renderPollingQuietly();
    expectCleanEmpty(error);
  });

  // iterations explicitly null — `[...null]` threw "not iterable".
  it("POLLING: iterations:null degrades to the clean empty state", async () => {
    RESPONSE = { iterations: null };
    const { error } = await renderPollingQuietly();
    expectCleanEmpty(error);
  });

  // A non-array `iterations` (a scalar / object) — `[...42]` / `[...{}]` threw.
  it("POLLING: a non-array iterations body degrades to the clean empty state", async () => {
    for (const bad of [42, "nope", { not: "an array" }]) {
      RESPONSE = { iterations: bad };
      const { error } = await renderPollingQuietly();
      expectCleanEmpty(error);
      cleanup();
    }
  });

  // The guard must NOT over-broadly blank a VALID load: a well-formed array body
  // still renders its rows. This pins the fix to "coerce bad shapes to []",
  // never "swallow good data".
  it("POLLING: a well-formed array body still renders its rows (guard is not over-broad)", async () => {
    RESPONSE = {
      iterations: [
        mk({ iteration_id: "iter-GOOD-A", ended_at: "2026-06-09T10:01:00Z" }),
        mk({ iteration_id: "iter-GOOD-B", ended_at: "2026-06-09T10:02:00Z" }),
      ],
    };
    const { error, warn } = await renderPollingQuietly();
    expect(
      screen.getByLabelText("load journal iter-GOOD-A"),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText("load journal iter-GOOD-B"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("resolved-count")).toHaveTextContent("2");
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });
});
