"""Bounded, paired evaluation harness for inference-policy trials.

The package deliberately has no import-time connection to a model server.
Use :mod:`bench.weekly_upgrade_eval.runner` to inspect or execute a frozen
manifest.
"""

from .manifest import DEFAULT_MANIFEST_PATH, ManifestError, load_manifest

__all__ = ["DEFAULT_MANIFEST_PATH", "ManifestError", "load_manifest"]
