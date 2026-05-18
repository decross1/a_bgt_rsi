"""Pytest bootstrap: put ui/ on sys.path so `import sampler...` resolves.

Keeps the UI layer self-contained under ui/ -- no repo-root package files.
Run the tests from the repo root: `pytest ui/sampler/tests`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
