// HARDEN — SystemActivityHero, focus on the NEW needsYou slot prop.
//
// House robustness doctrine: a slot whose value crosses a prop boundary may
// arrive malformed. needsYou is typed ReactNode, but React THROWS on a child
// it can't render (a bare object / array-of-objects: "Objects are not valid
// as a React child"), and renders a raw number including non-finite ones.
// Every such input must DEGRADE to a legible drop (the slot simply doesn't
// render), NEVER crash or blank the hero. Valid inputs (a React element,
// string, finite number, null/undefined) keep IDENTICAL behavior.
//
// These tests touch ONLY the needsYou render path; the computeActivity state
// machine and its existing tests are untouched.
import { render, screen } from "@testing-library/react";
import { createElement } from "react";
import SystemActivityHero from "../src/components/SystemActivityHero";

const NOW = Date.parse("2026-06-09T20:00:00.000+00:00");

function heroEl() {
  return screen.getByTestId("system-activity-hero");
}
function slot() {
  return screen.queryByTestId("system-activity-needs-you");
}

describe("SystemActivityHero — needsYou slot hardening", () => {
  // ---- valid-input behavior is PRESERVED ----

  it("a valid element renders in the slot (idle baseline still works)", () => {
    render(
      <SystemActivityHero
        nowMs={NOW}
        needsYou={<a data-testid="needs-link">3 need you →</a>}
      />,
    );
    expect(heroEl()).toHaveAttribute("data-state", "idle");
    expect(slot()).not.toBeNull();
    expect(screen.getByTestId("needs-link").textContent).toBe("3 need you →");
  });

  it("a plain string renders verbatim", () => {
    render(<SystemActivityHero nowMs={NOW} needsYou={"none need you →"} />);
    expect(slot()).not.toBeNull();
    expect(slot()!.textContent).toBe("none need you →");
  });

  it("a finite number renders as text", () => {
    render(<SystemActivityHero nowMs={NOW} needsYou={0} />);
    expect(slot()).not.toBeNull();
    expect(slot()!.textContent).toBe("0");
  });

  it("undefined needsYou renders no slot (hero usable outside dashboard)", () => {
    render(<SystemActivityHero nowMs={NOW} />);
    expect(slot()).toBeNull();
    expect(heroEl()).toHaveAttribute("data-state", "idle");
  });

  it("explicit null needsYou renders no slot", () => {
    render(<SystemActivityHero nowMs={NOW} needsYou={null} />);
    expect(slot()).toBeNull();
  });

  // ---- malformed inputs DEGRADE (no crash, no blank) ----

  it("a bare object as needsYou is dropped, not thrown (would-throw guard)", () => {
    render(
      <SystemActivityHero
        nowMs={NOW}
        needsYou={{ count: 3 } as unknown as React.ReactNode}
      />,
    );
    // The hero still renders; the malformed slot is simply absent.
    expect(heroEl()).toHaveAttribute("data-state", "idle");
    expect(slot()).toBeNull();
    expect(heroEl().textContent).not.toContain("[object Object]");
    expect(heroEl().textContent).not.toContain("count");
  });

  it("an array containing a non-element object is dropped, not thrown", () => {
    render(
      <SystemActivityHero
        nowMs={NOW}
        needsYou={[{ a: 1 }, { b: 2 }] as unknown as React.ReactNode}
      />,
    );
    expect(heroEl()).toBeInTheDocument();
    expect(slot()).toBeNull();
    expect(heroEl().textContent).not.toContain("[object Object]");
  });

  it("a mixed array keeps only the legible children (element + string)", () => {
    render(
      <SystemActivityHero
        nowMs={NOW}
        needsYou={
          [
            <a key="k" data-testid="ok-child">
              ok
            </a>,
            { junk: true },
            " tail",
          ] as unknown as React.ReactNode
        }
      />,
    );
    expect(slot()).not.toBeNull();
    expect(screen.getByTestId("ok-child").textContent).toBe("ok");
    expect(slot()!.textContent).toContain("ok");
    expect(slot()!.textContent).toContain("tail");
    expect(slot()!.textContent).not.toContain("[object Object]");
  });

  it("NaN needsYou never renders 'NaN' and drops the slot", () => {
    render(
      <SystemActivityHero
        nowMs={NOW}
        needsYou={Number.NaN as unknown as React.ReactNode}
      />,
    );
    expect(heroEl().textContent).not.toContain("NaN");
    expect(slot()).toBeNull();
  });

  it("Infinity needsYou is dropped (non-finite number)", () => {
    render(
      <SystemActivityHero
        nowMs={NOW}
        needsYou={Number.POSITIVE_INFINITY as unknown as React.ReactNode}
      />,
    );
    expect(heroEl().textContent).not.toContain("Infinity");
    expect(slot()).toBeNull();
  });

  it("a boolean needsYou is dropped (React ignores booleans anyway)", () => {
    render(
      <SystemActivityHero
        nowMs={NOW}
        needsYou={true as unknown as React.ReactNode}
      />,
    );
    expect(slot()).toBeNull();
    expect(heroEl().textContent).not.toContain("true");
  });

  it("an empty array is dropped (empty-vs-absent: no orphan slot wrapper)", () => {
    render(
      <SystemActivityHero
        nowMs={NOW}
        needsYou={[] as unknown as React.ReactNode}
      />,
    );
    expect(slot()).toBeNull();
  });

  it("a function as needsYou is dropped, not thrown", () => {
    render(
      <SystemActivityHero
        nowMs={NOW}
        needsYou={(() => "x") as unknown as React.ReactNode}
      />,
    );
    expect(heroEl()).toBeInTheDocument();
    expect(slot()).toBeNull();
  });

  // ---- ADVERSARIAL: deep-child throw past the shallow isValidElement guard ----
  //
  // asNode passes a VALID element through untouched — it cannot see inside an
  // opaque element. A producer-derived child rendered as <Link>{obj}</Link>
  // (where `obj` arrived as a bare object/array from loop_memory) sails past
  // isValidElement and then THROWS "Objects are not valid as a React child" at
  // render time, blanking the whole always-rendered header. A SlotBoundary
  // catches the render fault and degrades to the absent-slot fallback.

  function consoleQuiet() {
    // React logs caught render errors to console.error; silence the expected
    // noise so the suite output stays legible (the assertions, not the log,
    // are the contract).
    return vi.spyOn(console, "error").mockImplementation(() => {});
  }

  it("a valid element wrapping a bare-object child degrades, never blanks the hero", () => {
    const spy = consoleQuiet();
    const poison = createElement(
      "span",
      { "data-testid": "poison" },
      { summary: "escalation" } as unknown as React.ReactNode,
    );
    render(<SystemActivityHero nowMs={NOW} needsYou={poison} />);
    // The hero header survives — NOT blanked. This is the load-bearing claim:
    // a throw inside the slot must not take down the always-rendered header.
    expect(heroEl()).toHaveAttribute("data-state", "idle");
    expect(heroEl().textContent).toContain("IDLE");
    // The malformed slot is gone (no orphan wrapper, no leaked junk).
    expect(slot()).toBeNull();
    expect(heroEl().textContent).not.toContain("[object Object]");
    spy.mockRestore();
  });

  it("an array of valid elements where one wraps a malformed child degrades legibly", () => {
    const spy = consoleQuiet();
    const ok = createElement("a", { key: "ok", "data-testid": "ok-el" }, "ok");
    const poison = createElement(
      "span",
      { key: "bad" },
      [{ x: 1 }, { y: 2 }] as unknown as React.ReactNode,
    );
    render(
      <SystemActivityHero
        nowMs={NOW}
        needsYou={[ok, poison] as unknown as React.ReactNode}
      />,
    );
    // The whole slot drops (the boundary cannot partially recover one element
    // of a thrown subtree) but the hero header stays up.
    expect(heroEl()).toHaveAttribute("data-state", "idle");
    expect(slot()).toBeNull();
    expect(heroEl().textContent).not.toContain("[object Object]");
    spy.mockRestore();
  });

  it("a child component that throws on render degrades, never blanks the hero", () => {
    const spy = consoleQuiet();
    function Exploder(): React.ReactNode {
      throw new Error("producer-derived deref blew up");
    }
    render(
      <SystemActivityHero
        nowMs={NOW}
        needsYou={createElement(Exploder) as unknown as React.ReactNode}
      />,
    );
    expect(heroEl()).toHaveAttribute("data-state", "idle");
    expect(heroEl().textContent).toContain("IDLE");
    expect(slot()).toBeNull();
    spy.mockRestore();
  });

  it("a deep-throwing slot does not take down the activity verdict (registered state)", () => {
    const spy = consoleQuiet();
    const poison = createElement(
      "span",
      null,
      { bad: "node" } as unknown as React.ReactNode,
    );
    render(
      <SystemActivityHero
        nowMs={NOW}
        activeIteration={{
          iteration_id: "iter-x",
          topic: "boundary isolation",
          started_at: "2026-06-09T19:59:55.000+00:00",
          current_step: "step",
        }}
        needsYou={poison}
      />,
    );
    expect(heroEl()).toHaveAttribute("data-state", "registered");
    expect(heroEl().textContent).toContain(
      "RUNNING — boundary isolation · step",
    );
    expect(slot()).toBeNull();
    spy.mockRestore();
  });

  it("a malformed needsYou does not disturb the activity verdict (busy state)", () => {
    // The slot guard is independent of the state machine: a registered run
    // still renders RUNNING even when needsYou is garbage.
    render(
      <SystemActivityHero
        nowMs={NOW}
        activeIteration={{
          iteration_id: "iter-x",
          topic: "guard isolation",
          started_at: "2026-06-09T19:59:55.000+00:00",
          current_step: "step",
        }}
        needsYou={{ bad: "node" } as unknown as React.ReactNode}
      />,
    );
    expect(heroEl()).toHaveAttribute("data-state", "registered");
    expect(heroEl().textContent).toContain("RUNNING — guard isolation · step");
    expect(slot()).toBeNull();
  });
});
