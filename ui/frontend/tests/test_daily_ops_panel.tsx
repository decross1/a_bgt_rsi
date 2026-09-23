import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const D = vi.hoisted(() => ({
  summary: {} as unknown,
  messages: {} as unknown,
  messageError: null as unknown,
  post: vi.fn(),
  postDecision: vi.fn(),
}));

vi.mock("../src/api/dailyOps", async importOriginal => ({
  ...await importOriginal<typeof import("../src/api/dailyOps")>(),
  getDailyOpsSummary: vi.fn(),
  getDailyOpsMessages: vi.fn(),
  postDailyOpsMessage: D.post,
  postDailyOpsDecision: D.postDecision,
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

import DailyOpsPanel, { makeRequestId, nowLine } from "../src/components/DailyOpsPanel";

const now = "2026-09-20T08:00:00Z";
const PLAN = "2026-09-20-r2";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Loose = Record<string, any>;

function item(id: string, lane: string, status: string, extra: Loose = {}): Loose {
  return {
    id, goal: "G7.1", owner: lane.startsWith("nara") ? "nara" : lane === "owner_decision" ? "owner" : "oracle",
    lane, repo: "a_bgt_rsi", title: `Item ${id} title`, summary: null, why_today: `Why ${id}.`, acceptance: `Accept ${id}.`,
    depends_on: [], status, detail: `Detail for ${id}.`, evidence_msg_id: null, evidence_sha: null,
    evidence_at: null, ...extra,
  };
}

function summary(overrides: Loose = {}): Loose {
  return {
    schema_version: "daily-ops-summary/v3",
    available: true,
    generated_at: now,
    source_sha256: "a".repeat(64),
    current_plan_revision: PLAN,
    daily_plan: {
      id: PLAN, date: "2026-09-20", revision: "r2", path: `run_state/daily_plans/${PLAN}.json`,
      sha256: "b".repeat(64), written_at: now, is_current: true,
      week_alignment: "Finishes G0 before starting G1.",
      bottlenecks: ["Nothing can select the next research focus.", "The lane has nothing admissible."],
      review: { note_msg_id: "oracle-f04a55e3a7ddc8b3", sha_matches: true, verdict: "amend",
        review_msg_id: "claude-bfc06cece11638c0", reviewed_at: now, summary: "Accept d2, d4 and d5.",
        accepted_items: ["d2", "d4", "d5"] },
    },
    research_focus: {
      status: "none", observed_at: now,
      last_closure: { focus_id: "payoff-assistance", title: "Does payoff assistance improve strategic planning?",
        disposition: "killed", closed_at: "2026-09-19T23:39:12Z",
        reason: "Development closed for opportunity cost, not refuted.", closure_sha256: "c".repeat(64) },
    },
    work_items: [
      item("d1", "oracle_dev", "merged", { detail: "Merge oracle/2026-09-20-d1 at 8c6c92a", evidence_sha: "2cbe6dbe8a39", evidence_at: now }),
      item("d2", "nara_dev", "held", { evidence_msg_id: "nara-f5ac608bc8da3020", depends_on: ["d1"] }),
      item("d3", "oracle_dev", "awaiting_review"),
      item("d4", "nara_dev", "not_started"),
      item("d5", "owner_decision", "waiting_on_you", { evidence_msg_id: "claude-81a020b8a67564fb" }),
    ],
    waiting_on_you: [
      { kind: "owner_decision", id: `${PLAN}:d5`, title: "Item d5 title", asked_by: "claude", asked_at: now,
        msg_id: "claude-81a020b8a67564fb",
        cli: ".venv-chroma/bin/python -m orchestrator.oracle_mailbox post --as human:derrick --kind answer --to claude --in-reply-to claude-81a020b8a67564fb --body '{\"text\": \"...\"}'" },
      { kind: "question", id: "claude-18ae939243e70e7d", title: "Two authority rulings", asked_by: "claude",
        asked_at: now, msg_id: "claude-18ae939243e70e7d", cli: "answer claude-18ae939243e70e7d" },
    ],
    accomplishments: [
      { id: "2026-09-20:d1", kind: "merged", title: "2026-09-20 d1 (G7.1): Lane precheck", at: now, evidence: "2cbe6dbe8a39" },
      { id: "closure:c", kind: "focus_closed", title: "Focus killed: payoff assistance", at: now, evidence: "cccccccccccc" },
    ],
    improvements: [
      { sha: "f5ee462351aa", at: now, subject: "Mark G0.2 done (focus-selection CLI)", goals: ["G0.2"] },
      { sha: "b8018dfaa6a1", at: now, subject: "Now page: agent cards", goals: [] },
    ],
    agents: {
      oracle: { label: "Oracle", status: "working", detail: "Live run.", observed_at: now, source: "proc",
        role: "Steward (daily loop)", activity: "daily-loop phase work for 2026-09-20", activity_at: now,
        since: "2026-09-20T07:30:00Z" },
      pi_client: { label: "Pi client", status: "online", detail: "Oracle client reloaded.", observed_at: now, source: "session" },
      nara: { label: "Nara", status: "idle", detail: "Awaiting registered work.", observed_at: now, source: "service" },
    },
    warnings: [],
    sources: { plan: now, mailbox: now, focus: "2026-09-19T23:39:12Z", git: now },
    capabilities: { auth_required: true, write_available: true, targets: ["oracle"], intents: ["question", "change_request"],
      nara_interaction: "ask_oracle_about_nara", decision_write_available: true,
      decision_actions: ["modify", "skip", "reprioritize"] },
    ...overrides,
  };
}

function messages(overrides: Loose = {}) {
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
  D.post.mockReset().mockResolvedValue({ request_id: "request-2", status: "queued", accepted_at: now, duplicate: false, expected_plan_revision: PLAN });
  D.postDecision.mockReset().mockResolvedValue({
    request_id: "11111111-1111-4111-8111-111111111111", status: "queued",
    accepted_at: now, duplicate: false, target_kind: "work_card", target_id: "d2",
    action: "modify", expected_plan_revision: PLAN, execution_available: false,
  });
  vi.stubGlobal("crypto", { randomUUID: () => "11111111-1111-4111-8111-111111111111" });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("DailyOpsPanel", () => {
  it("heads the panel with the plan of record, its bottlenecks and the meta-oracle verdict", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-20T09:00:00Z"));
    show();
    expect(screen.getByTestId("daily-plan-badge")).toHaveTextContent("Plan of record 2026-09-20 r2 · written Sep 20");
    const plan = screen.getByTestId("daily-plan");
    expect(plan).toHaveTextContent("Today's plan · 2026-09-20 r2");
    expect(plan).toHaveTextContent("Week alignment: Finishes G0 before starting G1.");
    expect(plan).toHaveTextContent("Nothing can select the next research focus.");
    expect(screen.getByTestId("daily-plan-review")).toHaveTextContent(
      "Meta-oracle review: amend · accepted d2, d4, d5 · claude-bfc06cece11638c0");
    expect(plan).toHaveTextContent("updated 60 min ago");
    expect(screen.queryByTestId("daily-plan-stale")).toBeNull();
    expect(screen.queryByText(/Daily notes last updated/)).toBeNull();
    expect(screen.queryByText(/could not be verified/)).toBeNull();
  });

  it("says when the newest plan is not today's and when its producer went quiet", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-22T09:00:00Z"));
    const base = summary();
    D.summary = summary({ daily_plan: { ...base.daily_plan, is_current: false, review: null } });
    show();
    expect(screen.getByTestId("daily-plan-stale")).toHaveTextContent(
      "The newest plan is for 2026-09-20; Oracle has not written a plan for today yet.");
    expect(screen.getByTestId("daily-plan-review")).toHaveTextContent("No PLAN READY note names this plan file");
    expect(screen.getByTestId("daily-plan")).toHaveTextContent("producer idle since Sep 20");
  });

  it("shows every plan item with its live status and evidence, with no card cap", () => {
    show();
    expect(screen.getByRole("heading", { name: "Today's work" })).toBeInTheDocument();
    expect(screen.getAllByTestId(/^daily-work-card-d\d$/)).toHaveLength(5);
    expect(screen.getByText("5 items")).toBeInTheDocument();
    expect(screen.queryByText(/cards shown/)).toBeNull();
    const d1 = screen.getByTestId("daily-work-card-d1");
    expect(d1).toHaveTextContent("G7.1 · Oracle");
    expect(d1).toHaveTextContent("Item d1 title");
    expect(d1).toHaveTextContent("merged");
    expect(d1).toHaveTextContent("sha 2cbe6dbe8a39");
    expect(screen.getByTestId("daily-work-card-d2")).toHaveTextContent("held");
    expect(screen.getByTestId("daily-work-card-d2")).toHaveTextContent("nara-f5ac608bc8da3020");
    expect(screen.getByTestId("daily-work-card-d3")).toHaveTextContent("awaiting review");
    expect(screen.getByTestId("daily-work-card-d4")).toHaveTextContent("not started");
    expect(screen.getByTestId("daily-work-card-d5")).toHaveTextContent("waiting on you");
    const why = within(screen.getByTestId("daily-work-card-d2")).getByText("Details");
    fireEvent.click(why);
    expect(screen.getByTestId("daily-work-card-d2")).toHaveTextContent("Accept d2.");
    expect(screen.getByTestId("daily-work-card-d2")).toHaveTextContent("Depends ond1");
  });

  it("lists what is waiting on the owner as plain questions with decision buttons, no commands", () => {
    show();
    const waiting = screen.getByTestId("daily-waiting-on-you");
    expect(within(waiting).getByRole("heading", { name: "Waiting on you" })).toBeInTheDocument();
    const planDecision = screen.getByTestId(`daily-waiting-${PLAN}:d5`);
    expect(planDecision).toHaveTextContent("plan decision");
    expect(planDecision).not.toHaveTextContent("--kind answer");
    expect(planDecision).not.toHaveTextContent(".venv-chroma/bin/python");
    expect(within(planDecision).getByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(within(planDecision).getByRole("button", { name: "Decline" })).toBeInTheDocument();
    expect(within(planDecision).getByRole("button", { name: "Defer" })).toBeInTheDocument();
    expect(within(planDecision).getByRole("button", { name: "Reply…" })).toBeInTheDocument();
    const question = screen.getByTestId("daily-waiting-claude-18ae939243e70e7d");
    expect(question).toHaveTextContent("Two authority rulings");
    expect(question).not.toHaveTextContent("answer claude-18ae939243e70e7d");
    expect(within(question).getByRole("button", { name: "Approve" })).toBeInTheDocument();
  });

  it("sends an owner decision on a waiting item and shows it was sent", async () => {
    sessionStorage.setItem("oracle-lab-owner-access-key", "owner-secret");
    show();
    const planDecision = screen.getByTestId(`daily-waiting-${PLAN}:d5`);
    fireEvent.click(within(planDecision).getByRole("button", { name: "Approve" }));
    const editor = screen.getByTestId("daily-decision-editor");
    fireEvent.click(within(editor).getByRole("button", { name: "Send approval" }));
    await waitFor(() => expect(D.postDecision).toHaveBeenCalledWith(expect.objectContaining({
      accessKey: "owner-secret", targetKind: "work_card", targetId: "d5", action: "approve",
      expectedPlanRevision: PLAN,
    })));
    expect(await within(editor).findByText(/Sent to Oracle|Request queued/)).toBeInTheDocument();
  });

  it("requires a note before it will send a reply to a question", async () => {
    sessionStorage.setItem("oracle-lab-owner-access-key", "owner-secret");
    show();
    const question = screen.getByTestId("daily-waiting-claude-18ae939243e70e7d");
    fireEvent.click(within(question).getByRole("button", { name: "Reply…" }));
    const editor = screen.getByTestId("daily-decision-editor");
    expect(within(editor).getByRole("button", { name: "Send reply" })).toBeDisabled();
    fireEvent.change(within(editor).getByLabelText("Your reply"), { target: { value: "Proceed carefully." } });
    fireEvent.click(within(editor).getByRole("button", { name: "Send reply" }));
    await waitFor(() => expect(D.postDecision).toHaveBeenCalledWith(expect.objectContaining({
      targetKind: "question", targetId: "claude-18ae939243e70e7d", action: "reply", note: "Proceed carefully.",
    })));
  });

  it("keeps decision buttons live when the old relay is offline, and explains only a missing sign-in", () => {
    const base = summary();
    const relay = { status: "offline", detail: "Mailbox is unavailable or stale.", observed_at: now, source: "Oracle oversight mailbox heartbeat" };
    D.summary = summary({ agents: { ...base.agents, oracle: { ...base.agents.oracle, relay },
      pi_client: { ...base.agents.pi_client, relay } } });
    show();
    // Decisions go to the lab mailbox, so a dead Pi relay does not disable them.
    expect(screen.queryByTestId("daily-decisions-readonly")).toBeNull();
    expect(within(screen.getByTestId("daily-work-card-d2")).getByRole("button", { name: "Ask to modify" })).toBeEnabled();
    expect(screen.getByTestId("daily-ops-relay")).toHaveTextContent("Owner relay: offline — Mailbox is unavailable or stale.");

    D.summary = summary({ capabilities: { ...base.capabilities, decision_write_available: false } });
    show();
    expect(screen.getByTestId("daily-decisions-readonly")).toHaveTextContent(
      "Sign-in for owner actions isn't set up on this machine.");
  });

  it("queues a per-item request bound to the plan of record", async () => {
    sessionStorage.setItem("oracle-lab-owner-access-key", "owner-secret");
    show();
    fireEvent.click(within(screen.getByTestId("daily-work-card-d2")).getByRole("button", { name: "Ask to modify" }));
    const editor = screen.getByTestId("daily-decision-editor");
    fireEvent.change(within(editor).getByLabelText("Required change"), { target: { value: "Wait for d1." } });
    fireEvent.click(within(editor).getByRole("button", { name: "Queue modification request" }));
    await waitFor(() => expect(D.postDecision).toHaveBeenCalledWith({
      accessKey: "owner-secret", requestId: "11111111-1111-4111-8111-111111111111",
      targetKind: "work_card", targetId: "d2", action: "modify", expectedPlanRevision: PLAN,
      note: "Wait for d1.",
    }));
    expect(await within(editor).findByText(/Sent to Oracle/)).toHaveTextContent("No execution is implied");
  });

  it("does not apply a late request result to a different card editor", async () => {
    sessionStorage.setItem("oracle-lab-owner-access-key", "owner-secret");
    let resolveRequest: ((value: Record<string, unknown>) => void) | undefined;
    D.postDecision.mockReturnValueOnce(new Promise(resolve => { resolveRequest = resolve; }));
    show();
    fireEvent.click(within(screen.getByTestId("daily-work-card-d2")).getByRole("button", { name: "Ask to modify" }));
    let editor = screen.getByTestId("daily-decision-editor");
    fireEvent.change(within(editor).getByLabelText("Required change"), { target: { value: "Change d2." } });
    fireEvent.click(within(editor).getByRole("button", { name: "Queue modification request" }));
    fireEvent.click(within(screen.getByTestId("daily-work-card-d4")).getByRole("button", { name: "Ask to skip" }));
    editor = screen.getByTestId("daily-decision-editor");
    await act(async () => {
      resolveRequest?.({ request_id: "11111111-1111-4111-8111-111111111111", status: "queued", accepted_at: now,
        duplicate: false, target_kind: "work_card", target_id: "d2", action: "modify",
        expected_plan_revision: PLAN, execution_available: false });
      await Promise.resolve();
    });
    expect(within(editor).queryByText(/Sent to Oracle/)).toBeNull();
    expect(within(editor).getByRole("button", { name: "Queue skip request" })).toBeEnabled();
  });

  it("shows no active focus with the last closure and the exploratory intake", () => {
    show();
    expect(screen.getByRole("heading", { name: "Research focus" })).toBeInTheDocument();
    expect(screen.getByTestId("daily-focus-none")).toHaveTextContent("No active focus");
    expect(screen.getByText("exploratory arXiv intake")).toBeInTheDocument();
    const closure = screen.getByTestId("daily-focus-closure");
    expect(closure).toHaveTextContent("killed · Does payoff assistance improve strategic planning?");
    expect(closure).toHaveTextContent("payoff-assistance · closed Sep 19");
    expect(closure).toHaveTextContent("Development closed for opportunity cost");
    expect(screen.queryByText(/could not be verified/)).toBeNull();
  });

  it("shows a selected focus and an invalid focus source honestly", () => {
    D.summary = summary({ research_focus: { status: "selected", observed_at: now, focus_id: "f1",
      title: "Does coordination scale?", stage: "needs_clean_refinement", next_action: "Refine the hypothesis.",
      intake_policy: "focus_before_new_topics", selected_at: now } });
    const { unmount } = show();
    expect(screen.getByText("Does coordination scale?")).toBeInTheDocument();
    expect(screen.getByText("Refine the hypothesis.")).toBeInTheDocument();
    expect(screen.getByText("focus before new topics")).toBeInTheDocument();
    unmount();
    D.summary = summary({ research_focus: { status: "source_invalid", observed_at: now, reason: "FocusError" } });
    show();
    expect(screen.getByTestId("daily-focus-invalid")).toHaveTextContent("The research focus source is invalid: FocusError");
  });

  it("lists live accomplishments and main merges with goal ids highlighted", () => {
    show();
    expect(screen.getByRole("heading", { name: "Accomplished · last 7 days" })).toBeInTheDocument();
    expect(screen.getByText("2026-09-20 d1 (G7.1): Lane precheck")).toBeInTheDocument();
    expect(screen.getByText("Evidence: 2cbe6dbe8a39")).toBeInTheDocument();
    expect(screen.getByText("focus closed")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "System improvements · merged to main, last 7 days" })).toBeInTheDocument();
    expect(screen.getByText("Mark G0.2 done (focus-selection CLI)")).toBeInTheDocument();
    expect(screen.getByText("G0.2", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByText("main f5ee462351aa")).toBeInTheDocument();
    expect(screen.queryByText(/recorded Sep/)).toBeNull();
  });

  it("keeps more than four improvements behind the existing disclosure", () => {
    D.summary = summary({ improvements: Array.from({ length: 6 }, (_, index) => ({
      sha: `abcdef${index}`, at: now, subject: `Merged change ${index + 1}`, goals: [] })) });
    show();
    expect(screen.getByText("Merged change 4")).toBeInTheDocument();
    const more = screen.getByText("Show 2 more recorded items");
    fireEvent.click(more);
    expect(screen.getByText("Merged change 6")).toBeInTheDocument();
  });

  it("shows slim agent cards: status, one Now line and times, no plan list or prose", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-20T08:00:30Z"));
    const relay = { status: "offline", detail: "Mailbox is unavailable or stale.", observed_at: now, source: "Oracle oversight mailbox heartbeat" };
    D.summary = summary({
      agents: {
        oracle: { label: "Oracle", role: "Steward (daily loop)", status: "working", detail: "Live run observed in /proc.",
          observed_at: now, source: "/proc oracle-daily", activity: "daily-loop phase work for 2026-09-20",
          activity_at: "2026-09-20T07:30:00Z", since: "2026-09-20T07:30:00Z", relay },
        pi_client: { label: "Pi client", role: "Owner's interactive Oracle client", status: "idle",
          detail: "1 interactive Pi process(es).", observed_at: now, source: "/proc interactive pi",
          activity: null, activity_at: null, since: "2026-09-20T06:00:00Z", relay },
        nara: { label: "Nara research runner", role: "Research runner", status: "working",
          detail: "Nara service is active.", observed_at: now, source: "nara-daemon.service",
          activity: "lane: building Lab state packet", activity_at: "2026-09-20T07:58:00Z", since: "2026-09-20T07:58:00Z" },
        meta_oracle: { label: "Meta-oracle (Claude)", role: "Reviewer", status: "idle", detail: "No live run.",
          observed_at: now, source: "/proc meta_oracle_run.sh", activity: "last meta-oracle mode code for 2026-09-20 ended completed",
          activity_at: "2026-09-20T07:41:00Z", since: "2026-09-20T07:41:00Z" },
      },
    });
    sessionStorage.setItem("oracle-lab-owner-access-key", "owner-secret");
    show();
    fireEvent.change(screen.getByLabelText("Message to Oracle"), { target: { value: "Status?" } });

    expect(screen.getByTestId("daily-ops-agent-oracle-now")).toHaveTextContent("Now: daily-loop phase work for 2026-09-20");
    expect(screen.getByTestId("daily-ops-agent-pi-now")).toHaveTextContent("Now: idle since Sep 20, 06:00 AM UTC (2 h ago)");
    expect(screen.getByTestId("daily-ops-agent-nara-now")).toHaveTextContent("Now: lane");
    expect(screen.getByTestId("daily-ops-agent-meta-now")).toHaveTextContent(
      "Now: idle since Sep 20, 07:41 AM UTC (19 min ago) · last meta-oracle mode code for 2026-09-20 ended completed");
    const oracle = screen.getByTestId("daily-ops-agent-oracle");
    expect(oracle).toHaveTextContent("Observed just now");
    expect(oracle).not.toHaveTextContent("Live run observed");
    expect(oracle).not.toHaveTextContent("Today's plan");
    expect(oracle).not.toHaveTextContent("Owner message relay");
    // The activity card is working, but owner messaging follows the offline relay.
    expect(screen.getByRole("button", { name: "Queue for Oracle" })).toBeDisabled();
  });

  it("builds the Now line from facts, not prose", () => {
    expect(nowLine({ status: "offline", activity: null, since: null })).toBe("offline");
    expect(nowLine({ status: "active", activity: null, since: null })).toBe("active");
  });

  it("refuses a retired v2 hand-curated brief and falls back to the research view", () => {
    D.summary = { ...summary(), schema_version: "daily-ops-summary/v2" };
    show();
    expect(screen.getByTestId("daily-ops-fallback")).toHaveTextContent("Daily synthesis unavailable");
  });

  it("identifies the temporary bounded responder without implying full Oracle authority", () => {
    D.summary = summary({
      agents: {
        oracle: {
          label: "Oracle bounded UI responder", status: "idle",
          detail: "Temporary summary-only responder; canonical interactive Oracle remains paused. It can read only the bounded daily summary and write its private response draft; it cannot approve or execute work. Configured availability ends Sep 20, 04:02 PM UTC.",
          observed_at: now, source: "Oracle bounded UI responder mailbox heartbeat",
        },
        pi_client: {
          label: "Headless Pi client", status: "idle", detail: "Bounded responder client.",
          observed_at: now, source: "Oracle bounded UI responder mailbox heartbeat",
        },
        nara: { label: "Nara", status: "idle", detail: "Awaiting registered work.", observed_at: now, source: "service" },
      },
    });
    sessionStorage.setItem("oracle-lab-owner-access-key", "owner-secret");
    show();

    expect(screen.getByTestId("daily-ops-bounded-responder")).toHaveTextContent(
      "canonical interactive Oracle remains paused",
    );
    expect(screen.getByTestId("daily-ops-bounded-responder")).toHaveTextContent(
      "cannot approve or execute work",
    );
    expect(screen.getByRole("heading", { name: "Ask Oracle bounded UI responder or request an agenda change" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Message to Oracle bounded UI responder"), {
      target: { value: "What is the next gate?" },
    });
    expect(screen.getByRole("button", { name: "Queue for Oracle bounded UI responder" })).toBeEnabled();
    expect(screen.queryByText("Oracle is the owner-facing steward. Pi is its client; Nara is observed through Oracle.")).toBeNull();
  });

  it("keeps a bounded responder reply attributed after the live route returns to Oracle", () => {
    sessionStorage.setItem("oracle-lab-owner-access-key", "owner-secret");
    D.messages = messages({
      rows: [
        {
          request_id: "11111111-1111-4111-8111-111111111111", created_at: now,
          actor: "owner", intent: "question", status: "queued",
          text: "What is the next gate?", target: "oracle", plan_revision: null,
          responder_label: "Oracle bounded UI responder",
        },
        {
          request_id: "22222222-2222-4222-8222-222222222222",
          created_at: "2026-09-20T08:01:00Z", actor: "oracle", intent: "reply",
          status: "acknowledged", text: "Run the bounded replay.", target: "oracle",
          plan_revision: null, in_reply_to: "11111111-1111-4111-8111-111111111111",
          responder_label: "Oracle bounded UI responder",
        },
      ],
    });
    show();

    expect(screen.getByRole("heading", { name: "Ask Oracle or request an agenda change" })).toBeInTheDocument();
    expect(screen.getByText("to Oracle bounded UI responder")).toBeInTheDocument();
    expect(screen.getByText("Oracle bounded UI responder", { selector: "span.font-semibold" })).toBeInTheDocument();
    expect(screen.getByText("Run the bounded replay.")).toBeInTheDocument();
    expect(screen.queryByTestId("daily-ops-bounded-responder")).toBeNull();
  });

  it("keeps the bounded composer closed while its single turn is working", () => {
    const bounded = summary();
    bounded.agents.oracle = {
      label: "Oracle bounded UI responder", status: "working",
      detail: "Temporary summary-only responder; a bounded owner turn is in progress.",
      observed_at: now, source: "Oracle bounded UI responder mailbox heartbeat",
    };
    bounded.agents.pi_client = {
      label: "Headless Pi client", status: "working", detail: "One turn is active.",
      observed_at: now, source: "Oracle bounded UI responder mailbox heartbeat",
    };
    D.summary = bounded;
    sessionStorage.setItem("oracle-lab-owner-access-key", "owner-secret");
    show();

    fireEvent.change(screen.getByLabelText("Message to Oracle bounded UI responder"), {
      target: { value: "Queue another question." },
    });
    expect(screen.getByRole("button", { name: "Queue for Oracle bounded UI responder" })).toBeDisabled();
    expect(screen.getByText(/Oracle bounded UI responder is unavailable; your draft is kept here/i)).toBeInTheDocument();
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
      expectedPlanRevision: PLAN,
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
    expect(screen.getByText(/owner.key under this machine/)).toBeInTheDocument();
    expect(screen.queryByText(/^cat /)).toBeNull();
  });

  it("keeps plan changes disabled when no revision can be bound", () => {
    D.summary = summary({ current_plan_revision: null, daily_plan: null });
    show();
    fireEvent.change(screen.getByLabelText(/Owner access key/), { target: { value: "owner-secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Unlock for this tab" }));
    fireEvent.click(screen.getByRole("button", { name: "Request a plan change" }));
    fireEvent.change(screen.getByLabelText("Message to Oracle"), { target: { value: "Change the agenda." } });
    expect(screen.getByRole("button", { name: "Queue for Oracle" })).toBeDisabled();
    expect(screen.getByText(/No plan of record is available/)).toBeInTheDocument();
  });

  it("shows an honest read-only state when the router cannot write", () => {
    D.summary = summary({ capabilities: { auth_required: true, write_available: false, targets: ["oracle"], intents: ["question", "change_request"], nara_interaction: "ask_oracle_about_nara", decision_write_available: false, decision_actions: [] } });
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

  it("marks an agent card stale when its observation stopped refreshing", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-20T08:30:00Z"));
    show();
    expect(screen.getByTestId("daily-ops-agent-nara")).toHaveTextContent("Stale: observed 30 min ago");
    expect(screen.queryByTestId("daily-ops-agent-meta")).toBeNull();
  });

  it("preserves the legacy research view when the daily snapshot is malformed", () => {
    D.summary = { schema_version: "wrong" };
    show();
    expect(screen.getByTestId("daily-ops-fallback")).toHaveTextContent("Daily synthesis unavailable");
    expect(screen.getByTestId("research-ops-card")).toBeInTheDocument();
  });
});
