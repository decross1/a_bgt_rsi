// A single dashboard metric: label, current value, tone color, sparkline.
import Sparkline from "./Sparkline";

export type Tone = "ok" | "warn" | "bad" | "idle";

const TONE_TEXT: Record<Tone, string> = {
  ok: "text-emerald-400",
  warn: "text-amber-400",
  bad: "text-red-400",
  idle: "text-zinc-200",
};

const TONE_STROKE: Record<Tone, string> = {
  ok: "#34d399",
  warn: "#fbbf24",
  bad: "#f87171",
  idle: "#38bdf8",
};

interface MetricTileProps {
  label: string;
  value: string;
  unit?: string;
  tone?: Tone;
  values?: (number | null | undefined)[];
  reference?: number;
  note?: string;
}

export default function MetricTile({
  label,
  value,
  unit,
  tone = "idle",
  values,
  reference,
  note,
}: MetricTileProps) {
  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/40 p-3">
      <div className="text-xs uppercase tracking-wide text-zinc-500">{label}</div>
      <div className={`mt-1 text-xl font-semibold tabular-nums ${TONE_TEXT[tone]}`}>
        {value}
        {unit && (
          <span className="ml-1 text-xs font-normal text-zinc-500">{unit}</span>
        )}
      </div>
      <div className="mt-1 h-[26px]">
        {values && (
          <Sparkline values={values} color={TONE_STROKE[tone]} reference={reference} />
        )}
      </div>
      {note && <div className="mt-0.5 text-xs text-zinc-600">{note}</div>}
    </div>
  );
}
