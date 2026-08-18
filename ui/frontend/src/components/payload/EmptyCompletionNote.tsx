// EmptyCompletionNote — the empty-completion line for the expanded call
// reader (owner feedback 2026-08-18: the loud "EMPTY" banner is MISLEADING
// on retrieval-family calls, where a completion-less call is NORMAL — the
// tool result IS the output). When the call's prompt messages carry a tool
// result, the line is a muted factual note; a genuinely-empty GENERATION
// call (no tool results anywhere) keeps the loud rose EMPTY treatment.
// Presence-of-a-tool-role-message is the WHOLE test — nothing about the
// payload is re-judged client-side.
//
// Owned by the payload family; ModelIO.tsx (its own lane) swaps its inline
// banner for <EmptyCompletionNote messages={detail.prompt_messages} /> —
// the loud branch below is byte-identical to the banner it replaces.

/** True when the prompt messages contain at least one tool-result message
 * (the retrieval-family pattern). Null-safe over the passthrough shape. */
export function messagesHaveToolResult(messages: unknown): boolean {
  return (
    Array.isArray(messages) &&
    messages.some(
      (m) =>
        m != null &&
        typeof m === "object" &&
        (m as { role?: unknown }).role === "tool",
    )
  );
}

export default function EmptyCompletionNote({
  messages,
}: {
  messages: unknown;
}) {
  if (messagesHaveToolResult(messages)) {
    return (
      <div data-testid="empty-tool-note" className="text-xs text-zinc-500">
        {"no completion text — tool-result call (normal for retrieval/scoring stations)"}
      </div>
    );
  }
  return (
    <div data-testid="empty-loud" className="text-xs text-rose-400">
      {"EMPTY — the model returned no completion text."}
    </div>
  );
}
