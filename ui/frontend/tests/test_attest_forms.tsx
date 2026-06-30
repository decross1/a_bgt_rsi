// In-UI attestation forms (B4, D-046) — per-form contract tests against a
// STUBBED global fetch; nothing here ever execs a CLI or touches a live
// ledger. Covers, per docs/human_writeback_contract.md:
//   - frozen enum buttons + the REQUIRED-note gating (submit disabled empty);
//   - the submission sequence: POST → RE-POLL GET /api/human_todo (the item
//     leaving the queue — or gaining its deferred tag — is the durable
//     confirmation, not the POST response);
//   - 502 {rc, stderr}: stderr rendered VERBATIM, un-summarized, no re-poll;
//   - capability handshake: available:false AND a version-skew 404 both
//     degrade to the quiet CLI-fallback note (never red);
//   - BOTH success shapes: the appended ledger row (gate_cli / todo_cli:
//     gated_by / ack_by / attested_by = human:ui) and the finding_review
//     ENVELOPE (stamp at status_audit_row.changed_by; loop_feedback_row
//     null for in_review, which keeps the finding listed BY DESIGN);
//   - defer: offered for every blessed kind, the ONLY action for
//     stale_active_run / state_gate, legacy kind spellings normalized to
//     the frozen enum, unknown kinds get nothing.
//
// All fixture payloads are EXPLICITLY SYNTHETIC constructions mirroring the
// documented producer shapes (docs/DATA_SHAPES.md 2026-06-10 write-back
// ledgers; docs/human_writeback_contract.md success shapes) — they are not
// presented as live rows.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import BubbleAckForm from "../src/components/BubbleAckForm";
import DeferForm from "../src/components/DeferForm";
import FindingReviewForm from "../src/components/FindingReviewForm";
import GateVerdictForm from "../src/components/GateVerdictForm";
import { resetAttestCapabilityCache } from "../src/api/attest";

// --- fetch stub: routes by URL suffix, records every call in order ---

interface RecordedCall {
  url: string;
  method: string;
  body: Record<string, unknown> | null;
}

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: String(status),
    json: async () => body,
  } as unknown as Response;
}

type Route = (url: string, init?: RequestInit) => Response | undefined;

function stubFetch(route: Route): RecordedCall[] {
  const calls: RecordedCall[] = [];
  vi.stubGlobal("fetch", async (url: unknown, init?: RequestInit) => {
    const u = String(url);
    calls.push({
      url: u,
      method: init?.method ?? "GET",
      body:
        typeof init?.body === "string"
          ? (JSON.parse(init.body) as Record<string, unknown>)
          : null,
    });
    const resp = route(u, init);
    if (resp !== undefined) return resp;
    throw new Error(`unstubbed fetch in test: ${u}`);
  });
  return calls;
}

// --- capability fixtures (the GET /api/attest/available shape) ---

const CAP_ALL = {
  available: true,
  actions: { gate_verdict: true, finding_review: true, bubble_ack: true, defer: true },
};
const CAP_NONE = {
  available: false,
  actions: { gate_verdict: false, finding_review: false, bubble_ack: false, defer: false },
};

// --- SYNTHETIC success payloads, shaped per the documented contracts ---

// gate_cli stdout: the appended loop_feedback ledger row itself.
const GATE_ROW = {
  iteration_id: "iter-2026-06-09-001",
  verdict: "valid",
  note: "journal checked against the experiment ledger",
  gated_by: "human:ui",
  gated_at: "2026-06-10T18:00:00Z",
};

// todo_cli ack stdout: the appended coordinator_acks row
// ({bubble_run_id, ack_by, acked_at, note} — DATA_SHAPES 2026-06-10).
const ACK_ROW = {
  bubble_run_id: "coord-2026-06-08-003",
  ack_by: "human:ui",
  acked_at: "2026-06-10T18:05:00Z",
  note: "seen; tracked in dev notes",
};

// todo_cli defer stdout: the appended dev_session_queue row
// ({ref_id, kind, note, status:"open", attested_by, deferred_at}).
const DEFER_ROW = {
  ref_id: "run-stale-1",
  kind: "stale_active_run",
  note: "autopsy needed; not resolvable from the UI",
  status: "open",
  attested_by: "human:ui",
  deferred_at: "2026-06-10T18:10:00Z",
};

// finding_session --set-status stdout: an ENVELOPE, not a ledger row.
const FINDING_ENVELOPE_VALIDATED = {
  finding_id: "sf-001",
  session_id: null,
  outcome: "set-status",
  loop_feedback_row: {
    iteration_id: "iter-2026-06-07-002",
    verdict: "valid",
    gated_by: "human:ui",
  },
  status_audit_row: {
    finding_id: "sf-001",
    status: "validated",
    note: "replicated by hand",
    changed_by: "human:ui",
    changed_at: "2026-06-10T18:15:00Z",
  },
};
const FINDING_ENVELOPE_IN_REVIEW = {
  finding_id: "sf-001",
  session_id: null,
  outcome: "set-status",
  loop_feedback_row: null, // null for in_review, per the contract
  status_audit_row: {
    finding_id: "sf-001",
    status: "in_review",
    note: "needs a deeper look",
    changed_by: "human:ui",
    changed_at: "2026-06-10T18:20:00Z",
  },
};

const EMPTY_QUEUE = { items: [], counts: {} };

// Multi-line stderr that MUST surface verbatim (synthetic, argparse-shaped).
const STDERR_VERBATIM =
  "usage: gate_cli [-h] --iteration-id ID --verdict {valid,invalid,needs_revision}\n" +
  "gate_cli: error: iteration iter-2026-06-09-001 already has a loop_feedback row";

// findByLabelText: every form renders null/"checking…" until the cached
// capability handshake resolves (a microtask) — await the field, then type.
async function typeNote(label: string, value: string) {
  fireEvent.change(await screen.findByLabelText(label), { target: { value } });
}

beforeEach(() => {
  // The capability handshake is cached per page-load; tests must not leak
  // one test's stubbed answer into the next.
  resetAttestCapabilityCache();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("GateVerdictForm", () => {
  it("renders the three frozen verdict buttons (emerald/amber/red), disabled until a note is typed", async () => {
    stubFetch((u) =>
      u.endsWith("/api/attest/available") ? jsonResponse(200, CAP_ALL) : undefined,
    );
    render(<GateVerdictForm iterationId="iter-2026-06-09-001" />);

    const valid = await screen.findByRole("button", { name: "valid" });
    const needsRevision = screen.getByRole("button", { name: "needs_revision" });
    const invalid = screen.getByRole("button", { name: "invalid" });

    // Frozen enum tones: valid emerald, needs_revision amber, invalid red.
    expect(valid.className).toContain("emerald");
    expect(needsRevision.className).toContain("amber");
    expect(invalid.className).toContain("red");

    // REQUIRED note: every submit button is disabled while it is empty.
    expect(valid).toBeDisabled();
    expect(needsRevision).toBeDisabled();
    expect(invalid).toBeDisabled();

    await typeNote("gate verdict note (required)", "checked the journal");
    expect(valid).toBeEnabled();
    expect(needsRevision).toBeEnabled();
    expect(invalid).toBeEnabled();

    // outcome guidance: what each verdict actually does for the loop
    const guidance = screen.getByTestId("gate-verdict-guidance");
    expect(guidance).toHaveTextContent(/valid\s*=\s*approved/i);
    expect(guidance).toHaveTextContent(/needs_revision\s*=\s*paused/i);
    expect(guidance).toHaveTextContent(/invalid\s*=\s*rejected/i);
  });

  it("POSTs the clicked verdict then RE-POLLS the queue; the item leaving is the rendered confirmation", async () => {
    const calls = stubFetch((u, init) => {
      if (u.endsWith("/api/attest/available")) return jsonResponse(200, CAP_ALL);
      if (u.endsWith("/api/attest/gate_verdict") && init?.method === "POST") {
        return jsonResponse(200, GATE_ROW);
      }
      if (u.endsWith("/api/human_todo")) return jsonResponse(200, EMPTY_QUEUE);
      return undefined;
    });
    render(<GateVerdictForm iterationId="iter-2026-06-09-001" />);

    await typeNote(
      "gate verdict note (required)",
      "journal checked against the experiment ledger",
    );
    fireEvent.click(await screen.findByRole("button", { name: "valid" }));

    const success = await screen.findByTestId("attest-success");
    // The returned ledger row's identity stamp renders inline.
    expect(success).toHaveTextContent("human:ui");
    expect(success).toHaveTextContent("confirmed — item left the queue (re-poll)");

    // Sequence: POST first, THEN the confirmation re-poll of /api/human_todo.
    const postIndex = calls.findIndex((c) => c.url.endsWith("/api/attest/gate_verdict"));
    const repollIndex = calls.findIndex((c) => c.url.endsWith("/api/human_todo"));
    expect(postIndex).toBeGreaterThan(-1);
    expect(repollIndex).toBeGreaterThan(postIndex);
    expect(calls[postIndex].body).toEqual({
      iteration_id: "iter-2026-06-09-001",
      verdict: "valid",
      note: "journal checked against the experiment ledger",
    });
  });

  it("renders a 502's CLI stderr VERBATIM in a red mono block and does NOT re-poll", async () => {
    const calls = stubFetch((u, init) => {
      if (u.endsWith("/api/attest/available")) return jsonResponse(200, CAP_ALL);
      if (u.endsWith("/api/attest/gate_verdict") && init?.method === "POST") {
        return jsonResponse(502, { rc: 2, stderr: STDERR_VERBATIM });
      }
      if (u.endsWith("/api/human_todo")) return jsonResponse(200, EMPTY_QUEUE);
      return undefined;
    });
    render(<GateVerdictForm iterationId="iter-2026-06-09-001" />);

    await typeNote("gate verdict note (required)", "trying anyway");
    fireEvent.click(await screen.findByRole("button", { name: "invalid" }));

    const stderrBlock = await screen.findByTestId("attest-stderr");
    // VERBATIM: the exact multi-line CLI output, un-summarized.
    expect(stderrBlock.textContent).toBe(STDERR_VERBATIM);
    expect(stderrBlock.className).toContain("font-mono");
    expect(stderrBlock.className).toContain("red");
    expect(screen.getByText(/cli failed \(rc 2\)/i)).toBeInTheDocument();

    // A failed POST is not a write — there is nothing to confirm; no re-poll.
    expect(calls.some((c) => c.url.endsWith("/api/human_todo"))).toBe(false);
  });

  it("degrades to the quiet CLI-fallback note when the handshake says unavailable", async () => {
    stubFetch((u) =>
      u.endsWith("/api/attest/available") ? jsonResponse(200, CAP_NONE) : undefined,
    );
    render(<GateVerdictForm iterationId="iter-2026-06-09-001" />);

    expect(await screen.findByTestId("attest-unavailable")).toHaveTextContent(
      /CLI fallback/,
    );
    expect(screen.queryByRole("button", { name: "valid" })).toBeNull();
  });

  it("treats a version-skew 404 on the handshake as unavailable, never an error", async () => {
    stubFetch((u) =>
      u.endsWith("/api/attest/available")
        ? jsonResponse(404, { detail: "Not Found" })
        : undefined,
    );
    render(<GateVerdictForm iterationId="iter-2026-06-09-001" />);

    expect(await screen.findByTestId("attest-unavailable")).toBeInTheDocument();
    expect(screen.queryByTestId("attest-error")).toBeNull();
    expect(screen.queryByRole("button", { name: "valid" })).toBeNull();
  });

  it("caches the capability handshake per page-load — one GET serves multiple forms", async () => {
    const calls = stubFetch((u) =>
      u.endsWith("/api/attest/available") ? jsonResponse(200, CAP_ALL) : undefined,
    );
    render(
      <>
        <GateVerdictForm iterationId="iter-a" />
        <GateVerdictForm iterationId="iter-b" />
      </>,
    );
    expect(await screen.findAllByRole("button", { name: "valid" })).toHaveLength(2);
    expect(calls.filter((c) => c.url.endsWith("/api/attest/available"))).toHaveLength(1);
  });
});

describe("FindingReviewForm", () => {
  it("renders the frozen status buttons and requires a note", async () => {
    stubFetch((u) =>
      u.endsWith("/api/attest/available") ? jsonResponse(200, CAP_ALL) : undefined,
    );
    render(<FindingReviewForm findingId="sf-001" />);

    const validated = await screen.findByRole("button", { name: "validated" });
    const inReview = screen.getByRole("button", { name: "in_review" });
    const rejected = screen.getByRole("button", { name: "rejected" });
    expect(validated).toBeDisabled();
    expect(inReview).toBeDisabled();
    expect(rejected).toBeDisabled();

    await typeNote("finding review note (required)", "replicated by hand");
    expect(validated).toBeEnabled();
    expect(rejected).toBeEnabled();

    // outcome guidance: what each status does to the finding
    const guidance = screen.getByTestId("finding-review-guidance");
    expect(guidance).toHaveTextContent(/validated\s*=\s*sign off/i);
    expect(guidance).toHaveTextContent(/in_review\s*=\s*keep interrogating/i);
    expect(guidance).toHaveTextContent(/rejected\s*=\s*dismiss/i);
  });

  it("renders the ENVELOPE success shape: status_audit_row with its human:ui stamp (validated leaves the queue)", async () => {
    const calls = stubFetch((u, init) => {
      if (u.endsWith("/api/attest/available")) return jsonResponse(200, CAP_ALL);
      if (u.endsWith("/api/attest/finding_review") && init?.method === "POST") {
        return jsonResponse(200, FINDING_ENVELOPE_VALIDATED);
      }
      if (u.endsWith("/api/human_todo")) return jsonResponse(200, EMPTY_QUEUE);
      return undefined;
    });
    render(<FindingReviewForm findingId="sf-001" />);

    await typeNote("finding review note (required)", "replicated by hand");
    fireEvent.click(await screen.findByRole("button", { name: "validated" }));

    const success = await screen.findByTestId("attest-success");
    // Stamp resolved from status_audit_row.changed_by — the envelope shape,
    // not the ledger-row shape.
    expect(success).toHaveTextContent("human:ui");
    expect(success).toHaveTextContent("confirmed — item left the queue (re-poll)");
    // The audit row itself renders (the recorded write the human can read).
    const audit = screen.getByTestId("attest-audit-row");
    expect(audit).toHaveTextContent('"changed_by":"human:ui"');
    expect(audit).toHaveTextContent('"status":"validated"');

    expect(
      calls.find((c) => c.url.endsWith("/api/attest/finding_review"))?.body,
    ).toEqual({ finding_id: "sf-001", status: "validated", note: "replicated by hand" });
  });

  it("in_review keeps the finding listed BY DESIGN and the form says so instead of claiming a departure", async () => {
    stubFetch((u, init) => {
      if (u.endsWith("/api/attest/available")) return jsonResponse(200, CAP_ALL);
      if (u.endsWith("/api/attest/finding_review") && init?.method === "POST") {
        return jsonResponse(200, FINDING_ENVELOPE_IN_REVIEW);
      }
      if (u.endsWith("/api/human_todo")) {
        // Re-poll: the finding is STILL in the queue (status in_review).
        return jsonResponse(200, {
          items: [
            {
              kind: "finding_review",
              id: "sf-001",
              title: "Finding sf-001 surfaced",
              since: "2026-06-07T09:00:00Z",
            },
          ],
          counts: { finding_review: 1 },
        });
      }
      return undefined;
    });
    render(<FindingReviewForm findingId="sf-001" />);

    await typeNote("finding review note (required)", "needs a deeper look");
    fireEvent.click(await screen.findByRole("button", { name: "in_review" }));

    const success = await screen.findByTestId("attest-success");
    expect(success).toHaveTextContent(
      "finding stays in the review queue (in_review, by design)",
    );
    expect(success).toHaveTextContent("human:ui");
  });
});

describe("BubbleAckForm", () => {
  it("acks with a required note and confirms by the bubble leaving the re-polled queue", async () => {
    const calls = stubFetch((u, init) => {
      if (u.endsWith("/api/attest/available")) return jsonResponse(200, CAP_ALL);
      if (u.endsWith("/api/attest/bubble_ack") && init?.method === "POST") {
        return jsonResponse(200, ACK_ROW);
      }
      if (u.endsWith("/api/human_todo")) return jsonResponse(200, EMPTY_QUEUE);
      return undefined;
    });
    render(<BubbleAckForm bubbleRunId="coord-2026-06-08-003" />);

    const ack = await screen.findByRole("button", { name: "ack" });
    expect(ack).toBeDisabled(); // note required
    await typeNote("bubble ack note (required)", "seen; tracked in dev notes");
    expect(ack).toBeEnabled();
    fireEvent.click(ack);

    const success = await screen.findByTestId("attest-success");
    // Ledger-row success shape: ack_by carries the identity stamp.
    expect(success).toHaveTextContent("human:ui");
    expect(success).toHaveTextContent("confirmed — item left the queue (re-poll)");
    expect(calls.find((c) => c.url.endsWith("/api/attest/bubble_ack"))?.body).toEqual({
      bubble_run_id: "coord-2026-06-08-003",
      note: "seen; tracked in dev notes",
    });
  });
});

describe("DeferForm", () => {
  it("defers a stale_active_run (defer-only kind) and confirms via the deferred tag on re-poll", async () => {
    const calls = stubFetch((u, init) => {
      if (u.endsWith("/api/attest/available")) return jsonResponse(200, CAP_ALL);
      if (u.endsWith("/api/attest/defer") && init?.method === "POST") {
        return jsonResponse(200, DEFER_ROW);
      }
      if (u.endsWith("/api/human_todo")) {
        // A deferral assigns, it does not resolve: the item is STILL listed,
        // now carrying its additive deferred tag.
        return jsonResponse(200, {
          items: [
            {
              kind: "stale_active_run",
              id: "run-stale-1",
              title: "investigate/clear stale active_run — possible lock-leak",
              since: "2026-06-10T10:00:00Z",
              deferred: true,
              deferral: {
                note: "autopsy needed; not resolvable from the UI",
                by: "human:ui",
                at: "2026-06-10T18:10:00Z",
              },
            },
          ],
          counts: { stale_active_run: 1 },
        });
      }
      return undefined;
    });
    render(<DeferForm kind="stale_active_run" refId="run-stale-1" />);

    // Defer is the ONLY in-UI action for this kind — the form says so.
    expect(await screen.findByTestId("defer-only-note")).toHaveTextContent(
      /direct resolution stays a primary-session action/,
    );

    await typeNote("defer note (required)", "autopsy needed; not resolvable from the UI");
    const defer = screen.getByRole("button", { name: "defer" });
    expect(defer).toBeEnabled();
    fireEvent.click(defer);

    const success = await screen.findByTestId("attest-success");
    expect(success).toHaveTextContent("human:ui"); // attested_by from the row
    expect(success).toHaveTextContent("tagged in the queue (re-poll)");
    expect(calls.find((c) => c.url.endsWith("/api/attest/defer"))?.body).toEqual({
      kind: "stale_active_run",
      ref_id: "run-stale-1",
      note: "autopsy needed; not resolvable from the UI",
    });
  });

  it("requires a note before the defer button enables", async () => {
    stubFetch((u) =>
      u.endsWith("/api/attest/available") ? jsonResponse(200, CAP_ALL) : undefined,
    );
    render(<DeferForm kind="gate_verdict" refId="iter-2026-06-09-001" />);
    const defer = await screen.findByRole("button", { name: "defer" });
    expect(defer).toBeDisabled();
    await typeNote("defer note (required)", "park it for the dev session");
    expect(defer).toBeEnabled();
  });

  it("normalizes legacy kind spellings to the frozen defer enum before POSTing", async () => {
    const calls = stubFetch((u, init) => {
      if (u.endsWith("/api/attest/available")) return jsonResponse(200, CAP_ALL);
      if (u.endsWith("/api/attest/defer") && init?.method === "POST") {
        return jsonResponse(200, { ...DEFER_ROW, ref_id: "gate-week1-7", kind: "state_gate" });
      }
      if (u.endsWith("/api/human_todo")) return jsonResponse(200, EMPTY_QUEUE);
      return undefined;
    });
    render(<DeferForm kind="state_file_gate" refId="gate-week1-7" />);

    await typeNote("defer note (required)", "clear it next dev session");
    fireEvent.click(await screen.findByRole("button", { name: "defer" }));
    await screen.findByTestId("attest-success");

    // state_file_gate (legacy spelling) → state_gate (frozen enum member).
    expect(calls.find((c) => c.url.endsWith("/api/attest/defer"))?.body).toEqual({
      kind: "state_gate",
      ref_id: "gate-week1-7",
      note: "clear it next dev session",
    });
  });

  it("renders NOTHING for an unknown kind — the defer enum is frozen and the POST would 422", async () => {
    stubFetch((u) =>
      u.endsWith("/api/attest/available") ? jsonResponse(200, CAP_ALL) : undefined,
    );
    const { container } = render(<DeferForm kind="mystery_kind" refId="m-1" />);
    // Allow the capability microtask to settle, then assert absence.
    await waitFor(() => expect(container.innerHTML).toBe(""));
    expect(screen.queryByTestId("defer-form")).toBeNull();
  });
});
