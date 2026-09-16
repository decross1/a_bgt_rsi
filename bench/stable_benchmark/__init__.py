"""Versioned, replayable benchmark program for local model stacks.

Exports are lazy so UI/projection changes do not enter the causal execution
source bundle merely by importing the package.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS = {
    "LoadedDocument": ("manifest", "LoadedDocument"),
    "admit_replay": ("admission", "admit_replay"),
    "bind_run_manifest": ("manifest", "bind_run_manifest"),
    "compare_admitted": ("comparison", "compare_admitted"),
    "load_admission_receipt": ("admission", "load_admission_receipt"),
    "load_definition": ("manifest", "load_definition"),
    "load_run_manifest": ("manifest", "load_run_manifest"),
    "load_run_receipt": ("replay", "load_run_receipt"),
    "make_draft": ("manifest", "make_draft"),
    "program_projection": ("projection", "program_projection"),
    "publish_definition": ("manifest", "publish_definition"),
    "replay_run": ("replay", "replay_run"),
    "run_arm": ("runner", "run_arm"),
    "write_unissued_receipt": ("runner", "write_unissued_receipt"),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(f"{__name__}.{module_name}"), attribute)
    globals()[name] = value
    return value


__all__ = sorted(_EXPORTS)
