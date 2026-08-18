// ToolResultCard — the wrapper's tool-result envelope rendered visually
// (owner feedback 2026-08-18): status as a colored badge (passed = positive,
// anything else = warning), result fields as a definition grid — counts and
// short scalars as inline chips, long text as a readable prose block, arrays
// as a collapsed numbered list ("3 all_candidates ▸") — an errors section
// ONLY when non-empty, and the request ids as a tiny muted mono footer.
import type { ToolEnvelope } from "./parse";
import {
  CHIP_CLS,
  ClampedText,
  isLong,
  JsonDetails,
  safeJson,
  scalarText,
} from "./bits";

// passed = positive tone; every other status warns (the owner's spec — a
// non-passed envelope always deserves a second look).
function statusTone(status: string): string {
  return status === "passed"
    ? "bg-emerald-950 text-emerald-400"
    : "bg-amber-950 text-amber-300";
}

function ListValue({ k, items }: { k: string; items: unknown[] }) {
  return (
    <details data-testid={`envelope-list-${k}`} className="text-[13px]">
      <summary className="cursor-pointer select-none text-zinc-400 hover:text-zinc-200">
        {items.length} {k} ▸
      </summary>
      <ol className="ml-6 mt-1 flex list-decimal flex-col gap-1 marker:text-zinc-600">
        {items.map((it, i) => {
          const s = scalarText(it);
          return (
            <li key={i} className="text-zinc-300">
              {s == null ? (
                <JsonDetails label="{…}" value={it} />
              ) : isLong(s) ? (
                <ClampedText text={s} />
              ) : (
                <span className="font-mono text-[13px]">{s}</span>
              )}
            </li>
          );
        })}
      </ol>
    </details>
  );
}

export default function ToolResultCard({ env }: { env: ToolEnvelope }) {
  const resultIsObject =
    env.result != null &&
    typeof env.result === "object" &&
    !Array.isArray(env.result);
  const entries = resultIsObject
    ? Object.entries(env.result as Record<string, unknown>)
    : [];
  // Counts / booleans / short strings ride the status line as chips; long
  // strings, arrays, and nested objects get their own block below.
  const chips: [string, string][] = [];
  const blocks: [string, unknown][] = [];
  for (const [k, v] of entries) {
    const s = scalarText(v);
    if (s != null && !(typeof v === "string" && isLong(v))) chips.push([k, s]);
    else blocks.push([k, v]);
  }
  return (
    <div data-testid="tool-result-card" className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center gap-1.5">
        <span
          data-testid="envelope-status"
          className={`rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${statusTone(env.status)}`}
        >
          {env.status}
        </span>
        {chips.map(([k, v]) => (
          <span key={k} className={CHIP_CLS}>
            {k}: {v}
          </span>
        ))}
      </div>

      {blocks.map(([k, v]) => {
        if (typeof v === "string") {
          return (
            <div key={k}>
              <div className="text-[10px] uppercase tracking-wide text-zinc-500">
                {k}
              </div>
              <div
                data-testid={`envelope-prose-${k}`}
                className="mt-0.5 whitespace-pre-wrap rounded bg-zinc-900/50 p-2 text-[13px] leading-relaxed text-zinc-200"
              >
                {v}
              </div>
            </div>
          );
        }
        if (Array.isArray(v)) return <ListValue key={k} k={k} items={v} />;
        return (
          <JsonDetails
            key={k}
            label={`${k}: {…}`}
            value={v}
            testId={`envelope-obj-${k}`}
          />
        );
      })}

      {/* A non-object result (string / number / array) still renders — the
          envelope shape does not force result to be a dict. */}
      {!resultIsObject && env.result != null && (
        Array.isArray(env.result) ? (
          <ListValue k="result" items={env.result} />
        ) : typeof env.result === "string" ? (
          <div className="whitespace-pre-wrap rounded bg-zinc-900/50 p-2 text-[13px] leading-relaxed text-zinc-200">
            {env.result}
          </div>
        ) : (
          <span className={CHIP_CLS}>result: {scalarText(env.result)}</span>
        )
      )}

      {env.errors.length > 0 && (
        <div
          data-testid="envelope-errors"
          className="rounded border border-rose-900/50 bg-rose-950/30 p-2"
        >
          <div className="text-[10px] uppercase tracking-wide text-rose-400">
            errors
          </div>
          {env.errors.map((e, i) => (
            <div
              key={i}
              className="mt-0.5 whitespace-pre-wrap font-mono text-xs text-rose-200"
            >
              {scalarText(e) ?? safeJson(e)}
            </div>
          ))}
        </div>
      )}

      {(env.wrapperRequestId || env.parentRequestId) && (
        <div
          data-testid="envelope-ids"
          className="flex flex-wrap gap-x-3 font-mono text-[10px] text-zinc-600"
        >
          {env.wrapperRequestId && <span>wrapper {env.wrapperRequestId}</span>}
          {env.parentRequestId && <span>parent {env.parentRequestId}</span>}
        </div>
      )}
    </div>
  );
}
