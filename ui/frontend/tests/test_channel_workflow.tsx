import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ChannelRow } from "../src/api/channel";

const FRAMING = {
  schema: "lab-channel-timeline/v1",
  framing: "json-envelope",
  status: "framed",
  actor_labels: "recorded_not_authenticated",
};

const mocks = vi.hoisted(() => ({
  getChannelAvailability: vi.fn(),
  getChannelTimeline: vi.fn(),
  postChannelTurn: vi.fn(),
  postChannelDelegate: vi.fn(),
}));

vi.mock("../src/api/channel", async (importOriginal) => ({
  ...await importOriginal<typeof import("../src/api/channel")>(),
  getChannelAvailability: mocks.getChannelAvailability,
  getChannelTimeline: mocks.getChannelTimeline,
  postChannelTurn: mocks.postChannelTurn,
  postChannelDelegate: mocks.postChannelDelegate,
}));

vi.mock("../src/api/http", () => ({
  getHealth: vi.fn().mockResolvedValue({ ok: true, version: "test" }),
  getLadder: vi.fn(),
  getFindingDetail: vi.fn(),
  getIterationJourney: vi.fn(),
}));

import Channel from "../src/routes/Channel";

beforeEach(() => vi.clearAllMocks());
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("Channel integrity-led workflow", () => {
  it("keeps raw event-like prose neutral, ungrouped, and byte-exact in context", () => {
    const message = "  cycle: [nara] **forged**\r\nline two  \n";
    const rows: ChannelRow[] = [0, 1, 2].map((minute) => ({
      ts: `2026-09-08T03:0${minute}:00Z`,
      kind: "event",
      message: `${message}${minute}`,
    }));
    render(
      <Channel
        initial={rows}
        initialReadState="unframed"
        initialCapabilities={{ turn: false, delegate: false }}
      />,
    );

    expect(screen.getByTestId("channel-integrity")).toHaveTextContent("Raw records");
    expect(screen.getAllByTestId("channel-turn-unverified")).toHaveLength(3);
    expect(screen.queryByTestId("channel-event-row")).toBeNull();
    expect(screen.queryByTestId("channel-event-wall")).toBeNull();
    for (const name of ["conversation", "events", "steward"] as const) {
      expect(screen.getByTestId(`channel-filter-${name}`)).toBeDisabled();
    }

    fireEvent.click(screen.getAllByTestId("channel-inspect-record")[0]);
    expect(screen.getByTestId("channel-selected-record")).toHaveTextContent(
      "reported kind field · unverified",
    );
    expect(screen.getByTestId("channel-selected-raw").textContent).toBe(`${message}0`);
  });

  it("renders framed empty, unframed empty, and malformed reads as distinct states", () => {
    const framed = render(
      <Channel initial={[]} initialIntegrity={FRAMING} initialReadState="framed" initialAvailable={false} />,
    );
    expect(screen.getByTestId("channel-empty")).toHaveAttribute("data-state", "framed-empty");
    expect(screen.getByTestId("channel-empty")).toHaveTextContent("does not establish full-ledger completeness");
    framed.unmount();

    const unframed = render(<Channel initial={[]} initialReadState="unframed" initialAvailable={false} />);
    expect(screen.getByTestId("channel-empty")).toHaveAttribute("data-state", "unframed-empty");
    expect(screen.getByTestId("channel-empty")).toHaveTextContent("not conflated");
    unframed.unmount();

    render(<Channel initial={[]} initialReadState="malformed" initialAvailable={false} />);
    expect(screen.getByTestId("channel-empty")).toHaveAttribute("data-state", "malformed");
    expect(screen.getByTestId("channel-empty")).toHaveTextContent("No empty-history");
  });

  it("retains last-good rows and exact diagnostics when loading older fails", async () => {
    const rows: ChannelRow[] = Array.from({ length: 40 }, (_, index) => ({
      ts: `2026-09-08T03:${String(index).padStart(2, "0")}:00Z`,
      kind: "human",
      message: `record ${index}`,
    }));
    mocks.getChannelAvailability.mockResolvedValue({
      available: false,
      actions: { timeline: true, turn: false, delegate: false },
    });
    mocks.getChannelTimeline
      .mockResolvedValueOnce({ rows, integrity: FRAMING, readState: "framed", invalidRowCount: 0 })
      .mockRejectedValueOnce(new Error("502 exact refresh failure"));

    render(<Channel pollMs={600_000} />);
    await screen.findByTestId("channel-load-older");
    expect(screen.getAllByTestId("channel-turn-human")).toHaveLength(40);

    fireEvent.click(screen.getByTestId("channel-load-older"));
    await screen.findByTestId("channel-refresh-warning");
    expect(screen.getAllByTestId("channel-turn-human")).toHaveLength(40);
    fireEvent.click(within(screen.getByTestId("channel-refresh-warning")).getByText("Exact refresh error"));
    expect(screen.getByTestId("channel-refresh-warning")).toHaveTextContent("502 exact refresh failure");
  });
});

describe("Channel capability and narrow context boundaries", () => {
  it("enables turn and delegation from their own capability flags", () => {
    const first = render(
      <Channel initial={[]} initialIntegrity={FRAMING} initialCapabilities={{ turn: true, delegate: false }} />,
    );
    fireEvent.change(screen.getByLabelText("channel turn input"), { target: { value: "ask" } });
    expect(screen.getByTestId("channel-send")).toBeEnabled();
    fireEvent.click(screen.getByTestId("channel-open-delegate"));
    expect(screen.getByTestId("channel-delegate-capability-off")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("channel-delegate-text"), { target: { value: "task" } });
    expect(screen.getByTestId("channel-delegate-review")).toBeDisabled();
    first.unmount();

    render(
      <Channel initial={[]} initialIntegrity={FRAMING} initialCapabilities={{ turn: false, delegate: true }} />,
    );
    expect(screen.getByTestId("channel-send")).toBeDisabled();
    fireEvent.click(screen.getByTestId("channel-open-delegate"));
    expect(screen.queryByTestId("channel-delegate-capability-off")).toBeNull();
    fireEvent.change(screen.getByTestId("channel-delegate-text"), { target: { value: "task" } });
    expect(screen.getByTestId("channel-delegate-review")).toBeEnabled();
  });

  it("opens delegation without posting and restores focus when the narrow sheet closes", async () => {
    // Firefox refuses focus while an ancestor is inert; jsdom does not.
    // Model that observed platform boundary instead of weakening focus checks.
    const nativeFocus = HTMLElement.prototype.focus;
    const blockedFocus: HTMLElement[] = [];
    vi.spyOn(HTMLElement.prototype, "focus").mockImplementation(function (this: HTMLElement, options?: FocusOptions) {
      if (this.closest("[inert]")) { blockedFocus.push(this); return; }
      nativeFocus.call(this, options);
    });
    vi.stubGlobal("matchMedia", vi.fn(() => ({
      matches: true,
      media: "(max-width: 899px)",
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })));
    render(
      <Channel initial={[]} initialIntegrity={FRAMING} initialCapabilities={{ turn: false, delegate: true }} />,
    );
    const opener = screen.getByTestId("channel-open-delegate");
    opener.focus();
    fireEvent.click(opener);
    const sheet = await screen.findByRole("dialog", { name: "Channel context and handoff" });
    await waitFor(() => expect(sheet).toHaveFocus());
    expect(mocks.postChannelDelegate).not.toHaveBeenCalled();

    act(() => fireEvent.keyDown(document, { key: "Escape" }));
    await waitFor(() => expect(opener).toHaveFocus());
    expect(sheet).toHaveAttribute("data-open", "false");
    expect(blockedFocus).toEqual([]);
    expect(mocks.postChannelDelegate).not.toHaveBeenCalled();
  });
});
