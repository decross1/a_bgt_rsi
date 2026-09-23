import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  DailyOpsError,
  getDailyOpsMessages,
  getDailyOpsSummary,
  postDailyOpsDecision,
  postDailyOpsMessage,
  type DailyOpsDecisionAction,
  type DailyOpsIntent,
  type DailyOpsMessageRow,
} from "../api/dailyOps";
import { refreshPoll, usePolled } from "../api/pollhub";
import DailyDecisionCards, {
  type DailyDecisionRequest,
  type DailyWaitingItem,
  type DailyWorkCard,
  type WorkStatus,
} from "./DailyDecisionCards";
import { ResearchOpsCard } from "./ResearchOpsCard";

const SUMMARY_KEY = "daily_ops_summary";
const MESSAGES_KEY = "daily_ops_messages";
const OWNER_KEY = "oracle-lab-owner-access-key";
const AGENT_STATUS = new Set(["online", "active", "working", "idle", "waiting", "degraded", "stale", "failed", "offline", "unknown"]);
const MESSAGE_STATUS = new Set(["queued", "delivered", "acknowledged", "failed"]);
const WORK_STATUS = new Set<string>([
  "not_started", "awaiting_review", "held", "building", "validated", "failed", "withdrawn", "expired",
  "amend_requested", "accepted", "rejected", "merged", "waiting_on_you", "answered",
]);
const WORK_ACTION = new Set(["modify", "skip", "reprioritize"]);
const ACCOMPLISHMENT_KIND = new Set(["merged", "validated", "focus_closed", "day_closed"]);
/** A producer quiet this long is shown as idle since its last write, not as current. */
const QUIET_MS = 12 * 3600_000;

const record = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const bounded = (value: unknown, limit = 4096): value is string =>
  typeof value === "string" && value.length > 0 && value.length <= limit;
const timestamp = (value: unknown): value is string =>
  bounded(value, 64) && Number.isFinite(Date.parse(value));
const nullableText = (value: unknown, limit: number): string | null | undefined =>
  value === null || value === undefined ? null : bounded(value, limit) ? value : undefined;
const nullableTime = (value: unknown): string | null | undefined =>
  value === null || value === undefined ? null : timestamp(value) ? value : undefined;

type WorkItem = {
  id: string;
  title: string;
  detail: string;
  status: string;
  tags: string[];
  observedAt: string;
};

type PlanReview = {
  verdict: string | null;
  noteMsgId: string;
  reviewMsgId: string | null;
  reviewedAt: string | null;
  summary: string | null;
  shaMatches: boolean;
  acceptedItems: string[];
};

type DailyPlan = {
  id: string;
  date: string;
  revision: string;
  path: string;
  writtenAt: string;
  isCurrent: boolean;
  weekAlignment: string | null;
  bottlenecks: string[];
  review: PlanReview | null;
};

type Closure = {
  focusId: string | null;
  title: string | null;
  disposition: string | null;
  closedAt: string | null;
  reason: string | null;
};

type Focus = {
  status: "selected" | "none" | "source_invalid";
  focusId: string | null;
  title: string | null;
  stage: string | null;
  nextAction: string | null;
  intakePolicy: string | null;
  selectedAt: string | null;
  reason: string | null;
  lastClosure: Closure | null;
};

type AgentRelay = { status: string; detail: string; source: string };

type AgentState = {
  label: string;
  status: string;
  source: string;
  observedAt: string;
  role: string | null;
  activity: string | null;
  since: string | null;
  // Owner-message relay health (the oversight mailbox); gates the composer only.
  relay: AgentRelay;
};

type Sources = { plan: string | null; mailbox: string | null; focus: string | null; git: string | null };

type Summary = {
  available: boolean;
  generatedAt: string;
  plan: DailyPlan | null;
  focus: Focus;
  workCards: DailyWorkCard[];
  waiting: DailyWaitingItem[];
  accomplishments: WorkItem[];
  improvements: WorkItem[];
  agents: { oracle: AgentState; piClient: AgentState; nara: AgentState; metaOracle: AgentState | null } | null;
  warnings: string[];
  sources: Sources;
  writeAvailable: boolean;
  currentPlanRevision: string | null;
  decisionWriteAvailable: boolean;
};

function strings(value: unknown, limit: number, size: number): string[] | null {
  return Array.isArray(value) && value.length <= limit && value.every(item => bounded(item, size))
    ? value as string[] : null;
}

function planReview(value: unknown): PlanReview | null | undefined {
  if (value === null) return null;
  if (!record(value) || !bounded(value.note_msg_id, 80) || typeof value.sha_matches !== "boolean") return undefined;
  const verdict = nullableText(value.verdict, 16);
  const reviewMsgId = nullableText(value.review_msg_id, 80);
  const reviewedAt = nullableTime(value.reviewed_at);
  const summary = nullableText(value.summary, 400);
  const acceptedItems = strings(value.accepted_items, 16, 40);
  if (verdict === undefined || reviewMsgId === undefined || reviewedAt === undefined ||
      summary === undefined || acceptedItems === null) return undefined;
  return { verdict, noteMsgId: value.note_msg_id, reviewMsgId, reviewedAt, summary,
    shaMatches: value.sha_matches, acceptedItems };
}

function dailyPlan(value: unknown, revision: string | null): DailyPlan | null | undefined {
  if (value === null) return revision === null ? null : undefined;
  if (!record(value) || !bounded(value.id, 64) || value.id !== revision || !bounded(value.date, 10) ||
      !bounded(value.revision, 12) || !bounded(value.path, 200) || !timestamp(value.written_at) ||
      typeof value.is_current !== "boolean") return undefined;
  const weekAlignment = nullableText(value.week_alignment, 1200);
  const bottlenecks = strings(value.bottlenecks, 5, 400);
  const review = planReview(value.review);
  if (weekAlignment === undefined || bottlenecks === null || review === undefined) return undefined;
  return { id: value.id, date: value.date, revision: value.revision, path: value.path,
    writtenAt: value.written_at, isCurrent: value.is_current, weekAlignment, bottlenecks, review };
}

function focus(value: unknown): Focus | null {
  if (!record(value) || !["selected", "none", "source_invalid"].includes(String(value.status))) return null;
  const text = (key: string, limit = 1200) => nullableText(value[key], limit) ?? null;
  const closure = record(value.last_closure) ? {
    focusId: nullableText(value.last_closure.focus_id, 120) ?? null,
    title: nullableText(value.last_closure.title, 300) ?? null,
    disposition: nullableText(value.last_closure.disposition, 40) ?? null,
    closedAt: nullableTime(value.last_closure.closed_at) ?? null,
    reason: nullableText(value.last_closure.reason, 1200) ?? null,
  } : null;
  return {
    status: value.status as Focus["status"], focusId: text("focus_id"), title: text("title"),
    stage: text("stage"), nextAction: text("next_action"), intakePolicy: text("intake_policy"),
    selectedAt: nullableTime(value.selected_at) ?? null, reason: text("reason") ?? text("closure_error"),
    lastClosure: closure,
  };
}

function workCards(value: unknown, actions: DailyOpsDecisionAction[]): DailyWorkCard[] | null {
  if (!Array.isArray(value) || value.length > 12) return null;
  const cards: DailyWorkCard[] = [];
  for (const item of value) {
    if (!record(item) || !bounded(item.id, 40) || !bounded(item.title, 300) || !bounded(item.goal, 300) ||
        !bounded(item.owner, 300) || !bounded(item.lane, 300) || !bounded(item.repo, 300) ||
        !bounded(item.detail, 400) || !WORK_STATUS.has(String(item.status))) return null;
    const whyToday = nullableText(item.why_today, 1200);
    const acceptance = nullableText(item.acceptance, 1200);
    const evidenceMsgId = nullableText(item.evidence_msg_id, 80);
    const evidenceSha = nullableText(item.evidence_sha, 40);
    const evidenceAt = nullableTime(item.evidence_at);
    const dependsOn = strings(item.depends_on, 8, 40);
    if (whyToday === undefined || acceptance === undefined || evidenceMsgId === undefined ||
        evidenceSha === undefined || evidenceAt === undefined || dependsOn === null) return null;
    cards.push({ id: item.id, goal: item.goal, owner: item.owner, lane: item.lane, repo: item.repo,
      title: item.title, whyToday, acceptance, dependsOn, status: item.status as WorkStatus,
      detail: item.detail, evidenceMsgId, evidenceSha, evidenceAt, actions });
  }
  return cards;
}

function waiting(value: unknown): DailyWaitingItem[] {
  if (!Array.isArray(value)) return [];
  return value.slice(0, 16).flatMap((item): DailyWaitingItem[] => {
    if (!record(item) || !["question", "owner_decision"].includes(String(item.kind)) || !bounded(item.id, 120) ||
        !bounded(item.title, 300) || !bounded(item.asked_by, 60) || !bounded(item.cli, 600)) return [];
    const askedAt = nullableTime(item.asked_at);
    const msgId = nullableText(item.msg_id, 80);
    if (askedAt === undefined || msgId === undefined) return [];
    return [{ kind: item.kind as DailyWaitingItem["kind"], id: item.id, title: item.title,
      askedBy: item.asked_by, askedAt, msgId, cli: item.cli }];
  });
}

const ACCOMPLISHMENT_LABEL: Record<string, string> = {
  merged: "merged", validated: "validated", focus_closed: "focus closed", day_closed: "day closed",
};

function accomplishments(value: unknown): WorkItem[] {
  if (!Array.isArray(value)) return [];
  return value.slice(0, 16).flatMap((item): WorkItem[] =>
    record(item) && bounded(item.id, 120) && ACCOMPLISHMENT_KIND.has(String(item.kind)) &&
    bounded(item.title, 400) && timestamp(item.at) && bounded(item.evidence, 120)
      ? [{ id: item.id, title: item.title, detail: `Evidence: ${item.evidence}`,
        status: ACCOMPLISHMENT_LABEL[String(item.kind)], tags: [], observedAt: item.at }]
      : []);
}

function improvements(value: unknown): WorkItem[] {
  if (!Array.isArray(value)) return [];
  return value.slice(0, 40).flatMap((item): WorkItem[] => {
    const goals = record(item) ? strings(item.goals, 6, 12) : null;
    return record(item) && bounded(item.sha, 40) && timestamp(item.at) && bounded(item.subject, 240) && goals
      ? [{ id: item.sha, title: item.subject, detail: `main ${item.sha}`, status: "merged", tags: goals,
        observedAt: item.at }]
      : [];
  });
}

function agent(value: unknown): AgentState | null {
  if (!record(value) || !bounded(value.label, 512) || !bounded(value.status, 32) ||
      !AGENT_STATUS.has(value.status) || !timestamp(value.observed_at) || !bounded(value.source, 512)) return null;
  const role = nullableText(value.role, 512);
  const activity = nullableText(value.activity, 512);
  const since = nullableTime(value.since);
  const relay = value.relay;
  if (role === undefined || activity === undefined || since === undefined) return null;
  if (relay !== undefined && relay !== null && (!record(relay) || !bounded(relay.status, 32) ||
      !AGENT_STATUS.has(relay.status) || !bounded(relay.detail, 4096) || !bounded(relay.source, 512))) return null;
  const own = { status: value.status, detail: bounded(value.detail, 4096) ? value.detail : value.status, source: value.source };
  return { label: value.label, status: value.status, source: value.source, observedAt: value.observed_at,
    role, activity, since,
    relay: record(relay) ? { status: relay.status as string, detail: relay.detail as string, source: relay.source as string } : own };
}

export function admitDailyOpsSummary(value: unknown): Summary | null {
  if (!record(value) || value.schema_version !== "daily-ops-summary/v3" ||
      typeof value.available !== "boolean" || !timestamp(value.generated_at) ||
      !record(value.capabilities) || value.capabilities.auth_required !== true ||
      typeof value.capabilities.write_available !== "boolean" ||
      typeof value.capabilities.decision_write_available !== "boolean" ||
      !Array.isArray(value.capabilities.targets) || !value.capabilities.targets.includes("oracle") ||
      !Array.isArray(value.capabilities.intents) || !value.capabilities.intents.includes("question") ||
      !value.capabilities.intents.includes("change_request") || !record(value.sources)) return null;
  const currentPlanRevision = value.current_plan_revision === null || bounded(value.current_plan_revision, 64)
    ? value.current_plan_revision as string | null : undefined;
  if (currentPlanRevision === undefined) return null;
  const plan = dailyPlan(value.daily_plan, currentPlanRevision);
  const researchFocus = focus(value.research_focus);
  const actions = (Array.isArray(value.capabilities.decision_actions) ? value.capabilities.decision_actions : [])
    .filter((action): action is DailyOpsDecisionAction => typeof action === "string" && WORK_ACTION.has(action));
  const cards = workCards(value.work_items, actions);
  if (plan === undefined || researchFocus === null || cards === null) return null;
  const agents = record(value.agents) ? {
    oracle: agent(value.agents.oracle),
    piClient: agent(value.agents.pi_client),
    nara: agent(value.agents.nara),
    // Optional fourth card; an absent or invalid one hides only that card.
    metaOracle: agent(value.agents.meta_oracle),
  } : null;
  const source = (key: string) => nullableTime((value.sources as Record<string, unknown>)[key]) ?? null;
  return {
    available: value.available,
    generatedAt: value.generated_at,
    plan,
    focus: researchFocus,
    workCards: cards,
    waiting: waiting(value.waiting_on_you),
    accomplishments: accomplishments(value.accomplishments),
    improvements: improvements(value.improvements),
    agents: agents && agents.oracle && agents.piClient && agents.nara
      ? { oracle: agents.oracle, piClient: agents.piClient, nara: agents.nara, metaOracle: agents.metaOracle }
      : null,
    warnings: Array.isArray(value.warnings)
      ? value.warnings.filter((item): item is string => bounded(item, 512)).slice(0, 16)
      : [],
    sources: { plan: source("plan"), mailbox: source("mailbox"), focus: source("focus"), git: source("git") },
    writeAvailable: value.capabilities.write_available,
    currentPlanRevision,
    decisionWriteAvailable: value.capabilities.decision_write_available === true,
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
        !(item.plan_revision === null || bounded(item.plan_revision, 200)) ||
        !(item.responder_label === undefined || bounded(item.responder_label, 512))) return [];
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
  if (["done", "merged", "validated", "online", "active", "acknowledged", "accepted", "focus closed", "day closed"].includes(status))
    return { color: "var(--status-ok)", background: "var(--status-ok-bg)" };
  if (["blocked", "degraded", "failed", "stale", "amend", "reject", "invalid"].includes(status))
    return { color: "var(--status-warn)", background: "var(--status-warn-bg)" };
  if (["working", "delivered", "awaiting review"].includes(status))
    return { color: "var(--status-info)", background: "var(--status-info-bg)" };
  return { color: "var(--status-idle)", background: "var(--status-idle-bg)" };
}

function Status({ value }: { value: string }) {
  return <span className="rounded-full px-2 py-0.5 text-[11px] font-medium" style={statusStyle(value)}>{phrase(value)}</span>;
}

function ItemRows({ items }: { items: WorkItem[] }) {
  return <>{items.map(item => <li key={item.id} className="border-l-2 border-[var(--border-2)] pl-3">
      <div className="flex flex-wrap items-center gap-2"><span className="font-medium">{item.title}</span><Status value={item.status} />
        {item.tags.map(tag => <span key={tag} className="rounded bg-[var(--accent-muted)] px-1.5 py-0.5 font-mono text-[11px] font-semibold text-[var(--accent)]">{tag}</span>)}</div>
      <p className="mt-1 text-sm text-[var(--fg-muted)]">{preview(item.detail)}</p>
      {item.detail.length > 280 && <details className="mt-1 text-xs text-[var(--fg-muted)]">
        <summary className="cursor-pointer text-[var(--accent)]">Full recorded detail</summary>
        <p className="mt-1 whitespace-pre-wrap">{item.detail}</p>
      </details>}
      <p className="mt-1 text-xs text-[var(--fg-muted)]">{timeLabel(item.observedAt)}</p>
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

const OBSERVATION_STALE_MS = 2 * 60_000; // the bridge re-observes about every 30 s

function ago(value: string): string {
  const minutes = Math.max(0, Math.floor((Date.now() - Date.parse(value)) / 60_000));
  if (minutes < 1) return "just now";
  if (minutes < 120) return `${minutes} min ago`;
  return `${Math.floor(minutes / 60)} h ago`;
}

const SINCE_LABEL: Record<string, string> = {
  working: "working since", active: "active since", idle: "idle since",
  failed: "failed at", stale: "last seen", waiting: "waiting since", online: "since", offline: "offline since",
};

/** One "Now" line: what the agent runs right now, or since when it has been quiet. */
export function nowLine(state: { status: string; activity: string | null; since: string | null }): string {
  if (["working", "active"].includes(state.status)) return state.activity ?? phrase(state.status);
  const quiet = state.since ? `${SINCE_LABEL[state.status] ?? "since"} ${timeLabel(state.since)} (${ago(state.since)})`
    : phrase(state.status);
  return state.activity ? `${quiet} · ${state.activity}` : quiet;
}

/** Source age for a section; a quiet producer reads "idle since …", never as current. */
function SourceAge({ label, at }: { label: string; at: string | null }) {
  if (!at) return <p className="mt-1 text-xs text-[var(--fg-muted)]">Source: {label} · no record yet</p>;
  const quiet = Date.now() - Date.parse(at) > QUIET_MS;
  return <p className={`mt-1 text-xs ${quiet ? "text-[var(--status-warn)]" : "text-[var(--fg-muted)]"}`}>
    Source: {label} · {quiet ? `producer idle since ${timeLabel(at)}` : `updated ${ago(at)}`}</p>;
}

function AgentStrip({ agents }: { agents: NonNullable<Summary["agents"]> }) {
  const cards = [
    ["oracle", agents.oracle, "Steward"],
    ["pi", agents.piClient, "Oracle client"],
    ["nara", agents.nara, "Observed runner"],
    ...(agents.metaOracle ? [["meta", agents.metaOracle, "Reviewer"] as const] : []),
  ] as const;
  return <div className={`grid gap-2 sm:grid-cols-2 ${cards.length > 3 ? "xl:grid-cols-4" : "xl:grid-cols-3"}`}
    data-testid="daily-ops-agents">
    {cards.map(([key, state, role]) => {
      const stale = Date.now() - Date.parse(state.observedAt) > OBSERVATION_STALE_MS;
      return <div key={key} className="rounded border border-[var(--border-1)] p-3" data-testid={`daily-ops-agent-${key}`}>
      <div className="flex flex-wrap items-center gap-2"><span className="font-semibold">{state.label}</span><Status value={state.status} /></div>
      <p className="mt-1 text-xs uppercase tracking-wide text-[var(--fg-muted)]">{state.role ?? role}</p>
      <p className="mt-2 text-sm" data-testid={`daily-ops-agent-${key}-now`}><span className="font-medium">Now: </span>{nowLine(state)}</p>
      <p className={`mt-1 text-xs ${stale ? "text-[var(--status-warn)]" : "text-[var(--fg-muted)]"}`}>
        {stale ? "Stale: observed " : "Observed "}{ago(state.observedAt)}</p>
    </div>;
    })}
  </div>;
}

function MessageRows({ rows, defaultResponderLabel }: {
  rows: DailyOpsMessageRow[];
  defaultResponderLabel: string;
}) {
  return <>{rows.map(row => {
    const responderLabel = row.responder_label ?? defaultResponderLabel;
    const actorLabel = row.actor === "owner" ? "Owner" : row.actor === "oracle" ? responderLabel : "System";
    return <li key={`${row.request_id}:${row.created_at}:${row.actor}`} className="rounded border border-[var(--border-1)] bg-[var(--surface-1)] p-3">
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <span className="font-semibold">{actorLabel}</span>
      {row.actor === "owner" && <span className="text-[var(--fg-muted)]">to {responderLabel}</span>}
      {row.actor === "system" && <span className="text-[var(--fg-muted)]">for {responderLabel}</span>}
      <span className="text-[var(--fg-muted)]">{phrase(row.intent)}</span>
      <Status value={row.status} />
      <time className="ml-auto text-[var(--fg-muted)]">{timeLabel(row.created_at)}</time>
    </div>
    <p className="mt-2 whitespace-pre-wrap text-sm">{row.text}</p>
    {row.plan_revision && <p className="mt-1 font-mono text-xs text-[var(--fg-muted)]">plan {shortRevision(row.plan_revision)}</p>}
  </li>})}</>;
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

  const responderLabel = summary?.agents?.oracle.label ?? "Oracle";
  const clientLabel = summary?.agents?.piClient.label ?? "Pi client";
  const relay = summary?.agents?.oracle.relay;
  const boundedResponder = relay?.source === "Oracle bounded UI responder mailbox heartbeat";

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
  // Messaging readiness follows the owner relay, not the daily-loop activity card.
  const oracleReady = relay != null &&
    !["offline", "degraded", "unknown"].includes(relay.status) &&
    (!boundedResponder || relay.status === "idle");
  const changeBound = intent !== "change_request" || Boolean(summary?.currentPlanRevision);
  const canSubmit = writeAvailable && accessKey.length > 0 && text.trim().length > 0 &&
    text.trim().length <= 4096 && changeBound && oracleReady && submit.kind !== "submitting";
  const decisionRouteAvailable = summary?.decisionWriteAvailable === true &&
    Boolean(summary.currentPlanRevision) && oracleReady;
  // One accurate line for why per-item requests are unavailable.
  const readonlyReason = !summary?.currentPlanRevision
    ? "Change requests are unavailable: no plan of record is readable."
    : summary.decisionWriteAvailable !== true
      ? "Change requests are unavailable: no authenticated Oracle relay is configured for this backend."
      : `Change requests are unavailable: the Oracle Pi relay is ${relay ? phrase(relay.status) : "unobserved"}${relay ? ` (${relay.detail.replace(/\.$/, "")})` : ""}. Use the mailbox commands under Waiting on you.`;
  const decisionCanRequest = decisionRouteAvailable && accessKey.length > 0;
  const decisionBlockedReason = !accessKey
    ? "Unlock owner access below before sending a request."
    : !summary?.currentPlanRevision
      ? "No plan of record is available for a plan-bound request."
      : !summary.decisionWriteAvailable
        ? "The authenticated decision-request route is read-only."
        : !oracleReady
          ? `${responderLabel} is unavailable; requests remain unsent.`
          : null;

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

  function requireOwnerAccess() {
    const input = document.querySelector<HTMLInputElement>("#daily-owner-key");
    input?.scrollIntoView({ block: "center" });
    input?.focus();
  }

  async function requestDecision(request: DailyDecisionRequest) {
    if (!summary?.currentPlanRevision)
      throw new DailyOpsError(409, "no current plan revision is available");
    const receipt = await postDailyOpsDecision({
      accessKey,
      requestId: request.requestId,
      targetKind: request.targetKind,
      targetId: request.targetId,
      action: request.action,
      expectedPlanRevision: summary.currentPlanRevision,
      ...(request.note ? { note: request.note } : {}),
      ...(request.priority ? { priority: request.priority } : {}),
    });
    refreshPoll(SUMMARY_KEY);
    refreshPoll(MESSAGES_KEY);
    return receipt;
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
        <span className="rounded border border-[var(--border-2)] px-2 py-1 text-xs text-[var(--fg-muted)]" data-testid="daily-plan-badge">
          {summary.plan ? `Plan of record ${summary.plan.date} ${summary.plan.revision} · written ${timeLabel(summary.plan.writtenAt)}` : "No plan of record"}</span>
      </div>
    </div>

    {summary.warnings.length > 0 && <div role="status" className="mt-4 rounded border border-[var(--status-warn)] bg-[var(--status-warn-bg)] p-3 text-sm">
      {summary.warnings.map(warning => <p key={warning}>{warning}</p>)}
    </div>}

    <section aria-labelledby="daily-plan-heading" data-testid="daily-plan" className="mt-4 rounded border border-[var(--border-1)] p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id="daily-plan-heading" className="text-base font-semibold">{summary.plan ? `Today's plan · ${summary.plan.date} ${summary.plan.revision}` : "Today's plan"}</h3>
        {summary.plan && <Status value={summary.plan.review?.verdict ?? "awaiting review"} />}
      </div>
      {summary.plan ? <>
        {!summary.plan.isCurrent && <p role="status" data-testid="daily-plan-stale" className="mt-2 rounded border border-[var(--status-warn)] bg-[var(--status-warn-bg)] p-2 text-sm">
          The newest plan is for {summary.plan.date}; Oracle has not written a plan for today yet.</p>}
        {summary.plan.weekAlignment && <p className="mt-2 text-sm"><span className="font-semibold">Week alignment:</span> {preview(summary.plan.weekAlignment, 360)}</p>}
        {summary.plan.bottlenecks.length > 0 && <div className="mt-2 text-sm"><p className="font-semibold">Bottlenecks</p>
          <ul className="mt-1 list-disc space-y-1 pl-5">{summary.plan.bottlenecks.map(item => <li key={item}>{item}</li>)}</ul></div>}
        <p className="mt-2 text-sm" data-testid="daily-plan-review">{summary.plan.review
          ? summary.plan.review.verdict
            ? <>Meta-oracle review: <span className="font-semibold">{summary.plan.review.verdict}</span>{summary.plan.review.acceptedItems.length > 0 ? ` · accepted ${summary.plan.review.acceptedItems.join(", ")}` : ""} · {summary.plan.review.reviewMsgId}{summary.plan.review.shaMatches ? "" : " · reviewed a different file version"}</>
            : `PLAN READY ${summary.plan.review.noteMsgId} is awaiting the meta-oracle review.`
          : "No PLAN READY note names this plan file, so it has no meta-oracle review."}</p>
        {summary.plan.review?.summary && <details className="mt-1 text-xs text-[var(--fg-muted)]"><summary className="cursor-pointer text-[var(--accent)]">Review summary</summary><p className="mt-1">{summary.plan.review.summary}</p></details>}
      </> : <p className="mt-2 text-sm text-[var(--fg-muted)]">No readable plan under run_state/daily_plans/.</p>}
      <SourceAge label={summary.plan?.path ?? "run_state/daily_plans/"} at={summary.sources.plan} />
    </section>

    <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
      <div className="rounded border border-[var(--border-1)] p-4">
        <DailyDecisionCards cards={summary.workCards} waiting={summary.waiting}
          requestAvailable={decisionRouteAvailable} readonlyReason={readonlyReason}
          canRequest={decisionCanRequest} blockedReason={decisionBlockedReason}
          onRequireAccess={requireOwnerAccess} onRequest={requestDecision} />
        <SourceAge label="lab mailbox + git main" at={summary.sources.mailbox} />
      </div>
      <section aria-labelledby="daily-focus-heading" className="rounded border border-[var(--group-research)] p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 id="daily-focus-heading" className="text-base font-semibold">Research focus</h3>
          <Status value={summary.focus.status === "source_invalid" ? "invalid" : summary.focus.status === "none" ? "no focus" : "selected"} />
        </div>
        {summary.focus.status === "selected" ? <>
          <p className="mt-2 text-lg font-semibold leading-snug">{summary.focus.title}</p>
          {summary.focus.stage && <p className="mt-1 text-xs uppercase tracking-wide text-[var(--fg-muted)]">{phrase(summary.focus.stage)}</p>}
          {summary.focus.nextAction && <p className="mt-3 text-sm"><span className="font-semibold">Next:</span> {preview(summary.focus.nextAction, 360)}</p>}
          {summary.focus.intakePolicy && <p className="mt-2 text-sm"><span className="font-semibold">Intake:</span> {phrase(summary.focus.intakePolicy)}</p>}
        </> : summary.focus.status === "none" ? <>
          <p className="mt-2 text-lg font-semibold" data-testid="daily-focus-none">No active focus</p>
          <p className="mt-1 text-sm"><span className="font-semibold">New topics:</span> exploratory arXiv intake</p>
          {summary.focus.lastClosure && <div className="mt-3 rounded bg-[var(--surface-2)] p-3 text-sm" data-testid="daily-focus-closure">
            <p className="text-xs font-semibold uppercase tracking-wide text-[var(--fg-muted)]">Last closure</p>
            <p className="mt-1 font-medium">{summary.focus.lastClosure.disposition} · {summary.focus.lastClosure.title ?? summary.focus.lastClosure.focusId}</p>
            <p className="mt-1 text-xs text-[var(--fg-muted)]">{summary.focus.lastClosure.focusId}{summary.focus.lastClosure.closedAt ? ` · closed ${timeLabel(summary.focus.lastClosure.closedAt)}` : ""}</p>
            {summary.focus.lastClosure.reason && <p className="mt-1">{preview(summary.focus.lastClosure.reason, 240)}</p>}
          </div>}
        </> : <p className="mt-2 text-sm text-[var(--status-warn)]" data-testid="daily-focus-invalid">The research focus source is invalid: {summary.focus.reason ?? "unreadable"}. No focus is shown.</p>}
        <SourceAge label="orchestrator.research_focus" at={summary.sources.focus} />
        <div className="mt-3 flex flex-wrap gap-4 text-sm">
          <Link to="/ladder?research_scope=active" className="text-[var(--accent)]">Open thesis workspace →</Link>
          <Link to="/cycles" className="text-[var(--accent)]">Trace coordinator work →</Link>
        </div>
      </section>
    </div>

    <div className="mt-4 grid gap-4 md:grid-cols-2">
      <section aria-labelledby="daily-accomplishments-heading" className="rounded border border-[var(--border-1)] p-4">
        <h3 id="daily-accomplishments-heading" className="text-base font-semibold">Accomplished · last 7 days</h3>
        <ItemList items={summary.accomplishments} empty="Nothing merged, validated or closed in the last 7 days." />
        <SourceAge label="daily plans, lab mailbox, focus closures" at={summary.accomplishments[0]?.observedAt ?? summary.sources.mailbox} />
      </section>
      <section aria-labelledby="daily-improvements-heading" className="rounded border border-[var(--border-1)] p-4">
        <h3 id="daily-improvements-heading" className="text-base font-semibold">System improvements · merged to main, last 7 days</h3>
        <ItemList items={summary.improvements} empty="Nothing merged to main in the last 7 days." />
        <SourceAge label="git log --first-parent main" at={summary.sources.git} />
      </section>
    </div>

    <section aria-labelledby="daily-stewards-heading" className="mt-4">
      <div className="mb-2 flex flex-wrap items-end justify-between gap-2">
        <div><h3 id="daily-stewards-heading" className="text-base font-semibold">Lab stewardship</h3>
          <p className="mt-1 text-sm text-[var(--fg-muted)]">{boundedResponder
            ? `${responderLabel} is a temporary summary-only steward. ${clientLabel} carries its turns; Nara is observed through this surface.`
            : "Oracle is the owner-facing steward. Pi is its client; Nara is observed through Oracle."}</p></div>
        <button type="button" onClick={askAboutNara} className="rounded border border-[var(--border-2)] px-3 py-2 text-sm text-[var(--accent)]">Ask {responderLabel} about Nara</button>
      </div>
      {summary.agents ? <AgentStrip agents={summary.agents} /> :
        <p className="rounded border border-[var(--border-1)] p-3 text-sm text-[var(--fg-muted)]">Agent observations are unavailable.</p>}
    </section>

    <section id="daily-oracle" aria-labelledby="daily-owner-heading" className="mt-4 scroll-mt-20 rounded border border-[var(--border-1)] bg-[var(--surface-2)] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><h3 id="daily-owner-heading" className="text-base font-semibold">Ask {responderLabel} or request an agenda change</h3>
          <p className="mt-1 text-sm text-[var(--fg-muted)]">Requests enter the {responderLabel} mailbox. A queued request is not approval, execution, or a scientific verdict.</p>
          {relay && <p className="mt-1 text-xs text-[var(--fg-muted)]" data-testid="daily-ops-relay">Owner relay: {phrase(relay.status)} — {preview(relay.detail, 160)}</p>}</div>
        <Link to="/channel" className="text-sm text-[var(--accent)]">Lab event channel (separate) →</Link>
      </div>

      {boundedResponder && summary.agents && <div role="status" data-testid="daily-ops-bounded-responder"
        className="mt-4 rounded border border-[var(--status-warn)] bg-[var(--status-warn-bg)] p-3 text-sm">
        <p className="font-semibold">Temporary summary-only responder</p>
        <p className="mt-1">{summary.agents.oracle.relay.detail}</p>
      </div>}

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

      {accessKey && recentRows.length > 0 && <ol className="mt-4 space-y-2" aria-label="Recent Oracle requests and replies"><MessageRows rows={recentRows} defaultResponderLabel={responderLabel} /></ol>}
      {accessKey && earlierRows.length > 0 && <details className="mt-3 rounded border border-[var(--border-1)] bg-[var(--surface-1)] p-3">
        <summary className="cursor-pointer text-sm text-[var(--accent)]">Show {earlierRows.length} earlier mailbox event{earlierRows.length === 1 ? "" : "s"} ({sortedRows.length} fetched)</summary>
        <ol className="mt-3 space-y-2" aria-label="Earlier Oracle requests and replies"><MessageRows rows={earlierRows} defaultResponderLabel={responderLabel} /></ol>
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

        <label htmlFor="daily-owner-message" className="mt-4 block text-xs font-semibold uppercase tracking-wide text-[var(--fg-muted)]">Message to {responderLabel}</label>
        <textarea id="daily-owner-message" value={text} onChange={event => { setText(event.target.value); setSubmit({ kind: "idle" }); }} rows={4} maxLength={4096}
          placeholder={intent === "question" ? "Ask about the thesis, Nara, a blocker, or the next validation step…" : `Describe the agenda change you want ${responderLabel} to review…`}
          className="mt-1 w-full rounded border border-[var(--border-2)] bg-[var(--surface-1)] px-3 py-2 text-sm" />
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <button type="submit" disabled={!canSubmit}
            className="rounded bg-[var(--accent)] px-4 py-2 text-sm font-medium text-[var(--accent-fg)] disabled:cursor-not-allowed disabled:opacity-50">
            {submit.kind === "submitting" ? "Queueing…" : `Queue for ${responderLabel}`}
          </button>
          {intent === "change_request" && <span className={`text-xs ${summary.currentPlanRevision ? "text-[var(--fg-muted)]" : "text-[var(--status-warn)]"}`}>
            {summary.currentPlanRevision ? `Bound to plan ${shortRevision(summary.currentPlanRevision)}` : "No plan of record is available; change requests stay disabled."}
          </span>}
        </div>
        {!oracleReady && <p role="status" className="mt-2 text-sm text-[var(--status-warn)]">
          {responderLabel} is unavailable; your draft is kept here. Sending resumes after a healthy mailbox observation.
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
