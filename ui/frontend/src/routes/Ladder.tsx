// Ladder (/ladder) — the lab's visual centerpiece (revamp R1). The reduced
// idea-ledger state off GET /api/ladder (ui/backend/ladder.py runs the REAL
// reducer, workers/idea_ledger.py), rebuilt from a text table into a picture:
//
//   header  — the aggregate FUNNEL strip (hand-rolled SVG): L0→L5 narrowing
//             by how many clusters reached each rung, with gray kill-ribbons
//             dropping into a graveyard node; beside it the one chart, the
//             kills-per-rung bar ("where do ideas die?").
//   body    — a KANBAN board, one column per rung plus a collapsed Graveyard
//             grouped by kill code. Cards carry four things; everything else
//             is one click away in a PeekPanel, which is also the single path
//             onward to a member's dossier.
//   toggle  — board | table over the SAME data (the table is the board's
//             scannable, WCAG-clean twin).
//
// /ideas folds in here: the ideas.md markdown render (GET /api/ideas) is this
// page's FALLBACK body — shown when the backend predates /api/ladder (404 =
// version skew → EndpointMissingNote) or the ledger has never been written
// (204 → honest "no idea ledger yet"). Read-only throughout.
import { useEffect, useState } from "react";

import EndpointMissingNote, {
  isVersionSkew404,
} from "../components/EndpointMissingNote";
import MiniMarkdown from "../components/MiniMarkdown";
import ClusterPeek from "../components/ladder/ClusterPeek";
import KillsByRung from "../components/ladder/KillsByRung";
import LadderBoard from "../components/ladder/LadderBoard";
import LadderFunnel from "../components/ladder/LadderFunnel";
import LadderTable from "../components/ladder/LadderTable";
import { buildLadderModel, stemOf } from "../components/ladder/ladderModel";
import Card from "../design/Card";
import PeekPanel from "../design/PeekPanel";
import { SkeletonCard } from "../design/Skeleton";
import { registerPaletteActions } from "../design/CommandPalette";
import { getIdeas, getLadder } from "../api/http";
import type { LadderCluster, LadderResponse } from "../types/schemas";

const LADDER_ENDPOINT = "/api/ladder";

// The /ideas fallback body (the old routes/Ideas.tsx render, folded in).
function IdeasFallback({ initial }: { initial?: string | null }) {
  const [markdown, setMarkdown] = useState<string | null>(initial ?? null);
  const [loaded, setLoaded] = useState(initial !== undefined);

  useEffect(() => {
    if (initial !== undefined) return;
    let active = true;
    getIdeas()
      .then((resp) => {
        if (!active) return;
        setMarkdown(
          resp !== null && typeof resp.markdown === "string"
            ? resp.markdown
            : null,
        );
        setLoaded(true);
      })
      .catch(() => {
        /* the fallback is best-effort — the note above carries the state */
      });
    return () => {
      active = false;
    };
  }, [initial]);

  if (!loaded || markdown === null) return null;
  return (
    <Card testId="ladder-ideas-fallback" className="mt-3">
      <div
        style={{
          marginBottom: "var(--space-2)",
          fontSize: "var(--text-meta)",
          color: "var(--fg-muted)",
        }}
      >
        ideas.md projection (fallback)
      </div>
      <MiniMarkdown source={markdown} />
    </Card>
  );
}

interface Props {
  // Fixture overrides for tests: `initial` undefined = fetch live; null =
  // the 204 no-ledger state; an object = the payload. `initialIdeas` feeds
  // the fallback body the same way (null = absent ideas.md).
  initial?: LadderResponse | null;
  initialIdeas?: string | null;
  pollMs?: number;
}

export default function Ladder({ initial, initialIdeas, pollMs = 30_000 }: Props) {
  const [data, setData] = useState<LadderResponse | null>(initial ?? null);
  const [loaded, setLoaded] = useState(initial !== undefined);
  const [skew, setSkew] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"board" | "table">("board");
  const [graveyardOpen, setGraveyardOpen] = useState(false);
  const [picked, setPicked] = useState<LadderCluster | null>(null);

  useEffect(() => {
    if (initial !== undefined) return;
    let active = true;
    const load = () =>
      getLadder()
        .then((resp) => {
          if (!active) return;
          setData(resp);
          setLoaded(true);
          setSkew(false);
          setError(null);
        })
        .catch((e) => {
          if (!active) return;
          if (isVersionSkew404(e, LADDER_ENDPOINT)) {
            // Older backend binary without the endpoint — quiet note + the
            // ideas.md fallback body, never red.
            setSkew(true);
            setError(null);
          } else {
            setError(String(e));
          }
        });
    load();
    const id = setInterval(load, Math.max(5_000, pollMs));
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [initial, pollMs]);

  // The page's two verbs in the ⌘K palette. Navigation to /ladder is already
  // a built-in palette route entry, so registering it again here would only
  // duplicate the row. Both callbacks are functional setState — stable, so
  // this registers exactly once.
  useEffect(
    () =>
      registerPaletteActions([
        {
          id: "ladder-toggle-graveyard",
          label: "toggle graveyard",
          group: "Ladder",
          keywords: ["killed", "dead", "tombstone"],
          perform: () => setGraveyardOpen((v) => !v),
        },
        {
          id: "ladder-switch-view",
          label: "switch ladder view",
          group: "Ladder",
          keywords: ["board", "table", "kanban"],
          perform: () => setView((v) => (v === "board" ? "table" : "board")),
        },
      ]),
    [],
  );

  const nowMs = Date.now();
  const model = buildLadderModel(data);
  const agendaOpen = model.agenda.length;

  const viewBtn = (v: "board" | "table") => (
    <button
      key={v}
      type="button"
      data-testid={`ladder-view-${v}`}
      aria-pressed={view === v}
      onClick={() => setView(v)}
      style={{
        padding: "2px var(--space-3)",
        borderRadius: "var(--radius-control)",
        border: "1px solid",
        borderColor: view === v ? "var(--accent)" : "var(--border-1)",
        background: view === v ? "var(--accent-muted)" : "transparent",
        color: view === v ? "var(--fg)" : "var(--fg-muted)",
        fontSize: "var(--text-meta)",
        cursor: "pointer",
      }}
    >
      {v}
    </button>
  );

  return (
    <div className="page-full" data-testid="ladder-page">
      <header
        className="flex flex-wrap items-baseline"
        style={{ gap: "var(--space-3)", marginBottom: "var(--space-3)" }}
      >
        <h1
          style={{
            margin: 0,
            fontSize: "var(--text-title-lg)",
            fontWeight: "var(--weight-semibold)",
          }}
        >
          Ladder
        </h1>
        <p
          style={{
            margin: 0,
            flex: 1,
            minWidth: 260,
            fontSize: "var(--text-meta)",
            color: "var(--fg-muted)",
          }}
        >
          Every idea the lab is carrying, by how much evidence stands behind
          it. Only L4+ surfaces to you (D-059); the rest is the machine&apos;s
          to advance or kill.
        </p>
        <div className="flex" style={{ gap: "var(--space-1)" }}>
          {viewBtn("board")}
          {viewBtn("table")}
        </div>
      </header>

      {error !== null && (
        <div
          data-testid="ladder-error"
          style={{ fontSize: "var(--text-ui)", color: "var(--status-bad)" }}
        >
          {error}
        </div>
      )}

      {skew && (
        <>
          <EndpointMissingNote endpoint={LADDER_ENDPOINT} />
          <IdeasFallback initial={initialIdeas} />
        </>
      )}

      {!skew && error === null && !loaded && <SkeletonCard lines={4} />}

      {!skew && error === null && loaded && data === null && (
        <>
          <div
            data-testid="ladder-empty"
            style={{ fontSize: "var(--text-ui)", color: "var(--fg-muted)" }}
          >
            no idea ledger yet — memory/idea_ledger.jsonl has not been written
            on this checkout.
          </div>
          <IdeasFallback initial={initialIdeas} />
        </>
      )}

      {!skew && error === null && data !== null && (
        <>
          {/* The strip: funnel + the one chart, side by side. */}
          <div
            className="flex flex-wrap items-start"
            style={{ gap: "var(--space-4)", marginBottom: "var(--space-4)" }}
          >
            <Card className="flex-1" testId="ladder-funnel-panel">
              <div
                className="flex flex-wrap items-baseline"
                style={{
                  gap: "var(--space-4)",
                  marginBottom: "var(--space-2)",
                  fontSize: "var(--text-meta)",
                  color: "var(--fg-muted)",
                }}
                data-testid="ladder-counts-header"
              >
                <span className="tnum">{model.counts.open} open</span>
                <span className="tnum" style={{ color: "var(--status-ok)" }}>
                  {model.counts.surfaced} surfaced
                </span>
                <span className="tnum" style={{ color: "var(--status-bad)" }}>
                  {model.counts.killed} killed
                </span>
                <span className="tnum">{agendaOpen} open agenda</span>
              </div>
              <LadderFunnel
                reached={model.reached}
                killsByRung={model.killsByRung}
                killedTotal={model.killed.length}
              />
            </Card>
            <Card testId="ladder-kills-panel">
              <KillsByRung
                killsByRung={model.killsByRung}
                killsUnrung={model.killsUnrung}
              />
            </Card>
          </div>

          {view === "board" ? (
            <LadderBoard
              model={model}
              nowMs={nowMs}
              graveyardOpen={graveyardOpen}
              onToggleGraveyard={() => setGraveyardOpen((v) => !v)}
              onPick={setPicked}
            />
          ) : (
            <LadderTable
              clusters={model.clusters}
              nowMs={nowMs}
              onPick={setPicked}
            />
          )}

          {/* A live cluster the producer gave no L0..L5 rung has no column —
              an unknown rung is never shown as a fake L0. Say so out loud;
              the table view lists it. */}
          {model.unrung.length > 0 && (
            <p
              data-testid="ladder-unrung-note"
              style={{
                margin: "var(--space-3) 0 0",
                fontSize: "var(--text-meta)",
                color: "var(--fg-muted)",
              }}
            >
              {model.unrung.length} cluster
              {model.unrung.length === 1 ? "" : "s"} carry no evidence level —
              not on the board or in the funnel; see the table view.
            </p>
          )}

          <PeekPanel
            open={picked !== null}
            onClose={() => setPicked(null)}
            title={picked === null ? undefined : stemOf(picked)}
          >
            {picked !== null && (
              <ClusterPeek
                cluster={picked}
                agenda={model.agenda}
                nextOwed={model.nextOwed}
                nowMs={nowMs}
              />
            )}
          </PeekPanel>
        </>
      )}
    </div>
  );
}
