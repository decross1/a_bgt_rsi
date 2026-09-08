// Consolidated edge-case + property-fuzz hardening for Experiments (merged from per-round files).
//
// Merged verbatim from:
//   - tests/test_harden_Experiments_r1.tsx (missing/null/undefined fields)
//   - tests/test_harden_Experiments_r2.tsx (malformed value TYPES)
//   - tests/test_harden_Experiments_r3.tsx (scale + content)
//   - tests/test_harden_Experiments_r4.tsx (unknown/forward-compat verdict tone enum)
//
// Each source file's body is wrapped in its own top-level describe(...) so that
// describe/it names and the per-file top-level helpers/fixtures (which collide
// by name across rounds — `renderQuietly` x4 with differing bodies,
// `MALFORMED_CYCLES` x2 with differing bodies) are lexically isolated and never
// clash. Every it()/test() case and assertion is preserved verbatim.
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import Experiments from "../src/routes/Experiments";
import type { ResearchResponse } from "../src/types/experiments";
import type { CoordinatorCycle } from "../src/types/schemas";

// ===========================================================================
// round 1 — partial/legacy/malformed rows (missing/null/undefined fields)
// ADVERSARIAL HARDENING — round 1, edge-case category: missing/null/undefined
// optional fields + entirely-absent nested objects on /api/research and
// /api/coordinator/cycles rows. The /api/research payload is producer-owned
// (ui/backend/experiments.py walks experiments/*/results/ heterogeneously); a
// legacy/partial/malformed row — a tier with no `experiments`, an experiment
// with no `bridge`, a response with no `tiers`/`untiered`, a cycle with no
// `timestamp` — must NEVER crash the whole Research page. One bad row may
// drop out (filtered/guarded), but the surface must keep rendering.
//
// Injection: Experiments accepts `initial` (a ResearchResponse) +
// `initialCoordinatorCycles`. When `initial !== undefined` both effects bail
// (network-free), so the render path under test is exactly the production one
// fed adversarial data. We render in jsdom, spy on console.error/console.warn
// (vi.spyOn), and assert the page still mounts and neither spy fired.
// ===========================================================================
describe("Experiments hardening r1 — partial/legacy/malformed rows", () => {
  // A ResearchResponse a real producer could plausibly emit after a partial /
  // legacy / malformed write: `tiers` present but each tier or experiment is
  // missing the array fields the renderer reduces/maps over, and `untiered`
  // entirely absent. Cast through `unknown` because these shapes are deliberately
  // outside the (happy-path) type — that is the whole point of the category.
  const MALFORMED_RESEARCH = {
    available: true,
    // `tiers` itself present, but the rows inside are degenerate.
    tiers: [
      // A tier with NO `experiments` array at all (legacy / truncated write).
      {
        tier: "synthetic",
        label: "Synthetic",
        description: "Fully synthetic sandboxes.",
      },
      // A tier whose `experiments` is explicitly null.
      {
        tier: "semi_synthetic",
        label: "Semi-synthetic",
        description: "Semi-synthetic sandboxes.",
        experiments: null,
      },
      // A tier with an experiment that is missing `bridge` AND `verdict` (the two
      // fields the card reduces/branches on) and absent flag fields.
      {
        tier: "applied",
        label: "Applied",
        description: "Applied / CFTC-gated.",
        experiments: [
          { id: "exp_partial", title: "exp partial (no bridge, no verdict)" },
          // A second experiment whose `bridge` is null rather than [].
          {
            id: "exp_null_bridge",
            title: "exp null bridge",
            verdict: null,
            bridge: null,
          },
        ],
      },
    ],
    // `untiered` entirely ABSENT from the response (older backend / truncated).
  } as unknown as ResearchResponse;

  // Coordinator cycles a producer could emit partially: a row missing
  // `timestamp` (the sort key), missing `run_id` (the React key), and missing the
  // optional id-list footer fields. These flow through Experiments' sort + key
  // path before CoordinatorCycleCard renders them.
  const MALFORMED_CYCLES = [
    {
      // no timestamp, no run_id
      agent: "coordinator",
      topic: "legacy cycle missing timestamp + run_id",
      topic_source: "arxiv_pick",
      plan: [{ action: "noop" }],
      outcomes: [{ action: "noop", status: "passed" }],
    },
  ] as unknown as CoordinatorCycle[];

  function renderQuietly(node: React.ReactElement) {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    // initial is passed (not undefined) so both effects bail — fully network-free.
    render(<MemoryRouter>{node}</MemoryRouter>);
    const calls = {
      error: errSpy.mock.calls.map((c) => String(c[0])),
      warn: warnSpy.mock.calls.map((c) => String(c[0])),
    };
    errSpy.mockRestore();
    warnSpy.mockRestore();
    return calls;
  }

  it("renders the page on a research response with degenerate tiers/experiments", () => {
    const { error, warn } = renderQuietly(
      <Experiments initial={MALFORMED_RESEARCH} initialCoordinatorCycles={[]} />,
    );
    // The page mounted (no crash) and the tier sections still render.
    expect(screen.getByTestId("experiments-page")).toBeInTheDocument();
    expect(screen.getByTestId("tier-section-synthetic")).toBeInTheDocument();
    expect(screen.getByTestId("tier-section-applied")).toBeInTheDocument();
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });

  it("renders on malformed coordinator cycles (missing timestamp/run_id)", () => {
    const { error, warn } = renderQuietly(
      <Experiments
        initial={MALFORMED_RESEARCH}
        initialCoordinatorCycles={MALFORMED_CYCLES}
      />,
    );
    expect(screen.getByTestId("coordinator-cycles-section")).toBeInTheDocument();
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });

  it("renders on a response with no tiers and no untiered arrays", () => {
    const empty = { available: true } as unknown as ResearchResponse;
    const { error, warn } = renderQuietly(
      <Experiments initial={empty} initialCoordinatorCycles={[]} />,
    );
    expect(screen.getByTestId("experiments-page")).toBeInTheDocument();
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });
});

// ===========================================================================
// round 2 — malformed value TYPES
// ADVERSARIAL HARDENING — round 2, edge-case category: malformed value TYPES on
// the /api/research payload + /api/coordinator/cycles rows that feed
// routes/Experiments.tsx. The payload is producer-owned (the backend computes
// /api/research over experiments/*/results/ heterogeneously; cycles are
// appended JSONL) and may be partial/legacy/malformed — a row can carry the
// WRONG TYPE in a field: a string/object where the renderer maps/reduces an
// array, an object where a scalar React child / key / URL is expected, a
// NaN/Infinity metric value, a non-string timestamp/id. None of these may THROW,
// print "NaN"/"Infinity", blank the whole surface, or log a React
// console.error/warn. One bad row may degrade to "empty" but the page keeps
// rendering. (Round 1 covered missing/null/undefined fields; this round is the
// type-confusion class those guards did not address — the live producer is
// untyped JSONL, so a string-for-number / array-for-object is plausible.)
//
// Injection: Experiments accepts `initial` (a ResearchResponse) +
// `initialCoordinatorCycles`; with `initial !== undefined` both effects bail
// (network-free), so the render path under test is exactly production fed
// adversarial data. Render in jsdom, spy on console.error/console.warn, assert
// the page mounts and neither spy fired and no NaN/Infinity leaked to the DOM.
// ===========================================================================
describe("Experiments hardening r2 — malformed value TYPES", () => {
  // A ResearchResponse whose every field carries the WRONG TYPE somewhere a real
  // producer could plausibly emit it: an object where a scalar React child is
  // expected (label/description/tier id/exp id/title), a NaN/Infinity bridge
  // value, an object metric/value, a numeric iteration_id, a garbage verdict tone,
  // a tiers array with null/number elements, and an untiered exp with an object
  // id. Cast through `unknown` because these shapes are deliberately outside the
  // happy-path type — that is the whole point of the category.
  const MALFORMED_TYPES = {
    available: true,
    tiers: [
      // null + a number interleaved with a real tier (null-in-array): the page
      // must drop these, not crash on `null.tier` / render `42` as a section.
      null,
      42,
      {
        // tier id, label, description are OBJECTS / ARRAYS (React-child crash
        // vector) — must coerce to a fallback, not throw.
        tier: { not: "a string" },
        label: { weird: "obj" },
        description: ["array", "as", "description"],
        experiments: [
          // exp id + title are OBJECTS (React-child + key/testid/URL vector).
          { id: { nested: 1 }, title: ["arr"], verdict: null, bridge: [] },
          // NaN / Infinity bridge values must NOT print as "NaN"/"Infinity".
          {
            id: "exp_nan",
            title: "exp with non-finite metric values",
            verdict: { text: "Verdict: YES", tone: "ok" },
            bridge: [
              { iteration_id: "iter-x", metric: "accuracy", value: NaN },
              { iteration_id: "iter-y", metric: "revenue", value: Infinity },
            ],
          },
          // null element inside the experiments array (must be dropped).
          null,
        ],
      },
      {
        // `experiments` is a STRING (array-type confusion) — `.map` would throw.
        tier: "semi_synthetic",
        label: "Semi-synthetic",
        description: "experiments field is a string here",
        experiments: "oops-not-an-array",
      },
      {
        // verdict tone is a GARBAGE string outside {ok,warn,bad}; bridge value is
        // an OBJECT; metric is an OBJECT; iteration_id is a NUMBER.
        tier: "applied",
        label: "Applied",
        description: "garbage tone + object bridge fields",
        experiments: [
          {
            id: "exp_garbage_tone",
            title: "garbage tone",
            verdict: { text: "weird", tone: "magenta" },
            bridge: [{ iteration_id: 7, metric: { x: 1 }, value: { y: 2 } }],
          },
        ],
      },
    ],
    // untiered is itself fine but carries an exp whose id is an OBJECT.
    untiered: [{ id: { o: 1 }, title: "untiered obj id", verdict: null, bridge: [] }],
  } as unknown as ResearchResponse;

  // `tiers` itself the WRONG TYPE (a string, not an array) — the top-level reduce
  // + map would throw "tiers.reduce is not a function" and blank the page.
  const TIERS_IS_A_STRING = {
    available: true,
    tiers: "this is not an array",
    untiered: { also: "not an array" },
  } as unknown as ResearchResponse;

  // Coordinator cycles with type-confused fields that flow through Experiments'
  // sort/key path before CoordinatorCycleCard: a non-string (numeric) timestamp,
  // an object run_id, a null element in the array.
  const MALFORMED_CYCLES = [
    null,
    {
      timestamp: 1718000000000, // a NUMBER, not an ISO string
      run_id: { obj: "id" }, // object run_id (used as React key)
      agent: "coordinator",
      topic: "cycle with numeric timestamp + object run_id",
      topic_source: "arxiv_pick",
      plan: [{ action: "noop" }],
      outcomes: [{ action: "noop", status: "passed" }],
    },
  ] as unknown as CoordinatorCycle[];

  function renderQuietly(node: React.ReactElement) {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    // `initial` is passed (not undefined) so both effects bail — network-free.
    const { container } = render(<MemoryRouter>{node}</MemoryRouter>);
    const calls = {
      error: errSpy.mock.calls.map((c) => String(c[0])),
      warn: warnSpy.mock.calls.map((c) => String(c[0])),
      text: container.textContent ?? "",
    };
    errSpy.mockRestore();
    warnSpy.mockRestore();
    return calls;
  }

  it("renders the page when fields carry wrong types (object/NaN/garbage)", () => {
    const { error, warn, text } = renderQuietly(
      <Experiments initial={MALFORMED_TYPES} initialCoordinatorCycles={[]} />,
    );
    // The page mounted (no React-child throw) and the well-formed cards/tiers
    // still rendered alongside the dropped/degraded malformed ones.
    expect(screen.getByTestId("experiments-page")).toBeInTheDocument();
    expect(screen.getByTestId("research-card-exp_nan")).toBeInTheDocument();
    expect(screen.getByTestId("research-card-exp_garbage_tone")).toBeInTheDocument();
    // A non-finite metric value is NOT printed as "NaN"/"Infinity" anywhere.
    expect(text).not.toMatch(/NaN|Infinity/);
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });

  it("does not crash when `tiers`/`untiered` are not arrays", () => {
    const { error, warn } = renderQuietly(
      <Experiments initial={TIERS_IS_A_STRING} initialCoordinatorCycles={[]} />,
    );
    // Degrades to the available-but-empty surface (the footer + cycles section)
    // rather than throwing "tiers.reduce is not a function".
    expect(screen.getByTestId("experiments-page")).toBeInTheDocument();
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });

  it("renders on coordinator cycles with a numeric timestamp / object run_id", () => {
    const { error, warn } = renderQuietly(
      <Experiments
        initial={MALFORMED_TYPES}
        initialCoordinatorCycles={MALFORMED_CYCLES}
      />,
    );
    expect(screen.getByTestId("coordinator-cycles-section")).toBeInTheDocument();
    // The null cycle element was dropped; the one real cycle still rendered.
    expect(screen.getAllByTestId("coordinator-cycle-card")).toHaveLength(1);
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });
});

// ===========================================================================
// round 3 — scale + content
// ADVERSARIAL HARDENING — round 3, edge-case category: SCALE + CONTENT on the
// /api/research payload + /api/coordinator/cycles rows that feed
// routes/Experiments.tsx. The payload is producer-owned (the backend computes
// /api/research over experiments/*/results/ heterogeneously; cycles are appended
// JSONL) and the content is model-/walk-derived — so a row can carry a single
// very long unbroken string (5k chars), 1000+ rows in a list, or
// unicode/emoji/RTL/newline/HTML-looking text in any scalar field. None of these
// may THROW, blank the whole surface, or log a React console.error/warn.
//
// The headline bug this round fixes: a producer string truncated mid-codepoint
// leaves a LONE UTF-16 SURROGATE in an experiment `id`. The card interpolates
// the id into its `<Link to={/experiments/${encodeURIComponent(id)}}>` URL, and
// `encodeURIComponent` THROWS "URIError: URI malformed" on a lone surrogate —
// unwinding the whole grid so ONE corrupt id blanks the entire Research page.
// (Rounds 1/2 covered missing/null fields and wrong value TYPES; neither touched
// the lone-surrogate / scale class.)
//
// Injection: Experiments accepts `initial` (a ResearchResponse) +
// `initialCoordinatorCycles`; with `initial !== undefined` both effects bail
// (network-free), so the render path under test is exactly production fed
// adversarial data. Render in jsdom, spy on console.error/console.warn, assert
// the page mounts, neither spy fired, and no NaN/Infinity leaked to the DOM.
// ===========================================================================
describe("Experiments hardening r3 — scale + content", () => {
  // A single very long unbroken string a model/walk could plausibly produce.
  const LONG = "x".repeat(5000);
  // Emoji (astral) + RTL override + Arabic + a newline + HTML-looking markup + a
  // tab + CJK — exercises React's text-escaping + the asText/asArray coercions.
  const WEIRD = "\u{1D54F}\u{1F680}‮aعربي‬\n<script>alert(1)</script>\t漢字";
  // A LONE high surrogate (no trailing low surrogate) — the encodeURIComponent
  // throw vector. A producer string truncated mid-pair yields exactly this.
  const SURROGATE_ID = "exp\uD800_truncated";

  // A response carrying the scale+content adversarial shapes: a tier whose label
  // is 5k chars and description is the weird mix; an experiment whose id holds a
  // LONE SURROGATE (the URL-encode crash vector) plus 5k-char title/verdict and a
  // weird-content bridge; and an untiered exp whose id is the weird mix.
  const SCALE_CONTENT = {
    available: true,
    tiers: [
      {
        tier: "synthetic",
        label: LONG,
        description: WEIRD,
        experiments: [
          {
            // Lone surrogate in the id — interpolated into the Link URL.
            id: SURROGATE_ID,
            title: LONG,
            verdict: { text: LONG, tone: "ok" },
            bridge: [{ iteration_id: WEIRD, metric: LONG, value: WEIRD }],
          },
        ],
      },
    ],
    untiered: [{ id: WEIRD, title: WEIRD, verdict: null, bridge: [] }],
  } as unknown as ResearchResponse;

  function renderQuietly(node: React.ReactElement) {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    // `initial` is passed (not undefined) so both effects bail — network-free.
    const { container } = render(<MemoryRouter>{node}</MemoryRouter>);
    const calls = {
      error: errSpy.mock.calls.map((c) => String(c[0])),
      warn: warnSpy.mock.calls.map((c) => String(c[0])),
      text: container.textContent ?? "",
    };
    errSpy.mockRestore();
    warnSpy.mockRestore();
    return calls;
  }

  it("renders a lone-surrogate id without throwing URIError from encodeURIComponent", () => {
    const { error, warn } = renderQuietly(
      <Experiments initial={SCALE_CONTENT} initialCoordinatorCycles={[]} />,
    );
    // The page mounted (no URIError unwinding the grid). The malformed-id card
    // still renders — its data-testid carries the raw id, not the encoded URL.
    expect(screen.getByTestId("experiments-page")).toBeInTheDocument();
    expect(
      screen.getByTestId(`research-card-${SURROGATE_ID}`),
    ).toBeInTheDocument();
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });

  it("renders 5k-char strings + emoji/RTL/HTML/newline content cleanly", () => {
    const { error, warn, text } = renderQuietly(
      <Experiments initial={SCALE_CONTENT} initialCoordinatorCycles={[]} />,
    );
    // The 5k-char label is present (content not silently dropped) and no
    // NaN/Infinity leaked from any coercion path.
    expect(text).toContain(LONG);
    expect(text).not.toMatch(/NaN|Infinity/);
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });

  it("renders 1000+ experiment cards and 1000+ coordinator cycles", () => {
    const exps = Array.from({ length: 1200 }, (_, i) => ({
      id: `exp${i}`,
      title: `title ${i}`,
      verdict: null,
      bridge: [],
    }));
    const cycles = Array.from({ length: 1200 }, (_, i) => ({
      timestamp: `2026-06-09T00:00:${String(i % 60).padStart(2, "0")}Z`,
      run_id: `run-${i}`,
      agent: "coordinator",
      topic: `topic ${i}`,
      topic_source: "arxiv_pick",
      plan: [],
      outcomes: [],
      promoted_finding_ids: [],
      bubble_run_ids: [],
    })) as unknown as CoordinatorCycle[];
    const big = {
      available: true,
      tiers: [
        { tier: "synthetic", label: "Synthetic", description: "d", experiments: exps },
      ],
      untiered: [],
    } as unknown as ResearchResponse;

    const { error, warn } = renderQuietly(
      <Experiments initial={big} initialCoordinatorCycles={cycles} />,
    );
    expect(screen.getByTestId("experiments-page")).toBeInTheDocument();
    // All 1200 cycle cards rendered (no row silently dropped at scale).
    expect(screen.getAllByTestId("coordinator-cycle-card")).toHaveLength(1200);
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });
});

// ===========================================================================
// round 4 — unknown/forward-compat verdict tone enum
// ADVERSARIAL HARDENING — round 4, edge-case category: UNKNOWN / forward-compat
// enum values on the /api/research payload that feeds routes/Experiments.tsx.
// The verdict `tone` is a producer-owned enum ({ok|warn|bad|null} today); a
// future EMIT shape or a malformed/legacy row can carry a never-seen value
// there. The renderer (VerdictChip) maps it through a `toneCls[tone]` plain
// object. Round 2 already proved an ORDINARY unknown tone ("magenta") degrades
// to the muted "no verdict" path. This round targets the one unknown-enum value
// that round-2's "magenta" does NOT exercise: a tone string that collides with
// an inherited Object.prototype member name ("toString", "constructor",
// "valueOf", "hasOwnProperty", "__proto__"). With a bare `toneCls[tone]` lookup
// those resolve to a FUNCTION/object via the prototype chain instead of
// undefined, so the `!cls` fallback does NOT fire and the garbage interpolates
// into the chip's className ("class=...function toString() { [native code] }").
// The sibling provenance badges (SourceBadge/AgentBadge) were hardened against
// exactly this with own-key lookups; this asserts VerdictChip is too.
//
// Injection: Experiments accepts `initial` (a ResearchResponse); with
// `initial !== undefined` both effects bail (network-free), so the render path
// under test is exactly production fed the adversarial enum value. Render in
// jsdom, spy on console.error/console.warn, assert the page mounts, neither spy
// fired, the chip degraded to the muted "no verdict" tone, and no native-code
// garbage leaked into the DOM.
// ===========================================================================
describe("Experiments hardening r4 — unknown/forward-compat verdict tone enum", () => {
  // Every Object.prototype member name that a producer could emit as a novel
  // `tone`, each on its own experiment card. A bare bracket lookup resolves these
  // off the prototype chain to a function/value, defeating the `?? "no verdict"`
  // fallback.
  const PROTO_TONES = [
    "toString",
    "constructor",
    "valueOf",
    "hasOwnProperty",
    "__proto__",
    "isPrototypeOf",
    "propertyIsEnumerable",
    "toLocaleString",
  ];

  // A ResearchResponse whose verdict tones are all prototype-member names, plus a
  // forward-compat "nemoclaw" tone (a plausible never-seen EMIT value) and a real
  // {ok} card so we also confirm the happy path is untouched.
  const PROTO_TONE_PAYLOAD = {
    available: true,
    tiers: [
      {
        tier: "synthetic",
        label: "Synthetic",
        description: "unknown/forward-compat verdict tones",
        experiments: [
          // The genuine happy path stays green.
          {
            id: "exp_ok",
            title: "well-formed ok verdict",
            verdict: { text: "Verdict: YES", tone: "ok" },
            bridge: [],
          },
          // A novel forward-compat enum value (never crashes, never green/red).
          {
            id: "exp_nemoclaw_tone",
            title: "forward-compat tone",
            verdict: { text: "nemoclaw says maybe", tone: "nemoclaw" },
            bridge: [],
          },
          // One card per prototype-member tone — the proto-collision vector.
          ...PROTO_TONES.map((tone, i) => ({
            id: `exp_proto_${i}`,
            title: `prototype tone ${tone}`,
            verdict: { text: `tone is ${tone}`, tone },
            bridge: [],
          })),
          // A verdict whose `text` is also a prototype-member name (the muted
          // path renders `text` directly — make sure that stays a plain string).
          {
            id: "exp_proto_text",
            title: "verdict text is a proto name, tone unknown",
            verdict: { text: "constructor", tone: "constructor" },
            bridge: [],
          },
        ],
      },
    ],
    untiered: [],
  } as unknown as ResearchResponse;

  function renderQuietly(node: React.ReactElement) {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { container } = render(<MemoryRouter>{node}</MemoryRouter>);
    const calls = {
      error: errSpy.mock.calls.map((c) => String(c[0])),
      warn: warnSpy.mock.calls.map((c) => String(c[0])),
      text: container.textContent ?? "",
      html: container.innerHTML,
    };
    errSpy.mockRestore();
    warnSpy.mockRestore();
    return calls;
  }

  it("degrades a prototype-member-name tone to the muted 'no verdict' chip", () => {
    const { error, warn, text, html } = renderQuietly(
      <Experiments initial={PROTO_TONE_PAYLOAD} initialCoordinatorCycles={[]} />,
    );
    // The page mounted (no throw) and every card rendered.
    expect(screen.getByTestId("experiments-page")).toBeInTheDocument();
    expect(screen.getByTestId("research-card-exp_ok")).toBeInTheDocument();
    expect(
      screen.getByTestId("research-card-exp_nemoclaw_tone"),
    ).toBeInTheDocument();

    // No native-code / function source leaked into the rendered className or
    // text — the proto-collision did NOT splice a function into the chip class.
    expect(html).not.toMatch(/\[native code\]/);
    expect(html).not.toMatch(/function (toString|valueOf|isPrototypeOf)/);
    expect(text).not.toMatch(/\[object Object\]/);

    // Each prototype-tone chip degraded to the muted zinc "no verdict" palette
    // (NOT an emerald/amber/red tone), and renders its provided `text`.
    for (let i = 0; i < PROTO_TONES.length; i++) {
      const chip = screen.getByTestId(`verdict-exp_proto_${i}`);
      // The muted fallback uses text-zinc-400; a mis-resolved tone would carry
      // a function-string or an emerald/amber/red class instead.
      expect(chip.className).toContain("text-zinc-400");
      expect(chip.className).not.toMatch(/emerald|amber|red/);
      expect(chip.className).not.toMatch(/\[native code\]|function /);
    }

    // No React render errors/warnings for the whole batch.
    expect(error, `console.error: ${error.join(" | ")}`).toHaveLength(0);
    expect(warn, `console.warn: ${warn.join(" | ")}`).toHaveLength(0);
  });

  it("keeps the well-formed {ok} verdict green (no regression)", () => {
    renderQuietly(
      <Experiments initial={PROTO_TONE_PAYLOAD} initialCoordinatorCycles={[]} />,
    );
    const okChip = screen.getByTestId("verdict-exp_ok");
    expect(okChip.className).toContain("emerald");
  });
});
