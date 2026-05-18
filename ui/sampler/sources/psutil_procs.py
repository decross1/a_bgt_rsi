"""Host aggregate + per-process telemetry via psutil. See ui_plan.md section 5.1.

cpu_percent(interval=None) returns 0.0 on the first call for a given target,
so host and per-PID readings are primed: the host gauge once at startup, and
each process the first cycle it is seen (workers appear mid-run). Process
objects are cached across cycles -- psutil tracks cpu_percent state per object.
"""
import re
import shutil
import subprocess

import psutil

_ORCH_RE = re.compile(r"python.*orchestrator", re.IGNORECASE)
_WORKER_RE = re.compile(r"python.*worker", re.IGNORECASE)
_CHROMA_RE = re.compile(r"chroma\s+run", re.IGNORECASE)


def prime_host():
    """Seed the process-wide cpu_percent gauge (first call returns 0.0)."""
    psutil.cpu_percent(interval=None)


def read_host_aggregate():
    """Return (host_dict_without_cpu_temp, None) or (None, error_str).

    The caller fills in cpu_temp_c from the thermal source.
    """
    try:
        cpu = psutil.cpu_percent(interval=None)
        vmem = psutil.virtual_memory()
        try:
            load = psutil.getloadavg()
        except (AttributeError, OSError):
            load = (0.0, 0.0, 0.0)
        return {
            "cpu_pct": cpu,
            "mem_used_mb": round(vmem.used / (1024 * 1024), 1),
            "load_avg": [round(x, 2) for x in load],
        }, None
    except psutil.Error as exc:
        return None, f"psutil host read failed: {exc}"


def _vllm_container_pid(name):
    """Main PID of the vLLM container, or None. Re-read to catch restarts."""
    if shutil.which("docker") is None:
        return None
    try:
        proc = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Pid}}", name],
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    if proc.returncode != 0:
        return None
    try:
        pid = int(proc.stdout.strip())
    except ValueError:
        return None
    return pid if pid > 0 else None


class ProcessSampler:
    """Discovers and samples the tracked PID set once per interval."""

    def __init__(self, vllm_container="vllm-gemma4", rediscover_every=10):
        self.vllm_container = vllm_container
        self.rediscover_every = rediscover_every
        self._procs = {}        # pid -> psutil.Process (cached for cpu_percent)
        self._cycle = 0
        self._vllm_pid = None

    def _discover(self):
        """Return {pid: label} for the current tracked set."""
        found = {}
        # vLLM container PID changes on restart; re-inspect periodically.
        if self._vllm_pid is None or self._cycle % self.rediscover_every == 0:
            self._vllm_pid = _vllm_container_pid(self.vllm_container)
        if self._vllm_pid is not None and psutil.pid_exists(self._vllm_pid):
            found[self._vllm_pid] = "vllm-gemma4"

        for proc in psutil.process_iter(["pid", "cmdline"]):
            try:
                cmd = " ".join(proc.info["cmdline"] or [])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            if not cmd:
                continue
            pid = proc.info["pid"]
            if _ORCH_RE.search(cmd):
                found.setdefault(pid, "orchestrator")
            elif _WORKER_RE.search(cmd):
                found.setdefault(pid, f"worker-{pid}")
            elif _CHROMA_RE.search(cmd):
                found.setdefault(pid, "chromadb")
        return found

    def sample(self):
        """Return (processes_list, error_str_or_None), sorted by RSS desc."""
        self._cycle += 1
        try:
            found = self._discover()
        except psutil.Error as exc:
            return [], f"psutil discovery failed: {exc}"

        for pid in list(self._procs):
            if pid not in found:
                self._procs.pop(pid, None)

        rows = []
        for pid, label in found.items():
            proc = self._procs.get(pid)
            is_new = proc is None
            if is_new:
                try:
                    proc = psutil.Process(pid)
                    proc.cpu_percent(interval=None)   # prime; first call is 0.0
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                self._procs[pid] = proc
            try:
                with proc.oneshot():
                    # A freshly-primed process has no real reading yet.
                    cpu = 0.0 if is_new else proc.cpu_percent(interval=None)
                    rss = proc.memory_info().rss / (1024 * 1024)
                    threads = proc.num_threads()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                self._procs.pop(pid, None)
                continue
            rows.append({
                "pid": pid,
                "name": label,
                "cpu_pct": round(cpu, 1),
                "rss_mb": round(rss, 1),
                "threads": threads,
            })

        rows.sort(key=lambda r: r["rss_mb"], reverse=True)
        return rows, None
