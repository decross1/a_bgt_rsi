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
const PILOT_ID = "qfn-followon-known-opponent-lab8h-a";
const BRIDGE_SCHEMA = "guarded-research-attempts-observation/v1";
const bridgeIds = ["d", "c", "b", "a"].map(arm =>
  "qfn-followon-known-opponent-lab8h-bridge-" + arm);
const bridgeStatuses = new Set(["no_terminal_receipt", "source_unavailable",
  "incomplete", "guard_recorded_final_unverified", "guard_recorded_final_bound"]);
const bridgeRestore = new Set(["unknown", "guard_verified_parent_unverified",
  "guard_and_parent_verified"]);
const bridgeFinal = new Set(["unknown", "absent", "unverified", "bound"]);
const boundSha = (value: unknown) => value === null ||
  (typeof value === "string" && SHA.test(value));
function guardedRows(value: unknown): Record<string, unknown>[] | null {
  if (!obj(value) || value.schema_version !== BRIDGE_SCHEMA ||
      !utc(value.observed_at) || Date.now() - Date.parse(value.observed_at) < 0 ||
      Date.now() - Date.parse(value.observed_at) > 120_000 ||
      value.current_source_replay !== "not_performed" ||
      value.scientific_admission_claimed !== false ||
      value.private_content_exported !== false ||
      value.source_status !== "available" ||
      !Array.isArray(value.attempts) || value.attempts.length !== 4) return null;
  const rows = value.attempts;
  if (!rows.every((row: unknown, index: number) => {
    if (!obj(row) || row.window_id !== bridgeIds[index] ||
        !bridgeStatuses.has(String(row.terminal_status)) ||
        !bridgeRestore.has(String(row.restoration_status)) ||
        !bridgeFinal.has(String(row.final_record_status)) ||
        row.scientific_admission_claimed !== false ||
        !boundSha(row.result_raw_sha256) || !boundSha(row.state_raw_sha256) ||
        !boundSha(row.plan_raw_sha256) ||
        !boundSha(row.parent_emergency_raw_sha256) ||
        !boundSha(row.partial_audit_raw_sha256) ||
        !boundSha(row.loop_memory_raw_sha256) ||
        !boundSha(row.journal_raw_sha256)) return false;
    const status = String(row.terminal_status);
    if (status === "no_terminal_receipt" || status === "source_unavailable")
      return row.final_record_status === "unknown" && row.restoration_status === "unknown" &&
        row.result_raw_sha256 === null && row.state_raw_sha256 === null &&
        row.plan_raw_sha256 === null && row.partial_prompt_receipts === null &&
        row.parent_emergency_raw_sha256 === null &&
        row.partial_audit_raw_sha256 === null && row.iteration_id === null &&
        row.loop_memory_raw_sha256 === null && row.journal_raw_sha256 === null;
    if (!utc(row.started_at) || !utc(row.finished_at) ||
        !SHA.test(String(row.result_raw_sha256)) ||
        !SHA.test(String(row.state_raw_sha256)) ||
        !SHA.test(String(row.plan_raw_sha256))) return false;
    if (status === "incomplete")
      return row.final_record_status === "absent" &&
        (row.restoration_status === "guard_verified_parent_unverified" ||
         row.restoration_status === "guard_and_parent_verified") &&
        row.iteration_id === null && row.loop_memory_raw_sha256 === null &&
        row.journal_raw_sha256 === null &&
        (row.partial_prompt_receipts === null ||
         (index === 2 && row.partial_prompt_receipts === 15 &&
          SHA.test(String(row.partial_audit_raw_sha256))));
    if (index !== 0 || !ID.test(String(row.iteration_id))) return false;
    if (row.restoration_status !== "guard_verified_parent_unverified" ||
        row.parent_emergency_raw_sha256 !== null ||
        row.partial_prompt_receipts !== null ||
        row.partial_audit_raw_sha256 !== null) return false;
    return status === "guard_recorded_final_bound"
      ? row.final_record_status === "bound" &&
        SHA.test(String(row.loop_memory_raw_sha256)) &&
        SHA.test(String(row.journal_raw_sha256))
      : row.final_record_status === "unverified" &&
        row.loop_memory_raw_sha256 === null && row.journal_raw_sha256 === null;
  })) return null;
  const latest = rows.find((row: Record<string, unknown>) =>
    row.terminal_status !== "no_terminal_receipt" &&
    row.terminal_status !== "source_unavailable")?.window_id ?? null;
  return value.latest_terminal_window_id === latest ? rows : null;
}
function guardedLabel(row: Record<string, unknown>): string {
  switch (row.terminal_status) {
    case "no_terminal_receipt": return "No terminal receipt observed; outcome unknown";
    case "source_unavailable": return "Public attempt source unavailable; outcome withheld";
    case "incomplete":
      return row.restoration_status === "guard_and_parent_verified"
        ? "Incomplete; guard and parent verified restoration; no final research record"
        : "Incomplete; guard recorded restoration, parent recovery unverified; no final research record";
    case "guard_recorded_final_bound":
      return "Guard recorded and restored; final iteration record bound to loop memory and journal";
    default:
      return "Guard recorded and restored; final iteration record unverified";
  }
}
const PAYOFF_SCHEMA = "registered-payoff-jobs-observation/v1";
const payoffJobs = [
  { job_id: "payoff-representation-a", panel_id: "payoff-representation-a",
    not_before: "2026-09-15T19:00:00+00:00", expires_at: "2026-09-16T00:00:00+00:00",
    role: "first_fresh_payoff_representation_diagnostic", label: "A · first fresh input" },
  { job_id: "payoff-representation-b", panel_id: "payoff-representation-b",
    not_before: "2026-09-16T03:30:00+00:00", expires_at: "2026-09-16T08:00:00+00:00",
    role: "fresh_input_followup_not_same_prompt_reseed", label: "B · fresh-input follow-up" },
] as const;
const payoffStates = new Set(["not_due", "eligible_unprepared", "eligible_prepared", "prepared_unverified",
  "attempt_reserved_or_recorded", "zero_call_refusal_retry_eligible", "zero_call_refusal_retry_prepared",
  "expired_after_zero_call_refusal", "expired_unattempted", "admission_receipt_present_unverified",
  "admitted_attempt_verified"]);
const payoffRefusalCodes = new Set(["resource_lease_busy", "resource_probe_blocked", "availability_unknown"]);
const payoffRefusalValid = (v: unknown) => v === null ||
  (obj(v) && ((v.status === "receipt_present_unverified" && Object.keys(v).length === 1) ||
    (Object.keys(v).sort().join() === "failure_code,receipt_sha256,refused_at" &&
      typeof v.failure_code === "string" && payoffRefusalCodes.has(v.failure_code) &&
      SHA.test(String(v.receipt_sha256)) && utc(v.refused_at))));
const payoffRefusalText = (v: unknown) => {
  if (!obj(v)) return null;
  if (v.status === "receipt_present_unverified") return "Availability refusal receipt present; verification unavailable.";
  if (v.failure_code === "resource_lease_busy") return "Last no-call availability refusal: coordinator lease busy at " + stamp(v.refused_at) + ".";
  if (v.failure_code === "resource_probe_blocked") return "Last no-call availability refusal: resource probe blocked at " + stamp(v.refused_at) + ".";
  return "Last no-call availability refusal: availability unknown at " + stamp(v.refused_at) + ".";
};
const payoffState = (state: string) => ({
  not_due: "Not due",
  eligible_unprepared: "In window; preparation absent",
  eligible_prepared: "Prepared and eligible",
  prepared_unverified: "Preparation unverified",
  attempt_reserved_or_recorded: "Attempt reserved or recorded",
  zero_call_refusal_retry_eligible: "Proven zero-call refusal; retry eligible",
  zero_call_refusal_retry_prepared: "Proven zero-call refusal; retry prepared",
  expired_after_zero_call_refusal: "Window expired after zero-call refusal",
  expired_unattempted: "Window expired unattempted",
  admission_receipt_present_unverified: "Admission receipt present; replay unverified",
  admitted_attempt_verified: "Admitted attempt verified at last queue check",
} as Record<string, string>)[state] ?? "State unknown";

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
  const empirical = obj(view?.empirical_pilot) ? view.empirical_pilot : null;
  const payoff = obj(view?.payoff_jobs) ? view.payoff_jobs : null;
  const bridges = guardedRows(view?.guarded_research_attempts);
  const bridgeLatest = bridges?.find(row =>
    row.terminal_status !== "no_terminal_receipt" &&
    row.terminal_status !== "source_unavailable") ?? null;
  const payoffCheckedMs = payoff && utc(payoff.checked_at) ? Date.parse(String(payoff.checked_at)) : Number.NaN;
  const payoffCheckFresh = Number.isFinite(payoffCheckedMs) &&
    Date.now() - payoffCheckedMs >= 0 && Date.now() - payoffCheckedMs <= 360_000;
  const payoffRows = payoff && payoff.schema_version === PAYOFF_SCHEMA &&
    payoff.source_status === "available" && payoff.timer_activation === "not_verified" &&
    payoff.comparison_eligible === false && SHA.test(String(payoff.queue_source_sha256)) &&
    payoffCheckFresh && Array.isArray(payoff.jobs) && payoff.jobs.length === 2 &&
    payoff.jobs.every((row: unknown, index: number) => {
      const expected = payoffJobs[index];
      return obj(row) && row.job_id === expected.job_id && row.panel_id === expected.panel_id &&
        row.not_before === expected.not_before && row.expires_at === expected.expires_at &&
        row.role === expected.role && typeof row.state === "string" && payoffStates.has(row.state) &&
        (row.attempt_index === 0 || row.attempt_index === 1) &&
        typeof row.prepared_window_present === "boolean" && row.comparison_eligible === false &&
        payoffRefusalValid(row.last_availability_refusal);
    }) ? payoff.jobs as Record<string, unknown>[] : null;

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
      workCode === "freeze_and_run_registered_empirical_study" ||
      workCode === "review_admitted_empirical_pilot");
  const pilotRecorded = empirical && empirical.status === "recorded_admitted" &&
    ID.test(String(empirical.window_id)) && SHA.test(String(empirical.admission_receipt_sha256)) &&
    SHA.test(String(empirical.pilot_run_sha256)) && count(empirical.attempted_calls) &&
    empirical.attempted_calls <= 108 && count(empirical.complete_episodes) &&
    empirical.complete_episodes <= 12 && empirical.current_source_replay === "not_performed";
  const pilotAdmitted = pilotRecorded &&
    plannedWork?.pilot_admission_receipt_sha256 === empirical.admission_receipt_sha256;
  const behavior = obj(empirical?.behavior_summary) ? empirical.behavior_summary : null;
  const byUtility = obj(behavior?.by_utility) ? behavior.by_utility : null;
  const own = obj(byUtility?.own_payoff) ? byUtility.own_payoff : null;
  const joint = obj(byUtility?.joint_payoff) ? byUtility.joint_payoff : null;
  const behaviorBound = pilotRecorded && empirical?.window_id === PILOT_ID && behavior &&
    count(empirical.attempted_calls) && count(empirical.complete_episodes) &&
    behavior.schema_version === "known-opponent-pilot-behavior/v1" &&
    behavior.admission_receipt_sha256 === empirical.admission_receipt_sha256 &&
    behavior.pilot_run_sha256 === empirical.pilot_run_sha256 &&
    SHA.test(String(behavior.manifest_raw_sha256)) &&
    behavior.current_source_replay === "not_performed" &&
    behavior.theory_accepted === false && behavior.strategy_causal_claim === false &&
    behavior.scheduled_action_calls === 96 && count(behavior.valid_action_calls) &&
    behavior.valid_action_calls <= 96 && behavior.valid_action_calls <= empirical.attempted_calls &&
    behavior.complete_episodes === empirical.complete_episodes &&
    count(behavior.zero_regret_complete_episodes) &&
    behavior.zero_regret_complete_episodes <= empirical.complete_episodes &&
    behavior.comprehension_scheduled_episodes === 12 &&
    count(behavior.comprehension_passed) &&
    behavior.comprehension_passed <= empirical.complete_episodes &&
    behavior.comprehension_prompt_forms === 2 && behavior.form_repetitions_each === 6 &&
    byUtility && Object.keys(byUtility).sort().join() === "joint_payoff,own_payoff" &&
    own && joint && count(own.complete) && count(joint.complete) &&
    own.complete <= 6 && joint.complete <= 6 &&
    count(own.zero_regret) && count(joint.zero_regret) &&
    own.zero_regret <= own.complete && joint.zero_regret <= joint.complete &&
    own.complete + joint.complete === empirical.complete_episodes &&
    own.zero_regret + joint.zero_regret === behavior.zero_regret_complete_episodes;
  const successorWork = plannedWork && workCode === "activate_registered_successor" &&
    plannedWork.activation_required === true && nextId === plannedWork.campaign_id &&
    next?.manifest_sha256 === plannedWork.manifest_sha256;
  const linked = iteration && iteration.kind === "campaign_iteration_recorded" && ID.test(String(iteration.iteration_id)) &&
    ID.test(String(iteration.topic_id)) && utc(iteration.at) && SHA.test(String(iteration.loop_source_sha256)) ? iteration : null;
  const linkedGate = linked && ["pending", "blocked", "passed", "failed"].includes(String(linked.gate_status))
    ? String(linked.gate_status) : "unknown";
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
  else if (registeredWork && workCode === "review_admitted_empirical_pilot" && pilotAdmitted &&
           ID.test(String(plannedWork.study_id)) && SHA.test(String(plannedWork.preregistration_sha256)))
    nextWork = `Review admitted binary pilot ${String(plannedWork.study_id)}`;
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
          {linked && <dd className="mt-1 text-xs text-[var(--fg-muted)]">Review gate: {linkedGate}. A linked iteration does not itself establish an accepted finding.</dd>}
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
        {pilotRecorded && <div className="rounded border border-[var(--border-1)] p-3">
          <dt className="font-semibold">Recorded binary pilot</dt>
          <dd className="mt-1">{String(empirical?.complete_episodes)} complete episodes, {String(empirical?.attempted_calls)} attempted calls</dd>
          {behaviorBound && <dd className="mt-1 text-xs text-[var(--fg-muted)]">
            Action syntax: {String(behavior?.valid_action_calls)}/96 scheduled actions valid. Zero regret: {String(behavior?.zero_regret_complete_episodes)}/{String(behavior?.complete_episodes)} complete episodes
            {" "}({String(own?.zero_regret)}/{String(own?.complete)} own-payoff; {String(joint?.zero_regret)}/{String(joint?.complete)} joint-payoff).
            Comprehension: {String(behavior?.comprehension_passed)}/12 episodes correct, using two prompt forms repeated six times each. These are descriptive checks, not 12 independent questions.
          </dd>}
          <dd className="mt-1 text-xs text-[var(--fg-muted)]">Current source replay was not performed. The continuous-weight hypothesis remains unconfirmed; no strategic causal claim is made.</dd>
        </div>}
        <div className="rounded border border-[var(--border-1)] p-3">
          <dt className="font-semibold">Guarded research attempts</dt>
          {bridges ? <>
            <dd className="mt-1 text-xs text-[var(--fg-muted)]">Historical attempt receipts; current serving health and last linked campaign iteration are separate.</dd>
            {bridgeLatest && <dd className="mt-1 text-xs text-[var(--fg-muted)]">
              Latest terminal observation {String(bridgeLatest.window_id).slice(-1).toUpperCase()} · {stamp(bridgeLatest.finished_at)}.
            </dd>}
            {bridges.map((row, index) => <dd key={bridgeIds[index]} className="mt-2">
              <span className="font-medium">{bridgeIds[index].slice(-1).toUpperCase()}</span>: {guardedLabel(row)}.
              {row.partial_prompt_receipts === 15 && <span className="block text-xs text-[var(--fg-muted)]">
                A result/state-bound partial audit reports 15 prompt receipts; no empirical or scientific result was admitted.
              </span>}
              {row.terminal_status === "guard_recorded_final_bound" && <span className="block text-xs text-[var(--fg-muted)]">
                This verifies a final record's presence, not acceptance of its scientific claim.
              </span>}
            </dd>)}
          </> : <dd className="mt-1">Guarded attempt receipts unavailable or unbound; outcomes withheld.</dd>}
        </div>
        <div className="rounded border border-[var(--border-1)] p-3">
          <dt className="font-semibold">Registered payoff jobs</dt>
          {payoffRows ? payoffRows.map((job, index) => <dd key={payoffJobs[index].job_id} className="mt-2">
            <span className="font-medium">{payoffJobs[index].label}</span>: {payoffState(String(job.state))}.
            <span className="block text-xs text-[var(--fg-muted)]">Registered execution interval {stamp(job.not_before)}–{stamp(job.expires_at)}.</span>
            {payoffRefusalText(job.last_availability_refusal) && <span className="block text-xs text-[var(--fg-muted)]">{payoffRefusalText(job.last_availability_refusal)}</span>}
          </dd>) : <dd className="mt-1">
            {payoff?.schema_version === PAYOFF_SCHEMA && payoff?.source_status === "package_unavailable" &&
             payoff?.timer_activation === "not_verified" && payoffCheckFresh
              ? "Payoff job package unavailable; queue readiness is unknown." :
             "Payoff queue observation unavailable or stale; job readiness is unknown."}
          </dd>}
          {payoffRows && <dd className="mt-2 text-xs text-[var(--fg-muted)]">Last source-bound queue check {stamp(payoff?.checked_at)}. These are two finite empirical jobs, not automatically dispatched tasks.</dd>}
          <dd className="mt-1 text-xs text-[var(--fg-muted)]">Timer activation is not verified by queue readiness; preparation alone does not establish execution.</dd>
        </div>
      </dl>}
    <div className="mt-3 flex flex-wrap gap-4 text-sm"><Link to="/cycles" className="text-[var(--accent)]">Trace history →</Link>
      <Link to="/benchmarks" className="text-[var(--accent)]">Research follow-through →</Link></div>
  </section>;
}
