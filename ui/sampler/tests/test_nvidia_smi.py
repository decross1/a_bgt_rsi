"""read_gpu(): GB10 unified-memory [N/A] must NOT raise a read_error (it would
otherwise read as a permanent DEGRADED on the dashboard), while a genuinely
missing field still does."""
from types import SimpleNamespace

from sampler.sources import nvidia_smi


def _stub(monkeypatch, stdout: str):
    monkeypatch.setattr(nvidia_smi.shutil, "which", lambda _: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(
        nvidia_smi.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=stdout, stderr=""),
    )


def test_gb10_unified_memory_is_not_a_read_error(monkeypatch):
    # GB10: memory.used/total report [N/A]; util/temp/power read fine.
    _stub(monkeypatch, "0, [N/A], [N/A], 40, 11.7\n")
    gpu, error = nvidia_smi.read_gpu()
    assert gpu["mem_used_mb"] is None
    assert gpu["mem_total_mb"] is None
    assert gpu["util_pct"] == 0.0
    assert gpu["temp_c"] == 40.0
    assert gpu["power_w"] == 11.7
    # The fix: expected unified-memory nulls do NOT raise an error.
    assert error is None


def test_genuinely_missing_field_is_still_a_read_error(monkeypatch):
    # util_pct should always be present; [N/A] there IS a real read error.
    _stub(monkeypatch, "[N/A], 100, 1000, 40, 11.7\n")
    gpu, error = nvidia_smi.read_gpu()
    assert gpu["util_pct"] is None
    assert error is not None
    assert "util_pct" in error
    # ...and the expected memory fields are NOT named in the error.
    assert "mem_used_mb" not in error
