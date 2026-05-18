#!/usr/bin/env bash
# Telemetry sampler launcher. See ui_plan.md section 5.1.
# Restart-on-failure is the caller's job (systemd / supervisor / while-loop).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."   # -> ui/
exec python3 -m sampler.sampler "$@"
