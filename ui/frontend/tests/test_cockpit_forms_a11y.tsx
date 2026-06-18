// A11Y PASS — the NEW cockpit resolution form components (outcomes 4/5/6, the
// directive sign-off add-on, and the pre-verdict calibration capture). The
// apparatus moves the human from operator to *auditor*; an auditor on a screen
// reader must be able to (a) find and name every input/select/textarea, (b)
// reach a real submit <button>, (c) read the read-only would-run preview as a
// named region, and (d) perceive the disabled-stub state without relying on
// color. There is no headless browser / axe here, so this pins the CONCRETE a11y
// guarantees in the rendered DOM (accessible names via label/aria-label, real
// button semantics, the would-run <pre> carrying an accessible name, and the
// stub-disabled state being conveyed via the `disabled` attribute, not tone).
//
// This is ADDITIVE a11y only — behavior-preserving. The pre-existing contract
// test (test_cockpit_resolution_forms.tsx) pins the field shapes + valid-input
// behavior; this file pins the accessibility surface so a future tone-only
// "simplification" that drops a label / turns the button into a clickable div /
// strips the would-run name is caught.
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import AuthorizeFixForm from "../src/components/todo/AuthorizeFixForm";
import SpawnTopicForm from "../src/components/todo/SpawnTopicForm";
import AbstainForm from "../src/components/todo/AbstainForm";
import DirectiveSignOffField from "../src/components/todo/DirectiveSignOffField";
import CalibrationCapture from "../src/components/todo/CalibrationCapture";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// A render-time a11y regression (a missing key, an act() warning, a throw)
// surfaces on console.error in jsdom; assert it stays clean across every case.
function spyConsole() {
  return vi.spyOn(console, "error").mockImplementation(() => {});
}

// =========================================================================
// AuthorizeFixForm (outcome 4) — textarea + note input, real submit button,
// named would-run <pre>, conveyed stub-disabled state.
// =========================================================================
describe("a11y — AuthorizeFixForm", () => {
  it("the task textarea and note input each have an accessible name", () => {
    const errSpy = spyConsole();
    render(<AuthorizeFixForm findingId="f1" available={true} />);
    // queryByLabelText resolves the accessible name (aria-label here); a missing
    // label would make these throw / return null.
    const task = screen.getByLabelText(/authorize-fix task/i);
    expect(task.tagName.toLowerCase()).toBe("textarea");
    const note = screen.getByLabelText(/authorize-fix note/i);
    expect(note.tagName.toLowerCase()).toBe("input");
    expect(errSpy).not.toHaveBeenCalled();
  });

  it("submit is a real <button type=button> reachable by role+name", () => {
    render(<AuthorizeFixForm findingId="f1" available={true} />);
    const btn = screen.getByRole("button", { name: /authorize fix/i });
    expect(btn.tagName.toLowerCase()).toBe("button");
    expect(btn).toHaveAttribute("type", "button");
  });

  it("the read-only would-run preview is a <pre> with an accessible name", () => {
    render(<AuthorizeFixForm findingId="f1" available={true} />);
    const pre = screen.getByTestId("authorize-fix-argv");
    expect(pre.tagName.toLowerCase()).toBe("pre");
    // Named so a SR user reads "would run, ..." not an anonymous block.
    expect(pre).toHaveAccessibleName(/would run/i);
  });

  it("stub state conveys disabled via the disabled attribute, not color alone", () => {
    // available !== true → honest stub; the submit must be programmatically
    // disabled (perceivable to AT), and the stub copy is TEXT not just a tone.
    render(<AuthorizeFixForm findingId="f1" available={false} />);
    expect(screen.getByRole("button", { name: /authorize fix/i })).toBeDisabled();
    expect(screen.getByTestId("authorize-fix-stub")).toHaveTextContent(/stub/i);
  });
});

// =========================================================================
// SpawnTopicForm (outcome 5) — labelled <select>, labelled topic input.
// =========================================================================
describe("a11y — SpawnTopicForm", () => {
  it("the kind <select> is reachable by role with an accessible name", () => {
    const errSpy = spyConsole();
    render(<SpawnTopicForm findingId="f1" available={true} />);
    // combobox is the ARIA role of a <select>; name comes from its aria-label.
    const select = screen.getByRole("combobox", { name: /kind/i });
    expect(select.tagName.toLowerCase()).toBe("select");
    // Both options are present and named.
    expect(
      within(select).getByRole("option", { name: "finding" }),
    ).toBeInTheDocument();
    expect(within(select).getByRole("option", { name: "step" })).toBeInTheDocument();
    expect(errSpy).not.toHaveBeenCalled();
  });

  it("the topic input has an accessible name", () => {
    render(<SpawnTopicForm findingId="f1" available={true} />);
    expect(screen.getByLabelText(/new topic/i).tagName.toLowerCase()).toBe("input");
  });

  it("submit is a real button; would-run <pre> is named; stub disables submit", () => {
    render(<SpawnTopicForm findingId="f1" available={false} />);
    const btn = screen.getByRole("button", { name: /spawn topic/i });
    expect(btn).toHaveAttribute("type", "button");
    expect(btn).toBeDisabled();
    const pre = screen.getByTestId("spawn-topic-argv");
    expect(pre.tagName.toLowerCase()).toBe("pre");
    expect(pre).toHaveAccessibleName(/would run/i);
    expect(screen.getByTestId("spawn-topic-stub")).toHaveTextContent(/stub/i);
  });
});

// =========================================================================
// AbstainForm (outcome 6) — labelled note input, named would-run, stub state.
// =========================================================================
describe("a11y — AbstainForm", () => {
  it("the note input has an accessible name and submit is a real button", () => {
    const errSpy = spyConsole();
    render(<AbstainForm findingId="f1" available={true} />);
    expect(screen.getByLabelText(/abstain note/i).tagName.toLowerCase()).toBe(
      "input",
    );
    const btn = screen.getByRole("button", { name: /^abstain$/i });
    expect(btn).toHaveAttribute("type", "button");
    expect(errSpy).not.toHaveBeenCalled();
  });

  it("the would-run preview is a named <pre>", () => {
    render(<AbstainForm findingId="f1" available={true} />);
    const pre = screen.getByTestId("abstain-argv");
    expect(pre.tagName.toLowerCase()).toBe("pre");
    expect(pre).toHaveAccessibleName(/would run/i);
  });

  it("stub state disables submit (conveyed, not color-only)", () => {
    render(<AbstainForm findingId="f1" available={false} />);
    expect(screen.getByRole("button", { name: /^abstain$/i })).toBeDisabled();
    expect(screen.getByTestId("abstain-stub")).toHaveTextContent(/stub/i);
  });
});

// =========================================================================
// DirectiveSignOffField — labelled directive input; would-run named when shown.
// =========================================================================
describe("a11y — DirectiveSignOffField", () => {
  it("the directive input has an accessible name; submit is a real button", () => {
    const errSpy = spyConsole();
    render(<DirectiveSignOffField findingId="iter-1" note="why" available={true} />);
    expect(screen.getByLabelText(/sign-off directive/i).tagName.toLowerCase()).toBe(
      "input",
    );
    const btn = screen.getByRole("button", { name: /sign off with directive/i });
    expect(btn).toHaveAttribute("type", "button");
    // Empty directive → bare sign-off → submit stays disabled (conveyed state).
    expect(btn).toBeDisabled();
    expect(errSpy).not.toHaveBeenCalled();
  });

  it("the would-run <pre> is named once a directive is entered", () => {
    const errSpy = spyConsole();
    render(
      <DirectiveSignOffField
        findingId="iter-1"
        note="why"
        available={true}
      />,
    );
    // The argv only renders when a directive is non-empty; drive the input.
    const input = screen.getByLabelText(/sign-off directive/i);
    fireEvent.change(input, { target: { value: "proceed to step 9" } });
    const pre = screen.getByTestId("directive-signoff-argv");
    expect(pre.tagName.toLowerCase()).toBe("pre");
    expect(pre).toHaveAccessibleName(/would run/i);
    expect(errSpy).not.toHaveBeenCalled();
  });

  it("stub state disables the directive submit (conveyed, not color-only)", () => {
    render(<DirectiveSignOffField findingId="iter-1" note="why" available={false} />);
    expect(
      screen.getByRole("button", { name: /sign off with directive/i }),
    ).toBeDisabled();
    expect(screen.getByTestId("directive-signoff-stub")).toHaveTextContent(/stub/i);
  });
});

// =========================================================================
// CalibrationCapture — labelled prediction input + labelled range; real button.
// =========================================================================
describe("a11y — CalibrationCapture", () => {
  it("the prediction input and confidence slider each have accessible names", () => {
    const errSpy = spyConsole();
    render(
      <CalibrationCapture refId="f1" available={true} onCaptured={() => {}} />,
    );
    expect(
      screen.getByLabelText(/calibration prediction/i).tagName.toLowerCase(),
    ).toBe("input");
    // A range input exposes the slider role; it is named via aria-label.
    const slider = screen.getByRole("slider", { name: /calibration confidence/i });
    expect(slider).toHaveAttribute("type", "range");
    expect(errSpy).not.toHaveBeenCalled();
  });

  it("the capture control is a real <button type=button>", () => {
    render(
      <CalibrationCapture refId="f1" available={true} onCaptured={() => {}} />,
    );
    const btn = screen.getByRole("button", { name: /capture calibration/i });
    expect(btn.tagName.toLowerCase()).toBe("button");
    expect(btn).toHaveAttribute("type", "button");
  });

  it("the stub-availability state is conveyed by TEXT, not color alone", () => {
    render(
      <CalibrationCapture refId="f1" available={false} onCaptured={() => {}} />,
    );
    // The unavailable state carries readable text (not just a tone class):
    // the input is captured locally but not durably written.
    expect(screen.getByTestId("calibration-stub-banner")).toHaveTextContent(
      /not durably written|captured locally/i,
    );
    // Empty prediction → capture disabled, perceivable via the disabled attr.
    expect(
      screen.getByRole("button", { name: /capture calibration/i }),
    ).toBeDisabled();
  });
});
