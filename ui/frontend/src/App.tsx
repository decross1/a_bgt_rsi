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

const NAV_GROUPS: {
  id: NavGroupId;
  label: string;
  links: { to: string; label: string; end?: boolean; primary?: boolean }[];
}[] = [
  {
    id: "now",
    label: "Now",
    links: [{ to: "/", label: "pulse", end: true, primary: true }],
  },
  {
    id: "research",
    label: "Research",
    links: [
      { to: "/ladder", label: "ladder", primary: true },
      { to: "/dossier", label: "dossiers" },
      { to: "/experiments", label: "experiments" },
    ],
  },
  {
    id: "operations",
    label: "Operations",
    links: [
      { to: "/development", label: "development", primary: true },
      { to: "/channel", label: "channel" },
      { to: "/model-io", label: "model i/o" },
      { to: "/cycles", label: "cycles" },
      { to: "/graph", label: "graph" },
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
          <h2 className="atlas-nav-group-label" id={`nav-group-label-${group.id}`}>
            {group.label}
          </h2>
          <div className="atlas-nav-links">
            {group.links.map((link) => (
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
  const navToggleRef = useRef<HTMLButtonElement>(null);

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
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setNavOpen(false);
        navToggleRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isNarrow, navOpen]);

  const closeNarrowNav = () => {
    if (isNarrow) setNavOpen(false);
  };

  return (
    <div className="atlas-shell">
      {isNarrow && navOpen && (
        <button
          aria-label="Close navigation"
          className="atlas-sidebar-backdrop"
          onClick={() => setNavOpen(false)}
          type="button"
        />
      )}

      <aside
        aria-hidden={isNarrow && !navOpen ? true : undefined}
        aria-label="Oracle Lab navigation"
        className={`atlas-sidebar${navOpen ? " atlas-sidebar--open" : ""}`}
        data-testid="atlas-sidebar"
        id="atlas-sidebar"
        inert={isNarrow && !navOpen ? true : undefined}
      >
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

      <div className="atlas-workspace">
        <header className="atlas-mobile-header">
          <button
            aria-controls="atlas-sidebar"
            aria-expanded={navOpen}
            className="atlas-nav-toggle"
            onClick={() => setNavOpen((value) => !value)}
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
            <Route path="/ideas" element={<Navigate to="/ladder" replace />} />
            <Route path="/dossier" element={<DossierIndex />} />
            <Route path="/dossier/:id" element={<DossierReader />} />
            <Route path="/todo" element={<Navigate to="/dossier" replace />} />
            <Route path="/channel" element={<Channel />} />
            <Route path="/cycles" element={<Cycles />} />
            <Route path="/coordinator" element={<Navigate to="/cycles" replace />} />
            <Route path="/graph" element={<Graph />} />
            <Route path="/experiments" element={<Experiments />} />
            <Route path="/experiments/:expId" element={<ExperimentDetail />} />
            <Route path="/model-io" element={<ModelIO />} />
            <Route path="/chain/req/:requestId" element={<Inspector />} />
          </Routes>
        </main>
      </div>

      <CommandPalette />
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
