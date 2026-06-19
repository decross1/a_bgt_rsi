// Hardening for CalibrationCapture (ui/components/todo/CalibrationCapture.tsx)
// against the HOUSE ROBUSTNESS DOCTRINE.
//
// SURFACE FOCUS: confidence bounds [0,1] + non-number/NaN/Infinity; the
// capture-BEFORE-verdict ordering contract (onCaptured fires ONLY after a
// successful capture, and never before) holding under odd inputs.
//
// Why these guards: confidence flows from a <input type=range> whose onChange is
// `Number(e.target.value)` — a non-numeric value coerces to NaN, and a malformed
// initial/version-skew value could arrive < 0 or > 1. Unclamped, `.toFixed(2)`
// renders the human-facing label as "NaN"/"Infinity" and an out-of-[0,1]
// confidence is handed to the calibration ledger via onCaptured (the very number
// ARCH §6.5.4 wants honest). refId is producer-owned (a loop_memory finding
// id) — a null/non-string value must degrade to an empty ref, never crash the
// trim/POST. The fix clamps confidence into [0,1] (non-finite → 0.5 midpoint) and
// coerces a non-string refId to "". VALID-input behavior is unchanged
// (the existing test_cockpit_interrogation.tsx CalibrationCapture spec still
// passes — see DONE).
//
// No headless browser in this stack, so "renders without console errors" is the
// jsdom stand-in: render and assert console.error / console.warn were not called.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import CalibrationCapture from "../src/components/todo/CalibrationCapture";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function watchConsole() {
  return {
    error: vi.spyOn(console, "error").mockImplementation(() => {}),
    warn: vi.spyOn(console, "warn").mockImplementation(() => {}),
  };
}

// Stub the STUB POST /api/todo/calibration. Records each posted body so the
// ordering + body shape can be asserted; never execs a CLI or touches a ledger.
function stubCalibrationOk(): { calls: Array<Record<string, unknown> | null> } {
  const calls: Array<Record<string, unknown> | null> = [];
  vi.stubGlobal("fetch", async (_url: unknown, init?: RequestInit) => {
    calls.push(
      typeof init?.body === "string"
        ? (JSON.parse(init.body) as Record<string, unknown>)
        : null,
    );
    return {
      ok: true,
      status: 200,
      statusText: "200",
      json: async () => ({ stub: true, would_run: ["...argv..."] }),
    } as unknown as Response;
  });
  return { calls };
}

// A fetch that rejects/errors at the network layer — the capture must surface an
// error and, crucially, NOT fire onCaptured (the ordering contract: a failed
// capture must never open the verdict).
function stubCalibrationNetworkError() {
  vi.stubGlobal("fetch", async () => {
    throw new TypeError("network down");
  });
}

// A fetch that returns a version-skew 404 (running backend predates the seam).
function stubCalibration404() {
  vi.stubGlobal("fetch", async () => {
    return {
      ok: false,
      status: 404,
      statusText: "Not Found",
      json: async () => {
        throw new Error("no body");
      },
    } as unknown as Response;
  });
}

describe("CalibrationCapture hardening — confidence bounds + non-number/NaN", () => {
  it("the regression: an out-of-range confidence is CLAMPED into [0,1] before onCaptured", async () => {
    // A range input can be driven (by an odd browser / programmatic value) past
    // its declared min/max; the captured number must never escape [0,1].
    const { calls } = stubCalibrationOk();
    const c = watchConsole();
    const onCaptured = vi.fn();
    render(<CalibrationCapture refId="sf-iter-x" onCaptured={onCaptured} />);

    fireEvent.change(screen.getByLabelText(/calibration prediction/i), {
      target: { value: "survives" },
    });
    // Way above the max — must clamp to 1.
    fireEvent.change(screen.getByLabelText(/calibration confidence/i), {
      target: { value: "7" },
    });
    // The human-facing label degrades to the clamped value, never "7.00".
    expect(screen.getByText("1.00")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: /record blind calibration/i }),
    );
    await waitFor(() => expect(onCaptured).toHaveBeenCalledTimes(1));
    expect(onCaptured).toHaveBeenCalledWith({ prediction: "survives", confidence: 1 });
    expect(calls[0]).toMatchObject({ confidence: 1 });
    expect(c.error).not.toHaveBeenCalled();
    expect(c.warn).not.toHaveBeenCalled();
  });

  it("a negative confidence clamps to 0 (label + captured draft + body all 0)", async () => {
    const { calls } = stubCalibrationOk();
    const onCaptured = vi.fn();
    render(<CalibrationCapture refId="sf-iter-x" onCaptured={onCaptured} />);
    fireEvent.change(screen.getByLabelText(/calibration prediction/i), {
      target: { value: "fails" },
    });
    fireEvent.change(screen.getByLabelText(/calibration confidence/i), {
      target: { value: "-3" },
    });
    expect(screen.getByText("0.00")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: /record blind calibration/i }),
    );
    await waitFor(() => expect(onCaptured).toHaveBeenCalledTimes(1));
    expect(onCaptured).toHaveBeenCalledWith({ prediction: "fails", confidence: 0 });
    expect(calls[0]).toMatchObject({ confidence: 0 });
  });

  it("a NaN confidence (non-numeric range value) degrades to the 0.5 midpoint, never prints 'NaN'", async () => {
    const { calls } = stubCalibrationOk();
    const c = watchConsole();
    const onCaptured = vi.fn();
    const { container } = render(
      <CalibrationCapture refId="sf-iter-x" onCaptured={onCaptured} />,
    );
    fireEvent.change(screen.getByLabelText(/calibration prediction/i), {
      target: { value: "unknown" },
    });
    // Number("garbage") === NaN — the exact NaN-from-range hazard.
    fireEvent.change(screen.getByLabelText(/calibration confidence/i), {
      target: { value: "garbage" },
    });
    // Degrades to the neutral midpoint; the label never shows "NaN".
    expect(container.innerHTML).not.toContain("NaN");
    expect(screen.getByText("0.50")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: /record blind calibration/i }),
    );
    await waitFor(() => expect(onCaptured).toHaveBeenCalledTimes(1));
    expect(onCaptured).toHaveBeenCalledWith({ prediction: "unknown", confidence: 0.5 });
    expect(calls[0]).toMatchObject({ confidence: 0.5 });
    expect(c.error).not.toHaveBeenCalled();
    expect(c.warn).not.toHaveBeenCalled();
  });

  it("an Infinity confidence never leaks 'Infinity' into the label and captures a finite, in-range number", async () => {
    const { calls } = stubCalibrationOk();
    const onCaptured = vi.fn();
    const { container } = render(
      <CalibrationCapture refId="sf-iter-x" onCaptured={onCaptured} />,
    );
    fireEvent.change(screen.getByLabelText(/calibration prediction/i), {
      target: { value: "p" },
    });
    fireEvent.change(screen.getByLabelText(/calibration confidence/i), {
      target: { value: "Infinity" },
    });
    expect(container.innerHTML).not.toContain("Infinity");
    fireEvent.click(
      screen.getByRole("button", { name: /record blind calibration/i }),
    );
    await waitFor(() => expect(onCaptured).toHaveBeenCalledTimes(1));
    const draft = onCaptured.mock.calls[0][0] as { confidence: number };
    expect(Number.isFinite(draft.confidence)).toBe(true);
    expect(draft.confidence).toBeGreaterThanOrEqual(0);
    expect(draft.confidence).toBeLessThanOrEqual(1);
    expect(calls[0]).toMatchObject({ confidence: draft.confidence });
  });

  it("a valid in-range confidence is captured UNCHANGED (the clamp did not over-correct)", async () => {
    const { calls } = stubCalibrationOk();
    const onCaptured = vi.fn();
    render(<CalibrationCapture refId="sf-iter-x" onCaptured={onCaptured} />);
    fireEvent.change(screen.getByLabelText(/calibration prediction/i), {
      target: { value: "survives 2/3" },
    });
    fireEvent.change(screen.getByLabelText(/calibration confidence/i), {
      target: { value: "0.7" },
    });
    expect(screen.getByText("0.70")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: /record blind calibration/i }),
    );
    await waitFor(() => expect(onCaptured).toHaveBeenCalledTimes(1));
    expect(onCaptured).toHaveBeenCalledWith({
      prediction: "survives 2/3",
      confidence: 0.7,
    });
    expect(calls[0]).toMatchObject({ confidence: 0.7 });
  });
});

describe("CalibrationCapture hardening — capture-BEFORE-verdict ordering under odd inputs", () => {
  it("the contract: onCaptured does NOT fire when the POST fails at the network layer", async () => {
    stubCalibrationNetworkError();
    const c = watchConsole();
    const onCaptured = vi.fn();
    render(<CalibrationCapture refId="sf-iter-x" onCaptured={onCaptured} />);
    fireEvent.change(screen.getByLabelText(/calibration prediction/i), {
      target: { value: "survives" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /record blind calibration/i }),
    );
    // The error path renders, but the verdict must NEVER be opened on a failed
    // capture — onCaptured stays unfired.
    await waitFor(() =>
      expect(screen.getByTestId("calibration-error")).toBeInTheDocument(),
    );
    expect(onCaptured).not.toHaveBeenCalled();
    // The captured-success affordance never appeared.
    expect(screen.queryByTestId("calibration-captured")).toBeNull();
    expect(c.error).not.toHaveBeenCalled();
    expect(c.warn).not.toHaveBeenCalled();
  });

  it("a version-skew 404 surfaces an error and does NOT open the verdict (onCaptured unfired)", async () => {
    stubCalibration404();
    const onCaptured = vi.fn();
    render(<CalibrationCapture refId="sf-iter-x" onCaptured={onCaptured} />);
    fireEvent.change(screen.getByLabelText(/calibration prediction/i), {
      target: { value: "survives" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /record blind calibration/i }),
    );
    await waitFor(() =>
      expect(screen.getByTestId("calibration-error")).toBeInTheDocument(),
    );
    expect(onCaptured).not.toHaveBeenCalled();
    expect(screen.queryByTestId("calibration-captured")).toBeNull();
  });

  it("onCaptured never fires BEFORE a click (no auto-open) — empty prediction keeps the button disabled", () => {
    stubCalibrationOk();
    const onCaptured = vi.fn();
    render(<CalibrationCapture refId="sf-iter-x" onCaptured={onCaptured} />);
    // Before any interaction the verdict is NOT opened.
    expect(onCaptured).not.toHaveBeenCalled();
    // A whitespace-only prediction must not satisfy the required gate.
    fireEvent.change(screen.getByLabelText(/calibration prediction/i), {
      target: { value: "   " },
    });
    expect(
      screen.getByRole("button", { name: /record blind calibration/i }),
    ).toBeDisabled();
    expect(onCaptured).not.toHaveBeenCalled();
  });
});

describe("CalibrationCapture hardening — malformed refId prop", () => {
  // refId is producer-owned; the Props type says string, but a partial/legacy
  // record can hand a null/number/object at runtime. It must degrade to an empty
  // ref, never crash the render or the POST.
  const BAD_IDS: Array<[string, unknown]> = [
    ["null", null],
    ["undefined", undefined],
    ["a number", 42],
    ["an object", { id: "x" }],
    ["an array", ["a", "b"]],
    ["NaN", NaN],
  ];

  it("renders without throwing for every malformed refId", () => {
    for (const [name, id] of BAD_IDS) {
      const c = watchConsole();
      const { unmount } = render(
        <CalibrationCapture
          refId={id as unknown as string}
          onCaptured={vi.fn()}
        />,
      );
      // The capture UI is present (capture still works locally — ARCH §6.5.4).
      expect(screen.getByTestId("calibration-capture"), name).toBeInTheDocument();
      expect(c.error, name).not.toHaveBeenCalled();
      expect(c.warn, name).not.toHaveBeenCalled();
      unmount();
    }
  });

  it("a null refId POSTs an empty ref_id (degrade, not crash) and still honors the ordering contract", async () => {
    const { calls } = stubCalibrationOk();
    const onCaptured = vi.fn();
    render(
      <CalibrationCapture
        refId={null as unknown as string}
        onCaptured={onCaptured}
      />,
    );
    fireEvent.change(screen.getByLabelText(/calibration prediction/i), {
      target: { value: "survives" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /record blind calibration/i }),
    );
    await waitFor(() => expect(onCaptured).toHaveBeenCalledTimes(1));
    // Degraded to an empty ref — never the string "null"/"undefined".
    expect(calls[0]).toMatchObject({ ref_id: "", prediction: "survives" });
  });
});

describe("CalibrationCapture hardening — onCaptured throwing AFTER a successful POST", () => {
  // THE ADVERSARIAL CASE: the POST is the durable capture (once the seam lands it
  // writes the calibration_entry). onCaptured is the shell's verdict-reveal
  // callback — a producer-owned finding id, a malformed draft echo, or any render
  // fault in the revealed verdict form can make it THROW. The original code ran
  // onCaptured INSIDE the same try as the POST, so a callback throw was caught and
  // mislabeled as a FAILED capture: the UI rolled back to the error/retry state
  // even though the durable write had already happened. Retrying would (once the
  // seam lands) double-write the ledger. The fix: a POST failure (no write) is the
  // ONLY thing that opens the error/retry path; a throw from the post-success
  // callback leaves the capture standing (phase === "captured", no error shown).
  function stubCalibrationOkRec(): { calls: Array<Record<string, unknown> | null> } {
    const calls: Array<Record<string, unknown> | null> = [];
    vi.stubGlobal("fetch", async (_url: unknown, init?: RequestInit) => {
      calls.push(
        typeof init?.body === "string"
          ? (JSON.parse(init.body) as Record<string, unknown>)
          : null,
      );
      return {
        ok: true,
        status: 200,
        statusText: "200",
        json: async () => ({ stub: true }),
      } as unknown as Response;
    });
    return { calls };
  }

  it("a throwing onCaptured does NOT roll the successful capture back to the error/retry state", async () => {
    const { calls } = stubCalibrationOkRec();
    // jsdom logs the React error-boundary-less throw path noisily; the throw is
    // intentional here, so silence console.error for this one case only.
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const onCaptured = vi.fn(() => {
      throw new Error("shell verdict-reveal blew up");
    });
    render(<CalibrationCapture refId="sf-iter-x" onCaptured={onCaptured} />);
    fireEvent.change(screen.getByLabelText(/calibration prediction/i), {
      target: { value: "captured then callback throws" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /record blind calibration/i }),
    );
    await waitFor(() => expect(onCaptured).toHaveBeenCalledTimes(1));

    // The POST (the durable capture, once the seam lands) happened exactly once.
    expect(calls.length).toBe(1);
    // The capture STANDS: the success affordance is shown and the error/retry
    // path is NOT — a callback fault must not masquerade as a failed capture.
    expect(screen.getByTestId("calibration-captured")).toBeInTheDocument();
    expect(screen.queryByTestId("calibration-error")).toBeNull();
    // The capture form is gone (no re-present → no double-write on retry).
    expect(
      screen.queryByRole("button", {
        name: /record blind calibration/i,
      }),
    ).toBeNull();
    errSpy.mockRestore();
  });

  it("a POST failure STILL opens the error path and never fires onCaptured (the fix did not weaken the failure contract)", async () => {
    // Guard the other side of the split: an actual POST failure must still surface
    // an error AND keep onCaptured unfired (no durable write → safe to retry).
    vi.stubGlobal("fetch", async () => {
      throw new TypeError("network down");
    });
    const c = watchConsole();
    const onCaptured = vi.fn();
    render(<CalibrationCapture refId="sf-iter-x" onCaptured={onCaptured} />);
    fireEvent.change(screen.getByLabelText(/calibration prediction/i), {
      target: { value: "post fails" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /record blind calibration/i }),
    );
    await waitFor(() =>
      expect(screen.getByTestId("calibration-error")).toBeInTheDocument(),
    );
    expect(onCaptured).not.toHaveBeenCalled();
    expect(screen.queryByTestId("calibration-captured")).toBeNull();
    expect(c.error).not.toHaveBeenCalled();
    expect(c.warn).not.toHaveBeenCalled();
  });
});

describe("CalibrationCapture hardening — malformed refId prop (POST path)", () => {
  it("a null refId POSTs an empty ref_id (degrade, not crash) and still honors the ordering contract", async () => {
    const { calls } = stubCalibrationOk();
    const onCaptured = vi.fn();
    render(
      <CalibrationCapture
        refId={null as unknown as string}
        onCaptured={onCaptured}
      />,
    );
    fireEvent.change(screen.getByLabelText(/calibration prediction/i), {
      target: { value: "survives" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /record blind calibration/i }),
    );
    await waitFor(() => expect(onCaptured).toHaveBeenCalledTimes(1));
    // Degraded to an empty ref — never the string "null"/"undefined".
    expect(calls[0]).toMatchObject({ ref_id: "", prediction: "survives" });
  });
});
