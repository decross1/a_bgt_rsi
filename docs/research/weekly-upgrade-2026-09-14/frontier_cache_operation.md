# Frontier veto-cache operation

**Status:** implemented but inactive by default. Merging this code does not
enable the frontier screen or its cache.

This cache suppresses chronological repeats of an identical, completed
frontier **veto**. It does not cache passes, inconclusive reviews, malformed
responses, provider outages, write failures, or unconfirmed cross-provider
disagreements. It is not a concurrent singleflight mechanism: two simultaneous
misses may both call the reviewers.

## Activation

The existing frontier screen must be enabled separately. Cache reuse requires
all of these environment values:

```text
NARA_FRONTIER_SCREEN=1
NARA_FRONTIER_SCREEN_CACHE=1
FRONTIER_CLAUDE_CACHE_EPOCH=<reviewed epoch label>
FRONTIER_CODEX_CACHE_EPOCH=<reviewed epoch label>
```

`FRONTIER_*_CACHE_EPOCH` values are operator attestations defining a reviewed
cache period. They are **not observed or enforced immutable server-model
revisions**: the current subscription transports expose mutable Claude/Codex
model aliases. Reuse is conservatively bypassed if either epoch is absent.

The default TTL is 86,400 seconds (24 hours). An optional
`NARA_FRONTIER_SCREEN_CACHE_TTL_S` may shorten it or extend it to at most
604,800 seconds (7 days). Invalid, nonpositive, or over-limit values bypass the
cache and run a fresh screen.

Rotate both epoch labels, or disable caching, whenever the effective provider
model may have changed. Also rotate them after a model, reasoning, routing,
prompt, or review-policy change. Local prompt/reviewer code, transport source,
requested provider/model settings, resolved executable content/package
revision, candidate evidence, and TTL are independently key-bound and
invalidate old entries automatically. The epoch remains necessary because
those local bindings cannot detect a provider changing the model behind an
alias.

## Observation and failure behavior

`promote_findings()` reports `frontier_cache_hits`. Each screened result also
carries a `cache` object with its hit/store status and cache-key digest.

Cache reads, validation, and atomic writes use
`run_state/frontier_screen_cache/`, which is gitignored. A missing, corrupt,
expired, oversized, misrouted, or unwritable record produces a fresh frontier
screen. It never manufactures a veto and never converts an existing result.
Entries are capped at 64 KiB, 1,024 files, and seven days.

## Disable / rollback

Unset `NARA_FRONTIER_SCREEN_CACHE` (or set it to anything other than exact
`1`) to restore fresh frontier calls without changing the existing frontier
screen. Unsetting either provider epoch also forces fresh calls. Cached files
may remain on disk; they are unreachable while the flag is disabled, and any
later reuse must satisfy all current bindings and TTL checks.

Hermetic regression coverage is in `tests/test_frontier_screen_cache.py`.
