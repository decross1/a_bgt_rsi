// A dated delivery receipt, never a live GitHub or deployment status probe.
export const developmentReceipt = {
  recordedAt: "2026-09-05T22:51:41Z",
  head: "67df4af0a145d64990bdc5873b883565f89eacbd",
  implementation: "b9096ac9f809cd41791c02362f53155b0ca632c3",
  pr: "https://github.com/decross1/a_bgt_rsi/pull/3",
  title: "Overnight engineering: code published, integration held",
  changes: [
    "Claim and attempt identities; stale receipts cannot replace current evidence.",
    "Candidate checks require a real scoped diff, not an empty successful commit.",
    "Bounded Python execution with parent-recorded terminal evidence.",
    "Research inventory, historical fixture recovery and queue/archive tests.",
  ],
  checks: "296 integrity checks, 160 UI-independent fixture/renderer checks and 60 finite-profile checks passed in separate scoped runs. These are not a combined full-suite result.",
  next: "Qualify the full suite and real integrated smoke, then review the exact implementation range before merging or runtime adoption.",
  worker: "The separate Qwen worker remains held: 33 fixed examples passed, but invalid enum values and trailing-newline timestamps still violate its API.",
  audit: {
    recordedAt: "2026-09-05T03:02:05Z",
    iterations: 291,
    bound: 0,
    mismatch: 144,
    unverifiable: 147,
    exposure: "9e38f1640b9f6d4269bc90fd369b5a55b5a309ba13369054559e199adea34a3d",
  },
} as const;

// Separate from PR #3: this receipt concerns the UI delivered by PR #5.
// The observation is fixed in source; a later page load does not refresh it.
export const uiDeliveryReceipt = {
  recordedAt: "2026-09-06T21:43:39.147162+00:00",
  mergedAt: "2026-09-06T01:32:01Z",
  merge: "858cfb10656cc370e3fdf0018a6e45fd5d05e997",
  pr: "https://github.com/decross1/a_bgt_rsi/pull/5",
  title: "UI delivered: clearer provenance and stable thread history",
  changes: [
    "Development separates Codex delivery, Nara's channel and scientific evidence.",
    "Unverified ruling history stays view-only; unframed messages cannot become trusted actor rows.",
    "Model I/O retains loaded thread turns during polls and keeps different filters separate.",
  ],
  verification: "PR #5 received independent review; 1,338 frontend tests, 118 applicable backend tests, typecheck and build passed in its release checks. These are dated checks of that UI release, not the held core package.",
  observation: "The existing frontend served the merged UI source, and Development, Pulse and Model I/O rendered in a LAN browser check. No backend restart or imported-backend verification was performed.",
} as const;
