import { useEffect, useRef, useState } from "react";
import {
  BrowserRouter,
  Navigate,
  NavLink,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import LoopAlertBanner from "./components/LoopAlertBanner";
import CommandPalette from "./design/CommandPalette";
import "./design/primitives.css";
import "./design/AtlasShell.css";
import Channel from "./routes/Channel";
import Cycles from "./routes/Cycles";
import DossierIndex from "./routes/DossierIndex";
import DossierReader from "./routes/DossierReader";
import ExperimentDetail from "./routes/ExperimentDetail";
import Experiments from "./routes/Experiments";
import Graph from "./routes/Graph";
import Inspector from "./routes/Inspector";
import Ladder from "./routes/Ladder";
import ModelIO from "./routes/ModelIO";
import Pulse from "./routes/Pulse";
import Development from "./routes/Development";

type Theme = "light" | "dark";
type NavGroupId = "now" | "research" | "operations";

const THEME_STORAGE_KEY = "oracle-lab-theme";
const NARROW_NAV_QUERY = "(max-width: 760px)";
const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

function focusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    (element) => !element.closest('[aria-hidden="true"]'),
  );
}

const NAV_GROUPS: {
  id: NavGroupId;
  label: string;
  links: { to: string; label: string; end?: boolean; primary?: boolean }[];
}[] = [
  {
    id: "now",
    label: "Now",
    links: [{ to: "/", label: "Now", end: true, primary: true }],
  },
  {
    id: "research",
    label: "Research",
    links: [
      { to: "/ladder", label: "Research", primary: true },
      { to: "/dossier", label: "Record library" },
      { to: "/experiments", label: "Evaluations" },
    ],
  },
  {
    id: "operations",
    label: "Operations",
    links: [
      { to: "/development", label: "Operations", primary: true },
      { to: "/channel", label: "Conversation" },
      { to: "/model-io", label: "Calls" },
      { to: "/cycles", label: "Trace history" },
    ],
  },
];

function readTheme(): Theme {
  try {
    return window.localStorage.getItem(THEME_STORAGE_KEY) === "dark"
      ? "dark"
      : "light";
  } catch {
    return "light";
  }
}

function isNarrowViewport(): boolean {
  return typeof window.matchMedia === "function"
    ? window.matchMedia(NARROW_NAV_QUERY).matches
    : false;
}

function groupForPath(pathname: string): NavGroupId | null {
  if (pathname === "/") return "now";
  if (
    pathname === "/ideas" ||
    pathname === "/todo" ||
    pathname.startsWith("/ladder") ||
    pathname.startsWith("/dossier") ||
    pathname.startsWith("/experiments")
  ) {
    return "research";
  }
  if (
    pathname === "/coordinator" ||
    pathname.startsWith("/development") ||
    pathname.startsWith("/channel") ||
    pathname.startsWith("/model-io") ||
    pathname.startsWith("/cycles") ||
    pathname.startsWith("/graph") ||
    pathname.startsWith("/chain/req/")
  ) {
    return "operations";
  }
  return null;
}

function AtlasNavigation({
  selected,
  onNavigate,
}: {
  selected: NavGroupId | null;
  onNavigate: () => void;
}) {
  return (
    <nav className="atlas-nav" aria-label="Lab workspace">
      {NAV_GROUPS.map((group) => (
        <section
          className="atlas-nav-group"
          data-group={group.id}
          data-selected={selected === group.id ? "true" : "false"}
          data-testid={`nav-group-${group.id}`}
          key={group.id}
          aria-labelledby={`nav-group-label-${group.id}`}
        >
          <h2 className="sr-only" id={`nav-group-label-${group.id}`}>
            {group.label}
          </h2>
          <div className="atlas-nav-links">
            {group.links.filter((link) => link.primary || selected === group.id).map((link) => (
              <NavLink
                className={({ isActive }) =>
                  [
                    "atlas-nav-link",
                    link.primary ? "atlas-nav-link--primary" : "atlas-nav-link--context",
                    isActive ? "atlas-nav-link--active" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")
                }
                end={link.end ?? false}
                key={link.to}
                onClick={onNavigate}
                to={link.to}
              >
                {link.label}
              </NavLink>
            ))}
          </div>
        </section>
      ))}
    </nav>
  );
}

function LegacyRedirect({ to }: { to: string }) {
  const { search, hash } = useLocation();
  return <Navigate to={`${to}${search}${hash}`} replace />;
}

function ThemeToggle({ theme, onToggle }: { theme: Theme; onToggle: () => void }) {
  const next = theme === "light" ? "dark" : "light";
  return (
    <button
      className="atlas-theme-toggle"
      type="button"
      aria-label={`Switch to ${next} theme`}
      onClick={onToggle}
    >
      Theme: {theme}
    </button>
  );
}

function AtlasApp() {
  const { pathname } = useLocation();
  const [theme, setTheme] = useState<Theme>(readTheme);
  const [isNarrow, setIsNarrow] = useState(isNarrowViewport);
  const [navOpen, setNavOpen] = useState(() => !isNarrowViewport());
  const [paletteOpen, setPaletteOpen] = useState(false);
  const navToggleRef = useRef<HTMLButtonElement>(null);
  const sidebarRef = useRef<HTMLElement>(null);
  const sidebarCloseRef = useRef<HTMLButtonElement>(null);
  const drawerOpenerRef = useRef<HTMLElement | null>(null);
  const restoreDrawerFocusRef = useRef(false);

  const closeNarrowNav = (restoreFocus = true) => {
    if (!isNarrow) return;
    restoreDrawerFocusRef.current = restoreFocus;
    setNavOpen(false);
  };

  const openNarrowNav = () => {
    drawerOpenerRef.current = navToggleRef.current;
    restoreDrawerFocusRef.current = false;
    setNavOpen(true);
  };

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch {
      // Theme remains usable in-memory when storage is blocked or unavailable.
    }
  }, [theme]);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia(NARROW_NAV_QUERY);
    const sync = (matches: boolean) => {
      setIsNarrow(matches);
      setNavOpen(!matches);
    };
    const onChange = (event: MediaQueryListEvent) => sync(event.matches);
    sync(media.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    if (!isNarrow || !navOpen) return;
    sidebarCloseRef.current?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeNarrowNav();
        return;
      }

      if (event.key !== "Tab" || !sidebarRef.current) return;
      const focusable = focusableElements(sidebarRef.current);
      if (focusable.length === 0) {
        event.preventDefault();
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      if (!sidebarRef.current.contains(active)) {
        event.preventDefault();
        first.focus();
      } else if (event.shiftKey && active === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isNarrow, navOpen]);

  useEffect(() => {
    if (navOpen || !restoreDrawerFocusRef.current) return;
    restoreDrawerFocusRef.current = false;
    const opener = drawerOpenerRef.current;
    const target =
      opener?.isConnected && !opener.closest("[inert]") ? opener : navToggleRef.current;
    target?.focus();
  }, [navOpen]);

  const handlePaletteOpenChange = (open: boolean) => {
    setPaletteOpen(open);
    if (open && isNarrow && navOpen) closeNarrowNav(false);
  };

  return (
    <div className="atlas-shell">
      {isNarrow && navOpen && (
        <button
          aria-label="Close navigation"
          className="atlas-sidebar-backdrop"
          data-testid="atlas-sidebar-backdrop"
          onClick={() => closeNarrowNav()}
          tabIndex={-1}
          type="button"
        />
      )}

      <aside
        aria-hidden={paletteOpen || (isNarrow && !navOpen) ? true : undefined}
        aria-label="Oracle Lab navigation"
        className={`atlas-sidebar${navOpen ? " atlas-sidebar--open" : ""}`}
        data-testid="atlas-sidebar"
        id="atlas-sidebar"
        inert={paletteOpen || (isNarrow && !navOpen) ? true : undefined}
        ref={sidebarRef}
        tabIndex={-1}
      >
        <button
          aria-label="Close menu"
          className="atlas-sidebar-close"
          onClick={() => closeNarrowNav()}
          ref={sidebarCloseRef}
          type="button"
        >
          Close
        </button>
        <div className="atlas-brand">
          <span className="atlas-brand-name">Oracle Lab</span>
          <span className="atlas-brand-kicker">research workspace</span>
        </div>

        <AtlasNavigation selected={groupForPath(pathname)} onNavigate={closeNarrowNav} />

        <div className="atlas-sidebar-footer">
          <a
            className="atlas-external-link"
            href={`http://${window.location.hostname}:5180/dashboard.html`}
            rel="noreferrer"
            target="_blank"
          >
            brain <span aria-hidden="true">↗</span>
          </a>
          <ThemeToggle
            theme={theme}
            onToggle={() => setTheme((value) => (value === "light" ? "dark" : "light"))}
          />
          <span className="atlas-palette-hint">⌘K / Ctrl K to jump</span>
        </div>
      </aside>

      <div
        aria-hidden={paletteOpen || (isNarrow && navOpen) ? true : undefined}
        className="atlas-workspace"
        data-testid="atlas-workspace"
        inert={paletteOpen || (isNarrow && navOpen) ? true : undefined}
      >
        <header className="atlas-mobile-header">
          <button
            aria-controls="atlas-sidebar"
            aria-expanded={navOpen}
            className="atlas-nav-toggle"
            onClick={() => (navOpen ? closeNarrowNav() : openNarrowNav())}
            ref={navToggleRef}
            type="button"
          >
            Menu
          </button>
          <span>Oracle Lab</span>
        </header>

        <main className="atlas-main" data-testid="atlas-main">
          <LoopAlertBanner />
          <Routes>
            <Route path="/" element={<Pulse />} />
            <Route path="/development" element={<Development />} />
            <Route path="/ladder" element={<Ladder />} />
            <Route path="/ideas" element={<LegacyRedirect to="/ladder" />} />
            <Route path="/dossier" element={<DossierIndex />} />
            <Route path="/dossier/:id" element={<DossierReader />} />
            <Route path="/todo" element={<LegacyRedirect to="/dossier" />} />
            <Route path="/channel" element={<Channel />} />
            <Route path="/cycles" element={<Cycles />} />
            <Route path="/coordinator" element={<LegacyRedirect to="/cycles" />} />
            <Route path="/graph" element={<Graph />} />
            <Route path="/experiments" element={<Experiments />} />
            <Route path="/experiments/:expId" element={<ExperimentDetail />} />
            <Route path="/model-io" element={<ModelIO />} />
            <Route path="/chain/req/:requestId" element={<Inspector />} />
          </Routes>
        </main>
      </div>

      <CommandPalette
        fallbackFocusRef={isNarrow ? navToggleRef : sidebarRef}
        onOpenChange={handlePaletteOpenChange}
      />
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AtlasApp />
    </BrowserRouter>
  );
}
