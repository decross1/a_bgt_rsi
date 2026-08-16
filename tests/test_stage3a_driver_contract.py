"""The stage-3a battery driver must read keys the worker actually returns.

Why this test exists: on 2026-08-15 the Qwen 3.8 A/B window recorded
"liveness FAIL 22/22 — pin-amendment-class incompatibility" and BLOCKED the
upgrade. The driver was reading ``r["verdict"]`` and ``r["status"]``, keys
``novelty_skeptic.attack()`` has never returned, so the verdict was None on
every case for every model: liveness and kill FALSE by construction, and
no_false_kill TRUE by construction. A measuring instrument that cannot
produce a pass is not evidence about the thing being measured.

Hermetic: no model, no network — this is a contract test over the two
modules' shapes.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from orchestrator import novelty_skeptic as ns

DRIVER = Path(__file__).resolve().parent.parent / "bench" / "critic_eval" / "stage3a_driver.py"


def _attack_result_keys() -> set[str]:
    """The keys attack() really returns, read from _result's literal."""
    return set(ns._result("inconclusive", "r", None, "b", "m"))


def test_worker_result_is_the_contract_the_driver_must_read():
    keys = _attack_result_keys()
    assert "attack_verdict" in keys
    assert "verdict" not in keys, "a bare 'verdict' key would re-open the trap"
    assert "status" not in keys


def test_driver_never_reads_a_key_the_worker_does_not_return():
    """Every read of the attack RESULT (`res`) must name a real worker key.

    The result and the row dicts were both called `r` until 2026-08-16, which
    is how the mismatch hid in plain sight; the result is `res` now so this
    check can be exact."""
    tree = ast.parse(DRIVER.read_text())
    read: set[str] = set()
    for node in ast.walk(tree):
        # r.get("x")
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "res"
                and node.args and isinstance(node.args[0], ast.Constant)):
            read.add(node.args[0].value)
        # r["x"]
        if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
                and node.value.id == "res"
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)):
            read.add(node.slice.value)
    unknown = read - _attack_result_keys()
    assert not unknown, (
        f"stage3a_driver reads {sorted(unknown)} from the attack() result, "
        "which does not contain them — this is exactly the bug that produced "
        "the false 3.8 NO-CUTOVER verdict")


def test_verdict_helper_raises_instead_of_silently_returning_none():
    """A contract break must be LOUD. A silent None scores as 'unparseable',
    which is indistinguishable from a dead model (rule 4)."""
    src = DRIVER.read_text()
    assert "def _verdict_of(" in src
    ns_globals: dict = {}
    tree = ast.parse(src)
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "_verdict_of")
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<drv>", "exec"),
         ns_globals)
    verdict_of = ns_globals["_verdict_of"]
    assert verdict_of({"attack_verdict": "refuted"}) == "refuted"
    with pytest.raises(KeyError, match="attack_verdict"):
        verdict_of({"verdict": "refuted"})
