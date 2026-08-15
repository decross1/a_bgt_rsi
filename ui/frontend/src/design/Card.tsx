// Card — the surface primitive (R0 design system). Elevation = a lighter
// surface step (--surface-1) + a 1px border (--border-1) at --radius-card.
// NO box shadows — that is the system's elevation rule, not a style choice.
import { ReactNode } from "react";
import "./primitives.css";

export default function Card({
  title,
  children,
  className,
  testId,
}: {
  title?: ReactNode;
  children: ReactNode;
  className?: string;
  testId?: string;
}) {
  return (
    <section
      className={`dsn-card${className ? ` ${className}` : ""}`}
      data-testid={testId ?? "card"}
    >
      {title !== undefined && (
        <h3
          style={{
            margin: 0,
            marginBottom: "var(--space-3)",
            fontSize: "var(--text-title)",
            fontWeight: "var(--weight-medium)",
          }}
        >
          {title}
        </h3>
      )}
      {children}
    </section>
  );
}
