// StatusDot — the semantic status dot (R0 design system). Colors come ONLY
// from the semantic status token set (emerald/amber/rose/sky/zinc), which is
// reserved for run/rung status. `pulse` is opt-in and must mean "genuinely
// running right now" — a static state never pulses.
import "./primitives.css";

export type Status = "ok" | "warn" | "bad" | "info" | "idle";

const COLOR: Record<Status, string> = {
  ok: "var(--status-ok)",
  warn: "var(--status-warn)",
  bad: "var(--status-bad)",
  info: "var(--status-info)",
  idle: "var(--status-idle)",
};

export default function StatusDot({
  status,
  pulse = false,
  label,
  className,
}: {
  status: Status;
  /** ONLY when the thing is genuinely running/in-flight. */
  pulse?: boolean;
  /** Accessible name; defaults to the status word. */
  label?: string;
  className?: string;
}) {
  return (
    <span
      role="img"
      aria-label={label ?? status}
      data-testid="status-dot"
      data-status={status}
      className={`dsn-dot${pulse ? " dsn-dot--pulse" : ""}${className ? ` ${className}` : ""}`}
      style={{ color: COLOR[status] }}
    />
  );
}
