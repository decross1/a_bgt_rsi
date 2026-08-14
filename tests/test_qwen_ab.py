"""Tests for bench/critic_eval/qwen_ab.py — the Qwen 3.6 vs 3.8 A/B runner
skeleton (LOOP_V1 P5).

Hermetic: tmp_path weights roots, no docker, no network, no model calls.
The preflight refusal/pass paths exercise the REAL preflight_mem.sh via its
test-harness seam (PREFLIGHT_MEMINFO env — a file read, nothing else). The
live serve path is never executed by design: qwen_ab never serves; on a clean
preflight it prints the human-gated command and stops.
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from bench.critic_eval import qwen_ab


def _meminfo(tmp_path: Path, avail_kb: int) -> Path:
    p = tmp_path / "meminfo"
    p.write_text(f"MemTotal:       127000000 kB\nMemAvailable:   {avail_kb} kB\n")
    return p


def test_dry_run_prints_full_plan_and_exits_zero(tmp_path, capsys):
    rc = qwen_ab.main(["--dry-run", "--models-root", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    # Both models named, control/candidate framing present.
    assert "qwen3.6-27b-nvfp4-mtp" in out
    assert "qwen3.8-27b-nvfp4-mtp" in out
    assert "weights present: False" in out  # empty tmp root — honest, not coerced
    # All four battery stages appear.
    for stage in ("3a_skeptic_ladder", "3b_promotion_multivote",
                  "3c_twovoice_attacker", "3d_restate_hook"):
        assert stage in out
    # Serve commands carry the grounded production flags + pinned image.
    assert "vllm/vllm-openai:v0.21.0" in out
    assert "--quantization modelopt" in out
    assert "--gpu-memory-utilization 0.25" in out
    assert "qwen3_5_mtp" in out
    # Human gates stated.
    assert "HUMAN GATES" in out


def test_dry_run_reports_present_weights(tmp_path, capsys):
    (tmp_path / qwen_ab.MODEL_A).mkdir()
    qwen_ab.main(["--dry-run", "--models-root", str(tmp_path)])
    out = capsys.readouterr().out
    assert f"control  A: {qwen_ab.MODEL_A}  (weights present: True)" in out
    assert f"candidate B: {qwen_ab.MODEL_B}  (weights present: False)" in out


def test_live_refuses_without_candidate_weights(tmp_path, capsys):
    rc = qwen_ab.main(["--live", "--models-root", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "REFUSE live" in out
    assert "nothing served" in out


def test_live_refuses_when_preflight_fails(tmp_path, capsys, monkeypatch):
    (tmp_path / qwen_ab.MODEL_B).mkdir()
    # 10 GiB available << need(30) + margin(30): the real guard must refuse.
    monkeypatch.setenv(
        "PREFLIGHT_MEMINFO", str(_meminfo(tmp_path, 10 * 1024 * 1024)))
    rc = qwen_ab.main(["--live", "--models-root", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "REFUSE live: preflight_mem rc=1" in out
    assert "nothing served" in out


def test_live_preflight_pass_still_never_serves(tmp_path, capsys, monkeypatch):
    (tmp_path / qwen_ab.MODEL_B).mkdir()
    # 100 GiB available clears need+margin; runner must STILL stop at the
    # human gate — it prints the serve command, it does not run it.
    monkeypatch.setenv(
        "PREFLIGHT_MEMINFO", str(_meminfo(tmp_path, 100 * 1024 * 1024)))
    rc = qwen_ab.main(["--live", "--models-root", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "preflight PASS" in out
    assert "HUMAN GATE" in out
    assert "docker run" in out  # printed for the human, not executed


def test_live_fails_closed_when_preflight_script_missing(tmp_path, monkeypatch,
                                                         capsys):
    (tmp_path / qwen_ab.MODEL_B).mkdir()
    monkeypatch.setattr(qwen_ab, "PREFLIGHT_SH", tmp_path / "no_such.sh")
    rc = qwen_ab.main(["--live", "--models-root", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "rc=2" in out
    assert "fail-closed" in out


def test_mode_flag_is_required_and_exclusive(tmp_path):
    with pytest.raises(SystemExit) as ei:
        qwen_ab.main(["--models-root", str(tmp_path)])
    assert ei.value.code == 2
    with pytest.raises(SystemExit) as ei:
        qwen_ab.main(["--dry-run", "--live"])
    assert ei.value.code == 2
