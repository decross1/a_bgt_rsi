// parse.ts — PURE payload parsers for the Model I/O reader (owner feedback
// 2026-08-18: "the insight is great but the payload rendering is raw JSON").
// Render-only, no fetches, no mutation. Every parser returns null when the
// payload is not CONFIDENTLY the shape it targets, and the caller
// (MessageBody) falls back to the current raw-text rendering — malformed
// payloads are DISPLAYED raw, never hidden, never a crash.
//
// Ground truth for the shapes (read-only survey of logs/calls.jsonl):
//  - assistant tool_calls are logged SERIALIZED INTO content as a JSON-array
//    string of {id, type, function:{name, arguments}} where arguments is
//    itself an escaped JSON string — the blob the owner pasted;
//  - tool-role content is the wrapper envelope
//    {status, result, errors, wrapper_request_id?, parent_request_id?};
//  - thought markup follows agent_wrapper/cleanup.py's grammar: channel
//    tokens <channel|> / <|channel> / <|channel|> / <channel> (and the
//    analysis/final/message variants), with a bare label word (thought /
//    analysis / final / commentary) alone on a line or alone between two
//    tokens (`<|channel>thought\n<channel|>PROSE`).

export interface ParsedToolCall {
  id: string | null;
  name: string;
  /** Parsed argument entries, or null when arguments did not parse to an
   * object — rawArguments then carries what WAS there, shown verbatim. */
  args: [string, unknown][] | null;
  rawArguments: string | null;
}

// One tool_call entry → ParsedToolCall, or null when it is not
// function-shaped (which vetoes the WHOLE message back to raw).
function asToolCall(el: unknown): ParsedToolCall | null {
  if (el == null || typeof el !== "object" || Array.isArray(el)) return null;
  const fn = (el as { function?: unknown }).function;
  if (fn == null || typeof fn !== "object" || Array.isArray(fn)) return null;
  const name = (fn as { name?: unknown }).name;
  if (typeof name !== "string" || name === "") return null;
  const rawId = (el as { id?: unknown }).id;
  const argsRaw = (fn as { arguments?: unknown }).arguments;
  let args: [string, unknown][] | null = null;
  let rawArguments: string | null = null;
  if (typeof argsRaw === "string") {
    rawArguments = argsRaw;
    try {
      const parsed: unknown = JSON.parse(argsRaw);
      if (
        parsed != null &&
        typeof parsed === "object" &&
        !Array.isArray(parsed)
      ) {
        args = Object.entries(parsed as Record<string, unknown>);
        rawArguments = null;
      }
      // A non-object parse (number/array/string) keeps rawArguments —
      // displayed verbatim under the name chip, never hidden.
    } catch {
      /* malformed arguments string → rawArguments shown verbatim */
    }
  } else if (
    argsRaw != null &&
    typeof argsRaw === "object" &&
    !Array.isArray(argsRaw)
  ) {
    args = Object.entries(argsRaw as Record<string, unknown>);
  } else if (argsRaw !== undefined && argsRaw !== null) {
    rawArguments = String(argsRaw);
  }
  return {
    id: typeof rawId === "string" ? rawId : null,
    name,
    args,
    rawArguments,
  };
}

/** Tool calls out of a message: the `tool_calls` field when present, else
 * (assistant only) the serialized-into-content JSON-array form the wrapper
 * actually logs. Null unless EVERY entry is function-shaped — one bad entry
 * sends the whole message back to the raw rendering. */
export function parseToolCalls(
  role: unknown,
  content: unknown,
  toolCalls: unknown,
): ParsedToolCall[] | null {
  let arr: unknown = null;
  if (Array.isArray(toolCalls) && toolCalls.length > 0) {
    arr = toolCalls;
  } else if (
    role === "assistant" &&
    typeof content === "string" &&
    content.trimStart().startsWith("[")
  ) {
    try {
      arr = JSON.parse(content);
    } catch {
      return null; // truncated/malformed blob → raw fallback
    }
  }
  if (!Array.isArray(arr) || arr.length === 0) return null;
  const out: ParsedToolCall[] = [];
  for (const el of arr) {
    const tc = asToolCall(el);
    if (tc == null) return null;
    out.push(tc);
  }
  return out;
}

export interface ToolEnvelope {
  status: string;
  result: unknown;
  errors: unknown[];
  wrapperRequestId: string | null;
  parentRequestId: string | null;
}

const hasOwn = (obj: object, key: string): boolean =>
  Object.prototype.hasOwnProperty.call(obj, key);

/** The wrapper's tool-result envelope, or null when content is not it.
 * Requires an own string `status` plus at least one of result/errors —
 * arbitrary JSON objects stay raw. */
export function parseToolEnvelope(content: unknown): ToolEnvelope | null {
  if (typeof content !== "string" || !content.trimStart().startsWith("{")) {
    return null;
  }
  let obj: unknown;
  try {
    obj = JSON.parse(content);
  } catch {
    return null;
  }
  if (obj == null || typeof obj !== "object" || Array.isArray(obj)) return null;
  const rec = obj as Record<string, unknown>;
  if (!hasOwn(rec, "status") || typeof rec.status !== "string") return null;
  if (!hasOwn(rec, "result") && !hasOwn(rec, "errors")) return null;
  return {
    status: rec.status,
    result: hasOwn(rec, "result") ? rec.result : null,
    errors: Array.isArray(rec.errors) ? rec.errors : [],
    wrapperRequestId:
      typeof rec.wrapper_request_id === "string" ? rec.wrapper_request_id : null,
    parentRequestId:
      typeof rec.parent_request_id === "string" ? rec.parent_request_id : null,
  };
}

export interface ThoughtSplit {
  thought: string;
  answer: string;
}

// cleanup.py's _CHANNEL_TOKEN, ported: <channel|>, <|channel>, <|channel|>,
// <channel> + the analysis/final/message variants. Non-capturing group —
// String.split must not interleave captures.
const CHANNEL_TOKEN_SRC = "<\\|?(?:channel|analysis|final|message)\\|?>";
// A label is only a label when ALONE on its line / segment (cleanup.py's
// _LONE_CHANNEL_LABEL stance) — prose that merely STARTS with "Thought…"
// never reclassifies.
const LABEL_RE = /^\s*(thought|analysis|final|commentary|message)[ \t]*(?:\n|$)/i;
const THOUGHT_LABELS = new Set(["thought", "analysis", "commentary"]);

/** Split channel-markup content into thought vs visible answer. Null when no
 * channel token is present, or when nothing but markup remains (both →
 * caller renders raw). Unlabeled segments stay VISIBLE — the same stance as
 * strip_channel_markup, which keeps all prose. */
export function splitThought(content: unknown): ThoughtSplit | null {
  if (typeof content !== "string") return null;
  if (!new RegExp(CHANNEL_TOKEN_SRC, "i").test(content)) return null;
  const parts = content.split(new RegExp(CHANNEL_TOKEN_SRC, "gi"));
  const thoughts: string[] = [];
  const answers: string[] = [];
  if (parts[0].trim() !== "") answers.push(parts[0].trim());
  let pendingLabel: string | null = null;
  for (let i = 1; i < parts.length; i++) {
    let seg = parts[i];
    let label = pendingLabel;
    pendingLabel = null;
    const m = seg.match(LABEL_RE);
    if (m) {
      const rest = seg.slice(m[0].length);
      if (rest.trim() === "") {
        // `<|channel>thought<channel|>…` — the label sits alone between two
        // tokens and names the NEXT segment's channel.
        pendingLabel = m[1].toLowerCase();
        continue;
      }
      label = m[1].toLowerCase();
      seg = rest;
    }
    const text = seg.trim();
    if (text === "") continue;
    if (label != null && THOUGHT_LABELS.has(label)) thoughts.push(text);
    else answers.push(text);
  }
  const thought = thoughts.join("\n\n");
  const answer = answers.join("\n\n");
  if (thought === "" && answer === "") return null;
  return { thought, answer };
}
