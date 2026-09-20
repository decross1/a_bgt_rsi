import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const D = vi.hoisted(() => ({
  summary: {} as unknown,
  messages: {} as unknown,
  messageError: null as unknown,
  post: vi.fn(),
}));

vi.mock("../src/api/dailyOps", async importOriginal => ({
  ...await importOriginal<typeof import("../src/api/dailyOps")>(),
  getDailyOpsSummary: vi.fn(),
  getDailyOpsMessages: vi.fn(),
  postDailyOpsMessage: D.post,
}));

vi.mock("../src/api/pollhub", () => ({
  usePolled: (key: string) => ({
    data: key === "daily_ops_summary" ? D.summary : D.messages,
    error: key === "daily_ops_summary" ? null : D.messageError,
    failing: false,
    asOf: Date.now(),
  }),
  refreshPoll: vi.fn(),
}));

import DailyOpsPanel, { makeRequestId } from "../src/components/DailyOpsPanel";

const now = "2026-09-20T08:00:00Z";

function summary(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: "daily-ops-summary/v1",
    available: true,
    generated_at: now,
    source_sha256: "a".repeat(64),
    current_plan_revision: "plan-revision-20260920-0800",
    goals: [{ id: "goal-1", title: "Close the instrument gap", detail: "Freeze the corrected contract.", source: "focus", observed_at: now, status: "in_progress", owner: "oracle" }],
    accomplishments: [{ id: "done-1", title: "Rebuilt Oracle recall", detail: "Targeted retrieval works again.", source: "receipt", observed_at: now, status: "complete" }],
    improvements: [{ id: "improvement-1", title: "Bounded daily brief", detail: "Reduced startup context.", source: "receipt", observed_at: now, status: "verified" }],
    research_focus: {
      focus_id: "focus-1", title: "Does payoff assistance improve strategic planning?",
      status: "blocked", stage: "instrument calibration", next_action: "Review the corrected tool contract.",
      next_gate: { from: "calibration", to: "registered study", artifact: "Frozen preregistration and verifier", status: "blocked", owner: "Oracle + Codex" },
      blockers: ["Tool contract needs a fresh calibration"], source_receipt_sha256: "b".repeat(64), observed_at: now,
    },
    agents: {
      oracle: { label: "Oracle", status: "working", detail: "Reviewing the next gate.", observed_at: now, source: "mailbox" },
      pi_client: { label: "Pi", status: "online", detail: "Oracle client reloaded.", observed_at: now, source: "session" },
      nara: { label: "Nara", status: "idle", detail: "Awaiting registered work.", observed_at: now, source: "service" },
    },
    warnings: [],
    capabilities: { auth_required: true, write_available: true, targets: ["oracle"], intents: ["question", "change_request"], nara_interaction: "ask_oracle_about_nara" },
    ...overrides,
  };
}

function messages(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: "daily-ops-messages/v1",
    available: true,
    writable: true,
    rows: [{ request_id: "request-1", created_at: now, actor: "owner", intent: "question", status: "queued", text: "What is blocking the study?", target: "oracle", plan_revision: null }],
    ...overrides,
  };
}

function show() {
  return render(<MemoryRouter><DailyOpsPanel legacyResearchOps={null} /></MemoryRouter>);
}

beforeEach(() => {
  sessionStorage.clear();
  D.summary = summary();
  D.messages = messages();
  D.messageError = null;
  D.post.mockReset().mockResolvedValue({ request_id: "request-2", status: "queued", accepted_at: now, duplicate: false, expected_plan_revision: "plan-revision-20260920-0800" });
  vi.stubGlobal("crypto", { randomUUID: () => "11111111-1111-4111-8111-111111111111" });
});

describe("DailyOpsPanel", () => {
  it("summarizes the day and shows the main thesis exactly once", () => {
    show();
    expect(screen.getByText("Goals for today")).toBeInTheDocument();
    expect(screen.getByText("Recently accomplished")).toBeInTheDocument();
    expect(screen.getByText("System improvements")).toBeInTheDocument();
    expect(screen.getAllByText("Does payoff assistance improve strategic planning?")).toHaveLength(1);
    expect(screen.getByText("Oracle client")).toBeInTheDocument();
    expect(screen.getByText("Observed runner")).toBeInTheDocument();
    expect(screen.getByText(/queued request is not approval/i)).toBeInTheDocument();
  });

  it("keeps daily goals beyond the first four available inline", () => {
    D.summary = summary({
      goals: Array.from({ length: 6 }, (_, index) => ({
        id: `goal-${index + 1}`,
        title: `Daily goal ${index + 1}`,
        detail: `Source-bound detail ${index + 1}.`,
        source: "verified planner projection",
        observed_at: now,
        status: index > 2 ? "awaiting_owner" : "in_progress",
        owner: "oracle",
      })),
    });
    show();

    expect(screen.getByText("Daily goal 4")).toBeInTheDocument();
    const more = screen.getByText("Show 2 more recorded items");
    expect(more.closest("details")).not.toHaveAttribute("open");
    fireEvent.click(more);
    expect(more.closest("details")).toHaveAttribute("open");
    expect(screen.getByText("Daily goal 5")).toBeInTheDocument();
    expect(screen.getByText("Daily goal 6")).toBeInTheDocument();
  });

  it("retains a valid backend-boundary agenda goal behind a compact detail disclosure", () => {
    const boundaryTitle = "T".repeat(512);
    const boundaryDetail = "D".repeat(4096);
    D.summary = summary({
      goals: [{
        id: `g${"a".repeat(199)}`,
        title: boundaryTitle,
        detail: boundaryDetail,
        source: "sealed pending agenda",
        observed_at: now,
        status: "awaiting_owner",
        owner: "oracle",
      }],
    });
    show();

    expect(screen.getByText(boundaryTitle)).toBeInTheDocument();
    const disclosure = screen.getByText("Full recorded detail").closest("details");
    expect(disclosure).not.toHaveAttribute("open");
    expect(screen.getByText(boundaryDetail)).toBeInTheDocument();
  });

  it("queues a revision-bound plan change without claiming delivery", async () => {
    show();
    fireEvent.change(screen.getByLabelText(/Owner access key/), { target: { value: "owner-secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Unlock for this tab" }));
    fireEvent.click(await screen.findByRole("button", { name: "Request a plan change" }));
    fireEvent.change(screen.getByLabelText("Message to Oracle"), { target: { value: "Move the verifier review ahead of new topic intake." } });
    fireEvent.click(screen.getByRole("button", { name: "Queue for Oracle" }));
    await waitFor(() => expect(D.post).toHaveBeenCalledWith({
      accessKey: "owner-secret",
      requestId: "11111111-1111-4111-8111-111111111111",
      intent: "change_request",
      text: "Move the verifier review ahead of new topic intake.",
      expectedPlanRevision: "plan-revision-20260920-0800",
    }));
    expect(await screen.findByText(/Request queued/)).toHaveTextContent("No acknowledgment or execution is implied");
    expect(screen.queryByText(/delivered/i)).toBeNull();
  });

  it("builds an RFC 4122 v4 request id when randomUUID is unavailable", () => {
    vi.stubGlobal("crypto", {
      getRandomValues: (target: Uint8Array) => {
        target.set(Array.from({ length: 16 }, (_, index) => index));
        return target;
      },
    });

    expect(makeRequestId()).toBe("00010203-0405-4607-8809-0a0b0c0d0e0f");
  });

  it("retries an unconfirmed delivery with the same request id", async () => {
    let uuidCall = 0;
    vi.stubGlobal("crypto", {
      randomUUID: () => uuidCall++ === 0
        ? "11111111-1111-4111-8111-111111111111"
        : "22222222-2222-4222-8222-222222222222",
    });
    D.post
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce({ request_id: "11111111-1111-4111-8111-111111111111", status: "queued", accepted_at: now, duplicate: true, expected_plan_revision: null });
    show();
    fireEvent.change(screen.getByLabelText(/Owner access key/), { target: { value: "owner-secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Unlock for this tab" }));
    fireEvent.change(screen.getByLabelText("Message to Oracle"), { target: { value: "What is the next gate?" } });
    fireEvent.click(screen.getByRole("button", { name: "Queue for Oracle" }));
    expect(await screen.findByText(/Delivery unconfirmed; retry safely with the same request ID/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Queue for Oracle" }));
    await waitFor(() => expect(D.post).toHaveBeenCalledTimes(2));
    expect(D.post.mock.calls[0][0].requestId).toBe("11111111-1111-4111-8111-111111111111");
    expect(D.post.mock.calls[1][0].requestId).toBe("11111111-1111-4111-8111-111111111111");
    expect(await screen.findByText(/Existing request found/)).toBeInTheDocument();
  });

  it("uses a new request id when the payload changes after uncertain delivery", async () => {
    let uuidCall = 0;
    vi.stubGlobal("crypto", {
      randomUUID: () => uuidCall++ === 0
        ? "11111111-1111-4111-8111-111111111111"
        : "22222222-2222-4222-8222-222222222222",
    });
    D.post.mockRejectedValue(new TypeError("Failed to fetch"));
    show();
    fireEvent.change(screen.getByLabelText(/Owner access key/), { target: { value: "owner-secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Unlock for this tab" }));
    const textarea = screen.getByLabelText("Message to Oracle");
    fireEvent.change(textarea, { target: { value: "What is the next gate?" } });
    fireEvent.click(screen.getByRole("button", { name: "Queue for Oracle" }));
    await screen.findByText(/Delivery unconfirmed/i);

    fireEvent.change(textarea, { target: { value: "What is blocking the next gate?" } });
    fireEvent.click(screen.getByRole("button", { name: "Queue for Oracle" }));
    await waitFor(() => expect(D.post).toHaveBeenCalledTimes(2));
    expect(D.post.mock.calls[0][0].requestId).toBe("11111111-1111-4111-8111-111111111111");
    expect(D.post.mock.calls[1][0].requestId).toBe("22222222-2222-4222-8222-222222222222");
  });

  it("keeps earlier Oracle mailbox events inline and labels the event channel as separate", () => {
    sessionStorage.setItem("oracle-lab-owner-access-key", "owner-secret");
    D.messages = messages({
      rows: Array.from({ length: 7 }, (_, index) => ({
        request_id: `request-${index}`,
        created_at: `2026-09-20T08:0${index}:00Z`,
        actor: "owner",
        intent: "question",
        status: "queued",
        text: `Question ${index}`,
        target: "oracle",
        plan_revision: null,
      })),
    });
    show();

    expect(screen.getByText("Lab event channel (separate) →")).toBeInTheDocument();
    expect(screen.getByText("Show 2 earlier mailbox events (7 fetched)")).toBeInTheDocument();
    const setupSummary = screen.getByText("Where to get the local owner key");
    const setupDetail = setupSummary.closest("details");
    expect(setupDetail).not.toHaveAttribute("open");
    fireEvent.click(setupSummary);
    expect(setupDetail).toHaveAttribute("open");
    expect(screen.getByText("cat ~/.local/state/oracle-lab-ui/owner.key")).toBeInTheDocument();
  });

  it("keeps plan changes disabled when no revision can be bound", () => {
    D.summary = summary({ current_plan_revision: null });
    show();
    fireEvent.change(screen.getByLabelText(/Owner access key/), { target: { value: "owner-secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Unlock for this tab" }));
    fireEvent.click(screen.getByRole("button", { name: "Request a plan change" }));
    fireEvent.change(screen.getByLabelText("Message to Oracle"), { target: { value: "Change the agenda." } });
    expect(screen.getByRole("button", { name: "Queue for Oracle" })).toBeDisabled();
    expect(screen.getByText(/No current plan revision is available/)).toBeInTheDocument();
  });

  it("shows an honest read-only state when the router cannot write", () => {
    D.summary = summary({ capabilities: { auth_required: true, write_available: false, targets: ["oracle"], intents: ["question", "change_request"], nara_interaction: "ask_oracle_about_nara" } });
    D.messages = messages({ writable: false });
    show();
    expect(screen.getByTestId("daily-ops-readonly")).toHaveTextContent("authenticated Oracle router is not available");
    expect(screen.queryByTestId("daily-ops-composer")).toBeNull();
  });

  it("keeps history and a draft available but disables sending while Oracle is degraded", () => {
    const degraded = summary();
    degraded.agents.oracle.status = "degraded";
    degraded.agents.oracle.detail = "Mailbox review scope is not ready.";
    D.summary = degraded;
    sessionStorage.setItem("oracle-lab-owner-access-key", "owner-secret");
    show();

    expect(screen.getByText("What is blocking the study?")).toBeInTheDocument();
    const textarea = screen.getByLabelText("Message to Oracle");
    fireEvent.change(textarea, { target: { value: "Keep this question as a draft." } });
    expect(textarea).toHaveValue("Keep this question as a draft.");
    expect(screen.getByRole("button", { name: "Queue for Oracle" })).toBeDisabled();
    expect(screen.getByText(/Oracle is unavailable; your draft is kept here/i)).toBeInTheDocument();
    expect(D.post).not.toHaveBeenCalled();
  });

  it("clears a rejected owner key and keeps history locked", async () => {
    const { DailyOpsError } = await import("../src/api/dailyOps");
    sessionStorage.setItem("oracle-lab-owner-access-key", "bad-key");
    D.messageError = new DailyOpsError(403, "owner authentication required");
    show();
    expect(await screen.findByText(/Owner access key rejected/)).toBeInTheDocument();
    expect(sessionStorage.getItem("oracle-lab-owner-access-key")).toBeNull();
    expect(screen.getByTestId("daily-ops-locked")).toBeInTheDocument();
    expect(screen.queryByText("What is blocking the study?")).toBeNull();
  });

  it("preserves the legacy research view when the daily snapshot is malformed", () => {
    D.summary = { schema_version: "wrong" };
    show();
    expect(screen.getByTestId("daily-ops-fallback")).toHaveTextContent("Daily synthesis unavailable");
    expect(screen.getByTestId("research-ops-card")).toBeInTheDocument();
  });
});
