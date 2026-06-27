"""Pure scoring metrics for the backtest (no third-party deps)."""

from __future__ import annotations

import math
from collections.abc import Sequence


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
