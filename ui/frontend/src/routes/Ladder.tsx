// Existing Ladder: topic collections over unchanged individual research records.
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

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
import { buildThesisFamilies } from "../components/ladder/thesisModel";
import ThesisFamilies from "../components/ladder/ThesisFamilies";
import { useLadderSources } from "../api/ladder";
import Card from "../design/Card";
import PeekPanel from "../design/PeekPanel";
import { SkeletonCard } from "../design/Skeleton";
import { registerPaletteActions } from "../design/CommandPalette";
import { getIdeas } from "../api/http";
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
  initialIterations?: unknown[];
  pollMs?: number;
}

type View = "collections" | "board" | "table";

function receivedAt(at: number | null) {
  return at === null ? "not fetched in this view" : new Date(at).toISOString();
}

export default function Ladder({ initial, initialIdeas, initialIterations, pollMs = 30_000 }: Props) {
  const source = useLadderSources({ initial, initialIterations, pollMs });
  const { data, loaded, error } = source;
  const skew = isVersionSkew404(error, LADDER_ENDPOINT);
  const [view, setView] = useState<View>("collections");
  const [graveyardOpen, setGraveyardOpen] = useState(false);
  const [pickedKey, setPickedKey] = useState<string | null>(null);
  const model = useMemo(() => buildLadderModel(data ?? null), [data]);
  const thesis = useMemo(() => buildThesisFamilies(model.clusters, source.iterations), [model.clusters, source.iterations]);
  const recordKeys = useMemo(() => new Map(thesis.records.map((record) => [record.cluster, record.key])), [thesis]);
  // Every Board/Table row comes from the same model input, preserving its raw reference.
  const recordKey = (cluster: LadderCluster): string => recordKeys.get(cluster)!;
  // Resolve against current data on every refresh; do not retain an old object
  // as if it were the record's latest disposition.
  const pickedRecord = thesis.records.find((record) => record.key === pickedKey);
  const picked = pickedRecord?.cluster ?? null;
  const pick = (cluster: LadderCluster) => {
    setPickedKey(thesis.records.find((record) => record.cluster === cluster)?.key ?? null);
  };
  const sourceTimes = model.clusters.map((cluster) => cluster.last_event_ts)
    .filter((value): value is string => typeof value === "string" && Number.isFinite(Date.parse(value)));
  const latestEvent = sourceTimes.sort((a, b) => Date.parse(b) - Date.parse(a))[0];

  // The page's view and graveyard verbs in the ⌘K palette. Navigation to /ladder is already
  // a built-in palette route entry, so registering it again here would only
  // duplicate the row. Re-register on view changes so the graveyard action
  // locates its target even when invoked from a different view.
  useEffect(
    () =>
      registerPaletteActions([
        {
          id: "ladder-toggle-graveyard",
          label: "toggle graveyard",
          group: "Ladder",
          keywords: ["killed", "dead", "tombstone"],
          perform: () => {
            setView("board");
            setGraveyardOpen((open) => view === "board" ? !open : true);
          },
        },
        {
          id: "ladder-switch-view",
          label: "switch ladder view",
          group: "Ladder",
          keywords: ["collections", "board", "table", "kanban"],
          perform: () => setView((v) => v === "collections" ? "board" : v === "board" ? "table" : "collections"),
        },
      ]),
    [view],
  );

  const nowMs = Date.now();
  const agendaOpen = model.agenda.length;

  const viewBtn = (v: View) => (
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
          Recorded evidence levels, not revalidated experiment eligibility.
          Engineering delivery does not change these classifications.
        </p>
        {/* The lab's QUEUE (what these clusters owe next, plus the agenda and
            the refine candidates) lives in Pulse's secondary zone — this board
            is the state, that panel is the to-do. Pulse scrolls to the anchor
            on arrival. */}
        <Link
          to="/#lab-queue"
          data-testid="ladder-lab-queue-link"
          style={{ fontSize: "var(--text-meta)", color: "var(--accent)" }}
        >
          lab queue →
        </Link>
        <div className="flex" style={{ gap: "var(--space-1)" }}>
          {viewBtn("collections")}
          {viewBtn("board")}
          {viewBtn("table")}
        </div>
      </header>

      {error != null && !skew && (
        <div
          data-testid="ladder-error"
          style={{ fontSize: "var(--text-ui)", color: "var(--status-bad)" }}
        >
          Refresh failed: {String(error)}. {data != null && "Showing last received records."}
        </div>
      )}

      {skew && data == null && (
        <>
          <EndpointMissingNote endpoint={LADDER_ENDPOINT} />
          <IdeasFallback initial={initialIdeas} />
        </>
      )}

      {!skew && error == null && !loaded && <SkeletonCard lines={4} />}

      {!skew && error == null && loaded && data === null && (
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

      {data != null && (
        <>
          <Card className="mb-4" testId="ladder-source-state">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2" data-testid="ladder-counts-header">
              <strong>{model.clusters.length} recorded clusters</strong>
              <span>{model.counts.open} open</span>
              <span>{model.counts.killed} killed</span>
              <span>{model.counts.surfaced} surfaced</span>
              <span>{agendaOpen} open agenda</span>
              {initial === undefined && <button type="button" onClick={source.refresh}
                disabled={source.refreshing} className="text-[var(--accent)]">
                {source.refreshing ? "Refreshing sources…" : "Refresh sources"}
              </button>}
            </div>
            <details className="mt-2 text-xs text-[var(--fg-muted)]">
              <summary className="cursor-pointer">Source timestamps · latest recorded event: {latestEvent ?? "unknown"}</summary>
              <p className="mt-2" data-testid="ladder-source-times">
                Records received: {receivedAt(source.recordsAsOf)}. Topics received: {receivedAt(source.topicsAsOf)}.
                {" "}Latest recorded cluster event: {latestEvent ?? "unknown"}.
                {" "}These are separate snapshots; topic association does not validate claim or evidence binding.
              </p>
            </details>
            {source.topicsError !== null && <p role="status" className="mt-2 text-sm text-[var(--status-warn)]">
              Topic refresh failed: {source.topicsError}. {source.iterations !== undefined
                ? "Showing last received associations; their source time is above."
                : "Records remain individual until topic evidence is available."}
            </p>}
            {skew && <p role="status">The record endpoint is now unavailable. Showing last received records.</p>}
          </Card>

          <details className="mb-4" open={view !== "collections"}>
            <summary className="cursor-pointer text-sm text-[var(--fg-muted)]">Recorded stage overview — includes killed history</summary>
            <div className="grid gap-4 pt-3 lg:grid-cols-[minmax(0,1fr)_auto]">
              <Card className="min-w-0" testId="ladder-funnel-panel">
                <LadderFunnel reached={model.reached} killsByRung={model.killsByRung} killedTotal={model.killed.length} />
              </Card>
              <Card testId="ladder-kills-panel">
                <KillsByRung killsByRung={model.killsByRung} killsUnrung={model.killsUnrung} />
              </Card>
            </div>
          </details>

          {/* Keep this component mounted when switching views, preserving its
              collection expansion and member filters without a new controller. */}
          <div hidden={view !== "collections"}>
            <ThesisFamilies model={thesis} nextOwed={model.nextOwed} onPick={pick} nowMs={nowMs} />
          </div>
          {view === "board" && <LadderBoard model={model} recordKey={recordKey} nowMs={nowMs}
            graveyardOpen={graveyardOpen} onToggleGraveyard={() => setGraveyardOpen((v) => !v)} onPick={pick} />}
          {view === "table" && <div className="max-w-full overflow-x-auto">
            <LadderTable clusters={model.clusters} recordKey={recordKey} nowMs={nowMs} onPick={pick} />
          </div>}

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
            onClose={() => setPickedKey(null)}
            title={picked === null ? undefined : stemOf(picked)}
          >
            {picked !== null && (
              <ClusterPeek
                cluster={picked}
                record={pickedRecord}
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
