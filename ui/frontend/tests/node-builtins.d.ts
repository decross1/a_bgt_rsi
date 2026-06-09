// Minimal ambient declarations for the handful of Node builtins the live-data
// validation tests use to read the real gitignored JSONL the backend serves
// (test_validate_iterations.tsx, test_validate_lowevidence.tsx). The project
// intentionally does not depend on @types/node (the app is a browser bundle);
// these tests run under vitest, which resolves `node:*` at runtime via esbuild.
// This shim exists only so `tsc --noEmit` type-checks those reads (and, by
// giving readFileSync a real `string` return, removes the cascade of implicit
// `any` on the downstream .split/.filter/.sort callbacks). Scope is deliberately
// just the symbols imported; not a substitute for @types/node.
declare module "node:fs" {
  export function readFileSync(path: string, encoding: "utf8"): string;
}
declare module "node:path" {
  export function dirname(path: string): string;
  export function resolve(...segments: string[]): string;
}
declare module "node:url" {
  export function fileURLToPath(url: string | URL): string;
}
