import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  DailyOpsError,
  getDailyOpsMessages,
  getDailyOpsSummary,
  postDailyOpsMessage,
  type DailyOpsIntent,
  type DailyOpsMessageRow,
} from "../api/dailyOps";
import { refreshPoll, usePolled } from "../api/pollhub";
import { ResearchOpsCard } from "./ResearchOpsCard";

const SUMMARY_KEY = "daily_ops_summary";
const MESSAGES_KEY = "daily_ops_messages";
const OWNER_KEY = "oracle-lab-owner-access-key";
const STATUS = new Set(["planned", "in_progress", "blocked", "done", "awaiting_owner"]);
const IMPROVEMENT_STATUS = new Set(["proposed", "implemented", "verified", "blocked"]);
const AGENT_STATUS = new Set(["online", "working", "idle", "waiting", "degraded", "offline", "unknown"]);
const MESSAGE_STATUS = new Set(["queued", "delivered", "acknowledged", "failed"]);

const record = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const bounded = (value: unknown, limit = 4096): value is string =>
  typeof value === "string" && value.length > 0 && value.length <= limit;
const timestamp = (value: unknown): value is string =>
  bounded(value, 64) && Number.isFinite(Date.parse(value));

type WorkItem = {
  id: string;
  title: string;
  detail: string;
  status: string;
  owner?: string;
  observedAt: string;
};

type Focus = {
  focusId: string;
  title: string;
  status: string;
  stage: string;
  nextAction: string;
  nextGate: { from: string; to: string; artifact: string; status: string; owner: string };
  blockers: string[];
  observedAt: string;
};

type AgentState = {
  label: string;
  status: string;
  detail: string;
  observedAt: string;
};

type Summary = {
  available: boolean;
  generatedAt: string;
  goals: WorkItem[];
  accomplishments: WorkItem[];
  improvements: WorkItem[];
  focus: Focus | null;
  agents: { oracle: AgentState; piClient: AgentState; nara: AgentState } | null;
  warnings: string[];
  authRequired: boolean;
  writeAvailable: boolean;
  currentPlanRevision: string | null;
};

function workItems(value: unknown, kind: "goal" | "accomplishment" | "improvement"): WorkItem[] {
  if (!Array.isArray(value)) return [];
  const allowed = kind === "goal" ? STATUS : kind === "improvement" ? IMPROVEMENT_STATUS : new Set(["complete"]);
  return value.slice(0, 16).flatMap((item): WorkItem[] => {
    if (!record(item) || !bounded(item.id, 200) || !bounded(item.title, 512) ||
        !bounded(item.detail, 4096) || !bounded(item.status, 40) || !allowed.has(item.status) ||
        !timestamp(item.observed_at)) return [];
    const owner = kind === "goal" && bounded(item.owner, 32) ? item.owner : undefined;
    return [{ id: item.id, title: item.title, detail: item.detail, status: item.status,
      owner, observedAt: item.observed_at }];
  });
}

function focus(value: unknown): Focus | null {
  if (!record(value) || !record(value.next_gate) || !bounded(value.focus_id, 200) ||
      !bounded(value.title, 512) || !bounded(value.status, 32) || !bounded(value.stage, 512) ||
      !bounded(value.next_action, 4096) || !timestamp(value.observed_at) ||
      !bounded(value.next_gate.from, 512) || !bounded(value.next_gate.to, 512) ||
      !bounded(value.next_gate.artifact, 512) || !bounded(value.next_gate.status, 32) ||
      !bounded(value.next_gate.owner, 512)) return null;
  return {
    focusId: value.focus_id,
    title: value.title,
    status: value.status,
    stage: value.stage,
    nextAction: value.next_action,
    nextGate: {
      from: value.next_gate.from,
      to: value.next_gate.to,
      artifact: value.next_gate.artifact,
      status: value.next_gate.status,
      owner: value.next_gate.owner,
    },
    blockers: Array.isArray(value.blockers)
      ? value.blockers.filter((item): item is string => bounded(item, 512)).slice(0, 16)
      : [],
    observedAt: value.observed_at,
  };
}

function agent(value: unknown): AgentState | null {
  if (!record(value) || !bounded(value.label, 512) || !bounded(value.status, 32) ||
      !AGENT_STATUS.has(value.status) || !bounded(value.detail, 4096) || !timestamp(value.observed_at)) return null;
  return { label: value.label, status: value.status, detail: value.detail, observedAt: value.observed_at };
}

export function admitDailyOpsSummary(value: unknown): Summary | null {
  if (!record(value) || value.schema_version !== "daily-ops-summary/v1" ||
      typeof value.available !== "boolean" || !timestamp(value.generated_at) ||
      !record(value.capabilities) || value.capabilities.auth_required !== true ||
      typeof value.capabilities.write_available !== "boolean" ||
      !Array.isArray(value.capabilities.targets) || !value.capabilities.targets.includes("oracle") ||
      !Array.isArray(value.capabilities.intents) || !value.capabilities.intents.includes("question") ||
      !value.capabilities.intents.includes("change_request")) return null;
  const agents = record(value.agents) ? {
    oracle: agent(value.agents.oracle),
    piClient: agent(value.agents.pi_client),
    nara: agent(value.agents.nara),
  } : null;
  const completeAgents = agents && agents.oracle && agents.piClient && agents.nara
    ? { oracle: agents.oracle, piClient: agents.piClient, nara: agents.nara }
    : null;
  return {
    available: value.available,
    generatedAt: value.generated_at,
    goals: workItems(value.goals, "goal"),
    accomplishments: workItems(value.accomplishments, "accomplishment"),
    improvements: workItems(value.improvements, "improvement"),
    focus: focus(value.research_focus),
    agents: completeAgents,
    warnings: Array.isArray(value.warnings)
      ? value.warnings.filter((item): item is string => bounded(item, 512)).slice(0, 16)
      : [],
    authRequired: true,
    writeAvailable: value.capabilities.write_available,
    currentPlanRevision: value.current_plan_revision === null || bounded(value.current_plan_revision, 200)
      ? value.current_plan_revision as string | null
      : null,
  };
}

function admitMessages(value: unknown): { available: boolean; writable: boolean; rows: DailyOpsMessageRow[] } | null {
  if (!record(value) || value.schema_version !== "daily-ops-messages/v1" ||
      typeof value.available !== "boolean" || typeof value.writable !== "boolean" || !Array.isArray(value.rows)) return null;
  const rows = value.rows.slice(0, 100).flatMap((item): DailyOpsMessageRow[] => {
    if (!record(item) || !bounded(item.request_id, 160) || !timestamp(item.created_at) ||
        !["owner", "oracle", "system"].includes(String(item.actor)) ||
        !["question", "change_request", "reply", "receipt"].includes(String(item.intent)) ||
        !MESSAGE_STATUS.has(String(item.status)) || !bounded(item.text, 4096) || item.target !== "oracle" ||
        !(item.plan_revision === null || bounded(item.plan_revision, 200))) return [];
    return [item as unknown as DailyOpsMessageRow];
  });
  return { available: value.available, writable: value.writable, rows };
}

function timeLabel(value: string): string {
  return new Date(value).toLocaleString("en-US", {
    timeZone: "UTC", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  }) + " UTC";
}

function phrase(value: string): string {
  return value.replaceAll("_", " ");
}

function shortRevision(value: string): string {
  return value.length > 18 ? `${value.slice(0, 12)}…${value.slice(-4)}` : value;
}

function preview(value: string, limit = 280): string {
  if (value.length <= limit) return value;
  const head = value.slice(0, limit).replace(/\s+\S*$/, "").trimEnd();
  return `${head || value.slice(0, limit)}…`;
}

export function makeRequestId(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, "0"));
  return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10).join("")}`;
}

function statusStyle(status: string): React.CSSProperties {
  if (["done", "complete", "verified", "online", "acknowledged"].includes(status))
    return { color: "var(--status-ok)", background: "var(--status-ok-bg)" };
  if (["blocked", "degraded", "failed", "awaiting_owner"].includes(status))
    return { color: "var(--status-warn)", background: "var(--status-warn-bg)" };
  if (["working", "in_progress", "delivered"].includes(status))
    return { color: "var(--status-info)", background: "var(--status-info-bg)" };
  return { color: "var(--status-idle)", background: "var(--status-idle-bg)" };
}

function Status({ value }: { value: string }) {
  return <span className="rounded-full px-2 py-0.5 text-[11px] font-medium" style={statusStyle(value)}>{phrase(value)}</span>;
}

function ItemRows({ items }: { items: WorkItem[] }) {
  return <>{items.map(item => <li key={item.id} className="border-l-2 border-[var(--border-2)] pl-3">
      <div className="flex flex-wrap items-center gap-2"><span className="font-medium">{item.title}</span><Status value={item.status} /></div>
      <p className="mt-1 text-sm text-[var(--fg-muted)]">{preview(item.detail)}</p>
      {item.detail.length > 280 && <details className="mt-1 text-xs text-[var(--fg-muted)]">
        <summary className="cursor-pointer text-[var(--accent)]">Full recorded detail</summary>
        <p className="mt-1 whitespace-pre-wrap">{item.detail}</p>
      </details>}
      <p className="mt-1 text-xs text-[var(--fg-muted)]">{item.owner ? `${phrase(item.owner)} · ` : ""}{timeLabel(item.observedAt)}</p>
    </li>)}</>;
}

function ItemList({ items, empty }: { items: WorkItem[]; empty: string }) {
  if (items.length === 0) return <p className="mt-2 text-sm text-[var(--fg-muted)]">{empty}</p>;
  const visible = items.slice(0, 4);
  const remaining = items.slice(4);
  return <>
    <ul className="mt-2 space-y-3"><ItemRows items={visible} /></ul>
    {remaining.length > 0 && <details className="mt-3 rounded border border-[var(--border-1)] p-3">
      <summary className="cursor-pointer text-sm text-[var(--accent)]">Show {remaining.length} more recorded item{remaining.length === 1 ? "" : "s"}</summary>
      <ul className="mt-3 space-y-3"><ItemRows items={remaining} /></ul>
    </details>}
  </>;
}

function AgentStrip({ agents }: { agents: NonNullable<Summary["agents"]> }) {
  return <div className="grid gap-2 sm:grid-cols-3" data-testid="daily-ops-agents">
    {([
      ["oracle", agents.oracle, "Steward"],
      ["pi", agents.piClient, "Oracle client"],
      ["nara", agents.nara, "Observed runner"],
    ] as const).map(([key, state, role]) => <div key={key} className="rounded border border-[var(--border-1)] p-3">
      <div className="flex flex-wrap items-center gap-2"><span className="font-semibold">{state.label}</span><Status value={state.status} /></div>
      <p className="mt-1 text-xs uppercase tracking-wide text-[var(--fg-muted)]">{role}</p>
      <p className="mt-2 text-sm text-[var(--fg-muted)]">{preview(state.detail, 240)}</p>
      {state.detail.length > 240 && <details className="mt-1 text-xs text-[var(--fg-muted)]">
        <summary className="cursor-pointer text-[var(--accent)]">Full recorded detail</summary>
        <p className="mt-1 whitespace-pre-wrap">{state.detail}</p>
      </details>}
      <p className="mt-1 text-xs text-[var(--fg-muted)]">Observed {timeLabel(state.observedAt)}</p>
    </div>)}
  </div>;
}

function MessageRows({ rows }: { rows: DailyOpsMessageRow[] }) {
  return <>{rows.map(row => <li key={`${row.request_id}:${row.created_at}:${row.actor}`} className="rounded border border-[var(--border-1)] bg-[var(--surface-1)] p-3">
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <span className="font-semibold">{row.actor === "owner" ? "Owner" : row.actor === "oracle" ? "Oracle" : "System"}</span>
      <span className="text-[var(--fg-muted)]">{phrase(row.intent)}</span>
      <Status value={row.status} />
      <time className="ml-auto text-[var(--fg-muted)]">{timeLabel(row.created_at)}</time>
    </div>
    <p className="mt-2 whitespace-pre-wrap text-sm">{row.text}</p>
    {row.plan_revision && <p className="mt-1 font-mono text-xs text-[var(--fg-muted)]">plan {shortRevision(row.plan_revision)}</p>}
  </li>)}</>;
}

type SubmitState =
  | { kind: "idle" }
  | { kind: "submitting" }
  | { kind: "queued"; requestId: string; revision: string | null; duplicate: boolean }
  | { kind: "failed"; message: string };

type RetryableRequest = {
  fingerprint: string;
  requestId: string;
};

export function DailyOpsPanel({ legacyResearchOps, legacyFailing = false }: {
  legacyResearchOps: unknown;
  legacyFailing?: boolean;
}) {
  const [accessKey, setAccessKey] = useState(() =>
    typeof sessionStorage === "undefined" ? "" : sessionStorage.getItem(OWNER_KEY) ?? "");
  const summaryPoll = usePolled(SUMMARY_KEY, getDailyOpsSummary, { intervalMs: 60_000 });
  const messagesPoll = usePolled(MESSAGES_KEY, () => getDailyOpsMessages(accessKey), {
    intervalMs: 15_000,
    enabled: accessKey.length > 0,
  });
  const summary = admitDailyOpsSummary(summaryPoll.data);
  const messages = admitMessages(messagesPoll.data);
  const [intent, setIntent] = useState<DailyOpsIntent>("question");
  const [text, setText] = useState("");
  const [keyDraft, setKeyDraft] = useState(accessKey);
  const [submit, setSubmit] = useState<SubmitState>({ kind: "idle" });
  const [retryableRequest, setRetryableRequest] = useState<RetryableRequest | null>(null);

  useEffect(() => {
    if (accessKey && messagesPoll.error instanceof DailyOpsError &&
        [401, 403].includes(messagesPoll.error.status)) {
      sessionStorage.removeItem(OWNER_KEY);
      setAccessKey("");
      setKeyDraft("");
      setRetryableRequest(null);
      setSubmit({ kind: "failed", message: "Owner access key rejected. Message history remains locked and no request was queued." });
    }
  }, [accessKey, messagesPoll.error]);

  const sortedRows = useMemo(() => messages?.rows
    .slice()
    .sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at)) ?? [], [messages]);
  const recentRows = sortedRows.slice(-5);
  const earlierRows = sortedRows.slice(0, -5);
  const routerConfigured = summary?.writeAvailable === true;
  const writeAvailable = routerConfigured && accessKey.length > 0 && messages?.writable === true;
  const oracleReady = summary?.agents != null &&
    !["offline", "degraded", "unknown"].includes(summary.agents.oracle.status);
  const changeBound = intent !== "change_request" || Boolean(summary?.currentPlanRevision);
  const canSubmit = writeAvailable && accessKey.length > 0 && text.trim().length > 0 &&
    text.trim().length <= 4096 && changeBound && oracleReady && submit.kind !== "submitting";

  function saveAccessKey() {
    const next = keyDraft.trim();
    if (typeof sessionStorage !== "undefined") {
      if (next) sessionStorage.setItem(OWNER_KEY, next);
      else sessionStorage.removeItem(OWNER_KEY);
    }
    setAccessKey(next);
    setSubmit({ kind: "idle" });
    if (next) refreshPoll(MESSAGES_KEY);
  }

  function askAboutNara() {
    setIntent("question");
    setText("What is Nara currently working on, what is blocking it, and what should change next?");
    setSubmit({ kind: "idle" });
  }

  async function send(event: React.FormEvent) {
    event.preventDefault();
    if (!canSubmit || !summary) return;
    const normalizedText = text.trim();
    const revision = intent === "change_request" ? summary.currentPlanRevision : null;
    const fingerprint = JSON.stringify([intent, normalizedText, revision]);
    const requestId = retryableRequest?.fingerprint === fingerprint
      ? retryableRequest.requestId
      : makeRequestId();
    setSubmit({ kind: "submitting" });
    try {
      const receipt = await postDailyOpsMessage({
        accessKey,
        requestId,
        intent,
        text: normalizedText,
        ...(revision
          ? { expectedPlanRevision: revision }
          : {}),
      });
      setRetryableRequest(null);
      setSubmit({ kind: "queued", requestId: receipt.request_id,
        revision: receipt.expected_plan_revision, duplicate: receipt.duplicate });
      setText("");
      refreshPoll(MESSAGES_KEY);
      refreshPoll(SUMMARY_KEY);
    } catch (error) {
      const detail = error instanceof DailyOpsError ? error.detail : String(error);
      const deliveryUnconfirmed = !(error instanceof DailyOpsError) || error.status >= 500;
      if (deliveryUnconfirmed) {
        setRetryableRequest({ fingerprint, requestId });
        setSubmit({ kind: "failed", message: `Delivery unconfirmed; retry safely with the same request ID. ${detail}` });
      } else {
        setRetryableRequest(null);
        setSubmit({ kind: "failed", message: `Oracle router rejected the request: ${detail}` });
      }
    }
  }

  if (!summary || !summary.available) {
    return <div className="mb-4" data-testid="daily-ops-fallback">
      <div className="mb-3 rounded-lg border border-[var(--border-1)] bg-[var(--surface-1)] p-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-[var(--fg-muted)]">Daily lab brief</p>
        <h2 className="mt-1 text-lg font-semibold">Daily synthesis unavailable</h2>
        <p className="mt-2 text-sm text-[var(--fg-muted)]">
          {summaryPoll.error ? "The current brief could not be read. Existing research operations remain visible below." : "Waiting for the first source-bound daily snapshot. Existing research operations remain visible below."}
        </p>
      </div>
      <ResearchOpsCard data={legacyResearchOps} failing={legacyFailing} />
    </div>;
  }

  return <section data-testid="daily-ops-panel" aria-labelledby="daily-ops-heading"
    className="mb-4 rounded-lg border border-[var(--group-research)] bg-[var(--surface-1)] p-4">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-[var(--group-research)]">Daily lab brief</p>
        <h2 id="daily-ops-heading" className="mt-1 text-xl font-semibold">Today&apos;s research path</h2>
        <p className="mt-1 text-sm text-[var(--fg-muted)]">One source-bound view of intent, progress, stewardship, and owner requests.</p>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <a href="#daily-oracle" className="text-sm text-[var(--accent)]">Ask or change the plan ↓</a>
        <span className="rounded border border-[var(--border-2)] px-2 py-1 text-xs text-[var(--fg-muted)]">Snapshot {timeLabel(summary.generatedAt)}</span>
      </div>
    </div>

    {summary.warnings.length > 0 && <div role="status" className="mt-4 rounded border border-[var(--status-warn)] bg-[var(--status-warn-bg)] p-3 text-sm">
      {summary.warnings.map(warning => <p key={warning}>{warning}</p>)}
    </div>}

    <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]">
      <section aria-labelledby="daily-goals-heading" className="rounded border border-[var(--border-1)] p-4">
        <h3 id="daily-goals-heading" className="text-base font-semibold">Goals for today</h3>
        <ItemList items={summary.goals} empty="No daily goals are recorded in this snapshot." />
      </section>
      <section aria-labelledby="daily-focus-heading" className="rounded border border-[var(--group-research)] p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 id="daily-focus-heading" className="text-base font-semibold">Main research thesis</h3>
          {summary.focus && <Status value={summary.focus.status} />}
        </div>
        {summary.focus ? <>
          <p className="mt-2 text-lg font-semibold leading-snug">{summary.focus.title}</p>
          <p className="mt-1 text-xs uppercase tracking-wide text-[var(--fg-muted)]">{phrase(summary.focus.stage)}</p>
          <div className="mt-3 rounded bg-[var(--surface-2)] p-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-[var(--fg-muted)]">Next gate</p>
            <p className="mt-1 font-medium">{phrase(summary.focus.nextGate.from)} → {phrase(summary.focus.nextGate.to)}</p>
            <p className="mt-1 text-sm">{summary.focus.nextGate.artifact}</p>
            <p className="mt-1 text-xs text-[var(--fg-muted)]">{summary.focus.nextGate.owner} · {phrase(summary.focus.nextGate.status)}</p>
          </div>
          <p className="mt-3 text-sm"><span className="font-semibold">Next:</span> {preview(summary.focus.nextAction, 360)}</p>
          {summary.focus.nextAction.length > 360 && <details className="mt-1 text-xs text-[var(--fg-muted)]"><summary className="cursor-pointer text-[var(--accent)]">Full next action</summary><p className="mt-1 whitespace-pre-wrap">{summary.focus.nextAction}</p></details>}
          {summary.focus.blockers.length > 0 && <details className="mt-2 text-xs text-[var(--status-warn)]">
            <summary className="cursor-pointer">{summary.focus.blockers.length} recorded blocker{summary.focus.blockers.length === 1 ? "" : "s"} · {preview(summary.focus.blockers[0], 180)}</summary>
            <ul className="mt-1 list-disc space-y-1 pl-5">{summary.focus.blockers.map(blocker => <li key={blocker}>{blocker}</li>)}</ul>
          </details>}
        </> : <p className="mt-2 text-sm text-[var(--fg-muted)]">No source-bound main thesis is available.</p>}
        <div className="mt-3 flex flex-wrap gap-4 text-sm">
          <Link to="/ladder?research_scope=active" className="text-[var(--accent)]">Open thesis workspace →</Link>
          <Link to="/cycles" className="text-[var(--accent)]">Trace coordinator work →</Link>
        </div>
      </section>
    </div>

    <div className="mt-4 grid gap-4 md:grid-cols-2">
      <section aria-labelledby="daily-accomplishments-heading" className="rounded border border-[var(--border-1)] p-4">
        <h3 id="daily-accomplishments-heading" className="text-base font-semibold">Recently accomplished</h3>
        <ItemList items={summary.accomplishments} empty="No recent accomplishment is recorded in this snapshot." />
      </section>
      <section aria-labelledby="daily-improvements-heading" className="rounded border border-[var(--border-1)] p-4">
        <h3 id="daily-improvements-heading" className="text-base font-semibold">System improvements</h3>
        <ItemList items={summary.improvements} empty="No recent system improvement is recorded in this snapshot." />
      </section>
    </div>

    <section aria-labelledby="daily-stewards-heading" className="mt-4">
      <div className="mb-2 flex flex-wrap items-end justify-between gap-2">
        <div><h3 id="daily-stewards-heading" className="text-base font-semibold">Lab stewardship</h3>
          <p className="mt-1 text-sm text-[var(--fg-muted)]">Oracle is the owner-facing steward. Pi is its client; Nara is observed through Oracle.</p></div>
        <button type="button" onClick={askAboutNara} className="rounded border border-[var(--border-2)] px-3 py-2 text-sm text-[var(--accent)]">Ask Oracle about Nara</button>
      </div>
      {summary.agents ? <AgentStrip agents={summary.agents} /> :
        <p className="rounded border border-[var(--border-1)] p-3 text-sm text-[var(--fg-muted)]">Agent observations are unavailable.</p>}
    </section>

    <section id="daily-oracle" aria-labelledby="daily-owner-heading" className="mt-4 scroll-mt-20 rounded border border-[var(--border-1)] bg-[var(--surface-2)] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><h3 id="daily-owner-heading" className="text-base font-semibold">Ask Oracle or request an agenda change</h3>
          <p className="mt-1 text-sm text-[var(--fg-muted)]">Requests enter the Oracle mailbox. A queued request is not approval, execution, or a scientific verdict.</p></div>
        <Link to="/channel" className="text-sm text-[var(--accent)]">Lab event channel (separate) →</Link>
      </div>

      {routerConfigured && <div className="mt-4">
        <label htmlFor="daily-owner-key" className="block text-xs font-semibold uppercase tracking-wide text-[var(--fg-muted)]">Owner access key · kept in this tab only</label>
        <div className="mt-1 flex flex-col gap-2 sm:flex-row">
          <input id="daily-owner-key" type="password" autoComplete="off" value={keyDraft}
            onChange={event => setKeyDraft(event.target.value)} placeholder="Enter owner access key"
            className="min-w-0 flex-1 rounded border border-[var(--border-2)] bg-[var(--surface-1)] px-3 py-2 text-sm" />
          <button type="button" onClick={saveAccessKey} className="rounded border border-[var(--border-2)] px-3 py-2 text-sm text-[var(--accent)]">
            {accessKey ? "Update key" : "Unlock for this tab"}
          </button>
        </div>
        <p className="mt-1 text-xs text-[var(--fg-muted)]">The key is sent only in the Authorization header. It is not placed in the URL, timeline, or request text.</p>
        <details className="mt-2 text-xs text-[var(--fg-muted)]">
          <summary className="cursor-pointer text-[var(--accent)]">Where to get the local owner key</summary>
          <p className="mt-1">On the Spark host, read the local credential:</p>
          <code className="mt-1 inline-block rounded bg-[var(--surface-1)] px-2 py-1">cat ~/.local/state/oracle-lab-ui/owner.key</code>
        </details>
      </div>}

      {submit.kind === "failed" && <p aria-live="polite" className="mt-3 text-sm text-[var(--status-bad)]">{submit.message}</p>}
      {routerConfigured && !accessKey && <p className="mt-3 rounded border border-[var(--border-2)] p-3 text-sm text-[var(--fg-muted)]" data-testid="daily-ops-locked">
        Owner message history and the composer remain locked until this tab has a valid key.
      </p>}
      {routerConfigured && accessKey && messages === null && messagesPoll.error == null && <p className="mt-3 text-sm text-[var(--fg-muted)]">Checking owner access and loading the bounded message history…</p>}

      {accessKey && recentRows.length > 0 && <ol className="mt-4 space-y-2" aria-label="Recent Oracle requests and replies"><MessageRows rows={recentRows} /></ol>}
      {accessKey && earlierRows.length > 0 && <details className="mt-3 rounded border border-[var(--border-1)] bg-[var(--surface-1)] p-3">
        <summary className="cursor-pointer text-sm text-[var(--accent)]">Show {earlierRows.length} earlier mailbox event{earlierRows.length === 1 ? "" : "s"} ({sortedRows.length} fetched)</summary>
        <ol className="mt-3 space-y-2" aria-label="Earlier Oracle requests and replies"><MessageRows rows={earlierRows} /></ol>
      </details>}
      {accessKey && messages?.available === true && recentRows.length === 0 && <p className="mt-3 text-sm text-[var(--fg-muted)]">No owner-to-Oracle requests are recorded yet.</p>}
      {accessKey && messagesPoll.error != null && !(messagesPoll.error instanceof DailyOpsError && [401, 403].includes(messagesPoll.error.status)) &&
        <p role="status" className="mt-3 text-sm text-[var(--status-warn)]">Recent request status could not be refreshed; no delivery state was inferred.</p>}

      {!routerConfigured ? <div className="mt-4 rounded border border-[var(--border-2)] p-3 text-sm text-[var(--fg-muted)]" data-testid="daily-ops-readonly">
        Owner requests are read-only because the authenticated Oracle router is not available. Existing messages remain visible.
      </div> : writeAvailable ? <form onSubmit={send} className="mt-4" data-testid="daily-ops-composer">
        <fieldset>
          <legend className="text-xs font-semibold uppercase tracking-wide text-[var(--fg-muted)]">Request type</legend>
          <div className="mt-2 flex flex-wrap gap-2">
            {(["question", "change_request"] as const).map(value => <button key={value} type="button" aria-pressed={intent === value}
              onClick={() => { setIntent(value); setSubmit({ kind: "idle" }); }}
              className={`rounded-full border px-3 py-1.5 text-sm ${intent === value ? "border-[var(--accent)] bg-[var(--accent-muted)] text-[var(--accent)]" : "border-[var(--border-1)] text-[var(--fg-muted)]"}`}>
              {value === "question" ? "Ask a question" : "Request a plan change"}
            </button>)}
          </div>
        </fieldset>

        <label htmlFor="daily-owner-message" className="mt-4 block text-xs font-semibold uppercase tracking-wide text-[var(--fg-muted)]">Message to Oracle</label>
        <textarea id="daily-owner-message" value={text} onChange={event => { setText(event.target.value); setSubmit({ kind: "idle" }); }} rows={4} maxLength={4096}
          placeholder={intent === "question" ? "Ask about the thesis, Nara, a blocker, or the next validation step…" : "Describe the agenda change you want Oracle to review…"}
          className="mt-1 w-full rounded border border-[var(--border-2)] bg-[var(--surface-1)] px-3 py-2 text-sm" />
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <button type="submit" disabled={!canSubmit}
            className="rounded bg-[var(--accent)] px-4 py-2 text-sm font-medium text-[var(--accent-fg)] disabled:cursor-not-allowed disabled:opacity-50">
            {submit.kind === "submitting" ? "Queueing…" : "Queue for Oracle"}
          </button>
          {intent === "change_request" && <span className={`text-xs ${summary.currentPlanRevision ? "text-[var(--fg-muted)]" : "text-[var(--status-warn)]"}`}>
            {summary.currentPlanRevision ? `Bound to plan ${shortRevision(summary.currentPlanRevision)}` : "No current plan revision is available; change requests stay disabled."}
          </span>}
        </div>
        {!oracleReady && <p role="status" className="mt-2 text-sm text-[var(--status-warn)]">
          Oracle is unavailable; your draft is kept here. Sending resumes after a healthy mailbox observation.
        </p>}
        <div aria-live="polite" className="mt-2 min-h-5 text-sm">
          {submit.kind === "queued" && <p className="text-[var(--status-info)]">{submit.duplicate ? "Existing request found" : "Request queued"} · {submit.requestId}{submit.revision ? ` · plan ${shortRevision(submit.revision)}` : ""}. No acknowledgment or execution is implied.</p>}
        </div>
      </form> : null}
    </section>

    <details className="mt-4 rounded border border-[var(--border-1)] p-3">
      <summary className="cursor-pointer text-sm font-medium text-[var(--accent)]">Full research operations and diagnostic detail</summary>
      <div className="mt-3"><ResearchOpsCard data={legacyResearchOps} failing={legacyFailing} showFocus={false} /></div>
    </details>
  </section>;
}

export default DailyOpsPanel;
