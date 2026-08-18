// bits.tsx — the shared render atoms for the payload family (ToolCallChips /
// ToolResultCard). Deliberately tiny: a 2-line clamp with show-more, a
// collapsed pretty-JSON <details>, the quiet inline-chip class, and the
// scalar guards. All values are producer-owned JSON — the guards keep a
// weird value a displayed string, never a React-child crash.
import { ReactNode, useState } from "react";

/** Quiet inline chip (counts, metadata) — the chips.tsx family, non-enum. */
export const CHIP_CLS =
  "rounded bg-zinc-900 px-1.5 py-0.5 font-mono text-[10px] text-zinc-400";

/** String form of a scalar, or null for object/array (NOT a scalar). NaN and
 * null render as their honest literals — display, never a guess. */
export function scalarText(v: unknown): string | null {
  if (v === null) return "null";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return null;
}

/** True when a string needs the clamp/prose treatment instead of inline. */
export function isLong(s: string): boolean {
  return s.length > 160 || s.includes("\n");
}

/** JSON.stringify that can never throw at render time. */
export function safeJson(v: unknown, indent = 2): string {
  try {
    return JSON.stringify(v, null, indent) ?? String(v);
  } catch {
    return String(v);
  }
}

/** Long string collapsed to 2 lines with a show-more toggle. The full text is
 * always in the DOM — the clamp is visual only, nothing is hidden from
 * copy/search. */
export function ClampedText({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="min-w-0">
      <div
        data-testid="clamped-text"
        className="whitespace-pre-wrap font-mono text-[13px] text-zinc-300"
        style={
          open
            ? undefined
            : {
                display: "-webkit-box",
                WebkitLineClamp: 2,
                WebkitBoxOrient: "vertical",
                overflow: "hidden",
              }
        }
      >
        {text}
      </div>
      <button
        type="button"
        className="text-[10px] text-sky-400 hover:underline"
        onClick={() => setOpen((o) => !o)}
      >
        {open ? "show less" : "show more"}
      </button>
    </div>
  );
}

/** Nested array/object collapsed behind a <details> summary; expanding shows
 * pretty-printed JSON (bounded height). */
export function JsonDetails({
  label,
  value,
  testId,
}: {
  label: ReactNode;
  value: unknown;
  testId?: string;
}) {
  return (
    <details data-testid={testId} className="text-[13px]">
      <summary className="cursor-pointer select-none text-zinc-400 hover:text-zinc-200">
        {label}
      </summary>
      <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-zinc-950/60 p-1.5 font-mono text-xs text-zinc-300">
        {safeJson(value)}
      </pre>
    </details>
  );
}
