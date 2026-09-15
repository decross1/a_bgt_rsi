"""CPU-only, network-disabled immutable Mia reduced47K overlay builder.

Source only during the first paired GPU benchmark. Execute only after its
complete restoration, never with a resident/candidate service mutation.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import uuid
from pathlib import Path

HERE = Path(__file__).parent
BASE_ID = "sha256:da68dd27a8ef1dadd0f380178a51f0a0671dc4235933ea1ae89fdaf66295ec72"
STOCK_SHA = "7735cee47d0d1e4776bebd30d907e4a62160409ce4ef2d65611559f8d58af431"
PATCH_SHA = "2c7d19b8021f2c439920ae7f7df6f7b008eb635256a8423ef03e168d3984911f"
VOCAB_SHA = "20e36b6e8eae2598019298959a578ef8adc2948bbed7189e43a8da9b9d84a0b1"
VOCAB_FILE = Path("/mnt/models/qwen3.8-flash-next-mia-recipe-d0380900/"
                  "files/draft_vocab_en_code_47k.txt")
RECEIPT_DIR = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/"
    "qwen-flash-next-research/runtime/mia-reduced47k-image-build"
)
TAG = "local/qfn-mia-mtp3-reduced47k:source-v1"
BASE_TAG = "local/qfn-mia-base:" + BASE_ID.split(":", 1)[1]
MTP_PKG = (
    "/usr/local/lib/python3.12/dist-packages/vllm/models/"
    "qwen3_8_flash_next/nvidia/mtp.py"
)


def _run(argv: list[str], *, output: Path | None = None) -> str:
    if output is None:
        result = subprocess.run(argv, check=True, capture_output=True, text=True)
        return result.stdout.strip()
    with output.open("xb") as stream:
        result = subprocess.run(argv, check=True, stdout=stream,
                                stderr=subprocess.STDOUT)
    return str(result.returncode)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _inspect(image: str) -> dict:
    observed = json.loads(_run(["docker", "image", "inspect", image]))
    if not isinstance(observed, list) or len(observed) != 1:
        raise ValueError("Docker image inspection was not unique")
    return observed[0]


def build() -> dict:
    if not RECEIPT_DIR.parent.is_dir() or RECEIPT_DIR.is_symlink() or RECEIPT_DIR.exists():
        raise ValueError("immutable reduced image receipt output already exists")
    source = HERE / "source-audit/mtp.current-c0.py"
    patch = HERE / "patch_mtp_draft_vocab.py"
    dockerfile = HERE / "Dockerfile.mia-reduced47k-draft"
    if (_sha(source.read_bytes()) != STOCK_SHA
        or _sha(patch.read_bytes()) != PATCH_SHA
        or VOCAB_FILE.stat().st_size != 274_530
        or _sha(VOCAB_FILE.read_bytes()) != VOCAB_SHA):
        raise ValueError("reduced image stock/patch/vocabulary source drifted")
    ids = [int(line) for line in VOCAB_FILE.read_text().splitlines()]
    if (len(ids) != 47_149 or len(set(ids)) != 47_149
        or not all(0 <= id_ < 248_320 for id_ in ids)):
        raise ValueError("47K draft-vocabulary token IDs differ")
    parent = _inspect(BASE_ID)
    if parent.get("Id") != BASE_ID or parent.get("Architecture") != "arm64":
        raise ValueError("pinned Mia parent image/architecture differs")
    existing = subprocess.run(["docker", "image", "inspect", BASE_TAG], capture_output=True)
    if existing.returncode == 0:
        if _inspect(BASE_TAG).get("Id") != BASE_ID:
            raise ValueError("digest-named local base tag already binds another image")
    else:
        _run(["docker", "image", "tag", BASE_ID, BASE_TAG])
    if _inspect(BASE_TAG).get("Id") != BASE_ID:
        raise ValueError("local base tag does not bind exact parent")
    if subprocess.run(["docker", "image", "inspect", TAG], capture_output=True).returncode == 0:
        raise ValueError("child tag already exists; refusing to replace it")
    attempt = RECEIPT_DIR.with_name(
        f".mia-reduced47k-build-attempt-{uuid.uuid4().hex}"
    )
    attempt.mkdir(mode=0o700)
    _run([
        "docker", "build", "--network=none", "--pull=false",
        "--platform=linux/arm64", "-f", str(dockerfile),
        "-t", TAG, str(HERE),
    ], output=attempt / "build.log")
    child = _inspect(TAG)
    image_id = child.get("Id")
    if (not isinstance(image_id, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id)
        or image_id == BASE_ID or child.get("Architecture") != "arm64"):
        raise ValueError("reduced image ID or architecture differs")
    parent_layers = parent["RootFS"]["Layers"]
    if child["RootFS"]["Layers"][:len(parent_layers)] != parent_layers:
        raise ValueError("child filesystem does not preserve the exact parent layers")
    if _inspect(BASE_TAG).get("Id") != BASE_ID:
        raise ValueError("local base tag drifted during build")
    child_sha = _run([
        "docker", "run", "--rm", "--network=none", "--entrypoint=python3",
        image_id, "-c", "import hashlib;print(hashlib.sha256(open('"
        + MTP_PKG + "','rb').read()).hexdigest())",
    ])
    if not re.fullmatch(r"[0-9a-f]{64}", child_sha) or child_sha == STOCK_SHA:
        raise ValueError("reduced MTP module did not acquire a distinct patch SHA")
    receipt = {
        "schema": "mia-reduced-mtp3-overlay-build/v1",
        "status": "cpu_source_verified_unqualified",
        "image_id": image_id, "image_architecture": "arm64",
        "parent_image_id": BASE_ID,
        "verified_base_tag": BASE_TAG,
        "parent_layers": parent_layers,
        "builder_sha256": _sha(Path(__file__).read_bytes()),
        "recipe_commit": "d03809008834124e80223c3482f2ddb59577a48f",
        "base_mtp_sha256": STOCK_SHA,
        "mtp_patch_sha256": PATCH_SHA,
        "child_mtp_sha256": child_sha,
        "dockerfile_sha256": _sha(dockerfile.read_bytes()),
        "draft_vocab": {"path": str(VOCAB_FILE), "bytes": 274_530,
                        "sha256": VOCAB_SHA, "id_count": 47_149},
        "build_log_sha256": _sha((attempt / "build.log").read_bytes()),
        "old_mia_c0_image_replaced": False,
        "gpu_runtime_qualified": False,
    }
    raw = json.dumps(receipt, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    fd = os.open(attempt / "IMAGE_BUILD_RECEIPT.json",
                 os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    attempt.rename(RECEIPT_DIR)
    return {"receipt_path": str(RECEIPT_DIR / "IMAGE_BUILD_RECEIPT.json"),
            "receipt_sha256": _sha(raw), "receipt_bytes": len(raw),
            "image_id": image_id, "child_mtp_sha256": child_sha}


if __name__ == "__main__":
    print(json.dumps(build(), sort_keys=True, indent=2))
