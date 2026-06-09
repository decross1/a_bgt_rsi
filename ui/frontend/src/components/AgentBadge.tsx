// AgentBadge — provenance chip for the autonomy-observability views. Renders
// the run-log `agent` field (D-043) as a small uppercase badge so every row in
// the coordinator / activity / dashboard surfaces says WHO did it: coordinator
// vs nara vs a workflow sub-agent vs the human. See ui_plan.md §AUTONOMY
// OBSERVABILITY ("provenance everywhere"). Pure + tiny; matches the Badge idiom
// in ResolvedIterationsList.tsx (rounded, text-[10px], uppercase, tracking-wide).
//
// Tone by kind:
//   coordinator           -> sky   (the loop driver)
//   nara                   -> emerald (the iteration agent)
//   workflow:<id>/<role>   -> indigo, shown compactly as "wf:<role>"
//   human                  -> zinc  (a person acted)
//   unknown / absent       -> quiet zinc
// Renders null when `agent` is null/empty (no badge for an unattributed row).

const TONE: Record<string, string> = {
  coordinator: "bg-sky-950 text-sky-300",
  nara: "bg-emerald-950 text-emerald-400",
  workflow: "bg-indigo-950 text-indigo-300",
  human: "bg-zinc-800 text-zinc-400",
};

const QUIET = "bg-zinc-800 text-zinc-400";

// "workflow:<id>/<role>" -> "wf:<role>"; degrade gracefully when the id/role
// split is missing (e.g. bare "workflow:builder" -> "wf:builder", "workflow:"
// -> "wf"). The label is uppercased by CSS, so the text node stays lowercase.
function workflowLabel(agent: string): string {
  const rest = agent.slice("workflow:".length);
  const role = rest.includes("/") ? rest.slice(rest.lastIndexOf("/") + 1) : rest;
  const trimmed = role.trim();
  return trimmed ? `wf:${trimmed}` : "wf";
}

export default function AgentBadge({
  agent,
  className,
}: {
  agent?: string | null;
  className?: string;
}) {
  const value = agent?.trim();
  if (!value) return null;

  const isWorkflow = value.startsWith("workflow:");
  const tone = isWorkflow ? TONE.workflow : TONE[value] ?? QUIET;
  const label = isWorkflow ? workflowLabel(value) : value;

  return (
    <span
      data-testid="agent-badge"
      className={`rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${tone}${
        className ? ` ${className}` : ""
      }`}
    >
      {label}
    </span>
  );
}
