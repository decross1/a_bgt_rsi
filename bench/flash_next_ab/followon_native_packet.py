"""Freeze a real 65K Mia context canary before model-service mutation.

The source is the already tokenized public development packet, not model
metadata or a hand-declared token count. Preparing this on the CPU before
Nara/resident stop is mandatory for the native69,632 candidate profile.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from bench.flash_next_ab.harness import _read_regular_file, _strict_object

RESEARCH = Path(
    "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/"
    "qwen-flash-next-research/evaluation"
)
PACK_FILE = RESEARCH / "context-packs-draft-v2.json"
PACK_SHA256 = "f7e0619be42ca770c39728a51b3a73a92562780be7797662c4f63139ba5c7876"
COUNT_FILE = RESEARCH / "context-arm-tokenization-v1-20260915.json"
COUNT_SHA256 = "e28cd45e6e23a256b4f6b49ca2779173ec93bc018beb31a59f3a904e930ee110"
PACK_ID = "long_context_8k_grim_threshold-c65536-late"
TOKENIZER = Path("/mnt/models/qwen3.8-flash-next-mia-925d7be6")
TEMPLATE_SHA256 = "c3cf9e34abf4f9e36c2d72165aa9c132d3e2a725b6c2586aaa3a8af9d7a81041"
INPUT_TOKENS = 65_581
OUTPUT_TOKENS = 2_048
MESSAGE_SHA256 = "90584d5d55d665c262be09d2828b0f857a8449924405a6a29f2a46b762cf7186"


class NativePacketError(ValueError):
    pass


def _require(ok: bool, reason: str) -> None:
    if not ok:
        raise NativePacketError(reason)


def _raw(path: Path, maximum: int) -> bytes:
    raw, observed = _read_regular_file(path, label="native context source",
                                       max_bytes=maximum)
    _require(observed == path.absolute(),
             "native context source path was redirected")
    return raw


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def build_native_context_packet() -> dict:
    """Retokenize the actual packet with Mia's pinned chat template."""
    pack_raw = _raw(PACK_FILE, 8 * 1024 * 1024)
    counts_raw = _raw(COUNT_FILE, 512_000)
    _require(_sha(pack_raw) == PACK_SHA256 and _sha(counts_raw) == COUNT_SHA256,
             "native context pack or tokenization receipt changed")
    pack = _strict_object(pack_raw, "native context pack")
    counts = _strict_object(counts_raw, "native context tokenization")
    _require(pack.get("schema_version") == "flash-context-pack-manifest/v2"
             and counts.get("schema_version") == "flash-context-arm-tokenization/v1"
             and counts.get("pack_sha256") == PACK_SHA256,
             "native context packet/source identity differs")
    candidates = [row for row in pack.get("tasks", [])
                  if isinstance(row, dict) and row.get("id") == PACK_ID]
    arm = counts.get("arms", {}).get("flash_next_mia")
    rows = [row for row in arm.get("counts", [])
            if isinstance(row, dict) and row.get("cell_id") == PACK_ID] if isinstance(arm, dict) else []
    _require(len(candidates) == len(rows) == 1
             and arm.get("tokenizer_path") == str(TOKENIZER)
             and arm.get("template_sha256") == TEMPLATE_SHA256,
             "native context has no uniquely pinned Mia tokenizer/count")
    selected, counted = candidates[0], rows[0]
    messages = selected.get("messages")
    _require(isinstance(messages, list)
             and selected.get("actual_input_tokens") == INPUT_TOKENS
             and selected.get("max_output_tokens") == OUTPUT_TOKENS
             and selected.get("messages_sha256") == MESSAGE_SHA256
             and counted.get("source_messages_sha256") == MESSAGE_SHA256
             and counted.get("actual_input_tokens") == INPUT_TOKENS
             and counted.get("minimum_server_context_tokens")
                == INPUT_TOKENS + OUTPUT_TOKENS,
             "native context task/content/count differs")
    template = _raw(TOKENIZER / "chat_template.jinja", 512_000)
    _require(_sha(template) == TEMPLATE_SHA256,
             "native context chat template changed")
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(str(TOKENIZER), local_files_only=True)
    token_ids = tokenizer.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=True,
        enable_thinking=False, return_dict=False,
    )
    _require(isinstance(token_ids, list) and len(token_ids) == INPUT_TOKENS,
             "true native prompt token count differs from the frozen receipt")
    grader = selected.get("grader")
    expected = grader.get("expected") if isinstance(grader, dict) else None
    _require(isinstance(expected, dict)
             and expected.get("answer_code") == "claim_contradicted_threshold_0_5"
             and expected.get("citations") == [
                 "GT8A-CLAIM-0017", "GT8A-PAYOFF-0073",
                 "GT8A-THRESHOLD-0132",
             ], "native context exact public answer changed")
    answer = json.dumps(expected, separators=(",", ":"), ensure_ascii=False)
    _require(INPUT_TOKENS + OUTPUT_TOKENS <= 69_632,
             "native context plus reserved completion exceeds the profile")
    return {"pack_sha256": PACK_SHA256,
            "cell_id": PACK_ID,
            "source_messages_sha256": MESSAGE_SHA256,
            "actual_input_tokens": INPUT_TOKENS,
            "max_tokens": OUTPUT_TOKENS,
            "messages": copy.deepcopy(messages),
            "expected": answer}


def prepared_factory() -> object:
    """Return only after the true packet has been verified before mutation."""
    packet = build_native_context_packet()

    def frozen() -> dict:
        _require(_sha(_raw(PACK_FILE, 8 * 1024 * 1024)) == PACK_SHA256
                 and _sha(_raw(COUNT_FILE, 512_000)) == COUNT_SHA256
                 and _sha(_raw(TOKENIZER / "chat_template.jinja", 512_000))
                    == TEMPLATE_SHA256,
                 "prepared native packet source changed before probe")
        return copy.deepcopy(packet)

    return frozen
