// Role-E cockpit interrogation surfaces — the leaf components the DOSSIER
// READER mounts (originally the /todo cockpit's; the reader inherited them in
// UI simplification S2). Exercised against the typed fixtures in
// src/fixtures/todo (no network): ConcurrencyWarning, CalibrationCapture,
// TutorPanel.
//
// What this asserts, per the work order:
//   - ConcurrencyWarning: mid-flight => the warn/queue banner shows (naming the
//     contending run); idle => it renders NOTHING (not a hard block).
//   - CalibrationCapture: captures FIRST then fires onCaptured (the ordering
//     contract the shell uses to then reveal the verdict); persists via the
//     STUB postCalibration (writes nothing).
//   - TutorPanel: exposes NO verdict affordance — the fence is visible and the
//     component takes no verdict props. (The unweighted considerations section
//     was TRIMMED in S2 — the reader keeps claim/provenance/evidence refs +
//     the neutral outcome-effects line only.)
//
// The two-voice pane's coverage moved to tests/test_ChatPane.tsx when the
// TutorChatPane + TwoVoiceChatPane pair merged into the mode-parameterized
// ChatPane (S2).
//
// The only network surface touched is postCalibration (POST /api/todo/calibration);
// it is stubbed to return the would-run STUB preview — the test never execs a CLI
// or touches a live ledger.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ConcurrencyWarning from "../src/components/todo/ConcurrencyWarning";
import CalibrationCapture from "../src/components/todo/CalibrationCapture";
import TutorPanel from "../src/components/todo/TutorPanel";
import {
  CONCURRENCY_IDLE,
  CONCURRENCY_MIDFLIGHT,
} from "../src/fixtures/todo";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

// --- ConcurrencyWarning ---

describe("ConcurrencyWarning", () => {
  it("shows a warn/queue banner when an iteration is mid-flight", () => {
    render(<ConcurrencyWarning status={CONCURRENCY_MIDFLIGHT} />);
    const banner = screen.getByTestId("concurrency-warning");
    expect(banner).toBeInTheDocument();
    // Names the contending run and stays a warn, not a hard block.
    expect(banner).toHaveTextContent("loop_v0");
    expect(banner).toHaveTextContent(CONCURRENCY_MIDFLIGHT.label!);
    expect(banner).toHaveTextContent(/warn\/queue, not a block/i);
  });

  it("renders NOTHING when idle", () => {
    const { container } = render(<ConcurrencyWarning status={CONCURRENCY_IDLE} />);
    expect(screen.queryByTestId("concurrency-warning")).toBeNull();
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing while the injected status is unresolved (no fabricated warning)", () => {
    // No status prop and no fetch stub => self-fetch is pending; until it
    // resolves the guard shows nothing rather than fabricating a warning.
    // Provide a fetch that never resolves to keep it unresolved.
    vi.stubGlobal("fetch", () => new Promise<Response>(() => {}));
    render(<ConcurrencyWarning />);
    expect(screen.queryByTestId("concurrency-warning")).toBeNull();
  });
});

// --- CalibrationCapture ---

describe("CalibrationCapture", () => {
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
        // The honest STUB preview — would-run argv, writes nothing.
        json: async () => ({
          stub: true,
          lights_up_when: "the calibration_entry primary seam lands",
          would_run: [
            ".venv-chroma/bin/python",
            "-m",
            "orchestrator.calibration_cli",
            "--finding-id",
            "sf-iter-x",
          ],
        }),
      } as unknown as Response;
    });
    return { calls };
  }

  it("captures FIRST then fires onCaptured (ordering contract), posting via the stub", async () => {
    const { calls } = stubCalibrationOk();
    const onCaptured = vi.fn();
    render(
      <CalibrationCapture refId="sf-iter-x" onCaptured={onCaptured} />,
    );

    // The stub banner is visible (seam not yet live).
    expect(screen.getByTestId("calibration-stub-banner")).toBeInTheDocument();

    // onCaptured has NOT fired before capture — the verdict must not open first.
    expect(onCaptured).not.toHaveBeenCalled();

    const button = screen.getByRole("button", {
      name: /record blind calibration/i,
    });
    // Required prediction gates the button.
    expect(button).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/calibration prediction/i), {
      target: { value: "survives 2/3" },
    });
    fireEvent.change(screen.getByLabelText(/calibration confidence/i), {
      target: { value: "0.7" },
    });
    expect(button).toBeEnabled();
    fireEvent.click(button);

    await waitFor(() => expect(onCaptured).toHaveBeenCalledTimes(1));
    // The captured draft is handed to the shell.
    expect(onCaptured).toHaveBeenCalledWith({
      prediction: "survives 2/3",
      confidence: 0.7,
    });
    // It posted to the STUB calibration endpoint with the FLAT draft body.
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({
      ref_id: "sf-iter-x",
      prediction: "survives 2/3",
      confidence: 0.7,
    });
    expect(screen.getByTestId("calibration-captured")).toBeInTheDocument();
  });
});

// --- TutorPanel ---

describe("TutorPanel", () => {
  it("renders the overview but exposes NO verdict affordance behind a visible fence", () => {
    // U1 (2026-06-17): the tutor is now a real finding OVERVIEW, not a stub.
    // Inject `detail` (the override) so we deterministically exercise the loaded
    // state — the fence must hold WITH real content present (D-054), and the word
    // "verdict" must appear ONLY in the fence note (critic_verdict is labelled
    // "critic"; the mechanical outcome line avoids the word).
    render(
      <TutorPanel
        findingId="sf-iter-x"
        detail={{
          found: true,
          finding_id: "sf-iter-x",
          title: "novel_on_02 over-gated",
          claim: "the primary R0 gate over-gates novel_on_02",
          what_would_change_it: "a re-run that clears the gate",
          source_iteration_id: "iter-2026-05-27-006",
          critic_verdict: "survives",
        }}
      />,
    );
    // The real overview renders (no longer a stub).
    expect(screen.getByTestId("tutor-overview")).toBeInTheDocument();
    // The fence is visible to the human, even alongside real content.
    expect(screen.getByTestId("tutor-fence-note")).toHaveTextContent(
      /does not affect your verdict/i,
    );
    // S2 TRIM: the unweighted pros/cons considerations section is GONE — the
    // tutor teaches via claim/provenance/evidence + the neutral outcome line.
    expect(screen.queryByTestId("tutor-considerations")).toBeNull();
    // No verdict-shaped control: no valid/invalid/needs_revision buttons, no
    // verdict-labelled inputs leak in through this teaching surface.
    expect(screen.queryByRole("button", { name: /valid/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /invalid/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /needs_revision/i })).toBeNull();
    // The word "verdict" appears ONLY in the fence note (single-match holds).
    expect(screen.queryByText(/verdict/i)).toHaveTextContent(
      /does not affect your verdict/i,
    );
  });
});

// (TwoVoiceChatPane coverage moved to tests/test_ChatPane.tsx — the pane
// merged into the mode-parameterized ChatPane in UI simplification S2.)
