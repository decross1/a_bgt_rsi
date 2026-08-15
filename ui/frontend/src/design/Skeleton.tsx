// Skeleton — shape-matching loading shimmer (R0 design system). Use the shape
// that matches what will render: SkeletonRows before a ListRow list (rows at
// var(--row-h)), SkeletonCard before a Card. The shimmer is opacity-only and
// stops entirely under prefers-reduced-motion (primitives.css).
import { CSSProperties } from "react";
import "./primitives.css";

export function Skeleton({
  width,
  height = 12,
  className,
  style,
}: {
  width?: number | string;
  height?: number | string;
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <div
      aria-hidden="true"
      data-testid="skeleton"
      className={`dsn-skeleton${className ? ` ${className}` : ""}`}
      style={{ width, height, ...style }}
    />
  );
}

export function SkeletonRows({ count = 3 }: { count?: number }) {
  return (
    <div role="status" aria-label="loading" data-testid="skeleton-rows">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="dsn-row">
          <Skeleton width={16} height={16} style={{ borderRadius: "var(--radius-pill)" }} />
          <Skeleton width={`${55 - (i % 3) * 10}%`} />
          <Skeleton width="15%" style={{ marginLeft: "auto" }} />
        </div>
      ))}
    </div>
  );
}

export function SkeletonCard({ lines = 3 }: { lines?: number }) {
  return (
    <div
      role="status"
      aria-label="loading"
      data-testid="skeleton-card"
      className="dsn-skeleton dsn-skeleton--card"
    >
      <Skeleton width="40%" height={14} style={{ marginBottom: "var(--space-3)" }} />
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton
          key={i}
          width={`${90 - (i % 3) * 18}%`}
          style={{ marginBottom: "var(--space-2)" }}
        />
      ))}
    </div>
  );
}
