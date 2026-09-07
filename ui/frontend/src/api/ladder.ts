import { getIterations, getLadder } from "./http";
import { refreshPoll, usePolled, usePollActivity, usePollAsOf } from "./pollhub";
import type { LadderResponse } from "../types/schemas";

const RECORDS = "ladder:records";
const TOPICS = "ladder:iteration-topics:v1";
// Keep the join small. Full source papers and evidence remain in each dossier;
// retrieving every abstract here would add megabytes to each poll.
export const TOPIC_FIELDS = "iteration_id,seed,hypothesis,started_at,ended_at";

export function useLadderSources({ initial, initialIterations, pollMs }: {
  initial?: LadderResponse | null;
  initialIterations?: unknown[];
  pollMs: number;
}) {
  const enabled = initial === undefined;
  const records = usePolled(RECORDS, getLadder, {
    enabled, intervalMs: Math.max(5_000, pollMs), deadlineMs: 20_000,
  });
  const topics = usePolled(TOPICS, async () => {
    const response = await getIterations({ fields: TOPIC_FIELDS });
    if (!response || !Array.isArray(response.iterations)) {
      throw new Error("Iteration topic source is missing or malformed");
    }
    return response.iterations;
  }, { enabled, intervalMs: Math.max(30_000, pollMs), deadlineMs: 20_000 });
  const recordsAsOf = usePollAsOf(RECORDS);
  const topicsAsOf = usePollAsOf(TOPICS);
  const recordsRefreshing = usePollActivity(RECORDS);
  const topicsRefreshing = usePollActivity(TOPICS);
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
      if (enabled) { refreshPoll(RECORDS); refreshPoll(TOPICS); }
    },
  };
}
