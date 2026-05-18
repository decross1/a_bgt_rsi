"""GPU telemetry via `nvidia-smi`. See ui_plan.md section 5.1.

The Spark has a single GB10 GPU, so exactly one CSV line is expected; if
more ever appear we sample index 0.

GB10 uses unified memory, so `nvidia-smi` reports `[N/A]` for
memory.used / memory.total. Fields are parsed independently: an
unreadable field becomes null in the gpu object (the dashboard shows it
as n/a) while the readable fields -- util, temp, power -- are kept. The
return is (gpu_dict, error): both can be non-None when the object is
partial. (None, error) only when nvidia-smi wholly fails.
"""
import shutil
import subprocess

_QUERY = "utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw"
_FIELDS = ["util_pct", "mem_used_mb", "mem_total_mb", "temp_c", "power_w"]


def read_gpu():
    """Return (gpu_dict_or_None, error_str_or_None).

    A partial object (some fields null, e.g. GB10 unified memory) is
    returned together with an error string naming the missing fields.
    """
    if shutil.which("nvidia-smi") is None:
        return None, "nvidia-smi not on PATH"
    try:
        proc = subprocess.run(
            ["nvidia-smi", f"--query-gpu={_QUERY}",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return None, f"nvidia-smi exec failed: {exc}"
    if proc.returncode != 0:
        return None, f"nvidia-smi exit {proc.returncode}: {proc.stderr.strip()}"

    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    if not lines:
        return None, "nvidia-smi produced no output"
    fields = [f.strip() for f in lines[0].split(",")]
    if len(fields) != 5:
        return None, f"unexpected nvidia-smi field count: {fields}"

    gpu = {}
    unavailable = []
    for key, raw in zip(_FIELDS, fields):
        try:
            gpu[key] = float(raw)
        except ValueError:
            # e.g. "[N/A]" for memory on GB10 unified memory.
            gpu[key] = None
            unavailable.append(key)

    if len(unavailable) == len(_FIELDS):
        return None, f"nvidia-smi: all fields unreadable ({fields})"
    error = (f"nvidia-smi fields unavailable: {', '.join(unavailable)}"
             if unavailable else None)
    return gpu, error
