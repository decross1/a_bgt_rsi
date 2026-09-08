// CommandPalette — the global Cmd+K palette (R0 design system), cmdk-based.
// Mounted ONCE in App (inside BrowserRouter — it navigates). This slice seeds
// it with navigation entries for every route; later slices add verbs through
// registerPaletteActions (module-level registry, unsubscribe on unmount).
// The scrim is one of the two allowed glass surfaces (with the app header).
import { Command } from "cmdk";
import {
  type RefObject,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
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
  { id: "nav-pulse", label: "Now overview", to: "/", keywords: ["pulse", "home", "health", "owe"], group: "Now" },
  { id: "nav-ladder", label: "Research workspace", to: "/ladder", keywords: ["ladder", "ideas", "evidence", "rungs"], group: "Research" },
  { id: "nav-dossier", label: "Record library", to: "/dossier", keywords: ["dossier", "reader", "findings", "todo"], group: "Research" },
  { id: "nav-experiments", label: "Evaluations", to: "/experiments", keywords: ["experiments", "runs", "engine"], group: "Research" },
  { id: "nav-development", label: "Operations delivery", to: "/development", keywords: ["development", "codex", "engineering", "readiness", "overnight"], group: "Operations" },
  { id: "nav-channel", label: "Conversation", to: "/channel", keywords: ["channel", "chat", "nara", "lab"], group: "Operations" },
  { id: "nav-model-io", label: "Calls", to: "/model-io", keywords: ["model i/o", "calls", "dispatch", "wrapper"], group: "Operations" },
  { id: "nav-cycles", label: "Trace history", to: "/cycles", keywords: ["cycles", "coordinator", "engine"], group: "Operations" },
  { id: "nav-graph", label: "Recorded trace map", to: "/graph", keywords: ["graph", "chains", "engine", "flow"], group: "Operations" },
];

const ROUTE_GROUPS = ["Now", "Research", "Operations"] as const;

type CommandPaletteProps = {
  fallbackFocusRef?: RefObject<HTMLElement | null>;
  onOpenChange?: (open: boolean) => void;
};

const PALETTE_FOCUSABLE = [
  "button:not([disabled])",
  "input:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

export default function CommandPalette({
  fallbackFocusRef,
  onOpenChange,
}: CommandPaletteProps = {}) {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const actions = useSyncExternalStore(subscribe, getSnapshot);
  const dialogRef = useRef<HTMLDivElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);
  const wasOpenRef = useRef(false);

  const changeOpen = (next: boolean) => {
    if (next && !open) {
      openerRef.current =
        document.activeElement instanceof HTMLElement ? document.activeElement : null;
    }
    setOpen(next);
    onOpenChange?.(next);
  };

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        // Let an existing modal keep ownership of focus. The narrow Atlas drawer
        // is coordinated through onOpenChange and is the only modal handed off.
        if (!open && document.querySelector('[aria-modal="true"]')) return;
        e.preventDefault();
        changeOpen(!open);
      } else if (e.key === "Escape" && open) {
        e.preventDefault();
        changeOpen(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onOpenChange]);

  useEffect(() => {
    if (open) {
      wasOpenRef.current = true;
      return;
    }
    if (!wasOpenRef.current) return;
    wasOpenRef.current = false;
    const opener = openerRef.current;
    const fallback = fallbackFocusRef?.current;
    const target =
      opener?.isConnected && !opener.closest("[inert]")
        ? opener
        : fallback?.isConnected && !fallback.closest("[inert]")
          ? fallback
          : undefined;
    target?.focus();
  }, [fallbackFocusRef, open]);

  if (!open) return null;

  const run = (perform: () => void) => {
    changeOpen(false);
    perform();
  };

  const containFocus = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Tab" || !dialogRef.current) return;
    const focusable = Array.from(
      dialogRef.current.querySelectorAll<HTMLElement>(PALETTE_FOCUSABLE),
    );
    if (focusable.length === 0) {
      event.preventDefault();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;
    if (!dialogRef.current.contains(active)) {
      event.preventDefault();
      first.focus();
    } else if (focusable.length === 1 || (event.shiftKey && active === first)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
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
        onClick={() => changeOpen(false)}
      />
      <div
        aria-label="Command palette"
        aria-modal="true"
        className="dsn-palette"
        data-testid="command-palette"
        onKeyDown={containFocus}
        ref={dialogRef}
        role="dialog"
      >
        <Command label="Command palette" filter={(value, search) => {
          const query = search.trim().toLocaleLowerCase();
          // Match names and retained aliases directly. Fuzzy subsequences can
          // put "Research workspace" ahead of an exact "channel" alias.
          return value.toLocaleLowerCase().includes(query) ? 1 : 0;
        }}>
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
