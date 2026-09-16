import { Component, lazy, Suspense, useEffect, useRef, useState, type ReactNode } from "react";
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
import {
  researchScopeFromSearch,
  researchScopedHref,
  type ResearchScope,
} from "./researchScope";

// Each page loads on demand; the shell and current operational alert stay usable
// while a route loads, or when a stale client cannot fetch a newly deployed chunk.
const Channel = lazy(() => import("./routes/Channel"));
const Cycles = lazy(() => import("./routes/Cycles"));
const DossierIndex = lazy(() => import("./routes/DossierIndex"));
const DossierReader = lazy(() => import("./routes/DossierReader"));
const ExperimentDetail = lazy(() => import("./routes/ExperimentDetail"));
const Experiments = lazy(() => import("./routes/Experiments"));
const Inspector = lazy(() => import("./routes/Inspector"));
const Ladder = lazy(() => import("./routes/Ladder"));
const ModelIO = lazy(() => import("./routes/ModelIO"));
const Pulse = lazy(() => import("./routes/Pulse"));
const Development = lazy(() => import("./routes/Development"));
const BenchmarkProgress = lazy(() => import("./routes/BenchmarkProgress"));

class PageBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    return this.state.failed ? <section className="p-6" role="alert" aria-labelledby="page-error-heading">
      <h1 id="page-error-heading" className="text-xl font-semibold">This page could not be loaded</h1>
      <p className="mt-2">Reload to try again, or use the navigation to open another view.</p>
      <button type="button" className="mt-3 underline" onClick={() => window.location.reload()}>Reload page</button>
    </section> : this.props.children;
  }
}

type Theme = "light" | "dark";
type NavGroupId = "now" | "research" | "benchmarks" | "operations";

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
  links: { to: string; label: string; end?: boolean; primary?: boolean; archive?: boolean }[];
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
      { to: "/dossier", label: "Archive · records", archive: true },
      { to: "/experiments", label: "Archive · evaluations", archive: true },
    ],
  },
  {
    id: "benchmarks",
    label: "Benchmarks",
    links: [{ to: "/benchmarks", label: "Benchmarks", primary: true }],
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
  if (pathname.startsWith("/benchmarks")) return "benchmarks";
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
  researchScope,
}: {
  selected: NavGroupId | null;
  onNavigate: () => void;
  researchScope: ResearchScope;
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
                to={group.id === "research"
                  ? researchScopedHref(link.to, link.archive ? "all" : researchScope)
                  : link.to}
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
  const { pathname, search } = useLocation();
  const researchScope = researchScopeFromSearch(search);
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

        <AtlasNavigation
          selected={groupForPath(pathname)}
          onNavigate={closeNarrowNav}
          researchScope={researchScope}
        />

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
          <PageBoundary key={pathname}>
          <Suspense fallback={<p className="p-6" role="status">Loading page…</p>}>
          <Routes>
            <Route path="/" element={<Pulse />} />
            <Route path="/development" element={<Development />} />
            <Route path="/benchmarks" element={<BenchmarkProgress />} />
            <Route path="/ladder" element={<Ladder />} />
            <Route path="/ideas" element={<LegacyRedirect to="/ladder" />} />
            <Route path="/dossier" element={<DossierIndex />} />
            <Route path="/dossier/:id" element={<DossierReader />} />
            <Route path="/todo" element={<LegacyRedirect to="/dossier" />} />
            <Route path="/channel" element={<Channel />} />
            <Route path="/cycles" element={<Cycles />} />
            <Route path="/coordinator" element={<LegacyRedirect to="/cycles" />} />
            <Route path="/graph" element={<LegacyRedirect to="/cycles" />} />
            <Route path="/experiments" element={<Experiments />} />
            <Route path="/experiments/:expId" element={<ExperimentDetail />} />
            <Route path="/model-io" element={<ModelIO />} />
            <Route path="/chain/req/:requestId" element={<Inspector />} />
            <Route path="*" element={<section aria-labelledby="missing-route-heading"><h1 id="missing-route-heading">Page not found</h1><p>This address is unrecognized or retired. Use the navigation or command palette to find an existing record.</p><a href="/">Return to Now</a></section>} />
          </Routes>
          </Suspense>
          </PageBoundary>
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
