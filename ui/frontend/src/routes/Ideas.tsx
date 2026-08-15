// Ideas — the read-only ideas board (GET /api/ideas, 2026-08-14 work order C).
// memory/ideas.md is a DETERMINISTIC projection of the idea ledger
// (workers/idea_projection.py: Live work / Graveyard / Agenda sections), so a
// plain markdown render is the correct v0 surface — no editing affordance, no
// per-row chrome. The board regenerates upstream; this page just shows it.
//
// States (house doctrine — honest, never fabricated):
//   - 204/absent -> "no ideas board yet" (the projection has never run here);
//   - fetch error -> the error string, red, verbatim-ish;
//   - content -> MiniMarkdown (same bounded subset as experiment summaries).
// `initial` bypasses the fetch for fixture renders (null = absent file).
import { useEffect, useState } from "react";
import MiniMarkdown from "../components/MiniMarkdown";
import { getIdeas } from "../api/http";

interface Props {
  /** Fixture override: null = absent file; a string = the markdown. */
  initial?: string | null;
  pollMs?: number;
}

export default function Ideas({ initial, pollMs = 60_000 }: Props) {
  const [markdown, setMarkdown] = useState<string | null>(initial ?? null);
  const [loaded, setLoaded] = useState(initial !== undefined);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (initial !== undefined) return;
    let active = true;
    const load = () =>
      getIdeas()
        .then((resp) => {
          if (!active) return;
          const md = resp !== null && typeof resp.markdown === "string"
            ? resp.markdown
            : null;
          setMarkdown(md);
          setLoaded(true);
          setError(null);
        })
        .catch((e) => {
          if (active) setError(String(e));
        });
    load();
    const id = setInterval(load, Math.max(5_000, pollMs));
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [initial, pollMs]);

  return (
    <div className="mx-auto max-w-4xl p-5" data-testid="ideas-board">
      <header className="mb-3">
        <h1 className="text-sm font-semibold uppercase tracking-wide text-zinc-300">
          /ideas · idea ledger board
        </h1>
        <p className="mt-0.5 text-[11px] text-zinc-500">
          Read-only projection of the idea ledger (memory/ideas.md — Live work,
          Graveyard, Agenda). Regenerated deterministically by the apparatus;
          nothing here is editable.
        </p>
      </header>

      {error !== null && (
        <div className="text-xs text-red-400" data-testid="ideas-error">
          {error}
        </div>
      )}

      {error === null && loaded && markdown === null && (
        <div className="text-sm text-zinc-500" data-testid="ideas-empty">
          no ideas board yet — memory/ideas.md has not been generated on this
          checkout.
        </div>
      )}

      {error === null && markdown !== null && (
        <div className="rounded border border-zinc-800 bg-zinc-900/40 p-4">
          <MiniMarkdown source={markdown} />
        </div>
      )}
    </div>
  );
}
