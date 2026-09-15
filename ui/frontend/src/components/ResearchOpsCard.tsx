/** Source-bound campaign operations; scientific scores live in Benchmark Progress. */
import { Link } from "react-router-dom";

const SHA = /^[0-9a-f]{64}$/;
const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$/;
const obj = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);
const count = (v: unknown): v is number => typeof v === "number" && Number.isInteger(v) && v >= 0 && v <= 100_000;
const utc = (v: unknown): v is string => typeof v === "string" && v.length <= 48 &&
  (v.endsWith("Z") || v.endsWith("+00:00")) && Number.isFinite(Date.parse(v));
const stamp = (v: unknown) => utc(v)
  ? `${new Date(v).toLocaleString("en-US", { timeZone: "UTC", dateStyle: "medium", timeStyle: "short" })} UTC`
  : "Time unknown";
const queues = new Set(["eligible", "all_registered_topics_consumed", "source_unknown", "unknown"]);
const attempts = new Set(["succeeded", "fetch_failed", "embed_failed", "interrupted_unknown", "none", "unknown"]);

export function ResearchOpsCard({ data, failing = false }: { data: unknown; failing?: boolean }) {
  const observedMs = obj(data) && utc(data.observed_at) ? Date.parse(data.observed_at) : Number.NaN;
  const fresh = Number.isFinite(observedMs) && Date.now() - observedMs >= 0 && Date.now() - observedMs <= 120_000;
  const view = obj(data) && data.schema === "research-ops-status/v1" && fresh && !failing ? data : null;
  const campaign = obj(view?.active_campaign) ? view.active_campaign : null;
  const queue = obj(view?.campaign_queue) ? view.campaign_queue : null;
  const next = obj(view?.next_registered_campaign) ? view.next_registered_campaign : null;
  const plannedWork = obj(view?.next_work) ? view.next_work : null;
  const iteration = obj(view?.last_productive) ? view.last_productive : null;
  const cycle = obj(view?.last_cycle) ? view.last_cycle : null;
  const budget = obj(view?.budget) ? view.budget : null;
  const gate = obj(view?.dispatch_gate) ? view.dispatch_gate : null;
  const ingestion = obj(view?.ingestion) ? view.ingestion : null;
  const legacy = obj(view?.ingestion_legacy_log) ? view.ingestion_legacy_log : null;

  const campaignId = campaign && ID.test(String(campaign.campaign_id)) && SHA.test(String(campaign.manifest_sha256)) ? String(campaign.campaign_id) : null;
  const queueStatus = queue && typeof queue.status === "string" && queues.has(queue.status) &&
    (queue.status === "source_unknown" || queue.status === "unknown" || SHA.test(String(queue.loop_source_sha256))) ? queue.status : "unknown";
  const eligible = queue && count(queue.eligible_count) ? queue.eligible_count : null;
  const consumed = queue && count(queue.consumed_count) ? queue.consumed_count : null;
  const nextId = next && next.activation_required === true && ID.test(String(next.campaign_id)) &&
    SHA.test(String(next.manifest_sha256)) && count(next.registered_topic_count) ? String(next.campaign_id) : null;
  const workCode = plannedWork && typeof plannedWork.code === "string" ? plannedWork.code : "source_unknown";
  const registeredWork = plannedWork && plannedWork.activation_required === false &&
    campaignId === plannedWork.campaign_id && campaign?.manifest_sha256 === plannedWork.manifest_sha256 &&
    (workCode === "run_preregistered_campaign_topic" ||
      workCode === "freeze_and_run_registered_empirical_study");
  const successorWork = plannedWork && workCode === "activate_registered_successor" &&
    plannedWork.activation_required === true && nextId === plannedWork.campaign_id &&
    next?.manifest_sha256 === plannedWork.manifest_sha256;
  const linked = iteration && iteration.kind === "campaign_iteration_recorded" && ID.test(String(iteration.iteration_id)) &&
    ID.test(String(iteration.topic_id)) && utc(iteration.at) && SHA.test(String(iteration.loop_source_sha256)) ? iteration : null;
  const boundCycle = cycle && ID.test(String(cycle.run_id)) && utc(cycle.at) && SHA.test(String(cycle.raw_row_sha256)) &&
    SHA.test(String(cycle.cycles_source_sha256)) && count(cycle.planned_count) && count(cycle.dispatched_count) &&
    count(cycle.outcome_count) && (cycle.action_code === "noop" || cycle.action_code === "actions_planned") &&
    cycle.dispatched_count <= cycle.planned_count ? cycle : null;
  const budgetBound = budget && budget.source_status === "available" && count(budget.spent_today) &&
    count(budget.daily_cap) && count(budget.paced_allowance) && SHA.test(String(budget.ledger_sha256));
  const ingestionBound = ingestion?.source_status === "available";
  const attempt = ingestionBound && typeof ingestion?.latest_attempt_status === "string" &&
    attempts.has(ingestion.latest_attempt_status) ? ingestion.latest_attempt_status : "unknown";
  const success = ingestionBound && utc(ingestion?.last_success_at) &&
    SHA.test(String(ingestion?.last_success_input_sha256)) && SHA.test(String(ingestion?.last_success_pointer_sha256))
    ? ingestion.last_success_at : null;
  const legacyObserved = legacy && legacy.receipt_bound === false && utc(legacy.started_at) &&
    SHA.test(String(legacy.log_sha256)) &&
    ["source_unknown", "succeeded_log_observed", "fetch_failed_log_observed", "interrupted_unknown"].includes(String(legacy.status)) &&
    Array.isArray(legacy.http_codes_observed) && legacy.http_codes_observed.length <= 2 &&
    legacy.http_codes_observed.every((code: unknown) => code === "429" || code === "503") &&
    count(legacy.retry_count_observed) && legacy.retry_count_observed <= 6 ? legacy : null;

  let nextWork = "Next topic work is unknown";
  if (gate?.operator_pause === true) nextWork = "Coordinator paused";
  else if (successorWork) nextWork = `Activate registered successor ${nextId}`;
  else if (registeredWork && workCode === "freeze_and_run_registered_empirical_study" &&
           ID.test(String(plannedWork.study_id)) && SHA.test(String(plannedWork.preregistration_sha256)))
    nextWork = `Freeze and run registered study ${String(plannedWork.study_id)}`;
  else if (registeredWork && workCode === "run_preregistered_campaign_topic" &&
           ID.test(String(plannedWork.topic_id)) && eligible !== null && eligible > 0)
    nextWork = `Run registered topic ${String(plannedWork.topic_id)}`;
  else if (queueStatus === "eligible" && eligible !== null && eligible > 0)
    nextWork = `${eligible} registered topic${eligible === 1 ? "" : "s"} eligible`;
  else if (queueStatus === "all_registered_topics_consumed" && eligible === 0)
    nextWork = "All topics in this campaign have been used";
  else if (queueStatus === "source_unknown") nextWork = "Campaign queue source unverified";

  let ingestionText = "Source attempt status unknown";
  if (attempt === "succeeded") ingestionText = "Latest source attempt succeeded";
  else if (attempt === "fetch_failed") ingestionText = "Latest source fetch failed";
  else if (attempt === "embed_failed") ingestionText = "Latest source embedding failed";
  else if (attempt === "interrupted_unknown") ingestionText = "Latest source attempt stopped; result unknown";
  else if (attempt === "none") ingestionText = "No receipt-bound source attempt yet";

  return <section data-testid="research-ops-card" aria-labelledby="research-ops-heading"
    className="mb-4 rounded-lg border border-[var(--border-1)] bg-[var(--surface-1)] p-4">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><p className="text-xs font-semibold uppercase tracking-wide text-[var(--fg-muted)]">Research operations</p>
        <h2 id="research-ops-heading" className="mt-1 text-lg font-semibold">Research work status</h2>
        <p className="mt-1 text-sm text-[var(--fg-muted)]">Topic availability, coordinator plans, actual dispatch, and source collection have separate records.</p>
      </div>
      <span className="rounded border border-[var(--border-2)] px-2 py-1 text-xs">{view ? "Recorded observation" : "Current observation unavailable"}</span>
    </div>
    {!view ? <p className="mt-4 text-sm text-[var(--fg-muted)]">Current research operations and ingestion are unknown. System health and historical traces remain separate.</p>
      : <dl className="mt-4 grid gap-3 text-sm md:grid-cols-2">
        <div className="rounded border border-[var(--border-1)] p-3"><dt className="font-semibold">Next campaign work</dt>
          <dd className="mt-1">{nextWork}</dd>
          {successorWork || registeredWork ? <dd className="mt-1 text-xs text-[var(--fg-muted)]">Registered next step; no task dispatch is implied.</dd> : null}
          {campaignId && <dd className="mt-1 text-xs text-[var(--fg-muted)]">Active campaign {campaignId}{consumed !== null ? ` · ${consumed} topics used` : ""}</dd>}
          {nextId && <dd className="mt-1 text-xs text-[var(--fg-muted)]">Next registered campaign {nextId} awaits activation.</dd>}
          {queueStatus === "all_registered_topics_consumed" && gate?.other_actionable_work === "not_assessed" &&
            <dd className="mt-1 text-xs text-[var(--fg-muted)]">Other useful research actions have not been assessed here.</dd>}
        </div>
        <div className="rounded border border-[var(--border-1)] p-3"><dt className="font-semibold">Last linked campaign iteration</dt>
          <dd className="mt-1">{linked ? `${String(linked.iteration_id)} · ${stamp(linked.at)}` : "No linked iteration verified in this observation"}</dd>
          {linked && <dd className="mt-1 text-xs text-[var(--fg-muted)]">Topic {String(linked.topic_id)}</dd>}
        </div>
        <div className="rounded border border-[var(--border-1)] p-3"><dt className="font-semibold">Latest coordinator cycle</dt>
          <dd className="mt-1">{boundCycle ? `${boundCycle.action_code === "noop" ? "No-op plan" : "Plan recorded"} · ${String(boundCycle.planned_count)} planned · ${String(boundCycle.dispatched_count)} dispatched` : "No bound coordinator check"}</dd>
          {boundCycle && <dd className="mt-1 text-xs text-[var(--fg-muted)]">{stamp(boundCycle.at)} · {String(boundCycle.run_id)}</dd>}
          {budgetBound && <dd className="mt-1 text-xs text-[var(--fg-muted)]">Today's coordinator allowance: {String(budget.spent_today)}/{String(budget.daily_cap)} used; {String(budget.paced_allowance)} paced so far.</dd>}
        </div>
        <div className="rounded border border-[var(--border-1)] p-3"><dt className="font-semibold">Source ingestion</dt>
          <dd className="mt-1">{ingestionText}</dd>
          <dd className="mt-1 text-xs text-[var(--fg-muted)]">Last receipt-bound success: {success ? stamp(success) : "not verified"}</dd>
          {legacyObserved && <dd className="mt-1 text-xs text-[var(--fg-muted)]">
            {legacyObserved.status === "fetch_failed_log_observed" ? "Legacy log observed a failed fetch" :
             legacyObserved.status === "succeeded_log_observed" ? "Legacy log suggests a completed attempt" :
             "Legacy log attempt outcome unknown"} at {stamp(legacyObserved.started_at)}.
            {legacyObserved.status === "fetch_failed_log_observed" &&
              ` HTTP ${(legacyObserved.http_codes_observed as string[]).join("/")}; ${legacyObserved.retry_count_observed} retries.`}
            {" "}No receipt-bound source result is established by this log.
          </dd>}
        </div>
      </dl>}
    <div className="mt-3 flex flex-wrap gap-4 text-sm"><Link to="/cycles" className="text-[var(--accent)]">Trace history →</Link>
      <Link to="/benchmarks" className="text-[var(--accent)]">Research follow-through →</Link></div>
  </section>;
}
