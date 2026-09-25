import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const D = vi.hoisted(() => ({
  summary: {} as unknown,
  v3: undefined as unknown,
  messages: {} as unknown,
  messageError: null as unknown,
  post: vi.fn(),
  postDecision: vi.fn(),
}));

vi.mock("../src/api/dailyOps", async importOriginal => ({
  ...await importOriginal<typeof import("../src/api/dailyOps")>(),
  getDailyOpsSummary: vi.fn(),
  getDailyOpsV3Summary: vi.fn(),
  getDailyOpsMessages: vi.fn(),
  postDailyOpsMessage: D.post,
  postDailyOpsDecision: D.postDecision,
}));

vi.mock("../src/api/pollhub", () => ({
  usePolled: (key: string) => ({
    data: key === "daily_ops_summary" ? D.summary : key === "daily_ops_v3_summary" ? D.v3 : D.messages,
    error: key === "daily_ops_summary" ? null : D.messageError,
    failing: false,
    asOf: Date.now(),
  }),
  refreshPoll: vi.fn(),
}));

import DailyOpsPanel, { makeRequestId } from "../src/components/DailyOpsPanel";
import { admitDailyOpsV3Summary } from "../src/components/DailyOpsV3Panel";

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

function v2Summary(overrides: Record<string, unknown> = {}) {
  const revision = "1044a9c5ff6b617a7f7fce104019202fd77d38bdb2294ff8749100ed331e9621";
  return summary({
    schema_version: "daily-ops-summary/v2",
    current_plan_revision: revision,
    warnings: [],
    capabilities: {
      auth_required: true, write_available: true, targets: ["oracle"],
      intents: ["question", "change_request"], nara_interaction: "ask_oracle_about_nara",
      decision_write_available: true, decision_actions: ["modify", "skip", "reprioritize"],
    },
    work_cards: [
      {
        id: "build-v2-runner", title: "Finish the experiment runner", what: "Build the runner and evidence records for the current thesis.",
        benefit: "Lets us run a controlled test and inspect exactly what happened.",
        cost: { summary: "4–8 engineering hours; no local study runs.", kind: "estimate", basis: "Codex planning estimate from the accepted v2 development sequence; not measured effort." },
        conviction: { score: 9, kind: "estimate", basis: "Reviewer judgment that this work is worth doing; not a probability of a positive research result." },
        worth_time: { recommendation: "do_now", basis: "The offline core is complete; this is the next missing integration." },
        status: "authorized", owner: "codex", depends_on: [], source: "curated daily brief", observed_at: now,
        approval_required: false, actions: ["modify", "skip", "reprioritize"],
      },
      {
        id: "verify-v2-replay", title: "Check that results can be reproduced", what: "Independently replay the retained evidence and check new fixtures.",
        benefit: "Catches missing or duplicate steps before we trust study results.",
        cost: { summary: "2–4 review hours; no local study runs.", kind: "estimate", basis: "Codex planning estimate from the accepted v2 development sequence; not measured effort." },
        conviction: { score: 9, kind: "estimate", basis: "Reviewer judgment that this work is worth doing; not a probability of a positive research result." },
        worth_time: { recommendation: "after_dependency", basis: "Start after the runner and new replay fixtures are available." },
        status: "authorized", owner: "codex", depends_on: ["build-v2-runner"], source: "curated daily brief", observed_at: now,
        approval_required: false, actions: ["modify", "skip", "reprioritize"],
      },
      {
        id: "draft-v2-shakedown", title: "Plan a small trial", what: "Draft a small, excluded shakedown test for review.",
        benefit: "Finds setup problems cheaply before the registered study.",
        cost: { summary: "1–2 agent/review hours; about 1–5 local model minutes.", kind: "estimate", basis: "Codex planning estimate from the accepted v2 development sequence; not measured effort." },
        conviction: { score: 8, kind: "estimate", basis: "Reviewer judgment that this work is worth doing; not a probability of a positive research result." },
        worth_time: { recommendation: "after_dependency", basis: "Draft after independent runner/replay acceptance; this card does not run a study." },
        status: "authorized", owner: "oracle", depends_on: ["verify-v2-replay"], source: "curated daily brief", observed_at: now,
        approval_required: false, actions: ["modify", "skip", "reprioritize"],
      },
    ],
    agenda_decision: {
      id: "agenda-decision-1044", agenda_id: "morning-20260920", revision,
      title: "Morning agenda needs amendment", what: "Keep the runner direction, but replace the stale task framing.",
      reason: "It imported unrelated L1 debt and used historical episodes as a denominator.",
      disposition: "amend_required", approval_required: false, approve_enabled: false,
      execution_available: false, actions: ["modify", "skip"],
      task_titles: ["Repeat old calibration", "Resolve unrelated L1 debt"],
      source: "independent semantic review", observed_at: now,
    },
    ...overrides,
  });
}

function v3Summary(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: "daily-ops-summary/v3", generated_at: now, current_plan_revision: "2026-09-25",
    daily_plan: { id: "2026-09-25", date: "2026-09-25", revision: "r1", path: "run_state/daily_plans/2026-09-25.json", sha256: "a".repeat(64), written_at: now, is_current: true, week_alignment: null, bottlenecks: [], review: null },
    research_focus: { status: "none", observed_at: now },
    work_items: [{ id: "d1", goal: "G1", owner: "oracle", lane: "oracle_dev", repo: "a_bgt_rsi", title: "Reconcile the card", summary: null, why_today: null, acceptance: null, depends_on: [], status: "held", detail: "Waiting for source-bound review.", evidence_msg_id: null, evidence_sha: null, evidence_at: null }],
    waiting_on_you: [
      { kind: "question", id: "owner-1", title: "Two exceptions", question: "Which evidence resolves these exceptions?", context: null, choices: [], recommendation: null, consequence: null, asked_by: "oracle", asked_at: now, msg_id: "oracle-owner-1", cli: "read only", awaiting_asker: false, handoff_msg_id: null },
      { kind: "question", id: "claude-1", title: "Claude handoff", question: "Awaiting Claude", context: null, choices: [], recommendation: null, consequence: null, asked_by: "claude", asked_at: now, msg_id: "claude-1", cli: "read only", awaiting_asker: true, handoff_msg_id: "codex-handoff-1" },
    ],
    question_updates: [], accomplishments: [], improvements: [], warnings: [], sources: { plan: now, mailbox: now, focus: null, git: now },
    agents: { oracle: { label: "Oracle", role: "steward", status: "idle", detail: "Idle.", observed_at: now, source: "mailbox", activity: null, activity_at: null, since: null }, pi_client: { label: "Pi client", role: "client", status: "offline", detail: "Offline.", observed_at: now, source: "service", activity: null, activity_at: null, since: null }, nara: { label: "Nara", role: "runner", status: "offline", detail: "Offline.", observed_at: now, source: "service", activity: null, activity_at: null, since: null } },
    ...overrides,
  };
}

function show() {
  return render(<MemoryRouter><DailyOpsPanel legacyResearchOps={null} /></MemoryRouter>);
}

beforeEach(() => {
  sessionStorage.clear();
  D.summary = summary();
  D.v3 = undefined;
  D.messages = messages();
  D.messageError = null;
  D.post.mockReset().mockResolvedValue({ request_id: "request-2", status: "queued", accepted_at: now, duplicate: false, expected_plan_revision: "plan-revision-20260920-0800" });
  D.postDecision.mockReset().mockResolvedValue({
    request_id: "11111111-1111-4111-8111-111111111111", status: "queued",
    accepted_at: now, duplicate: false, target_kind: "work_card", target_id: "build-v2-runner",
    action: "modify", expected_plan_revision: "1044a9c5ff6b617a7f7fce104019202fd77d38bdb2294ff8749100ed331e9621",
    execution_available: false,
  });
  vi.stubGlobal("crypto", { randomUUID: () => "11111111-1111-4111-8111-111111111111" });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("DailyOpsPanel", () => {
  it("prefers the read-only v3 mailbox cards and splits exact handoffs from reconciliation", () => {
    D.v3 = v3Summary();
    show();

    expect(screen.getByTestId("daily-ops-v3-panel")).toBeInTheDocument();
    expect(screen.getByTestId("daily-v3-reconciliation")).toHaveTextContent("Needs agent reconciliation");
    expect(screen.getByTestId("daily-v3-awaiting-claude")).toHaveTextContent("Awaiting Claude");
    expect(screen.queryByRole("button", { name: /ask to|approve|decline|defer|reconcile/i })).toBeNull();
  });

  it("rejects a handoff reference on a card the producer did not route", () => {
    expect(admitDailyOpsV3Summary(v3Summary({ waiting_on_you: [{
      ...v3Summary().waiting_on_you[0], handoff_msg_id: "codex-handoff-1",
    }] }))).toBeNull();
  });

  it("admits a historical plan only as read-only context without a current revision", () => {
    const base = v3Summary();
    D.v3 = v3Summary({
      current_plan_revision: null,
      daily_plan: { ...base.daily_plan, is_current: false },
    });
    show();

    expect(screen.getByTestId("daily-ops-v3-panel")).toBeInTheDocument();
    expect(screen.getByText(/historical only/)).toBeInTheDocument();
    expect(screen.queryByTestId("daily-ops-v3-fallback")).toBeNull();
  });

  it("rejects inconsistent current versus historical plan revision combinations", () => {
    const base = v3Summary();
    expect(admitDailyOpsV3Summary({ ...base, current_plan_revision: null })).toBeNull();
    expect(admitDailyOpsV3Summary({
      ...base,
      daily_plan: { ...base.daily_plan, is_current: false },
    })).toBeNull();
  });

  it("fails closed on every widened or incomplete v3 boundary and retains v2", () => {
    const base = v3Summary();
    const invalid = [
      { ...base, unexpected: true },
      { ...base, sources: {} },
      { ...base, research_focus: { status: "none" } },
      { ...base, agents: { ...base.agents, oracle: { ...base.agents.oracle, status: "invented" } } },
      { ...base, work_items: [{ ...base.work_items[0], unexpected: true }] },
    ];
    for (const value of invalid) expect(admitDailyOpsV3Summary(value)).toBeNull();

    D.v3 = invalid[0];
    D.summary = v2Summary();
    show();
    expect(screen.queryByTestId("daily-ops-v3-panel")).toBeNull();
    expect(screen.getByTestId("daily-ops-v3-fallback")).toBeInTheDocument();
    expect(screen.getByTestId("daily-decision-cards")).toBeInTheDocument();
  });

  it("replaces verbose goals with three concise source-bound work cards", () => {
    D.summary = v2Summary();
    show();

    expect(screen.getByRole("heading", { name: "Today's work" })).toBeInTheDocument();
    expect(screen.getByText("These steps are already authorized. No owner approval is needed.")).toBeInTheDocument();
    expect(screen.getAllByTestId(/^daily-work-card-/)).toHaveLength(3);
    expect(screen.queryByText("Close the instrument gap")).toBeNull();
    expect(screen.getByText("Build the runner and evidence records for the current thesis.")).toBeInTheDocument();
    expect(screen.getByText("Lets us run a controlled test and inspect exactly what happened.")).toBeInTheDocument();
    expect(screen.getByText("4–8 engineering hours; no local study runs.")).toBeInTheDocument();
    expect(screen.getAllByText("9/10")).toHaveLength(2);
    expect(screen.getByText("8/10")).toBeInTheDocument();
    expect(screen.getAllByText("estimate").length).toBeGreaterThanOrEqual(6);
    expect(screen.getByText("Build the runner and evidence records for the current thesis.")).toBeVisible();
    expect(screen.getAllByText("Build the runner and evidence records for the current thesis.")).toHaveLength(1);
    const metadata = screen.getAllByText("Basis, dependencies, and source")[0].closest("details");
    expect(metadata).not.toHaveAttribute("open");
  });

  it("shows the invalid agenda separately without an approval control", () => {
    D.summary = v2Summary();
    show();

    const agenda = screen.getByTestId("daily-agenda-decision");
    expect(agenda).toHaveTextContent("amend required");
    expect(agenda).toHaveTextContent("This agenda cannot be approved");
    expect(within(agenda).queryByRole("button", { name: /approve/i })).toBeNull();
    expect(within(agenda).getByRole("button", { name: "Request corrected draft" })).toBeEnabled();
    expect(within(agenda).getByRole("button", { name: "Ask to skip" })).toBeEnabled();
    const provenance = within(agenda).getByText("Revision, superseded proposal titles, and source").closest("details");
    expect(provenance).not.toHaveAttribute("open");
  });

  it("turns the AMEND action into a corrected-draft request, not approval", async () => {
    D.summary = v2Summary();
    sessionStorage.setItem("oracle-lab-owner-access-key", "owner-secret");
    show();
    const agenda = screen.getByTestId("daily-agenda-decision");

    fireEvent.click(within(agenda).getByRole("button", { name: "Request corrected draft" }));
    const editor = screen.getByTestId("daily-decision-editor");
    fireEvent.change(within(editor).getByLabelText("Required change"), {
      target: { value: "Keep only the three current dependency-ordered steps." },
    });
    fireEvent.click(within(editor).getByRole("button", { name: "Queue modification request" }));

    await waitFor(() => expect(D.postDecision).toHaveBeenCalledWith({
      accessKey: "owner-secret",
      requestId: "11111111-1111-4111-8111-111111111111",
      targetKind: "agenda",
      targetId: "agenda-decision-1044",
      action: "modify",
      expectedPlanRevision: "1044a9c5ff6b617a7f7fce104019202fd77d38bdb2294ff8749100ed331e9621",
      note: "Keep only the three current dependency-ordered steps.",
    }));
    expect(within(editor).getByText(/No execution is implied/)).toBeInTheDocument();
    expect(within(agenda).queryByRole("button", { name: /approve/i })).toBeNull();
  });

  it("focuses a card request and queues only an exact-revision advisory", async () => {
    D.summary = v2Summary();
    sessionStorage.setItem("oracle-lab-owner-access-key", "owner-secret");
    show();
    const card = screen.getByTestId("daily-work-card-build-v2-runner");

    fireEvent.click(within(card).getByRole("button", { name: "Ask to modify" }));
    const editor = screen.getByTestId("daily-decision-editor");
    await waitFor(() => expect(editor).toHaveFocus());
    const submit = within(editor).getByRole("button", { name: "Queue modification request" });
    expect(submit).toBeDisabled();
    const note = within(editor).getByLabelText("Required change");
    expect(note).toHaveAttribute("maxlength", "3000");
    fireEvent.change(note, {
      target: { value: "Keep the runner bounded to the accepted replay contract." },
    });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);

    await waitFor(() => expect(D.postDecision).toHaveBeenCalledWith({
      accessKey: "owner-secret",
      requestId: "11111111-1111-4111-8111-111111111111",
      targetKind: "work_card",
      targetId: "build-v2-runner",
      action: "modify",
      expectedPlanRevision: "1044a9c5ff6b617a7f7fce104019202fd77d38bdb2294ff8749100ed331e9621",
      note: "Keep the runner bounded to the accepted replay contract.",
    }));
    expect(await within(editor).findByText(/Request queued/)).toHaveTextContent("No execution is implied");
    expect(submit).toBeDisabled();
    fireEvent.click(submit);
    expect(D.postDecision).toHaveBeenCalledTimes(1);
    expect(D.post).not.toHaveBeenCalled();
  });

  it("does not apply a late request result to a different card editor", async () => {
    D.summary = v2Summary();
    sessionStorage.setItem("oracle-lab-owner-access-key", "owner-secret");
    let resolveRequest: ((value: Record<string, unknown>) => void) | undefined;
    D.postDecision.mockReturnValueOnce(new Promise(resolve => { resolveRequest = resolve; }));
    show();

    const first = screen.getByTestId("daily-work-card-build-v2-runner");
    fireEvent.click(within(first).getByRole("button", { name: "Ask to modify" }));
    let editor = screen.getByTestId("daily-decision-editor");
    fireEvent.change(within(editor).getByLabelText("Required change"), {
      target: { value: "Change the first card." },
    });
    fireEvent.click(within(editor).getByRole("button", { name: "Queue modification request" }));
    expect(within(editor).getByRole("button", { name: "Sending…" })).toBeDisabled();
    fireEvent.submit(editor.querySelector("form") as HTMLFormElement);
    expect(D.postDecision).toHaveBeenCalledTimes(1);

    const second = screen.getByTestId("daily-work-card-verify-v2-replay");
    fireEvent.click(within(second).getByRole("button", { name: "Ask to skip" }));
    editor = screen.getByTestId("daily-decision-editor");
    expect(within(editor).getByRole("heading", {
      name: "Ask to skip · Check that results can be reproduced",
    })).toBeInTheDocument();
    expect(within(editor).getByRole("button", { name: "Queue skip request" })).toBeEnabled();

    await act(async () => {
      resolveRequest?.({
        request_id: "11111111-1111-4111-8111-111111111111", status: "queued",
        accepted_at: now, duplicate: false, target_kind: "work_card",
        target_id: "build-v2-runner", action: "modify",
        expected_plan_revision: "1044a9c5ff6b617a7f7fce104019202fd77d38bdb2294ff8749100ed331e9621",
        execution_available: false,
      });
      await Promise.resolve();
    });

    expect(within(editor).queryByText(/Request queued/)).toBeNull();
    expect(within(editor).getByRole("button", { name: "Queue skip request" })).toBeEnabled();
    expect(D.postDecision).toHaveBeenCalledTimes(1);
  });

  it("keeps a request local and focuses owner access until the tab is unlocked", async () => {
    D.summary = v2Summary();
    show();
    const card = screen.getByTestId("daily-work-card-build-v2-runner");

    fireEvent.click(within(card).getByRole("button", { name: "Ask to skip" }));
    const editor = screen.getByTestId("daily-decision-editor");
    expect(within(editor).getByRole("button", { name: "Queue skip request" })).toBeDisabled();
    fireEvent.click(within(editor).getByRole("button", { name: "Open owner access controls ↓" }));
    await waitFor(() => expect(screen.getByLabelText(/Owner access key/)).toHaveFocus());
    expect(D.postDecision).not.toHaveBeenCalled();
  });

  it("keeps decision controls read-only when only the chat router can write", () => {
    const candidate = v2Summary() as Record<string, unknown>;
    candidate.capabilities = {
      ...(candidate.capabilities as Record<string, unknown>),
      decision_write_available: false,
    };
    D.summary = candidate;
    sessionStorage.setItem("oracle-lab-owner-access-key", "owner-secret");
    show();

    expect(screen.getByTestId("daily-decisions-readonly")).toHaveTextContent(
      "Decision requests are read-only",
    );
    const card = screen.getByTestId("daily-work-card-build-v2-runner");
    expect(within(card).getByRole("button", { name: "Ask to modify" })).toBeDisabled();
    expect(screen.queryByTestId("daily-decision-editor")).toBeNull();

    fireEvent.change(screen.getByLabelText("Message to Oracle"), {
      target: { value: "The separate chat route still works." },
    });
    expect(screen.getByRole("button", { name: "Queue for Oracle" })).toBeEnabled();
    expect(D.postDecision).not.toHaveBeenCalled();
  });

  it("keeps decision controls read-only while Oracle is degraded", () => {
    const candidate = v2Summary() as Record<string, unknown>;
    const agents = candidate.agents as Record<string, Record<string, unknown>>;
    candidate.agents = {
      ...agents,
      oracle: { ...agents.oracle, status: "degraded", detail: "Review scope is unavailable." },
    };
    D.summary = candidate;
    sessionStorage.setItem("oracle-lab-owner-access-key", "owner-secret");
    show();

    const card = screen.getByTestId("daily-work-card-build-v2-runner");
    expect(within(card).getByRole("button", { name: "Ask to skip" })).toBeDisabled();
    expect(screen.getByTestId("daily-decisions-readonly")).toBeInTheDocument();
    expect(D.postDecision).not.toHaveBeenCalled();
  });

  it("rejects a v2 agenda that is not bound to the exact displayed revision", () => {
    const candidate = v2Summary() as Record<string, unknown>;
    candidate.agenda_decision = {
      ...(candidate.agenda_decision as Record<string, unknown>),
      revision: "different-revision",
    };
    D.summary = candidate;
    show();

    expect(screen.getByTestId("daily-ops-fallback")).toHaveTextContent("Daily synthesis unavailable");
    expect(screen.queryByTestId("daily-decision-cards")).toBeNull();
  });

  it("rejects future agenda dispositions that v2 cannot authorize", () => {
    const candidate = v2Summary() as Record<string, unknown>;
    candidate.agenda_decision = {
      ...(candidate.agenda_decision as Record<string, unknown>),
      disposition: "ready_for_review",
    };
    D.summary = candidate;
    show();

    expect(screen.getByTestId("daily-ops-fallback")).toHaveTextContent("Daily synthesis unavailable");
    expect(screen.queryByText(/ready for review/i)).toBeNull();
  });

  it("does not call unreviewed sealed tasks superseded", () => {
    const candidate = v2Summary() as Record<string, unknown>;
    candidate.agenda_decision = {
      ...(candidate.agenda_decision as Record<string, unknown>),
      disposition: "review_required",
    };
    D.summary = candidate;
    show();

    expect(screen.getByText("Revision, sealed proposal titles, and source")).toBeInTheDocument();
    expect(screen.queryByText("Revision, superseded proposal titles, and source")).toBeNull();
  });

  it("summarizes the day and shows the main thesis exactly once", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-20T12:00:00Z"));
    show();
    expect(screen.getByText("Goals for today")).toBeInTheDocument();
    expect(screen.getByText("Recently accomplished")).toBeInTheDocument();
    expect(screen.getByText("System improvements")).toBeInTheDocument();
    expect(screen.getAllByText("Does payoff assistance improve strategic planning?")).toHaveLength(1);
    expect(screen.getByText("Oracle client")).toBeInTheDocument();
    expect(screen.getByText("Observed runner")).toBeInTheDocument();
    expect(screen.getByText(/queued request is not approval/i)).toBeInTheDocument();
    expect(screen.getByText(/Daily notes last updated Sep 20/)).toBeInTheDocument();
    expect(screen.queryByTestId("daily-notes-stale")).toBeNull();
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

  it("dates authored notes while retaining a fresh agenda task after rollover", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-21T00:01:00Z"));
    D.summary = summary({
      generated_at: "2026-09-20T23:59:00Z",
      goals: [
        ...summary().goals,
        {
          id: "pending-agenda-current",
          title: "Review the current sealed proposal",
          detail: "This task was projected after the authored notes and still awaits owner review.",
          source: "sealed pending agenda",
          observed_at: "2026-09-21T00:00:30Z",
          status: "awaiting_owner",
          owner: "oracle",
        },
      ],
    });

    show();

    expect(screen.getByTestId("daily-notes-stale")).toHaveTextContent(
      "Authored daily notes are from Sep 20, 2026 UTC. Their statuses reflect that update.",
    );
    expect(screen.getByTestId("daily-notes-stale")).toHaveTextContent(
      "The current sealed agenda, thesis, and agent observations update separately.",
    );
    expect(screen.getByRole("heading", { name: "Recorded goals and current agenda" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Accomplishments recorded Sep 20, 2026" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Improvements recorded Sep 20, 2026" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Goals for today" })).toBeNull();
    expect(screen.getByText("Close the instrument gap")).toBeInTheDocument();
    expect(screen.getByText("Review the current sealed proposal")).toBeInTheDocument();
    expect(screen.getByText((_, element) =>
      element?.textContent === "oracle · Sep 21, 12:00 AM UTC")).toBeInTheDocument();
    expect(screen.getAllByText("Does payoff assistance improve strategic planning?")).toHaveLength(1);
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
