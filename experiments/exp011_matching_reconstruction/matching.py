#!/usr/bin/env python3
"""exp011 — deterministic man-proposing Gale–Shapley (n=12, list-of-rankings).

Pure mechanism module: no I/O, no randomness, no LLM calls. Profiles are
lists of rankings: ``men_prefs[m]`` is man m's list of woman indices,
best first; ``women_prefs[w]`` is woman w's list of man indices, best
first. Determinism: free men propose lowest-index-first (FIFO queue
seeded 0..n-1), so identical profiles always produce the identical
matching — pinned by tests.
"""
from __future__ import annotations

from collections import deque


def _validate_profile(prefs: list[list[int]], n: int, side: str) -> None:
    """Every list must be a permutation of range(n) — never coerced."""
    if len(prefs) != n:
        raise ValueError(f"{side}: expected {n} lists, got {len(prefs)}")
    for i, row in enumerate(prefs):
        if sorted(row) != list(range(n)):
            raise ValueError(f"{side}[{i}] is not a permutation of 0..{n - 1}")


def gale_shapley(men_prefs: list[list[int]],
                 women_prefs: list[list[int]]) -> list[int]:
    """Man-proposing deferred acceptance. Returns ``match_of_woman``:
    ``match_of_woman[w]`` = the man matched to woman w (man-optimal
    stable matching; full lists + equal sides => everyone matched)."""
    n = len(men_prefs)
    _validate_profile(men_prefs, n, "men_prefs")
    _validate_profile(women_prefs, n, "women_prefs")
    # woman_rank[w][m] = position of man m in woman w's list (0 = best)
    woman_rank = [[0] * n for _ in range(n)]
    for w in range(n):
        for pos, m in enumerate(women_prefs[w]):
            woman_rank[w][m] = pos
    next_choice = [0] * n           # next list position each man proposes to
    match_of_woman = [-1] * n
    free = deque(range(n))          # lowest-index-first: the determinism pin
    while free:
        m = free.popleft()
        w = men_prefs[m][next_choice[m]]
        next_choice[m] += 1
        cur = match_of_woman[w]
        if cur == -1:
            match_of_woman[w] = m
        elif woman_rank[w][m] < woman_rank[w][cur]:
            match_of_woman[w] = m
            free.append(cur)
        else:
            free.append(m)
    return match_of_woman


def match_of_man(match_of_woman: list[int]) -> list[int]:
    """Invert a matching: ``out[m]`` = the woman matched to man m."""
    n = len(match_of_woman)
    out = [-1] * n
    for w, m in enumerate(match_of_woman):
        out[m] = w
    return out


def is_stable(match_of_woman: list[int], men_prefs: list[list[int]],
              women_prefs: list[list[int]]) -> bool:
    """No blocking pair: no (m, w) unmatched to each other where both
    strictly prefer each other to their assigned partners."""
    n = len(match_of_woman)
    mom = match_of_man(match_of_woman)
    man_rank = [{w: pos for pos, w in enumerate(men_prefs[m])}
                for m in range(n)]
    woman_rank = [{m: pos for pos, m in enumerate(women_prefs[w])}
                  for w in range(n)]
    for m in range(n):
        for w in range(n):
            if mom[m] == w:
                continue
            if (man_rank[m][w] < man_rank[m][mom[m]]
                    and woman_rank[w][m] < woman_rank[w][match_of_woman[w]]):
                return False
    return True
