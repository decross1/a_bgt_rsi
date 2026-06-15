// HostMemoryTile shows host RAM USED (GiB) from telemetry's host.mem_used_mb,
// and renders an honest unavailable state ("—") when no host sample carries a
// usable mem figure — it never fabricates a number (inviolate rule 4). The
// `initial` prop pins the render so the test never touches the network.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import HostMemoryTile, {
  hostMemSeries,
} from "../src/components/HostMemoryTile";
import type { TelemetrySample } from "../src/types/schemas";

// Minimal telemetry sample carrying just the host block under test.
function sample(memUsedMb: number | null): TelemetrySample {
  return {
    timestamp: "2026-06-14T10:00:00.000+00:00",
    gpu: null,
    host:
      memUsedMb == null
        ? null
        : { cpu_pct: 10, mem_used_mb: memUsedMb, cpu_temp_c: 44, load_avg: [1, 1, 1] },
    vllm: null,
    processes: [],
    read_errors: null,
  };
}

describe("HostMemoryTile", () => {
  it("renders host RAM used in GiB from the latest sample", () => {
    // 8192 MB → 8.0 GiB; latest of the two samples wins.
    render(<HostMemoryTile initial={[sample(4096), sample(8192)]} />);
    expect(screen.getByText("Host RAM")).toBeInTheDocument();
    expect(screen.getByText("8.0")).toBeInTheDocument();
    expect(screen.getByText("GiB")).toBeInTheDocument();
    expect(screen.getByText("used")).toBeInTheDocument();
  });

  it("renders an honest unavailable state when host telemetry is null", () => {
    render(<HostMemoryTile initial={[sample(null)]} />);
    expect(screen.getByText("Host RAM")).toBeInTheDocument();
    // No fabricated number — an em dash and an explicit unavailable note.
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByText("host telemetry unavailable")).toBeInTheDocument();
    // It must NOT claim a GiB figure for a missing reading.
    expect(screen.queryByText("GiB")).toBeNull();
  });

  it("renders unavailable for an empty telemetry series (pre-sample)", () => {
    render(<HostMemoryTile initial={[]} />);
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByText("host telemetry unavailable")).toBeInTheDocument();
  });
});

describe("hostMemSeries", () => {
  it("converts mem_used_mb to GiB and picks the latest usable reading", () => {
    const { values, latestGiB } = hostMemSeries([sample(2048), sample(6144)]);
    expect(values).toEqual([2, 6]);
    expect(latestGiB).toBe(6);
  });

  it("maps a null/absent host to a null point and skips it for the latest", () => {
    // A trailing null host sample must not blank a tile with fresh data behind it.
    const { values, latestGiB } = hostMemSeries([sample(3072), sample(null)]);
    expect(values).toEqual([3, null]);
    expect(latestGiB).toBe(3);
  });

  it("returns a null latest when no sample carries a usable mem figure", () => {
    expect(hostMemSeries([sample(null)]).latestGiB).toBeNull();
    expect(hostMemSeries([]).latestGiB).toBeNull();
  });
});
