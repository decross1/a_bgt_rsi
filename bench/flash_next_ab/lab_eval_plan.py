"""Freeze a new role-policy evaluation without changing historical A/B sources."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from . import adapters, harness, manifest
from .followon_v5_parent import load_parent

ROOT = Path(__file__).resolve().parents[2]
RESEARCH = Path('/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-14/qwen-flash-next-research')
FLASH_PARENT = RESEARCH / 'evaluation/followon-qualified-parents/qfn-mia-mtp3-red47k-20260915-a.json'
RESIDENT_RECEIPT = RESEARCH / 'runtime/resident-qualification-v2.json'
RESIDENT_INVENTORY = RESEARCH / 'runtime/resident-model-artifacts.json'
SCHEMA = 'lab-model-eval-plan/v1'
SUITE = 'lab-role-policy-original126-development-20260915-v1'
COHORTS = ('resident', 'flash')
ENDPOINT_MODELS = {
    'resident_gemma': 'gemma-4-26b-a4b',
    'resident_qwen': 'qwen3.8-27b-nvfp4-mtp',
    'flash_next_mia': 'qwen3.8-flash-next-mia',
}
BUNDLE_FILES = (
    'bench/flash_next_ab/lab_eval_plan.py',
    'bench/flash_next_ab/lab_eval_runner.py',
    'bench/flash_next_ab/lab_eval_replay.py',
    'bench/flash_next_ab/adapters.py',
    'bench/flash_next_ab/harness.py',
    'bench/flash_next_ab/manifest.py',
    'bench/flash_next_ab/transport.py',
    'bench/flash_next_ab/private_evidence.py',
)
# Primary grading remains exact. Only this secondary audit may remove one whole
# Markdown code fence or append one missing terminal LF; no arbitrary repair.
PRESENTATION_DIAGNOSTIC = {
    'primary_grades_unchanged': True,
    'outer_fence_only': True,
    'append_one_missing_terminal_lf_for_diff_only': True,
    'sandbox_regrade_after_normalization': True,
    'normalized_scores_never_replace_primary': True,
}


class LabPlanError(ValueError):
    pass


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _source_bundle() -> dict[str, str]:
    return {name: manifest.sha256_file(ROOT / name) for name in BUNDLE_FILES}


def _policy(endpoint: str, logical: str) -> dict[str, Any]:
    bases = {
        # The unchanged role-effort adapter reads these original policy IDs to
        # distinguish a medium first call from an xhigh escalation.
        'critic_current': (.2, .95, 'xhigh'),
        'critic_medium': (.2, .95, 'medium'),
        'critic_xhigh': (.2, .95, 'xhigh'),
        'science_medium': (.2, .95, 'medium'),
        'execution_off': (.2, .95, None),
        'topic_hypothesis_off': (.7, .95, None),
        'topic_planner_off': (.1, .9, None),
        'context_off': (0.0, 1.0, None),
        'portfolio_coding_off': (.2, .95, None),
        'historical_coding_off': (.2, .9, None),
        'explore_medium': (1.0, .95, 'medium'),
        'deterministic_off': (0.0, 1.0, None),
    }
    if endpoint not in ENDPOINT_MODELS or logical not in bases:
        raise LabPlanError('endpoint or policy is not registered')
    temperature, top_p, effort = bases[logical]
    result: dict[str, Any] = {
        'temperature': temperature, 'top_p': top_p,
        'top_k': 64 if endpoint == 'resident_gemma' else 20,
        'enable_thinking': False if endpoint == 'resident_gemma' else effort is not None,
    }
    if endpoint != 'resident_gemma' and effort is not None:
        result['reasoning_effort'] = effort
    return result


def _policies(endpoint: str) -> dict[str, dict[str, Any]]:
    return {logical: _policy(endpoint, logical) for logical in (
        'critic_current', 'critic_medium', 'critic_xhigh', 'science_medium', 'execution_off',
        'topic_hypothesis_off', 'topic_planner_off', 'context_off',
        'portfolio_coding_off', 'historical_coding_off', 'explore_medium',
        'deterministic_off',
    )}


def _resident_endpoint(cell: adapters.CellDefinition, call: adapters.CallSpec) -> str:
    if (cell.family == 'objective' and call.role in {'critic', 'generator', 'evidence'}
        or cell.family == 'portfolio' and call.role in {'generator', 'evidence'}
        or cell.family == 'role_effort'):
        return 'resident_qwen'
    return 'resident_gemma'


def _new_policy_id(cell: adapters.CellDefinition, call: adapters.CallSpec) -> str:
    if cell.family == 'objective':
        if call.role == 'critic':
            return 'critic_xhigh' if call.policy_id == 'critic_current' else 'critic_medium'
        return 'execution_off' if call.role == 'execution' else 'science_medium'
    if cell.family == 'topic':
        return 'topic_hypothesis_off' if call.role == 'generator' else 'topic_planner_off'
    if cell.family == 'context':
        return 'context_off'
    if cell.family == 'portfolio':
        return 'portfolio_coding_off' if call.role == 'coding' else 'science_medium'
    if cell.family == 'diversity':
        return 'explore_medium' if call.policy_id == 'explore' else 'deterministic_off'
    if cell.family == 'role_effort':
        if call.policy_id not in {'critic_current', 'critic_medium'}:
            raise LabPlanError('role-effort source policy changed')
        return call.policy_id
    if cell.family == 'historical':
        return 'historical_coding_off'
    raise LabPlanError('unregistered task family')


def _new_budget(cell: adapters.CellDefinition, call: adapters.CallSpec) -> tuple[int, float]:
    if cell.family == 'objective':
        return 1024, 75.0
    if cell.family == 'topic':
        return 512, 25.0
    if cell.family == 'context':
        return 2048, 100.0
    if cell.family == 'portfolio':
        return (8192, 240.0) if call.role == 'coding' else (6144, 120.0)
    if cell.family == 'diversity':
        return (call.max_tokens, 60.0) if call.timeout_s == 80 else (call.max_tokens, call.timeout_s)
    if cell.family == 'role_effort':
        return call.max_tokens, call.timeout_s
    if cell.family == 'historical':
        return 8192, 240.0
    raise LabPlanError('unregistered task family')


def definitions() -> list[adapters.CellDefinition]:
    source = adapters.load_cells()
    if len(source) != 126 or sum(len(cell.calls) for cell in source) != 145:
        raise LabPlanError('original development cell registration changed')
    result = []
    for cell in source:
        calls = []
        for call in cell.calls:
            budget, timeout = _new_budget(cell, call)
            calls.append(dataclasses.replace(
                call, policy_id=_new_policy_id(cell, call),
                max_tokens=budget, timeout_s=timeout,
            ))
        result.append(dataclasses.replace(cell, calls=tuple(calls)))
    if len({cell.cell_id for cell in result}) != 126:
        raise LabPlanError('cell identity changed or duplicated')
    return result


def _certificates() -> tuple[dict[str, Any], dict[str, Any]]:
    resident = harness.validate_resident_qualification_files(
        RESIDENT_RECEIPT, RESIDENT_INVENTORY, require_passed=True,
    )
    flash = load_parent(FLASH_PARENT)
    if (flash.document['candidate_spec_id'] != 'mia-925d7be6-mtp3-reduced47k-v2opt-v1'
            or flash.document['max_model_len'] != 32768
            or flash.qualification_summary['admission_eligible'] is not True):
        raise LabPlanError('optimized Flash runtime certificate differs')
    refs = {
        'resident': {
            'receipt_path': str(RESIDENT_RECEIPT),
            'receipt_sha256': resident['qualification_receipt_sha256'],
            'inventory_path': str(RESIDENT_INVENTORY),
            'inventory_sha256': resident['artifact_inventory_sha256'],
            'probe_scope': resident['probe_scope'],
        },
        'flash': {
            'parent_path': str(FLASH_PARENT),
            'parent_sha256': flash.source_sha256,
            'qualification_receipt_sha256': flash.document['qualification_receipt_sha256'],
            'candidate_spec_id': flash.document['candidate_spec_id'],
            'candidate_spec_sha256': flash.document['candidate_spec_sha256'],
            'max_model_len': flash.document['max_model_len'],
            'mtp_speculative_tokens': flash.document['mtp_speculative_tokens'],
        },
    }
    identity = {
        'resident_gemma': {
            'served_model': ENDPOINT_MODELS['resident_gemma'],
            'artifact_sha256': resident['artifact_sha256_by_endpoint']['resident_gemma'],
            'runtime_sha256': resident['runtime_sha256_by_endpoint']['resident_gemma'],
            'max_model_len': 32768,
        },
        'resident_qwen': {
            'served_model': ENDPOINT_MODELS['resident_qwen'],
            'artifact_sha256': resident['artifact_sha256_by_endpoint']['resident_qwen'],
            'runtime_sha256': resident['runtime_sha256_by_endpoint']['resident_qwen'],
            'max_model_len': 16384,
        },
        'flash_next_mia': {
            'served_model': ENDPOINT_MODELS['flash_next_mia'],
            'artifact_sha256': flash.document['model_artifact_sha256'],
            'runtime_sha256': flash.document['runtime_sha256'],
            'max_model_len': flash.document['max_model_len'],
        },
    }
    return refs, identity


def build_plan() -> tuple[dict[str, Any], dict[str, adapters.CellDefinition]]:
    refs, identities = _certificates()
    cells = definitions()
    declared = [cell.cell_id for cell in cells]
    call_routes = {
        'resident': {
            cell.cell_id: [_resident_endpoint(cell, call) for call in cell.calls]
            for cell in cells
        },
        'flash': {
            cell.cell_id: ['flash_next_mia'] * len(cell.calls)
            for cell in cells
        },
    }
    endpoints = {
        name: {**identity, 'policies': _policies(name)}
        for name, identity in identities.items()
    }
    plan = {
        'schema_version': SCHEMA, 'suite_id': SUITE,
        'cell_set': 'reused_original126_development',
        'cohorts': list(COHORTS),
        'runtime_certificates': refs,
        'endpoints': endpoints,
        'call_routes': call_routes,
        'declared_cells': declared,
        'cell_receipts': {cell.cell_id: cell.receipt() for cell in cells},
        'evaluator_source_bundle': _source_bundle(),
        'presentation_diagnostic': PRESENTATION_DIAGNOSTIC,
        'hard_call_ceiling_s': sum(call.timeout_s for cell in cells for call in cell.calls),
        'promotion_authorized': False,
        'limitations': [
            'All 126 source tasks are reused public development fixtures; no held-out confirmation.',
            'This compares two deployable model/policy/runtime bundles, not weights alone.',
            'Gemma has no Qwen reasoning-effort control and uses explicit thinking off.',
            'Resident science/evidence and all role-effort arms use Qwen; topic, coding, objective tools and context use Gemma.',
            'Role-effort retains original medium/xhigh policy IDs so the unchanged adaptive adapter can escalate correctly.',
            'Original primary grades and manifests remain immutable; normalization is secondary only.',
        ],
    }
    if abs(plan['hard_call_ceiling_s'] - 9740.0) > 1e-6:
        raise LabPlanError('registered worst call ceiling changed')
    return plan, {cell.cell_id: cell for cell in cells}


def validate_plan(plan: Any) -> dict[str, adapters.CellDefinition]:
    expected, cells = build_plan()
    if not isinstance(plan, dict) or plan != expected:
        raise LabPlanError('plan differs from code-owned tasks, policies, certificates or source')
    for cohort in COHORTS:
        for cell_id in plan['declared_cells']:
            cell = cells[cell_id]
            names = plan['call_routes'][cohort][cell_id]
            if len(names) != len(cell.calls):
                raise LabPlanError('call-route count differs')
            for call, name in zip(cell.calls, names, strict=True):
                if (name not in plan['endpoints']
                    or call.policy_id not in plan['endpoints'][name]['policies']
                    or plan['endpoints'][name]['served_model'] != ENDPOINT_MODELS[name]):
                    raise LabPlanError('call route or effective policy differs')
    return cells


def freeze_plan(path: str | Path) -> dict[str, Any]:
    target = Path(path).absolute()
    if target.exists() or not target.parent.is_dir() or target.parent.is_symlink():
        raise LabPlanError('plan must be a new regular direct child')
    plan, _ = build_plan()
    raw = manifest.canonical_json(plan) + b'\n'
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_CLOEXEC', 0), 0o600)
    try:
        with os.fdopen(fd, 'wb', closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(fd)
    return {'path': str(target), 'raw_sha256': _sha(raw),
            'plan_sha256': manifest.sha256_json(plan),
            'declared_cells': len(plan['declared_cells']),
            'hard_call_ceiling_s': plan['hard_call_ceiling_s']}


def load_plan(path: str | Path) -> tuple[dict[str, Any], dict[str, adapters.CellDefinition], str]:
    raw, _actual = harness._read_regular_file(path, label='lab evaluation frozen plan', max_bytes=4_000_000)
    try:
        plan = harness._strict_object(raw, 'lab evaluation frozen plan')
    except (ValueError, TypeError) as exc:
        raise LabPlanError('plan is malformed') from exc
    cells = validate_plan(plan)
    return plan, cells, _sha(raw)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze-plan', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(freeze_plan(args.freeze_plan), sort_keys=True))
