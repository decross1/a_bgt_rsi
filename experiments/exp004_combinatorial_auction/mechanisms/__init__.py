"""Mechanism modules for exp004 (combinatorial-auction rung).

Each mechanism exposes a single pure function::

    clear(bid_profile, *, rng=None) -> {"allocation", "payments",
                                        "revenue", "mechanism"}

No LLM dependency; all mechanisms are fully seeded pure-Python.
"""
