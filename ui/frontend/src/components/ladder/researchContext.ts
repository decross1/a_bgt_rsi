import type { LadderCluster } from "../../types/schemas";
import type {
  FamilyRecord,
  RecordedIteration,
  ThesisFamily,
} from "./thesisModel";

interface ExactClaimNote {
  clusterId: string;
  hypothesis: string;
  shortLabel: string;
  summary: string;
  claimHash: string;
  rawRowHash: string;
  sourceLine: number;
  recordedLevelAt: string;
  latestReviewAt: string;
  limitations: string[];
  blocker: string;
  proposedTest: string;
  proposedDecision: string;
}

export interface ResearchEvidenceLine {
  label: string;
  text: string;
}

export interface ResearchClaimContext {
  key: string;
  record: FamilyRecord;
  iteration?: RecordedIteration;
  iterationId: string;
  hypothesis: string;
  topic: string;
  shortLabel: string;
  summary: string;
  sourceEndedAt: string;
  recordedEventAt: string;
  latestReviewAt?: string;
  claimHash?: string;
  rawRowHash?: string;
  sourceLine?: number;
  isPinnedExactClaim: boolean;
  claimStanding: string;
  applicationFit: string;
  evidenceValidity: string;
  executionMode: string;
  evidenceDelta: string;
  supportingEvidence: ResearchEvidenceLine[];
  limitingEvidence: ResearchEvidenceLine[];
  rawOutcome: ResearchEvidenceLine[];
  blocker: string;
  proposedTest?: string;
  decision: string;
  stageRequirement?: string;
}

const GAP_GINI =
  "In a liquid democracy model, a smaller spectral gap in the delegation transition matrix results in higher transient variance of the Gini coefficient during the convergence phase towards the stationary distribution.";
const CLUSTER_MINORITY =
  "In liquid democracy networks, high local clustering coefficients decrease the effective representation of minority nodes by concentrating delegated weight through reinforced transitive paths, rather than diluting it through redundancy.";
const CENTRALITY_VOLATILITY =
  "In liquid democracy networks, an increase in the eigenvector centrality of a subset of delegates leads to higher systemic volatility because the rapid convergence of delegated weights reduces the time-to-equilibrium following stochastic preference shifts.";

// These notes are a dated, source-grounded presentation of LAB022/LAB024.
// They are selected only by the exact iteration ID AND exact hypothesis bytes.
// LAB024 is closed/held and the proposed tests below are not an adopted protocol.
const EXACT_CLAIMS: Record<string, ExactClaimNote> = {
  "iter-2026-08-16-003": {
    clusterId: "cl-iter-2026-08-16-003",
    hypothesis: GAP_GINI,
    shortLabel: "Spectral gap → transient Gini variance",
    summary: "Whether slower delegation-matrix mixing raises transient inequality variance during convergence.",
    claimHash: "917d176d2efc6e5754ae1600e1e1b397f3fe0e8cb8474e88c4e2e23ab434bd77",
    rawRowHash: "986a3eb5b265cfaa2c1dd515624b45aed3892dbd652ebd2d1683ef9c5350aa47",
    sourceLine: 112,
    recordedLevelAt: "2026-08-16T02:03:28.689931Z",
    latestReviewAt: "2026-09-06T15:41:30.626927Z",
    limitations: [
      "A 2026-09-05 analytical preflight supplied a conditional counterexample: in its admitted P(g) matrix family and fixed horizon, a smaller gap produced lower two-time Gini variance. Its applicability to other liquid-democracy models remains unknown.",
      "2026-09-06 automated frontier review, inspected in the 2026-09-07 source assessment: no bound outcome, comparison, graph ensemble, or controls were recorded. This is model-authored attention evidence, not a human scientific ruling.",
    ],
    blocker: "2026-09-07 source assessment: define the admissible delegation dynamics, matrix class, variance estimand, initialization and horizon, then resolve whether the conditional counterexample applies. That snapshot did not establish exact claim/spec/result binding.",
    proposedTest: "First decide whether the model admits P(g)=(1-g)I+gJ/n. If a narrower model is chosen, create a linked new claim and compare low/high gaps under the same stationary distribution, initialization, horizon and preregistered Gini estimand.",
    proposedDecision: "2026-09-07 proposal: pause application work pending the model/estimand decision. No human scientific disposition was recorded by that assessment.",
  },
  "iter-2026-08-17-014": {
    clusterId: "cl-iter-2026-08-17-014",
    hypothesis: CLUSTER_MINORITY,
    shortLabel: "Clustering → minority representation",
    summary: "Whether local clustering reinforces delegated-weight concentration and lowers minority representation.",
    claimHash: "48c2d45ae1a9426953f8313f83e4381b11a3057a734a3cbbddac475c105bd148",
    rawRowHash: "6398190e6435cab50d402726728965ac845f5a077ecdfa8ad9c2eb9492b5f4f6",
    sourceLine: 142,
    recordedLevelAt: "2026-08-17T05:00:14.365960Z",
    latestReviewAt: "2026-09-06T16:16:05.785832Z",
    limitations: [
      "The recorded critic rationale discusses spectral gap and Shapley weighting rather than the exact clustering/minority-representation mechanism; the red-team proceed was defaulted after a schema mismatch.",
      "2026-09-06 automated frontier review, inspected in the 2026-09-07 source assessment: no network experiment, baseline, minority-representation measure, or reinforcement-versus-redundancy ablation was recorded. This is not a human ruling.",
    ],
    blocker: "2026-09-07 source assessment: define the contact versus delegation graph, resolver and cycle rules, minority membership and representation endpoint, and controls for degree, homophily and chain depth. That bounded registry inspection found no compatible driver.",
    proposedTest: "Use paired degree- and homophily-controlled rewiring to vary local clustering, preregister a minority-representation endpoint, and disable the asserted multi-path reinforcement as an ablation. Refuse the mapping if the chosen delegation rule has no reinforcement mechanism.",
    proposedDecision: "2026-09-07 proposal: pause until the graph, resolver, endpoint and compatible driver are defined. A failed application mapping would leave the scientific question separate.",
  },
  "iter-2026-08-24-006": {
    clusterId: "cl-iter-2026-08-24-006",
    hypothesis: CENTRALITY_VOLATILITY,
    shortLabel: "Centrality → convergence → volatility",
    summary: "Whether concentrated delegate centrality shortens settling time and thereby raises a separate post-shock volatility outcome.",
    claimHash: "2985b0ce6c9091e9888d552e3e2e8437dae99900de6a79cc2d31d1f29cfc2a7b",
    rawRowHash: "74d9a53167064b8b5c26d3d704ed3c37a3aba36cb385ce716631f5cc612195e8",
    sourceLine: 210,
    recordedLevelAt: "2026-08-24T09:12:46.387744Z",
    latestReviewAt: "2026-09-06T16:16:05.785832Z",
    limitations: [
      "The recorded red-team review warns that faster convergence and volatility are distinct and that the volatility outcome is undefined.",
      "2026-09-06 automated frontier review, inspected in the 2026-09-07 source assessment: centrality, topology, power concentration, shocks and update rate were not separated. This is model-authored attention evidence, not a human ruling.",
    ],
    blocker: "2026-09-07 source assessment: define centrality exposure, the shock process, settling time and a separate volatility outcome, then establish whether the proposed matched intervention and causal mediation are feasible.",
    proposedTest: "Under matched topology controls and identical shocks, vary delegate-centrality concentration and measure both settling time and a distinct volatility endpoint. Cross this with an independently controlled smoothing/update rate; reject a design that defines volatility as convergence speed.",
    proposedDecision: "2026-09-07 proposal: pause until the two causal links, outcomes and matched intervention are identifiable. That assessment recorded no market or human scientific disposition.",
  },
};

function asRecord(value: unknown): Readonly<Record<string, unknown>> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Readonly<Record<string, unknown>>
    : null;
}

function asText(value: unknown): string | null {
  if (typeof value === "string" && value.trim().length > 0) return value;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  if (typeof value === "boolean") return String(value);
  return null;
}

function exactClaimFor(record: FamilyRecord, iteration?: RecordedIteration): ExactClaimNote | undefined {
  if (iteration === undefined || iteration.hypothesis === undefined || !record.hasUniqueSourceId) return undefined;
  const note = EXACT_CLAIMS[iteration.id];
  return note?.hypothesis === iteration.hypothesis && note.clusterId === asText(record.cluster.cluster_id)
    ? note
    : undefined;
}

function explicitApplication(source: Readonly<Record<string, unknown>>): string | null {
  const direct = asText(source.application_fit);
  if (direct !== null) return `Recorded source: ${direct}`;
  const block = asRecord(source.application_fit);
  if (block === null) return null;
  const status = asText(block.status) ?? asText(block.state);
  const reason = asText(block.reason) ?? asText(block.detail);
  if (status === null && reason === null) return null;
  return `Recorded source: ${[status, reason].filter((value): value is string => value !== null).join(" · ")}`;
}

function explicitExecutionMode(source: Readonly<Record<string, unknown>>): string | null {
  const outcome = asRecord(source.experiment_outcome);
  return asText(outcome?.execution_mode) ?? asText(outcome?.run_mode) ?? asText(source.execution_mode);
}

function addLine(
  target: ResearchEvidenceLine[],
  label: string,
  values: Array<string | null>,
): void {
  const text = values.filter((value): value is string => value !== null).join(" · ");
  if (text.length > 0) target.push({ label, text });
}

function evidenceFromSource(
  source: Readonly<Record<string, unknown>>,
  cluster: LadderCluster,
  exact?: ExactClaimNote,
): {
  supporting: ResearchEvidenceLine[];
  limiting: ResearchEvidenceLine[];
  outcome: ResearchEvidenceLine[];
} {
  const supporting: ResearchEvidenceLine[] = [];
  const limiting: ResearchEvidenceLine[] = [];
  const outcome: ResearchEvidenceLine[] = [];
  const retrieval = asRecord(source.retrieval);
  const relevance = asRecord(retrieval?.relevance);
  const novelty = asRecord(source.novelty);
  const critique = asRecord(source.critique);
  const redteam = asRecord(source.redteam);
  const rawOutcome = asRecord(source.experiment_outcome);

  addLine(supporting, "Retrieval review (recorded)", [
    asText(relevance?.reason),
    asText(relevance?.low_confidence) === null ? null : `low_confidence=${asText(relevance?.low_confidence)}`,
  ]);
  addLine(supporting, "Novelty review (recorded)", [
    asText(novelty?.class),
    asText(novelty?.rationale),
  ]);
  addLine(supporting, "Critic review (recorded)", [
    asText(critique?.verdict),
    asText(critique?.rationale),
    asText(critique?.contradicting_paper_id) === null
      ? null
      : `contradicting_paper_id=${asText(critique?.contradicting_paper_id)}`,
  ]);

  const redteamStatus = asText(redteam?.subagent_status);
  const redteamCritique = asText(redteam?.critique);
  if (redteam !== null) {
    addLine(
      redteamStatus === "schema_mismatch" || redteamCritique !== null ? limiting : supporting,
      "Red-team review (recorded)",
      [asText(redteam.verdict), redteamStatus === null ? null : `status=${redteamStatus}`, redteamCritique],
    );
  }

  const kill = asRecord(cluster.kill_reason);
  if (kill !== null || asText(cluster.status) === "killed") {
    addLine(limiting, "Killed history (recorded)", [
      asText(kill?.code),
      asText(kill?.detail),
      asText(kill?.evidence_key) === null ? null : `evidence=${asText(kill?.evidence_key)}`,
    ]);
  }

  if (exact !== undefined) {
    for (const limitation of exact.limitations) {
      limiting.push({ label: "Dated source qualification", text: limitation });
    }
  }

  if (rawOutcome !== null) {
    addLine(outcome, "Recorded outcome identity", [
      asText(rawOutcome.experiment_id),
      asText(rawOutcome.metric),
      asText(rawOutcome.trials) === null ? null : `trials=${asText(rawOutcome.trials)}`,
    ]);
    const value = asText(rawOutcome.value) ?? (asRecord(rawOutcome.value) === null
      ? null
      : JSON.stringify(rawOutcome.value));
    addLine(outcome, "Recorded outcome detail", [value, asText(rawOutcome.summary), asText(rawOutcome.results_path)]);
  }

  return { supporting, limiting, outcome };
}

function contextFor(
  record: FamilyRecord,
  iteration: RecordedIteration | undefined,
  index: number,
  nextOwed: Record<string, string>,
): ResearchClaimContext {
  const exact = exactClaimFor(record, iteration);
  const source = iteration?.source ?? {};
  const evidence = evidenceFromSource(source, record.cluster, exact);
  const status = asText(record.cluster.status) ?? "unknown status";
  const stage = asText(record.cluster.evidence_level) ?? "unknown stage";
  const gate = asText(source.gate_status);
  const outcomePresent = asRecord(source.experiment_outcome) !== null;
  const application = explicitApplication(source);
  const execution = explicitExecutionMode(source);
  const binding = asRecord(source.claim_experiment_binding);
  const comparison = asRecord(source.evidence_comparison);
  const sourceEndedAt = asText(source.ended_at) ?? "unknown";
  const recordedEventAt = asText(record.cluster.last_event_ts) ?? exact?.recordedLevelAt ?? "unknown";
  const iterationId = iteration?.id ?? "iteration unavailable";
  const hypothesis = iteration?.hypothesis ?? "No exact hypothesis text is available in the received iteration source.";
  const topic = iteration?.topic ?? (record.topics.join("; ") || "Recorded topic unavailable");
  const stageRequirement = nextOwed[stage];

  let evidenceDelta: string;
  if (!outcomePresent) {
    evidenceDelta = "Not established — an outcome, compatible comparison, and exact claim/spec/result binding are not supplied in the received projection.";
  } else if (binding === null || comparison === null) {
    evidenceDelta = "Not established — a raw outcome is supplied, while a compatible comparison and exact claim/spec/result binding are not supplied in the received projection.";
  } else {
    evidenceDelta = "Not established in this view — binding and comparison metadata are recorded, but their validity has not been independently qualified here.";
  }

  return {
    key: `${record.key}:${iterationId}:${index}`,
    record,
    iteration,
    iterationId,
    hypothesis,
    topic,
    shortLabel: exact?.shortLabel ?? record.title,
    summary: exact?.summary ?? "Context derived only from the selected record and its received iteration source.",
    sourceEndedAt,
    recordedEventAt,
    latestReviewAt: exact?.latestReviewAt,
    claimHash: exact?.claimHash,
    rawRowHash: exact?.rawRowHash,
    sourceLine: exact?.sourceLine,
    isPinnedExactClaim: exact !== undefined,
    claimStanding: `${status} · ${stage}${gate === null ? " · iteration gate unknown" : ` · iteration gate ${gate}`}`,
    applicationFit: application ?? (exact === undefined
      ? "Unmapped — explicit application fit is not supplied in the received projection."
      : "Unmapped — the 2026-09-07 source assessment identified no suitable application or market, and this received projection supplies no explicit mapping."),
    evidenceValidity: "Unknown — recorded reviews and raw outcomes are shown separately; this thin projection cannot authenticate exact binding, evidence validity, or later evidence state.",
    executionMode: execution === null
      ? "Unknown — an execution-mode field is not supplied in the received projection."
      : `Recorded source: ${execution}`,
    evidenceDelta,
    supportingEvidence: evidence.supporting,
    limitingEvidence: evidence.limiting,
    rawOutcome: evidence.outcome,
    blocker: exact?.blocker ?? "No claim-specific blocker is supplied in this projection. Inspect the exact dossier before choosing work.",
    proposedTest: exact?.proposedTest,
    decision: exact?.proposedDecision ?? "No claim-specific scientific or application decision is supplied in this projection.",
    ...(stageRequirement === undefined ? {} : { stageRequirement }),
  };
}


export function researchContextsForRecord(
  record: FamilyRecord,
  nextOwed: Record<string, string>,
): ResearchClaimContext[] {
  if (record.iterations.length === 0) return [contextFor(record, undefined, 0, nextOwed)];
  return record.iterations.map((iteration, index) => contextFor(record, iteration, index, nextOwed));
}

export function researchContextsForFamily(
  family: ThesisFamily,
  nextOwed: Record<string, string>,
): ResearchClaimContext[] {
  return family.records.flatMap((record) => researchContextsForRecord(record, nextOwed));
}
