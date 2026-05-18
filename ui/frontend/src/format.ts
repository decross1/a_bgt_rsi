// Number formatting shared across dashboard components.

export function fmt(n: number | null | undefined, digits = 0): string {
  return typeof n === "number" && Number.isFinite(n) ? n.toFixed(digits) : "n/a";
}

/** A 0-1 ratio as a percentage string, or "n/a". */
export function fmtRatioPct(n: number | null | undefined, digits = 0): string {
  return typeof n === "number" && Number.isFinite(n)
    ? `${(n * 100).toFixed(digits)}`
    : "n/a";
}
