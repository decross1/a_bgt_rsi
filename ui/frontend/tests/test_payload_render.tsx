// Payload renderers for the Model I/O expanded view (owner feedback
// 2026-08-18: "insight great, payload rendering is raw JSON — hard to
// read"). The load-bearing pins:
//
//  1. assistant tool_calls — BOTH the tool_calls field and the
//     serialized-into-content escaped-JSON form the wrapper actually logs —
//     render as chip-rows with parsed args; the raw blob is NOT in the
//     default render and stays reachable via the per-card raw toggle;
//  2. the tool-role {status, result, errors, …} envelope renders as a
//     status badge + count chips + prose block + collapsed numbered list,
//     errors ONLY when non-empty, request ids as a muted footer;
//  3. channel markup splits into a dimmed "thought" block vs the visible
//     answer, tokens never leak into the rendered text;
//  4. FAIL-SAFE: every malformed payload is DISPLAYED raw — never hidden,
//     never a crash;
//  5. density: role chips + a single meta chip row in the expanded view,
//     no raw JSON string in the default render (snapshot-free assertions).
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import MessageBody from "../src/components/payload/MessageBody";
import EmptyCompletionNote from "../src/components/payload/EmptyCompletionNote";
import ModelIO from "../src/routes/ModelIO";
import type {
  DispatchTraceResponse,
  ModelIOResponse,
} from "../src/api/modelIO";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

// The REAL logged shape: the tool_calls array serialized INTO content, with
// arguments as an escaped JSON string (this is the blob the owner pasted).
const SERIALIZED_TC =
  '[{"id": "chatcmpl-tool-a8c788ee", "type": "function", "function": ' +
  '{"name": "query_chroma", "arguments": ' +
  '"{\\"text\\": \\"Tit-for-Tat dominance in repeated PD\\", \\"k\\": 10}"}}]';

const LONG_TEXT =
  "Increasing the context window size in a repeated Prisoner's Dilemma " +
  "leads to higher cooperation rates specifically because agents can " +
  "maintain longer-term memory of previous rounds' payoffs, rather than " +
  "through improved instruction following.";

const ENVELOPE = JSON.stringify({
  status: "passed",
  result: {
    k: 10,
    text: LONG_TEXT,
    all_candidates: ["cand one", "cand two", "cand three"],
    candidates_considered: 3,
  },
  errors: [],
  wrapper_request_id: "w-123",
  parent_request_id: "p-456",
});

// ─── 1. tool-call chips ─────────────────────────────────────────────────

it("renders serialized-into-content tool_calls as chips; raw blob only behind the toggle", () => {
  render(<MessageBody role="assistant" content={SERIALIZED_TC} />);
  expect(screen.getByTestId("toolcall-chip")).toBeInTheDocument();
  expect(screen.getByText("query_chroma")).toBeInTheDocument();
  // Parsed args as key:value rows — the escaped string was JSON.parse'd.
  expect(screen.getByText("text:")).toBeInTheDocument();
  expect(
    screen.getByText("Tit-for-Tat dominance in repeated PD"),
  ).toBeInTheDocument();
  expect(screen.getByText("10")).toBeInTheDocument();
  // The raw escaped-JSON blob is NOT in the default render.
  expect(document.body.textContent).not.toContain('"arguments"');
  expect(document.body.textContent).not.toContain('\\"text\\"');
  // The per-card raw toggle brings it back verbatim.
  fireEvent.click(screen.getByTestId("raw-toggle"));
  expect(document.body.textContent).toContain('"arguments"');
  fireEvent.click(screen.getByTestId("raw-toggle"));
  expect(document.body.textContent).not.toContain('"arguments"');
});

it("renders a tool_calls FIELD array; long string args clamp with show-more", () => {
  const longArg = "x".repeat(200);
  render(
    <MessageBody
      role="assistant"
      content={null}
      toolCalls={[
        {
          id: "t1",
          type: "function",
          function: {
            name: "novelty_classify",
            arguments: JSON.stringify({ k: 10, hypothesis_text: longArg }),
          },
        },
      ]}
    />,
  );
  expect(screen.getByText("novelty_classify")).toBeInTheDocument();
  expect(screen.getByText("k:")).toBeInTheDocument();
  expect(screen.getByText("10")).toBeInTheDocument();
  // The long value is clamped with a show-more toggle.
  expect(screen.getByTestId("clamped-text").textContent).toBe(longArg);
  const more = screen.getByRole("button", { name: "show more" });
  fireEvent.click(more);
  expect(
    screen.getByRole("button", { name: "show less" }),
  ).toBeInTheDocument();
});

it("shows unparseable arguments VERBATIM under the name (never hidden)", () => {
  render(
    <MessageBody
      role="assistant"
      content={null}
      toolCalls={[
        {
          id: "t1",
          type: "function",
          function: { name: "query_chroma", arguments: "{not json" },
        },
      ]}
    />,
  );
  expect(screen.getByText("query_chroma")).toBeInTheDocument();
  expect(screen.getByTestId("toolcall-raw-args").textContent).toBe(
    "{not json",
  );
});

// ─── 2. the tool-result envelope card ───────────────────────────────────

it("renders the envelope: status badge, count chips, prose, collapsed list, ids; NO errors section when empty", () => {
  render(<MessageBody role="tool" content={ENVELOPE} />);
  const status = screen.getByTestId("envelope-status");
  expect(status.textContent).toBe("passed");
  expect(status.className).toContain("emerald");
  // Counts as inline chips.
  expect(screen.getByText("k: 10")).toBeInTheDocument();
  expect(screen.getByText("candidates_considered: 3")).toBeInTheDocument();
  // Long "text" field as a readable prose block, not raw JSON.
  expect(screen.getByTestId("envelope-prose-text").textContent).toBe(
    LONG_TEXT,
  );
  // Arrays as a collapsed numbered list with a count summary.
  expect(screen.getByText(/3 all_candidates/)).toBeInTheDocument();
  expect(screen.getByText("cand two")).toBeInTheDocument();
  // Errors section ONLY when non-empty.
  expect(screen.queryByTestId("envelope-errors")).toBeNull();
  // Request ids as the muted footer.
  expect(screen.getByTestId("envelope-ids").textContent).toContain("w-123");
  expect(screen.getByTestId("envelope-ids").textContent).toContain("p-456");
  // The raw JSON text is not in the default render.
  expect(document.body.textContent).not.toContain('"status"');
  expect(document.body.textContent).not.toContain('"wrapper_request_id"');
});

it("renders a non-passed envelope with the warning tone and a highlighted errors section", () => {
  render(
    <MessageBody
      role="tool"
      content={JSON.stringify({
        status: "failed",
        result: {},
        errors: ["chroma timeout after 30s"],
      })}
    />,
  );
  const status = screen.getByTestId("envelope-status");
  expect(status.textContent).toBe("failed");
  expect(status.className).toContain("amber");
  expect(screen.getByTestId("envelope-errors").textContent).toContain(
    "chroma timeout after 30s",
  );
});

// ─── 3. thought split ───────────────────────────────────────────────────

it("splits channel markup into a labeled thought block and the visible answer", () => {
  render(
    <MessageBody
      role="assistant"
      content={
        "<|channel>thought\n<channel|>Deep reasoning here." +
        "<|channel>final<channel|>The visible answer."
      }
    />,
  );
  const thought = screen.getByTestId("thought-block");
  expect(thought.textContent).toContain("thought");
  expect(thought.textContent).toContain("Deep reasoning here.");
  expect(thought.textContent).not.toContain("The visible answer.");
  expect(screen.getByTestId("answer-block").textContent).toBe(
    "The visible answer.",
  );
  // No channel token ever leaks into the rendered text.
  expect(document.body.textContent).not.toContain("<|channel>");
  expect(document.body.textContent).not.toContain("<channel|>");
});

it("keeps an unlabeled channel segment VISIBLE as answer text (strip semantics), no thought block", () => {
  render(
    <MessageBody role="assistant" content={"<channel|>Only narration prose."} />,
  );
  expect(screen.queryByTestId("thought-block")).toBeNull();
  expect(screen.getByTestId("answer-block").textContent).toBe(
    "Only narration prose.",
  );
  expect(document.body.textContent).not.toContain("<channel|>");
});

// ─── 4. the fail-safe rule: malformed → displayed raw ───────────────────

it("displays a truncated tool_calls blob raw (no chips, no toggle, no crash)", () => {
  const broken = '[{"id": "x", "function": {';
  render(<MessageBody role="assistant" content={broken} />);
  expect(screen.queryByTestId("toolcall-chip")).toBeNull();
  expect(screen.queryByTestId("raw-toggle")).toBeNull();
  expect(document.body.textContent).toContain(broken);
});

it("vetoes the WHOLE message back to raw when one tool_calls entry is not function-shaped", () => {
  const mixed =
    '[{"id":"a","type":"function","function":{"name":"ok","arguments":"{}"}},{"id":"b"}]';
  render(<MessageBody role="assistant" content={mixed} />);
  expect(screen.queryByTestId("toolcall-chip")).toBeNull();
  expect(document.body.textContent).toContain('"function"');
});

it("displays non-JSON and non-envelope tool content raw", () => {
  const { unmount } = render(
    <MessageBody role="tool" content={"not json at all"} />,
  );
  expect(screen.queryByTestId("tool-result-card")).toBeNull();
  expect(screen.getByText("not json at all")).toBeInTheDocument();
  unmount();
  // Valid JSON but NOT the envelope (no status) → raw, never guessed.
  render(<MessageBody role="tool" content={'{"result": {"k": 1}}'} />);
  expect(screen.queryByTestId("tool-result-card")).toBeNull();
  expect(document.body.textContent).toContain('{"result": {"k": 1}}');
});

// ─── 5. density pass on the expanded call view (integration) ────────────

const CALLS: ModelIOResponse = {
  calls: [
    {
      ts: "2026-08-18T01:00:00Z",
      request_id: "req-1",
      parent_request_id: null,
      model: "gemma-4-26b-a4b",
      backend: "vllm-gemma",
      caller_tag: "nara.run_iteration",
      run_id: null,
      latency_ms: 4991,
      input_tokens: 822,
      output_tokens: 55,
      prompt_preview: "Evaluate this research topic",
      completion_preview: "Weighing prior art",
      empty: false,
    },
  ],
  source: "logs/calls.jsonl",
  window_truncated: false,
  scanned_bytes: 4096,
  max_scan_bytes: 16777216,
  generated_at: "2026-08-18T01:00:03Z",
};

const TRACE: DispatchTraceResponse = {
  orchestrator_available: false,
  spawn_available: false,
  tasks: [],
  spawns: [],
  generated_at: "2026-08-18T01:00:03Z",
};

const DETAIL = {
  found: true,
  call: {
    timestamp: "2026-08-18T01:00:00Z",
    request_id: "req-1",
    model: "gemma-4-26b-a4b",
    latency_ms: 4991,
    temperature: 0,
    prompt_messages: [
      { role: "system", content: "You are Nara." },
      { role: "assistant", content: SERIALIZED_TC },
      { role: "tool", content: ENVELOPE },
    ],
    completion:
      "<|channel>thought\n<channel|>Weighing prior art." +
      "<|channel>final<channel|>Verdict: novel enough to proceed.",
    usage: { input_tokens: 822, output_tokens: 55 },
  },
};

function stubRoutes() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: unknown) => {
      const u = String(url);
      const body = u.includes("/api/model_io/")
        ? DETAIL
        : u.includes("/api/model_io")
          ? CALLS
          : u.includes("/api/dispatch_trace")
            ? TRACE
            : { version: "abc1234" };
      return {
        ok: true,
        status: 200,
        statusText: "200",
        json: async () => body,
      } as Response;
    }),
  );
}

it("expanded view is chips-first: role chips, one meta chip row, structured payloads, no raw JSON by default", async () => {
  stubRoutes();
  render(<ModelIO />);
  await waitFor(() =>
    expect(screen.getAllByTestId("modelio-row")).toHaveLength(1),
  );
  fireEvent.click(screen.getByTestId("modelio-row"));
  await waitFor(() =>
    expect(screen.getByTestId("call-expansion")).toBeInTheDocument(),
  );
  // Role labels are now chips: system, assistant, tool + the completion chip.
  expect(screen.getAllByTestId("role-chip")).toHaveLength(4);
  // The metadata is ONE compact chip row carrying latency/tokens/ids.
  const meta = screen.getByTestId("meta-chips");
  expect(meta.textContent).toContain("lat 4991ms");
  expect(meta.textContent).toContain("in 822 tok");
  expect(meta.textContent).toContain("req req-1");
  // Structured payload renders replaced the raw blobs.
  expect(screen.getByTestId("toolcall-chip")).toBeInTheDocument();
  expect(screen.getByText("query_chroma")).toBeInTheDocument();
  expect(screen.getByTestId("tool-result-card")).toBeInTheDocument();
  expect(screen.getByTestId("thought-block").textContent).toContain(
    "Weighing prior art.",
  );
  expect(screen.getByTestId("completion-body").textContent).toContain(
    "Verdict: novel enough to proceed.",
  );
  // The owner's pasted pain points are gone from the DEFAULT render.
  expect(document.body.textContent).not.toContain('"arguments"');
  expect(document.body.textContent).not.toContain('\\"text\\"');
  expect(document.body.textContent).not.toContain('"wrapper_request_id"');
});

// ─── 6. retrieval-station verdict cards (owner feedback: raw JSON hard to
//        read). Detection is by KEY SIGNATURE (>=3 signature keys), never by
//        caller name; near-misses fall through to the generic grid; values
//        render AS LOGGED (no client-side re-judging). ─────────────────────

const ESCALATION_RESULT = {
  should_escalate: false,
  max_score: 0.42,
  distinct_books: 0,
  books: [],
  reason: "no book crossed the score threshold",
  score_threshold: 0.7,
  min_distinct_books: 3,
};

const TOPICALITY_PAYLOAD = {
  relevance: 0.61,
  low_confidence: false,
  reason: "anchor cosine well above the R0 floor",
  anchor_cosine: 0.82,
  curated_overlap: null,
  neighbor_spread: 0.4,
  topicality: true,
  category: "escalation_dynamics",
  rule_fired: "R0",
};

it("renders the escalation verdict: NO-ESCALATE badge, meter with threshold tick, books chip, ONE reason line", () => {
  render(
    <MessageBody
      role="tool"
      content={JSON.stringify({
        status: "passed",
        result: ESCALATION_RESULT,
        errors: [],
      })}
    />,
  );
  expect(screen.getByTestId("verdict-escalation")).toBeInTheDocument();
  const badge = screen.getByTestId("escalate-badge");
  expect(badge.textContent).toBe("no-escalate");
  expect(badge.className).toContain("emerald");
  // The envelope chrome stays.
  expect(screen.getByTestId("envelope-status").textContent).toBe("passed");
  // Threshold-tick math: domain = max(1, 0.42, 0.7) = 1 → fill 42%, tick 70%
  // (CSSOM serializes the component's "42.0%" to "42%").
  expect(screen.getByTestId("score-meter-fill").style.width).toBe("42%");
  expect(screen.getByTestId("score-meter-tick").style.left).toBe("70%");
  // Below the threshold → red fill.
  expect(screen.getByTestId("score-meter-fill").className).toContain("rose");
  expect(screen.getByTestId("books-chip").textContent).toBe("books 0/3");
  const reason = screen.getByTestId("verdict-reason");
  expect(reason.textContent).toBe("no book crossed the score threshold");
  expect(reason.className).toContain("truncate"); // ONE line, dim
  // The generic grid did NOT also render the fields.
  expect(screen.queryByText("max_score: 0.42")).toBeNull();
  expect(screen.queryByText("should_escalate: false")).toBeNull();
  // Empty books array → no list details.
  expect(screen.queryByTestId("verdict-books")).toBeNull();
});

it("escalation meter: green fill at/above threshold; the domain stretches to max_score (tick math)", () => {
  render(
    <MessageBody
      role="tool"
      content={JSON.stringify({
        status: "passed",
        result: {
          ...ESCALATION_RESULT,
          should_escalate: true,
          max_score: 1.4,
          distinct_books: 4,
          books: ["book-a", "book-b", "book-c", "book-d"],
        },
        errors: [],
      })}
    />,
  );
  const badge = screen.getByTestId("escalate-badge");
  expect(badge.textContent).toBe("escalate");
  expect(badge.className).toContain("amber");
  // domain = max(1, 1.4, 0.7) = 1.4 → fill 100%, tick at 50%.
  expect(screen.getByTestId("score-meter-fill").style.width).toBe("100%");
  expect(screen.getByTestId("score-meter-tick").style.left).toBe("50%");
  expect(screen.getByTestId("score-meter-fill").className).toContain(
    "emerald",
  );
  expect(screen.getByTestId("books-chip").textContent).toBe("books 4/3");
  // Non-empty books stay reachable behind a collapsed details.
  expect(screen.getByTestId("verdict-books")).toBeInTheDocument();
  expect(screen.getByText(/4 books/)).toBeInTheDocument();
});

it("escalation with a missing score renders null-safe chips instead of a meter (values as logged)", () => {
  const partial = {
    should_escalate: false,
    distinct_books: 1,
    books: ["book-a"],
    score_threshold: 0.7,
    min_distinct_books: 3,
  }; // 5 signature keys, but no max_score → no meter geometry to draw
  render(
    <MessageBody
      role="tool"
      content={JSON.stringify({ status: "passed", result: partial, errors: [] })}
    />,
  );
  expect(screen.getByTestId("verdict-escalation")).toBeInTheDocument();
  expect(screen.queryByTestId("score-meter")).toBeNull();
  expect(document.body.textContent).toContain("max_score —");
  expect(document.body.textContent).toContain("threshold 0.7");
  expect(screen.getByTestId("books-chip").textContent).toBe("books 1/3");
  // No reason logged → no reason line invented.
  expect(screen.queryByTestId("verdict-reason")).toBeNull();
});

it("renders the topicality verdict from a BARE tool payload: badge, rule chip, metric row with null-safe dashes", () => {
  render(
    <MessageBody role="tool" content={JSON.stringify(TOPICALITY_PAYLOAD)} />,
  );
  expect(screen.getByTestId("verdict-topicality")).toBeInTheDocument();
  const badge = screen.getByTestId("topicality-badge");
  expect(badge.textContent).toBe("topical");
  expect(badge.className).toContain("emerald");
  expect(screen.getByTestId("category-chip").textContent).toBe(
    "escalation_dynamics",
  );
  expect(screen.getByTestId("rule-chip").textContent).toBe("rule R0");
  expect(screen.getByText("relevance: 0.61")).toBeInTheDocument();
  expect(screen.getByTestId("low-confidence-chip").textContent).toBe(
    "low_confidence: false",
  );
  const metrics = screen.getByTestId("metric-row");
  expect(metrics.textContent).toContain("anchor_cosine 0.82");
  expect(metrics.textContent).toContain("curated_overlap —"); // null → dash
  expect(metrics.textContent).toContain("neighbor_spread 0.4");
  expect(screen.getByTestId("verdict-reason").textContent).toBe(
    "anchor cosine well above the R0 floor",
  );
  // Bare payload → no envelope chrome; the raw blob stays behind the toggle.
  expect(screen.queryByTestId("envelope-status")).toBeNull();
  expect(document.body.textContent).not.toContain('"anchor_cosine"');
  fireEvent.click(screen.getByTestId("raw-toggle"));
  expect(document.body.textContent).toContain('"anchor_cosine"');
});

it("renders the off-topic direction with warning tones and a low-confidence highlight (null category omitted)", () => {
  render(
    <MessageBody
      role="tool"
      content={JSON.stringify({
        status: "passed",
        result: {
          ...TOPICALITY_PAYLOAD,
          topicality: false,
          low_confidence: true,
          category: null,
          anchor_cosine: null,
        },
        errors: [],
      })}
    />,
  );
  const badge = screen.getByTestId("topicality-badge");
  expect(badge.textContent).toBe("off-topic");
  expect(badge.className).toContain("amber");
  expect(screen.getByTestId("low-confidence-chip").className).toContain(
    "amber",
  );
  expect(screen.queryByTestId("category-chip")).toBeNull();
  expect(screen.getByTestId("metric-row").textContent).toContain(
    "anchor_cosine —",
  );
});

it("falls through to the generic grid on a near-miss shape (only 2 signature keys)", () => {
  render(
    <MessageBody
      role="tool"
      content={JSON.stringify({
        status: "passed",
        result: { max_score: 0.4, score_threshold: 0.7, note: "two keys" },
        errors: [],
      })}
    />,
  );
  expect(screen.queryByTestId("verdict-escalation")).toBeNull();
  expect(screen.queryByTestId("verdict-topicality")).toBeNull();
  expect(screen.queryByTestId("score-meter")).toBeNull();
  // The generic grid rendered the fields instead.
  expect(screen.getByTestId("tool-result-card")).toBeInTheDocument();
  expect(screen.getByText("max_score: 0.4")).toBeInTheDocument();
  expect(screen.getByText("score_threshold: 0.7")).toBeInTheDocument();
});

it("a BARE near-miss payload stays on the raw fail-safe (no verdict, no envelope, no crash)", () => {
  const bare = '{"relevance": 0.5, "low_confidence": true}';
  render(<MessageBody role="tool" content={bare} />);
  expect(screen.queryByTestId("verdict-topicality")).toBeNull();
  expect(screen.queryByTestId("tool-result-card")).toBeNull();
  expect(screen.queryByTestId("raw-toggle")).toBeNull();
  expect(document.body.textContent).toContain(bare);
});

// ─── 7. empty-completion contextualization (owner feedback: the EMPTY
//        banner is misleading on retrieval-family calls, where
//        completion-less is NORMAL — the tool result IS the output). ──────

it("mutes the empty-completion line when the call carries tool results (retrieval-family)", () => {
  render(
    <EmptyCompletionNote
      messages={[
        { role: "system", content: "You are the escalation scorer." },
        { role: "tool", content: ENVELOPE },
      ]}
    />,
  );
  const note = screen.getByTestId("empty-tool-note");
  expect(note.textContent).toBe(
    "no completion text — tool-result call (normal for retrieval/scoring stations)",
  );
  expect(note.className).toContain("zinc"); // muted, not alarming
  expect(screen.queryByTestId("empty-loud")).toBeNull();
  expect(document.body.textContent).not.toContain("EMPTY");
});

it("keeps the loud EMPTY treatment for a genuinely-empty GENERATION call (no tool results)", () => {
  const { unmount } = render(
    <EmptyCompletionNote
      messages={[
        { role: "system", content: "You are Nara." },
        { role: "user", content: "Propose a hypothesis." },
      ]}
    />,
  );
  const loud = screen.getByTestId("empty-loud");
  expect(loud.textContent).toBe(
    "EMPTY — the model returned no completion text.",
  );
  expect(loud.className).toContain("rose");
  expect(screen.queryByTestId("empty-tool-note")).toBeNull();
  unmount();
  // A malformed / absent messages field also stays loud — never guessed.
  render(<EmptyCompletionNote messages={undefined} />);
  expect(screen.getByTestId("empty-loud")).toBeInTheDocument();
});
