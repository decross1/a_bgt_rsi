"""Unit tests for experiments/exp004_combinatorial_auction/mechanisms/vcg.py.

Pure-Python, MOCK_LLM-safe, fully seeded. No LLM dependency.

The VCG mechanism module imports ``feasible_allocations`` and
``allocation_welfare`` from the sibling ``bundles`` module (a parallel
exp004 component). To keep THIS test self-contained and green regardless
of that parallel component's build state, we install a contract-faithful
stand-in ``bundles`` module into ``sys.modules`` BEFORE importing ``vcg``.
The stand-in implements exactly the frozen exp004 contract:

    BUNDLES = [(0,), (1,), (0, 1)]
    feasible_allocations(n) -> list of {bidder_idx: bundle}, items pairwise
        disjoint across winners, including partial + empty allocations.
    allocation_welfare(alloc, valuations) -> sum of valuations[i][bundle].

The arithmetic asserted below is hand-computed: we verify the EXACT
Clarke-pivot payment, not merely that ``clear`` runs.
"""
from __future__ import annotations

import importlib
import itertools
import random
import sys
import types
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_BUNDLES = [(0,), (1,), (0, 1)]


def _feasible_allocations(n_bidders: int) -> list:
    """Contract-faithful enumerator: each bidder takes one of BUNDLES or
    nothing; winners' bundles must be pairwise disjoint. Includes partial
    and the empty (nothing-sold) allocation."""
    choices = [None] + _BUNDLES  # None == this bidder wins nothing
    out = []
    for combo in itertools.product(choices, repeat=n_bidders):
        used: set = set()
        ok = True
        alloc = {}
        for i, bundle in enumerate(combo):
            if bundle is None:
                continue
            s = set(bundle)
            if s & used:
                ok = False
                break
            used |= s
            alloc[i] = bundle
        if ok:
            out.append(alloc)
    return out


def _allocation_welfare(alloc: dict, valuations: list) -> float:
    return sum(valuations[i][bundle] for i, bundle in alloc.items())


def _install_bundles_stub() -> None:
    pkg = "experiments.exp004_combinatorial_auction"
    # Ensure the real package objects exist so the relative import target
    # resolves; we only stub the leaf `bundles` submodule.
    importlib.import_module(pkg)
    mod_name = f"{pkg}.bundles"
    stub = types.ModuleType(mod_name)
    stub.BUNDLES = list(_BUNDLES)
    stub.feasible_allocations = _feasible_allocations
    stub.allocation_welfare = _allocation_welfare
    sys.modules[mod_name] = stub


_install_bundles_stub()

from experiments.exp004_combinatorial_auction.mechanisms import vcg  # noqa: E402

# vcg has bound its bundles imports above; remove the stub so the real
# bundles.py (which also exposes draw_valuation) loads for other test modules
# (e.g. test_exp006_design). Without this the stub leaks and breaks collection.
sys.modules.pop("experiments.exp004_combinatorial_auction.bundles", None)


def _utility(bid_profile, valuations, bidder):
    """True utility of `bidder` = true value of allocated bundle - payment."""
    out = vcg.clear(bid_profile, rng=random.Random(0))
    alloc = out["allocation"]
    pay = out["payments"]
    if bidder in alloc:
        return valuations[bidder][alloc[bidder]] - pay.get(bidder, 0.0)
    return 0.0


class ExactPivotArithmetic(unittest.TestCase):
    def test_single_item_contest_is_second_price(self):
        """Both bidders contest item 0 and value nothing else. A* sells
        item 0 to bidder 0 (10 > 6). The externality bidder 0 imposes is
        the 6 that bidder 1 would have captured -> bidder 0's pivot payment
        is EXACTLY 6 (Vickrey second-price as the single-item special
        case). Item 1 is worthless to everyone; the welfare-max set
        contains ties that may incidentally assign it to a zero-value
        winner, so we assert the load-bearing facts (bidder 0 wins item 0,
        pays 6, revenue 6) and that any incidental winner pays 0."""
        b0 = {(0,): 10.0, (1,): 0.0, (0, 1): 10.0}
        b1 = {(0,): 6.0, (1,): 0.0, (0, 1): 6.0}
        out = vcg.clear([b0, b1], rng=random.Random(0))
        self.assertEqual(out["mechanism"], "vcg")
        # Tie-robust: bidder 0 wins item 0, but the equal-welfare set lets
        # VCG pick either {0:(0,)} or {0:(0,1)} (b0[(0,1)]==10 too) depending
        # on bundles' enumeration order. The load-bearing facts are the pivot
        # payment (6) and revenue (6), which hold under either tie outcome.
        self.assertIn(0, out["allocation"][0])
        self.assertEqual(out["payments"][0], 6.0)
        self.assertEqual(out["revenue"], 6.0)
        # Any incidental zero-value winner (e.g. item 1) pays exactly 0.
        for i, p in out["payments"].items():
            if i != 0:
                self.assertEqual(p, 0.0)

    def test_two_winners_split_with_pivots(self):
        """Bidder 0 wants item 0, bidder 1 wants item 1; a third bidder
        wants the whole bundle (0,1)=15. A* gives 0->(0,)=12 and
        1->(1,)=9 (welfare 21 > 15). Each winner's pivot is the welfare
        the bundle-bidder would have captured net of the other winner.

        W(A*) = 21.
        Payment_0: others' welfare in A* = 9; W_{-0} (exclude 0) = best of
          {bidder1 (1,)=9} vs {bidder2 (0,1)=15} = 15. p0 = 15 - 9 = 6.
        Payment_1: others' welfare in A* = 12; W_{-1} (exclude 1) = best of
          {bidder0 (0,)=12} vs {bidder2 (0,1)=15} = 15. p1 = 15 - 12 = 3.
        """
        b0 = {(0,): 12.0, (1,): 0.0, (0, 1): 12.0}
        b1 = {(0,): 0.0, (1,): 9.0, (0, 1): 9.0}
        b2 = {(0,): 0.0, (1,): 0.0, (0, 1): 15.0}
        out = vcg.clear([b0, b1, b2], rng=random.Random(0))
        self.assertEqual(out["allocation"], {0: (0,), 1: (1,)})
        self.assertEqual(out["payments"], {0: 6.0, 1: 3.0})
        self.assertEqual(out["revenue"], 9.0)

    def test_bundle_winner_pays_displaced_singletons(self):
        """One bidder values the whole bundle high; two singleton bidders
        are displaced. b0(0,1)=20 wins; b1(0,)=7, b2(1,)=8 lose.
        W(A*)=20, others in A*=0.
        W_{-0} = best without bidder0 = b1 (0,) + b2 (1,) = 15.
        p0 = 15 - 0 = 15."""
        b0 = {(0,): 0.0, (1,): 0.0, (0, 1): 20.0}
        b1 = {(0,): 7.0, (1,): 0.0, (0, 1): 7.0}
        b2 = {(0,): 0.0, (1,): 8.0, (0, 1): 8.0}
        out = vcg.clear([b0, b1, b2], rng=random.Random(0))
        self.assertEqual(out["allocation"], {0: (0, 1)})
        self.assertEqual(out["payments"], {0: 15.0})
        self.assertEqual(out["revenue"], 15.0)


class Strategyproofness(unittest.TestCase):
    def test_truthful_is_best_response(self):
        """Scripted profile: bidder 0's true value of item 0 is 10, the
        rival (bidder 1) bids 6 for item 0. Under VCG, deviating from
        truthful bidding cannot raise bidder 0's utility."""
        true0 = {(0,): 10.0, (1,): 0.0, (0, 1): 10.0}
        rival = {(0,): 6.0, (1,): 0.0, (0, 1): 6.0}

        truthful_u = _utility([true0, rival], [true0, rival], 0)

        # Sweep a range of misreports for bidder 0; truthful must weakly
        # dominate every one (utility measured at TRUE values).
        for v01 in (0.0, 3.0, 5.0, 6.0, 7.0, 9.0, 12.0, 20.0, 50.0):
            for vb in (0.0, 5.0, 10.0, 20.0):
                misreport = {(0,): v01, (1,): 0.0, (0, 1): vb}
                dev_u = _utility([misreport, rival], [true0, rival], 0)
                self.assertLessEqual(
                    dev_u,
                    truthful_u + 1e-9,
                    msg=f"deviation {misreport} beat truthful "
                    f"(dev={dev_u}, truthful={truthful_u})",
                )

    def test_losing_truthfully_then_overbidding_to_win_hurts(self):
        """If truthful loses, overbidding to win forces a payment above
        true value -> negative utility, strictly worse than the 0 of
        losing. Concrete: true value 4, rival 6."""
        true0 = {(0,): 4.0, (1,): 0.0, (0, 1): 4.0}
        rival = {(0,): 6.0, (1,): 0.0, (0, 1): 6.0}
        truthful_u = _utility([true0, rival], [true0, rival], 0)
        self.assertEqual(truthful_u, 0.0)  # bidder 0 loses, pays nothing
        overbid = {(0,): 9.0, (1,): 0.0, (0, 1): 9.0}
        dev_u = _utility([overbid, rival], [true0, rival], 0)
        # Wins at price 6, true value 4 -> utility 4 - 6 = -2.
        self.assertEqual(dev_u, -2.0)
        self.assertLess(dev_u, truthful_u)


class FeasibilityInvariants(unittest.TestCase):
    def test_no_item_allocated_twice(self):
        rng = random.Random(7)
        for _ in range(200):
            profile = []
            for _b in range(3):
                profile.append(
                    {
                        (0,): rng.uniform(0, 50),
                        (1,): rng.uniform(0, 50),
                        (0, 1): rng.uniform(0, 80),
                    }
                )
            out = vcg.clear(profile, rng=rng)
            used: list = []
            for bundle in out["allocation"].values():
                used.extend(bundle)
            self.assertEqual(
                len(used), len(set(used)), msg=f"item double-allocated: {out['allocation']}"
            )

    def test_payments_nonnegative_and_one_per_winner(self):
        b0 = {(0,): 10.0, (1,): 0.0, (0, 1): 10.0}
        b1 = {(0,): 6.0, (1,): 0.0, (0, 1): 6.0}
        out = vcg.clear([b0, b1], rng=random.Random(0))
        self.assertEqual(set(out["payments"]), set(out["allocation"]))
        for p in out["payments"].values():
            self.assertGreaterEqual(p, 0.0)


if __name__ == "__main__":
    unittest.main()
