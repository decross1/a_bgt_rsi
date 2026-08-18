// useDocTitles — batch doc-id → title resolution for retrieval surfaces
// (owner request 2026-08-18: "2604.15267" should read "2604.15267 — <its
// title>"). Shared by the dossier ChunksPeek and the model-io tool-result
// neighbor rows.
//
// Contract with the reader:
//   - the bare id renders FIRST; the title fills in when the endpoint
//     answers (no spinner, no layout jump);
//   - a failed / missing / skewed endpoint leaves the bare id standing —
//     absence of a title is never an error state on screen;
//   - one GET per ≤50-id batch (the backend's explicit cap), deduped
//     across all mounted consumers via a module-level cache + in-flight
//     set, so ten neighbor rows never mean ten requests.
//
// Cache semantics: a resolved id caches its title; an id the backend
// confirmed unresolved caches as null (asked, answered, absent). A
// TRANSPORT failure caches nothing, so a later mount may retry.
import { useEffect, useState } from "react";
import { API_BASE } from "../api/http";

export type DocTitle = { title: string; kind: string; detail?: string };

const BATCH_MAX = 50;

const cache = new Map<string, DocTitle | null>();
const inflight = new Set<string>();
const listeners = new Set<() => void>();

function notify() {
  listeners.forEach((l) => l());
}

/** Test-only: forget everything (module caches outlive vitest renders). */
export function _resetDocTitlesForTests() {
  cache.clear();
  inflight.clear();
}

function usable(id: string): boolean {
  // Comma is the batch separator; an id carrying one can't ride the GET.
  return id.length > 0 && !id.includes(",");
}

async function fetchBatches(missing: string[]) {
  for (let i = 0; i < missing.length; i += BATCH_MAX) {
    const batch = missing.slice(i, i + BATCH_MAX);
    try {
      const resp = await fetch(
        `${API_BASE}/api/doc_titles?ids=${encodeURIComponent(batch.join(","))}`,
      );
      if (resp.ok) {
        const data = (await resp.json()) as Record<string, unknown>;
        for (const id of batch) {
          const hit = data[id] as DocTitle | undefined;
          const good =
            hit != null &&
            typeof hit === "object" &&
            typeof hit.title === "string" &&
            hit.title.length > 0;
          cache.set(id, good ? hit : null);
        }
      }
      // non-2xx (503 thin venv, 404 version skew, 400): nothing cached —
      // bare ids stay, and a later mount may retry against a healed backend.
    } catch {
      // network / JSON failure: same honest degradation.
    } finally {
      batch.forEach((id) => inflight.delete(id));
    }
  }
  notify();
}

/** Resolve titles for `ids`. Returns only the ids that resolved — callers
 * render the bare id whenever their key is absent. */
export default function useDocTitles(
  ids: readonly string[],
): Record<string, DocTitle> {
  const [, setTick] = useState(0);
  // Stable want-key: dedup + sort so re-renders with a same-set/new-array
  // prop never re-trigger the effect.
  const key = Array.from(new Set(ids.filter(usable))).sort().join(",");

  useEffect(() => {
    const listener = () => setTick((t) => t + 1);
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);

  useEffect(() => {
    const wanted = key.length > 0 ? key.split(",") : [];
    const missing = wanted.filter((id) => !cache.has(id) && !inflight.has(id));
    if (missing.length === 0) return;
    missing.forEach((id) => inflight.add(id));
    void fetchBatches(missing);
  }, [key]);

  const out: Record<string, DocTitle> = {};
  for (const id of ids) {
    const hit = cache.get(id);
    if (hit != null) out[id] = hit;
  }
  return out;
}
