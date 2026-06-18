"""Runtime skill-friction signal emitter — the apparatus side of the
skill-signals stream (D-056; docs/skill_signals_contract.md).

A best-effort, non-blocking append to run_state/skill_signals.jsonl the moment an
agent hits friction with a framework skill. The framework reads this file
READ-ONLY on its own pass. This module NEVER reads/writes/imports the brain,
never calls a framework script, never reads a framework registry (D-014 /
CLAUDE.md Dynamic-Workflow-discipline rule 3). The ONLY thing it touches is
run_state/skill_signals.jsonl.

Self-standing (verified): this module's correctness depends on NOTHING in the
framework. Even if the framework never ingests the file, the worst case is a row
no one reads downstream — it can never make us write a bad file or violate a rule.

Phasing (D-056): the call sites that emit (b) GAP and (c) MISUSE ship first;
(a) FRICTION (form (i) — genuine run-log-skill misfit only) is added later. This
helper accepts the full signal_class enum so (a) needs no schema change.
"""
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Module-global target, resolved at CALL time. D-048: tests/conftest.py
# monkeypatches this to tmp_path so a full pytest run adds ZERO live rows.
SKILL_SIGNALS_PATH = REPO_ROOT / "run_state" / "skill_signals.jsonl"

SIGNAL_CLASSES = ("friction", "misuse", "gap")
SEVERITIES = ("low", "med", "high")

# In-repo skill-name constant: CLAUDE.md rule 3 skill_subset + the framework-skill
# examples named there. NON-DROPPING (see below) — never a framework registry read.
KNOWN_SKILLS = ("run-log", "validate", "fallback", "resume-state",
                "gate-check", "brain-recall")


def _utcnow_iso() -> str:
    return (datetime.datetime.now(datetime.timezone.utc)
            .isoformat(timespec="seconds").replace("+00:00", "Z"))


def emit_skill_signal(*, agent: str, skill: str, signal_class: str,
                      severity: str, evidence: str, task_id: str,
                      invocation_ref: str | None = None,
                      expected: str | None = None,
                      actual: str | None = None,
                      suggested_fix: str | None = None,
                      path=None) -> bool:
    """Append ONE skill-signal row to run_state/skill_signals.jsonl (or `path`).

    Best-effort and NON-BLOCKING (rule 7): any failure is swallowed with a stderr
    breadcrumb so a lost signal never stalls the task. This helper NEVER writes the
    mandatory run-log row — that is the caller's responsibility, written FIRST and
    unconditionally (rule 6); the skill-signal is supplementary.

    `signal_class` must be in SIGNAL_CLASSES and `severity` in SEVERITIES — rejected,
    not coerced (rule 4); an out-of-enum value is a caller error and is swallowed.
    `skill` is recorded verbatim; if it is not in KNOWN_SKILLS the row STILL emits
    with `skill_known: false` (NON-DROPPING — a framework rename can never cause
    apparatus-side data loss; we never read a framework registry, D-014). Do NOT
    pass `_source` — the framework adds it. Returns True on append, False on swallow.
    """
    try:
        if signal_class not in SIGNAL_CLASSES:
            raise ValueError(f"signal_class must be one of {SIGNAL_CLASSES}")
        if severity not in SEVERITIES:
            raise ValueError(f"severity must be one of {SEVERITIES}")
        if not (isinstance(skill, str) and skill.strip()):
            raise ValueError("skill must be a non-empty string")
        if not (isinstance(task_id, str) and task_id.strip()):
            raise ValueError("task_id must be a non-empty string")

        row = {
            "timestamp": _utcnow_iso(),
            "agent": agent,
            "skill": skill,
            "signal_class": signal_class,
            "severity": severity,
            "evidence": evidence,
            "task_id": task_id,
        }
        if skill not in KNOWN_SKILLS:
            row["skill_known"] = False  # advisory; NON-DROPPING (row still emits)
        for key, val in (("invocation_ref", invocation_ref),
                         ("expected", expected), ("actual", actual),
                         ("suggested_fix", suggested_fix)):
            if val is not None:
                row[key] = val

        target = Path(path) if path is not None else SKILL_SIGNALS_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        return True
    except Exception as exc:  # rule 7: swallow ONLY this side-channel, never the task
        print(f"[skill_signal_emit_failed] {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return False
