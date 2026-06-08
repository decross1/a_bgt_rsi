"""exp008_qat_eval — config-load/validate + serve_qat.sh safety test.

Offline (MOCK_LLM default). No model call: the only subprocess is
serve_qat.sh --dry-run, which prints args and executes nothing.
"""
import subprocess
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "experiments" / "exp008_qat_eval"
CONFIG = EXP / "config.yaml"
SERVE = EXP / "serve_qat.sh"


def _load():
    with CONFIG.open() as fh:
        return yaml.safe_load(fh)


def test_config_loads_and_has_required_top_level_keys():
    cfg = _load()
    for key in ("experiment_id", "arms", "sampling", "fixtures",
                "metrics", "materiality", "logging"):
        assert key in cfg, f"missing top-level key: {key}"
    assert cfg["experiment_id"] == "exp008_qat_eval"


def test_three_arms_with_required_shape():
    cfg = _load()
    arms = {a["id"]: a for a in cfg["arms"]}
    assert {"A", "B", "C"} <= set(arms), "expected arms A, B, C"
    # A is the read-only production control on vLLM.
    assert arms["A"]["read_only"] is True
    assert arms["A"]["engine"] == "vllm"
    assert ":8000" in arms["A"]["endpoint"]
    # B is the llama.cpp GGUF candidate on scratch :8002.
    assert arms["B"]["engine"] == "llama.cpp"
    assert ":8002" in arms["B"]["endpoint"]
    # C is the optional vLLM unquantized-QAT candidate on scratch :8002.
    assert arms["C"].get("optional") is True
    assert arms["C"]["engine"] == "vllm"
    assert ":8002" in arms["C"]["endpoint"]
    # every arm has checkpoint repo + revision + content-hash placeholders.
    for aid, arm in arms.items():
        ck = arm["checkpoint"]
        for f in ("repo", "revision", "content_hash"):
            assert f in ck, f"arm {aid} checkpoint missing {f}"


def test_sampling_is_greedy_one_at_a_time():
    cfg = _load()
    s = cfg["sampling"]
    assert s["temperature"] == 0, "quality runs must be greedy (temp 0)"
    assert s["concurrency"] == 1, "must be one request at a time"


def test_fixtures_point_at_novelty_calibration_glob():
    cfg = _load()
    assert cfg["fixtures"]["glob"] == \
        "experiments/fixtures/novelty_calibration/*.json"
    # glob actually resolves against the repo.
    matches = list(REPO.glob(cfg["fixtures"]["glob"]))
    assert matches, "novelty_calibration glob matched no fixtures"


def test_metrics_and_materiality_keys_present():
    cfg = _load()
    assert "primary" in cfg["metrics"]
    mat = cfg["materiality"]
    # a pre-registered threshold must exist and the small-N caveat must be noted.
    assert "margin_over_noise_floor" in mat
    assert "fallback_absolute_disagreement_threshold" in mat
    assert "small_n_caveat" in mat
    assert "directional" in mat["small_n_caveat"].lower()


def test_logging_isolated_from_production():
    cfg = _load()
    log = cfg["logging"]
    assert log["run_dir"] == "experiments/exp008_qat_eval/runs"
    # production log is named only to forbid it.
    assert log["production_log_forbidden"] == "logs/calls.jsonl"


def _dry_run(*args):
    return subprocess.run(
        ["bash", str(SERVE), *args],
        capture_output=True, text=True, cwd=str(REPO), timeout=30,
    )


def test_serve_dry_run_prints_8002_and_never_8000():
    for arm in ("B", "C"):
        res = _dry_run("up", arm, "--dry-run")
        assert res.returncode == 0, f"arm {arm} dry-run failed: {res.stderr}"
        out = res.stdout
        assert ":8002" in out or "8002:8002" in out, \
            f"arm {arm} dry-run did not print scratch :8002 args"
        assert ":8000" not in out, \
            f"arm {arm} dry-run referenced production :8000"


def test_serve_script_source_never_references_production_8000():
    src = SERVE.read_text()
    assert "8000" not in src, "serve_qat.sh must never reference :8000"
    assert "8002" in src, "serve_qat.sh must bind scratch :8002"


def test_serve_down_dry_run():
    res = _dry_run("down", "--dry-run")
    assert res.returncode == 0
    assert "qat-eval-scratch" in res.stdout
    assert "8000" not in res.stdout
