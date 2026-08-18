// EndpointMissingNote — the graceful version-skew render. The frontend
// regularly runs NEWER than the :8700 backend binary (today's live server
// predates /api/attest/* and /api/activity/active_runs), so a 404 from a
// known LIST/CAPABILITY endpoint is version skew, not an error: it renders as
// this quiet zinc note — never red. A 500 stays red (the caller's normal
// error path), and a RESOURCE-404 (e.g. journal-by-id "no journal entry for
// this iteration") keeps its existing semantics — those endpoints are
// deliberately NOT in the known list below.
//
// `<version>` is /api/health's `version` field — since the 2026-06-10 fix
// that snapshots _git_sha() at import, it means "the sha of the RUNNING
// binary", which is exactly what a skew note must name.
import { useEffect, useState } from "react";
import { getHealth } from "../api/http";

// Known list/capability endpoints whose 404 means "this backend build does
// not HAVE the endpoint" rather than "the resource was not found". The attest
// POST surfaces are included via the capability handshake: a frontend that
// sees 404 on any of them degrades exactly like a 404 on /api/attest/available.
const SKEW_404_ENDPOINTS: ReadonlySet<string> = new Set([
  "/api/activity/active_runs",
  "/api/attest/available",
  "/api/human_todo",
  "/api/lab_todo",
  "/api/ladder",
  "/api/attest/gate_verdict",
  "/api/attest/finding_review",
  "/api/attest/bubble_ack",
  "/api/attest/defer",
  // S4 lab channel: a backend predating /api/channel/* degrades quietly.
  "/api/channel/timeline",
  "/api/channel/available",
  // Model I/O viewer (2026-08-18): the running :8700 binary predates these
  // until its next reload — the page must degrade quietly, not go red.
  "/api/model_io",
  "/api/dispatch_trace",
]);

/** True when `err` is a 404 from a KNOWN list/capability endpoint — i.e.
 * version skew (older backend binary), to be rendered as the quiet
 * EndpointMissingNote instead of red. False for any other status (a 500
 * stays red), for unknown endpoints (resource-404s keep their semantics),
 * and for non-HTTP errors.
 *
 * Duck-types `.status` rather than `instanceof HttpError`: several test
 * suites module-mock ../api/http (which would make the class binding
 * undefined and an instanceof throw), and a cross-bundle class identity is
 * not guaranteed — the carried status is the contract. */
export function isVersionSkew404(err: unknown, endpoint: string): boolean {
  if (!SKEW_404_ENDPOINTS.has(endpoint)) return false;
  if (err == null || typeof err !== "object") return false;
  return (err as { status?: unknown }).status === 404;
}

interface EndpointMissingNoteProps {
  // The endpoint path the 404 came from, e.g. "/api/activity/active_runs".
  endpoint: string;
  // The running backend's sha. When omitted the note fetches it once from
  // /api/health itself (quiet failure -> "unknown"). Pass it (or null) to
  // keep a test render fetch-free.
  version?: string | null;
}

export default function EndpointMissingNote({
  endpoint,
  version,
}: EndpointMissingNoteProps) {
  const [fetched, setFetched] = useState<string | null>(null);
  const selfFetch = version === undefined;

  useEffect(() => {
    if (!selfFetch) return;
    // Module-mocked ../api/http in some suites omits getHealth — skip the
    // fetch rather than throw; the note then reads "sha unknown".
    if (typeof getHealth !== "function") return;
    let on = true;
    getHealth()
      .then((h) => {
        if (on && typeof h?.version === "string" && h.version) {
          setFetched(h.version);
        }
      })
      .catch(() => {
        /* health unreachable — the note stays "sha unknown" */
      });
    return () => {
      on = false;
    };
  }, [selfFetch]);

  const sha = (selfFetch ? fetched : version) || "unknown";

  return (
    <div
      data-testid="endpoint-missing-note"
      className="rounded border border-zinc-800 bg-zinc-900/40 px-3 py-2 text-xs text-zinc-500"
    >
      <span className="font-mono text-zinc-400">{endpoint}</span>
      <span> — endpoint not in this backend build (sha {sha})</span>
    </div>
  );
}
