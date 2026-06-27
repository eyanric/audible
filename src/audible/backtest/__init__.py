"""Backtest harness (the §B / §5 honesty gate).

Mirrors the draft use-case: season N opportunity -> predict season N+1, out-of-sample,
scored in each league's own scoring. Turns the board's caveats into measurements and
gates promotion of any method from tilt/flag -> projection-of-record.
"""

from .harness import FoldResult, run_fold
from .idp import stickiness
from .metrics import mae, rmse, spearman, top_n_hit_rate, value_test

__all__ = [
    "FoldResult",
    "mae",
    "rmse",
    "run_fold",
    "spearman",
    "stickiness",
    "top_n_hit_rate",
    "value_test",
]
