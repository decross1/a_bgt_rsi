import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import Experiments from "../src/routes/Experiments";
import type { ResearchResponse } from "../src/types/experiments";

function renderQuietly(initial: ResearchResponse) {
  const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  const view = render(
    <MemoryRouter>
      <Experiments initial={initial} />
    </MemoryRouter>,
  );
  const result = {
    ...view,
    errors: errorSpy.mock.calls.map((call) => String(call[0])),
    warnings: warnSpy.mock.calls.map((call) => String(call[0])),
    text: view.container.textContent ?? "",
    html: view.container.innerHTML,
  };
  errorSpy.mockRestore();
  warnSpy.mockRestore();
  return result;
}

describe("Experiments catalog hardening", () => {
  it("keeps readable rows when neighboring tiers and rows are malformed", () => {
    const payload = {
      available: true,
      tiers: [
        null,
        {
          tier: "synthetic",
          label: "Synthetic",
          description: "Source group",
          experiments: [
            null,
            {
              id: "exp_readable",
              title: "Readable source",
              verdict: null,
              bridge: null,
            },
          ],
        },
        {
          tier: "applied",
          label: "Applied",
          experiments: "wrong shape",
        },
      ],
      untiered: [],
    } as unknown as ResearchResponse;
    const { errors, warnings } = renderQuietly(payload);
    expect(screen.getByTestId("research-card-exp_readable")).toBeInTheDocument();
    expect(screen.getByTestId("catalog-malformed")).toHaveTextContent(
      /malformed source rows/i,
    );
    expect(errors).toHaveLength(0);
    expect(warnings).toHaveLength(0);
  });

  it("does not render objects, NaN or Infinity as source text", () => {
    const payload = {
      available: true,
      tiers: [
        {
          tier: { wrong: true },
          label: ["wrong"],
          experiments: [
            {
              id: "exp_numbers",
              title: { wrong: true },
              verdict: { text: { wrong: true }, tone: "ok" },
              bridge: [
                { iteration_id: "iter-a", metric: "score", value: NaN },
                { iteration_id: "iter-b", metric: "score", value: Infinity },
              ],
              has_results_dir: true,
              n_results_files: Infinity,
            },
          ],
        },
      ],
      untiered: [],
    } as unknown as ResearchResponse;
    const { text, errors, warnings } = renderQuietly(payload);
    expect(screen.getByTestId("research-card-exp_numbers")).toBeInTheDocument();
    expect(text).not.toMatch(/NaN|Infinity|\[object Object\]/);
    expect(errors).toHaveLength(0);
    expect(warnings).toHaveLength(0);
  });

  it("renders escaped unusual content and safely links a lone-surrogate id", () => {
    const weird = "‮عربي‬\n<script>alert(1)</script> 漢字";
    const loneSurrogate = "exp\uD800_truncated";
    const payload = {
      available: true,
      tiers: [
        {
          tier: "synthetic",
          label: "Synthetic",
          experiments: [
            {
              id: loneSurrogate,
              title: weird,
              verdict: { text: weird, tone: "warn" },
              bridge: [],
            },
          ],
        },
      ],
      untiered: [],
    } as unknown as ResearchResponse;
    const { container, errors, warnings } = renderQuietly(payload);
    expect(screen.getByTestId(`research-card-${loneSurrogate}`)).toBeInTheDocument();
    expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).toContain("<script>alert(1)</script>");
    expect(errors).toHaveLength(0);
    expect(warnings).toHaveLength(0);
  });

  it("treats prototype-member and forward-compatible tones as unqualified", () => {
    const tones = ["toString", "constructor", "__proto__", "future-tone"];
    const payload = {
      available: true,
      tiers: [
        {
          tier: "synthetic",
          label: "Synthetic",
          experiments: tones.map((tone, index) => ({
            id: `exp_${index}`,
            title: `Tone ${tone}`,
            verdict: { text: `reported ${tone}`, tone },
            bridge: [],
          })),
        },
      ],
      untiered: [],
    } as unknown as ResearchResponse;
    const { html, errors, warnings } = renderQuietly(payload);
    for (let index = 0; index < tones.length; index += 1) {
      expect(screen.getByTestId(`verdict-exp_${index}`))
        .toHaveAttribute("data-tone", "unknown");
    }
    expect(html).not.toMatch(/\[native code\]|function toString/);
    expect(errors).toHaveLength(0);
    expect(warnings).toHaveLength(0);
  });

  it("keeps a 1200-entry source catalog renderable without reviving cycles", () => {
    const experiments = Array.from({ length: 1200 }, (_, index) => ({
      id: `exp_${index}`,
      title: `Source ${index}`,
      verdict: null,
      bridge: [],
      has_results_dir: false,
      n_results_files: 0,
    }));
    const payload = {
      available: true,
      tiers: [
        {
          tier: "synthetic",
          label: "Synthetic",
          experiments,
        },
      ],
      untiered: [],
    } as unknown as ResearchResponse;
    const { errors, warnings } = renderQuietly(payload);
    expect(screen.getByText(/Showing 1200 of 1200/)).toBeInTheDocument();
    expect(screen.getAllByRole("article")).toHaveLength(1200);
    expect(screen.queryByTestId("coordinator-cycles-section")).toBeNull();
    expect(errors).toHaveLength(0);
    expect(warnings).toHaveLength(0);
  });

  it("distinguishes malformed top-level lists from a valid empty response", () => {
    const malformed = {
      available: true,
      tiers: "not an array",
      untiered: { not: "an array" },
    } as unknown as ResearchResponse;
    const { errors, warnings } = renderQuietly(malformed);
    expect(screen.getByTestId("catalog-malformed")).toBeInTheDocument();
    expect(screen.getByTestId("catalog-empty")).toBeInTheDocument();
    expect(errors).toHaveLength(0);
    expect(warnings).toHaveLength(0);
  });
});
