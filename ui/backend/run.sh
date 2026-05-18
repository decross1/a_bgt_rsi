#!/usr/bin/env bash
# Backend launcher. See ui_plan.md section 5.2. Serves on :8700.
# Point at fixture logs:  UI_LOGS_DIR=/tmp/fixture_logs ui/backend/run.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."   # -> ui/
exec python3 -m uvicorn backend.app:app --host 0.0.0.0 --port 8700 "$@"
