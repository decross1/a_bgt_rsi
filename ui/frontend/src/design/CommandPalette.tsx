// CommandPalette — the global Cmd+K palette (R0 design system), cmdk-based.
// Mounted ONCE in App (inside BrowserRouter — it navigates). This slice seeds
// it with navigation entries for every route; later slices add verbs through
// registerPaletteActions (module-level registry, unsubscribe on unmount).
// The scrim is one of the two allowed glass surfaces (with the app header).
import { Command } from "cmdk";
import { useEffect, useState, useSyncExternalStore } from "react";
import { useNavigate } from "react-router-dom";
import "./primitives.css";

export type PaletteAction = {
  id: string;
  label: string;
  /** Group heading in the list; defaults to "Actions". */
  group?: string;
  /** Extra match terms beyond the label. */
  keywords?: string[];
  perform: () => void;
};

// ---- registerable action list (routes are built-in; verbs register here) ----
let registered: PaletteAction[] = [];
const listeners = new Set<() => void>();

export function registerPaletteActions(actions: PaletteAction[]): () => void {
  registered = [...registered, ...actions];
  listeners.forEach((l) => l());
  return () => {
    registered = registered.filter((a) => !actions.includes(a));
    listeners.forEach((l) => l());
  };
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
function getSnapshot(): PaletteAction[] {
  return registered;
}

// Reachable route surfaces in the same three groups as the Atlas sidebar.
const ROUTES: {
  id: string;
  label: string;
  to: string;
  keywords: string[];
  group: "Now" | "Research" | "Operations";
}[] = [
  { id: "nav-pulse", label: "pulse", to: "/", keywords: ["home", "health", "owe"], group: "Now" },
  { id: "nav-ladder", label: "ladder", to: "/ladder", keywords: ["ideas", "evidence", "rungs"], group: "Research" },
  { id: "nav-dossier", label: "dossiers", to: "/dossier", keywords: ["reader", "findings", "todo"], group: "Research" },
  { id: "nav-experiments", label: "experiments", to: "/experiments", keywords: ["runs", "engine"], group: "Research" },
  { id: "nav-development", label: "development", to: "/development", keywords: ["codex", "engineering", "readiness", "overnight"], group: "Operations" },
  { id: "nav-channel", label: "channel", to: "/channel", keywords: ["chat", "nara", "lab"], group: "Operations" },
  { id: "nav-model-io", label: "model i/o", to: "/model-io", keywords: ["calls", "dispatch", "wrapper"], group: "Operations" },
  { id: "nav-cycles", label: "cycles", to: "/cycles", keywords: ["coordinator", "engine"], group: "Operations" },
  { id: "nav-graph", label: "graph", to: "/graph", keywords: ["chains", "engine", "flow"], group: "Operations" },
];

const ROUTE_GROUPS = ["Now", "Research", "Operations"] as const;

export default function CommandPalette() {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const actions = useSyncExternalStore(subscribe, getSnapshot);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      } else if (e.key === "Escape") {
        setOpen(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  if (!open) return null;

  const run = (perform: () => void) => {
    setOpen(false);
    perform();
  };

  const groups = new Map<string, PaletteAction[]>();
  for (const a of actions) {
    const g = a.group ?? "Actions";
    groups.set(g, [...(groups.get(g) ?? []), a]);
  }

  return (
    <>
      <div
        className="dsn-palette-scrim"
        data-testid="palette-scrim"
        aria-hidden="true"
        onClick={() => setOpen(false)}
      />
      <div
        aria-label="Command palette"
        aria-modal="true"
        className="dsn-palette"
        data-testid="command-palette"
        role="dialog"
      >
        <Command label="Command palette">
          <Command.Input autoFocus placeholder="Go to…" />
          <Command.List>
            <Command.Empty>No matches.</Command.Empty>
            {ROUTE_GROUPS.map((heading) => (
              <Command.Group heading={heading} key={heading}>
                {ROUTES.filter((route) => route.group === heading).map((route) => (
                  <Command.Item
                    key={route.id}
                    value={`${route.label} ${route.keywords.join(" ")}`}
                    onSelect={() => run(() => navigate(route.to))}
                  >
                    {route.label}
                    <span className="dsn-palette-hint">{route.to}</span>
                  </Command.Item>
                ))}
              </Command.Group>
            ))}
            {[...groups.entries()].map(([heading, items]) => (
              <Command.Group key={heading} heading={heading}>
                {items.map((a) => (
                  <Command.Item
                    key={a.id}
                    value={`${a.label} ${(a.keywords ?? []).join(" ")}`}
                    onSelect={() => run(a.perform)}
                  >
                    {a.label}
                  </Command.Item>
                ))}
              </Command.Group>
            ))}
          </Command.List>
        </Command>
      </div>
    </>
  );
}
