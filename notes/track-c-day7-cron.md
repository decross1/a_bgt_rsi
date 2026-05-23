# Track C — Day 7: SLA + claims-GC cron wrappers

Two wrappers in `cron/` operationalize the SLA framework
(`agent/autonomy.md` §2) and the claim/lock GC sweep
(`agent/collision_protocol.md` §7):

- `cron/sla-sweep.sh` — every 15 min; runs `gate_sla_check.py` (soft-gate
  4h auto-clear, hard-gate 48h escalation) and `claims_check.py --gc`.
- `cron/claims-weekly.sh` — Sundays 04:00 UTC; appends the
  `claims_check.py --weekly-summary` figures to
  `notes/weekly-claims-<UTCdate>.md` for the weekly retrospective.

## Install playbook (human; copy-paste)

```bash
# 1. Confirm the scripts are present and executable in the main checkout
ls -l /home/decross1/projects/a_bgt_rsi/cron/sla-sweep.sh \
      /home/decross1/projects/a_bgt_rsi/cron/claims-weekly.sh

# 2. Smoke-test once from the shell before scheduling
/home/decross1/projects/a_bgt_rsi/cron/sla-sweep.sh
/home/decross1/projects/a_bgt_rsi/cron/claims-weekly.sh

# 3. Append to crontab (`crontab -e`):
*/15 * * * *  /home/decross1/projects/a_bgt_rsi/cron/sla-sweep.sh     >> /home/decross1/cron-sla-sweep.log 2>&1
0 4 * * 0     /home/decross1/projects/a_bgt_rsi/cron/claims-weekly.sh >> /home/decross1/cron-sla-sweep.log 2>&1
```

Both scripts share `/home/decross1/cron-sla-sweep.log` and use
`.venv-chroma` (pyyaml is required by `claims_check.py --validate-ownership`;
`.venv` doesn't have it).
