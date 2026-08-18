// MessageBody — the payload dispatcher for the Model I/O expanded view
// (owner feedback 2026-08-18: less text dense, more visual). Picks ONE
// structured renderer per message:
//   assistant tool_calls (field OR serialized-into-content) → ToolCallChips
//   tool-role {status, result, errors, …} envelope           → ToolResultCard
//   channel-markup content                                    → ThoughtBlock
// FAIL-SAFE RULE: any parse miss falls back to the current raw-text <pre> —
// malformed payloads are DISPLAYED raw, never hidden, never a crash. When a
// structured render is chosen, a per-card "raw" toggle keeps the original
// blob reachable. Render-only; reusable by the dossier lane later.
import { useState } from "react";
import { parseToolCalls, parseToolEnvelope, splitThought } from "./parse";
import { safeJson } from "./bits";
import ToolCallChips from "./ToolCallChips";
import ToolResultCard from "./ToolResultCard";
import ThoughtBlock from "./ThoughtBlock";
import VerdictCard, { parseBareVerdict } from "./VerdictCard";

// Raw view of whatever the message carried. Non-string content (malformed
// row) is stringified for DISPLAY — shown, never a React-child crash.
function rawText(content: unknown, toolCalls: unknown): string {
  if (typeof content === "string" && content !== "") return content;
  if (toolCalls != null) return safeJson(toolCalls);
  if (content == null) return "";
  return safeJson(content);
}

export default function MessageBody({
  role,
  content,
  toolCalls,
  testId,
}: {
  role: string;
  content: unknown;
  toolCalls?: unknown;
  testId?: string;
}) {
  const [showRaw, setShowRaw] = useState(false);

  const calls = parseToolCalls(role, content, toolCalls);
  const envelope =
    calls == null && role === "tool" ? parseToolEnvelope(content) : null;
  // A retrieval-station verdict logged BARE as tool content (no wrapper
  // envelope) still gets the verdict rendering — detection is by key
  // signature (see VerdictCard), never by caller name. Envelope-wrapped
  // verdicts are ToolResultCard's job.
  const bareVerdict =
    calls == null && envelope == null && role === "tool"
      ? parseBareVerdict(content)
      : null;
  const split =
    calls == null && envelope == null && bareVerdict == null
      ? splitThought(content)
      : null;
  const structured =
    calls != null || envelope != null || bareVerdict != null || split != null;

  const raw = (
    <pre className="max-h-64 overflow-y-auto whitespace-pre-wrap rounded bg-zinc-950/60 p-1.5 font-mono text-[13px] text-zinc-300">
      {rawText(content, toolCalls)}
    </pre>
  );

  return (
    <div data-testid={testId}>
      {structured && (
        <button
          type="button"
          data-testid="raw-toggle"
          aria-pressed={showRaw}
          className="float-right ml-2 rounded border border-zinc-800 px-1 py-0.5 text-[9px] text-zinc-500 hover:border-zinc-600 hover:text-zinc-300"
          onClick={() => setShowRaw((r) => !r)}
        >
          {showRaw ? "formatted" : "raw"}
        </button>
      )}
      {!structured || showRaw ? (
        raw
      ) : (
        <div className="max-h-96 overflow-y-auto">
          {calls != null ? (
            <ToolCallChips calls={calls} />
          ) : envelope != null ? (
            <ToolResultCard env={envelope} />
          ) : bareVerdict != null ? (
            <VerdictCard family={bareVerdict.family} data={bareVerdict.data} />
          ) : (
            // split is non-null here by construction of `structured`.
            <ThoughtBlock split={split!} />
          )}
        </div>
      )}
    </div>
  );
}
