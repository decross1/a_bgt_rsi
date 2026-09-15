import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { ModelRuntime, ServedModel } from "../src/api/http";

vi.mock("../src/api/http", () => ({
  getWorkloadHint: vi.fn().mockResolvedValue({ available: false }),
}));

import ModelServerCard from "../src/components/ModelServerCard";

const selectedProfile: NonNullable<ModelRuntime["candidate_variant"]> = {
  spec_id: "mia-925d7be6-ctx69632-bf16kv3g-v1",
  spec_sha256: "a".repeat(64),
  repository: "Mia-AiLab/Qwen3.8-Flash-Next-NVFP4",
  revision: "925d7be6c14c6c9442ef83e8f05b5a3c39304f69",
  served_model: "qwen3.8-flash-next-mia",
  image_id: `sha256:${"b".repeat(64)}`,
  model_artifact_sha256: "c".repeat(64),
  profile: "MIA-NATIVE69632-BF16KV3G-MTP0",
  configured_max_context_tokens: 69632,
  configured_mtp_speculative_tokens: 0,
  configured_kv_cache_memory_bytes: 3 * 1024 ** 3,
  source: "registered_plan_and_controller_state",
  image_evidence: "registered_source_only",
  promotion_authorized: false,
};

const catalog: ServedModel = {
  url: "http://127.0.0.1:8012",
  model: "qwen3.8-flash-next-mia",
  error: null,
  probed_at: new Date().toISOString(),
  configured_model: "qwen3.8-flash-next",
  configured_max_context_tokens: 32768,
  observed_max_context_tokens: null,
  deployment_role: "research_candidate",
  benchmark_cohort: "flash",
  promotion_authorized: false,
  models_endpoint_status: "available",
  service_status: "online",
  identity_status: "mismatch",
  metrics_endpoint_status: "unreachable",
  activity_status: "unknown",
  metrics: null,
  metrics_error: null,
};

it("shows the controller-bound profile without relabeling the static inventory default", () => {
  render(
    <ModelServerCard
      title="Flash research candidate"
      endpointName="flash"
      servedModel="qwen3.8-flash-next-mia"
      pick={() => null}
      samples={[]}
      accent="violet"
      inventory={catalog}
      selectedVariant={selectedProfile}
    />,
  );
  const profile = screen.getByTestId("flash-profile-config");
  expect(profile.textContent)
    .toContain(`${selectedProfile.configured_max_context_tokens?.toLocaleString()} tokens`);
  expect(profile.textContent).toContain("MTP configured depth 0");
  expect(profile.textContent).toContain("KV reserve 3.0 GiB");
  expect(profile.textContent).toContain("do not measure context quality or decode speed");
  expect(screen.getByText(/Static inventory default:/).textContent)
    .toContain("qwen3.8-flash-next");
});
