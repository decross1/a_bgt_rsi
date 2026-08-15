// RefPeekBody — what a /channel reference chip peeks at (revamp R4). The chip
// carries an id the apparatus wrote into a message; this body fetches the SMALL
// summary for it and offers the one link onward to the full surface:
//
//   cl-*   → GET /api/ladder, the matching cluster            → /ladder
//   sf-*   → GET /api/finding/{id}                            → /dossier/{id}
//   iter-* → GET /api/iteration/{id}/journey                  → /dossier/{id}
//
// Read-only end to end (all three are GETs with no writer), and NO disposition
// is rendered — the channel fence holds inside the peek too. An id the backend
// does not know renders an honest "not found" (the ladder/finding/journey
// endpoints all answer 200 with found:false / a missing row), never an
// invented summary; a 404 from an older backend binary reads as version skew.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import RungGlyph from "../../design/RungGlyph";
import { SkeletonRows } from "../../design/Skeleton";
import { asText } from "../ladder/ladderModel";
import { getFindingDetail, getIterationJourney, getLadder } from "../../api/http";
import type { ChannelRef } from "./channelModel";
import type { LadderCluster } from "../../types/schemas";

interface Line {
  label: string;
  value: string;
}

interface Found {
  status: "found";
  headline: string;
  lines: Line[];
  /** Non-null only for a cluster (the rung ring belongs to the ladder). */
  level: unknown;
  killed: boolean;
  to: string;
  toLabel: string;
}

type PeekState =
  | { status: "loading" }
  | { status: "missing"; note: string }
  | { status: "error"; note: string }
  | Found;

function clip(text: string, max = 240): string {
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

function clusterSummary(id: string, cluster: LadderCluster): Found {
  const killed = asText(cluster.status) === "killed";
  const lines: Line[] = [
    { label: "status", value: asText(cluster.status) ?? "unknown" },
    { label: "rung", value: asText(cluster.evidence_level) ?? "no rung" },
    {
      label: "members",
      value: String(
        typeof cluster.member_count === "number"
          ? cluster.member_count
          : (cluster.members?.length ?? 0),
      ),
    },
    { label: "last event", value: asText(cluster.last_event_ts) ?? "unknown" },
  ];
  const detail = asText(cluster.kill_reason?.detail);
  const code = asText(cluster.kill_reason?.code);
  if (killed && (code !== null || detail !== null)) {
    lines.push({
      label: "killed",
      value: [code, detail].filter((p) => p !== null).join(" — "),
    });
  }
  return {
    status: "found",
    headline: clip(asText(cluster.stem) ?? id),
    lines,
    level: cluster.evidence_level,
    killed,
    to: "/ladder",
    toLabel: "open the ladder",
  };
}

async function loadRef(refItem: ChannelRef): Promise<PeekState> {
  const { id, kind } = refItem;
  if (kind === "cluster") {
    const resp = await getLadder();
    if (resp === null) {
      return {
        status: "missing",
        note: "no idea ledger on this checkout — nothing to peek at yet.",
      };
    }
    const clusters = Array.isArray(resp.clusters) ? resp.clusters : [];
    const hit = clusters.find((c) => asText(c.cluster_id) === id);
    if (hit === undefined) {
      return { status: "missing", note: `${id} is not in the idea ledger.` };
    }
    return clusterSummary(id, hit);
  }
  if (kind === "finding") {
    const detail = await getFindingDetail(id);
    if (detail.found !== true) {
      return { status: "missing", note: `${id} is not in surfaced_findings.` };
    }
    const lines: Line[] = [
      { label: "status", value: asText(detail.status) ?? "unknown" },
      { label: "novelty", value: asText(detail.novelty_class) ?? "unknown" },
    ];
    const claim = asText(detail.claim);
    if (claim !== null) lines.push({ label: "claim", value: clip(claim) });
    const source = asText(detail.source_iteration_id);
    if (source !== null) lines.push({ label: "from iteration", value: source });
    return {
      status: "found",
      headline: clip(asText(detail.title) ?? id),
      lines,
      level: null,
      killed: false,
      to: `/dossier/${id}`,
      toLabel: "open the dossier",
    };
  }
  const journey = await getIterationJourney(id);
  if (journey.found !== true || journey.iteration == null) {
    return { status: "missing", note: `${id} is not in loop_memory.` };
  }
  const it = journey.iteration;
  const lines: Line[] = [
    { label: "gate", value: asText(it.gate_status) ?? "unknown" },
    { label: "novelty", value: asText(it.novelty?.class) ?? "unknown" },
    { label: "started", value: asText(it.started_at) ?? "unknown" },
  ];
  const summary = asText(it.nara_summary);
  if (summary !== null) lines.push({ label: "summary", value: clip(summary) });
  return {
    status: "found",
    headline: clip(asText(it.seed?.topic) ?? id),
    lines,
    level: null,
    killed: false,
    to: `/dossier/${id}`,
    toLabel: "open the dossier",
  };
}

export default function RefPeekBody({ refItem }: { refItem: ChannelRef }) {
  const [state, setState] = useState<PeekState>({ status: "loading" });

  useEffect(() => {
    let active = true;
    setState({ status: "loading" });
    loadRef(refItem)
      .then((next) => {
        if (active) setState(next);
      })
      .catch((e: unknown) => {
        if (!active) return;
        const status = (e as { status?: number })?.status;
        setState(
          status === 404
            ? {
                status: "missing",
                note: "this backend binary predates the endpoint this id lives on (version skew) — nothing was read.",
              }
            : { status: "error", note: String(e) },
        );
      });
    return () => {
      active = false;
    };
  }, [refItem]);

  if (state.status === "loading") {
    return (
      <div data-testid="channel-peek-loading">
        <SkeletonRows count={3} />
      </div>
    );
  }
  if (state.status === "missing") {
    return (
      <div data-testid="channel-peek-missing" className="chn-peek-value">
        <p style={{ margin: 0 }}>{state.note}</p>
        <p
          style={{
            margin: "var(--space-2) 0 0",
            fontSize: "var(--text-meta)",
            color: "var(--fg-muted)",
          }}
        >
          the id is rendered exactly as the apparatus wrote it into the
          transcript; nothing is inferred for it here.
        </p>
      </div>
    );
  }
  if (state.status === "error") {
    return (
      <div
        data-testid="channel-peek-error"
        style={{
          margin: 0,
          fontFamily: "var(--font-mono)",
          fontSize: "var(--text-meta)",
          color: "var(--status-bad)",
          whiteSpace: "pre-wrap",
        }}
      >
        {state.note}
      </div>
    );
  }

  return (
    <div data-testid="channel-peek-body">
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "var(--space-2)",
          fontSize: "var(--text-meta)",
          color: "var(--fg-muted)",
          fontFamily: "var(--font-mono)",
        }}
      >
        {refItem.kind === "cluster" && (
          <RungGlyph level={state.level} killed={state.killed} />
        )}
        <span>{refItem.id}</span>
        <span>·</span>
        <span>{refItem.kind}</span>
      </div>
      <p
        className="chn-peek-value"
        data-testid="channel-peek-headline"
        style={{ marginTop: "var(--space-2)" }}
      >
        {state.headline}
      </p>
      <dl style={{ margin: 0 }}>
        {state.lines.map((line) => (
          <div key={line.label}>
            <dt className="chn-peek-label">{line.label}</dt>
            <dd className="chn-peek-value" style={{ marginInlineStart: 0 }}>
              {line.value}
            </dd>
          </div>
        ))}
      </dl>
      <p style={{ margin: "var(--space-4) 0 0" }}>
        <Link
          to={state.to}
          data-testid="channel-peek-link"
          style={{ color: "var(--accent)", fontSize: "var(--text-ui)" }}
        >
          {state.toLabel} →
        </Link>
      </p>
    </div>
  );
}
