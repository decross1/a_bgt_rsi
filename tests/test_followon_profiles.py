"""Code-owned profile and contract source tests.

The original Mia C0 identity and runtime are pinned independently.
"""
from __future__ import annotations

import copy
import json
import struct

import pytest

from bench.flash_next_ab import qualification as q
from bench.flash_next_ab.candidate_registry import MIA, select_candidate
from bench.flash_next_ab.followon_profiles import (
    MIA_CTX69632,
    MIA_MTP1,
    MIA_MTP2,
    MIA_MTP3,
    MIA_MTP3_REDUCED47K_FP8_QSA,
    MIA_MTP3_REDUCED47K_OPT,
    MTP_MODULE_SHA256,
    REGISTERED_MIA_SPECS,
    requires_profile_canary,
    select_mia_contract,
)
from bench.flash_next_ab.mia_candidate_integration import (
    plan_mia_qualification,
    validate_mia_contract,
    validate_output,
)

C0_SPEC_SHA256 = "dde4fe1f72cf91de92089a95748cee1f6a8204e351d517aa0ae46d8d27122857"
FULLVOCAB = (MIA_MTP1, MIA_MTP2, MIA_MTP3)


def _contract(spec):
    """Construct the future v5 contract from the exact old safety/accounting."""
    old = json.loads(MIA.contract_path.read_text())
    value = copy.deepcopy(old)
    value["schema"] = spec.contract_schema
    value["contract_id"] = spec.contract_id
    value["profile"] = spec.profile
    value["candidate"] = {"id": spec.spec_id, "spec_sha256": spec.identity_sha256()}
    value["image"] = {"id": spec.image_id, "architecture": "arm64"}
    value["model"] = spec.expected_model_section()
    value["runtime"] = spec.expected_runtime_section()
    value["probe_set"] = spec.qualification_probe_set
    value["safety"]["min_mem_available_gib"] = spec.min_mem_available_gib
    value["safety"]["paging_policy"] = spec.paging_policy()
    if spec is not MIA:
        value["safety"]["profile_canary_timeout_seconds"] = (
            spec.profile_canary_timeout_seconds
        )
    return value


def test_old_c0_registration_is_byte_identical():
    assert MIA.identity_sha256() == C0_SPEC_SHA256
    assert MIA.expected_runtime_section()["mtp_speculative_tokens"] == 0
    assert MIA.expected_runtime_section()["max_model_len"] == 32768
    assert MIA.expected_runtime_section()["kv_cache_memory_bytes"] == 2 * 1024**3
    argv = MIA.launch_argv(compilation_config=q.COMPILATION_CONFIG)
    assert "--speculative-config" not in argv
    assert requires_profile_canary(MIA) is False
    assert "VLLM_MTP_DRAFT_VOCAB" not in " ".join(argv)
    old = json.loads(MIA.contract_path.read_text())
    expected = plan_mia_qualification(old, "a" * 64,
                                      MIA.output_root / "qfn-mia-c0-regression", q)
    assert expected["docker_create_argv"] == argv


@pytest.mark.parametrize("spec,depth", [(MIA_MTP1, 1), (MIA_MTP2, 2), (MIA_MTP3, 3)])
def test_mtp_depth_is_literal_full_vocab(spec, depth):
    assert spec in REGISTERED_MIA_SPECS
    assert spec.image_id == MIA.image_id
    assert spec.model_artifact_sha256() == MIA.model_artifact_sha256()
    assert spec.packed_ple_sha256 == MIA.packed_ple_sha256
    assert spec.max_model_len == 32768 and spec.kv_cache_memory_bytes == 2 * 1024**3
    assert spec.mtp_module_sha256 == MTP_MODULE_SHA256
    argv = spec.launch_argv(compilation_config=q.COMPILATION_CONFIG)
    assert argv.count("--speculative-config") == 1
    obj = json.loads(argv[argv.index("--speculative-config") + 1])
    assert obj == {"method": "mtp", "num_speculative_tokens": depth}
    assert not {"use_local_argmax_reduction", "num_speculative_tokens_per_batch_size"} & set(obj)
    assert "VLLM_MTP_DRAFT_VOCAB" not in " ".join(argv)
    assert spec.expected_runtime_section()["mtp_speculative_tokens"] == depth
    assert spec.expected_runtime_section()["speculative_config"] == obj
    assert spec.container_name != MIA.container_name
    assert spec.compile_cache != MIA.compile_cache
    assert spec.run_id_prefix == f"qfn-mia-mtp{depth}-"
    assert requires_profile_canary(spec) is True


def test_context_profile_is_native_bf16_mtp0_and_exact_kv():
    spec = MIA_CTX69632
    assert spec.image_id == MIA.image_id
    assert spec.model_artifact_sha256() == MIA.model_artifact_sha256()
    assert spec.max_model_len == 69632
    assert spec.kv_cache_memory_bytes == 3 * 1024**3
    assert spec.mtp_speculative_tokens == 0
    runtime = spec.expected_runtime_section()
    assert runtime["kv_cache_dtype"] == "auto"
    assert runtime["mamba_ssm_cache_dtype"] == "float32"
    assert runtime["language_model_only"] is True
    assert "speculative_config" not in runtime
    argv = spec.launch_argv(compilation_config=q.COMPILATION_CONFIG)
    assert argv[argv.index("--max-model-len") + 1] == "69632"
    assert argv[argv.index("--kv-cache-memory-bytes") + 1] == str(3 * 1024**3)
    assert "--hf-overrides" not in argv
    assert "--speculative-config" not in argv
    assert spec.run_id_prefix == "qfn-mia-ctx69632-"
    assert requires_profile_canary(spec) is True


def test_reduced_child_model_verification_hashes_vocab_before_mutation(monkeypatch):
    spec = MIA_MTP3_REDUCED47K_OPT
    contract = _contract(spec)
    expected = spec.expected_model_files()
    seen = []

    def source_hash(path, size, monitor=None):
        seen.append((path, size))
        if path == spec.packed_ple_path:
            return spec.packed_ple_sha256
        if path == spec.draft_vocab_path:
            return spec.draft_vocab_sha256
        row = expected.get(path.name)
        assert path.parent == spec.model_path and row["bytes"] == size
        return row["sha256"]

    monkeypatch.setattr(q, "_hash_regular_file", source_hash)
    proof = q.verify_model(contract, spec=spec)
    assert proof["full_sha256"] is True
    assert proof["candidate"] == contract["candidate"]
    assert proof["reduced_draft_vocab"] == {
        "path": str(spec.draft_vocab_path), "bytes": 274_530,
        "sha256": spec.draft_vocab_sha256, "id_count": 47_149,
    }
    assert seen[-1] == (spec.draft_vocab_path, spec.draft_vocab_bytes)

    def wrong_vocab(path, size, monitor=None):
        return "0" * 64 if path == spec.draft_vocab_path else source_hash(path, size, monitor)

    monkeypatch.setattr(q, "_hash_regular_file", wrong_vocab)
    with pytest.raises(q.QualificationError, match="reduced draft vocabulary"):
        q.verify_model(contract, spec=spec)


def test_fp8_qsa_overlay_is_a_distinct_registered_child_of_optimized_parent():
    parent = MIA_MTP3_REDUCED47K_OPT
    child = MIA_MTP3_REDUCED47K_FP8_QSA
    assert child in REGISTERED_MIA_SPECS
    assert parent.identity_sha256() == (
        "e71d3134f407cad3c288c21f9485c27352676dbb7de647c5b567777256702a50"
    )
    assert child.image_id == (
        "sha256:ba65a549de4dce8cab70f27c200e408b28470ea175fc8c301e27b4deb154fbed"
    )
    assert child.image_id != parent.image_id
    assert child.model_artifact_sha256() == parent.model_artifact_sha256()
    assert child.model_path == parent.model_path
    assert child.draft_vocab_sha256 == parent.draft_vocab_sha256
    assert child.compile_cache != parent.compile_cache
    assert child.container_name != parent.container_name
    assert child.contract_path != parent.contract_path
    assert child.image_build_receipt_sha256 == (
        "3a75a795ec167885794a55de29e1a39e537fb0e953508ea9475cfce450e36ebc"
    )
    assert requires_profile_canary(child) is True


def test_v5_plan_binds_current_registered_source_before_host_ops(monkeypatch):
    from bench.flash_next_ab import followon_dispatch

    spec = MIA_MTP3_REDUCED47K_OPT
    contract = _contract(spec)
    output = spec.output_root / "qfn-mia-mtp3-red47k-source-unit"
    plan = plan_mia_qualification(contract, "a" * 64, output, q)
    bundle = followon_dispatch.frozen_followon_source_bundle()
    assert plan["registered_code_root"] == str(followon_dispatch.FOLLOWON_CODE_ROOT)
    assert plan["followon_source_bundle"] == bundle
    assert plan["followon_source_bundle_sha256"] == q.sha256(bundle)

    corrupted = copy.deepcopy(bundle)
    corrupted["reduced_profile_literal.py"]["sha256"] = "0" * 64
    monkeypatch.setattr(followon_dispatch, "frozen_followon_source_bundle",
                        lambda: corrupted)
    with pytest.raises(q.QualificationError, match="immutable registration"):
        q.execute_worker(plan, contract, output, spec=spec)


@pytest.mark.parametrize("spec", REGISTERED_MIA_SPECS)
def test_contract_selects_only_its_registered_object(spec):
    value = _contract(spec)
    assert select_candidate(value) is spec
    assert select_mia_contract(value) is spec
    assert validate_mia_contract(value, q) == json.loads(q.canonical_json(value))
    planned = plan_mia_qualification(value, "b" * 64,
                                      spec.output_root / f"{spec.run_id_prefix}regression", q)
    assert planned["candidate"] == value["candidate"]
    assert planned["docker_create_argv"] == spec.launch_argv(
        compilation_config=q.COMPILATION_CONFIG)
    assert planned["probe_set"] == spec.qualification_probe_set


@pytest.mark.parametrize("spec", (MIA_MTP1, MIA_MTP2, MIA_MTP3, MIA_CTX69632))
def test_mixed_contract_and_wrong_run_prefix_rejected(spec):
    value = _contract(spec)
    value["candidate"] = {"id": MIA.spec_id, "spec_sha256": MIA.identity_sha256()}
    with pytest.raises((ValueError, TypeError)):
        select_mia_contract(value)
    with pytest.raises(ValueError):
        validate_output(spec.output_root / "qfn-mia-c0-wrong-profile", spec)


def test_mia_static_mtp_tensor_and_quant_header():
    config = json.loads((MIA.model_path / "config.json").read_text())
    text = config["text_config"]
    assert text["mtp_num_hidden_layers"] == 1 and text["num_hidden_layers"] == 48
    assert text["max_position_embeddings"] >= 69632
    assert text["vocab_size"] == 248320 and text["hidden_size"] == 2560
    assert config["tie_word_embeddings"] is False
    quant = json.loads((MIA.model_path / "hf_quant_config.json").read_text())
    assert quant["quant_algo"] == "MIXED_PRECISION"
    for name in ("mtp.layers.0.mlp.experts", "mtp.layers.48.mlp.experts"):
        assert quant["quantized_layers"][name] == {
            "quant_algo": "W4A16_NVFP4", "group_size": 16,
        }
    shard = MIA.model_path / "model-00034-of-00034.safetensors"
    with shard.open("rb") as h:
        header_len = struct.unpack("<Q", h.read(8))[0]
        assert 0 < header_len < 2_000_000
        header = json.loads(h.read(header_len))
    mtp = {k: v for k, v in header.items() if k.startswith("mtp.")}
    assert len(mtp) == 4637
    assert all(k == "__metadata__" or k.startswith("mtp.") for k in header)
    assert sum(v["data_offsets"][1] - v["data_offsets"][0] for v in mtp.values()) == 1596720640
