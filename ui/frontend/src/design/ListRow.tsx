// ListRow — the 36px dense list row (R0 design system). Hover = one surface
// step (--surface-2); height rides the --row-h token, so density switches via
// a container's data-density="dense" attribute, not a prop. An onClick row is
// keyboard-operable (role=button, Enter/Space).
import { KeyboardEvent, ReactNode } from "react";
import "./primitives.css";

export default function ListRow({
  children,
  onClick,
  selected = false,
  className,
  testId,
}: {
  children: ReactNode;
  onClick?: () => void;
  selected?: boolean;
  className?: string;
  testId?: string;
}) {
  const interactive = typeof onClick === "function";
  const cls = [
    "dsn-row",
    interactive ? "dsn-row--interactive" : "",
    selected ? "dsn-row--selected" : "",
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ");
  const onKeyDown = interactive
    ? (e: KeyboardEvent) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick();
        }
      }
    : undefined;
  return (
    <div
      className={cls}
      data-testid={testId ?? "list-row"}
      onClick={onClick}
      onKeyDown={onKeyDown}
      role={interactive ? "button" : undefined}
      tabIndex={interactive ? 0 : undefined}
      aria-pressed={interactive && selected ? true : undefined}
    >
      {children}
    </div>
  );
}
