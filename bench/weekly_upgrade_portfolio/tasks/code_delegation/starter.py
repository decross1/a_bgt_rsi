"""Synthetic development task: replace this file with a correct implementation."""


def resolve(ballots):
    """Resolve unit-weight direct ballots and transitive ``->voter`` delegations.

    Return ``{"totals": {"A": int, "B": int}, "exhausted": [voter_ids...]}``.
    A delegation path that enters a cycle/self-loop, points to a missing voter,
    or encounters any value other than ``A``, ``B``, or ``-><id>`` exhausts
    every originating vote on that path. Do not mutate ``ballots``.
    """
    raise NotImplementedError
