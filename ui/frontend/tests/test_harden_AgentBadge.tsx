// Consolidated edge-case + property-fuzz hardening for AgentBadge (merged from per-round files).
//
// ----------------------------------------------------------------------------
// Source: test_harden_AgentBadge_r1.tsx
// Adversarial hardening (round 1, edge-case category): missing/null/undefined
// optional fields + a non-string `agent` from a legacy/malformed JSONL row.
//
// `agent` is read off producer-owned JSONL (the run log / coordinator-cycle
// rows), so even though the type says `string`, a pre-2026-06-09 / malformed
// row can carry a number, object, array, or boolean. Optional-chaining only
// guards null/undefined — `(123).trim()` threw `TypeError: agent.trim is not a
// function` and crashed the entire CoordinatorCycleCard / Activity failed-
// dispatch list (one bad row blanked the whole surface). The component must
// treat any non-string the same as absent: render nothing, never throw, never
// log a React console.error/warn.
//
// ----------------------------------------------------------------------------
// Source: test_harden_AgentBadge_r2.tsx
// Adversarial hardening (round 2, malformed value TYPES category): a producer-
// owned `agent` STRING whose value collides with an inherited Object.prototype
// member name ("constructor", "toString", "__proto__", "valueOf",
// "hasOwnProperty", "isPrototypeOf").
//
// These survive round 1's `typeof agent === "string"` guard (they ARE strings),
// then hit the tone lookup `TONE[value] ?? QUIET`. Because such keys resolve via
// the prototype chain, the bare lookup returned a FUNCTION ("function Object() {
// [native code] }") or "[object Object]" instead of `undefined` — so `?? QUIET`
// did NOT fall through and that garbage was interpolated straight into the
// rendered className (e.g. "...tracking-wide function toString() { [native
// code] }"). The fix looks up own keys only (hasOwnProperty.call); any value
// not in TONE's own keys — including prototype-name collisions — renders as the
// QUIET zinc badge, no garbage, no crash, no React console noise.
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AgentBadge from "../src/components/AgentBadge";

const PROTO_KEYS = [
  "constructor",
  "toString",
  "__proto__",
  "valueOf",
  "hasOwnProperty",
  "isPrototypeOf",
];

describe("AgentBadge hardening — non-string / absent agent (r1)", () => {
  describe("AgentBadge — non-string / absent agent hardening", () => {
    let errSpy: ReturnType<typeof vi.spyOn>;
    let warnSpy: ReturnType<typeof vi.spyOn>;

    beforeEach(() => {
      errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
      warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    });
    afterEach(() => {
      errSpy.mockRestore();
      warnSpy.mockRestore();
    });

    function expectNoBadgeNoNoise() {
      expect(screen.queryByTestId("agent-badge")).toBeNull();
      expect(errSpy).not.toHaveBeenCalled();
      expect(warnSpy).not.toHaveBeenCalled();
    }

    it("does not crash when agent is a number (legacy/malformed row)", () => {
      // @ts-expect-error producer-owned JSONL can emit a non-string agent
      expect(() => render(<AgentBadge agent={123} />)).not.toThrow();
      expectNoBadgeNoNoise();
    });

    it("does not crash when agent is an object", () => {
      // @ts-expect-error producer-owned JSONL can emit a non-string agent
      expect(() => render(<AgentBadge agent={{ name: "coordinator" }} />)).not.toThrow();
      expectNoBadgeNoNoise();
    });

    it("does not crash when agent is an array", () => {
      // @ts-expect-error producer-owned JSONL can emit a non-string agent
      expect(() => render(<AgentBadge agent={["coordinator"]} />)).not.toThrow();
      expectNoBadgeNoNoise();
    });

    it("does not crash when agent is a boolean", () => {
      // @ts-expect-error producer-owned JSONL can emit a non-string agent
      expect(() => render(<AgentBadge agent={true} />)).not.toThrow();
      expectNoBadgeNoNoise();
    });

    it("does not crash when agent is undefined (optional field absent)", () => {
      expect(() => render(<AgentBadge agent={undefined} />)).not.toThrow();
      expectNoBadgeNoNoise();
    });

    it("still renders a normal string agent unchanged (no regression)", () => {
      render(<AgentBadge agent="coordinator" />);
      const badge = screen.getByTestId("agent-badge");
      expect(badge).toHaveTextContent("coordinator");
      expect(errSpy).not.toHaveBeenCalled();
      expect(warnSpy).not.toHaveBeenCalled();
    });

    it("renders the forward-compat nemoclaw_agent value as a quiet badge", () => {
      // The new EMIT value (not in the data yet) — must render, not crash.
      render(<AgentBadge agent="nemoclaw_agent" />);
      const badge = screen.getByTestId("agent-badge");
      expect(badge).toHaveTextContent("nemoclaw_agent");
      expect(badge.className).toContain("text-zinc-400"); // quiet/unknown tone
    });
  });
});

describe("AgentBadge hardening — prototype-name string collision (r2)", () => {
  describe("AgentBadge — prototype-name string collision hardening (r2)", () => {
    let errSpy: ReturnType<typeof vi.spyOn>;
    let warnSpy: ReturnType<typeof vi.spyOn>;

    beforeEach(() => {
      errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
      warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    });
    afterEach(() => {
      errSpy.mockRestore();
      warnSpy.mockRestore();
    });

    for (const key of PROTO_KEYS) {
      it(`renders "${key}" as a quiet badge — no garbage className, no crash`, () => {
        expect(() => render(<AgentBadge agent={key} />)).not.toThrow();
        const badge = screen.getByTestId("agent-badge");
        const cn = badge.className;
        // The bug: a function literal / "[object Object]" leaked into className.
        expect(cn).not.toContain("function");
        expect(cn).not.toContain("native code");
        expect(cn).not.toContain("[object");
        // Unknown agent => quiet zinc tone, with the value shown as its own label.
        expect(cn).toContain("text-zinc-400");
        expect(badge).toHaveTextContent(key);
        // No React render error/warn on this category.
        expect(errSpy).not.toHaveBeenCalled();
        expect(warnSpy).not.toHaveBeenCalled();
      });
    }

    it("does not crash on a workflow agent whose role collides with a proto name", () => {
      // workflow:* takes the compaction path (not the TONE lookup), but guard it too.
      expect(() =>
        render(<AgentBadge agent="workflow:wf-1/constructor" />),
      ).not.toThrow();
      const badge = screen.getByTestId("agent-badge");
      expect(badge).toHaveTextContent("wf:constructor");
      expect(badge.className).toContain("text-indigo-300"); // workflow tone, intact
      expect(badge.className).not.toContain("function");
      expect(errSpy).not.toHaveBeenCalled();
      expect(warnSpy).not.toHaveBeenCalled();
    });

    it("still tones a real known agent correctly (no regression from the guard)", () => {
      render(<AgentBadge agent="coordinator" />);
      const badge = screen.getByTestId("agent-badge");
      expect(badge).toHaveTextContent("coordinator");
      expect(badge.className).toContain("text-sky-300"); // own-key lookup still hits
      expect(errSpy).not.toHaveBeenCalled();
      expect(warnSpy).not.toHaveBeenCalled();
    });
  });
});
