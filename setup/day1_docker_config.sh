#!/usr/bin/env bash
# day1_block2_docker_config (corrected) — cache-clear cron + Docker host cgroupns.
#
# FIX vs plan.yaml: the plan command writes daemon.json key "cgroupns",
# which dockerd rejects ("directives don't match any configuration
# option: cgroupns"). The correct daemon-level key is
# "default-cgroupns-mode" (host|private) — the daemon default that the
# per-container `docker run --cgroupns host` flag overrides.
#
# Run as root:   sudo bash setup/day1_docker_config.sh
# Idempotent — safe to re-run.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: run as root — sudo bash setup/day1_docker_config.sh" >&2
  exit 1
fi

echo "=== 1. drop_caches cron (every 30 min) in root crontab ==="
CRON_LINE='*/30 * * * * sync && echo 3 | tee /proc/sys/vm/drop_caches > /dev/null'
{ crontab -l 2>/dev/null | grep -vF 'drop_caches' || true; echo "$CRON_LINE"; } | crontab -

echo "=== 2. default-cgroupns-mode:host in /etc/docker/daemon.json ==="
python3 - <<'PY'
import json, pathlib
p = pathlib.Path("/etc/docker/daemon.json")
txt = p.read_text() if p.exists() else ""
d = json.loads(txt) if txt.strip() else {}
d.pop("cgroupns", None)                 # drop the invalid key if present
d["default-cgroupns-mode"] = "host"
p.write_text(json.dumps(d, indent=2) + "\n")
print("daemon.json ->", json.dumps(d))
PY

echo "=== 3. restart docker ==="
systemctl reset-failed docker.service docker.socket 2>/dev/null || true
systemctl restart docker

echo "=== 4. verify ==="
sleep 2
docker info >/dev/null 2>&1 && echo "docker daemon: UP" || echo "docker daemon: STILL DOWN"
echo "--- docker info cgroup lines ---"
docker info 2>/dev/null | grep -i cgroup || echo "(no cgroup line)"
echo "--- root crontab ---"
crontab -l | grep drop_caches || echo "(no drop_caches line)"
echo "=== DONE ==="
