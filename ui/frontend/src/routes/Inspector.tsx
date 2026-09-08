import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import ChainTree from "../components/ChainTree";
import { getChainByRequest } from "../api/http";
import type { ChainNode, ChainResponse } from "../types/schemas";
import "./traces.css";

interface ErrorInfo {
  status: number | null;
  detail: string;
}

function errorInfo(value: unknown): ErrorInfo {
  if (value && typeof value === "object") {
    const candidate = value as { status?: unknown; detail?: unknown; message?: unknown };
    return {
      status: typeof candidate.status === "number" ? candidate.status : null,
      detail:
        typeof candidate.detail === "string"
          ? candidate.detail
          : typeof candidate.message === "string"
            ? candidate.message
            : "No diagnostic detail was supplied.",
    };
  }
  return { status: null, detail: typeof value === "string" ? value : "No diagnostic detail was supplied." };
}

function isChainResponse(value: unknown): value is ChainResponse {
  return value !== null && typeof value === "object" && typeof (value as { found?: unknown }).found === "boolean";
}

function childrenOf(node: ChainNode): ChainNode[] {
  return Array.isArray(node.children)
    ? node.children.filter((child): child is ChainNode => child !== null && typeof child === "object")
    : [];
}

function flatten(node: ChainNode | null): ChainNode[] {
  if (!node || typeof node !== "object") return [];
  return [node, ...childrenOf(node).flatMap(flatten)];
}

function rawRecord(node: ChainNode): Record<string, unknown> {
  return node.raw !== null && typeof node.raw === "object" && !Array.isArray(node.raw) ? node.raw : {};
}

function safeReturn(value: unknown): string | null {
  if (typeof value !== "string") return null;
  return /^\/(graph|cycles)(\?|$)/.test(value) ? value : null;
}

function shortId(value: string): string {
  return value.length > 22 ? `${value.slice(0, 10)}…${value.slice(-8)}` : value;
}

function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export default function Inspector() {
  const { requestId } = useParams<{ requestId: string }>();
  const rootedAt = requestId ?? "";
  const location = useLocation();
  const navigate = useNavigate();
  const routeState = location.state as { returnTo?: unknown; focusNodeId?: unknown } | null;
  const returnTo = safeReturn(routeState?.returnTo) ?? "/graph";
  const returnLabel = returnTo.startsWith("/cycles") ? "Back to trace history" : "Back to recorded map";
  const [data, setData] = useState<ChainResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(Boolean(rootedAt));
  const [retry, setRetry] = useState(0);
  const [showRaw, setShowRaw] = useState(false);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");

  useEffect(() => {
    if (!rootedAt) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setData(null);
    setError(null);
    setLoading(true);
    getChainByRequest(rootedAt)
      .then((response) => {
        if (cancelled) return;
        if (!isChainResponse(response)) {
          setError(new Error("The Inspector response was not a readable chain record."));
          return;
        }
        setData(response);
      })
      .catch((reason) => {
        if (!cancelled) setError(reason);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [retry, rootedAt]);

  const rawLines = useMemo(
    () =>
      data?.root
        ? flatten(data.root)
            .filter((node) => !node.embedded)
            .map((node) => JSON.stringify(rawRecord(node)))
        : [],
    [data],
  );

  const goBack = () => {
    navigate(returnTo, {
      state: typeof routeState?.focusNodeId === "string" ? { focusNodeId: routeState.focusNodeId } : undefined,
    });
  };

  const copy = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setCopyState("copied");
    } catch {
      setCopyState("failed");
    }
  };

  const toolbar = (
    <div className="trace-inspector-actions">
      <button type="button" className="trace-action-button" onClick={goBack}>{returnLabel}</button>
      {rootedAt && (
        <button type="button" className="trace-action-button" onClick={() => copy(rootedAt)}>
          Copy exact request ID
        </button>
      )}
      {copyState !== "idle" && <span role="status">{copyState === "copied" ? "Request ID copied" : "Copy unavailable"}</span>}
    </div>
  );

  if (!rootedAt) {
    return (
      <main className="trace-page" data-testid="inspector-page">
        <header className="trace-page-header"><div><p className="trace-kicker">Operations · exact request</p><h1>Request record</h1></div></header>
        <section className="trace-inspector-surface trace-inspector-state" data-state="malformed">
          <h2>No request ID in this route</h2>
          <p>Open a supplied request from the recorded map or call stream.</p>
          {toolbar}
        </section>
      </main>
    );
  }

  const info = error ? errorInfo(error) : null;
  const noIndexedRecord = info?.status === 404 || data?.found === false;

  if (loading) {
    return (
      <main className="trace-page" data-testid="inspector-page">
        <header className="trace-page-header"><div><p className="trace-kicker">Operations · exact request</p><h1>Request record</h1><p title={rootedAt}>Looking up {shortId(rootedAt)} in the recorded call index.</p></div></header>
        <section className="trace-inspector-surface trace-inspector-state" data-testid="inspector-loading"><h2>Looking up indexed call…</h2><p>The selected ID is being checked once against the existing read-only endpoint.</p></section>
      </main>
    );
  }

  if (noIndexedRecord) {
    const diagnostic = info ?? { status: null, detail: "The response reported found=false." };
    return (
      <main className="trace-page" data-testid="inspector-page">
        <header className="trace-page-header"><div><p className="trace-kicker">Operations · exact request</p><h1>Request record</h1><p title={rootedAt}>{shortId(rootedAt)}</p></div></header>
        <section className="trace-inspector-surface trace-inspector-state" data-state="unindexed" data-testid="inspector-unindexed">
          <p className="trace-kicker">Lookup result</p>
          <h2>No indexed call record</h2>
          <p>This request ID did not resolve in the call index. That does not establish whether its dispatch or underlying run succeeded or failed.</p>
          {toolbar}
          <button type="button" className="trace-action-button" onClick={() => setRetry((value) => value + 1)}>Retry lookup</button>
          <details className="trace-source-disclosure">
            <summary>Exact lookup diagnostic</summary>
            <code>{diagnostic.status != null ? `${diagnostic.status} ` : ""}{diagnostic.detail}</code>
          </details>
        </section>
      </main>
    );
  }

  if (error) {
    return (
      <main className="trace-page" data-testid="inspector-page">
        <header className="trace-page-header"><div><p className="trace-kicker">Operations · exact request</p><h1>Request record</h1><p title={rootedAt}>{shortId(rootedAt)}</p></div></header>
        <section className="trace-inspector-surface trace-inspector-state" data-state="error" data-testid="inspector-error">
          <p className="trace-kicker">Lookup unavailable</p>
          <h2>Request inspector unavailable</h2>
          <p>The lookup failed before a chain result was established.</p>
          {toolbar}
          <button type="button" className="trace-action-button" onClick={() => setRetry((value) => value + 1)}>Retry lookup</button>
          <details className="trace-source-disclosure"><summary>Exact lookup diagnostic</summary><code>{info?.status != null ? `${info.status} ` : ""}{info?.detail}</code></details>
        </section>
      </main>
    );
  }

  if (!data || !data.root || typeof data.root !== "object") {
    return (
      <main className="trace-page" data-testid="inspector-page">
        <header className="trace-page-header"><div><p className="trace-kicker">Operations · exact request</p><h1>Request record</h1><p title={rootedAt}>{shortId(rootedAt)}</p></div></header>
        <section className="trace-inspector-surface trace-inspector-state" data-state="malformed" data-testid="inspector-malformed-response">
          <h2>Indexed response has no readable chain</h2>
          <p>The endpoint returned a result without a usable root record. It is not presented as an empty chain.</p>
          {toolbar}
        </section>
      </main>
    );
  }

  const rootLabel =
    (typeof data.root.task_type === "string" && data.root.task_type) ||
    (typeof data.root.caller_tag === "string" && data.root.caller_tag) ||
    "Recorded call chain";
  const nodeCount = finiteNumber(data.node_count);
  const latency = finiteNumber(data.total_latency_ms);
  const malformedTools = finiteNumber(data.malformed_tool_calls) ?? 0;
  const recordedAt = typeof data.root.timestamp === "string" && data.root.timestamp ? data.root.timestamp : "not reported";

  return (
    <main className="trace-page" data-testid="inspector-page">
      <header className="trace-page-header">
        <div>
          <p className="trace-kicker">Operations · exact request</p>
          <h1>Request record</h1>
          <p>{rootLabel} · recorded {recordedAt}</p>
        </div>
        {toolbar}
      </header>

      <section className="trace-inspector-summary" aria-label="Request summary">
        <div><span>Structure</span><strong>{nodeCount != null ? `${nodeCount} node${nodeCount === 1 ? "" : "s"}` : "Not reported"}</strong></div>
        <div><span>Summed call latency</span><strong>{latency != null ? `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(latency)} ms` : "Not reported"}</strong></div>
        <div><span>Provenance</span><strong>Wrapper-rooted call log</strong></div>
      </section>

      {malformedTools > 0 && (
        <div className="trace-notice" data-tone="error" data-testid="malformed-tool-banner">
          <strong>Malformed tool_calls recorded.</strong>
          <span>{malformedTools} node{malformedTools === 1 ? "" : "s"} carries a non-array payload. Raw bytes remain available.</span>
        </div>
      )}
      {data.malformed && (
        <div className="trace-notice" data-tone="warning" data-testid="malformed-chain-banner">
          A parent_request_id cycle was recorded. The walk stopped at that boundary.
        </div>
      )}

      <section className="trace-inspector-surface" aria-labelledby="chain-heading">
        <div className="trace-section-heading"><div><h2 id="chain-heading">Recorded parent tree</h2><p>Indentation follows stored parent links and is capped for narrow readability.</p></div></div>
        <ChainTree root={data.root} />
      </section>

      <details className="trace-raw-disclosure" open={showRaw} onToggle={(event) => setShowRaw(event.currentTarget.open)}>
        <summary>Raw JSONL and exact identifiers · {rawLines.length} line{rawLines.length === 1 ? "" : "s"}</summary>
        {showRaw && (
          <>
            <div className="trace-inspector-actions">
              <button type="button" className="trace-action-button" onClick={() => copy(rawLines.join("\n"))}>Copy raw JSONL</button>
            </div>
            <pre data-testid="inspector-raw-jsonl">{rawLines.join("\n")}</pre>
          </>
        )}
      </details>
    </main>
  );
}
