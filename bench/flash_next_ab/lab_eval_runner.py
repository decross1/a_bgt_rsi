"""Execute a separately frozen original-126 policy rerun under a controller gate."""
from __future__ import annotations

import argparse
import copy
import math
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import harness, manifest, transport
from .lab_eval_plan import COHORTS, load_plan

SCHEMA = 'lab-model-eval-run/v1'
MAX_BUDGET_S = 10_430.0


class LabRunError(RuntimeError):
    pass


def _admission(plan: dict[str, Any], cohort: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LabRunError('controller admission receipt is absent')
    expected_names = {
        name for routes in plan['call_routes'][cohort].values() for name in routes
    }
    expected_identity = {
        name: {
            key: plan['endpoints'][name][key]
            for key in ('served_model', 'artifact_sha256', 'runtime_sha256')
        }
        for name in expected_names
    }
    certificate = plan['runtime_certificates'][cohort]
    expected_certificate_sha = (
        certificate['parent_sha256'] if cohort == 'flash'
        else certificate['receipt_sha256']
    )
    spec_sha = (
        certificate['candidate_spec_sha256'] if cohort == 'flash' else None
    )
    if (
        value.get('schema_version') != 'lab-model-eval-admission/v1'
        or value.get('admitted') is not True
        or value.get('cohort') != cohort
        or value.get('plan_sha256') != manifest.sha256_json(plan)
        or value.get('certificate_sha256') != expected_certificate_sha
        or value.get('endpoint_identities') != expected_identity
        or value.get('candidate_spec_sha256') != spec_sha
        or value.get('monitor_armed') is not True
        or not isinstance(value.get('window_id'), str)
        or not value['window_id']
        or any(
            not isinstance(value.get(key), str)
            or len(value[key]) != 64
            or any(char not in '0123456789abcdef' for char in value[key])
            for key in ('controller_source_bundle_sha256', 'ready_proof_sha256')
        )
    ):
        raise LabRunError('controller admission differs from frozen model/runtime plan')
    return copy.deepcopy(value)


def _arm_for_cell(plan: dict[str, Any], cohort: str, cell_id: str,
                  cell: Any) -> dict[str, Any]:
    by_role: dict[str, str] = {}
    for call, endpoint in zip(cell.calls, plan['call_routes'][cohort][cell_id], strict=True):
        existing = by_role.setdefault(call.role, endpoint)
        if existing != endpoint:
            raise LabRunError('one cell changed endpoints within a role')
    routes = []
    for role, name in by_role.items():
        identity = plan['endpoints'][name]
        routes.append({
            'role': role,
            'endpoint_name': name,
            'served_model': identity['served_model'],
            'artifact_sha256': identity['artifact_sha256'],
            'runtime_sha256': identity['runtime_sha256'],
            'policies': identity['policies'],
        })
    return {'cohort': cohort, 'routes': routes}


def run(
    plan_path: str | Path,
    *,
    cohort: str,
    output_dir: str | Path,
    runtime_budget_s: float,
    admission_gate: Callable[[dict[str, Any], str], Any],
    cancel_event: Any,
    invoke_fn: Callable = transport.complete,
    monotonic: Callable[[], float] = time.monotonic,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Keep every declared task in the denominator, including unissued cells.

    The controller owns service mutation, real-time safety and exact restore.
    This function invokes no endpoint until the certificate/live gate passes.
    """
    if cohort not in COHORTS or not callable(admission_gate):
        raise LabRunError('cohort and admission gate must be registered')
    if cancel_event is None or not callable(getattr(cancel_event, 'is_set', None)):
        raise LabRunError('an armed controller cancel event is required')
    if not callable(invoke_fn):
        raise LabRunError('invoke function is not callable')
    if (isinstance(runtime_budget_s, bool) or not isinstance(runtime_budget_s, (float, int))
            or not math.isfinite(runtime_budget_s) or not 0 < runtime_budget_s <= MAX_BUDGET_S):
        raise LabRunError('runtime budget is outside bounded range')
    plan, cells, raw_sha = load_plan(plan_path)
    # The live controller rechecks actual container IDs, endpoint readiness and
    # safety monitor. The historical certificate is rehashed in load_plan.
    gate = _admission(plan, cohort, admission_gate(plan, cohort))
    if cancel_event.is_set():
        raise LabRunError('controller cancelled before output creation')
    output = harness._output_dir(output_dir)
    if output.parent.is_symlink() or not output.parent.is_dir():
        raise LabRunError('run output parent is absent or redirected')
    output.mkdir(mode=0o700)
    run_id = run_id or f'lab-eval-{cohort}-{uuid.uuid4().hex[:16]}'
    if not isinstance(run_id, str) or not run_id:
        raise LabRunError('run ID is invalid')
    start = monotonic()
    deadline = start + float(runtime_budget_s)
    outcomes: list[dict[str, Any]] = []
    stopped = False
    evidence_ordinal = 0

    def persist_evidence(cell: Any, evidence: dict[str, Any]) -> dict[str, Any]:
        nonlocal evidence_ordinal
        complete = {
            'schema_version': evidence.pop('schema_version'),
            'run_id': run_id, 'cohort': cohort,
            'cell_id': cell.cell_id, **evidence,
        }
        descriptor = harness._persist_private_call(
            output, ordinal=evidence_ordinal, evidence=complete,
        )
        evidence_ordinal += 1
        return descriptor

    def checkpoint() -> None:
        harness._write_json(output / 'checkpoint.json', {
            'schema_version': 'lab-model-eval-checkpoint/v1',
            'run_id': run_id, 'cohort': cohort,
            'plan_raw_sha256': raw_sha,
            'recorded_cells': [row['cell_id'] for row in outcomes],
            'elapsed_s': max(0.0, monotonic() - start),
            'promotion_authorized': False,
        })

    checkpoint()
    for cell_id in plan['declared_cells']:
        cell = cells[cell_id]
        cancelled = bool(cancel_event.is_set())
        if stopped or cancelled or monotonic() >= deadline:
            stopped = True
            reason = 'controller_cancelled' if cancelled else 'runtime_budget_exhausted'
            outcomes.append(harness._not_run_outcome(
                cell, cohort, failure_code=reason, error=reason,
            ))
            checkpoint()
            continue
        arm = _arm_for_cell(plan, cohort, cell_id, cell)
        row = harness._execute_outcome(
            cell, cohort, arm=arm, deadline=deadline,
            invoke_fn=invoke_fn, cancel_event=cancel_event,
            monotonic=monotonic, persist_evidence=persist_evidence,
        )
        outcomes.append(row)
        if row['status'] == 'cancelled':
            stopped = True
        checkpoint()
    status = ('aborted' if stopped or cancel_event.is_set()
              or any(row['status'] == 'not_run' for row in outcomes) else 'complete')
    prompt_tokens_by_endpoint: dict[str, list[int]] = {}
    for row in outcomes:
        for call in row['calls']:
            usage = call.get('usage')
            if (isinstance(usage, dict)
                    and type(usage.get('prompt_tokens')) is int
                    and usage['prompt_tokens'] >= 0):
                prompt_tokens_by_endpoint.setdefault(
                    call['endpoint_name'], [],
                ).append(usage['prompt_tokens'])
    prompt_tokens = [token for values in prompt_tokens_by_endpoint.values()
                     for token in values]
    result = {
        'schema_version': SCHEMA, 'run_id': run_id,
        'cohort': cohort, 'status': status,
        'suite_id': plan['suite_id'], 'cell_set': plan['cell_set'],
        'plan_raw_sha256': raw_sha,
        'plan_sha256': manifest.sha256_json(plan),
        'evaluator_source_bundle': copy.deepcopy(plan['evaluator_source_bundle']),
        'runtime_certificate': copy.deepcopy(plan['runtime_certificates'][cohort]),
        'controller_admission': gate,
        'candidate_variant_id': (
            plan['runtime_certificates']['flash']['candidate_spec_id']
            if cohort == 'flash' else 'resident-role-bundle'),
        'configured_context_tokens_by_endpoint': {
            name: row['max_model_len'] for name, row in plan['endpoints'].items()
            if name.startswith('resident_') == (cohort == 'resident')
        },
        'measured_prompt_tokens_max': max(prompt_tokens) if prompt_tokens else None,
        'measured_prompt_tokens_max_by_endpoint': {
            name: max(prompt_tokens_by_endpoint[name]) if name in prompt_tokens_by_endpoint else None
            for name in plan['endpoints']
            if name in {route for routes in plan['call_routes'][cohort].values()
                        for route in routes}
        },
        'runtime_budget_s': float(runtime_budget_s),
        'elapsed_s': max(0.0, monotonic() - start),
        'declared_cells': list(plan['declared_cells']),
        'outcomes': outcomes,
        'promotion_authorized': False,
    }
    harness._write_json(output / 'run.json', result)
    (output / 'checkpoint.json').unlink(missing_ok=True)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--cohort', choices=COHORTS, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--runtime-budget-s', type=float, required=True)
    parser.parse_args(argv)
    # Live CLI is deliberately controller-only: importing this module cannot
    # manufacture an admission gate or silently call a model.
    parser.error('invoke lab_eval_runner.run from the supervised lab window')
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
