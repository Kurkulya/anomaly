"""Chance alone (ADR-0009): could a random split of the pooled sessions change as much as the real one?

chance_alone pools the sessions of two windows, splits them again with the real group sizes, and
gives the share of splits whose change is at least as large as the real change. Every split is
counted when there are PERMUTATION_SPLITS or fewer distinct ones (the real split is one of them);
otherwise PERMUTATION_SPLITS random splits are drawn from a generator seeded with PERMUTATION_SEED,
so the same data always gives the same share, and the real split is counted as one more, so the
share is never 0. The real change and every split's change use the same `statistic(values)`.

This module imports neither the verdict nor the trends module, so both can call it.
"""
import random
from itertools import combinations
from math import comb

from .constants import PERMUTATION_SEED, PERMUTATION_SPLITS

TWO_WAY = 'two-way'    # a change in either direction counts
WORSE = 'worse'        # only a rise counts: for every metric here, more is worse
SLACK = 1e-9           # relative: floating-point noise never drops the real split out of its own count


def chance_alone(before, after, statistic, direction=TWO_WAY):
    """The share (0 to 1) of splits of the pooled `before` and `after` values, each split keeping the
    real group sizes, whose change `statistic(after) - statistic(before)` is at least as large as
    the real one: in size for TWO_WAY, as a rise for WORSE. Both windows need at least one value."""
    pooled, size = tuple(before) + tuple(after), len(before)
    real = statistic(after) - statistic(before)
    if direction == TWO_WAY:
        real = abs(real)
    elif direction != WORSE:
        raise ValueError(f'unknown direction {direction!r}: {TWO_WAY} or {WORSE}')
    bar = real - SLACK * max(1.0, abs(real))
    every = comb(len(pooled), size) <= PERMUTATION_SPLITS
    changes = [statistic(rest) - statistic(picked) for picked, rest in splits(pooled, size, every)]
    hits = sum(1 for change in changes if (abs(change) if direction == TWO_WAY else change) >= bar)
    return hits / len(changes) if every else (hits + 1) / (len(changes) + 1)


def splits(pooled, size, every):
    """(first group, second group) with `size` values in the first group: every split of `pooled`
    when `every`, else PERMUTATION_SPLITS seeded random ones."""
    if every:
        for chosen in combinations(range(len(pooled)), size):
            picked = set(chosen)
            yield ([pooled[i] for i in chosen], [value for i, value in enumerate(pooled) if i not in picked])
        return
    generator, order = random.Random(PERMUTATION_SEED), list(pooled)
    for _ in range(PERMUTATION_SPLITS):
        generator.shuffle(order)
        yield order[:size], order[size:]
