import { useEffect, useState } from "react";
import { API_BASE } from "../api/http";
import Card from "../design/Card";
import { useNow } from "../time";
import { developmentReceipt as receipt } from "../data/developmentReceipt";

type RecordValue = Record<string, unknown>;
type Source = { data: RecordValue | null; receivedAt: string | null; loading: boolean; error: string | null };
const endpoints = {
  ladder: "/api/ladder",
  frontier: "/api/frontier_reviews?limit=100",
  channel: "/api/channel/timeline?limit=1000",
  health: "/api/health",
} as const;
type SourceKey = keyof typeof endpoints;
const keys = Object.keys(endpoints) as SourceKey[];
const blank = (): Source => ({ data: null, receivedAt: null, loading: true, error: null });
const isRecord = (v: unknown): v is RecordValue => v !== null && typeof v === "object" && !Array.isArray(v);
const rows = (v: unknown): RecordValue[] => Array.isArray(v) ? v.filter(isRecord) : [];
const text = (v: unknown): string => typeof v === "string" && v ? v : "unknown";
const validTime = (v: unknown): v is string => typeof v === "string" && Number.isFinite(Date.parse(v));
const latest = (values: unknown[]) => values.filter(validTime).sort((a, b) => Date.parse(b) - Date.parse(a))[0] ?? null;

function validate(key: SourceKey, body: unknown): RecordValue {
  if (!isRecord(body)) throw new Error("Source missing or response shape unknown");
  const field = key === "ladder" ? "clusters" : key === "frontier" ? "events" : key === "channel" ? "rows" : null;
  if (field && (!Array.isArray(body[field]) || !(body[field] as unknown[]).every(isRecord))) {
    throw new Error(`Source missing or invalid ${field}; no zero count inferred`);
  }
  if (key === "ladder" && (!isRecord(body.counts) || !["open", "surfaced", "killed"].every((name) => {
    const count = (body.counts as RecordValue)[name];
    return typeof count === "number" && Number.isInteger(count) && count >= 0;
  }))) throw new Error("Recorded counts missing or invalid; no zero count inferred");
  return body;
}

function SourceState({ source }: { source: Source }) {
  return <div className="mt-2 text-xs text-[var(--fg-muted)]">
    <p>Last successful read: {source.receivedAt ?? "not yet available"}</p>
    <p>Browser read in progress: {source.loading ? "yes" : "no"}</p>
    {source.error && <p role="status" className="text-[var(--status-warn)]">
      Read failed: {source.error}. {source.data ? "Showing the previous observation; current state is unknown." : "State is unknown, not empty."}
    </p>}
  </div>;
}

function SourceTime({ label, value }: { label: string; value: unknown }) {
  const age = validTime(value) ? Math.floor((Date.now() - Date.parse(value)) / 60_000) : null;
  return <p className="text-xs text-[var(--fg-muted)]">{label}: {validTime(value) ? value : "not reported"}
    {age !== null && (age < 0 ? " (future-dated; clock/source needs checking)" : ` (${age} min old)`)}</p>;
}

export default function Development() {
  useNow(30_000);
  const [refresh, setRefresh] = useState(0);
  const [sources, setSources] = useState<Record<SourceKey, Source>>({ ladder: blank(), frontier: blank(), channel: blank(), health: blank() });
  useEffect(() => {
    const controllers: AbortController[] = [];
    let active = true;
    for (const key of keys) {
      const controller = new AbortController();
      controllers.push(controller);
      const timer = setTimeout(() => controller.abort(), 15_000);
      setSources((s) => ({ ...s, [key]: { ...s[key], loading: true } }));
      fetch(`${API_BASE}${endpoints[key]}`, { signal: controller.signal })
        .then(async (response) => {
          if (!response.ok || response.status === 204) throw new Error(`HTTP ${response.status}`);
          return validate(key, await response.json());
        })
        .then((data) => {
          if (active) setSources((s) => ({ ...s, [key]: { data, receivedAt: new Date().toISOString(), loading: false, error: null } }));
        })
        .catch((error: unknown) => {
          if (active) setSources((s) => ({ ...s, [key]: { ...s[key], loading: false, error: String(error) } }));
        })
        .finally(() => clearTimeout(timer));
    }
    return () => { active = false; controllers.forEach((c) => c.abort()); };
  }, [refresh]);

  const clusters = rows(sources.ladder.data?.clusters);
  const channel = rows(sources.channel.data?.rows);
  const events = rows(sources.frontier.data?.events);
  // Feed is newest-first. Keep one current row per proposal; no ruling is written here.
  const seen = new Set<string>();
  const proposals = events.filter((e) => {
    if (e.type !== "agenda" || typeof e.proposal_id !== "string" || seen.has(e.proposal_id)) return false;
    seen.add(e.proposal_id);
    return true;
  });
  const unresolved = proposals.filter((p) => !["accepted", "dismissed"].includes(text(p.effective_status ?? p.status)));
  const available = sources.frontier.data?.available;
  const agendaAvailable = isRecord(available) && available.agenda === true;
  const windows = sources.frontier.data?.windows;
  const truncated = (isRecord(windows) && isRecord(windows.agenda) && windows.agenda.truncated === true)
    || (typeof sources.frontier.data?.events_in_window === "number" && sources.frontier.data.events_in_window > events.length);

  return <div className="page-full" data-testid="development-page">
    <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
      <div><h1 className="text-xl font-semibold">Development and research readiness</h1>
        <p className="mt-1 text-sm text-[var(--fg-muted)]">Three lanes, with different sources and different meanings of progress.</p></div>
      <button type="button" onClick={() => setRefresh((n) => n + 1)} disabled={keys.some((k) => sources[k].loading)}
        className="rounded border border-[var(--border-1)] px-3 py-2 text-sm disabled:opacity-50">Read latest snapshots</button>
    </header>
    <div className="grid gap-4 lg:grid-cols-3">
      <Card title="Codex engineering / delivery" testId="development-engineering">
        <p className="font-medium">{receipt.title}</p>
        <p className="mt-2 text-xs text-[var(--fg-muted)]">Static receipt recorded {receipt.recordedAt}; not live GitHub status.</p>
        <ul className="my-3 list-disc space-y-2 pl-5 text-sm">{receipt.changes.map((change) => <li key={change}>{change}</li>)}</ul>
        <a href={receipt.pr} target="_blank" rel="noreferrer" className="text-[var(--accent)]">Open PR #3 for current delivery status ↗</a>
        <p className="mt-2 break-all text-xs">Published source at receipt: {receipt.head}</p>
        <p className="mt-3 text-sm">{receipt.checks}</p>
        <p className="mt-3 text-sm"><strong>Next evidence:</strong> {receipt.next}</p>
        <p className="mt-3 text-sm"><strong>Held worker:</strong> {receipt.worker}</p>
        <details className="mt-4 text-sm"><summary className="cursor-pointer">Historical binding audit — separate from current counts</summary>
          <p className="mt-2">Recorded {receipt.audit.recordedAt}: {receipt.audit.iterations} historical iterations; {receipt.audit.bound} bound, {receipt.audit.mismatch} mismatch, {receipt.audit.unverifiable} unverifiable under the repaired envelope rule.</p>
          <p>This describes claim/evidence association. It does not mean the hypotheses are false or show today&apos;s ledger totals.</p>
          <p className="mt-2 break-all text-xs">Source-bound exposure SHA256: {receipt.audit.exposure}</p>
        </details>
      </Card>
      <Card title="Nara runtime / channel" testId="development-runtime">
        <p className="text-sm">Nara is the separate Gemma runtime agent. Codex engineering does not automatically post a Nara reply or dispatch a Qwen task.</p>
        <div className="my-3 space-y-2">
          <SourceTime label="Latest Nara message in loaded timeline" value={latest(channel.filter((r) => r.kind === "nara").map((r) => r.ts))} />
          <SourceTime label="Latest channel turn in loaded timeline" value={latest(channel.filter((r) => r.kind !== "event").map((r) => r.ts))} />
        </div>
        <p className="text-sm">An old message date is not a liveness verdict. This read shows up to 1,000 timeline rows; an absent Nara row means no message was found in that window.</p>
        <SourceState source={sources.channel} />
        <a href="/channel" className="mt-3 block text-[var(--accent)]">Read Nara&apos;s channel →</a>
        <p className="mt-4 text-sm"><strong>Running backend revision:</strong> {text(sources.health.data?.version)}</p>
        <p className="text-xs text-[var(--fg-muted)]">Backend-reported revision captured at process import; not the source branch or proof of clean deployed bytes. Deployed frontend commit is not reported by this backend.</p>
        <SourceState source={sources.health} />
      </Card>
      <Card title="Scientific evidence / agenda" testId="development-science">
        <p className="text-sm">Ladder positions are recorded classifications, not revalidated experiment eligibility. Engineering commits do not promote research.</p>
        {sources.ladder.data ? <>
          <p className="my-3 text-lg font-semibold">{clusters.length} recorded clusters</p>
          <table className="w-full text-left text-sm"><caption className="mb-2 text-left text-xs">Positions in the loaded ledger projection</caption>
            <thead><tr><th>Rung</th><th>Open</th><th>Surfaced</th><th>Killed</th><th>Recorded next test</th></tr></thead>
            <tbody>{["L0", "L1", "L2", "L3", "L4", "L5"].map((level) => <tr key={level}>
              <th>{level}</th>{["open", "surfaced", "killed"].map((status) => <td key={status}>{clusters.filter((c) => c.status === status && c.evidence_level === level).length}</td>)}
              <td className="text-xs">{isRecord(sources.ladder.data?.next_owed) ? text(sources.ladder.data.next_owed[level]) : "not reported"}</td>
            </tr>)}</tbody>
          </table>
          <p className="mt-2 text-xs">Other / unclassified: {clusters.filter((c) => !["open", "surfaced", "killed"].includes(text(c.status)) || !["L0", "L1", "L2", "L3", "L4", "L5"].includes(text(c.evidence_level))).length}</p>
          <SourceTime label="Latest recorded cluster event (not confirmation)" value={latest(clusters.map((c) => c.last_event_ts))} />
          <p className="text-xs text-[var(--fg-muted)]">Source: idea-ledger projection. Source file hash and cache age are not reported by this endpoint.</p>
        </> : <p className="my-3 text-sm">Recorded counts unavailable — no zero or historical snapshot substituted.</p>}
        <SourceState source={sources.ladder} />
        <a href="/ladder" className="mt-3 block text-[var(--accent)]">Inspect the ladder and next tests →</a>
        <hr className="my-4 border-[var(--border-1)]" />
        <p className="text-sm">Frontier proposals are suggestions until a human records a ruling. Acceptance onto the agenda is not a completed experiment.</p>
        {agendaAvailable ? <>
          <p className="my-2 text-sm">Loaded proposals: {unresolved.length} unresolved · {proposals.filter((p) => (p.effective_status ?? p.status) === "accepted").length} accepted · {proposals.filter((p) => (p.effective_status ?? p.status) === "dismissed").length} dismissed</p>
          <SourceTime label="Latest proposal in loaded feed" value={latest(proposals.map((p) => p.ts))} />
          {truncated && <p className="text-sm text-[var(--status-warn)]">Partial feed window — counts are not the complete agenda history.</p>}
          <details className="my-3 text-sm"><summary className="cursor-pointer">Older unresolved suggestions ({unresolved.length})</summary>
            <ul className="mt-2 list-disc space-y-2 pl-5">{unresolved.map((p) => <li key={String(p.proposal_id)}>{text(p.topic)} <span className="text-xs text-[var(--fg-muted)]">— {text(p.ts)}; {text(p.effective_status ?? p.status)}</span></li>)}</ul>
          </details>
        </> : <p className="my-2 text-sm">Proposal source unavailable or not reported — unresolved suggestions are not cleared.</p>}
        <SourceTime label="Frontier projection generated" value={sources.frontier.data?.generated_at} />
        <p className="text-xs text-[var(--fg-muted)]">Backend refresh in progress: not reported. The projection timestamp is separate from this browser read and any read error.</p>
        <SourceState source={sources.frontier} />
        <p className="mt-3 text-sm">The frontier feed reads review and proposal ledgers, not Codex handoffs. No new entry is fabricated when engineering ships.</p>
        <a href="/model-io" className="mt-3 block text-[var(--accent)]">Review suggestions and human ruling controls →</a>
      </Card>
    </div>
    <p className="mt-4 text-xs text-[var(--fg-muted)]">This page reads existing snapshots on arrival or request. It does not call the heavy lab-queue refresh, run a model, accept a proposal or change a research result.</p>
  </div>;
}
