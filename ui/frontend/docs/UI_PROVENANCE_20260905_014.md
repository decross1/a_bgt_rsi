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

## Result and bounded claims

Channel reads now use a UI-owned JSON-envelope helper around the existing pure merged timeline function. Message bodies cannot create additional actor rows by containing formatted text. The endpoint validates envelope schema and row field types; malformed output is HTTP502. `framed` means message boundaries were preserved. Recorded labels are not authenticated, and the inherited timeline reader still may omit missing/malformed source lines; source completeness and newest-source truth are not established by framing.

Frontier status history is scanned from the beginning while retaining only rulings for visible proposal IDs. An older ruling therefore cannot disappear solely by aging beyond64KiB. Missing, malformed, unreadable or invalid status history makes current effective status unknown, while a valid last observed ruling remains visible as evidence. Source integrity includes complete/missing/truncated/errors. Retained memory and error details are bounded, but full status scanning is linear in source bytes and does not detect every concurrent source mutation.

Development requires the new integrity metadata before using actor-specific dates or current agenda counts. Legacy backend responses are uncertain. Proposals and observed rulings remain visible when current status is unknown. The page uses stable keys in the existing poll hub, guarded manual refresh and separate activity notifications. Source reads occur on mount/request, without periodic polling; StrictMode re-subscriptions reuse the in-flight request. Cache reset and backend policy were not changed.

Validation at the final source:55 focused frontend checks and the complete1309-test frontend suite passed with zero skips;117 applicable backend checks passed. Typecheck and production build passed with the existing bundle-size warning. An earlier full frontend run had1301 passes and1 failure at the same session-thread assertion that failed during LAB013. The final full run followed source changes from independent review, not an unrelated failure cleanup; the intermittent assertion is not claimed repaired. Original red tests, seven additional frontend review falsifiers, backend review negatives and the channel eager-import collection failure remain in private evidence. Human action/security assertions were preserved.

Independent frontend review identified authoritative truncation, raw-status fallback, legacy availability veto and pending-settlement remount gaps. The final frontend repair addresses all four; a bounded source confirmation matched the five exact reviewed hashes and found no remaining issue in that scope. This preparation does not replace HQ review of the whole exact public candidate.

Delivery is a new source candidate descended from the preserved LAB013 revision. No backend process adopted these changes, no source was copied to the live Vite checkout, and no service was restarted. A newer frontend with an older backend explicitly withholds these provenance claims. Fresh exact-commit independent review and resolution of applicable validation/adoption gates are required before merge; this task does not authorize automatic merge or a backend restart.
