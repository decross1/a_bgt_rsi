import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/components/LoopAlertBanner", () => ({
  default: () => <div data-testid="loop-alert-banner" />,
}));
vi.mock("../src/routes/Pulse", () => ({ default: () => <div data-testid="route-pulse" /> }));
vi.mock("../src/routes/Development", () => ({ default: () => <div data-testid="route-development" /> }));
vi.mock("../src/routes/Ladder", () => ({ default: () => <div data-testid="route-ladder" /> }));
vi.mock("../src/routes/DossierIndex", () => ({ default: () => <div data-testid="route-dossier-index" /> }));
vi.mock("../src/routes/DossierReader", () => ({ default: () => <div data-testid="route-dossier-reader" /> }));
vi.mock("../src/routes/Channel", () => ({ default: () => <div data-testid="route-channel" /> }));
vi.mock("../src/routes/Cycles", () => ({ default: () => <div data-testid="route-cycles" /> }));
vi.mock("../src/routes/Graph", () => ({ default: () => <div data-testid="route-graph" /> }));
vi.mock("../src/routes/Experiments", () => ({ default: () => <div data-testid="route-experiments" /> }));
vi.mock("../src/routes/ExperimentDetail", () => ({ default: () => <div data-testid="route-experiment-detail" /> }));
vi.mock("../src/routes/ModelIO", () => ({ default: () => <div data-testid="route-model-io" /> }));
vi.mock("../src/routes/Inspector", () => ({ default: () => <div data-testid="route-inspector" /> }));

import App from "../src/App";

type Oklch = [number, number, number];

function readOklch(source: string, property: string): Oklch {
  const match = source.match(
    new RegExp(`--${property}:\\s*oklch\\(([0-9.]+)\\s+([0-9.]+)\\s+([0-9.]+)`),
  );
  if (!match) throw new Error(`Missing OKLCH property: ${property}`);
  return [Number(match[1]), Number(match[2]), Number(match[3])];
}

function relativeLuminance([lightness, chroma, hue]: Oklch): number {
  const radians = (hue * Math.PI) / 180;
  const a = chroma * Math.cos(radians);
  const b = chroma * Math.sin(radians);
  const l = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (lightness - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const linear = [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
  ].map((channel) => Math.max(0, Math.min(1, channel)));
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

function contrast(first: Oklch, second: Oklch): number {
  const a = relativeLuminance(first);
  const b = relativeLuminance(second);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

const originalMatchMedia = window.matchMedia;

function useViewport(narrow: boolean) {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: narrow,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
    writable: true,
  });
}

beforeEach(() => {
  useViewport(false);
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  window.history.replaceState({}, "", "/");
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: originalMatchMedia,
    writable: true,
  });
  document.documentElement.removeAttribute("data-theme");
  window.localStorage.clear();
  window.history.replaceState({}, "", "/");
});

describe("Atlas shell route preservation", () => {
  it.each([
    ["/", "route-pulse"],
    ["/development", "route-development"],
    ["/ladder", "route-ladder"],
    ["/dossier", "route-dossier-index"],
    ["/dossier/claim-1", "route-dossier-reader"],
    ["/channel", "route-channel"],
    ["/cycles", "route-cycles"],
    ["/graph", "route-graph"],
    ["/experiments", "route-experiments"],
    ["/experiments/exp-1", "route-experiment-detail"],
    ["/model-io", "route-model-io"],
    ["/chain/req/request-1", "route-inspector"],
  ])("keeps %s on its existing surface", (path, testId) => {
    window.history.replaceState({}, "", path);
    render(<App />);
    expect(screen.getByTestId(testId)).toBeInTheDocument();
    expect(within(screen.getByTestId("atlas-main")).getByTestId("loop-alert-banner")).toBeInTheDocument();
  });

  it.each([
    ["/ideas", "/ladder", "route-ladder"],
    ["/todo", "/dossier", "route-dossier-index"],
    ["/coordinator", "/cycles", "route-cycles"],
  ])("retains the %s redirect", async (from, to, testId) => {
    window.history.replaceState({}, "", from);
    render(<App />);
    await waitFor(() => expect(screen.getByTestId(testId)).toBeInTheDocument());
    expect(window.location.pathname).toBe(to);
  });
});

describe("Atlas navigation grouping", () => {
  it.each([
    ["/", "now"],
    ["/ladder", "research"],
    ["/dossier/claim-1", "research"],
    ["/experiments/exp-1", "research"],
    ["/development", "operations"],
    ["/channel", "operations"],
    ["/model-io", "operations"],
    ["/cycles", "operations"],
    ["/graph", "operations"],
    ["/chain/req/request-1", "operations"],
  ])("selects %s inside the %s group", (path, selected) => {
    window.history.replaceState({}, "", path);
    render(<App />);
    for (const group of ["now", "research", "operations"]) {
      expect(screen.getByTestId(`nav-group-${group}`)).toHaveAttribute(
        "data-selected",
        group === selected ? "true" : "false",
      );
    }
  });

  it("keeps the three primary routes and every context destination visible", () => {
    render(<App />);
    const nav = screen.getByRole("navigation", { name: "Lab workspace" });
    const destinations = [
      ["pulse", "/"],
      ["ladder", "/ladder"],
      ["dossiers", "/dossier"],
      ["experiments", "/experiments"],
      ["development", "/development"],
      ["channel", "/channel"],
      ["model i/o", "/model-io"],
      ["cycles", "/cycles"],
      ["graph", "/graph"],
    ];
    for (const [name, href] of destinations) {
      expect(within(nav).getByRole("link", { name })).toHaveAttribute("href", href);
    }
    expect(screen.getByRole("link", { name: /brain/ })).toHaveAttribute(
      "href",
      `http://${window.location.hostname}:5180/dashboard.html`,
    );
  });
});

describe("Atlas theme and narrow navigation", () => {
  it("defaults to light, retains a dark option, and remembers the choice", async () => {
    const first = render(<App />);
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", "light"));
    fireEvent.click(screen.getByRole("button", { name: "Switch to dark theme" }));
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", "dark"));
    expect(window.localStorage.getItem("oracle-lab-theme")).toBe("dark");

    first.unmount();
    render(<App />);
    expect(screen.getByRole("button", { name: "Switch to light theme" })).toBeInTheDocument();
  });

  it("keeps both themes usable when browser storage throws", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("storage blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("storage blocked");
    });

    expect(() => render(<App />)).not.toThrow();
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", "light"));
    fireEvent.click(screen.getByRole("button", { name: "Switch to dark theme" }));
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", "dark"));
  });

  it("opens, closes, and restores focus for the narrow sidebar", async () => {
    useViewport(true);
    window.history.replaceState({}, "", "/ladder");
    render(<App />);

    const toggle = screen.getByRole("button", { name: "Menu" });
    const sidebar = screen.getByTestId("atlas-sidebar");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(sidebar).toHaveAttribute("aria-hidden", "true");

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(sidebar).not.toHaveAttribute("aria-hidden");

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(toggle).toHaveAttribute("aria-expanded", "false"));
    expect(toggle).toHaveFocus();

    fireEvent.click(toggle);
    fireEvent.click(screen.getByRole("link", { name: "ladder" }));
    await waitFor(() => expect(toggle).toHaveAttribute("aria-expanded", "false"));
  });
});

describe("Atlas light-theme source compatibility", () => {
  it("keeps every Channel role label above 4.5:1 without changing role hues", () => {
    const here = dirname(fileURLToPath(import.meta.url));
    const shell = readFileSync(resolve(here, "../src/design/AtlasShell.css"), "utf8");
    const tokens = readFileSync(resolve(here, "../src/design/tokens.css"), "utf8");
    const channel = readFileSync(
      resolve(here, "../src/components/channel/channel.css"),
      "utf8",
    );
    const lightOverride = shell.match(
      /:root:not\(\[data-theme="dark"\]\) \.atlas-main \.chn \{([^}]+)\}/,
    )?.[1];

    expect(lightOverride).toBeDefined();
    expect(channel).toContain("--voice-nara: oklch(0.72 0.12 290)");
    expect(channel).toContain("--voice-pi: oklch(0.74 0.12 330)");
    expect(lightOverride).toContain("--voice-human: var(--neutral-600)");
    expect(lightOverride).toContain("--voice-oracle: var(--neutral-700)");
    expect(lightOverride).toContain("--voice-other: var(--fg-muted)");

    const surface = readOklch(tokens, "surface-1");
    const voices = [
      readOklch(lightOverride ?? "", "voice-nara"),
      readOklch(lightOverride ?? "", "voice-pi"),
      readOklch(tokens, "neutral-600"),
      readOklch(tokens, "neutral-700"),
      readOklch(tokens, "fg-muted"),
    ];
    for (const voice of voices) {
      expect(contrast(voice, surface)).toBeGreaterThanOrEqual(4.5);
    }
  });
});
