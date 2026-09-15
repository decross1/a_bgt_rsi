"""CPU-only context pack construction; never launches a model or calls an API.

Preserves every focal record, question and grader from the public development
source. Only irrelevant records and focal placement change. Token counts include
the actual chat template and generation prefix for the selected tokenizer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

SUITE_ID = "flash-context-placement-public-development-v1-20260915"
TARGETS = (2048, 8192, 16384, 32768, 65536)
PLACEMENTS = ("early", "middle", "late")
OUTPUT_CAP = 2048
SOURCE_SHA256 = "7a65db923631d01c296ba8e65e924e646c9134082bb2a600c099eeb66eb6f735"
TOKENIZER_PATH = Path("/mnt/models/qwen3.8-flash-next-nvfp4-fc694b54")
TEMPLATE_SHA256 = "c3cf9e34abf4f9e36c2d72165aa9c132d3e2a725b6c2586aaa3a8af9d7a81041"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def components(task: dict) -> tuple[str, list[str], str]:
    lines = task["prompt"].splitlines()
    focal = [line for line in lines if line.startswith("[GT")]
    other = [line for line in lines if not line.startswith(("[GT", "[SYN-"))]
    if len(other) != 2 or not other[1].startswith("Question:"):
        raise ValueError("unexpected source layout")
    ids = [re.match(r"\[([^]]+)\]", line).group(1) for line in focal]
    expected = task["grader"]["expected"]["citations"]
    if set(ids) != set(expected) or len(ids) != len(expected):
        raise ValueError("focal records differ from required evidence")
    return other[0], focal, other[1]


def distractor(index: int) -> str:
    subjects = ("roommate matching", "network formation", "cost sharing", "committee voting")
    # No source facts, answer codes, or real empirical claims enter padding.
    return (
        f"[SYN-SWEEP-D{index:06d}] Public synthetic archive distractor {index:06d}: "
        f"the {subjects[index % len(subjects)]} fixture recorded a parser checksum "
        "under an unrelated formatting batch. This administrative record contains "
        "no evidence about the focal claim and must not be cited."
    )


def messages(task: dict, noise_count: int, placement: str) -> list[dict]:
    intro, focal, question = components(task)
    fraction = {"early": 0.1, "middle": 0.5, "late": 0.9}[placement]
    split = int(noise_count * fraction)
    noise = [distractor(i + 1) for i in range(noise_count)]
    prompt = "\n".join([intro, *noise[:split], *focal, *noise[split:], question])
    return [{"role": "system", "content": task["system"]}, {"role": "user", "content": prompt}]


def count(tokenizer, rendered_messages: list[dict]) -> int:
    ids = tokenizer.apply_chat_template(
        rendered_messages, tokenize=True, add_generation_prompt=True,
        enable_thinking=False, return_dict=False,
    )
    return len(ids)


def focal_position(tokenizer, rendered_messages: list[dict], focal: list[str]) -> dict:
    text = tokenizer.apply_chat_template(
        rendered_messages, tokenize=False, add_generation_prompt=True,
        enable_thinking=False,
    )
    first = text.index(focal[0])
    end = text.index(focal[-1]) + len(focal[-1])
    encoded = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)
    expected = tokenizer.apply_chat_template(
        rendered_messages, tokenize=True, add_generation_prompt=True,
        enable_thinking=False, return_dict=False,
    )
    if encoded["input_ids"] != expected:
        raise ValueError("offset tokenization differs from the served template")
    indices = [i for i, (a, b) in enumerate(encoded["offset_mapping"])
               if a < b and a < end and b > first]
    if not indices:
        raise ValueError("focal evidence has no token span")
    return {
        "token_start": min(indices), "token_end_exclusive": max(indices) + 1,
        "start_fraction": min(indices) / len(expected),
        "end_fraction": (max(indices) + 1) / len(expected),
    }


def pack(task: dict, target: int, placement: str, tokenizer) -> dict:
    if target not in TARGETS or placement not in PLACEMENTS:
        raise ValueError("unregistered target or placement")
    lo, hi = 0, max(64, target // 20)
    while count(tokenizer, messages(task, hi, placement)) < target:
        hi *= 2
        if hi > 16384:
            raise ValueError("padding bound exceeded")
    if count(tokenizer, messages(task, 0, placement)) > target:
        raise ValueError("complete focal packet already exceeds target")
    while lo < hi:
        mid = (lo + hi) // 2
        if count(tokenizer, messages(task, mid, placement)) < target:
            lo = mid + 1
        else:
            hi = mid
    rendered = messages(task, lo, placement)
    actual = count(tokenizer, rendered)
    if not target <= actual <= target + 128:
        raise ValueError("actual token count outside declared band")
    return {
        "id": f"{task['id']}-c{target}-{placement}",
        "source_task_id": task["id"], "family": "context_evidence",
        "target_input_tokens": target, "actual_input_tokens": actual,
        "placement": placement, "distractor_count": lo,
        "placement_basis": "fraction_of_distractor_records",
        "observed_focal_token_position": focal_position(tokenizer, rendered, components(task)[1]),
        "max_output_tokens": OUTPUT_CAP,
        "minimum_server_context_tokens": actual + OUTPUT_CAP,
        "template_overhead_included": True,
        "messages": rendered, "messages_sha256": digest(canonical(rendered)),
        "grader": task["grader"],
        "focal_records_sha256": digest(canonical(components(task)[1])),
        "source_task_sha256": digest(canonical(task)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.source.read_bytes()
    if digest(raw) != SOURCE_SHA256:
        raise ValueError("source manifest drift")
    if digest((TOKENIZER_PATH / "chat_template.jinja").read_bytes()) != TEMPLATE_SHA256:
        raise ValueError("template drift")
    if args.output.exists():
        raise ValueError("refusing to overwrite an existing pack")
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(str(TOKENIZER_PATH), local_files_only=True)
    source = json.loads(raw)
    tasks = [pack(task, target, placement, tokenizer) for target in TARGETS
             for task in source["tasks"] for placement in PLACEMENTS]
    document = {
        "schema_version": "flash-context-pack-manifest/v2", "suite_id": SUITE_ID,
        "source_sha256": digest(raw), "builder_sha256": digest(Path(__file__).read_bytes()),
        "tokenizer_path": str(TOKENIZER_PATH), "template_sha256": TEMPLATE_SHA256,
        "thinking": "off", "temperature": 0.0, "top_p": 1.0,
        "tasks": tasks, "gpu_calls": 0, "endpoint_calls": 0,
        "limitations": ["public development evidence", "four evidence tasks only",
                         "placements are not independent task replicates",
                         "tokenizer-specific input counts; retokenize other model arms",
                         "explicit focal GT markers and repetitive synthetic distractors",
                         "not a realistic multi-paper synthesis benchmark",
                         "unsupported input plus output capacity is not_run, not a task failure"],
    }
    with args.output.open("x") as stream:
        json.dump(document, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    print(json.dumps({"path": str(args.output), "tasks": len(tasks),
                      "sha256": digest(args.output.read_bytes())}))


if __name__ == "__main__":
    main()
