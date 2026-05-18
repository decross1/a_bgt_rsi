#!/usr/bin/env bash
# Filesystem cache drop. Installed in root's crontab (every 30 min) by
# setup/day1_docker_config.sh — prevents the documented decode slowdown
# to ~16 tok/s when the page cache fills the unified memory.
#
# Crontab line (root):
#   */30 * * * * sync && echo 3 | tee /proc/sys/vm/drop_caches > /dev/null
sync && echo 3 | tee /proc/sys/vm/drop_caches > /dev/null
