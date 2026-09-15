import { getIterations, getLadder } from "./http";
import { refreshPoll, usePolled, usePollActivity, usePollAsOf } from "./pollhub";
import type { LadderResponse } from "../types/schemas";
import { browserResearchScope, type ResearchScope } from "../researchScope";

// Keep the join small. Full source papers and evidence remain in each dossier;
// retrieving every abstract here would add megabytes to each poll.
export const TOPIC_FIELDS = "iteration_id,seed,hypothesis,started_at,ended_at";

export function useLadderSources({ initial, initialIterations, pollMs, researchScope }: {
  initial?: LadderResponse | null;
  initialIterations?: unknown[];
  pollMs: number;
  researchScope?: ResearchScope;
}) {
  const scope = researchScope ?? browserResearchScope();
  const recordsKey = `ladder:records:${scope}`;
  const topicsKey = `ladder:iteration-topics:v1:${scope}`;
  const enabled = initial === undefined;
  const records = usePolled(recordsKey, () => getLadder(scope), {
    enabled, intervalMs: Math.max(5_000, pollMs), deadlineMs: 20_000,
  });
  const topics = usePolled(topicsKey, async () => {
    const response = await getIterations({ fields: TOPIC_FIELDS }, scope);
    if (!response || !Array.isArray(response.iterations)) {
      throw new Error("Iteration topic source is missing or malformed");
    }
    return response.iterations;
  }, { enabled, intervalMs: Math.max(30_000, pollMs), deadlineMs: 20_000 });
  const recordsAsOf = usePollAsOf(recordsKey);
  const topicsAsOf = usePollAsOf(topicsKey);
  const recordsRefreshing = usePollActivity(recordsKey);
  const topicsRefreshing = usePollActivity(topicsKey);
  return {
    data: enabled ? records.data : initial,
    loaded: !enabled || records.data !== undefined,
    error: enabled && records.failing ? records.error : null,
    iterations: enabled ? topics.data : initialIterations,
    topicsError: enabled && topics.failing ? String(topics.error) : null,
    recordsAsOf: enabled ? recordsAsOf : null,
    topicsAsOf: enabled ? topicsAsOf : null,
    refreshing: enabled && (recordsRefreshing || topicsRefreshing),
    refresh: () => {
      if (enabled) { refreshPoll(recordsKey); refreshPoll(topicsKey); }
    },
  };
}
