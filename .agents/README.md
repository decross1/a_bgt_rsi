# `.agents/` — framework symlinks

This directory holds symlinks into the
[`agent_system`](https://github.com/decross1/agent_system) framework
that sits at `/home/decross1/projects/agent_system/`. Editing files
in `agent_system` propagates here automatically.

## Layout

- `skills/` — 24 skills from `agent_system/.agents/skills/`, one
  symlink per skill (each is a directory containing `SKILL.md`).
- `agents/` — 4 dev-agent profiles (`planner.md`, `builder.md`,
  `experimenter.md`, `auditor.md`).

## Install command (for reference)

```bash
cd /home/decross1/projects/agent_system
./install.sh --target-path /home/decross1/projects/a_bgt_rsi/.agents/skills --filter all
# agent profiles linked manually:
mkdir -p /home/decross1/projects/a_bgt_rsi/.agents/agents
ln -sf /home/decross1/projects/agent_system/.agents/agents/*.md \
       /home/decross1/projects/a_bgt_rsi/.agents/agents/
```

## BOUNDARY divergence

`agent_system/BOUNDARY.md` recommends installing only the
runtime-safe core (`resume-state`, `gate-check`, `validate`,
`run-log`, `fallback`) into a project's runtime. This project
intentionally installs all 24 skills + 4 agent profiles. Rationale
is recorded in `../DECISIONS.md` D-032.

The five runtime-safe core skills are exercised by Nara at runtime;
the others are available but not auto-loaded. We track the
divergence here so the next person who reads BOUNDARY.md isn't
surprised.

## Uninstall

```bash
# Remove this project's symlinks (not the framework itself):
rm -rf /home/decross1/projects/a_bgt_rsi/.agents/{skills,agents}
```

Or run `agent_system/install.sh --uninstall` from the framework root
(but note that ad-hoc `--target-path` installs are not tracked by
that command per `install.sh:249`).
