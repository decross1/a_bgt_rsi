// CloseOutStrip — the session's CLOSE-OUT surface (GAP 2).
//
// `finding_session.end_session` has always routed the real close-outs
// (validated/rejected -> the gate-feedback edge; spawn_topic -> the
// finding_followups queue; refine -> in_review). The owner test-driving the
// cockpit could not FIND that: the two-voice pane just ended, and the question
// "how do we get the outcome of this to yield a follow up for nara?" had no
// answer on screen. This strip is the answer, PERSISTENT under the session:
// it names the four outcomes, what each WRITES, and what consumes it
// downstream — and for spawn_topic it carries the prefill.
//
// THE FENCE HOLDS (D-053/D-054, inviolate rule 4). The strip takes NO verdict
// prop and posts NO verdict: validate / reject / refine are NAMED here and
// RECORDED in the disposition footer's forms (the only dispositions). The one
// interactive path is spawn_topic, which is a SESSION-EXIT that writes NOTHING
// (`POST /api/todo/spawn_topic` returns an honest indicator — the writer of
// record is end_session). Nothing here re-implements a seam: the outcome
// descriptor comes from `GET /api/todo/close_out` (so the copy is the
// backend's truth, not frontend prose that can drift from the writers) and the
// spawn post is the EXISTING cockpit endpoint.
//
// PREFILL: when the two-voice attacker (Qwen) has spoken, its last turn seeds
// the topic field — read-only as a source (the transcript is never mutated),
// and always editable by the human before submit. No attacker turn -> no
// prefill, and the field says so rather than inventing a topic.
import { useEffect, useRef, useState } from "react";
import { API_BASE } from "../../api/http";
import { postSpawnTopic, TodoError, type TodoResult } from "../../api/todo";

type SpawnKind = "finding" | "step";

// One row of the backend descriptor. Every field is producer-owned.
interface CloseOutOutcome {
  outcome?: string | null;
  label?: string | null;
  endpoint?: string | null;
  writes?: string | null;
  downstream?: string | null;
  session_exit?: boolean | null;
}

interface CloseOutDescriptor {
  available: boolean;
  writer: string;
  followups_queue: string;
  outcomes: CloseOutOutcome[];
  /** True when the running backend predates /api/todo/close_out (404). */
  skew?: boolean;
}

const UNAVAILABLE: CloseOutDescriptor = {
  available: false,
  writer: "",
  followups_queue: "",
  outcomes: [],
};

const asStr = (v: unknown): string => (typeof v === "string" ? v : "");

// Producer-owned body -> a safe descriptor. A malformed/partial payload
// degrades to "no outcomes listed" rather than throwing or half-rendering.
function asDescriptor(body: unknown): CloseOutDescriptor {
  if (body === null || typeof body !== "object" || Array.isArray(body)) {
    return UNAVAILABLE;
  }
  const b = body as Record<string, unknown>;
  const rows = Array.isArray(b.outcomes) ? (b.outcomes as unknown[]) : [];
  return {
    available: b.available === true,
    writer: asStr(b.writer),
    followups_queue: asStr(b.followups_queue),
    outcomes: rows.filter(
      (r): r is CloseOutOutcome =>
        r !== null && typeof r === "object" && !Array.isArray(r),
    ),
  };
}

export async function getCloseOut(): Promise<CloseOutDescriptor> {
  const resp = await fetch(`${API_BASE}/api/todo/close_out`);
  // 404 == version skew (the running backend predates the endpoint) — quiet,
  // NAMED degradation; never an error and never invented outcome copy.
  if (resp.status === 404) return { ...UNAVAILABLE, skew: true };
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  try {
    return asDescriptor(await resp.json());
  } catch {
    return UNAVAILABLE;
  }
}

// `would_run` is producer-owned argv; render only scalar tokens.
const wouldRunText = (argv: unknown[]): string =>
  argv
    .filter(
      (t): t is string | number =>
        typeof t === "string" || (typeof t === "number" && Number.isFinite(t)),
    )
    .map(String)
    .join(" ");

interface Props {
  findingId: string;
  /** The last ATTACKER (Qwen) turn of this session, when one exists — the
   *  read-only source the topic field is seeded from. */
  attackerSuggestion?: string | null;
  /** Injectable for tests; defaults to the real GET. */
  fetchDescriptor?: () => Promise<CloseOutDescriptor>;
}

export default function CloseOutStrip({
  findingId,
  attackerSuggestion = null,
  fetchDescriptor = getCloseOut,
}: Props) {
  const safeId = asStr(findingId);
  const suggestion = asStr(attackerSuggestion).trim();

  const [desc, setDesc] = useState<CloseOutDescriptor | null>(null);
  const [kind, setKind] = useState<SpawnKind>("finding");
  const [topic, setTopic] = useState("");
  const [result, setResult] = useState<TodoResult | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [submitting, setSubmitting] = useState(false);
  // Once the human types, the prefill stops overwriting their draft.
  const touched = useRef(false);

  useEffect(() => {
    let live = true;
    fetchDescriptor()
      .then((d) => {
        if (live) setDesc(d);
      })
      .catch(() => {
        if (live) setDesc(UNAVAILABLE);
      });
    return () => {
      live = false;
    };
  }, [fetchDescriptor]);

  // Seed from the attacker's last turn — only while the human has not typed.
  useEffect(() => {
    if (!touched.current && suggestion !== "") setTopic(suggestion);
  }, [suggestion]);

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      setResult(
        await postSpawnTopic({ finding_id: safeId, kind, topic: topic.trim() }),
      );
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setSubmitting(false);
    }
  };

  const outcomes = desc?.outcomes ?? [];

  return (
    <div
      data-testid="close-out-strip"
      className="mt-1.5 rounded border border-sky-900/60 bg-sky-950/10 px-2 py-1.5"
    >
      <div className="text-[10px] uppercase tracking-wide text-sky-400">
        close-out · what ending this session actually does
      </div>

      {desc === null ? (
        <div className="mt-0.5 text-[11px] text-zinc-500" data-testid="close-out-loading">
          loading the close-out outcomes…
        </div>
      ) : outcomes.length === 0 ? (
        <div className="mt-0.5 text-[11px] text-amber-400/80" data-testid="close-out-skew">
          {desc.skew === true
            ? "this backend predates /api/todo/close_out — the outcome details are UNAVAILABLE here (not absent from the loop); the disposition footer below still records them."
            : "close-out outcomes unavailable from the backend — the disposition footer below still records them."}
        </div>
      ) : (
        <ul className="mt-1 flex flex-col gap-1" data-testid="close-out-outcomes">
          {outcomes.map((o, i) => (
            <li
              key={asStr(o.outcome) || i}
              data-testid="close-out-outcome"
              className="text-[11px] text-zinc-400"
            >
              <span className="font-mono uppercase tracking-wide text-zinc-300">
                {asStr(o.label) || asStr(o.outcome) || "—"}
              </span>
              {o.session_exit === true && (
                <span className="ml-1 rounded bg-cyan-950 px-1 py-0.5 font-mono text-[9px] uppercase text-cyan-300">
                  session exit
                </span>
              )}
              <span className="ml-1 text-zinc-500">
                writes {asStr(o.writes) || "—"}
              </span>
              <div className="text-[10px] text-zinc-600">
                → {asStr(o.downstream) || "—"}
                {asStr(o.endpoint) !== "" && (
                  <span className="ml-1 font-mono">{asStr(o.endpoint)}</span>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-1 text-[10px] text-zinc-600" data-testid="close-out-fence">
        the verdict outcomes are recorded in the disposition footer below (the
        only dispositions — this strip never records one). Only the follow-up
        topic is a session exit, and it writes no verdict.
      </div>

      {/* SPAWN FOLLOW-UP TOPIC — the answer to "how does this yield a follow
          up for nara?". Prefilled from the attacker's last turn when there is
          one; the human edits before submitting. */}
      <div className="mt-1.5 border-t border-zinc-800/60 pt-1.5">
        <div className="text-[10px] uppercase tracking-wide text-cyan-400">
          spawn follow-up topic → {desc?.followups_queue || "finding_followups"}
        </div>
        {suggestion !== "" ? (
          <div className="mt-0.5" data-testid="close-out-prefill-source">
            <div className="text-[10px] uppercase tracking-wide text-zinc-600">
              prefilled from the attacker's last turn (read-only source — edit
              the field below before submitting)
            </div>
            <div
              className="mt-0.5 max-h-16 overflow-y-auto whitespace-pre-wrap rounded border border-red-900/60 bg-red-950/10 px-1.5 py-1 text-[10px] text-zinc-400"
              data-testid="close-out-prefill-text"
            >
              {suggestion}
            </div>
          </div>
        ) : (
          <div className="mt-0.5 text-[10px] text-zinc-600" data-testid="close-out-no-prefill">
            no attacker turn in this session yet — nothing to prefill; write the
            follow-up topic yourself.
          </div>
        )}

        <label className="mt-1 flex items-center gap-2 text-[11px] text-zinc-400">
          <span className="uppercase tracking-wide text-zinc-600">kind</span>
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value as SpawnKind)}
            aria-label="follow-up kind (finding or step)"
            className="rounded border border-zinc-800 bg-zinc-950 px-2 py-1 font-mono text-[11px] text-zinc-200 focus:border-zinc-600 focus:outline-none"
          >
            <option value="finding">finding</option>
            <option value="step">step</option>
          </select>
        </label>
        <textarea
          value={topic}
          onChange={(e) => {
            touched.current = true;
            setTopic(e.target.value);
          }}
          aria-label="follow-up topic (required)"
          placeholder="follow-up topic (required — what Nara should chase next)"
          rows={2}
          className="mt-1 w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1 font-mono text-[11px] text-zinc-200 placeholder:text-zinc-600 focus:border-zinc-600 focus:outline-none"
        />
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            disabled={submitting || topic.trim() === "" || safeId === ""}
            onClick={() => void submit()}
            data-testid="close-out-spawn"
            className={
              "rounded border border-cyan-800 bg-cyan-950 px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide text-cyan-300 hover:bg-cyan-900 " +
              "disabled:cursor-not-allowed disabled:border-zinc-800 disabled:bg-zinc-900 disabled:text-zinc-600"
            }
          >
            spawn follow-up topic
          </button>
          {suggestion !== "" && topic !== suggestion && (
            <button
              type="button"
              onClick={() => {
                touched.current = false;
                setTopic(suggestion);
              }}
              data-testid="close-out-reset-prefill"
              className="rounded border border-zinc-800 bg-zinc-950 px-2 py-0.5 text-[10px] uppercase tracking-wide text-zinc-500 hover:text-zinc-300"
            >
              reset to attacker's suggestion
            </button>
          )}
          {submitting && (
            <span className="text-[11px] text-zinc-500" data-testid="close-out-submitting">
              submitting…
            </span>
          )}
        </div>

        {result !== null && (
          <div className="mt-1 text-[11px] text-cyan-300" data-testid="close-out-result">
            {asStr(result.status) === "session_exit"
              ? "session exit — exit this session into spawn_topic; end_session is the writer of record (nothing was written here)"
              : "follow-up topic recorded"}
            {Array.isArray(result.would_run) && (
              <pre
                data-testid="close-out-wouldrun"
                className="mt-0.5 overflow-x-auto whitespace-pre-wrap rounded border border-zinc-800 bg-zinc-950 p-2 font-mono text-[11px] text-zinc-400"
              >
                {wouldRunText(result.would_run as unknown[])}
              </pre>
            )}
          </div>
        )}

        {error !== null &&
          (error instanceof TodoError && error.stderr !== null ? (
            <pre
              data-testid="close-out-stderr"
              className="mt-1 overflow-x-auto whitespace-pre-wrap rounded border border-red-900 bg-red-950/40 p-2 font-mono text-[11px] text-red-400"
            >
              {error.stderr}
            </pre>
          ) : (
            <div data-testid="close-out-error" className="mt-1 text-[11px] text-red-400">
              {error.message}
            </div>
          ))}
      </div>
    </div>
  );
}
