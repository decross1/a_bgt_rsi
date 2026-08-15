// OweStrip — Pulse's "do I owe anything" strip (UI simplification S1). ONE
// /api/human_todo poll, filtered to what the human actually OWES under the
// 2026-08 selection-before-the-human inversion (D-059): blocking decisions
// (gate_verdict + state_gate families) and finding_review items that CLEAR
// the evidence-ladder bar (L4/L5 — shared logic in src/ladderBar.ts). The 31
// pre-ladder findings and the informational kinds (bubbles, stale runs) stay
// OFF this strip — they live in the dossier index's "everything else".
//
// Rows link into the dossier reader (/dossier/:id — the route lands in S2;
// until then the link 404s forward, which is expected). A ladder histogram
// line (per-level counts over ALL finding rows) keeps the demoted mass
// honest without listing it. A 404 from the endpoint is an HONEST "queue
// UNKNOWN" — never a calm empty state off a dead endpoint.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getHumanTodo } from "../api/http";
import { ageLabel, clearsLadderBar, evidenceLevelOf } from "../ladderBar";
import type { HumanTodoItem } from "../types/schemas";

// Coerce a producer-owned display scalar to renderable text (the
// HumanTodoPanel idiom): object/array drop to null, never a throw.
function asText(v: unknown): string | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "string") return v;
  if (typeof v === "number") return Number.isFinite(v) ? String(v) : null;
  if (typeof v === "boolean") return String(v);
  return null;
}

// The owed kinds, folded across both label generations (the backend emits
// state_gate; the older TS union spelled it state_file_gate).
function isBlockingKind(kind: string | null): boolean {
  return (
    kind === "gate_verdict" ||
    kind === "state_gate" ||
    kind === "state_file_gate"
  );
}

function owed(item: HumanTodoItem): boolean {
  const kind = asText(item.kind);
  if (isBlockingKind(kind)) return true;
  return kind === "finding_review" && clearsLadderBar(item);
}

interface Props {
  // Fixture injection (tests render synchronously, never fetch).
  initial?: HumanTodoItem[];
  pollMs?: number;
}

export default function OweStrip({ initial, pollMs = 10000 }: Props) {
  const [items, setItems] = useState<HumanTodoItem[]>(initial ?? []);
  const [loaded, setLoaded] = useState(initial !== undefined);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (initial !== undefined) return;
    let active = true;
    const load = () =>
      getHumanTodo()
        .then((r) => {
          if (!active) return;
          setItems(Array.isArray(r?.items) ? r.items : []);
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

  // Producer-owned rows: drop non-object entries (HumanTodoPanel idiom).
  const rows = (Array.isArray(items) ? items : []).filter(
    (it): it is HumanTodoItem =>
      typeof it === "object" && it !== null && !Array.isArray(it),
  );
  const owedRows = rows.filter(owed);

  // Ladder histogram over ALL finding rows (demoted included) — derived from
  // the items themselves, no extra fetch. Absent/malformed level counts
  // under "no level" (the legacy bucket), honestly.
  const findingRows = rows.filter((it) => asText(it.kind) === "finding_review");
  const levelCounts = new Map<string, number>();
  for (const it of findingRows) {
    const level = evidenceLevelOf(it) ?? "no level";
    levelCounts.set(level, (levelCounts.get(level) ?? 0) + 1);
  }
  const levelOrder = [...levelCounts.keys()].sort((a, b) => {
    if (a === "no level") return 1;
    if (b === "no level") return -1;
    return b.localeCompare(a); // L5 first, down the ladder
  });

  const endpointMissing = error !== null && /\b404\b/.test(error);
  const nowMs = Date.now();

  return (
    <div
      className="rounded border border-zinc-800 bg-zinc-900/40 p-4"
      data-testid="owe-strip"
    >
      <div className="flex items-baseline gap-2">
        <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          You owe
        </h2>
        <span className="text-[10px] text-zinc-600">
          gate verdicts + findings that cleared L4
        </span>
        <span
          data-testid="owe-count"
          className={`ml-auto rounded px-1.5 py-0.5 text-[11px] ${
            owedRows.length > 0
              ? "bg-amber-950 text-amber-400"
              : "text-zinc-500"
          }`}
        >
          {owedRows.length}
        </span>
      </div>

      {error &&
        (endpointMissing ? (
          // Honest 404 state: the queue SOURCE is missing — say so, never
          // render the calm "you owe nothing" off a dead endpoint.
          <div className="mt-2 text-xs text-amber-400" data-testid="owe-error">
            /api/human_todo returned 404 — the queue is UNKNOWN, not empty.
          </div>
        ) : (
          <div className="mt-2 text-xs text-red-400" data-testid="owe-error">
            {error}
          </div>
        ))}

      {loaded && !error && owedRows.length === 0 && (
        <div className="mt-2 text-sm text-zinc-500" data-testid="owe-empty">
          You owe nothing — the loop is unblocked.
        </div>
      )}

      {owedRows.length > 0 && (
        <ul className="mt-2 space-y-1.5">
          {owedRows.map((item, i) => {
            const id = asText(item.id);
            const kind = asText(item.kind) ?? "unknown";
            const title = asText(item.title) ?? id ?? "(untitled)";
            const level = evidenceLevelOf(item);
            const blocking = isBlockingKind(kind);
            const body = (
              <>
                <span
                  aria-hidden="true"
                  className={`inline-block h-1.5 w-1.5 self-center rounded-full ${
                    blocking ? "bg-red-400" : "bg-emerald-400"
                  }`}
                />
                <span className="text-zinc-200">{title}</span>
                {level && (
                  <span className="rounded bg-emerald-950 px-1 py-0.5 text-[10px] text-emerald-400">
                    {level}
                  </span>
                )}
                <span className="text-[10px] uppercase tracking-wide text-zinc-600">
                  {kind}
                </span>
                <span className="ml-auto font-mono text-[10px] text-zinc-500">
                  {ageLabel(item.since, nowMs)}
                </span>
              </>
            );
            return (
              <li key={`${id ?? "owe"}-${i}`} data-testid={`owe-row-${i}`}>
                {id ? (
                  // Into the dossier reader (S2 route; forward-404 until then).
                  <Link
                    to={`/dossier/${encodeURIComponent(id)}`}
                    className="flex flex-wrap items-baseline gap-2 rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1.5 text-xs hover:border-zinc-600"
                  >
                    {body}
                  </Link>
                ) : (
                  // No usable id — still listed (it still needs the human),
                  // just not linkable.
                  <div className="flex flex-wrap items-baseline gap-2 rounded border border-zinc-800/60 bg-zinc-950/40 px-2 py-1.5 text-xs">
                    {body}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {findingRows.length > 0 && !error && (
        <div
          className="mt-2 font-mono text-[10px] text-zinc-600"
          data-testid="owe-ladder-counts"
        >
          ladder:{" "}
          {levelOrder
            .map((level) => `${level} ×${levelCounts.get(level)}`)
            .join(" · ")}
        </div>
      )}
    </div>
  );
}
