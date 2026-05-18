// HealthStrip renders current values and labels all five tiles.
import { render, screen } from "@testing-library/react";
import HealthStrip from "../src/components/HealthStrip";
import type { TelemetrySample } from "../src/types/schemas";

function sample(tempC: number): TelemetrySample {
  return {
    timestamp: "2026-05-18T10:00:00.000+00:00",
    gpu: {
      util_pct: 0,
      mem_used_mb: null, // GB10 unified memory
      mem_total_mb: null,
      temp_c: tempC,
      power_w: 5.5,
    },
    host: { cpu_pct: 10, mem_used_mb: 5000, cpu_temp_c: 44, load_avg: [1, 1, 1] },
    vllm: null,
    processes: [],
    read_errors: null,
  };
}

describe("HealthStrip", () => {
  it("shows the latest GPU temp and labels every tile", () => {
    render(<HealthStrip samples={[sample(41), sample(83)]} />);
    for (const label of ["GPU util", "GPU memory", "GPU temp", "GPU power", "CPU temp"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getByText("83.0")).toBeInTheDocument(); // latest sample's temp
    expect(screen.getByText("GB10 unified memory — n/a")).toBeInTheDocument();
  });
});
