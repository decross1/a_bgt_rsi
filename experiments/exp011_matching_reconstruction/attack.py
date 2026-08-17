#!/usr/bin/env python3
"""exp011 — two-mode preference-reconstruction attack (prereg-LOCKED).

Prereg: experiments/PREREG_l2block_2026-08-17.md §exp011.

Constraint semantics: a recorded pair ``(u, v)`` means "t prefers man u
to man v" (u >_t v). Perturbations are ALWAYS applied to the ORIGINAL
baseline profile (never cumulative); at most 2 proposer lists differ
from baseline in any single mechanism run (k=2, pinned).

Mode 1 (merge-sort pairwise probes, <= 33 comparisons at n=12): probe
(a, b) puts t at position 1 of both a's and b's lists. If mu'(t) is in
{a, b} the pairwise order is revealed; if mu'(t) = c not in {a, b},
record c >_t a AND c >_t b — EXACTLY the pinned recording, nothing more.

Mode 2 (frontier demotion, spends the remaining budget): promote a
(t to top of a's list) + demote the current known frontier f (t to
BOTTOM of f's list), on a fixed deterministic schedule targeting the
largest constraint-unordered group. Recording uses the prereg's own
"provably proposed" principle applied to the observed full matching:
in man-proposing GS, any man whose observed partner sits strictly below
t on his own PERTURBED list must have proposed to t and been rejected,
so mu'(t) >_t that man. (The prereg pins Mode 1's recording verbatim
and only the probe structure for Mode 2; this is the sound recording
that lets Mode 2 attack the frontier ceiling it was added to attack.)

Reconstruction = deterministic topological linear extension of ALL
recorded constraints. Scoring lives in ``tau_scored``: unordered pairs
contribute exactly 0 (chance), never favorably.

The attack never reads the target's true ranking: it sees only the
baseline matching plus per-query full matchings from the oracle.
"""
from __future__ import annotations

N = 12
Q_MAX = 44                    # ceil(n * log2 n) at n=12 (prereg budget)
MODE1_MAX_COMPARISONS = 33    # merge-sort worst case at n=12 (prereg)


def perturb(men_prefs: list[list[int]], t: int, top: tuple = (),
            bottom: tuple = ()) -> list[list[int]]:
    """Fresh perturbed copy of the ORIGINAL profile. ``top``: men whose
    list gets t moved to position 1; ``bottom``: men whose list gets t
    moved to last. Remainder keeps original order. k=2 pinned."""
    touched = set(top) | set(bottom)
    if len(touched) > 2:
        raise ValueError(f"k=2 pinned: {len(touched)} lists perturbed")
    out = [list(row) for row in men_prefs]
    for m in top:
        out[m] = [t] + [x for x in men_prefs[m] if x != t]
    for m in bottom:
        out[m] = [x for x in men_prefs[m] if x != t] + [t]
    return out


def transitive_closure(constraints: set, n: int = N) -> list[list[bool]]:
    """Boolean reachability over the constraint DAG. A cycle means a
    recording bug (all constraints are sound w.r.t. one true ranking) —
    raised, never coerced."""
    reach = [[False] * n for _ in range(n)]
    for u, v in constraints:
        reach[u][v] = True
    for k in range(n):
        rk = reach[k]
        for i in range(n):
            if reach[i][k]:
                ri = reach[i]
                for j in range(n):
                    if rk[j]:
                        ri[j] = True
    for i in range(n):
        if reach[i][i]:
            raise RuntimeError(f"constraint cycle through man {i}")
    return reach


def topological_extension(constraints: set, n: int = N) -> list[int]:
    """Deterministic Kahn linear extension, best-first: among ready
    nodes always take the smallest index."""
    closure = transitive_closure(constraints, n)  # cycle check
    del closure
    indeg = [0] * n
    succ: list[set] = [set() for _ in range(n)]
    for u, v in constraints:
        if v not in succ[u]:
            succ[u].add(v)
            indeg[v] += 1
    order: list[int] = []
    remaining = set(range(n))
    while remaining:
        m = min(x for x in remaining if indeg[x] == 0)
        order.append(m)
        remaining.discard(m)
        for v in succ[m]:
            indeg[v] -= 1
    return order


def tau_scored(closure: list[list[bool]], true_ranking: list[int],
               n: int = N) -> tuple[float, int, int, int]:
    """LOCKED scoring: tau = (concordant_known - discordant_known) /
    C(n,2); pairs unordered in the closure contribute exactly 0 and are
    counted in unresolved. Returns (tau, unresolved, conc, disc)."""
    pos = {m: i for i, m in enumerate(true_ranking)}  # 0 = t's favorite
    conc = disc = unresolved = 0
    for u in range(n):
        for v in range(u + 1, n):
            if closure[u][v] or closure[v][u]:
                if closure[u][v] == (pos[u] < pos[v]):
                    conc += 1
                else:
                    disc += 1
            else:
                unresolved += 1
    return (conc - disc) / (n * (n - 1) // 2), unresolved, conc, disc


def largest_unordered_group(closure: list[list[bool]],
                            n: int = N) -> list[int]:
    """Largest set of pairwise closure-incomparable men (exact max
    antichain; brute force over 2^n masks, deterministic tie-break =
    lowest mask). n=12 => 4096 masks: trivial."""
    incomp = [0] * n  # bit j set iff i,j incomparable (i != j)
    for i in range(n):
        for j in range(n):
            if i != j and not closure[i][j] and not closure[j][i]:
                incomp[i] |= 1 << j
    best_mask, best_size = 0, 0
    for mask in range(1, 1 << n):
        size = bin(mask).count("1")
        if size <= best_size:
            continue
        ok = True
        rest = mask
        while rest:
            low = rest & -rest
            i = low.bit_length() - 1
            if mask & ~incomp[i] != low:  # some other member comparable to i
                ok = False
                break
            rest ^= low
        if ok:
            best_mask, best_size = mask, size
    return [i for i in range(n) if best_mask >> i & 1]


def _known_frontier(closure: list[list[bool]], group: list[int],
                    baseline_match: int, n: int = N) -> int:
    """The current known frontier: the LOWEST man known (via closure) to
    beat every group member — fewest men known below him, tie-break by
    index. Fallback: the baseline match (the best natural proposer the
    adversary watched win)."""
    gset = set(group)
    doms = [u for u in range(n)
            if u not in gset and all(closure[u][g] for g in group)]
    if not doms:
        return baseline_match
    return min(doms, key=lambda u: (sum(closure[u]), u))


def _merge_sort(items: list[int], compare) -> list[int]:
    """Top-down merge sort; compare(a, b) -> True iff a goes first.
    Fixed comparison schedule given the comparator's answers."""
    if len(items) <= 1:
        return items
    mid = len(items) // 2
    left = _merge_sort(items[:mid], compare)
    right = _merge_sort(items[mid:], compare)
    out: list[int] = []
    i = j = 0
    while i < len(left) and j < len(right):
        if compare(left[i], right[j]):
            out.append(left[i])
            i += 1
        else:
            out.append(right[j])
            j += 1
    out.extend(left[i:])
    out.extend(right[j:])
    return out


def run_attack(oracle, men_prefs: list[list[int]], t: int,
               baseline_mow: list[int], n: int = N,
               q_max: int = Q_MAX) -> dict:
    """Full two-mode attack. ``oracle(perturbed_men_prefs)`` runs the
    mechanism (true women's lists live inside it — the attack never sees
    them) and returns match_of_woman. Returns constraints, per-query
    log, closure, and the deterministic reconstruction."""
    constraints: set = set()
    query_log: list[dict] = []
    baseline_match = baseline_mow[t]

    def issue(top: tuple, bottom: tuple):
        pmp = perturb(men_prefs, t, top=top, bottom=bottom)
        mow = oracle(pmp)
        dev = sum(1 for w in range(n) if mow[w] != baseline_mow[w])
        return pmp, mow, dev

    def record(new: set, entry: dict) -> None:
        added = new - constraints
        constraints.update(added)
        entry["new_constraints"] = len(added)
        query_log.append(entry)

    # --- Mode 1: merge-sort pairwise probes ---------------------------
    def compare(a: int, b: int) -> bool:
        if len(query_log) >= q_max:      # unreachable at n=12 (33 < 44)
            return True                  # stable fallback, no probe
        _, mow, dev = issue(top=(a, b), bottom=())
        winner = mow[t]
        entry = {"mode": 1, "pair": (a, b), "winner": winner,
                 "deviation_size": dev}
        if winner == a:
            record({(a, b)}, entry)
            return True
        if winner == b:
            record({(b, a)}, entry)
            return False
        record({(winner, a), (winner, b)}, entry)
        return True                      # unresolved: stable merge (left first)

    _merge_sort(list(range(n)), compare)
    mode1_queries = len(query_log)
    if mode1_queries > MODE1_MAX_COMPARISONS:
        raise RuntimeError(
            f"mode 1 issued {mode1_queries} > {MODE1_MAX_COMPARISONS}")

    # --- Mode 2: frontier-demotion probes ------------------------------
    probed: set = set()  # (a, f) pairs already issued (reruns are no-ops)
    while len(query_log) < q_max:
        closure = transitive_closure(constraints, n)
        if sum(1 for u in range(n) for v in range(u + 1, n)
               if not closure[u][v] and not closure[v][u]) == 0:
            break                        # fully resolved: early termination
        group = largest_unordered_group(closure, n)
        f = _known_frontier(closure, group, baseline_match, n)
        a = next((g for g in sorted(group)
                  if g != f and (g, f) not in probed), None)
        if a is None:
            break                        # plateau: schedule exhausted
        probed.add((a, f))
        pmp, mow, dev = issue(top=(a,), bottom=(f,))
        winner = mow[t]
        mom = [-1] * n
        for w, m in enumerate(mow):
            mom[m] = w
        new = set()
        for m in range(n):
            if m == winner:
                continue
            # m provably proposed to t iff his observed partner sits
            # strictly below t on his PERTURBED list.
            row = pmp[m]
            if row.index(t) < row.index(mom[m]):
                new.add((winner, m))
        record(new, {"mode": 2, "promoted": a, "demoted": f,
                     "winner": winner, "deviation_size": dev})

    closure = transitive_closure(constraints, n)
    return {
        "constraints": constraints,
        "query_log": query_log,
        "queries_used": len(query_log),
        "mode1_queries": mode1_queries,
        "closure": closure,
        "reconstruction": topological_extension(constraints, n),
    }
