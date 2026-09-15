import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LocalModelResearchPanel } from "../src/components/LocalModelResearchPanel";
import type { LocalModelResearchProgress } from "../src/types/benchmarkProgress";

const base: LocalModelResearchProgress = {
  schema_version: "local-model-research-progress/v1", status: "available",
  candidate: "Qwen3.8 Flash-Next", accounting: "Outside the weekly maintenance allowance.",
  evidence_note: "Public development evidence only.", promotion_authorized: false,
  qualification_runs: [], comparisons: [], warnings: [],
};

describe("local model research", () => {
  it("shows pending work without invented scores", () => {
    render(<LocalModelResearchPanel data={base} />);
    expect(screen.getByText(/No qualification result recorded/)).toBeInTheDocument();
    expect(screen.getByText(/No validated paired run/)).toBeInTheDocument();
    expect(screen.getByText(/Outside the weekly/)).toBeInTheDocument();
  });
  it("does not interpret an orphan state as a live process", () => {
    render(<LocalModelResearchPanel data={{ ...base, qualification_runs: [{
      id: "qfn-c0-old", status: "unfinished_receipt", phase: "readiness", finished_at: null,
      candidate_window_minutes: null, minimum_memory_gib: null, probe_count: null,
      model_started: null,
      restoration: "unverified", source_sha256: "a".repeat(64),
    }] }} />);
    expect(screen.getByText(/Unfinished receipt · process state unverified/)).toBeInTheDocument();
    expect(screen.getByText(/Last recorded phase: readiness/)).toBeInTheDocument();
    expect(screen.getByText("Model identity pending")).toBeInTheDocument();
  });
  it("withholds gains from incomplete pairs even if a bad payload has numbers", () => {
    const arm = { declared: 2, attempted: 1, passed: 1, success_rate: 1, successful_task_runs_per_hour: 99 };
    render(<LocalModelResearchPanel data={{ ...base, comparisons: [{
      id: "pair", status: "incomplete", manifest_sha256: "a".repeat(64),
      comparison_eligible: false,
      run_sha256: { resident: "b".repeat(64), flash: "c".repeat(64) }, promotion_authorized: false,
      families: [{ family: "historical", comparison_eligible: false, paired_success_delta: 0.5, equal_source_task_success_delta: 0.5, source_task_interval_95: [0.3, 0.8], cohorts: { resident: arm, flash: arm } }],
    }] }} />);
    expect(screen.getAllByText("Withheld")).toHaveLength(3);
    expect(screen.queryByText("+50.0 pp")).not.toBeInTheDocument();
    expect(screen.getByText(/Comparison incomplete/)).toBeInTheDocument();
  });
  it("shows source errors and no result when unavailable", () => {
    render(<LocalModelResearchPanel data={{ ...base, status: "unavailable", warnings: ["Source invalid"] }} />);
    expect(screen.getByText(/No progress or result is inferred/)).toBeInTheDocument();
    expect(screen.getByText("Source invalid")).toBeInTheDocument();
  });
  it("separates Mia source identity from a host guardrail abort", () => {
    render(<LocalModelResearchPanel data={{ ...base, qualification_runs: [{
      id: "qfn-mia-c0-test", status: "failed", phase: "complete",
      finished_at: "2026-09-15T06:00:00+00:00", candidate_window_minutes: 4,
      minimum_memory_gib: 31, probe_count: 0, model_started: true,
      restoration: "verified", source_sha256: "a".repeat(64),
      failure_class: "experimental_startup_host_pageout_guardrail_abort",
      variant: {
        id: "mia-925d7be6-c0-s1", repository: "Mia-AiLab/Qwen3.8-Flash-Next-NVFP4",
        revision: "925d7be6c14c6c9442ef83e8f05b5a3c39304f69",
        served_model: "qwen3.8-flash-next-mia",
        image_id: "sha256:da68dd27a8ef1dadd0f380178a51f0a0671dc4235933ea1ae89fdaf66295ec72",
        model_artifact_sha256: "a40ce50173dd3aff54da88503894967e5248bbb927f9e4a91eff5a6a7270c168",
        spec_sha256: "dde4fe1f72cf91de92089a95748cee1f6a8204e351d517aa0ae46d8d27122857",
        qualification_profile: "C0-MIA-S1",
        evidence_class: "REGISTERED_SOURCE_ONLY",
      },
    }] }} />);
    expect(screen.getByText("Mia NVFP4")).toBeInTheDocument();
    expect(screen.getByText(/Host paging guardrail stopped qualification/)).toHaveTextContent("no model-quality conclusion");
    expect(screen.getByText(/registered source only/)).toBeInTheDocument();
    expect(screen.queryByText(/runtime qualified/)).toBeNull();
  });
  it("withholds a malformed or unregistered variant without blanking the panel", () => {
    render(<LocalModelResearchPanel data={{ ...base, qualification_runs: [{
      id: "qfn-mia-c0-unbound", status: "unfinished_receipt", phase: "readiness",
      finished_at: null, candidate_window_minutes: null, minimum_memory_gib: null,
      probe_count: null, model_started: null, restoration: "unverified",
      source_sha256: "a".repeat(64),
      variant: { id: null } as unknown as LocalModelResearchProgress["qualification_runs"][number]["variant"],
    }] }} />);
    expect(screen.getByText("Variant unavailable")).toBeInTheDocument();
    expect(screen.queryByText("Mia NVFP4")).toBeNull();
  });
  it("shows observed server startup separately from failed qualification and request speed", () => {
    render(<LocalModelResearchPanel data={{ ...base, qualification_runs: [{
      id: "qfn-c0-s1-recorded", status: "failed", phase: "complete",
      finished_at: "2026-09-15T05:33:37+00:00",
      candidate_window_minutes: 11.8, minimum_memory_gib: 31.1,
      probe_count: 3, model_started: true, restoration: "verified",
      source_sha256: "a".repeat(64),
      startup_seconds: 639.256889, startup_status: "recorded",
      startup_source_sha256: "b".repeat(64),
      qualification_elapsed_seconds: 1390.971028,
    }] }} />);
    expect(screen.getByText("639.3 s")).toBeInTheDocument();
    expect(screen.getByText("Full qualification: 1391.0 s")).toBeInTheDocument();
    expect(screen.getByText("Container start → model endpoint ready")).toBeInTheDocument();
    expect(screen.getByText(/Server startup measures container start/)).toHaveTextContent("separate from the full qualification window and from request latency");
    expect(screen.getByText("Readiness SHA256")).toBeInTheDocument();
    expect(screen.getByText("Result SHA256")).toBeInTheDocument();
    expect(screen.getByText("failed")).toBeInTheDocument();
  });
  it("keeps missing or invalid startup evidence distinct from zero", () => {
    const shared = {
      status: "failed" as const, phase: "complete", finished_at: null,
      candidate_window_minutes: null, minimum_memory_gib: null,
      probe_count: 0, model_started: false, restoration: "verified",
      source_sha256: "a".repeat(64), startup_seconds: null,
      startup_source_sha256: null,
    };
    render(<LocalModelResearchPanel data={{ ...base, qualification_runs: [
      { ...shared, id: "qfn-c0-before-ready", startup_status: "not_recorded" },
      { ...shared, id: "qfn-c0-invalid-ready", startup_status: "unavailable" },
    ] }} />);
    expect(screen.getByText("Source unavailable")).toBeInTheDocument();
    expect(screen.getAllByText("Not recorded").length).toBeGreaterThan(0);
    expect(screen.queryByText("0.0 s")).toBeNull();
  });
});
