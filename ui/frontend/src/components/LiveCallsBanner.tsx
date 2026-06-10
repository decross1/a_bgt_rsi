// PAGE A — live wrapper-call banner. The run-mode-agnostic "something is
// happening right now" signal: when /api/activity/monitor reports recent calls
// in the call log (live_calls.active), the apparatus is working even if no
// orchestrator task and no loop iteration is registered — e.g. a raw
// experiment driver (exp005/run.py) calling nara.run_iteration directly. This
// is exactly the case that used to leave /activity blank during a live run.
//
// 2026-06-10: when the backend's additive `groups[]` is present, the banner
// renders one row per (caller_tag, model, backend, run_id) aggregate — the
// fix for the one-model-label bug (a single top `model` shown while two
// backends served). Each row: tag · ×count · model, a backend chip (roles.ts
// tones; ABSENT when the record carried no backend — never guessed from the
// model name), and a run chip anchoring #run-<run_id> on the Now board when
// the run is registered, or a quiet zinc "unregistered" when run_id is null.
// `groups` absent (older backend) falls back to the original aggregate line.
import { backendTone, callerTagTone } from "../roles";
import { elapsed, useNow } from "../time";
import type { LiveCallGroup, LiveCalls } from "../types/activity";

// Coerce a producer-owned display scalar (ActiveRunCard idiom): object/array
// drop to "" so one malformed group field can never blank the banner.
function asText(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "";
  if (typeof value === "boolean") return String(value);
  return "";
}

function asCount(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function GroupRow({ group, index }: { group: LiveCallGroup; index: number }) {
  const tag = asText(group.tag);
  const model = asText(group.model);
  const backend = asText(group.backend);
  const runId = asText(group.run_id);
  const count = asCount(group.count);

  return (
    <li
      data-testid={`live-call-group-${index}`}
      className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5"
    >
      <span className={`font-mono ${callerTagTone(group.tag)}`}>
        {tag || "(untagged)"}
      </span>
      {count != null && (
        <>
          <span className="text-emerald-700">·</span>
          <span className="font-mono text-emerald-300/90">×{count}</span>
        </>
      )}
      {model && (
        <>
          <span className="text-emerald-700">·</span>
          <span className="font-mono text-emerald-400/70">{model}</span>
        </>
      )}
      {/* Backend chip — passthrough provenance. A null backend (pre-EMIT row)
          renders NOTHING here: absence is honest; guessing from the model
          name is fabrication. */}
      {backend && (
        <span
          data-testid={`live-call-group-backend-${index}`}
          className={`rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${backendTone(group.backend)}`}
        >
          {backend}
        </span>
      )}
      {runId ? (
        <a
          href={`#run-${runId}`}
          data-testid={`live-call-group-run-${index}`}
          title="registered run — jump to its Now-board card"
          className="rounded bg-zinc-800 px-1.5 py-0.5 font-mono text-[10px] text-emerald-300 hover:text-emerald-200"
        >
          {runId}
        </a>
      ) : (
        <span
          data-testid={`live-call-group-unregistered-${index}`}
          title="these calls carry no run_id — activity without provenance"
          className="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-zinc-500"
        >
          unregistered
        </span>
      )}
    </li>
  );
}

export default function LiveCallsBanner({ data }: { data: LiveCalls }) {
  const now = useNow();
  if (!data.active) return null;

  // groups[] is additive and producer-owned: only an array with at least one
  // object row engages the grouped render; anything else (older backend,
  // malformed payload) falls back to the original aggregate line.
  const groups = Array.isArray(data.groups)
    ? data.groups.filter(
        (g): g is LiveCallGroup =>
          g != null && typeof g === "object" && !Array.isArray(g),
      )
    : [];
  const grouped = groups.length > 0;
  const otherCount = asCount(data.other_count);

  const tags = data.caller_tags.map((t) => t.tag).join(", ");
  return (
    <div
      data-testid="live-calls-banner"
      className="rounded border border-emerald-800/50 bg-emerald-950/20 p-3 text-xs text-emerald-300"
    >
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="font-medium">
          ● live — {data.count} call{data.count === 1 ? "" : "s"} in last{" "}
          {data.window_s}s
          {data.calls_per_s != null ? ` (~${data.calls_per_s}/s)` : ""}
        </span>
        {!grouped && tags && (
          <span className="font-mono text-emerald-400/80">{tags}</span>
        )}
        {!grouped && data.model && (
          <span className="font-mono text-emerald-400/60">{data.model}</span>
        )}
        {data.last_call_at && (
          <span className="text-emerald-500/70">
            last call {elapsed(data.last_call_at, now)} ago
          </span>
        )}
      </div>
      {grouped && (
        <ul className="mt-1.5 space-y-1" data-testid="live-call-groups">
          {groups.map((g, i) => (
            <GroupRow
              key={`${asText(g.tag)}|${asText(g.model)}|${asText(g.backend)}|${asText(g.run_id)}|${i}`}
              group={g}
              index={i}
            />
          ))}
        </ul>
      )}
      {grouped && data.groups_truncated === true && (
        <div
          className="mt-1 text-emerald-500/70"
          data-testid="live-call-groups-truncated"
        >
          +{otherCount ?? "?"} more call{otherCount === 1 ? "" : "s"}
        </div>
      )}
      <div className="mt-0.5 text-emerald-500/60">
        {grouped
          ? "wrapper-call activity by (tag, model, backend, run) — a run chip jumps to its Now-board card; “unregistered” calls carry no run_id."
          : "wrapper-call activity — this run isn't dispatching through the orchestrator or the loop, so there are no per-task rows below."}
      </div>
    </div>
  );
}
