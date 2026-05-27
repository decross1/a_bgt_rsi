"""Telemetry sampler daemon. See ui_plan.md section 5.1.

Composes one JSON object per interval from four sources (GPU, host, vLLM,
processes) and appends it to ui/logs/telemetry.jsonl. Read-only with
respect to the apparatus: it observes nvidia-smi, the vLLM /metrics
endpoint, psutil, and thermal zones, and never writes outside ui/.

A second optional vLLM endpoint (Qwen3.6-27B NVFP4-MTP on :8001 by
default) is sampled in parallel to the primary Gemma endpoint. The new
field is `vllm_qwen` — same shape as `vllm`. When the URL is empty/unset
or the endpoint is unreachable, `vllm_qwen` is written as null
(graceful degradation; the existing `vllm` behavior is unchanged).

Run:  cd ui && python3 -m sampler.sampler
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .sources import nvidia_smi, psutil_procs, thermal, vllm_metrics

_UI_DIR = Path(__file__).resolve().parents[1]            # .../ui
DEFAULT_OUTPUT = _UI_DIR / "logs" / "telemetry.jsonl"
DEFAULT_SCHEMA = _UI_DIR / "schema" / "telemetry.jsonl.schema.json"
DEFAULT_VLLM_URL = "http://localhost:8000/metrics"
# Qwen endpoint default; overridable via --vllm-qwen-url or env
# VLLM_QWEN_METRICS_URL. Empty string disables the second reader entirely
# (sample lines still carry vllm_qwen: null so the key set is stable).
DEFAULT_VLLM_QWEN_URL = "http://localhost:8001/metrics"


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Sampler:
    """One sampler instance: holds the stateful source readers."""

    def __init__(self, output_path=DEFAULT_OUTPUT, vllm_url=DEFAULT_VLLM_URL,
                 interval=1.0, vllm_qwen_url=DEFAULT_VLLM_QWEN_URL):
        self.output_path = Path(output_path)
        self.interval = interval
        self.vllm = vllm_metrics.VllmMetricsReader(vllm_url)
        # Second reader for the Qwen endpoint. An empty/None URL disables
        # the reader entirely — sample() then writes vllm_qwen: null
        # without attempting an HTTP call (no error noise on hosts that
        # don't run vllm-qwen).
        self.vllm_qwen = (
            vllm_metrics.VllmMetricsReader(vllm_qwen_url) if vllm_qwen_url else None
        )
        self.procs = psutil_procs.ProcessSampler()
        self._primed = False

    def prime(self):
        """Seed readings whose first call is meaningless (cpu_percent, rates)."""
        psutil_procs.prime_host()
        self.procs.sample()      # primes per-PID cpu_percent
        self.vllm.read()         # primes counter rates
        if self.vllm_qwen is not None:
            self.vllm_qwen.read()
        self._primed = True

    def sample(self):
        """Gather one telemetry record. Never raises -- failures land in read_errors."""
        if not self._primed:
            self.prime()
        errors = {}

        gpu, err = nvidia_smi.read_gpu()
        if err:
            errors["nvidia-smi"] = err

        host, err = psutil_procs.read_host_aggregate()
        if err:
            errors["psutil"] = err

        cpu_temp, err = thermal.read_cpu_temp()
        if err:
            errors["thermal"] = err
        if host is not None:
            host["cpu_temp_c"] = cpu_temp

        vllm, err = self.vllm.read()
        if err:
            errors["vllm-metrics"] = err

        # Qwen endpoint: graceful degradation. Disabled reader => null
        # without an error key (expected state on Gemma-only hosts).
        # Reader present but failing => null + a distinct error key so the
        # primary Gemma read isn't conflated with the Qwen read.
        if self.vllm_qwen is None:
            vllm_qwen = None
        else:
            vllm_qwen, err = self.vllm_qwen.read()
            if err:
                errors["vllm-qwen-metrics"] = err

        processes, err = self.procs.sample()
        if err:
            errors["psutil"] = err

        return {
            "timestamp": _now_iso(),
            "gpu": gpu,
            "host": host,
            "vllm": vllm,
            "vllm_qwen": vllm_qwen,
            "processes": processes,
            "read_errors": errors or None,
        }

    def run(self, stop_event=None, max_samples=None):
        """Sample on a fixed interval until stop_event is set or max_samples hit.

        Returns the number of samples written.
        """
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.prime()
        count = 0
        with open(self.output_path, "a", encoding="utf-8") as fh:
            while not (stop_event is not None and stop_event.is_set()):
                start = time.monotonic()
                try:
                    record = self.sample()
                except Exception as exc:  # belt-and-suspenders: keep the daemon up
                    record = {
                        "timestamp": _now_iso(),
                        "gpu": None, "host": None, "vllm": None,
                        "vllm_qwen": None,
                        "processes": [],
                        "read_errors": {"sampler": f"unhandled: {exc!r}"},
                    }
                fh.write(json.dumps(record) + "\n")
                fh.flush()
                count += 1
                if max_samples is not None and count >= max_samples:
                    break
                sleep_for = self.interval - (time.monotonic() - start)
                if sleep_for > 0:
                    if stop_event is not None:
                        stop_event.wait(sleep_for)
                    else:
                        time.sleep(sleep_for)
        return count


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Telemetry sampler for the orchestrator dashboard "
                    "(ui_plan.md section 5.1).")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help=f"output JSONL path (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--vllm-url", default=DEFAULT_VLLM_URL,
                        help="vLLM Prometheus /metrics URL")
    # Env var wins over the built-in default; explicit --vllm-qwen-url
    # wins over both (argparse default fills only when both env and flag
    # are absent). Empty string disables the Qwen reader entirely.
    parser.add_argument(
        "--vllm-qwen-url",
        default=os.environ.get("VLLM_QWEN_METRICS_URL", DEFAULT_VLLM_QWEN_URL),
        help=(
            "vLLM (Qwen) Prometheus /metrics URL. Empty string disables "
            "the second reader; sample lines still carry vllm_qwen: null."
        ),
    )
    parser.add_argument("--interval", type=float, default=1.0,
                        help="sample interval in seconds (default: 1.0)")
    parser.add_argument("--max-samples", type=int, default=None,
                        help="stop after N samples (default: run forever)")
    args = parser.parse_args(argv)

    sampler = Sampler(
        args.output, args.vllm_url, args.interval,
        vllm_qwen_url=args.vllm_qwen_url,
    )
    qwen_note = args.vllm_qwen_url or "(disabled)"
    print(f"sampler: writing {args.output} every {args.interval}s "
          f"(vLLM {args.vllm_url}; vLLM-Qwen {qwen_note})", file=sys.stderr)
    try:
        written = sampler.run(max_samples=args.max_samples)
    except KeyboardInterrupt:
        print("\nsampler: stopped", file=sys.stderr)
        return 0
    print(f"sampler: wrote {written} samples", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
