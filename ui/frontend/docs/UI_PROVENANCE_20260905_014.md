# LAB014 provenance repairs

LAB013 production closed after exact HOLD; prior tests do not establish framing, complete status history or StrictMode deduplication. Fresh source-only candidate based on e7f08ce/public d1c4.

Fix three findings with red regressions first and at most two production iterations per finding. Channel read transport must preserve structured row boundaries and qualify actor labels as recorded, not authenticated. A pure UI-owned structured-output helper is allowed only where required to avoid formatted-text parsing; no model/action invocation change. Frontier reads must preserve older human rulings and expose incomplete/malformed/missing sources, never trust legacy integrity-free status. Development uses the established poll hub, with actual StrictMode, manual refresh, failed/stale/missing fixtures.

Exact allowed paths:
- ui/backend/lab_channel_seam.py
- ui/backend/channel_timeline_reader.py
- ui/backend/tests/test_lab_channel_seam.py
- ui/backend/frontier_reviews.py
- ui/backend/tests/test_frontier_reviews.py
- ui/frontend/src/routes/Development.tsx
- ui/frontend/src/api/development.ts
- ui/frontend/src/api/pollhub.ts
- ui/frontend/tests/test_development.tsx
- ui/frontend/tests/test_pollhub.tsx
- ui/frontend/docs/UI_PROVENANCE_20260905_014.md

Accepted 2026-09-05T23:58:37+00:00; code target 2026-09-06T00:23:37+00:00; terminal 2026-09-06T00:33:37+00:00. No models, research, raw-ledger edits, authority changes, cache reset, service/rebind/new service. Commit/push exact candidate for fresh independent review; no merge or backend adoption claim. Private fixtures remain excluded. Parent owns commits and reconciles disjoint backend lanes.
