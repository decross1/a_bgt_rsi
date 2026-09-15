"""Independently replay frozen lab grades from private raw local streams."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from . import adapters, harness, manifest
from .lab_eval_plan import load_plan
from .lab_eval_runner import _admission
from .private_evidence import validate_private_evidence

SCHEMA = 'lab-model-eval-grade-replay/v1'
FENCE = re.compile(r'\A```(?:diff|patch|text)?\n(.*)\n```\n?\Z', re.DOTALL)


class ReplayError(ValueError):
    pass


def _normalized_diff(content: str) -> tuple[str, list[str]]:
    changes = []
    match = FENCE.fullmatch(content)
    if match:
        content = match.group(1)
        changes.append('whole_outer_code_fence_removed')
    if content.startswith('diff --git ') and not content.endswith('\n'):
        content += '\n'
        changes.append('one_missing_terminal_lf_appended')
    return content, changes


def _private_calls(outcome: dict, output: Path) -> list[dict]:
    details = outcome['grade']['details']
    private = details['_private_call_evidence']['artifacts']
    result = []
    for call, descriptor in zip(outcome['calls'], private, strict=True):
        raw, actual = harness._read_regular_file(
            output / descriptor['metadata_path'],
            label='replay private call metadata',
            max_bytes=harness.MAX_PRIVATE_METADATA_BYTES,
        )
        if (actual != (output / descriptor['metadata_path']).absolute()
                or len(raw) != descriptor['metadata_bytes']
                or manifest.sha256_file(actual) != descriptor['metadata_sha256']):
            raise ReplayError('private metadata source changed during grade replay')
        metadata = harness._strict_object(raw, 'replay private metadata')
        if (metadata['call_id'] != call['call_id']
                or metadata['status'] != call['status']):
            raise ReplayError('private/public call identity differs')
        result.append(metadata)
    return result


def _is_coding(cell: adapters.CellDefinition) -> bool:
    return (cell.family == 'historical'
            or cell.family == 'portfolio' and any(call.role == 'coding' for call in cell.calls))


def _grade(
    cell: adapters.CellDefinition,
    outcome: dict,
    metadata: list[dict],
    *,
    plan: dict,
    cohort: str,
    normalize_diff: bool,
) -> tuple[adapters.AdapterResult, list[str]]:
    recorded = iter(zip(outcome['calls'], metadata, strict=True))
    transformations: list[str] = []

    def invoke(spec: adapters.CallSpec) -> adapters.CallResult:
        try:
            call, private = next(recorded)
        except StopIteration as exc:
            raise ReplayError('grader issued a call absent from the recorded prefix') from exc
        request = private['request']
        endpoint_name = plan['call_routes'][cohort][cell.cell_id][spec.call_index]
        endpoint = plan['endpoints'][endpoint_name]
        if (spec.call_id != call['call_id']
                or spec.call_index != call['call_index']
                or spec.role != call['role']
                or spec.policy_id != call['policy_id']
                or spec.seed != call['seed']
                or spec.max_tokens != call['max_tokens']
                or manifest.sha256_json(list(spec.messages or ())) != call['messages_sha256']
                or manifest.sha256_json(list(spec.tools)) != call['tools_sha256']
                or request['request_sha256'] != call['request_sha256']
                or call['endpoint_name'] != endpoint_name
                or call['served_model'] != endpoint['served_model']
                or call['artifact_sha256'] != endpoint['artifact_sha256']
                or request['resolved_policy'] != endpoint['policies'][spec.policy_id]):
            raise ReplayError('grader call differs from recorded source or policy')
        response = private['response']
        content = response['content'] if call['status'] == 'returned' else None
        if normalize_diff and isinstance(content, str):
            content, changes = _normalized_diff(content)
            transformations.extend(changes)
        return adapters.CallResult(
            spec, call['status'], content,
            tuple(response['tool_calls']), call,
        )

    graded = adapters.execute_cell(cell, invoke)
    if next(recorded, None) is not None:
        raise ReplayError('recorded calls were not consumed by unchanged grader')
    return graded, transformations


def replay_run(plan_path: str | Path, run_path: str | Path) -> dict[str, Any]:
    plan, definitions, plan_raw_sha = load_plan(plan_path)
    raw, actual = harness._read_regular_file(run_path, label='lab evaluation run', max_bytes=16_000_000)
    run = harness._strict_object(raw, 'lab evaluation run')
    if (run.get('schema_version') != 'lab-model-eval-run/v1'
            or run.get('status') != 'complete'
            or run.get('plan_raw_sha256') != plan_raw_sha
            or run.get('plan_sha256') != manifest.sha256_json(plan)
            or run.get('declared_cells') != plan['declared_cells']
            or run.get('runtime_certificate') != plan['runtime_certificates'].get(run.get('cohort'))
            or run.get('evaluator_source_bundle') != plan['evaluator_source_bundle']
            or run.get('promotion_authorized') is not False
            or len(run.get('outcomes', [])) != 126):
        raise ReplayError('only a complete, exact-source original126 run can be replayed')
    _admission(plan, run['cohort'], run.get('controller_admission'))
    if [row.get('cell_id') for row in run['outcomes']] != plan['declared_cells']:
        raise ReplayError('ordered 126-cell denominator differs from frozen plan')
    output = actual.parent
    evidence = validate_private_evidence(run, output)
    mismatches = []
    replayed = 0
    normalized_attempted = 0
    normalized_passes = 0
    normalized_changes: dict[str, int] = {}
    for outcome in run['outcomes']:
        cell_id = outcome['cell_id']
        cell = definitions[cell_id]
        if (outcome['source'] != cell.source
                or outcome['adapter'] != cell.adapter
                or outcome['grader'] != cell.grader
                or outcome['cohort'] != run['cohort']):
            raise ReplayError('outcome source/grader/arm identity differs')
        metadata = _private_calls(outcome, output)
        try:
            graded, _ = _grade(
                cell, outcome, metadata, plan=plan,
                cohort=run['cohort'], normalize_diff=False,
            )
        except Exception as exc:  # noqa: BLE001 - replay mismatches remain visible
            mismatches.append({'cell_id': cell_id, 'kind': type(exc).__name__})
        else:
            replayed += 1
            expected_pass = bool(graded.passed and outcome['status'] == 'returned')
            expected_code = None if expected_pass else (graded.failure_code or f"outcome_{outcome['status']}")
            if expected_pass != outcome['passed'] or expected_code != outcome['failure_code']:
                mismatches.append({'cell_id': cell_id, 'kind': 'grade_difference'})
        if _is_coding(cell) and outcome['status'] == 'returned':
            normalized_attempted += 1
            try:
                normalized, changes = _grade(
                    cell, outcome, metadata, plan=plan,
                    cohort=run['cohort'], normalize_diff=True,
                )
            except Exception as exc:  # noqa: BLE001 - diagnostic cannot rescue unknown
                mismatches.append({'cell_id': cell_id, 'kind': f'normalization_{type(exc).__name__}'})
            else:
                normalized_passes += int(normalized.passed)
                for change in changes:
                    normalized_changes[change] = normalized_changes.get(change, 0) + 1
    result = {
        'schema_version': SCHEMA,
        'run_id': run['run_id'], 'cohort': run['cohort'],
        'run_raw_sha256': manifest.sha256_file(actual),
        'plan_raw_sha256': plan_raw_sha,
        'private_calls_verified': evidence['calls_verified'],
        'private_streams_verified': evidence['response_streams_verified'],
        'primary_cells_replayed': replayed,
        'primary_grade_mismatches': mismatches,
        'primary_replay_passed': replayed == 126 and not mismatches,
        'normalization_diagnostic': {
            'coding_returned_attempted': normalized_attempted,
            'sandbox_passes_after_exact_predeclared_transform': normalized_passes,
            'transform_counts': normalized_changes,
            'never_replaces_primary_score': True,
        },
        'private_content_exported': False,
        'promotion_authorized': False,
    }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error('replay output exists')
    value = replay_run(args.plan, args.run)
    args.output.write_bytes(manifest.canonical_json(value) + b'\n')
    print(json.dumps({'replay_passed': value['primary_replay_passed'],
                      'mismatches': len(value['primary_grade_mismatches'])}))
    return 0 if value['primary_replay_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
