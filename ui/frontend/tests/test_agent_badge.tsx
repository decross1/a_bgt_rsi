// AgentBadge renders the provenance `agent` string as a small uppercase badge,
// tones it by kind, compacts workflow agents to "wf:<role>", and renders
// nothing for a null/empty agent.
import { render, screen } from "@testing-library/react";
import AgentBadge from "../src/components/AgentBadge";

describe("AgentBadge", () => {
  it("renders the coordinator agent verbatim (CSS uppercases it)", () => {
    render(<AgentBadge agent="coordinator" />);
    const badge = screen.getByTestId("agent-badge");
    expect(badge).toHaveTextContent("coordinator");
    expect(badge.className).toContain("text-sky-300");
    expect(badge.className).toContain("uppercase");
  });

  it("tones nara emerald", () => {
    render(<AgentBadge agent="nara" />);
    const badge = screen.getByTestId("agent-badge");
    expect(badge).toHaveTextContent("nara");
    expect(badge.className).toContain("text-emerald-400");
  });

  it("tones human zinc", () => {
    render(<AgentBadge agent="human" />);
    const badge = screen.getByTestId("agent-badge");
    expect(badge).toHaveTextContent("human");
    expect(badge.className).toContain("text-zinc-400");
  });

  it("compacts a workflow agent to wf:<role> and tones it indigo", () => {
    render(<AgentBadge agent="workflow:wf-2026-06-09-001/builder" />);
    const badge = screen.getByTestId("agent-badge");
    expect(badge).toHaveTextContent("wf:builder");
    // The full id and the "workflow:" prefix are dropped from the label.
    expect(badge.textContent).not.toContain("wf-2026-06-09-001");
    expect(badge.className).toContain("text-indigo-300");
  });

  it("falls back to wf:<rest> when a workflow agent has no id/role split", () => {
    render(<AgentBadge agent="workflow:auditor" />);
    expect(screen.getByTestId("agent-badge")).toHaveTextContent("wf:auditor");
  });

  it("renders an unknown agent as a quiet zinc badge with its own text", () => {
    render(<AgentBadge agent="arxiv_pick" />);
    const badge = screen.getByTestId("agent-badge");
    expect(badge).toHaveTextContent("arxiv_pick");
    expect(badge.className).toContain("text-zinc-400");
  });

  it("appends a passed className", () => {
    render(<AgentBadge agent="coordinator" className="ml-auto" />);
    expect(screen.getByTestId("agent-badge").className).toContain("ml-auto");
  });

  it("renders nothing when agent is null", () => {
    const { container } = render(<AgentBadge agent={null} />);
    expect(screen.queryByTestId("agent-badge")).toBeNull();
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when agent is empty/whitespace", () => {
    render(<AgentBadge agent="   " />);
    expect(screen.queryByTestId("agent-badge")).toBeNull();
  });
});
