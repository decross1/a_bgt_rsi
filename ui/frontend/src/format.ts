// Number formatting shared across dashboard components.

export function fmt(n: number | null | undefined, digits = 0): string {
  return typeof n === "number" && Number.isFinite(n) ? n.toFixed(digits) : "n/a";
}

/** A 0-1 ratio scaled to its percentage VALUE (n*100), or "n/a". Callers
 * append the "%" sign themselves. */
export function fmtRatioPct(n: number | null | undefined, digits = 0): string {
  return typeof n === "number" && Number.isFinite(n)
    ? `${(n * 100).toFixed(digits)}`
    : "n/a";
}
