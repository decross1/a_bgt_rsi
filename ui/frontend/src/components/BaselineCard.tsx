// Healthy-baseline reference card (ui_plan.md section 5.3). Constants from
// ui_plan.md r2 and CLAUDE.md; should become data-driven from bench/day1.csv
// once the apparatus commits it (ui_plan.md section 9, open question).

const BASELINES: { label: string; value: string }[] = [
  {
    label: "Decode tok/s",
    value: "NVFP4 baseline ≈52; MTP (≈96) deferred; hard floor 40",
  },
  { label: "GPU idle power", value: "≈5 W measured (apparatus passes ≤35 W)" },
  { label: "GPU temp", value: "green ≤70 °C · amber 70-80 · red >80" },
  { label: "CPU temp", value: "green ≤75 °C · amber 75-85 · red >85" },
  { label: "GPU power", value: "green ≤90 W · amber 90-110 · red >110" },
  { label: "Stack", value: "CUDA 13.0 · MARLIN NVFP4 MoE · vLLM v0.20.0" },
];

export default function BaselineCard() {
  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/40 p-4">
      <h2 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
        Healthy baseline (day 1)
      </h2>
      <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
        {BASELINES.map((b) => (
          <div key={b.label} className="flex gap-2">
            <dt className="shrink-0 text-zinc-500">{b.label}:</dt>
            <dd className="text-zinc-300">{b.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
