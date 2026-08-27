"""Pure scoring metrics for the backtest (no third-party deps)."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence


def _ranks(xs: Sequence[float]) -> list[float]:
    """Average (tie-corrected) ranks, ascending."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _pearson(a: Sequence[float], b: Sequence[float]) -> float:
    n = len(a)
    if n < 2:
        return math.nan
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((ai - ma) * (bi - mb) for ai, bi in zip(a, b, strict=True))
    va = sum((ai - ma) ** 2 for ai in a)
    vb = sum((bi - mb) ** 2 for bi in b)
    if va <= 0 or vb <= 0:
        return math.nan
    return cov / (math.sqrt(va) * math.sqrt(vb))


def spearman(predicted: Sequence[float], actual: Sequence[float]) -> float:
    """Spearman rank correlation between predicted and actual."""
    if len(predicted) < 2:
        return math.nan
    return _pearson(_ranks(predicted), _ranks(actual))


def mae(predicted: Sequence[float], actual: Sequence[float]) -> float:
    if not predicted:
        return math.nan
    return sum(abs(p - a) for p, a in zip(predicted, actual, strict=True)) / len(predicted)


def rmse(predicted: Sequence[float], actual: Sequence[float]) -> float:
    if not predicted:
        return math.nan
    se = sum((p - a) ** 2 for p, a in zip(predicted, actual, strict=True))
    return math.sqrt(se / len(predicted))


def top_n_hit_rate(
    ids: Sequence[str], predicted: Sequence[float], actual: Sequence[float], n: int
) -> float:
    """Of the predicted top-N, how many landed in the actual top-N."""
    if not ids:
        return math.nan
    n = min(n, len(ids))
    pred_top = {ids[i] for i in sorted(range(len(ids)), key=lambda i: -predicted[i])[:n]}
    act_top = {ids[i] for i in sorted(range(len(ids)), key=lambda i: -actual[i])[:n]}
    return len(pred_top & act_top) / n


def value_test(
    value: Sequence[float], actual: Sequence[float]
) -> tuple[float, float, float, int, int]:
    """Do positive-value (target) picks outscore negative-value (fade) picks?

    Returns (mean_actual_targets, mean_actual_fades, edge, n_targets, n_fades). A positive
    edge means the value signal is real -- targets really did beat fades.
    """
    targets = [a for v, a in zip(value, actual, strict=True) if v > 0]
    fades = [a for v, a in zip(value, actual, strict=True) if v < 0]
    mt = sum(targets) / len(targets) if targets else math.nan
    mf = sum(fades) / len(fades) if fades else math.nan
    return mt, mf, mt - mf, len(targets), len(fades)


def pairwise_accuracy(
    ids: Sequence[str],
    rank: Mapping[str, float],
    actual: Mapping[str, float],
    position: Mapping[str, str],
) -> tuple[float, int]:
    """Within-position pairwise accuracy: of all same-position pairs, how many are ordered right.

    Within position on purpose. Across positions the comparison is dominated by the fact that
    a WR outscores a kicker, which every arm gets right and which no draft decision turns on.
    The decision that matters is "these two receivers, which one first", and that is the only
    pair this counts.

    Ties on either side are skipped rather than scored: two players who finished on the same
    points do not have a right order, and an arm should be neither rewarded nor punished for
    the order it happened to put them in.

    Returns (accuracy, pairs_compared); accuracy is 0.5 when nothing is comparable.
    """
    by_pos: dict[str, list[str]] = {}
    for pid in ids:
        if pid in rank and pid in actual and pid in position:
            by_pos.setdefault(position[pid], []).append(pid)

    concordant = pairs = 0
    for group in by_pos.values():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                if actual[a] == actual[b] or rank[a] == rank[b]:
                    continue
                pairs += 1
                # rank is better-is-lower, actual is better-is-higher
                if (rank[a] < rank[b]) == (actual[a] > actual[b]):
                    concordant += 1
    return (concordant / pairs if pairs else 0.5), pairs


def paired_bootstrap(
    ids: Sequence[str],
    rank_x: Mapping[str, float],
    rank_y: Mapping[str, float],
    actual: Mapping[str, float],
    position: Mapping[str, str],
    *,
    rounds: int = 2000,
    seed: int = 20260826,
) -> tuple[float, float, float]:
    """CI for (accuracy of x) - (accuracy of y), resampling PLAYERS, both arms together.

    Paired on purpose: the two arms are scored on the identical resample every round, so the
    interval reflects the difference between them rather than the sampling noise they share.
    Resampling players rather than pairs keeps the unit of independence the player, since
    every pair involving one player moves together when that player's season does.

    Deterministic: same ids, same seed, same interval, every run.
    """
    import random

    rng = random.Random(seed)
    pool = [p for p in ids if p in actual and p in position]
    diffs: list[float] = []
    for _ in range(rounds):
        sample = [pool[rng.randrange(len(pool))] for _ in range(len(pool))]
        ax, _ = pairwise_accuracy(sample, rank_x, actual, position)
        ay, _ = pairwise_accuracy(sample, rank_y, actual, position)
        diffs.append(ax - ay)
    diffs.sort()
    lo = diffs[int(0.025 * len(diffs))]
    hi = diffs[min(int(0.975 * len(diffs)), len(diffs) - 1)]
    return (sum(diffs) / len(diffs), lo, hi)
