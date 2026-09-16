export interface ResearchApplicationLane {
  id: "options" | "prediction_markets" | "crypto" | string;
  label: string;
  priority: string;
  status: string;
  mechanism: string;
  test: string;
  requirements: string[];
  kill_condition: string;
  source_ids: string[];
}

export interface ResearchApplicationNextStep {
  id: string;
  label: string;
  status: string;
  deliverable: string;
}

export interface ResearchApplicationSource {
  id: string;
  title: string;
  url: string;
  accessed_at: string;
}

export interface ResearchApplicationAgendaRecord {
  schema_version: "research-application-agenda/v1";
  agenda_id: string;
  recorded_at: string;
  status: "proposed_research_agenda";
  owner_direction: string;
  selection_rule: string;
  horizon: string;
  research_question: string;
  execution_authorized: false;
  data_entitlement_verified: false;
  lanes: ResearchApplicationLane[];
  next_agenda: ResearchApplicationNextStep[];
  history_policy: string;
  sources: ResearchApplicationSource[];
}

export interface ResearchApplicationAgendaResponse {
  schema_version: "research-application-agenda/v1";
  generated_at: string;
  available: boolean;
  agenda: ResearchApplicationAgendaRecord | null;
  source_sha256: string | null;
  warnings: string[];
}
