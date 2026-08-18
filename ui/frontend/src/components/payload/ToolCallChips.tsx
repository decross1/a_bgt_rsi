// ToolCallChips — assistant tool_calls as chip-rows (owner feedback
// 2026-08-18: the escaped-JSON blob is "really hard to read"). One row per
// call: wrench glyph + bold function name + the PARSED arguments as an
// indented key:value grid. Scalars inline (`k: 10`), long strings clamped to
// 2 lines with show-more, arrays/objects collapsed behind a count summary.
// The raw blob never appears here — MessageBody's per-card raw toggle keeps
// it reachable.
import type { ParsedToolCall } from "./parse";
import { ClampedText, isLong, JsonDetails, scalarText } from "./bits";

function Wrench() {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="shrink-0 text-zinc-500"
    >
      <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
    </svg>
  );
}

function ArgRow({ k, v }: { k: string; v: unknown }) {
  const scalar = scalarText(v);
  if (scalar != null && !(typeof v === "string" && isLong(v))) {
    return (
      <div className="flex items-baseline gap-1.5 font-mono text-[13px]">
        <span className="shrink-0 text-zinc-500">{k}:</span>
        <span className="min-w-0 break-words text-zinc-200">{scalar}</span>
      </div>
    );
  }
  if (typeof v === "string") {
    return (
      <div className="font-mono text-[13px]">
        <span className="text-zinc-500">{k}:</span>
        <ClampedText text={v} />
      </div>
    );
  }
  const label = Array.isArray(v)
    ? `${k}: [${v.length} item${v.length === 1 ? "" : "s"}]`
    : `${k}: {…}`;
  return <JsonDetails label={label} value={v} />;
}

export default function ToolCallChips({ calls }: { calls: ParsedToolCall[] }) {
  return (
    <div className="flex flex-col gap-1.5">
      {calls.map((c, i) => (
        <div
          key={c.id ?? i}
          data-testid="toolcall-chip"
          className="rounded border border-zinc-800 bg-zinc-950/50 px-2 py-1.5"
        >
          <div className="flex items-center gap-1.5">
            <Wrench />
            <span className="font-mono text-[13px] font-semibold text-zinc-100">
              {c.name}
            </span>
            {c.id && (
              <span
                className="ml-auto truncate font-mono text-[10px] text-zinc-600"
                title={c.id}
              >
                {c.id}
              </span>
            )}
          </div>
          {c.args != null && c.args.length > 0 && (
            <div className="ml-5 mt-1 flex flex-col gap-0.5">
              {c.args.map(([k, v]) => (
                <ArgRow key={k} k={k} v={v} />
              ))}
            </div>
          )}
          {/* Arguments that would not parse to an object: shown VERBATIM
              (fail-safe rule — displayed raw, never hidden). */}
          {c.rawArguments != null && (
            <pre
              data-testid="toolcall-raw-args"
              className="ml-5 mt-1 whitespace-pre-wrap rounded bg-zinc-950/60 p-1.5 font-mono text-xs text-zinc-400"
            >
              {c.rawArguments}
            </pre>
          )}
        </div>
      ))}
    </div>
  );
}
