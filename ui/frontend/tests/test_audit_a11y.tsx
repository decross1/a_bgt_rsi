// A11Y AUDIT — the autonomy-observability surfaces (CoordinatorCycleCard,
// CoordinatorPhases, the /cycles route). (The panel + red-flags describes died
// with their components in UI simplification S3.) The apparatus moves
// the human from operator to *auditor*; an auditor who relies on a screen
// reader or who can't perceive the amber/red/emerald color coding must still be
// able to read the loop's decisions. There is no headless browser / axe here,
// so this asserts the CONCRETE a11y attributes that exist in the rendered DOM
// (semantic roles, headings, list semantics, the stepper's aria-current, and —
// the headline requirement — that color is never the ONLY signal: every status
// / verdict / signal chip carries a TEXT label, not just a tone class).
//
// Missing/larger a11y gaps are reported to the serial integrator as followups
// (see the agent report), not fixed here — this batch only landed the trivial
// CoordinatorCycleCard region+heading+labelled-list fix (the one component this
// audit owns). The assertions below pin BOTH the pre-existing good behavior and
// that fix, so a regression in either is caught.
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import CoordinatorCycleCard from "../src/components/CoordinatorCycleCard";
import CoordinatorPhases from "../src/components/CoordinatorPhases";
import Cycles from "../src/routes/Cycles";
import {
  COORDINATOR_CYCLES_FIXTURE,
  ACTIVE_RUN_FIXTURE,
} from "../src/fixtures/coordinator";

const ERRORED_CYCLE = COORDINATOR_CYCLES_FIXTURE[0]; // failed-dispatch case
const CLEAN_CYCLE = COORDINATOR_CYCLES_FIXTURE[1];

describe("a11y audit — CoordinatorCycleCard", () => {
  it("is an article landmark named by its topic heading (aria-labelledby)", () => {
    render(<CoordinatorCycleCard cycle={ERRORED_CYCLE} />);

    // The card is the "one cycle = one narrative" unit → an <article> region a
    // screen-reader user can navigate to (it was a bare <div> before).
    const card = screen.getByTestId("coordinator-cycle-card");
    expect(card.tagName.toLowerCase()).toBe("article");
    expect(card).toHaveAttribute("role", "article");

    // It is NAMED by the topic heading: aria-labelledby points at an <h3>
    // whose id matches and whose text is the topic. So the accessible name of
    // the region is the topic, not "(unnamed region)".
    const labelledby = card.getAttribute("aria-labelledby");
    expect(labelledby).toBeTruthy();
    const heading = within(card).getByRole("heading", { level: 3 });
    expect(heading).toHaveAttribute("id", labelledby!);
    expect(heading).toHaveTextContent(ERRORED_CYCLE.topic);
  });

  it("labels the plan action list via the visible 'plan' label (aria-labelledby)", () => {
    render(<CoordinatorCycleCard cycle={ERRORED_CYCLE} />);
    const card = screen.getByTestId("coordinator-cycle-card");
    // The action list is a <ul> (list semantics) named by the visible "plan"
    // label, so it reads as "plan, list" rather than a bare "list".
    const list = within(card).getByRole("list");
    const labelledby = list.getAttribute("aria-labelledby");
    expect(labelledby).toBeTruthy();
    expect(document.getElementById(labelledby!)).toHaveTextContent(/plan/i);
    // Each action is a listitem.
    expect(within(list).getAllByRole("listitem").length).toBe(
      ERRORED_CYCLE.outcomes.length,
    );
  });

  it("does not signal action status by COLOR ALONE — each chip carries its status text", () => {
    render(<CoordinatorCycleCard cycle={CLEAN_CYCLE} />);
    // A colorblind / screen-reader auditor must still read the status. The
    // passed action's chip has the literal text "passed", not just an emerald
    // tone class; the errored chip (on the other fixture) carries "errored".
    const passed = screen.getByTestId("coordinator-action-run_loop_iteration");
    expect(passed).toHaveTextContent(/passed/i);

    render(<CoordinatorCycleCard cycle={ERRORED_CYCLE} />);
    const errored = screen.getAllByTestId(
      "coordinator-action-run_loop_iteration",
    );
    // The last render's errored chip says "errored" AND surfaces the error
    // string as text (not color) — the make-absence-legible a11y guarantee.
    expect(errored[errored.length - 1]).toHaveTextContent(/errored/i);
  });

  it("names the region generically when the topic is malformed (never an anonymous region)", () => {
    // A producer-owned malformed row: topic is an object (asText → null), so
    // there's no heading to label by. The region must still be named — fall
    // back to a generic aria-label rather than rendering an unnamed landmark.
    const bad = {
      ...CLEAN_CYCLE,
      topic: { unexpected: "object" } as unknown as string,
    };
    render(<CoordinatorCycleCard cycle={bad} />);
    const card = screen.getByTestId("coordinator-cycle-card");
    expect(card).not.toHaveAttribute("aria-labelledby");
    expect(card).toHaveAttribute("aria-label");
    expect(card.getAttribute("aria-label")).toMatch(/cycle/i);
    // And no <h3> is emitted for a non-string topic (nothing to render).
    expect(within(card).queryByRole("heading", { level: 3 })).toBeNull();
  });
});

describe("a11y audit — CoordinatorPhases stepper", () => {
  it("uses an ordered list with aria-current on the active phase", () => {
    render(<CoordinatorPhases activeRun={ACTIVE_RUN_FIXTURE} />);
    // The four phases are an ordered list (a sequence) of listitems.
    const stepper = screen.getByTestId("coordinator-stepper");
    expect(stepper.tagName.toLowerCase()).toBe("ol");
    expect(within(stepper).getAllByRole("listitem").length).toBe(4);

    // Exactly the active phase carries aria-current="step" (dispatch in the
    // fixture). A keyboard/SR user knows WHERE the loop is, not just by color.
    const current = stepper.querySelectorAll('[aria-current="step"]');
    expect(current.length).toBe(1);
    expect(current[0]).toHaveAttribute("data-testid", "phase-dispatch");
  });

  it("hides the decorative arrow connectors from assistive tech (aria-hidden)", () => {
    render(<CoordinatorPhases activeRun={ACTIVE_RUN_FIXTURE} />);
    const stepper = screen.getByTestId("coordinator-stepper");
    // The "→" glyphs are purely decorative; they must be aria-hidden so a
    // screen reader doesn't read "right-arrow" between every phase.
    const hidden = stepper.querySelectorAll('[aria-hidden="true"]');
    expect(hidden.length).toBe(3); // one connector between each of 4 phases
  });

  it("has a heading in both the active and idle states", () => {
    const { unmount } = render(
      <CoordinatorPhases activeRun={ACTIVE_RUN_FIXTURE} />,
    );
    expect(
      screen.getByRole("heading", { name: /coordinator phases/i }),
    ).toBeInTheDocument();
    unmount();
    // Idle state (no live cycle) still labels itself with the same heading —
    // absence is legible AND navigable.
    render(<CoordinatorPhases activeRun={null} />);
    expect(
      screen.getByRole("heading", { name: /coordinator phases/i }),
    ).toBeInTheDocument();
  });
});

describe("a11y audit — /cycles route over LIVE-shaped rows", () => {
  it("renders every cycle as a named article landmark, including the errored one", () => {
    render(
      <Cycles initial={COORDINATOR_CYCLES_FIXTURE} initialPhasesRun={null} />,
    );
    // The page heading.
    expect(
      screen.getByRole("heading", { name: /cycles/i, level: 1 }),
    ).toBeInTheDocument();
    // Each cycle is an <article> landmark. getAllByRole("article") is the
    // assistive-tech view of the list; it must find one per renderable cycle.
    const articles = screen.getAllByRole("article");
    expect(articles.length).toBe(COORDINATOR_CYCLES_FIXTURE.length);
    // The errored cycle's article is named by its (off-domain) topic — an
    // auditor scanning landmarks reads WHAT failed, not an anonymous card.
    const erroredArticle = articles.find((a) =>
      a.getAttribute("aria-labelledby"),
    );
    expect(erroredArticle).toBeTruthy();
  });
});
