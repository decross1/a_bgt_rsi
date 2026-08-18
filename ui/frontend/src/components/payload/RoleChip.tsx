// RoleChip — the small colored role chip for message cards (density pass,
// owner feedback 2026-08-18). Roles are producer-owned strings: own-key
// lookup only (the SourceBadge prototype-collision guard), unknown roles
// quiet zinc, non-strings degrade to "?" — never a throw.
const ROLE_CHIP_TONE: Record<string, string> = {
  system: "bg-zinc-800 text-zinc-300",
  user: "bg-sky-950 text-sky-300",
  assistant: "bg-emerald-950 text-emerald-300",
  tool: "bg-amber-950 text-amber-300",
  completion: "bg-fuchsia-950 text-fuchsia-300",
};

export default function RoleChip({ role }: { role: unknown }) {
  const key = typeof role === "string" && role !== "" ? role : "?";
  const tone = Object.prototype.hasOwnProperty.call(ROLE_CHIP_TONE, key)
    ? ROLE_CHIP_TONE[key]
    : "bg-zinc-800 text-zinc-400";
  return (
    <span
      data-testid="role-chip"
      className={`rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${tone}`}
    >
      {key}
    </span>
  );
}
