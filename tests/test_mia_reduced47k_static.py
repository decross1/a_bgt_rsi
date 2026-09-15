"""CPU-only source gate for a distinct, unbuilt reduced-MTP3 overlay."""
from __future__ import annotations

import ast
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1] / "bench/flash_next_ab/image_build"
STOCK = HERE / "source-audit/mtp.current-c0.py"
PATCH = HERE / "patch_mtp_draft_vocab.py"
IDS = Path("/mnt/models/qwen3.8-flash-next-mia-recipe-d0380900/"
           "files/draft_vocab_en_code_47k.txt")


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_exact_stock_patch_and_47149_ids_make_a_separate_image_source(tmp_path):
    assert _sha(STOCK) == "7735cee47d0d1e4776bebd30d907e4a62160409ce4ef2d65611559f8d58af431"
    assert _sha(PATCH) == "2c7d19b8021f2c439920ae7f7df6f7b008eb635256a8423ef03e168d3984911f"
    assert IDS.stat().st_size == 274_530
    assert _sha(IDS) == "20e36b6e8eae2598019298959a578ef8adc2948bbed7189e43a8da9b9d84a0b1"
    values = [int(line) for line in IDS.read_text().splitlines()]
    assert len(values) == len(set(values)) == 47_149
    assert all(0 <= value < 248_320 for value in values)
    shutil.copy2(STOCK, tmp_path / "mtp_patched.py.orig")
    shutil.copy2(PATCH, tmp_path / "patch_mtp_draft_vocab.py")
    subprocess.run([sys.executable, str(tmp_path / "patch_mtp_draft_vocab.py")],
                   cwd=tmp_path, check=True, capture_output=True, text=True)
    patched = (tmp_path / "mtp_patched.py").read_text()
    ast.parse(patched)
    assert "VLLM_MTP_DRAFT_VOCAB" in patched
    assert "def get_top_tokens" in patched
    dockerfile = (HERE / "Dockerfile.mia-reduced47k-draft").read_text()
    assert "FROM local/qfn-mia-base:da68dd27a8ef1dadd0f380178a51f0a0671dc4235933ea1ae89fdaf66295ec72" in dockerfile
    builder = (HERE / "build_reduced_overlay.py").read_text()
    assert 'BASE_ID = "sha256:da68dd27a8ef1dadd0f380178a51f0a0671dc4235933ea1ae89fdaf66295ec72"' in builder
    assert "7735cee47d0d1e4776bebd30d907e4a62160409ce4ef2d65611559f8d58af431" in dockerfile
    assert "2c7d19b8021f2c439920ae7f7df6f7b008eb635256a8423ef03e168d3984911f" in dockerfile
