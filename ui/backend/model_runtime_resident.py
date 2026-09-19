"""Owner-selected permanent deployment, separate from old experiment receipts."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

ROOT = Path('/home/decross1/projects/a_bgt_rsi')


def project_permanent(root=ROOT):
    path = root / 'config/model_deployment.json'
    if not path.exists():
        return None
    try:
        raw = path.read_bytes()
        config = json.loads(raw)
        if (config.get('topology') != 'single_flash' or config.get('production_authorized') is not True
                or config.get('model') != 'nvidia/Qwen3.8-Flash-Next-NVFP4'
                or config.get('base_url') != 'http://127.0.0.1:30080/v1'):
            return None
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    try:
        state = json.loads((root / 'run_state/flash_resident.json').read_text())
        phase = state.get('phase', 'unknown')
        boot_matches = state.get('boot_id') == Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        fresh = 0 <= time.time() - float(state['heartbeat_epoch']) <= 45
        live = False
        if boot_matches and fresh:
            try:
                ticks = int(Path(f'/proc/{int(state["pid"])}/stat').read_text().rsplit(')', 1)[1].split()[19])
                live = ticks == state['process_start_ticks']
            except (OSError, KeyError, TypeError, ValueError):
                pass
        if phase in {'ready', 'starting', 'preparing'} and not live:
            phase = 'unverified'
        error = state.get('error')
        if not boot_matches:
            phase, error = 'awaiting_start', 'Waiting for the permanent resident service in this boot.'
    except (OSError, KeyError, ValueError, TypeError, AttributeError) as exc:
        phase, error, state = 'awaiting_start', f'Resident status unavailable: {type(exc).__name__}', {}
    return {
        'schema_version': 'model-runtime/v1',
        'observed_at': datetime.now(timezone.utc).isoformat(),
        'mode': 'resident' if phase == 'ready' else 'transitioning' if phase in {'starting', 'preparing'} else 'unknown',
        'mode_source': 'permanent_deployment',
        'mode_source_sha256': hashlib.sha256(raw).hexdigest(),
        'resident_services_expected': 'stopped',
        'nara_service_expected': 'running' if phase == 'ready' else 'paused',
        'run_id': 'flash-permanent-20260919',
        'phase': phase,
        'candidate_id': state.get('container_id'),
        'candidate_variant': None,
        'production_authorized': True,
        'source_error': error,
    }
