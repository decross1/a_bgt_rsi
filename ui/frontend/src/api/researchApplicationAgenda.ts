import type { ResearchApplicationAgendaResponse } from "../types/researchApplicationAgenda";

const API_PORT = import.meta.env.VITE_API_PORT ?? "8700";
const API_BASE = `http://${window.location.hostname}:${API_PORT}`;

export async function getResearchApplicationAgenda(): Promise<ResearchApplicationAgendaResponse> {
  const response = await fetch(`${API_BASE}/api/research_application_agenda`);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return (await response.json()) as ResearchApplicationAgendaResponse;
}
