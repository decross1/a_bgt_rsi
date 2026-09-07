import { useDevelopmentSources, type Source } from "../api/development";
import Card from "../design/Card";
import { useNow } from "../time";
import { developmentReceipt as receipt, uiDeliveryReceipt as uiReceipt } from "../data/developmentReceipt";

type RecordValue = Record<string, unknown>;
const isRecord = (v: unknown): v is RecordValue => v !== null && typeof v === "object" && !Array.isArray(v);
const rows = (v: unknown): RecordValue[] => Array.isArray(v) ? v.filter(isRecord) : [];
const text = (v: unknown): string => typeof v === "string" && v ? v : "unknown";
const validTime = (v: unknown): v is string => typeof v === "string" && Number.isFinite(Date.parse(v));
const latest = (values: unknown[]) => values.filter(validTime).sort((a, b) => Date.parse(b) - Date.parse(a))[0] ?? null;


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
  const { sources, refreshSources } = useDevelopmentSources();

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
  const unresolved = proposals.filter((p) => p.effective_status === "proposed");
  const channelIntegrity = sources.channel.data?.integrity;
  const framedChannel = isRecord(channelIntegrity)
    && channelIntegrity.schema === "lab-channel-timeline/v1"
    && channelIntegrity.framing === "json-envelope"
    && channelIntegrity.status === "framed"
    && channelIntegrity.actor_labels === "recorded_not_authenticated";
  const frontierIntegrity = sources.frontier.data?.integrity;
  const agendaIntegrity = isRecord(frontierIntegrity) ? frontierIntegrity.agenda : null;
  const statusIntegrity = isRecord(frontierIntegrity) ? frontierIntegrity.agenda_status : null;
  const readableIntegrity = (v: unknown): v is RecordValue => isRecord(v)
    && typeof v.complete === "boolean" && v.missing === false
    && typeof v.truncated === "boolean" && Array.isArray(v.errors) && v.errors.length === 0
    && (v.complete === true || v.truncated === true);
  const currentStatuses = proposals.every((p) => typeof p.effective_status === "string" && ["proposed", "accepted", "dismissed"].includes(p.effective_status))
    && events.filter((e) => e.type === "agenda").every((e) => typeof e.proposal_id === "string" && e.proposal_id.length > 0);
  const agendaStatusKnown = currentStatuses && readableIntegrity(agendaIntegrity)
    && readableIntegrity(statusIntegrity) && statusIntegrity.complete === true
    && statusIntegrity.truncated === false && !sources.frontier.error;
  const integrityErrors = [agendaIntegrity, statusIntegrity].flatMap((v) => isRecord(v) && Array.isArray(v.errors)
    ? v.errors.filter((e): e is string => typeof e === "string") : []);
  const windows = sources.frontier.data?.windows;
  const truncated = (isRecord(agendaIntegrity) && (agendaIntegrity.truncated === true || agendaIntegrity.complete === false))
    || (isRecord(windows) && isRecord(windows.agenda) && windows.agenda.truncated === true)
    || (typeof sources.frontier.data?.events_in_window === "number" && sources.frontier.data.events_in_window > events.length);

  return <div className="page-full" data-testid="development-page">
    <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
      <div><p className="mb-1 text-xs font-medium uppercase tracking-widest text-[var(--fg-muted)]">Operations</p>
        <h1 className="text-3xl font-semibold tracking-tight">Delivery and readiness</h1>
        <p className="mt-2 text-sm text-[var(--fg-muted)]">What changed, what remains held, and which evidence is needed next.</p></div>
      <button type="button" onClick={refreshSources} disabled={Object.values(sources).some((source) => source.loading)}
        className="rounded border border-[var(--border-1)] px-3 py-2 text-sm disabled:opacity-50">Read latest snapshots</button>
    </header>
    <section aria-label="Readiness at a glance" className="mb-5 grid gap-4 rounded-lg border border-[var(--border-1)] bg-[var(--surface-1)] p-4 lg:grid-cols-3">
      <div><h2 className="text-sm font-semibold">Engineering</h2><p className="mt-1 text-sm">Dated delivery receipts below. The core package and worker have separate holds.</p><a href="#delivery-evidence" className="mt-2 inline-block text-sm text-[var(--accent)]">Changed / held / next evidence</a></div>
      <div><h2 className="text-sm font-semibold">Nara runtime</h2><p className="mt-1 text-sm">A channel message is runtime history. Engineering does not create a new Nara turn.</p><a href="/model-io" className="mt-2 inline-block text-sm text-[var(--accent)]">Inspect actual call records</a></div>
      <div><h2 className="text-sm font-semibold">Research</h2><p className="mt-1 text-sm">Recorded stages describe the ledger. They do not establish new evidence or market fit.</p><a href="/ladder" className="mt-2 inline-block text-sm text-[var(--accent)]">Open claims and evidence</a></div>
    </section>
    <div id="delivery-evidence" className="grid gap-4 lg:grid-cols-3">
      <Card title="Codex engineering / delivery" testId="development-engineering">
        <p className="font-medium">{uiReceipt.title}</p>
        <ul className="my-3 list-disc space-y-2 pl-5 text-sm">{uiReceipt.changes.map((change) => <li key={change}>{change}</li>)}</ul>
        <a href={uiReceipt.pr} target="_blank" rel="noreferrer" className="text-[var(--accent)]">Merged UI work — PR #5 ↗</a>
        <p className="mt-2 text-xs text-[var(--fg-muted)]">Dated UI observation: {uiReceipt.recordedAt}; not live deployment status.</p>
        <details className="mt-3 text-sm"><summary className="cursor-pointer">UI delivery evidence and limits</summary>
          <p className="mt-2">Merged {uiReceipt.mergedAt}. {uiReceipt.observation}</p>
          <p className="mt-2 break-all text-xs">UI source merge: {uiReceipt.merge}</p>
          <p className="mt-2">{uiReceipt.verification}</p>
        </details>
        <hr className="my-4 border-[var(--border-1)]" />
        <p className="text-sm font-medium">Earlier core package — PR #3 remains separate and held</p>
        <p className="mt-2 text-sm">The UI delivery does not merge the claim/attempt and execution components or clear their integration checks.</p>
        <details className="mt-3 text-sm"><summary className="cursor-pointer">Earlier package receipt and next evidence</summary>
          <p className="mt-2">{receipt.title}</p>
          <p className="mt-2 text-xs text-[var(--fg-muted)]">Static receipt recorded {receipt.recordedAt}; not live GitHub status.</p>
          <ul className="my-3 list-disc space-y-2 pl-5">{receipt.changes.map((change) => <li key={change}>{change}</li>)}</ul>
          <a href={receipt.pr} target="_blank" rel="noreferrer" className="text-[var(--accent)]">PR #3 package status ↗</a>
          <p className="mt-2 break-all text-xs">Published source at receipt: {receipt.head}</p>
          <p className="mt-3">{receipt.checks}</p>
          <p className="mt-3"><strong>Next evidence:</strong> {receipt.next}</p>
        </details>
        <p className="mt-3 text-sm"><strong>Held worker:</strong> {receipt.worker}</p>
        <details className="mt-4 text-sm"><summary className="cursor-pointer">Historical binding audit — separate from current counts</summary>
          <p className="mt-2">Recorded {receipt.audit.recordedAt}: {receipt.audit.iterations} historical iterations; {receipt.audit.bound} bound, {receipt.audit.mismatch} mismatch, {receipt.audit.unverifiable} unverifiable under the repaired envelope rule.</p>
          <p>This describes claim/evidence association. It does not mean the hypotheses are false or show today&apos;s ledger totals.</p>
          <p className="mt-2 break-all text-xs">Source-bound exposure SHA256: {receipt.audit.exposure}</p>
        </details>
      </Card>
      <Card title="Nara runtime / channel" testId="development-runtime">
        <p className="text-sm">Nara is the separate Gemma runtime agent. Codex engineering does not automatically post a Nara reply or dispatch a Qwen task.</p>
        {framedChannel ? <div className="my-3 space-y-2">
          <SourceTime label="Latest Nara message in loaded timeline" value={latest(channel.filter((r) => r.kind === "nara").map((r) => r.ts))} />
          <SourceTime label="Latest channel turn in loaded timeline" value={latest(channel.filter((r) => r.kind !== "event").map((r) => r.ts))} />
        </div> : <p className="my-3 text-sm text-[var(--status-warn)]">Actor-specific dates withheld: this backend has not provided verified structured framing. Legacy formatted text can contain actor-shaped message lines.</p>}
        <p className="text-xs text-[var(--fg-muted)]">Actor labels are recorded, not cryptographically authenticated. Structured framing preserves message boundaries; it does not attest ledger completeness.</p>
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
          <div className="overflow-x-auto"><table className="w-full text-left text-sm [&_th]:py-1 [&_th]:pr-3 [&_th]:align-top [&_td]:py-1 [&_td]:pr-3 [&_td]:align-top"><caption className="mb-2 text-left text-xs">Positions in the loaded ledger projection</caption>
            <thead><tr><th>Rung</th><th>Open</th><th>Surfaced</th><th>Killed</th><th>Recorded next test</th></tr></thead>
            <tbody>{["L0", "L1", "L2", "L3", "L4", "L5"].map((level) => <tr key={level}>
              <th>{level}</th>{["open", "surfaced", "killed"].map((status) => <td key={status}>{clusters.filter((c) => c.status === status && c.evidence_level === level).length}</td>)}
              <td className="text-xs">{isRecord(sources.ladder.data?.next_owed) ? text(sources.ladder.data.next_owed[level]) : "not reported"}</td>
            </tr>)}</tbody>
          </table></div>
          <p className="mt-2 text-xs">Other / unclassified: {clusters.filter((c) => !["open", "surfaced", "killed"].includes(text(c.status)) || !["L0", "L1", "L2", "L3", "L4", "L5"].includes(text(c.evidence_level))).length}</p>
          <SourceTime label="Latest recorded cluster event (not confirmation)" value={latest(clusters.map((c) => c.last_event_ts))} />
          <p className="text-xs text-[var(--fg-muted)]">Source: idea-ledger projection. Source file hash and cache age are not reported by this endpoint.</p>
        </> : <p className="my-3 text-sm">Recorded counts unavailable — no zero or historical snapshot substituted.</p>}
        <SourceState source={sources.ladder} />
        <a href="/ladder" className="mt-3 block text-[var(--accent)]">Inspect the ladder and next tests →</a>
        <hr className="my-4 border-[var(--border-1)]" />
        <p className="text-sm">Frontier proposals are suggestions until a human records a ruling. Acceptance onto the agenda is not a completed experiment.</p>
        {agendaStatusKnown ? <>
          <p className="my-2 text-sm">Loaded proposals: {unresolved.length} unresolved · {proposals.filter((p) => p.effective_status === "accepted").length} accepted · {proposals.filter((p) => p.effective_status === "dismissed").length} dismissed</p>
          <SourceTime label="Latest proposal in loaded feed" value={latest(proposals.map((p) => p.ts))} />
          {truncated && <p className="text-sm text-[var(--status-warn)]">Partial feed window — counts are not the complete agenda history.</p>}
          <details className="my-3 text-sm"><summary className="cursor-pointer">Older unresolved suggestions ({unresolved.length})</summary>
            <ul className="mt-2 list-disc space-y-2 pl-5">{unresolved.map((p) => <li key={String(p.proposal_id)}>{text(p.topic)} <span className="text-xs text-[var(--fg-muted)]">— {text(p.ts)}; {text(p.effective_status)}</span></li>)}</ul>
          </details>
        </> : <>
          <p className="my-2 text-sm text-[var(--status-warn)]">Agenda status is uncertain: complete ruling history and readable proposal-source metadata have not been established. No current unresolved, accepted or dismissed count is inferred.</p>
          <p className="text-sm">{proposals.length > 0
            ? `${proposals.length} proposal records in this observation; current rulings unverified.`
            : sources.frontier.data
              ? "No proposal records in this loaded window; source completeness and current rulings unverified — unresolved suggestions are not cleared."
              : "Proposal source unavailable or not reported — unresolved suggestions are not cleared."}</p>
          <details className="my-3 text-sm"><summary className="cursor-pointer">Suggestions with uncertain status ({proposals.length})</summary>
            <ul className="mt-2 list-disc space-y-2 pl-5">{proposals.map((p) => <li key={String(p.proposal_id)}>{text(p.topic)} <span className="text-xs text-[var(--fg-muted)]">— {text(p.ts)}; {isRecord(p.ruling) ? `last observed ruling: ${text(p.ruling.status)}` : `proposal record: ${text(p.status)}`}; current status unverified</span></li>)}</ul>
          </details>
        </>}
        {integrityErrors.length > 0 && <p role="status" className="text-sm text-[var(--status-warn)]">Source integrity errors: {integrityErrors.join("; ")}</p>}
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
