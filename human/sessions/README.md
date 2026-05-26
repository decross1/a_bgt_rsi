# `human/sessions/` — per-session working notes

One file per working day: `YYYY-MM-DD.md`. Each file is the day's
plan **and** end-of-session retrospective. The current session note
is the live source of truth for what's being worked on; the primary
Claude Code session reads it after `CLAUDE.md` and `LOOP_V0.md`.

## Suggested structure

```markdown
# Session — YYYY-MM-DD

## Focus
One or two sentences: what we're building or deciding today.

## Plan
- bullet of concrete intent
- another bullet
- (optionally) parallel UI session: yes/no, what it'll work on

## Outcomes (filled in at end of session)
- what was actually done
- what works / what's broken
- decisions made (cross-link to DECISIONS.md if durable)

## Next session
- proposed focus
- open questions for the human
```

Sessions are written **with** the human at the start, not generated
unilaterally by the agent. The end-of-session update happens before
the agent stops.
