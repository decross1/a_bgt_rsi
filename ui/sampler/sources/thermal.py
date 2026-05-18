"""Host CPU temperature via /sys/class/thermal. See ui_plan.md section 5.1.

Reports the mean of all thermal zones (millidegrees -> Celsius). Returns
(None, error) when no zone is readable so the sampler can record
read_errors["thermal"] and write host.cpu_temp_c: null.
"""
import glob

_ZONE_GLOB = "/sys/class/thermal/thermal_zone*/temp"


def read_cpu_temp():
    """Return (mean_celsius, None) or (None, error_str)."""
    paths = sorted(glob.glob(_ZONE_GLOB))
    if not paths:
        return None, "no thermal zones found"

    temps = []
    errors = []
    for path in paths:
        try:
            with open(path, encoding="utf-8") as fh:
                temps.append(int(fh.read().strip()) / 1000.0)
        except (OSError, ValueError) as exc:
            errors.append(f"{path}: {exc}")

    if not temps:
        return None, "; ".join(errors) or "all thermal zone reads failed"
    return sum(temps) / len(temps), None
