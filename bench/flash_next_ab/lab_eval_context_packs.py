"""Build matched, CPU-tokenized context packets within qualified TOTAL capacity.

Every arm receives byte-identical messages. This is public development evidence;
the 32K lane means a 32,768-token server limit with 2,048 output reserved.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from . import followon_context_packs as original
from . import harness, manifest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'experiments/weekly_context_capability_v1_2026-09-14.json'
SOURCE_SHA256 = '7a65db923631d01c296ba8e65e924e646c9134082bb2a600c099eeb66eb6f735'
SCHEMA = 'lab-context-capacity-packets/v1'
CAPACITIES = (8192, 16384, 32768)
INPUT_TARGET = {8192: 6000, 16384: 14000, 32768: 30000}
OUTPUT_RESERVE = 2048
PLACEMENTS = ('early', 'middle', 'late')
MODELS = {
    'resident_gemma': ('/mnt/models/gemma-4-26b-a4b-nvfp4',
                       '94899c0f917d93f6fe81c95744d1e8ddab2d21d39228d2e4aec1fb2a25bff413'),
    'resident_qwen': ('/mnt/models/qwen3.8-27b-nvfp4-mtp',
                      'c3cf9e34abf4f9e36c2d72165aa9c132d3e2a725b6c2586aaa3a8af9d7a81041'),
    'flash_next_mia': ('/mnt/models/qwen3.8-flash-next-mia-925d7be6',
                       'c3cf9e34abf4f9e36c2d72165aa9c132d3e2a725b6c2586aaa3a8af9d7a81041'),
}


class ContextPackError(ValueError):
    pass


def _source() -> list[dict[str, Any]]:
    raw, actual = harness._read_regular_file(
        SOURCE, label='registered context development source', max_bytes=2_000_000,
    )
    if actual != SOURCE.absolute() or hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ContextPackError('registered context development source changed')
    value = harness._strict_object(raw, 'context development source')
    tasks = value.get('tasks')
    if (not isinstance(tasks, list) or len(tasks) != 4
            or len({task.get('id') for task in tasks if isinstance(task, dict)}) != 4):
        raise ContextPackError('four objective evidence tasks are required')
    for task in tasks:
        original.components(task)
        if task['grader']['kind'] != 'evidence_attribution':
            raise ContextPackError('objective citation grader changed')
    return tasks


def _tokenizers() -> tuple[dict, dict]:
    from transformers import AutoTokenizer  # CPU-only, after source admission

    identities, loaded = {}, {}
    for name, (directory, expected_template) in MODELS.items():
        model = Path(directory)
        files = {}
        for leaf in ('chat_template.jinja', 'tokenizer.json', 'tokenizer_config.json'):
            raw, actual = harness._read_regular_file(
                model / leaf, label=f'{name} tokenizer {leaf}', max_bytes=40_000_000,
            )
            if actual != (model / leaf).absolute():
                raise ContextPackError('registered tokenizer path redirected')
            files[leaf] = hashlib.sha256(raw).hexdigest()
        if files['chat_template.jinja'] != expected_template:
            raise ContextPackError(f'{name} chat template changed')
        identities[name] = {'tokenizer_path': directory, 'file_sha256': files}
        loaded[name] = AutoTokenizer.from_pretrained(directory, local_files_only=True)
    return identities, loaded


def _noise_count(task: dict, cap: int, placement: str, tokenizers: dict) -> int:
    """Choose one packet using the Mia tokenizer, then check every supported arm."""
    target = INPUT_TARGET[cap]
    mia = tokenizers['flash_next_mia']
    lo, hi = 0, max(64, target // 20)
    if original.count(mia, original.messages(task, 0, placement)) > target:
        raise ContextPackError('complete focal packet exceeds input target')
    while original.count(mia, original.messages(task, hi, placement)) < target:
        hi *= 2
        if hi > 1024:
            raise ContextPackError('synthetic distractor bound exceeded')
    while lo < hi:
        mid = (lo + hi) // 2
        if original.count(mia, original.messages(task, mid, placement)) < target:
            lo = mid + 1
        else:
            hi = mid
    chosen = lo
    supported = ('resident_gemma', 'flash_next_mia')
    if cap < 32768:
        supported += ('resident_qwen',)
    for name in supported:
        actual = original.count(tokenizers[name], original.messages(task, chosen, placement))
        if actual + OUTPUT_RESERVE > cap:
            raise ContextPackError(f'{name} packet exceeds qualified {cap}-token server')
    return chosen


def build_packets(tokenizers: dict, identities: dict) -> dict[str, Any]:
    tasks = _source()
    rows = []
    for cap in CAPACITIES:
        for task in tasks:
            for placement in PLACEMENTS:
                noise = _noise_count(task, cap, placement, tokenizers)
                messages = original.messages(task, noise, placement)
                counts = {
                    name: original.count(tokenizer, messages)
                    for name, tokenizer in tokenizers.items()
                }
                supported = ['resident_gemma', 'flash_next_mia']
                if cap < 32768:
                    supported.append('resident_qwen')
                if any(counts[name] + OUTPUT_RESERVE > cap for name in supported):
                    raise ContextPackError('reserved output no longer fits qualified server')
                rows.append({
                    'cell_id': f"{task['id']}-total{cap}-{placement}",
                    'source_task_id': task['id'], 'server_context_tokens': cap,
                    'input_target_tokens': INPUT_TARGET[cap],
                    'output_reserve_tokens': OUTPUT_RESERVE,
                    'placement': placement, 'distractor_count': noise,
                    'supported_endpoints': supported,
                    'actual_prompt_tokens_by_endpoint': counts,
                    'messages': messages,
                    'messages_sha256': manifest.sha256_json(messages),
                    'grader': task['grader'],
                    'grader_sha256': manifest.sha256_json(task['grader']),
                    'focal_records_sha256': manifest.sha256_json(original.components(task)[1]),
                    'source_task_sha256': manifest.sha256_json(task),
                })
    if len(rows) != 36 or len({row['cell_id'] for row in rows}) != 36:
        raise ContextPackError('matched context matrix is incomplete')
    return {
        'schema_version': SCHEMA,
        'source_manifest_sha256': SOURCE_SHA256,
        'builder_source_sha256': manifest.sha256_file(__file__),
        'helper_source_sha256': manifest.sha256_file(original.__file__),
        'tokenizers': identities,
        'input_target_by_total_capacity': INPUT_TARGET,
        'output_reserve_tokens': OUTPUT_RESERVE,
        'cells': rows,
        'endpoint_calls': 0,
        'limitations': [
            'All four evidence tasks are public development fixtures.',
            'The 32K lane is 30K input plus 2K output, not 32K input.',
            'Synthetic distractors and placements are not independent questions.',
            'Retokenization is per arm; message content is identical across arms.',
            'Qwen resident 32K is not supported by its qualified 16K server.',
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists() or args.output.parent.is_symlink():
        parser.error('output already exists or parent is redirected')
    identities, tokenizers = _tokenizers()
    document = build_packets(tokenizers, identities)
    with args.output.open('xb') as handle:
        handle.write(manifest.canonical_json(document) + b'\n')
    print(json.dumps({'cells': len(document['cells']),
                      'raw_sha256': manifest.sha256_file(args.output)}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
