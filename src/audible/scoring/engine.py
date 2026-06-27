"""The deterministic scoring core.

This is the load-bearing principle in code: all fantasy points come from pure,
reproducible arithmetic here. The LLM layer reasons *over* these numbers; it never
computes them.
"""

from __future__ import annotations

from collections.abc import Mapping


def score_stat_line(stats: Mapping[str, float], scoring: Mapping[str, float]) -> float:
    """Score a raw stat line against league scoring weights.

    points = sum over scoring keys of ``weight * stats.get(key, 0)``.

    Iterating over *scoring* keys (not the stat line) is deliberate: stat lines carry
    non-scoring fields -- ``adp_*``, ``pts_half_ppr``, ``gp``, total-tackle ``idp_tkl``
    (when solo/assist are scored separately) -- and keying off the scoring weights means
    none of them can leak into the score. A stat the league scores but the line doesn't
    project simply contributes 0.
    """
    return sum(weight * stats.get(key, 0.0) for key, weight in scoring.items())
