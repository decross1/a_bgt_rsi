import subprocess
import sys

import pytest

from orchestrator.weekly_upgrade_trial import (
    TRIAL_MODULES,
    TRIALS,
    live_trial_processes,
)


@pytest.mark.parametrize("module", sorted(set(TRIAL_MODULES.values())))
def test_discover_every_registered_trial_module_with_exact_output(tmp_path, module):
    # A harmless sleeper carries controlled argv tokens. No model module runs.
    process = subprocess.Popen([
        sys.executable, "-c", "import time; time.sleep(30)", module,
        "--output-dir", str(tmp_path / "evaluation"),
    ], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        assert process.pid in live_trial_processes(tmp_path)
        assert process.pid not in live_trial_processes(tmp_path / "different")
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_every_registered_kind_has_one_shared_command_and_recovery_mapping():
    assert {kind for kind, _ in TRIALS.values()} == set(TRIAL_MODULES)
