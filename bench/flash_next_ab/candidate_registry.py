"""Code-owned Mia checkpoint and runtime identity for local C0 qualification.

No endpoint, image, model path, argv or environment value is accepted from a
contract or model response. NVIDIA v3 remains handled by qualification.py.
This module has no host effects. Selection only registers an isolated research
candidate; it does not promote a production model.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class CandidateSpec:
    spec_id: str
    contract_schema: str
    contract_id: str
    profile: str
    repository: str
    revision: str
    model_path: Path
    image_id: str
    served_name: str
    container_name: str
    compile_cache: Path
    contract_path: Path
    output_root: Path
    host_port: int
    files: tuple[tuple[str, int, str], ...]
    weight_files: tuple[str, ...]
    indexed_weight_files: tuple[str, ...]
    safetensors_total_bytes: int
    tensor_payload_bytes: int
    indexed_total_size_bytes: int
    repository_total_bytes: int
    packed_ple_path: Path
    packed_ple_bytes: int
    packed_ple_sha256: str
    acquisition_receipt_path: Path
    acquisition_receipt_sha256: str
    acquisition_receipt_bytes: int
    image_build_receipt_path: Path
    image_build_receipt_sha256: str
    image_build_receipt_bytes: int
    ple_build_receipt_path: Path
    ple_build_receipt_sha256: str
    ple_build_receipt_bytes: int
    recipe_commit: str
    paging_policy_json: str

    max_model_len: int = 32768
    kv_cache_memory_bytes: int = 2 * 1024**3
    docker_memory_limit_bytes: int = 96 * 1024**3
    min_mem_available_gib: int = 20

    @property
    def endpoint_name(self) -> str:
        """Fixed local transport route for this Mia research candidate."""
        return "flash_next_mia"

    def __post_init__(self) -> None:
        names = [row[0] for row in self.files]
        if names != sorted(names) or len(names) != len(set(names)):
            raise ValueError("candidate manifest must be exact, unique and sorted")
        if sum(row[1] for row in self.files) != self.repository_total_bytes:
            raise ValueError("candidate repository byte sum differs")
        safetensors = {name for name in names if name.endswith(".safetensors")}
        if safetensors != set(self.weight_files):
            raise ValueError("candidate safetensor set differs")
        if not set(self.indexed_weight_files) <= safetensors:
            raise ValueError("candidate indexed shard set differs")
        if sum(size for name, size, _ in self.files if name in safetensors) != self.safetensors_total_bytes:
            raise ValueError("candidate safetensor byte sum differs")

    def expected_model_files(self) -> dict[str, dict[str, Any]]:
        return {name: {"bytes": size, "sha256": digest} for name, size, digest in self.files}

    def model_artifact_sha256(self) -> str:
        return _digest({"repository": self.repository, "revision": self.revision,
                        "files": self.expected_model_files()})

    def identity_snapshot(self) -> dict[str, Any]:
        return {
            "spec_id": self.spec_id, "repository": self.repository, "revision": self.revision,
            "model_path": str(self.model_path), "image_id": self.image_id,
            "served_name": self.served_name, "container_name": self.container_name,
            "compile_cache": str(self.compile_cache), "contract_path": str(self.contract_path),
            "output_root": str(self.output_root), "host_port": self.host_port,
            "model_artifact_sha256": self.model_artifact_sha256(),
            "packed_ple": {"path": str(self.packed_ple_path), "bytes": self.packed_ple_bytes,
                           "sha256": self.packed_ple_sha256},
            "proof_receipts": {
                "acquisition": {"path": str(self.acquisition_receipt_path),
                                "sha256": self.acquisition_receipt_sha256,
                                "bytes": self.acquisition_receipt_bytes},
                "image_build": {"path": str(self.image_build_receipt_path),
                                "sha256": self.image_build_receipt_sha256,
                                "bytes": self.image_build_receipt_bytes},
                "ple_build": {"path": str(self.ple_build_receipt_path),
                              "sha256": self.ple_build_receipt_sha256,
                              "bytes": self.ple_build_receipt_bytes},
            },
            "recipe_commit": self.recipe_commit,
            "paging_policy": self.paging_policy(),
            "max_model_len": self.max_model_len,
            "kv_cache_memory_bytes": self.kv_cache_memory_bytes,
            "docker_memory_limit_bytes": self.docker_memory_limit_bytes,
            "min_mem_available_gib": self.min_mem_available_gib,
        }

    def identity_sha256(self) -> str:
        return _digest(self.identity_snapshot())

    def paging_policy(self) -> dict[str, Any]:
        """Return a fresh exact policy object; callers cannot mutate registration."""
        observed = json.loads(self.paging_policy_json)
        if _canonical(observed).decode() != self.paging_policy_json:
            raise ValueError("candidate paging policy is not canonical")
        return observed

    def expected_model_section(self) -> dict[str, Any]:
        return {
            "repository": self.repository, "revision": self.revision,
            "host_path": str(self.model_path), "container_path": "/models/qwen",
            "served_name": self.served_name,
            "safetensors_total_bytes": self.safetensors_total_bytes,
            "tensor_payload_bytes": self.tensor_payload_bytes,
            "repository_total_bytes": self.repository_total_bytes,
            "artifact_sha256": self.model_artifact_sha256(),
            "files": self.expected_model_files(),
            "full_sha256_before_mutation": True,
        }

    def expected_runtime_section(self) -> dict[str, Any]:
        return {
            "container_name": self.container_name,
            "host_address": "127.0.0.1", "host_port": self.host_port,
            "container_port": 8000, "compile_cache_path": str(self.compile_cache),
            "max_model_len": self.max_model_len, "max_num_seqs": 1,
            "gpu_memory_utilization": 0.75,
            "kv_cache_memory_bytes": self.kv_cache_memory_bytes,
            "max_num_batched_tokens": 4096,
            "kv_cache_dtype": "auto", "mamba_ssm_cache_dtype": "float32",
            "mtp_speculative_tokens": 0, "prefix_caching": False,
            "async_scheduling": False, "qsa_exact_topk": True,
            "language_model_only": True,
            "docker_memory_limit_bytes": self.docker_memory_limit_bytes,
            "docker_memory_swap_total_bytes": self.docker_memory_limit_bytes,
            "distributed_executor_backend": "mp",
            "safetensors_load_strategy": "lazy",
            "packed_ple_host_path": str(self.packed_ple_path),
            "packed_ple_bytes": self.packed_ple_bytes,
            "packed_ple_sha256": self.packed_ple_sha256,
        }

    def launch_argv(self, *, compilation_config: str) -> list[str]:
        """Exact local C0 launch vector; this function never invokes Docker."""
        cache = self.compile_cache
        env = (
            ("HF_HUB_OFFLINE", "1"), ("TRANSFORMERS_OFFLINE", "1"),
            ("VLLM_ENGINE_READY_TIMEOUT_S", "3600"),
            ("VLLM_PLE_CPU_OFFLOAD", "1"),
            ("VLLM_PLE_PACKED_TABLE_DIR", "/models/ple"),
            ("VLLM_PLE_OFFLOAD_STEP_TIMEOUT", "300"),
            ("VLLM_QSA_EXACT_TOPK", "1"),
            ("VLLM_MXFP8_EMULATION_DEQUANT_AT_LOAD", "0"),
            ("PROMETHEUS_MULTIPROC_DIR", "/tmp/vllm-prometheus"),
        )
        argv = [
            "docker", "create", "--name", self.container_name, "--restart=no",
            "--gpus", "all", "--memory", str(self.docker_memory_limit_bytes),
            "--memory-swap", str(self.docker_memory_limit_bytes),
            "--ipc=host", "-p", f"127.0.0.1:{self.host_port}:8000",
            "--tmpfs", "/tmp/vllm-prometheus:rw,size=256m",
            "-v", f"{self.model_path}:/models/qwen:ro",
            "-v", f"{self.packed_ple_path.parent}:/models/ple:ro",
            "-v", f"{cache}:/root/.cache:rw",
        ]
        for name, value in env:
            argv += ["-e", f"{name}={value}"]
        argv += [
            self.image_id, "/models/qwen",
            "--served-model-name", self.served_name,
            "--host", "0.0.0.0", "--port", "8000",
            "--load-format", "safetensors", "--safetensors-load-strategy", "lazy",
            "--trust-remote-code", "--quantization", "modelopt",
            "--tensor-parallel-size", "1",
            "--max-model-len", str(self.max_model_len),
            "--max-num-seqs", "1", "--language-model-only",
            "--gpu-memory-utilization", "0.75",
            "--kv-cache-memory-bytes", str(self.kv_cache_memory_bytes),
            "--no-enable-prefix-caching", "--enable-chunked-prefill",
            "--max-num-batched-tokens", "4096",
            "--distributed-executor-backend", "mp",
            "--compilation-config", compilation_config,
            "--no-enable-flashinfer-autotune",
            "--kv-cache-dtype", "auto",
            "--mamba-ssm-cache-dtype", "float32",
            "--no-async-scheduling",
            "--reasoning-parser", "qwen3",
            "--enable-auto-tool-choice", "--tool-call-parser", "qwen3_coder",
        ]
        return argv


# This tuple is generated from the independently SHA-verified 51-file pinned
# Mia manifest; it is deliberately embedded in code rather than loaded from an
# external contract or mutable acquisition receipt. See generate_registry.py.
MIA_FILES: tuple[tuple[str, int, str], ...] = (
    ('.gitattributes', 1635, 'd1a8f4a1d2e3787c5956393d9306365ebefe1912cb76828870682b1ab16f5c27'),
    ('README.md', 599, '88aa02fb581958b987c78ce8536e5913a1522156b7657a19ecdafbf8cf3be4ab'),
    ('amax.safetensors', 20003400, 'd2c9c496023f255246e4da5ec2d06e23570e8c361461159f494a1018965e6631'),
    ('amax_checkpoint.json', 1003, 'fa77bb5fcd4cf99cd57294752ebfe25d8ec316f9289dc2b27a2c55eeb606362f'),
    ('amax_checkpoint.safetensors', 20001100, '683be5968daa0451dbffb7c9fd2968803ec298adaf09d03a7825bec9295aa781'),
    ('chat_template.jinja', 8952, 'c3cf9e34abf4f9e36c2d72165aa9c132d3e2a725b6c2586aaa3a8af9d7a81041'),
    ('config.json', 109897, '2d655dfa625c3c018f9685031367bc83f8532d3faf3333d7c838b2bdc13b8a7e'),
    ('generation_config.json', 2097, '735ec63e625c2086fbec18327233a03a7b060fddabfd7915af4e6fdcec3187a2'),
    ('hf_quant_config.json', 99088, 'd60c54caa65317fd8f1338bdeb81b9014512ac8f21ec18da22541cb88c6784b7'),
    ('merges.txt', 3353259, 'a9d356d7bdf1ef4949e3e748e95b8e10ad9d4e2e838eddc38a0a7b6b94d1db8d'),
    ('model-00001-of-00034.safetensors', 2841505880, '3f870511a20ad170c997517765f03d475bcd364ae1a6011491085cab620d3c39'),
    ('model-00002-of-00034.safetensors', 1575009800, 'fe8f4bdbce28f4911f10460b75581b6c88a8ade9b836d2f1ec22c6bee6f976a8'),
    ('model-00003-of-00034.safetensors', 1575009808, '2b7d1312a660cf17bb05c34e1ac79570820f86fb1e1115108ee40562e48acb5e'),
    ('model-00004-of-00034.safetensors', 1575009808, '25ba4508c209a5cc54c04edb1edb8d0a0b5efa80e5f99637e2263fa78d6a25e8'),
    ('model-00005-of-00034.safetensors', 1575009808, 'a9848067bb49f44b8339bcdca9d60ca74d801a6df874c979c6f901c8da6ff545'),
    ('model-00006-of-00034.safetensors', 1575009808, '66fc496b58675a90b94d9f36765fe67692dd8a4c966ec0692e076d751f835c8d'),
    ('model-00007-of-00034.safetensors', 1575009808, '68f89e84be13069bd9f2928b44a9f9638d628fd62be5abb6a4fc956c1af25ea9'),
    ('model-00008-of-00034.safetensors', 1575009808, 'b8bdaa0a7b027dc0fa38c2e43bb31e8ddf9ba9288d3d0f28c422e6947241d96e'),
    ('model-00009-of-00034.safetensors', 1575009808, '6c5a85990b16a93f0e7e28fb76f56713d5cbc05bef494bb15360188f575746e9'),
    ('model-00010-of-00034.safetensors', 1575009808, '8734a1fc3b5857391fbf2252d4305391a9f77894b70577949f472fc75386582f'),
    ('model-00011-of-00034.safetensors', 1575009808, '29792378d43c9f70d9f3fbdd07d0ee24b38f81fe27aff25a02ba0d3cde8df13c'),
    ('model-00012-of-00034.safetensors', 1575009808, 'b23e615ebefff4753d982d9ec6a8be6ad57353a8900146a3ec4e217f81c10e61'),
    ('model-00013-of-00034.safetensors', 1575009808, '9da7b4570fc3f13cb781e5aca5e79d0edfc10be5555a18bc7bda8f47459d5acf'),
    ('model-00014-of-00034.safetensors', 1575009808, '53e770d0bdf6261e30abaae2477aa0b50f6686511e0240514ded0fd65edbfeba'),
    ('model-00015-of-00034.safetensors', 1575009816, '03440de56d127ff58e72963aafd0de0574b825667330c50b4441bb300dae9f06'),
    ('model-00016-of-00034.safetensors', 1575009824, 'ce2e0474ccb34c56003a61608b46d3a8f668c218a9993c1f861239df83afe77b'),
    ('model-00017-of-00034.safetensors', 1575009824, '57f84845e0b8bcab738e70f0f880e941f1baa8da14663293d7d40481288c73a0'),
    ('model-00018-of-00034.safetensors', 1575009824, '3477df0be60910576fc5a1f8159d8dbbf7847a03872b9cb53664808e1d5dfac8'),
    ('model-00019-of-00034.safetensors', 2438722732, '43c22213b2fe0990c7fc2aa54c0ea65062eb93253b4ea419914d1a655e64b23a'),
    ('model-00020-of-00034.safetensors', 5133924592, 'b7143694bf8698c5b704ae9b3d492a0e9b8ef57bdda8ae6f3f29f264c183ad17'),
    ('model-00021-of-00034.safetensors', 5194891408, '522bbbc894183865726e06ca44021d275d03cc0e8dcd60a2c7074d870e811d37'),
    ('model-00022-of-00034.safetensors', 5133933936, '5a4789f6da6b386b09cb9093b0315fe12a816142958e4d8a4ae83e4fbaa066e7'),
    ('model-00023-of-00034.safetensors', 5194908864, 'cd0aaef1c8688cb4e35b488048ede2a6b653e1d558b20d4657567df24dc8be13'),
    ('model-00024-of-00034.safetensors', 5188755712, 'd07198edd38ae8740d556487729ae87be1e21e31a88cf6624c1b3f9d0fc6de76'),
    ('model-00025-of-00034.safetensors', 5133940040, 'c7d5e642968679ca14d07bdb1e8c2187c59898611d05a6909c209738642c9519'),
    ('model-00026-of-00034.safetensors', 5194907416, '47a7c7a70188cb3dc318071a5278260c4b05d7ce1b69c3b99e7bf1c0e42c353b'),
    ('model-00027-of-00034.safetensors', 5133940216, 'a81fedf160434806e81f36731c853fe4e3f973dea2f0817043987f32b4915a54'),
    ('model-00028-of-00034.safetensors', 5194907672, '91c5d479fe4de1035c430ad7fd3de9d15214a46fd786ca7909d1f2fa40ef603a'),
    ('model-00029-of-00034.safetensors', 5133939992, 'f31c6f61968f6f9e85d469f31c55c82ab6c5f2bc54c1d7a0cd6b23ac45f0ce15'),
    ('model-00030-of-00034.safetensors', 5194908960, 'df8627f5b8b0711b2ebf415c1f2549ef0b50f964e0babb560469b191b33c6a14'),
    ('model-00031-of-00034.safetensors', 5188755536, '654c8f9ae1ab5de393cbcdd46a13bd0d3d1c1005e575879e0e660d40ad9ef425'),
    ('model-00032-of-00034.safetensors', 5133940208, '7de2e680802ad92a0e019f875ebc07f2d5d82c8bca1c64b0f817d547bc3c9de7'),
    ('model-00033-of-00034.safetensors', 5021547836, '0fbcdf16c13cd830447efdcd3be19b82ec0e76b7f57f0e96952c1f2b62002b11'),
    ('model-00034-of-00034.safetensors', 1597270800, 'fe0a0a227e39c4d02dc66c726d3e1ad87ef082e90a6b023ac90b2bb301672203'),
    ('model-inputscales.safetensors', 9669936, '49c7d04606ff7c8f103b4d1fc9742b44649a2937b25ecc896a5450ab1020f308'),
    ('model.safetensors.index.json', 33074286, '435eef76fc10fc6e932a208a1f85a86bc9c7ffc389b27b34ba83bb6a5d0371e9'),
    ('preprocessor_config.json', 390, '27225450ac9c6529872ee1924fcb0962ff5634834f817040f444118116f4e516'),
    ('tokenizer.json', 12809320, '0997f410c57a1f4e53b09e4be8f4a172d90edd9564368fb0847030937229b9f3'),
    ('tokenizer_config.json', 17928, 'b11349aafa7cdc6a320767cf7ceb29ed82f7eda5d65e8e0819e76f0ce947bf27'),
    ('video_preprocessor_config.json', 385, '7768af27c1fafa9cc9011c1dc20067e03f8915e03b63504550e11d5066986d13'),
    ('vocab.json', 6722759, 'ce99b4cb2983d118806ce0a8b777a35b093e2000a503ebde25853284c9dfa003'),
)
MIA_INDEX_SHARDS: tuple[str, ...] = (
    'model-00001-of-00034.safetensors',
    'model-00002-of-00034.safetensors',
    'model-00003-of-00034.safetensors',
    'model-00004-of-00034.safetensors',
    'model-00005-of-00034.safetensors',
    'model-00006-of-00034.safetensors',
    'model-00007-of-00034.safetensors',
    'model-00008-of-00034.safetensors',
    'model-00009-of-00034.safetensors',
    'model-00010-of-00034.safetensors',
    'model-00011-of-00034.safetensors',
    'model-00012-of-00034.safetensors',
    'model-00013-of-00034.safetensors',
    'model-00014-of-00034.safetensors',
    'model-00015-of-00034.safetensors',
    'model-00016-of-00034.safetensors',
    'model-00017-of-00034.safetensors',
    'model-00018-of-00034.safetensors',
    'model-00019-of-00034.safetensors',
    'model-00020-of-00034.safetensors',
    'model-00021-of-00034.safetensors',
    'model-00022-of-00034.safetensors',
    'model-00023-of-00034.safetensors',
    'model-00024-of-00034.safetensors',
    'model-00025-of-00034.safetensors',
    'model-00026-of-00034.safetensors',
    'model-00027-of-00034.safetensors',
    'model-00028-of-00034.safetensors',
    'model-00029-of-00034.safetensors',
    'model-00030-of-00034.safetensors',
    'model-00031-of-00034.safetensors',
    'model-00032-of-00034.safetensors',
    'model-00033-of-00034.safetensors',
    'model-00034-of-00034.safetensors',
    'model-inputscales.safetensors',
)

MIA = CandidateSpec(
    spec_id="mia-925d7be6-c0-s1", contract_schema="qwen-flash-next-qualification/v4",
    contract_id="qwen38-flash-next-mia-c0-s1-20260915", profile="C0-MIA-S1",
    repository="Mia-AiLab/Qwen3.8-Flash-Next-NVFP4",
    revision="925d7be6c14c6c9442ef83e8f05b5a3c39304f69",
    model_path=Path("/mnt/models/qwen3.8-flash-next-mia-925d7be6"),
    image_id="sha256:da68dd27a8ef1dadd0f380178a51f0a0671dc4235933ea1ae89fdaf66295ec72",
    served_name="qwen3.8-flash-next-mia",
    container_name="vllm-qwen-ab-flash-mia-20260915",
    compile_cache=Path("/home/decross1/projects/a_bgt_rsi_runtime_candidates/flash-next-20260914/compile-cache-mia-c0/qwen38-flash-next-mia-d038-c0"),
    contract_path=Path("/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/qwen-flash-next-research/runtime/launch-contract.mia-c0.json"),
    output_root=Path("/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/qwen-flash-next-research/qualification-runs"),
    host_port=8012,
    files=MIA_FILES,
    weight_files=tuple(name for name, _, _ in MIA_FILES if name.endswith(".safetensors")),
    indexed_weight_files=MIA_INDEX_SHARDS,
    safetensors_total_bytes=105879543020,
    tensor_payload_bytes=105798973864,
    indexed_total_size_bytes=105839538520,
    repository_total_bytes=105935744618,
    packed_ple_path=Path("/mnt/models/qwen3.8-flash-next-mia-ple-925d7be6/language_model.model.layers.1.ple.ple_embedding.ngram_embedding.packed_u8"),
    packed_ple_bytes=28800138240,
    packed_ple_sha256="e404177a577d4f27930df88d8055af66c4b66b5b2d0a194ef66f8a6c55fbefaf",
    acquisition_receipt_path=Path("/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/qwen-flash-next-research/download/mia-acquisition/acquisition-receipt.json"),
    acquisition_receipt_sha256="7c03284cfb5f0a6137d6c6e48095ed200252f752f8f3cd7d24b142064e7dee2e",
    acquisition_receipt_bytes=5892,
    image_build_receipt_path=Path("/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/qwen-flash-next-research/runtime/mia-candidate-build/IMAGE_BUILD_RECEIPT.json"),
    image_build_receipt_sha256="b7fc40e423867b35e06afa46ca1c157fade813d98e1452f26bcc050c25153db2",
    image_build_receipt_bytes=4172,
    ple_build_receipt_path=Path("/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/qwen-flash-next-research/download/mia-ple-build/preparation-receipt.json"),
    ple_build_receipt_sha256="90fda2e8c46494d4d686f87ee6cdeaa7008102ca522266e20f38f530a36e6245",
    ple_build_receipt_bytes=2179,
    recipe_commit="d03809008834124e80223c3482f2ddb59577a48f",
    paging_policy_json='{"candidate_cgroup_oom_initial_max":0,"candidate_cgroup_oom_kill_initial_max":0,"candidate_cgroup_oom_kill_max_delta":0,"candidate_cgroup_oom_max_delta":0,"candidate_cgroup_swap_max_bytes":0,"host_page_size_bytes":4096,"load":{"phase_total_breach_bytes":4294967296,"window_5s_breach_bytes":536870912,"window_60s_breach_bytes":2147483648},"max_sample_gap_seconds":10,"ready_quiescence_seconds":60,"restoration_host_swap_action":"diagnostic_only","serving":{"phase_total_breach_bytes":134217728,"window_5s_breach_bytes":33554432,"window_60s_breach_bytes":67108864},"startup_gate_phases":["load","ready"]}',
)


def select_candidate(contract: dict[str, Any]) -> CandidateSpec | None:
    """Return Mia only for its exact versioned ID; None means legacy NVIDIA.

    No service call or model-provided field may select a variant. Unsupported
    versions and mixed IDs fail closed, including a Mia claim in v3.
    """
    if not isinstance(contract, dict):
        raise TypeError("candidate contract is not an object")
    schema = contract.get("schema")
    if schema == "qwen-flash-next-qualification/v3":
        if "candidate" in contract or contract.get("contract_id") not in {
            "qwen38-flash-next-c0-s0-20260915", "qwen38-flash-next-c0-s1-20260915"
        }:
            raise ValueError("legacy NVIDIA contract identity differs")
        return None
    if schema != MIA.contract_schema:
        raise ValueError("unsupported candidate contract schema")
    if contract.get("contract_id") != MIA.contract_id or contract.get("profile") != MIA.profile:
        raise ValueError("Mia contract identity differs")
    if contract.get("candidate") != {"id": MIA.spec_id, "spec_sha256": MIA.identity_sha256()}:
        raise ValueError("Mia spec identity differs")
    return MIA
