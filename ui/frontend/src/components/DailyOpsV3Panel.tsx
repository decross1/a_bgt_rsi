import { Link } from "react-router-dom";
import { ResearchOpsCard } from "./ResearchOpsCard";

const record = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const keys = (value: Record<string, unknown>, expected: readonly string[]) =>
  Object.keys(value).length === expected.length && expected.every(key => Object.hasOwn(value, key));
const allowedKeys = (value: Record<string, unknown>, permitted: readonly string[]) =>
  Object.keys(value).every(key => permitted.includes(key));
const text = (value: unknown, limit = 4096): value is string =>
  typeof value === "string" && value.length > 0 && value.length <= limit && value === value.trim() &&
  Array.from(value).every(char => {
    const code = char.codePointAt(0);
    return code !== undefined && code >= 32;
  });
const stamp = (value: unknown): value is string => text(value, 40) &&
  /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{6})?Z$/.test(value) && Number.isFinite(Date.parse(value));
const optionalText = (value: unknown, limit: number): string | null | undefined =>
  value === null || value === undefined ? null : text(value, limit) ? value : undefined;
const phrase = (value: string) => value.replaceAll("_", " ");
const timeLabel = (value: string) => new Date(value).toLocaleString("en-US", {
  timeZone: "UTC", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
}) + " UTC";

type V3Plan = { id: string; revision: string; isCurrent: boolean; path: string; writtenAt: string } | null;
type V3Focus = { status: string; title: string | null; stage: string | null; nextAction: string | null };
type V3Work = { id: string; goal: string; owner: string; lane: string; repo: string; title: string; detail: string; status: string; whyToday: string | null; acceptance: string | null; dependsOn: string[] };
type V3Waiting = { id: string; kind: string; title: string; question: string; context: string | null; choices: string[]; recommendation: string | null; consequence: string | null; askedBy: string; askedAt: string | null; msgId: string | null; awaitingAsker: boolean; handoffMsgId: string | null };
type V3Update = { id: string; title: string; disposition: string; summary: string; reason: string; resolvedAt: string; evidence: string[] };
type V3Achievement = { id: string; kind: string; title: string; at: string; evidence: string };
type V3Agent = { label: string; role: string | null; status: string; detail: string; observedAt: string; source: string; activity: string | null };

export type DailyOpsV3Summary = {
  generatedAt: string;
  plan: V3Plan;
  focus: V3Focus;
  work: V3Work[];
  waiting: V3Waiting[];
  updates: V3Update[];
  accomplishments: V3Achievement[];
  improvements: V3Achievement[];
  agents: V3Agent[];
  warnings: string[];
};

function strings(value: unknown, limit: number, length: number): string[] | null {
  return Array.isArray(value) && value.length <= limit && value.every(item => text(item, length))
    ? value as string[] : null;
}

function plan(value: unknown, revision: unknown): V3Plan | undefined {
  if (value === null) return revision === null ? null : undefined;
  if (!record(value) || !text(value.id, 64) || !text(value.revision, 12) ||
      !text(value.path, 200) || !stamp(value.written_at) || typeof value.is_current !== "boolean" ||
      !keys(value, ["id", "date", "revision", "path", "sha256", "written_at", "is_current", "week_alignment", "bottlenecks", "review"]) ||
      !/^\d{4}-\d\d-\d\d$/.test(String(value.date)) || !/^[0-9a-f]{64}$/.test(String(value.sha256)) ||
      optionalText(value.week_alignment, 1200) === undefined || !Array.isArray(value.bottlenecks) ||
      value.bottlenecks.length > 5 || !value.bottlenecks.every(item => text(item, 400))) return undefined;
  // A historical plan is evidence only.  It must never carry an actionable
  // current revision, while a current plan must bind its own immutable id.
  if ((value.is_current && value.id !== revision) || (!value.is_current && revision !== null)) return undefined;
  if (value.review !== null) {
    if (!record(value.review) || !keys(value.review, ["note_msg_id", "sha_matches", "verdict", "review_msg_id", "reviewed_at", "summary", "accepted_items"]) ||
        !text(value.review.note_msg_id, 80) || typeof value.review.sha_matches !== "boolean" ||
        !(value.review.verdict === null || ["accept", "amend", "reject"].includes(String(value.review.verdict))) ||
        optionalText(value.review.review_msg_id, 80) === undefined ||
        !(value.review.reviewed_at === null || stamp(value.review.reviewed_at)) ||
        optionalText(value.review.summary, 400) === undefined || !Array.isArray(value.review.accepted_items) ||
        !value.review.accepted_items.every(item => text(item, 40))) return undefined;
  }
  return { id: value.id, revision: value.revision, isCurrent: value.is_current, path: value.path, writtenAt: value.written_at };
}

function focus(value: unknown): V3Focus | null {
  if (!record(value) || !["selected", "none", "source_invalid"].includes(String(value.status)) ||
      !stamp(value.observed_at) || !allowedKeys(value, ["status", "observed_at", "focus_id", "title", "stage", "next_action", "intake_policy", "selected_at", "reason", "last_closure", "closure_error"])) return null;
  const title = optionalText(value.title, 1200);
  const stage = optionalText(value.stage, 1200);
  const nextAction = optionalText(value.next_action, 1200);
  if (title === undefined || stage === undefined || nextAction === undefined ||
      optionalText(value.focus_id, 1200) === undefined || optionalText(value.intake_policy, 1200) === undefined ||
      optionalText(value.reason, 1200) === undefined || optionalText(value.closure_error, 1200) === undefined ||
      !(value.selected_at === null || value.selected_at === undefined || stamp(value.selected_at))) return null;
  const closure = value.last_closure;
  if (closure !== null && closure !== undefined) {
    if (!record(closure) || !keys(closure, ["focus_id", "title", "disposition", "closed_at", "reason", "closure_sha256"]) ||
        !(closure.closed_at === null || stamp(closure.closed_at)) ||
        ["focus_id", "title", "disposition", "reason", "closure_sha256"].some(key => optionalText(closure[key], 1200) === undefined)) return null;
  }
  return { status: String(value.status), title, stage, nextAction };
}

function work(value: unknown): V3Work[] | null {
  if (!Array.isArray(value) || value.length > 12) return null;
  const statuses = new Set(["not_started", "awaiting_review", "held", "building", "validated", "failed", "withdrawn", "expired", "amend_requested", "accepted", "rejected", "merged", "waiting_on_you", "answered", "resolved"]);
  const rows: V3Work[] = [];
  for (const item of value) {
    if (!record(item) || !keys(item, ["id", "goal", "owner", "lane", "repo", "title", "summary", "why_today", "acceptance", "depends_on", "status", "detail", "evidence_msg_id", "evidence_sha", "evidence_at"]) || !text(item.id, 40) || !text(item.goal, 300) || !text(item.owner, 300) ||
        !text(item.lane, 300) || !text(item.repo, 300) || !text(item.title, 300) || !text(item.detail, 400) ||
        !statuses.has(String(item.status))) return null;
    const whyToday = optionalText(item.why_today, 1200);
    const acceptance = optionalText(item.acceptance, 1200);
    const summary = optionalText(item.summary, 90);
    const evidenceMsg = optionalText(item.evidence_msg_id, 80);
    const evidenceSha = optionalText(item.evidence_sha, 40);
    const dependsOn = strings(item.depends_on, 8, 40);
    if (whyToday === undefined || acceptance === undefined || summary === undefined || evidenceMsg === undefined ||
        evidenceSha === undefined || !(item.evidence_at === null || stamp(item.evidence_at)) || dependsOn === null) return null;
    rows.push({ id: item.id, goal: item.goal, owner: item.owner, lane: item.lane, repo: item.repo,
      title: item.title, detail: item.detail, status: String(item.status), whyToday, acceptance, dependsOn });
  }
  return rows;
}

function waiting(value: unknown): V3Waiting[] | null {
  if (!Array.isArray(value) || value.length > 16) return null;
  const rows: V3Waiting[] = [];
  for (const item of value) {
    if (!record(item) || !keys(item, ["kind", "id", "title", "question", "context", "choices", "recommendation", "consequence", "asked_by", "asked_at", "msg_id", "cli", "awaiting_asker", "handoff_msg_id"]) || !["question", "owner_decision"].includes(String(item.kind)) || !text(item.id, 120) ||
        !text(item.title, 300) || !text(item.question, 300) || !text(item.asked_by, 60) ||
        typeof item.awaiting_asker !== "boolean") return null;
    const context = optionalText(item.context, 1200);
    const recommendation = optionalText(item.recommendation, 600);
    const consequence = optionalText(item.consequence, 600);
    const askedAt = item.asked_at === null ? null : stamp(item.asked_at) ? item.asked_at : undefined;
    const msgId = optionalText(item.msg_id, 80);
    const handoffMsgId = optionalText(item.handoff_msg_id, 80);
    const choices = strings(item.choices, 8, 300);
    if (context === undefined || recommendation === undefined || consequence === undefined || askedAt === undefined ||
        msgId === undefined || handoffMsgId === undefined || !text(item.cli, 600) || choices === null ||
        (!item.awaiting_asker && handoffMsgId !== null)) return null;
    rows.push({ id: item.id, kind: String(item.kind), title: item.title, question: item.question, context,
      choices, recommendation, consequence, askedBy: item.asked_by, askedAt, msgId,
      awaitingAsker: item.awaiting_asker, handoffMsgId });
  }
  return rows;
}

function updates(value: unknown): V3Update[] | null {
  if (!Array.isArray(value) || value.length > 10) return null;
  const rows: V3Update[] = [];
  for (const item of value) {
    if (!record(item) || !keys(item, ["id", "question_id", "title", "question", "disposition", "summary", "reason", "blocking_artifact", "resolved_by", "resolved_at", "evidence_msg_ids"]) || !text(item.id, 80) || !text(item.question_id, 80) || !text(item.title, 300) || !text(item.question, 300) || !["withdrawn", "superseded", "prerequisite", "informational", "contested", "presentation_archived_claim"].includes(String(item.disposition)) ||
        !text(item.summary, 1200) || !text(item.reason, 1200) || !stamp(item.resolved_at)) return null;
    const evidence = strings(item.evidence_msg_ids, 8, 80);
    if (evidence === null || optionalText(item.blocking_artifact, 240) === undefined || !text(item.resolved_by, 60)) return null;
    rows.push({ id: item.id, title: item.title, disposition: String(item.disposition), summary: item.summary,
      reason: item.reason, resolvedAt: item.resolved_at, evidence });
  }
  return rows;
}

function achievements(value: unknown, limit: number): V3Achievement[] | null {
  if (!Array.isArray(value) || value.length > limit) return null;
  const rows: V3Achievement[] = [];
  for (const item of value) {
    if (!record(item) || !keys(item, ["id", "kind", "title", "at", "evidence"]) || !text(item.id, 120) || !["merged", "validated", "focus_closed", "day_closed"].includes(String(item.kind)) || !text(item.title, 400) || !stamp(item.at) || !text(item.evidence, 120)) return null;
    rows.push({ id: item.id, kind: String(item.kind), title: item.title, at: item.at, evidence: item.evidence });
  }
  return rows;
}

function improvements(value: unknown): V3Achievement[] | null {
  if (!Array.isArray(value) || value.length > 40) return null;
  const rows: V3Achievement[] = [];
  for (const item of value) {
    if (!record(item) || !keys(item, ["sha", "at", "subject", "goals"]) || !/^[0-9a-f]{7,40}$/.test(String(item.sha)) || !stamp(item.at) || !text(item.subject, 240) ||
        !Array.isArray(item.goals) || !item.goals.every(goal => /^G\d+(?:\.\d+)?$/.test(String(goal)))) return null;
    rows.push({ id: String(item.sha), kind: "improvement", title: item.subject, at: item.at, evidence: String(item.sha) });
  }
  return rows;
}

function agents(value: unknown): V3Agent[] | null {
  if (!record(value)) return null;
  if (!Object.hasOwn(value, "oracle") || !Object.hasOwn(value, "pi_client") || !Object.hasOwn(value, "nara") ||
      !allowedKeys(value, ["oracle", "pi_client", "nara", "meta_oracle"])) return null;
  const rows: V3Agent[] = [];
  for (const key of ["oracle", "pi_client", "nara", "meta_oracle"]) {
    const item = value[key];
    if (item === undefined) {
      if (key !== "meta_oracle") return null;
      continue;
    }
    if (item === null) return null;
    if (!record(item) || !keys(item, ["label", "role", "status", "detail", "observed_at", "source", "activity", "activity_at", "since"]) || !text(item.label, 512) || !["online", "active", "working", "idle", "waiting", "degraded", "stale", "failed", "offline", "unknown"].includes(String(item.status)) || !text(item.detail, 512) ||
        !stamp(item.observed_at) || !text(item.source, 512) || !(item.activity_at === null || stamp(item.activity_at)) || !(item.since === null || stamp(item.since)) || (key === "pi_client" && !item.label.toLowerCase().includes("client"))) return null;
    const role = text(item.role, 512) ? item.role : undefined;
    const activity = optionalText(item.activity, 512);
    if (role === undefined || activity === undefined) return null;
    rows.push({ label: item.label, role, status: String(item.status), detail: item.detail, observedAt: item.observed_at,
      source: item.source, activity });
  }
  return rows;
}

/** Strict enough to fail closed, while tolerating producer-only fields we do not render. */
export function admitDailyOpsV3Summary(value: unknown): DailyOpsV3Summary | null {
  if (!record(value) || !keys(value, ["schema_version", "generated_at", "current_plan_revision", "daily_plan", "research_focus", "work_items", "waiting_on_you", "question_updates", "accomplishments", "improvements", "agents", "warnings", "sources"]) || value.schema_version !== "daily-ops-summary/v3" || !stamp(value.generated_at) ||
      !(value.current_plan_revision === null || text(value.current_plan_revision, 64)) || !record(value.sources)) return null;
  const parsedPlan = plan(value.daily_plan, value.current_plan_revision);
  const parsedFocus = focus(value.research_focus);
  const parsedWork = work(value.work_items);
  const parsedWaiting = waiting(value.waiting_on_you);
  const parsedUpdates = updates(value.question_updates);
  const parsedAccomplishments = achievements(value.accomplishments, 16);
  const parsedImprovements = improvements(value.improvements);
  const parsedAgents = agents(value.agents);
  const warnings = strings(value.warnings, 16, 512);
  if (parsedPlan === undefined || parsedFocus === null || parsedWork === null || parsedWaiting === null ||
      parsedUpdates === null || parsedAccomplishments === null || parsedImprovements === null ||
      parsedAgents === null || warnings === null || !keys(value.sources, ["plan", "mailbox", "focus", "git"]) ||
      !Object.values(value.sources).every(source => source === null || stamp(source))) return null;
  return { generatedAt: value.generated_at, plan: parsedPlan, focus: parsedFocus, work: parsedWork,
    waiting: parsedWaiting, updates: parsedUpdates, accomplishments: parsedAccomplishments,
    improvements: parsedImprovements, agents: parsedAgents, warnings };
}

function Badge({ value }: { value: string }) {
  return <span className="rounded-full bg-[var(--status-idle-bg)] px-2 py-0.5 text-[11px] font-medium text-[var(--status-idle)]">{phrase(value)}</span>;
}

function WaitingCard({ item, claude }: { item: V3Waiting; claude: boolean }) {
  return <li data-testid={`daily-v3-waiting-${item.id}`} className="rounded border border-[var(--border-1)] bg-[var(--surface-1)] p-3">
    <div className="flex flex-wrap items-center gap-2"><span className="font-medium">{item.title}</span><Badge value={claude ? "awaiting asker" : "agent reconciliation"} /></div>
    {item.question !== item.title && <p className="mt-2 text-sm">{item.question}</p>}
    {item.context && <p className="mt-2 text-sm text-[var(--fg-muted)]">{item.context}</p>}
    {item.choices.length > 0 && <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-[var(--fg-muted)]">{item.choices.map((choice, index) => <li key={`${item.id}-${index}`}>{choice}</li>)}</ul>}
    {item.recommendation && <p className="mt-2 text-sm"><span className="font-medium">Recommendation: </span>{item.recommendation}</p>}
    {item.consequence && <p className="mt-2 text-sm text-[var(--fg-muted)]"><span className="font-medium">If deferred: </span>{item.consequence}</p>}
    <p className="mt-2 text-xs text-[var(--fg-muted)]">Asked by {claude ? "Claude" : item.askedBy}{item.askedAt ? ` · ${timeLabel(item.askedAt)}` : ""}{item.msgId ? ` · source ${item.msgId}` : ""}{claude && item.handoffMsgId ? ` · exact handoff ${item.handoffMsgId}` : ""}</p>
  </li>;
}

/** Read-only v3 presentation. It intentionally imports no v2 decision writer. */
export function DailyOpsV3Panel({ summary, legacyResearchOps, legacyFailing = false }: { summary: DailyOpsV3Summary; legacyResearchOps: unknown; legacyFailing?: boolean }) {
  const ownerItems = summary.waiting.filter(item => !item.awaitingAsker);
  const awaitingClaude = summary.waiting.filter(item => item.awaitingAsker);
  return <section data-testid="daily-ops-v3-panel" aria-labelledby="daily-ops-v3-heading" className="mb-4 rounded-lg border border-[var(--group-research)] bg-[var(--surface-1)] p-4">
    <div className="flex flex-wrap items-start justify-between gap-3"><div>
      <p className="text-xs font-semibold uppercase tracking-wide text-[var(--group-research)]">Live mailbox-derived brief</p>
      <h2 id="daily-ops-v3-heading" className="mt-1 text-xl font-semibold">Today&apos;s research path</h2>
      <p className="mt-1 text-sm text-[var(--fg-muted)]">v3 is read-only. These cards describe evidence and routing; they do not submit a decision or close a question.</p>
    </div><span className="rounded border border-[var(--border-2)] px-2 py-1 text-xs text-[var(--fg-muted)]">Live view {timeLabel(summary.generatedAt)}</span></div>

    {summary.warnings.length > 0 && <div role="status" className="mt-4 rounded border border-[var(--status-warn)] bg-[var(--status-warn-bg)] p-3 text-sm">{summary.warnings.map(warning => <p key={warning}>{warning}</p>)}</div>}

    <div className="mt-4 grid gap-4 lg:grid-cols-2"><section className="rounded border border-[var(--border-1)] p-3"><h3 className="font-semibold">Plan of record</h3>
      {summary.plan ? <><p className="mt-2 text-sm">{summary.plan.id} · {summary.plan.revision} · {summary.plan.isCurrent ? "current" : "historical only"}</p><p className="mt-1 text-xs text-[var(--fg-muted)]">{summary.plan.path} · {timeLabel(summary.plan.writtenAt)}</p></> : <p className="mt-2 text-sm text-[var(--fg-muted)]">No source-bound daily plan is available.</p>}</section>
      <section className="rounded border border-[var(--group-research)] p-3"><h3 className="font-semibold">Main research thesis</h3>{summary.focus.title ? <><p className="mt-2 font-medium">{summary.focus.title}</p>{summary.focus.stage && <p className="mt-1 text-sm text-[var(--fg-muted)]">{phrase(summary.focus.stage)}</p>}{summary.focus.nextAction && <p className="mt-2 text-sm"><span className="font-medium">Next: </span>{summary.focus.nextAction}</p>}</> : <p className="mt-2 text-sm text-[var(--fg-muted)]">No source-bound main thesis is selected.</p>}<div className="mt-3"><Link to="/ladder?research_scope=active" className="text-sm text-[var(--accent)]">Open thesis workspace →</Link></div></section></div>

    <section className="mt-4" aria-labelledby="daily-v3-work"><h3 id="daily-v3-work" className="font-semibold">Today&apos;s work</h3><p className="mt-1 text-sm text-[var(--fg-muted)]">Live status only; no v3 work-card action is sent through the legacy decision route.</p>
      {summary.work.length === 0 ? <p className="mt-2 text-sm text-[var(--fg-muted)]">No current work items are recorded.</p> : <ul className="mt-3 grid gap-3 xl:grid-cols-2">{summary.work.map(item => <li key={item.id} data-testid={`daily-v3-work-${item.id}`} className="rounded border border-[var(--border-1)] p-3"><div className="flex flex-wrap items-center gap-2"><span className="font-medium">{item.title}</span><Badge value={item.status} /></div><p className="mt-1 text-sm text-[var(--fg-muted)]">{item.goal} · {phrase(item.lane)} · {item.repo}</p><p className="mt-2 text-sm">{item.detail}</p>{item.whyToday && <p className="mt-2 text-sm text-[var(--fg-muted)]"><span className="font-medium">Why today: </span>{item.whyToday}</p>}{item.acceptance && <p className="mt-2 text-sm text-[var(--fg-muted)]"><span className="font-medium">Acceptance: </span>{item.acceptance}</p>}</li>)}</ul>}</section>

    <section className="mt-4"><h3 className="font-semibold">Lab stewardship</h3><div className="mt-2 grid gap-2 sm:grid-cols-3">{summary.agents.map(agent => <div key={agent.label} className="rounded border border-[var(--border-1)] p-3"><div className="flex flex-wrap items-center gap-2"><span className="font-medium">{agent.label}</span><Badge value={agent.status} /></div>{agent.role && <p className="mt-1 text-xs uppercase tracking-wide text-[var(--fg-muted)]">{agent.role}</p>}<p className="mt-2 text-sm text-[var(--fg-muted)]">{agent.activity ?? agent.detail}</p><p className="mt-1 text-xs text-[var(--fg-muted)]">Observed {timeLabel(agent.observedAt)}</p></div>)}</div></section>

    <section data-testid="daily-v3-reconciliation" className="mt-4 rounded border border-[var(--status-warn)] p-3"><h3 className="font-semibold">Needs agent reconciliation</h3><p className="mt-1 text-sm text-[var(--fg-muted)]">These open cards remain non-terminal. An agent must reconcile them; this view offers no owner-action button.</p>{ownerItems.length === 0 ? <p className="mt-2 text-sm text-[var(--fg-muted)]">No open reconciliation exception is recorded.</p> : <ul className="mt-3 space-y-3">{ownerItems.map(item => <WaitingCard key={item.id} item={item} claude={false} />)}</ul>}</section>
    {awaitingClaude.length > 0 && <section data-testid="daily-v3-awaiting-claude" className="mt-4 rounded border border-[var(--border-1)] p-3"><h3 className="font-semibold">Awaiting Claude</h3><p className="mt-1 text-sm text-[var(--fg-muted)]">Each card is routed only by its exact reviewed handoff. It remains open context, not an owner vote.</p><ul className="mt-3 space-y-3">{awaitingClaude.map(item => <WaitingCard key={item.id} item={item} claude />)}</ul></section>}

    {summary.updates.length > 0 && <section className="mt-4 rounded border border-[var(--border-1)] p-3"><h3 className="font-semibold">Updated / prerequisites</h3><ul className="mt-2 space-y-2">{summary.updates.map(item => <li key={item.id}><p className="font-medium">{item.title} <Badge value={item.disposition} /></p><p className="text-sm">{item.summary}</p><p className="text-xs text-[var(--fg-muted)]">Why: {item.reason} · {timeLabel(item.resolvedAt)}{item.evidence.length ? ` · evidence ${item.evidence.join(", ")}` : ""}</p></li>)}</ul></section>}
    <details className="mt-4 rounded border border-[var(--border-1)] p-3"><summary className="cursor-pointer text-sm font-medium text-[var(--accent)]">Full research operations and diagnostic detail</summary><div className="mt-3"><ResearchOpsCard data={legacyResearchOps} failing={legacyFailing} showFocus={false} /></div></details>
  </section>;
}
