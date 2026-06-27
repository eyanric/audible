"""Draft assistant: opportunity-adjusted draft value vs ADP (Addendum 01, steps 4-5).

Draft-board-facing only. The full OpportunityProvider/blend into in-season VORP, the
backtest gate, and weekly start/sit are Phase 2 and are NOT pulled forward here.
"""

from .board import DraftBoard, DraftEntry, build_board
from .coverage import split_scoring

__all__ = ["DraftBoard", "DraftEntry", "build_board", "split_scoring"]
