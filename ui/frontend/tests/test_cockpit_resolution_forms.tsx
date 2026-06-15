// Cockpit NEW resolution stub-forms (Role D) — contract tests against a STUBBED
// global fetch; nothing here ever execs a CLI or touches a live ledger. Covers
// the four NEW outcome surfaces whose writers are unbuilt PART-2 seams:
//   - AuthorizeFixForm   (outcome 4 — gated spawn-contract enqueue)
//   - SpawnTopicForm     (outcome 5 — finding_followups)
//   - AbstainForm        (outcome 6 — honest no-verdict exit)
//   - DirectiveSignOffField (the optional --directive add-on to a sign-off)
//
// Each is HONEST about being a stub (inviolate rule 4): when its capability flag
// is false it shows "stub — lights up when the <named> primary seam lands" and
// disables submit; it renders the would-run argv READ-ONLY (D-046 / rule 8 — no
// execute button); it surfaces the {status:"stub", would_run} response without
// faking a write; and a 502 {rc, stderr} renders the stderr VERBATIM.
//
// The success payloads are EXPLICITLY SYNTHETIC stub envelopes matching the
// documented producer shape ({stub:true, lights_up_when, would_run}) — never a
// live row.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import AuthorizeFixForm from "../src/components/todo/AuthorizeFixForm";
import SpawnTopicForm from "../src/components/todo/SpawnTopicForm";
import AbstainForm from "../src/components/todo/AbstainForm";
import DirectiveSignOffField from "../src/components/todo/DirectiveSignOffField";

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

// A read-only would-run stub envelope (the documented stub shape).
const stubEnvelope = (...argv: string[]) => ({
  stub: true,
  status: "stub",
  lights_up_when: "the PART-2 primary seam lands",
  would_run: argv,
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

// =========================================================================
// AuthorizeFixForm — outcome 4
// =========================================================================
describe("AuthorizeFixForm (outcome 4)", () => {
  it("when unavailable: shows the stub note, disables submit, still shows discipline copy", () => {
    stubFetch(() => undefined);
    render(<AuthorizeFixForm findingId="finding-001" available={false} />);
    expect(screen.getByTestId("authorize-fix-stub")).toBeInTheDocument();
    // the hard-line copy is present even in stub state
    expect(screen.getByTestId("authorize-fix-discipline")).toHaveTextContent(
      /approve the WORK, not a merge/i,
    );
    // disabled even with a note (capability off)
    fireEvent.change(screen.getByLabelText(/authorize-fix note/i), {
      target: { value: "fix the citation wiring" },
    });
    expect(screen.getByRole("button", { name: /authorize fix/i })).toBeDisabled();
  });

  it("required task + note gate submit; renders the would-run argv read-only (no execute)", () => {
    stubFetch(() => undefined);
    render(<AuthorizeFixForm findingId="finding-001" available={true} />);
    const button = screen.getByRole("button", { name: /authorize fix/i });
    // empty task + note: disabled
    expect(button).toBeDisabled();
    // task only -> still disabled (note required)
    fireEvent.change(screen.getByLabelText(/authorize-fix task/i), {
      target: { value: "do the work" },
    });
    expect(button).toBeDisabled();
    // + note -> enabled
    fireEvent.change(screen.getByLabelText(/authorize-fix note/i), {
      target: { value: "why" },
    });
    expect(button).not.toBeDisabled();
    // argv preview present and read-only (a <pre>, not a button)
    const argv = screen.getByTestId("authorize-fix-argv");
    expect(argv.tagName.toLowerCase()).toBe("pre");
    expect(argv).toHaveTextContent(/orchestrator\.todo_cli authorize-fix/);
    expect(argv).toHaveTextContent(/finding-001/);
    // no execute affordance anywhere
    expect(screen.queryByRole("button", { name: /execute|run/i })).toBeNull();
  });

  it("posts to /api/todo/authorize_fix and renders the stub response honestly", async () => {
    const argv = ".venv-chroma/bin/python -m orchestrator.todo_cli authorize-fix --finding-id finding-001";
    const calls = stubFetch((u) =>
      u.endsWith("/api/todo/authorize_fix")
        ? jsonResponse(200, stubEnvelope(argv))
        : undefined,
    );
    render(<AuthorizeFixForm findingId="finding-001" available={true} />);
    fireEvent.change(screen.getByLabelText(/authorize-fix task/i), {
      target: { value: "rewrite the citation wiring so the verdict cites on-domain anchors" },
    });
    fireEvent.change(screen.getByLabelText(/authorize-fix note/i), {
      target: { value: "fix the citation wiring" },
    });
    fireEvent.click(screen.getByRole("button", { name: /authorize fix/i }));
    await waitFor(() => expect(screen.getByTestId("authorize-fix-result")).toBeInTheDocument());
    expect(screen.getByTestId("authorize-fix-result")).toHaveTextContent(/stub response/i);
    const post = calls.find((c) => c.url.endsWith("/api/todo/authorize_fix"));
    expect(post?.method).toBe("POST");
    expect(post?.body).toMatchObject({
      ref_id: "finding-001",
      task: "rewrite the citation wiring so the verdict cites on-domain anchors",
      note: "fix the citation wiring",
    });
  });

  it("502 {rc, stderr}: renders the CLI stderr VERBATIM", async () => {
    stubFetch((u) =>
      u.endsWith("/api/todo/authorize_fix")
        ? jsonResponse(502, { rc: 2, stderr: "error: spawn-contract enqueue not yet blessed" })
        : undefined,
    );
    render(<AuthorizeFixForm findingId="finding-001" available={true} />);
    fireEvent.change(screen.getByLabelText(/authorize-fix task/i), {
      target: { value: "do the work" },
    });
    fireEvent.change(screen.getByLabelText(/authorize-fix note/i), {
      target: { value: "go" },
    });
    fireEvent.click(screen.getByRole("button", { name: /authorize fix/i }));
    await waitFor(() => expect(screen.getByTestId("authorize-fix-stderr")).toBeInTheDocument());
    expect(screen.getByTestId("authorize-fix-stderr")).toHaveTextContent(
      "error: spawn-contract enqueue not yet blessed",
    );
  });
});

// =========================================================================
// SpawnTopicForm — outcome 5
// =========================================================================
describe("SpawnTopicForm (outcome 5)", () => {
  it("when unavailable: shows the stub note and disables submit", () => {
    stubFetch(() => undefined);
    render(<SpawnTopicForm findingId="finding-001" available={false} />);
    expect(screen.getByTestId("spawn-topic-stub")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /spawn topic/i })).toBeDisabled();
  });

  it("topic is required to enable submit; kind defaults to finding; argv is read-only", () => {
    stubFetch(() => undefined);
    render(<SpawnTopicForm findingId="finding-001" available={true} />);
    const button = screen.getByRole("button", { name: /spawn topic/i });
    // empty topic -> disabled (kind has a valid default already)
    expect(button).toBeDisabled();
    // + topic -> enabled
    fireEvent.change(screen.getByLabelText(/new topic/i), { target: { value: "anchor coverage" } });
    expect(button).not.toBeDisabled();
    // the kind selector defaults to "finding" and is part of the argv preview
    const argv = screen.getByTestId("spawn-topic-argv");
    expect(argv.tagName.toLowerCase()).toBe("pre");
    expect(argv).toHaveTextContent(/--kind finding/);
  });

  it("posts to /api/todo/spawn_topic with ref_id + kind + topic and renders the stub response", async () => {
    const calls = stubFetch((u) =>
      u.endsWith("/api/todo/spawn_topic") ? jsonResponse(200, stubEnvelope("argv")) : undefined,
    );
    render(<SpawnTopicForm findingId="finding-001" available={true} />);
    fireEvent.change(screen.getByLabelText(/spawn-topic kind/i), { target: { value: "step" } });
    fireEvent.change(screen.getByLabelText(/new topic/i), { target: { value: "anchor coverage" } });
    fireEvent.click(screen.getByRole("button", { name: /spawn topic/i }));
    await waitFor(() => expect(screen.getByTestId("spawn-topic-result")).toBeInTheDocument());
    const post = calls.find((c) => c.url.endsWith("/api/todo/spawn_topic"));
    expect(post?.method).toBe("POST");
    expect(post?.body).toMatchObject({
      ref_id: "finding-001",
      kind: "step",
      topic: "anchor coverage",
    });
  });
});

// =========================================================================
// AbstainForm — outcome 6
// =========================================================================
describe("AbstainForm (outcome 6)", () => {
  it("states the no-verdict semantics explicitly (not a soft sign-off)", () => {
    stubFetch(() => undefined);
    render(<AbstainForm findingId="finding-001" available={true} />);
    expect(screen.getByTestId("abstain-semantics")).toHaveTextContent(/No verdict is recorded/i);
    expect(screen.getByTestId("abstain-semantics")).toHaveTextContent(/not a soft sign-off/i);
  });

  it("required note gates submit; argv read-only; stub note when unavailable", () => {
    stubFetch(() => undefined);
    const { rerender } = render(<AbstainForm findingId="finding-001" available={false} />);
    expect(screen.getByTestId("abstain-stub")).toBeInTheDocument();
    rerender(<AbstainForm findingId="finding-001" available={true} />);
    expect(screen.getByRole("button", { name: /^abstain$/i })).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/abstain note/i), { target: { value: "revisit after R0 fix" } });
    expect(screen.getByRole("button", { name: /^abstain$/i })).not.toBeDisabled();
    expect(screen.getByTestId("abstain-argv").tagName.toLowerCase()).toBe("pre");
  });

  it("posts to /api/todo/abstain and renders the stub response honestly", async () => {
    const calls = stubFetch((u) =>
      u.endsWith("/api/todo/abstain") ? jsonResponse(200, stubEnvelope("argv")) : undefined,
    );
    render(<AbstainForm findingId="finding-001" available={true} />);
    fireEvent.change(screen.getByLabelText(/abstain note/i), { target: { value: "revisit later" } });
    fireEvent.click(screen.getByRole("button", { name: /^abstain$/i }));
    await waitFor(() => expect(screen.getByTestId("abstain-result")).toBeInTheDocument());
    expect(screen.getByTestId("abstain-result")).toHaveTextContent(/stub response/i);
    const post = calls.find((c) => c.url.endsWith("/api/todo/abstain"));
    expect(post?.body).toMatchObject({ ref_id: "finding-001", note: "revisit later" });
  });
});

// =========================================================================
// DirectiveSignOffField — the optional --directive add-on
// =========================================================================
describe("DirectiveSignOffField (sign-off directive add-on)", () => {
  it("empty directive = bare sign-off: shows the bare note, disables the directive submit", () => {
    stubFetch(() => undefined);
    render(<DirectiveSignOffField iterationId="iter-002" note="checked" available={true} />);
    expect(screen.getByTestId("directive-signoff-bare")).toHaveTextContent(/bare sign-off/i);
    expect(screen.getByRole("button", { name: /sign off with directive/i })).toBeDisabled();
    // no argv preview until a directive is typed (the bare path is attest's job)
    expect(screen.queryByTestId("directive-signoff-argv")).toBeNull();
  });

  it("a directive reveals the read-only argv and lifts the value via onDirectiveChange", () => {
    stubFetch(() => undefined);
    const onDirectiveChange = vi.fn();
    render(
      <DirectiveSignOffField
        iterationId="iter-002"
        note="checked"
        available={true}
        onDirectiveChange={onDirectiveChange}
      />,
    );
    fireEvent.change(screen.getByLabelText(/sign-off directive/i), {
      target: { value: "proceed to step 9" },
    });
    expect(onDirectiveChange).toHaveBeenCalledWith("proceed to step 9");
    const argv = screen.getByTestId("directive-signoff-argv");
    expect(argv.tagName.toLowerCase()).toBe("pre");
    expect(argv).toHaveTextContent(/gate_cli/);
    expect(argv).toHaveTextContent(/--directive/);
    expect(argv).toHaveTextContent(/proceed to step 9/);
    expect(screen.getByRole("button", { name: /sign off with directive/i })).not.toBeDisabled();
  });

  it("unavailable: stub note + directive submit disabled even with a directive", () => {
    stubFetch(() => undefined);
    render(<DirectiveSignOffField iterationId="iter-002" note="checked" available={false} />);
    expect(screen.getByTestId("directive-signoff-stub")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/sign-off directive/i), {
      target: { value: "proceed" },
    });
    expect(screen.getByRole("button", { name: /sign off with directive/i })).toBeDisabled();
  });

  it("posts to /api/todo/directive_signoff with iteration_id + directive + note", async () => {
    const calls = stubFetch((u) =>
      u.endsWith("/api/todo/directive_signoff")
        ? jsonResponse(200, stubEnvelope("argv"))
        : undefined,
    );
    render(<DirectiveSignOffField iterationId="iter-002" note="checked" available={true} />);
    fireEvent.change(screen.getByLabelText(/sign-off directive/i), {
      target: { value: "proceed to step 9" },
    });
    fireEvent.click(screen.getByRole("button", { name: /sign off with directive/i }));
    await waitFor(() => expect(screen.getByTestId("directive-signoff-result")).toBeInTheDocument());
    const post = calls.find((c) => c.url.endsWith("/api/todo/directive_signoff"));
    expect(post?.method).toBe("POST");
    expect(post?.body).toMatchObject({
      iteration_id: "iter-002",
      directive: "proceed to step 9",
      note: "checked",
    });
  });
});
