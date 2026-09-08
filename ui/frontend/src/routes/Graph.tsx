import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import ActivityGraph from "../components/ActivityGraph";
import { getActivityGraph } from "../api/activity";
import type { ActivityGraphResponse } from "../types/activity";
import "./traces.css";

type Detail = "overview" | "full";
const GRAPH_POLL_MS = 5000;

interface GraphProps {
  initialGraph?: ActivityGraphResponse;
}

function isGraphObject(value: unknown): value is ActivityGraphResponse {
  return value !== null && typeof value === "object";
}

export default function Graph({ initialGraph }: GraphProps) {
  const [params, setParams] = useSearchParams();
  const detail: Detail = params.get("view") === "full" ? "full" : "overview";
  const [graph, setGraph] = useState<ActivityGraphResponse | null>(initialGraph ?? null);
  const [error, setError] = useState<string | null>(null);
  const graphSignature = useRef("");
  const live = initialGraph === undefined;

  useEffect(() => {
    if (!live) return;
    let cancelled = false;
    graphSignature.current = "";
    const poll = () => {
      getActivityGraph(detail)
        .then((next) => {
          if (cancelled) return;
          if (!isGraphObject(next)) throw new Error("Graph response must be an object");
          const signature = JSON.stringify({
            available: next.available,
            detail: next.detail,
            nodes: next.nodes,
            edges: next.edges,
            generated_at: next.generated_at,
            truncated: next.truncated,
          });
          if (signature !== graphSignature.current) {
            graphSignature.current = signature;
            setGraph(next);
          }
          setError(null);
        })
        .catch((reason) => {
          if (!cancelled) setError(String(reason));
        });
    };
    poll();
    const id = setInterval(poll, GRAPH_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [detail, live]);

  const setDetail = (value: Detail) => {
    const next = new URLSearchParams(params);
    if (value === "overview") next.delete("view");
    else next.set("view", value);
    next.delete("node");
    setParams(next);
  };

  return (
    <main className="trace-page" data-testid="graph-page">
      <header className="trace-page-header">
        <div>
          <p className="trace-kicker">Operations · recorded execution</p>
          <h1>Recorded trace map</h1>
          <p>Inspect supplied execution relationships. Layout is for navigation, not a causal claim.</p>
        </div>
        <nav className="trace-view-switch" aria-label="Trace view">
          <Link to="/cycles">List</Link>
          <span aria-current="page">Map</span>
        </nav>
      </header>

      <section className="trace-map-surface" aria-labelledby="map-results-heading">
        <div className="trace-map-toolbar">
          <div>
            <h2 id="map-results-heading">Recent recorded tasks</h2>
            <p>Overview keeps one supplied task node. Full asks for recorded descendants.</p>
          </div>
          <DetailToggle value={detail} onChange={setDetail} />
        </div>

        <div className="trace-filters trace-map-filters" role="search">
          <label className="trace-search">
            <span>Search map records</span>
            <input
              type="search"
              value={params.get("q") ?? ""}
              onChange={(event) => {
                const next = new URLSearchParams(params);
                if (event.target.value) next.set("q", event.target.value);
                else next.delete("q");
                next.delete("node");
                setParams(next);
              }}
              placeholder="Label, kind, task or request ID"
            />
          </label>
          <label>
            <span>Status</span>
            <select
              aria-label="map status filter"
              value={params.get("status") ?? "all"}
              onChange={(event) => {
                const next = new URLSearchParams(params);
                if (event.target.value === "all") next.delete("status");
                else next.set("status", event.target.value);
                next.delete("node");
                setParams(next);
              }}
            >
              <option value="all">All recorded</option>
              <option value="active">Active</option>
              <option value="ok">OK</option>
              <option value="error">Error</option>
              <option value="unknown">Unknown</option>
            </select>
          </label>
        </div>

        {error && (
          <div className="trace-notice" data-tone="error" data-testid="graph-error">
            <strong>{graph ? "Map refresh failed" : "Recorded map unavailable"}</strong>
            {graph && <span>Showing the last loaded snapshot.</span>}
            <details>
              <summary>Read diagnostic</summary>
              <code>{error}</code>
            </details>
          </div>
        )}

        <div className="trace-map-results">
          {graph ? (
            <ActivityGraph data={graph} />
          ) : !error ? (
            <div className="trace-empty" data-testid="activity-graph-loading">Loading the recorded map…</div>
          ) : null}
        </div>
      </section>
    </main>
  );
}

function DetailToggle({ value, onChange }: { value: Detail; onChange: (detail: Detail) => void }) {
  return (
    <div className="trace-detail-toggle" data-testid="detail-toggle" aria-label="Map detail">
      <button type="button" aria-pressed={value === "overview"} onClick={() => onChange("overview")}>
        Overview
      </button>
      <button type="button" aria-pressed={value === "full"} onClick={() => onChange("full")}>
        Full
      </button>
    </div>
  );
}
