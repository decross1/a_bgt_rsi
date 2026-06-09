// HumanTodoPanel — the human's work queue (GET /api/human_todo). The one
// surface allowed to DEMAND attention: 11+ iterations were sitting at
// gate_status="pending" with no verdict and nothing on screen said so
// (observability_reconciliation_plan.md §"the human's queue is invisible").
// The panel aggregates everything blocked on a human — pending gate verdicts,
// findings awaiting review, unacked bubbles, a stale active_run, state-file
// gates — grouped by kind, oldest-first, each with the EXACT copy-pastable CLI
// command that resolves it (e.g. `python -m orchestrator.gate_cli
// --iteration-id <id> --verdict ...`). The command comes verbatim from the
// backend; the panel never invents one. Write-back buttons are B4, gated on
// the A5 CLI-contract blessing — this slice is read-only.
//
// Poll discipline mirrors SurfacedFindingsPanel/BubblesPanel: an `initial`
// prop bypasses polling (tests render synchronously from fixtures); otherwise
// it polls getHumanTodo(), cleans up on unmount, and surfaces an error string
// rather than throwing. Empty queue is the CALM state ("Nothing needs you —
// the loop is unblocked."), not an alarm — per the don't-over-alarm principle
// the red tint exists only while the count is > 0.
import { useEffect, useState } from "react";
import { getHumanTodo } from "../api/http";
import type { HumanTodoItem } from "../types/schemas";

// Humanized labels for the known queue kinds. Looked up by OWN key only (the
// SurfacedFindingsPanel.toneFor idiom): `kind` is producer-owned, so a value
// colliding with an Object.prototype member ("toString", ...) must not resolve
// to a function through the prototype chain. An unknown kind falls back to the
// raw kind string — rendered quiet, never crashing.
const KIND_LABELS: Record<string, string> = {
  gate_verdict: "awaiting gate verdict",
  finding_review: "finding review",
  bubble_unacked: "bubble unacknowledged",
  stale_active_run: "stale active run",
  state_file_gate: "state-file gate",
  // Aliases matching the live /api/human_todo producer's KINDS exactly
  // (backend/human_todo.py emits these two spellings on its items).
  bubble_ack: "bubble unacknowledged",
  state_gate: "state-file gate",
};

// Display order for known kinds (gate verdicts are the loop's hard blocker, so
// they lead). Unknown kinds append after, in first-appearance order.
const KIND_ORDER = [
  "gate_verdict",
  "finding_review",
  "bubble_unacked",
  "bubble_ack",
  "stale_active_run",
  "state_file_gate",
  "state_gate",
];

// Coerce a producer-owned display scalar to renderable text. An object/array
// rendered as a React child throws and blanks the WHOLE page, so those drop to
// null; a finite number/bool stringifies. (Mirrors SurfacedFindingsPanel.asText.)
function asText(v: unknown): string | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "string") return v;
  if (typeof v === "number") return Number.isFinite(v) ? String(v) : null;
  if (typeof v === "boolean") return String(v);
  // object / array / anything else: not safely renderable as text — skip it.
  return null;
}

function kindLabel(kind: string): string {
  return Object.prototype.hasOwnProperty.call(KIND_LABELS, kind)
    ? KIND_LABELS[kind]
    : kind;
}

function shortTimestamp(iso: unknown): string {
  // `since` is producer-owned: a non-string (epoch number, object) must not
  // throw `.replace is not a function`. (Mirrors BubblesPanel.shortTimestamp.)
  const s = asText(iso);
  if (!s) return "—";
  return s.replace("T", " ").replace("Z", "");
}

// Copy button for the resolve command. navigator.clipboard is absent in
// non-secure contexts AND in jsdom — guard with `?.` so the button is inert
// (never throwing) where the API is missing.
function CopyButton({ command }: { command: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    const writeText = navigator.clipboard?.writeText?.bind(navigator.clipboard);
    if (!writeText) return;
    writeText(command)
      .then(() => setCopied(true))
      .catch(() => {
        /* clipboard write denied — leave the button as-is */
      });
  };
  useEffect(() => {
    if (!copied) return;
    const id = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(id);
  }, [copied]);
  return (
    <button
      type="button"
      onClick={copy}
      aria-label="Copy resolve command"
      className="rounded border border-zinc-700 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-zinc-400 hover:bg-zinc-800"
    >
      {copied ? "copied" : "copy"}
    </button>
  );
}

interface Props {
  initial?: HumanTodoItem[];
  pollMs?: number;
}

export default function HumanTodoPanel({ initial, pollMs = 10000 }: Props) {
  const [items, setItems] = useState<HumanTodoItem[]>(initial ?? []);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(initial !== undefined);

  useEffect(() => {
    if (initial !== undefined) return;
    let active = true;
    const load = () =>
      getHumanTodo()
        .then((r) => {
          if (!active) return;
          setItems(r.items);
          setLoaded(true);
          setError(null);
        })
        .catch((e) => {
          if (active) setError(String(e));
        });
    load();
    const id = setInterval(load, pollMs);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [initial, pollMs]);

  // Producer-owned payload: `items` may not be an array (→ clean empty state,
  // never a `.filter` throw) and a row may be a non-object scalar/null/array
  // (→ skipped, so one malformed line can't blank the queue; an ARRAY row is
  // typeof "object" but has no fields — drop it too). The count badge and
  // empty state reflect renderable rows only.
  const rows = (Array.isArray(items) ? items : []).filter(
    (it): it is HumanTodoItem =>
      typeof it === "object" && it !== null && !Array.isArray(it),
  );

  // Group by kind (a missing/non-string kind groups under "unknown" rather
  // than being dropped — the item still needs the human), kinds in KIND_ORDER
  // then first-appearance, items oldest-first within each group. A missing
  // `since` sorts last — an item of unknown age must not jump the queue.
  const groups = new Map<string, HumanTodoItem[]>();
  for (const row of rows) {
    const kind = asText(row.kind) ?? "unknown";
    const group = groups.get(kind);
    if (group) group.push(row);
    else groups.set(kind, [row]);
  }
  const orderedKinds = [
    ...KIND_ORDER.filter((k) => groups.has(k)),
    ...[...groups.keys()].filter((k) => !KIND_ORDER.includes(k)),
  ];
  for (const kind of orderedKinds) {
    groups.get(kind)!.sort((a, b) => {
      const sa = asText(a.since);
      const sb = asText(b.since);
      if (sa === sb) return 0;
      if (sa === null) return 1;
      if (sb === null) return -1;
      return sa.localeCompare(sb);
    });
  }

  const total = rows.length;

  return (
    <div
      className="rounded border border-zinc-800 bg-zinc-900/40 p-4"
      data-testid="human-todo-panel"
    >
      <div className="flex items-baseline gap-2">
        <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          Human TODO
        </h2>
        <span className="text-[10px] text-zinc-600">
          /api/human_todo · blocked on you
        </span>
        <span
          data-testid="human-todo-count"
          className={`ml-auto rounded px-1.5 py-0.5 text-[11px] ${
            total > 0 ? "bg-red-950 text-red-400" : "text-zinc-500"
          }`}
        >
          {total}
        </span>
      </div>

      {error && <div className="mt-2 text-xs text-red-400">{error}</div>}

      {loaded && total === 0 && !error && (
        <div className="mt-2 text-sm text-zinc-500" data-testid="human-todo-empty">
          Nothing needs you — the loop is unblocked.
        </div>
      )}

      {orderedKinds.map((kind) => (
        <div key={kind} className="mt-3">
          <div className="flex items-baseline gap-2">
            <h3 className="text-[10px] font-medium uppercase tracking-wide text-zinc-500">
              {kindLabel(kind)}
            </h3>
            <span className="text-[10px] text-zinc-600">
              {groups.get(kind)!.length}
            </span>
          </div>
          <ul className="mt-1.5 space-y-1.5">
            {groups.get(kind)!.map((item, i) => {
              const title = asText(item.title);
              const id = asText(item.id);
              const detail = asText(item.detail);
              const command = asText(item.resolve_command);
              return (
                <li
                  key={`${id ?? "todo"}-${i}`}
                  data-testid={`todo-${kind}-${i}`}
                  className="rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1.5"
                >
                  <div className="flex flex-wrap items-baseline gap-2 text-xs">
                    <span className="text-zinc-200">
                      {title ?? id ?? "(untitled)"}
                    </span>
                    <span className="ml-auto font-mono text-[10px] text-zinc-500">
                      {shortTimestamp(item.since)}
                    </span>
                  </div>
                  {detail && (
                    <div className="mt-0.5 text-[11px] text-zinc-400">
                      {detail}
                    </div>
                  )}
                  {command && (
                    <div className="mt-1 flex items-center gap-2">
                      <code className="block flex-1 overflow-x-auto whitespace-pre rounded bg-zinc-900 px-2 py-1 font-mono text-[11px] text-zinc-300">
                        {command}
                      </code>
                      <CopyButton command={command} />
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </div>
  );
}
